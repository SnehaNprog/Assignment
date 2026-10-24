"""The concierge agent: our own model loop, tools, state and safety rules.

How the safety rules are held, in code rather than by the model:
  1. Nothing private leaves: the model never sees private member fields, every
     vendor message is built from ticket fields (outbound.py), and `_send` scans
     the final text against every member's details before it goes.
  2. Human approval: `propose_job` only stores a proposal; `approve` sends it.
  3. Exactly once: one job proposal per ticket, identical tickets reused,
     duplicate events dropped, and every send carries a fixed idempotency key.
  4. Verify: a confirmation is compared field by field with the ticket.
  5. Silence: `tick` reminds once, then hands the ticket to a person.
  6. Unsure: vague requests, cancellations, changes and vendors asking for
     personal details all raise an alert for a person.
"""
from __future__ import annotations

import json
import re
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime

from world.events import render_group_message, render_vendor_reply
from world.pricing import cost_usd
from world.transport import TransportTimeout

from . import checks, outbound
from .gate import is_request
from .privacy import PrivacyGuard, describe
from .tools import SYSTEM, TOOLS

REMIND_AFTER = 30       # minutes of vendor silence before the one reminder
ESCALATE_AFTER = 30     # further minutes of silence before a person takes over
DUPLICATE_WINDOW = 10   # minutes in which the same text from the same sender counts as a repeat
MAX_STEPS = 8           # model turns per event
MAX_SEND_ATTEMPTS = 3   # the transport may time out; retries reuse the idempotency key

LIVE = ("open", "needs_info", "awaiting_approval", "sent", "confirmed", "needs_human")
TOOL_NAMES = {t["name"] for t in TOOLS}


@dataclass
class Ticket:
    ticket_id: str
    member_id: str
    category: str
    request_summary: str
    venue: str | None
    date: str | None          # YYYY-MM-DD
    time: str | None          # HH:MM
    party_size: int | None
    status: str = "open"
    extras: list[str] = field(default_factory=list)
    vendor_id: str | None = None
    source_text: str = ""
    notes: list[str] = field(default_factory=list)
    last_activity: datetime | None = None   # when we sent the job, or the vendor last wrote
    reminded_at: datetime | None = None
    cancel_sent: bool = False


@dataclass
class Proposal:
    proposal_id: str
    ticket_id: str
    vendor_id: str
    outbound_message: str
    held_back: list[str]
    kind: str                 # "job" (first message) or "follow_up"
    state: str = "pending"    # pending, sending, sent, void, blocked
    approver: str | None = None
    receipt: dict | None = None


class Concierge:
    def __init__(self, world, client, model: str = "claude-haiku-5-5", prefilter: bool = True):
        """`client` is FakeAnthropic(...) or anthropic.Anthropic(). Same interface.

        prefilter: skip the model for messages the small classifier calls chatter.
        """
        self.world = world
        self.client = client
        self.model = model
        self.prefilter = prefilter
        self.house = world.data.house
        self.venues = self.house["venues"]
        self.guard = PrivacyGuard(world.data.members, self.house)
        self._tickets: dict[str, Ticket] = {}
        self._proposals: dict[str, Proposal] = {}
        self._alerts: list[dict] = []
        self._seen_ids: set[str] = set()
        self._recent: dict[tuple, datetime] = {}
        self._sent_keys: dict[str, dict] = {}
        self._event: dict = {}
        self._usage = {"calls": 0, "input_tokens": 0, "output_tokens": 0, "cache_read_input_tokens": 0,
                       "cost_usd": 0.0, "model_seconds": 0.0, "skipped_by_prefilter": 0}

    @property
    def now(self) -> datetime:
        return self.world.clock.now

    # ---- the world calls these -------------------------------------------
    def on_group_message(self, group_id: str, member_id: str, sender: str, text: str, message_id: str) -> None:
        """A member wrote in their WhatsApp group."""
        if self._is_repeat(message_id, ("group", group_id, sender, text.strip().lower())):
            return
        cancelling = bool(checks.CANCEL.search(text))
        if self.prefilter and not cancelling and not is_request(text):
            self._usage["skipped_by_prefilter"] += 1
            return
        self._event = {"kind": "group_message", "member_id": member_id, "text": text, "created": [], "cancelled": []}
        prompt = render_group_message(group_id, member_id, sender, text) + "\n---\n" + self._member_context(member_id)
        if not self._run(prompt):
            self._alert(None, f"Could not process a message from {sender} in {group_id}; please read it: {text!r}")
        self._after_group_message(member_id, text, cancelling)

    def on_vendor_reply(self, vendor_id: str, ticket_id: str, text: str, message_id: str) -> None:
        """A vendor answered on the thread of `ticket_id`."""
        if self._is_repeat(message_id, ("vendor", vendor_id, ticket_id, text.strip().lower())):
            return
        t = self._tickets.get(ticket_id)
        if t is None:
            self._alert(None, f"{vendor_id} wrote about a ticket we do not know ({ticket_id}): {text!r}")
            return
        if vendor_id != t.vendor_id:
            self._alert(t.ticket_id, f"{vendor_id} wrote on a ticket that was given to {t.vendor_id}; ignored: {text!r}")
            return
        t.last_activity = self.now
        t.notes.append(f"vendor said: {text}")

        # Decided in code, without the model:
        if t.status == "cancelled":
            if not t.cancel_sent:
                self._alert(t.ticket_id, f"Vendor wrote on a cancelled ticket: {text!r}")
            return
        asked = checks.asks_for_private(text)
        if asked:
            self._escalate(t, f"Vendor asked for personal details ({', '.join(asked)}). Nothing was shared. "
                              f"A person should reply, for example with the house contact {self.house['house_phone']}.")
            return
        if t.status == "confirmed":
            self._escalate(t, f"Vendor wrote again after confirming; check it before telling the member: {text!r}")
            return
        if t.status != "sent":
            self._alert(t.ticket_id, f"New vendor message while a person handles this ticket: {text!r}")
            return

        self._event = {"kind": "vendor_reply", "member_id": t.member_id, "ticket_id": t.ticket_id, "text": text}
        prompt = render_vendor_reply(vendor_id, ticket_id, t.member_id, text) + "\n---\n" + self._ticket_context(t)
        self._run(prompt)
        if t.status == "sent":  # the model left it as it was; make sure nothing important is ignored
            if checks.looks_like_confirmation(text):
                self._confirm(t, text)
            elif checks.CANCEL.search(text):
                self._escalate(t, f"Vendor says the booking is cancelled: {text!r}")
            elif re.search(r"\?|\bneed|\bunable\b|\bcannot\b|\bcan'?t\b|\bnot available\b|\bfully booked\b|\bsorry\b", text, re.I):
                self._escalate(t, f"Vendor needs something or cannot do it: {text!r}")

    def tick(self) -> None:
        """Called once every fake minute. Use it for timers and follow-ups."""
        for t in list(self._tickets.values()):
            if t.status != "sent" or t.last_activity is None:
                continue
            if t.reminded_at is None:
                if self.world.clock.minutes_since(t.last_activity) >= REMIND_AFTER:
                    t.reminded_at = self.now
                    self._send(t, t.vendor_id, outbound.reminder_message(asdict(t), self.house["booking_name"]),
                               key=f"reminder:{t.ticket_id}")
                    t.notes.append("sent the one reminder")
            elif self.world.clock.minutes_since(max(t.reminded_at, t.last_activity)) >= ESCALATE_AFTER:
                quiet = int(self.world.clock.minutes_since(t.last_activity))
                self._escalate(t, f"Vendor silent for {quiet} minutes, including {ESCALATE_AFTER} after one reminder. "
                                  "A person should chase by phone or try another vendor.")

    # ---- a human (or our review) calls these -----------------------------
    def pending_proposals(self) -> list[dict]:
        """Jobs waiting for a human."""
        return [{"proposal_id": p.proposal_id, "ticket_id": p.ticket_id, "vendor_id": p.vendor_id,
                 "outbound_message": p.outbound_message, "held_back": list(p.held_back)}
                for p in self._proposals.values() if self._is_pending(p)]

    def approve(self, proposal_id: str, approver: str) -> dict:
        """A human approved. Send it (once). Return a small dict describing what happened."""
        p = self._proposals.get(proposal_id)
        if p is None:
            return {"ok": False, "error": f"unknown proposal {proposal_id}"}
        if p.state in ("sending", "sent"):
            return {"ok": True, "status": "already_sent", "proposal_id": proposal_id,
                    "message_id": (p.receipt or {}).get("message_id"), "approver": p.approver}
        if not self._is_pending(p):
            ticket = self._tickets[p.ticket_id]
            if p.state == "pending" and ticket.status == "cancelled":
                p.state = "void"
            return {"ok": False, "status": p.state, "error": f"ticket {ticket.ticket_id} is {ticket.status}; nothing sent"}
        if not approver:
            return {"ok": False, "error": "an approver name is required"}

        t = self._tickets[p.ticket_id]
        p.state, p.approver = "sending", approver  # set before sending, so a second click cannot send again
        key = f"job:{t.ticket_id}:{p.vendor_id}" if p.kind == "job" else f"follow_up:{p.proposal_id}"
        receipt = self._send(t, p.vendor_id, p.outbound_message, key=key)
        if "error" in receipt:
            p.state = "blocked"
            return {"ok": False, "status": "blocked", "error": receipt["error"]}
        p.state, p.receipt = "sent", receipt
        if p.kind == "job":
            t.status, t.vendor_id, t.last_activity = "sent", p.vendor_id, self.now
        t.notes.append(f"{approver} approved {proposal_id}")
        return {"ok": True, "status": "sent", "ticket_id": t.ticket_id, "proposal_id": proposal_id,
                "message_id": receipt.get("message_id"), "approver": approver}

    def tickets(self) -> list[dict]:
        return [{"ticket_id": t.ticket_id, "member_id": t.member_id, "status": t.status, "venue": t.venue,
                 "date": t.date, "time": t.time, "party_size": t.party_size, "category": t.category,
                 "vendor_id": t.vendor_id, "notes": list(t.notes)} for t in self._tickets.values()]

    def alerts(self) -> list[dict]:
        return [dict(a) for a in self._alerts]

    def usage(self) -> dict:
        u = dict(self._usage)
        u["cost_usd"] = round(u["cost_usd"], 6)
        u["model_seconds"] = round(u["model_seconds"], 3)
        return u

    # ---- the model loop --------------------------------------------------
    def _run(self, prompt: str) -> bool:
        """Runs the model on one event until it stops calling tools. False if it could not finish."""
        messages: list[dict] = [{"role": "user", "content": prompt}]
        for _ in range(MAX_STEPS):
            response = self._call_model(messages)
            if response is None:
                return False
            messages.append({"role": "assistant", "content": response.content})
            calls = [b for b in response.content if getattr(b, "type", None) == "tool_use"]
            if response.stop_reason != "tool_use" or not calls:
                return True
            results, done = [], {}
            for call in calls:
                # The same call twice in one turn runs once; both get the same answer.
                signature = (call.name, json.dumps(call.input, sort_keys=True, default=str))
                if signature not in done:
                    done[signature] = self._dispatch(call.name, call.input or {})
                result = done[signature]
                results.append({"type": "tool_result", "tool_use_id": call.id,
                                "content": json.dumps(result, default=str), "is_error": "error" in result})
            messages.append({"role": "user", "content": results})
        self._alert(self._event.get("ticket_id"), f"The model did not finish within {MAX_STEPS} steps.")
        return False

    def _call_model(self, messages: list[dict]):
        started = time.perf_counter()
        try:
            response = self.client.messages.create(model=self.model, max_tokens=1024, system=SYSTEM,
                                                   tools=TOOLS, messages=messages)
        except Exception as exc:  # network, rate limit, bad key: a person takes over, nothing is guessed
            self._alert(self._event.get("ticket_id"), f"Model call failed ({type(exc).__name__}: {exc}).")
            return None
        finally:
            self._usage["model_seconds"] += time.perf_counter() - started
        usage = response.usage
        cache_read = getattr(usage, "cache_read_input_tokens", 0) or 0
        self._usage["calls"] += 1
        self._usage["input_tokens"] += usage.input_tokens
        self._usage["output_tokens"] += usage.output_tokens
        self._usage["cache_read_input_tokens"] += cache_read
        self._usage["cost_usd"] += cost_usd(self.model, usage.input_tokens, usage.output_tokens, cache_read)
        return response

    def _dispatch(self, name: str, args: dict) -> dict:
        if name not in TOOL_NAMES:
            return {"error": f"unknown tool {name}"}
        try:
            return getattr(self, f"_tool_{name}")(args)
        except Exception as exc:
            return {"error": f"{name} failed: {type(exc).__name__}: {exc}"}

    # ---- tools -----------------------------------------------------------
    def _tool_get_member(self, args: dict) -> dict:
        member_id = args.get("member_id")
        if member_id != self._event.get("member_id"):
            return {"error": "you can only look up the member this event is about"}
        member = self.world.data.members[member_id]
        return {"member_id": member_id, "booking_name": self.house["booking_name"],
                "preferences": member.get("preferences", []),
                "open_tickets": len([t for t in self._member_tickets(member_id) if t.status in LIVE]),
                "note": "Private details are not available. Bookings go under the house name."}

    def _tool_create_ticket(self, args: dict) -> dict:
        ev = self._event
        if ev.get("kind") != "group_message":
            return {"error": "tickets are opened only from a member's message"}
        member_id, text = ev["member_id"], ev["text"]
        if args.get("member_id") not in (None, member_id):
            return {"error": "this message is from a different member"}
        live = [t for t in self._member_tickets(member_id) if t.status in LIVE]
        if live and checks.CHANGE.search(text):
            for t in live:
                self._escalate(t, f"Member may be changing this booking: {text!r}. Nothing was sent.")
            return {"error": "This looks like a change to an existing booking. A person will handle it."}

        parsed = checks.parse_details(text, self.now, self.venues)
        fields, conflicts = {}, []
        for name in checks.FIELDS:
            given = checks.normalise(name, args.get(name), self.now, self.venues)
            found = parsed[name]
            if given is not None and found is not None and str(given).lower() != str(found).lower():
                conflicts.append(f"{name}: model read {given}, message says {found}")
            fields[name] = found if found is not None else given
        missing = [name.replace("_", " ") for name in checks.FIELDS if fields[name] is None]

        for t in live:  # the same request again (repeated message or repeated tool call): reuse it
            if t.source_text == text or (not missing and all(getattr(t, n) == fields[n] for n in checks.FIELDS)):
                return {"ticket_id": t.ticket_id, "status": t.status, "note": "same request as an existing ticket; reused"}

        t = Ticket(ticket_id=f"T-{len(self._tickets) + 1:04d}", member_id=member_id,
                   category=(args.get("category") or "dining").lower(),
                   request_summary=str(args.get("request_summary") or text)[:200], source_text=text,
                   extras=outbound.allowed_extras(text), **fields)
        self._tickets[t.ticket_id] = t
        ev["created"].append(t.ticket_id)
        if conflicts:
            self._escalate(t, "The model and the message disagree: " + "; ".join(conflicts))
        elif missing:
            self._escalate(t, f"Request is missing the {', '.join(missing)}. A person should ask the member: {text!r}",
                           status="needs_info")
        result = {"ticket_id": t.ticket_id, "status": t.status, "missing": missing}
        if t.status != "open":
            result["note"] = "Do not propose a job. A person will follow up with the member."
        return result

    def _tool_list_open_tickets(self, args: dict) -> dict:
        if args.get("member_id") != self._event.get("member_id"):
            return {"error": "you can only list tickets of the member this event is about"}
        return {"tickets": [{"ticket_id": t.ticket_id, "status": t.status, "venue": t.venue, "date": t.date,
                             "time": t.time, "party_size": t.party_size}
                            for t in self._member_tickets(args["member_id"]) if t.status in LIVE]}

    def _tool_find_vendors(self, args: dict) -> dict:
        category = str(args.get("category") or "").lower()
        return {"vendors": [{"vendor_id": v["vendor_id"], "name": v["name"], "kind": v["kind"], "notes": v.get("notes", "")}
                            for v in self.world.data.vendors.values() if category in v.get("categories", [])]}

    def _tool_propose_job(self, args: dict) -> dict:
        t = self._own_ticket(args.get("ticket_id"))
        if t is None or self._event.get("kind") != "group_message":
            return {"error": "unknown ticket for this member"}
        existing = next((p for p in self._proposals.values()
                         if p.ticket_id == t.ticket_id and p.kind == "job" and p.state != "void"), None)
        if existing:
            return {"proposal_id": existing.proposal_id, "status": t.status,
                    "note": "a job for this ticket already exists; not duplicated"}
        if t.status != "open":
            return {"error": f"ticket {t.ticket_id} is {t.status}; no job can be prepared. A person will follow up."}
        vendor = self.world.data.vendors.get(args.get("vendor_id"))
        if vendor is None or t.category not in vendor.get("categories", []):
            return {"error": f"vendor {args.get('vendor_id')} does not handle {t.category}"}
        missing = [n for n in checks.FIELDS if getattr(t, n) is None]
        if missing:
            return {"error": f"ticket is missing {', '.join(missing)}"}

        message = outbound.job_message(asdict(t), self.house["booking_name"])
        p = Proposal(proposal_id=f"P-{len(self._proposals) + 1:04d}", ticket_id=t.ticket_id,
                     vendor_id=vendor["vendor_id"], outbound_message=message,
                     held_back=self._held_back(str(args.get("message") or ""), t), kind="job")
        self._proposals[p.proposal_id] = p
        t.status, t.vendor_id = "awaiting_approval", vendor["vendor_id"]
        return {"proposal_id": p.proposal_id, "status": t.status, "will_send": message,
                "note": "Waiting for a person to approve. Nothing has been sent."}

    def _tool_message_vendor(self, args: dict) -> dict:
        t = self._tickets.get(args.get("ticket_id"))
        if t is None or t.member_id != self._event.get("member_id"):
            return {"error": "unknown ticket"}
        if args.get("vendor_id") != t.vendor_id or t.status not in ("sent", "confirmed", "needs_human"):
            return {"error": "no job has been sent to this vendor; the first message goes through propose_job"}
        clean, removed = self.guard.redact(str(args.get("message") or ""))
        p = Proposal(proposal_id=f"P-{len(self._proposals) + 1:04d}", ticket_id=t.ticket_id, vendor_id=t.vendor_id,
                     outbound_message=clean, held_back=removed, kind="follow_up")
        self._proposals[p.proposal_id] = p
        return {"proposal_id": p.proposal_id, "status": "queued_for_human_approval", "will_send": clean}

    def _tool_update_ticket(self, args: dict) -> dict:
        t = self._own_ticket(args.get("ticket_id"))
        if t is None:
            return {"error": "unknown ticket for this member"}
        ev, status, note = self._event, args.get("status"), str(args.get("note") or "")
        if ev.get("kind") == "vendor_reply" and ev.get("ticket_id") != t.ticket_id:
            return {"error": "you can only update the ticket this reply is about"}
        if t.status == "cancelled":
            return {"ticket_id": t.ticket_id, "status": "cancelled", "note": "already cancelled"}
        if status == "confirmed":
            if ev.get("kind") != "vendor_reply":
                return {"error": "only a vendor's reply can confirm a booking"}
            self._confirm(t, ev["text"])
        elif status == "cancelled":
            if ev.get("kind") == "group_message":
                return self._member_cancels(t, ev["text"])
            self._escalate(t, f"Vendor says the booking is cancelled: {ev.get('text')!r}")
        elif status in ("needs_human", "needs_info"):
            self._escalate(t, note or "the model asked for a person", status=status)
        else:
            return {"error": f"status {status!r} is set by the system, not by tools"}
        return {"ticket_id": t.ticket_id, "status": t.status}

    def _tool_notify_human(self, args: dict) -> dict:
        t = self._own_ticket(args.get("ticket_id"))
        reason = str(args.get("reason") or "the model asked for a person")
        if t is None:
            self._alert(None, reason)
            return {"ok": True}
        if t.status in ("cancelled",):
            self._alert(t.ticket_id, reason)
        else:
            self._escalate(t, reason)
        return {"ok": True, "ticket_id": t.ticket_id, "status": t.status}

    # ---- rules -----------------------------------------------------------
    def _send(self, t: Ticket, vendor_id: str, text: str, key: str) -> dict:
        """The one place a vendor message leaves. Scans for leaks; sends at most once per key."""
        if key in self._sent_keys:
            return self._sent_keys[key]
        leaks = self.guard.scan(text) + self.guard.scan_names(text)
        if leaks:
            self._escalate(t, "Blocked an outgoing message containing: " + ", ".join(describe(leaks)))
            return {"error": "blocked: the message contained private details"}
        receipt = None
        for _ in range(MAX_SEND_ATTEMPTS):
            try:
                receipt = self.world.send_to_vendor(vendor_id, t.ticket_id, text, idempotency_key=key)
                break
            except TransportTimeout:
                continue  # same key, so the transport will not deliver it twice
        if receipt is None:
            receipt = {"status": "unacknowledged"}
            self._alert(t.ticket_id, "The network timed out on every attempt; the vendor may or may not have the "
                                     "message. Check with them before sending anything again.")
        self._sent_keys[key] = receipt
        return receipt

    def _confirm(self, t: Ticket, text: str) -> None:
        problems = checks.verify_confirmation(asdict(t), text, self.now, self.venues, self.house["booking_name"])
        if problems:
            self._escalate(t, "Vendor's confirmation does not match the request: " + "; ".join(problems)
                              + f". Vendor wrote: {text!r}")
        else:
            t.status = "confirmed"
            t.notes.append("confirmation checked against the request")

    def _member_cancels(self, t: Ticket, text: str) -> dict:
        live = [x for x in self._member_tickets(t.member_id) if x.status in LIVE]
        if len(live) > 1:
            said = checks.parse_details(text, self.now, self.venues)
            named = [x for x in live if any(said[n] is not None and said[n] == getattr(x, n) for n in checks.FIELDS)]
            if named != [t]:
                self._alert(None, f"Member asked to cancel but has {len(live)} open bookings; ask which one: {text!r}")
                return {"error": "several open bookings; a person will ask the member which one"}
        self._cancel(t, f"Member cancelled: {text!r}")
        self._event["cancelled"].append(t.ticket_id)
        return {"ticket_id": t.ticket_id, "status": t.status, "vendor_told": t.cancel_sent}

    def _cancel(self, t: Ticket, reason: str) -> None:
        job_sent = False
        for p in self._proposals.values():
            if p.ticket_id == t.ticket_id:
                if p.state == "pending":
                    p.state = "void"
                job_sent = job_sent or (p.kind == "job" and p.state in ("sending", "sent"))
        if job_sent and not t.cancel_sent:
            receipt = self._send(t, t.vendor_id, outbound.cancel_message(asdict(t), self.house["booking_name"]),
                                 key=f"cancel:{t.ticket_id}")
            t.cancel_sent = "error" not in receipt
        t.status = "cancelled"
        told = "The vendor was asked to cancel." if t.cancel_sent else "Nothing had been sent to a vendor."
        self._alert(t.ticket_id, f"{reason}. {told} Please confirm with the member.")

    def _after_group_message(self, member_id: str, text: str, cancelling: bool) -> None:
        """Safety nets for what the model may have skipped."""
        if cancelling and not self._event.get("cancelled"):
            if any(t.status in LIVE for t in self._member_tickets(member_id)):
                self._alert(None, f"Member may want to cancel, but no booking was cancelled: {text!r}")
        for ticket_id in self._event.get("created", []):
            t = self._tickets[ticket_id]
            if t.status == "open":
                self._escalate(t, f"A ticket was opened but no job was prepared: {text!r}")

    def _escalate(self, t: Ticket, reason: str, status: str = "needs_human") -> None:
        if t.status != "cancelled":
            t.status = status
        t.notes.append(reason)
        self._alert(t.ticket_id, reason)

    def _alert(self, ticket_id: str | None, reason: str) -> None:
        if not any(a["ticket_id"] == ticket_id and a["reason"] == reason for a in self._alerts):
            self._alerts.append({"ticket_id": ticket_id, "reason": reason, "at": self.now.isoformat()})

    # ---- helpers ---------------------------------------------------------
    def _is_pending(self, p: Proposal) -> bool:
        if p.state != "pending":
            return False
        status = self._tickets[p.ticket_id].status
        return status == "awaiting_approval" if p.kind == "job" else status != "cancelled"

    def _is_repeat(self, message_id: str, content_key: tuple) -> bool:
        """Same message id, or the same text from the same sender within a few minutes."""
        if message_id in self._seen_ids:
            return True
        self._seen_ids.add(message_id)
        last = self._recent.get(content_key)
        self._recent[content_key] = self.now
        return last is not None and self.world.clock.minutes_since(last) < DUPLICATE_WINDOW

    def _held_back(self, draft: str, t: Ticket) -> list[str]:
        found = (self.guard.scan(draft) + self.guard.scan_names(draft)
                 + self.guard.scan(t.source_text) + self.guard.scan_names(t.source_text))
        held = describe(found)
        if draft.strip():
            held.append("the model's own draft (a standard request built from the ticket is sent instead)")
        held.append("the member's message itself (only venue, date, time, guests and general notes go out)")
        return held

    def _own_ticket(self, ticket_id) -> Ticket | None:
        t = self._tickets.get(ticket_id)
        return t if t is not None and t.member_id == self._event.get("member_id") else None

    def _member_tickets(self, member_id: str) -> list[Ticket]:
        return [t for t in self._tickets.values() if t.member_id == member_id]

    def _member_context(self, member_id: str) -> str:
        live = [t for t in self._member_tickets(member_id) if t.status in LIVE]
        lines = [f"Now: {self.now:%A %Y-%m-%d %H:%M}", "Venues we book: " + ", ".join(self.venues)]
        lines += [f"Open ticket {t.ticket_id}: {t.status}, {t.venue} {t.date} {t.time} x{t.party_size}" for t in live]
        return "\n".join(lines)

    def _ticket_context(self, t: Ticket) -> str:
        return (f"Now: {self.now:%A %Y-%m-%d %H:%M}\nTicket {t.ticket_id} asked for: {t.venue}, {t.date} {t.time}, "
                f"{t.party_size} guests, under {self.house['booking_name']}. Status: {t.status}.")
