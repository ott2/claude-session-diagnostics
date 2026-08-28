"""Parse Claude Code session transcripts into billed API requests.

A session transcript is a JSONL file under ~/.claude/projects/<project>/<uuid>.jsonl.

The single most important behaviour here is deduplication. A transcript writes
one `assistant` line per content block, and every one of those lines carries a
*complete copy* of the same `usage` object. Summing usage per line overstates
cost by roughly 2-3x. Requests are therefore keyed on (requestId, message.id)
and counted once.
"""

from __future__ import annotations

import json
import os
from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from . import pricing

DEFAULT_ROOT = Path.home() / ".claude" / "projects"

# Tools that change the workspace. The first of these in a session marks the
# point where orientation gave way to productive work -- the only observable
# "ready to work" signal in a transcript.
MUTATING_TOOLS = frozenset({"Edit", "Write", "NotebookEdit"})


@dataclass(frozen=True)
class Request:
    """One billed API request, deduplicated."""

    timestamp: datetime
    model: str | None
    input_tokens: int
    output_tokens: int
    cache_write_5m: int
    cache_write_1h: int
    cache_read: int
    fast: bool
    session_id: str
    project: str
    transcript: Path
    request_id: str | None
    message_id: str | None
    is_sidechain: bool
    version: str | None
    tools: tuple[str, ...] = ()
    cwd: str | None = None
    agent_id: str | None = None
    # Reported by the API when a cache lookup failed, and why. Present only on
    # newer Claude Code versions; None means either no miss or no reporting.
    # See `has_diagnostics` to tell those apart.
    cache_miss_reason: str | None = None
    cache_missed_tokens: int = 0
    has_diagnostics: bool = False

    @property
    def is_subagent(self) -> bool:
        return self.agent_id is not None

    @property
    def mutates(self) -> bool:
        """True if this request called a tool that changes the workspace."""
        return any(t in MUTATING_TOOLS for t in self.tools)

    @property
    def cache_write(self) -> int:
        return self.cache_write_5m + self.cache_write_1h

    @property
    def context_tokens(self) -> int:
        """Total prompt size: everything the model read on this request."""
        return self.input_tokens + self.cache_write + self.cache_read

    @property
    def cost(self) -> float:
        return pricing.cost(
            self.model,
            input_tokens=self.input_tokens,
            output_tokens=self.output_tokens,
            cache_write_5m=self.cache_write_5m,
            cache_write_1h=self.cache_write_1h,
            cache_read=self.cache_read,
            fast=self.fast,
            at=self.timestamp,
        )

    @property
    def cold_premium(self) -> float:
        """USD paid above a warm-cache read for this request's cache writes."""
        return pricing.cold_start_premium(
            self.model, self.cache_write_1h, self.cache_write_5m, at=self.timestamp
        )

    @property
    def priced(self) -> bool:
        return pricing.price_for(self.model) is not None


@dataclass
class ParseStats:
    """Counters describing what the parser did and what it dropped."""

    files: int = 0
    lines: int = 0
    assistant_lines: int = 0
    requests: int = 0
    duplicate_lines: int = 0
    malformed_lines: int = 0
    missing_usage: int = 0
    synthetic: int = 0
    missing_cwd: int = 0
    subagent_files: int = 0
    unpriced_models: set[str] = field(default_factory=set)

    @property
    def duplication_factor(self) -> float:
        """assistant lines per real request; 1.0 means no duplication."""
        return self.assistant_lines / self.requests if self.requests else 0.0


def _parse_ts(raw: str | None) -> datetime | None:
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw)
    except ValueError:
        return None


# How many trailing path segments to use as a project label. One segment is
# often ambiguous across sibling repos ("core", "v1", "frontend"); two restores
# the owning group.
DEFAULT_PROJECT_DEPTH = 2


def project_label(
    cwd: str | None,
    transcript: Path,
    depth: int = DEFAULT_PROJECT_DEPTH,
    project_dir: str | None = None,
) -> str:
    """Human-readable project label, preferring the transcript's own `cwd`.

    ~/.claude/projects encodes the working directory by replacing '/' with '-',
    which is lossy and cannot be decoded: `-src-acme-acme-core` is equally
    consistent with `src/acme/acme-core` and `src/acme-acme/core`. Records
    carry the real path in `cwd`, so use that whenever it is present and fall
    back to the encoded directory name only when it is not.
    """
    depth = max(1, depth)
    if cwd:
        parts = [p for p in Path(cwd).parts if p not in ("/", "")]
        if parts:
            return "/".join(parts[-depth:])
    # No cwd: the encoded name is all we have. Strip the leading separator and
    # keep it whole rather than splitting on '-' and guessing wrongly. For a
    # nested subagent transcript the parent directory is a session uuid, so the
    # caller supplies the owning project directory.
    fallback = project_dir or transcript.parent.name
    return fallback.lstrip("-") or fallback


def _first_cwd(path: Path) -> str | None:
    """Read the working directory from the first record that carries one."""
    try:
        with path.open("r", encoding="utf-8", errors="replace") as handle:
            for line in handle:
                if '"cwd"' not in line:
                    continue
                try:
                    rec = json.loads(line)
                except (json.JSONDecodeError, ValueError):
                    continue
                cwd = rec.get("cwd")
                if isinstance(cwd, str) and cwd:
                    return cwd
    except OSError:
        return None
    return None


def _string_field(line: str, key: str) -> str | None:
    """Read one string field from a JSON line, or None if it is not usable."""
    try:
        rec = json.loads(line)
    except (json.JSONDecodeError, ValueError):
        return None
    value = rec.get(key) if isinstance(rec, dict) else None
    return value if isinstance(value, str) and value.strip() else None


def transcript_project_dir(path: Path, root: Path) -> str:
    """The project directory a transcript belongs to, however deeply nested."""
    try:
        return path.relative_to(root).parts[0]
    except ValueError:
        return path.parent.name


def agent_id(path: Path) -> str | None:
    """Subagent identifier for a nested transcript, or None for a main lane.

    Subagent work lives at
    `<project>/<session-uuid>/subagents/agent-<id>.jsonl`, and workflow agents
    one level deeper under `subagents/workflows/<wf-id>/`. Both are real billed
    traffic belonging to the parent session.
    """
    stem = path.stem
    return stem if "subagents" in path.parts else None


def iter_transcripts(
    root: Path | str = DEFAULT_ROOT,
    project: str | None = None,
    since: datetime | None = None,
) -> Iterator[Path]:
    """Yield every transcript under `root`, at any depth.

    Subagent transcripts are nested inside a directory named after their parent
    session, so a single-level glob silently drops them -- in practice the large
    majority of files and a sixth of all spend.

    Hidden directories are skipped. Claude Code writes backup copies of whole
    transcripts into `.cwd-fix-backup-*/`, and those are byte-identical
    duplicates of live sessions; including them double-counts real requests.

    `since` keeps only the files modified at or after that moment. A file is
    written when its records are written, so its modification time is never
    earlier than its last record: the filter cannot discard a lane that is still
    in use. It can keep a file whose last *request* is older, because a user
    message or a mode change also writes a line, so the caller must still
    compare the timestamps it parses.
    """
    root = Path(root).expanduser()
    if not root.exists():
        return
    needle = project.lower() if project else None
    cutoff = since.timestamp() if since is not None else None
    for path in sorted(root.rglob("*.jsonl")):
        rel = path.relative_to(root)
        if any(part.startswith(".") for part in rel.parts):
            continue
        if cutoff is not None:
            try:
                if path.stat().st_mtime < cutoff:
                    continue
            except OSError:
                continue
        if needle:
            cwd = _first_cwd(path)
            haystack = (cwd or transcript_project_dir(path, root)).lower()
            if needle not in haystack:
                continue
        yield path


def session_dir(path: Path, root: Path | str = DEFAULT_ROOT) -> Path | None:
    """The directory that holds a session's subagent lanes.

    It is `<project>/<session-uuid>/`, whether `path` is the main transcript
    `<project>/<session-uuid>.jsonl` or a lane below `subagents/`.
    """
    root = Path(root).expanduser()
    try:
        parts = path.relative_to(root).parts
    except ValueError:
        return None
    if "subagents" in parts:
        parts = parts[: parts.index("subagents")]
    else:
        parts = parts[:-1] + (path.stem,)
    return root.joinpath(*parts) if parts else None


def session_files(
    paths: Iterable[Path], root: Path | str = DEFAULT_ROOT
) -> list[Path]:
    """Add the rest of each session to a selection of transcripts.

    A main transcript gets the subagent lanes below its session directory, and a
    subagent lane gets its main transcript. A selection made by modification
    time holds only the files that a session wrote recently, so without this
    step the cost of a session includes only part of the work it did.
    """
    root = Path(root).expanduser()
    # dict, not set: the order of the files stays stable, which keeps the
    # deduplication deterministic when two files hold the same records.
    out: dict[Path, None] = {}
    for path in paths:
        path = Path(path)
        out.setdefault(path, None)
        directory = session_dir(path, root)
        if directory is None:
            continue
        main = directory.parent / f"{directory.name}.jsonl"
        if main.is_file():
            out.setdefault(main, None)
        if directory.is_dir():
            for nested in sorted(directory.rglob("*.jsonl")):
                rel = nested.relative_to(directory)
                if any(part.startswith(".") for part in rel.parts):
                    continue
                out.setdefault(nested, None)
    return list(out)


def session_title(path: Path) -> str | None:
    """The name of the session that wrote this transcript, or None.

    Claude Code writes an `ai-title` record and rewrites it as the work changes,
    so the last one is the current name. Approximately one transcript in five
    has no title. Most of those carry a `last-prompt` record, which names the
    session well enough to recognise it.
    """
    title = prompt = None
    try:
        handle = path.open("r", encoding="utf-8", errors="replace")
    except OSError:
        return None
    with handle:
        for line in handle:
            if '"aiTitle"' in line:
                title = _string_field(line, "aiTitle") or title
            elif '"lastPrompt"' in line:
                prompt = _string_field(line, "lastPrompt") or prompt
    text = title or prompt
    return " ".join(text.split()) if text else None


def parse_transcript(
    path: Path,
    stats: ParseStats | None = None,
    project_depth: int = DEFAULT_PROJECT_DEPTH,
    project_dir: str | None = None,
    seen: set[tuple[str | None, str | None]] | None = None,
) -> list[Request]:
    """Parse one transcript into deduplicated requests, ordered by timestamp.

    Pass a shared `seen` set across transcripts to deduplicate globally rather
    than per file. Message ids are unique per API response, so a repeat across
    two files means one of them is a copy, not new spend.
    """
    stats = stats if stats is not None else ParseStats()
    stats.files += 1
    cwd = _first_cwd(path)
    if cwd is None:
        stats.missing_cwd += 1
    proj = project_label(cwd, path, project_depth, project_dir)
    agent = agent_id(path)
    if agent:
        stats.subagent_files += 1
    seen = seen if seen is not None else set()
    out: list[Request] = []

    try:
        handle = path.open("r", encoding="utf-8", errors="replace")
    except OSError:
        return out

    with handle:
        for line in handle:
            stats.lines += 1
            # Cheap prefilter: most lines are user messages / attachments / metadata.
            if '"assistant"' not in line:
                continue
            try:
                rec = json.loads(line)
            except (json.JSONDecodeError, ValueError):
                stats.malformed_lines += 1
                continue
            if not isinstance(rec, dict) or rec.get("type") != "assistant":
                continue
            stats.assistant_lines += 1

            msg = rec.get("message") or {}
            usage = msg.get("usage")
            if not isinstance(usage, dict):
                stats.missing_usage += 1
                continue

            model = msg.get("model")
            if pricing.normalise_model(model) is None:
                stats.synthetic += 1
                continue

            key = (rec.get("requestId"), msg.get("id"))
            # A line with neither identifier cannot be deduplicated; keep it
            # rather than dropping real spend, but it is rare.
            if key != (None, None):
                if key in seen:
                    stats.duplicate_lines += 1
                    continue
                seen.add(key)

            ts = _parse_ts(rec.get("timestamp"))
            if ts is None:
                stats.malformed_lines += 1
                continue

            creation = usage.get("cache_creation")
            if isinstance(creation, dict):
                w5 = int(creation.get("ephemeral_5m_input_tokens") or 0)
                w1 = int(creation.get("ephemeral_1h_input_tokens") or 0)
            else:
                # Older transcripts report only the aggregate. Claude Code has
                # used 1h TTL throughout that period, so attribute it there.
                w5, w1 = 0, int(usage.get("cache_creation_input_tokens") or 0)

            # First-class cache diagnostics, when the client version reports
            # them. This is the API saying *why* a lookup failed, which the
            # token counts alone cannot tell you.
            has_diag = "diagnostics" in msg
            miss_reason = None
            missed_tokens = 0
            if has_diag:
                reason = (msg.get("diagnostics") or {}).get("cache_miss_reason")
                if isinstance(reason, dict):
                    miss_reason = reason.get("type")
                    missed_tokens = int(reason.get("cache_missed_input_tokens") or 0)

            content = msg.get("content")
            tools = (
                tuple(
                    b["name"]
                    for b in content
                    if isinstance(b, dict) and b.get("type") == "tool_use" and b.get("name")
                )
                if isinstance(content, list)
                else ()
            )

            req = Request(
                timestamp=ts,
                model=model,
                input_tokens=int(usage.get("input_tokens") or 0),
                output_tokens=int(usage.get("output_tokens") or 0),
                cache_write_5m=w5,
                cache_write_1h=w1,
                cache_read=int(usage.get("cache_read_input_tokens") or 0),
                fast=usage.get("speed") == "fast",
                session_id=rec.get("sessionId") or path.stem,
                project=proj,
                transcript=path,
                request_id=rec.get("requestId"),
                message_id=msg.get("id"),
                is_sidechain=bool(rec.get("isSidechain")),
                version=rec.get("version"),
                tools=tools,
                cwd=cwd,
                agent_id=agent,
                cache_miss_reason=miss_reason,
                cache_missed_tokens=missed_tokens,
                has_diagnostics=has_diag,
            )
            if not req.priced:
                stats.unpriced_models.add(str(model))
            out.append(req)
            stats.requests += 1

    out.sort(key=lambda r: r.timestamp)
    return out


def load(
    root: Path | str = DEFAULT_ROOT,
    project: str | None = None,
    paths: Iterable[Path] | None = None,
    project_depth: int = DEFAULT_PROJECT_DEPTH,
) -> tuple[list[Request], ParseStats]:
    """Parse many transcripts. Returns (requests, stats)."""
    stats = ParseStats()
    requests: list[Request] = []
    root_path = Path(root).expanduser()
    sources = paths if paths is not None else iter_transcripts(root, project)
    # Shared across files: a message id repeated in two transcripts is a copy
    # (Claude Code's backup directories hold whole duplicated sessions), not a
    # second billed request.
    seen: set[tuple[str | None, str | None]] = set()
    for path in sources:
        path = Path(path)
        requests.extend(
            parse_transcript(
                path,
                stats,
                project_depth,
                project_dir=transcript_project_dir(path, root_path),
                seen=seen,
            )
        )
    requests.sort(key=lambda r: r.timestamp)
    return requests, stats
