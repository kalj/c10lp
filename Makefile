# Open flow for the blinky: Verilog -> Yosys -> ypnr.py (pack, place, route, assemble) -> out/ypnr_blink.rbf
#   make baseline      the one Quartus step: the all-zero design the assembler starts from (out/lo_quartus_0000.rbf)
#   make blinky        build the bitstream (no Quartus)
#   make blinky-check  also build the same netlist in Quartus with our placement/routing forced, and diff (needs Quartus)
#   make npnr-blinky   the same design placed and routed by nextpnr-himbaechel (c10lp uarch, ../nextpnr built with it)
#                      -> out/ypnr_blink.rbf; blinky-check then cross-checks that file
#   make npnr-blinky-io  the same with the output pin as a nextpnr cell (pin path library) -> out/ypnr_blink.rbf
#   make npnr-pins     examples/pins.v, D1..D4 in and D5 out, all through the pin path library -> out/ypnr_pins.rbf
#   make npnr-cnt-en   examples/cnt_en.v, a counter with clock enable from D1 -> out/ypnr_cnt_en.rbf
YOSYS ?= yosys

out/blink.json: examples/blink.v
	$(YOSYS) -q -p "read_verilog $<; synth_intel -family cyclone10lp -nodsp -nobram -top blink; write_json $@"

out/lo_quartus_0000.rbf:
	python3 flow/baseline.py

baseline: out/lo_quartus_0000.rbf

out/ypnr_blink.rbf: out/blink.json out/lo_quartus_0000.rbf flow/ypnr.py flow/ynet.py flow/router.py flow/asm.py lib/switchmodel.py
	python3 flow/ypnr.py $< blink

blinky: out/ypnr_blink.rbf

blinky-check: out/ypnr_blink.rbf
	python3 flow/ycheck.py out/blink.json blink

NEXTPNR ?= ../nextpnr

npnr-blinky: out/blink.json out/lo_quartus_0000.rbf
	nextpnr/build_chipdb.sh $(NEXTPNR)
	python3 nextpnr/c10lp_netlist.py out/blink.json blink out/npnr_blink.json
	# a placement nextpnr can route with the hops we know: retry seeds (each run takes well under a second)
	for s in $$(seq 1 60); do $(NEXTPNR)/build/nextpnr-himbaechel --device 10CL016 --json out/npnr_blink.json \
	    --pre-place nextpnr/region_row.py --seed $$s --write out/npnr_blink_routed.json > out/npnr_blink.log 2>&1 \
	    && echo "nextpnr: routed with seed $$s" && break; done
	python3 nextpnr/npnr2asm.py out/npnr_blink_routed.json out/npnr_blink_side.json blink

# the output pin as a nextpnr cell: D5 reached over the pin path library (mapping/iopaths.py), the output LE at a
# library LE (X6Y4 N24), the rest placed by nextpnr in X4..X8 row 4 (board-tested 2026-11-26, 2.8611 Hz, at commit
# c2f034e; later database changes route it differently, cross-checked exact again)
npnr-blinky-io: out/blink.json out/lo_quartus_0000.rbf
	nextpnr/build_chipdb.sh $(NEXTPNR)
	python3 nextpnr/c10lp_netlist.py out/blink.json blink out/npnr_blinkio.json --io --out-le 6,4,24
	for s in $$(seq 1 60); do C10LP_REGION=4,4,8,4 $(NEXTPNR)/build/nextpnr-himbaechel --device 10CL016 \
	    --json out/npnr_blinkio.json --pre-place nextpnr/region_row.py --seed $$s --router router1 \
	    --write out/npnr_blinkio_routed.json > out/npnr_blinkio.log 2>&1 && echo "nextpnr: routed with seed $$s" && break; done
	python3 nextpnr/npnr2asm.py out/npnr_blinkio_routed.json out/npnr_blinkio_side.json blink

# D1..D4 in, D5 out (examples/pins.v): pin-fed LUTs constrained to the LABs the pin path library reaches, nextpnr
# choosing among them (nextpnr/npnr_io.py narrows the sets when a net doesn't route) -> out/ypnr_pins.rbf;
# cross-check: python3 flow/ycheck.py out/pins.json pins --timing --fresh
out/pins.json: examples/pins.v
	$(YOSYS) -q -p "read_verilog $<; synth_intel -family cyclone10lp -nodsp -nobram -top pins; write_json $@"

npnr-pins: out/pins.json out/lo_quartus_0000.rbf
	nextpnr/build_chipdb.sh $(NEXTPNR)
	python3 nextpnr/c10lp_netlist.py out/pins.json pins out/npnr_pins.json --io --out-le 6,4,24
	python3 nextpnr/npnr_io.py out/npnr_pins.json out/npnr_pins_side.json pins --seeds 10 --rounds 12

# a 24-bit counter with clock enable from D1 (examples/cnt_en.v): the enable through LAB_CONTROL_MUX slot 2 (ctlmux.json)
# -> out/ypnr_cnt_en.rbf; cross-check: python3 flow/ycheck.py out/cnt_en.json cnt_en --timing --fresh
out/cnt_en.json: examples/cnt_en.v
	$(YOSYS) -q -p "read_verilog $<; synth_intel -family cyclone10lp -nodsp -nobram -top cnt_en; write_json $@"

npnr-cnt-en: out/cnt_en.json out/lo_quartus_0000.rbf
	nextpnr/build_chipdb.sh $(NEXTPNR)
	python3 nextpnr/c10lp_netlist.py out/cnt_en.json cnt_en out/npnr_cnt_en.json --io --out-le 6,6,30
	python3 nextpnr/npnr_io.py out/npnr_cnt_en.json out/npnr_cnt_en_side.json cnt_en --region "3,4,9,9;5,5,8,7;4,6,9,7" --seeds 15 --rounds 8

# the same counter with an async clear from D1 instead (examples/cnt_clr.v): CLRN through LAB_CONTROL_MUX slot 0
out/cnt_clr.json: examples/cnt_clr.v
	$(YOSYS) -q -p "read_verilog $<; synth_intel -family cyclone10lp -nodsp -nobram -top cnt_clr; write_json $@"

npnr-cnt-clr: out/cnt_clr.json out/lo_quartus_0000.rbf
	nextpnr/build_chipdb.sh $(NEXTPNR)
	python3 nextpnr/c10lp_netlist.py out/cnt_clr.json cnt_clr out/npnr_cnt_clr.json --io --out-le 6,6,30
	python3 nextpnr/npnr_io.py out/npnr_cnt_clr.json out/npnr_cnt_clr_side.json cnt_clr --region "3,4,9,9;5,5,8,7;4,6,9,7" --seeds 15 --rounds 8

# and a sync clear from D1 (examples/cnt_sclr.v: dffeas instances, Yosys folds a behavioural one into the LUTs)
out/cnt_sclr.json: examples/cnt_sclr.v
	$(YOSYS) -q -p "read_verilog $<; synth_intel -family cyclone10lp -nodsp -nobram -top cnt_sclr; write_json $@"

npnr-cnt-sclr: out/cnt_sclr.json out/lo_quartus_0000.rbf
	nextpnr/build_chipdb.sh $(NEXTPNR)
	python3 nextpnr/c10lp_netlist.py out/cnt_sclr.json cnt_sclr out/npnr_cnt_sclr.json --io --out-le 6,6,30
	python3 nextpnr/npnr_io.py out/npnr_cnt_sclr.json out/npnr_cnt_sclr_side.json cnt_sclr --region 3,4,9,9 --seeds 15 --rounds 6

# a combination lock on D1..D4 (examples/lock.v), the second real design
out/lock.json: examples/lock.v
	$(YOSYS) -q -p "read_verilog $<; synth_intel -family cyclone10lp -nodsp -nobram -top lock; write_json $@"

npnr-lock: out/lock.json out/lo_quartus_0000.rbf
	nextpnr/build_chipdb.sh $(NEXTPNR)
	python3 nextpnr/c10lp_netlist.py out/lock.json lock out/npnr_lock.json --io --out-le 6,6,30
	python3 nextpnr/npnr_io.py out/npnr_lock.json out/npnr_lock_side.json lock --region 5,6,8,7 --seeds 20 --rounds 8

.PHONY: baseline blinky blinky-check npnr-blinky npnr-blinky-io npnr-pins npnr-cnt-en npnr-cnt-clr npnr-cnt-sclr npnr-lock
