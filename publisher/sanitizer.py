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
"""Public-safety validator and sanitizer for Argolis-bound GenMedia digests and scripts.

Ensures zero internal Google shortlinks (go/, b/, cl/, turbo/, ariane/),
internal corporate domains (g3doc, moma, x20web, critique, googleplex),
employee email addresses (@google.com), or unannounced internal model
codenames ever reach the external Google Cloud Storage (GCS) bucket or public RSS feed.
"""

from __future__ import annotations

import re
from typing import Sequence

# Patterns that indicate unredacted internal corporate references.
FORBIDDEN_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "internal shortlink (go/, b/, cl/, turbo/, ariane/)",
        re.compile(
            r"(?<![A-Za-z0-9_.-])(?:https?://)?(?:go|b|cl|turbo|ariane|launch)/[A-Za-z0-9_./-]+",
            re.IGNORECASE,
        ),
    ),
    (
        "internal Google corp domain",
        re.compile(
            r"\b(?:g3doc|moma|x20web|googleplex|critique|yaqs|plx|sherlog|sponge)\b"
            r"|[A-Za-z0-9.-]+\.corp\.google\.com",
            re.IGNORECASE,
        ),
    ),
    (
        "internal @google.com email",
        re.compile(r"\b[A-Za-z0-9._%+-]+@google\.com\b", re.IGNORECASE),
    ),
    (
        "Google3 depot path",
        re.compile(r"(?://depot/google3/|/google/src/|google3/[A-Za-z0-9_.-]+/)", re.IGNORECASE),
    ),
    (
        "internal model codename",
        re.compile(
            r"\b(?:macaron-cookie|spicy-mayo|bouncybohr|gempix|fiercefalcon|"
            r"supernova|snowball|sonic-boom|sonic-bolt|thorin|ghostlite)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "personal/informal FDE showcase or PoC project",
        re.compile(
            r"\b(?:vidgen-omni|vidgen|genatelier|gen-fashion-atelier|linkfox|"
            r"repro_agent|gemini_tts_pronunciation|live_transcribe)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "Google Workspace document/chat URL",
        re.compile(
            r"\b(?:docs|drive|slides|sheets|chat|mail)\.google\.com\b",
            re.IGNORECASE,
        ),
    ),
    (
        "pre-GA or confidential program marker",
        re.compile(
            r"\b(?:Private\s+Preview|Trusted\s+Tester|Internal\s+Only|Under\s+NDA)\b",
            re.IGNORECASE,
        ),
    ),
)


class UnsafeContentError(ValueError):
    """Raised when Argolis-bound text contains internal Google markers."""


def find_violations(text: str) -> list[str]:
    """Scans text and returns human-readable descriptions of any safety violations."""
    violations: list[str] = []
    for label, pattern in FORBIDDEN_PATTERNS:
        matches = sorted({m.group(0) for m in pattern.finditer(text)})
        if matches:
            sample = ", ".join(matches[:5])
            violations.append(f"{label}: {sample}")
    return violations


def assert_public_safe(text: str, context_name: str = "content") -> None:
    """Raises UnsafeContentError if text contains any forbidden internal markers."""
    violations = find_violations(text)
    if violations:
        joined = "; ".join(violations)
        raise UnsafeContentError(
            f"Refusing to publish {context_name} to — detected internal markers: {joined}"
        )


def scrub_internal_markers(text: str) -> str:
    """Best-effort pre-scrubber removing bare internal shortlinks before validation."""
    cleaned = text.replace(r"\$", "$")
    # Strip parenthetical internal bug/CL citations like `(b/123456, cl/789012)`.
    cleaned = re.sub(
        r"\(\s*(?:(?:https?://)?(?:go|b|cl|turbo|ariane)/[A-Za-z0-9_./-]+[\s,;]*)+?\)",
        "",
        cleaned,
        flags=re.IGNORECASE,
    )
    # Collapse leftover double spaces before punctuation.
    cleaned = re.sub(r"[ \t]{2,}", " ", cleaned)
    cleaned = re.sub(r" +([.,;:])", r"\1", cleaned)
    return cleaned.strip() + "\n"


def validate_all_texts(items: Sequence[tuple[str, str]]) -> None:
    """Validates multiple `(context_name, text)` pairs before GCS upload."""
    for name, content in items:
        assert_public_safe(content, context_name=name)
