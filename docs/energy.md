# Energy per token: the evidence

**`csd` does not read this file, and it ships no energy constant.** This
document gives the published evidence for energy per token, and it shows
each step from the fields of `csd export` to watt-hours. The user supplies
every constant and owns it.

`csd export` supplies the measured half: the token quantities of each
session. This document supplies the other half, and that half is not
measured for Claude. No provider publishes energy per token for a Claude
model. No source publishes the hardware, the batch size or the power at
which Claude is served. Thus every result below is a range, and each
range has its operating point beside it.

In the terms of [`DESIGN.md`](../DESIGN.md#measured-and-inferred), every
energy figure in this document is **inferred**. The export fields that it
starts from are **measured**.

Last revised 2026-10-06. The figures come from benchmarks and estimates
that change each week. Examine the dates before you use a range.

The text uses the terms in `DESIGN.md`. A **request** is one billed API
call. The **context** is the number of prompt tokens that a request sends.
A **cache read** and a **cache write** are the reported token fields.

## How to read the figures

Each source figure has one of these kinds. Keep them separate.

| Kind | Meaning |
|---|---|
| **measured** | A benchmark, a production system or a telemetry system recorded the value. |
| **simulated** | A model of the hardware and the workload calculated the value. |
| **estimated** | A publisher's own model calculated the value, and the publisher does not give the method. |
| **derived** | This document calculated the value from published figures. The arithmetic is given. |
| **assumed** | No primary source gives the value. Secondary reporting or a vendor rack figure supplies it. |

Each power figure also has a **basis**. The bases differ by up to 4×. That
is as large as the quantities that this document estimates.

| Basis | Meaning |
|---|---|
| package TDP | The rated power of the chip package only. Do not use it as a denominator. |
| IT power per chip | The power of the rack, divided by the chips in it. |
| all-in provisioned | IT power plus cooling and electrical losses, at the rated maximum. |
| capacity | The power of a whole fleet, idle hardware included. |
| measured draw | The power that the hardware drew during the benchmark. |

Most figures here use **all-in provisioned** power. Hardware in inference
does not draw its full rated power. Thus these figures are upper bounds,
by an unknown factor of up to about 4×.

An **operating point** is the model (with its **active** parameters), the
precision, the hardware, the deployment scale (one node or one rack), the
serving engine, the speed in output tokens per second for each user
(tok/s/user), the context, the workload and the power basis. Two figures
that differ in any of these are not comparable unless you state how they
differ.

**Figure numbers** count the charts of an article in page order, from 1.
"Chart-read ±5%" means that the value was read from a chart, not from a
table or from the text.

## How to read a chain

Each route below is a numbered chain. One row is one step. Each row
gives:

- the **quantity** that the step produces;
- the **choice** made at the step;
- the **range** that the evidence gives for that choice;
- the **factor**: the result at the high end of the range divided by the
  result at the low end, with all other steps held constant;
- the value for the **example corpus**.

You can examine each row independently. Each chain ends with the step
whose factor is largest.

## The export fields

`csd export` gives these measured fields for each session. See
[The export record](../DESIGN.md#the-export-record).

| Field | Use in the chains |
|---|---|
| `input_tokens` | Prefill. Prompt tokens that are neither a cache write nor a cache read. |
| `cache_write_5m`, `cache_write_1h` | Prefill. The sum is measured. For old transcripts, the split between them is inferred. Only Route 3 uses the split. |
| `cache_read` | Cache reads. |
| `output_tokens` | Decode. |
| `fast_output_tokens` | The part of `output_tokens` that ran in fast mode. |
| `output_context_product` | The sum, for each request, of `output_tokens` × context. Divide by `output_tokens` to get the mean context, weighted by output. |

## The example corpus

The chains use one corpus as an example. This is not a result for Claude.
The corpus is one person's Claude Code transcripts, as `csd summary`
reported them in
[issue #1](https://github.com/keziacousins/claude-session-diagnostics/issues/1):
124,484 requests, 6.9M input tokens, 554.4M cache writes, 23,087.4M cache
reads and 124.5M output tokens. That is 23.77B tokens in total, 97.1% cache
reads and 0.52% output. The totals are minimums (see `csd coverage`).

Those totals came before the export fields existed. Thus they do not split
the cache writes by TTL, and they do not give `output_context_product` or
`fast_output_tokens`. The chains use the mean context per request,
approximately 185K, where they need a context. A copy of the same person's
transcripts on 2026-10-06 (149,373 requests) gave these values:

- mean context weighted by output, 212K, against 198K for each request;
- 84% of the cache writes at 1 hour;
- no fast-mode output.

On a second corpus, the weighted mean was 240K against 178K
(`kezia-pr-review`).

The shape of the example corpus agrees with the two published agentic
workloads:

| | AgentX traces (`sa-agentx`) | SemiAnalysis September mix (`sa-subs`) | example corpus |
|---|---|---|---|
| tokens per request | ~179k | – | ~185k |
| mean output per request | ~970 | – | ~1,000 |
| output, share of all tokens | 0.7–0.8% | 0.3% | 0.52% |
| cache reads, share of all tokens | – | 96.6% | 97.1% |
| cache reads, share of prompt tokens | ~95% | – | 97.6% |

## The current span

As of 2026-10-06, for the example corpus:

| Route | Operating point | Example corpus |
|---|---|---|
| 1, per total token | DeepSeek V4 Pro (49B active), rack scale, 75–100 tok/s/user, provisioned | **100 – 310 kWh** |
| 2, by phase | 2026 silicon, ~55 tok/s/user, `m` 1.5–3.0, provisioned | **60 – 280 kWh** |
| 2b, by phase, production rates | DeepSeek V3/R1 (37B active), H800, 20–22 tok/s/user, provisioned | **94 – 163 kWh** |
| 3, top-down | Anthropic's fleet, API revenue per MW at Opus 5.5 list, capacity | **840 – 990 kWh** |
| 3, cost-side check | 90–95% API margin, kWh per $ of TCO by chip | 370 – 1,620 kWh |
| 1, per total token | Kimi K3 (2.8T total), GB300 or B300, 40–85 tok/s/user, public software, provisioned | 1,700 – 3,100 kWh |

On current evidence, **approximately 100 to approximately 1,000 kWh** is
the span for the example corpus.

- **The low end** is a mid-size model at full load. Three routes agree
  there: a rack-scale benchmark (Route 1, V4 Pro), the phase constants on
  2026 silicon (Route 2), and a lab's own production fleet (Route 2b). A
  benchmark at full load has no idle hardware in it.
- **The high end** is Anthropic's fleet average on capacity (Route 3). It
  includes idle hardware and provisioning, so it is an upper bound on the
  energy that the hardware drew. The cost-side check agrees with it.
- **The K3 row is above the span.** It is an upper bound on the overhead
  of a Claude-sized model on public software. It is not an upper bound on
  the size of the model. See [Open tensions](#open-tensions).

The gap between the low end and the high end has two possible causes:
fleet utilisation and provisioning, and the size of the model. No current
source separates them.

## Route 1: energy per total token

Use this route when a benchmark replays traffic of the same shape. AgentX
does that (`sa-agentx`). The cache reads, the decode at long context and
the prefill are already inside the constant.

```
E = e_total × (input_tokens + cache_write_5m + cache_write_1h + cache_read + output_tokens)
```

| # | Quantity | Choice | Range | Factor | Example corpus |
|---|---|---|---|---|---|
| 1 | `T`, total tokens: the sum of the five token fields | none; measured | – | 1 | 23.77B |
| 2 | agreement of the token mix with the benchmark | the AgentX traces as the workload | output 0.7–0.8% against 0.52%; cache reads ~95% against 97.6% of prompt tokens | not measured; a check, not a multiplier | agrees |
| 3 | the open model that stands in for Claude | DeepSeek V4 Pro (1.6T total, 49B active) or Kimi K3 (2.8T total, ~104B active, speculative) | V4 Pro to K3, same chip, engine, date and speed | **6.3×** | – |
| 4 | deployment scale | NVL72 rack or 8-GPU node | GB300 NVL72 to B200 node, V4 Pro, 100 tok/s/user | 4.1× | – |
| 5 | hardware generation | Rubin or Blackwell; H200 or MI355X | B200 node 4.0e-5 to H200 1.2e-4 Wh per token; 3.11× from H100 to B200 on another model | ~3× | – |
| 6 | serving engine | SGLang, TRT-LLM or vLLM | GB300, 75–100 tok/s/user | 1.2–1.3×; up to 4× at 125 tok/s/user | – |
| 7 | speed | the 75–100 tok/s/user columns. Standard Claude is served at ~47–51 (`dib-dataset`, assumed) | 75 to 100 on GB300 SGLang | 1.33× | – |
| 8 | power basis | all-in provisioned, as the source gives it | provisioned to measured draw | up to ~4× lower; not measured | – |
| 9 | PUE | inside the all-in utility power of the source | – | 1 | – |
| 10 | `e_total`, Wh per total token | V4 Pro, VR or GB300 NVL72, 75–100 tok/s/user | 4.3e-6 – 1.3e-5 | 3.0× | – |
| 11 | `E = T × e_total` | – | – | – | **100 – 310 kWh** |

**The step that matters most is step 3, the proxy model: 6.3×.** With K3
in place of V4 Pro at step 10 (GB300 or B300, 40–85 tok/s/user, 7.1e-5 –
1.3e-4 Wh per total token), the result is 1,700 – 3,100 kWh. Steps 4 and
5 are next. No source confirms the hardware or the deployment scale for
Claude.

Notes on the steps:

- **Step 3.** Active parameters explain 2.1× of the 6.3×. The other ~3× is
  not the compute of the model. It is the same size as the effect of
  software in the same benchmark (step 6). See
  [Open tensions](#open-tensions).
- **Step 7.** The lowest column of the V4 Pro table is 75 tok/s/user. That
  is above the speed of standard Claude. On GB300 SGLang, the curve gives
  ~53M tokens/s per MW at ~30 tok/s/user against 37.94M at 75 (chart-read
  ±5%). Thus the 75 column overstates the energy at ~50 tok/s/user by at
  most ~1.4× on that hardware (derived).
- **Fast mode.** The export does not give the prompt tokens of the fast
  requests. Thus Route 1 cannot apply a separate constant to fast mode.
  Use Route 2 for fast mode.

## Route 2: prefill, cache reads and decode

Use this route to see where the energy goes. It needs three constants and
a context term.

```
E = e_prefill × (input_tokens + cache_write_5m + cache_write_1h)
  + e_read    × cache_read
  + e_decode  × m × (output_tokens − fast_output_tokens)
  + e_fast    × m × fast_output_tokens
```

| # | Quantity | Choice | Range | Factor | Example corpus |
|---|---|---|---|---|---|
| 1 | `P`, prefill tokens: `input_tokens + cache_write_5m + cache_write_1h` | a cache write is a prefill that the API also stores; count it as prefill | – | 1 | 561.3M |
| 2 | `e_prefill`, Wh per fresh prompt token | ratio route (decode ÷ 4.3–8.4×), simulator, or production | 1e-5 – 6e-5 | 6× on this term | 5.6 – 34 kWh |
| 3 | `e_read`, Wh per cache read | zero, the physical estimate, or the simulated maximum | 0 – 2.6e-7 | adds at most 6 kWh | 0 – 6 kWh |
| 4 | `O`, standard output: `output_tokens − fast_output_tokens` | none; measured | – | 1 | 124.5M (fast output not recorded in these totals) |
| 5 | `e_decode`, Wh per output token at short context (8k), standard speed | the ~55 tok/s/user column, because standard Claude is served at ~47–51 | 3.0e-4 – 6.4e-4 | 2.1× | 37 – 80 kWh before `m` |
| 6 | context of the output: `output_context_product / output_tokens` | none; measured | – | 1 | ~185K (mean for each request; see above) |
| 7 | `m`, decode at that context ÷ decode at 8k | the simulated ratio from 8k to 128k | 1.5 – 3.0; 1.8 – 4.5 at 185K by the linear form below | **2×**; 2.5× with the linear form | – |
| 8 | the decode term: `e_decode × m × O` | – | – | – | 56 – 239 kWh |
| 9 | `e_fast`, Wh per fast-mode output token | at least the 100 tok/s/user column; fast mode is ~120–130 | 5.6e-4 – 1.3e-3, or more | at least 1.85–2.09× against step 5, on fast output only | 0 |
| 10 | power basis | all-in provisioned, with assumed chip power | provisioned to measured draw | up to ~4× lower; not measured | – |
| 11 | PUE | 1.10 – 1.20, inside step 5 | – | 1.09× | – |
| 12 | `E`, the sum of the terms | – | – | – | **60 – 280 kWh** |

**The steps that matter most are steps 5 and 7, the two halves of the
decode term.** Output is 0.52% of the tokens and 86–91% of the energy at
these constants. With each other step at the middle of its range, step 5
moves the result by ~95 kWh, step 7 by ~88 kWh, and step 2 by ~28 kWh.
Step 3 does not change the result by more than 6 kWh.

Notes on the steps:

- **Step 2.** The ratio route divides the decode range by the measured
  marginal ratio of output energy to input energy (4.3–8.4×, `caravaca`,
  A100). It gives 2e-5 – 6e-5. The K3 simulator gives 0.9e-5 – 2.3e-5 for
  an 8k prefill on Blackwell (`sa-dataflow`). DeepSeek's production
  disclosure gives 3.1e-5 – 3.8e-5 Blackwell-equivalent (`deepseek-day6`),
  which is an upper bound. See [Open tensions](#open-tensions).
- **Step 3.** A cache read loads stored KV tensors. It does not repeat the
  prefill computation. Both estimates put a cache read at 1/100 of a
  prefill token or less. You can set `e_read` to zero, but state that you
  did.
- **Step 5.** Other routes to `e_decode` give other values. The simulator
  gives 1.2e-4 – 1.9e-4 at 8k (`sa-dataflow`). DeepSeek's production fleet
  gives 6.8e-5 – 8.3e-5 Blackwell-equivalent at 20–22 tok/s/user
  (`deepseek-day6`). Across these routes the factor is up to ~9×. The
  ~55 column is the only one at the speed of standard Claude.
- **Step 7.** The linear form `m(c) = 1 + k × c` makes the sum over the
  requests exact:

  ```
  e_decode × m × O  becomes  e_decode × (O + k × output_context_product)
  ```

  Here `e_decode` is the value at a context near zero. The simulated
  ratios `r` = 1.51–2.96 from 8k to 128k give
  `k = (r − 1) / (128,000 − 8,000 × r)` = 4.4e-6 – 1.9e-5 per token of
  context. At 185K, that is `m` = 1.8–4.5. This is an extrapolation above
  128k (**derived** from **simulated** values). The linear form has a
  physical reason: a decode step is limited by memory bandwidth, and it
  reads the weights (a fixed amount) and the KV cache (an amount that is
  proportional to the context). No measurement on real hardware tests it.
- **Step 7.** `output_context_product` uses the context that the request
  was sent with. It does not include the tokens that the request
  generates, although decode also attends over them. For outputs of about
  1,000 tokens at a context of about 185k, the difference is less than 1%.
- **Step 9.** See [Fast mode](#fast-mode).

### Route 2b: the phases at production rates

DeepSeek published the throughput of its own production fleet for one day
(`deepseek-day6`). It is the only production disclosure from any lab. The
rates are tokens over node-time, so they include the real duty cycle.

| # | Quantity | Choice | Range | Factor | Example corpus |
|---|---|---|---|---|---|
| 1 | `P`, prefill tokens | as Route 2 | – | 1 | 561.3M |
| 2 | node power | an H800 node at 10.2 kW IT (the DGX H100 maximum) × PUE 1.10–1.35 (assumed) | 11.2 – 13.8 kW | 1.23× | – |
| 3 | `e_prefill`: all prefill-node energy charged to fresh tokens | node power ÷ fresh tokens per second per node | 9.7e-5 – 1.2e-4 Wh (H800) | 1.23×, from step 2 | 54 – 67 kWh |
| 4 | cache reads | excluded | – | – | 0 |
| 5 | `e_decode` at 20–22 tok/s/user and a mean KV length of ~5k | node power ÷ output tokens per second per node | 2.1e-4 – 2.6e-4 Wh (H800) | 1.23×, from step 2 | 26 – 32 kWh before `m` |
| 6 | `m` | as Route 2, step 7 | 1.5 – 3.0 | **2×** | 39 – 97 kWh |
| 7 | `E` on H800 | – | – | – | **94 – 163 kWh** |
| 8 | hardware generation | ÷ 3.11 for Blackwell (`sa-inferencemax`) | H800 to Blackwell-equivalent | 3.11× | 30 – 52 kWh |
| 9 | speed | DeepSeek served at 20–22 tok/s/user; standard Claude at ~47–51 | the 20 column to the ~55 column of `sa-tpu` | 1.9–2.7× on the decode term (derived); not applied in steps 7 and 8 | – |

**The step that matters most is step 8, the hardware generation: 3.11×.**
Step 6 (`m`, 2×) and step 9 (speed, 1.9–2.7× on decode) are next. Step 3
is an upper bound, because the same nodes also load the 56% of input that
hit DeepSeek's on-disk cache.

The fleet ran a 22% output share at a ~5k context. The example corpus is
0.52% output at ~185K. Thus the constants for each phase transfer, and the
energy per total token of the fleet does not.

## Route 3: top-down, from Anthropic's fleet

This route does not use a benchmark. SemiAnalysis estimates Anthropic's
API revenue per MW of compute (`sa-subs` figure 2). The inverse is energy
per dollar of API revenue. Apply it to the corpus at list price.

```
E = (Σ field × list price) × (MWh per MW-year ÷ API revenue per MW-year)
```

| # | Quantity | Choice | Range | Factor | Example corpus |
|---|---|---|---|---|---|
| 1 | `$`, the corpus at Opus 5.5 list: input $4, 5-minute write $5, 1-hour write $8, cache read $0.20, output $20 per million tokens | the TTL of the cache writes | all writes at 5 minutes to all at 1 hour | 1.17× | $9,907 – 11,570 |
| 2 | cache reads in `$` or not | include them: the revenue weighting is the fleet's own | with or without | **1.9×** (cache reads are 40–47% of `$`) | – |
| 3 | kWh per $ of API revenue: 8,760 MWh per MW-year ÷ $102.9M per MW | the period of "revenue per MW" is assumed to be one year; the MW basis is not stated | 0.0851 kWh per $ | not known; up to ~1.35× if the MW are IT power | – |
| 4 | `E = $ × kWh per $` | – | – | – | **840 – 990 kWh**; 450 – 590 without cache reads |
| 5 | capacity against draw | revenue per MW is on capacity, idle hardware included | – | not known; the result is an upper bound on the energy drawn | – |
| 6 | the model mix of the fleet | revenue per MW is a fleet average over models | Fable 5.1 list is 2.5× Opus 5.5 list | not known | – |

**The step that matters most is step 2, the cache reads: 1.9×.** Step 5
can be larger, but no source gives the utilisation of the fleet.

Notes on the steps:

- **Step 1.** The list prices are those of `sa-subs` figure 10, and they
  agree with Anthropic's price list. The 1-hour write price is 2× the input
  price. With the export fields, the split between `cache_write_5m` and
  `cache_write_1h` is known, so this step gives one value, not a range. For
  old transcripts the split is inferred (see
  [The export record](../DESIGN.md#the-export-record)).
- **Step 1.** The route prices every request at Opus 5.5 list, whatever
  model served it. The `cost` field of `csd export` uses the price of each
  model on the date of each request. It is a different quantity.
- **Step 2.** The revenue weighting charges a cache read at its price, not
  at its compute. A cache read costs 1/20 of an input token at list price,
  and less than 1/100 of a prefill token in compute. The SemiAnalysis
  agentic mix agrees with the corpus (96.6% cache reads), so the weighting
  is the fleet's own weighting.
- **Step 3.** The figure is internally consistent: $102.9M × (1 − 92.2%)
  = $8.0M of compute cost per MW, as the chart states. $8M per MW-year is
  $913 per MWh, against $1,090 of GB300 TCO per all-in MWh. Thus the MW
  are probably all-in.

### Route 3, cost-side check

The same quantity from the cost side. It is a check on step 3, not a
second estimate.

| # | Quantity | Choice | Range | Factor | Example corpus |
|---|---|---|---|---|---|
| 1 | `$`, as Route 3 | – | – | 1.17× | $9,907 – 11,570 |
| 2 | compute cost: `$ × (1 − margin)` | the API gross margin | 90 – 95% (Andras's estimate; SemiAnalysis gives 92.2%) | **2×** | $495 – 1,157 |
| 3 | kWh per $ of TCO: all-in kW per chip ÷ owning TCO per chip-hour | the chip | 0.74 – 1.40 (Ironwood); 0.92 (GB300); 1.06 – 1.27 (B200) | 1.9× | – |
| 4 | `E` | – | – | – | **370 – 1,620 kWh** |

**The step that matters most is step 2, the margin: 2×.** Step 3 (the
chip, 1.9×) is next.

## Which choices matter most

Largest first. The factor is for the step alone, with the others held
constant.

| Choice | Factor | Route and step | Does `csd` measure it? |
|---|---|---|---|
| The open model that stands in for Claude | 6.3× (V4 Pro to K3, same chip, engine, date and speed) | 1.3 | The model id only. Claude's parameter count is not published. |
| Deployment scale | 4.1× (8-GPU B200 node against GB300 NVL72) | 1.4 | No |
| Power basis | up to ~4× (TDP or provisioned against measured) | 1.8, 2.10 | No |
| Serving software | up to 4× between engines at one point; 1.6–1.8× from one software change in one day | 1.6 | No |
| Hardware generation | 3.11× (H100 to B200) | 1.5, 2b.8 | No. The hardware that serves Claude is not published. |
| `e_prefill` | 6× on the prefill term; ~28 kWh on the example corpus | 2.2 | No |
| `e_decode`, at a given speed | 2.1× | 2.5 | No |
| Speed, standard traffic | 1.33× from 75 to 100 tok/s/user; ≤ ~1.4× from the 75 column to ~50 | 1.7, 2.5 | Partly. Standard Claude is served at ~47–51 tok/s/user (assumed). |
| Speed, fast mode | at least 1.85–2.09× on fast-mode output only | 2.9 | **Yes**: `fast_output_tokens` |
| Context, `m` | 2× (1.5–3.0); 2.5× with the linear form | 2.7 | **Yes**: `output_context_product` |
| Margin | 2× (90–95%) | 3 check, 2 | No |
| Cache reads, in the top-down route | 1.9× | 3.2 | **Yes**: `cache_read` |
| Cache write TTL, in the top-down route | 1.17× | 3.1 | **Yes**: `cache_write_5m`, `cache_write_1h` |
| PUE | 1.09–1.35 where published | 2.11, 2b.2 | No |

Interactivity across a whole curve spans approximately 44× on one rack
(`sa-rubin` figures 15 and 16). For standard traffic, the speed of Claude
is now known approximately, and the remaining factor is small. Fast mode
is the exception.

Claude runs on at least four hardware stacks at the same time: AWS
Trainium2/3, Google TPUs, Nvidia on Azure, and Nvidia at xAI's Colossus 1.
No public source says which stack serves which model on which date
(`kezia-review`). A table of constants keyed by model and date would thus
have the same range in each row.

## Fast mode

Fast mode serves the same weights at ~2.5× the speed of standard mode, for
2× the price (`dib-dataset`, assumed; Anthropic's price list gives the 2×).
That is ~120–130 tok/s/user, above the 100 tok/s/user column. Fast-mode
output is the only part of a corpus above the speed range of the
evidence.

- A request records one timestamp, not a duration. Thus the transcripts do
  not show the speed of a request. `fast_output_tokens` is the only signal
  of speed that `csd` has.
- In Route 2, apply `e_fast` to `fast_output_tokens` and `e_decode` to the
  rest of `output_tokens`. `e_fast` is at least the 100 tok/s/user value,
  5.6e-4 – 1.3e-3 Wh per output token (`sa-tpu`), and no source gives a
  value at 120–130.
- Above 100 tok/s/user, the energy per token depends strongly on the
  hardware. From 100 to 125 tok/s/user, V4 Pro on Vera Rubin NVL72 uses
  1.15× more energy per token; on GB300 SGLang 2.4×; on GB300 TRT-LLM 7.1×
  (`sa-rubin` figure 16, derived).

## Cache counterfactual

If the 23.09B cache reads of the example corpus had been prefilled at
1e-5 – 6e-5 Wh each, they would have used 230 – 1,390 kWh. As cache reads,
at the simulated maximum, they used at most about 6 kWh. This is the
energy that the cache saved. It does not depend on the proxy model.

## Open tensions

Each tension gives the evidence in each direction. None is settled.

**Which open model stands in for Claude.** This is the largest open
question. The V4 Pro rows use a model with 49B active parameters.
SemiAnalysis uses Kimi K3 (2.8T total) as its proxy for Claude, by
parameter count (`sa-agentx`). On the same chip, engine, date and speed,
K3 gets 6.3× fewer tokens per dollar.

- Toward the lower figure:
  - K3's serving software was one month old, and the article says so.
    Software alone moved figures by 1.6–4× elsewhere in the same
    benchmark.
  - K3 has ~104B active parameters (Artificial Analysis; Epoch marks the
    figure "speculative"), against 49B for V4 Pro. That explains 2.1× of
    the 6.3×. The other ~3× is not the compute of the model.
  - Anthropic serves on its own stacks, not on public recipes.
  - Anthropic's fleet average (Route 3, 840–990 kWh) is 1.7–3.7×
    below the K3 result.
  - All figures use provisioned power.
- Toward the higher figure:
  - K3 is the only proxy that a source chose for Claude. Its figures agree
    across three chips.
  - The FT reported industry estimates of ~5T total parameters for Fable 5
    and ~8T for Mythos 5 (via `dib-dataset`; not read at the source). The
    two cannot both be correct, because Anthropic says that the two models
    share weights. But they put the class at several trillion total
    parameters, at or above K3. Thus K3 is not an upper bound on the size
    of the model.
  - The estimated active parameters of Claude are larger than those of V4
    Pro: Opus 5 ~100B (45–260B), Fable 5.1 ~150B (60–400B) (`dib-dataset`,
    estimates). If energy were proportional to active parameters, the V4
    Pro result would become 200–630 kWh at 100B and 310–950 kWh at 150B.
    This is an argument, not a figure.

The author of this document reads the K3 rows as an **upper bound on the
overhead of a Claude-sized model on public software**. They are not an
upper bound on its size, and they are not a central estimate for Claude.
That is judgement, not measurement. The fleet figure (Route 3) agrees
with it. Report both rows, and state which model your result assumes.

**The gap between the benchmarks and the fleet.** Route 3 is 2.7–9.9× above
the V4 Pro result of Route 1. Part of that gap is fleet utilisation and
provisioning: a benchmark at full load has no idle hardware. Part may be
the size of the model: the linear argument above gives 200–950 kWh. No
current source separates the two parts.

**The decode range assumes a speed.** 2e-4 – 6e-4 Wh per output token is
the 20–60 tok/s/user range. At 100 tok/s/user it is 5.6e-4 – 1.3e-3.
Artificial Analysis measured Opus 5 at 48–51 tok/s/user and Fable 5.1 at
47–50 (60–67 at the two highest effort levels) on 2026-09-13 (via
`dib-dataset`; not read at the source). Thus standard traffic is in the
~55 column. These speeds are for one provider path, measured from
outside. Two things move the value lower: provisioned power overstates
most at high speed, because small batches draw less than the rated power;
and these figures are from 8-GPU nodes or aggregated TPU serving, where
rack-scale and disaggregated serving use less energy. Quote a decode
figure only with its speed.

**The ratio of 1.85–2.09× assumes constant power.** `sa-tpu` gives costs
at ~55 and at 100 tok/s/user on the same chip. The hourly cost of a chip
does not change with its operating point, so the cost ratio is the energy
ratio if power per chip is constant. That is true of provisioned power.
It is not true of measured power (`kezia-review`).

**Prefill.** The ratio route gives 2e-5 – 6e-5 Wh. The K3 simulator gives
0.9e-5 – 2.3e-5. The ratio route carries the older hardware at the top of
the decode range. DeepSeek's production figure, 3.1e-5 – 3.8e-5
Blackwell-equivalent, is in the upper half of the range, and it is an
upper bound. No measured source on 2026 hardware exists.

**The KV size behind `m`.** Published architectures hold 69 KiB (MLA) to
504 KiB (GQA) of KV per token at FP16, and about half that at FP8
(`kezia-review`). `sa-dataflow` gives about 25 kB for new hybrid models
and about 70 kB for proven compressed attention. More KV per token makes
`m` larger. The simulated 1.5–3.0 is for K3, which has localized
attention. A model with full attention would have a larger `m`. In
FLOPs, decode attention at 128k adds only 17–43% to the weights
(`dib-dataset`), so `m` is an effect of memory bandwidth. Nothing is
measured on real hardware.

**Measured and simulated disagree on 8-GPU nodes.** AgentX puts V4 Pro on
B200 at 4.0e-5 Wh per total token. The simulator's K3 on B200 gives about
1e-5 for the same token mix. The models, the traces and the power bases
are different. The two are not reconciled.

**The basis of the top-down figure.** `sa-subs` labels its chart "rough
numbers". It does not state the period of "revenue per MW" or the basis
of the MW. A period other than one year changes the result in proportion.
The figure is on capacity, so it includes idle hardware.

## Sources

"Retrieved" is the date on which the page was read. For a page with a
paywall, only the part before the paywall was read.

### SemiAnalysis (InferenceX, InferenceMAX, AgentX, Tokenomics)

One publisher, one benchmark family and one power model (the "AI
Datacenter Industry Model"). The figures agree in basis, and they have the
same limits.

#### `sa-agentx`

- **Title:** *AgentX - InferenceXv3: Does CUDA Moat Hold up in Agentic
  Inferencing?*
- **URL:** <https://newsletter.semianalysis.com/p/agentx-inferencexv3-does-cuda-moat>
- **Authors:** Cam Quilici, Bryan Shan, Alec Ibarra, Daniel Nishball, Zane
  Fong, Kimbo Chen, Dylan Patel.
- **Published:** 2026-08-24 (chart data 2026-08-20 to 22).
  **Retrieved:** 2026-09-26, nearly all before the paywall.
- **Kind:** measured throughput. Cost from the SemiAnalysis TCO model. No
  power figure.
- **The workload** (text): SemiAnalysis staff's own Claude Code and Codex
  sessions, captured by a proxy. 8,000+ sessions, 3.4M requests, 610B
  tokens. 393 sessions are public:
  <https://huggingface.co/datasets/semianalysisai/cc-traces-weka-062126>.
  Dataset medians: input 142k, output 444. 44% of sessions use subagents.
  The replay limits idle time to 5 minutes.
- **Request sizes** (chart subtitles, about 1.6M completed requests, from
  figure 12): input p50 88k, p90 272k, p99 675k; output p50 413, p75 983,
  p90 2.2k, p99 8.6k. A log-normal fit gives a mean output of about 970 per
  request (derived).
- **Token mix:** figure 20, about 5% prefill, about 93% HBM cache hits and
  about 1.5% DRAM offload hits. Figures 28 and 29 together give output at
  0.69–0.78% of all tokens.
- **Model facts** (text): DeepSeek V4 Pro has 49B active of 1.6T. Kimi K3,
  2.8T, "is in the same range in terms of number of parameters vs Claude's
  Mythos/Fable5 model architecture. We use this as an open weights proxy."
  This is the only statement about the size of a Claude model by a
  benchmark publisher. It is SemiAnalysis's statement, not Anthropic's.
- **Figures taken:**
  - Chart title blocks: owning TCO in $/chip/hour, as `sa-engram`, and also
    MI300X 0.95, MI325X 1.10, RTX 6000 Pro 0.68. Exact.
  - Figure 7 (V4 Pro, tokens per $): GB300 TRT-LLM about 87M @80 and 62M
    @100 tok/s/user; B300 vLLM about 60M @40. Chart-read ±5%.
  - Figure 28 (K3, tokens per $): GB300 Dynamo vLLM 13.0M @50, 9.7M @83,
    3.1M @218; B300 vLLM 9.5M @40, 8.2M @64; B200 9.0M @44, 5.8M @86.
    Chart-read ±5–10%.
  - Figure 29 (K3, output tokens/s per chip): GB300 64 @50, 43 @83, 15 @218;
    B300 40 @64. Chart-read ±5–10%.
  - Text: SemiAnalysis says that it now captures power telemetry. It has not
    published it.
- **Derived:** tokens/s per chip = tokens per $ × TCO per hour ÷ 3,600.
  Wh per token = all-in W per chip ÷ (tokens/s per chip × 3,600). K3: GB300
  7.1e-5 @50, 9.5e-5 @83, 3.0e-4 @218; B300 9.6e-5 – 1.3e-4 @40–64; B200
  1.2e-4 – 2.2e-4 @44–86. Per output token, all other work included:
  9.2e-3 – 1.4e-2 Wh at 50–85 tok/s/user. Same chip, engine, date and
  speed (B300 vLLM @40): V4 Pro ÷ K3 = 6.3× in tokens per dollar.
  Cross-check: V4 Pro on GB300 @100 is 39.8k tokens/s per chip by this
  route, and 44.8k by `sa-rubin` three weeks later.
- **Limits:** K3 serving software was one month old. The article says that
  B200 performance was poor until one software change. K3 ran on vLLM only.
  All values are chart-read.

#### `sa-rubin`

- **Title:** *Rubin NVL72 Agentic Inference: 67x better Performance per
  Dollar*
- **URL:** <https://newsletter.semianalysis.com/p/vera-rubin-nvl72-agentic-inference>
- **Authors:** Bryan Shan, Alec Ibarra, Cam Quilici, Wenyao Gao, Dylan
  Patel.
- **Published:** 2026-09-14. **Retrieved:** 2026-09-25, before the paywall.
- **Kind:** measured throughput (AgentX, "InferenceX Official Preview";
  Rubin on pre-release TRT-LLM). Power from the SemiAnalysis model,
  all-in provisioned.
- **Operating point:** DeepSeek V4 Pro 0813, 1.6T total, 49B active; FP4
  (H200 at FP8); agentic; P90 speed.
- **Figures taken:**
  - Figure 16, a table, "Total throughput in million tok/s per all-in
    utility MW", at 75 / 100 / 125 / 150 / 170 / 200 tok/s/user.
    GB300 Dynamo SGLang 37.94 / 28.47 / 12.01 / 5.14 / 3.92 / 2.73.
    GB300 Dynamo TRT-LLM 44.14 / 21.15 / 2.97 / 1.01 / 0.35 / –.
    VR NVL72 TRT-LLM 64.00 / 59.38 / 51.55 / 36.98 / 21.78 / 7.43. Exact.
  - Text, at 100 tok/s/user: B200 SGLang 6.95M, B300 vLLM 5.56M, H200
    Dynamo SGLang (FP8) 2.26M, MI355X SGLang 2.01M tokens/s per MW. Exact.
  - Figure 15 title block: all-in power per chip, VR200 3.3 kW, GB300
    2.12 kW, MI355X 2.09 kW. Exact. Also the whole GB300 curve, ~53M at ~30
    to ~1.2M at ~280 tok/s/user (chart-read ±5%).
  - Text: SemiAnalysis gives 60–100 tok/s/user as the speed at which
    providers would serve this model.
  - Text, the paragraph on DSX MaxLPS: GPUs at medium to high inference
    speeds do not draw their full rated power. The publisher states here
    that the provisioned basis overstates.
- **Derived:** Wh per total token = 1 ÷ (M tokens/s per MW × 3.6). At 75–100
  tok/s/user: VR 4.3–4.7e-6; GB300 SGLang 7.3–9.8e-6; GB300 TRT-LLM 6.3e-6
  – 1.3e-5. At 100: B200 4.0e-5, B300 5.0e-5, H200 1.2e-4, MI355X 1.4e-4.
  At 100 tok/s/user, an 8-GPU B200 node uses 4.1× the energy per token of
  GB300 NVL72. GB300's owning TCO ($2.31, `sa-engram`) over its 2.12 kW is
  $1.09 per all-in kWh, so electricity at $0.05–0.10 per kWh is 5–9% of
  the TCO.
- **Limits:** preview results. A later model (V4.1 Flash) replaced this one
  before publication. The engine moves results by up to 4×.

#### `sa-engram`

- **Title:** *Engrams: Codesign for Efficient DRAM/SSD Offloading*
- **URL:** <https://newsletter.semianalysis.com/p/engrams-embedding-entendre-codesign>
- **Authors:** Bryan Shan, Cam Quilici, Alec Ibarra, Kimbo Chen, Myron Xie,
  Dylan Patel.
- **Published:** 2026-09-18. **Retrieved:** 2026-09-25, before the paywall.
- **Kind:** measured throughput (AgentX). Cost from the TCO model.
- **Operating point:** DeepSeek V4.1 Flash, 522B total, 8B active per
  prompt token and 16B per output token (figure 15), 1M context, vLLM.
- **Figures taken:**
  - Figure 14 title block: owning TCO, $/chip/hour, "Owning at Large
    Hyperscaler Volume", July 2026: H100 1.17, H200 1.22, B200 1.73, B300
    2.26, GB200 1.86, GB300 2.31, MI355X 1.50. Exact. These convert any
    tokens-per-dollar chart from the same benchmark into tokens/s per chip.
  - Figure 13 (B200, tokens per $1): about 192M / 147M / 121M / 60M at 62 /
    100 / 125 / 208 tok/s/user. The 121M is in the text (exact); the others
    are chart-read ±5%.
  - Figure 19: B300 improved 1.59–1.76× between the runs of 2026-09-15 and
    2026-09-16, from one software change.
- **Derived:** B200 running Flash, 92.3k tokens/s per chip @62 and 70.6k
  @100. With the assumed B200 all-in power: 5.5–6.6e-6 Wh per token @62,
  7.2–8.6e-6 @100. At 100 tok/s/user on one B200 node, V4 Pro gets about
  14.0k tokens/s per chip, against 70.6k for Flash: about 5× for model size.
- **Limits:** the article does not state B200 power. The conversion uses the
  assumed value below. Day-0 software.

#### `sa-dataflow`

- **Title:** *Computation and Data Movement for Inference*
- **URL:** <https://newsletter.semianalysis.com/p/computation-and-data-movement-for>
- **Authors:** Tanj Bennett, Bryan Shan, Dylan Patel.
- **Published:** 2026-09-21. **Retrieved:** 2026-09-25, before the paywall.
- **Kind:** **simulated** (the SemiAnalysis Inference Simulator:
  "workload-and-hardware projections, not measured benchmark results").
- **Operating point:** Kimi K3, with its localized-attention layers
  modelled. GB200 NVL72, B200, B300, 16–64 GPUs. Decode is 1,000 output
  tokens after 8k, 32k or 128k of context. Midfill is 1k tokens added to a
  cache of 31k or 127k. Prefill is 8k or 32k of fresh tokens.
- **Figures taken:** figure 28 (energy per query in J, log axis), chart-read
  ±15%. The legend uses some colours two times, so the identification of
  each series is a judgement.
  - Decode, throughput end (13–26 ms per output token), J per 1,000-token
    query: GB200 8k 590, 32k 655, 128k 892; B200 8k 417, 32k 489, 128k
    1,236; B300 8k 694, 32k 783, 128k 1,132.
  - Decode, latency end (4.5–6 ms per output token): 4,700–8,600 J per query.
  - 8k prefill: 270–650 J per query.
  - 127k + 1k midfill: 30–120 J per query.
  - Figures 3 to 5 plot Claude Code traces with the shape of the example
    corpus.
  - Text: KV about 25 kB per token for new hybrid models, about 70 kB for
    proven compressed attention.
- **Derived:** per token = J per query ÷ tokens ÷ 3,600. Decode 1.2–1.9e-4
  Wh @8k, 2.5–3.4e-4 @128k. `m` from 8k to 128k: 1.51× (GB200), 2.96×
  (B200), 1.63× (B300). 8k prefill 0.9–2.3e-5 Wh per token. If all the
  energy of a 127k + 1k midfill went to the cache read: ≤ 2.6e-7 Wh per
  cached token. This is an upper bound.
- **Limits:** simulated. The power model is not stated. K3's localized
  attention can make its context slope smaller than that of a model with
  full attention.

#### `sa-tpu`

- **Title:** *TPU Inference Externalization Full Steam Ahead — InferenceX*
- **URL:** <https://newsletter.semianalysis.com/p/tpu-inferencex-full-steam>
- **Authors:** Alec Ibarra, Cam Quilici, Bryan Shan, Wenyao Gao, Daniel
  Nishball, Zane Fong, Dylan Patel.
- **Published:** 2026-09-07. **Retrieved:** 2026-09-25.
- **Kind:** measured throughput. Cost from the TCO model.
- **Operating point:** Qwen3.5-397B FP8 (active parameters not published),
  8k in / 1k out; Ironwood, B200, B300.
- **Figures taken** (all in the text before the paywall, except the
  figure 3 title block):
  - At **20 tok/s/user**: 9,364 / 8,903 / 8,925 total tokens/s per chip.
  - At **100 tok/s/user**: $0.181 / $0.222 / $0.276 per million total
    tokens.
  - At a **20-second median response time**: $0.098 / $0.106 / $0.132. For
    8k in / 1k out, this is about 50–60 tok/s/user, not 20.
  - Figure 3 title block: "Hourly cost: TPU $1.21/chip • B200 $1.73/GPU •
    B300 $2.26/GPU". Exact. The B200 and B300 values agree with `sa-engram`.
  - Text: Anthropic committed to more than one million TPUs, "used mainly
    for training but also for inference" (SemiAnalysis, November 2025).
  - Text: Google uses disaggregated serving internally. The external stack
    does not. Thus these Ironwood figures overstate the energy of Google's
    own serving by an unstated amount.
- **Derived:** tokens/s per chip at 100 tok/s/user = TCO ÷ (3,600 × $ per
  token): 1,857 / 2,165 / 2,275. So 20 → 100 tok/s/user costs 3.9–5.0× per
  token. Converted to energy per output token with the assumed power below,
  and with the 8k/1k mix removed by the 4.3–8.4× ratio of `caravaca`:
  1.1–3.4e-4 @20, 3.0–6.4e-4 @~55, 5.6e-4 – 1.3e-3 @100.
- **Limits:** do not pair the costs at "20 seconds" with the throughput at
  "20 tok/s/user". They are different operating points.

#### `sa-inferencemax`

- **Title:** *InferenceMAX™: Open Source Inference Benchmarking*
- **URL:** <https://newsletter.semianalysis.com/p/inferencemax-open-source-inference>
- **Authors:** Kimbo Chen, Dylan Patel.
- **Published:** 2025-10-09. **Retrieved:** 2026-09-25.
- **Kind:** measured throughput. All-in provisioned power.
- **Operating point:** gpt-oss 120B (5.1B of 116.8B active), FP4, 1k in /
  8k out.
- **Figures taken** (section "Performance per MW Results"): H100 900,000
  and B200 2.8M tokens/s per all-in provisioned MW; MI300X 750,000 and
  MI355X 2.55M, at 90 tok/s/user. Also: "colocation rent and electricity
  cost typically make up less than 20% of the total cost of ownership".
- **Derived:** 3.09e-4 → 9.92e-5 Wh per token, **3.11×** for one hardware
  generation. The ratio transfers to other models. The level does not.

#### `sa-subs`

- **Title:** *Anthropic Subscriptions Offer 5x+ More Value Than OpenAI*
- **URL:** <https://newsletter.semianalysis.com/p/anthropic-subscriptions-offer-5x>
- **Published:** early October 2026. The page gives no date. The text
  refers to OpenAI's DevDay "last week" and to grandfathering until
  October 29th. **Retrieved:** 2026-10-06, before the paywall.
- **Kind:** **estimated** (the SemiAnalysis Tokenomics Model; figure 2 says
  "All numbers are rough estimates"), and measured subscription limits. No
  power figure.
- **Figures taken:**
  - Figure 2, "Anthropic unit economics · rough numbers", exact as printed:
    - API: $102.9M revenue per MW, 92.2% gross margin, 90% of revenue,
      58.3% of compute.
    - Subscriptions: $16M per MW, 50% margin, 10% of revenue, 41.7% of
      compute.
    - Blended: $66.7M per MW, 88.0% margin, $8M compute cost per MW.
    - The period and the MW basis are not stated.
  - Figure 10, the worked example:
    - SemiAnalysis's September agentic mix: 0.4% input, 2.6% cache writes,
      96.6% cache reads, 0.3% output.
    - Opus 5.5 list: $4 input, $5 cache write, $0.20 cache read, $20
      output per million tokens.
  - Text: Opus 5.5 cut input and output prices by 20% against Opus 5, and
    cache reads by 60%.
- **Derived:** 8,760 MWh ÷ $102.9M = 0.0851 kWh per $ of API revenue
  (period assumed to be one year). On the SemiAnalysis mix at Opus 5.5
  list: 3.4e-5 Wh per total token. $102.9M × 7.8% = $8.0M, as stated.
  $8M per MW-year is $913 per MWh, against $1,090 of GB300 TCO per all-in
  MWh, so the MW are probably all-in.
- **Limits:** estimates from a paid model, not disclosures. Revenue per MW
  is a fleet average over models and workloads. It is on capacity, not on
  draw.

### Production disclosures and secondary data

#### `deepseek-day6`

- **Title:** *Day 6: One More Thing — DeepSeek-V3/R1 Inference System
  Overview* (open-infra-index, Open Source Week).
- **URL:** <https://github.com/deepseek-ai/open-infra-index/blob/main/202502OpenSourceWeek/day_6_one_more_thing_deepseekV3R1_inference_system_overview.md>
- **Authors:** DeepSeek.
- **Published:** 2025-03-01. **Retrieved:** 2026-10-04, the whole page.
- **Kind:** **measured** production throughput: a lab's own fleet over 24
  hours. No power figure.
- **Operating point:** DeepSeek V3/R1 (671B total, 37B active), FP8, H800.
  Prefill over 4 nodes (EP32), decode over 18 nodes (EP144), disaggregated.
  Web, app and API traffic, 12:00 2025-02-27 to 12:00 2025-02-28, UTC+8.
- **Figures taken** (text, exact):
  - Peak 278 nodes, average 226.75 nodes of 8 H800. Nodes move to research
    and training at night, so the average is the inference fleet.
  - 608B input tokens, of which 342B (56.3%) hit the on-disk KV cache;
    168B output tokens; 20–22 tok/s/user; mean KV length per output token
    4,989.
  - Per node: 73.7k input tokens/s in prefill (cache hits included), 14.8k
    output tokens/s in decode.
- **Check:** those rates account for 5,445 of the 5,442 node-hours. Thus
  they are tokens over node-time, and they include the real duty cycle.
- **Derived** (with the assumed H800 node power below): fleet 61–75 MWh per
  day, 7.9–9.7e-5 Wh per total token on its own mix. Decode 2.1–2.6e-4 Wh
  per output token on H800, 6.8–8.3e-5 Blackwell-equivalent (÷ 3.11).
  Prefill 4.2–5.2e-5 per input token with cache hits included, or
  9.7e-5 – 1.2e-4 charged to fresh tokens only (3.1–3.8e-5
  Blackwell-equivalent).
- **Limits:** a 22% output share at ~5k context, unlike agentic coding.
  The power is assumed.

#### `dib-dataset`

- **Title:** *Compute cost of human work*, dataset and research notes
  (snapshot `v1-2026-09-17`, commit `d8afbff`).
- **URL:** <https://github.com/damonbinder/compute-cost-of-human-work>
- **Authors:** Damon Binder, with research notes that ChatGPT and Claude
  agents wrote at his direction. CC0.
- **Published:** 2026-09-17. **Retrieved:** 2026-10-04.
- **Kind:** secondary. The notes cite primary sources (Artificial Analysis,
  Epoch, SemiAnalysis, the FT, `unexcitedneurons`). Each figure below is
  as the notes report it. None was examined at its primary source.
  Under the kinds of this document, every figure taken from it is
  **assumed**.
- **Figures taken:**
  - Active parameters (`models.csv`): DeepSeek V4 Pro 49B (reported); Kimi
    K3 104B of 2.78T (Artificial Analysis; Epoch "Speculative"). Estimated
    priors: Claude Opus 5 100B (45–260B), Fable 5 and 5.1 150B (60–400B).
  - Served decode speeds (Artificial Analysis, 2026-09-13), tok/s/user at
    low / medium / high / xhigh / max effort: Opus 5 48 / 48 / 50 / 51 /
    51; Fable 5.1 47 / 50 / 49 / 60 / 67. Earlier: Opus 4.5–4.7 ~44, Opus
    4.8 58. Sonnet 4.5 48.7 on Bedrock and 38.5 on Azure.
  - Fast mode: the same weights at "roughly 2.5x normal speed" for 2× the
    price.
  - Total parameters (the FT, 2026-08-07): industry estimates of ~8T for
    Mythos 5 and ~5T for Fable 5. These are inconsistent, because
    Anthropic says that the two models share weights.
  - Decode attention FLOPs relative to 2P: 1.04 at 32k and 1.17 at 128k
    for a 100B model; 1.43 at 128k for 40B.
- **Limits:** speed is an engineered product property at Anthropic, so a
  model size inferred from speed is uncertain by ±2.5×.

#### `unexcitedneurons`

- **Title:** *Estimating the size of Claude Opus*
- **URL:** <https://unexcitedneurons.substack.com/p/estimating-the-size-of-claude-opus>
- **Published:** 2026-03-12. **Retrieved:** 2026-10-04, before the paywall.
- **Kind:** derived from decode speed on Google Vertex and an effective
  bandwidth calibrated on three open models.
- **Taken:** Opus 4.6 at 43 tok/s/user implies 93–105 GB of active weights
  per token: 93–105B active at FP8, 127–154B with FP4 experts. The author
  says: "I have no clue what optimizations Opus may have". Not used in a
  chain.

### Papers and preprints

- **`oviedo`**: Oviedo et al. (Microsoft), *Energy use of AI inference,
  efficiency pathways, and test-time scaling*, Joule (2026).
  <https://arxiv.org/abs/2509.20241>. Measured and modelled, H100 nodes,
  frontier scale, production assumptions. Taken: median 0.31 Wh per query
  (IQR 0.16–0.60) over a response of 300–500 tokens. A 15× longer
  **output** costs 12.6×. That result is about output length, not context
  length (`kezia-review`).
- **`google`**: Elsworth et al. (Google), *Measuring the environmental
  impact of delivering AI at Google Scale*, 2025-08-21.
  <https://arxiv.org/abs/2508.15734>. Production telemetry, full stack.
  Taken: 0.24 Wh for the median Gemini Apps text prompt (0.14 accelerator,
  0.06 host, 0.02 idle, 0.02 PUE). The paper does not give the number of
  output tokens. About 8e-4 Wh per output token assumes about 300.
- **`caravaca`**: Caravaca, Cuevas & Cuevas, *From Prompts to Power*,
  2025-11-05. <https://arxiv.org/abs/2511.05597>. Measured, 21 GPU
  configurations, reference figures on A100. Taken: the marginal ratio of
  output to input energy, 4.3× (opt-30b) to 8.4× (mean across models).
  3.6e-4 Wh per output token for opt-30b.
- **`mlenergy`**: Chung et al., the ML.ENERGY benchmark.
  <https://arxiv.org/abs/2505.06371>. Measured. Taken: 0.12 J per token for
  an 8B model at batch 64; TDP overstates energy by up to 4.1× (as cited in
  `kezia-review`; not yet examined in the paper).
- **`luccioni`**: Luccioni, Jernite & Strubell, *Power Hungry Processing*,
  FAccT '24. <https://arxiv.org/abs/2311.16863>. The type of task changes
  energy more than the size of the model. Every per-query source above
  measures chat. The transcripts that `csd` reads are agentic coding.

**The five decode routes.** Four are on H100-era hardware or older, at
short context and an unstated speed: `caravaca` 3.6e-4 (A100, a 30B dense
model), `epoch` 6e-4, `google` about 8e-4, `oviedo` 6.2e-4 – 1.0e-3 Wh per
output token. The fifth, `sa-tpu`, is on 2026 silicon: 1.1e-4 – 3.4e-4 at
20 tok/s/user. The three frontier-scale H100 routes divided by 3.11× give
1.9e-4 – 3.2e-4. That overlaps the 2026 figure. The routes measure one
quantity on two hardware generations. They do not conflict.

### Other sources

- **`epoch`**: Epoch AI, *How much energy does ChatGPT use?*, 2025-02-07.
  <https://epoch.ai/gradient-updates/how-much-energy-does-chatgpt-use>.
  FLOPs × TDP. Taken: 0.3 Wh per GPT-4o query over a stated 500 output
  tokens, so 6e-4 Wh per output token.
- **`kezia-review`**: Kezia Cousins, the review of issue #1, 2026-09-25.
  <https://github.com/keziacousins/claude-session-diagnostics/issues/1#issuecomment-5839492585>.
  Taken: the table of factors; the hardware that serves Claude (Trainium2/3,
  Google TPUs, Nvidia on Azure, xAI Colossus 1 at 300 MW through May 2029,
  <https://techcrunch.com/2026/05/20/anthropic-will-pay-xai-1-25-billion-per-month-for-compute/>);
  KV per token, 69 KiB (DeepSeek-V3, MLA, FP16,
  <https://arxiv.org/abs/2412.19437> §4.2) to 504 KiB (Llama 3.1 405B, GQA,
  FP16, <https://arxiv.org/abs/2407.21783> Table 3); energy per bit, about
  20 pJ for a DRAM read (Horowitz, ISSCC 2014), 4–11 pJ for PCIe, 1.3 pJ for
  NVLink-C2C, 3–4 pJ for HBM (no primary source); a cache read at 5e-10 –
  7e-8 Wh per token; PUE 1.09–1.35 where published; the correction of the
  generation factor to 3.11×.
- **`kezia-pr-review`**: Kezia Cousins, the review of PR #2, 2026-09-26.
  <https://github.com/keziacousins/claude-session-diagnostics/pull/2#pullrequestreview-5325219354>.
  Taken: on a second corpus (69,929 requests), the mean context weighted
  by output is 240K against a mean context of 178K.
- **`google-ironwood`**: Google, the Ironwood announcement.
  <https://blog.google/products/google-cloud/ironwood-tpu-age-of-inference/>.
  Taken: 9,216 chips in "nearly 10 MW".
- **`dib-cheaper`**: Damon Binder, *When they can perform a task, AIs are
  much cheaper than humans*, 2026-09-27.
  <https://defensesindepth.bio/when-they-can-perform-a-task-ais-are-much-cheaper-than-humans/>.
  No energy figure. It is the link to `dib-dataset`, and through it to
  `deepseek-day6` and `unexcitedneurons`.

### Assumed inputs

A source that gives throughput and no power needs these values. They are the
weakest inputs here: secondary reporting and vendor rack figures.

- **Ironwood**, IT power 1,085–1,406 W per chip: from `google-ironwood`
  (9,216 chips in nearly 10 MW) to about 90 kW per rack of 64 chips. The
  package TDP of about 600 W is the wrong denominator.
- **B200** (GB200 NVL72), 1,667–1,833 W per chip: 120 kW nominal to 130–132
  kW sustained per rack, over 72 GPUs.
- **B300** (GB300 NVL72), 1,875–1,972 W per chip: 135–142 kW per rack over
  72 GPUs.
- **H800 node** (8 GPUs, for `deepseek-day6`): 10.2 kW IT, the DGX H100
  maximum.
- **PUE** 1.10–1.20 for the chips above; 1.10–1.35 for the H800 node.
- Thus B200 all-in is about 1.83–2.20 kW, and an H800 node all-in is
  11.2–13.8 kW. The only all-in value that SemiAnalysis states for a
  Blackwell part is GB300 at 2.12 kW (`sa-rubin`). That is inside the
  equivalent B300 range, 2.06–2.37 kW.

### Not used

- Sam Altman's 0.34 Wh per query: no method is published.
- The older figure of 3 Wh per query: Epoch's estimate revises it by 10×.
- Mistral's lifecycle analysis of Mistral Large 2: it gives CO2e and water,
  not energy.
- **Retired 2026-10-06:** an Anthropic inference margin of ~70%, and the
  upper bound of 4,000–8,500 kWh for the example corpus that came from it.
  The margin was secondhand (`dib-dataset`), and no primary source for it
  was found. SemiAnalysis's own figure is 92.2% on API (`sa-subs`). The
  cost-side check now uses 90–95%.

## Watch list

These publications would change the ranges. The most useful comes first. A
figure without its full operating point cannot be used.

1. **Measured power** in InferenceX (announced as "PowerX"). The ratio of
   measured to provisioned power for one configuration at several speeds
   would correct every per-MW figure here.
2. **AgentX on TPU (Ironwood) and Trainium2/3**, the stacks known to serve
   Claude. Capture tokens/s per all-in MW, or tokens per $ with the TCO in
   the chart title.
3. **Any chart of tokens/s per all-in MW** with its power per chip. The
   B200, B300 and H800 node values are still assumed here.
4. **Context-length sweeps on real hardware**: decode at 8k / 32k / 128k /
   1M, or runs with and without cache hits. This would make `m` measured.
5. **One model at two sizes on one benchmark and one chip**, with active
   parameters, and K3 on mature software. This decides the question of the
   proxy model.
6. **The speeds at which Claude is served**, read directly from Artificial
   Analysis at each release, for each provider (Anthropic API, Bedrock,
   Vertex, Azure). Any change in the price or the speed of fast mode.
7. **Anthropic fleet data**: the period and the MW basis of "revenue per
   MW"; revenue per MW for each model; fleet utilisation, which converts
   capacity into drawn energy; MW and PUE for each site.
8. **Anthropic's API margin and revenue per MW** in later SemiAnalysis
   publications, and changes to list prices. The top-down result is
   proportional to 1 ÷ revenue per MW.
9. **Another production disclosure** like `deepseek-day6`: fleet size,
   tokens per day and throughput for each phase, from any lab.
10. **Dated reruns of an unchanged configuration**: how fast software
    alone moves the figures.
11. **The public AgentX dataset** (link under `sa-agentx`): exact shares of
    cached, fresh and output tokens, and the value of
    `output_context_product` for those traces.

Also: any active parameter count for a Claude model, and any energy
disclosure from Anthropic.

## Errors to avoid

Each of these occurred at least once during this work.

- Two different "20"s: 20 seconds of latency and 20 tok/s/user.
- P90 speed read as median speed.
- A cost per token with no TCO: cost alone gives no energy.
- Throughput per decode chip in a disaggregated configuration, compared
  with throughput per chip in an aggregated one.
- Charts marked "preview" or "UNOFFICIAL overlay".
- Package TDP used as the power denominator.
- Energy derived from price through an assumed share of electricity. A
  price includes hardware, colocation, cost of capital and margin.
  Electricity and colocation together are less than 20% of the TCO
  (`sa-inferencemax`). On GB300 at $0.05–0.10 per kWh, electricity alone is
  5–9%. That conversion gives back only the share that you assumed. Route
  3 is different: it uses a stated revenue per MW of the fleet that served
  the tokens.
- Model size read from decode speed. Anthropic sets its serving speed as a
  product property, and it sells fast mode. Thus speed underestimates
  size.
- Cost weighted by revenue read as compute. At Opus 5.5 list, cache reads
  are 40–47% of the price of the example corpus (57–64% at Opus 5 list),
  and much less than 1% of its compute.
- Token counts compared across tokenizers. Claude 4.7 and later produce
  approximately 30% more tokens for the same text. Energy per token
  transfers per position. Token counts do not transfer.
- A figure chosen high "to be safe". A result three times too high is as
  wrong as a result three times too low.
