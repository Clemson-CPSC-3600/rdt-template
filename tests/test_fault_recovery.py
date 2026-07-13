"""Bundle 3 checks for deterministic corruption and combined fault recovery."""

import struct

import pytest

from rdt_support import ACK_PACKET, DATA_PACKET, EventEntity, FaultPlan
from tests.rdt_test_utils import (
    assert_exact_full_duplex_delivery,
    assert_fault_plan_activated,
    packet_identity,
    RecordingSimulator,
    run_simulation,
)


FAULT_SCENARIOS = [
    pytest.param(
        FaultPlan(corrupt_attempts={(EventEntity.A, DATA_PACKET, 2): 1}),
        id="corrupted-data",
    ),
    pytest.param(
        FaultPlan(corrupt_attempts={(EventEntity.B, ACK_PACKET, 1): 1}),
        id="corrupted-ack",
    ),
    pytest.param(
        FaultPlan(drop_attempts={(EventEntity.A, DATA_PACKET, 1): 2}),
        id="sustained-data-loss",
    ),
    pytest.param(
        FaultPlan(
            drop_attempts={
                (EventEntity.A, DATA_PACKET, 0): 1,
                (EventEntity.B, DATA_PACKET, 3): 1,
            },
            corrupt_attempts={
                (EventEntity.A, ACK_PACKET, 2): 1,
                (EventEntity.B, ACK_PACKET, 2): 1,
            },
        ),
        id="combined-full-duplex-faults",
    ),
]


@pytest.mark.bundle(3)
@pytest.mark.parametrize("faults", FAULT_SCENARIOS)
def test_exact_delivery_under_deterministic_faults(faults):
    messages_a = tuple(f"A-{index}" for index in range(8))
    messages_b = tuple(f"B-{index}" for index in range(7))
    simulator = run_simulation(
        messages_a,
        messages_b,
        faults=faults,
        arrival_interval=0.01,
        timer_interval=2.0,
    )

    assert_exact_full_duplex_delivery(simulator)
    assert_fault_plan_activated(simulator, faults)
    assert simulator.events_processed < simulator.max_events


@pytest.mark.bundle(3)
def test_corrupt_future_duplicate_and_malformed_acks_do_not_open_the_window():
    from src.gbn_host import GBNHost

    simulator = RecordingSimulator()
    sender = GBNHost(simulator, EventEntity.A, 2.0, 3)
    for payload in ("zero", "one", "two", "three", "four"):
        sender.receive_from_application_layer(payload)
    simulator.network_packets.clear()

    sender.receive_from_network_layer(sender.create_ack_pkt(4))
    sender.receive_from_network_layer(sender.create_ack_pkt(0) + b"extra")

    stale_checksum_ack = bytearray(sender.create_ack_pkt(0))
    struct.pack_into("!I", stale_checksum_ack, 2, 1)
    sender.receive_from_network_layer(bytes(stale_checksum_ack))

    assert simulator.network_packets == []

    sender.receive_from_network_layer(sender.create_ack_pkt(0))
    sender.receive_from_network_layer(sender.create_ack_pkt(0))
    assert [
        packet_identity(packet) for _, packet in simulator.network_packets
    ] == [(DATA_PACKET, 3)]


@pytest.mark.bundle(3)
def test_corrupt_and_malformed_data_repeat_the_last_cumulative_ack():
    from src.gbn_host import GBNHost

    simulator = RecordingSimulator()
    receiver = GBNHost(simulator, EventEntity.B, 2.0, 4)

    corrupt_zero = bytearray(receiver.create_data_pkt(0, "zero"))
    corrupt_zero[-1] ^= 0x01

    malformed_zero = bytearray(receiver.create_data_pkt(0, "zero"))
    struct.pack_into("!H", malformed_zero, 6, 0)
    struct.pack_into("!I", malformed_zero, 8, 5)
    checksum = receiver.create_checksum(bytes(malformed_zero))
    struct.pack_into("!H", malformed_zero, 6, checksum)

    receiver.receive_from_network_layer(bytes(corrupt_zero))
    receiver.receive_from_network_layer(bytes(malformed_zero))

    invalid_utf8_zero = bytearray(struct.pack("!HIHI1s", 0, 0, 0, 1, b"\xff"))
    checksum = receiver.create_checksum(bytes(invalid_utf8_zero))
    struct.pack_into("!H", invalid_utf8_zero, 6, checksum)
    receiver.receive_from_network_layer(bytes(invalid_utf8_zero))

    receiver.receive_from_network_layer(receiver.create_data_pkt(0, "zero"))

    corrupt_one = bytearray(receiver.create_data_pkt(1, "one"))
    corrupt_one[-1] ^= 0x01
    malformed_one = bytearray(receiver.create_data_pkt(1, "one"))
    struct.pack_into("!H", malformed_one, 6, 0)
    struct.pack_into("!I", malformed_one, 8, 4)
    checksum = receiver.create_checksum(bytes(malformed_one))
    struct.pack_into("!H", malformed_one, 6, checksum)

    receiver.receive_from_network_layer(bytes(corrupt_one))
    receiver.receive_from_network_layer(bytes(malformed_one))

    sentinel = (ACK_PACKET, (1 << 32) - 1)
    assert simulator.application_payloads == [(EventEntity.B, "zero")]
    assert [
        packet_identity(packet) for _, packet in simulator.network_packets
    ] == [
        sentinel,
        sentinel,
        sentinel,
        (ACK_PACKET, 0),
        (ACK_PACKET, 0),
        (ACK_PACKET, 0),
    ]


@pytest.mark.bundle(3)
def test_unknown_packet_type_is_ignored_without_delivery_or_ack():
    from src.gbn_host import GBNHost

    simulator = RecordingSimulator()
    receiver = GBNHost(simulator, EventEntity.B, 2.0, 4)
    unknown = bytearray(struct.pack("!HIH", 9, 0, 0))
    checksum = receiver.create_checksum(bytes(unknown))
    struct.pack_into("!H", unknown, 6, checksum)

    receiver.receive_from_network_layer(bytes(unknown))

    assert simulator.application_payloads == []
    assert simulator.network_packets == []


@pytest.mark.bundle(3)
def test_out_of_order_data_is_not_delivered_or_buffered():
    from src.gbn_host import GBNHost

    simulator = RecordingSimulator()
    receiver = GBNHost(simulator, EventEntity.B, 2.0, 4)

    receiver.receive_from_network_layer(receiver.create_data_pkt(1, "future"))
    assert simulator.application_payloads == []
    assert [
        packet_identity(packet) for _, packet in simulator.network_packets
    ] == [(ACK_PACKET, (1 << 32) - 1)]

    receiver.receive_from_network_layer(receiver.create_data_pkt(0, "first"))
    assert simulator.application_payloads == [(EventEntity.B, "first")]
    assert [
        packet_identity(packet) for _, packet in simulator.network_packets
    ] == [(ACK_PACKET, (1 << 32) - 1), (ACK_PACKET, 0)]


@pytest.mark.bundle(3)
def test_duplicate_data_is_acknowledged_but_delivered_only_once():
    from src.gbn_host import GBNHost

    simulator = RecordingSimulator()
    receiver = GBNHost(simulator, EventEntity.B, 2.0, 4)
    packet = receiver.create_data_pkt(0, "once")

    receiver.receive_from_network_layer(packet)
    receiver.receive_from_network_layer(packet)

    assert simulator.application_payloads == [(EventEntity.B, "once")]
    assert [
        packet_identity(packet) for _, packet in simulator.network_packets
    ] == [(ACK_PACKET, 0), (ACK_PACKET, 0)]
