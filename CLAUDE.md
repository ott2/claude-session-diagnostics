# claude-session-diagnostics

`csd` reads Claude Code session transcripts and measures cost and prompt-cache
behaviour. Python 3.11 or later, standard library only. The test suite runs on
3.11, 3.12, 3.13 and 3.14.

```bash
./venv/bin/python -m csd summary -v
./venv/bin/python -m unittest discover -s tests
```

`DESIGN.md` gives the terms, the cost model and the reason for each rule below.
Read it before you change the parser, the prices or the analyses.

## Rules

**Do not add a dependency.** The tool uses the standard library only.

**Use the terms in `DESIGN.md`.** Each concept has one name. A request is never a
turn. A cache is warm, never hot. Money above a warm read is a premium, never a
tax or waste. Documentation, comments and CLI output all use the same names.

**Write documentation in ASD-STE100.** Keep sentences short. Use the active
voice. Do not use figurative language.

**Remove duplicate records with one global key set**, `(requestId, message.id)`.
A key set for each file counts the backup directories two times. Examine
`ParseStats.duplication_factor` after each change to the parser.

**Search for transcripts recursively.** Most transcripts are nested below
`subagents/`. A `*/*.jsonl` pattern discards approximately one fifth of all cost.

**Keep measured values and inferred values separate.** `is_cold_start` is
inferred. `cache_miss_reason` is reported. They are different predicates. Do not
make them agree. Label which is which in any output.

**Take project labels from `cwd`**, never from the directory name. The directory
encoding cannot be decoded.

**Verify prices against the `claude-api` skill**, not from memory. Run `csd
models` after each change to `pricing.py` and check for models that have no
price.

**Show the total cost beside any premium.** A premium alone reads as the price of
the request.

**Format currency with `_money()`.**

**Cross-check a change to the cost calculation against a frozen copy of the
corpus**, not only against the unit tests. The fixtures are synthetic and cannot
find a systematic error in the prices.

## Cautions

**The corpus changes while you use it.** Work in this repository adds records.
Compare against a copy, not against a number from an earlier run.

**Old transcripts are incomplete.** Totals that cover an early period are
minimums. Do not read the deletion of old transcripts as a change in usage.
