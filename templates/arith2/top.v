// SPDX-License-Identifier: GPL-3.0-or-later
// tpatch.py template "arith2": two LEs in arithmetic mode, e0.cout -> e1.cin.
//   e0: dataa = A (D1), datab = B (D2), datad = D (D4); carry chain start, datac unconnected
//   e1: dataa = C (D3), datab = B (D2), datad = D (D4), cin = e0.cout; combout -> Q (D5)
// (no constant inputs: Quartus folds constants into the stored LUT bits)
// e0 placeholder 11CC ignores datac (unconnected, no carry in). Used to learn, on silicon, how the LUT mask works in arithmetic mode (LUT-only patches).
module fuzz_top(input wire A, B, C, D, output wire Q);
  wire c1, y0;
  cyclone10lp_lcell_comb #(.lut_mask(16'h11CC), .sum_lutc_input("cin"), .dont_touch("on"))
    e0 (.dataa(A), .datab(B), .datad(D), .cout(c1), .combout(y0));
  cyclone10lp_lcell_comb #(.lut_mask(16'h3CEC), .sum_lutc_input("cin"), .dont_touch("on"))
    e1 (.dataa(C), .datab(B), .datad(D), .cin(c1), .combout(Q));
endmodule
