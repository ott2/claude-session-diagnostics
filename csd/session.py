"""Group requests into sessions, lanes and warm segments.

Three levels, each meaning something different:

  Session  one piece of work: a main conversation plus every subagent it spawned
  Lane     one transcript, and therefore one independent prompt cache
  Segment  a run of requests within a lane during which that cache stayed warm

Cache behaviour is only meaningful *within* a lane. Lanes run concurrently and
cache independently, so a gap measured across two of them means nothing.

Main and subagent lanes behave so differently that mixing them corrupts the
analysis. Measured over this corpus:

                     main      subagent
  requests/lane        73             9
  duration          280 min      0.9 min
  gaps over the TTL   1.53%        0.09%

A subagent is briefed, works for about a minute, and exits. It starts cold every
time by design, so counting that as a restart premium is wrong, and its sub-minute
gaps would swamp the decay curve. Cache analyses therefore default to main lanes
and treat subagents separately, while cost totals always include both.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path

from .parser import Request

# Claude Code writes 1-hour-TTL cache entries almost exclusively, so an hour of
# silence is the point at which context must be rebuilt from scratch.
CACHE_TTL = timedelta(hours=1)

# A request is treated as a cold read if it recovered less than this fraction of
# its prompt from cache. Used to detect cold starts from usage alone, without
# relying on wall-clock gaps.
COLD_READ_FRACTION = 0.5

# Below this prompt size, a "cold start" is not economically interesting -- it
# is a fresh short conversation, not a lost 200K context.
MIN_INTERESTING_CONTEXT = 20_000

# A session counts as a cold start if its opening request did not resume a prior
# *conversation*.
#
# The threshold is deliberately well above zero. Roughly half of all sessions
# open by reading 15-20K from cache: that is the shared static prefix (system
# prompt and tool schemas) left warm by another concurrent session, not this
# conversation's own history. Treating those as "warm" excludes whole projects
# from startup analysis -- the busiest ones, since they are the most likely to
# have a sibling session running.
#
# A genuinely resumed conversation would read back its entire prior context,
# typically 100K+. Anything below this bound is a fresh conversation.
COLD_OPENING_READ = 50_000


@dataclass
class Segment:
    """A run of requests during which the cache stayed warm."""

    requests: list[Request]

    @property
    def start(self) -> datetime:
        return self.requests[0].timestamp

    @property
    def end(self) -> datetime:
        return self.requests[-1].timestamp

    @property
    def duration(self) -> timedelta:
        return self.end - self.start

    @property
    def cost(self) -> float:
        return sum(r.cost for r in self.requests)

    @property
    def peak_context(self) -> int:
        return max((r.context_tokens for r in self.requests), default=0)

    @property
    def startup_cost(self) -> float:
        """Cost of the first request -- what this segment paid to get going."""
        return self.requests[0].cost if self.requests else 0.0

    @property
    def startup_premium(self) -> float:
        """Cold-cache premium on the first request of the segment."""
        return self.requests[0].cold_premium if self.requests else 0.0


@dataclass
class Lane:
    """One transcript: a single conversation with its own prompt cache.

    A session's main lane is one lane; every subagent it spawns is another.
    Lanes run concurrently and cache independently, so cache decay and segment
    boundaries are only meaningful within a lane, never across them.
    """

    transcript: Path
    agent_id: str | None
    requests: list[Request]
    segments: list[Segment]

    @property
    def is_subagent(self) -> bool:
        return self.agent_id is not None

    @property
    def start(self) -> datetime:
        return self.requests[0].timestamp

    @property
    def end(self) -> datetime:
        return self.requests[-1].timestamp

    @property
    def duration(self) -> timedelta:
        return self.end - self.start

    @property
    def cost(self) -> float:
        return sum(r.cost for r in self.requests)

    @property
    def peak_context(self) -> int:
        return max((r.context_tokens for r in self.requests), default=0)

    @property
    def restarts(self) -> int:
        return max(0, len(self.segments) - 1)

    @property
    def restart_premium(self) -> float:
        """Premium paid rebuilding this lane's cache after it expired.

        The opening segment is excluded: establishing context the first time is
        the work, not a premium. For a subagent that is the whole story, which is
        why subagent lanes contribute almost nothing here.
        """
        return sum(s.startup_premium for s in self.segments[1:])

    @property
    def started_cold(self) -> bool:
        return bool(self.requests) and self.requests[0].cache_read < COLD_OPENING_READ


@dataclass
class Session:
    """One session: its main lane plus every subagent it spawned.

    Subagent transcripts record the parent's `sessionId`, so they group here
    naturally and their cost counts toward the session that caused it.
    """

    session_id: str
    project: str
    requests: list[Request]
    segments: list[Segment]
    lanes: list[Lane] = field(default_factory=list)

    @property
    def main_lanes(self) -> list[Lane]:
        return [lane for lane in self.lanes if not lane.is_subagent]

    @property
    def subagent_lanes(self) -> list[Lane]:
        return [lane for lane in self.lanes if lane.is_subagent]

    @property
    def subagent_cost(self) -> float:
        return sum(lane.cost for lane in self.subagent_lanes)

    @property
    def subagent_share(self) -> float:
        total = self.cost
        return self.subagent_cost / total if total else 0.0

    @property
    def main_requests(self) -> list[Request]:
        return [r for lane in self.main_lanes for r in lane.requests]

    @property
    def is_orphaned(self) -> bool:
        """True if only subagent transcripts survive for this session.

        Claude Code prunes old top-level transcripts but leaves the nested
        `subagents/` directories behind, so an orphan is the residue of a
        session whose main lane is no longer on disk. Its main-lane spend is
        unrecoverable, which makes any total spanning that period a floor rather
        than an actual figure.
        """
        return not self.main_lanes

    @property
    def start(self) -> datetime:
        return self.requests[0].timestamp

    @property
    def end(self) -> datetime:
        return self.requests[-1].timestamp

    @property
    def wall_duration(self) -> timedelta:
        return self.end - self.start

    @property
    def active_duration(self) -> timedelta:
        """Main-lane wall time excluding idle gaps longer than the cache TTL.

        Subagent lanes are excluded because they run concurrently with the main
        lane; adding their durations would double-count the same wall time.
        """
        return sum(
            (s.duration for lane in self.main_lanes for s in lane.segments), timedelta()
        )

    @property
    def cost(self) -> float:
        """Total spend, main lane and subagents together."""
        return sum(r.cost for r in self.requests)

    @property
    def main_cost(self) -> float:
        return sum(lane.cost for lane in self.main_lanes)

    @property
    def peak_context(self) -> int:
        """Largest main-lane prompt. Subagents carry their own smaller contexts."""
        return max((r.context_tokens for r in self.main_requests), default=0)

    @property
    def output_tokens(self) -> int:
        return sum(r.output_tokens for r in self.requests)

    @property
    def fast_output_tokens(self) -> int:
        """Output tokens of the requests that the transcript marks as fast mode."""
        return sum(r.output_tokens for r in self.requests if r.fast)

    @property
    def input_tokens(self) -> int:
        return sum(r.input_tokens for r in self.requests)

    @property
    def cache_write_5m(self) -> int:
        return sum(r.cache_write_5m for r in self.requests)

    @property
    def cache_write_1h(self) -> int:
        return sum(r.cache_write_1h for r in self.requests)

    @property
    def cache_read(self) -> int:
        return sum(r.cache_read for r in self.requests)

    @property
    def output_context_product(self) -> int:
        """Sum over requests of output tokens times the context sent.

        Summed per request: the product of two averages is not the average of
        the product. The context is the prompt the request was sent with; the
        tokens that the request generates are not included.
        """
        return sum(r.output_tokens * r.context_tokens for r in self.requests)

    @property
    def restarts(self) -> int:
        """Main-lane cache expiries.

        Counted per lane, since each lane caches independently. Subagents are
        excluded: they start cold by design and finish inside a minute, so their
        opening write is the work rather than a lost cache.
        """
        return sum(lane.restarts for lane in self.main_lanes)

    @property
    def restart_premium(self) -> float:
        """USD spent re-writing main-lane context a warm cache would have served."""
        return sum(lane.restart_premium for lane in self.main_lanes)

    @property
    def models(self) -> set[str]:
        return {r.model for r in self.requests if r.model}

    @property
    def started_cold(self) -> bool:
        """True if the main conversation did not resume a prior one."""
        return any(lane.started_cold for lane in self.main_lanes)

    def first_mutation(self) -> tuple[int, Request] | None:
        """The main lane's first workspace change, as (1-based index, request).

        The observable boundary between orienting and working: everything before
        it is reading, searching and running commands to build up context.
        Subagent lanes are excluded -- a subagent arrives already briefed, so its
        first edit says nothing about how long orientation takes.
        """
        for i, req in enumerate(self.main_requests, start=1):
            if req.mutates:
                return i, req
        return None


def split_segments(requests: list[Request], ttl: timedelta = CACHE_TTL) -> list[Segment]:
    """Split an ordered request list wherever the gap exceeds the cache TTL."""
    if not requests:
        return []
    segments: list[Segment] = []
    current = [requests[0]]
    for prev, req in zip(requests, requests[1:]):
        if req.timestamp - prev.timestamp > ttl:
            segments.append(Segment(current))
            current = [req]
        else:
            current.append(req)
    segments.append(Segment(current))
    return segments


def build_lanes(requests: list[Request], ttl: timedelta = CACHE_TTL) -> list[Lane]:
    """Group requests by transcript into Lanes, each with its own segments."""
    grouped: dict[str, list[Request]] = defaultdict(list)
    for req in requests:
        grouped[str(req.transcript)].append(req)

    lanes: list[Lane] = []
    for reqs in grouped.values():
        reqs.sort(key=lambda r: r.timestamp)
        lanes.append(
            Lane(
                transcript=reqs[0].transcript,
                agent_id=reqs[0].agent_id,
                requests=reqs,
                segments=split_segments(reqs, ttl),
            )
        )
    lanes.sort(key=lambda lane: lane.start)
    return lanes


def build_sessions(requests: list[Request], ttl: timedelta = CACHE_TTL) -> list[Session]:
    """Group requests into Sessions, ordered by start time.

    Grouping is by session id, not by transcript: a subagent transcript records
    the parent's session id, so its spend lands on the session that caused it.
    Within a session, requests are split into lanes -- one per transcript --
    because each transcript is a separate prompt cache.
    """
    # Keyed on session id alone. Session ids are uuids, so they do not collide
    # across projects, and a subagent occasionally records a different cwd than
    # its parent -- including the project in the key would split those sessions
    # in two.
    grouped: dict[str, list[Request]] = defaultdict(list)
    for req in requests:
        grouped[req.session_id].append(req)

    sessions: list[Session] = []
    for session_id, reqs in grouped.items():
        reqs.sort(key=lambda r: r.timestamp)
        lanes = build_lanes(reqs, ttl)
        # Prefer the main lane's project label; a subagent may have moved.
        main = next((lane for lane in lanes if not lane.is_subagent), None)
        project = (main or lanes[0]).requests[0].project
        sessions.append(
            Session(
                session_id=session_id,
                project=project,
                requests=reqs,
                segments=[s for lane in lanes for s in lane.segments],
                lanes=lanes,
            )
        )
    sessions.sort(key=lambda s: s.start)
    return sessions


def is_cold_start(req: Request, min_context: int = MIN_INTERESTING_CONTEXT) -> bool:
    """True if this request rebuilt a substantial context from a cold cache.

    Detected from usage alone: a large prompt of which little came from cache.
    """
    ctx = req.context_tokens
    if ctx < min_context:
        return False
    return (req.cache_read / ctx) < COLD_READ_FRACTION
