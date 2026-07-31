#!/usr/bin/env python3
"""Generate placeholder PNG icons for the browser extension."""
import struct
import zlib


def create_png(width, height, color=(96, 165, 250)):
    """Create a minimal solid-color PNG file as bytes."""

    def chunk(chunk_type, data):
        c = chunk_type + data
        crc = struct.pack(">I", zlib.crc32(c) & 0xFFFFFFFF)
        return struct.pack(">I", len(data)) + c + crc

    # IHDR
    ihdr_data = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    ihdr = chunk(b"IHDR", ihdr_data)

    # IDAT — raw pixel data (filter byte 0 + RGB triplets)
    raw = b""
    for y in range(height):
        raw += b"\x00"  # filter: none
        for x in range(width):
            # Simple gradient from top-left to bottom-right
            r = int(color[0] * (1 - y / max(height - 1, 1) * 0.3))
            g = int(color[1] * (1 - y / max(height - 1, 1) * 0.3))
            b = int(color[2])
            raw += struct.pack("BBB", r, g, b)

    compressed = zlib.compress(raw)
    idat = chunk(b"IDAT", compressed)

    # IEND
    iend = chunk(b"IEND", b"")

    # PNG signature
    signature = b"\x89PNG\r\n\x1a\n"

    return signature + ihdr + idat + iend


def main():
    sizes = {"16": 16, "48": 48, "128": 128}
    for name, size in sizes.items():
        path = f"extension/icons/icon{name}.png"
        png_data = create_png(size, size)
        with open(path, "wb") as f:
            f.write(png_data)
        print(f"Created {path} ({size}x{size})")


if __name__ == "__main__":
    main()
