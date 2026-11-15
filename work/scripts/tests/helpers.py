import datetime as dt


def stamp(day):
    """A generated value whose `at` is local noon on DAY (YYYY-MM-DD), so its local date is DAY anywhere."""
    at = dt.datetime.fromisoformat(f"{day}T12:00:00").astimezone().isoformat()
    return f"{{ by: process:work-tools, at: {at} }}"


def header(**fields):
    """Status-file text with a valid default header; pass field=None to omit one."""
    meta = {"title": "T", "state": "active", "next": "Do it", "generated": stamp("2026-10-01")}
    meta.update(fields)
    lines = ["---"] + [f"{k}: {v}" for k, v in meta.items() if v is not None]
    return "\n".join(lines + ["---", "", "## Log", ""]) + "\n"
