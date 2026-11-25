---
title: Facemetric AI API
sdk: docker
app_port: 7860
---

# Facemetric AI

**A guided facial-analysis prototype for skin, hair, measurements, and personalized care suggestions.**

Built with **Next.js**, **FastAPI**, **MediaPipe**, and **OpenCV**.

> **Important:** Facemetric AI is an informational tool, not a medical diagnosis or a substitute for professional care. Measurements and recommendations are estimates and should be validated before real-world use.

## What you can do

| Area | What it offers |
|---|---|
| Guided analysis | Capture a front photo, with optional side, three-quarter, and top views. |
| Face measurements | Facial landmarks, proportions, profile angles, and measurement-based scores. |
| Skin and hair insights | Skin-zone observations, hairline checks, and follow-up guidance. |
| Personal care plan | Skin-care routines, product suggestions, home-remedy evidence ratings, and a dated countdown plan. |
| Reports and progress | A shareable report, optional accounts, and progress check-ins. |
| Payments and review | Stripe or Razorpay checkout, plus an optional expert-review workflow. |

Before/after previews are **simulated edits**, not predictions of treatment results. Optional AI try-on uses an external provider when configured; review [Provider Privacy](docs/PROVIDER_PRIVACY.md) before enabling it.

## How it works

1. The browser guides the user through photo capture and basic quality checks.
2. The FastAPI service processes landmarks and available image views.
3. The app builds measurements, observations, and a personalized report.
4. The user can review the preview, save progress, or unlock additional report features.

## Run it locally

### Requirements

- Python 3.10 or newer
- Node.js 20 LTS (or a compatible current LTS release) and npm
- The model files listed below

### 1. Set up and start the backend

The following commands are for **Windows PowerShell**:

```powershell
cd backend
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
Copy-Item .env.example .env

New-Item -ItemType Directory -Force models | Out-Null
curl.exe -L "https://storage.googleapis.com/mediapipe-models/face_landmarker/face_landmarker/float16/latest/face_landmarker.task" -o models\face_landmarker.task
curl.exe -L "https://storage.googleapis.com/mediapipe-models/image_segmenter/deeplab_v3/float32/latest/deeplab_v3.tflite" -o models\deeplab_v3.tflite
curl.exe -L "https://huggingface.co/Xenova/modnet/resolve/main/onnx/model.onnx" -o models\modnet.onnx
curl.exe -L "https://storage.googleapis.com/mediapipe-models/image_segmenter/selfie_multiclass_256x256/float32/1/selfie_multiclass_256x256.tflite" -o models\selfie_multiclass.tflite

.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload --port 8000
```

Keep this terminal open. The API will be available at `http://localhost:8000`.

On **macOS or Linux**, use the equivalent commands:

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
cp .env.example .env
mkdir -p models

curl -L "https://storage.googleapis.com/mediapipe-models/face_landmarker/face_landmarker/float16/latest/face_landmarker.task" -o models/face_landmarker.task
curl -L "https://storage.googleapis.com/mediapipe-models/image_segmenter/deeplab_v3/float32/latest/deeplab_v3.tflite" -o models/deeplab_v3.tflite
curl -L "https://huggingface.co/Xenova/modnet/resolve/main/onnx/model.onnx" -o models/modnet.onnx
curl -L "https://storage.googleapis.com/mediapipe-models/image_segmenter/selfie_multiclass_256x256/float32/1/selfie_multiclass_256x256.tflite" -o models/selfie_multiclass.tflite

python -m uvicorn app.main:app --reload --port 8000
```

### 2. Set up and start the frontend

In a second terminal:

```bash
cd frontend
npm ci
npm run dev
```

Open [http://localhost:3000](http://localhost:3000). The Next.js dev server forwards `/api/*` requests to `http://127.0.0.1:8000`. Set `API_URL` if your backend runs elsewhere.

On Windows, [start.bat](start.bat) can open both development servers after the backend environment and frontend dependencies have been installed.

### Model files

Model weights are intentionally not stored in Git. The commands above download the files used for face landmarks, side-profile segmentation, and hair segmentation into `backend/models/`.

Two additional models are optional:

- `ediffiqa_tiny_jun2024.onnx` enables the extra photo-quality score.
- `face_recognition_sface_2021dec.onnx` is used for face-identity checks in AI try-on.

Obtain optional models from their upstream sources and review their licenses before distributing or using them commercially. The optional SPIGA integration has a separate licensing warning below.

## Configuration

Edit `backend/.env` for local settings. The example file documents all available options.

| Setting | Purpose |
|---|---|
| `ANTHROPIC_API_KEY` | Enables Claude-written reports. Without it, the app uses its rule-based report fallback. |
| `RAZORPAY_KEY_ID`, `RAZORPAY_KEY_SECRET` | Enables Razorpay checkout. When configured, Razorpay takes priority over Stripe. |
| `STRIPE_SECRET_KEY`, `STRIPE_WEBHOOK_SECRET` | Enables Stripe checkout and webhook verification. Use test credentials during development. |
| `ADMIN_TOKEN`, `REVIEW_REQUIRED` | Protects the review dashboard and optionally holds paid reports for approval. |
| `DATA_ENCRYPTION_KEY`, `RETENTION_DAYS` | Controls report encryption and retention behavior. Review the security docs before deployment. |
| `FAL_KEY` or `GEMINI_API_KEY` | Enables optional, paid AI try-on through an external provider. |

With no payment provider configured, local development uses a **development-only unlock flow**. Do not deploy with that behavior enabled. Keep `.env`, model files, and user data private; never commit secrets.

## Main features

### Face, skin, and hair

- Guided front-camera capture with pose, lighting, sharpness, and liveness checks.
- Facial landmarks, proportions, profile measurements, and three-quarter jaw-angle estimation.
- Skin-zone observations and hairline checks, subject to the available model files and photo quality.
- Optional progress tracking for signed-in users.

### Personalized recommendations

- AM/PM routines with budget-aware product suggestions.
- Indian-context features such as rupee price bands, local product links, climate-aware advice, and wedding/festival countdown plans.
- Home remedies labeled by evidence level, with safety warnings.
- Report checks that constrain generated text to the analysis and apply safety rules.

### Reports, payments, and expert review

- Free preview with additional report sections available after unlock.
- Stripe and Razorpay payment flows, including webhook verification.
- Optional `/admin` review dashboard for paid reports.
- Optional hairstyle, beard, or glasses try-on through a configured image provider.

## API at a glance

The frontend and API are designed to run together locally. Useful endpoints include:

| Endpoint | Purpose |
|---|---|
| `POST /api/check` | Check a front photo before analysis. |
| `POST /api/check-side` | Check a side-profile photo. |
| `POST /api/check-three-quarter` | Check a three-quarter photo. |
| `POST /api/analyze` | Create an analysis from the selected photos and profile details. |
| `GET /api/analyses/{id}` | Retrieve an analysis and its current report state. |
| `POST /api/analyses/{id}/checkout` | Start checkout for a report. |
| `POST /api/analyses/{id}/confirm` | Verify payment and unlock the report. |
| `GET /api/me/progress` | Retrieve account progress and check-in status. |
| `GET/PUT/POST /api/admin/...` | Manage expert review (requires the admin token). |

The complete endpoint list is in [Endpoint Matrix](docs/ENDPOINT_MATRIX.md).

## Development

Frontend checks:

```bash
cd frontend
npm run lint
npm run build
```

Backend tests are in `backend/tests/` and use `pytest`:

```bash
cd backend
python -m pip install pytest
python -m pytest
```

## Project layout

```text
backend/
  app/             FastAPI routes and analysis modules
  tests/           Backend tests
  models/          Local model weights (not committed)
  data/            Local application data (not committed)
browser-tests/     Playwright browser tests
docs/              Validation, privacy, and deployment documentation
frontend/
  src/app/         Next.js pages
  src/components/  UI components
  src/lib/         Frontend helpers and types
```

## Limitations and responsible use

- This is an MVP. Facial measurements and image-based observations can be affected by pose, lighting, camera distance, occlusion, and model limitations.
- The app does not diagnose conditions or guarantee treatment outcomes. Encourage users to consult a qualified professional for medical concerns.
- Some models and optional providers have separate licensing, privacy, and usage costs. Review those terms before enabling them.
- Before production, review [Security and Privacy](docs/SECURITY_AND_PRIVACY.md), [Provider Privacy](docs/PROVIDER_PRIVACY.md), and [Production Readiness](docs/PRODUCTION_READINESS.md).
- SPIGA jaw-corner support is optional. Its weights are trained on WFLW research data; obtain legal review before enabling it commercially.
