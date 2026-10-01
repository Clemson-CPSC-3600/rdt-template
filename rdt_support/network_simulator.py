"""Deterministic event-driven network simulator for the Go-Back-N project.

The simulator is assignment infrastructure, not student work.  It presents
the four callbacks documented in PROTOCOL.md and records enough observable
state for behavioral tests.  Faults are selected by packet identity and
attempt number, so a scenario is repeatable without depending on a random
number generator or on an instructor implementation's exact event trace.
"""

from __future__ import annotations

import heapq
import itertools
import struct
from collections import Counter
from dataclasses import dataclass, field
from enum import Enum, IntEnum
from typing import Dict, Iterable, List, Mapping, Optional, Tuple, Type


DATA_PACKET = 0
ACK_PACKET = 1

# Wire size of the DATA header (!HIHI): type + seq + checksum + length.
_DATA_HEADER_SIZE = 12


class EventEntity(IntEnum):
    """The two full-duplex protocol endpoints."""

    A = 0
    B = 1


PacketKey = Tuple[EventEntity, int, int]


@dataclass
class FaultPlan:
    """Number of initial attempts to drop or corrupt for selected packets.

    Keys have the form ``(sender, packet_type, sequence_number)``.  For
    example, ``{(EventEntity.A, DATA_PACKET, 2): 1}`` drops A's first attempt
    to transmit DATA sequence number 2.  A packet listed in both mappings is
    dropped; corruption is only meaningful for an attempt that reaches the
    receiver.
    """

    drop_attempts: Mapping[PacketKey, int] = field(default_factory=dict)
    corrupt_attempts: Mapping[PacketKey, int] = field(default_factory=dict)


@dataclass(frozen=True)
class Transmission:
    """One call made by a host to ``pass_to_network_layer``."""

    time: float
    sender: EventEntity
    receiver: EventEntity
    packet_type: int
    sequence_number: int
    attempt: int
    dropped: bool
    corrupted: bool


@dataclass
class TraceEvent:
    """One observable event captured for the human-readable stream logs.

    Every field is observable at the simulator boundary -- never host internal
    state -- so a rendering is a pure function of what actually crossed a layer.
    That is what lets a student log and a reference log diff meaningfully: they
    differ only where the two hosts genuinely behaved differently.
    """

    order: int  # emission counter; stable tie-break when times are equal
    time: float
    kind: str  # app_down|app_up|send|net|recv|timer_start|timer_stop|timer_fire
    owner: EventEntity  # data stream this belongs to, named by its DATA sender
    entity: EventEntity  # the acting host (the receiver for net/recv events)
    packet_type: Optional[int] = None
    seq_num: Optional[int] = None
    attempt: Optional[int] = None
    payload: Optional[str] = None
    sent_bytes: Optional[bytes] = None
    delivered_bytes: Optional[bytes] = None
    outcome: Optional[str] = None  # net events: intact|corrupted|lost
    timer_interval: Optional[float] = None
    after_corrupt: bool = False  # send emitted while reacting to a corrupt packet


class _EventKind(str, Enum):
    APPLICATION = "application"
    NETWORK = "network"
    TIMER = "timer"


@dataclass(order=True)
class _QueuedEvent:
    time: float
    order: int
    kind: _EventKind = field(compare=False)
    entity: EventEntity = field(compare=False)
    value: object = field(compare=False, default=None)
    generation: int = field(compare=False, default=0)
    corrupt: bool = field(compare=False, default=False)


class NetworkSimulator:
    """Run two instances of a student's host across a reliable-order medium.

    The medium may drop or corrupt packets but does not duplicate or reorder
    packets that it actually delivers.  Both endpoints can receive
    application messages, which exercises a sender and receiver in each host.
    """

    def __init__(
        self,
        host_type: Type[object],
        messages_from_a: Iterable[str] = (),
        messages_from_b: Iterable[str] = (),
        *,
        timer_interval: float = 2.0,
        window_size: int = 5,
        arrival_interval: float = 0.05,
        network_delay: float = 0.05,
        faults: Optional[FaultPlan] = None,
        max_events: int = 20_000,
        capture_trace: bool = False,
    ) -> None:
        if timer_interval <= 0:
            raise ValueError("timer_interval must be positive")
        if window_size <= 0:
            raise ValueError("window_size must be positive")
        if arrival_interval < 0 or network_delay <= 0:
            raise ValueError("arrival_interval must be nonnegative and delay positive")

        self.time = 0.0
        self.timer_interval = timer_interval
        self.window_size = window_size
        self.max_events = max_events
        self.events_processed = 0
        self.timer_violations: List[str] = []

        self.sent_payloads: Dict[EventEntity, List[str]] = {
            EventEntity.A: list(messages_from_a),
            EventEntity.B: list(messages_from_b),
        }
        self.delivered_payloads: Dict[EventEntity, List[str]] = {
            EventEntity.A: [],
            EventEntity.B: [],
        }
        self.transmissions: List[Transmission] = []

        self._network_delay = network_delay
        self._faults = faults or FaultPlan()
        self._attempts: Counter[PacketKey] = Counter()
        self._queue: List[_QueuedEvent] = []
        self._event_order = itertools.count()
        self._trace: Optional[List[TraceEvent]] = [] if capture_trace else None
        self._trace_order = itertools.count()
        self._reacting_corrupt = False  # true while a host processes a corrupt packet
        self._last_network_arrival = {
            EventEntity.A: 0.0,
            EventEntity.B: 0.0,
        }
        self._timer_deadline: Dict[EventEntity, Optional[float]] = {
            EventEntity.A: None,
            EventEntity.B: None,
        }
        self._timer_generation = {
            EventEntity.A: 0,
            EventEntity.B: 0,
        }

        self.A = host_type(self, EventEntity.A, timer_interval, window_size)
        self.B = host_type(self, EventEntity.B, timer_interval, window_size)
        self.hosts = {EventEntity.A: self.A, EventEntity.B: self.B}

        for index, payload in enumerate(self.sent_payloads[EventEntity.A]):
            self._schedule(
                index * arrival_interval,
                _EventKind.APPLICATION,
                EventEntity.A,
                payload,
            )
        for index, payload in enumerate(self.sent_payloads[EventEntity.B]):
            self._schedule(
                (index * arrival_interval) + (arrival_interval / 2),
                _EventKind.APPLICATION,
                EventEntity.B,
                payload,
            )

    @staticmethod
    def opposite_entity(entity: EventEntity) -> EventEntity:
        return EventEntity.B if entity == EventEntity.A else EventEntity.A

    @property
    def trace(self) -> List[TraceEvent]:
        """Captured observable events (empty unless ``capture_trace=True``)."""

        return list(self._trace) if self._trace is not None else []

    def _emit(
        self,
        kind: str,
        time: float,
        owner: EventEntity,
        entity: EventEntity,
        **fields,
    ) -> None:
        if self._trace is None:
            return
        self._trace.append(
            TraceEvent(
                order=next(self._trace_order),
                time=time,
                kind=kind,
                owner=owner,
                entity=entity,
                **fields,
            )
        )

    def _stream_owner(self, packet_type: int, sender: EventEntity) -> EventEntity:
        # DATA belongs to its sender's stream; an ACK belongs to the stream of
        # the data it acknowledges -- the peer that sent that data.
        if packet_type == DATA_PACKET:
            return sender
        return self.opposite_entity(sender)

    @staticmethod
    def _payload_text(packet: bytes, packet_type: int) -> Optional[str]:
        if packet_type != DATA_PACKET:
            return None
        try:
            return packet[_DATA_HEADER_SIZE:].decode("utf-8")
        except (UnicodeError, IndexError):
            return None

    def _schedule(
        self,
        time: float,
        kind: _EventKind,
        entity: EventEntity,
        value: object = None,
        generation: int = 0,
        corrupt: bool = False,
    ) -> None:
        heapq.heappush(
            self._queue,
            _QueuedEvent(
                time,
                next(self._event_order),
                kind,
                entity,
                value,
                generation,
                corrupt,
            ),
        )

    @staticmethod
    def _packet_identity(packet: bytes) -> Tuple[int, int]:
        if not isinstance(packet, bytes) or len(packet) < 6:
            raise ValueError("network packets must contain a type and sequence number")
        return struct.unpack("!HI", packet[:6])

    @staticmethod
    def _corrupt(packet: bytes) -> bytes:
        values = bytearray(packet)
        values[-1] ^= 0x01
        return bytes(values)

    def pass_to_network_layer(self, entity: EventEntity, packet: bytes) -> None:
        """Schedule a host-created packet for the opposite endpoint."""

        packet_type, sequence_number = self._packet_identity(packet)
        key = (entity, packet_type, sequence_number)
        self._attempts[key] += 1
        attempt = self._attempts[key]

        drop_limit = int(self._faults.drop_attempts.get(key, 0))
        corrupt_limit = int(self._faults.corrupt_attempts.get(key, 0))
        dropped = attempt <= drop_limit
        corrupted = not dropped and attempt <= corrupt_limit
        receiver = self.opposite_entity(entity)

        self.transmissions.append(
            Transmission(
                time=self.time,
                sender=entity,
                receiver=receiver,
                packet_type=packet_type,
                sequence_number=sequence_number,
                attempt=attempt,
                dropped=dropped,
                corrupted=corrupted,
            )
        )
        if self._trace is not None:
            owner = self._stream_owner(packet_type, entity)
            self._emit(
                "send",
                self.time,
                owner,
                entity,
                packet_type=packet_type,
                seq_num=sequence_number,
                attempt=attempt,
                payload=self._payload_text(packet, packet_type),
                sent_bytes=bytes(packet),
                after_corrupt=self._reacting_corrupt,
            )

        if dropped:
            if self._trace is not None:
                # Show the loss at the arrival time it would have had, without
                # advancing the medium's serialization clock -- a dropped packet
                # never occupies a delivery slot.
                lost_at = (
                    max(self.time, self._last_network_arrival[receiver])
                    + self._network_delay
                )
                self._emit(
                    "net",
                    lost_at,
                    owner,
                    receiver,
                    packet_type=packet_type,
                    seq_num=sequence_number,
                    outcome="lost",
                    sent_bytes=bytes(packet),
                )
            return

        delivered_packet = self._corrupt(packet) if corrupted else bytes(packet)
        arrival_time = max(self.time, self._last_network_arrival[receiver])
        arrival_time += self._network_delay
        self._last_network_arrival[receiver] = arrival_time
        self._schedule(
            arrival_time,
            _EventKind.NETWORK,
            receiver,
            delivered_packet,
            corrupt=corrupted,
        )

        if self._trace is not None:
            self._emit(
                "net",
                arrival_time,
                owner,
                receiver,
                packet_type=packet_type,
                seq_num=sequence_number,
                outcome="corrupted" if corrupted else "intact",
                sent_bytes=bytes(packet),
                delivered_bytes=delivered_packet,
            )
            # Emit the receive eagerly, at arrival time, so it sorts ahead of
            # the reactions the host makes when the NETWORK event later fires.
            self._emit(
                "recv",
                arrival_time,
                owner,
                receiver,
                packet_type=packet_type,
                seq_num=sequence_number,
            )

    def pass_to_application_layer(self, entity: EventEntity, payload: str) -> None:
        """Record data delivered by a host to its local application."""

        self.delivered_payloads[entity].append(payload)
        self._emit(
            "app_up",
            self.time,
            self.opposite_entity(entity),
            entity,
            payload=payload,
        )

    def start_timer(self, entity: EventEntity, increment: float) -> None:
        """Start the endpoint's single Go-Back-N timer."""

        if self._timer_deadline[entity] is not None:
            self.timer_violations.append(f"{entity.name}: timer started while running")
            self._emit(
                "timer_warn",
                self.time,
                entity,
                entity,
                payload="started a timer while one was already running",
            )
            return
        self._timer_generation[entity] += 1
        generation = self._timer_generation[entity]
        deadline = self.time + increment
        self._timer_deadline[entity] = deadline
        self._emit("timer_start", self.time, entity, entity, timer_interval=increment)
        self._schedule(deadline, _EventKind.TIMER, entity, generation=generation)

    def stop_timer(self, entity: EventEntity) -> None:
        """Cancel the endpoint's current timer, if one exists."""

        if self._timer_deadline[entity] is None:
            self.timer_violations.append(f"{entity.name}: timer stopped while idle")
            self._emit(
                "timer_warn",
                self.time,
                entity,
                entity,
                payload="stopped a timer while none was running",
            )
            return
        self._timer_deadline[entity] = None
        self._timer_generation[entity] += 1
        self._emit("timer_stop", self.time, entity, entity)

    def attempts_for(
        self,
        sender: EventEntity,
        packet_type: int,
        sequence_number: int,
    ) -> int:
        """Return how many times a selected packet identity was transmitted."""

        return self._attempts[(sender, packet_type, sequence_number)]

    def run(self) -> "NetworkSimulator":
        """Process events until the simulation becomes quiescent."""

        while self._queue:
            event = heapq.heappop(self._queue)
            self.events_processed += 1
            if self.events_processed > self.max_events:
                raise RuntimeError(
                    "simulation exceeded its event limit; the protocol may not converge"
                )

            self.time = event.time
            host = self.hosts[event.entity]
            if event.kind == _EventKind.APPLICATION:
                self._emit(
                    "app_down",
                    self.time,
                    event.entity,
                    event.entity,
                    payload=event.value,
                )
                host.receive_from_application_layer(event.value)
            elif event.kind == _EventKind.NETWORK:
                self._reacting_corrupt = event.corrupt
                host.receive_from_network_layer(event.value)
                self._reacting_corrupt = False
            elif event.kind == _EventKind.TIMER:
                if event.generation != self._timer_generation[event.entity]:
                    continue
                if self._timer_deadline[event.entity] != event.time:
                    continue
                self._timer_deadline[event.entity] = None
                self._emit("timer_fire", self.time, event.entity, event.entity)
                host.timer_interrupt()

        return self

    @property
    def delivery_complete(self) -> bool:
        """Whether both receivers obtained the opposite sender's exact stream."""

        return (
            self.delivered_payloads[EventEntity.B]
            == self.sent_payloads[EventEntity.A]
            and self.delivered_payloads[EventEntity.A]
            == self.sent_payloads[EventEntity.B]
        )
