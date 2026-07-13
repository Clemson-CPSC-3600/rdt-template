"""Bundle 1 checks for packet encoding, parsing, and corruption detection."""

import struct

import pytest


def _host():
    from src.gbn_host import GBNHost

    return GBNHost(None, None, 2.0, 5)


@pytest.mark.bundle(1)
def test_internet_checksum_known_vector_and_carry():
    host = _host()
    data = bytes.fromhex("0001f203f4f5f6f7")
    assert host.create_checksum(data) == 0x220D
    assert host.create_checksum(bytes.fromhex("010203")) == 0xFBFD


@pytest.mark.bundle(1)
def test_data_packet_round_trip_uses_network_byte_order():
    host = _host()
    packet = host.create_data_pkt(7, "hello")
    packet_type, sequence, checksum, length = struct.unpack("!HIHI", packet[:12])

    assert packet_type == 0
    assert sequence == 7
    assert length == 5
    assert checksum != 0
    assert packet[12:] == b"hello"
    unpacked = host.unpack_pkt(packet)
    assert unpacked["packet_type"] == 0
    assert unpacked["seq_num"] == 7
    assert unpacked["checksum"] == checksum
    assert unpacked["payload_length"] == 5
    assert unpacked["payload"] == "hello"
    assert not host.is_corrupt(packet)


@pytest.mark.bundle(1)
@pytest.mark.parametrize(
    ("payload", "expected_length"),
    [("", 0), ("é🙂", 6)],
    ids=["empty", "multibyte-utf8"],
)
def test_data_packet_length_counts_encoded_utf8_bytes(payload, expected_length):
    host = _host()
    encoded = payload.encode("utf-8")

    packet = host.create_data_pkt(8, payload)
    packet_type, sequence, _, length = struct.unpack("!HIHI", packet[:12])

    assert packet_type == 0
    assert sequence == 8
    assert length == len(encoded) == expected_length
    assert packet[12:] == encoded
    assert host.unpack_pkt(packet)["payload"] == payload
    assert not host.is_corrupt(packet)


@pytest.mark.bundle(1)
def test_ack_packet_round_trip_has_no_payload():
    host = _host()
    packet = host.create_ack_pkt(23)
    packet_type, sequence, checksum = struct.unpack("!HIH", packet)

    assert len(packet) == 8
    assert packet_type == 1
    assert sequence == 23
    unpacked = host.unpack_pkt(packet)
    assert unpacked["packet_type"] == 1
    assert unpacked["seq_num"] == 23
    assert unpacked["checksum"] == checksum
    assert not host.is_corrupt(packet)


@pytest.mark.bundle(1)
def test_bit_flip_is_detected_without_altering_original_packet():
    host = _host()
    packet = host.create_data_pkt(3, "checksum-me")
    damaged = bytearray(packet)
    damaged[-1] ^= 0x04

    assert not host.is_corrupt(packet)
    assert host.is_corrupt(bytes(damaged))


@pytest.mark.bundle(3)
@pytest.mark.parametrize(
    "packet",
    [
        b"",
        b"\x00",
        struct.pack("!HIH", 1, 4, 0) + b"extra",
        struct.pack("!HIHI", 0, 4, 0, 20) + b"short",
    ],
    ids=["empty", "partial-type", "ack-with-trailing-data", "bad-data-length"],
)
def test_malformed_packet_shapes_are_ignored_by_the_endpoint(packet):
    from rdt_support import EventEntity
    from src.gbn_host import GBNHost
    from tests.rdt_test_utils import RecordingSimulator

    simulator = RecordingSimulator()
    host = GBNHost(simulator, EventEntity.A, 2.0, 5)

    host.receive_from_network_layer(packet)

    assert simulator.application_payloads == []
