"""Blink check for the guided camera: a printed photo or a still picture on a screen can't blink.

The browser records MediaPipe's eyeBlinkLeft/Right blendshape scores for the last few seconds
before capture and asks the person to blink once. Here we check that sequence for one natural
blink: both eyes open, both close together (> 0.5) for 40-800 ms, then open again. A natural
blink lasts 100-400 ms; one camera frame is ~70 ms here, so short blinks may show as one frame.

This stops casual spoofing only - a video replay or a crafted request can still pass, so it is
reported as a signal ("blink seen"), not as identity verification.
"""
from __future__ import annotations

OPEN, CLOSED = 0.35, 0.5


def check(samples: list) -> dict:
    """`samples`: [[t_ms, blink_left, blink_right], ...] in time order."""
    try:
        s = [(float(t), float(bl), float(br)) for t, bl, br in samples[-200:]]
    except (TypeError, ValueError):
        return {"checked": False, "passed": False, "reason": "unreadable"}
    if len(s) < 8:
        return {"checked": False, "passed": False, "reason": "too few frames"}
    if any(b[0] <= a[0] for a, b in zip(s, s[1:])):
        return {"checked": True, "passed": False, "reason": "timestamps out of order"}

    blinks = []
    i = 0
    while i < len(s):
        if min(s[i][1], s[i][2]) > CLOSED:  # both eyes closed
            j = i
            while j + 1 < len(s) and min(s[j + 1][1], s[j + 1][2]) > CLOSED:
                j += 1
            opened_before = i > 0 and max(s[i - 1][1], s[i - 1][2]) < OPEN
            opened_after = j + 1 < len(s) and max(s[j + 1][1], s[j + 1][2]) < OPEN
            # Duration: from the last open frame before to the first open frame after, minus one frame.
            dur = (s[j + 1][0] - s[i - 1][0]) if opened_before and opened_after else 0
            frame = (s[-1][0] - s[0][0]) / (len(s) - 1)
            if opened_before and opened_after and 40 <= dur - frame <= 800:
                blinks.append(round(dur - frame))
            i = j + 1
        else:
            i += 1
    span = s[-1][0] - s[0][0]
    return {"checked": True, "passed": bool(blinks), "blinks": len(blinks), "seconds": round(span / 1000, 1),
            "reason": None if blinks else "no blink seen"}
