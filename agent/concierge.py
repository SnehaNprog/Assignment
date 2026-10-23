"""YOUR CODE GOES HERE.

Build the concierge agent from scratch: the model loop, the tools, the safety
rules, the state. Split it into as many files inside `agent/` as you like.

The only thing we require is this class and these method names and return
shapes, because play.py and our review drive your agent through them.
"""
from __future__ import annotations


class Concierge:
    def __init__(self, world, client, model: str = "claude-haiku-5-5"):
        """`client` is FakeAnthropic(...) or anthropic.Anthropic(). Same interface."""
        self.world = world
        self.client = client
        self.model = model

    # ---- the world calls these -------------------------------------------
    def on_group_message(self, group_id: str, member_id: str, sender: str, text: str, message_id: str) -> None:
        """A member wrote in their WhatsApp group."""
        raise NotImplementedError

    def on_vendor_reply(self, vendor_id: str, ticket_id: str, text: str, message_id: str) -> None:
        """A vendor answered on the thread of `ticket_id`."""
        raise NotImplementedError

    def tick(self) -> None:
        """Called once every fake minute. Use it for timers and follow-ups."""
        raise NotImplementedError

    # ---- a human (or our review) calls these -----------------------------
    def pending_proposals(self) -> list[dict]:
        """Jobs waiting for a human. Each item:
        {"proposal_id": str, "ticket_id": str, "vendor_id": str,
         "outbound_message": str,   # EXACTLY what will be sent if approved
         "held_back": list[str]}    # what you removed or refused to send, in plain words
        """
        raise NotImplementedError

    def approve(self, proposal_id: str, approver: str) -> dict:
        """A human approved. Send it (once). Return a small dict describing what happened."""
        raise NotImplementedError

    def tickets(self) -> list[dict]:
        """Each item at least: {"ticket_id", "member_id", "status", "venue", "date", "time", "party_size"}.
        status is one of: open, needs_info, awaiting_approval, sent, confirmed, needs_human, cancelled
        """
        raise NotImplementedError

    def alerts(self) -> list[dict]:
        """Things a human must look at. Each item at least: {"ticket_id", "reason"}."""
        raise NotImplementedError

    def usage(self) -> dict:
        """Model usage so far: {"calls", "input_tokens", "output_tokens", "cost_usd"}."""
        raise NotImplementedError
