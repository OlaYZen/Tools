"""Salsa20 layer of the GT7 Simulator Interface protocol.

Every telemetry datagram the PS5 emits is Salsa20-encrypted.  The key is a
fixed ASCII string baked into the game; the nonce is derived per-packet from
a 32-bit seed the console leaves *in the clear* at offset 0x40 of the
ciphertext.

    nonce = LE32(seed ^ XOR) || LE32(seed)

The XOR constant is what distinguishes the packet formats, and it is the one
piece that is *not* shared between them:

    format A (296 B, heartbeat 'A')  ->  0xDEADBEAF
    format B (316 B, heartbeat 'B')  ->  0xDEADBEEF

Both were confirmed live against a PS5 (see README "Evidence").  Note the
one-letter difference: A uses the misspelled BEAF, B uses the real BEEF.

A successful decrypt is self-verifying twice over: plaintext[0:4] must be the
magic b"0S7G" (0x47375330 as a little-endian u32), and the game hardcodes
water temp 85.0 / oil temp 110.0 at 0x58/0x5C.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass

from Cryptodome.Cipher import Salsa20

#: The key is the 32-byte prefix of this 37-byte string.
KEY_STRING = b"Simulator Interface Packet GT7 ver 0.0"
KEY = KEY_STRING[:32]

#: Offset of the clear-text nonce seed inside the ciphertext.
IV_OFFSET = 0x40

#: plaintext[0:4] of a valid packet, as a little-endian u32.
MAGIC = 0x47375330


@dataclass(frozen=True, slots=True)
class PacketFormat:
    """One negotiated wire format."""

    name: str
    heartbeat: bytes  #: byte to send to the console to request this format
    size: int  #: exact datagram length
    iv_xor: int  #: nonce-derivation constant
    cracked: bool = True
    note: str = ""


FORMAT_A = PacketFormat("A", b"A", 296, 0xDEADBEAF, note="classic; universally supported")
FORMAT_B = PacketFormat("B", b"B", 316, 0xDEADBEEF, note="A + 5 motion/steering floats")
#: Requested with '~'.  The console answers, but the nonce derivation is not
#: known - see README.  Kept here so the CLI can still probe and dump it.
FORMAT_TILDE = PacketFormat(
    "~", b"~", 344, 0, cracked=False, note="uncracked: nonce derivation unknown"
)

FORMATS = (FORMAT_A, FORMAT_B, FORMAT_TILDE)
BY_NAME = {f.name: f for f in FORMATS}
BY_SIZE = {f.size: f for f in FORMATS}


class DecryptionError(ValueError):
    """Raised when a datagram does not decrypt to a valid GT7 packet."""


def format_for(payload: bytes) -> PacketFormat | None:
    """Identify a datagram's format by its length."""
    return BY_SIZE.get(len(payload))


def decrypt(payload: bytes, iv_xor: int | None = None) -> bytes:
    """Decrypt one raw datagram and verify its magic.

    `iv_xor` defaults to the constant for the format implied by the packet
    length, so a caller can hand over datagrams during a format switch (the
    console keeps streaming the old format for ~10s) without special-casing.
    """
    if len(payload) < IV_OFFSET + 4:
        raise DecryptionError(f"packet too short: {len(payload)} bytes")

    if iv_xor is None:
        fmt = format_for(payload)
        if fmt is None:
            raise DecryptionError(f"unknown packet size {len(payload)}")
        if not fmt.cracked:
            raise DecryptionError(
                f"format {fmt.name} ({fmt.size} B) is not decryptable: {fmt.note}"
            )
        iv_xor = fmt.iv_xor

    (seed,) = struct.unpack_from("<I", payload, IV_OFFSET)
    nonce = struct.pack("<II", seed ^ iv_xor, seed)
    plain = Salsa20.new(key=KEY, nonce=nonce).decrypt(payload)

    (magic,) = struct.unpack_from("<I", plain, 0)
    if magic != MAGIC:
        raise DecryptionError(
            f"bad magic 0x{magic:08x} (expected 0x{MAGIC:08x}) "
            "- wrong IV constant, game version, or not a GT7 packet"
        )
    return plain
