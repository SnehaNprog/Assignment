"""Small, deliberately simple text parsers shared by BookBot and the fake model.

You may use these in your own solution, but you do not have to. They are not
perfect (real messages never are), and that is part of the job.
"""
from __future__ import annotations

import re
from datetime import date, datetime, timedelta

WORD_NUMBERS = {
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6,
    "seven": 7, "eight": 8, "nine": 9, "ten": 10, "eleven": 11, "twelve": 12,
    "do": 2, "teen": 3, "char": 4, "paanch": 5,
}
WEEKDAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
MONTHS = ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"]

_NUM = r"(\d{1,2}|" + "|".join(WORD_NUMBERS) + r")"


def _to_int(token: str) -> int:
    token = token.lower()
    return int(token) if token.isdigit() else WORD_NUMBERS[token]


def parse_party_size(text: str) -> int | None:
    low = text.lower()
    patterns = [
        r"table for " + _NUM + r"\b",
        r"\b" + _NUM + r"\s*(?:people|persons|pax|guests|adults|of us|log|logon|logo)\b",
        r"\bfor " + _NUM + r"\b(?!\s*(?:am|pm|baje|:))",
    ]
    for pattern in patterns:
        m = re.search(pattern, low)
        if m:
            return _to_int(m.group(1))
    return None


def parse_time(text: str) -> str | None:
    """Returns "HH:MM" (24 hour) or None."""
    low = text.lower()
    m = re.search(r"\b(\d{1,2})(?:[:.](\d{2}))?\s*(am|pm)\b", low)
    if m:
        hour, minute = int(m.group(1)) % 12, int(m.group(2) or 0)
        if m.group(3) == "pm":
            hour += 12
        return f"{hour:02d}:{minute:02d}"
    m = re.search(r"\b(\d{1,2})(?::(\d{2}))?\s*baje\b", low)
    if m:
        hour, minute = int(m.group(1)), int(m.group(2) or 0)
        if hour < 12 and hour >= 5:
            hour += 12
        return f"{hour:02d}:{minute:02d}"
    m = re.search(r"\b([01]?\d|2[0-3]):([0-5]\d)\b", low)
    if m:
        return f"{int(m.group(1)):02d}:{m.group(2)}"
    if "lunch" in low:
        return None
    return None


def parse_date(text: str, now: datetime) -> date | None:
    """Understands ISO dates, "7 Nov", "today", "tomorrow" and weekday names.

    Vague words like "weekend" or "soon" return None on purpose.
    """
    low = text.lower()
    m = re.search(r"\b(20\d{2})-(\d{2})-(\d{2})\b", low)
    if m:
        return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    m = re.search(r"\b(\d{1,2})\s*(" + "|".join(MONTHS) + r")[a-z]*\b", low)
    if m:
        day, month = int(m.group(1)), MONTHS.index(m.group(2)) + 1
        year = now.year if month >= now.month else now.year + 1
        return date(year, month, day)
    today = now.date()
    if re.search(r"\btoday\b|\btonight\b|\baaj\b", low):
        return today
    if re.search(r"\btomorrow\b", low):
        return today + timedelta(days=1)
    for index, name in enumerate(WEEKDAYS):
        if re.search(r"\b" + name + r"\b", low) or re.search(r"\b" + name[:3] + r"\b", low):
            ahead = (index - today.weekday()) % 7
            return today + timedelta(days=ahead or 7)
    return None


def parse_venue(text: str, venues: list[str]) -> str | None:
    low = text.lower()
    for venue in venues:
        if venue.lower() in low:
            return venue
    return None


def fmt_date(d: date) -> str:
    return f"{d:%a} {d.day} {d:%b %Y}"


def fmt_time(hhmm: str) -> str:
    hour, minute = (int(x) for x in hhmm.split(":"))
    suffix = "pm" if hour >= 12 else "am"
    hour12 = hour % 12 or 12
    return f"{hour12}:{minute:02d} {suffix}"
