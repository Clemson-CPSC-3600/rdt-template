#!/usr/bin/env python3
"""Render per-stream event logs and compare your host against the reference.

For each scenario this runs the deterministic simulator twice -- once with your
``src/gbn_host.py`` and once with the reference -- splits each run into two
one-direction logs (A->B and B->A), writes them under ``trace-logs/``, and
prints the first line where your behavior diverges from the reference.

    python tools/trace_streams.py                 # all scenarios, src vs reference
    python tools/trace_streams.py --scenario corrupt-first-data
    python tools/trace_streams.py --list

Because the simulator is fully deterministic, the reference logs are a stable
golden trace: the only thing that ever differs is how a host reacts.  Read the
FIRST differing line -- everything after it is downstream noise.

When ``solution/gbn_host.py`` is absent (as in a student repo), the comparison
uses the golden logs committed under ``rdt_support/reference_traces/``.
Instructors regenerate them from the solution with::

    python tools/trace_streams.py --write-reference-traces
"""

from __future__ import annotations

import argparse
import importlib.util
import sys
from pathlib import Path
from typing import Optional

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from rdt_support import (  # noqa: E402  (import after sys.path setup)
    ACK_PACKET,
    DATA_PACKET,
    EventEntity,
    FaultPlan,
    NetworkSimulator,
    diff_report,
    render_all,
)


# Each host's log file suffix: A sends the A->B stream, B the B->A stream.
STREAM_FILES = {EventEntity.A: "a2b", EventEntity.B: "b2a"}

# Each scenario is (messages_from_a, messages_from_b, FaultPlan, kwargs).
SCENARIOS = {
    "corrupt-first-data": (
        ("hello", "world"),
        ("hi",),
        FaultPlan(corrupt_attempts={(EventEntity.A, DATA_PACKET, 0): 1}),
        {"timer_interval": 2.0, "window_size": 5,
         "arrival_interval": 0.01, "network_delay": 0.05},
    ),
    "clean-bidirectional": (
        ("A-0", "A-1", "A-2"),
        ("B-0", "B-1"),
        FaultPlan(),
        {"arrival_interval": 0.01},
    ),
    "dropped-data": (
        ("A-0", "A-1", "A-2"),
        ("B-0",),
        FaultPlan(drop_attempts={(EventEntity.A, DATA_PACKET, 1): 1}),
        {"arrival_interval": 0.01},
    ),
    "combined-faults": (
        tuple(f"A-{i}" for i in range(4)),
        tuple(f"B-{i}" for i in range(3)),
        FaultPlan(
            drop_attempts={(EventEntity.A, DATA_PACKET, 0): 1},
            corrupt_attempts={
                (EventEntity.B, DATA_PACKET, 1): 1,
                (EventEntity.A, ACK_PACKET, 2): 1,
            },
        ),
        {"arrival_interval": 0.01},
    ),
}


def load_host(path: Path):
    """Import ``GBNHost`` from a standalone file under a unique module name."""

    spec = importlib.util.spec_from_file_location(f"_host_{path.parent.name}", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.GBNHost


def run(host_type, scenario) -> Optional[NetworkSimulator]:
    """Run one scenario; return the simulator, or ``None`` if the host is a stub."""

    messages_a, messages_b, faults, kwargs = scenario
    sim = NetworkSimulator(
        host_type, messages_a, messages_b, faults=faults, capture_trace=True, **kwargs
    )
    try:
        sim.run()
    except NotImplementedError:
        return None
    return sim


def load_golden_logs(traces_dir: Path, name: str) -> Optional[dict]:
    """Read one scenario's committed reference logs, or ``None`` if missing."""

    logs = {}
    for owner, slug in STREAM_FILES.items():
        path = traces_dir / name / f"{slug}.txt"
        if not path.exists():
            return None
        logs[owner] = path.read_text()
    return logs


def write_golden_logs(reference_type, traces_dir: Path) -> int:
    """Render every scenario with the reference and store the logs as golden."""

    for name, scenario in SCENARIOS.items():
        sim = run(reference_type, scenario)
        if sim is None:
            print(f"reference host is a stub; cannot render {name}", file=sys.stderr)
            return 2
        logs = render_all(sim)
        out_dir = traces_dir / name
        out_dir.mkdir(parents=True, exist_ok=True)
        for owner, slug in STREAM_FILES.items():
            (out_dir / f"{slug}.txt").write_text(logs[owner])
        print(f"wrote {out_dir}/")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--scenario", help="run only this scenario (see --list)")
    parser.add_argument("--list", action="store_true", help="list scenario names and exit")
    parser.add_argument("--out", default="trace-logs", help="output directory")
    parser.add_argument("--student", default="src/gbn_host.py")
    parser.add_argument("--reference", default="solution/gbn_host.py")
    parser.add_argument("--reference-traces", default="rdt_support/reference_traces",
                        help="golden logs used when the reference host is absent")
    parser.add_argument("--write-reference-traces", action="store_true",
                        help="(instructor) regenerate the golden logs from the reference")
    args = parser.parse_args()

    if args.list:
        for name in SCENARIOS:
            print(name)
        return 0

    if args.scenario and args.scenario not in SCENARIOS:
        print(f"unknown scenario {args.scenario!r}; try --list", file=sys.stderr)
        return 2
    names = [args.scenario] if args.scenario else list(SCENARIOS)

    reference_path = REPO_ROOT / args.reference
    reference_type = load_host(reference_path) if reference_path.exists() else None
    traces_dir = REPO_ROOT / args.reference_traces

    if args.write_reference_traces:
        if reference_type is None:
            print(f"cannot write golden logs: {args.reference} does not exist",
                  file=sys.stderr)
            return 2
        return write_golden_logs(reference_type, traces_dir)

    student_path = REPO_ROOT / args.student
    student_type = load_host(student_path) if student_path.exists() else None

    if student_type is None and reference_type is None and not traces_dir.is_dir():
        print(f"nothing to render: neither {args.student} nor {args.reference} exists",
              file=sys.stderr)
        return 2

    out_root = REPO_ROOT / args.out
    stream_files = STREAM_FILES
    any_divergence = False

    for name in names:
        scenario = SCENARIOS[name]
        out_dir = out_root / name
        out_dir.mkdir(parents=True, exist_ok=True)
        print(f"[{name}]")

        reference_logs = None
        if reference_type is not None:
            reference_sim = run(reference_type, scenario)
            if reference_sim is not None:
                reference_logs = render_all(reference_sim)
        else:
            reference_logs = load_golden_logs(traces_dir, name)
        if reference_logs is not None:
            for owner, slug in stream_files.items():
                (out_dir / f"reference.{slug}.log").write_text(reference_logs[owner])

        student_logs = None
        if student_type is not None:
            student_sim = run(student_type, scenario)
            if student_sim is None:
                print(f"  {args.student} is not implemented yet — nothing to render")
            else:
                student_logs = render_all(student_sim)
                for owner, slug in stream_files.items():
                    (out_dir / f"yours.{slug}.log").write_text(student_logs[owner])

        if student_logs and reference_logs:
            for owner in stream_files:
                peer = EventEntity.B if owner == EventEntity.A else EventEntity.A
                report = diff_report(
                    student_logs[owner], reference_logs[owner],
                    f"  stream {owner.name}→{peer.name}",
                )
                print(report)
                if "✗" in report:
                    any_divergence = True
        elif student_logs:
            print(f"  wrote your logs to {out_dir}/ (no reference available to compare)")
        elif reference_logs:
            print(f"  wrote reference logs to {out_dir}/")

    print(f"\nLogs under {out_root}/")
    return 1 if any_divergence else 0


if __name__ == "__main__":
    raise SystemExit(main())
