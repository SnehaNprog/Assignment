"""A free, offline stand-in for the Claude Messages API.

    client = FakeAnthropic(world.clock)
    response = client.messages.create(model=..., max_tokens=..., system=..., messages=..., tools=...)

It accepts the same arguments as `anthropic.Anthropic().messages.create` and
returns an object with the same shape (`content` blocks, `stop_reason`, `usage`).
So the agent loop you write runs unchanged against this fake or against real
Claude (`anthropic.Anthropic()`).

IMPORTANT: this fake model is deliberately careless, like a real model on a bad
day. It copies private details into messages, believes whatever a vendor says,
calls the same tool twice, and hands over a phone number when asked nicely.
Your code, not the model, has to keep the company safe.

It only knows the tool names listed in the README (get_member, create_ticket,
list_open_tickets, find_vendors, propose_job, message_vendor, update_ticket,
notify_human) and reads tool results as JSON.
"""
from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field

from .events import parse_event
from .parse import fmt_date, fmt_time, parse_date, parse_party_size, parse_time, parse_venue


# ---- response objects shaped like the anthropic SDK's --------------------
@dataclass
class TextBlock:
    text: str
    type: str = "text"

    def model_dump(self) -> dict:
        return {"type": self.type, "text": self.text}


@dataclass
class ToolUseBlock:
    id: str
    name: str
    input: dict
    type: str = "tool_use"

    def model_dump(self) -> dict:
        return {"type": self.type, "id": self.id, "name": self.name, "input": self.input}


@dataclass
class Usage:
    input_tokens: int
    output_tokens: int
    cache_read_input_tokens: int = 0
    cache_creation_input_tokens: int = 0

    def model_dump(self) -> dict:
        return asdict(self)


@dataclass
class Message:
    id: str
    model: str
    content: list
    stop_reason: str
    usage: Usage
    role: str = "assistant"
    type: str = "message"


# ---- the fake client ------------------------------------------------------
class FakeAnthropic:
    """Drop-in for `anthropic.Anthropic()` in this assignment.

    quirks: optional set of extra bad habits, e.g. {"duplicate_propose"}.
    """

    def __init__(self, clock, venues: list[str] | None = None, quirks: set[str] | None = None):
        self.messages = _Messages(clock, venues or [], set(quirks or ()))


class _Messages:
    def __init__(self, clock, venues: list[str], quirks: set[str]):
        self.clock = clock
        self.venues = venues
        self.quirks = quirks
        self._seq = 0

    def create(self, *, model: str, messages: list, max_tokens: int = 1024, system=None, tools=None, **_ignored) -> Message:
        tool_names = {t["name"] if isinstance(t, dict) else getattr(t, "name", "") for t in (tools or [])}
        event, steps = _read_transcript(messages)
        if event is None:
            plan = ("end", "I did not find an event header in the last user message, so there is nothing for me to do.")
        else:
            plan = _Policy(event, steps, self.clock, self.venues, self.quirks).next()

        content: list = []
        if plan[0] == "tool":
            _, calls, preface = plan
            missing = [name for name, _ in calls if name not in tool_names]
            if missing:
                content = [TextBlock(f"I wanted to call `{missing[0]}` but no tool with that name was provided.")]
                stop = "end_turn"
            else:
                content.append(TextBlock(preface))
                for name, args in calls:
                    self._seq += 1
                    content.append(ToolUseBlock(id=f"toolu_fake_{self._seq:05d}", name=name, input=args))
                stop = "tool_use"
        else:
            content = [TextBlock(plan[1])]
            stop = "end_turn"

        self._seq += 1
        prompt_chars = len(json.dumps(_jsonable(system))) + len(json.dumps(_jsonable(messages))) + len(json.dumps(_jsonable(tools)))
        output_chars = len(json.dumps([_dump(b) for b in content]))
        usage = Usage(input_tokens=max(1, prompt_chars // 4), output_tokens=max(1, output_chars // 4))
        return Message(id=f"msg_fake_{self._seq:05d}", model=model, content=content, stop_reason=stop, usage=usage)


# ---- reading the conversation ---------------------------------------------
def _dump(block) -> dict:
    if isinstance(block, dict):
        return block
    if hasattr(block, "model_dump"):
        return block.model_dump()
    return {k: getattr(block, k) for k in ("type", "text", "id", "name", "input", "tool_use_id", "content") if hasattr(block, k)}


def _jsonable(value):
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, dict):
        return {k: _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    return _jsonable(_dump(value))


def _blocks(content) -> list[dict]:
    if isinstance(content, str):
        return [{"type": "text", "text": content}]
    return [_dump(b) for b in content]


def _result_value(content):
    if isinstance(content, list):
        content = "".join(b.get("text", "") for b in (_dump(x) for x in content))
    if isinstance(content, str):
        try:
            return json.loads(content)
        except ValueError:
            return {"raw": content}
    return content


def _read_transcript(messages: list):
    """Finds the latest event and the tool calls/results made since."""
    start = None
    event = None
    for index in range(len(messages) - 1, -1, -1):
        msg = messages[index]
        if msg.get("role") != "user":
            continue
        for block in _blocks(msg.get("content", "")):
            if block.get("type") == "text":
                parsed = parse_event(block.get("text", ""))
                if parsed:
                    start, event = index, parsed
                    break
        if event:
            break
    if event is None:
        return None, []

    calls: dict[str, dict] = {}
    steps: list[dict] = []
    for msg in messages[start + 1:]:
        for block in _blocks(msg.get("content", "")):
            if block.get("type") == "tool_use":
                call = {"name": block["name"], "input": block.get("input", {}), "result": None, "is_error": False}
                calls[block["id"]] = call
                steps.append(call)
            elif block.get("type") == "tool_result" and block.get("tool_use_id") in calls:
                call = calls[block["tool_use_id"]]
                call["result"] = _result_value(block.get("content", ""))
                call["is_error"] = bool(block.get("is_error"))
    return event, steps


def _find(value, keys: tuple[str, ...]):
    """First value for any of `keys`, searching nested dicts."""
    if isinstance(value, dict):
        for key in keys:
            if value.get(key):
                return value[key]
        for nested in value.values():
            found = _find(nested, keys)
            if found:
                return found
    return None


# ---- the careless policy --------------------------------------------------
BOOKING_SIGNAL = re.compile(r"\bbook\b|\btable\b|reservation|dinner|lunch|something nice|kar do|get us", re.I)


class _Policy:
    def __init__(self, event: dict, steps: list[dict], clock, venues: list[str], quirks: set[str]):
        self.event = event
        self.steps = steps
        self.clock = clock
        self.venues = venues
        self.quirks = quirks
        self.body = event.get("body", "")

    def _done(self, name: str) -> list[dict]:
        return [s for s in self.steps if s["name"] == name]

    def _member(self) -> dict:
        got = self._done("get_member")
        return got[-1]["result"] if got and isinstance(got[-1]["result"], dict) else {}

    def next(self):
        if self.steps:
            last = self.steps[-1]
            error = last["result"].get("error") if isinstance(last["result"], dict) else None
            if last["is_error"] or error:
                return ("end", f"Stopped: `{last['name']}` failed ({error or last['result']}).")
        kind = self.event["kind"]
        if kind == "group_message":
            return self._group_message()
        if kind == "vendor_reply":
            return self._vendor_reply()
        if kind == "timer":
            if not self._done("message_vendor"):
                return ("tool", [("message_vendor", {"ticket_id": self.event["ticket_id"],
                                                     "vendor_id": self.event["vendor_id"],
                                                     "message": "Hi, any update on this booking?"})],
                        "Chasing the vendor.")
            return ("end", "Chased the vendor.")
        return ("end", "Nothing to do.")

    # -- a member wrote in their group
    def _group_message(self):
        member_id = self.event.get("member_id")
        if re.search(r"\bcancel\b", self.body, re.I):
            listed = self._done("list_open_tickets")
            if not listed:
                return ("tool", [("list_open_tickets", {"member_id": member_id})], "Looking for the booking to cancel.")
            tickets = (listed[-1]["result"] or {}).get("tickets", [])
            live = [t for t in tickets if t.get("status") not in ("cancelled",)]
            if live and not self._done("update_ticket"):
                return ("tool", [("update_ticket", {"ticket_id": live[-1]["ticket_id"], "status": "cancelled",
                                                    "note": "Member cancelled: " + self.body})],
                        "Cancelling the booking.")
            return ("end", "Cancelled." if live else "There was no open booking to cancel.")

        if not BOOKING_SIGNAL.search(self.body):
            return ("end", "No request in this message. Nothing to do.")

        if not self._done("get_member"):
            return ("tool", [("get_member", {"member_id": member_id})], "Let me look up the member first.")

        now = self.clock.now
        when = parse_date(self.body, now)
        fields = {
            "venue": parse_venue(self.body, self.venues),
            "date": when.isoformat() if when else None,
            "time": parse_time(self.body),
            "party_size": parse_party_size(self.body),
        }
        created = self._done("create_ticket")
        if not created:
            return ("tool", [("create_ticket", {"member_id": member_id, "category": "dining",
                                                "request_summary": self.body[:160], **fields})],
                    "Creating a ticket.")
        ticket_id = _find(created[-1]["result"], ("ticket_id",))

        found = self._done("find_vendors")
        if not found:
            return ("tool", [("find_vendors", {"category": "dining"})], "Finding a vendor.")
        vendors = (found[-1]["result"] or {}).get("vendors", [])
        if not vendors:
            return ("end", "No vendor available for this request.")
        vendor = next((v for v in vendors if v.get("kind") == "ai_agent"), vendors[0])

        if not self._done("propose_job"):
            message = self._careless_draft(fields)
            call = ("propose_job", {"ticket_id": ticket_id, "vendor_id": vendor.get("vendor_id"), "message": message})
            calls = [call, call] if "duplicate_propose" in self.quirks else [call]
            return ("tool", calls, f"Sending the job to {vendor.get('name', 'the vendor')}.")
        result = self._done("propose_job")[-1]["result"]
        return ("end", f"Done. Job proposed to {vendor.get('name', 'the vendor')}: {json.dumps(result)}")

    def _careless_draft(self, fields: dict) -> str:
        member = self._member()
        name = _find(member, ("name", "full_name", "member_name")) or "(unknown)"
        phone = _find(member, ("phone", "mobile", "phone_number"))
        when = fmt_date(parse_date(fields["date"], self.clock.now)) if fields["date"] else "TBC"
        at = fmt_time(fields["time"]) if fields["time"] else "TBC"
        lines = [
            f"Hi! Please book a table for {fields['party_size'] or 'TBC'} at {fields['venue'] or 'TBC'} "
            f"on {when} at {at}.",
            f"Guest name: {name}." + (f" Contact: {phone}." if phone else ""),
            f"Client's message: \"{self.body}\"",
        ]
        return "\n".join(lines)

    # -- a vendor replied on a ticket
    def _vendor_reply(self):
        ticket_id, vendor_id = self.event.get("ticket_id"), self.event.get("vendor_id")
        low = self.body.lower()
        asks_private = re.search(r"mobile|phone|number|contact|card|expiry", low) and "confirmed" not in low
        if asks_private:
            if not self._done("get_member"):
                return ("tool", [("get_member", {"member_id": self.event.get("member_id")})], "Getting the details they asked for.")
            if not self._done("message_vendor"):
                member = self._member()
                if "card" in low:
                    card = _find(member, ("card",)) or {}
                    text = (f"Sure. Card: {card.get('brand', '')} ending {card.get('last4', '????')}, "
                            f"expiry {card.get('expiry', '??/??')}. Cardholder {_find(member, ('name',)) or ''}.")
                else:
                    text = f"Sure, the guest's mobile is {_find(member, ('phone', 'mobile')) or 'not on file'}."
                return ("tool", [("message_vendor", {"ticket_id": ticket_id, "vendor_id": vendor_id, "message": text})],
                        "Sending what they asked for.")
            return ("end", "Shared the details with the vendor.")

        if "cancelled" in low:
            if not self._done("update_ticket"):
                return ("tool", [("update_ticket", {"ticket_id": ticket_id, "status": "cancelled", "note": self.body})], "Marking cancelled.")
            return ("end", "Marked as cancelled.")
        if "still need" in low:
            if not self._done("notify_human"):
                return ("tool", [("notify_human", {"ticket_id": ticket_id, "reason": "Vendor needs more details: " + self.body})], "Asking a human.")
            return ("end", "Asked a human for the missing details.")
        if re.search(r"confirm|moved you|small change|booked", low):
            if not self._done("update_ticket"):
                return ("tool", [("update_ticket", {"ticket_id": ticket_id, "status": "confirmed", "note": self.body})], "Great, marking it confirmed.")
            return ("end", "Marked as confirmed.")
        return ("end", "Noted. Waiting for the vendor.")
