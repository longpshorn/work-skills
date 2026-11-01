def header(**fields):
    """Status-file text with a valid default header; pass field=None to omit one."""
    meta = {"title": "T", "state": "active", "next": "Do it", "updated": "2026-10-01"}
    meta.update(fields)
    lines = ["---"] + [f"{k}: {v}" for k, v in meta.items() if v is not None]
    return "\n".join(lines + ["---", "", "## Log", ""]) + "\n"
