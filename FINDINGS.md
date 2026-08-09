# Findings

**These are hypotheses, not established facts.**

Every figure in this document comes from one person's Claude Code corpus:
approximately 26,000 requests in 199 sessions, on one machine, from one way of
working. A different workload can give different results. Read each section as a
claim to test, not as a measurement that you can apply directly to your own work.

Some claims are more portable than others. The behaviour of the cache is a
property of the API, so it should reproduce for anybody. The cost figures depend
on how the operator works: how long a session runs, how much the operator
delegates, and which model the operator selects. Treat those as an example, not
as a standard.

## Test these claims against your own corpus

The tool that produced every table here is in this repository. It reads your own
transcripts. Each section names the command that generates its figures.

```bash
pip install .
csd summary
```

If your corpus disagrees with a claim below, the disagreement is the useful
result. Please open an issue with the command and the output.

## Review the method, not only the numbers

The figures are only as good as the parsing and the arithmetic behind them.
`DESIGN.md` states the terms, the cost model, and every measurement decision,
together with the reason for each one. It also records the faults that earlier
versions of this tool had, and how each fault changed the result.

Corrections to the method are more valuable than corrections to the numbers.

## Terms

This document uses one name for each concept. `DESIGN.md` defines all of them.
The four that matter most here:

- **lane** — one transcript and the one prompt cache that serves it
- **request** — one billed API call, and the unit of position inside a lane
- **expiry** — the event in which a cache stops being valid
- **premium** — the money paid above the cost of a warm read

Session counts, token counts and ratios come from the corpus above. Money figures
are for one session or for one request. This document does not report total
spend.

## 0. The cache TTL is one hour, and the hour starts at the last use

Run `csd ttl`. There are three separate questions.

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

The sample in each group is small. This is the claim in this document that most
needs a second corpus to confirm it.

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

If this holds for you, the rule is simple. **Use a session one time each hour,
and its cache stays warm.**

## 1. The cache stays complete for one hour, then it is gone

Run `csd decay`. This is the median fraction of the prompt that the client had to
write again, in groups by the idle gap since the previous request:

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

Therefore any gap of less than approximately 55 minutes is free. To cross the
hour costs a complete rebuild of the context, at a median of $2.20 for one
request, and up to $8.21 for the largest sessions here. **The size of that cost
depends on your context size, so it is the figure least likely to transfer.**

The remaining read of 14K to 15K tokens in the groups above 2 hours is the static
prefix: the system prompt and the tool schemas. Other sessions that run at the
same time keep that prefix warm. This session does not.

## 2. Cold restarts were 17% of all cost

Run `csd summary`. 17% of the cost of this corpus went on writing context again
that a warm cache would have served at one tenth of the price. 116 of 199
sessions had at least one expiry during the session. There were 399 expiries in
total.

This share depends on how often the operator leaves a session idle. It is
behaviour in real time, not a property of the tool or of the API. Your share
could be near zero.

## 3. Startup cost is observable, and varies by a factor of 2.6 between projects

Run `csd startup`. The context increases steadily and reaches no plateau:
approximately 29K tokens at request 1, 52K by request 10, and 104K by request 40.
Therefore no inflection marks the end of orientation.

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
context again after an expiry. The project names below are anonymous:

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

The ratio of 2.5 is the part of this section most likely to hold for others. The
absolute figures depend on the size of the codebase and on the project
instructions.

## 4. The carry cost applies to every request, and it accumulates

Run `csd growth`. Every request reads the complete context again. Therefore the
cost of a request increases with the context, and the cumulative cost grows
faster than the request count:

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

The exponent of 1.18 is specific to this corpus, because it depends on how fast
the context grows. The mechanism is not: every request re-reads the whole
context, and that is a property of the API.

This is the carry cost for each request, before the model generates any output.
These figures are arithmetic on the published rates, so they apply to anybody:

| context | Opus ($5/M) | Fable ($10/M) |
|---|---|---|
| 200K | $0.100 | $0.200 |
| 400K | $0.200 | $0.400 |
| 800K | $0.400 | $0.800 |

Long lanes in this corpus reach 651K tokens at p90 and 894K at p99. Therefore the
end of a large session pays **$0.33 to $0.80 for each request, only to read
itself again.** In this corpus the carry cost is larger than the restart premium,
and it is less visible.

## 5. One long warm session does not cost less than several short ones

Run `csd crossover`. The first hypothesis was that one long warm session costs
less than several short sessions, because each short session pays for startup
context again. In this corpus, startup is too cheap for that hypothesis to hold:

- To make a new session productive costs approximately 81K tokens, which is
  **$0.81** on Opus.
- To carry a 600K context instead of a 200K context costs **$0.16 for each
  request**, and it continues for the life of the session.

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

**Restart counts are observed, not assumed.** In this corpus a session of
approximately 200 main requests has a median of **3** expiries (p25 1, p75 5).
Only 20% have none. A session of approximately 40 requests has a median of **0**,
and 51% have none. A default of zero would favour the long session, so
`crossover` reads the median for each length and reports it. Use `--restarts` and
`--short-restarts` to set the values yourself.

**Rework decides the comparison, and a transcript cannot measure it.** Rework is
the extra requests that short sessions need to rebuild understanding that the
long session still holds in context: to read the same files again, and to derive
the same structure again. It stays an explicit input for that reason:

```bash
csd crossover --rework 0.5
```

**The break-even point is approximately 88% rework** at the observed restart
rate. Below that, the short strategy costs less. Above it, the long session does.

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
long session costs less from **10 sessions**, not from 20. Therefore the answer
is between the two extremes. A small number of substantial sessions costs less
than one very large session, and less than many small ones.

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
input that changes the answer.

Therefore the guidance from this corpus is:

- **The short strategy costs less** when the work divides well enough to need
  less than approximately 2.4 times the requests. To carry a large context is a
  cost on every request, not a single cost.
- **Never let a large session stay idle across the hour.** A 600K session that
  expires two times costs $12 more, which removes the complete advantage of
  holding the context. If you hold a large context, use it actively.

**The model prices tokens only.** Whether a smaller context can do the work is a
judgement that the transcripts cannot make, and it is the largest limit on this
section. If splitting the work makes the results worse, the token saving is not
the number that matters.

## 6. Subagents behave differently, and they are one fifth of the cost

Run `csd subagents`. Subagent transcripts are nested at
`<project>/<session-uuid>/subagents/agent-*.jsonl`. They are 1,863 of 2,094
files. They record the `sessionId` of the parent, so the tool attributes their
cost to the session that started them. They do not behave like a main lane:

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
71% of cost in `studio-tools` and 0.2% in `orchard/survey`. That range is a
property of how the operator works, not of the tool.

## 7. Approximately one half of the record is deleted

Run `csd coverage`.

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

This affects any long history. Check your own coverage before you compare two
periods.

## What the API measures, and what this tool infers

Keep the two separate. `DESIGN.md` states the rule; this section shows what the
corpus contains.

**Measured, directly from the `usage` object.** The API puts every prompt token
in exactly one of three fields, so these are counts, not estimates:
`input_tokens`, `cache_creation_input_tokens` and `cache_read_input_tokens`.
Therefore **the cache hit rate is measured, not inferred.** There is no flag for
a hit or a miss on one request, because a cache serves part of a prompt, so the
hit rate must be weighted by tokens.

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

**Inferred, and labelled as inferred:** the cold start (a context of 20K tokens
or more, with less than 50% served from the cache), the restart (a gap longer
than the TTL), the cold-start premium (a comparison against a warm read), and the
ready point (the first `Edit` or `Write`).

The inferred cold start and the reported miss reason agree on 384 requests, but
they measure different things, and the disagreements have explanations:

- Of 277 requests that the tool marks and the API does not, 147 are the first
  request of a lane. No cache existed to miss, but the client still had to build
  the context.
- Of 188 requests that the API marks and the tool does not, the median request
  still served **99.3%** of its prompt from the cache. That is a partial miss,
  not a cold rebuild.

The tool keeps both signals. Do not try to make them agree.

## The model mix in this corpus

Run `csd models`. The rates are published. The request counts and the shares show
which models this operator selected, and yours will differ:

| model | in $/M | out $/M | requests | share of cost |
|---|---|---|---|---|
| claude-opus-4-7 | 5.00 | 25.00 | 12,144 | 39.5% |
| claude-opus-5 | 5.00 | 25.00 | 9,044 | 20.6% |
| claude-fable-5 | 10.00 | 50.00 | 2,813 | 12.8% |
| claude-opus-4-6 | 5.00 | 25.00 | 7,931 | 10.8% |
| claude-opus-4-8 | 5.00 | 25.00 | 3,805 | 9.3% |
| claude-sonnet-5 | 3.00 | 15.00 | 8,092 | 4.4% * |
| claude-haiku-4-5 | 1.00 | 5.00 | 9,298 | 1.4% |

`*` The tool applied the introductory price. **Rates are not constant over time.**
Sonnet 5 started at $2/$10 for each million tokens, until 2026-08-31, and then
moved to $3/$15. Therefore the tool prices each request against the rate that
applied on its timestamp.

## Worked example: the client pays for a cold restart one time, not two times

This claim is arithmetic, not statistics. You can check it against any single
request in your own corpus with `csd trace`.

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

### Why it is one payment, not two

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
