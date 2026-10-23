"""The only way a message leaves the building.

`Transport.sent` is the ground truth of everything any vendor ever received.
Our tests read it. If something private is in there, it leaked.
"""
from __future__ import annotations

from datetime import datetime


class TransportTimeout(Exception):
    """The send may or may not have been delivered. You cannot tell from here."""


class Transport:
    def __init__(self, clock, bookbot, flaky: bool = False):
        self.clock = clock
        self.bookbot = bookbot
        self.flaky = flaky
        self.sent: list[dict] = []
        self._by_key: dict[str, dict] = {}
        self._seq = 0
        self._flaked = False

    def send(self, vendor_id: str, ticket_id: str, text: str, idempotency_key: str | None = None) -> dict:
        """Deliver `text` to a vendor on the thread for `ticket_id`.

        If `idempotency_key` was used before, the earlier receipt is returned and
        nothing is delivered again.

        In flaky mode the FIRST send is delivered and then raises TransportTimeout,
        exactly like a real network that drops the acknowledgement.
        """
        if idempotency_key and idempotency_key in self._by_key:
            return self._by_key[idempotency_key]

        self._seq += 1
        receipt = {
            "message_id": f"OUT-{self._seq:04d}",
            "vendor_id": vendor_id,
            "ticket_id": ticket_id,
            "text": text,
            "at": self.clock.now,
            "idempotency_key": idempotency_key,
        }
        self.sent.append(receipt)
        if idempotency_key:
            self._by_key[idempotency_key] = receipt
        if vendor_id == "V-BOOKBOT":
            self.bookbot.receive(ticket_id, text)

        if self.flaky and not self._flaked:
            self._flaked = True
            raise TransportTimeout("message sent, but no acknowledgement came back (network timeout)")
        return receipt

    def sent_to(self, vendor_id: str) -> list[dict]:
        return [m for m in self.sent if m["vendor_id"] == vendor_id]

    def at(self) -> datetime:
        return self.clock.now
