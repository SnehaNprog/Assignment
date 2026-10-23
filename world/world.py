"""The simulated company your concierge agent lives in.

    world = World(bookbot="correct")
    concierge = Concierge(world, client)     # you write Concierge
    world.attach(concierge)
    world.member_says("G-101", "Book Koen for Saturday 8pm, 4 of us")
    for p in concierge.pending_proposals():
        concierge.approve(p["proposal_id"], approver="nisha")
    world.advance(30)                         # 30 fake minutes pass

The world calls your Concierge when something happens:
    on_group_message(...)   a member wrote in their WhatsApp group
    on_vendor_reply(...)    a vendor (BookBot) answered on a ticket thread
    tick()                  once every fake minute, for timers and follow-ups
"""
from __future__ import annotations

from .bookbot import BookBot
from .clock import Clock
from .data import load_data
from .transport import Transport


class World:
    def __init__(self, bookbot: str = "correct", flaky: bool = False):
        self.clock = Clock()
        self.data = load_data()
        self.bookbot = BookBot(self.clock, self.data.house["venues"], behavior=bookbot)
        self.transport = Transport(self.clock, self.bookbot, flaky=flaky)
        self.concierge = None
        self.log: list[dict] = []  # a readable trace of everything that happened
        self._in_seq = 0

    def attach(self, concierge) -> None:
        self.concierge = concierge

    # ---- things that happen to the company ----------------------------
    def member_says(self, group_id: str, text: str, message_id: str | None = None, sender: str | None = None) -> str:
        group = self.data.groups[group_id]
        member = self.data.members[group["member_id"]]
        if message_id is None:
            self._in_seq += 1
            message_id = f"IN-{self._in_seq:04d}"
        sender = sender or member["name"]
        self.log.append({"at": self.clock.now, "kind": "member", "group_id": group_id, "sender": sender, "text": text})
        self.concierge.on_group_message(group_id=group_id, member_id=member["member_id"], sender=sender,
                                        text=text, message_id=message_id)
        return message_id

    def advance(self, minutes: int) -> None:
        """Let fake time pass, one minute at a time."""
        for _ in range(minutes):
            self.clock.advance(1)
            for reply in self.bookbot.due(self.clock.now):
                self._in_seq += 1
                self.log.append({"at": self.clock.now, "kind": "vendor_reply", **reply})
                self.concierge.on_vendor_reply(vendor_id=reply["vendor_id"], ticket_id=reply["ticket_id"],
                                               text=reply["text"], message_id=f"VR-{self._in_seq:04d}")
            self.concierge.tick()

    # ---- helpers for the agent ----------------------------------------
    def send_to_vendor(self, vendor_id: str, ticket_id: str, text: str, idempotency_key: str | None = None) -> dict:
        """The ONLY way to message a vendor. May raise transport.TransportTimeout."""
        before = len(self.transport.sent)
        try:
            return self.transport.send(vendor_id, ticket_id, text, idempotency_key=idempotency_key)
        finally:
            for out in self.transport.sent[before:]:
                self.log.append({"at": self.clock.now, "kind": "sent", "vendor_id": vendor_id,
                                 "ticket_id": ticket_id, "text": out["text"]})
