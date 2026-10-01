"""Guard the committed golden trace logs against drift from the solution.

Student repos have no ``solution/``, so ``tools/trace_streams.py`` compares a
student's host against the logs in ``rdt_support/reference_traces/``.  If the
reference solution or the simulator changes, those logs go stale silently;
this test catches that in the instructor repo.  It is not graded (no bundle
marker) and skips wherever the solution is absent.
"""

import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SOLUTION = PROJECT_ROOT / "solution" / "gbn_host.py"
TRACES = PROJECT_ROOT / "rdt_support" / "reference_traces"

sys.path.insert(0, str(PROJECT_ROOT / "tools"))
import trace_streams  # noqa: E402


@pytest.mark.skipif(not SOLUTION.exists(), reason="reference solution not present")
@pytest.mark.parametrize("name", list(trace_streams.SCENARIOS))
def test_golden_logs_match_reference_solution(name):
    reference_type = trace_streams.load_host(SOLUTION)
    sim = trace_streams.run(reference_type, trace_streams.SCENARIOS[name])
    rendered = trace_streams.render_all(sim)
    golden = trace_streams.load_golden_logs(TRACES, name)

    assert golden is not None, f"missing golden logs for {name}"
    for owner in trace_streams.STREAM_FILES:
        assert rendered[owner] == golden[owner], (
            f"{name} golden log is stale; regenerate with "
            "python tools/trace_streams.py --write-reference-traces"
        )
