# GenMedia Pulse — Daily Digest Portal & Two-Host Podcast

Lightweight, zero-database web portal and Apple Podcasts / Podcast 2.0 RSS server hosted on Google Cloud Run and backed by Google Cloud Storage (`gs://<GCS_BUCKET>`).

## Architecture

- **Producer (`publisher/publish_episode.py`)**:
  1. Validates `digest.md` with `publisher/sanitizer.py` to ensure zero internal links, emails, or confidential markers reach public Cloud Storage.
  2. Generates a ~5-minute (`750–900` words) two-host conversational English dialogue (**Alex** `Kore` + **Maya** `Puck`) using `google-genai` on Vertex AI (`GOOGLE_CLOUD_LOCATION=global`).
  3. Compiles dual-track acronyms (`publisher/pronunciation.py`), synthesizes turns concurrently via `gemini-3.8-flash-tts`, masters `-16 LUFS` / `128 kbps` CBR MP3 via `ffmpeg`, uploads `{digest.md, transcript.json, podcast.mp3}` to GCS, and updates `index.json`.
- **Stateless Web Portal & RSS (`portal/app.py`)**:
  - `GET /` & `GET /episodes/{YYYY-MM-DD}`: Editorial Markdown digest + sticky audio player + click-to-seek two-host transcript.
  - `GET /feed.xml` (and `/rss.xml`): Apple Podcasts / Podcast 2.0 RSS 2.0 XML.
  - `GET /media/{YYYY-MM-DD}.mp3`: RFC 9110 HTTP `206 Partial Content` (`Accept-Ranges: bytes`) streaming from Cloud Storage (or `LOCAL_EPISODES_DIR` offline).
  - `GET /cover.jpg`: `2048x2048` cover artwork generated via `gemini-nano-banana-2.1`.

## Quick Start

```bash
# 1. Configure environment variables
cp .env.example .env

# 2. Run unit tests
.venv/bin/python -m unittest discover -s tests -v

# 3. Run portal locally with the included synthetic sample episode (no GCP required)
LOCAL_EPISODES_DIR=episodes_local .venv/bin/uvicorn portal.app:app --host 0.0.0.0 --port 8080

# 4. Publish a new daily episode to Google Cloud Storage
export GOOGLE_CLOUD_PROJECT="your-gcp-project-id"
export GOOGLE_CLOUD_LOCATION="global"
export GCS_BUCKET="your-gcs-bucket-name"
.venv/bin/python publisher/publish_episode.py \
  --date 2026-11-09 \
  --digest-file episodes_local/2026-11-09_source.md
```

## Click-to-Deploy

See [`click-to-deploy/`](click-to-deploy/) for Terraform infrastructure-as-code provisioning Cloud Run (behind an External HTTPS Application Load Balancer with Serverless NEG and IAP), GCS, Artifact Registry, and Vertex AI APIs.
