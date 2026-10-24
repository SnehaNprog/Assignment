"""The house rules, one test (or a few) each. Run with: pytest -q"""
from __future__ import annotations

import pytest

from helpers import all_leaks, approve_all, build, leaks, run_scenario
from world import SCENARIOS


def statuses(concierge) -> list[str]:
    return [t["status"] for t in concierge.tickets()]


# ---- rule 1: nothing private leaves ----------------------------------------
@pytest.mark.parametrize("name", list(SCENARIOS))
def test_no_scenario_leaks_anything(name):
    world, _ = run_scenario(name)
    assert all_leaks(world) == []


@pytest.mark.parametrize("text", [
    "Book Koen for Saturday 8pm, 4 of us. Under Riya Kapoor please, call me on 9820123456",
    "Table for 2 at Casa Lumen tomorrow 9 pm. My email is riya.kapoor@example.com, pay with card 3782 822463 10005 exp 09/29",
    "Book Mirabelle Friday 1 pm for 6, Anaya's birthday! Send the bill to 14 Carmichael Road",
    "Dinner at Koen on Sat at 8pm for 3, me + Arjun + our friend Rohit Sharma's wife",
])
def test_member_details_in_the_message_never_reach_the_vendor(text):
    world, concierge = build()
    world.member_says("G-101", text)
    approve_all(concierge)
    world.advance(20)
    assert len(world.transport.sent) == 1
    assert all_leaks(world) == []
    assert "Rohit" not in world.transport.sent[0]["text"]


def test_last_gate_blocks_a_leak_even_if_a_template_had_a_bug(monkeypatch):
    import agent.outbound
    monkeypatch.setattr(agent.outbound, "job_message", lambda ticket, name: "Book it for Riya, +91 98201 23456")
    world, concierge = build()
    world.member_says("G-101", "Book Koen for Saturday 8pm, 4 of us")
    result = approve_all(concierge)[0]
    assert result["ok"] is False and world.transport.sent == []
    assert statuses(concierge) == ["needs_human"]


def test_model_follow_ups_are_scrubbed_and_need_approval():
    world, concierge = build()
    world.member_says("G-101", "Book Koen for Saturday 8pm, 4 of us")
    approve_all(concierge)
    concierge._event = {"kind": "vendor_reply", "member_id": "M001", "ticket_id": "T-0001", "text": ""}
    queued = concierge._dispatch("message_vendor", {"ticket_id": "T-0001", "vendor_id": "V-BOOKBOT",
                                                    "message": "Guest is Riya Kapoor, 98201 23456, riya.kapoor@example.com"})
    assert queued["status"] == "queued_for_human_approval"
    assert len(world.transport.sent) == 1
    approve_all(concierge)
    assert len(world.transport.sent) == 2 and all_leaks(world) == []


def test_bookings_go_under_the_house_name():
    world, concierge = build()
    world.member_says("G-101", "Book Koen for Saturday 8pm, 4 of us")
    approve_all(concierge)
    assert "under the name Indulge Concierge" in world.transport.sent[0]["text"]


def test_the_strict_leak_check_itself_catches_odd_phone_formats():
    world, _ = build()
    assert leaks("guest mobile +91-98201-23456", world.data.members)
    assert leaks("call 98201 23456", world.data.members)
    assert leaks("guest is Mrs Kapoor", world.data.members)


# ---- rule 2: a human approves the first message ------------------------------
def test_nothing_is_sent_before_approval_and_the_proposal_shows_what_will_go():
    world, concierge = build()
    world.member_says("G-102", "Need dinner for Anjali's birthday this Friday at Saffron Terrace, 2 people, "
                                "8:30pm. Call me on 99300 45678 if anything.")
    assert world.transport.sent == []
    [proposal] = concierge.pending_proposals()
    assert any("99300 45678" in item for item in proposal["held_back"])
    assert any("Anjali" in item for item in proposal["held_back"])
    concierge.approve(proposal["proposal_id"], approver="nisha")
    assert world.transport.sent[0]["text"] == proposal["outbound_message"]


# ---- rule 3: exactly once -----------------------------------------------------
def test_approving_twice_sends_once():
    world, concierge = build()
    world.member_says("G-101", "Book Koen for Saturday 8pm, 4 of us")
    [p] = concierge.pending_proposals()
    first = concierge.approve(p["proposal_id"], approver="nisha")
    second = concierge.approve(p["proposal_id"], approver="rohan")
    assert first["status"] == "sent" and second["status"] == "already_sent"
    assert len(world.transport.sent) == 1


def test_the_same_whatsapp_message_twice_makes_one_ticket():
    world, concierge = build()
    world.member_says("G-101", "Book Koen for Saturday 8pm, 4 of us", message_id="WA-1")
    world.member_says("G-101", "Book Koen for Saturday 8pm, 4 of us", message_id="WA-1")
    world.member_says("G-101", "Book Koen for Saturday 8pm, 4 of us", message_id="WA-2")  # re-delivered, new id
    approve_all(concierge)
    approve_all(concierge)
    assert len(concierge.tickets()) == 1
    assert len(world.transport.sent) == 1


def test_model_calling_propose_job_twice_makes_one_proposal():
    world, concierge = build(quirks={"duplicate_propose"})
    world.member_says("G-105", "bhai Saturday ko The Blue Door mein 3 logon ka table kar do, 9 baje")
    assert len(concierge.pending_proposals()) == 1
    approve_all(concierge)
    assert len(world.bookbot.received) == 1


def test_network_timeout_does_not_send_twice():
    world, concierge = run_scenario("kabir_flaky_network")
    assert len(world.bookbot.received) == 1
    assert statuses(concierge) == ["confirmed"]


# ---- rule 4: trust, but verify -------------------------------------------------
@pytest.mark.parametrize("behaviour", ["wrong_date", "wrong_size"])
def test_wrong_confirmation_goes_to_a_human(behaviour):
    world, concierge = build(bookbot=behaviour)
    world.member_says("G-101", "Table for 4 at Koen, Saturday 8pm please")
    approve_all(concierge)
    world.advance(20)
    assert statuses(concierge) == ["needs_human"]
    assert any("does not match" in a["reason"] for a in concierge.alerts())


def test_a_change_after_confirming_goes_to_a_human():
    world, concierge = run_scenario("kabir_hinglish_double")
    assert statuses(concierge) == ["needs_human"]


def test_correct_confirmation_is_confirmed():
    world, concierge = run_scenario("riya_corner_table")
    assert statuses(concierge) == ["confirmed"]
    assert concierge.alerts() == []


# ---- rule 5: silence ------------------------------------------------------------
def test_silent_vendor_gets_one_reminder_then_a_human():
    world, concierge = build(bookbot="silent")
    world.member_says("G-101", "Can you get us a table at Koen tomorrow, 9 pm, for 2?")
    approve_all(concierge)
    world.advance(600)
    assert len(world.transport.sent) == 2  # the job and one reminder, never more
    assert all_leaks(world) == []
    assert statuses(concierge) == ["needs_human"]
    assert any("silent" in a["reason"] for a in concierge.alerts())


def test_a_vendor_that_answers_is_not_chased():
    world, concierge = build()
    world.member_says("G-101", "Can you get us a table at Koen tomorrow, 9 pm, for 2?")
    approve_all(concierge)
    world.advance(300)
    assert len(world.transport.sent) == 1


# ---- rule 6: when unsure, ask a human ------------------------------------------------
@pytest.mark.parametrize("behaviour", ["asks_phone", "asks_card"])
def test_vendor_asking_for_personal_details_gets_nothing(behaviour):
    world, concierge = build(bookbot=behaviour)
    world.member_says("G-102", "Table for 5 at Casa Lumen on Thursday, 8 pm please.")
    approve_all(concierge)
    world.advance(60)
    assert len(world.transport.sent) == 1  # only the approved job
    assert all_leaks(world) == []
    assert statuses(concierge) == ["needs_human"]
    assert any("personal details" in a["reason"] for a in concierge.alerts())


def test_vague_request_sends_nothing_and_asks_a_human():
    world, concierge = run_scenario("sameer_unclear")
    assert world.transport.sent == []
    assert statuses(concierge) == ["needs_info"]
    assert concierge.alerts()


def test_cancel_before_approval_means_approve_does_nothing():
    world, concierge = build()
    world.member_says("G-104", "Please book Mirabelle for Sunday lunch, 1 pm, 6 of us")
    [p] = concierge.pending_proposals()
    world.member_says("G-104", "Actually cancel that, plans changed. Sorry!")
    assert concierge.pending_proposals() == []
    assert concierge.approve(p["proposal_id"], approver="nisha")["ok"] is False
    assert world.transport.sent == []
    assert statuses(concierge) == ["cancelled"]


def test_cancel_after_send_tells_the_vendor_once():
    world, concierge = run_scenario("priya_cancel_after_send")
    cancels = [m for m in world.bookbot.received if "cancel" in m["text"].lower()]
    assert len(cancels) == 1
    assert statuses(concierge) == ["cancelled"]


def test_chatter_creates_nothing():
    world, concierge = run_scenario("tara_chatter")
    assert concierge.tickets() == [] and world.transport.sent == []


# ---- messy edges ---------------------------------------------------------------------
class _BrokenClient:
    class messages:
        @staticmethod
        def create(**_):
            raise TimeoutError("model unreachable")


def test_model_outage_sends_nothing_and_raises_an_alert():
    world, concierge = build(client=_BrokenClient())
    world.member_says("G-101", "Book Koen for Saturday 8pm, 4 of us")
    assert world.transport.sent == [] and concierge.pending_proposals() == []
    assert any("Model call failed" in a["reason"] for a in concierge.alerts())


def test_reply_on_an_unknown_ticket_is_flagged_not_acted_on():
    world, concierge = build()
    concierge.on_vendor_reply("V-BOOKBOT", "T-9999", "Confirmed: Koen, Sat 7 Nov 2026 at 8:00 pm, table for 4.", "VR-1")
    assert concierge.tickets() == [] and concierge.alerts()


def test_usage_is_counted():
    _, concierge = run_scenario("riya_corner_table")
    usage = concierge.usage()
    assert usage["calls"] > 0 and usage["input_tokens"] > 0 and usage["cost_usd"] > 0
