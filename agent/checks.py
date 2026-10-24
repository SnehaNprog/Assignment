"""Plain-code judgements the model is not trusted with.

Reading booking details out of text, checking a vendor's confirmation against
the ticket, and spotting a vendor asking for personal details.
"""
from __future__ import annotations

import re
from datetime import date, datetime

from world.parse import parse_date, parse_party_size, parse_time, parse_venue

FIELDS = ("venue", "date", "time", "party_size")

CANCEL = re.compile(r"\bcancel|\bcall (?:it )?off\b|\bdon'?t (?:need|book)\b|\bno longer need\b|\bnahi chahiye\b", re.I)
CHANGE = re.compile(r"\b(?:change|move|push|shift|reschedule|instead|make it|prepone|postpone)\b", re.I)

# Things a vendor must never get from us. Matched only when the vendor is ASKING (see asks_for_private).
_PRIVATE_NOUNS = re.compile(
    r"\b(?:mobile|phone|cell|whatsapp|contact (?:number|details|no)|e-?mail|address|card|cvv|cvc|expiry|"
    r"credit|debit|upi|passport|aadhaa?r|pan number|id proof|full name|real name|surname|last name|"
    r"guest'?s? (?:own )?(?:name|number|details)|date of birth|dob)\b", re.I)
_ASKING = re.compile(r"\?|\b(?:please|pls|kindly|need|needs|require|requires|share|send|provide|give|"
                     r"what is|what's|can you|could you|must|before|to (?:lock|hold|confirm|secure))\b", re.I)
# "Confirmed", not "will confirm shortly"
_CONFIRM_WORDS = re.compile(r"\b(?:confirmed|booked|reserved|all set|locked in)\b", re.I)
_UNDER_NAME = re.compile(r"under (?:the name )?[\"']?([A-Za-z][A-Za-z ]*?)[\"']?(?:[.,]|$)", re.I)


def parse_details(text: str, now: datetime, venues: list[str]) -> dict:
    when = parse_date(text, now)
    return {
        "venue": parse_venue(text, venues),
        "date": when.isoformat() if when else None,
        "time": parse_time(text),
        "party_size": parse_party_size(text),
    }


def normalise(field: str, value, now: datetime, venues: list[str]):
    """Brings a model-supplied value to the ticket's format, or None if it cannot be read."""
    if value in (None, "", "null", "unknown", "TBC"):
        return None
    text = str(value).strip()
    if field == "venue":
        return parse_venue(text, venues) or text
    if field == "date":
        try:
            return date.fromisoformat(text[:10]).isoformat()
        except ValueError:
            when = parse_date(text, now)
            return when.isoformat() if when else None
    if field == "time":
        if re.fullmatch(r"\d{1,2}:\d{2}", text):
            hour, minute = text.split(":")
            return f"{int(hour):02d}:{minute}"
        return parse_time(text)
    if field == "party_size":
        if text.isdigit():
            return int(text)
        return parse_party_size(text) or parse_party_size(f"{text} people")
    return text


def asks_for_private(text: str) -> list[str]:
    """What personal details the vendor is asking for, or [] if it is not asking."""
    nouns = [m.group(0).lower() for m in _PRIVATE_NOUNS.finditer(text)]
    if not nouns:
        return []
    # A plain confirmation that mentions e.g. "under the name Indulge Concierge" is not a request.
    for sentence in re.split(r"(?<=[.!?])\s+", text):
        if _PRIVATE_NOUNS.search(sentence) and _ASKING.search(sentence):
            return sorted(set(nouns))
    return []


def looks_like_confirmation(text: str) -> bool:
    return bool(_CONFIRM_WORDS.search(text))


def verify_confirmation(ticket: dict, text: str, now: datetime, venues: list[str], booking_name: str) -> list[str]:
    """Every way the vendor's message differs from what the member asked for. [] means it matches."""
    said = parse_details(text, now, venues)
    problems = []
    for field in FIELDS:
        asked, got = ticket.get(field), said[field]
        label = field.replace("_", " ")
        if got is None:
            problems.append(f"vendor did not state the {label} (member asked for {asked})")
        elif asked is not None and str(got).lower() != str(asked).lower():
            problems.append(f"{label}: member asked for {asked}, vendor said {got}")
    name = _UNDER_NAME.search(text)
    if name and name.group(1).strip().lower() != booking_name.lower():
        problems.append(f"booked under '{name.group(1).strip()}', not the house name {booking_name}")
    return problems
