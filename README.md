# Facemetric-AI — facial analysis MVP

Guided front photo (+ optional side profile and three-quarter view) → 478 facial landmarks,
profile silhouette tracing and jaw-angle estimation → up to 23 measured markers + zone-based
skin analysis → simulated before/after previews → personalised non-surgical plan, with
Stripe payments, an expert review dashboard and a shareable results card.

```
frontend/  Next.js 15 + Tailwind (landing, questionnaire + photo/camera, report)
backend/   FastAPI + MediaPipe Face Landmarker + OpenCV + Claude API
```

## Run locally

**Backend** (Python 3.10+):
```bash
cd backend
python -m venv .venv
.venv/Scripts/pip install -r requirements.txt      # Windows (use .venv/bin on mac/linux)
curl -L -o models/face_landmarker.task https://storage.googleapis.com/mediapipe-models/face_landmarker/face_landmarker/float16/latest/face_landmarker.task
curl -L -o models/deeplab_v3.tflite https://storage.googleapis.com/mediapipe-models/image_segmenter/deeplab_v3/float32/latest/deeplab_v3.tflite
curl -L -o models/modnet.onnx https://huggingface.co/Xenova/modnet/resolve/main/onnx/model.onnx
cp .env.example .env                              # add ANTHROPIC_API_KEY
.venv/Scripts/python -m uvicorn app.main:app --reload --port 8000
```

**Frontend**:
```bash
cd frontend
npm install
npm run dev        # http://localhost:3000  (proxies /api/* to :8000)
```

Without `ANTHROPIC_API_KEY` the app still works — reports are written by the
rule-based fallback in `backend/app/report.py` instead of Claude.

## India features

- **Razorpay + ₹ plans** - Full report ₹299, with expert review ₹799 (the expert plan routes to the
  review dashboard). UPI, cards, netbanking, wallets via Razorpay's in-page checkout.
- **Indian skin concerns** - uneven tone & tan (colour-based, so shadows don't count), pigmentation
  patches, acne marks (PIH), dark circles, with thresholds relative to the person's own skin tone.
  Skin-tone group (ITA°) is used only for safety advice. Never "fairness"; steroid/bleach warnings.
- **Routine in ₹** - AM/PM routine from concerns, skin type and budget, with products sold in India,
  price bands, a cheaper swap, and Nykaa/Amazon links (`AMAZON_ASSOCIATE_TAG` for commission).
- **Desi nuskhe** - home remedies rated works / okay / myth / avoid (2 free as a teaser).
- **Glow-up countdown** - wedding/festival date -> dated week-by-week plan (bride/groom variants).

- **Face shape + styling** - oval/round/square/oblong/heart/diamond from landmark ratios
  (`styling.py`), with hairstyles, beard styles (men), glasses frames and what to avoid; adjusted for a
  receding hairline, a slim jaw or a long lower face. Thresholds are starting values - calibrate.
- **City + season** - ~45 Indian cities mapped to climate zones (`climate.py`); the season (incl.
  Chennai's Oct-Dec monsoon) and winter pollution switch moisturiser/sunscreen texture, add tips and a
  "coming up" note. Recomputed on every read, so a saved routine follows the seasons.
- **Hair fall check** - MediaPipe multiclass segmenter (`models/selfie_multiclass.tflite`) traces the
  hairline and temples on the front photo; an optional top-of-head photo measures scalp show-through.
  A short questionnaire maps to likely causes (pattern, shock shedding, iron/B12/vit D, thyroid, PCOS,
  dandruff), blood tests to ask for, a plan and hair myths. "See a dermatologist" flags are always free.
- **Accounts + progress** - email/password accounts (`accounts.py`, PBKDF2 hashes, hashed bearer
  tokens in `data/users/`). Analyses made while signed in are saved automatically; others can be
  claimed with "Save to my progress". `/account` charts skin and hair scores across check-ins.

Setup: add `RAZORPAY_KEY_ID`, `RAZORPAY_KEY_SECRET` (test keys `rzp_test_...` first) and, for the
webhook, `RAZORPAY_WEBHOOK_SECRET` with the webhook URL `https://<your-domain>/api/razorpay/webhook`
(events: `order.paid`, `payment.captured`). Prices: `PRICE_FULL`, `PRICE_EXPERT` in paise.

## Accuracy upgrades (research-backed)

- **Real-world scale + selfie distortion** (`geometry.py`): iris width (11.7 mm) gives mm and camera
  distance. Close selfies (~30 cm) widen the nose up to ~30% (Ward et al., JAMA FPS 2018), so landmarks
  are depth-corrected before measuring - only when the focal length is known (EXIF or our live camera).
  The guided camera shows a live distance and won't auto-capture under 35 cm.
- **Multi-frame averaging**: the guided camera sends landmarks from ~20 steady frames; the server
  aligns them and takes a per-point median (simulated jitter: ratio error 9.8% -> 2.6%).
- **Indian reference values** (`metrics.py`, `profile.py`): nose/eye gap 1.15, mouth/nose 1.40, jaw
  0.86/0.80, single fWHR ideal, North-Indian/Kerala soft-tissue profile norms.
- **Photo checks** (`imaging.py`): resolution-independent sharpness, cheek-based uneven light / shadow /
  clipping, beauty-filter detection (skin vs eye band-pass texture), glasses and beard via segmentation.
- **Skin** (`skin.py`): segmentation removes hair/beard/glasses from the skin mask; white balance from the
  sclera; melanin index next to ITA; Hayashi acne grade, mMASI-style pigmentation extent, dark-circle grade.
- **Hair** (`hair.py`): hairline height and temple recession in cm with published norms; refined wash-test
  question, short-hair (miniaturisation) cue, red-flag questions; lab panel from Indian prevalence data
  (CBC, ferritin, TSH, vitamin D; B12 if vegetarian; androgens + prolactin for PCOS signs).
- **Report safety** (`report.py`): every Claude report is checked in code (banned fairness/cure wording,
  numbers must come from the measurements, doctor referral when flagged, no procedures for under-18s),
  retried once with the problems, else the rule-based report is used. System prompt is cached.
- **Routine safety** (`products.py`): pregnancy/breastfeeding (no retinol/salicylic serums),
  isotretinoin (no actives), steroid-cream history, sun exposure; iron-oxide tinted SPF for pigmentation.
- **Previews**: feature shifts capped at 3% of face width; overall skin colour locked (never lighter).
- **AI photo-quality score** (`faceid.py`): eDifFIQA-tiny (CC-BY-4.0, `models/ediffiqa_tiny_jun2024.onnx`)
  warns on low-quality photos; **colour-cast warning** from the whites of the eyes (tube light, warm bulb).
- **Blink liveness** (`liveness.py`): the guided camera asks for one blink before auto-capture and sends
  the blink scores; the server checks for a real blink. Stops photo-of-a-photo, not video replays.
- **Beard**: when a beard covers the jaw, jaw/chin measurements (front, three-quarter and chin-based
  profile angles) are left out instead of guessed, and face-shape confidence is lowered.
- **Parting width** (`hair.py`): on the top-of-head photo the parting is found and measured in mm (scale
  from head width, ±20%), with "Christmas-tree" widening detection for female-pattern thinning.
- **Neck & tan** (`skin.py`): neck vs cheek colour (face tan / neck darker). A front photo can't tell chin
  shadow from acanthosis nigricans, so the photo only prompts; a "dark velvety neck/underarms" answer
  gives a doctor + fasting sugar/HbA1c recommendation. Redness threshold is lowered for deeper skin.
- **Aligned progress** (`imaging.aligned_b64`, `accounts.py`): every photo is also stored eye-aligned, the
  progress page overlays first vs latest, and hair changes are marked "real" only above their repeat error
  (hairline 0.5 cm, parting 1.5 mm / 25%, scalp 4%). Different lighting between photos is flagged.
- **6-8 week routine check-in** (`POST /api/me/checkin`): irritation (which product), progress and
  consistency. Irritation removes that active (or pauses all actives for 2 weeks); "same + daily +
  no irritation" adds the next active; "worse" sends to a dermatologist. Calendar (.ics) reminder.
- **Report grounding** (`report.py`): every section lists `based_on` evidence keys (shown as "Based on"
  chips); numbers are checked against everything in the payload; safety rules for pregnancy,
  isotretinoin, minors, hydroquinone/steroid creams; unsafe methods are filtered out before the model
  sees them. **Eval set**: `python -m evals.report_evals` (50 profiles + validator tests, free);
  `--live 10` also asks Claude for 10 reports (needs `ANTHROPIC_API_KEY`).
- **AI try-on** (`tryon.py`, paid reports): recommended hairstyles/beards/glasses on the client's photo via
  fal.ai FLUX Kontext (`FAL_KEY`) or Gemini image (`GEMINI_API_KEY`), ~₹3-4 each, 6 per report. Every
  result must pass an SFace identity check (Apache-2.0) and a skin-colour check, or it isn't shown.
- **SPIGA jaw corners** (`jawline.py`, optional): `pip install -r requirements-spiga.txt` and
  `ENABLE_SPIGA=1`. Code is BSD-3 but the weights are trained on WFLW (non-commercial research data) -
  **get a legal review before enabling in production**. The jaw ideal was set on MediaPipe points, so
  re-check it if you enable this.

Not done (needs data or licences): a trained acne detector (no commercial-use weights exist - train on
your own consented Indian photos with an Apache-licensed detector), a learned face-shape classifier, and
a 300-photo dermatologist-labelled calibration set to tune every threshold above.

## Payments (Stripe)

Free preview → paid unlock. After upload the user sees their overall and category scores,
annotated photos, two sample measurements and strengths. Paying unlocks every
measurement, the feature-by-feature plan, the 90-day plan and PDF export. The
Claude-written report is generated only after payment, so free previews cost nothing.

- **Dev mode** (no `STRIPE_SECRET_KEY`): "Unlock" skips checkout. Never deploy like this.
- **Stripe mode**: set `STRIPE_SECRET_KEY` (test key `sk_test_...` first), `PUBLIC_URL`, and
  the price in `backend/.env`. Unlock is verified on return from Checkout
  (`/confirm`), and also by webhook in case the user closes the tab:
  ```bash
  stripe listen --forward-to localhost:8000/api/stripe/webhook   # prints STRIPE_WEBHOOK_SECRET
  ```
  Test card: `4242 4242 4242 4242`, any future date, any CVC.

## Expert review dashboard

`/admin` (password = `ADMIN_TOKEN` in `backend/.env`). Lists every analysis, filters by
"Needs review" / paid / unpaid, and opens an editor for the whole report: headline,
overview, strengths, sections, recommendations (or add from the method library), 90-day
plan and a personal note to the client. "Regenerate" rewrites it with Claude.

Set `REVIEW_REQUIRED=true` to hold paid reports ("being reviewed") until a specialist
approves them; approved reports show a "Specialist reviewed" badge and the note.

## How the analysis works

| Step | File |
|---|---|
| Landmarks, head pose, expression blendshapes | `backend/app/landmarks.py` |
| Photo quality gate (pose, blur, light, expression) | `backend/app/imaging.py` |
| Yaw correction + 13 measurements + scores | `backend/app/metrics.py` |
| Side profile: silhouette (MODNet / DeepLab) → edge snapping → 9 profile angles | `backend/app/profile.py` |
| Three-quarter view → jaw (gonial) angle from 3D landmarks | `backend/app/three_quarter.py` |
| Skin zones: wrinkles, blemishes, dark spots, dark circles, redness, texture, shine | `backend/app/skin.py` |
| Simulated before/after previews (local warps + retouch, no external AI) | `backend/app/previews.py` |
| Photo quality gate + annotated overlay | `backend/app/imaging.py` |
| Method library (the product's core IP) | `backend/app/recommendations.py` |
| Written report (Claude, structured output) | `backend/app/report.py` |
| Razorpay / Stripe checkout, verification, webhooks | `backend/app/payments.py` |
| AM/PM routine with Indian products | `backend/app/products.py` |
| Home remedies rated by evidence | `backend/app/remedies.py` |
| Wedding / festival glow-up countdown | `backend/app/countdown.py` |
| Review dashboard API | `backend/app/admin.py` |
| API, preview/unlock | `backend/app/main.py` |
| JSON storage in `backend/data/` | `backend/app/store.py` |
| Live camera guidance (in-browser MediaPipe) | `frontend/src/lib/faceGuide.ts`, `frontend/src/components/Cameras.tsx` |
| Share card (canvas, on-device) | `frontend/src/components/ShareCard.tsx` |

## API

- `POST /api/check` — `front` image → quality check only (fast)
- `POST /api/check-side` — `side` image (+ `sex`) → can the profile be traced? + preview
- `POST /api/check-three-quarter` — `three_quarter` image → jaw angle check + preview
- `POST /api/analyze` — `front`, optional `side`, `three_quarter` and `top` images, `profile` JSON → analysis, saved
- `GET  /api/analyses/{id}` — saved analysis (preview until paid)
- `POST /api/analyses/{id}/checkout` — `{plan}` → Razorpay order options or a Stripe/dev URL
- `POST /api/analyses/{id}/confirm` — Razorpay signature / Stripe session → verifies, writes the full report
- `POST /api/{razorpay|stripe}/webhook` — payment webhooks
- `POST /api/check-top` — `top` image → scalp coverage check + preview
- `POST /api/auth/signup` / `login` / `logout`, `GET /api/me` — accounts (`Authorization: Bearer <token>`)
- `POST /api/me/analyses/{id}/claim` — save a signed-out analysis to the account
- `GET  /api/me/progress` — all check-ins + first-vs-latest changes (with real-change flags) + check-in status
- `POST /api/me/checkin` — `{analysis_id, irritation, irritating, progress, consistency}` → adjusts that report's routine
- `POST /api/analyses/{id}/tryon` — `{kind: hair|beard|glasses, style}` (paid; style must be one recommended in the report)
- `GET/PUT/POST /api/admin/...` — review dashboard (header `X-Admin-Token`)

## Next steps

1. Calibrate reference ranges (`metrics.py`, `profile.py`, `three_quarter.py`) and skin
   thresholds (`skin.py`) on real labelled photos, per sex / ethnicity / age.
2. Train or license skin models (acne, wrinkles, pigmentation) and drop them into `skin.py`.
3. Accounts + history + Postgres + S3 instead of JSON files.
4. Before launch: consent flow, biometric-data compliance (GDPR / BIPA / CCPA),
   retention + deletion policy, 18+ age gate, terms & medical disclaimer.
