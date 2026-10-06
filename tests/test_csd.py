"""Tests for csd. Standard library unittest only.

Run: python -m unittest discover -s tests
"""

from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from csd import analysis, cli, parser, pricing, session


def _line(
    *,
    ts: str,
    request_id: str,
    message_id: str,
    model: str = "claude-opus-5",
    # Defaults to zero so a fixture's context_tokens is exactly writes + reads;
    # tests that care about uncached input pass it explicitly.
    input_tokens: int = 0,
    output_tokens: int = 20,
    write_1h: int = 0,
    write_5m: int = 0,
    read: int = 0,
    session_id: str = "sess-1",
    tools: tuple[str, ...] = (),
    cwd: str = "/Users/someone/src/demo",
    speed: str | None = None,
    # False writes the old format: only the total of the cache writes, with no
    # `cache_creation` object to split it by TTL.
    split: bool = True,
) -> str:
    content = [{"type": "text", "text": "..."}]
    content += [
        {"type": "tool_use", "id": f"tu-{i}", "name": name, "input": {}}
        for i, name in enumerate(tools)
    ]
    usage = {
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "cache_creation_input_tokens": write_1h + write_5m,
        "cache_read_input_tokens": read,
    }
    if split:
        usage["cache_creation"] = {
            "ephemeral_1h_input_tokens": write_1h,
            "ephemeral_5m_input_tokens": write_5m,
        }
    if speed is not None:
        usage["speed"] = speed
    return json.dumps(
        {
            "type": "assistant",
            "timestamp": ts,
            "requestId": request_id,
            "sessionId": session_id,
            "cwd": cwd,
            "isSidechain": False,
            "version": "2.1.0",
            "message": {
                "id": message_id,
                "model": model,
                "content": content,
                "usage": usage,
            },
        }
    )


def _write_transcript(dirpath: Path, name: str, lines: list[str]) -> Path:
    proj = dirpath / "-Users-someone-src-demo"
    proj.mkdir(parents=True, exist_ok=True)
    path = proj / f"{name}.jsonl"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


class TestPricing(unittest.TestCase):
    def test_normalise_strips_suffixes(self):
        self.assertEqual(pricing.normalise_model("claude-opus-5[1m]"), "claude-opus-5")
        self.assertEqual(pricing.normalise_model("anthropic.claude-opus-5"), "claude-opus-5")
        self.assertEqual(
            pricing.normalise_model("claude-haiku-4-5-20251001"), "claude-haiku-4-5"
        )
        self.assertEqual(pricing.normalise_model("claude-opus-5-fast"), "claude-opus-5")

    def test_synthetic_is_unpriced(self):
        self.assertIsNone(pricing.normalise_model("<synthetic>"))
        self.assertIsNone(pricing.price_for("<synthetic>"))
        self.assertEqual(pricing.cost("<synthetic>", input_tokens=10_000), 0.0)

    def test_cache_multipliers(self):
        # 1M tokens at $5/M input.
        base = pricing.cost("claude-opus-5", input_tokens=1_000_000)
        self.assertAlmostEqual(base, 5.0)
        self.assertAlmostEqual(
            pricing.cost("claude-opus-5", cache_write_1h=1_000_000), 5.0 * 2.00
        )
        self.assertAlmostEqual(
            pricing.cost("claude-opus-5", cache_write_5m=1_000_000), 5.0 * 1.25
        )
        self.assertAlmostEqual(
            pricing.cost("claude-opus-5", cache_read=1_000_000), 5.0 * 0.10
        )

    def test_fast_mode_costs_more(self):
        std = pricing.cost("claude-opus-5", output_tokens=1_000_000)
        fast = pricing.cost("claude-opus-5", output_tokens=1_000_000, fast=True)
        self.assertAlmostEqual(std, 25.0)
        self.assertAlmostEqual(fast, 50.0)

    def test_intro_rate_applies_before_the_cutoff(self):
        """Sonnet 5 launched at $2/$10 through 2026-08-31, then $3/$15."""
        during = datetime(2026, 8, 9, tzinfo=timezone.utc)
        self.assertAlmostEqual(
            pricing.cost("claude-sonnet-5", input_tokens=1_000_000, at=during), 2.0
        )
        self.assertAlmostEqual(
            pricing.cost("claude-sonnet-5", output_tokens=1_000_000, at=during), 10.0
        )

    def test_intro_rate_ends_after_the_cutoff(self):
        after = datetime(2026, 9, 1, tzinfo=timezone.utc)
        self.assertAlmostEqual(
            pricing.cost("claude-sonnet-5", input_tokens=1_000_000, at=after), 3.0
        )

    def test_intro_cutoff_is_inclusive(self):
        last = datetime(2026, 8, 31, 23, 59, tzinfo=timezone.utc)
        self.assertAlmostEqual(
            pricing.cost("claude-sonnet-5", input_tokens=1_000_000, at=last), 2.0
        )

    def test_undated_request_falls_back_to_standard_rate(self):
        self.assertAlmostEqual(
            pricing.cost("claude-sonnet-5", input_tokens=1_000_000), 3.0
        )

    def test_models_without_intro_pricing_ignore_the_date(self):
        during = datetime(2026, 8, 9, tzinfo=timezone.utc)
        self.assertAlmostEqual(
            pricing.cost("claude-opus-5", input_tokens=1_000_000, at=during), 5.0
        )

    def test_request_cost_uses_its_own_timestamp(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_transcript(root, "s1", [
                _line(ts="2026-08-09T10:00:00Z", request_id="r0", message_id="m0",
                      model="claude-sonnet-5", input_tokens=1_000_000),
                _line(ts="2026-09-09T10:00:00Z", request_id="r1", message_id="m1",
                      model="claude-sonnet-5", input_tokens=1_000_000),
            ])
            reqs, _ = parser.load(root=root)
            by_ts = {r.timestamp.date().isoformat(): r for r in reqs}
            # Output tokens default to 20, so compare the input component only.
            self.assertLess(by_ts["2026-08-09"].cost, by_ts["2026-09-09"].cost)

    def test_worked_example_premium_and_total_are_distinct(self):
        """A real cold start, traced end to end.

        Fable 5 at $10/M in, $50/M out. 417,356 tokens re-written at the 1h
        rate, 16,715 read back, 2 uncached, 4,153 generated.

        The premium is NOT the request's cost: it is the difference between the
        cold cost and what the same request would have cost warm. Reading the
        premium as the total understates it, and reading it as pure avoidable
        loss overstates what staying warm would have saved.
        """
        kwargs = dict(
            input_tokens=2, cache_write_1h=417_356, cache_read=16_715,
            output_tokens=4_153,
        )
        cold = pricing.cost("claude-fable-5", **kwargs)
        premium = pricing.cold_start_premium("claude-fable-5", 417_356)

        # Cold: writes at 2.00x, read at 0.10x, input at 1.00x, output at $50/M.
        self.assertAlmostEqual(cold, 8.5715, places=3)
        # Premium: the re-written tokens at (2.00 - 0.10) x the input rate.
        self.assertAlmostEqual(premium, 7.9298, places=3)
        # Warm counterfactual: those tokens read back instead of written.
        warm = pricing.cost(
            "claude-fable-5",
            input_tokens=2, cache_read=16_715 + 417_356, output_tokens=4_153,
        )
        self.assertAlmostEqual(warm, 0.6417, places=3)
        self.assertAlmostEqual(cold - warm, premium, places=6)

    def test_same_premium_needs_half_the_context_on_a_dearer_model(self):
        """Model choice moves the number as much as context size does."""
        opus = pricing.cold_start_premium("claude-opus-5", 800_000)
        fable = pricing.cold_start_premium("claude-fable-5", 400_000)
        self.assertAlmostEqual(opus, fable)

    def test_cold_premium_is_write_minus_read(self):
        premium = pricing.cold_start_premium("claude-opus-5", cache_write_1h=1_000_000)
        self.assertAlmostEqual(premium, 5.0 * (2.00 - 0.10))


class TestParserDedup(unittest.TestCase):
    """The behaviour that most affects correctness: one request, many lines."""

    def test_repeated_usage_counted_once(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            # Three lines, same requestId/message.id -> one billed request.
            lines = [
                _line(ts="2026-01-01T10:00:00Z", request_id="r1", message_id="m1",
                      output_tokens=100)
                for _ in range(3)
            ]
            lines.append(
                _line(ts="2026-01-01T10:00:30Z", request_id="r2", message_id="m2",
                      output_tokens=50)
            )
            _write_transcript(root, "s1", lines)

            reqs, stats = parser.load(root=root)
            self.assertEqual(stats.assistant_lines, 4)
            self.assertEqual(len(reqs), 2)
            self.assertEqual(stats.duplicate_lines, 2)
            self.assertEqual(sum(r.output_tokens for r in reqs), 150)

    def test_synthetic_lines_excluded(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_transcript(root, "s1", [
                _line(ts="2026-01-01T10:00:00Z", request_id="r1", message_id="m1"),
                _line(ts="2026-01-01T10:00:05Z", request_id="r2", message_id="m2",
                      model="<synthetic>"),
            ])
            reqs, stats = parser.load(root=root)
            self.assertEqual(len(reqs), 1)
            self.assertEqual(stats.synthetic, 1)

    def test_malformed_lines_do_not_abort_parse(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_transcript(root, "s1", [
                '{"type": "assistant", broken json',
                _line(ts="2026-01-01T10:00:00Z", request_id="r1", message_id="m1"),
            ])
            reqs, stats = parser.load(root=root)
            self.assertEqual(len(reqs), 1)
            self.assertEqual(stats.malformed_lines, 1)

    def test_legacy_transcript_without_cache_creation_split(self):
        """Older logs report only the aggregate; attribute it to the 1h TTL."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            rec = json.loads(_line(ts="2026-01-01T10:00:00Z", request_id="r1",
                                   message_id="m1", write_1h=500))
            del rec["message"]["usage"]["cache_creation"]
            _write_transcript(root, "s1", [json.dumps(rec)])
            reqs, _ = parser.load(root=root)
            self.assertEqual(reqs[0].cache_write_1h, 500)
            self.assertEqual(reqs[0].cache_write_5m, 0)

    def test_prompt_tokens_land_in_exactly_one_bucket(self):
        """The three usage buckets partition the prompt; they do not overlap.

        A cold restart does NOT pay the input rate to re-read the context and
        then a write rate on top. Each token is billed once: the 2.00x on a 1h
        cache write is the all-in price for processing it and caching it. The
        giveaway in real data is that `input_tokens` stays near zero on a cold
        restart while `cache_creation_input_tokens` carries the whole context.
        """
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_transcript(root, "s1", [
                _line(ts="2026-01-01T10:00:00Z", request_id="r0", message_id="m0",
                      input_tokens=2, write_1h=417_356, read=16_715),
            ])
            reqs, _ = parser.load(root=root)
            r = reqs[0]
            self.assertEqual(r.context_tokens, 2 + 417_356 + 16_715)
            # Priced once, at the write multiplier -- not input + write.
            expected = (
                2 * 5 / 1e6
                + 417_356 * 5 / 1e6 * pricing.CACHE_WRITE_1H
                + 16_715 * 5 / 1e6 * pricing.CACHE_READ
                + 20 * 25 / 1e6  # default output tokens in the fixture
            )
            self.assertAlmostEqual(r.cost, expected, places=6)

    def test_warm_request_writes_only_the_new_content(self):
        """After a restart the context is not re-written on each request.

        Tokens written on a request equal the growth in context since the previous
        one -- verified across 25,685 real warm requests, exact to within a token.
        """
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_transcript(root, "s1", [
                # Cold: whole context written.
                _line(ts="2026-01-01T10:00:00Z", request_id="r0", message_id="m0",
                      input_tokens=2, write_1h=417_356, read=16_715),
                # Next request: prefix read back, only the delta written.
                _line(ts="2026-01-01T10:01:00Z", request_id="r1", message_id="m1",
                      input_tokens=2, write_1h=4_329, read=434_071),
            ])
            reqs, _ = parser.load(root=root)
            cold, warm = reqs
            growth = warm.context_tokens - cold.context_tokens
            self.assertEqual(warm.cache_write, growth)
            # And the warm request is an order of magnitude cheaper.
            self.assertLess(warm.cost, cold.cost / 10)

    def test_context_tokens_sums_whole_prompt(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_transcript(root, "s1", [
                _line(ts="2026-01-01T10:00:00Z", request_id="r1", message_id="m1",
                      input_tokens=100, write_1h=200, read=700)
            ])
            reqs, _ = parser.load(root=root)
            self.assertEqual(reqs[0].context_tokens, 1000)


class TestSegments(unittest.TestCase):
    def _reqs(self, offsets_minutes: list[int]) -> list[parser.Request]:
        base = datetime(2026, 1, 1, 10, 0, tzinfo=timezone.utc)
        return [
            parser.Request(
                timestamp=base + timedelta(minutes=m),
                model="claude-opus-5",
                input_tokens=0,
                output_tokens=10,
                cache_write_5m=0,
                cache_write_1h=1000,
                cache_read=50_000,
                fast=False,
                session_id="s",
                project="demo",
                transcript=Path("/tmp/s.jsonl"),
                request_id=f"r{i}",
                message_id=f"m{i}",
                is_sidechain=False,
                version="2.1.0",
            )
            for i, m in enumerate(offsets_minutes)
        ]

    def test_gap_under_ttl_stays_one_segment(self):
        segs = session.split_segments(self._reqs([0, 30, 59]))
        self.assertEqual(len(segs), 1)

    def test_gap_over_ttl_splits(self):
        segs = session.split_segments(self._reqs([0, 30, 121, 130]))
        self.assertEqual(len(segs), 2)
        self.assertEqual(len(segs[0].requests), 2)
        self.assertEqual(len(segs[1].requests), 2)

    def test_restart_premium_excludes_first_segment(self):
        reqs = self._reqs([0, 200])
        sess = session.build_sessions(reqs)[0]
        self.assertEqual(sess.restarts, 1)
        # Only the second segment's opening request counts as a premium.
        self.assertAlmostEqual(sess.restart_premium, reqs[1].cold_premium)

    def test_active_duration_excludes_idle_gaps(self):
        reqs = self._reqs([0, 30, 300, 330])
        sess = session.build_sessions(reqs)[0]
        self.assertEqual(sess.wall_duration, timedelta(minutes=330))
        self.assertEqual(sess.active_duration, timedelta(minutes=60))

    def test_cold_start_detection(self):
        warm, cold = self._reqs([0, 200])
        self.assertFalse(session.is_cold_start(warm))
        rebuilt = parser.Request(
            **{**warm.__dict__, "cache_write_1h": 200_000, "cache_read": 0}
        )
        self.assertTrue(session.is_cold_start(rebuilt))

    def test_small_context_is_not_a_cold_start(self):
        tiny = parser.Request(
            **{**self._reqs([0])[0].__dict__, "cache_write_1h": 500, "cache_read": 0}
        )
        self.assertFalse(session.is_cold_start(tiny))


class TestGrowthCurve(unittest.TestCase):
    """Cost accumulation as a lane lengthens."""

    def _lane(self, n_requests: int, growth: int) -> Path:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        lines = []
        ctx = 0
        for i in range(n_requests):
            read = ctx
            ctx += growth
            hh, mm = divmod(i, 60)
            lines.append(_line(
                ts=f"2026-01-01T{10 + hh:02d}:{mm:02d}:00Z",
                request_id=f"r{i}", message_id=f"m{i}", session_id="S1",
                write_1h=growth, read=read,
            ))
        _write_transcript(root, "s1", lines)
        return root

    def _curve(self, n_requests: int, growth: int, **kw):
        reqs, _ = parser.load(root=self._lane(n_requests, growth))
        return analysis.growth_curve(session.build_sessions(reqs), **kw)

    def test_cost_per_request_rises_with_context(self):
        g = self._curve(60, 2_000, min_requests=50, at_requests=(1, 25, 50))
        costs = [p.median_cost_per_request for p in g.points]
        self.assertEqual(costs, sorted(costs))
        contexts = [p.median_context for p in g.points]
        self.assertEqual(contexts, sorted(contexts))

    def test_linear_context_growth_pushes_cost_toward_quadratic(self):
        """Constant tokens added per request is the worst case for cost growth.

        The cache-read term alone would be exactly quadratic, but each request also
        pays a constant write and output cost, and those linear terms pull the
        fitted exponent below 2. Real sessions land lower still (~1.2), because
        the context grows more slowly later rather than at a constant rate.
        """
        g = self._curve(210, 2_000, min_requests=200)
        self.assertIsNotNone(g.exponent)
        self.assertGreater(g.exponent, 1.5, "should be clearly super-linear")
        self.assertLess(g.exponent, 2.1)

    def test_decelerating_growth_lowers_the_exponent(self):
        """Halve the growth per request and the curve flattens."""
        fast = self._curve(210, 4_000, min_requests=200)
        slow = self._curve(210, 500, min_requests=200)
        self.assertGreater(fast.exponent, slow.exponent)

    def test_short_lanes_are_excluded(self):
        g = self._curve(30, 2_000, min_requests=200)
        self.assertEqual(g.points, [])
        self.assertEqual(g.lanes, 0)

    def test_carry_cost_scales_with_context_and_model_rate(self):
        g = self._curve(60, 2_000, min_requests=50, at_requests=(1,))
        # 0.10x the input rate: $5/M for Opus, $10/M for Fable.
        self.assertAlmostEqual(g.carry_cost_per_request(800_000, "claude-opus-5"), 0.40)
        self.assertAlmostEqual(g.carry_cost_per_request(800_000, "claude-fable-5"), 0.80)
        self.assertAlmostEqual(g.carry_cost_per_request(400_000, "claude-opus-5"), 0.20)


class TestStrategyComparison(unittest.TestCase):
    BASE = dict(
        model="claude-opus-5", startup_tokens=29_000, requests=200,
        long_peak=600_000, short_peak=200_000, short_sessions=5,
    )

    def test_breakeven_rework_makes_totals_match(self):
        c = analysis.compare_strategies(**self.BASE)
        self.assertGreater(c.breakeven_rework, 0)
        at = analysis.compare_strategies(**self.BASE, rework=c.breakeven_rework)
        # Request counts are rounded to whole requests, so allow a little slack.
        self.assertLess(
            abs(at.long_run.total - at.short_runs.total) / at.long_run.total, 0.01
        )

    def test_rework_carries_its_own_context(self):
        """More requests must mean more context, or extra work comes out free.

        The earlier model pinned peak context to the supplied value regardless
        of request count, so rework silently reduced the implied growth rate and
        the split strategy was let off far too lightly.
        """
        base = analysis.compare_strategies(**self.BASE).short_runs
        heavy = analysis.compare_strategies(**self.BASE, rework=1.5).short_runs
        self.assertGreater(heavy.requests, base.requests)
        self.assertGreater(heavy.peak_context, base.peak_context)
        # The growth rate is a property of the work, not of how much is done.
        self.assertAlmostEqual(
            heavy.growth_per_request, base.growth_per_request, places=6
        )

    def test_peak_context_matches_the_supplied_value_at_baseline(self):
        """With no rework, derived peaks reproduce what the caller asked for."""
        c = analysis.compare_strategies(**self.BASE)
        self.assertAlmostEqual(c.long_run.peak_context, 600_000, delta=500)
        self.assertAlmostEqual(c.short_runs.peak_context, 200_000, delta=500)

    def test_mismatched_inputs_are_flagged_not_silently_costed(self):
        """Peaks are given independently of the session split, so they can
        describe a short session growing far faster per request than the long
        one. That is an input error, and it must be visible."""
        skewed = analysis.compare_strategies(
            **{**self.BASE, "short_sessions": 10}
        )
        self.assertFalse(skewed.inputs_consistent)
        self.assertGreater(skewed.growth_ratio, 1.5)

        matched = analysis.compare_strategies(
            **{**self.BASE, "short_sessions": 10, "short_peak": 80_000}
        )
        self.assertTrue(matched.inputs_consistent)

    def test_carry_cost_is_superlinear_in_rework(self):
        """Doubling the requests more than doubles carry: context rises too."""
        one = analysis.compare_strategies(**self.BASE, rework=0.0).short_runs
        two = analysis.compare_strategies(**self.BASE, rework=1.0).short_runs
        self.assertGreater(two.carry_cost, 2 * one.carry_cost)

    def test_costs_are_totals_and_peak_is_per_session(self):
        """Pin the units, because the row mixes them.

        `requests` and every cost are sums across the whole strategy;
        `peak_context` is what each individual session reaches.
        """
        c = analysis.compare_strategies(**self.BASE, ready_cost_each=2.0)
        short, long_ = c.short_runs, c.long_run

        # Productive work is identical; total requests are not, because the
        # split strategy orients five times.
        self.assertEqual(short.productive_requests, long_.productive_requests)
        self.assertEqual(short.requests_per_session, short.requests / 5)

        # Peak is per session, so the short ones stay small despite equal work.
        self.assertLess(short.peak_context, long_.peak_context / 2)

        # Orienting is charged once per session, so it scales with session count.
        single = analysis.compare_strategies(
            **{**self.BASE, "short_sessions": 1}, ready_cost_each=2.0
        ).short_runs
        self.assertAlmostEqual(short.ready_cost, 5 * single.ready_cost, places=6)

    def test_orientation_is_charged_once_per_session_in_money_and_requests(self):
        """Splitting pays to get up to speed every time.

        Orienting is measured (`observed_ready_tokens`), not derived from a
        token write: reading and searching costs ~2.5x what writing the same
        context would. Charging it as a single cold write understated the split
        strategy's cost by that factor, five times over.
        """
        c = analysis.compare_strategies(
            **self.BASE, ready_cost_each=2.02, ready_requests_each=19
        )
        self.assertAlmostEqual(c.long_run.ready_cost, 2.02, places=6)
        self.assertAlmostEqual(c.short_runs.ready_cost, 5 * 2.02, places=6)
        # And it consumes requests, so the strategies do different totals.
        self.assertEqual(c.long_run.ready_requests, 19)
        self.assertEqual(c.short_runs.ready_requests, 5 * 19)
        self.assertGreater(c.short_runs.requests, c.long_run.requests)

    def test_enough_sessions_makes_splitting_lose(self):
        """The user's theory: orientation paid N times eventually dominates."""
        kw = dict(ready_cost_each=2.02, ready_requests_each=19, long_restarts=3)
        few = analysis.compare_strategies(**{**self.BASE, "short_sessions": 2}, **kw)
        many = analysis.compare_strategies(**{**self.BASE, "short_sessions": 40}, **kw)
        self.assertLess(few.short_runs.total, few.long_run.total)
        self.assertGreater(many.short_runs.total, many.long_run.total)

    def test_ready_cost_does_not_scale_with_rework(self):
        """Rework is extra productive work, not extra orientation."""
        a = analysis.compare_strategies(**self.BASE, ready_cost_each=2.02)
        b = analysis.compare_strategies(**self.BASE, ready_cost_each=2.02, rework=2.0)
        self.assertAlmostEqual(a.short_runs.ready_cost, b.short_runs.ready_cost)
        self.assertGreater(b.short_runs.productive_requests, a.short_runs.productive_requests)

    def test_short_sessions_can_be_charged_restarts_too(self):
        """Restarts are wall-clock behaviour, not a property of the strategy.

        Charging only the long run silently favours it. Short sessions idle past
        the hour as well; each one that does rebuilds its own (smaller) context.
        """
        neither = analysis.compare_strategies(**self.BASE)
        both = analysis.compare_strategies(
            **self.BASE, long_restarts=3, short_restarts_each=1
        )
        self.assertGreater(both.long_run.restart_cost, 0)
        self.assertGreater(both.short_runs.restart_cost, 0)
        self.assertEqual(neither.short_runs.restart_cost, 0.0)
        # One restart per short session, each rebuilding that session's peak.
        rate = 5 / 1e6
        expected = 5 * both.short_runs.peak_context * rate * pricing.CACHE_WRITE_1H
        self.assertAlmostEqual(both.short_runs.restart_cost, expected, places=4)

    def test_output_cancels_at_equal_requests_but_not_under_rework(self):
        """Output is per-request and context-independent.

        Omitting it is harmless when both strategies do the same number of
        requests, but under rework the split strategy does more of them -- so
        leaving it out quietly favours splitting.
        """
        even = analysis.compare_strategies(**self.BASE, output_cost_per_request=0.05)
        self.assertAlmostEqual(
            even.long_run.output_cost, even.short_runs.output_cost, places=6
        )
        self.assertAlmostEqual(even.long_run.output_cost, 200 * 0.05, places=6)

        with_rework = analysis.compare_strategies(
            **self.BASE, rework=1.0, output_cost_per_request=0.05
        )
        self.assertGreater(
            with_rework.short_runs.output_cost, with_rework.long_run.output_cost
        )

    def test_output_lowers_the_breakeven(self):
        """Charging the split strategy for its extra requests narrows its margin."""
        without = analysis.compare_strategies(**self.BASE)
        with_out = analysis.compare_strategies(**self.BASE, output_cost_per_request=0.05)
        self.assertLess(with_out.breakeven_rework, without.breakeven_rework)

    def test_observed_output_cost_is_a_median_per_request(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_transcript(root, "s1", [
                _line(ts="2026-01-01T10:00:00Z", request_id="r0", message_id="m0",
                      output_tokens=1_000_000),
            ])
            reqs, _ = parser.load(root=root)
            sessions = session.build_sessions(reqs)
            # 1M output tokens on Opus 5 at $25/M.
            self.assertAlmostEqual(analysis.observed_output_cost(sessions), 25.0)

    def test_observed_restarts_reads_comparable_sessions(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            # One session of 4 requests with a >1h gap in the middle.
            _write_transcript(root, "s1", [
                _line(ts="2026-01-01T10:00:00Z", request_id="r0", message_id="m0",
                      session_id="S1", write_1h=50_000),
                _line(ts="2026-01-01T10:01:00Z", request_id="r1", message_id="m1",
                      session_id="S1", write_1h=500, read=50_000),
                _line(ts="2026-01-01T12:00:00Z", request_id="r2", message_id="m2",
                      session_id="S1", write_1h=50_500),
                _line(ts="2026-01-01T12:01:00Z", request_id="r3", message_id="m3",
                      session_id="S1", write_1h=500, read=50_500),
            ])
            reqs, _ = parser.load(root=root)
            sessions = session.build_sessions(reqs)
            self.assertEqual(analysis.observed_restarts(sessions, 4), 1)
            # No session of ~500 requests exists, so nothing to observe.
            self.assertEqual(analysis.observed_restarts(sessions, 500), 0)

    def test_restarts_only_charge_the_long_run(self):
        without = analysis.compare_strategies(
            "claude-opus-5", 29_000, 200, 600_000, 200_000, 5
        )
        with_restarts = analysis.compare_strategies(
            "claude-opus-5", 29_000, 200, 600_000, 200_000, 5, long_restarts=2
        )
        self.assertEqual(with_restarts.short_runs.total, without.short_runs.total)
        # Two restarts re-write the 600K peak at the 1h write rate.
        expected = 2 * 600_000 * (5.0 / 1_000_000) * pricing.CACHE_WRITE_1H
        self.assertAlmostEqual(
            with_restarts.long_run.total - without.long_run.total, expected
        )


class TestStartup(unittest.TestCase):
    """Startup context: a measurable prefix, and a ramp that never plateaus."""

    def _cold_session_lines(self, contexts: list[int], name: str) -> list[str]:
        lines = []
        for i, ctx in enumerate(contexts):
            # First request is a pure cold write; later ones read the prior
            # context back and write only the delta.
            read = contexts[i - 1] if i else 0
            lines.append(
                _line(
                    ts=f"2026-01-01T10:{i:02d}:00Z",
                    request_id=f"r{i}",
                    message_id=f"m{i}",
                    input_tokens=0,
                    write_1h=ctx - read,
                    read=read,
                    session_id=name,
                )
            )
        return lines

    def _sessions(self, contexts: list[int]):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        _write_transcript(root, "s1", self._cold_session_lines(contexts, "s1"))
        reqs, _ = parser.load(root=root)
        return session.build_sessions(reqs)

    def test_prefix_is_first_request_context(self):
        sessions = self._sessions([30_000, 40_000, 55_000, 61_000])
        self.assertEqual(analysis.startup_prefix_tokens(sessions), 30_000)

    def test_resumed_conversation_is_not_a_cold_session(self):
        """Reading back a whole prior context means the conversation was warm."""
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        _write_transcript(root, "warm", [
            _line(ts="2026-01-01T10:00:00Z", request_id="r0", message_id="m0",
                  write_1h=1_000, read=250_000),
        ])
        reqs, _ = parser.load(root=root)
        sessions = session.build_sessions(reqs)
        self.assertEqual(analysis.cold_sessions(sessions), [])
        self.assertEqual(analysis.startup_prefix_tokens(sessions), 0)

    def test_warm_shared_prefix_still_counts_as_cold(self):
        """The regression that hid whole projects from startup analysis.

        Half of all sessions open reading 15-20K: the shared system prompt and
        tool schemas left warm by a concurrent session. The conversation is
        still new, so these must count as cold starts.
        """
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        _write_transcript(root, "s1", [
            _line(ts="2026-01-01T10:00:00Z", request_id="r0", message_id="m0",
                  write_1h=14_000, read=16_000),
            _line(ts="2026-01-01T10:01:00Z", request_id="r1", message_id="m1",
                  write_1h=40_000, read=30_000, tools=("Edit",)),
        ])
        reqs, _ = parser.load(root=root)
        sessions = session.build_sessions(reqs)
        self.assertEqual(len(analysis.cold_sessions(sessions)), 1)
        point = analysis.observed_ready_tokens(sessions)
        self.assertIsNotNone(point)
        self.assertEqual(point.samples, 1)

    def test_ramp_is_monotonic_and_reports_pool_size(self):
        sessions = self._sessions([30_000, 40_000, 55_000, 61_000, 70_000])
        ramp = analysis.startup_ramp(sessions, indices=(1, 3, 5))
        self.assertEqual([i for i, _, _ in ramp], [1, 3, 5])
        medians = [m for _, m, _ in ramp]
        self.assertEqual(medians, sorted(medians))
        self.assertTrue(all(pool == 1 for _, _, pool in ramp))

    def test_ramp_skips_indices_beyond_session_length(self):
        sessions = self._sessions([30_000, 40_000])
        ramp = analysis.startup_ramp(sessions, indices=(1, 2, 10))
        self.assertEqual([i for i, _, _ in ramp], [1, 2])

    def test_ready_at_request_locates_threshold(self):
        sessions = self._sessions([30_000, 40_000, 55_000, 61_000])
        self.assertEqual(analysis.ready_at_request(sessions, 60_000), 4)
        self.assertEqual(analysis.ready_at_request(sessions, 30_000), 1)

    def test_ready_at_request_returns_none_when_unreached(self):
        sessions = self._sessions([30_000, 40_000])
        self.assertIsNone(analysis.ready_at_request(sessions, 500_000))

    def test_context_at_request(self):
        sessions = self._sessions([30_000, 40_000, 55_000])
        self.assertEqual(analysis.context_at_request(sessions, 2), 40_000)
        self.assertIsNone(analysis.context_at_request(sessions, 9))


class TestSubagentDiscovery(unittest.TestCase):
    """Nested subagent transcripts: found, attributed, and held apart."""

    def _root(self) -> Path:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        return Path(tmp.name)

    def _write(self, root: Path, rel: str, lines: list[str]) -> Path:
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return path

    def _corpus(self) -> Path:
        """A main transcript plus one subagent, sharing a session id."""
        root = self._root()
        proj = "-Users-me-src-demo"
        self._write(root, f"{proj}/S1.jsonl", [
            _line(ts="2026-01-01T10:00:00Z", request_id="r0", message_id="m0",
                  session_id="S1", write_1h=30_000),
            _line(ts="2026-01-01T10:05:00Z", request_id="r1", message_id="m1",
                  session_id="S1", write_1h=2_000, read=30_000),
        ])
        self._write(root, f"{proj}/S1/subagents/agent-abc.jsonl", [
            _line(ts="2026-01-01T10:01:00Z", request_id="r2", message_id="m2",
                  session_id="S1", write_1h=20_000),
        ])
        return root

    def test_nested_transcripts_are_discovered(self):
        """A single-level glob silently drops the majority of transcripts."""
        root = self._corpus()
        found = sorted(p.name for p in parser.iter_transcripts(root))
        self.assertEqual(found, ["S1.jsonl", "agent-abc.jsonl"])

    def test_subagent_requests_are_flagged_and_attributed(self):
        reqs, stats = parser.load(root=self._corpus())
        self.assertEqual(stats.subagent_files, 1)
        subs = [r for r in reqs if r.is_subagent]
        self.assertEqual(len(subs), 1)
        self.assertEqual(subs[0].agent_id, "agent-abc")

    def test_subagent_folds_into_parent_session_as_its_own_lane(self):
        reqs, _ = parser.load(root=self._corpus())
        sessions = session.build_sessions(reqs)
        self.assertEqual(len(sessions), 1)
        s = sessions[0]
        self.assertEqual(len(s.lanes), 2)
        self.assertEqual(len(s.main_lanes), 1)
        self.assertEqual(len(s.subagent_lanes), 1)
        self.assertAlmostEqual(s.cost, s.main_cost + s.subagent_cost)
        self.assertGreater(s.subagent_cost, 0)

    def test_hidden_backup_directories_are_skipped(self):
        """`.cwd-fix-backup-*/` holds byte-identical copies of live sessions."""
        root = self._corpus()
        proj = "-Users-me-src-demo"
        self._write(root, f"{proj}/.cwd-fix-backup-20260518/S1.jsonl", [
            _line(ts="2026-01-01T10:00:00Z", request_id="r0", message_id="m0",
                  session_id="S1", write_1h=30_000),
        ])
        names = [p.name for p in parser.iter_transcripts(root)]
        self.assertEqual(names.count("S1.jsonl"), 1)

    def test_duplicate_message_ids_across_files_counted_once(self):
        """Global dedup: the same request copied into a second file is not new spend."""
        root = self._root()
        proj = "-Users-me-src-demo"
        line = _line(ts="2026-01-01T10:00:00Z", request_id="r0", message_id="m0",
                     session_id="S1", write_1h=30_000)
        self._write(root, f"{proj}/S1.jsonl", [line])
        self._write(root, f"{proj}/S2.jsonl", [line])
        reqs, stats = parser.load(root=root)
        self.assertEqual(len(reqs), 1)
        self.assertEqual(stats.duplicate_lines, 1)

    def test_orphaned_session_detected(self):
        """Subagent files outliving their pruned parent transcript."""
        root = self._root()
        self._write(root, "-Users-me-src-demo/GONE/subagents/agent-x.jsonl", [
            _line(ts="2026-01-01T10:00:00Z", request_id="r0", message_id="m0",
                  session_id="GONE", write_1h=20_000),
        ])
        reqs, _ = parser.load(root=root)
        sessions = session.build_sessions(reqs)
        self.assertTrue(sessions[0].is_orphaned)
        cov = analysis.coverage_report(sessions)
        self.assertEqual(cov.orphaned, 1)
        self.assertEqual(cov.intact, 0)

    def test_session_survives_subagent_recording_a_different_cwd(self):
        """Grouping on session id alone; a moved subagent must not split it."""
        root = self._root()
        self._write(root, "-Users-me-src-demo/S1.jsonl", [
            _line(ts="2026-01-01T10:00:00Z", request_id="r0", message_id="m0",
                  session_id="S1", cwd="/Users/me/src/demo", write_1h=30_000),
        ])
        self._write(root, "-Users-me-src-demo/S1/subagents/agent-y.jsonl", [
            _line(ts="2026-01-01T10:01:00Z", request_id="r1", message_id="m1",
                  session_id="S1", cwd="/Users/me/src/elsewhere", write_1h=10_000),
        ])
        reqs, _ = parser.load(root=root)
        sessions = session.build_sessions(reqs)
        self.assertEqual(len(sessions), 1)
        # The label follows the main lane, not the wandering subagent.
        self.assertEqual(sessions[0].project, "src/demo")

    def test_subagents_excluded_from_cache_analyses_by_default(self):
        """A subagent's cold open is by design, not a lost cache."""
        root = self._root()
        # Main lane stays below the interesting-context threshold, so the
        # subagent is the only cold-start candidate in the corpus.
        self._write(root, "-Users-me-src-demo/S1.jsonl", [
            _line(ts="2026-01-01T10:00:00Z", request_id="r0", message_id="m0",
                  session_id="S1", write_1h=5_000),
        ])
        # Opens cold with a large context, two hours after the main lane.
        self._write(root, "-Users-me-src-demo/S1/subagents/agent-z.jsonl", [
            _line(ts="2026-01-01T12:00:00Z", request_id="r1", message_id="m1",
                  session_id="S1", write_1h=200_000),
            _line(ts="2026-01-01T12:01:00Z", request_id="r2", message_id="m2",
                  session_id="S1", write_1h=1_000, read=200_000),
        ])
        reqs, _ = parser.load(root=root)
        sessions = session.build_sessions(reqs)

        self.assertEqual(len(analysis.cold_starts(sessions)), 0)
        self.assertEqual(sessions[0].restarts, 0)
        self.assertEqual(sessions[0].restart_premium, 0.0)

        included = analysis.cold_starts(sessions, include_subagents=True)
        self.assertEqual(len(included), 1)
        self.assertTrue(included[0].request.is_subagent)

    def test_decay_never_pairs_requests_across_lanes(self):
        """Two lanes are separate caches; the interval between them is meaningless."""
        root = self._root()
        self._write(root, "-Users-me-src-demo/S1.jsonl", [
            _line(ts="2026-01-01T10:00:00Z", request_id="r0", message_id="m0",
                  session_id="S1", write_1h=100_000),
        ])
        self._write(root, "-Users-me-src-demo/S1/subagents/agent-w.jsonl", [
            _line(ts="2026-01-01T10:00:10Z", request_id="r1", message_id="m1",
                  session_id="S1", write_1h=100_000),
        ])
        reqs, _ = parser.load(root=root)
        sessions = session.build_sessions(reqs)
        # One request in each lane means no in-lane pair, so no samples at all.
        self.assertEqual(analysis.decay_curve(sessions, include_subagents=True), [])


class TestTtlEvidence(unittest.TestCase):
    """The empirical case for the cache TTL, assembled from the corpus."""

    def _sessions(self, lines: list[str], subagent_lines: list[str] | None = None):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        d = root / "-Users-me-src-demo"
        d.mkdir(parents=True)
        (d / "S1.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8")
        if subagent_lines:
            sd = d / "S1" / "subagents"
            sd.mkdir(parents=True)
            (sd / "agent-a.jsonl").write_text(
                "\n".join(subagent_lines) + "\n", encoding="utf-8"
            )
        reqs, _ = parser.load(root=root)
        return session.build_sessions(reqs)

    def test_requested_ttl_split_by_lane_kind(self):
        main = [_line(ts="2026-01-01T10:00:00Z", request_id="r0", message_id="m0",
                      session_id="S1", write_1h=30_000)]
        sub = [_line(ts="2026-01-01T10:01:00Z", request_id="r1", message_id="m1",
                     session_id="S1", write_5m=20_000)]
        e = analysis.ttl_evidence(self._sessions(main, sub))
        self.assertEqual(e.requested["main"]["1h"], 1)
        self.assertEqual(e.requested["main"]["5m"], 0)
        self.assertEqual(e.requested["subagent"]["5m"], 1)
        self.assertEqual(e.requested["subagent"]["1h"], 0)

    def test_boundary_separates_alive_from_dead(self):
        lines = [
            _line(ts="2026-01-01T10:00:00Z", request_id="r0", message_id="m0",
                  session_id="S1", write_1h=100_000),
            # +20 min: cache alive, small delta write
            _line(ts="2026-01-01T10:20:00Z", request_id="r1", message_id="m1",
                  session_id="S1", write_1h=1_000, read=100_000),
            # +61 min: cache gone, whole prompt re-written
            _line(ts="2026-01-01T11:21:00Z", request_id="r2", message_id="m2",
                  session_id="S1", write_1h=101_000, read=0),
        ]
        e = analysis.ttl_evidence(self._sessions(lines))
        buckets = {b.label: b for b in e.boundary}
        self.assertLess(buckets["0-30"].median_rewrite, 0.05)
        self.assertEqual(buckets["0-30"].dead_share, 0.0)
        self.assertGreater(buckets["60-62"].median_rewrite, 0.95)
        self.assertEqual(buckets["60-62"].dead_share, 1.0)

    def test_age_invariance_uses_lane_age_not_gap(self):
        """A long-lived lane touched often should show no decay with age."""
        lines = [_line(ts="2026-01-01T10:00:00Z", request_id="r0", message_id="m0",
                       session_id="S1", write_1h=100_000)]
        # Ten more requests at 20-minute spacing: lane ages past 3h, gaps stay short.
        for i in range(1, 11):
            hh, mm = divmod(20 * i, 60)
            lines.append(_line(ts=f"2026-01-01T{10 + hh:02d}:{mm:02d}:00Z",
                               request_id=f"r{i}", message_id=f"m{i}",
                               session_id="S1", write_1h=500, read=100_000))
        e = analysis.ttl_evidence(self._sessions(lines))
        labels = {b.label for b in e.age_invariance}
        self.assertIn("<1h", labels)
        self.assertIn("1-3h", labels)
        for b in e.age_invariance:
            self.assertLess(b.median_rewrite, 0.05, f"{b.label} should stay warm")
            self.assertEqual(b.dead_share, 0.0)

    def test_early_death_attributed_to_reported_cause(self):
        rec = json.loads(_line(ts="2026-01-01T10:10:00Z", request_id="r1",
                               message_id="m1", session_id="S1",
                               write_1h=100_000, read=0))
        rec["message"]["diagnostics"] = {"cache_miss_reason": {"type": "tools_changed"}}
        lines = [
            _line(ts="2026-01-01T10:00:00Z", request_id="r0", message_id="m0",
                  session_id="S1", write_1h=100_000),
            json.dumps(rec),
        ]
        e = analysis.ttl_evidence(self._sessions(lines))
        self.assertEqual(e.early_deaths, 1)
        self.assertEqual(e.early_causes.get("tools_changed"), 1)

    def test_early_death_without_diagnostics_is_labelled_unreported(self):
        lines = [
            _line(ts="2026-01-01T10:00:00Z", request_id="r0", message_id="m0",
                  session_id="S1", write_1h=100_000),
            _line(ts="2026-01-01T10:10:00Z", request_id="r1", message_id="m1",
                  session_id="S1", write_1h=100_000, read=0),
        ]
        e = analysis.ttl_evidence(self._sessions(lines))
        self.assertEqual(e.early_causes.get("not reported"), 1)


class TestReportedCacheMisses(unittest.TestCase):
    """`message.diagnostics.cache_miss_reason` -- the API's own miss reporting."""

    def _load(self, records: list[dict]):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        d = root / "-Users-me-src-demo"
        d.mkdir(parents=True)
        (d / "S1.jsonl").write_text(
            "\n".join(json.dumps(r) for r in records) + "\n", encoding="utf-8"
        )
        reqs, _ = parser.load(root=root)
        return reqs, session.build_sessions(reqs)

    def _rec(self, i: int, diagnostics=..., **usage) -> dict:
        rec = json.loads(_line(ts=f"2026-01-01T10:{i:02d}:00Z", request_id=f"r{i}",
                               message_id=f"m{i}", session_id="S1", **usage))
        if diagnostics is not ...:
            rec["message"]["diagnostics"] = diagnostics
        return rec

    def test_miss_reason_and_tokens_captured(self):
        reqs, _ = self._load([
            self._rec(0, diagnostics={"cache_miss_reason": {
                "type": "tools_changed", "cache_missed_input_tokens": 36_209}},
                write_1h=40_000),
        ])
        r = reqs[0]
        self.assertEqual(r.cache_miss_reason, "tools_changed")
        self.assertEqual(r.cache_missed_tokens, 36_209)
        self.assertTrue(r.has_diagnostics)

    def test_null_diagnostics_is_a_reported_hit_not_absence(self):
        """Distinguish 'reported, no miss' from 'version does not report'."""
        reqs, _ = self._load([
            self._rec(0, diagnostics=None, write_1h=1_000, read=50_000),
            self._rec(1),  # no diagnostics key at all
        ])
        reported, absent = reqs[0], reqs[1]
        self.assertTrue(reported.has_diagnostics)
        self.assertIsNone(reported.cache_miss_reason)
        self.assertFalse(absent.has_diagnostics)
        self.assertIsNone(absent.cache_miss_reason)

    def test_report_groups_by_reason_and_tracks_coverage(self):
        _, sessions = self._load([
            self._rec(0, diagnostics={"cache_miss_reason": {"type": "tools_changed"}},
                      write_1h=40_000),
            self._rec(1, diagnostics={"cache_miss_reason": {"type": "unavailable"}},
                      write_1h=10_000, read=30_000),
            self._rec(2, diagnostics=None, write_1h=1_000, read=40_000),
            self._rec(3),  # no diagnostics key
        ])
        rep = analysis.miss_report(sessions)
        self.assertEqual(rep.total_misses, 2)
        self.assertEqual(rep.requests_with_diagnostics, 3)
        self.assertEqual(rep.requests_total, 4)
        self.assertAlmostEqual(rep.coverage, 0.75)
        self.assertEqual({r.reason for r in rep.reasons}, {"tools_changed", "unavailable"})

    def test_self_inflicted_reasons_are_separated(self):
        _, sessions = self._load([
            self._rec(0, diagnostics={"cache_miss_reason": {"type": "system_changed"}},
                      write_1h=40_000),
            self._rec(1, diagnostics={"cache_miss_reason": {
                "type": "previous_message_not_found"}}, write_1h=40_000),
        ])
        rep = analysis.miss_report(sessions)
        by = {r.reason: r for r in rep.reasons}
        self.assertTrue(by["system_changed"].self_inflicted)
        self.assertFalse(by["previous_message_not_found"].self_inflicted)
        self.assertAlmostEqual(rep.self_inflicted_premium, by["system_changed"].premium)

    def test_reported_miss_and_inferred_cold_start_are_different_predicates(self):
        """A partial miss keeps most of the prefix, so it is not a cold rebuild."""
        reqs, _ = self._load([
            self._rec(0, diagnostics={"cache_miss_reason": {"type": "tools_changed"}},
                      write_1h=1_000, read=150_000),
        ])
        r = reqs[0]
        self.assertEqual(r.cache_miss_reason, "tools_changed")  # API: miss
        self.assertFalse(session.is_cold_start(r))              # heuristic: not cold


class TestCliFormatting(unittest.TestCase):
    """Table rendering: columns must line up and headings must be distinct."""

    def _point(self, samples: int = 10) -> analysis.ReadyPoint:
        return analysis.ReadyPoint(
            scope="demo", samples=samples, median_tokens=82_000,
            p25_tokens=55_000, p75_tokens=115_000, median_request_index=19,
            median_cost=2.02, p75_cost=3.53, median_rebuild_cost=0.79,
        )

    def test_ready_row_aligns_with_its_header(self):
        import io
        from contextlib import redirect_stdout

        width = 20
        buf = io.StringIO()
        with redirect_stdout(buf):
            cli._print_ready(self._point(), "all projects", width)
        row = buf.getvalue().rstrip("\n")
        self.assertEqual(len(row), width + len(cli.READY_HEADER))

    def test_ready_header_has_no_duplicate_labels(self):
        """Two columns both reading 'p75' is ambiguous -- cost vs tokens."""
        labels = [label for label, _ in cli.READY_COLUMNS]
        self.assertEqual(len(labels), len(set(labels)), labels)

    def test_ready_columns_fit_their_labels(self):
        for label, width in cli.READY_COLUMNS:
            self.assertLessEqual(len(label), width, f"{label!r} overflows its column")

    def test_low_sample_marker_stays_inside_the_table(self):
        import io
        from contextlib import redirect_stdout

        width = 20
        buf = io.StringIO()
        with redirect_stdout(buf):
            cli._print_ready(self._point(samples=2), "  tiny", width)
        row = buf.getvalue().rstrip("\n")
        self.assertTrue(row.endswith("2*"))
        self.assertEqual(len(row), width + len(cli.READY_HEADER))

    def test_money_keeps_the_sign_inside_its_field(self):
        # The bug: '$' appended after a full-width numeric column collides.
        self.assertEqual(cli._money(1245.34, 11), "  $1,245.34")
        self.assertEqual(len(cli._money(1245.34, 11)), 11)
        self.assertTrue(cli._money(0.5, 8).startswith(" "))


class TestReadyPoint(unittest.TestCase):
    """The observed 'ready to work' marker: context at the first Edit/Write."""

    def _load(self, transcripts: dict[str, list[str]]):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        for name, lines in transcripts.items():
            _write_transcript(root, name, lines)
        reqs, _ = parser.load(root=root)
        return session.build_sessions(reqs)

    def test_tool_names_are_captured(self):
        sessions = self._load({"s1": [
            _line(ts="2026-01-01T10:00:00Z", request_id="r0", message_id="m0",
                  tools=("Read", "Grep")),
        ]})
        req = sessions[0].requests[0]
        self.assertEqual(req.tools, ("Read", "Grep"))
        self.assertFalse(req.mutates)

    def test_mutating_tool_detected(self):
        sessions = self._load({"s1": [
            _line(ts="2026-01-01T10:00:00Z", request_id="r0", message_id="m0",
                  tools=("Bash", "Write")),
        ]})
        self.assertTrue(sessions[0].requests[0].mutates)

    def test_first_mutation_index_and_context(self):
        sessions = self._load({"s1": [
            _line(ts="2026-01-01T10:00:00Z", request_id="r0", message_id="m0",
                  write_1h=30_000, tools=("Read",)),
            _line(ts="2026-01-01T10:01:00Z", request_id="r1", message_id="m1",
                  write_1h=20_000, read=30_000, tools=("Grep",)),
            _line(ts="2026-01-01T10:02:00Z", request_id="r2", message_id="m2",
                  write_1h=30_000, read=50_000, tools=("Edit",)),
        ]})
        hit = sessions[0].first_mutation()
        self.assertIsNotNone(hit)
        index, req = hit
        self.assertEqual(index, 3)
        self.assertEqual(req.context_tokens, 80_000)

    def test_session_that_never_mutates_is_excluded(self):
        sessions = self._load({"s1": [
            _line(ts="2026-01-01T10:00:00Z", request_id="r0", message_id="m0",
                  write_1h=30_000, tools=("Read",)),
        ]})
        self.assertIsNone(sessions[0].first_mutation())
        self.assertIsNone(analysis.observed_ready_tokens(sessions))

    def test_observed_ready_tokens_reports_median_and_spread(self):
        transcripts = {}
        for i, ctx in enumerate((40_000, 60_000, 80_000)):
            transcripts[f"s{i}"] = [
                _line(ts="2026-01-01T10:00:00Z", request_id=f"a{i}", message_id=f"x{i}",
                      write_1h=10_000, session_id=f"s{i}", tools=("Read",)),
                _line(ts="2026-01-01T10:01:00Z", request_id=f"b{i}", message_id=f"y{i}",
                      write_1h=ctx - 10_000, read=10_000, session_id=f"s{i}",
                      tools=("Edit",)),
            ]
        point = analysis.observed_ready_tokens(self._load(transcripts))
        self.assertEqual(point.samples, 3)
        self.assertEqual(point.median_tokens, 60_000)
        self.assertEqual(point.median_request_index, 2)
        self.assertLessEqual(point.p25_tokens, point.median_tokens)
        self.assertGreaterEqual(point.p75_tokens, point.median_tokens)

    def test_resolve_prefers_override_then_observation(self):
        sessions = self._load({"s1": [
            _line(ts="2026-01-01T10:00:00Z", request_id="r0", message_id="m0",
                  write_1h=70_000, tools=("Edit",)),
        ]})
        tokens, origin = analysis.resolve_ready_tokens(sessions, override=99_000)
        self.assertEqual(tokens, 99_000)
        self.assertEqual(origin, "supplied")

        tokens, origin = analysis.resolve_ready_tokens(sessions)
        self.assertEqual(tokens, 70_000)
        self.assertIn("observed", origin)

    def test_resolve_falls_back_when_nothing_observed(self):
        sessions = self._load({"s1": [
            _line(ts="2026-01-01T10:00:00Z", request_id="r0", message_id="m0",
                  tools=("Read",)),
        ]})
        tokens, origin = analysis.resolve_ready_tokens(sessions)
        self.assertEqual(tokens, analysis.FALLBACK_READY_TOKENS)
        self.assertIn("fallback", origin)

    def test_low_sample_is_flagged_unreliable(self):
        sessions = self._load({"s1": [
            _line(ts="2026-01-01T10:00:00Z", request_id="r0", message_id="m0",
                  write_1h=70_000, tools=("Edit",)),
        ]})
        self.assertFalse(analysis.observed_ready_tokens(sessions).reliable)


class TestProjectLabel(unittest.TestCase):
    """Labels come from the transcript's `cwd`; the directory name is lossy."""

    DEMO = Path("/root/-Users-me-src-acme-acme-core/s.jsonl")

    def test_ambiguous_dash_encoding_resolved_by_cwd(self):
        """`-src-acme-acme-core` cannot be decoded; cwd says what it is."""
        self.assertEqual(
            parser.project_label("/Users/me/src/acme/acme-core", self.DEMO, depth=2),
            "acme/acme-core",
        )
        self.assertEqual(
            parser.project_label("/Users/me/src/acme-acme/core", self.DEMO, depth=2),
            "acme-acme/core",
        )

    def test_depth_controls_segments(self):
        cwd = "/Users/me/src/acme/acme-core"
        self.assertEqual(parser.project_label(cwd, self.DEMO, depth=1), "acme-core")
        self.assertEqual(parser.project_label(cwd, self.DEMO, depth=3), "src/acme/acme-core")

    def test_depth_beyond_path_length_is_safe(self):
        self.assertEqual(parser.project_label("/tmp", self.DEMO, depth=9), "tmp")

    def test_depth_is_clamped_to_at_least_one(self):
        self.assertEqual(
            parser.project_label("/Users/me/src/demo", self.DEMO, depth=0), "demo"
        )

    def test_falls_back_to_directory_name_without_cwd(self):
        label = parser.project_label(None, self.DEMO, depth=2)
        self.assertEqual(label, "Users-me-src-acme-acme-core")

    def test_sibling_projects_do_not_collide(self):
        """The regression: trailing-segment labels merged unrelated projects."""
        a = parser.project_label("/Users/me/src/acme/acme-core", self.DEMO, depth=2)
        b = parser.project_label(
            "/Users/me/src/beacon/beacon-core", self.DEMO, depth=2
        )
        self.assertNotEqual(a, b)


class TestByProject(unittest.TestCase):
    def _root_with(self, specs: list[tuple[str, str, dict]]) -> Path:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        # Distinct session ids and message ids per project: sessions group by
        # session id alone, and dedup is global across files.
        for i, (dirname, cwd, kwargs) in enumerate(specs):
            d = root / dirname
            d.mkdir(parents=True, exist_ok=True)
            (d / "s.jsonl").write_text(
                _line(ts="2026-01-01T10:00:00Z", request_id=f"r{i}", message_id=f"m{i}",
                      session_id=f"sess-{i}", cwd=cwd, **kwargs) + "\n",
                encoding="utf-8",
            )
        return root

    def test_groups_by_project_ordered_by_spend(self):
        root = self._root_with([
            ("-Users-me-src-small", "/Users/me/src/small", {"output_tokens": 10}),
            ("-Users-me-src-big", "/Users/me/src/big", {"output_tokens": 10_000}),
        ])
        reqs, _ = parser.load(root=root)
        groups = analysis.by_project(session.build_sessions(reqs))
        self.assertEqual(list(groups), ["src/big", "src/small"])

    def test_ready_tokens_computed_per_project(self):
        root = self._root_with([
            ("-a", "/Users/me/src/alpha", {"write_1h": 40_000, "tools": ("Edit",)}),
            ("-b", "/Users/me/src/beta", {"write_1h": 90_000, "tools": ("Edit",)}),
        ])
        reqs, _ = parser.load(root=root)
        points = analysis.ready_tokens_by_project(session.build_sessions(reqs))
        self.assertEqual(points["src/alpha"].tokens, 40_000)
        self.assertEqual(points["src/beta"].tokens, 90_000)

    def test_project_filter_matches_full_working_directory(self):
        root = self._root_with([
            ("-a", "/Users/me/src/acme/acme-core", {}),
            ("-b", "/Users/me/src/orchard/atlas", {}),
        ])
        reqs, _ = parser.load(root=root, project="acme")
        self.assertTrue(reqs)
        self.assertTrue(all(r.project == "acme/acme-core" for r in reqs))

        reqs, _ = parser.load(root=root, project="atlas")
        self.assertTrue(all(r.project == "orchard/atlas" for r in reqs))

    def test_load_honours_project_depth(self):
        root = self._root_with([("-a", "/Users/me/src/acme/acme-core", {})])
        reqs, _ = parser.load(root=root, project_depth=1)
        self.assertEqual(reqs[0].project, "acme-core")
        reqs, _ = parser.load(root=root, project_depth=3)
        self.assertEqual(reqs[0].project, "src/acme/acme-core")


class TestDecayCurve(unittest.TestCase):
    def test_curve_separates_warm_from_cold(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_transcript(root, "s1", [
                # warm: small delta write, big read
                _line(ts="2026-01-01T10:00:00Z", request_id="r1", message_id="m1",
                      write_1h=100_000, read=0),
                _line(ts="2026-01-01T10:00:30Z", request_id="r2", message_id="m2",
                      write_1h=1_000, read=100_000),
                # cold: >1h gap, whole context re-written
                _line(ts="2026-01-01T12:00:00Z", request_id="r3", message_id="m3",
                      write_1h=101_000, read=0),
            ])
            reqs, _ = parser.load(root=root)
            sessions = session.build_sessions(reqs)
            curve = {b.label: b for b in analysis.decay_curve(sessions)}
            self.assertLess(curve["<1m"].median_rewrite_fraction, 0.05)
            self.assertGreater(curve["1-2h"].median_rewrite_fraction, 0.95)


class TestTotals(unittest.TestCase):
    def test_cache_hit_rate(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_transcript(root, "s1", [
                _line(ts="2026-01-01T10:00:00Z", request_id="r1", message_id="m1",
                      input_tokens=0, write_1h=100, read=900),
            ])
            reqs, _ = parser.load(root=root)
            t = analysis.totals(session.build_sessions(reqs))
            self.assertAlmostEqual(t.cache_hit_rate, 0.9)


class TestExport(unittest.TestCase):
    """The measured token quantities in `csd export`, summed over all lanes."""

    def _root(self) -> Path:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        _write_transcript(root, "s1", [
            # A short output at a small context, then a long one at a large context.
            _line(ts="2026-01-01T10:00:00Z", request_id="r1", message_id="m1",
                  output_tokens=100, write_1h=10_000),
            _line(ts="2026-01-01T10:01:00Z", request_id="r2", message_id="m2",
                  input_tokens=500, output_tokens=1_000, write_5m=4_500, read=95_000,
                  speed="fast"),
        ])
        nested = root / "-Users-someone-src-demo" / "s1" / "subagents"
        nested.mkdir(parents=True)
        (nested / "agent-a.jsonl").write_text(
            _line(ts="2026-01-01T10:00:30Z", request_id="r3", message_id="m3",
                  output_tokens=50, write_5m=2_000) + "\n",
            encoding="utf-8",
        )
        return root

    def _export(self, root: Path) -> list[dict]:
        import io
        from contextlib import redirect_stdout

        buf = io.StringIO()
        with redirect_stdout(buf):
            cli.main(["--root", str(root), "export"])
        return json.loads(buf.getvalue())

    def test_context_split_is_summed_over_all_lanes(self):
        (rec,) = self._export(self._root())
        self.assertEqual(rec["requests"], 3)
        self.assertEqual(rec["input_tokens"], 500)
        self.assertEqual(rec["cache_write_5m"], 4_500 + 2_000)
        self.assertEqual(rec["cache_write_1h"], 10_000)
        self.assertEqual(rec["cache_read"], 95_000)
        self.assertEqual(rec["output_tokens"], 100 + 1_000 + 50)

    def test_context_split_accounts_for_every_prompt_token(self):
        reqs, _ = parser.load(root=self._root())
        (s,) = session.build_sessions(reqs)
        self.assertEqual(
            s.input_tokens + s.cache_write_5m + s.cache_write_1h + s.cache_read,
            sum(r.context_tokens for r in s.requests),
        )

    def test_output_context_product_is_summed_per_request(self):
        """The product of two averages is not the average of the product."""
        (rec,) = self._export(self._root())
        per_request = 100 * 10_000 + 1_000 * 100_000 + 50 * 2_000
        self.assertEqual(rec["output_context_product"], per_request)

        n = rec["requests"]
        context = rec["input_tokens"] + rec["cache_write_5m"] \
            + rec["cache_write_1h"] + rec["cache_read"]
        from_means = n * (rec["output_tokens"] / n) * (context / n)
        self.assertNotAlmostEqual(rec["output_context_product"], from_means, places=0)

    def test_output_context_product_excludes_generated_tokens(self):
        """The context is the prompt the request was sent with, not prompt plus output."""
        (rec,) = self._export(self._root())
        with_output = 100 * 10_100 + 1_000 * 101_000 + 50 * 2_050
        self.assertLess(rec["output_context_product"], with_output)
        self.assertEqual(rec["output_context_product"], 101_100_000)

    def test_old_transcript_cache_writes_go_to_1h(self):
        """Old transcripts report only the total of the cache writes.

        The parser gives that total to 1 hour, which is an inferred split. A
        session can mix the two formats, so the measured split of the new
        requests must stay as reported.
        """
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        _write_transcript(root, "s1", [
            # Old format: 3,000 written, TTL not reported.
            _line(ts="2026-01-01T10:00:00Z", request_id="r1", message_id="m1",
                  write_5m=3_000, split=False),
            # New format: the split is reported.
            _line(ts="2026-01-01T10:01:00Z", request_id="r2", message_id="m2",
                  write_5m=2_000, write_1h=1_000, read=3_000),
        ])
        (rec,) = self._export(root)
        self.assertEqual(rec["cache_write_1h"], 3_000 + 1_000)
        self.assertEqual(rec["cache_write_5m"], 2_000)
        self.assertEqual(
            rec["input_tokens"] + rec["cache_write_5m"]
            + rec["cache_write_1h"] + rec["cache_read"],
            3_000 + 3_000 + 3_000,
        )

    def test_fast_output_tokens_counts_only_fast_requests(self):
        (rec,) = self._export(self._root())
        self.assertEqual(rec["fast_output_tokens"], 1_000)
        self.assertEqual(rec["output_tokens"], 100 + 1_000 + 50)


class TestWarmLanes(unittest.TestCase):
    """Which lanes are still warm, and what going back to one costs."""

    def _lane(
        self, minutes_ago: float, *, session_id: str = "s1", read: int = 100_000
    ) -> analysis.WarmLane:
        now = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)
        req = parser.Request(
            timestamp=now - timedelta(minutes=minutes_ago),
            model="claude-opus-5",
            input_tokens=0,
            output_tokens=10,
            cache_write_5m=0,
            cache_write_1h=1_000,
            cache_read=read,
            fast=False,
            session_id=session_id,
            project="demo",
            transcript=Path(f"/tmp/{session_id}.jsonl"),
            request_id="r1",
            message_id="m1",
            is_sidechain=False,
            version="2.1.0",
        )
        sess = session.build_sessions([req])[0]
        return analysis.WarmLane(lane=sess.lanes[0], session=sess, now=now)

    def test_time_left_counts_from_the_last_request(self):
        lane = self._lane(minutes_ago=15)
        self.assertEqual(lane.idle, timedelta(minutes=15))
        self.assertEqual(lane.remaining, timedelta(minutes=45))
        self.assertTrue(lane.is_warm)

    def test_a_lane_past_the_ttl_is_not_warm(self):
        lane = self._lane(minutes_ago=75)
        self.assertFalse(lane.is_warm)
        self.assertEqual(lane.remaining, timedelta(minutes=-15))

    def test_resume_reads_the_context_back_and_cold_writes_it(self):
        """0.1x against 2.0x on the same tokens: the premium is the difference."""
        lane = self._lane(minutes_ago=5)
        context = lane.context  # 1,000 written + 100,000 read
        self.assertEqual(context, 101_000)
        base = context * 5.0 / 1_000_000  # Opus 5 input rate
        self.assertAlmostEqual(lane.resume_cost, base * 0.10)
        self.assertAlmostEqual(lane.rebuild_cost, base * 2.00)
        self.assertAlmostEqual(lane.premium, lane.rebuild_cost - lane.resume_cost)

    def _corpus(self, root: Path) -> list[session.Session]:
        """Three main lanes, last used 5, 40 and 90 minutes before noon."""
        for name, ts in (
            ("s1", "2026-01-01T11:55:00Z"),
            ("s2", "2026-01-01T11:20:00Z"),
            ("s3", "2026-01-01T10:30:00Z"),
        ):
            _write_transcript(root, name, [
                _line(ts=ts, request_id=f"r-{name}", message_id=f"m-{name}",
                      session_id=name, write_1h=1_000, read=100_000),
            ])
        reqs, _ = parser.load(root=root)
        return session.build_sessions(reqs)

    def test_window_holds_out_older_lanes_and_expiry_sorts_last(self):
        now = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)
        with tempfile.TemporaryDirectory() as tmp:
            sessions = self._corpus(Path(tmp))

            warm = analysis.warm_lanes(sessions, now)
            self.assertEqual([w.session.session_id for w in warm], ["s2", "s1"])
            self.assertTrue(all(w.is_warm for w in warm))

            wide = analysis.warm_lanes(sessions, now, window=timedelta(hours=3))
            # Warm first, the one that expires soonest at the top; then the
            # expired lanes, the most recent of them first.
            self.assertEqual([w.session.session_id for w in wide], ["s2", "s1", "s3"])
            self.assertFalse(wide[-1].is_warm)

    def test_subagent_lanes_are_held_out_by_default(self):
        now = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            proj = root / "-Users-someone-src-demo"
            (proj / "s1" / "subagents").mkdir(parents=True)
            (proj / "s1" / "subagents" / "agent-a.jsonl").write_text(
                _line(ts="2026-01-01T11:50:00Z", request_id="ra", message_id="ma",
                      session_id="s1", write_1h=20_000) + "\n",
                encoding="utf-8",
            )
            sessions = self._corpus(root)

            self.assertEqual(len(analysis.warm_lanes(sessions, now)), 2)
            folded = analysis.warm_lanes(sessions, now, include_subagents=True)
            self.assertEqual(len(folded), 3)
            self.assertTrue(any(w.lane.is_subagent for w in folded))


class TestRecentTranscripts(unittest.TestCase):
    """Selecting only the files a warm lane could have written."""

    def _root(self) -> Path:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        proj = root / "-Users-someone-src-demo"
        (proj / "s1" / "subagents").mkdir(parents=True)
        line = _line(ts="2026-01-01T10:00:00Z", request_id="r1", message_id="m1")
        for rel in ("s1.jsonl", "s1/subagents/agent-a.jsonl", "old.jsonl"):
            (proj / rel).write_text(line + "\n", encoding="utf-8")
        return root

    def _age(self, path: Path, minutes: float) -> None:
        import os
        stamp = datetime.now(timezone.utc).timestamp() - minutes * 60
        os.utime(path, (stamp, stamp))

    def test_since_keeps_only_recently_written_files(self):
        root = self._root()
        proj = root / "-Users-someone-src-demo"
        self._age(proj / "old.jsonl", 240)
        self._age(proj / "s1" / "subagents" / "agent-a.jsonl", 240)
        since = datetime.now(timezone.utc) - timedelta(hours=1)
        found = sorted(p.name for p in parser.iter_transcripts(root, since=since))
        self.assertEqual(found, ["s1.jsonl"])

    def test_a_session_keeps_the_lanes_it_wrote_earlier(self):
        """A session's subagents ran before it, so mtime alone loses their cost."""
        root = self._root()
        proj = root / "-Users-someone-src-demo"
        found = parser.session_files([proj / "s1.jsonl"], root)
        self.assertEqual(
            sorted(p.name for p in found), ["agent-a.jsonl", "s1.jsonl"]
        )

    def test_a_subagent_lane_pulls_in_its_main_transcript(self):
        root = self._root()
        proj = root / "-Users-someone-src-demo"
        found = parser.session_files([proj / "s1" / "subagents" / "agent-a.jsonl"], root)
        self.assertIn(proj / "s1.jsonl", found)

    def test_session_dir_is_the_same_for_both_kinds_of_lane(self):
        root = self._root()
        proj = root / "-Users-someone-src-demo"
        self.assertEqual(
            parser.session_dir(proj / "s1.jsonl", root),
            parser.session_dir(proj / "s1" / "subagents" / "agent-a.jsonl", root),
        )


class TestSessionTitle(unittest.TestCase):
    """The name a transcript records for its session."""

    def _write(self, lines: list[str]) -> Path:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        path = Path(tmp.name) / "s1.jsonl"
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return path

    def test_the_last_title_wins(self):
        """The client rewrites the title as the work changes."""
        path = self._write([
            json.dumps({"type": "ai-title", "aiTitle": "First idea"}),
            json.dumps({"type": "last-prompt", "lastPrompt": "do the thing"}),
            json.dumps({"type": "ai-title", "aiTitle": "What it became"}),
        ])
        self.assertEqual(parser.session_title(path), "What it became")

    def test_the_last_prompt_names_a_session_that_has_no_title(self):
        path = self._write([
            json.dumps({"type": "last-prompt", "lastPrompt": "do the\n  thing"}),
        ])
        self.assertEqual(parser.session_title(path), "do the thing")

    def test_no_title_and_no_prompt_gives_none(self):
        path = self._write([json.dumps({"type": "user", "message": {}})])
        self.assertIsNone(parser.session_title(path))


class TestWarmCommand(unittest.TestCase):
    """End to end: the table renders and names the operator's own lane."""

    def _run(self, argv: list[str]) -> str:
        import io
        from contextlib import redirect_stdout

        buf = io.StringIO()
        with redirect_stdout(buf):
            cli.main(argv)
        return buf.getvalue()

    def _root(self, minutes_ago: float = 10) -> Path:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        when = datetime.now(timezone.utc) - timedelta(minutes=minutes_ago)
        _write_transcript(root, "s1", [
            _line(ts=when.strftime("%Y-%m-%dT%H:%M:%SZ"), request_id="r1",
                  message_id="m1", session_id="s1", write_1h=1_000, read=100_000),
            json.dumps({"type": "ai-title", "aiTitle": "Rename the widget"}),
        ])
        return root

    def test_a_warm_lane_is_listed_with_its_title(self):
        out = self._run(["--root", str(self._root()), "warm"])
        self.assertIn("Rename the widget", out)
        self.assertIn("src/demo", out)
        # 60 minute TTL, idle 10 minutes. Part minutes are cut, not rounded up,
        # so the time left is never overstated.
        self.assertIn("49m", out)
        self.assertIn("1 lane(s) still warm", out)

    def test_the_current_session_is_marked(self):
        from unittest import mock

        env = {cli.CURRENT_SESSION_ENV: "s1"}
        with mock.patch.dict("os.environ", env):
            out = self._run(["--root", str(self._root()), "warm"])
        self.assertIn("s1*", out)
        self.assertIn("the session that this command is running in", out)

    def test_a_subagent_lane_names_itself(self):
        """Its session title would repeat the row above it."""
        root = self._root()
        nested = root / "-Users-someone-src-demo" / "s1" / "subagents"
        nested.mkdir(parents=True)
        when = datetime.now(timezone.utc) - timedelta(minutes=12)
        (nested / "agent-a.jsonl").write_text(
            _line(ts=when.strftime("%Y-%m-%dT%H:%M:%SZ"), request_id="r2",
                  message_id="m2", session_id="s1", write_1h=20_000) + "\n",
            encoding="utf-8",
        )
        out = self._run(["--root", str(root), "warm", "--include-subagents"])
        self.assertIn("subagent agent-a", out)
        self.assertEqual(out.count("Rename the widget"), 1)

    def test_a_lane_outside_the_window_is_not_shown(self):
        out = self._run(["--root", str(self._root(minutes_ago=200)), "warm"])
        self.assertIn("No lane was used", out)

    def test_a_wider_window_shows_the_expired_lane(self):
        out = self._run(
            ["--root", str(self._root(minutes_ago=200)), "warm", "--window", "300"]
        )
        self.assertIn("expired", out)
        self.assertNotIn("still warm", out)


if __name__ == "__main__":
    unittest.main()
