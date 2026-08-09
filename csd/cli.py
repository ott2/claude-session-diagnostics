"""Command-line interface. Standard library only."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import timedelta
from pathlib import Path

from . import analysis, parser as parser_mod, pricing
from .session import CACHE_TTL, build_sessions


def _fmt_tokens(n: float) -> str:
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}M"
    if n >= 1_000:
        return f"{n / 1_000:.0f}K"
    return f"{n:.0f}"


def _money(value: float, width: int = 10, decimals: int = 2) -> str:
    """Right-align a currency value with the '$' inside the field.

    Writing `{n:>8,}${cost:>9.2f}` jams the sign against the previous column
    whenever that column fills its width, so the sign always goes in the field.
    """
    return f"{'$' + format(value, f',.{decimals}f'):>{width}}"


def _label_width(labels, minimum: int = 12, maximum: int = 44) -> int:
    """Width that fits the longest label, so distinct projects stay distinct.

    Truncating to a fixed width silently collapsed sibling projects into
    identical-looking rows, so the default ceiling is generous.
    """
    longest = max((len(str(x)) for x in labels), default=minimum)
    return max(minimum, min(maximum, longest))


def _fmt_duration(td: timedelta) -> str:
    secs = int(td.total_seconds())
    if secs < 60:
        return f"{secs}s"
    if secs < 3600:
        return f"{secs // 60}m"
    return f"{secs // 3600}h{(secs % 3600) // 60:02d}m"


def _load(args) -> tuple[list, parser_mod.ParseStats]:
    requests, stats = parser_mod.load(
        root=args.root, project=args.project, project_depth=args.project_depth
    )
    if not requests:
        print(f"No session data found under {args.root}", file=sys.stderr)
        sys.exit(1)
    return requests, stats


def _ttl(args) -> timedelta:
    return timedelta(minutes=args.ttl) if args.ttl else CACHE_TTL


def cmd_summary(args) -> None:
    requests, stats = _load(args)
    sessions = build_sessions(requests, _ttl(args))
    t = analysis.totals(sessions)
    r = analysis.restart_report(sessions)

    print(f"Sessions        {t.sessions:>12,}")
    print(f"Requests        {t.requests:>12,}")
    print(f"Total cost      {'$' + format(t.cost, ',.2f'):>12}")
    print()
    print(f"Input tokens    {_fmt_tokens(t.input_tokens):>12}")
    print(f"Output tokens   {_fmt_tokens(t.output_tokens):>12}")
    print(f"Cache writes    {_fmt_tokens(t.cache_write):>12}")
    print(f"Cache reads     {_fmt_tokens(t.cache_read):>12}")
    print(f"Cache hit rate  {t.cache_hit_rate:>11.1%}")
    print()
    sub = analysis.subagent_report(sessions)
    print(f"Main-lane spend      {'$' + format(t.cost - sub.cost, ',.2f'):>12}")
    print(f"Subagent spend       {'$' + format(sub.cost, ',.2f'):>12}  "
          f"({sub.share:.1%} across {sub.lanes:,} subagents)")
    print()
    print(f"Mid-session restarts       {r.mid_session_restarts:>7,}")
    print(f"Sessions affected          {r.sessions_with_restarts:>7,} of {r.total_sessions:,}")
    print(f"Cold-restart premium       {'$' + format(r.restart_premium, ',.2f'):>7}")
    print(f"  as share of total spend  {r.premium_share:>7.1%}")
    print("\nRestart figures cover main lanes only; subagents open cold by design.")

    cov = analysis.coverage_report(sessions)
    if cov.orphaned:
        print(
            f"\nWARNING: {cov.orphaned:,} of {cov.total:,} sessions "
            f"({cov.orphan_share:.0%}) have no main transcript -- only their\n"
            f"subagent files survive. Their main-lane spend is unrecoverable, so the\n"
            f"total above is a floor. Run `csd coverage` for the affected periods."
        )

    if args.verbose:
        print()
        print("Parser:")
        print(f"  transcripts           {stats.files:,}")
        print(f"  assistant lines       {stats.assistant_lines:,}")
        print(f"  deduplicated to       {stats.requests:,} requests")
        print(f"  duplicate lines       {stats.duplicate_lines:,} "
              f"({stats.duplication_factor:.2f}x inflation if not deduped)")
        if stats.synthetic:
            print(f"  synthetic (excluded)  {stats.synthetic:,}")
        if stats.malformed_lines:
            print(f"  malformed             {stats.malformed_lines:,}")
        if stats.unpriced_models:
            print(f"  UNPRICED MODELS       {', '.join(sorted(stats.unpriced_models))}")


def cmd_decay(args) -> None:
    requests, _ = _load(args)
    sessions = build_sessions(requests, _ttl(args))
    curve = analysis.decay_curve(sessions, include_subagents=args.include_subagents)

    scope = "all lanes" if args.include_subagents else "main lanes only"
    print(f"Cache decay vs idle gap between consecutive requests ({scope})")
    print("(rewrite = fraction of the prompt that had to be re-written)\n")
    print(f"{'gap':>8}  {'n':>7}  {'rewrite':>8}  {'cache read':>11}  "
          f"{'cache write':>12}  {'premium':>9}")
    print("-" * 64)
    for b in curve:
        print(
            f"{b.label:>8}  {b.samples:>7,}  {b.median_rewrite_fraction:>7.1%}  "
            f"{_fmt_tokens(b.median_cache_read):>11}  "
            f"{_fmt_tokens(b.median_cache_write):>12}  "
            f"${b.median_premium:>8.4f}"
        )
    print("\nAll figures are medians. A rewrite fraction near 1.0 means the cache")
    print("was gone and the entire context was rebuilt at the cache-write rate.")


def cmd_cold(args) -> None:
    requests, _ = _load(args)
    sessions = build_sessions(requests, _ttl(args))
    events = analysis.cold_starts(
        sessions, args.min_context, include_subagents=args.include_subagents
    )

    if not events:
        print("No cold starts above the context threshold.")
        return

    total = sum(c.premium for c in events)
    shown = events[: args.limit]
    print(f"{len(events):,} cold starts rebuilding >{_fmt_tokens(args.min_context)} of context")
    print(f"Total premium over a warm read: ${total:,.2f}\n")
    w = _label_width([c.session.project for c in shown])
    header = (f"{'when':>17}  {'context':>8}  {'idle':>7}  {'cost':>8}  "
              f"{'if warm':>8}  {'premium':>8}  {'project':<{w}}  session")
    print(header)
    print("-" * len(header))
    for c in shown:
        idle = _fmt_duration(timedelta(seconds=c.idle_before)) if c.idle_before else "start"
        cost = c.request.cost
        print(
            f"{c.request.timestamp:%Y-%m-%d %H:%M}  "
            f"{_fmt_tokens(c.context):>8}  {idle:>7}  ${cost:>7.2f}  "
            f"${cost - c.premium:>7.2f}  ${c.premium:>7.2f}  "
            f"{c.session.project:<{w}}  {c.session.session_id[:8]}"
        )
    print(
        "\ncost    what this request actually cost, cold\n"
        "if warm what the same request would have cost had the cache survived\n"
        "premium the difference -- the price of the cache having expired\n"
        "Rebuilding is not free even when warm: the tokens are still read back."
    )


def cmd_sessions(args) -> None:
    requests, _ = _load(args)
    sessions = build_sessions(requests, _ttl(args))
    sessions.sort(key=lambda s: s.cost, reverse=True)
    shown = sessions[: args.limit]

    w = _label_width([s.project for s in shown])
    header = (f"{'when':>17}  {'reqs':>5}  {'wall':>7}  {'peak ctx':>8}  "
              f"{'restarts':>8}  {'cost':>9}  {'premium':>7}  {'project':<{w}}")
    print(header)
    print("-" * len(header))
    for s in shown:
        print(
            f"{s.start:%Y-%m-%d %H:%M}  {len(s.requests):>5,}  "
            f"{_fmt_duration(s.wall_duration):>7}  {_fmt_tokens(s.peak_context):>8}  "
            f"{s.restarts:>8}  ${s.cost:>8.2f}  ${s.restart_premium:>6.2f}  "
            f"{s.project:<{w}}"
        )
    print("\n'premium' is the money paid to write context again after an expiry.")


def _ttl_table(buckets, unit: str) -> None:
    print(f"{unit:>12}{'n':>8}{'median rewrite':>17}{'cache dead':>13}")
    print("-" * 50)
    for b in buckets:
        print(f"{b.label:>12}{b.samples:>8,}{b.median_rewrite:>16.2%}{b.dead_share:>13.1%}")


def cmd_growth(args) -> None:
    requests, _ = _load(args)
    sessions = build_sessions(requests, _ttl(args))
    g = analysis.growth_curve(sessions, min_requests=args.min_requests)

    if not g.points:
        print(f"No uninterrupted lane reached {args.min_requests} requests.")
        return

    print(f"Cost accumulation over {g.lanes} uninterrupted main "
          f"lane(s) of >={g.min_requests} requests\n")
    header = (f"{'req':>6}{'lanes':>7}{'context':>11}"
              f"{'cost/req':>12}{'cumulative':>13}")
    print(header)
    print("-" * len(header))
    for p in g.points:
        print(
            f"{p.request_index:>6}{p.lanes:>7}{p.median_context:>11,.0f}"
            f"{_money(p.median_cost_per_request, 12, 4)}"
            f"{_money(p.median_cumulative, 13)}"
        )

    if g.exponent:
        print(f"\nCumulative cost grows about as requests^{g.exponent:.2f} "
              f"(linear = 1.0, quadratic = 2.0).")
        print("Faster than linear, because every request re-reads the whole context.")
        print("Slower than quadratic, because the context grows more slowly later.")

    print("\nThe carry cost of the context on each request, before any output:\n")
    print(f"{'context':>11}", end="")
    models = ["claude-opus-5", "claude-fable-5"]
    for m in models:
        print(f"{m:>18}", end="")
    print()
    print("-" * (11 + 18 * len(models)))
    for ctx in (200_000, 400_000, 800_000):
        print(f"{ctx:>11,}", end="")
        for m in models:
            print(_money(g.carry_cost_per_request(ctx, m), 18, 3), end="")
        print()
    print("\nOn every request, for as long as the session lives. This is the")
    print("term that makes a long session expensive, not the restarts.")


def cmd_trace(args) -> None:
    requests, _ = _load(args)
    sessions = build_sessions(requests, _ttl(args))
    matches = [s for s in sessions if s.session_id.startswith(args.session)]
    if not matches:
        print(f"No session id starts with {args.session!r}.", file=sys.stderr)
        print("Run `csd sessions` or `csd cold` to find one.", file=sys.stderr)
        sys.exit(1)
    if len(matches) > 1:
        print(f"{args.session!r} matches {len(matches)} sessions:", file=sys.stderr)
        for s in matches[:10]:
            print(f"  {s.session_id}  {s.project}", file=sys.stderr)
        sys.exit(1)

    s = matches[0]
    lanes = s.lanes if args.include_subagents else s.main_lanes
    print(f"session {s.session_id}   {s.project}")
    print(f"total ${s.cost:,.2f} over {len(s.requests):,} requests "
          f"in {len(s.lanes)} lane(s)\n")

    for lane in lanes:
        kind = f"subagent {lane.agent_id}" if lane.is_subagent else "main lane"
        print(f"--- {kind}: {len(lane.requests):,} requests, ${lane.cost:,.2f} ---")
        header = (f"{'time':>19}{'gap':>7}{'input':>8}{'written':>10}"
                  f"{'read':>10}{'context':>10}{'cost':>9}")
        print(header)
        prev = None
        shown = lane.requests[: args.limit]
        for r in shown:
            gap = ""
            cold = ""
            if prev is not None:
                mins = (r.timestamp - prev).total_seconds() / 60
                gap = _fmt_duration(timedelta(minutes=mins))
                if mins > 60:
                    cold = "  <- cache expired"
            print(
                f"{r.timestamp:%Y-%m-%d %H:%M:%S}{gap:>7}{r.input_tokens:>8,}"
                f"{r.cache_write:>10,}{r.cache_read:>10,}{r.context_tokens:>10,}"
                f"${r.cost:>8.2f}{cold}"
            )
            prev = r.timestamp
        if len(lane.requests) > len(shown):
            print(f"  ... {len(lane.requests) - len(shown):,} more "
                  f"(use -n to show more)")
        print()

    print(
        "written = tokens cached on this request, which is only the new content.\n"
        "The cached prefix is re-read, never re-written, so a warm request writes a\n"
        "small delta and reads everything else back at a tenth of the input rate."
    )


def cmd_models(args) -> None:
    requests, stats = _load(args)
    sessions = build_sessions(requests, _ttl(args))
    rows = analysis.spend_by_model(sessions)

    w = _label_width([r.model for r in rows], minimum=20)
    header = (f"{'model':<{w}}{'in $/M':>9}{'out $/M':>9}{'reqs':>9}"
              f"{'cost':>11}{'share':>8}")
    print(header)
    print("-" * len(header))
    total = sum(r.cost for r in rows)
    for r in rows:
        mark = " *" if r.intro_applied else ""
        share = r.cost / total if total else 0.0
        print(
            f"{r.model:<{w}}{r.rate_input:>9.2f}{r.rate_output:>9.2f}"
            f"{r.requests:>9,}{_money(r.cost, 11)}{share:>8.1%}{mark}"
        )
    print("-" * len(header))
    print(f"{'all':<{w}}{'':>18}{sum(r.requests for r in rows):>9,}{_money(total, 11)}")

    if any(r.intro_applied for r in rows):
        print("\n* promotional launch pricing applied for requests dated inside the")
        print("  promo window; rates shown are the standard ones.")
    if stats.unpriced_models:
        print(f"\nUNPRICED: {', '.join(sorted(stats.unpriced_models))}")
        print("These contribute $0 and are excluded from every total.")
    else:
        print("\nEvery model in the corpus has a price; no spend is silently dropped.")


def cmd_ttl(args) -> None:
    requests, _ = _load(args)
    sessions = build_sessions(requests, _ttl(args))
    e = analysis.ttl_evidence(sessions)

    print("1. Which TTL the client requests (measured, from cache_creation)\n")
    print(f"{'lane':>12}{'5m writes':>12}{'1h writes':>12}")
    print("-" * 36)
    for kind, counts in e.requested.items():
        print(f"{kind:>12}{counts['5m']:>12,}{counts['1h']:>12,}")
    print("\nMain lanes ask for the 1h TTL; subagents mostly ask for 5m, which")
    print("suits a lane that lives about a minute.")

    print("\n\n2. When the cache stops being valid -- main lanes, by idle gap\n")
    _ttl_table(e.boundary, "gap (min)")
    print("\nThe transition is abrupt, not gradual: the cache is intact right up")
    print("to the hour and gone immediately after.")

    if e.subagent_boundary:
        print("\n\n3. Subagent lanes, despite mostly requesting a 5m TTL\n")
        _ttl_table(e.subagent_boundary, "gap (min)")
        print("\nThey survive well past five minutes and fail at the same hour mark.")
        print("A prompt is a mix of prefixes written at different TTLs, so what")
        print("survives is the 1h portion shared with the parent session.")

    print("\n\n4. Does the clock run from creation or from last use?\n")
    print("Requests whose gap since the previous one was short (<30 min),")
    print("bucketed by how long their lane had already been alive:\n")
    _ttl_table(e.age_invariance, "lane age")
    print("\nFlat. A lane alive for a day holds its cache as well as a fresh one,")
    print("so the hour is measured from last use and touching a session resets it.")

    print(f"\n\n5. Early expiry: {e.early_deaths:,} of {e.early_total:,} "
          f"({e.early_share:.2%}) lost the cache inside 55 minutes\n")
    for cause, n in e.early_causes.items():
        print(f"   {n:>5,}  {cause}")
    print("\nMostly self-inflicted rather than eviction: the tool set or system")
    print("prompt changed mid-conversation and invalidated the prefix.")


def cmd_misses(args) -> None:
    requests, _ = _load(args)
    sessions = build_sessions(requests, _ttl(args))
    rep = analysis.miss_report(sessions)

    print("Cache misses as reported by the API (message.diagnostics)\n")
    print(f"Requests reporting diagnostics  {rep.requests_with_diagnostics:>10,} "
          f"of {rep.requests_total:,} ({rep.coverage:.1%})")
    print(f"Misses reported                 {rep.total_misses:>10,}")
    if not rep.reasons:
        print("\nNo misses reported. Older client versions omit this field entirely,")
        print("so absence here is not evidence of a perfect cache.")
        return

    print()
    w = _label_width([r.reason for r in rep.reasons], minimum=26)
    header = f"{'reason':<{w}}{'count':>8}{'premium':>11}{'reported tokens':>17}"
    print(header)
    print("-" * len(header))
    for r in rep.reasons:
        mark = " *" if r.self_inflicted else ""
        tokens = _fmt_tokens(r.reported_missed_tokens) if r.reported_missed_tokens else "-"
        print(f"{r.reason + mark:<{w}}{r.count:>8,}{_money(r.premium, 11)}{tokens:>17}")

    print(
        f"\n* something in the request changed and invalidated a prefix that would\n"
        f"  otherwise have been reused -- these are avoidable. "
        f"Premium: ${rep.self_inflicted_premium:,.2f}"
    )
    print(
        "\nThis is the API reporting a failed lookup, which is not the same as\n"
        "`csd cold`: a miss can be partial (most of the prefix still hit), and\n"
        "cannot occur on a lane's first request because there was no prior cache."
    )


def cmd_coverage(args) -> None:
    requests, _ = _load(args)
    sessions = build_sessions(requests, _ttl(args))
    cov = analysis.coverage_report(sessions)

    print("Transcript coverage by month\n")
    print(f"{'month':>9}{'intact':>9}{'orphaned':>10}{'status':>12}")
    print("-" * 40)
    for month in sorted(cov.by_month):
        intact, orphaned = cov.by_month[month]
        status = "complete" if not orphaned else ("PARTIAL" if intact else "FRAGMENTS")
        print(f"{month:>9}{intact:>9,}{orphaned:>10,}{status:>12}")
    print("-" * 40)
    print(f"{'all':>9}{cov.intact:>9,}{cov.orphaned:>10,}")

    if not cov.orphaned:
        print("\nEvery session has its main transcript. Totals are complete.")
        return

    print(
        f"\n{cov.orphaned:,} sessions ({cov.orphan_share:.0%}) exist only as subagent\n"
        f"files; ${cov.orphan_cost:,.2f} of surviving fragment spend is attributed to them.\n"
        "Their main-lane spend cannot be recovered."
    )
    if cov.complete_from:
        print(f"\nThe record looks complete from {cov.complete_from} onward.")
        print("Restrict comparisons to that range to avoid reading pruning as a trend.")
    print(
        "\nClaude Code prunes old top-level transcripts but leaves the nested\n"
        "subagents/ directories in place, which is why the fragments remain."
    )


def cmd_subagents(args) -> None:
    requests, _ = _load(args)
    sessions = build_sessions(requests, _ttl(args))
    r = analysis.subagent_report(sessions)

    if not r.lanes:
        print("No subagent transcripts found.")
        return

    print(f"Subagents            {r.lanes:>10,}")
    print(f"Requests             {r.requests:>10,}")
    print(f"Spend                {'$' + format(r.cost, ',.2f'):>10}  "
          f"({r.share:.1%} of all spend)")
    print(f"Sessions using them  {r.sessions_using:>10,} of {r.total_sessions:,}")
    print()
    print(f"Per subagent, median: {r.median_requests:.0f} requests, "
          f"{r.median_duration_seconds / 60:.1f} min, "
          f"{_fmt_tokens(r.median_peak_context)} peak context")
    print(
        "\nSubagents are short-lived and start cold by design, so they are held out\n"
        "of the cache analyses (`decay`, `cold`, restart premium) by default --\n"
        "pass --include-subagents to fold them in. Their spend is always counted."
    )

    groups = analysis.by_project(sessions)
    rows = [(p, analysis.subagent_report(g)) for p, g in groups.items()]
    rows = [(p, sr) for p, sr in rows if sr.lanes]
    if not rows:
        return
    print()
    w = _label_width([p for p, _ in rows])
    header = (f"{'project':<{w}}{'subagents':>11}{'reqs':>8}{'spend':>10}"
              f"{'share':>8}{'med reqs':>10}{'med min':>9}")
    print(header)
    print("-" * len(header))
    for project, sr in rows:
        print(
            f"{project:<{w}}{sr.lanes:>11,}{sr.requests:>8,}{_money(sr.cost, 10)}"
            f"{sr.share:>8.1%}{sr.median_requests:>10.0f}"
            f"{sr.median_duration_seconds / 60:>9.1f}"
        )
    print("\nshare = subagent spend as a fraction of that project's total spend")


def cmd_projects(args) -> None:
    requests, _ = _load(args)
    sessions = build_sessions(requests, _ttl(args))
    groups = analysis.by_project(sessions)
    ready = analysis.ready_tokens_by_project(sessions)

    w = _label_width(groups)
    header = (f"{'project':<{w}}{'sessions':>9}{'reqs':>8}{'cost':>10}"
              f"{'restarts':>9}{'premium':>9}{'hit':>7}{'ready':>8}")
    print(header)
    print("-" * len(header))
    for project, group in groups.items():
        t = analysis.totals(group)
        r = analysis.restart_report(group)
        point = ready.get(project)
        if point is None:
            ready_col = "-"
        else:
            ready_col = _fmt_tokens(point.tokens) + ("" if point.reliable else "?")
        print(
            f"{project:<{w}}{t.sessions:>9,}{t.requests:>8,}{_money(t.cost, 11)}"
            f"{r.mid_session_restarts:>9,}{_money(r.restart_premium, 10)}"
            f"{t.cache_hit_rate:>7.1%}{ready_col:>8}"
        )
    total = analysis.totals(sessions)
    report = analysis.restart_report(sessions)
    print("-" * len(header))
    print(
        f"{'all':<{w}}{total.sessions:>9,}{total.requests:>8,}{_money(total.cost, 11)}"
        f"{report.mid_session_restarts:>9,}{_money(report.restart_premium, 10)}"
        f"{total.cache_hit_rate:>7.1%}{'':>8}"
    )
    print("\npremium = money paid to write context again after an expiry")
    print("ready = observed context at the first Edit/Write of a cold session")
    print(f"        '?' means fewer than {analysis.MIN_READY_SAMPLES} samples")


# (label, width) so the header and rows cannot drift apart, and so the labels
# can be checked for ambiguity -- two columns both reading "p75" is unreadable.
READY_COLUMNS: list[tuple[str, int]] = [
    ("context", 9), ("ctx p75", 9), ("at req", 8),
    ("cost", 9), ("cost p75", 10), ("rebuild", 10), ("n", 7),
]
READY_HEADER = "".join(f"{label:>{w}}" for label, w in READY_COLUMNS)


def _print_ready(point: analysis.ReadyPoint | None, label: str, width: int) -> None:
    if point is None:
        print(f"{label:<{width}}  no cold session reached a first Edit/Write")
        return
    # '*' rather than a trailing phrase, so the row stays inside the table.
    n = f"{point.samples}{'' if point.reliable else '*'}"
    print(
        f"{label:<{width}}{_fmt_tokens(point.tokens):>9}"
        f"{_fmt_tokens(point.p75_tokens):>9}{point.median_request_index:>8}"
        f"{_money(point.median_cost, 9)}{_money(point.p75_cost, 10)}"
        f"{_money(point.median_rebuild_cost, 10)}{n:>7}"
    )


def cmd_startup(args) -> None:
    requests, _ = _load(args)
    sessions = build_sessions(requests, _ttl(args))
    prefix = analysis.startup_prefix_tokens(sessions)

    print(f"Fixed prefix  {_fmt_tokens(prefix)}  "
          f"(median context on request 1 of a cold session)")
    print("System prompt + tool schemas + project instructions: what a fresh")
    print("session writes before doing anything at all.\n")

    print("Ready to work: context at the first Edit/Write of a cold session.")
    print("Everything before that is orientation -- reading, searching, running")
    print("commands -- so this is the observed cost of getting productive.\n")
    points = analysis.ready_tokens_by_project(sessions)
    shown = (
        {}
        if args.no_projects
        else {p: pt for p, pt in points.items() if pt.samples >= args.min_samples}
    )
    w = _label_width(["all projects", *(f"  {p}" for p in shown)])
    print(f"{'':<{w}}{READY_HEADER}")
    print("-" * (w + len(READY_HEADER)))
    _print_ready(analysis.observed_ready_tokens(sessions), "all projects", w)
    for project, point in shown.items():
        _print_ready(point, f"  {project}", w)

    print("\nContext ramp over the opening requests of cold sessions:\n")
    ramp = analysis.startup_ramp(sessions)
    print(f"{'request':>8}  {'median context':>15}  {'sessions':>9}")
    print("-" * 38)
    for index, median, pool in ramp:
        print(f"{index:>8}  {_fmt_tokens(median):>15}  {pool:>9}")
    print(
        "\ncontext   prompt size at the first Edit/Write (ctx p75 = its 75th pct)\n"
        "at req    how many requests of orienting that took\n"
        "cost      what those orienting requests actually cost, all in\n"
        "rebuild   what re-establishing that context costs if the cache expires\n"
        f"n         cold sessions sampled; * = fewer than "
        f"{analysis.MIN_READY_SAMPLES}, treat as indicative\n"
        "\nCost does not track context size alone -- it also depends on how many\n"
        "requests the orienting took, how much was generated along the way, and\n"
        "which model ran. Projects reorder between the token and cost columns."
    )
    print(
        "\nThe ramp never plateaus -- context accrues steadily as work proceeds --\n"
        "which is why the first-mutation marker is used instead of looking for an\n"
        "inflection point that does not exist."
    )


def cmd_crossover(args) -> None:
    requests, _ = _load(args)
    sessions = build_sessions(requests, _ttl(args))
    startup, origin = analysis.resolve_ready_tokens(sessions, args.startup_tokens)
    prefix = analysis.startup_prefix_tokens(sessions)
    observed = analysis.observed_ready_tokens(sessions)
    ready_cost = (
        args.ready_cost
        if args.ready_cost is not None
        else (observed.median_cost if observed else 0.0)
    )
    ready_reqs = (
        args.ready_requests
        if args.ready_requests is not None
        else (observed.median_request_index if observed else 0)
    )

    long_restarts = (
        args.restarts
        if args.restarts is not None
        else analysis.observed_restarts(sessions, args.requests)
    )
    short_each = (
        args.short_restarts
        if args.short_restarts is not None
        else analysis.observed_restarts(sessions, args.requests // max(1, args.sessions))
    )
    c = analysis.compare_strategies(
        model=args.model,
        startup_tokens=startup,
        requests=args.requests,
        long_peak=args.large,
        short_peak=args.small,
        short_sessions=args.sessions,
        long_restarts=long_restarts,
        short_restarts_each=short_each,
        rework=args.rework,
        output_cost_per_request=(
            args.output_cost
            if args.output_cost is not None
            else analysis.observed_output_cost(sessions)
        ),
        ready_cost_each=ready_cost,
        ready_requests_each=ready_reqs,
    )
    print(f"Model            {c.model}")
    print(f"Startup context  {_fmt_tokens(c.startup_tokens)} ({origin})")
    print(f"                 fixed prefix {_fmt_tokens(prefix)}; see `csd startup`")
    origin_r = "supplied" if args.restarts is not None else "observed for this length"
    print(f"Getting ready    ${ready_cost:.2f} and {ready_reqs} requests per session "
          f"(see `csd startup`)")
    print(f"Work             {args.requests} productive requests, +{args.rework:.0%} "
          f"rework for the split strategy")
    print(f"Cache expiries   {long_restarts} on the long session, "
          f"{short_each} on each short one ({origin_r})\n")

    print("Costs are TOTALS for the whole strategy; 'ea' columns are per session.\n")
    header = (f"{'':<19}{'sess':>5}{'reqs':>6}{'req ea':>8}{'peak ea':>9}"
              f"{'ready':>9}{'growth':>9}{'carry':>10}{'output':>9}"
              f"{'restart':>9}{'total':>11}")
    print(header)
    print("-" * len(header))
    for s in (c.long_run, c.short_runs):
        print(
            f"{s.label:<19}{s.sessions:>5}{s.requests:>6}"
            f"{s.requests_per_session:>8.0f}{_fmt_tokens(s.peak_context):>9}"
            f"{_money(s.ready_cost, 9)}{_money(s.growth_cost, 9)}"
            f"{_money(s.carry_cost, 10)}{_money(s.output_cost, 9)}"
            f"{_money(s.restart_cost, 9)}{_money(s.total, 11)}"
        )
    if c.short_runs.sessions > 1:
        per = c.short_runs.total / c.short_runs.sessions
        print(f"\n{c.short_runs.label}: ${per:,.2f} each, "
              f"${c.short_runs.total:,.2f} for all {c.short_runs.sessions}.")
    print(f"\nContext grows {c.long_run.growth_per_request:,.0f} tokens/request "
          f"(long) and {c.short_runs.growth_per_request:,.0f} (short), derived from\n"
          f"the peaks you supplied. Peak follows request count, so rework carries "
          f"its own context.")
    if not c.inputs_consistent:
        print(
            f"\nWARNING: the short sessions are assumed to accumulate context "
            f"{c.growth_ratio:.1f}x\nfaster per request than the long one. That is an "
            f"artefact of the peaks and\nsession count you gave, not a finding. "
            f"Set --small to about "
            f"{int(c.startup_tokens + c.long_run.growth_per_request * c.short_runs.requests_per_session):,}\n"
            f"to compare like with like."
        )
    print(f"\n{c.verdict}.")
    if c.breakeven_rework == float("inf"):
        print("No amount of rework makes the split strategy more expensive.")
    elif c.breakeven_rework < 0:
        print("The split strategy loses even with zero rework.")
    elif c.breakeven_rework > 3:
        print(f"Break-even: the split strategy only loses once it needs "
              f"{c.breakeven_rework:.0%} more\nrequests -- so far out that the "
              f"comparison is effectively one-sided.")
    else:
        print(
            f"Break-even: the split strategy stops being cheaper once it needs "
            f"{c.breakeven_rework:.0%} more requests\nto rebuild the understanding "
            f"the long session already had."
        )
    print(
        "\nready   = orienting, once per session -- measured all-in, not a token write\n"
        "growth  = new tokens cached once      carry = context re-read each request\n"
        "output  = tokens generated          restart = context rebuilt after expiry"
    )


def cmd_export(args) -> None:
    requests, stats = _load(args)
    sessions = build_sessions(requests, _ttl(args))
    payload = [
        {
            "session_id": s.session_id,
            "project": s.project,
            "start": s.start.isoformat(),
            "end": s.end.isoformat(),
            "requests": len(s.requests),
            "wall_seconds": s.wall_duration.total_seconds(),
            "active_seconds": s.active_duration.total_seconds(),
            "peak_context": s.peak_context,
            "output_tokens": s.output_tokens,
            "cost": round(s.cost, 6),
            "restarts": s.restarts,
            "restart_premium": round(s.restart_premium, 6),
            "models": sorted(s.models),
        }
        for s in sessions
    ]
    json.dump(payload, sys.stdout, indent=2)
    sys.stdout.write("\n")


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="csd",
        description="Cost and cache diagnostics for Claude Code sessions.",
    )
    p.add_argument("--root", default=str(parser_mod.DEFAULT_ROOT),
                   help="session transcript root (default: ~/.claude/projects)")
    p.add_argument("--project", help="only include projects matching this substring "
                                     "(matched against the full working directory)")
    p.add_argument("--project-depth", type=int, default=parser_mod.DEFAULT_PROJECT_DEPTH,
                   metavar="N",
                   help="path segments in a project label, e.g. 2 -> acme/acme-core "
                        f"(default: {parser_mod.DEFAULT_PROJECT_DEPTH})")
    p.add_argument("--ttl", type=int, metavar="MIN",
                   help="cache TTL in minutes for segment splitting (default: 60)")
    sub = p.add_subparsers(dest="command", required=True)

    s = sub.add_parser("summary", help="totals, cache hit rate, cost of restarts")
    s.add_argument("-v", "--verbose", action="store_true", help="show parser diagnostics")
    s.set_defaults(func=cmd_summary)

    # Only the cache analyses take this; it sits on the subcommands so it can be
    # written after them, which is the order people reach for.
    subagent_flag = dict(
        action="store_true",
        help="fold subagent lanes in; they are short-lived and start cold by "
             "design, so they are held out by default",
    )

    s = sub.add_parser("decay", help="measured cache decay against idle time")
    s.add_argument("--include-subagents", **subagent_flag)
    s.set_defaults(func=cmd_decay)

    s = sub.add_parser("cold", help="the most expensive cold starts, in order")
    s.add_argument("--min-context", type=int, default=20_000)
    s.add_argument("-n", "--limit", type=int, default=25)
    s.add_argument("--include-subagents", **subagent_flag)
    s.set_defaults(func=cmd_cold)

    s = sub.add_parser("sessions", help="cost of each session")
    s.add_argument("-n", "--limit", type=int, default=25)
    s.set_defaults(func=cmd_sessions)

    s = sub.add_parser("growth", help="how cost accumulates as a session becomes longer")
    s.add_argument("--min-requests", type=int, default=200,
                   help="only use lanes that had no expiry and are at least this long")
    s.set_defaults(func=cmd_growth)

    s = sub.add_parser("trace", help="request-by-request ledger for one session")
    s.add_argument("session", help="session id, or a unique prefix of one")
    s.add_argument("-n", "--limit", type=int, default=40)
    s.add_argument("--include-subagents", action="store_true",
                   help="also trace the session's subagent lanes")
    s.set_defaults(func=cmd_trace)

    s = sub.add_parser("models", help="requests by model and the rates applied")
    s.set_defaults(func=cmd_models)

    s = sub.add_parser("ttl", help="evidence for how long the cache stays warm")
    s.set_defaults(func=cmd_ttl)

    s = sub.add_parser("misses", help="cache misses that the API reports, and their causes")
    s.set_defaults(func=cmd_misses)

    s = sub.add_parser("coverage", help="how complete the transcript record is")
    s.set_defaults(func=cmd_coverage)

    s = sub.add_parser("subagents", help="cost and shape of delegated work")
    s.set_defaults(func=cmd_subagents)

    s = sub.add_parser("projects", help="cost, restarts and startup cost for each project")
    s.set_defaults(func=cmd_projects)

    s = sub.add_parser("startup", help="startup cost, for all projects and for each one")
    s.add_argument("--min-samples", type=int, default=2,
                   help="hide projects with fewer cold sessions than this")
    s.add_argument("--no-projects", action="store_true",
                   help="show the overall figure only")
    s.set_defaults(func=cmd_startup)

    s = sub.add_parser("crossover", help="one long warm session vs several short ones")
    s.add_argument("--model", default="claude-opus-5")
    s.add_argument("--startup-tokens", type=int,
                   help="context a fresh session needs to be productive "
                        "(default: observed from these sessions)")
    s.add_argument("--requests", type=int, default=200,
                   help="PRODUCTIVE requests of work, excluding orientation")
    s.add_argument("--ready-cost", type=float, default=None, metavar="USD",
                   help="cost of orienting one session (default: observed)")
    s.add_argument("--ready-requests", type=int, default=None, metavar="N",
                   help="requests spent orienting one session (default: observed)")
    s.add_argument("--small", type=int, default=200_000, help="peak context of a short session")
    s.add_argument("--large", type=int, default=600_000, help="peak context of the long session")
    s.add_argument("--sessions", type=int, default=5,
                   help="how many short sessions replace the long one")
    s.add_argument("--restarts", type=int, default=None,
                   help="cache expiries on the long session "
                        "(default: observed median for sessions of that length)")
    s.add_argument("--short-restarts", type=int, default=None, metavar="N",
                   help="cache expiries on EACH short session "
                        "(default: observed median for sessions of that length)")
    s.add_argument("--output-cost", type=float, default=None, metavar="USD",
                   help="cost of generated output per request "
                        "(default: observed median)")
    s.add_argument("--rework", type=float, default=0.0, metavar="FRAC",
                   help="extra requests the short sessions need to rebuild the "
                        "context the long session still had (0.3 = 30%% more)")
    s.set_defaults(func=cmd_crossover)

    s = sub.add_parser("export", help="records for each session, as JSON")
    s.set_defaults(func=cmd_export)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    args.func(args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
