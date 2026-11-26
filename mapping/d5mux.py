#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""D5 output block mux select per I/O-block line, from the corpus (cells that are a function of the line).

  d5mux.py          -> out/d5mux.json
"""
import os
os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import json, glob, os, sys, collections
sys.path[:0] = ['lib', 'flow', 'mapping']
import numpy as np, xdev, routemap as R
byline = collections.defaultdict(list)
for f in sorted(glob.glob('out/*_jobs.json')):
    if 'holdout' in f: continue
    for name in json.load(open(f)):
        rp = f'out/{name}.route.json'
        if not os.path.exists(rp): continue
        for k, p in json.load(open(rp))['paths'].items():
            nodes = [e[0] for e in p if isinstance(e, list)]
            if 'BLOCK_INPUT_MUX_X6_Y0_N0_I10' in nodes:
                i = nodes.index('BLOCK_INPUT_MUX_X6_Y0_N0_I10'); byline[int(nodes[i - 1].rsplit('_I', 1)[1])].append(name); break
lo, hi = 250, 265
freq = {}
for L, ns in byline.items():
    A = np.array([np.unpackbits(np.frombuffer(xdev.load('out', n)[32 + lo*255:32 + hi*255], np.uint8), bitorder='little') for n in ns[:40]])
    freq[L] = A.mean(0)
F = np.array([freq[L] for L in sorted(freq)])
idx = np.nonzero(np.all((F < 0.05) | (F > 0.95), axis=0) & (F.max(0) > 0.95) & (F.min(0) < 0.05))[0]
# only bytes 6/7 (plane 7): the cells in bytes 253/254 that also follow the line track the corpus designs' input pads
# (the board-tested blinky, line 1, matches Quartus's build without them)
idx = [i for i in idx if (int(i) % 2040) // 8 in (6, 7)]
cells = [[lo + int(i) // 2040, (int(i) % 2040) // 8, int(i) % 8] for i in idx]
out = {"_doc": "D5's I/O block (X6Y0): line k of its LOCAL_INTERCONNECT -> BLOCK_INPUT_MUX_X6_Y0_N0_I10; cells set "
               "(frame, byte, plane), the others of 'cells' clear. From the corpus (mapping/d5mux.py).",
       "cells": cells, "builds": {str(L): len(v) for L, v in byline.items()},
       "select": {str(L): [c for c, i in zip(cells, idx) if F[Li, i] > 0.95] for Li, L in enumerate(sorted(freq))}}
json.dump(out, open('out/d5mux.json', 'w'), indent=0)
print(len(cells), 'cells,', len(out['select']), 'lines')
