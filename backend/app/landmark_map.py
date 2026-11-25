"""Central, documented MediaPipe Face Landmarker index map (478 landmarks: 468 face-mesh + 10 iris).

Conventions
-----------
* "R_" / "L_" are the SUBJECT's right / left. The subject's right is on the IMAGE's left (un-mirrored photo).
* Coordinates from `landmarks.detect()` are pixels: x = x_norm * width, y = y_norm * height, z = z_norm * width
  (z is relative depth, smaller = nearer the camera; it is not metric).
* Indices 468-472 are the right iris (centre first), 473-477 the left iris.
* The mapping is verified by tests/test_landmark_map.py (structure) and tests/test_landmarks_real.py (a mirrored photo must
  give mirror-image landmarks with each left/right pair swapped - this checks the pairs against the real model).

New code must import names from here instead of writing numeric indices. Modules that still contain numeric literals
(skin.py, hair.py, imaging.py, previews.py, profile.py, ...) are listed in docs/LANDMARK_VALIDATION.md.
"""
from __future__ import annotations

MAP_VERSION = "landmark-map-v1"
LANDMARK_COUNT = 478
FACE_MESH_COUNT = 468

R_EYE_OUT, R_EYE_IN, R_EYE_UP, R_EYE_LOW = 33, 133, 159, 145
L_EYE_IN, L_EYE_OUT, L_EYE_UP, L_EYE_LOW = 362, 263, 386, 374
R_IRIS, L_IRIS = 468, 473
R_BROW_TOP, L_BROW_TOP = 105, 334
R_ZYGO, L_ZYGO = 234, 454
R_GONION, L_GONION = 172, 397
FOREHEAD, GLABELLA, NASION, NOSE_TIP, SUBNASALE = 10, 9, 168, 1, 2
R_ALA, L_ALA = 129, 358
R_MOUTH, L_MOUTH = 61, 291
UPPER_LIP_TOP, UPPER_LIP_IN, LOWER_LIP_IN, LOWER_LIP_BOTTOM = 0, 13, 14, 17
MENTON = 152

MIDLINE = [10, 151, 9, 8, 168, 6, 197, 195, 5, 4, 1, 2, 0, 13, 14, 17, 18, 200, 199, 175, 152]
# Midline points that don't protrude much (nose tip shifts sideways with any head turn).
MIDLINE_STABLE = [10, 151, 9, 8, 168, 0, 13, 14, 17, 18, 200, 199, 175, 152]
SYMMETRY_PAIRS = [
    (33, 263), (133, 362), (159, 386), (145, 374), (105, 334), (46, 276), (70, 300),
    (107, 336), (234, 454), (93, 323), (132, 361), (58, 288), (172, 397), (136, 365),
    (61, 291), (129, 358), (50, 280), (205, 425), (40, 270), (91, 321),
]


# Iris extents (horizontal edge points) used for the iris-based scale (geometry.iris_px)
R_IRIS_H = (469, 471)
L_IRIS_H = (474, 476)
# Other named points used by the measurement / figure modules
FOREHEAD_TOP = FOREHEAD  # mesh point 10: top of the forehead surface (NOT the hairline)
R_BROW_IN, L_BROW_IN = 107, 336
R_BROW_OUT, L_BROW_OUT = 70, 300
R_FOREHEAD_SIDE, L_FOREHEAD_SIDE = 54, 284
LOWER_LIP_TOP_IN = LOWER_LIP_IN

ALL_NAMED = {k: v for k, v in dict(globals()).items() if k.isupper() and isinstance(v, int) and k not in ("LANDMARK_COUNT", "FACE_MESH_COUNT")}
