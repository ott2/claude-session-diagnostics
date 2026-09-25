# Design notes

This document records the terms, the cost model and the measurement decisions
behind `csd`. It explains why the code works the way it does.

`FINDINGS.md` reports what one corpus showed. This document reports how the tool
measures it. If you doubt a figure in `FINDINGS.md`, the method is here.

The text follows ASD-STE100 (Simplified Technical English). Sentences are short.
Each concept has one name. The names are defined in [Terms](#terms) and are not
varied elsewhere.

## Terms

Use these names exactly. Do not use a different word for the same thing.

| Term | Definition |
|---|---|
| **transcript** | One JSONL file on disk. It records one lane. |
| **lane** | One transcript and the one prompt cache that serves it. A lane is the only scope in which cache behaviour is meaningful. |
| **main lane** | The lane of a session that the operator talks to directly. |
| **subagent lane** | A lane that a main lane starts to do delegated work. |
| **session** | One piece of work. A session contains one main lane and every subagent lane that the main lane starts. |
| **segment** | A run of requests inside one lane in which the cache stayed warm. A lane has one segment for each cold start. |
| **request** | One billed API call. This is the unit of cost and the unit of position inside a lane. Do not call it a turn. |
| **context** | The number of prompt tokens that a request sends. |
| **cache write** | Prompt tokens that the API stored in the cache. The API reports these as `cache_creation_input_tokens`. |
| **cache read** | Prompt tokens that the API served from the cache. The API reports these as `cache_read_input_tokens`. |
| **warm** | The state of a cache that is still valid. Do not use the word hot. |
| **expiry** | The event in which a cache stops being valid. |
| **restart** | The cache write that a lane must pay after an expiry. An expiry is the cause. A restart is the effect. Do not use the two terms as synonyms. |
| **cold start** | A request that starts a new segment. `is_cold_start` **infers** this from the token counts. |
| **cache miss reason** | The cause of a failed cache lookup, as **reported** by the API in `message.diagnostics.cache_miss_reason`. This is not the same predicate as a cold start. See [Measured and inferred](#measured-and-inferred). |
| **premium** | The money paid above the cost of a warm read. Do not use the words tax, waste or wasted. |
| **carry cost** | The money paid to re-read the context on one request. |
| **orientation** | The requests at the start of a cold session that read and search, before the first change to a file. |
| **ready point** | The first `Edit` or `Write` of a cold session. This is the only boundary between orientation and work that a transcript shows. |
| **rework** | The extra requests that a short session needs to rebuild lost understanding. |
| **TTL** | The time for which a cache stays warm after its last use. |

## Data source

A transcript is a JSONL file below `~/.claude/projects`. Each line is one record.
The `usage` object of an `assistant` record holds the token counts that this tool
measures.

### Remove duplicate records with a global key

Use the key `(requestId, message.id)`. Keep one record for each key.

A transcript writes one `assistant` line for each content block. Every one of
those lines repeats the complete `usage` object. A tool that adds the usage of
each line makes the cost approximately two times too large.

Use one key set for all files. Do not use one key set for each file. The
directories `.cwd-fix-backup-*` hold copies of complete sessions. The copies are
identical to the originals. A key set for each file counts these copies two
times.

`ParseStats.duplication_factor` is the indicator for this fault. Examine it after
each change to the parser.

### Find the nested transcripts

Most transcripts are not at the top level. Subagent transcripts are at
`<project>/<session-uuid>/subagents/agent-*.jsonl`. Some are one level lower,
below `subagents/workflows/<wf-id>/`.

A `*/*.jsonl` pattern finds approximately one file in nine. It discards
approximately one fifth of all cost without a warning. Therefore the search must
be recursive. The search must ignore hidden directories.

A subagent transcript records the `sessionId` of its **parent**. This is what
makes attribution to a session possible.

### Strip the date from model ids

Subagent lanes use model ids with a date suffix, for example
`claude-haiku-4-5-20251001`. Main lanes use the short alias. `normalise_model`
removes the suffix.

A check that does not remove the suffix counts many thousands of requests too
few.

### Old transcripts are incomplete

The client deletes old transcripts. It does not delete their `subagents`
directories. Therefore many old sessions remain only as fragments.

A total that covers a period with fragments is a minimum, not an exact figure.
`coverage_report` shows which periods are complete. The `summary` command gives a
warning.

Do not read the deletion of old transcripts as a change in how much the operator
works.

### The corpus changes while you use it

Work in this repository adds records to the corpus. Therefore totals change
between two runs of the same command.

To compare two versions of the code, copy the corpus first:

```bash
cp -R ~/.claude/projects /tmp/snapshot
```

Compare against the copy. Do not compare against a number from an earlier run.

### `<synthetic>` is not a billed request

The value `<synthetic>` in the model field marks a client-side error message.
`pricing.normalise_model` returns `None` for it. The parser counts these records
in `ParseStats.synthetic`.

## The cache TTL

`CACHE_TTL` is 1 hour. This value is measured. It is not an assumption. The `csd
ttl` command shows the evidence and `TestTtlEvidence` holds the value stable.

Three results support the value:

- **The boundary is sharp at 60 minutes.** A gap of 58 to 60 minutes gives a
  rewrite in 0.6% of pairs, and no dead cache. A gap of 60 to 62 minutes gives a
  rewrite in 96.3% of pairs, and a dead cache in 80%.
- **The hour starts at the last use, not at the creation.** Hold the gap short
  and change the age of the lane. The rewrite fraction stays flat from less than
  1 hour to more than 24 hours, across approximately 26,000 samples. Each use of
  a session sets the clock back to zero. Therefore the cache does not decay, and
  the client does not rebuild it at intervals.
- **Early death is rare.** It occurs in 0.31% of pairs. Most early deaths are
  self-inflicted (`tools_changed`, `system_changed`). They are not evictions.

### The requested TTL is different for each kind of lane

Main lanes request 1 hour almost always. Subagent lanes request 5 minutes more
often than 1 hour, which agrees with a lane that lives approximately 1 minute.

However, subagent caches die at the hour, not at five minutes. A prompt mixes
prefixes that were written with different TTLs. The 1-hour part, which the lane
shares with its parent, is the part that stays warm.

Do not set a different TTL constant for each kind of lane because of the
requested value. The segmentation needs the observed behaviour.

Old transcripts do not report the split between 5-minute and 1-hour writes. They
report only the total. The tool attributes that total to 1 hour.

## Measured and inferred

Keep the difference between measured and inferred values visible. Label each one
in any output.

### The hit rate is measured

The API puts every prompt token in exactly one of three fields: `input_tokens`,
`cache_creation_input_tokens` or `cache_read_input_tokens`. The hit rate is
arithmetic on these counts.

There is no flag for a hit or a miss on one request. A cache serves part of a
prompt. Therefore the hit rate must be weighted by tokens.

### The cache miss reason is reported

`message.diagnostics.cache_miss_reason` states why a lookup failed.
Approximately three requests in five carry it. Old clients do not write the key.

`Request.has_diagnostics` separates "reported, and there was no miss" from "not
reported". Do not combine these two states. A tool that combines them shows a
perfect cache.

These reasons are self-inflicted, and therefore the operator can act on them:

- `tools_changed`
- `system_changed`
- `model_changed`
- `messages_changed`

### A cold start and a cache miss reason are different predicates

Do not try to make the two agree.

- A reported miss can be partial. In half of the reported misses, more than 99%
  of the prompt still came from the cache.
- A reported miss cannot occur on the first request of a lane, because no cache
  existed before it.

Keep both values. State which one is measured and which one is inferred.

## Cost model

The cache multipliers apply to the input rate:

| Operation | Multiplier |
|---|---|
| 5-minute write | 1.25 |
| 1-hour write | 2.00 |
| read | 0.10 |

`pricing.cold_start_premium` calculates `tokens x rate x (2.00 - 0.10)`. This is
the money paid above a warm read. Most analyses use this value.

### The three token fields do not overlap

The three fields divide the prompt. A cold restart pays once, at the write
multiplier. It does not pay the input rate to read the context and a write rate
in addition. The proof is that `input_tokens` stays near zero on a cold restart.

Writes are also strictly incremental. On a warm request, the cache write equals
the growth of the context. This holds across more than 25,000 real requests, to
±1 token.

Therefore a restart is a single cost, and the next request repairs it fully. Do
not model a restart as a continuous penalty.

Two tests hold these properties stable:

- `test_prompt_tokens_land_in_exactly_one_bucket`
- `test_warm_request_writes_only_the_new_content`

The `csd trace` command shows the full ledger for one session.

### The carry cost is super-linear, not quadratic

Every request reads the whole context again. Therefore the cumulative cost grows
faster than the request count. In this corpus it grows as approximately
`requests^1.18` (`csd growth`).

The exponent is less than 2 because the context grows more slowly as a session
continues: approximately 2.2K tokens for each early request, and approximately
1.1K after request 100.

Compaction is not the cause. Compaction almost never occurs here: 0.04% of
requests shrink the context. Do not attribute the lower exponent to pruning. If
the growth stays constant, the exponent moves towards 2.

The carry cost is the largest cost of a long session. At a context of 800K
tokens it is approximately $0.40 for each request on Opus, and approximately
$0.80 on Fable. The total is more than the total restart premium.

When you present `crossover`, do not describe the carry cost as a flat figure for
each request. It is a mean of a curve that rises. The end of the curve holds most
of the money.

### A premium is not a cost

Show the total cost beside any premium. A premium alone reads as the price of the
request, and the reader interprets it incorrectly.

Example: a premium of $7.93 came from a request that cost $8.57. The same request
would have cost $0.64 warm.

The `csd cold` command prints cost, if-warm and premium for this reason.
`test_worked_example_premium_and_total_are_distinct` holds the arithmetic stable
against a real request.

### Prices depend on the model and on the date

`Price.rates(at, fast)` selects the rate that applied on the date of the request.
`Request.cost` gives it `self.timestamp`.

Sonnet 5 started at $2/$10 for each million tokens, until 2026-08-31. After that
date the rate is $3/$15. A tool that applies the later rate to earlier requests
makes the cost too large.

To add a model that has an introductory price, set `intro_input`, `intro_output`
and `intro_until`. Do not set the introductory price as the base price. If you
set it as the base price, the figures become incorrect when the introductory
period ends, and nothing reports the fault.

Before you change `pricing.py`, read the `claude-api` skill. Do not use memory.
Model ids and rates change. The `csd models` command shows the rates that the
tool applied, and lists models that have no price. Examine it after each change
to the prices.

### Format currency with `_money()`

Do not write a format such as `{n:>8,}${x:>9.2f}`. The dollar sign touches the
previous column when that column is full.

## Analysis design

There are three levels:

1. **session** — one piece of work
2. **lane** — one transcript and one prompt cache
3. **segment** — a run inside a lane in which the cache stayed warm

Cache behaviour is meaningful only inside one lane. Lanes run at the same time
against separate caches. Therefore you must never make a pair from requests in
two different lanes. `decay_curve` and `cold_starts` operate on one lane at a
time for this reason.

`Session.restart_premium` does not include the first segment of each lane. That
write is necessary work. It is not a loss.

### Group sessions by session id only

Do not use the key `(project, session_id)`. Session ids are UUIDs, and therefore
they do not collide.

A subagent sometimes records a `cwd` that is different from the `cwd` of its
parent. A key that includes the project divides such a session into two. The
project label comes from the main lane, not from a subagent.

### Keep subagents out of the cache analyses by default

A subagent lane lives approximately 0.9 minutes. A main lane lives approximately
280 minutes. A subagent lane crosses the TTL in 0.09% of gaps. A main lane
crosses it in 1.53%.

A subagent starts cold because that is its design. To count that as a loss is
incorrect. The short gaps of subagent lanes also make the median cache read
approximately one half of its true value for main lanes.

The tool always counts the cost of subagents. `include_subagents=True` adds them
to the analyses.

### Take the project label from `cwd`

The directory names below `~/.claude/projects` replace each `/` with `-`. This
encoding cannot be decoded. The name `-src-acme-acme-core` agrees with
`acme/acme-core` and equally with `acme-acme/core`.

An earlier version divided the name at each `-` and kept the last part. That
version combined two different projects into one row. The totals were incorrect,
not only the label.

`project_label()` reads the `cwd` of the transcript. If there is no `cwd`, it
uses the encoded name complete.

The default depth is 2. CLI tables make the project column as wide as the data.
A fixed width would cut the labels and cause the same collision on the screen.

### `COLD_OPENING_READ` is 50K, not a small number

Approximately one half of all sessions open with a read of 15K to 20K tokens from
the cache. This is the **shared** system prompt and the tool schemas. A session
that runs at the same time left them warm. This is not a warm conversation.

A threshold of 5K removes the busiest projects from all startup analysis. Those
projects are the most likely to have a second session that runs at the same time.

A conversation that the operator truly resumed reads back more than 100K tokens.
`test_warm_shared_prefix_still_counts_as_cold` guards this threshold.

### The `warm` view answers a question about now

`analysis.warm_lanes` reports the lanes that are still warm and the time that
each one has left. It is the only analysis that uses the clock of the computer.
Every other analysis reports the past.

The row is a lane, not a session. A cache belongs to one lane. The time left is
the TTL less the idle time, because the hour runs from the last use.

Subagent lanes are held out by default. A subagent exits after approximately one
minute. Its cache holds nothing that the operator can go back to.

#### Read only the recent transcripts

The command selects the files that a lane changed inside the window. It does not
read the corpus. This makes the command approximately 15 times faster, which is
necessary for a view that the operator looks at many times in one hour.

The modification time of a file is never earlier than its last record. Therefore
the filter cannot discard a lane that is still warm. It can keep a file that has
no recent **request**, because a user message also writes a line. The analysis
compares the timestamps of the requests, and removes those lanes.

`parser.session_files` then adds the other lanes of each session. A session
wrote its subagent lanes before the window started. Without this step the `spent`
column shows only part of what the session cost.

Verify a change to this path against a full load of the corpus. The two must
agree for each session, to the cent.

#### The two costs are estimates for the next request

`resume_cost` reads the context back at 0.10x. `rebuild_cost` writes the same
context again at 2.00x. Both use the context and the model of the last request.
Neither includes the output tokens or the new content of the next request. Those
are the same in the two conditions.

The premium is the difference. The operator pays it only if the operator goes
back to the lane after the expiry. A lane that expires and stays closed costs
nothing.

#### The session name comes from the transcript

The client writes an `ai-title` record and writes it again as the work changes.
The last one is the current name. Approximately one transcript in five has no
title. Most of those have a `last-prompt` record, which is sufficient to
recognise the session.

`CLAUDE_CODE_SESSION_ID` gives the id of the session that the command runs in.
The output marks that row.

The figures come from the transcripts on disk. A request that is in flight is
not on disk. Therefore the row for the current session is one request behind.

## The strategy comparison

`analysis.compare_strategies` compares one long warm session against several
short cold sessions.

The `rework` term decides the answer. A transcript cannot measure it. Therefore
`rework` must stay an explicit input, and any verdict must report
`breakeven_rework` beside it.

### Context comes from `growth_per_request`, not from a fixed peak

The peak context of a strategy follows from the number of requests that the
strategy runs.

An earlier version took the peak as a fixed input. In that version, rework raised
the request count but left the context unchanged. The extra work therefore cost
nothing, the implied growth rate fell without a warning, and the break-even
figure was almost two times the true figure.

The carry cost is quadratic in the rework factor. Therefore `breakeven_rework`
uses bisection. It does not use a linear solution.

### `Strategy` mixes units, deliberately

- The costs and `requests` are totals for the complete strategy.
- `peak_context` is a value for one session.

One table row that holds both is difficult to read. Therefore any output must
label the units. The CLI uses the column names `req ea` and `peak ea`, and states
the convention above the table.
`test_costs_are_totals_and_peak_is_per_session` holds this stable.

### Output tokens are a term in the model

`output_cost_per_request` defaults to `observed_output_cost()`.

Output tokens cancel when the request counts are equal. They do not cancel under
rework. Therefore a model that omits them favours the short sessions.

Any cost for each request that you add later has the same property. Examine
whether it survives the asymmetry that rework causes.

### Charge orientation for each session, from measurement

`ready_cost` comes from `ReadyPoint.median_cost`, which is approximately $2.02.
`ready_requests_each` comes from `median_request_index`, which is approximately
19.

An earlier version gave the ready **context** to a parameter that the model
treated as a prefix written at the start. That version charged approximately
$0.82 for something that measurement puts at $2.02. It also did not subtract the
orienting requests from the work budget, and therefore the short sessions
received their re-orientation at no cost. Both faults favoured the short
sessions.

`requests` now means **productive** requests. `Strategy.requests` adds
orientation back.

Keep this result: the short sessions cost less up to approximately 10 to 20
sessions, and cost more above that number. Orientation paid N times becomes
larger than the saving in carry cost. Do not state that short sessions are
cheaper without the number of sessions.

### `ReadyPoint` holds a cost as well as a token count

- `median_cost` is the cumulative cost of the orienting requests. It is measured.
  It is not calculated from the size of the context.
- `median_rebuild_cost` is the cost to establish the same context again after an
  expiry.

Orientation costs approximately 2.5 times the rebuild. Orientation is many
requests, each with its own reads and its own output. A rebuild is one cold
write.

### Restart counts default to observed medians, not to zero

`observed_restarts()` reads the median for main lanes of a comparable length. A
lane of approximately 200 requests has a median of 3 restarts. A lane of
approximately 40 requests has a median of 0.

Zero was an optimistic default. It favoured the long session and moved the
break-even figure by approximately one half.

A restart is behaviour in real time. It shows how often the operator leaves a
session idle for more than an hour. It is not a property of the strategy.
Therefore short sessions also pay for restarts, through `short_restarts_each`.

### Inconsistent inputs are possible

The peak context and the session count are separate inputs. Therefore a caller
can describe a scenario that cannot occur. For example, `--sessions 10` with an
unchanged `--small` means that the short sessions accumulate context more than
two times faster for each request.

`inputs_consistent` and `growth_ratio` detect this condition. The CLI gives a
warning and shows a corrected `--small` value.

Do not correct such a result by trusting the totals. The inputs are wrong. The
model is not wrong.

### Startup context has no plateau

A cold session adds approximately 2K tokens for each request, and it continues to
do so. The context is approximately 29K at request 1, approximately 52K at
request 10, and approximately 104K at request 40. No inflection shows the end of
orientation.

Keep these two quantities separate:

- `startup_prefix_tokens()` is the context of request 1. This is the fixed
  prefix, approximately 29K tokens.
- `observed_ready_tokens()` is the context at the ready point, approximately 81K
  tokens as a median.

An earlier version used the first value where the second was needed. That version
made the cost of a restart too small.

Startup varies by a factor of approximately 2 between projects, from
approximately 58K to approximately 120K tokens. Therefore report it for each
project with `ready_tokens_by_project`. Do not quote one median for all projects.

## The export record

`csd export` writes one JSON record for each session. The table gives each
field, the lanes that it covers, and whether it is measured or inferred.
**Measured** means a value from the transcript, or arithmetic on such values.
**Inferred** means a value that depends on a rule of this tool, such as the TTL.

| Field | Lanes | Kind | Definition |
|---|---|---|---|
| `session_id` | all | measured | The `sessionId` of the session. |
| `project` | main | measured | The project label, from the `cwd` of the main lane. |
| `start`, `end` | all | measured | The timestamps of the first and the last request. |
| `requests` | all | measured | The number of requests. |
| `wall_seconds` | all | measured | The time from `start` to `end`. |
| `active_seconds` | main | inferred | The sum of the segment durations. Gaps longer than the TTL are removed. |
| `peak_context` | main | measured | The largest context of one request. |
| `output_tokens` | all | measured | The sum of `output_tokens`. |
| `input_tokens` | all | measured | The sum of `input_tokens`. These prompt tokens are neither a cache write nor a cache read. |
| `cache_write_5m` | all | measured | The sum of the 5-minute cache writes. |
| `cache_write_1h` | all | measured | The sum of the 1-hour cache writes. Old transcripts report only a total, which the tool attributes to 1 hour. |
| `cache_read` | all | measured | The sum of the cache reads. |
| `output_context_product` | all | measured | The sum, for each request, of `output_tokens` × context. See below. |
| `cost` | all | measured | The cost in USD, from the token counts and the rates in `pricing.py`. |
| `restarts` | main | inferred | The number of segments after the first, in each lane. |
| `restart_premium` | main | inferred | The premium of the first request of each of those segments. |
| `models` | all | measured | The model ids, without the date suffix. |

`input_tokens`, `cache_write_5m`, `cache_write_1h` and `cache_read` divide the
prompt tokens of the session with no overlap. Their sum is the total context
that the session sent, over all requests.

### `output_context_product` is summed for each request

For each request, the tool multiplies `output_tokens` by the context of that
request, and adds the products. Do not calculate this value from the totals. The
product of two averages is not the average of the product. A session whose long
outputs come late, at a large context, has a larger value than its means give.

The context is the prompt that the request was sent with. It does not include
the tokens that the request generates. Decode also attends over those tokens.
The field excludes them on purpose, so that the value stays exact arithmetic on
the reported counts.

Divide by `output_tokens` to get the mean context, weighted by output, at which
the session generated its output.

## Verify a change to the cost calculation

Unit tests are not sufficient. The test suite uses synthetic fixtures, and
therefore it cannot find a systematic error in the prices.

Write an independent implementation. Run it against a frozen copy of the corpus.
Compare the two results. The two paths currently agree to the cent across more
than 26,000 requests.
