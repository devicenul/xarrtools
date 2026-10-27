"""Background scheduler calculation helpers and validation for xarrtools.

Provides pure, testable scheduling math:
- validate_time_of_day: ensures optional HH:MM format (00:00 - 23:59).
- parse_time_of_day: parses HH:MM into (hour, minute).
- compute_next_run: calculates the next scheduled execution datetime (UTC-aware; time of day is local).
- is_due: determines whether a scheduled refresh should run given last_run, interval, time_of_day, and now.
"""
from datetime import date, datetime, timedelta, timezone, tzinfo
import re
from typing import Optional, Pattern, Tuple, Union

TIME_OF_DAY_REGEX: Pattern[str] = re.compile(r"^([01]\d|2[0-3]):([0-5]\d)$")


def validate_time_of_day(val: Optional[str]) -> bool:
    """Validates that val is either empty/None or a valid 24h 'HH:MM' string (00:00 - 23:59)."""
    if val is None:
        return True
    if not isinstance(val, str):
        return False
    s = val.strip()
    if not s:
        return True
    return bool(TIME_OF_DAY_REGEX.match(s))


def parse_time_of_day(val: Optional[str]) -> Optional[Tuple[int, int]]:
    """Parses a valid 'HH:MM' string into (hour, minute). Returns None if empty/None. Raises ValueError if invalid."""
    if val is None:
        return None
    if not isinstance(val, str):
        raise ValueError(f"Invalid time_of_day '{val}', expected 'HH:MM' string")
    s = val.strip()
    if not s:
        return None
    match = TIME_OF_DAY_REGEX.match(s)
    if not match:
        raise ValueError(f"Invalid time_of_day '{val}', expected 'HH:MM' (00:00 - 23:59)")
    return int(match.group(1)), int(match.group(2))


def _to_utc_datetime(dt: Optional[Union[datetime, str]]) -> Optional[datetime]:
    """Converts a datetime or ISO string to a timezone-aware UTC datetime."""
    if dt is None:
        return None
    if isinstance(dt, str):
        s = dt.strip()
        if not s:
            return None
        parsed = datetime.fromisoformat(s.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    if isinstance(dt, datetime):
        if dt.tzinfo is None:
            return dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    raise TypeError(f"Expected datetime, ISO string or None, got {type(dt)}")


def _local_candidate(day: Union[date, datetime], h: int, m: int, tz: Optional[tzinfo]) -> datetime:
    """Returns the UTC-aware instant of wall-clock h:m on `day` in `tz` (system local zone if None)."""
    naive = datetime(day.year, day.month, day.day, h, m, 0)
    if tz is None:
        return naive.astimezone(timezone.utc)  # naive -> interpreted as system local time
    return naive.replace(tzinfo=tz).astimezone(timezone.utc)


def compute_next_run(
    last_run: Optional[Union[datetime, str]],
    interval_hours: int,
    time_of_day: Optional[str] = None,
    now: Optional[datetime] = None,
    tz: Optional[tzinfo] = None,
) -> datetime:
    """Computes the next execution timestamp (UTC timezone-aware).

    Args:
        last_run: When the scheduler last ran (datetime, ISO string, or None if never).
        interval_hours: Refresh interval in hours, clamped between 1 and 168.
        time_of_day: Optional 'HH:MM' wall-clock target in LOCAL time (`tz`, default system zone).
        now: Current time (defaults to datetime.now(timezone.utc)).
        tz: Timezone used to interpret time_of_day (defaults to the system local timezone).
    """
    interval_hours = max(1, min(168, int(interval_hours)))
    current = _to_utc_datetime(now) if now is not None else datetime.now(timezone.utc)
    if current is None:
        current = datetime.now(timezone.utc)
    last = _to_utc_datetime(last_run)

    has_tod = validate_time_of_day(time_of_day) and bool(time_of_day and time_of_day.strip())

    if not has_tod:
        # Interval-only scheduling
        if last is None:
            return current + timedelta(hours=interval_hours)
        return last + timedelta(hours=interval_hours)

    # Time-of-day scheduling (daily at HH:MM local time)
    tod_parsed = parse_time_of_day(time_of_day)
    assert tod_parsed is not None
    h, m = tod_parsed

    day = current.astimezone(tz).date() if tz is not None else current.astimezone().date()
    candidate = _local_candidate(day, h, m, tz)

    while candidate <= current or (last is not None and candidate <= last):
        day = day + timedelta(days=1)
        candidate = _local_candidate(day, h, m, tz)
    return candidate


def is_due(
    last_run: Optional[Union[datetime, str]],
    interval_hours: int,
    time_of_day: Optional[str] = None,
    now: Optional[datetime] = None,
    startup_time: Optional[datetime] = None,
    startup_delay_seconds: int = 60,
    enabled: bool = True,
) -> bool:
    """Determines whether a scheduled refresh is due to run.

    Restart behavior:
    - If enabled is False, returns False.
    - If last_run is present, it is only due when now >= compute_next_run(...) (not immediately on restart).
    - If last_run is None (never run before) and startup_time is provided, it is due only after startup_delay_seconds.
    """
    if not enabled:
        return False

    current = _to_utc_datetime(now) if now is not None else datetime.now(timezone.utc)
    if current is None:
        current = datetime.now(timezone.utc)
    last = _to_utc_datetime(last_run)

    if last is None:
        if startup_time is not None:
            start_utc = _to_utc_datetime(startup_time)
            assert start_utc is not None
            return current >= start_utc + timedelta(seconds=startup_delay_seconds)
        return True

    next_run = compute_next_run(last, interval_hours, time_of_day, current)
    return current >= next_run
