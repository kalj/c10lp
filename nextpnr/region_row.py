# nextpnr --pre-place script: keep every cell in the region C10LP_REGION="x0,y0,x1,y1" (default one LAB row in the
# LAB-clock region X0..12 our clock model covers).  C10LP_CELL_REGIONS names a JSON file {cell: [[x, y], ...]} of
# per-cell sets of LABs that override it (c10lp_netlist.py --io: LUTs fed by input pins may sit only in LABs the pin
# path library reaches from all their pins; nextpnr chooses among them).  A LUT's register follows it.
import json
import os
x0, y0, x1, y1 = map(int, os.environ.get("C10LP_REGION", "1,3,12,3").split(","))
ctx.createRectangularRegion("c10lp_region", x0, y0, x1, y1)
per = json.load(open(os.environ["C10LP_CELL_REGIONS"])) if os.environ.get("C10LP_CELL_REGIONS") else {}
names = {}
for i, (c, labs) in enumerate(sorted(per.items())):
    names[c] = f"c10lp_cell{i}"
    # (no createRegion in the Python API: a one-LAB rectangle, then the other LABs' bels; a region is a bel set)
    ctx.createRectangularRegion(names[c], labs[0][0], labs[0][1], labs[0][0], labs[0][1])
    for x, y in labs[1:]:
        for n in range(16):
            for k in ("LUT", "FF"):
                ctx.addBelToRegion(names[c], f"X{x}Y{y}/LE{n}_{k}")     # bels by name in the Python API
for name, cell in ctx.cells:
    if cell.type in ("LUT4", "DFF"):
        own = name[2:] if name.startswith("r_") else name
        ctx.constrainCellToRegion(name, names.get(own, "c10lp_region"))
