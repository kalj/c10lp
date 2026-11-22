#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Turn an .rbf into the bit-reversed byte array the MKR Vidor sketch flow expects.

Arduino's flow embeds the Quartus .ttf in a sketch (`#include "app.h"` inside
the .fpga_bitstream section) after reversing the bit order of every byte
(what revBytes / ByteReverser do).  Bitstreams we patch ourselves have no
.ttf, so this builds the same array straight from an .rbf.

  vidor_pack.py design.rbf -o app.h            C initializer list for the sketch
  vidor_pack.py design.rbf --bin -o app.bin    raw bit-reversed bytes
  vidor_pack.py design.rbf --check-ttf design.ttf
        confirm that Quartus's .ttf holds exactly the .rbf bytes (run this once on a
        Quartus build before trusting this tool for patched files)
"""
import argparse
import sys

REV = bytes(int(f"{i:08b}"[::-1], 2) for i in range(256))


def read_ttf(path: str) -> bytes:
    txt = open(path).read().replace("\n", ",").replace("\r", ",")
    return bytes(int(t) for t in (s.strip() for s in txt.split(",")) if t)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("rbf")
    ap.add_argument("-o", "--output")
    ap.add_argument("--bin", action="store_true")
    ap.add_argument("--check-ttf")
    a = ap.parse_args()
    data = open(a.rbf, "rb").read()
    if a.check_ttf:
        t = read_ttf(a.check_ttf)
        if t == data:
            print(f"OK: .ttf == .rbf ({len(t):,} bytes)")
            return 0
        if t == data.translate(REV):
            print("NOTE: .ttf is already the bit-reversed .rbf; Arduino's reversal "
                  "would then undo it. Check before flashing.")
            return 1
        print(f"MISMATCH: .ttf {len(t):,} bytes vs .rbf {len(data):,} bytes "
              "(compression setting differs?)")
        return 1
    out = data.translate(REV)
    if not a.output:
        ap.error("-o is required")
    if a.bin:
        open(a.output, "wb").write(out)
    else:
        with open(a.output, "w") as f:
            for i in range(0, len(out), 16):
                f.write(",".join(str(b) for b in out[i:i + 16]) + ",\n")
    print(f"wrote {a.output}: {len(out):,} bytes, bit-reversed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
