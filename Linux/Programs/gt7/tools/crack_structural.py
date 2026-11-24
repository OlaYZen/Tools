#!/usr/bin/env python3
"""Structural-oracle attack on an unknown GT7 packet format.

The earlier attack (tools/crack.py) tested candidates against the magic and
against the hardcoded 85.0/110.0 temperatures - both of which assume the
unknown format keeps format A's header and layout. If it does not, those
oracles are blind.

This one assumes nothing about layout. A correctly decrypted GT7 packet is
full of structural zeros (76 of 316 bytes in format B); ciphertext has none.
Counting zero bytes is therefore a sensitive, layout-free oracle: seeing >=12
zeros in 344 random bytes has probability ~1e-11, so even 1e8 trials expect
essentially no false positives.

It also tries nonce derivations the first tool did not: nonce bytes lifted
directly out of the packet, and seed-with-zero-word forms.
"""

from __future__ import annotations

import argparse
import itertools
import struct
import sys
from pathlib import Path

from Cryptodome.Cipher import Salsa20

BASE = b"Simulator Interface Packet GT7 ver 0.0"
ZERO_THRESHOLD = 12


def candidate_keys() -> list[tuple[bytes, str]]:
    seen: set[bytes] = set()
    out: list[tuple[bytes, str]] = []

    def add(raw: bytes, why: str) -> None:
        key = raw[:32]
        if len(key) == 32 and key not in seen:
            seen.add(key)
            out.append((key, why))

    add(BASE, "known GT7 key")
    for base in (BASE,
                 b"Simulator Interface Packet ver 0.0",
                 b"Simulator Interface Packet GT6 ver 0.0",
                 b"Simulator Interface Packet GTS ver 0.0",
                 b"Gran Turismo 7 Simulator Interface Packet"):
        for major, minor in itertools.product(range(3), range(10)):
            variant = base.replace(b"0.0", f"{major}.{minor}".encode())
            for start in range(max(1, len(variant) - 31)):
                add(variant[start:], f"{base[:20].decode()}… v{major}.{minor}+{start}")
    return out


def candidate_xors() -> list[int]:
    xors = {0xDEADBEAF, 0xDEADBEEF, 0x00000000, 0xFFFFFFFF, 0xCAFEBABE, 0xDEADC0DE}
    for low in range(256):
        xors.add(0xDEADBE00 | low)
        xors.add(0xDEAD00EF | (low << 8))
        xors.add((low << 24) | 0x00ADBEEF)
    return sorted(xors)


def nonces(data: bytes) -> list[tuple[bytes, str]]:
    """Every nonce we are willing to try, with a label for reporting."""
    out: list[tuple[bytes, str]] = []
    xors = candidate_xors()
    for offset in range(0, len(data) - 3, 4):
        (seed,) = struct.unpack_from("<I", data, offset)
        for xor in xors:
            mixed = seed ^ xor
            out.append((struct.pack("<II", mixed, seed), f"xor@{offset:#04x}^{xor:#010x}"))
            out.append((struct.pack("<II", seed, mixed), f"rxor@{offset:#04x}^{xor:#010x}"))
        out.append((struct.pack("<II", seed, 0), f"seed0@{offset:#04x}"))
        out.append((struct.pack("<II", 0, seed), f"0seed@{offset:#04x}"))
    # Nonce lifted verbatim out of the packet, at any byte offset.
    for offset in range(0, len(data) - 7):
        out.append((data[offset:offset + 8], f"direct@{offset:#04x}"))
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("packet")
    ap.add_argument("--threshold", type=int, default=ZERO_THRESHOLD)
    args = ap.parse_args()

    data = Path(args.packet).read_bytes()
    keys = candidate_keys()
    nonce_list = nonces(data)
    total = len(keys) * len(nonce_list)
    print(f"[*] {len(data)}-byte packet, {data.count(0)} zeros in ciphertext")
    print(f"[*] {len(keys)} keys x {len(nonce_list):,} nonces = {total:,} trials")
    print(f"[*] oracle: >= {args.threshold} zero bytes in the plaintext", flush=True)

    best = (0, "", "")
    hits = []
    for index, (key, why) in enumerate(keys):
        for nonce, label in nonce_list:
            plain = Salsa20.new(key=key, nonce=nonce).decrypt(data)
            zeros = plain.count(0)
            if zeros > best[0]:
                best = (zeros, why, label)
            if zeros >= args.threshold:
                hits.append((zeros, key, why, label))
                print(f"[+] HIT {zeros} zeros  key={key!r} ({why})  nonce={label}",
                      flush=True)
        if index % 10 == 0:
            print(f"    key {index}/{len(keys)}  best so far: {best[0]} zeros "
                  f"({best[2]})", flush=True)

    print(f"\n[*] best score: {best[0]} zero bytes via {best[1]} / {best[2]}")
    if hits:
        print(f"[+] {len(hits)} candidate(s)")
        return 0
    print("[-] nothing structural found; derivation is outside this search space")
    return 1


if __name__ == "__main__":
    sys.exit(main())
