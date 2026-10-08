import re
from datetime import datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

_ISO = re.compile(r"^P(?:(\d+)D)?(?:T(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?)?$")


def parse_duration(s: str) -> timedelta:
    m = _ISO.match(s or "")
    if not m or not any(m.groups()):
        raise ValueError(f"bad ISO-8601 duration: {s!r}")
    d, h, mi, sec = (int(g or 0) for g in m.groups())
    return timedelta(days=d, hours=h, minutes=mi, seconds=sec)


def utc(dt: datetime) -> datetime:
    """SQLite hands back naive datetimes; everything we store is UTC."""
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt.astimezone(timezone.utc)


def next_window_start(now: datetime, window: dict | None) -> datetime | None:
    """None if `now` is inside the call window, else the next window start (UTC).
    Deferred, never skipped. Always real time: time_scale does not apply here."""
    if not window:
        return None
    tz = ZoneInfo(window["tz"])
    start = time.fromisoformat(window["start"])
    end = time.fromisoformat(window["end"])
    local = utc(now).astimezone(tz)
    if start <= local.time() < end:
        return None
    day = local.date() if local.time() < start else local.date() + timedelta(days=1)
    return datetime.combine(day, start, tzinfo=tz).astimezone(timezone.utc)
