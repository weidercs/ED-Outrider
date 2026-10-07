"""Small helpers shared by ed_outrider.py and the outrider modules (no dependencies of their own)."""
import time


def ts_seconds(ts):
    """Journal timestamp ('2026-09-28T02:06:56Z') -> seconds since the epoch (UTC)."""
    import calendar
    return calendar.timegm(time.strptime(ts[:19], "%Y-%m-%dT%H:%M:%S"))


def iso_ts(t):
    """time.time() -> a journal-style UTC timestamp. A time before 1970 (a "since" many years back) reads as 1970:
    Windows' gmtime refuses a negative one, and no journal is that old."""
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(max(0, t)))
