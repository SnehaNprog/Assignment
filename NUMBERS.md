# Numbers

Produced by `python bench.py` (fake model). Re-run with `python bench.py --live` for real Claude.

**Which numbers are real:**
- `calls` are real counts of `messages.create`.
- `input tok` / `output tok` / `cost` come from the fake model's ESTIMATE (characters / 4), priced at
  `world/pricing.py` rates for claude-haiku-5-5. Not real usage. No live run was made (no API key).
- `model s` is near zero because the fake model answers instantly; real Haiku would be roughly 0.5-1.5 s
  per call (estimate). `wall s` on `tara_chatter` is the one-off load of the classifier (~0.7 s), not per message.

### before: pre-filter OFF (claude-haiku-5-5, fake model: tokens are estimates (chars / 4))

| scenario | calls | input tok | output tok | cost | model s | wall s |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| riya_corner_table | 7 | 8,432 | 491 | $0.0011 | 0.00 | 0.00 |
| mehta_birthday_wrong_date | 7 | 8,501 | 513 | $0.0011 | 0.00 | 0.00 |
| kabir_hinglish_double | 7 | 8,470 | 538 | $0.0011 | 0.00 | 0.00 |
| sameer_unclear | 5 | 6,263 | 291 | $0.0008 | 0.00 | 0.00 |
| priya_cancel_before_approval | 8 | 9,423 | 472 | $0.0012 | 0.00 | 0.00 |
| priya_cancel_after_send | 8 | 9,405 | 472 | $0.0012 | 0.00 | 0.00 |
| riya_silent | 5 | 6,211 | 350 | $0.0008 | 0.00 | 0.00 |
| riya_asks_phone | 5 | 6,208 | 355 | $0.0008 | 0.00 | 0.00 |
| mehta_asks_card | 5 | 6,217 | 354 | $0.0008 | 0.00 | 0.00 |
| kabir_flaky_network | 7 | 8,193 | 431 | $0.0010 | 0.00 | 0.00 |
| tara_chatter | 3 | 2,781 | 54 | $0.0003 | 0.00 | 0.00 |
| **all 11 scenarios** | 67 | 80,104 | 4,321 | $0.0102 | 0.00 | 0.01 |
| **a day: 300 member messages** | 539 | 632,068 | 21,513 | $0.0740 | 0.03 | 0.03 |

### after: pre-filter ON (claude-haiku-5-5, fake model: tokens are estimates (chars / 4))

| scenario | calls | input tok | output tok | cost | model s | wall s |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| riya_corner_table | 7 | 8,432 | 491 | $0.0011 | 0.00 | 0.00 |
| mehta_birthday_wrong_date | 7 | 8,501 | 513 | $0.0011 | 0.00 | 0.00 |
| kabir_hinglish_double | 7 | 8,470 | 538 | $0.0011 | 0.00 | 0.00 |
| sameer_unclear | 5 | 6,263 | 291 | $0.0008 | 0.00 | 0.00 |
| priya_cancel_before_approval | 8 | 9,423 | 472 | $0.0012 | 0.00 | 0.00 |
| priya_cancel_after_send | 8 | 9,405 | 472 | $0.0012 | 0.00 | 0.00 |
| riya_silent | 5 | 6,211 | 350 | $0.0008 | 0.00 | 0.00 |
| riya_asks_phone | 5 | 6,208 | 355 | $0.0008 | 0.00 | 0.00 |
| mehta_asks_card | 5 | 6,217 | 354 | $0.0008 | 0.00 | 0.00 |
| kabir_flaky_network | 7 | 8,193 | 431 | $0.0010 | 0.00 | 0.00 |
| tara_chatter | 0 | 0 | 0 | $0.0000 | 0.00 | 0.52 |
| **all 11 scenarios** | 64 | 77,323 | 4,267 | $0.0099 | 0.00 | 0.53 |
| **a day: 300 member messages** | 397 | 490,876 | 18,957 | $0.0586 | 0.02 | 0.09 |

### the change: skip the model when the small classifier says chatter

| workload | calls before → after | cost before → after | saved |
| --- | --- | --- | ---: |
| 11 scenarios | 67 → 64 | $0.0102 → $0.0099 | 3% |
| 300-message day | 539 → 397 | $0.0740 → $0.0586 | 21% |

**Reading the change.** Chatter is about half of member messages but costs one call each, while a real
request costs 5-8 calls, so skipping chatter saves ~21% of a realistic day, and 100% on pure chatter
(`tara_chatter`: 3 calls → 0). In the day sample, 25 chatter messages still reach the model (keyword net:
"dinner", "table", "?"), which is the price of missing no real request. The gate skipped 2 messages labelled
`request`; both are mislabelled chatter ("Good morning ☀️"-style), see `classifier/train.py` output.
