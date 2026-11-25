"""Glow-up countdown for a wedding, festival or other big day.

Turns the event date into a dated, week-by-week plan. Milestones already in the past are
dropped; very close events get a short "quick glow" plan instead.
"""
from __future__ import annotations

from datetime import date, timedelta

EVENT_TYPES = {
    "own_wedding": "Your wedding",
    "family_wedding": "A family wedding",
    "festival": "Festival",
    "other": "Big day",
}

# (days_before, title, who, needs) - who: all | bride | groom | wedding ; needs: optional skin concern key
MILESTONES = [
    (112, "Start your routine", "all", None,
     "Begin the AM/PM routine from your report. Add one active at a time, two weeks apart."),
    (112, "See a dermatologist for stubborn concerns", "all", "medical",
     "Acne or pigmentation that hasn't improved needs 3+ months of supervised treatment - start now."),
    (112, "Sleep, water and movement", "all", None,
     "7-8 hours of sleep and regular exercise show in your skin within weeks."),
    (84, "Book your trials", "wedding", None,
     "Shortlist and book trials with your makeup artist / salon and stylist."),
    (84, "Add your second active", "all", None,
     "If your skin is happy, add the next step from your routine (e.g. a night active)."),
    (56, "Professional treatment window", "all", None,
     "Peels, hydrafacials or laser only on a dermatologist's advice - this is the last safe window for anything strong."),
    (56, "Dental cleaning", "wedding", None, "Cleaning or whitening now leaves time for any sensitivity to settle."),
    (42, "Test hair colour or treatments", "all", None,
     "Try any new colour, keratin or smoothening now, never in the last month."),
    (42, "Makeup trial with your skin prep", "bride", None,
     "Do the trial with your real routine underneath and check how your sunscreen sits under makeup."),
    (28, "Last facial, peel or wax test", "all", None,
     "Final professional facial or peel. Patch-test any new waxing or salon product."),
    (28, "Freeze your routine", "all", None,
     "No new products from today - stick with what your skin already likes."),
    (21, "Decide haircut and beard shape", "groom", None,
     "Lock the hairstyle and beard shape with your barber and start growing to length."),
    (21, "Body polish - first round", "bride", None, "Gentle body polish now, second round in the final week."),
    (14, "Plan threading and waxing dates", "all", None,
     "Schedule hair removal so the last session is 2-3 days before, never the day before."),
    (14, "Hydration focus", "all", None, "Sheet masks or a hydrating serum 2-3 times a week; cut back on salt and alcohol."),
    (10, "Haircut", "groom", None, "Final haircut 7-10 days before so it settles."),
    (5, "Brows shaped", "all", None, "Brows threaded or shaped 3-5 days before - redness has time to fade."),
    (3, "Manicure and pedicure", "all", None, "Hands and feet are in every photo."),
    (2, "Mehendi", "bride", None, "1-2 days before so the colour peaks on the day."),
    (1, "Beard line-up", "groom", None, "Clean line-up the day before; trim neckline a finger-width above the Adam's apple."),
    (1, "Early night", "all", None, "No new products, no alcohol, 8 hours of sleep."),
    (0, "On the day", "all", None,
     "Gentle cleanse, hydrating serum, moisturiser, SPF 50, then primer. Carry blotting papers and reapply SPF if outdoors."),
]

QUICK_GLOW = [
    (0, "Quick glow plan", "Your event is close, so skip new actives and peels. Focus on: gentle cleanse, "
        "moisturiser, SPF 50 daily, hydrating sheet masks, cold compress for puffy eyes, 8 hours of sleep, "
        "and less salt and alcohol."),
]


def build(event: dict | None, profile: dict, skin: dict, today: date | None = None) -> dict | None:
    if not event or not event.get("date"):
        return None
    try:
        day = date.fromisoformat(event["date"])
    except ValueError:
        return None
    today = today or date.today()
    days_left = (day - today).days
    if days_left < 0:
        return None
    kind = event.get("type") if event.get("type") in EVENT_TYPES else "other"
    wedding = kind in ("own_wedding", "family_wedding")
    sex = (profile.get("sex") or "").lower()
    concerns = {c["key"]: c["score"] for c in skin.get("concerns", [])} if skin.get("available") else {}
    medical = any(concerns.get(k, 100) < 60 for k in ("blemishes", "pigmentation", "acne_marks"))

    def applies(who: str, needs: str | None) -> bool:
        if needs == "medical" and not medical:
            return False
        if who == "all":
            return True
        if who == "wedding":
            return wedding
        if who == "bride":
            return kind == "own_wedding" and sex.startswith("f")
        if who == "groom":
            return kind == "own_wedding" and sex.startswith("m")
        return False

    phases: dict[int, dict] = {}
    if days_left < 14:
        for before, title, detail in QUICK_GLOW:
            phases[before] = {"date": day.isoformat(), "items": [{"title": title, "detail": detail}]}
    else:
        for before, title, who, needs, detail in MILESTONES:
            if not applies(who, needs):
                continue
            if before == 112 or before > days_left:
                # Foundational steps (and booking trials) start today; other passed windows are skipped.
                if before != 112 and title != "Book your trials":
                    continue
                before = days_left
            when = day - timedelta(days=before)
            phases.setdefault(before, {"date": when.isoformat(), "items": []})["items"].append({"title": title, "detail": detail})

    ordered = [dict(days_before=k, **v) for k, v in sorted(phases.items(), reverse=True)]
    return {
        "type": kind,
        "label": EVENT_TYPES[kind],
        "date": day.isoformat(),
        "days_left": days_left,
        "phases": ordered,
    }
