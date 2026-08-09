"""Analyses that answer the questions the raw usage data can support.

Three things are measurable here without guessing:

1. How fast the prompt cache decays with idle time (`decay_curve`).
2. What each cold restart actually cost (`cold_starts`, `restart_report`).
3. Where the break-even sits between carrying one large warm context and
   paying a fresh startup cost per session (`crossover`).
"""

from __future__ import annotations

import statistics
from collections import defaultdict
from dataclasses import dataclass, field

from . import pricing
from .parser import Request
from .session import Session, is_cold_start

# Gap buckets for the decay curve, as (upper_bound_seconds, label).
GAP_BUCKETS: list[tuple[float, str]] = [
    (60, "<1m"),
    (300, "1-5m"),
    (900, "5-15m"),
    (1800, "15-30m"),
    (3600, "30-60m"),
    (7200, "1-2h"),
    (86400, "2-24h"),
    (float("inf"), ">24h"),
]

# Prompts smaller than this carry too little context for cache behaviour to be
# informative, and would dominate the sample with trivial first requests.
MIN_CONTEXT_FOR_DECAY = 5_000


def _bucket(gap_seconds: float) -> str:
    for upper, label in GAP_BUCKETS:
        if gap_seconds < upper:
            return label
    return GAP_BUCKETS[-1][1]


@dataclass
class DecayBucket:
    label: str
    samples: int = 0
    rewrite_fractions: list[float] = field(default_factory=list)
    cache_reads: list[int] = field(default_factory=list)
    cache_writes: list[int] = field(default_factory=list)
    premiums: list[float] = field(default_factory=list)

    @property
    def median_rewrite_fraction(self) -> float:
        return statistics.median(self.rewrite_fractions) if self.rewrite_fractions else 0.0

    @property
    def median_cache_read(self) -> float:
        return statistics.median(self.cache_reads) if self.cache_reads else 0.0

    @property
    def median_cache_write(self) -> float:
        return statistics.median(self.cache_writes) if self.cache_writes else 0.0

    @property
    def median_premium(self) -> float:
        return statistics.median(self.premiums) if self.premiums else 0.0


def decay_curve(
    sessions: list[Session],
    min_context: int = MIN_CONTEXT_FOR_DECAY,
    include_subagents: bool = False,
) -> list[DecayBucket]:
    """Measure re-write fraction against idle gap, across consecutive requests.

    For each adjacent pair of requests *within a lane*, bucket by the gap between
    them and record what fraction of the later request's prompt had to be
    re-written rather than read from cache. This is the empirical cache-decay
    curve: it shows where the TTL cliff actually falls.

    Pairs are never taken across lanes: two lanes run concurrently against
    separate caches, so the interval between them says nothing about decay.
    Subagent lanes are excluded by default -- they are sub-minute bursts that
    would swamp the short buckets without describing how a session ages.
    """
    buckets: dict[str, DecayBucket] = {label: DecayBucket(label) for _, label in GAP_BUCKETS}
    lanes = [
        lane
        for session in sessions
        for lane in (session.lanes if include_subagents else session.main_lanes)
    ]
    for lane in lanes:
        reqs = lane.requests
        for prev, req in zip(reqs, reqs[1:]):
            ctx = req.context_tokens
            if ctx < min_context:
                continue
            gap = (req.timestamp - prev.timestamp).total_seconds()
            b = buckets[_bucket(gap)]
            b.samples += 1
            b.rewrite_fractions.append(req.cache_write / ctx)
            b.cache_reads.append(req.cache_read)
            b.cache_writes.append(req.cache_write)
            b.premiums.append(req.cold_premium)
    return [buckets[label] for _, label in GAP_BUCKETS if buckets[label].samples]


@dataclass
class GrowthPoint:
    request_index: int
    lanes: int
    median_context: float
    median_cost_per_request: float
    median_cumulative: float


@dataclass
class GrowthCurve:
    """How cost accumulates as a session gets longer.

    Every request re-reads the whole context at the cache-read rate. So the
    cost of a request rises with the context, and the cumulative cost grows
    faster than the request count. It is not quadratic in practice: the context
    grows more slowly as the session continues, so the exponent is nearer 1.3
    than 2.0. The carry cost on a large context is real, and it is the largest
    term in any long session.
    """

    points: list[GrowthPoint]
    exponent: float | None  # fitted from cumulative cost vs request count
    lanes: int
    min_requests: int

    def carry_cost_per_request(self, context: int, model: str) -> float:
        """What re-reading `context` costs on every request, before any output."""
        p = pricing.price_for(model)
        rate = (p.input if p else 0.0) / 1_000_000
        return context * rate * pricing.CACHE_READ


def growth_curve(
    sessions: list[Session],
    min_requests: int = 200,
    at_requests: tuple[int, ...] = (1, 25, 50, 100, 150, 200),
) -> GrowthCurve:
    """Track context, cost and cumulative cost against the request index.

    Restricted to uninterrupted lanes -- a restart would add a large one-off
    write and distort the shape being measured.
    """
    lanes = [
        lane
        for s in sessions
        for lane in s.main_lanes
        if len(lane.segments) == 1 and len(lane.requests) >= min_requests
    ]
    points: list[GrowthPoint] = []
    for t in at_requests:
        pool = [lane for lane in lanes if len(lane.requests) >= t]
        if not pool:
            continue
        points.append(
            GrowthPoint(
                request_index=t,
                lanes=len(pool),
                median_context=statistics.median(
                    lane.requests[t - 1].context_tokens for lane in pool
                ),
                median_cost_per_request=statistics.median(
                    lane.requests[t - 1].cost for lane in pool
                ),
                median_cumulative=statistics.median(
                    sum(r.cost for r in lane.requests[:t]) for lane in pool
                ),
            )
        )

    # Fit an exponent from the first and last usable points: cost ~ requests^k.
    exponent = None
    usable = [p for p in points if p.request_index > 1 and p.median_cumulative > 0]
    if len(usable) >= 2:
        lo, hi = usable[0], usable[-1]
        if lo.median_cumulative > 0 and hi.request_index > lo.request_index:
            import math

            exponent = math.log(hi.median_cumulative / lo.median_cumulative) / math.log(
                hi.request_index / lo.request_index
            )

    return GrowthCurve(
        points=points, exponent=exponent, lanes=len(lanes), min_requests=min_requests
    )


@dataclass
class ModelSpend:
    model: str
    normalised: str | None
    rate_input: float
    rate_output: float
    intro_applied: bool
    requests: int
    cost: float
    output_tokens: int
    cache_write: int
    cache_read: int


def spend_by_model(sessions: list[Session]) -> list[ModelSpend]:
    """Cost broken down by model, with the rates actually applied.

    Every request is priced at its own model's rate, and at the rate in force on
    its own date -- so this also shows where promotional pricing was applied.
    """
    rows: dict[str, dict] = defaultdict(
        lambda: {"requests": 0, "cost": 0.0, "out": 0, "cw": 0, "cr": 0, "intro": 0}
    )
    for s in sessions:
        for r in s.requests:
            row = rows[str(r.model)]
            row["requests"] += 1
            row["cost"] += r.cost
            row["out"] += r.output_tokens
            row["cw"] += r.cache_write
            row["cr"] += r.cache_read
            p = pricing.price_for(r.model)
            if p is not None and p.rates(r.timestamp) != (p.input, p.output):
                row["intro"] += 1

    out: list[ModelSpend] = []
    for model, row in rows.items():
        p = pricing.price_for(model)
        out.append(
            ModelSpend(
                model=model,
                normalised=pricing.normalise_model(model),
                rate_input=p.input if p else 0.0,
                rate_output=p.output if p else 0.0,
                intro_applied=row["intro"] > 0,
                requests=row["requests"],
                cost=row["cost"],
                output_tokens=row["out"],
                cache_write=row["cw"],
                cache_read=row["cr"],
            )
        )
    out.sort(key=lambda m: m.cost, reverse=True)
    return out


@dataclass
class TtlBucket:
    label: str
    samples: int
    median_rewrite: float
    dead_share: float  # share of pairs where >90% of the prompt was re-written


def _ttl_buckets(
    pairs: list[tuple[float, float]], edges: list[tuple[float, float, str]]
) -> list[TtlBucket]:
    out: list[TtlBucket] = []
    for lo, hi, label in edges:
        vals = [f for gap, f in pairs if lo <= gap < hi]
        if not vals:
            continue
        out.append(
            TtlBucket(
                label=label,
                samples=len(vals),
                median_rewrite=statistics.median(vals),
                dead_share=sum(1 for f in vals if f > 0.9) / len(vals),
            )
        )
    return out


def _lane_pairs(sessions: list[Session], subagents: bool) -> list[tuple[float, float, object]]:
    """(gap_minutes, rewrite_fraction, request) for consecutive in-lane pairs."""
    out = []
    for s in sessions:
        lanes = s.subagent_lanes if subagents else s.main_lanes
        for lane in lanes:
            for a, b in zip(lane.requests, lane.requests[1:]):
                if b.context_tokens < MIN_CONTEXT_FOR_DECAY:
                    continue
                gap = (b.timestamp - a.timestamp).total_seconds() / 60
                out.append((gap, b.cache_write / b.context_tokens, b))
    return out


# Fine buckets straddling the nominal one-hour boundary.
BOUNDARY_EDGES = [
    (0, 30, "0-30"), (30, 45, "30-45"), (45, 55, "45-55"), (55, 58, "55-58"),
    (58, 60, "58-60"), (60, 62, "60-62"), (62, 65, "62-65"), (65, 70, "65-70"),
    (70, 80, "70-80"), (80, 120, "80-120"), (120, float("inf"), "120+"),
]

AGE_EDGES = [
    (0, 60, "<1h"), (60, 180, "1-3h"), (180, 360, "3-6h"),
    (360, 720, "6-12h"), (720, 1440, "12-24h"), (1440, float("inf"), ">24h"),
]


@dataclass
class TtlEvidence:
    """What the corpus shows about how long a prompt cache actually survives."""

    requested: dict[str, dict[str, int]]  # lane kind -> {"5m": n, "1h": n}
    boundary: list[TtlBucket]  # main lanes, fine buckets around 60 min
    subagent_boundary: list[TtlBucket]
    age_invariance: list[TtlBucket]  # short-gap requests bucketed by lane age
    early_deaths: int
    early_total: int
    early_causes: dict[str, int]

    @property
    def early_share(self) -> float:
        return self.early_deaths / self.early_total if self.early_total else 0.0


def ttl_evidence(sessions: list[Session], age_gap_limit: float = 30.0) -> TtlEvidence:
    """Assemble the empirical case for the cache TTL.

    Three independent questions, each answerable from the corpus:

    1. Which TTL does the client *request*? First-class, from `cache_creation`.
    2. When does the cache actually die? Fine buckets around the boundary.
    3. Does the clock run from cache creation or from last use? If from
       creation, requests with a short gap would still start failing once the
       lane passed an hour old; if from last use, lane age is irrelevant.
    """
    requested: dict[str, dict[str, int]] = {
        "main": {"5m": 0, "1h": 0},
        "subagent": {"5m": 0, "1h": 0},
    }
    for s in sessions:
        for lane in s.lanes:
            key = "subagent" if lane.is_subagent else "main"
            for r in lane.requests:
                if r.cache_write_5m:
                    requested[key]["5m"] += 1
                elif r.cache_write_1h:
                    requested[key]["1h"] += 1

    main_pairs = _lane_pairs(sessions, subagents=False)
    sub_pairs = _lane_pairs(sessions, subagents=True)

    # Age invariance: hold the gap short, vary how long the lane has been alive.
    aged: list[tuple[float, float]] = []
    for s in sessions:
        for lane in s.main_lanes:
            start = lane.requests[0].timestamp
            for a, b in zip(lane.requests, lane.requests[1:]):
                gap = (b.timestamp - a.timestamp).total_seconds() / 60
                if gap >= age_gap_limit or b.context_tokens < MIN_CONTEXT_FOR_DECAY:
                    continue
                age = (b.timestamp - start).total_seconds() / 60
                aged.append((age, b.cache_write / b.context_tokens))

    early = [(g, f, r) for g, f, r in main_pairs if g < 55]
    dead = [r for g, f, r in early if f > 0.9]
    causes: dict[str, int] = defaultdict(int)
    for r in dead:
        key = r.cache_miss_reason or (
            "reported hit" if r.has_diagnostics else "not reported"
        )
        causes[key] += 1

    return TtlEvidence(
        requested=requested,
        boundary=_ttl_buckets([(g, f) for g, f, _ in main_pairs], BOUNDARY_EDGES),
        subagent_boundary=_ttl_buckets(
            [(g, f) for g, f, _ in sub_pairs],
            [(0, 5, "0-5"), (5, 10, "5-10"), (10, 30, "10-30"),
             (30, 60, "30-60"), (60, float("inf"), "60+")],
        ),
        age_invariance=_ttl_buckets(aged, AGE_EDGES),
        early_deaths=len(dead),
        early_total=len(early),
        early_causes=dict(sorted(causes.items(), key=lambda kv: -kv[1])),
    )


@dataclass
class ColdStart:
    """A single request that rebuilt a large context from a cold cache."""

    request: Request
    session: Session
    idle_before: float | None  # seconds since previous request, None if first

    @property
    def premium(self) -> float:
        return self.request.cold_premium

    @property
    def context(self) -> int:
        return self.request.context_tokens


def cold_starts(
    sessions: list[Session],
    min_context: int = 20_000,
    include_subagents: bool = False,
) -> list[ColdStart]:
    """Every request that paid to rebuild a substantial cold context.

    Idle time is measured within the lane, since that is the cache that expired.
    Subagent lanes are excluded by default: a subagent opens cold on purpose, so
    reporting that as a lost cache would be misleading.
    """
    found: list[ColdStart] = []
    for session in sessions:
        lanes = session.lanes if include_subagents else session.main_lanes
        for lane in lanes:
            for i, req in enumerate(lane.requests):
                if not is_cold_start(req, min_context):
                    continue
                idle = None
                if i > 0:
                    idle = (req.timestamp - lane.requests[i - 1].timestamp).total_seconds()
                found.append(ColdStart(request=req, session=session, idle_before=idle))
    found.sort(key=lambda c: c.premium, reverse=True)
    return found


@dataclass
class RestartReport:
    total_cost: float
    restart_premium: float
    mid_session_restarts: int
    sessions_with_restarts: int
    total_sessions: int

    @property
    def premium_share(self) -> float:
        return self.restart_premium / self.total_cost if self.total_cost else 0.0


def restart_report(sessions: list[Session]) -> RestartReport:
    """Aggregate the cost of mid-session cache expiry across a corpus."""
    total = sum(s.cost for s in sessions)
    premium = sum(s.restart_premium for s in sessions)
    restarts = sum(s.restarts for s in sessions)
    affected = sum(1 for s in sessions if s.restarts)
    return RestartReport(
        total_cost=total,
        restart_premium=premium,
        mid_session_restarts=restarts,
        sessions_with_restarts=affected,
        total_sessions=len(sessions),
    )


@dataclass
class Strategy:
    """Modelled cost of one way of getting a fixed amount of work done."""

    label: str
    sessions: int
    productive_requests: int
    ready_requests: int  # total across all sessions
    peak_context: int
    growth_per_request: float
    ready_cost: float
    growth_cost: float
    carry_cost: float
    output_cost: float
    restart_cost: float

    @property
    def requests(self) -> int:
        """Every request the strategy makes, orientation included."""
        return self.productive_requests + self.ready_requests

    @property
    def total(self) -> float:
        return (
            self.ready_cost
            + self.growth_cost
            + self.carry_cost
            + self.output_cost
            + self.restart_cost
        )

    @property
    def requests_per_session(self) -> float:
        return self.requests / self.sessions if self.sessions else 0.0


@dataclass
class Comparison:
    """One long warm session versus several short ones, for the same work."""

    model: str
    startup_tokens: int
    long_run: Strategy
    short_runs: Strategy
    rework: float
    breakeven_rework: float

    @property
    def delta(self) -> float:
        """Positive means the long warm session is cheaper."""
        return self.short_runs.total - self.long_run.total

    @property
    def growth_ratio(self) -> float:
        """How differently the two strategies are assumed to accumulate context.

        The peaks are supplied independently of the request split, so it is easy
        to describe a short session that grows several times faster per request
        than the long one. Far from 1.0 means the inputs disagree with each
        other, not that one strategy is genuinely better.
        """
        base = self.long_run.growth_per_request
        return self.short_runs.growth_per_request / base if base else 1.0

    @property
    def inputs_consistent(self) -> bool:
        return 0.67 <= self.growth_ratio <= 1.5

    @property
    def verdict(self) -> str:
        if abs(self.delta) < 0.01:
            return "the two strategies cost about the same"
        cheaper, dearer = (
            (self.long_run, self.short_runs)
            if self.long_run.total < self.short_runs.total
            else (self.short_runs, self.long_run)
        )
        pct = abs(self.delta) / dearer.total if dearer.total else 0.0
        return f"{cheaper.label} is cheaper by ${abs(self.delta):,.2f} ({pct:.0%})"


def _strategy(
    label: str,
    *,
    rate_in: float,
    sessions: int,
    productive_requests: int,
    ready_context: int,
    ready_cost_each: float,
    ready_requests_each: int,
    growth_per_request: float,
    output_cost_per_request: float = 0.0,
    restarts: int = 0,
) -> Strategy:
    """Cost-model one strategy.

    Every session pays to orient before it can work: `ready_requests_each`
    requests costing `ready_cost_each`, arriving at `ready_context`. Both are
    measured (`observed_ready_tokens`), not derived from a token count -- reading
    and searching costs far more than writing the same context would, because it
    is a process of many requests rather than one cold write.

    Splitting work therefore pays for orientation once per session, in money and
    in requests. Productive requests are what remains, growing the context from
    `ready_context` toward the peak:

      ready    -- orienting, once per session (all-in: writes, reads, output)
      growth   -- writing each new token into cache exactly once
      carry    -- reading the mean context back on every productive request
      output   -- generating on every productive request
      restart  -- re-writing the whole peak context after a cache expiry
    """
    write = rate_in * pricing.CACHE_WRITE_1H
    read = rate_in * pricing.CACHE_READ
    per_session = productive_requests / sessions if sessions else 0
    peak = ready_context + growth_per_request * per_session
    mean_context = (ready_context + peak) / 2
    return Strategy(
        label=label,
        sessions=sessions,
        productive_requests=productive_requests,
        ready_requests=sessions * ready_requests_each,
        peak_context=int(peak),
        growth_per_request=growth_per_request,
        ready_cost=sessions * ready_cost_each,
        growth_cost=sessions * max(0.0, peak - ready_context) * write,
        carry_cost=productive_requests * mean_context * read,
        output_cost=productive_requests * output_cost_per_request,
        restart_cost=restarts * peak * write,
    )


def compare_strategies(
    model: str,
    startup_tokens: int,
    requests: int,
    long_peak: int,
    short_peak: int,
    short_sessions: int,
    long_restarts: int = 0,
    short_restarts_each: int = 0,
    rework: float = 0.0,
    output_cost_per_request: float = 0.0,
    ready_cost_each: float = 0.0,
    ready_requests_each: int = 0,
) -> Comparison:
    """Compare one long session against `short_sessions` shorter ones.

    The long run reaches `long_peak` context; each short run reaches
    `short_peak` and pays its own startup. `long_restarts` charges the long run
    for cache expiries -- the risk that makes a big warm context expensive to
    leave idle.

    `rework` is the fraction of *extra* requests the short sessions need to
    rebuild understanding the long session simply still had: 0.3 means they take
    30% more requests to do the same job. This is the term that decides the
    comparison, and it is the one the transcripts cannot measure -- it depends
    on how separable the work is. `breakeven_rework` reports how large it would
    have to be for the two strategies to cost the same.
    """
    p = pricing.price_for(model)
    rate_in = (p.input if p else 0.0) / 1_000_000

    # Convert the supplied peaks into growth rates at the *baseline* workload.
    # Context then follows request count, so extra requests carry extra context
    # instead of being free.
    long_growth = max(0.0, long_peak - startup_tokens) / requests if requests else 0.0
    short_baseline = requests / short_sessions if short_sessions else 0
    short_growth = (
        max(0.0, short_peak - startup_tokens) / short_baseline if short_baseline else 0.0
    )

    common = dict(
        rate_in=rate_in,
        ready_context=startup_tokens,
        ready_cost_each=ready_cost_each,
        ready_requests_each=ready_requests_each,
        output_cost_per_request=output_cost_per_request,
    )
    long_run = _strategy(
        "one long session",
        sessions=1,
        productive_requests=requests,
        growth_per_request=long_growth,
        restarts=long_restarts,
        **common,
    )

    def short_at(r: float) -> Strategy:
        return _strategy(
            f"{short_sessions} short sessions",
            sessions=short_sessions,
            productive_requests=round(requests * (1 + r)),
            growth_per_request=short_growth,
            restarts=short_restarts_each * short_sessions,
            **common,
        )

    short_runs = short_at(rework)

    # Carry is now quadratic in the rework factor (more requests means both more
    # requests and a larger context on each), so bisect rather than solve directly.
    target = long_run.total
    breakeven = float("inf")
    if short_at(0.0).total < target:
        lo, hi = 0.0, 1.0
        for _ in range(60):  # grow the bracket until the split strategy loses
            if short_at(hi).total >= target:
                break
            lo, hi = hi, hi * 2
        else:
            hi = float("inf")
        if hi != float("inf"):
            for _ in range(80):
                mid = (lo + hi) / 2
                if short_at(mid).total < target:
                    lo = mid
                else:
                    hi = mid
            breakeven = (lo + hi) / 2
    else:
        breakeven = -1.0  # already more expensive with no rework at all

    return Comparison(
        model=model,
        startup_tokens=startup_tokens,
        long_run=long_run,
        short_runs=short_runs,
        rework=rework,
        breakeven_rework=breakeven,
    )


# Fallback when a project has too few cold sessions to measure a ready point.
# Prefer `observed_ready_tokens`; this exists so callers always have a number.
FALLBACK_READY_TOKENS = 60_000

# Minimum cold sessions reaching a first mutation before a per-project ready
# figure is trustworthy enough to report unqualified.
MIN_READY_SAMPLES = 4


def cold_sessions(sessions: list[Session], min_requests: int = 1) -> list[Session]:
    """Sessions that began with a genuinely cold cache."""
    return [s for s in sessions if s.started_cold and len(s.requests) >= min_requests]


@dataclass
class ReadyPoint:
    """Observed context and spend at which sessions start changing the workspace."""

    scope: str
    samples: int
    median_tokens: int
    p25_tokens: int
    p75_tokens: int
    median_request_index: int
    # Cumulative cost of every request up to and including the first mutation:
    # what orienting actually cost, rather than what the context would cost to
    # write. Varies by model as well as by token count, so a project on a dearer
    # model can cost more to start despite a smaller context.
    median_cost: float
    p75_cost: float
    median_rebuild_cost: float

    @property
    def reliable(self) -> bool:
        return self.samples >= MIN_READY_SAMPLES

    @property
    def tokens(self) -> int:
        return self.median_tokens


def _percentile(values: list[int], fraction: float) -> int:
    ordered = sorted(values)
    idx = min(len(ordered) - 1, int(len(ordered) * fraction))
    return ordered[idx]


def observed_ready_tokens(sessions: list[Session], scope: str = "all") -> ReadyPoint | None:
    """Measure the context at which cold sessions first change the workspace.

    This replaces a hand-picked "ready to work" constant with something the
    transcripts actually contain. Everything before the first Edit/Write is
    orientation -- reading files, searching, running commands -- so the context
    at that moment is the observed cost of getting a fresh session productive.

    Returns None when no cold session in scope ever reached a mutation.
    """
    contexts: list[int] = []
    indices: list[int] = []
    costs: list[float] = []
    rebuilds: list[float] = []
    for s in cold_sessions(sessions):
        hit = s.first_mutation()
        if hit is None:
            continue
        index, req = hit
        contexts.append(req.context_tokens)
        indices.append(index)
        # Everything spent getting here, across the orientation requests.
        costs.append(sum(r.cost for r in s.main_requests[:index]))
        # What re-establishing this much context costs if the cache expires:
        # the same tokens written cold rather than read back.
        rebuilds.append(
            pricing.cold_start_premium(req.model, req.context_tokens, at=req.timestamp)
        )
    if not contexts:
        return None
    ordered = sorted(costs)
    return ReadyPoint(
        scope=scope,
        samples=len(contexts),
        median_tokens=int(statistics.median(contexts)),
        p25_tokens=_percentile(contexts, 0.25),
        p75_tokens=_percentile(contexts, 0.75),
        median_request_index=int(statistics.median(indices)),
        median_cost=statistics.median(costs) if costs else 0.0,
        p75_cost=ordered[min(len(ordered) - 1, int(len(ordered) * 0.75))] if ordered else 0.0,
        median_rebuild_cost=statistics.median(rebuilds) if rebuilds else 0.0,
    )


def by_project(sessions: list[Session]) -> dict[str, list[Session]]:
    """Group sessions by project, largest spend first."""
    grouped: dict[str, list[Session]] = defaultdict(list)
    for s in sessions:
        grouped[s.project].append(s)
    return dict(
        sorted(grouped.items(), key=lambda kv: sum(s.cost for s in kv[1]), reverse=True)
    )


def ready_tokens_by_project(sessions: list[Session]) -> dict[str, ReadyPoint]:
    """Observed ready point per project, for projects where one is measurable."""
    out: dict[str, ReadyPoint] = {}
    for project, group in by_project(sessions).items():
        point = observed_ready_tokens(group, scope=project)
        if point is not None:
            out[project] = point
    return out


def observed_output_cost(sessions: list[Session]) -> float:
    """Median USD spent generating output on a single main-lane request.

    Output is independent of context, so it mostly cancels when two strategies
    do the same number of requests -- but not under rework, where the split
    strategy does more of them. Omitting it therefore biases the comparison in
    favour of splitting.
    """
    costs: list[float] = []
    for s in sessions:
        for r in s.main_requests:
            p = pricing.price_for(r.model)
            if p is None:
                continue
            _, rate_out = p.rates(r.timestamp)
            costs.append(r.output_tokens * rate_out / 1_000_000)
    return statistics.median(costs) if costs else 0.0


def observed_restarts(sessions: list[Session], requests: int, tolerance: float = 0.5) -> int:
    """Median mid-session cache expiries for main lanes of comparable length.

    Restarts are a function of how a session is used -- how often it is left
    idle past the hour -- not of the strategy being modelled. Assuming zero is
    an optimistic default that quietly favours the long session, so the observed
    rate for sessions of similar length is used instead.
    """
    lo = requests * (1 - tolerance)
    hi = requests * (1 + tolerance)
    pool = [s for s in sessions if lo <= len(s.main_requests) <= hi]
    if not pool:
        return 0
    return int(statistics.median(s.restarts for s in pool))


def resolve_ready_tokens(
    sessions: list[Session], override: int | None = None
) -> tuple[int, str]:
    """Pick a ready-to-work figure and say where it came from.

    Order of preference: an explicit override, then the observed median for
    these sessions, then a fallback constant. The source string is returned so
    callers can show the reader which one applied.
    """
    if override:
        return override, "supplied"
    point = observed_ready_tokens(sessions)
    if point is None:
        return FALLBACK_READY_TOKENS, "fallback -- no mutations observed"
    if not point.reliable:
        return point.tokens, f"observed, only {point.samples} sessions"
    return point.tokens, f"observed from {point.samples} cold sessions"


def startup_prefix_tokens(sessions: list[Session]) -> int:
    """Median context on the opening request of a cold session.

    This is the irreducible fixed prefix -- system prompt, tool schemas, project
    instructions -- written before any work happens. It is well defined and
    directly measurable, unlike the point at which a session is "ready".
    """
    cold = cold_sessions(sessions)
    if not cold:
        return 0
    return int(statistics.median(s.requests[0].context_tokens for s in cold))


def context_at_request(sessions: list[Session], index: int) -> int | None:
    """Median context at the 1-based `index`-th request of a cold session."""
    values = [
        s.requests[index - 1].context_tokens
        for s in cold_sessions(sessions, min_requests=index)
    ]
    return int(statistics.median(values)) if values else None


def startup_ramp(
    sessions: list[Session], indices: tuple[int, ...] = (1, 5, 10, 15, 20, 30, 40)
) -> list[tuple[int, int, int]]:
    """Context growth over the opening requests of cold sessions.

    Returns (request_index, median_context, sessions_sampled). There is no
    plateau in practice -- context accrues steadily as work proceeds -- so this
    is presented as a ramp for the reader to locate their own "ready" point on,
    not as evidence for any particular startup figure.
    """
    out: list[tuple[int, int, int]] = []
    for i in indices:
        pool = cold_sessions(sessions, min_requests=i)
        if not pool:
            continue
        median = statistics.median(s.requests[i - 1].context_tokens for s in pool)
        out.append((i, int(median), len(pool)))
    return out


def ready_at_request(sessions: list[Session], ready_tokens: int) -> int | None:
    """Which request number a cold session typically reaches `ready_tokens` at.

    Locates a supplied startup assumption on the measured ramp, so the reader
    can sanity-check it against their own sessions.
    """
    for i in range(1, 60):
        pool = cold_sessions(sessions, min_requests=i)
        if not pool:
            return None
        if statistics.median(s.requests[i - 1].context_tokens for s in pool) >= ready_tokens:
            return i
    return None


@dataclass
class Totals:
    requests: int
    sessions: int
    cost: float
    input_tokens: int
    output_tokens: int
    cache_write: int
    cache_read: int

    @property
    def cache_hit_rate(self) -> float:
        """Share of all prompt tokens served from cache."""
        prompt = self.input_tokens + self.cache_write + self.cache_read
        return self.cache_read / prompt if prompt else 0.0


# Miss reasons the user can act on: something in the request changed and
# invalidated a prefix that would otherwise have been reused.
SELF_INFLICTED_MISSES = frozenset(
    {"tools_changed", "system_changed", "model_changed", "messages_changed"}
)


@dataclass
class MissReason:
    reason: str
    count: int
    premium: float
    reported_missed_tokens: int

    @property
    def self_inflicted(self) -> bool:
        return self.reason in SELF_INFLICTED_MISSES


@dataclass
class MissReport:
    """Cache misses as reported by the API, not inferred from token counts."""

    reasons: list[MissReason]
    requests_with_diagnostics: int
    requests_total: int

    @property
    def coverage(self) -> float:
        """Share of requests whose client version reports cache diagnostics."""
        return (
            self.requests_with_diagnostics / self.requests_total
            if self.requests_total
            else 0.0
        )

    @property
    def total_misses(self) -> int:
        return sum(r.count for r in self.reasons)

    @property
    def self_inflicted_premium(self) -> float:
        return sum(r.premium for r in self.reasons if r.self_inflicted)


def miss_report(sessions: list[Session]) -> MissReport:
    """Group API-reported cache misses by reason.

    Distinct from `cold_starts`, which infers expensive rebuilds from token
    ratios. This is the API stating that a lookup failed and why -- it fires on
    partial misses too, and cannot occur on a lane's first request because there
    was no prior cache to miss. The two answer different questions; keep both.
    """
    reqs = [r for s in sessions for r in s.requests]
    counts: dict[str, list[float]] = defaultdict(lambda: [0, 0.0, 0])
    for r in reqs:
        if not r.cache_miss_reason:
            continue
        row = counts[r.cache_miss_reason]
        row[0] += 1
        row[1] += r.cold_premium
        row[2] += r.cache_missed_tokens
    reasons = [
        MissReason(reason=k, count=int(v[0]), premium=v[1], reported_missed_tokens=int(v[2]))
        for k, v in counts.items()
    ]
    reasons.sort(key=lambda r: r.premium, reverse=True)
    return MissReport(
        reasons=reasons,
        requests_with_diagnostics=sum(1 for r in reqs if r.has_diagnostics),
        requests_total=len(reqs),
    )


@dataclass
class CoverageReport:
    """How complete the transcript record is.

    Old top-level transcripts get pruned while their nested `subagents/`
    directories survive, leaving sessions represented only by fragments. Totals
    covering those periods are floors, not measurements, so this is reported
    rather than quietly folded in.
    """

    intact: int
    orphaned: int
    orphan_cost: float
    by_month: dict[str, tuple[int, int]]  # month -> (intact, orphaned)

    @property
    def total(self) -> int:
        return self.intact + self.orphaned

    @property
    def orphan_share(self) -> float:
        return self.orphaned / self.total if self.total else 0.0

    @property
    def complete_from(self) -> str | None:
        """First month with no orphans, i.e. where the record looks trustworthy."""
        for month in sorted(self.by_month):
            intact, orphaned = self.by_month[month]
            if intact and not orphaned:
                return month
        return None


def coverage_report(sessions: list[Session]) -> CoverageReport:
    by_month: dict[str, list[int]] = {}
    intact = orphaned = 0
    orphan_cost = 0.0
    for s in sessions:
        month = s.start.strftime("%Y-%m")
        row = by_month.setdefault(month, [0, 0])
        if s.is_orphaned:
            orphaned += 1
            orphan_cost += s.cost
            row[1] += 1
        else:
            intact += 1
            row[0] += 1
    return CoverageReport(
        intact=intact,
        orphaned=orphaned,
        orphan_cost=orphan_cost,
        by_month={m: (v[0], v[1]) for m, v in by_month.items()},
    )


@dataclass
class SubagentReport:
    """How much delegation costs, and what shape it takes."""

    lanes: int
    requests: int
    cost: float
    total_cost: float
    sessions_using: int
    total_sessions: int
    median_requests: float
    median_duration_seconds: float
    median_peak_context: float

    @property
    def share(self) -> float:
        return self.cost / self.total_cost if self.total_cost else 0.0


def subagent_report(sessions: list[Session]) -> SubagentReport:
    lanes = [lane for s in sessions for lane in s.subagent_lanes]
    counts = [len(lane.requests) for lane in lanes]
    durations = [lane.duration.total_seconds() for lane in lanes]
    peaks = [lane.peak_context for lane in lanes]
    return SubagentReport(
        lanes=len(lanes),
        requests=sum(counts),
        cost=sum(lane.cost for lane in lanes),
        total_cost=sum(s.cost for s in sessions),
        sessions_using=sum(1 for s in sessions if s.subagent_lanes),
        total_sessions=len(sessions),
        median_requests=statistics.median(counts) if counts else 0.0,
        median_duration_seconds=statistics.median(durations) if durations else 0.0,
        median_peak_context=statistics.median(peaks) if peaks else 0.0,
    )


def totals(sessions: list[Session]) -> Totals:
    reqs = [r for s in sessions for r in s.requests]
    return Totals(
        requests=len(reqs),
        sessions=len(sessions),
        cost=sum(r.cost for r in reqs),
        input_tokens=sum(r.input_tokens for r in reqs),
        output_tokens=sum(r.output_tokens for r in reqs),
        cache_write=sum(r.cache_write for r in reqs),
        cache_read=sum(r.cache_read for r in reqs),
    )
