# Open flow for the blinky: Verilog -> Yosys -> ypnr.py (pack, place, route, assemble) -> out/ypnr_blink.rbf
#   make blinky        build the bitstream (no Quartus)
#   make blinky-check  also build the same netlist in Quartus with our placement/routing forced, and diff (needs Quartus)
YOSYS ?= yosys

out/blink.json: examples/blink.v
	$(YOSYS) -q -p "read_verilog $<; synth_intel -family cyclone10lp -nodsp -nobram -top blink; write_json $@"

out/ypnr_blink.rbf: out/blink.json ypnr.py ynet.py router.py asm.py
	python3 ypnr.py $< blink

blinky: out/ypnr_blink.rbf

blinky-check: out/ypnr_blink.rbf
	python3 ycheck.py out/blink.json blink

.PHONY: blinky blinky-check
