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
"""Two-host conversational English podcast script generator via Vertex AI GenAI SDK.

Transforms a public-safe Markdown daily GenMedia digest into a structured ~5-minute
(750-900 words, 16-22 turns) morning dialogue between Alex (Model Architecture &
Benchmarks lead, voice `Kore`) and Maya (Product Strategy & Creative Workflows lead,
voice `Puck`).
"""

from __future__ import annotations

from typing import Literal

from google.genai import types
from pydantic import BaseModel, Field

from publisher.gcp_auth import get_genai_client
from publisher.pronunciation import compile_tts_transcript
from publisher.sanitizer import assert_public_safe

HOST_PROFILES: dict[str, dict[str, str]] = {
    "Alex": {
        "voice": "Kore",
        "role": "GenMedia Architecture & Benchmarks Lead",
        "style": "Warm, articulate broadcast anchor, crisp technical pacing, engaging and conversational",
    },
    "Maya": {
        "voice": "Puck",
        "role": "Creative AI Product & GTM Strategist",
        "style": "Energetic, insightful co-host, pragmatic and conversational studio delivery",
    },
}


class DialogueTurnSpec(BaseModel):
    """Single conversational turn emitted by the LLM script writer."""

    speaker: Literal["Alex", "Maya"] = Field(
        description="Speaker name, alternating naturally between Alex and Maya."
    )
    topic_tag: str = Field(
        description="Short 2-4 word topic label for this turn (e.g. 'Omni 1.2 Flash GA')."
    )
    text: str = Field(
        description=(
            "Natural spoken English dialogue (35-65 words per turn, plain text without "
            "Markdown bullets or URLs)."
        )
    )


class PodcastScriptSpec(BaseModel):
    """Structured two-host podcast script returned by Gemini."""

    episode_title: str = Field(description="Compelling episode title under 85 characters.")
    episode_summary: str = Field(
        description="Crisp 1-2 sentence show-notes summary (under 240 characters)."
    )
    turns: list[DialogueTurnSpec] = Field(
        description="16 to 22 conversational turns totaling 750 to 920 words (~5 minutes)."
    )


SCRIPT_SYSTEM_PROMPT = """You are the executive producer of 'GenMedia Pulse', a sharp, 5-minute daily morning podcast covering generative video, interactive world models, image synthesis, and audio AI.

Write a lively, substantive two-host English dialogue based strictly on the provided daily Markdown digest:
- **Alex**: GenMedia Architecture & Benchmarks Lead — unpacks model capabilities, resolutions, latency/pricing economics, and Arena.ai benchmark shifts.
- **Maya**: Creative AI Product & GTM Strategist — connects model launches to real-world creative production, enterprise workflows, and developer takeaways.

Rules:
1. Target **16 to 22 turns** and **750 to 900 total spoken words** (~5 minutes at natural broadcast pace).
2. Alternate naturally between Alex and Maya. Open with a brisk welcome naming today's date and top headline, and close with a crisp 20-second sign-off on what builders should watch next.
3. Keep each turn between 30 and 65 words so the conversation feels dynamic — never monologue for 150+ words.
4. Write pure spoken English prose: NO URLs, NO Markdown formatting (`**`, `#`, backticks), NO bullet lists, and NO stage directions like `[laughs]` or `(sfx)`.
5. Strict public-safety rule: NEVER mention internal corporate shortlinks, bug numbers, changelists, internal email addresses, or unannounced internal codenames. Stick strictly to publicly stated facts in the digest.
"""


def generate_podcast_script(
    episode_date: str,
    digest_markdown: str,
    model_candidates: tuple[str, ...] = ("gemini-3-flash-preview", "gemini-2.5-pro"),
) -> dict[str, object]:
    """Generates a validated two-host script dictionary ready for TTS synthesis."""
    assert_public_safe(digest_markdown, context_name="input digest_markdown")
    client = get_genai_client()

    user_prompt = (
        f"Episode Date: {episode_date}\n\n"
        f"Daily GenMedia Digest (Markdown):\n{digest_markdown}\n\n"
        "Generate the 5-minute two-host 'GenMedia Pulse' episode script as structured JSON."
    )

    last_err: Exception | None = None
    parsed: PodcastScriptSpec | None = None
    used_model = model_candidates[0]

    for model_id in model_candidates:
        try:
            resp = client.models.generate_content(
                model=model_id,
                contents=user_prompt,
                config=types.GenerateContentConfig(
                    system_instruction=SCRIPT_SYSTEM_PROMPT,
                    temperature=0.65,
                    response_mime_type="application/json",
                    response_schema=PodcastScriptSpec,
                ),
            )
            if resp.parsed and isinstance(resp.parsed, PodcastScriptSpec):
                parsed = resp.parsed
            elif resp.text:
                parsed = PodcastScriptSpec.model_validate_json(resp.text)
            if parsed and len(parsed.turns) >= 8:
                used_model = model_id
                break
        except Exception as exc:  # noqa: BLE001
            last_err = exc

    if parsed is None:
        raise RuntimeError(f"Failed to generate podcast script across {model_candidates}: {last_err}")

    enriched_turns: list[dict[str, object]] = []
    total_words = 0
    for idx, turn in enumerate(parsed.turns):
        assert_public_safe(turn.text, context_name=f"script turn #{idx + 1}")
        profile = HOST_PROFILES[turn.speaker]
        display_text = turn.text.strip()
        tts_text = compile_tts_transcript(display_text)
        total_words += len(display_text.split())
        enriched_turns.append(
            {
                "index": idx,
                "speaker": turn.speaker,
                "role": profile["role"],
                "voice": profile["voice"],
                "style": profile["style"],
                "topic_tag": turn.topic_tag.strip(),
                "display_text": display_text,
                "tts_transcript": tts_text,
            }
        )

    assert_public_safe(parsed.episode_title, context_name="episode_title")
    assert_public_safe(parsed.episode_summary, context_name="episode_summary")

    return {
        "date": episode_date,
        "episode_title": parsed.episode_title.strip(),
        "episode_summary": parsed.episode_summary.strip(),
        "script_model": used_model,
        "word_count": total_words,
        "turns": enriched_turns,
    }
