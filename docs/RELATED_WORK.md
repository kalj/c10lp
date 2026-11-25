# Related work (survey, 2026-11-24)

Read as data: cloned repos and fetched pages; nothing from them was run. Scope: open efforts on Intel/Altera bitstreams, with
weight on Cyclone IV / Cyclone 10 LP. Where our work fits is at the end.

## Summary

| Project | Target | Method | Status (as of 2026-11-24) | Routing |
|---|---|---|---|---|
| **this repo** (kalj/c10lp) | 10CL016 (= EP4CE15 die), 10CL006 checked | Quartus outputs only: RBF diffs, timing reports (`-show_routing`); silicon tests on a Vidor 4000 | active | exact per-position hop bits work on silicon (5/5 full reroutes); die-wide model 2/11 blind |
| [14sea/Cyclone_CRAM_Mapper](https://github.com/14sea/Cyclone_CRAM_Mapper) | EP4CE6 | clean-room pair-diff, `.rcf` back-annotation, Quartus golds | last push 2026-09-30; 11★, 2 forks; our issue #3 unanswered | per-class codecs (C4/R4 families); replay of mined routes |
| [Siroco](https://gitlab.com/franlego98/siroco) ([docs](https://siroco.franlego98.dev/bitstream/general/)) | EP4CE6E22C8 | RBF diffs + Chip Planner | 16 commits, 2026-01-10 … 2026-04-15; no license file | a few hand-found I/O-to-C16 bytes for 4 pins |
| labeth fork of 14sea (PRs #1, #2, both closed) | EP4CE6/EP4CE10 (`cycloneive1`) | decompiles Quartus device files (`.ddb`) and intercepts `quartus_asm` with gdb | 2026-07-28; rejected upstream as not clean-room | claims a device-wide `{src → dest : bits}` table (~352k arcs) |
| [Mistral](https://github.com/Ravenslofty/mistral) | Cyclone V (all dies) | routing databases from Quartus internals (README: "help without having to look inside quartus") | active again (Sep–Nov 2026, by galibert); BSD-3 | complete; experimental nextpnr arch |
| `fpgacc` / `fpgaas` | Cyclone V (at least) | unknown | not public; named only in Mistral commit e48ce11 (2026-11-04: "verified byte-identical … vs fpgacc fpgaas references") | unknown |
| [Yosys `synth_intel`](https://yosyshq.readthedocs.io/projects/yosys/en/stable/cmd/index_techlibs_intel.html) | MAX 10, Cyclone IV, `cyclone10lp` | synthesis to vendor cells | maintained | n/a; our front end |
| [nextpnr](https://github.com/YosysHQ/nextpnr) | iCE40, ECP5, Nexus, Gowin, NG-Ultra, GateMate; experimental Cyclone V, MachXO2, 7-series | per-family databases; new families via Himbächel | no Cyclone IV/10 LP arch, no issues or PRs found | — |
| [Perumalla, Stowasser, Emmert, NAECON 2023](https://arxiv.org/pdf/2603.17883) ("Fast FPGA Reverse Engineering for Hardware Metering and Fingerprinting") | 7 Series, Cyclone IV/V | academic | listed in the SoK survey (Karadağ et al., arXiv 2603.17883) as covering "all LUTs, 100%" | none |
| [LSE 2016 MAX V talk](https://www.lse.epita.fr/lse-summer-week-2016/slides/lse-summer-week-2016-07-maxv_cpld.pdf) | MAX V CPLD | RBF diffs | unfinished | none |

The SoK's table of bitstream-format work (Table 1) lists no routing work on any Intel/Altera part. Every academic work it
lists on Intel/Altera parts covers LUTs only. Other Altera academic work is about bitstream encryption (Swierczynski et
al., Stratix II/III, TRETS 2015).

## Siroco in detail (code read 2026-11-24)

- **Contents:** docs (zensical site), four notebooks, `exps/gen.sh` (Quartus 24.1 std loop over pin assignments) and
  `gen_bitstream.py`. The script hand-patches a blank RBF (I/O enables and some I/O-to-column bytes for pins 68/69/110/111)
  and recomputes CRCs.
- **Layout:** `[242, 5040] + [210]*1727`, then 59 bytes of 0xFF. The core starts at byte 5282, the same as our
  `rbfgeom` for the 10CL006 / EP4CE6 die (preamble 32, 210-byte frames, CRC frames 25..1751). Their "column" boundaries
  (`colsDelim`, 33 entries) correspond to our per-column frame groups.
- **CRC:** reflected poly 0x8005, refin/refout, **init 0x2A7F**, over each 208-byte section. Ours is the same polynomial and
  reflection over the same 208 bytes, but with init 0xFE54 (inferred per file by `rbfgeom`). Their init fails on all 1,727
  frames of our 10CL006 file, and ours fits. So the init differs between their files (Quartus 24.1) and ours (21.1.1).
  Open question: does it depend on the Quartus version or on bitstream options? (FE54 followed by bytes `00 99` gives 2A7F;
  that may be a coincidence.)
- **Findings beyond ours:** none. I/O enable at sections 10/24, bytes 2/207, for EP4CE6 pins. We have the periphery format,
  pull-ups, drive and I/O tiles.

## The device-file route (labeth fork): why we don't use it

It reads the routing model out of Quartus's own device databases and instruments the assembler. That's exactly what our
project rule (memory: routing-method-decision) and 14sea's clean-room policy exclude. 14sea's reply to PR #2: material
"derived from decompiling or instrumenting Quartus binaries or parsing its device databases is outside what we can
accept". So we don't read, import or compare against its tables, so that the provenance of our bit tables stays clean.
Its existence does tell us that a complete static switch table exists in Quartus for this die (~352k arcs on
`cycloneive1`), which roughly sizes the job.

## Methods we could still adopt (clean-room)

1. **`.rcf` routing back-annotation:** a documented Quartus text output, used by 14sea. It lists the full route of
   *every* net, not only the critical timing paths. That would multiply the hops labelled per compile, since our
   timing-report labels cover at most 40 paths per input. *Needs your OK*: our approved Quartus outputs are RBFs and
   timing reports.
2. **Dense forcing designs** (14sea's "snake-chain dense-fill", which they mention in their reply to PR #1). Same idea as
   our `xrkn` line-forcing, scaled up.
3. **"Decode-or-refuse":** a decoder that reports unknown regions instead of guessing. Good discipline for our assembler
   and disassembler.

## Where our work fits

- **Our position:** only our work and 14sea's are clean-room and past the format basics. Ours is the only one on
  Cyclone 10 LP, has the broadest silicon validation (LUTs, FFs, I/O, PLL, M9K, DSP, clocks, and inter-LAB routes written
  by us), and, as far as these notes show, the only cross-die results (10CL016 ≡ EP4CE15, 10CL006 ≡ EP4CE6).
- **The gap everyone has:** nobody has published a die-wide, clean-room Cyclone IV routing database or a nextpnr arch.
  A Himbächel uarch built on such a database is the missing piece for a Yosys → nextpnr → RBF flow, with Mistral's
  nextpnr arch as a structural reference.
- **People:** 14sea (EP4CE6, quiet since September), Siroco's author (early-stage, same goal), and Mistral's maintainer
  (active, knows how an Intel family enters nextpnr).
