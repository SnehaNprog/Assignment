"""The simulated world. Read it, use it, but do not change it: our review runs a
clean copy of this folder against your agent."""
from .clock import Clock
from .events import parse_event, render_group_message, render_timer, render_vendor_reply
from .fake_llm import FakeAnthropic
from .scenarios import SCENARIOS
from .transport import TransportTimeout
from .world import World

__all__ = [
    "Clock", "FakeAnthropic", "SCENARIOS", "TransportTimeout", "World",
    "parse_event", "render_group_message", "render_timer", "render_vendor_reply",
]
