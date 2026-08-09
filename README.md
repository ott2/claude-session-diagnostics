# claude-session-diagnostics

Cost and prompt-cache diagnostics for Claude Code session transcripts.
Python 3.11 or later, standard library only, no dependencies.

This tool answers two questions:

- How often must you use a session to keep its cache warm?
- What do you pay when the cache expires?

```bash
python -m csd summary          # totals, cache hit rate, cost of restarts
python -m csd models           # requests by model and the rates applied
python -m csd growth           # how cost accumulates as a session becomes longer
python -m csd ttl              # evidence for how long the cache stays warm
python -m csd decay            # measured cache decay against idle time
python -m csd cold             # the most expensive cold starts, in order
python -m csd startup          # startup cost, for all projects and for each one
python -m csd projects         # cost, restarts and startup cost for each project
python -m csd misses           # cache misses that the API reports, and their causes
python -m csd subagents        # cost and shape of delegated work
python -m csd coverage         # how complete the transcript record is
python -m csd sessions         # cost of each session
python -m csd trace SESSION    # request-by-request ledger for one session
python -m csd crossover        # one long warm session against several short ones
python -m csd export           # records for each session, as JSON
```

Global flags: `--root` (transcript directory, default `~/.claude/projects`),
`--project SUBSTRING`, `--project-depth N`, `--ttl MINUTES`.

Project labels come from the `cwd` that each transcript records. The tool shows
the last `--project-depth` parts of that path. The default depth is 2, for
example `acme/acme-core`.

The directory names below `~/.claude/projects` replace each `/` with `-`. That
encoding cannot be decoded: the name `-src-acme-acme-core` agrees with
`acme/acme-core` and equally with `acme-acme/core`. Therefore the tool uses the
recorded `cwd` instead. `--project` matches against the complete working
directory.

## Install

The tool has no dependencies. You can run it from a copy of this repository:

```bash
git clone https://github.com/keziacousins/claude-session-diagnostics
cd claude-session-diagnostics
python -m csd summary
```

To install the `csd` command instead:

```bash
pip install .
csd summary
```

## Terms

This document uses one name for each concept. `DESIGN.md` defines all of them.
The four that matter most here:

- **lane** — one transcript and the one prompt cache that serves it
- **request** — one billed API call, and the unit of position inside a lane
- **expiry** — the event in which a cache stops being valid
- **premium** — the money paid above the cost of a warm read

## Results from the local corpus

The figures below come from approximately 26,000 requests in 199 sessions.
Session counts, token counts and ratios are from that corpus. Money figures are
per session or per request. This document does not report total spend.

### 0. What the corpus establishes about the cache TTL

Run `python -m csd ttl`. There are three separate questions.

**Which TTL the client requests.** The API reports this in `cache_creation`:

| lane | 5m writes | 1h writes |
|---|---|---|
| main | 229 | 26,152 |
| subagent | 16,965 | 11,320 |

Main lanes request 1 hour. Subagent lanes mostly request 5 minutes, which agrees
with a lane that lives approximately 1 minute.

**When the cache stops being valid.** The change is abrupt, not gradual:

| gap | n | median rewrite | cache dead |
|---|---|---|---|
| 55–58 min | 14 | 3.2% | 21.4% |
| **58–60 min** | 5 | **0.6%** | **0.0%** |
| **60–62 min** | 5 | **96.3%** | **80.0%** |
| 62–65 min | 5 | 100.0% | 100.0% |

Subagent lanes fail at the same hour, although they mostly request 5 minutes. A
prompt mixes prefixes that were written with different TTLs. The part that stays
warm is the 1-hour part that the lane shares with its parent.

**Whether the clock starts at creation or at last use.** Hold the gap below 30
minutes and change the age of the lane:

| lane age | n | median rewrite |
|---|---|---|
| <1h | 8,494 | 0.91% |
| 3–6h | 2,165 | 0.36% |
| 12–24h | 3,424 | 0.24% |
| >24h | 5,780 | 0.25% |

The value stays flat across 26,000 samples. Therefore the hour starts at the last
use, not at the creation. Each use of a session sets the clock back to zero. A
lane that is one day old holds its cache as well as a new lane. The cache does
not decay, and you do not need to rebuild it at intervals.

**Early death is rare, and it is mostly self-inflicted.** In 79 of 25,769 pairs
(0.31%) the cache stopped being valid in less than 55 minutes. The API explains
40 of those with `tools_changed` or `system_changed`: the request changed shape
during the conversation. Eviction pressure is not the cause.

Therefore the rule is simple. **Use a session one time each hour, and its cache
stays warm.**

### 1. The cache stays complete for one hour, then it is gone

This is the median fraction of the prompt that the client had to write again, in
groups by the idle gap since the previous request:

| idle gap | n | rewritten | cache read | premium |
|---|---|---|---|---|
| <1m | 22,613 | 0.4% | 222K | $0.008 |
| 1–5m | 1,959 | 0.8% | 212K | $0.016 |
| 5–15m | 607 | 0.8% | 231K | $0.018 |
| 15–30m | 180 | 0.9% | 202K | $0.021 |
| 30–60m | 138 | 0.8% | 201K | $0.018 |
| **1–2h** | **106** | **100.0%** | **0** | **$2.20** |
| 2–24h | 212 | 96.2% | 15K | $2.50 |
| >24h | 81 | 97.4% | 14K | $1.70 |

Nothing decreases gradually. Claude Code writes cache entries with a 1-hour TTL
(25,848 of 26,147 writes in this corpus). The complete context stays valid until
the TTL, and then all of it is gone.

**Therefore any gap of less than approximately 55 minutes is free. To cross the
hour costs a complete rebuild of the context**, at a median of $2.20 for one
request, and up to $8.21 for the largest sessions here.

The remaining read of 14K to 15K tokens in the groups above 2 hours is the static
prefix: the system prompt and the tool schemas. Other sessions that run at the
same time keep that prefix warm. This session does not.

### 2. Cold restarts were 17% of all cost

17% of the cost of this corpus went on writing context again that a warm cache
would have served at one tenth of the price. 116 of 199 sessions had at least one
expiry during the session. There were 399 expiries in total.

This is the largest single item that the operator can act on.

### 3. Startup cost is observable, and varies by a factor of 2.6 between projects

The context increases steadily and reaches no plateau: approximately 29K tokens
at request 1, 52K by request 10, and 104K by request 40. Therefore no inflection
marks the end of orientation.

Instead the tool takes the boundary from an observable event: **the first `Edit`
or `Write` of a cold session.** Before that event the session reads, searches and
runs commands. The context at that moment is the measured cost to become
productive.

| | tokens | what it is |
|---|---|---|
| fixed prefix (request 1) | **29K** | system prompt, tool schemas, project instructions |
| ready to work (first change to a file) | **81K** | median of 141 cold sessions, at approximately request 19 |

`csd startup` reports this for each project, in tokens and in money. The money is
the cumulative cost of every orienting request, and the cost to build that
context again after an expiry:

| | context | at req | cost | rebuild |
|---|---|---|---|---|
| all projects | 82K | 19 | $2.02 | $0.79 |
| bluebird/bluebird-v2 | 123K | 36 | $4.61 | $1.17 |
| orchard/atlas | 94K | 20 | $2.26 | $1.02 |
| src/side-project | 58K | 14 | $1.71 | $0.55 |
| acme/acme-frontend | 46K | 17 | $1.21 | $0.44 |

**To become ready costs approximately 2.5 times the cost to build the same
context again** ($2.02 against $0.79). Orientation is a process of approximately
19 requests that read and search. Each of those requests has its own reads and
its own output. A rebuild is one cold write.

The projects also change order between the two columns. The cost follows the
request count and the output as well as the final size of the context.

### 3a. The carry cost applies to every request, and it accumulates

Every request reads the complete context again. Therefore the cost of a request
increases with the context, and the cumulative cost grows faster than the request
count. Run `csd growth`:

| request | context | cost each | cumulative |
|---|---|---|---|
| 1 | 28,116 | $0.1287 | $0.13 |
| 50 | 117,445 | $0.0918 | $4.14 |
| 100 | 189,358 | $0.1123 | $9.73 |
| 200 | 296,164 | $0.1819 | $24.28 |

Across lanes that had no expiry, the cumulative cost grows as approximately
`requests^1.18`. This is faster than linear but slower than quadratic.

Compaction is not the reason for the lower exponent. Compaction almost never
occurs here: 10 of 24,925 requests reduced the context by more than 20K tokens,
which is 0.04%. The reason is that the context grows more slowly as the session
continues: approximately 2.2K tokens for each early request, and approximately
1.1K after request 100. If the growth stays constant, the exponent moves towards
2.

This is the carry cost for each request, before the model generates any output:

| context | Opus ($5/M) | Fable ($10/M) |
|---|---|---|
| 200K | $0.100 | $0.200 |
| 400K | $0.200 | $0.400 |
| 800K | $0.400 | $0.800 |

Long lanes in this corpus reach 651K tokens at p90 and 894K at p99. Therefore the
end of a large session pays **$0.33 to $0.80 for each request, only to read
itself again.** This is what makes a long session expensive. The carry cost is
larger than the restart premium, and it is less visible.

### 4. One long warm session does not cost less than several short ones

The first hypothesis was that one long warm session costs less than several short
sessions, because each short session pays for startup context again. Startup is
too cheap for that hypothesis to hold:

- To make a new session productive costs approximately 81K tokens, which is
  **$0.81** on Opus.
- To carry a 600K context instead of a 200K context costs **$0.16 for each
  request**, and it continues for the life of the session, because every request
  reads the complete prompt again.

This is 200 requests of work on Opus 5:

| | sess | reqs | req ea | peak ea | ready | growth | carry | output | restart | total |
|---|---|---|---|---|---|---|---|---|---|---|
| one long session | 1 | 219 | 219 | 600K | $2.02 | $5.18 | $34.08 | $2.26 | $18.00 | **$61.55** |
| 5 short sessions | 5 | 295 | 59 | 200K | $10.10 | $5.92 | $14.08 | $2.26 | $0.00 | **$32.36** |

**The costs and `reqs` are totals for the complete strategy. The `ea` columns are
values for one session.** Both strategies do the same 200 productive requests.
The short sessions also orient five times, which is 95 requests and $10.10
against 19 requests and $2.02.

**The tool charges orientation from measurement. It does not calculate
orientation from a token count.** To write an 82K prefix costs $0.82. To reach
that state costs **$2.02**, because it takes 19 requests that read and search,
each with its own reads and its own output. To charge orientation as one cold
write makes the short strategy appear 2.5 times too cheap, five times over.

The short strategy costs 47% less, if the work truly divides.

**Restart counts are observed, not assumed.** In this corpus a session of
approximately 200 main requests has a median of **3** expiries (p25 1, p75 5).
Only 20% have none. A session of approximately 40 requests has a median of **0**,
and 51% have none. A default of zero would favour the long session, so
`crossover` reads the median for each length and reports it. Use `--restarts` and
`--short-restarts` to set the values yourself.

**Rework decides the comparison.** Rework is the extra requests that short
sessions need to rebuild understanding that the long session still holds in
context: to read the same files again, and to derive the same structure again.

```
python -m csd crossover --rework 0.5
```

**The break-even point is approximately 88% rework** at the observed restart
rate.

### How many pieces before the short strategy stops winning?

Orientation paid N times becomes the larger cost. This divides 200 productive
requests on Opus, and the long session has its observed 3 restarts:

| sessions | orientation | one long | split | lower cost |
|---|---|---|---|---|
| 2 | $4.04 | $61.55 | $22.75 | split |
| 5 | $10.10 | $61.55 | $32.36 | split |
| 10 | $20.21 | $61.55 | $48.38 | split |
| **20** | $40.42 | $61.55 | $80.42 | **one long session** |
| 40 | $80.83 | $61.55 | $144.50 | **one long session** |

If the operator uses the long session attentively and never crosses the hour, the
long session costs less from **10 sessions**, not from 20. Therefore the answer is
between the two extremes. A small number of substantial sessions costs less than
one very large session, and less than many small sessions.

**The model charges output tokens for each request**, at the observed median of
$0.011. Output tokens cancel when both strategies do the same number of requests.
They do not cancel under rework, where the short strategy does more requests. To
omit them favours the short strategy.

The peaks that you supply set a growth rate for each request. Therefore **rework
carries its own context**: to do 55% more requests also means a larger context on
each request, and the carry cost grows faster than linearly. An earlier version
fixed the peak context and ignored the request count, which made rework almost
free and put the break-even point at 114%.

The model reports the implied growth rate for each strategy, and gives a warning
when the two rates disagree. The peaks and the session counts are separate
inputs, and together they can describe a scenario that cannot occur.

The conclusion does not change much with the startup figure. The break-even point
moves very little as startup goes from 29K to 60K to 82K tokens. Rework is the
input that changes the answer, and that is why it stays an explicit input.

Therefore the guidance is:

- **The short strategy costs less** when the work divides well enough to need
  less than approximately 2.4 times the requests. To carry a large context is a
  cost on every request, not a single cost.
- **Never let a large session stay idle across the hour.** A 600K session that
  expires two times costs $12 more, which removes the complete advantage of
  holding the context. If you hold a large context, use it actively.

The model prices tokens only. The transcripts cannot judge whether a smaller
context can do the work.

### 5. Subagents behave differently, and they are one fifth of the cost

Subagent transcripts are nested at
`<project>/<session-uuid>/subagents/agent-*.jsonl`. They are 1,863 of 2,094 files.
They record the `sessionId` of the parent, so the tool attributes their cost to
the session that started them. They do not behave like a main lane:

| | main lane | subagent lane |
|---|---|---|
| lanes | 200 | 1,783 |
| requests each | 73 | 9 |
| duration | 280 min | **0.9 min** |
| peak context | 172K | 63K |
| gaps longer than the TTL | 1.53% | **0.09%** |

A subagent receives a brief, works for approximately one minute, and stops. It
starts cold because that is its design, and it almost never crosses the cache
TTL. Therefore the cache analyses (`decay`, `cold`, and the restart premium) use
**main lanes only** by default. `--include-subagents` adds them. The tool always
counts their cost.

To include them makes the median cache read approximately one half of its true
value for main lanes (223K to 115K), and makes the `<1m` group two times larger.
That is the distortion that the separation prevents.

The share of work that a session delegates varies greatly between projects. It is
71% of cost in `studio-tools` and 0.2% in `orchard/survey`. Run `python -m csd
subagents`.

### 6. Approximately one half of the record is deleted, and the loss is not equal across time

```
month     intact  orphaned      status
2026-01        0        64   FRAGMENTS
2026-02        0        69   FRAGMENTS
2026-03        0        42   FRAGMENTS
2026-04       24         0    complete
...
```

Claude Code deletes old top-level transcripts. It does not delete the nested
`subagents` directories. Therefore 175 sessions remain only as subagent
fragments, and the cost of their main lanes cannot be recovered.

**Any total that covers January to March 2026 is a minimum, not a measurement.**
`csd summary` gives a warning, and `csd coverage` shows the range that is safe to
compare over. In this corpus that range starts in April.

## Correctness notes

**Deduplication is necessary, and it must use one global key set.** A transcript
writes one `assistant` line for each content block. Every one of those lines
repeats the same complete `usage` object. A tool that adds the usage of each line
makes the cost approximately two times too large.

The tool keys requests on `(requestId, message.id)` and counts each key one time.
The key set covers all files. It is not one key set for each file: Claude Code
writes complete backups of a session into `.cwd-fix-backup-*`, and those copies
are identical to the originals. On inspection, 484 of 484 message ids matched. A
key set for each file would count them two times once the search is recursive.
The search also ignores hidden directories.

**Transcripts nest.** A single-level `*/*.jsonl` pattern finds 231 of 2,094 files
and misses every subagent, which is one fifth of all cost. Therefore discovery is
recursive.

The tool also handles three other cases:

- It excludes `<synthetic>` records. These are client-side error messages, not
  billed API calls.
- It attributes the aggregate `cache_creation_input_tokens` of old transcripts to
  the 1-hour TTL. Those transcripts do not report the split between 5 minutes and
  1 hour.
- It reports unknown model ids. It does not price them silently at zero.

The total cost agrees to the cent with an independent implementation, across a
frozen copy of more than 26,000 requests.

## Measured values and inferred values

The two are easy to confuse, so this section states which is which.

**Measured, directly from the `usage` object of the API.** The API puts every
prompt token in exactly one of three fields. Therefore these are counts, not
estimates:

| field | meaning |
|---|---|
| `input_tokens` | not cached, full price |
| `cache_creation_input_tokens` | written to the cache |
| `cache_read_input_tokens` | served from the cache |
| `cache_creation.ephemeral_{5m,1h}_input_tokens` | which TTL the client wrote |
| `output_tokens` | generated |

Therefore **the cache hit rate is measured, not inferred.** It is
`cache_read / (input + cache_write + cache_read)`, a ratio of reported counts.

There is no flag for a hit or a miss on one request. A cache serves part of a
prompt: a typical request reads most of its prefix from the cache and writes a
small addition. Therefore the hit rate must be weighted by tokens.

**Also measured, on newer clients.**
`message.diagnostics.cache_miss_reason` states why a lookup failed. Run `csd
misses`. The field is present on 61% of requests here:

| reason | count | share of miss premium | avoidable |
|---|---|---|---|
| `previous_message_not_found` | 355 | 90.0% | no |
| `tools_changed` | 60 | 6.1% | **yes** |
| `system_changed` | 13 | 3.2% | **yes** |
| `unavailable` | 140 | 0.6% | no |
| `model_changed` | 3 | 0.1% | **yes** |

Approximately one tenth of the premium from reported misses comes from requests
that changed shape during a conversation. The operator can avoid that part.

**Inferred, and labelled as inferred:**

- **cold start** — a context of 20K tokens or more, with less than 50% served
  from the cache. This is a heuristic for cost.
- **restart** — a gap longer than the TTL, taken from the timestamps.
- **cold-start premium** — a comparison against a different outcome: the same
  tokens at the read rate instead of the write rate.
- **ready to work** — the first `Edit` or `Write`.

The inferred cold start and the reported miss reason agree on 384 requests, but
they measure different things. The disagreements have explanations, and they are
not errors:

- Of 277 requests that the tool marks and the API does not, 147 are the first
  request of a lane. No cache existed to miss, but the client still had to build
  the context.
- Of 188 requests that the API marks and the tool does not, the median request
  still served **99.3%** of its prompt from the cache. That is a partial miss,
  not a cold rebuild.

The tool keeps both signals.

## Cost model

The tool prices every request at the rate of its own model, and at the rate that
applied on its own date. Run `python -m csd models`:

| model | in $/M | out $/M | requests | share of cost |
|---|---|---|---|---|
| claude-opus-4-7 | 5.00 | 25.00 | 12,144 | 39.5% |
| claude-opus-5 | 5.00 | 25.00 | 9,044 | 20.6% |
| claude-fable-5 | 10.00 | 50.00 | 2,813 | 12.8% |
| claude-opus-4-6 | 5.00 | 25.00 | 7,931 | 10.8% |
| claude-opus-4-8 | 5.00 | 25.00 | 3,805 | 9.3% |
| claude-sonnet-5 | 3.00 | 15.00 | 8,092 | 4.4% * |
| claude-haiku-4-5 | 1.00 | 5.00 | 9,298 | 1.4% |

`*` The tool applied the introductory price.

**Rates are not constant over time.** Sonnet 5 started at $2/$10 for each million
tokens, until 2026-08-31, and then moved to $3/$15. Therefore the tool prices each
request against the rate that applied on its timestamp. To price the whole corpus
at the current rate makes the earlier requests too expensive.

The tool normalises model ids before it looks up a price. All of these resolve to
the same rate:

- a date snapshot, for example `claude-haiku-4-5-20251001`
- a `[1m]` context suffix
- a `-fast` suffix
- the Bedrock prefix `anthropic.`

`csd models` reports unknown models. It does not price them silently at zero.
Where the transcript reports fast mode in `usage.speed`, the tool bills at the
Opus fast rates.

The cache multipliers apply to the input rate:

| | multiplier |
|---|---|
| 5-minute cache write | 1.25x |
| 1-hour cache write | 2.00x |
| cache read | 0.10x |

The **cold-start premium** is `tokens x input_rate x (2.00 - 0.10)`. This is the
money paid above the cost of a warm read for the same tokens. It is the price of
letting the cache expire.

### Worked example

This is one line from `csd cold`, followed through the complete calculation:

```
2026-07-29 06:14   434K   7h19m   $8.57   $0.64   $7.93   orchard/atlas
                                   cost  if warm  premium
```

For that single request on `claude-fable-5` ($10/M in, $50/M out), the API
reported:

| field | tokens |
|---|---|
| `cache_creation_input_tokens` (1h) | 417,356 |
| `cache_read_input_tokens` | 16,715 |
| `input_tokens` | 2 |
| `output_tokens` | 4,153 |
| **context** | **434,073** |

**Cold. What the request cost:**

```
417,356 x $10/M x 2.00  (1h cache write) = $8.3471
 16,715 x $10/M x 0.10  (cache read)     = $0.0167
      2 x $10/M x 1.00  (not cached)     = $0.0000
  4,153 x $50/M         (output)         = $0.2077
                                           -------
                                           $8.5715
```

**Warm. What the same request would have cost**, with those 417,356 tokens read
from the cache instead of written again:

```
417,356 x $10/M x 0.10                   = $0.4174
 + read / input / output unchanged       = $0.2244
                                           -------
                                           $0.6417
```

**The premium is $8.5715 − $0.6417 = $7.93.** That reduces exactly to
`417,356 x $10/M x (2.00 − 0.10)`.

### The client pays for a cold restart one time, not two times

A reader can assume that a cold restart pays the input rate to read 400K tokens
again, and then a write rate to cache them again. That is not correct.

**The three token fields divide the prompt.** Each token is in exactly one field.
The 2.00x on a 1-hour cache write is the complete price to process that token and
to cache it. The evidence above is `input_tokens: 2`. If the client read the
context and then cached it, the context would appear in both fields.

The client also does not write the context again on later requests. This is `csd
trace` on that session:

```
   time     gap    input  cache_write  cache_read   context     cost
22:55:00                2          359     433,232   433,593   $0.46
06:14:57    440m        2      417,356      16,715   434,073   $8.57  <- cache expired
06:15:41      1m        2        4,329     434,071   438,402   $0.58
```

One minute after the restart of $8.57, the next request costs **$0.58**. The
client reads the 434K tokens at 0.10x and writes only 4,329 new tokens. Across
25,685 real warm requests, the tokens written equal the growth of the context to
within ±1 token, and 86.9% are exact. Therefore the client truly never writes the
cached prefix again.

**A restart is a single cost, not a continuous penalty.** You pay 2.00x one time
on the complete context, and immediately return to reading it at 0.10x. Therefore
the correction is simply to not cross the hour. The damage is one event, and the
next request repairs it completely.

This example makes two other things concrete:

- To resume was **not** free, even warm. It cost $0.64, because every request
  reads the context again.
- The line above it in `csd cold` shows 864K tokens on Opus 4.7 at $8.64, which is
  almost the same cost as 434K tokens on Fable. **At $10/M against $5/M, the
  choice of model changes the cost as much as the size of the context does.**

## Layout

```
csd/pricing.py    model price table, cache multipliers, cost arithmetic
csd/parser.py     JSONL discovery, deduplication, Request records
csd/session.py    sessions, warm segments, cold-start detection
csd/analysis.py   decay curve, restart accounting, strategy comparison
csd/cli.py        argparse CLI
tests/            unittest suite (98 tests)
DESIGN.md         terms, cost model and measurement decisions
```

```bash
python -m unittest discover -s tests
```

## Prior art

`ccusage` is the reference for the cost calculation. This project follows its
`(requestId, message.id)` deduplication. It adds the split between the 5-minute
and 1-hour caches, the analysis of segments, and the accounting of restarts.

## Licence

MIT. See `LICENSE`.
