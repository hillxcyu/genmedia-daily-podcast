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
"""FastAPI application for the GenMedia Daily Digest Web Portal and RSS Feed.

Serves GFM-rendered daily Markdown digests, interactive synced two-host podcast
transcripts, Podcast 2.0 / Apple Podcasts RSS 2.0 XML (`/feed.xml`), and RFC 9110
HTTP 206 byte-range MP3 streaming (`/media/{date}.mp3`) backed by Cloud Storage.
"""

from __future__ import annotations

import html
from pathlib import Path
import re
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
import markdown

from portal.gcs_store import EpisodeStore
from portal.rss_builder import build_rss_xml

BASE_DIR = Path(__file__).resolve().parent.parent
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
RANGE_RE = re.compile(r"^bytes=(\d*)-(\d*)$")
TABLE_BLOCK_RE = re.compile(r"<table\b[^>]*>.*?</table>", re.DOTALL | re.IGNORECASE)
TH_CELL_RE = re.compile(r"<th\b[^>]*>(.*?)</th>", re.DOTALL | re.IGNORECASE)
TBODY_BLOCK_RE = re.compile(r"(<tbody\b[^>]*>)(.*?)(</tbody>)", re.DOTALL | re.IGNORECASE)
TR_BLOCK_RE = re.compile(r"(<tr\b[^>]*>)(.*?)(</tr>)", re.DOTALL | re.IGNORECASE)
TD_OPEN_RE = re.compile(r"<td(\b[^>]*)>", re.IGNORECASE)
HTML_TAG_RE = re.compile(r"<[^>]+>")


def _inject_table_data_labels(rendered_html: str) -> str:
    """Stamps `data-label` attributes onto `<td>` cells from their column `<th>` headers."""

    def _rewrite_table(table_match: re.Match[str]) -> str:
        table_html = table_match.group(0)
        headers = [
            html.escape(html.unescape(HTML_TAG_RE.sub("", th)).strip(), quote=True)
            for th in TH_CELL_RE.findall(table_html)
        ]
        if not headers:
            return table_html

        def _rewrite_row(tr_match: re.Match[str]) -> str:
            tr_open, tr_inner, tr_close = tr_match.groups()
            col_idx = 0

            def _rewrite_td(td_match: re.Match[str]) -> str:
                nonlocal col_idx
                attrs = td_match.group(1)
                label = headers[col_idx] if col_idx < len(headers) else ""
                col_idx += 1
                if not label or "data-label=" in attrs.lower():
                    return td_match.group(0)
                return f'<td{attrs} data-label="{label}">'

            return f"{tr_open}{TD_OPEN_RE.sub(_rewrite_td, tr_inner)}{tr_close}"

        def _rewrite_tbody(tb_match: re.Match[str]) -> str:
            tb_open, tb_inner, tb_close = tb_match.groups()
            return f"{tb_open}{TR_BLOCK_RE.sub(_rewrite_row, tb_inner)}{tb_close}"

        return TBODY_BLOCK_RE.sub(_rewrite_tbody, table_html)

    return TABLE_BLOCK_RE.sub(_rewrite_table, rendered_html)


def render_markdown_to_html(md_text: str) -> str:
    """Renders GitHub-flavored Markdown (tables, fenced code, TOC ids) to mobile-ready HTML."""
    normalized_md = md_text.replace(r"\$", "$")
    rendered = markdown.markdown(
        normalized_md,
        extensions=["extra", "sane_lists", "smarty", "toc"],
        output_format="html5",
    )
    return _inject_table_data_labels(rendered)


def resolve_public_base_url(request: Request) -> str:
    """Resolves canonical external scheme + host behind Cloud Run's HTTPS proxy."""
    proto = request.headers.get("x-forwarded-proto", request.url.scheme).split(",")[0].strip()
    host = request.headers.get("x-forwarded-host", request.url.netloc).split(",")[0].strip()
    if host.endswith(".run.app"):
        proto = "https"
    return f"{proto}://{host}"


def create_app(store: EpisodeStore | None = None) -> FastAPI:
    """Application factory enabling clean dependency injection in unit tests."""
    app = FastAPI(
        title="GenMedia Pulse — Daily Digest & Podcast Portal",
        description="Daily generative video, world, image, and audio AI models digest & podcast.",
        version="1.0.0",
    )
    episode_store = store or EpisodeStore()
    app.state.store = episode_store

    app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")
    templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))

    @app.exception_handler(HTTPException)
    async def http_exc_handler(_request: Request, exc: HTTPException) -> JSONResponse:
        return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})

    @app.exception_handler(Exception)
    async def unhandled_exc_handler(_request: Request, exc: Exception) -> JSONResponse:
        return JSONResponse(status_code=500, content={"detail": f"Internal server error: {exc}"})

    def _validate_date(date_str: str) -> str:
        clean = date_str.strip()
        if not DATE_RE.match(clean):
            raise HTTPException(status_code=400, detail="Invalid episode date format (expected YYYY-MM-DD).")
        return clean

    def _render_episode_page(request: Request, target_date: str | None) -> HTMLResponse:
        manifest = episode_store.get_manifest()
        episodes: list[dict[str, Any]] = list(manifest.get("episodes", []))
        base_url = resolve_public_base_url(request)
        feed_url = f"{base_url}/feed.xml"
        apple_podcast_url = re.sub(r"^https?://", "podcast://", feed_url)

        selected_meta: dict[str, Any] | None = None
        if target_date:
            for ep in episodes:
                if ep.get("date") == target_date:
                    selected_meta = ep
                    break
            if selected_meta is None:
                md_probe = episode_store.get_digest_markdown(target_date)
                if md_probe is None:
                    raise HTTPException(status_code=404, detail=f"Episode {target_date} not found.")
                selected_meta = {
                    "date": target_date,
                    "title": f"GenMedia Pulse — {target_date}",
                    "summary": "",
                    "duration_label": "--:--",
                    "tags": [],
                }
        elif episodes:
            selected_meta = episodes[0]

        digest_html = ""
        transcript_data: dict[str, Any] | None = None
        active_date = ""
        if selected_meta is not None:
            active_date = str(selected_meta["date"])
            raw_md = episode_store.get_digest_markdown(active_date) or ""
            # Strip leading H1 from Markdown body so the page maintains a single semantic <h1>.
            body_md = re.sub(r"^\s*#\s+[^\n]+\n+", "", raw_md, count=1)
            digest_html = render_markdown_to_html(body_md)
            transcript_data = episode_store.get_transcript(active_date)

        return templates.TemplateResponse(
            request=request,
            name="index.html",
            context={
                "podcast_title": manifest.get("podcast_title", "GenMedia Pulse"),
                "podcast_subtitle": manifest.get("podcast_subtitle", ""),
                "episodes": episodes,
                "current_episode": selected_meta,
                "active_date": active_date,
                "digest_html": digest_html,
                "transcript": transcript_data,
                "feed_url": feed_url,
                "apple_podcast_url": apple_podcast_url,
                "base_url": base_url,
            },
        )

    @app.get("/healthz")
    @app.get("/api/health")
    async def healthz() -> dict[str, Any]:
        manifest = episode_store.get_manifest()
        return {
            "status": "ok",
            "bucket": episode_store.bucket_name,
            "episode_count": len(manifest.get("episodes", [])),
        }

    @app.get("/", response_class=HTMLResponse)
    async def home(request: Request) -> HTMLResponse:
        return _render_episode_page(request, target_date=None)

    @app.get("/episodes/{episode_date}", response_class=HTMLResponse)
    async def view_episode(request: Request, episode_date: str) -> HTMLResponse:
        clean_date = _validate_date(episode_date)
        return _render_episode_page(request, target_date=clean_date)

    @app.get("/api/episodes")
    async def api_list_episodes() -> dict[str, Any]:
        return episode_store.get_manifest()

    @app.get("/api/episodes/{episode_date}")
    async def api_get_episode(episode_date: str) -> dict[str, Any]:
        clean_date = _validate_date(episode_date)
        md = episode_store.get_digest_markdown(clean_date)
        if md is None:
            raise HTTPException(status_code=404, detail=f"Episode {clean_date} not found.")
        return {
            "date": clean_date,
            "digest_markdown": md,
            "digest_html": render_markdown_to_html(md),
            "transcript": episode_store.get_transcript(clean_date),
        }

    @app.api_route("/feed.xml", methods=["GET", "HEAD"])
    @app.api_route("/rss.xml", methods=["GET", "HEAD"])
    async def rss_feed(request: Request) -> Response:
        base_url = resolve_public_base_url(request)
        manifest = episode_store.get_manifest()

        def _render_ep_html(ep_date: str) -> str:
            md = episode_store.get_digest_markdown(ep_date)
            return render_markdown_to_html(md) if md else ""

        xml_str = build_rss_xml(base_url=base_url, manifest=manifest, html_renderer=_render_ep_html)
        xml_bytes = xml_str.encode("utf-8")
        headers = {
            "Cache-Control": "public, max-age=300",
            "Content-Length": str(len(xml_bytes)),
        }
        if request.method == "HEAD":
            return Response(
                status_code=200,
                media_type="application/rss+xml; charset=utf-8",
                headers=headers,
            )
        return Response(
            content=xml_bytes,
            media_type="application/rss+xml; charset=utf-8",
            headers=headers,
        )

    @app.api_route("/cover.jpg", methods=["GET", "HEAD"])
    async def cover_image(request: Request) -> Response:
        data = episode_store.get_cover_bytes()
        if data is None:
            raise HTTPException(status_code=404, detail="Podcast cover image not found.")
        headers = {
            "Cache-Control": "public, max-age=86400",
            "Content-Length": str(len(data)),
        }
        if request.method == "HEAD":
            return Response(status_code=200, media_type="image/jpeg", headers=headers)
        return Response(
            content=data,
            media_type="image/jpeg",
            headers=headers,
        )

    @app.api_route("/media/{episode_date}.mp3", methods=["GET", "HEAD"])
    async def stream_episode_mp3(request: Request, episode_date: str) -> Response:
        clean_date = _validate_date(episode_date)
        total_size = episode_store.get_audio_size(clean_date)
        if total_size is None or total_size <= 0:
            raise HTTPException(status_code=404, detail=f"Audio for {clean_date} not found.")

        common_headers = {
            "Accept-Ranges": "bytes",
            "Cache-Control": "public, max-age=3600",
            "Content-Disposition": f'inline; filename="genmedia-pulse-{clean_date}.mp3"',
        }

        range_header = request.headers.get("range", "").strip()
        if not range_header:
            headers = {**common_headers, "Content-Length": str(total_size)}
            if request.method == "HEAD":
                return Response(status_code=200, media_type="audio/mpeg", headers=headers)
            return StreamingResponse(
                episode_store.iter_audio_range(clean_date, 0, total_size - 1),
                status_code=200,
                media_type="audio/mpeg",
                headers=headers,
            )

        match = RANGE_RE.match(range_header)
        if not match:
            raise HTTPException(status_code=416, detail="Malformed Range header.")

        start_str, end_str = match.groups()
        if start_str == "" and end_str == "":
            raise HTTPException(status_code=416, detail="Empty byte range.")

        if start_str == "":
            # Suffix byte-range request: `bytes=-500`
            suffix_len = int(end_str)
            start = max(0, total_size - suffix_len)
            end = total_size - 1
        else:
            start = int(start_str)
            end = int(end_str) if end_str != "" else total_size - 1

        if start >= total_size or start < 0 or end < start:
            return Response(
                status_code=416,
                headers={"Content-Range": f"bytes */{total_size}", "Accept-Ranges": "bytes"},
            )

        end = min(end, total_size - 1)
        content_length = end - start + 1
        partial_headers = {
            **common_headers,
            "Content-Range": f"bytes {start}-{end}/{total_size}",
            "Content-Length": str(content_length),
        }

        if request.method == "HEAD":
            return Response(status_code=206, media_type="audio/mpeg", headers=partial_headers)

        return StreamingResponse(
            episode_store.iter_audio_range(clean_date, start, end),
            status_code=206,
            media_type="audio/mpeg",
            headers=partial_headers,
        )

    return app


app = create_app()
