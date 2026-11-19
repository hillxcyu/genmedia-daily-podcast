# Copyright 2026 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     https://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
"""Multi-turn Gemini 3.8 Flash TTS synthesizer and FFmpeg podcast masterer.

Synthesizes two-host dialogue turns concurrently via Vertex AI `gemini-3.8-flash-tts`
(`location=global`), records exact cumulative `start_sec` / `end_sec` turn timestamps
for click-to-seek transcripts, inserts natural 180ms conversational room pauses, and
masters a `-16 LUFS`, `128 kbps` CBR MP3 via `ffmpeg`.
"""

from __future__ import annotations

import asyncio
import base64
import io
from pathlib import Path
import subprocess
import tempfile
from typing import Any
import wave

import httpx

from publisher.gcp_auth import (
    get_Bearer_headers,
    get_gcp_credentials,
    get_location,
    get_project_id,
)

INTER_TURN_PAUSE_SEC = 0.18
LEAD_IN_PAUSE_SEC = 0.25
TAIL_OUT_PAUSE_SEC = 0.40
DEFAULT_SAMPLE_RATE = 24000


def _ensure_mono_16bit_wav(raw_bytes: bytes, fallback_rate: int = DEFAULT_SAMPLE_RATE) -> tuple[bytes, int]:
    """Extracts 16-bit mono PCM frames and sample rate from Gemini TTS inline audio."""
    if raw_bytes.startswith(b"RIFF"):
        with wave.open(io.BytesIO(raw_bytes), "rb") as wf:
            rate = wf.getframerate() or fallback_rate
            pcm = wf.readframes(wf.getnframes())
            return pcm, rate
    return raw_bytes, fallback_rate


async def _synthesize_single_turn(
    client: httpx.AsyncClient,
    sem: asyncio.Semaphore,
    project_id: str,
    location: str,
    creds: Any,
    turn: dict[str, Any],
    tts_model: str,
) -> tuple[int, bytes, int]:
    """Synthesizes one speaker turn with exponential backoff retry."""
    idx = int(turn["index"])
    url = (
        f"https://aiplatform.googleapis.com/v1/projects/{project_id}"
        f"/locations/{location}/publishers/google/models/{tts_model}:generateContent"
    )
    part: dict[str, Any] = {"text": str(turn["tts_transcript"])}
    style = str(turn.get("style", "")).strip()
    if style:
        part["speechMetadata"] = {"style": style}

    payload = {
        "contents": [{"role": "user", "parts": [part]}],
        "generationConfig": {
            "responseModalities": ["AUDIO"],
            "speechConfig": {
                "languageCode": "en-US",
                "voiceConfig": {
                    "prebuiltVoiceConfig": {"voiceName": str(turn["voice"])}
                },
            },
        },
    }

    async with sem:
        last_err: Exception | None = None
        for attempt in range(4):
            try:
                headers = get_Bearer_headers(creds, project_id)
                resp = await client.post(url, headers=headers, json=payload)
                if resp.status_code == 200:
                    body = resp.json()
                    b64_audio = body["candidates"][0]["content"]["parts"][0]["inlineData"]["data"]
                    pcm, rate = _ensure_mono_16bit_wav(base64.b64decode(b64_audio))
                    return idx, pcm, rate
                last_err = RuntimeError(f"HTTP {resp.status_code}: {resp.text[:300]}")
            except Exception as exc:  # noqa: BLE001
                last_err = exc
            await asyncio.sleep(1.5 * (attempt + 1))

    raise RuntimeError(f"Turn #{idx} TTS synthesis failed after retries: {last_err}")


async def synthesize_podcast_async(
    script_data: dict[str, Any],
    output_mp3_path: Path,
    tts_model: str = "gemini-3.8-flash-tts",
    concurrency: int = 3,
) -> dict[str, Any]:
    """Synthesizes all turns, masters CBR MP3 via ffmpeg, and returns updated transcript."""
    project_id = get_project_id()
    location = get_location()
    creds = get_gcp_credentials(project_id)
    turns: list[dict[str, Any]] = list(script_data["turns"])

    sem = asyncio.Semaphore(concurrency)
    async with httpx.AsyncClient(timeout=60.0) as client:
        results = await asyncio.gather(
            *[
                _synthesize_single_turn(client, sem, project_id, location, creds, turn, tts_model)
                for turn in turns
            ]
        )

    ordered = sorted(results, key=lambda item: item[0])
    sample_rate = ordered[0][2] if ordered else DEFAULT_SAMPLE_RATE

    def silence_bytes(seconds: float) -> bytes:
        num_samples = int(round(seconds * sample_rate))
        return b"\x00\x00" * num_samples

    stitched_pcm = bytearray()
    stitched_pcm.extend(silence_bytes(LEAD_IN_PAUSE_SEC))
    cursor_sec = LEAD_IN_PAUSE_SEC

    updated_turns: list[dict[str, Any]] = []
    for (idx, pcm, rate), turn in zip(ordered, turns):
        num_samples = len(pcm) // 2
        dur_sec = num_samples / float(rate)
        start_sec = round(cursor_sec, 2)
        end_sec = round(cursor_sec + dur_sec, 2)

        turn_copy = dict(turn)
        turn_copy["index"] = idx
        turn_copy["start_sec"] = start_sec
        turn_copy["end_sec"] = end_sec
        turn_copy["duration_sec"] = round(dur_sec, 2)
        updated_turns.append(turn_copy)

        stitched_pcm.extend(pcm)
        cursor_sec += dur_sec
        if idx < len(turns) - 1:
            stitched_pcm.extend(silence_bytes(INTER_TURN_PAUSE_SEC))
            cursor_sec += INTER_TURN_PAUSE_SEC

    stitched_pcm.extend(silence_bytes(TAIL_OUT_PAUSE_SEC))
    total_duration_sec = round(cursor_sec + TAIL_OUT_PAUSE_SEC, 2)

    output_mp3_path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp_wav:
        tmp_wav_path = Path(tmp_wav.name)

    try:
        with wave.open(str(tmp_wav_path), "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(sample_rate)
            wf.writeframes(bytes(stitched_pcm))

        # Master to -16 LUFS broadcast standard & 128 kbps CBR MP3 for accurate byte-range seeking.
        ffmpeg_cmd = [
            "ffmpeg",
            "-y",
            "-i",
            str(tmp_wav_path),
            "-af",
            "loudnorm=I=-16:TP=-1.5:LRA=11",
            "-ar",
            "44100",
            "-ac",
            "1",
            "-codec:a",
            "libmp3lame",
            "-b:a",
            "128k",
            "-write_xing",
            "0",
            str(output_mp3_path),
        ]
        subprocess.run(ffmpeg_cmd, check=True, capture_output=True, text=True)
    finally:
        tmp_wav_path.unlink(missing_ok=True)

    # Probe exact mastered MP3 duration with ffprobe if available.
    try:
        probe = subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-show_entries",
                "format=duration",
                "-of",
                "default=noprint_wrappers=1:nokey=1",
                str(output_mp3_path),
            ],
            check=True,
            capture_output=True,
            text=True,
        )
        probed = float(probe.stdout.strip())
        if probed > 0:
            total_duration_sec = round(probed, 2)
    except Exception:  # noqa: BLE001
        pass

    enriched = dict(script_data)
    enriched["tts_model"] = tts_model
    enriched["duration_sec"] = total_duration_sec
    enriched["audio_bytes"] = output_mp3_path.stat().st_size
    enriched["turns"] = updated_turns
    return enriched


def synthesize_podcast(
    script_data: dict[str, Any],
    output_mp3_path: Path,
    tts_model: str = "gemini-3.8-flash-tts",
) -> dict[str, Any]:
    """Synchronous wrapper for `synthesize_podcast_async`."""
    return asyncio.run(
        synthesize_podcast_async(
            script_data=script_data,
            output_mp3_path=output_mp3_path,
            tts_model=tts_model,
        )
    )
