# Go-Back-N Protocol Specification

This document defines the required protocol behavior. The supplied simulator
models an unreliable network layer: packets may be lost or have a bit changed,
but packets that arrive are not duplicated or reordered by the medium.

## Endpoint interface

The simulator constructs two hosts with:

```python
GBNHost(simulator, entity, timer_interval, window_size)
```

It calls three methods:

- `receive_from_application_layer(payload)` when the local application has a
  string to send;
- `receive_from_network_layer(packet)` when a packet reaches this endpoint;
- `timer_interrupt()` when this endpoint's single sender timer expires.

The host may call four simulator methods:

- `pass_to_network_layer(entity, packet)`;
- `pass_to_application_layer(entity, payload)`;
- `start_timer(entity, timer_interval)`;
- `stop_timer(entity)`.

Both hosts send and receive concurrently. Each `GBNHost` therefore maintains
independent sender and receiver state.

### Packet helper interface

The starter also declares five public packet helpers. The grader calls these
methods directly, so their names and basic results are part of the assignment
interface:

- `create_data_pkt(seq_num, payload)` returns one DATA packet as `bytes`;
- `create_ack_pkt(seq_num)` returns one ACK packet as `bytes`;
- `create_checksum(packet)` returns the 16-bit Internet checksum as an integer;
- `is_corrupt(packet)` returns whether the packet checksum is invalid; and
- `unpack_pkt(packet)` returns a dictionary containing the decoded wire fields.

For DATA, the dictionary must contain `packet_type`, `seq_num`, `checksum`,
`payload_length`, and `payload`. For ACK, it must contain `packet_type`,
`seq_num`, and `checksum`. The packet type values are the wire values `0` and
`1`; an `IntEnum` equal to those values is also acceptable. `seq_num`,
`checksum`, and `payload_length` are Python integers. The DATA `payload` is the
decoded Python string, not the encoded wire bytes. Extra dictionary fields are
allowed. The grader does not require a particular exception type from
`unpack_pkt` for malformed input; it grades malformed input through the
endpoint's observable behavior.

## Wire format

All integer fields use network byte order (big endian). Python `struct` format
strings are shown as the unambiguous encoding definition.

### DATA packet

| Field | Type | Size | Value |
|---|---:|---:|---|
| packet type | unsigned short | 2 bytes | `0` |
| sequence number | unsigned int | 4 bytes | packet number |
| checksum | unsigned short | 2 bytes | Internet checksum |
| payload length | unsigned int | 4 bytes | UTF-8 byte length |
| payload | bytes | variable | UTF-8 string bytes |

Header format: `!HIHI`. The packet has exactly `12 + payload_length` bytes.

### ACK packet

| Field | Type | Size | Value |
|---|---:|---:|---|
| packet type | unsigned short | 2 bytes | `1` |
| acknowledged sequence | unsigned int | 4 bytes | highest contiguous DATA received |
| checksum | unsigned short | 2 bytes | Internet checksum |

Format: `!HIH`. An ACK has exactly 8 bytes and no payload.

Sequence numbers are unsigned 32-bit packet numbers. Tests use values far
below wraparound. `4294967295` is reserved as the receiver's initial
"nothing received yet" cumulative ACK value.

## Internet checksum

Use the standard 16-bit Internet checksum:

1. Set the checksum field to zero while creating a packet.
2. Interpret the bytes as big-endian 16-bit words, padding an odd final byte
   with zero for calculation only.
3. Add the words using end-around carry.
4. Store the one's complement of the sum.

Running the same calculation over an intact packet, including its stored
checksum, produces zero. Any nonzero result means the packet is corrupt.

## Sender behavior

Maintain these conceptual values:

- `window_base`: oldest unacknowledged sequence number;
- `next_seq_num`: sequence number to assign next;
- buffered packets for every number in
  `[window_base, next_seq_num)`;
- application messages waiting for window space.

When the application supplies a message:

1. Send it immediately if `next_seq_num < window_base + window_size`.
2. Otherwise, retain it until cumulative ACKs open space.
3. Start the single timer when sending into an empty outstanding window.

On a valid cumulative ACK numbered `n`:

- ignore it unless `window_base <= n < next_seq_num`;
- remove all acknowledged packets through `n`;
- set `window_base` to `n + 1`;
- stop the timer if no packets remain outstanding, otherwise restart it for
  the new oldest outstanding packet;
- fill newly opened window slots from the application buffer.

On timeout, restart the timer and retransmit every packet in the outstanding
window in sequence-number order. This is the defining Go-Back-N behavior.

Corrupt, malformed, duplicate, and out-of-window ACKs do not move the window.

## Receiver behavior

Maintain `expected_seq_num`, initially zero, and the last valid cumulative ACK.

For an intact DATA packet with exactly the expected sequence number:

1. deliver its payload to the application;
2. ACK that sequence number;
3. increment `expected_seq_num`.

For a duplicate, future, or corrupt DATA packet, do not deliver its payload
and do not buffer it. Repeat the ACK for the highest contiguous packet already
delivered. Before DATA zero has been accepted, that ACK uses the reserved
sequence number `4294967295`.

This rule provides exactly-once, in-order application delivery even when a
sender retransmits packets whose ACK was lost.

## Correctness contract

For every finite simulator scenario, after faults stop occurring:

- each receiver eventually obtains the opposite sender's complete message
  list;
- order and duplicate multiplicity are preserved exactly;
- neither sender transmits new DATA outside its fixed window;
- retransmission eventually makes progress after loss or corruption.

The grader does not require a particular private design or an exact packet
count when more than one correct event sequence is possible.
