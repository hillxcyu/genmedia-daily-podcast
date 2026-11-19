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
"""Podcast 2.0 and Apple Podcasts (iTunes) compliant RSS 2.0 feed generator.

Builds valid XML with `<itunes:image>`, `<itunes:duration>`, `<itunes:explicit>`,
`<enclosure type="audio/mpeg">`, RFC-2822 `<pubDate>`, and `<content:encoded>`
HTML show notes rendered from each episode's Markdown digest.
"""

from __future__ import annotations

from datetime import datetime, timezone
from email.utils import format_datetime
from typing import Any, Callable
import xml.etree.ElementTree as ET

ITUNES_NS = "http://www.itunes.com/dtds/podcast-1.0.dtd"
CONTENT_NS = "http://purl.org/rss/1.0/modules/content/"
ATOM_NS = "http://www.w3.org/2005/Atom"

ET.register_namespace("itunes", ITUNES_NS)
ET.register_namespace("content", CONTENT_NS)
ET.register_namespace("atom", ATOM_NS)


def _to_rfc2822(iso_str: str, fallback_date: str) -> str:
    """Formats an ISO-8601 timestamp or YYYY-MM-DD date string into RFC-2822."""
    try:
        if iso_str:
            dt = datetime.fromisoformat(iso_str.replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return format_datetime(dt)
    except ValueError:
        pass

    try:
        dt = datetime.strptime(fallback_date, "%Y-%m-%d").replace(
            hour=0, minute=0, second=0, tzinfo=timezone.utc
        )
        return format_datetime(dt)
    except ValueError:
        return format_datetime(datetime.now(timezone.utc))


def build_rss_xml(
    base_url: str,
    manifest: dict[str, Any],
    html_renderer: Callable[[str], str] | None = None,
) -> str:
    """Builds a complete RSS 2.0 XML document string."""
    root_url = base_url.rstrip("/")
    feed_url = f"{root_url}/feed.xml"
    cover_url = f"{root_url}/cover.jpg"

    rss = ET.Element("rss", {"version": "2.0"})
    channel = ET.SubElement(rss, "channel")

    title = str(manifest.get("podcast_title") or "GenMedia Pulse — Daily AI Media Models Briefing")
    subtitle = str(
        manifest.get("podcast_subtitle")
        or "Daily 5-minute two-host briefing on generative video, world simulation, image, and audio AI."
    )

    ET.SubElement(channel, "title").text = title
    ET.SubElement(channel, "link").text = root_url
    ET.SubElement(channel, "description").text = subtitle
    ET.SubElement(channel, "language").text = "en-us"
    ET.SubElement(channel, "lastBuildDate").text = _to_rfc2822(
        str(manifest.get("updated_at") or ""), ""
    )

    ET.SubElement(
        channel,
        f"{{{ATOM_NS}}}link",
        {"href": feed_url, "rel": "self", "type": "application/rss+xml"},
    )
    ET.SubElement(channel, f"{{{ITUNES_NS}}}author").text = "GenMedia Pulse Studio"
    ET.SubElement(channel, f"{{{ITUNES_NS}}}summary").text = subtitle
    ET.SubElement(channel, f"{{{ITUNES_NS}}}type").text = "episodic"
    ET.SubElement(channel, f"{{{ITUNES_NS}}}explicit").text = "false"
    ET.SubElement(channel, f"{{{ITUNES_NS}}}image", {"href": cover_url})
    ET.SubElement(channel, f"{{{ITUNES_NS}}}category", {"text": "Technology"})

    img_el = ET.SubElement(channel, "image")
    ET.SubElement(img_el, "url").text = cover_url
    ET.SubElement(img_el, "title").text = title
    ET.SubElement(img_el, "link").text = root_url

    episodes: list[dict[str, Any]] = list(manifest.get("episodes", []))
    for idx, ep in enumerate(episodes):
        ep_date = str(ep.get("date", "")).strip()
        if not ep_date:
            continue
        ep_title = str(ep.get("title") or f"GenMedia Pulse — {ep_date}")
        ep_summary = str(ep.get("summary") or subtitle)
        ep_url = f"{root_url}/episodes/{ep_date}"
        mp3_url = f"{root_url}/media/{ep_date}.mp3"
        audio_bytes = int(ep.get("audio_bytes") or 0)
        duration_sec = int(round(float(ep.get("duration_sec") or 0)))

        item = ET.SubElement(channel, "item")
        ET.SubElement(item, "title").text = ep_title
        ET.SubElement(item, "link").text = ep_url
        ET.SubElement(item, "guid", {"isPermaLink": "false"}).text = f"genmedia-pulse-{ep_date}"
        ET.SubElement(item, "pubDate").text = _to_rfc2822(
            str(ep.get("published_at") or ""), ep_date
        )
        ET.SubElement(item, "description").text = ep_summary

        if html_renderer is not None:
            rendered_html = html_renderer(ep_date)
            if rendered_html:
                ET.SubElement(item, f"{{{CONTENT_NS}}}encoded").text = rendered_html

        ET.SubElement(
            item,
            "enclosure",
            {
                "url": mp3_url,
                "length": str(max(audio_bytes, 1)),
                "type": "audio/mpeg",
            },
        )
        ET.SubElement(item, f"{{{ITUNES_NS}}}duration").text = str(max(duration_sec, 1))
        ET.SubElement(item, f"{{{ITUNES_NS}}}summary").text = ep_summary
        ET.SubElement(item, f"{{{ITUNES_NS}}}explicit").text = "false"
        ET.SubElement(item, f"{{{ITUNES_NS}}}episodeType").text = "full"
        ET.SubElement(item, f"{{{ITUNES_NS}}}image", {"href": cover_url})
        ET.SubElement(item, f"{{{ITUNES_NS}}}episode").text = str(len(episodes) - idx)

    xml_bytes = ET.tostring(rss, encoding="utf-8", xml_declaration=True)
    return xml_bytes.decode("utf-8")
