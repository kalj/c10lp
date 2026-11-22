#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Guided first hardware test on the MKR Vidor 4000 (10CL016).

Loads the low-drive test bitstreams one by one into the FPGA's SRAM over JTAG
(openFPGALoader through the SAMD21's USB-Blaster emulator, never into flash:
a power cycle restores the Arduino image), asks you what D5 reads for each
D1/D2 combination, and logs every answer to out/hwtest_<time>.jsonl.

Wiring: meter (or LED + 330 ohm) from D5 to GND; a jumper from D1 and/or D2
to GND when asked.  D1..D4 have weak pull-ups, so "open" means 1.

  python3 hwtest.py             run the test
  python3 hwtest.py --check     only the preflight checks (board, cable, files)
  python3 hwtest.py --dry-run   walk through without touching hardware
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import rbfgeom  # noqa: E402

OUT = os.path.join(HERE, "out")
IDCODE = 0x020F20DD          # 10CL016
SIZE = 510_856
AND = lambda d1, d2: d1 & d2  # noqa: E731  mask 8888 = dataa AND datab
ZERO = lambda d1, d2: 0       # noqa: E731

# (file, function D5 should follow, what a pass/fail tells us)
TESTS = {
    "quartus8888": ("lo_quartus_8888.rbf", AND,
                    "Quartus's own build: cable, loading and pin wiring work"),
    "quartus0000": ("lo_quartus_0000.rbf", ZERO,
                    "control: D5 held low proves the FPGA really is configured"),
    "x8888": ("lo_x8888.rbf", AND,
              "patched LUT with the header checksum left stale"),
    "x8888_far": ("lo_x8888_X30Y20N12.rbf", AND,
                  "patched by the position model at X30Y20N12, stale header"),
    "x8888_hdr": ("lo_x8888_hdr.rbf", AND,
                  "patched LUT with the header checksum fixed"),
}
COMBOS = [(1, 1), (0, 1), (1, 0), (0, 0)]
WORD = {1: "open", 0: "GND "}


def run(cmd: list[str], dry: bool) -> tuple[int, str]:
    if dry:
        print(f"  (dry run) {' '.join(cmd)}")
        return 0, f"idcode 0x{IDCODE:08x}"
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    except FileNotFoundError:
        return 127, f"{cmd[0]} not installed"
    except subprocess.TimeoutExpired:
        return 124, "timed out"
    return r.returncode, r.stdout + r.stderr


def check_file(path: str) -> str | None:
    if not os.path.exists(path):
        return "missing"
    b = open(path, "rb").read()
    if len(b) != SIZE:
        return f"size {len(b)}, expected {SIZE}"
    g = rbfgeom.infer(b)
    if g.frame != 255 or g.crc_frames != list(range(37, 2003)):
        return f"frame CRCs invalid ({len(g.crc_frames)} of 1966 good)"
    return None


def preflight(dry: bool, need: list[str]) -> bool:
    ok = True
    print("== Preflight")
    bad = {k: check_file(os.path.join(OUT, TESTS[k][0])) for k in need}
    for k, err in bad.items():
        f = TESTS[k][0]
        sha = "" if err else hashlib.sha256(open(os.path.join(OUT, f), "rb").read()).hexdigest()[:12]
        print(f"  {f:28s} {'ERROR: ' + err if err else 'ok, sha256 ' + sha}")
        ok &= err is None
    rc, txt = run(["lsusb", "-d", "09fb:6001"], dry)
    if rc:
        print("  USB-Blaster 09fb:6001 not on USB. Upload the USBBlaster example sketch "
              "(README, 'Loading bitstreams', Route A) and replug.")
        return False
    print("  USB-Blaster emulator on USB: ok")
    rc, txt = run(["openFPGALoader", "-c", "usb-blaster", "--detect"], dry)
    low = txt.lower()
    if rc or f"{IDCODE:x}" not in low:
        print(f"  openFPGALoader --detect did not report IDCODE 0x{IDCODE:08X} (exit {rc}):")
        print("    " + "\n    ".join(txt.strip().splitlines()[-6:]))
        return False
    print(f"  JTAG sees IDCODE 0x{IDCODE:08X} (10CL016): ok")
    return ok


def ask(prompt: str, dry: bool, script: list[str]) -> str:
    while True:
        if dry:
            a = script.pop(0) if script else "h"
            print(f"{prompt}{a}")
        else:
            a = input(prompt).strip().lower()
        if a in ("h", "l", "m", "s", "q"):
            return a
        print("    answer h (high, ~3.3 V / LED on), l (low, ~0 V / LED off), "
              "m (in between), s (skip), q (quit)")


def one_test(key: str, dry: bool, log, script: list[str]) -> str:
    f, fn, what = TESTS[key]
    print(f"\n== {f}: {what}")
    t0 = time.time()
    rc, txt = run(["openFPGALoader", "-c", "usb-blaster", os.path.join(OUT, f)], dry)
    rec = dict(test=key, file=f, load_rc=rc, load_s=round(time.time() - t0, 1),
               load_tail=txt.strip().splitlines()[-3:], readings=[])
    if rc:
        print(f"  load FAILED (exit {rc}):\n    " + "\n    ".join(rec["load_tail"]))
        rec["result"] = "load-failed"
        log.write(json.dumps(rec) + "\n")
        return "fail"
    print(f"  loaded in {rec['load_s']} s. For each line set the jumpers, then type what D5 reads.")
    verdict = "pass"
    for d1, d2 in COMBOS:
        want = "h" if fn(d1, d2) else "l"
        a = ask(f"  D1 {WORD[d1]}  D2 {WORD[d2]}  -> D5 [h/l/m/s/q]? ", dry, script)
        if a == "q":
            rec["result"] = "quit"
            log.write(json.dumps(rec) + "\n")
            return "quit"
        rec["readings"].append(dict(d1=d1, d2=d2, want=want, got=a))
        if a == "m":
            print("  !! An in-between voltage can mean two drivers on D5. Unplug USB now and "
                  "check the wiring before going on.")
            verdict = "fail"
        elif a != "s" and a != want:
            verdict = "fail"
    if all(r["got"] == "s" for r in rec["readings"]):
        verdict = "skipped"
    rec["result"] = verdict
    log.write(json.dumps(rec) + "\n")
    log.flush()
    print(f"  -> {verdict.upper()}")
    return verdict


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--check", action="store_true", help="preflight only")
    ap.add_argument("--dry-run", action="store_true", help="no hardware; fake answers")
    ap.add_argument("--answers", default="", help="dry run: answers, e.g. hlll,llll,...")
    a = ap.parse_args()
    script = list(a.answers.replace(",", ""))

    if not preflight(a.dry_run, list(TESTS)):
        print("\nPreflight failed; nothing was loaded.")
        return 1
    if a.check:
        return 0
    print("\nNote: an unconfigured FPGA leaves D5 floating with a weak pull-up, which a meter\n"
          "also reads as high. That is why every file is checked with D1/D2 grounded too, and\n"
          "why the all-zero control must read low.")
    path = os.path.join(OUT, time.strftime("hwtest_%Y%m%d_%H%M%S.jsonl"))
    res = {}
    with open(path, "w") as log:
        order = ["quartus8888", "quartus0000", "x8888"]
        for k in order:
            res[k] = one_test(k, a.dry_run, log, script)
            if res[k] == "quit":
                break
            if k in ("quartus8888", "quartus0000") and res[k] != "pass":
                print("\nThe Quartus-built files must pass before patched files mean anything. "
                      "Stopping here; see the README troubleshooting notes.")
                break
        else:
            nxt = "x8888_far" if res["x8888"] == "pass" else "x8888_hdr"
            if res["x8888"] != "quit":
                res[nxt] = one_test(nxt, a.dry_run, log, script)

    print("\n== Summary")
    for k, v in res.items():
        print(f"  {TESTS[k][0]:28s} {v.upper()}")
    concl = []
    if res.get("x8888") == "pass":
        concl.append("The chip accepts a hand-patched LUT and does NOT check the header sum.")
    if res.get("x8888") == "fail" and res.get("x8888_hdr") == "pass":
        concl.append("The chip checks the header sum; patched files need --fix-header.")
    if res.get("x8888") == "fail" and res.get("x8888_hdr") == "fail":
        concl.append("Patched files fail even with the header fixed: compare the two loads' "
                     "openFPGALoader output in the log.")
    if res.get("x8888_far") == "pass":
        concl.append("The lutpos.py position model works on silicon.")
    for c in concl:
        print("  " + c)
    print(f"  Log: {path}")
    print("  Power-cycle the board (or double-tap reset) to get the Arduino image back.")
    return 0 if all(v == "pass" for v in res.values()) else 2


if __name__ == "__main__":
    sys.exit(main())
