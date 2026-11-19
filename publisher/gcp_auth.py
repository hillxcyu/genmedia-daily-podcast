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
"""GCP authentication and client factory for local runs and Cloud Run.

On Cloud Run (`K_SERVICE` set), uses native Application Default Credentials.
On local workstations, optionally uses a named `gcloud` configuration if
`GCLOUD_CONFIG_NAME` is set, falling back to Application Default Credentials.
"""

from __future__ import annotations

import os
import subprocess
import time
from typing import Any

import google.auth
import google.auth.credentials
import google.auth.transport.requests
from google.cloud import storage
from google import genai

DEFAULT_PROJECT = "your-gcp-project-id"
DEFAULT_LOCATION = "global"
DEFAULT_BUCKET = "your-gcs-bucket-name"
CLOUD_PLATFORM_SCOPES = ["https://www.googleapis.com/auth/cloud-platform"]


class GcloudCliCredentials(google.auth.credentials.Credentials):
    """Auto-refreshing Google credentials backed by `gcloud auth print-access-token`."""

    def __init__(self, configuration: str = "", quota_project_id: str | None = None) -> None:
        super().__init__()
        self.configuration = configuration
        self._quota_project_id = quota_project_id
        self._fetched_at = 0.0
        self.refresh(None)

    @property
    def valid(self) -> bool:
        return bool(self.token) and (time.monotonic() - self._fetched_at) < 2400.0

    @property
    def expired(self) -> bool:
        return not self.valid

    @property
    def quota_project_id(self) -> str | None:
        return self._quota_project_id

    def refresh(self, request: Any) -> None:  # noqa: ARG002
        cmd = ["gcloud", "auth", "print-access-token"]
        if self.configuration:
            cmd.append(f"--configuration={self.configuration}")
        proc = subprocess.run(cmd, check=True, capture_output=True, text=True, timeout=15)
        token = proc.stdout.strip()
        if not token:
            raise RuntimeError("gcloud auth print-access-token returned an empty token.")
        self.token = token
        self._fetched_at = time.monotonic()


def get_project_id() -> str:
    """Returns target GCP project ID from `GOOGLE_CLOUD_PROJECT`."""
    return os.environ.get("GOOGLE_CLOUD_PROJECT", DEFAULT_PROJECT).strip() or DEFAULT_PROJECT


def get_location() -> str:
    """Returns Vertex AI location (defaulting to 'global')."""
    return os.environ.get("GOOGLE_CLOUD_LOCATION", DEFAULT_LOCATION).strip() or DEFAULT_LOCATION


def get_bucket_name() -> str:
    """Returns target GCS bucket name."""
    return os.environ.get("GCS_BUCKET", DEFAULT_BUCKET).strip() or DEFAULT_BUCKET


def get_gcp_credentials(project_id: str | None = None) -> google.auth.credentials.Credentials:
    """Returns credentials authorized for the target GCP project."""
    target_project = project_id or get_project_id()
    if os.environ.get("K_SERVICE"):
        creds, _ = google.auth.default(scopes=CLOUD_PLATFORM_SCOPES)
        if hasattr(creds, "with_quota_project"):
            creds = creds.with_quota_project(target_project)
        return creds

    gcloud_cfg = os.environ.get("GCLOUD_CONFIG_NAME", "").strip()
    if gcloud_cfg:
        try:
            return GcloudCliCredentials(configuration=gcloud_cfg, quota_project_id=target_project)
        except Exception:
            pass
    creds, _ = google.auth.default(scopes=CLOUD_PLATFORM_SCOPES)
    if hasattr(creds, "with_quota_project"):
        creds = creds.with_quota_project(target_project)
    return creds


def get_Bearer_headers(creds: google.auth.credentials.Credentials, project_id: str) -> dict[str, str]:
    """Builds authenticated HTTP headers with quota project binding."""
    if not creds.valid:
        creds.refresh(google.auth.transport.requests.Request())
    return {
        "Authorization": f"Bearer {creds.token}",
        "x-goog-user-project": project_id,
        "Content-Type": "application/json",
    }


def get_genai_client(project_id: str | None = None, location: str | None = None) -> genai.Client:
    """Constructs a Vertex AI-backed google-genai client."""
    proj = project_id or get_project_id()
    loc = location or get_location()
    creds = get_gcp_credentials(proj)
    return genai.Client(vertexai=True, project=proj, location=loc, credentials=creds)


def get_storage_client(project_id: str | None = None) -> storage.Client:
    """Constructs a Google Cloud Storage client."""
    proj = project_id or get_project_id()
    creds = get_gcp_credentials(proj)
    return storage.Client(project=proj, credentials=creds)
