"""Shared primitives for the EventEngine benchmark suite.

Provides the versioned artifact-dir generation (library ``__version__`` +
current git head, computed at runtime), environment metadata collection,
statistics aggregation, and engine lifecycle helpers.
"""

from __future__ import annotations

import os
import platform
import statistics
import subprocess
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
BENCH_DIR = Path(__file__).resolve().parent
ARTIFACTS_ROOT = BENCH_DIR / "artifacts"

GIT_HEAD_LEN = 12


def git_head(short: int = GIT_HEAD_LEN) -> str:
    """Current git HEAD hash, first ``short`` characters.

    Returns "nogit" when the repo root is not inside a git repository or git
    is unavailable.
    """
    try:
        out = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            check=True,
            timeout=5,
        )
        head = out.stdout.strip()
        return head[:short] if short else head
    except (subprocess.SubprocessError, OSError):
        return "nogit"


def git_branch() -> str:
    """Current git branch name, or 'nogit' when unavailable."""
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            check=True,
            timeout=5,
        )
        return out.stdout.strip()
    except (subprocess.SubprocessError, OSError):
        return "nogit"


def versioned_dir_name(tag: str | None = None) -> str:
    """Artifact directory name: ``'<__version__>-<git_head[:12]>[-<tag>]'``.

    Both components are read at runtime — the library version from
    ``event_engine.__version__`` and the code state from ``git rev-parse``.
    """
    from event_engine import __version__

    name = f"{__version__}-{git_head()}"
    if tag:
        name = f"{name}-{tag}"
    return name


def versioned_artifacts_dir(tag: str | None = None, override: str | None = None) -> Path:
    """Directory holding this run's artifacts; created if missing.

    Defaults to ``tests/benchmarks/artifacts/<__version__>-<git_head>``.
    ``override`` replaces the whole directory path (e.g. from ``--out``).
    """
    out = Path(override) if override else ARTIFACTS_ROOT / versioned_dir_name(tag)
    out.mkdir(parents=True, exist_ok=True)
    return out


def collect_env() -> dict:
    """Environment metadata attached to every artifact."""
    from event_engine import __version__

    return {
        "version": __version__,
        "git_head": git_head(short=0),
        "git_head_short": git_head(),
        "git_branch": git_branch(),
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "platform": platform.platform(),
        "machine": platform.machine(),
        "processor": platform.processor() or platform.machine() or "unknown",
        "cpu_count": os.cpu_count(),
        "python": platform.python_version(),
        "executable": __import__("sys").executable,
        "repo_root": str(REPO_ROOT),
    }


def aggregate(trials: list[float]) -> dict:
    """Aggregate a list of per-op-seconds trial samples.

    Returns mean / std / coefficient-of-variation% / min / max / median.
    """
    n = len(trials)
    mean = statistics.fmean(trials)
    std = statistics.stdev(trials) if n > 1 else 0.0
    return {
        "n": n,
        "mean_s": mean,
        "std_s": std,
        "cv_pct": (std / mean * 100.0) if mean else 0.0,
        "min_s": min(trials),
        "max_s": max(trials),
        "median_s": statistics.median(trials),
    }


def percentiles_us(xs_ns: list[int], ps: tuple[int, ...] = (50, 95, 99)) -> dict:
    """Pooled latency percentiles in microseconds.

    ``xs_ns`` is the concatenation of all trial latency samples in ns.
    """
    xs = sorted(xs_ns)
    n = len(xs)
    out = {}
    for p in ps:
        out[f"p{p}_us"] = xs[int(p / 100.0 * (n - 1))] / 1e3
    out["avg_us"] = statistics.fmean(xs) / 1e3
    out["max_us"] = xs[-1] / 1e3
    return out


def ratio_vs(baseline_mean: float, candidate_mean: float) -> float:
    """Throughput/speed ratio of ``candidate`` relative to ``baseline``.

    >1.0 means the candidate is faster; the baseline itself is 1.0.
    """
    if baseline_mean <= 0.0:
        return float("nan")
    return candidate_mean / baseline_mean


def dispose(engine) -> None:
    """Stop (if running) and clear an engine, tolerating any state.

    Benchmarks measure time inside the timed region only; cleanup happens
    outside it, so failures here must not abort the run.
    """
    try:
        if engine.active:
            engine.stop()
    except Exception:
        pass
    try:
        engine.clear()
    except Exception:
        pass
