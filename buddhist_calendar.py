"""Upcoming Buddhist observances (config/buddhist_calendar.yaml) for planning posts."""

from datetime import date, timedelta

import yaml

from project_paths import PROJECT_ROOT


CALENDAR_PATH = PROJECT_ROOT / "config" / "buddhist_calendar.yaml"
# Post a day or two before: people share teachings ahead of the day.
LEAD_DAYS = 1


def _as_date(value):
    return value if isinstance(value, date) else date.fromisoformat(str(value))


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
            "note": event.get("note", "Date is approximate; check your local calendar."),
            "idea": idea,
            "post_on": post_on.isoformat(),
            "brief": (
                f"For {event['name']} ({start.strftime('%B %-d')}). {event.get('note', '')} "
                f"Idea: {idea}"
            ).strip(),
        })
    return sorted(found, key=lambda item: item["date"])
