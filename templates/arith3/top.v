// SPDX-License-Identifier: GPL-3.0-or-later
// tpatch.py template "arith3": three LEs in arithmetic mode, e0.cout -> e1.cin -> e1.cout -> e2.cin.
//   e0: dataa = A (D1), datab = B (D2), datad = D (D4); chain start (datac unconnected, mask ignores c)
//   e1: dataa = C (D3), datab = B (D2), datad = D (D4), cin; its sum output is unused (carry only)
//   e2: dataa = C, datab = A, datad = D, cin; combout -> Q (D5)
// Used to measure the middle LE's carry function on silicon (LUT-only patches).
module fuzz_top(input wire A, B, C, D, output wire Q);
  wire c1, c2, y0, y1;
  cyclone10lp_lcell_comb #(.lut_mask(16'h11CC), .sum_lutc_input("cin"), .dont_touch("on"))
    e0 (.dataa(A), .datab(B), .datad(D), .cout(c1), .combout(y0));
  cyclone10lp_lcell_comb #(.lut_mask(16'h96E8), .sum_lutc_input("cin"), .dont_touch("on"))
    e1 (.dataa(C), .datab(B), .datad(D), .cin(c1), .cout(c2), .combout(y1));
  cyclone10lp_lcell_comb #(.lut_mask(16'h3CEC), .sum_lutc_input("cin"), .dont_touch("on"))
    e2 (.dataa(C), .datab(A), .datad(D), .cin(c2), .combout(Q));
endmodule
