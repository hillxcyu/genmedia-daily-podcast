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
"""End-to-end daily publisher CLI for the GenMedia Daily Digest Portal & Podcast.

Validates public-safety rules on `digest.md`, generates a ~5-minute two-host
conversational script, synthesizes and masters `podcast.mp3` via Gemini 3.8 TTS +
FFmpeg, uploads `{digest.md, transcript.json, podcast.mp3}` to Google Cloud Storage (GCS), and
atomically updates `index.json`.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
from typing import Any

# Allow running directly as `python publisher/publish_episode.py`.
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from google.api_core.exceptions import NotFound

from publisher.audio_synthesizer import synthesize_podcast
from publisher.gcp_auth import get_bucket_name, get_storage_client
from publisher.sanitizer import assert_public_safe, scrub_internal_markers, validate_all_texts
from publisher.script_generator import generate_podcast_script


def format_duration_mmss(seconds: float) -> str:
    """Formats seconds as MM:SS for UI badges and iTunes duration tags."""
    total = max(0, int(round(seconds)))
    mins, secs = divmod(total, 60)
    return f"{mins:02d}:{secs:02d}"


def publish_episode(
    episode_date: str,
    digest_path: Path,
    title_override: str = "",
    summary_override: str = "",
    tags: list[str] | None = None,
    upload_to_gcs: bool = True,
    tts_model: str = "gemini-3.8-flash-tts",
) -> dict[str, Any]:
    """Runs safety checks, script generation, TTS synthesis, and GCS upload."""
    raw_digest = digest_path.read_text(encoding="utf-8")
    cleaned_digest = scrub_internal_markers(raw_digest)
    assert_public_safe(cleaned_digest, context_name=f"digest ({digest_path})")

    print(f"[1/4] Generating two-host English podcast script for {episode_date}...")
    script_data = generate_podcast_script(
        episode_date=episode_date,
        digest_markdown=cleaned_digest,
    )
    if title_override.strip():
        assert_public_safe(title_override, context_name="title_override")
        script_data["episode_title"] = title_override.strip()
    if summary_override.strip():
        assert_public_safe(summary_override, context_name="summary_override")
        script_data["episode_summary"] = summary_override.strip()

    ep_dir = PROJECT_ROOT / "episodes_local" / episode_date
    ep_dir.mkdir(parents=True, exist_ok=True)
    local_digest_path = ep_dir / "digest.md"
    local_mp3_path = ep_dir / "podcast.mp3"
    local_transcript_path = ep_dir / "transcript.json"

    local_digest_path.write_text(cleaned_digest, encoding="utf-8")

    print(
        f"[2/4] Synthesizing {len(script_data['turns'])} turns ({script_data['word_count']} words) "
        f"with {tts_model}..."
    )
    transcript_payload = synthesize_podcast(
        script_data=script_data,
        output_mp3_path=local_mp3_path,
        tts_model=tts_model,
    )

    published_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    episode_tags = tags or ["Video AI", "Image AI", "Audio AI", "Benchmarks"]
    validate_all_texts([(f"tag '{t}'", t) for t in episode_tags])

    transcript_payload["published_at"] = published_at
    transcript_payload["tags"] = episode_tags
    transcript_json_str = json.dumps(transcript_payload, indent=2, ensure_ascii=False)
    assert_public_safe(transcript_json_str, context_name="transcript.json")
    local_transcript_path.write_text(transcript_json_str + "\n", encoding="utf-8")

    episode_entry = {
        "date": episode_date,
        "title": transcript_payload["episode_title"],
        "summary": transcript_payload["episode_summary"],
        "published_at": published_at,
        "duration_sec": transcript_payload["duration_sec"],
        "duration_label": format_duration_mmss(float(transcript_payload["duration_sec"])),
        "audio_bytes": transcript_payload["audio_bytes"],
        "word_count": transcript_payload["word_count"],
        "turn_count": len(transcript_payload["turns"]),
        "tags": episode_tags,
    }

    if upload_to_gcs:
        bucket_name = get_bucket_name()
        print(f"[3/4] Uploading episode artifacts to gs://{bucket_name}/episodes/{episode_date}/...")
        storage_client = get_storage_client()
        bucket = storage_client.bucket(bucket_name)

        digest_blob = bucket.blob(f"episodes/{episode_date}/digest.md")
        digest_blob.cache_control = "no-cache"
        digest_blob.upload_from_string(cleaned_digest, content_type="text/markdown; charset=utf-8")

        transcript_blob = bucket.blob(f"episodes/{episode_date}/transcript.json")
        transcript_blob.cache_control = "no-cache"
        transcript_blob.upload_from_string(
            transcript_json_str, content_type="application/json; charset=utf-8"
        )

        mp3_blob = bucket.blob(f"episodes/{episode_date}/podcast.mp3")
        mp3_blob.cache_control = "public, max-age=3600"
        mp3_blob.upload_from_filename(str(local_mp3_path), content_type="audio/mpeg")

        print(f"[4/4] Updating manifest gs://{bucket_name}/index.json...")
        index_blob = bucket.blob("index.json")
        existing_episodes: list[dict[str, Any]] = []
        try:
            raw_index = index_blob.download_as_text(encoding="utf-8")
            parsed_index = json.loads(raw_index)
            existing_episodes = list(parsed_index.get("episodes", []))
        except NotFound:
            existing_episodes = []

        merged_by_date = {ep["date"]: ep for ep in existing_episodes if "date" in ep}
        merged_by_date[episode_date] = episode_entry
        sorted_episodes = sorted(
            merged_by_date.values(),
            key=lambda item: str(item["date"]),
            reverse=True,
        )
        manifest = {
            "podcast_title": "GenMedia Pulse — Daily AI Media Models Briefing",
            "podcast_subtitle": (
                "Daily 5-minute two-host briefing on generative video, world simulation, "
                "image synthesis, and audio AI models."
            ),
            "updated_at": published_at,
            "episodes": sorted_episodes,
        }
        index_blob.cache_control = "no-cache"
        index_blob.upload_from_string(
            json.dumps(manifest, indent=2, ensure_ascii=False) + "\n",
            content_type="application/json; charset=utf-8",
        )
    else:
        local_index_path = PROJECT_ROOT / "episodes_local" / "index.json"
        existing_local: list[dict[str, Any]] = []
        if local_index_path.exists():
            existing_local = list(
                json.loads(local_index_path.read_text(encoding="utf-8")).get("episodes", [])
            )
        merged = {ep["date"]: ep for ep in existing_local if "date" in ep}
        merged[episode_date] = episode_entry
        manifest = {
            "podcast_title": "GenMedia Pulse — Daily AI Media Models Briefing",
            "podcast_subtitle": (
                "Daily 5-minute two-host briefing on generative video, world simulation, "
                "image synthesis, and audio AI models."
            ),
            "updated_at": published_at,
            "episodes": sorted(merged.values(), key=lambda x: str(x["date"]), reverse=True),
        }
        local_index_path.write_text(
            json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )

    print(
        f"Published {episode_date}: '{episode_entry['title']}' "
        f"({episode_entry['duration_label']}, {round(episode_entry['audio_bytes'] / 1024 / 1024, 2)} MB)"
    )
    return episode_entry


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Sanitize daily GenMedia digest, synthesize 2-host podcast, and upload to GCS."
    )
    parser.add_argument("--date", required=True, help="Episode date in YYYY-MM-DD format")
    parser.add_argument("--digest-file", required=True, type=Path, help="Path to public-safe digest.md")
    parser.add_argument("--title", default="", help="Optional episode title override")
    parser.add_argument("--summary", default="", help="Optional 1-2 sentence summary override")
    parser.add_argument(
        "--tags",
        default="Video AI,Image AI,Audio AI,World Models",
        help="Comma-separated topic tags",
    )
    parser.add_argument("--tts-model", default="gemini-3.8-flash-tts", help="Vertex AI TTS model ID")
    parser.add_argument("--no-upload", action="store_true", help="Write locally without GCS upload")
    args = parser.parse_args()

    tag_list = [t.strip() for t in args.tags.split(",") if t.strip()]
    publish_episode(
        episode_date=args.date,
        digest_path=args.digest_file,
        title_override=args.title,
        summary_override=args.summary,
        tags=tag_list,
        upload_to_gcs=not args.no_upload,
        tts_model=args.tts_model,
    )


if __name__ == "__main__":
    main()
