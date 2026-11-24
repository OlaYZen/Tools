# Sample captures

Raw (still encrypted) datagrams, straight off the wire.

| File | Format | Notes |
|---|---|---|
| `format_b_316.bin` | B, 316 B | decrypts with key + XOR `0xDEADBEEF` |
| `tilde_344.bin` | `~`, 344 B | **not decryptable** — target for `tools/crack.py` |

```bash
python tools/crack.py captures/tilde_344.bin --wide
```
