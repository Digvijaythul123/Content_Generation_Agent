"""Upcoming Buddhist observances (config/buddhist_calendar.yaml) for planning posts."""

from datetime import date, timedelta

import yaml

from project_paths import PROJECT_ROOT


CALENDAR_PATH = PROJECT_ROOT / "config" / "buddhist_calendar.yaml"
# Post a day or two before: people share teachings ahead of the day.
LEAD_DAYS = 1
UPOSATHA_NOTE = (
    "The full moon Uposatha is a Buddhist observance day: many Buddhists keep "
    "extra precepts (often eight), visit a temple, listen to teachings, give, "
    "and meditate."
)


def _as_date(value):
    return value if isinstance(value, date) else date.fromisoformat(str(value))


def occasion_brief(name, start, end, note, idea):
    """A brief that makes the post about the day and makes people aware of it."""
    when = start.strftime("%A, %B %-d")
    if end != start:
        when += f" to {end.strftime('%B %-d')}"
    return (
        f"Occasion: {name} ({when}).\n"
        f"What it is: {note}\n"
        "Make this post about this day and help people become aware of it: "
        "name the day in the first on-screen line (for example "
        "\"Tomorrow is the full moon\"), explain in plain words what it is and "
        "why it matters, and give one simple way to observe it today. "
        f"Teaching to use: {idea}"
    )


def upcoming(today=None, days=45, path=CALENDAR_PATH):
    """Observances starting (or still running) within the next ``days``."""
    today = today or date.today()
    try:
        events = (yaml.safe_load(path.read_text(encoding="utf-8")) or {}).get("events", [])
    except (OSError, yaml.YAMLError):
        return []
    found = []
    for event in events:
        start = _as_date(event["date"])
        end = _as_date(event.get("end", start))
        if end < today or start > today + timedelta(days=days):
            continue
        kind = event.get("kind", "festival")
        idea = event.get("idea") or (
            "A short teaching to keep on the full moon (Uposatha): the Five "
            "Precepts, a few minutes of meditation, or one line from the Dhammapada."
            if kind == "uposatha" else ""
        )
        post_on = max(today, start - timedelta(days=LEAD_DAYS))
        found.append({
            "name": event["name"],
            "kind": kind,
            "date": start.isoformat(),
            "end": end.isoformat() if end != start else None,
            "note": event.get("note") or (UPOSATHA_NOTE if kind == "uposatha" else "Date is approximate; check your local calendar."),
            "idea": idea,
            "post_on": post_on.isoformat(),
            "brief": occasion_brief(event["name"], start, end,
                                    event.get("note") or (UPOSATHA_NOTE if kind == "uposatha" else ""), idea),
        })
    return sorted(found, key=lambda item: item["date"])
