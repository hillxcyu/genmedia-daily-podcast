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

output "app_url" {
  description = "External HTTPS URL for the GenMedia Pulse portal behind the Application Load Balancer."
  value       = "https://${local.effective_domain}"
}

output "lb_ip" {
  description = "Static external IP address of the HTTPS Application Load Balancer."
  value       = google_compute_global_address.web.address
}

output "lb_domain" {
  description = "Managed-certificate hostname for the GenMedia Pulse portal."
  value       = local.effective_domain
}

output "gcs_bucket_name" {
  description = "Private GCS bucket storing daily digests, transcripts, MP3 audio, and cover art."
  value       = google_storage_bucket.podcast.name
}

output "artifact_registry_repo" {
  description = "Artifact Registry Docker repository path."
  value       = "${var.data_location}-docker.pkg.dev/${var.project_id}/${google_artifact_registry_repository.images.repository_id}"
}

output "cloud_run_service_name" {
  description = "Deployed Cloud Run service name."
  value       = google_cloud_run_v2_service.portal.name
}

output "runtime_service_account_email" {
  description = "Least-privilege runtime service account email attached to Cloud Run."
  value       = google_service_account.runtime.email
}
