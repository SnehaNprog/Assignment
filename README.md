# AI Engineer assignment: the concierge booking agent

Thank you for taking this on. It should take **about 4 hours**. Please stop at 4 hours and tell us
what is unfinished. Honest notes about gaps score better than a rushed finish.

## The story

We are a luxury concierge company. Our members are busy families who message us on WhatsApp for
everything: a table tonight, flowers for a birthday, a car to the airport. Each member has a private
group with our team.

More and more of the legwork can be done by **outside AI agents**: bots run by other companies that
can book a restaurant in minutes. They are fast and cheap. They are also strangers. We must never
hand them a member's name, phone number, address or card, and we must never let one mistake turn
into a double booking or a wrong confirmation that nobody notices.

Your job: **build the agent that sits between our members and an outside booking bot.** It reads a
member's message, opens a ticket, prepares the job for the outside bot, waits for a human to
approve, sends it safely, and handles whatever the bot says back.

Everything here is simulated and fake. No real people, no real services, no cost by default.

## What is in this folder

```text
world/        The simulated world. Read it. Do not change it (we review with a clean copy).
  world.py      World: the clock, the data, the transport and BookBot, and how events reach you
  bookbot.py    BookBot, the outside booking agent. It misbehaves on purpose.
  fake_llm.py   FakeAnthropic, a free offline stand-in for the Claude Messages API.
                It is careless on purpose: it copies private details, trusts vendors, repeats itself.
  transport.py  The only way a message leaves the building. transport.sent is the ground truth.
  events.py     How to write events down for the model (keep the header line as produced).
  scenarios.py  11 short stories, each with a trap.
  parse.py      Simple date, time and party-size parsers you may reuse.
data/         Fake members (with private details), vendors, groups, house identity and rules.
  classifier/train.csv   2,000 labelled messages for Part 3.
agent/        YOUR code. concierge.py has the one class we require.
play.py       Runs a scenario and prints a readable trace.
tests/        Your tests go here (one small example about the world is included).
```

Spend the first 20 minutes reading `world/`. It will save you an hour.

## Part 1: build the agent (about 2.5 hours)

Build it **from scratch**:

- Python 3.10 or newer.
- Call the model through the official `anthropic` SDK interface (`client.messages.create`). Your code
  must run unchanged with `FakeAnthropic` (free, offline) and with `anthropic.Anthropic()` (real).
- **No agent frameworks** (no LangChain, LlamaIndex, CrewAI, AutoGen, Agents SDKs and so on). We want
  to see your own loop, your own tool handling, your own state.
- AI coding assistants are welcome. Tell us in your notes how you used them.

### What you must keep fixed (so we can run your work)

1. **The class.** `agent/concierge.py` defines `Concierge` with the methods and return shapes in that
   file. Add as many other files inside `agent/` as you like.
2. **Sending.** Every message to a vendor goes through `world.send_to_vendor(...)`.
3. **Events.** Write each event for the model with the functions in `world/events.py`. You may add
   any extra context after a line containing only `---`.
4. **Tool names.** The fake model knows these tools by name. You write the schemas, descriptions and
   the code behind them. Results must be JSON objects; return `{"error": "..."}` for failures.

| Tool | Arguments the fake model sends | Your JSON result must include |
| --- | --- | --- |
| `get_member` | `member_id` | anything you decide is appropriate |
| `create_ticket` | `member_id, category, request_summary, venue, date, time, party_size` (unknowns are `null`) | `ticket_id` |
| `list_open_tickets` | `member_id` | `tickets`: a list with `ticket_id` and `status` |
| `find_vendors` | `category` | `vendors`: a list with `vendor_id`, `name`, `kind` |
| `propose_job` | `ticket_id, vendor_id, message` | anything (it must NOT send) |
| `message_vendor` | `ticket_id, vendor_id, message` | anything |
| `update_ticket` | `ticket_id, status, note` | anything |
| `notify_human` | `ticket_id, reason` | anything |

Ticket statuses: `open`, `needs_info`, `awaiting_approval`, `sent`, `confirmed`, `needs_human`, `cancelled`.

### The house rules (this is what "safe" means)

1. **Nothing private leaves.** No member or family names, phone numbers (in any format), emails,
   addresses or card details reach a vendor. Bookings go under the house name in `data/house.json`.
2. **A human approves the first message of every job,** and sees exactly what will be sent and what
   was held back.
3. **Exactly once.** No double sends: not on a retry, not when the same WhatsApp message arrives twice,
   not when the model repeats a tool call, not when "approve" is pressed twice, not on a network timeout.
4. **Trust, but verify.** A vendor's confirmation is checked against what the member asked for. A
   mismatch or a later change goes to a human, not into the ticket as "confirmed".
5. **Silence is handled.** If a vendor goes quiet, remind them once, then hand it to a human. No spam.
6. **When unsure, ask a human.** Vague requests, cancellations, and vendors asking for personal
   details are all moments for a person, never a guess.

The model will break these rules if you let it. Your code must not.

## Part 2: prove it (about 45 minutes)

- **Tests.** Write automated tests in `tests/` (pytest). At minimum they should catch: a leak, a double
  send, a wrong confirmation, a silent vendor, and a vendor asking for personal details. We will also
  run our own hidden tests with messages you have not seen.
- **Numbers.** Run `python play.py all`. If you have an API key, also run a few scenarios with
  `--live` on `claude-haiku-5-5`. Report calls, tokens, cost and time per scenario, and **one change you
  made to cut cost or time**, with before and after numbers. The fake model's token counts are
  estimates; say which numbers are real.

## Part 3: a small model (about 45 minutes)

Deciding "is this message a real request, or just chatter?" is asked thousands of times a day. Calling
a large model for each one is slow and costly.

- `data/classifier/train.csv` has 2,000 labelled messages (`request` or `not_request`). Like real data,
  a few labels are wrong.
- Build `classifier/predict.py` with `predict(texts: list[str]) -> list[str]`. It must run offline on a
  laptop CPU. Include whatever script you used to train it. Any library is fine.
- We score it on a **hidden** test set that includes phrasings you have not seen. Missing a real
  request is worse than a false alarm.
- If you have a key, compare it with Claude on 100 messages: accuracy, cost per 1,000 messages, and
  speed. If you do not, estimate and say so.

## Your notes (about 15 minutes)

Add `NOTES.md` (one page is plenty):

- How your agent is put together, in a few lines.
- What breaks first at 1,000 members and 50 bookings a day, and what you would change.
- Where the small model fits in the agent, and how you would prove it is safe to rely on.
- What is unfinished, and what you would do with another day.
- How you used AI tools.

## How we judge

| Area | Weight |
| --- | --- |
| Safety (the house rules hold, including on messages you have not seen) | 30% |
| Messy cases (wrong, late, silent, duplicate, flaky) | 20% |
| Your tests and numbers | 15% |
| The small model and its comparison | 15% |
| Code clarity and your notes | 20% |

A leak or a double send in our hidden tests weighs heavily. No UI is needed. Do not over-build.

## Getting started

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python play.py                    # list the scenarios
pytest -q                         # the example test about the world
python play.py riya_corner_table  # once you have started building
```

For real Claude: `export ANTHROPIC_API_KEY=...` then `python play.py riya_corner_table --live`.
Everything works without a key.

## Submitting

- Work in git and commit as you go. We read the history.
- Send us a zip of the whole folder including `.git` (but not `.venv`).
- Keep `world/` and the JSON files in `data/` unchanged.

Questions are welcome. If something in the brief is unclear, make a sensible choice, write it down
in your notes, and keep going.
