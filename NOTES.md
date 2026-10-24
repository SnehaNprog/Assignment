# Notes

## How the agent is put together

- **`agent/concierge.py`** holds the agent: our own loop (model call, run tools, return JSON results, at most 8 steps), the tools, and the state (tickets, proposals, alerts, sent keys). Its top docstring maps each house rule to the code that enforces it.
- **Code enforces the rules, not the prompt.** The model never sees private member fields (`get_member` returns only preferences). Every vendor message is built from ticket fields (`agent/outbound.py`); the model's draft is discarded. One function, `_send`, scans the final text against every member's details and generic phone, email and card shapes (`agent/privacy.py`), then sends with a fixed idempotency key.
- **Code decides, without the model:**
  - whether a confirmation matches the ticket, field by field (`agent/checks.py`)
  - whether a vendor is asking for personal details
  - silence timers: one reminder at 30 minutes, then a person at 60
  - replies on cancelled or already-confirmed tickets
- **The model is used for** reading member messages and plain vendor replies. Each tool re-checks the rules: one job per ticket, identical tickets reused, only a verified reply can confirm.

**Choices I made where the brief was open:**
- A member's cancel of a job already sent is sent to the vendor automatically, using a fixed template, and alerts a person. The scenario requires BookBot to be told.
- A confirmation that leaves out any field is treated as unverified.
- The same text from the same sender within 10 minutes is treated as a duplicate.
- The project needs Python 3.10+; I used 3.12.

## Results

- **Tests:** 45 pytest tests. To check the tests can fail, I broke the agent on purpose 7 ways (forwarded member text, removed the leak gate, removed idempotency keys, trusted confirmations, reminded forever, ignored requests for personal details, allowed double approve). The tests caught all 7.
- **Numbers:** `NUMBERS.md` (from `python bench.py`). The cost cut was skipping the model when the classifier says chatter: on a 300-message day, calls went from 539 to 397 and cost from $0.074 to $0.059 (21% less). Only the call counts are real; the token counts are the fake model's estimates. There was no live run because I had no API key.
- **Small model:** `classifier/`. It is TF-IDF on words and character n-grams, fed into logistic regression. I cleaned the labels first: majority vote on duplicates, then dropped 27 rows that cross-validation confidently contradicted.
  - Cross-validation gives 99.6% accuracy, but that is inflated by templated duplicates.
  - On 60 hand-written messages in a new style, the classifier scored 0.88 accuracy and 0.97 recall.
  - The agent's gate (classifier OR keyword list) missed 0 of 30 requests, at the cost of 10 false alarms out of 30 chatter messages.
  - Against Claude: ~$0 and ~5 ms per message for the classifier, versus an **estimated** $0.01 per 1,000 messages and ~0.5 s per message for Haiku. Claude's accuracy was not measured (no key; `classifier/compare_claude.py` runs the comparison when a key is set).

## What breaks first at 1,000 members and 50 bookings a day

1. **State lives in memory.** A restart loses tickets, timers and sent keys, and could resend a job. I would move state to Postgres, with unique constraints on idempotency keys, and send through an outbox table so that "approved" and "sent" are written in one transaction.
2. **The people handling alerts.** Every cancellation, mismatch and false alarm becomes an alert. At this volume they need priorities, grouping per ticket, and an "acknowledge" action.
3. **Vendor replies parsed with regexes.** These work for BookBot only. Each new vendor needs its own adapter or a structured reply format. Until then, anything unparsed goes to a person.
4. **Cost and latency.** Most of the input tokens on each call are the tool schemas and system prompt, which repeat every time. Prompt caching (once the prompt is over the minimum size) and handling more steps in code would cut both.

## Where the small model fits, and how to prove it is safe

It sits in `agent/gate.py`, before any model call on a member message. Cancellations always bypass it. It only saves money: a skipped message is still in the WhatsApp group for the team to see. To prove it safe:
- Run it in shadow mode for a few weeks: the model still sees every message, and we log what the gate would have skipped.
- Have a person audit a sample of skipped messages each week.
- Switch it on only if recall on real, human-labelled traffic stays at or above 99%. Keep the keyword net in front of it, and re-check monthly for drift.

## Unfinished, and what I would do with another day

- A live run on `claude-haiku-5-5`, plus a measured Claude comparison on the 100 messages.
- Model-written follow-ups (`message_vendor`) are scrubbed and need approval, but the scrub cannot catch a name it does not know unless it appears as "Name's".
- The extras allowlist drops special requests it does not recognise.
- Booking changes, and categories other than dining, go to a person rather than being automated.
- Members are never messaged back.
- The unseen test set is small and I wrote it myself.
- Any 6-digit number is flagged as a postal code. That is safe but noisy.
- handled some more edge casses 

## How I used AI tools
Due to time constraints, I used AI as a junior developer to accelerate implementation while retaining ownership of the architecture and engineering decisions. I defined the architecture, broke the work into small, sequential steps, and provided explicit instructions for each change. After every step, I thoroughly reviewed the code, tested the implementation, and verified the results before moving on to the next task.

When time permitted, I handled more of the coding manually. I also leveraged AI to generate test cases, stress-test the system by exploring edge cases and failure scenarios, and create datasets for evaluating model performance. This allowed me to speed up development without compromising my focus on code quality, correctness, and rigorous testing.
