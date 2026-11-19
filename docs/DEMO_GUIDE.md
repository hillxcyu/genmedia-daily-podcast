# GenMedia Pulse — Seller Demo Guide

## Executive Summary & Pitch Context

- **Target Buyer Personas:** Chief Marketing Officers (CMOs), VP of Content & Creative Operations, Media & Entertainment Engineering Directors, and AI Platform Architects.
- **Customer Pain Point:** Enterprise creative and engineering teams struggle to keep pace with daily breakthroughs across generative video, world simulation, image synthesis, and audio AI models. Manual research digests are static, time-consuming to read on mobile, and lack an automated, brand-safe audio briefing workflow.
- **Value Proposition:** GenMedia Pulse transforms raw daily Markdown research into a zero-database web portal, an Apple Podcasts / Podcast 2.0 RSS feed, and a broadcast-mastered two-host AI podcast (`-16 LUFS`, `128 kbps` CBR MP3) with click-to-seek transcripts—cutting daily content-to-audio production time from hours to under 2 minutes per episode.
- **Estimated Demo Duration:** 10–12 minutes.

---

## How to Build

GenMedia Pulse is architected as a stateless, zero-database Python application on Google Cloud using **Vertex AI (`google-genai`)**, **Gemini 3.8 Flash TTS**, **Gemini Nano Banana 2.1**, **Google Cloud Storage**, and **Google Cloud Run**.

### Step 1: Scaffold the Project & Dependencies
- Application dependencies are declared in [`requirements.txt`](../requirements.txt) (and pinned with SHA-256 supply-chain hashes in [`click-to-deploy/requirements.txt`](../click-to-deploy/requirements.txt)).
- Authentication and client initialization live in [`publisher/gcp_auth.py`](../publisher/gcp_auth.py), which routes Vertex AI calls through `GOOGLE_CLOUD_LOCATION=global` and uses Application Default Credentials (ADC) on Cloud Run.

### Step 2: Build the Content Sanitization & Pronunciation Pipeline
- [`publisher/sanitizer.py`](../publisher/sanitizer.py) enforces strict pre-publication guardrails, blocking internal links, confidential codenames, or email addresses before any LLM or TTS call runs.
- [`publisher/pronunciation.py`](../publisher/pronunciation.py) compiles a dual-track transcript: keeping clean technical acronyms (`4K`, `1080p`, `T2V/I2V/R2V`, `Arena.ai`) in the visual transcript while expanding them phonetically for natural speech synthesis.

### Step 3: Build the Script, Cover Art & Audio Synthesis Pipeline
- [`publisher/script_generator.py`](../publisher/script_generator.py) uses `google-genai` structured outputs (Pydantic) to turn a Markdown digest into a 16–22 turn (`750–900` words) dialogue between two hosts (**Alex** `Kore` and **Maya** `Puck`).
- [`publisher/audio_synthesizer.py`](../publisher/audio_synthesizer.py) synthesizes turns concurrently via Vertex AI `gemini-3.8-flash-tts`, records exact `start_sec` / `end_sec` timestamps for click-to-seek playback, inserts 180 ms conversational room pauses, and masters a `-16 LUFS` / `128 kbps` CBR MP3 with `ffmpeg`.
- [`publisher/generate_cover.py`](../publisher/generate_cover.py) generates `2048x2048` Apple Podcasts-compliant cover artwork via `gemini-nano-banana-2.1`.
- [`publisher/publish_episode.py`](../publisher/publish_episode.py) orchestrates validation, synthesis, and atomic upload of `digest.md`, `transcript.json`, `podcast.mp3`, and `index.json` to Cloud Storage.

### Step 4: Serve the Stateless Web Portal & RSS Feed
- [`portal/gcs_store.py`](../portal/gcs_store.py) implements TTL-cached reads and `256 KiB` chunked byte-range streaming from Cloud Storage (with `LOCAL_EPISODES_DIR` fallback for offline/local testing).
- [`portal/rss_builder.py`](../portal/rss_builder.py) generates Apple Podcasts / Podcast 2.0 compliant RSS 2.0 XML (`/feed.xml` and `/rss.xml`).
- [`portal/app.py`](../portal/app.py) serves the FastAPI web portal, responsive Markdown digest, sticky audio player, interactive click-to-seek transcript, and RFC 9110 `206 Partial Content` MP3 streaming.

### Step 5: Test & Deploy
- Run the unit test suite (`tests/test_portal_and_publisher.py`) to verify sanitizer guardrails, pronunciation normalization, RSS XML schema, and HTTP `206` byte-range streaming.
- Deploy infrastructure via [`click-to-deploy/`](../click-to-deploy/) Terraform.

---

## Pillar 1: Setup & Deployment Instructions

### 1.1 Prerequisites & IAM Permissions
- **GCP Environment:** A Google Cloud project with billing enabled.
- **Required IAM Roles (Deployer):** `roles/owner` or the combination of `roles/run.admin`, `roles/storage.admin`, `roles/artifactregistry.admin`, `roles/compute.loadBalancerAdmin`, `roles/iam.serviceAccountAdmin`, and `roles/serviceusage.serviceUsageAdmin`.
- **Required IAM Roles (Runtime Service Account — provisioned automatically by Terraform):** `roles/aiplatform.user`, `roles/logging.logWriter`, `roles/serviceusage.serviceUsageConsumer`, and bucket-scoped `roles/storage.objectAdmin`.
- **Required APIs (enabled automatically by Terraform):** `aiplatform.googleapis.com`, `artifactregistry.googleapis.com`, `cloudbuild.googleapis.com`, `compute.googleapis.com`, `iam.googleapis.com`, `iap.googleapis.com`, `logging.googleapis.com`, `run.googleapis.com`, `secretmanager.googleapis.com`, `serviceusage.googleapis.com`, and `storage.googleapis.com`.
- **Local Tools (for manual CLI deployment or episode publishing):** `gcloud`, `terraform` (`>= 1.5`), `python3` (`>= 3.11`), and `ffmpeg` (for audio mastering when publishing new episodes).

### 1.2 Option A: Automated Click-to-Deploy (Recommended)
1. Launch the Click-to-Deploy workflow from the Demo Portal for **GenMedia Pulse**.
2. Select your target GCP organization and project, and set `data_location` (default: `us-central1`).
3. Wait approximately **4–6 minutes** for Terraform to enable APIs, create the private GCS bucket, Artifact Registry, Cloud Run service (`INGRESS_TRAFFIC_INTERNAL_LOAD_BALANCER`), External HTTPS Load Balancer, Serverless NEG, and IAP service identity.
4. Build and push the container image to the provisioned Artifact Registry repository, then upload the sample episode (`episodes_local/`) to the provisioned GCS bucket:

```bash
export PROJECT_ID="your-gcp-project-id"
export REGION="us-central1"
export BUCKET_NAME="${PROJECT_ID}-genmedia-podcast"

gcloud builds submit \
  --project="${PROJECT_ID}" \
  --tag="${REGION}-docker.pkg.dev/${PROJECT_ID}/genmedia-pulse/genmedia-pulse:latest" \
  -f click-to-deploy/Dockerfile .

gcloud run services update genmedia-pulse \
  --project="${PROJECT_ID}" \
  --region="${REGION}" \
  --image="${REGION}-docker.pkg.dev/${PROJECT_ID}/genmedia-pulse/genmedia-pulse:latest"

gcloud storage cp -r episodes_local/2026-11-09 episodes_local/index.json episodes_local/cover.jpg \
  "gs://${BUCKET_NAME}/"
```

### 1.3 Option B: Manual CLI / Terraform Deployment
```bash
export PROJECT_ID="your-gcp-project-id"
export REGION="us-central1"

cd click-to-deploy
terraform init
terraform apply \
  -var="project_id=${PROJECT_ID}" \
  -var="data_location=${REGION}"
```

### 1.4 Option C: Instant Local / Offline Verification (Zero GCP Setup)
```bash
cp .env.example .env
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python -m unittest discover -s tests -v
LOCAL_EPISODES_DIR=episodes_local .venv/bin/uvicorn portal.app:app --host 0.0.0.0 --port 8080
```

### 1.5 Deployment Verification
Confirm the Cloud Run service is active and serving behind the Load Balancer:
```bash
gcloud run services list --project="${PROJECT_ID}" --region="${REGION}"
terraform -chdir=click-to-deploy output -raw app_url
```

### 1.6 Teardown & Cost Cleanup
To remove all provisioned cloud resources and prevent ongoing charges:
```bash
cd click-to-deploy
terraform destroy -var="project_id=${PROJECT_ID}" -var="data_location=${REGION}"
```

---

## Pillar 2: How to Access the Demo

### 2.1 Retrieving Entry Point URLs
- **From Click-to-Deploy:** Copy the `app_url` value from the deployment completion output.
- **From Terraform CLI:** Run `terraform -chdir=click-to-deploy output -raw app_url` (or `http://localhost:8080` when running locally with `LOCAL_EPISODES_DIR=episodes_local`).
- **RSS Feed Endpoint:** Append `/feed.xml` (or `/rss.xml`) to the base `app_url`.
- **Health Check Endpoint:** Append `/api/health` to verify backend readiness (`200 OK`).

### 2.2 Credentials & Network Prerequisites
- **Authentication:** When deployed behind External HTTPS Load Balancer + Identity-Aware Proxy (IAP), sign in with your authorized `@google.com` or project IAM user account (`roles/iap.httpsResourceAccessor`).
- **Cloud Run Ingress Security:** Cloud Run is configured with `INGRESS_TRAFFIC_INTERNAL_LOAD_BALANCER` so all public traffic must traverse the HTTPS Load Balancer and IAP—direct `*.run.app` access is blocked.
- **No In-App Login Required:** Once past IAP (or when running locally), the portal loads directly with no extra demo username or password.

### 2.3 Expected Initial Landing State
Upon opening the portal URL, confirm you see:
1. The **GenMedia Pulse** editorial header with the latest episode title (*"Stateful Sessions and the Rise of Interactive World Models"* for the included `2026-11-09` sample episode).
2. A sticky bottom/top **Audio Player** showing `05:32` total duration, playback speed controls (`1x`, `1.25x`, `1.5x`, `2x`), and a **Subscribe via RSS** link.
3. The formatted **Executive Summary & Technical Digest** tables on the left/main column and the **Interactive Two-Host Transcript** (Alex & Maya) with topic tags.

---

## Demo Walkthrough (Pillar 3 & Pillar 4: Step-by-Step Walkthrough & Seller Talking Script)

### Opening Discovery Hook (Before Sharing Screen)
> **What to Say:** *"Many creative and engineering leaders tell us their teams spend hours every week curating AI model updates across video, image, and audio—only to end up with static newsletters nobody has time to read. How does your team currently turn internal research or market intelligence into engaging, executive-ready briefings?"*

### Step 1: Explore the Zero-DB Editorial Portal & Sticky Audio Player
- **What to Do (Click Sequence):**
  1. Open the portal landing page (`/`).
  2. Scroll through the **Executive Summary** and the **Capability / Production Impact** Markdown table.
  3. Click **Play** on the sticky audio player and toggle playback speed between `1.0x` and `1.5x`.
- **Expected Visual Outcome:** Audio starts streaming immediately (via RFC 9110 HTTP `206 Partial Content` byte-range requests) without downloading the entire MP3 upfront, while the editorial digest remains crisp and readable.
- **What to Say (Seller Script):** *"Notice there is no database—no Cloud SQL, no Firestore—behind this portal. Everything is served statelessly from Cloud Run reading directly from private Cloud Storage with byte-range streaming. Your teams get instant playback on desktop or mobile with near-zero idle infrastructure cost."*
- **Why Google Cloud (Differentiator Callout):** *"By pairing Cloud Run with Cloud Storage byte-range streaming and an External HTTPS Load Balancer with IAP, you get enterprise access control and zero-ops scaling out of the box."*

### Step 2: Interactive Click-to-Seek Two-Host Transcript
- **What to Do (Click Sequence):**
  1. Locate the **Two-Host Transcript** section showing alternating turns from **Alex** and **Maya** with topic pills (e.g., `Omni 1.2 GA`, `Enterprise Workflows`).
  2. Click any transcript turn further down the episode (for example, Maya's turn on `Enterprise Workflows`).
- **Expected Visual Outcome:** The audio player immediately jumps to that exact `start_sec` timestamp (`206 Partial Content` range seek) and highlights the active speaker turn in real time as audio plays.
- **What to Say (Seller Script):** *"Busy executives don't always have five minutes to listen linearly. Because our Gemini 3.8 TTS pipeline records exact turn-level timestamps during synthesis, any reader can scan topic tags and click straight into the exact 20-second segment they care about."*

### Step 3: Apple Podcasts / Podcast 2.0 RSS Feed & Cover Art
- **What to Do (Click Sequence):**
  1. Click **RSS Feed** (`/feed.xml`) in the portal navigation.
  2. Optionally open `/cover.jpg` in a new tab to show the `2048x2048` artwork.
- **Expected Visual Outcome:** Valid RSS 2.0 XML with `<itunes:image>`, `<itunes:duration>`, and `<enclosure type="audio/mpeg">` tags, plus crisp `2048x2048` editorial cover art generated by `gemini-nano-banana-2.1`.
- **What to Say (Seller Script):** *"Every episode is simultaneously published as a standards-compliant Podcast 2.0 RSS feed. Employees or subscribers can listen in their favorite podcast client on their morning commute, while the web portal gives them the full reference tables and clickable transcript."*

### Step 4: Automated Producer Pipeline & Public-Safety Guardrails (Optional Technical Deep Dive)
- **What to Do (Click Sequence):**
  1. Show [`publisher/sanitizer.py`](../publisher/sanitizer.py) or run the test suite (`.venv/bin/python -m unittest discover -s tests -v`) in your terminal.
  2. Highlight how `publisher/publish_episode.py` turns a single Markdown file (`episodes_local/2026-11-09_source.md`) into a mastered podcast episode:
     ```bash
     python publisher/publish_episode.py \
       --date 2026-11-09 \
       --digest-file episodes_local/2026-11-09_source.md
     ```
- **Expected Visual Outcome:** All 7 unit tests pass in `< 0.2s`, demonstrating automated blocking of internal links/emails/codenames and exact acronym-to-speech normalization (`4K` → `four-K`, `T2V/I2V/R2V` → `text-to-video, image-to-video, and reference-to-video`).
- **What to Say (Seller Script):** *"Enterprise customers worry about two things with AI-generated media: brand pronunciation and accidental data leaks. Before a single token hits the LLM, our deterministic sanitizer blocks internal links, emails, or confidential codenames, and our pronunciation compiler ensures model names and acronyms sound like a human broadcast anchor."*
- **Why Google Cloud (Differentiator Callout):** *"Using Vertex AI's `google-genai` SDK with Gemini structured outputs, Gemini 3.8 Flash TTS, and Nano Banana 2.1 under one unified GCP security boundary means your content never leaves your enterprise project."*

### Closing & Next-Step Transition
- **Common Customer Objection & Response:**
  - *Objection:* *"Can we customize the host voices, language, or connect this to our own internal Confluence/BigQuery briefs?"*
  - *Response:* *"Yes—host personas and voices are configured in a single dictionary (`HOST_PROFILES` in `publisher/script_generator.py`), Gemini 3.8 TTS supports multilingual synthesis, and the publisher CLI accepts any Markdown input so it plugs directly into your existing docs or data pipelines."*
- **Call to Action:** *"We can deploy this architecture into your sandbox project using the included Terraform in under 10 minutes and run it against a sample of your own internal or customer newsletter. Who from your content and platform team should join us for a 30-minute build session next week?"*

---

## Troubleshooting & Live-Demo Recovery Tips

- **SSL Certificate Still Provisioning After First Terraform Apply:** Google-managed SSL certificates on a new External HTTPS Load Balancer can take 10–20 minutes to become `ACTIVE`. For an immediate live demo fallback, run the portal locally in offline mode (`LOCAL_EPISODES_DIR=episodes_local .venv/bin/uvicorn portal.app:app --port 8080`).
- **Cloud Run Cold Start:** The first request after idle scale-to-zero may take ~1–2 seconds. Open `/api/health` 2 minutes before your customer call to warm the container.
- **Audio Seek Returns 404 or Empty Manifest:** Verify `index.json`, `cover.jpg`, and `episodes/<YYYY-MM-DD>/{digest.md,transcript.json,podcast.mp3}` exist in the target `GCS_BUCKET` (or `episodes_local/` when running locally).
