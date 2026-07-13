"""Student-facing feedback and focused-run behavior for ``run_tests.py``."""

from __future__ import annotations

import importlib.util
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _load_runner_module():
    spec = importlib.util.spec_from_file_location(
        "run_tests_feedback_under_test", PROJECT_ROOT / "run_tests.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _runner(module, *, bundle=None):
    runner = module.BundleTestRunner.__new__(module.BundleTestRunner)
    runner.root_dir = PROJECT_ROOT
    runner.verbose = False
    runner.bundle = bundle
    runner.show_all = False
    runner.pytest_args = []
    runner._component_groups = []
    runner._unmarked_count = 0
    return runner


def test_printed_failure_command_is_copyable_from_project_root(capsys):
    module = _load_runner_module()
    runner = _runner(module)
    group = {
        "tests": [
            {
                "file": "test_packet_format.py",
                "name": "test_malformed_packet[empty]",
                "nodeid": "tests/test_packet_format.py::test_malformed_packet[empty]",
                "passed": False,
                "longrepr": "E assert False",
            }
        ]
    }

    runner._render_group_failures(group)

    output = capsys.readouterr().out
    assert (
        'python -m pytest "tests/test_packet_format.py::'
        'test_malformed_packet[empty]" -v'
    ) in output


def test_focused_bundle_run_does_not_write_or_report_an_overall_grade(capsys):
    module = _load_runner_module()
    runner = _runner(module, bundle=2)
    writes = []
    runner.write_status_cache = writes.append
    bundles_data = {
        1: [],
        2: [
            {
                "file": "test_window.py",
                "name": "test_window",
                "nodeid": "tests/test_window.py::test_window",
                "passed": True,
                "points": 1,
                "longrepr": "",
            }
        ],
        3: [],
    }

    runner.print_bundle_results(bundles_data)

    output = capsys.readouterr().out
    assert writes == []
    assert "FOCUSED BUNDLE 2 RESULTS" in output
    assert "overall grade" in output.lower()
    assert "Not Passing" not in output


def test_default_pytest_command_suppresses_redundant_failure_summary():
    module = _load_runner_module()
    runner = _runner(module)

    command = runner.build_pytest_command(["tests/test_example.py"])

    assert "--no-summary" in command
