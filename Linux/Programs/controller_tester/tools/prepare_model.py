#!/usr/bin/env python3
"""Shrink the textures inside a .glb so it loads fast and uses less GPU memory.

    python3 tools/prepare_model.py ~/Downloads/playstation_5_dualsense.glb models/dualsense.glb --size 2048

Geometry is copied untouched; only embedded images are resized (PNG stays PNG,
JPEG stays JPEG).
"""
import argparse, io, json, struct
from PIL import Image


def read_glb(path):
    data = open(path, "rb").read()
    magic, version, _ = struct.unpack_from("<III", data, 0)
    assert magic == 0x46546C67 and version == 2, "not a glTF 2.0 binary"
    off, gltf, bin_chunk = 12, None, b""
    while off < len(data):
        length, ctype = struct.unpack_from("<II", data, off)
        chunk = data[off + 8: off + 8 + length]
        if ctype == 0x4E4F534A:
            gltf = json.loads(chunk)
        elif ctype == 0x004E4942:
            bin_chunk = chunk
        off += 8 + length
    return gltf, bin_chunk


def write_glb(path, gltf, bin_chunk):
    js = json.dumps(gltf, separators=(",", ":")).encode()
    js += b" " * (-len(js) % 4)
    bin_chunk += b"\0" * (-len(bin_chunk) % 4)
    total = 12 + 8 + len(js) + 8 + len(bin_chunk)
    with open(path, "wb") as f:
        f.write(struct.pack("<III", 0x46546C67, 2, total))
        f.write(struct.pack("<II", len(js), 0x4E4F534A) + js)
        f.write(struct.pack("<II", len(bin_chunk), 0x004E4942) + bin_chunk)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("src")
    ap.add_argument("dst")
    ap.add_argument("--size", type=int, default=2048)
    a = ap.parse_args()

    gltf, bin_chunk = read_glb(a.src)
    views = gltf["bufferViews"]
    image_views = {img["bufferView"]: img for img in gltf.get("images", []) if "bufferView" in img}

    blobs = []
    for i, bv in enumerate(views):
        raw = bin_chunk[bv.get("byteOffset", 0): bv.get("byteOffset", 0) + bv["byteLength"]]
        if i in image_views:
            img = Image.open(io.BytesIO(raw))
            if max(img.size) > a.size:
                img = img.resize((a.size, a.size * img.size[1] // img.size[0]), Image.LANCZOS)
                out = io.BytesIO()
                if image_views[i].get("mimeType") == "image/jpeg":
                    img.convert("RGB").save(out, "JPEG", quality=90)
                else:
                    img.save(out, "PNG", optimize=True)
                raw = out.getvalue()
        blobs.append(raw)

    new_bin = bytearray()
    for bv, raw in zip(views, blobs):
        new_bin += b"\0" * (-len(new_bin) % 4)
        bv["byteOffset"] = len(new_bin)
        bv["byteLength"] = len(raw)
        new_bin += raw
    gltf["buffers"] = [{"byteLength": len(new_bin) + (-len(new_bin) % 4)}]
    write_glb(a.dst, gltf, bytes(new_bin))
    print(f"wrote {a.dst}: {len(new_bin) / 1e6:.1f} MB")


if __name__ == "__main__":
    main()
