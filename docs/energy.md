# Energy per token: the evidence

**`csd` does not read this file, and it ships no energy constant.** This
document is the working behind the constants that a user can choose. It
records the published evidence, the arithmetic, and the assumption behind
each figure. The user supplies every constant and owns it.

`csd export` supplies the measured half: the token quantities of each
session. This document supplies the other half, and that half is not
measured for Claude. No provider publishes energy per token for a Claude
model. No source publishes the hardware, the batch size or the speed at
which Claude is served. Every figure below is therefore a range, and each
range has its operating point beside it.

Last revised 2026-09-26. The figures come from benchmarks that change
each week. Examine the dates before you use a range.

The text uses the terms in [`DESIGN.md`](../DESIGN.md). A **request** is
one billed API call. The **context** is the number of prompt tokens that a
request sends. A **cache read** and a **cache write** are the reported
token fields.

## How to read the figures

Each figure has one of these kinds. Keep them separate.

| Kind | Meaning |
|---|---|
| **measured** | A benchmark or a telemetry system recorded the value. |
| **simulated** | A model of the hardware and the workload calculated the value. |
| **derived** | This document calculated the value from published figures. The arithmetic is given. |
| **assumed** | A value that no primary source gives. Secondary reporting or a vendor rack figure supplies it. |

Each power figure also has a **basis**. The bases differ by up to 4×. That
is as large as the quantities that this document estimates.

| Basis | Meaning |
|---|---|
| package TDP | The rated power of the chip package only. Do not use it as a denominator. |
| IT power per chip | The power of the rack, divided by the chips in it. |
| all-in provisioned | IT power plus cooling and electrical losses, at the rated maximum. |
| measured draw | The power that the hardware drew during the benchmark. |

Most figures here use **all-in provisioned** power. Hardware in inference
does not draw its full rated power. Therefore these figures are upper
bounds, by an unknown factor of up to about 4×.

An **operating point** is the model (with its **active** parameters), the
precision, the hardware, the deployment scale (one node or one rack), the
serving engine, the speed in output tokens per second for each user
(tok/s/user), the context and the workload. Two figures that differ in any
of these are not comparable unless you state how they differ.

**Figure numbers** count the charts of an article in page order, from 1.
"Chart-read ±5%" means that the value was read from a chart, not from a
table or from the text.

## Apply constants to the export fields

`csd export` gives these measured fields for each session. See
[The export record](../DESIGN.md#the-export-record).

- `input_tokens`, `cache_write_5m`, `cache_write_1h`, `cache_read`: the
  split of the prompt tokens. The four fields do not overlap.
- `output_tokens`.
- `output_context_product`: the sum, for each request, of `output_tokens`
  × the context of the request.
- `fast_output_tokens`: the output of the requests that ran in fast mode.

Use one of two routes. Do not add terms from one route to the other.

### Route 1: energy per total token

```
E = e_total × (input_tokens + cache_write_5m + cache_write_1h + cache_read + output_tokens)
```

`e_total` is energy per token of all kinds, measured on a workload of the
same shape. The cache reads, the decode at long context and the prefill are
already inside the constant. This is the best route when a benchmark
replays agentic coding traffic. AgentX does that (`sa-agentx`).

The route is correct only if the token mix of your sessions agrees with the
mix of the benchmark. Compare them first. The AgentX mix is about 5%
prefill, about 95% cache reads and 0.7–0.8% output.

### Route 2: the phases, with a context term

```
E = e_prefill × (input_tokens + cache_write_5m + cache_write_1h)
  + e_decode  × D
  + e_read    × cache_read
```

- `e_prefill` is energy per fresh prompt token. A cache write is a prefill
  that the API also stores. Count it as prefill.
- `e_read` is energy per cache read. The evidence puts it at less than
  1/100 of `e_prefill`. You can set it to zero, but state that you did.
- `D` is the output, weighted by the context at which it was generated.

For `D`, use one of these:

- **One multiplier.** `D = output_tokens × m`. Choose `m` for the mean
  context, weighted by output:
  `output_context_product / output_tokens`.
- **A linear context term.** Assume `m(c) = 1 + k × c` for a context of
  `c` tokens. Then the sum over the requests is exact:

  ```
  D = output_tokens + k × output_context_product
  ```

  Here `e_decode` is the value at a context near zero.

The linear form is an assumption. It has a physical reason: a decode step is
limited by memory bandwidth, and it reads the weights (a fixed amount) and
the KV cache (an amount proportional to the context). No measurement on real
hardware tests it. The simulator figures in `sa-dataflow` give two points,
at 8k and 128k. For a ratio `r = E(128k) / E(8k)`:

```
k = (r − 1) / (128,000 − 8,000 × r)
```

The simulated ratios 1.51–2.96 give `k` = 4.4e-6 – 1.9e-5 per token of
context. At 185k tokens, that is `m` = 1.8–4.5. This is an extrapolation
above 128k (**derived** from **simulated** values).

`output_context_product` uses the context that the request was sent with.
It does not include the tokens that the request generates, although decode
also attends over them. For outputs of about 1,000 tokens at a context of
about 185k, the difference is less than 1%.

### Speed

Energy per output token increases with the speed of generation. On one chip
and one model, 20 → 100 tok/s/user costs 3.9–5.0× the energy per token
(`sa-tpu`). The transcripts do not record a duration for each request.
`fast_output_tokens` is the only signal of speed that `csd` has. If you use
a different `e_decode` for fast mode, apply it to `fast_output_tokens`, and
apply the standard value to `output_tokens − fast_output_tokens`.

### What to state with a result

State the route, each constant, the operating point of each constant, the
power basis, and which open model stands in for Claude. A result without
these cannot be checked.

## Current ranges

As of 2026-09-26.

### Energy per total token, agentic coding

These are for Route 1. The model that stands in for Claude changes the
result more than any other choice. See [Tensions](#open-tensions).

| Operating point | Wh per total token | Kind, basis | Source |
|---|---|---|---|
| DeepSeek V4 Pro (1.6T total, **49B active**), FP4, Vera Rubin NVL72 or GB300 NVL72 (rack scale), TRT-LLM or SGLang, **75–100 tok/s/user** | **4.3e-6 – 1.3e-5** | measured throughput; all-in provisioned power | `sa-rubin`, `sa-agentx` |
| DeepSeek V4 Pro, B200 or B300 **8-GPU node**, 100 tok/s/user | 4.0e-5 – 5.0e-5 | as above | `sa-rubin` |
| DeepSeek V4 Pro, H200 (FP8) or MI355X, 100 tok/s/user | 1.2e-4 – 1.4e-4 | as above | `sa-rubin` |
| DeepSeek V4.1 Flash (522B total, 8B active per prompt token, 16B per output token), B200, 62–100 tok/s/user | 5.5e-6 – 8.6e-6 | measured throughput; TCO model; **assumed** B200 power | `sa-engram` |
| **Kimi K3 (2.8T total, active not published)**, GB300 or B300, vLLM, **40–85 tok/s/user** | **7.1e-5 – 1.3e-4** | measured throughput; TCO model; stated or assumed all-in power; serving software one month old | `sa-agentx` |

On the same chip, engine, date and speed (B300, vLLM, 40 tok/s/user), V4
Pro gets **6.3×** the tokens per dollar that K3 gets. The first and the last
rows differ by more than 6.3×, because they also differ in deployment scale
and speed.

The K3 row, per **output** token with all other work included: 9.2e-3 –
1.4e-2 Wh at 50–85 tok/s/user.

### Energy by phase

These are for Route 2.

| Quantity | Range | Operating point | Kind | Source |
|---|---|---|---|---|
| Decode, per output token, short context | **2e-4 – 6e-4 Wh** | 20–60 tok/s/user; 2026 silicon, or older silicon divided by 3.11× | five routes, reconciled; see below | `sa-tpu`, `sa-inferencemax`, `oviedo`, `google`, `epoch` |
| Decode, per output token, short context, by speed | 1.1–3.4e-4 @20; 3.0–6.4e-4 @~55; 5.6e-4 – 1.3e-3 @100 tok/s/user | Qwen3.5-397B FP8, 8k in / 1k out; Ironwood, B200, B300 | measured throughput; provisioned power; derived | `sa-tpu` |
| Decode, per output token, 8k context | 1.2e-4 – 1.9e-4 Wh | Kimi K3, GB200 / B200 / B300, throughput end (13–26 ms per output token) | simulated | `sa-dataflow` |
| Decode, per output token, 128k context | 2.5e-4 – 3.4e-4 Wh | as above | simulated | `sa-dataflow` |
| `m`, decode at 128k ÷ decode at 8k | **1.5 – 3.0** | as above; K3 has localized attention | simulated | `sa-dataflow` |
| `k`, the linear context term | 4.4e-6 – 1.9e-5 per token | from the row above | derived | this document |
| Prefill, per fresh prompt token | **1e-5 – 6e-5 Wh**, open | ratio route 2e-5 – 6e-5; simulator 0.9e-5 – 2.3e-5 | derived; simulated | `caravaca`; `sa-dataflow` |
| Cache read, per token | **≤ 2.6e-7 Wh** (simulated ceiling); 5e-10 – 7e-8 (physical estimate) | K3 midfill; bytes moved × energy per bit | simulated; derived | `sa-dataflow`; `kezia-review` |

**The five decode routes.** Four are on H100-era hardware or older, at
short context and an unstated speed: `caravaca` 3.6e-4 (A100, a 30B dense
model), `epoch` 6e-4, `google` about 8e-4, `oviedo` 6.2e-4 – 1.0e-3 Wh per
output token. The fifth, `sa-tpu`, is on 2026 silicon: 1.1e-4 – 3.4e-4 at
20 tok/s/user. `sa-inferencemax` measures one hardware generation (H100 →
B200) at 3.11×. The three frontier-scale H100 routes divided by 3.11× give
1.9e-4 – 3.2e-4. That overlaps the 2026 figure. The routes measure one
quantity on two hardware generations. They do not conflict.

**Cache reads cost little.** A cache read loads stored KV tensors. It does
not repeat the prefill computation. Both estimates put a cache read at 1/100
of a prefill token or less. The cost of a long context is in two other
places: each output token attends over the whole KV cache (`m`), and each
fresh token in prefill attends over the cached prefix.

## Applied to one corpus

This is an example, not a result for Claude. The corpus is one person's
Claude Code transcripts, as `csd summary` reported them in
[issue #1](https://github.com/keziacousins/claude-session-diagnostics/issues/1):
124,484 requests, 6.9M input tokens, 554.4M cache writes, 23,087.4M cache
reads and 124.5M output tokens. That is 23.77B tokens in total, 97.1% cache
reads and 0.52% output. The totals are minimums (see `csd coverage`).

Its shape agrees with the AgentX traces (`sa-agentx`):

| | AgentX | this corpus |
|---|---|---|
| tokens per request | ~179k | ~185k |
| mean output per request | ~970 | ~1,000 |
| output share | 0.7–0.8% | 0.52% |
| cache reads, share of prompt tokens | ~95% | 97.6% |

Route 1 applied to it:

| Constant | Corpus |
|---|---|
| V4 Pro, rack scale, 75–100 tok/s/user | **100 – 310 kWh** |
| V4 Pro, 8-GPU B200 or B300 node, 100 tok/s/user | 950 – 1,190 kWh |
| V4 Pro, H200 or MI355X, 100 tok/s/user | 2,900 – 3,300 kWh |
| V4.1 Flash, B200, 62–100 tok/s/user | 130 – 210 kWh |
| **K3, GB300 or B300, 40–85 tok/s/user** | **1,700 – 3,000 kWh** |
| K3, GB300, 218 tok/s/user | ~7,000 kWh |

For comparison: if the 23.09B cached tokens had been prefilled at 1e-5 –
6e-5 Wh each, they would have cost 230 – 1,390 kWh. The cache reads at the
simulated ceiling cost at most about 6 kWh.

Across these rows the result spans about 100 to 7,000 kWh. The span becomes
about 3× only if you fix the model, the hardware generation and the speed.
No source confirms any of the three for Claude.

## What changes the result

Largest first.

| Factor | Span | Evidence | Does `csd` measure it? |
|---|---|---|---|
| Speed (tok/s/user) | 3.9–5.0× from 20 → 100 tok/s/user (8k in / 1k out); 1.33× from 75 → 100 (agentic); about 44× across one whole curve on one rack | `sa-tpu`; `sa-rubin` figures 15 and 16 | Partly: `fast_output_tokens`. A request has one timestamp, not a duration. |
| Model size | about 5× per chip, V4 Pro vs V4.1 Flash, same node; 6.3× K3 vs V4 Pro, same chip, engine, date and speed | `sa-engram` with `sa-rubin`; `sa-agentx` | The model id only. Claude's parameter count is not published. |
| Deployment scale | 4.1×, 8-GPU B200 node vs GB300 NVL72, same model and speed | `sa-rubin` | No |
| Serving software | up to 4× between engines at one point; 1.6–1.8× from one software change in one day | `sa-rubin` figure 16; `sa-engram` figure 19 | No |
| Power basis | up to about 4× (TDP vs measured); about 2× (package TDP vs rack) | `mlenergy` via `kezia-review`; `sa-tpu` | No |
| Hardware generation | 3.11× (H100 → B200) | `sa-inferencemax` | No. The hardware that serves Claude is not published. |
| Context length | 1.5–3.0× on decode, 8k → 128k | `sa-dataflow` | Yes: `output_context_product` |
| PUE | 1.09–1.35 where published | `kezia-review` | No |

Claude runs on at least four hardware stacks at the same time: AWS
Trainium2/3, Google TPUs, Nvidia on Azure, and Nvidia at xAI's Colossus 1.
No public source says which stack serves which model on which date
(`kezia-review`). A table of constants keyed by model and date would
therefore have the same range in each row.

## Open tensions

Each tension gives the evidence in each direction. None is settled.

**Which open model stands in for Claude.** This is the largest open
question. The V4 Pro rows use a model with 49B active parameters.
SemiAnalysis uses Kimi K3 (2.8T total) as its proxy for Claude, by
parameter count (`sa-agentx`). On the same chip, engine, date and speed,
K3 gets 6.3× fewer tokens per dollar.

- Toward the lower figure: K3's serving software was one month old, and the
  article says so. Software alone moved figures by 1.6–4× elsewhere in the
  same benchmark. K3's active parameter count is not published. Anthropic
  serves on its own stacks, not on public recipes. All figures use
  provisioned power.
- Toward the higher figure: K3 is the only proxy that a source chose for
  Claude. Its figures agree across three chips.

The author of this document reads the K3 rows as an **upper bound for a
Claude-sized model on public software**, not as a central estimate for
Claude. That is judgement, not measurement. Report both rows, and state
which model your result assumes.

**The decode range assumes a speed.** 2e-4 – 6e-4 Wh is the 20–60
tok/s/user regime. At 100 tok/s/user it is 5.6e-4 – 1.3e-3. No source states
the speed at which Claude is served. Two things move the value toward the
lower range: provisioned power overstates most at high speed, because small
batches draw less than the rated power; and these figures are from 8-GPU
nodes or aggregated TPU serving, where rack-scale and disaggregated serving
do better. Quote a decode figure only with its speed.

**The 1.85–2.09× ratio assumes constant power.** `sa-tpu` gives costs at
~55 and at 100 tok/s/user on the same chip. The hourly cost of a chip does
not change with its operating point, so the cost ratio is the energy ratio,
if power per chip is constant. That is true of provisioned power. It is not
true of measured power (`kezia-review`).

**Prefill.** The ratio route divides the decode range by the measured
marginal ratio of output to input energy (4.3–8.4×, `caravaca`, A100). It
gives 2e-5 – 6e-5 Wh. The K3 simulator gives 0.9e-5 – 2.3e-5 for an 8k
prefill on Blackwell. The ratio route carries the older hardware at the top
of the decode range. Therefore the 2026 value is probably in the lower half.
No measured source exists.

**The KV size behind `m`.** Published architectures hold 69 KiB (MLA) to
504 KiB (GQA) of KV per token at FP16, and about half that at FP8
(`kezia-review`). `sa-dataflow` gives about 25 kB for new hybrid models and
about 70 kB for proven compressed attention. More KV per token makes `m`
larger. The simulated 1.5–3.0 is for K3, which has localized attention. A
model with full attention would have a larger `m`. Nothing is measured on
real hardware.

**Measured and simulated disagree on 8-GPU nodes.** AgentX puts V4 Pro on
B200 at 4.0e-5 Wh per total token. The simulator's K3 on B200 gives about
1e-5 for the same token mix. The models, the traces and the power bases are
different. The two are not reconciled.

**The width of the whole range.** When the hardware, the speed and the model
are free, the multiplied uncertainties give one to two orders of magnitude
(`kezia-review`). The AgentX rows alone span about 70× on the example
corpus.

## Sources

"Retrieved" is the date on which the page was read. For a page with a
paywall, only the part before the paywall was read.

### SemiAnalysis (InferenceX, InferenceMAX, AgentX)

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
  The replay caps idle time at 5 minutes.
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
  This is the only statement about the size of a Claude model in any source
  here. It is SemiAnalysis's statement, not Anthropic's.
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
  1.2e-4 – 2.2e-4 @44–86. Same chip, engine, date and speed (B300 vLLM @40):
  V4 Pro ÷ K3 = 6.3× in tokens per dollar. Cross-check: V4 Pro on GB300 @100
  is 39.8k tokens/s per chip by this route, and 44.8k by `sa-rubin` three
  weeks later.
- **Limits:** K3 serving software was one month old. The article says that
  B200 performance was poor until one software change. K3's active
  parameter count is not given. K3 ran on vLLM only. All values are
  chart-read.

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
    2.12 kW, MI355X 2.09 kW. Exact.
  - Text: SemiAnalysis gives 60–100 tok/s/user as the speed at which
    providers would serve this model.
  - Text, the paragraph on DSX MaxLPS: GPUs at medium to high inference
    speeds do not draw their full rated power. The publisher states here
    that the provisioned basis overstates.
- **Derived:** Wh per total token = 1 ÷ (M tokens/s per MW × 3.6). At 75–100
  tok/s/user: VR 4.3–4.7e-6; GB300 SGLang 7.3–9.8e-6; GB300 TRT-LLM 6.3e-6
  – 1.3e-5. At 100: B200 4.0e-5, B300 5.0e-5, H200 1.2e-4, MI355X 1.4e-4.
  At 100 tok/s/user, an 8-GPU B200 node uses 4.1× the energy per token of
  GB300 NVL72.
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
    corpus above.
  - Text: KV about 25 kB per token for new hybrid models, about 70 kB for
    proven compressed attention.
- **Derived:** per token = J per query ÷ tokens ÷ 3,600. Decode 1.2–1.9e-4
  Wh @8k, 2.5–3.4e-4 @128k. `m` from 8k to 128k: 1.51× (GB200), 2.96×
  (B200), 1.63× (B300). 8k prefill 0.9–2.3e-5 Wh per token. If all the
  energy of a 127k + 1k midfill went to the cache read: ≤ 2.6e-7 Wh per
  cached token. This is a ceiling.
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
- **Figures taken** (all in the text before the paywall, except the last):
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
    does not. Therefore these Ironwood figures overstate the energy of
    Google's own serving by an unstated amount.
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
  `kezia-review`; not yet checked against the paper).
- **`luccioni`**: Luccioni, Jernite & Strubell, *Power Hungry Processing*,
  FAccT '24. <https://arxiv.org/abs/2311.16863>. The type of task changes
  energy more than the size of the model. Every per-query source above
  measures chat. The transcripts that `csd` reads are agentic coding.

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
- **`google-ironwood`**: Google, the Ironwood announcement.
  <https://blog.google/products/google-cloud/ironwood-tpu-age-of-inference/>.
  Taken: 9,216 chips in "nearly 10 MW".

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
- **PUE** 1.10–1.20.
- Therefore B200 all-in is about 1.83–2.20 kW. The only all-in value that
  SemiAnalysis states for a Blackwell part is GB300 at 2.12 kW (`sa-rubin`).
  That is inside the equivalent B300 range, 2.06–2.37 kW.

### Not used

- Sam Altman's 0.34 Wh per query: no method is published.
- The older figure of 3 Wh per query: Epoch's estimate revises it by 10×.
- Mistral's lifecycle analysis of Mistral Large 2: it gives CO2e and water,
  not energy.

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
   B200 and B300 node values are still assumed here.
4. **Context-length sweeps on real hardware**: decode at 8k / 32k / 128k /
   1M, or runs with and without cache hits. This would make `m` measured.
5. **One model at two sizes on one benchmark and one chip**, with active
   parameters, and K3 on mature software. This decides the question of the
   proxy model.
6. **The speeds at which providers serve**, and any measured Claude API
   speed.
7. **Anthropic fleet and site data**: MW and PUE by site. With the tokens
   served, this gives energy per token from the top down, independent of any
   benchmark.
8. **Dated reruns of an unchanged configuration**: how fast software alone
   moves the figures.
9. **The public AgentX dataset** (link under `sa-agentx`): exact shares of
   cached, fresh and output tokens, and the value of `output_context_product`
   for those traces.

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
- Energy derived from price. A price includes hardware, colocation, cost of
  capital and margin. Electricity and colocation together are less than 20%
  of the TCO (`sa-inferencemax`). On GB300 at $0.05–0.10 per kWh,
  electricity alone is 5–9% (derived from `sa-rubin` and `sa-engram`). The
  conversion gives back only the share of electricity that you assumed.
- A figure chosen high "to be safe". A result three times too high is as
  wrong as a result three times too low.
