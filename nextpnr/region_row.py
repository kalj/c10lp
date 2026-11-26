# nextpnr --pre-place script: keep every cell in one LAB row (the database has no vertical routing yet) and in the
# LAB-clock region X0..12 our clock model covers.  The row and columns come from C10LP_REGION="x0,y0,x1,y1".
import os
x0, y0, x1, y1 = map(int, os.environ.get("C10LP_REGION", "1,3,12,3").split(","))
ctx.createRectangularRegion("c10lp_region", x0, y0, x1, y1)
for name, cell in ctx.cells:
    if cell.type in ("LUT4", "DFF"):
        ctx.constrainCellToRegion(name, "c10lp_region")
