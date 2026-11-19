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
"""Unit test suite for sanitizer guardrails, TTS pronunciation, RSS XML, and HTTP 206 streaming."""

from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest
import xml.etree.ElementTree as ET

from fastapi.testclient import TestClient

from portal.app import create_app, render_markdown_to_html
from portal.gcs_store import EpisodeStore
from publisher.pronunciation import compile_tts_transcript
from publisher.sanitizer import UnsafeContentError, assert_public_safe, scrub_internal_markers


class SanitizerAndPronunciationTests(unittest.TestCase):
    """Tests public-safety leak prevention and Gemini 3.8 TTS acronym normalization."""

    def test_sanitizer_blocks_internal_links_emails_and_codenames(self) -> None:
        unsafe_samples = [
            "Check b/567314357 for launch timeline.",
            "Landed in cl/994607411 yesterday.",
            "See go/genmedia-faq for internal pricing.",
            "Contact owner@google.com for allowlist.",
            "Internal recipe macaron-cookie and spicy-mayo.",
            "Config at //depot/google3/cloud/ai/config.gcl",
            "Position vidgen-omni Retail Commercial Workflows for 30s spots.",
            "Deck at https://docs.google.com/presentation/d/1b5jlgCWk3Q2LFr5tDYAZZps6Pw_N2_EaIfbAwk9M_3A/edit",
            "Customer PoC using genAtelier and linkfox dataset.",
            "Feature launches in Private Preview next week under Trusted Tester.",
        ]
        for sample in unsafe_samples:
            with self.subTest(sample=sample):
                with self.assertRaises(UnsafeContentError):
                    assert_public_safe(sample)

    def test_sanitizer_allows_clean_public_digest(self) -> None:
        clean = (
            "## Gemini Omni 1.2 Flash Reaches General Availability\n\n"
            "Google Cloud launched `gemini-omni-1.2-flash` with 3s-15s video generation, "
            r"4K standalone upscaling at \$0.02/s, and OpenAI released GPT-Image 2.6."
        )
        scrubbed = scrub_internal_markers(clean)
        self.assertNotIn(r"\$", scrubbed)
        self.assertIn("$0.02/s", scrubbed)
        assert_public_safe(scrubbed)

    def test_markdown_renderer_unescapes_dollars_and_stamps_table_labels(self) -> None:
        md = (
            r"Pricing starts at \$0.02/s (`360p`) and \$0.21/s (`4K`)." "\n\n"
            "| Capability | Spec | Price |\n"
            "| :--- | :--- | :--- |\n"
            r"| **Draft** | `360p` | \$0.02/s |" "\n"
        )
        rendered = render_markdown_to_html(md)
        self.assertNotIn(r"\$", rendered)
        self.assertIn("$0.02/s", rendered)
        self.assertIn('data-label="Capability"', rendered)
        self.assertIn('data-label="Spec"', rendered)
        self.assertIn('data-label="Price"', rendered)

    def test_pronunciation_expands_genmedia_acronyms(self) -> None:
        spoken = compile_tts_transcript(
            "Omni 1.2 supports T2V/I2V/R2V up to 4K and 1080p — beating Arena.ai baselines."
        )
        self.assertIn("Omni one-point-two", spoken)
        self.assertIn("text-to-video, image-to-video, and reference-to-video", spoken)
        self.assertIn("four-K", spoken)
        self.assertIn("ten-eighty-P", spoken)
        self.assertIn("Arena dot A-I", spoken)
        self.assertIn("<short pause>", spoken)


class PortalAndRssTests(unittest.TestCase):
    """Tests FastAPI portal HTML rendering, RSS 2.0 XML schema, and RFC 9110 Range streaming."""

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / "cover.jpg").write_bytes(b"\xff\xd8\xff\xe0MOCK_JPEG_DATA")

        ep_dir = self.root / "2026-11-09"
        ep_dir.mkdir(parents=True)
        (ep_dir / "digest.md").write_text(
            "# Nov 9 Briefing\n\n## Video Models\n\n- **Gemini Omni 1.2 Flash** is now GA.\n",
            encoding="utf-8",
        )
        # Deterministic 4096-byte fake MP3 payload for exact byte-range assertions.
        mp3_payload = bytes(i % 256 for i in range(4096))
        (ep_dir / "podcast.mp3").write_bytes(mp3_payload)

        transcript = {
            "date": "2026-11-09",
            "episode_title": "Omni 1.2 Flash GA & GPT-Image 2.6 Shake Up Arena",
            "episode_summary": "A 5-minute dive into 15s video editing and native SVG image models.",
            "duration_sec": 302.4,
            "audio_bytes": len(mp3_payload),
            "turns": [
                {
                    "index": 0,
                    "speaker": "Alex",
                    "topic_tag": "Omni 1.2 GA",
                    "start_sec": 0.25,
                    "end_sec": 14.8,
                    "display_text": "Welcome back to GenMedia Pulse for November ninth.",
                },
                {
                    "index": 1,
                    "speaker": "Maya",
                    "topic_tag": "Enterprise Workflows",
                    "start_sec": 14.98,
                    "end_sec": 29.5,
                    "display_text": "Big week for creative studios with 15-second video editing.",
                },
            ],
        }
        (ep_dir / "transcript.json").write_text(json.dumps(transcript), encoding="utf-8")

        manifest = {
            "podcast_title": "GenMedia Pulse — Daily AI Media Models Briefing",
            "podcast_subtitle": "Daily 5-minute GenMedia briefing.",
            "updated_at": "2026-11-09T00:05:00+00:00",
            "episodes": [
                {
                    "date": "2026-11-09",
                    "title": transcript["episode_title"],
                    "summary": transcript["episode_summary"],
                    "published_at": "2026-11-09T00:05:00+00:00",
                    "duration_sec": 302.4,
                    "duration_label": "05:02",
                    "audio_bytes": len(mp3_payload),
                    "tags": ["Video AI", "Image AI"],
                }
            ],
        }
        (self.root / "index.json").write_text(json.dumps(manifest), encoding="utf-8")

        store = EpisodeStore(local_dir=self.root)
        self.client = TestClient(create_app(store=store))

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_home_and_episode_page_render_single_h1_and_transcript(self) -> None:
        resp = self.client.get("/")
        self.assertEqual(resp.status_code, 200)
        html = resp.text
        self.assertEqual(html.count("<h1"), 1)
        self.assertIn("Omni 1.2 Flash GA &amp; GPT-Image 2.6 Shake Up Arena", html)
        self.assertIn("Gemini Omni 1.2 Flash", html)
        self.assertIn("Welcome back to GenMedia Pulse", html)

    def test_rss_feed_is_valid_itunes_podcast_xml(self) -> None:
        resp = self.client.get(
            "/feed.xml",
            headers={"X-Forwarded-Proto": "https", "X-Forwarded-Host": "example.a.run.app"},
        )
        self.assertEqual(resp.status_code, 200)
        self.assertIn("application/rss+xml", resp.headers["content-type"])
        root = ET.fromstring(resp.text)
        self.assertEqual(root.tag, "rss")
        enclosure = root.find("./channel/item/enclosure")
        self.assertIsNotNone(enclosure)
        assert enclosure is not None
        self.assertEqual(
            enclosure.attrib["url"], "https://example.a.run.app/media/2026-11-09.mp3"
        )
        self.assertEqual(enclosure.attrib["length"], "4096")
        self.assertEqual(enclosure.attrib["type"], "audio/mpeg")

        head_feed = self.client.head("/feed.xml")
        self.assertEqual(head_feed.status_code, 200)
        head_cover = self.client.head("/cover.jpg")
        self.assertEqual(head_cover.status_code, 200)
        self.assertEqual(head_cover.headers["content-type"], "image/jpeg")
        health = self.client.get("/api/health")
        self.assertEqual(health.status_code, 200)

    def test_mp3_streaming_supports_head_full_and_partial_206_ranges(self) -> None:
        head_resp = self.client.head("/media/2026-11-09.mp3")
        self.assertEqual(head_resp.status_code, 200)
        self.assertEqual(head_resp.headers["accept-ranges"], "bytes")
        self.assertEqual(head_resp.headers["content-length"], "4096")

        part_resp = self.client.get(
            "/media/2026-11-09.mp3", headers={"Range": "bytes=100-199"}
        )
        self.assertEqual(part_resp.status_code, 206)
        self.assertEqual(part_resp.headers["content-range"], "bytes 100-199/4096")
        self.assertEqual(part_resp.headers["content-length"], "100")
        self.assertEqual(part_resp.content, bytes(i % 256 for i in range(100, 200)))


if __name__ == "__main__":
    unittest.main()
