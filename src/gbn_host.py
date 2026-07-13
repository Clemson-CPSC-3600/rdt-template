"""Student starter for a full-duplex Go-Back-N protocol endpoint.

Read PROTOCOL.md before implementing these methods.  Keep the public class,
method names, constructor signature, and packet formats unchanged; you may add
private helper methods and state as needed.
"""

from __future__ import annotations

import struct
from enum import IntEnum


MAX_UNSIGNED_INT = (1 << 32) - 1
DATA_HEADER_FORMAT = "!HIHI"
ACK_FORMAT = "!HIH"
DATA_HEADER_SIZE = struct.calcsize(DATA_HEADER_FORMAT)
ACK_SIZE = struct.calcsize(ACK_FORMAT)


class PacketType(IntEnum):
    DATA = 0
    ACK = 1


class GBNHost:
    """One endpoint containing both the sender and receiver GBN state."""

    def __init__(self, simulator, entity, timer_interval, window_size):
        self.simulator = simulator
        self.entity = entity
        self.timer_interval = timer_interval
        self.window_size = window_size

        # Sender state.  A dictionary avoids treating absolute sequence
        # numbers as indexes into a fixed-size list.
        self.window_base = 0
        self.next_seq_num = 0
        self.unacked_buffer = {}
        self.app_layer_buffer = []

        # Receiver state.  Initialize last_ack_pkt after create_ack_pkt works.
        self.expected_seq_num = 0
        self.last_ack_pkt = None

    def receive_from_application_layer(self, payload):
        """Buffer and send application data while space remains in the window."""

        raise NotImplementedError

    def receive_from_network_layer(self, packet):
        """Handle one DATA or ACK packet received from the network."""

        raise NotImplementedError

    def timer_interrupt(self):
        """Retransmit the outstanding Go-Back-N window after a timeout."""

        raise NotImplementedError

    def create_data_pkt(self, seq_num, payload):
        """Return a DATA ``bytes`` packet for integer ``seq_num`` and string payload."""

        raise NotImplementedError

    def create_ack_pkt(self, seq_num):
        """Return an ACK ``bytes`` packet for integer ``seq_num``."""

        raise NotImplementedError

    def create_checksum(self, packet):
        """Return the integer 16-bit Internet checksum for packet ``bytes``."""

        raise NotImplementedError

    def unpack_pkt(self, packet):
        """Return the documented DATA or ACK fields as a dictionary."""

        raise NotImplementedError

    def is_corrupt(self, packet):
        """Return whether packet ``bytes`` fail the Internet checksum."""

        raise NotImplementedError
