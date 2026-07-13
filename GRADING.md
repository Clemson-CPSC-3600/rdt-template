# Specification Grading: Reliable Data Transfer

This assignment uses three cumulative, pass/fail bundles. Each bundle is one
grading point. A bundle is complete only when every test assigned to it passes,
and a higher bundle is awarded only after every lower bundle is complete.

| Completed bundles | Grade level | Required behavior |
|---|---|---|
| none | Not passing | Core packet or delivery contract incomplete |
| Bundle 1 | C | Packet format, checksum, lossless full-duplex delivery |
| Bundles 1–2 | B | Fixed window, buffering, cumulative ACKs, timeout recovery |
| Bundles 1–3 | A | Exact delivery under corruption and combined faults |

## Bundle 1: protocol foundation

Bundle 1 requires:

- DATA and ACK fields packed in network byte order;
- a correct 16-bit Internet checksum with end-around carry;
- strict parsing of packet size and payload length;
- detection of a changed packet bit;
- exact, in-order, full-duplex delivery without network faults;
- no unnecessary DATA retransmission in calibrated lossless scenarios.

## Bundle 2: Go-Back-N sender

Bundle 2 requires:

- never sending new DATA beyond the fixed window;
- buffering application messages while the window is full;
- treating ACKs cumulatively and opening all acknowledged slots;
- one timer associated with the oldest outstanding packet;
- retransmitting the entire outstanding window after timeout;
- recovering from a lost DATA packet and from a lost final ACK.

## Bundle 3: robust receiver and fault recovery

Bundle 3 requires:

- discarding rather than buffering future DATA;
- never delivering duplicate DATA twice;
- repeating the most recent cumulative ACK for damaged or unexpected DATA;
- ignoring damaged ACKs without moving the sender window;
- eventual exact delivery under deterministic corruption, repeated loss, and
  simultaneous faults in both directions.

## Scoring authority

The same `BundleTestRunner.compute_bundle_status` calculation drives local
output, GitHub Classroom, and Gradescope. GitHub Classroom invokes
`github_grader.py`; Gradescope invokes `gradescope/gradescope_grader.py` with
the instructor's canonical tests. Neither path uses the old assignment's
weighted individual tests or exact reference packet-count snapshots.

Run `python run_tests.py` to see the current result. Use `--all` for every
failure or `-v` for full pytest tracebacks.
