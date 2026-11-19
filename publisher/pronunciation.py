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
"""Dual-track GenMedia terminology and acronym normalizer for Gemini 3.8 TTS.

Because Gemini 3.8 TTS (`DaikonPromptBuilder`) force-prefills `parts[].text`
verbatim and rejects SSML/systemInstruction, this module keeps clean
`display_text` for the web transcript while compiling phonetic `tts_transcript`
expansions and natural `<short pause>` tags for spoken clarity.
"""

from __future__ import annotations

import re

# Ordered acronym and technical term expansions for natural English broadcast speech.
TTS_REPLACEMENTS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"\bT2V/I2V/R2V\b"), "text-to-video, image-to-video, and reference-to-video"),
    (re.compile(r"\bT2V\b"), "text-to-video"),
    (re.compile(r"\bI2V\b"), "image-to-video"),
    (re.compile(r"\bR2V\b"), "reference-to-video"),
    (re.compile(r"\bV2V\b"), "video-to-video"),
    (re.compile(r"\bT2I\b"), "text-to-image"),
    (re.compile(r"\bTTS\b"), "T-T-S"),
    (re.compile(r"\bSTT\b"), "speech-to-text"),
    (re.compile(r"\bRLxF\b"), "R-L-by-F"),
    (re.compile(r"\bLoRA\b"), "Lora"),
    (re.compile(r"\bGSUs\b"), "G-S-Us"),
    (re.compile(r"\bGSU\b"), "G-S-U"),
    (re.compile(r"\bLUFS\b"), "lufs"),
    (re.compile(r"\bRGBA\b"), "R-G-B-A"),
    (re.compile(r"\bSVG\b"), "S-V-G"),
    (re.compile(r"\bGIF\b"), "gif"),
    (re.compile(r"\bGA\b"), "G-A"),
    (re.compile(r"\bEAP\b"), "E-A-P"),
    (re.compile(r"\b1P\b"), "first-party"),
    (re.compile(r"\b3P\b"), "third-party"),
    (re.compile(r"\b1080p\b", re.IGNORECASE), "ten-eighty-P"),
    (re.compile(r"\b720p\b", re.IGNORECASE), "seven-twenty-P"),
    (re.compile(r"\b360p\b", re.IGNORECASE), "three-sixty-P"),
    (re.compile(r"\b4K\b"), "four-K"),
    (re.compile(r"\b8K\b"), "eight-K"),
    (re.compile(r"\b2K\b"), "two-K"),
    (re.compile(r"\b1K\b"), "one-K"),
    (re.compile(r"\b24\s*fps\b", re.IGNORECASE), "twenty-four frames per second"),
    (re.compile(r"\bArena\.ai\b", re.IGNORECASE), "Arena dot A-I"),
    (re.compile(r"\bLMArena\b", re.IGNORECASE), "L-M Arena"),
    (re.compile(r"\bGenMedia\b"), "Gen-Media"),
    (re.compile(r"\bGPT-Image\b", re.IGNORECASE), "G-P-T Image"),
    (re.compile(r"\bOmni\s+1\.2\b", re.IGNORECASE), "Omni one-point-two"),
    (re.compile(r"\bOmni\s+1\.5\b", re.IGNORECASE), "Omni one-point-five"),
    (re.compile(r"\bVeo\s+3\.1\b", re.IGNORECASE), "Veo three-point-one"),
    (re.compile(r"\bNano\s+Banana\s+2\.1\b", re.IGNORECASE), "Nano Banana two-point-one"),
    (re.compile(r"\bSeedance\s+2\.5\b", re.IGNORECASE), "Seedance two-point-five"),
    (re.compile(r"\bWan\s+3\.0\b", re.IGNORECASE), "Wan three-point-oh"),
    (re.compile(r"\bFLUX\s+3\b", re.IGNORECASE), "Flux three"),
)


def compile_tts_transcript(display_text: str) -> str:
    """Converts clean UI display text into a spoken-friendly Gemini 3.8 TTS transcript."""
    out = display_text.strip()
    # Strip Markdown emphasis/backticks that should not be read literally.
    out = re.sub(r"`([^`]+)`", r"\1", out)
    out = re.sub(r"\*\*([^*]+)\*\*", r"\1", out)
    out = re.sub(r"\*([^*]+)\*", r"\1", out)

    for pattern, spoken in TTS_REPLACEMENTS:
        out = pattern.sub(spoken, out)

    # Convert em-dashes into natural short conversational pauses.
    out = re.sub(r"\s*—\s*", " <short pause> ", out)
    out = re.sub(r"\s{2,}", " ", out)
    return out.strip()
