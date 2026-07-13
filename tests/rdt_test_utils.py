"""Shared fixtures and behavioral assertions for the assignment tests."""

from __future__ import annotations

import struct

from rdt_support import EventEntity, NetworkSimulator


class RecordingSimulator:
    """Small callback recorder for sender/receiver state-machine unit tests."""

    def __init__(self):
        self.network_packets = []
        self.application_payloads = []
        self.timer_starts = []
        self.timer_stops = []
        self.timer_calls = []

    def pass_to_network_layer(self, entity, packet):
        self.network_packets.append((entity, packet))

    def pass_to_application_layer(self, entity, payload):
        self.application_payloads.append((entity, payload))

    def start_timer(self, entity, increment):
        self.timer_starts.append((entity, increment))
        self.timer_calls.append(("start", entity, increment))

    def stop_timer(self, entity):
        self.timer_stops.append(entity)
        self.timer_calls.append(("stop", entity))


def packet_identity(packet):
    """Return ``(packet_type, sequence_number)`` from a wire packet."""

    return struct.unpack("!HI", packet[:6])


def run_simulation(messages_from_a, messages_from_b=(), **kwargs):
    """Run the student's host type in the deterministic project simulator."""

    from src.gbn_host import GBNHost

    simulator = NetworkSimulator(
        GBNHost,
        messages_from_a,
        messages_from_b,
        **kwargs,
    )
    return simulator.run()


def assert_exact_full_duplex_delivery(simulator):
    """Require ordered, duplicate-free delivery in both directions."""

    assert simulator.delivered_payloads[EventEntity.B] == simulator.sent_payloads[
        EventEntity.A
    ], "B must receive A's messages once each and in their original order"
    assert simulator.delivered_payloads[EventEntity.A] == simulator.sent_payloads[
        EventEntity.B
    ], "A must receive B's messages once each and in their original order"
    assert simulator.delivery_complete
    assert simulator.timer_violations == []


def assert_fault_plan_activated(simulator, faults):
    """Require every configured fault attempt to appear in the event trace."""

    for fault_mapping, flag_name in (
        (faults.drop_attempts, "dropped"),
        (faults.corrupt_attempts, "corrupted"),
    ):
        for (sender, packet_type, sequence_number), attempt_count in fault_mapping.items():
            activated_attempts = {
                transmission.attempt
                for transmission in simulator.transmissions
                if transmission.sender == sender
                and transmission.packet_type == packet_type
                and transmission.sequence_number == sequence_number
                and getattr(transmission, flag_name)
            }
            expected_attempts = set(range(1, int(attempt_count) + 1))
            assert expected_attempts <= activated_attempts, (
                f"fault did not activate for {(sender, packet_type, sequence_number)}: "
                f"expected {flag_name} attempts {sorted(expected_attempts)}, "
                f"observed {sorted(activated_attempts)}"
            )
