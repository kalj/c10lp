// SPDX-License-Identifier: GPL-3.0-or-later
// tpatch.py template "arith3b": like arith3, but the middle LE's sum output is also used, so e1
// needs both its sum and its carry.  Q (D5) = x(y1, q2, A, B), a plain LUT. Placeholders for e1, e2
// and x are asymmetric so their input orders can be read from the base (e0 stays fixed).
module fuzz_top(input wire A, B, C, D, output wire Q);
  wire c1, c2, y0, y1, q2;
  cyclone10lp_lcell_comb #(.lut_mask(16'h11CC), .sum_lutc_input("cin"), .dont_touch("on"))
    e0 (.dataa(A), .datab(B), .datad(D), .cout(c1), .combout(y0));
  cyclone10lp_lcell_comb #(.lut_mask(16'h5ED4), .sum_lutc_input("cin"), .dont_touch("on"))
    e1 (.dataa(C), .datab(B), .datad(D), .cin(c1), .cout(c2), .combout(y1));
  cyclone10lp_lcell_comb #(.lut_mask(16'h3CEC), .sum_lutc_input("cin"), .dont_touch("on"))
    e2 (.dataa(C), .datab(A), .datad(D), .cin(c2), .combout(q2));
  cyclone10lp_lcell_comb #(.lut_mask(16'h3A0A), .sum_lutc_input("datac"), .dont_touch("on"))
    x (.dataa(y1), .datab(q2), .datac(A), .datad(B), .combout(Q));
endmodule
