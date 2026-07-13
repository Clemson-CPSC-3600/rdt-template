"""Guard the promise that grading does not depend on private host design."""

from __future__ import annotations

import ast
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent
GRADED_TESTS = (
    "test_packet_format.py",
    "test_lossless_delivery.py",
    "test_window_and_timeout.py",
    "test_fault_recovery.py",
)
PRIVATE_STATE_NAMES = {
    "app_layer_buffer",
    "expected_seq_num",
    "last_ack_pkt",
    "next_seq_num",
    "unacked_buffer",
    "window_base",
}


def _is_unpack_call(node: ast.AST) -> bool:
    return isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and (
        node.func.attr == "unpack_pkt"
    )


def _is_pytest_raises(node: ast.AST) -> bool:
    return isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and (
        isinstance(node.func.value, ast.Name)
        and node.func.value.id == "pytest"
        and node.func.attr == "raises"
    )


def test_graded_tests_depend_only_on_the_documented_host_contract():
    violations = []

    for filename in GRADED_TESTS:
        path = PROJECT_ROOT / "tests" / filename
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=filename)

        private_attributes = sorted(
            {
                node.attr
                for node in ast.walk(tree)
                if isinstance(node, ast.Attribute) and node.attr in PRIVATE_STATE_NAMES
            }
        )
        if private_attributes:
            violations.append(f"{filename}: private state {private_attributes}")

        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module == "src.gbn_host":
                imported = {alias.name for alias in node.names}
                unsupported = sorted(imported - {"GBNHost"})
                if unsupported:
                    violations.append(
                        f"{filename}: undocumented module exports {unsupported}"
                    )

            if isinstance(node, ast.Compare) and any(
                _is_unpack_call(candidate) for candidate in (node.left, *node.comparators)
            ):
                if any(
                    isinstance(candidate, ast.Dict)
                    for candidate in (node.left, *node.comparators)
                ):
                    violations.append(
                        f"{filename}: exact unpack_pkt dictionary comparison"
                    )

            if isinstance(node, ast.With) and any(
                _is_pytest_raises(item.context_expr) for item in node.items
            ):
                if any(_is_unpack_call(candidate) for candidate in ast.walk(node)):
                    violations.append(
                        f"{filename}: exception-specific unpack_pkt contract"
                    )

    assert violations == []


def test_packet_helpers_and_parse_fields_are_part_of_the_written_contract():
    protocol = (PROJECT_ROOT / "PROTOCOL.md").read_text(encoding="utf-8")
    normalized_protocol = " ".join(protocol.split())

    required_terms = {
        "create_data_pkt",
        "create_ack_pkt",
        "create_checksum",
        "unpack_pkt",
        "is_corrupt",
        "packet_type",
        "seq_num",
        "checksum",
        "payload_length",
        "payload",
    }

    assert {term for term in required_terms if term not in protocol} == set()
    assert "Extra dictionary fields are allowed" in normalized_protocol
    assert "does not require a particular exception type" in normalized_protocol
    assert "seq_num, checksum, and payload_length are Python integers" in (
        normalized_protocol.replace("`", "")
    )
    assert "payload is the decoded Python string" in normalized_protocol.replace(
        "`", ""
    )


def test_student_facing_tests_and_setup_match_the_bundle_grading_model():
    point_decorators = []
    malformed_bundle = None

    for filename in GRADED_TESTS:
        path = PROJECT_ROOT / "tests" / filename
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=filename)
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            for decorator in node.decorator_list:
                if not isinstance(decorator, ast.Call) or not isinstance(
                    decorator.func, ast.Attribute
                ):
                    continue
                if decorator.func.attr == "points":
                    point_decorators.append(f"{filename}:{node.name}")
                if "malformed_packet_shapes" in node.name and (
                    decorator.func.attr == "bundle"
                ):
                    malformed_bundle = ast.literal_eval(decorator.args[0])

    readme = (PROJECT_ROOT / "README.md").read_text(encoding="utf-8")
    testing = (PROJECT_ROOT / "TESTING.md").read_text(encoding="utf-8")

    assert point_decorators == []
    assert malformed_bundle == 3
    assert "Activate.ps1" in readme
    assert "Activate.ps1" in testing
