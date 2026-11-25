<!-- Posted 2026-11-23 as https://github.com/14sea/Cyclone_CRAM_Mapper/issues/3#issuecomment-7095463508. Text as posted. -->

An update on the local-interconnect side: I've now rewired LUT inputs on silicon without Quartus,
and found the rule for when it works. All on the 10CL016 (MKR Vidor 4000); the LUT-input mux table
from my last comment also matched your EP4CE6 builds, so I expect this to carry over.

**Setup.** A Quartus build where four LEs in one LAB drive the four inputs of a fifth (pinned with
`dont_touch`; the dst's asymmetric mask shows which physical input each source landed on). A
"rewire" changes only dst's select bits for one physical input, from `li_local_table.json`, so that
it picks another source LE that is already present in the LAB. dst's LUT mask is also patched so
D5 shows that input. A pre-load gate checks that only those select bits and the LUT cells differ
from the Quartus build. Every input combination is then checked on the board.

**What happened.** The first rewires mostly failed, but always the same way: the input read a
constant and never a wrong source. Whether one worked didn't depend only on the (input, source)
pair. It depended on which other input already selected that source.

**The structure behind it** (160 builds where two inputs share one source): Quartus only ever shares a
source between one fixed pair of inputs, and the select bits then match the table exactly. So each
LE's local line reaches exactly two of a LUT's four inputs directly, one of {0, 1} and one of {2, 3}
(physical input numbering from the LUT minterm order):

| source LE slot (N) | direct inputs |
|---|---|
| 4, 8, 14 | 0, 2 |
| 22, 26, 30 | 0, 3 |
| 0, 2, 16, 18, 20, 24, 28 | 1, 2 |
| 6, 10, 12 | 1, 3 |

Any other (input, source) connection, e.g. input 0 ← N12, which Quartus does use, goes through a second
path that needs bits on the source LE's side. So a dst-only rewire of input p to source s works
**iff p is a direct input of s, and s's local line is driven** (the input that already selects s
reaches it directly). Otherwise the input selects an undriven line and reads a constant. That fits
the failures, and no failure looked like two drivers fighting.

**Validation.**
- The rule accounts for all 44 rewire outcomes it was derived from.
- **Blind test:** on 6 new bases, the predictions for 19 rewires were committed before anything was
  loaded (`blind_predictions.json`). **19/19 were right**: 17/17 predicted rewires worked on silicon,
  including pairs never tried before, and both predicted failures failed.
- Every run reloaded a Quartus all-zero control before and after and checked the D1..D4 readback.

Files in https://github.com/kalj/c10lp: `rewire.py` (the writes), `sharemap.py` / `lirule.py` (the
rule), `li_direct.json` (the table above), `blindtest.py` and `blind_predictions.json`.

Open: the second (source-side) path, and anything from outside the LAB. Sources from neighbouring
LABs use the same two-level select structure, but which LAB line carries a signal is Quartus's
choice, so mapping wire → LAB line needs single-route experiments like your signature mining. I'd
rather ask than reinvent that: does your C4/R4 work give you the LAB-line driver selects, and do you
think they'd transfer to the CE15 die the way the LUT and local-mux layouts do?
