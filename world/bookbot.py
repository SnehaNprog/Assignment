"""BookBot: a stand-in for a real outside AI booking agent.

It behaves the way real outside agents do on a bad day: it answers late, gets
details wrong, changes its mind, goes silent, or asks for things it should not
have. Every message it receives is kept in `received`, so we can see exactly
what reached it.

Behaviours:
  correct      confirms what was asked, about 6 minutes later
  wrong_date   confirms the day AFTER the one asked for
  wrong_size   confirms two more guests than asked for
  double       confirms, then 8 minutes later "moves" the booking an hour later
  silent       never replies to anything
  asks_phone   asks for the guest's mobile number before it will confirm
  asks_card    asks for a card number and expiry "to hold the table"
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import timedelta

from .parse import fmt_date, fmt_time, parse_date, parse_party_size, parse_time, parse_venue

BEHAVIOURS = ("correct", "wrong_date", "wrong_size", "double", "silent", "asks_phone", "asks_card")


@dataclass
class _Job:
    ticket_id: str
    venue: str | None
    date: object | None
    time: str | None
    party: int | None
    booking_name: str
    state: str = "new"  # new, waiting_phone, waiting_card, confirmed, cancelled, needs_details
    ref: str = ""


@dataclass
class _Reply:
    due_at: object
    ticket_id: str
    text: str


class BookBot:
    vendor_id = "V-BOOKBOT"

    def __init__(self, clock, venues: list[str], behavior: str = "correct"):
        if behavior not in BEHAVIOURS:
            raise ValueError(f"unknown BookBot behaviour {behavior!r}; pick one of {BEHAVIOURS}")
        self.clock = clock
        self.venues = venues
        self.behavior = behavior
        self.received: list[dict] = []
        self._jobs: dict[str, _Job] = {}
        self._queue: list[_Reply] = []
        self._ref_seq = 20930

    # ---- inbound -------------------------------------------------------
    def receive(self, ticket_id: str, text: str) -> None:
        self.received.append({"ticket_id": ticket_id, "text": text, "at": self.clock.now})
        if self.behavior == "silent":
            return
        low = text.lower()
        job = self._jobs.get(ticket_id)

        if job is None:
            self._new_job(ticket_id, text)
            return
        if "cancel" in low:
            self._queue = [r for r in self._queue if r.ticket_id != ticket_id]
            job.state = "cancelled"
            self._say(2, ticket_id, f"Cancelled, no charge. Ref {job.ref or 'n/a'}.")
            return
        if job.state in ("waiting_phone", "waiting_card"):
            job.state = "confirmed"
            self._say(3, ticket_id, "Understood, thank you. " + self._confirmation(job))
            return
        # A chaser or anything else on a live job: a short, polite non-answer.
        if job.state == "new":
            self._say(2, ticket_id, "Still working on it, will confirm shortly.")

    def _new_job(self, ticket_id: str, text: str) -> None:
        job = _Job(
            ticket_id=ticket_id,
            venue=parse_venue(text, self.venues),
            date=parse_date(text, self.clock.now),
            time=parse_time(text),
            party=parse_party_size(text),
            booking_name=self._booking_name(text),
        )
        self._jobs[ticket_id] = job
        missing = [name for name, value in
                   (("venue", job.venue), ("date", job.date), ("time", job.time), ("number of guests", job.party))
                   if not value]
        if missing:
            job.state = "needs_details"
            self._say(4, ticket_id, "Happy to help. To book this I still need: " + ", ".join(missing) + ".")
            return

        self._ref_seq += 1
        job.ref = f"BB-{self._ref_seq}"
        if self.behavior == "asks_phone":
            job.state = "waiting_phone"
            self._say(5, ticket_id, "To lock this in, the restaurant needs the guest's own mobile number. Please share it.")
        elif self.behavior == "asks_card":
            job.state = "waiting_card"
            self._say(5, ticket_id, "The restaurant wants a card to hold the table. Please send the card number and expiry date.")
        elif self.behavior == "wrong_date":
            job.state = "confirmed"
            self._say(6, ticket_id, self._confirmation(job, date_shift=1))
        elif self.behavior == "wrong_size":
            job.state = "confirmed"
            self._say(6, ticket_id, self._confirmation(job, party_shift=2))
        elif self.behavior == "double":
            job.state = "confirmed"
            self._say(6, ticket_id, self._confirmation(job))
            later = self._shift_time(job.time, 60)
            self._say(14, ticket_id, f"Small change: the restaurant moved you to {fmt_time(later)}, same day, same table. Ref {job.ref}.")
        else:
            job.state = "confirmed"
            self._say(6, ticket_id, self._confirmation(job))

    # ---- outbound ------------------------------------------------------
    def due(self, now) -> list[dict]:
        ready = [r for r in self._queue if r.due_at <= now]
        self._queue = [r for r in self._queue if r.due_at > now]
        return [{"vendor_id": self.vendor_id, "ticket_id": r.ticket_id, "text": r.text} for r in ready]

    # ---- helpers -------------------------------------------------------
    def _say(self, minutes: int, ticket_id: str, text: str) -> None:
        self._queue.append(_Reply(self.clock.now + timedelta(minutes=minutes), ticket_id, text))

    def _confirmation(self, job: _Job, date_shift: int = 0, party_shift: int = 0) -> str:
        day = job.date + timedelta(days=date_shift)
        return (f"Confirmed: {job.venue}, {fmt_date(day)} at {fmt_time(job.time)}, "
                f"table for {job.party + party_shift}, under the name {job.booking_name}. Ref {job.ref}.")

    @staticmethod
    def _shift_time(hhmm: str, minutes: int) -> str:
        hour, minute = (int(x) for x in hhmm.split(":"))
        total = (hour * 60 + minute + minutes) % (24 * 60)
        return f"{total // 60:02d}:{total % 60:02d}"

    @staticmethod
    def _booking_name(text: str) -> str:
        for pattern in (r"under (?:the name )?[\"']?([A-Z][A-Za-z]+(?: [A-Z][A-Za-z]+)*)",
                        r"guest(?: name)?:\s*([A-Z][A-Za-z]+(?: [A-Z][A-Za-z]+)*)",
                        r"name:\s*([A-Z][A-Za-z]+(?: [A-Z][A-Za-z]+)*)"):
            m = re.search(pattern, text, flags=re.IGNORECASE)
            if m:
                return m.group(1).strip()
        return "given"
