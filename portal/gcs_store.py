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
"""Stateless Google Cloud Storage data layer with TTL caching and byte-range reads.

Supports both live Google Cloud Storage (`gs://<GCS_BUCKET>`) on Cloud Run /
local workstations and a deterministic `LOCAL_EPISODES_DIR` filesystem backend
for unit tests and offline development.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
import subprocess
import time
from typing import Any, Iterator

import google.auth
import google.auth.credentials
from google.api_core.exceptions import NotFound
from google.cloud import storage

DEFAULT_PROJECT = "your-gcp-project-id"
DEFAULT_BUCKET = "your-gcs-bucket-name"
CHUNK_SIZE = 256 * 1024  # 256 KiB streaming chunks


class _LocalGcloudCredentials(google.auth.credentials.Credentials):
    """Refreshes local `gcloud` CLI token when running outside Cloud Run."""

    def __init__(self, configuration: str = "") -> None:
        super().__init__()
        self.configuration = configuration
        self._fetched_at = 0.0
        self.refresh(None)

    @property
    def valid(self) -> bool:
        return bool(self.token) and (time.monotonic() - self._fetched_at) < 2400.0

    @property
    def expired(self) -> bool:
        return not self.valid

    def refresh(self, request: Any) -> None:  # noqa: ARG002
        cmd = ["gcloud", "auth", "print-access-token"]
        if self.configuration:
            cmd.append(f"--configuration={self.configuration}")
        proc = subprocess.run(cmd, check=True, capture_output=True, text=True, timeout=15)
        self.token = proc.stdout.strip()
        self._fetched_at = time.monotonic()


@dataclass
class _CacheEntry:
    value: Any
    expires_at: float


class EpisodeStore:
    """Reads daily digests, transcripts, cover art, and MP3 byte-ranges."""

    def __init__(
        self,
        bucket_name: str | None = None,
        local_dir: Path | None = None,
    ) -> None:
        env_local = os.environ.get("LOCAL_EPISODES_DIR", "").strip()
        self.local_dir: Path | None = local_dir or (Path(env_local) if env_local else None)
        self.project_id = os.environ.get("GOOGLE_CLOUD_PROJECT", DEFAULT_PROJECT).strip() or DEFAULT_PROJECT
        self.bucket_name = (
            bucket_name or os.environ.get("GCS_BUCKET", DEFAULT_BUCKET).strip() or DEFAULT_BUCKET
        )
        self._storage_client: storage.Client | None = None
        self._cache: dict[str, _CacheEntry] = {}

    def _get_cached(self, key: str) -> Any | None:
        entry = self._cache.get(key)
        if entry and entry.expires_at > time.monotonic():
            return entry.value
        return None

    def _set_cached(self, key: str, value: Any, ttl_sec: float) -> Any:
        self._cache[key] = _CacheEntry(value=value, expires_at=time.monotonic() + ttl_sec)
        return value

    def _bucket(self) -> storage.Bucket:
        if self._storage_client is None:
            if os.environ.get("K_SERVICE"):
                creds, _ = google.auth.default(
                    scopes=["https://www.googleapis.com/auth/cloud-platform"]
                )
                self._storage_client = storage.Client(project=self.project_id, credentials=creds)
            else:
                cfg = os.environ.get("GCLOUD_CONFIG_NAME", "").strip()
                if cfg:
                    try:
                        creds = _LocalGcloudCredentials(configuration=cfg)
                        self._storage_client = storage.Client(project=self.project_id, credentials=creds)
                    except Exception:
                        self._storage_client = storage.Client(project=self.project_id)
                else:
                    self._storage_client = storage.Client(project=self.project_id)
        return self._storage_client.bucket(self.bucket_name)

    def get_manifest(self) -> dict[str, Any]:
        """Returns `index.json` manifest (with 20s TTL cache)."""
        cached = self._get_cached("manifest")
        if cached is not None:
            return cached

        default_manifest: dict[str, Any] = {
            "podcast_title": "GenMedia Pulse — Daily AI Media Models Briefing",
            "podcast_subtitle": (
                "Daily 5-minute two-host briefing on generative video, world simulation, "
                "image synthesis, and audio AI models."
            ),
            "updated_at": "",
            "episodes": [],
        }

        if self.local_dir is not None:
            idx_path = self.local_dir / "index.json"
            if not idx_path.exists():
                return default_manifest
            data = json.loads(idx_path.read_text(encoding="utf-8"))
            return self._set_cached("manifest", data, ttl_sec=5.0)

        try:
            raw = self._bucket().blob("index.json").download_as_text(encoding="utf-8")
            data = json.loads(raw)
            return self._set_cached("manifest", data, ttl_sec=20.0)
        except NotFound:
            return default_manifest

    def get_digest_markdown(self, episode_date: str) -> str | None:
        """Returns raw Markdown digest for `episode_date`, or None if missing."""
        cache_key = f"digest:{episode_date}"
        cached = self._get_cached(cache_key)
        if cached is not None:
            return str(cached)

        if self.local_dir is not None:
            p = self.local_dir / episode_date / "digest.md"
            if not p.exists():
                return None
            return str(self._set_cached(cache_key, p.read_text(encoding="utf-8"), ttl_sec=10.0))

        try:
            md = self._bucket().blob(f"episodes/{episode_date}/digest.md").download_as_text(
                encoding="utf-8"
            )
            return str(self._set_cached(cache_key, md, ttl_sec=120.0))
        except NotFound:
            return None

    def get_transcript(self, episode_date: str) -> dict[str, Any] | None:
        """Returns structured two-host `transcript.json` for `episode_date`."""
        cache_key = f"transcript:{episode_date}"
        cached = self._get_cached(cache_key)
        if cached is not None:
            return dict(cached)

        if self.local_dir is not None:
            p = self.local_dir / episode_date / "transcript.json"
            if not p.exists():
                return None
            data = json.loads(p.read_text(encoding="utf-8"))
            return dict(self._set_cached(cache_key, data, ttl_sec=10.0))

        try:
            raw = self._bucket().blob(f"episodes/{episode_date}/transcript.json").download_as_text(
                encoding="utf-8"
            )
            data = json.loads(raw)
            return dict(self._set_cached(cache_key, data, ttl_sec=120.0))
        except NotFound:
            return None

    def get_cover_bytes(self) -> bytes | None:
        """Returns `cover.jpg` bytes."""
        cached = self._get_cached("cover_jpg")
        if cached is not None:
            return bytes(cached)

        if self.local_dir is not None:
            p = self.local_dir / "cover.jpg"
            if not p.exists():
                return None
            return bytes(self._set_cached("cover_jpg", p.read_bytes(), ttl_sec=60.0))

        try:
            raw = self._bucket().blob("cover.jpg").download_as_bytes()
            return bytes(self._set_cached("cover_jpg", raw, ttl_sec=600.0))
        except NotFound:
            return None

    def get_audio_size(self, episode_date: str) -> int | None:
        """Returns total byte length of `podcast.mp3`, or None if not found."""
        cache_key = f"audio_size:{episode_date}"
        cached = self._get_cached(cache_key)
        if cached is not None:
            return int(cached)

        if self.local_dir is not None:
            p = self.local_dir / episode_date / "podcast.mp3"
            if not p.exists():
                return None
            return int(self._set_cached(cache_key, p.stat().st_size, ttl_sec=30.0))

        blob = self._bucket().blob(f"episodes/{episode_date}/podcast.mp3")
        try:
            blob.reload()
        except NotFound:
            return None
        if blob.size is None:
            return None
        return int(self._set_cached(cache_key, int(blob.size), ttl_sec=300.0))

    def iter_audio_range(self, episode_date: str, start: int, end: int) -> Iterator[bytes]:
        """Streams inclusive byte range `[start, end]` of `podcast.mp3` in 256 KiB chunks."""
        if self.local_dir is not None:
            p = self.local_dir / episode_date / "podcast.mp3"
            with p.open("rb") as fh:
                fh.seek(start)
                remaining = end - start + 1
                while remaining > 0:
                    chunk = fh.read(min(CHUNK_SIZE, remaining))
                    if not chunk:
                        break
                    remaining -= len(chunk)
                    yield chunk
            return

        blob = self._bucket().blob(f"episodes/{episode_date}/podcast.mp3")
        cursor = start
        while cursor <= end:
            chunk_end = min(cursor + CHUNK_SIZE - 1, end)
            data = blob.download_as_bytes(start=cursor, end=chunk_end, raw_download=True)
            if not data:
                break
            yield data
            cursor += len(data)
