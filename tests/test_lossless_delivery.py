"""Bundle 1 checks for the baseline full-duplex Go-Back-N behavior."""

import pytest

from rdt_support import DATA_PACKET, EventEntity
from tests.rdt_test_utils import assert_exact_full_duplex_delivery, run_simulation


@pytest.mark.bundle(1)
def test_lossless_delivery_in_both_directions():
    messages_a = ("alpha", "bravo", "charlie", "delta")
    messages_b = ("one", "two", "three")
    simulator = run_simulation(
        messages_a,
        messages_b,
        arrival_interval=0.5,
        timer_interval=2.0,
    )

    assert_exact_full_duplex_delivery(simulator)
    assert simulator.timer_violations == []


@pytest.mark.bundle(1)
def test_lossless_packets_do_not_need_retransmission():
    messages = tuple(f"message-{index}" for index in range(7))
    simulator = run_simulation(
        messages,
        arrival_interval=0.3,
        timer_interval=2.0,
    )

    assert_exact_full_duplex_delivery(simulator)
    for sequence_number in range(len(messages)):
        assert simulator.attempts_for(
            EventEntity.A,
            DATA_PACKET,
            sequence_number,
        ) == 1


@pytest.mark.bundle(1)
def test_empty_stream_is_a_valid_completed_simulation():
    simulator = run_simulation((), ())
    assert_exact_full_duplex_delivery(simulator)
    assert simulator.events_processed == 0


@pytest.mark.bundle(1)
def test_lossless_delivery_preserves_empty_unicode_and_duplicate_values():
    messages_a = ("same", "same", "", "é🙂", "same")
    messages_b = ("🙂", "", "🙂", "naïve")

    simulator = run_simulation(
        messages_a,
        messages_b,
        arrival_interval=0.05,
        timer_interval=2.0,
    )

    assert_exact_full_duplex_delivery(simulator)
    assert simulator.timer_violations == []
