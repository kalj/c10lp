# nextpnr --pre-place script (test of vertical routing): cells alternate between two one-row regions, so many nets
# must cross rows.  C10LP_SPLIT="x0,x1,yA,yB"; a register goes with its LUT (r_<lut>).
import os
x0, x1, ya, yb = map(int, os.environ.get("C10LP_SPLIT", "8,10,3,4").split(","))
ctx.createRectangularRegion("rowA", x0, ya, x1, ya)
ctx.createRectangularRegion("rowB", x0, yb, x1, yb)
luts = sorted(n for n, c in ctx.cells if c.type == "LUT4")
side = {n: ("rowA" if i % 2 == 0 else "rowB") for i, n in enumerate(luts)}
for name, cell in ctx.cells:
    if cell.type == "LUT4":
        ctx.constrainCellToRegion(name, side[name])
    elif cell.type == "DFF":
        ctx.constrainCellToRegion(name, side.get(name[2:], "rowA"))
