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
"""Generates Apple Podcasts-compliant 2048x2048 cover art via Gemini Nano Banana 2.1.

Synthesizes an editorial podcast cover image on Vertex AI (`location=global`),
ensures exact 2048x2048 RGB JPEG dimensions under Apple Podcasts' 512 KB limit,
and uploads `cover.jpg` to the target Google Cloud Storage (GCS) bucket.
"""

from __future__ import annotations

import argparse
import io
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from google.genai import types
from PIL import Image

from publisher.gcp_auth import get_bucket_name, get_genai_client, get_storage_client

COVER_PROMPT = (
    "A sophisticated, minimalist editorial podcast cover illustration for a flagship "
    "daily technology briefing titled 'GENMEDIA PULSE' with subtitle 'DAILY BRIEFING'. "
    "Warm cream archival paper texture background (#F6F2EA) with bold geometric Bauhaus "
    "and Swiss typographic composition in deep obsidian ink (#16181D), warm terracotta "
    "vermilion (#C84B31), and muted brass gold (#B88B4A). Abstract soundwave prisms "
    "refracting into cinema film frames and optical lenses. Crisp, balanced serif "
    "headline 'GENMEDIA PULSE' centered cleanly at the top, minimal, museum-grade "
    "print poster aesthetic, flat 2D editorial illustration, 1:1 square."
)


def generate_and_upload_cover(output_path: Path, upload_to_gcs: bool = True) -> Path:
    """Generates 2048x2048 cover.jpg (<500 KB) and optionally uploads to GCS."""
    client = get_genai_client()
    response = client.models.generate_content(
        model="gemini-nano-banana-2.1",
        contents=COVER_PROMPT,
        config=types.GenerateContentConfig(
            response_modalities=["IMAGE"],
            image_config=types.ImageConfig(aspect_ratio="1:1", image_size="2K"),
        ),
    )

    raw_bytes: bytes | None = None
    for candidate in response.candidates or []:
        if not candidate.content:
            continue
        for part in candidate.content.parts or []:
            if part.inline_data and part.inline_data.data:
                raw_bytes = part.inline_data.data
                break
        if raw_bytes:
            break

    if not raw_bytes:
        raise RuntimeError("gemini-nano-banana-2.1 did not return image bytes for cover art.")

    img = Image.open(io.BytesIO(raw_bytes)).convert("RGB")
    if img.size != (2048, 2048):
        img = img.resize((2048, 2048), Image.Resampling.LANCZOS)

    # Encode under Apple Podcasts' 512 KB enclosure/artwork threshold while keeping crisp detail.
    jpeg_bytes = b""
    for quality in (88, 82, 76, 70):
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=quality, optimize=True, progressive=True)
        jpeg_bytes = buf.getvalue()
        if len(jpeg_bytes) <= 490_000:
            break

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_bytes(jpeg_bytes)

    if upload_to_gcs:
        storage_client = get_storage_client()
        bucket = storage_client.bucket(get_bucket_name())
        blob = bucket.blob("cover.jpg")
        blob.cache_control = "public, max-age=86400"
        blob.upload_from_string(jpeg_bytes, content_type="image/jpeg")

    return output_path


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate and upload 2048x2048 podcast cover art.")
    parser.add_argument(
        "--out",
        type=Path,
        default=Path(__file__).resolve().parent.parent / "episodes_local" / "cover.jpg",
        help="Local output path for cover.jpg",
    )
    parser.add_argument("--no-upload", action="store_true", help="Skip uploading to GCS")
    args = parser.parse_args()
    saved = generate_and_upload_cover(args.out, upload_to_gcs=not args.no_upload)
    size_kb = round(saved.stat().st_size / 1024.0, 1)
    print(f"Generated cover art: {saved} ({size_kb} KB)")


if __name__ == "__main__":
    main()
