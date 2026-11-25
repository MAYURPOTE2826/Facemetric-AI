# Facial measurement methodology (current implementation)

All values come from MediaPipe Face Landmarker (478 landmarks, 2D pixel coordinates; z is used only for yaw and
perspective correction). Indices live in `backend/app/metrics.py` (ratios) and `backend/app/anthropometry.py` (mm table).

## Scale (millimetres)
`mm_per_px = 11.7 mm / mean iris diameter in px` (`geometry.mm_per_px`). The 11.7 mm is a population average.
- Uncertainty: individual iris diameter varies, which scales every size by the same unknown factor, before landmark error. No uncertainty figure has been measured.
- Camera distance is estimated from the iris and a focal length (EXIF if present, else 26 mm equivalent); landmarks are
  rescaled by depth to reduce selfie perspective (`geometry.undistort`).
- **Not validated against physical measurements.** Treat mm as approximate; ratios are the more reliable output.

## Ratios that were audited
| Metric | Formula | Notes |
|---|---|---|
| `fwhr` | bizygomatic width / (upper-lip-top y - mean brow-top y) | was eyelid-based; fixed. Reference ~1.9 |
| `esr` | inter-pupil distance / bizygomatic width | |
| `midface_ratio` | inter-pupil distance / (upper-lip-top y - pupil y) | |
| `thirds_lower_mid` | (subnasale to menton) / (glabella to subnasale) | chin point is unreliable under a beard |
| `lower_third_split` | (stomion to subnasale) / (menton to stomion) | affected by smiling and beard |
| `intercanthal_eye` | inner-eye gap / mean eye width | rule of fifths = 1.0 |
| anthropometry `face_width : height` | bizygomatic / nasion-to-menton | a **different** ratio from `fwhr`; both appear in the report and must not be compared |

## Pre-processing
1. `frontalize`: rotates the 3D landmarks about the vertical axis to balance left/right pairs (search +/-30 deg).
2. `_level`: rotates the 2D points so the pupil line is horizontal.

Generated figures (`align.py`, `diagrams.py`, `imaging.annotate`) apply the same pupil-line levelling to the photo.

## Reference ranges
Placeholders from general anthropometry literature; not calibrated to any population and **not universal standards**.
Calibration by a qualified expert on consented data is required before they are presented as norms.
