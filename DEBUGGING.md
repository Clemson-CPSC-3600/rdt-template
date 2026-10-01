# Debugging with Stream Trace Logs

When a bundle test fails, the assertion tells you *that* your protocol
misbehaved, not *where*. This tool renders every event your `GBNHost` produces —
every packet sent, every packet received, every timer, every hand-off to and
from the application — as a readable log, and shows you the first line where
your behavior diverges from a correct implementation. The reference logs it
compares against ship with the repo in `rdt_support/reference_traces/`.

The network simulator is **fully deterministic**: the same scenario always
produces the same events at the same times. Two consequences follow, and they
are the whole idea behind this tool:

1. Your own log is a faithful, replayable picture of what your host actually did.
2. The reference log never changes, so if your log differs from it, the
   difference is caused by *your host*, not by luck. **Read the first differing
   line — everything after it is downstream noise.**

## Quick start

From the project root, with your virtual environment activated:

```bash
source venv/bin/activate          # Windows: .\venv\Scripts\Activate.ps1

python tools/trace_streams.py                 # all scenarios
python tools/trace_streams.py --list          # list scenario names
python tools/trace_streams.py --scenario corrupt-first-data
```

Each run writes logs under `trace-logs/<scenario>/` and prints a one-line
verdict per stream:

```text
[corrupt-first-data]
  stream A→B: ✓ matches reference (53 lines)
  stream B→A: ✓ matches reference (16 lines)
```

or, when you diverge:

```text
[combined-faults]
  stream A→B: ✗ first divergence at line 95
    reference: t=2.400   B      send    ACK seq=3  (repeat — reacted to a corrupt packet)
    yours:     (end of log)
  stream B→A: ✓ matches reference (80 lines)
```

The files it writes:

| File | What it is |
|---|---|
| `trace-logs/<scenario>/yours.a2b.log` | your host's log for the A→B data stream |
| `trace-logs/<scenario>/yours.b2a.log` | your host's log for the B→A data stream |
| `trace-logs/<scenario>/reference.*.log` | the same, from a correct implementation |

Open `yours.*.log` and `reference.*.log` for the failing stream side by side (or
`diff` them) and jump to the reported line.

> **Two ways to use it.** Even before you compare against the reference, reading
> your *own* log is the fastest way to see what your host is doing — where it
> stays silent, sends the wrong sequence number, or mismanages its timer. The
> reference comparison then tells you the exact first place you went wrong.

## Why there are two logs, not one

Both hosts send and receive at the same time (full duplex), which is confusing
to read all at once. So each scenario is split into two **one-direction
streams**, and each gets its own log:

- **A→B** — A sends DATA, B acknowledges. Contains A's sends, the network's
  handling of them, B's receives and application deliveries, B's ACKs travelling
  back, and A's sender timer.
- **B→A** — the mirror image: B sends DATA, A acknowledges.

An ACK belongs to the stream of the *data it acknowledges*, so B's ACKs appear
in the A→B log even though they travel from B to A.

## How to read a log line

Every line starts with a simulator timestamp and a **lane** — who acted:

| Lane | Meaning |
|---|---|
| `APP→A` | the application handed a message to host A to send |
| `A→APP` | host A delivered a received message up to its application |
| `A` / `B` | the host itself: a `send`, a `recv`, or a `timer` action |
| `NET` | the network medium: it delivered, **corrupted**, or **lost** a packet |

Each packet line shows a readable summary plus **decoded header fields**
(`len`, `cksum` in decimal), and the **raw wire bytes** on the line below. A
real excerpt (`corrupt-first-data`, stream A→B), annotated:

```text
t=0.000   APP→A  queue   "hello"                              ← app gives A a message
t=0.000   A      timer   start (2.000s)                       ← A arms its sender timer
t=0.000   A      send    DATA seq=0 len=5 cksum=48168  "hello"  attempt=1
                  0000 0000 0000 bc28 0000 0005 6865 6c6c 6f  ← decoded fields + raw bytes
t=0.050   NET    DATA seq=0  CORRUPTED in transit             ← the medium flipped a bit
                  sent      0000 0000 0000 bc28 0000 0005 6865 6c6c 6f
                  delivered 0000 0000 0000 bc28 0000 0005 6865 6c6c 6e   (byte 16: 6f→6e)
t=0.050   B      recv    DATA seq=0                            ← B receives the damaged packet
t=0.050   B      send    ACK seq=— cksum=65534  (repeat — reacted to a corrupt packet)
                  0001 ffff ffff fffe                         ← B repeats its last ACK
```

Key annotations:

- **`len` / `cksum`** are the decoded length and checksum (in decimal) — so a
  packing or checksum bug is visible without hand-parsing the hex. `cksum=48168`
  here is the same value the raw bytes store as `bc28`.
- **`NET ... CORRUPTED`** shows the `sent` and `delivered` bytes so you can see
  exactly which byte changed. **`NET ... LOST`** means the packet never arrives —
  there is no `recv` line after it. **`delivered intact`** means it arrived
  unchanged.
- **`seq=—`** is the "nothing received yet" cumulative ACK (the reserved value
  `4294967295`).
- **`timer WARNING: ...`** flags an illegal timer operation — starting a timer
  while one is already running, or stopping one when none is. The Go-Back-N
  sender keeps at most one timer, so these mean a timer-management bug.
- **`(repeat — reacted to a corrupt packet)`** flags an ACK your host repeated
  because a corrupt packet arrived. The corrupt packet that triggered it may be
  in the *other* stream's log at the same timestamp — that is expected. Because a
  corrupt packet's type cannot be trusted, the correct reaction to *any* corrupt
  packet is to repeat your last ACK (see the "Handling corruption" rule in
  [PROTOCOL.md](PROTOCOL.md)).

### The byte line

Bytes are shown in raw hex, grouped into the 16-bit words the Internet checksum
sums over, so a mis-packed field or a wrong checksum jumps out. For the DATA
packet above (`!HIHI` header + payload):

```text
0000   0000 0000   bc28   0000 0005   6865 6c6c 6f
type   seq         cksum  length      "hello"
```

`bc28` is the checksum, and `cksum=48168` on the line above is that same value
in decimal — see the worked example in [PROTOCOL.md](PROTOCOL.md#worked-example).

An ACK (`!HIH`, no payload) is `type  seq  cksum`, e.g. `0001 ffff ffff fffe`
is an ACK (`0001`) for sequence `ffffffff` with checksum `fffe`.

## Finding your bug: the first divergence

When a stream reports `✗ first divergence at line N`, that line is where your
host first did something a correct host would not. Everything above line N
matched exactly. Everything below it is unreliable — one wrong action shifts all
later events and timestamps, so **do not chase differences past the first one.**

Fix that one thing, re-run, and the divergence will either disappear or move
later. Work down the log one divergence at a time.

## Symptom → likely cause

| What you see at the divergence | Likely cause |
|---|---|
| `yours: (end of log)` / a missing `send ACK` after a `NET ... CORRUPTED` | You don't repeat your last ACK on a corrupt packet — or you read the (untrustworthy) type of a corrupt packet before reacting. |
| A missing `timer stop`, or a `timer start` where the reference has none | Timer mismanagement: not stopping the timer when a cumulative ACK clears the window, or restarting it at the wrong moment. |
| A `timer WARNING:` line in your log | You started a timer while one was already running, or stopped one that wasn't. The sender keeps exactly one timer. |
| Your `cksum=` differs from the reference's, or `send` bytes differ in a header field | A packing bug in `create_data_pkt` / `create_ack_pkt` / `create_checksum`. Compare the decoded fields and the byte line word by word. |
| An `A→APP deliver` the reference doesn't have, or a wrong `send ACK seq=` | Delivering or acknowledging an out-of-order or duplicate DATA packet instead of repeating the last cumulative ACK. |
| On timeout, you `send` fewer DATA packets than the reference | Go-Back-N retransmits the **whole** outstanding window on timeout, not just the base packet. |
| You `send DATA` for a sequence number the reference hasn't reached | Sending past the sender window, or advancing `next_seq_num` incorrectly. |
| A `send ACK seq=k` where the reference sends a higher `seq` | ACKs are **cumulative** — acknowledge the highest in-order packet received, not each packet individually. |

## Tips

- **Only the first divergence matters.** Re-run after each fix.
- **Check both streams.** A bug in your receiver shows up in the stream where the
  *other* host is sending.
- **The reference is fixed.** If the logs differ, it is your host — the network
  did the exact same thing to both runs.
- Use `--scenario <name>` to focus on one failing case; `--list` shows them all.
- These logs are a **debugging aid, not a grader.** The bundle tests
  (`python run_tests.py`) remain the authority on whether your project passes.
