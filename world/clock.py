"""A fake clock, so "BookBot was silent for 45 minutes" takes milliseconds to test."""
from __future__ import annotations

from datetime import datetime, timedelta

# Monday 2 November 2026, 10:00 (India time). Every scenario starts here.
START = datetime(2026, 11, 2, 10, 0)


class Clock:
    def __init__(self, start: datetime = START):
        self.now = start

    def advance(self, minutes: int = 1) -> datetime:
        self.now = self.now + timedelta(minutes=minutes)
        return self.now

    def minutes_since(self, then: datetime) -> float:
        return (self.now - then).total_seconds() / 60.0
