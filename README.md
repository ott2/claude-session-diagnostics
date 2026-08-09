# claude-session-diagnostics

[![tests](https://github.com/keziacousins/claude-session-diagnostics/actions/workflows/tests.yml/badge.svg)](https://github.com/keziacousins/claude-session-diagnostics/actions/workflows/tests.yml)

Cost and prompt-cache diagnostics for Claude Code session transcripts.
Python 3.11 or later, standard library only, no dependencies.

Claude Code records every session as a JSONL transcript below
`~/.claude/projects`. Each assistant record carries the token counts that the API
reported: what was sent uncached, what was written to the prompt cache, and what
was read back from it. `csd` reads those records and reports what they cost.

It answers two questions:

- How often must you use a session to keep its cache warm?
- What do you pay when the cache expires?

The tool reads your transcripts only. It sends nothing anywhere, and it makes no
API calls.

## Install

There are no dependencies. Run it from a copy of this repository:

```bash
git clone https://github.com/keziacousins/claude-session-diagnostics
cd claude-session-diagnostics
python -m csd summary
```

Or install the `csd` command:

```bash
pip install .
csd summary
```

## Use

```bash
csd summary          # totals, cache hit rate, cost of restarts
csd models           # requests by model and the rates applied
csd growth           # how cost accumulates as a session becomes longer
csd ttl              # evidence for how long the cache stays warm
csd decay            # measured cache decay against idle time
csd cold             # the most expensive cold starts, in order
csd startup          # startup cost, for all projects and for each one
csd projects         # cost, restarts and startup cost for each project
csd misses           # cache misses that the API reports, and their causes
csd subagents        # cost and shape of delegated work
csd coverage         # how complete the transcript record is
csd sessions         # cost of each session
csd trace SESSION    # request-by-request ledger for one session
csd crossover        # one long warm session against several short ones
csd export           # records for each session, as JSON
```

Every command accepts `--root` (transcript directory, default
`~/.claude/projects`), `--project SUBSTRING`, `--project-depth N` and
`--ttl MINUTES`. Use `csd <command> --help` for the options of one command.

Start with `csd summary` for the totals, then `csd cold` to see which sessions
cost the most to restart.

### Project labels

Project labels come from the `cwd` that each transcript records. The tool shows
the last `--project-depth` parts of that path, and the default is 2, for example
`acme/acme-core`.

The directory names below `~/.claude/projects` replace each `/` with `-`, and
that encoding cannot be decoded: the name `-src-acme-acme-core` agrees with
`acme/acme-core` and equally with `acme-acme/core`. The recorded `cwd` is used
instead. `--project` matches against the complete working directory.

## Documentation

- **[FINDINGS.md](FINDINGS.md)** — what one corpus of approximately 26,000
  requests shows about cache lifetime, restart cost and session length. These are
  **hypotheses from a single user's usage**, not established facts. Each section
  names the command that reproduces it, so you can test the claims against your
  own transcripts. Disagreements are welcome.
- **[DESIGN.md](DESIGN.md)** — the terms, the cost model and every measurement
  decision, with the reason for each. Read this before you trust a number, or
  before you change the parser or the prices. Review of the method is more
  valuable than agreement with the numbers.

## Contributing

Two kinds of contribution are especially useful:

1. **Run it on your own corpus** and report where your results differ from
   `FINDINGS.md`. Include the command and its output.
2. **Review the method.** If the parsing, the deduplication or the cost
   arithmetic is wrong, every number here is wrong with it.

```bash
python -m unittest discover -s tests
```

The suite has 98 tests and runs on Python 3.11 through 3.14. It uses synthetic
fixtures, so it cannot catch a systematic pricing error — `DESIGN.md` explains
how to cross-check cost changes against a frozen copy of a real corpus.

## Layout

```
csd/pricing.py    model price table, cache multipliers, cost arithmetic
csd/parser.py     JSONL discovery, deduplication, Request records
csd/session.py    sessions, warm segments, cold-start detection
csd/analysis.py   decay curve, restart accounting, strategy comparison
csd/cli.py        argparse CLI
tests/            unittest suite
DESIGN.md         terms, cost model and measurement decisions
FINDINGS.md       results from one corpus, framed as hypotheses
```

## Prior art

`ccusage` is the reference for the cost calculation. This project follows its
`(requestId, message.id)` deduplication. It adds the split between the 5-minute
and 1-hour caches, the analysis of segments, and the accounting of restarts.

## Attribution

Authored by Claude Opus 5. Prompted, reviewed and tested by Kezia Cousins.

## Licence

MIT. See `LICENSE`.
