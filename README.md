# Project 2: Reliable Data Transfer with Go-Back-N

In this project you will implement one endpoint of a full-duplex reliable data
transfer protocol. Two instances of your `GBNHost` communicate across a
simulated network that can lose or corrupt packets. Your implementation must
deliver every application message once, in order, in both directions.

The protocol is Go-Back-N: packet-number sequence numbers, cumulative
acknowledgments, a fixed sender window, one timer per sender, and no
handshake or connection teardown. Congestion control, selective ACKs, and
TCP-style byte-stream sequence numbers are not part of this assignment.

Read [PROTOCOL.md](PROTOCOL.md) before writing code. It is the authoritative
wire-format and state-machine specification.

## What you implement

You work in one file:

```text
src/gbn_host.py
```

The starter declares the required `GBNHost` interface. You may add private
helper methods and state, but do not rename the class, its constructor, or its
public methods. This includes the five packet helpers documented under
"Packet helper interface" in [PROTOCOL.md](PROTOCOL.md). Private attribute
names and container types are your choice. The network simulator in
`rdt_support/` is provided course infrastructure and should not be modified.

## Setup

On macOS or Linux, from the project root:

```bash
python3 -m venv venv
source venv/bin/activate
python -m pip install -r requirements.txt
```

In Windows PowerShell:

```powershell
py -m venv venv
.\venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

The distributed repository already contains the starter in `src/gbn_host.py`.
The copy under `template/` is a clean backup in case you need to restore it.

After the environment exists, run Python only through that local environment.
With the environment activated, `python` points to the correct interpreter;
you can also invoke `./venv/bin/python` explicitly on macOS/Linux.

## Run the tests

```bash
python run_tests.py
python run_tests.py --bundle 1
python run_tests.py --all
python run_tests.py -v
```

The normal runner executes only tests carrying an explicit Bundle 1, 2, or 3
marker. It preserves the repository's development-trace capture and reports
the lowest incomplete bundle first. See [TESTING.md](TESTING.md) for focused
commands and test organization.

## Specification-grading bundles

| Bundle | Protocol capability | Grade when cumulative |
|---|---|---|
| 1 | Internet checksum, packet encoding/parsing, lossless full-duplex delivery | C |
| 2 | Fixed sender window, buffering, cumulative ACKs, timeout-based Go-Back-N recovery | B |
| 3 | Duplicate/out-of-order handling and exact delivery under corruption and combined faults | A |

Every test in a bundle must pass, and higher bundles require all lower bundles.
Tests judge protocol behavior rather than requiring the reference
implementation's exact number or timing of transmissions.

## Suggested implementation order

1. Implement the Internet checksum and verify packet creation/parsing.
2. Make one DATA packet travel losslessly from one host to the other.
3. Add cumulative ACK processing and the sender window.
4. Buffer application messages when the window is full.
5. Implement timeout retransmission of the complete outstanding window.
6. Handle damaged, duplicate, and out-of-order packets without duplicate
   application delivery.
7. Exercise both directions at the same time.

## Submission

Commit and push your work to the GitHub Classroom repository. The Classroom
workflow runs the same bundle authority as `python run_tests.py`; Gradescope
also uses the instructor's canonical copy of these tests.

Local AI-agent interactions and test-run snapshots are captured as described
in [AI_POLICY.md](AI_POLICY.md) and [PROCESS_TRACKING.md](PROCESS_TRACKING.md).
