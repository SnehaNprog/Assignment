"""What must never reach a vendor, and the last check before anything is sent.

The guard knows every member's private details (not just the current one's),
plus generic shapes: phone numbers in any format, emails, card numbers and
expiry dates, PIN codes. The house booking identity is the only contact detail
allowed out.
"""
from __future__ import annotations

import re

_EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
# Seven or more digits, allowing to in consideration all the casses of phone number ex +91 981111 23456, 99300-44444, (022) 4000 0000
_DIGITS = re.compile(r"\+?\d[\d\s().-]{5,}\d")
_EXPIRY = re.compile(r"\b(?:0[1-9]|1[0-2])\s*/\s*(?:\d{2}|\d{4})\b")
_PINCODE = re.compile(r"\b\d{6}\b")
_CARD_WORDS = re.compile(r"\b(?:cvv|cvc|card number|card no|expiry|expiration)\b", re.I)
# "Anjali's birthday": a capitalised word used as a possessive is almost always a person. 
_POSSESSIVE = re.compile(r"\b([A-Z][a-z]{2,})'s\b")
_NOT_NAMES = {"client", "member", "guest", "today", "tomorrow", "tonight", "everyone", "nobody", "someone",
              "mom", "dad", "mum", "it", "that", "what", "there", "here", "who", "let", "year", "week"}


def _digits(text: str) -> str:
    return re.sub(r"\D", "", text)


class PrivacyGuard:
    def __init__(self, members: dict, house: dict):
        self.house = house
        self._house_digits = _digits(house.get("house_phone", ""))
        self._house_email = house.get("house_email", "").lower()
        self._allowed_words = {w.lower() for v in house.get("venues", []) for w in v.split()}
        self._allowed_words |= {w.lower() for w in house.get("booking_name", "").split()}
        # (label, value, compiled pattern) for every known private detail
        self._known: list[tuple[str, str, re.Pattern]] = []
        self._phones: list[tuple[str, str]] = []
        for m in members.values():
            people = [("member's name", m.get("name", ""))]
            people += [(f"family member's name ({f.get('relation', 'family')})", f.get("name", ""))
                       for f in m.get("family", [])]
            for label, full in people:
                if not full:
                    continue
                self._add(label, full)
                for part in full.split():
                    if part.lower() not in self._allowed_words and len(part) > 2:
                        self._add(label, part)
            if m.get("email"):
                self._add("email address", m["email"])
            if m.get("phone"):
                self._phones.append(("phone number", _digits(m["phone"])[-10:]))
            for chunk in re.split(r",", m.get("address", "")):
                chunk = chunk.strip()
                if len(chunk) >= 5 and not chunk.isdigit():
                    self._add("home address", chunk)
            card = m.get("card") or {}
            if card.get("last4"):
                self._add("card details", card["last4"])
            if card.get("expiry"):
                self._add("card details", card["expiry"])

    def _add(self, label: str, value: str) -> None:
        pattern = re.compile(r"(?<![\w])" + re.escape(value) + r"(?![\w])", re.I)
        self._known.append((label, value, pattern))

    #finding 
    def scan(self, text: str, dedupe: bool = True) -> list[tuple[str, str]]:
        """Every private-looking thing in `text`, as (what it is, the exact text)."""
        found: list[tuple[str, str]] = []
        for label, _value, pattern in self._known:
            for m in pattern.finditer(text):
                found.append((label, m.group(0)))
        for m in _EMAIL.finditer(text):
            if m.group(0).lower() != self._house_email:
                found.append(("email address", m.group(0)))
        for m in _DIGITS.finditer(text):
            digits = _digits(m.group(0))
            if len(digits) >= 7 and digits != self._house_digits and not self._house_digits.endswith(digits):
                label = "card number" if len(digits) >= 13 else "phone number"
                found.append((label, m.group(0).strip()))
        for m in _EXPIRY.finditer(text):
            found.append(("card expiry date", m.group(0)))
        for m in _PINCODE.finditer(text):
            found.append(("postal code", m.group(0)))
        for m in _CARD_WORDS.finditer(text):
            found.append(("card details", m.group(0)))
        # Known phone numbers written with odd spacing or partially
        flat = _digits(text)
        for label, phone in self._phones:
            if phone and phone in flat and not any(phone in _digits(v) for _, v in found):
                found.append((label, phone))
        return _dedupe(found) if dedupe else found

    def scan_names(self, text: str) -> list[tuple[str, str]]:
        """People mentioned by possessive ("Arjun's parents") who are not in our records."""
        return [("a person's name", m.group(1)) for m in _POSSESSIVE.finditer(text)
                if m.group(1).lower() not in self._allowed_words | _NOT_NAMES]

    def redact(self, text: str) -> tuple[str, list[str]]:
        """Free text with every private detail replaced. Returns (clean text, what was removed)."""
        findings = self.scan(text, dedupe=False) + self.scan_names(text)
        for _label, value in sorted(findings, key=lambda f: -len(f[1])):
            text = re.sub(re.escape(value), "[withheld]", text, flags=re.I)
        return text, describe(findings)


def describe(findings: list[tuple[str, str]]) -> list[str]:
    return [f"{label}: {value}" for label, value in _dedupe(findings)]


def _dedupe(items: list[tuple[str, str]]) -> list[tuple[str, str]]:
    """Drops repeats, and parts of a longer finding ("Riya" when "Riya Kapoor" is already listed)."""
    seen: list[str] = []
    out = []
    for label, value in sorted(items, key=lambda f: -len(f[1])):
        key = value.lower()
        if not any(key in s for s in seen):
            seen.append(key)
            out.append((label, value))
    return out
