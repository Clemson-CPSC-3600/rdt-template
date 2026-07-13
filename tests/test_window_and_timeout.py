"""Bundle 2 checks for window discipline and Go-Back-N retransmission."""

import pytest

from rdt_support import ACK_PACKET, DATA_PACKET, EventEntity, FaultPlan
from tests.rdt_test_utils import (
    RecordingSimulator,
    assert_exact_full_duplex_delivery,
    packet_identity,
    run_simulation,
)


WINDOW_BOUNDARY_CASES = [
    pytest.param(1, 0, id="window-1-empty"),
    pytest.param(1, 1, id="window-1-full"),
    pytest.param(1, 2, id="window-1-plus-one"),
    pytest.param(2, 0, id="window-2-empty"),
    pytest.param(2, 1, id="window-2-one"),
    pytest.param(2, 2, id="window-2-full"),
    pytest.param(2, 3, id="window-2-plus-one"),
    pytest.param(5, 0, id="window-5-empty"),
    pytest.param(5, 1, id="window-5-one"),
    pytest.param(5, 5, id="window-5-full"),
    pytest.param(5, 6, id="window-5-plus-one"),
]


@pytest.mark.bundle(2)
@pytest.mark.parametrize(("window_size", "message_count"), WINDOW_BOUNDARY_CASES)
def test_sender_respects_small_window_boundaries(window_size, message_count):
    from src.gbn_host import GBNHost

    simulator = RecordingSimulator()
    host = GBNHost(simulator, EventEntity.A, 2.0, window_size)
    for sequence_number in range(message_count):
        host.receive_from_application_layer(f"payload-{sequence_number}")

    assert [
        packet_identity(packet) for _, packet in simulator.network_packets
    ] == [
        (DATA_PACKET, sequence_number)
        for sequence_number in range(min(window_size, message_count))
    ]


@pytest.mark.bundle(2)
@pytest.mark.parametrize("window_size", [1, 2, 5])
def test_burst_delivery_crosses_each_window_boundary(window_size):
    messages = tuple(f"payload-{index}" for index in range(window_size + 1))

    simulator = run_simulation(
        messages,
        window_size=window_size,
        arrival_interval=0.0,
        timer_interval=1.0,
    )

    assert_exact_full_duplex_delivery(simulator)


@pytest.mark.bundle(2)
def test_sender_buffers_messages_beyond_the_window():
    from src.gbn_host import GBNHost

    simulator = RecordingSimulator()
    host = GBNHost(simulator, EventEntity.A, 2.0, 3)
    for payload in ("zero", "one", "two", "three", "four", "five", "six"):
        host.receive_from_application_layer(payload)

    identities = [packet_identity(packet) for _, packet in simulator.network_packets]
    assert identities == [(DATA_PACKET, 0), (DATA_PACKET, 1), (DATA_PACKET, 2)]
    assert simulator.timer_starts == [(EventEntity.A, 2.0)]


@pytest.mark.bundle(2)
def test_cumulative_ack_opens_multiple_window_slots():
    from src.gbn_host import GBNHost

    simulator = RecordingSimulator()
    host = GBNHost(simulator, EventEntity.A, 2.0, 3)
    for payload in ("zero", "one", "two", "three", "four", "five", "six"):
        host.receive_from_application_layer(payload)

    host.receive_from_network_layer(host.create_ack_pkt(1))
    identities = [packet_identity(packet) for _, packet in simulator.network_packets]

    assert identities[-2:] == [(DATA_PACKET, 3), (DATA_PACKET, 4)]

    host.receive_from_network_layer(host.create_ack_pkt(4))
    identities = [packet_identity(packet) for _, packet in simulator.network_packets]
    assert identities[-2:] == [(DATA_PACKET, 5), (DATA_PACKET, 6)]


@pytest.mark.bundle(2)
def test_timeout_retransmits_the_entire_outstanding_window():
    from src.gbn_host import GBNHost

    simulator = RecordingSimulator()
    host = GBNHost(simulator, EventEntity.A, 2.0, 3)
    for payload in ("zero", "one", "two"):
        host.receive_from_application_layer(payload)

    simulator.network_packets.clear()
    host.timer_interrupt()
    retransmissions = [
        packet_identity(packet) for _, packet in simulator.network_packets
    ]

    assert retransmissions == [(DATA_PACKET, 0), (DATA_PACKET, 1), (DATA_PACKET, 2)]
    assert simulator.timer_starts == [
        (EventEntity.A, 2.0),
        (EventEntity.A, 2.0),
    ]


@pytest.mark.bundle(2)
def test_timer_lifecycle_follows_the_oldest_outstanding_packet():
    from src.gbn_host import GBNHost

    simulator = RecordingSimulator()
    host = GBNHost(simulator, EventEntity.A, 2.5, 3)
    for payload in ("zero", "one", "two"):
        host.receive_from_application_layer(payload)

    assert simulator.timer_calls == [("start", EventEntity.A, 2.5)]

    host.receive_from_network_layer(host.create_ack_pkt(0))
    assert simulator.timer_calls == [
        ("start", EventEntity.A, 2.5),
        ("stop", EventEntity.A),
        ("start", EventEntity.A, 2.5),
    ]

    calls_after_partial_ack = list(simulator.timer_calls)
    host.receive_from_network_layer(host.create_ack_pkt(0))
    host.receive_from_network_layer(host.create_ack_pkt(8))
    corrupt_ack = bytearray(host.create_ack_pkt(1))
    corrupt_ack[-1] ^= 0x01
    host.receive_from_network_layer(bytes(corrupt_ack))
    assert simulator.timer_calls == calls_after_partial_ack

    host.receive_from_network_layer(host.create_ack_pkt(2))
    assert simulator.timer_calls == [
        ("start", EventEntity.A, 2.5),
        ("stop", EventEntity.A),
        ("start", EventEntity.A, 2.5),
        ("stop", EventEntity.A),
    ]


@pytest.mark.bundle(2)
def test_single_data_loss_recovers_by_go_back_n_timeout():
    messages = tuple(f"payload-{index}" for index in range(9))
    faults = FaultPlan(
        drop_attempts={(EventEntity.A, DATA_PACKET, 1): 1},
    )
    simulator = run_simulation(
        messages,
        faults=faults,
        arrival_interval=0.01,
        timer_interval=1.0,
    )

    assert_exact_full_duplex_delivery(simulator)
    assert simulator.attempts_for(EventEntity.A, DATA_PACKET, 1) >= 2


@pytest.mark.bundle(2)
def test_lost_final_ack_is_recovered_by_retransmitting_data():
    messages = tuple(f"payload-{index}" for index in range(6))
    faults = FaultPlan(
        drop_attempts={(EventEntity.B, ACK_PACKET, 5): 1},
    )
    simulator = run_simulation(
        messages,
        faults=faults,
        arrival_interval=0.02,
        timer_interval=1.0,
    )

    assert_exact_full_duplex_delivery(simulator)
    assert simulator.attempts_for(EventEntity.A, DATA_PACKET, 5) >= 2
    assert simulator.attempts_for(EventEntity.B, ACK_PACKET, 5) >= 2
