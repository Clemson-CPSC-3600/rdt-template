"""Human-readable per-stream rendering of a ``NetworkSimulator`` trace.

A full-duplex run is split into two single-direction logs (A->B and B->A), each
rendered top-to-bottom in true simulated order.  The rendering is a pure
function of the observable :class:`TraceEvent` stream -- no host internal state
-- so a student's log and the reference log differ only where the two hosts
actually behaved differently.  :func:`diff_report` finds the first such line.
"""

from __future__ import annotations

from typing import Dict, List, Optional

from .network_simulator import (
    ACK_PACKET,
    DATA_PACKET,
    EventEntity,
    NetworkSimulator,
    TraceEvent,
)

MAX_UNSIGNED_INT = (1 << 32) - 1
_INDENT = " " * 18
_RULE = "─" * 74


def _seq(seq_num: Optional[int]) -> str:
    if seq_num is None or seq_num == MAX_UNSIGNED_INT:
        return "—"
    return str(seq_num)


def _type_name(packet_type: Optional[int]) -> str:
    if packet_type == DATA_PACKET:
        return "DATA"
    if packet_type == ACK_PACKET:
        return "ACK"
    return "????"


def _words(raw: Optional[bytes]) -> str:
    """Render raw bytes grouped into the 16-bit words the checksum sums over."""

    if not raw:
        return ""
    return " ".join(raw[i : i + 2].hex() for i in range(0, len(raw), 2))


def _fields(raw: Optional[bytes], packet_type: Optional[int]) -> str:
    """Decode the checksum (in decimal) and, for DATA, the length field.

    These are the two header fields the readable summary does not already show,
    so a packing or checksum bug is visible without hand-parsing the hex.
    """

    if not raw or len(raw) < 8:
        return ""
    checksum = int.from_bytes(raw[6:8], "big")
    if packet_type == DATA_PACKET and len(raw) >= 12:
        return f"len={int.from_bytes(raw[8:12], 'big')} cksum={checksum}"
    return f"cksum={checksum}"


def _byte_delta(sent: Optional[bytes], delivered: Optional[bytes]) -> str:
    if not sent or not delivered:
        return ""
    parts = [
        f"byte {i}: {sent[i]:02x}→{delivered[i]:02x}"
        for i in range(min(len(sent), len(delivered)))
        if sent[i] != delivered[i]
    ]
    if len(sent) != len(delivered):
        parts.append("length changed")
    return f"({', '.join(parts)})" if parts else ""


def _lane(event: TraceEvent) -> str:
    name = event.entity.name
    if event.kind == "app_down":
        return f"APP→{name}"
    if event.kind == "app_up":
        return f"{name}→APP"
    if event.kind == "net":
        return "NET"
    return name  # send / recv / timer_* -> the acting host


def _render_event(event: TraceEvent) -> List[str]:
    head = f"t={event.time:.3f}"
    prefix = f"{head:<9} {_lane(event):<6} "
    kind = event.kind

    if kind == "app_down":
        return [f'{prefix}queue   "{event.payload}"']
    if kind == "app_up":
        return [f'{prefix}deliver "{event.payload}"']
    if kind == "timer_start":
        return [f"{prefix}timer   start ({event.timer_interval:.3f}s)"]
    if kind == "timer_stop":
        return [f"{prefix}timer   stop"]
    if kind == "timer_fire":
        return [f"{prefix}timer   fires  → retransmit window"]
    if kind == "timer_warn":
        return [f"{prefix}timer   WARNING: {event.payload}"]

    tag = f"{_type_name(event.packet_type)} seq={_seq(event.seq_num)}"

    if kind == "send":
        detail = tag
        fields = _fields(event.sent_bytes, event.packet_type)
        if fields:
            detail += f" {fields}"
        if event.payload is not None:
            detail += f'  "{event.payload}"'
        if event.packet_type == DATA_PACKET and event.attempt is not None:
            detail += f"  attempt={event.attempt}"
        if event.after_corrupt:
            # The trigger (a corrupt packet whose type could not be trusted) may
            # live in the OTHER stream's log, so name the cause here.
            detail += "  (repeat — reacted to a corrupt packet)"
        return [f"{prefix}send    {detail}", f"{_INDENT}{_words(event.sent_bytes)}"]

    if kind == "recv":
        # No byte line: identical to the delivered bytes on the NET line above.
        return [f"{prefix}recv    {tag}"]

    if kind == "net":
        if event.outcome == "lost":
            fields = _fields(event.sent_bytes, event.packet_type)
            header = f"{prefix}{tag}" + (f" {fields}" if fields else "")
            lines = [f"{header}  LOST in transit  (never reaches {event.entity.name})"]
            if event.sent_bytes:
                lines.append(f"{_INDENT}{_words(event.sent_bytes)}")
            return lines
        if event.outcome == "corrupted":
            # The delivered packet's decoded fields are untrustworthy, so show
            # only the raw sent-vs-delivered bytes and which one changed.
            return [
                f"{prefix}{tag}  CORRUPTED in transit",
                f"{_INDENT}sent      {_words(event.sent_bytes)}",
                f"{_INDENT}delivered {_words(event.delivered_bytes)}   "
                f"{_byte_delta(event.sent_bytes, event.delivered_bytes)}",
            ]
        fields = _fields(event.delivered_bytes, event.packet_type)
        header = f"{prefix}{tag}" + (f" {fields}" if fields else "")
        return [
            f"{header}  delivered intact",
            f"{_INDENT}{_words(event.delivered_bytes)}",
        ]

    return [f"{prefix}{kind}"]


def render_stream(sim: NetworkSimulator, owner: EventEntity) -> str:
    """Render the one-direction log for the stream whose DATA sender is ``owner``."""

    peer = sim.opposite_entity(owner)
    lines = [
        f"STREAM {owner.name}→{peer.name}   "
        f"({owner.name} sends data · {peer.name} acknowledges)",
        _RULE,
    ]
    events = sorted(
        (event for event in sim.trace if event.owner == owner),
        key=lambda event: (event.time, event.order),
    )
    for event in events:
        lines.extend(_render_event(event))
    return "\n".join(lines) + "\n"


def render_all(sim: NetworkSimulator) -> Dict[EventEntity, str]:
    """Return both stream logs, keyed by the stream's DATA sender."""

    return {owner: render_stream(sim, owner) for owner in (EventEntity.A, EventEntity.B)}


def first_divergence(yours: str, reference: str) -> Optional[int]:
    """Zero-based index of the first line that differs, or ``None`` if identical."""

    mine = yours.splitlines()
    theirs = reference.splitlines()
    for index in range(max(len(mine), len(theirs))):
        left = mine[index] if index < len(mine) else None
        right = theirs[index] if index < len(theirs) else None
        if left != right:
            return index
    return None


def diff_report(yours: str, reference: str, label: str) -> str:
    """One-line-per-stream verdict pointing at the first divergence, if any."""

    index = first_divergence(yours, reference)
    if index is None:
        return f"{label}: ✓ matches reference ({len(reference.splitlines())} lines)"
    mine = yours.splitlines()
    theirs = reference.splitlines()
    return "\n".join(
        [
            f"{label}: ✗ first divergence at line {index + 1}",
            f"    reference: {theirs[index] if index < len(theirs) else '(end of log)'}",
            f"    yours:     {mine[index] if index < len(mine) else '(end of log)'}",
        ]
    )
