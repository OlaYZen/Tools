#!/usr/bin/env python3
"""Search for the key / nonce derivation of an unknown GT7 packet format.

This is the tool that recovered format B's `0xDEADBEEF` constant, kept so the
344-byte `~` format can be attacked further. It brute-forces
(key x nonce-seed offset x XOR constant x word order) and tests each candidate
with two oracles that do not assume anything about the layout beyond the
header:

  magic  - plaintext[0:4] is b"<digit>S7G"
  temps  - the game's hardcoded water 85.0 / oil 110.0 at 0x58 / 0x5C

Usage:
    python tools/crack.py captures/tilde_344.bin [--wide]

Exit status is 0 if a candidate was found, 1 otherwise.
"""

from __future__ import annotations

import argparse
import itertools
import struct
import sys
from pathlib import Path

from Cryptodome.Cipher import Salsa20

BASE = b"Simulator Interface Packet GT7 ver 0.0"


def candidate_keys(wide: bool) -> list[tuple[bytes, str]]:
    seen: set[bytes] = set()
    out: list[tuple[bytes, str]] = []

    def add(raw: bytes, why: str) -> None:
        key = raw[:32]
        if len(key) == 32 and key not in seen:
            seen.add(key)
            out.append((key, why))

    add(BASE, "known GT7 key")
    bases = [BASE]
    if wide:
        bases += [
            b"Simulator Interface Packet ver 0.0",
            b"Simulator Interface Packet GT6 ver 0.0",
            b"Simulator Interface Packet GTS ver 0.0",
            b"Gran Turismo 7 Simulator Interface Packet",
        ]
    for base in bases:
        for major, minor in itertools.product(range(3), range(10)):
            variant = base.replace(b"0.0", f"{major}.{minor}".encode())
            # Every 32-byte window, in case the game slices the string elsewhere.
            for start in range(max(1, len(variant) - 31)):
                add(variant[start:], f"{base[:26].decode()}… ver {major}.{minor} +{start}")
    return out


def candidate_xors(wide: bool) -> list[int]:
    xors = {0xDEADBEAF, 0xDEADBEEF, 0x00000000, 0xFFFFFFFF, 0xCAFEBABE, 0xDEADC0DE}
    for low in range(256):
        xors.add(0xDEADBE00 | low)
        xors.add(0xDEAD00EF | (low << 8))
        xors.add((low << 24) | 0x00ADBEEF)
    if wide:
        # The whole 0xDEADxxxx family.
        xors.update(range(0xDEAD0000, 0xDEAE0000))
    return sorted(xors)


def check(plain: bytes) -> str | None:
    if plain[1:4] == b"S7G" and 0x30 <= plain[0] <= 0x39:
        return "magic"
    if len(plain) >= 0x60:
        water, oil = struct.unpack_from("<ff", plain, 0x58)
        if water == 85.0 and oil == 110.0:
            return "temps"
    return None


def crack(data: bytes, wide: bool) -> list[tuple[str, ...]]:
    keys = candidate_keys(wide)
    xors = candidate_xors(wide)
    offsets = range(0, len(data) - 3, 4)
    total = len(keys) * len(xors) * len(offsets) * 2
    print(f"[*] {len(data)}-byte packet: {len(keys)} keys x {len(offsets)} offsets "
          f"x {len(xors)} constants x 2 orders = {total:,} trials", flush=True)

    hits = []
    for index, (key, why) in enumerate(keys):
        for offset in offsets:
            (seed,) = struct.unpack_from("<I", data, offset)
            for xor in xors:
                mixed = seed ^ xor
                for nonce in (struct.pack("<II", mixed, seed),
                              struct.pack("<II", seed, mixed)):
                    plain = Salsa20.new(key=key, nonce=nonce).decrypt(data)
                    oracle = check(plain)
                    if oracle:
                        hit = (repr(key), why, f"0x{offset:02x}", f"0x{xor:08x}",
                               nonce.hex(), oracle)
                        hits.append(hit)
                        print(f"[+] HIT key={key!r} ({why}) seed@{offset:#04x} "
                              f"xor={xor:#010x} via {oracle}", flush=True)
        if index % 20 == 0:
            print(f"    key {index}/{len(keys)}  hits={len(hits)}", flush=True)
    return hits


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("packet", help="file holding one raw (encrypted) datagram")
    ap.add_argument("--wide", action="store_true",
                    help="much larger search: extra key families and all 0xDEADxxxx")
    args = ap.parse_args()

    data = Path(args.packet).read_bytes()
    hits = crack(data, args.wide)
    if hits:
        print(f"\n[+] {len(hits)} candidate(s) found")
        return 0
    print("\n[-] no candidate found; the derivation is outside this search space")
    return 1


if __name__ == "__main__":
    sys.exit(main())
