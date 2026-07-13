# Testing the Go-Back-N Project

Run all commands from the repository root and through the project-local
virtual environment.

On macOS or Linux:

```bash
source venv/bin/activate
python run_tests.py
```

In Windows PowerShell:

```powershell
.\venv\Scripts\Activate.ps1
python run_tests.py
```

`run_tests.py` is the grading authority. It selects only tests with explicit
`@pytest.mark.bundle(1|2|3)` markers, records the development snapshot in
student repositories, and reports the lowest incomplete bundle first.

## Useful commands

```bash
python run_tests.py --bundle 1          # packet format + lossless baseline
python run_tests.py --bundle 2          # sender window + timeout recovery
python run_tests.py --bundle 3          # corruption + combined faults
python run_tests.py --all               # show failures in every bundle
python run_tests.py -v                  # full pytest names and tracebacks
python run_tests.py -k checksum          # pass a pytest name filter through
python run_tests.py --failed             # rerun pytest's previous failures
```

Students normally should not invoke raw pytest because the course runner also
handles capture and bundle reporting. Instructors should likewise use
`run_tests.py` when validating `solution/`; the runner temporarily copies the
top-level solution files into `src/` and restores `src/` afterward.

## Assignment test components

| Component | File | Main responsibility |
|---|---|---|
| Packet format | `tests/test_packet_format.py` | wire layout, checksum, parsing, malformed packets |
| Lossless delivery | `tests/test_lossless_delivery.py` | baseline full-duplex exact delivery |
| Window and timeout | `tests/test_window_and_timeout.py` | buffering, cumulative ACKs, Go-Back-N retransmission |
| Fault recovery | `tests/test_fault_recovery.py` | corruption, sustained/combined faults, duplicates |

The component order is declared in `project-template-config.json`. The runner
uses it only to focus feedback and suppress cascading failures; bundle credit
still depends on every marked test.

## Deterministic scenarios

The provided `rdt_support.NetworkSimulator` accepts a `FaultPlan` keyed by:

```text
(sender endpoint, packet type, sequence number) -> number of initial attempts
```

That lets a test say “drop A's first DATA 2” or “corrupt B's first ACK 4”
without relying on a random seed or an exact reference trace. The medium
preserves packet order, and the tests compare complete delivered lists—not
sets—so reordering and duplicates fail visibly.

## Reading failures

Start with the first unlocked component in the lowest incomplete bundle.
Packet-format failures commonly cascade into every later protocol test. For a
focused traceback, copy the command printed beneath the failure, for example:

```bash
python -m pytest tests/test_window_and_timeout.py::test_timeout_retransmits_the_entire_outstanding_window -v
```

If a simulation reaches its event limit, inspect whether a timeout is being
restarted and whether duplicate DATA produces the last cumulative ACK. The
event limit converts non-converging protocols into a finite, actionable test
failure.
