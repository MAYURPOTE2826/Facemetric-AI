# `frontalize()` vs MediaPipe yaw - investigation

Reproduce: `python -m evals.frontalize_investigation --image <photo> [--image <photo2>]`; tests: `tests/test_frontalize_and_landmarks.py`.
Neither estimate is declared "correct": **no ground-truth head pose exists in this project.** n = 2 photographs.

## Conventions (established)
- `frontalize_with_status()` returns the rotation `d` (degrees) applied to the 3D landmarks about the vertical image axis
  (`x' = x cos d + z sin d`, `z' = -x sin d + z cos d`) that best balances the summed `|x - midline|` of the left and right members of the
  symmetry pairs. Adding a head turn `a` changes the result by exactly `-a` (verified: slope 1, 0.00 deg error on exact geometry).
- MediaPipe yaw is the Euler yaw (`cv2.RQDecomp3x3`) of the rotation block of `facial_transformation_matrixes`.
- That matrix is expressed with the **x axis flipped** relative to the image frame. Found empirically: de-posing the landmarks with the
  matrix only balances them under the x-flipped convention (left/right imbalance 1328 -> 365 on photo A, 400 -> 63 on photo B; the other
  six axis conventions are worse).
- Camera model: neither method uses one; `z` is MediaPipe's relative depth scaled by image width (not metric). The matrix has unit scale.
- Inputs: `frontalize` uses the 478 landmarks' x, y, z and the 20 symmetry pairs; MediaPipe's pose is from its own face model fit.
- Reference frames differ: `frontalize` finds the rotation that makes THIS face's left/right distances equal (so it also absorbs the
  subject's own asymmetry and the mesh's asymmetry); MediaPipe's yaw is relative to a canonical frontal face model.

## Findings
1. **A real defect, now fixed: in-plane roll leaked into the yaw estimate.** On a symmetric synthetic face with true yaw exactly 0:
   2 deg of roll gave -7.3 deg, 5 deg gave -17.7 deg, and 10 deg saturated the search (-30.5 deg). `frontalize` ran on the raw points
   before the roll was removed. Fix: level the pupil line first. After the fix the estimate is 0.00 deg at every roll tested (0-30),
   and a true +10 deg yaw is recovered as -10.00 at rolls of 0, 5 and 20 deg. Regression-tested on exact geometry.
2. **The real-photo gap is mostly a criterion difference, not a bug.** After removing MediaPipe's pose from the landmarks, `frontalize`
   still finds +4.85 deg of residual turn on photo A, which accounts for A's whole gap; B's residual is -1.20 deg, which does not
   account for B's gap.
3. **Measured gaps (frontalize minus MediaPipe), before -> after the roll fix:** photo A -4.83 -> -5.68 deg; photo B +3.48 -> +2.63 deg.
   Same sign on both. The roll fix changed each by under 1 deg because these photos have only 0.5 and 2 deg of roll.
4. **Mirror consistency:** MediaPipe yaw is mirror-exact (0.06-0.08 deg). `frontalize` is off by 1.25 deg (A) and 0.75 deg (B) after the fix.
5. **Saturation (unchanged and explicit):** the search is +/-30 deg; beyond it the result clamps to +/-30.5 deg and can wrap to the wrong
   side (photo A, extra 35 deg -> +30.55). `status = saturated` is returned, symmetry is suppressed. Range not widened (see below).
6. **Unexplained:** why photo B's remaining gap (2.63 deg) is larger than its de-posed residual (-1.20 deg). Hypotheses not tested:
   pitch/roll coupling with the matrix's Euler decomposition, different weighting of landmarks in the two methods.

## Decisions
- **Roll-first fix: implemented** (demonstrated on exact geometry).
- **Range not widened; MediaPipe's yaw not substituted:** neither change can be demonstrated correct without ground-truth pose, so the
  conservative behaviour is kept. Beyond +/-30 deg the far side of the face is largely hidden and its landmarks are guesses.
- **Deterministic comparison tests** pin the measured relationship as regression guards, not as truth: same sign, gap under 8 deg
  (measured 2.6-5.7), mirror consistency under 2.5 deg (measured 0.75-1.25), MediaPipe mirror under 0.5 deg (measured 0.06-0.08), the
  x-flipped convention balancing the landmarks, and saturation still reported at 45 deg.

## Open
A decision between the balance criterion and MediaPipe's pose needs captured photographs with a **measured** head pose (e.g. a
motion-capture or calibrated-turntable session). Until then `frontalize` is used only for relative correction and its status is respected.
