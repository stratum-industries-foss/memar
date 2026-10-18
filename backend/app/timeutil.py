"""Naive-UTC timestamps.

datetime.utcnow() is deprecated (Python 3.12+) and scheduled for removal. The
database and APIs store naive UTC datetimes, so this returns exactly what
utcnow() returned: the current UTC time without tzinfo.
"""
from datetime import datetime, timezone


def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)
