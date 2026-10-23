"""Example tests about the world itself (no agent needed). Put your own tests next to this file."""
from world import FakeAnthropic, World, render_group_message
from world.transport import TransportTimeout


def test_bookbot_confirms_a_complete_job():
    world = World(bookbot="correct")
    world.transport.send("V-BOOKBOT", "T-1", "Table for 4 at Koen on Saturday at 8 pm, under the name Indulge Concierge.")
    world.clock.advance(10)
    replies = world.bookbot.due(world.clock.now)
    assert "Confirmed: Koen, Sat 7 Nov 2026 at 8:00 pm, table for 4" in replies[0]["text"]


def test_flaky_transport_delivers_then_times_out():
    world = World(flaky=True)
    try:
        world.transport.send("V-BOOKBOT", "T-1", "hello", idempotency_key="k1")
    except TransportTimeout:
        pass
    world.transport.send("V-BOOKBOT", "T-1", "hello", idempotency_key="k1")
    assert len(world.bookbot.received) == 1


def test_fake_model_starts_by_looking_up_the_member():
    world = World()
    client = FakeAnthropic(world.clock, world.data.house["venues"])
    event = render_group_message("G-101", "M001", "Riya Kapoor", "Book Koen for Saturday 8pm, 4 of us")
    tools = [{"name": "get_member", "description": "", "input_schema": {"type": "object", "properties": {}}}]
    response = client.messages.create(model="claude-haiku-5-5", max_tokens=512, tools=tools,
                                      messages=[{"role": "user", "content": event}])
    assert response.stop_reason == "tool_use"
    assert response.content[-1].name == "get_member"
