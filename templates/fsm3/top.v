// SPDX-License-Identifier: GPL-3.0-or-later
// tpatch.py template "fsm3": an 8-state machine with one input.
//   state s[2:0] (power-up 0), clocked by B (D2);
//   next_i = LUT_i(a = A (D1), b = s[0], c = s[1], d = s[2]);
//   Q (D5) = LUT_out(a = s[0], b = s[1], c = s[2], d = C (D3)).
// The masks below are placeholders: tpatch.py rewrites them.  Each must be asymmetric
// enough that only one input order explains it (lutpos.unique_perm_mask), because the
// base build is how tpatch.py learns each LUT's input order.
module fuzz_top(input wire A, B, C, D, output wire Q);
  reg  [2:0] s;
  wire [2:0] n;
  cyclone10lp_lcell_comb #(.lut_mask(16'h3CEC), .sum_lutc_input("datac"), .dont_touch("on"))
    next0 (.dataa(A), .datab(s[0]), .datac(s[1]), .datad(s[2]), .combout(n[0]));
  cyclone10lp_lcell_comb #(.lut_mask(16'h97B8), .sum_lutc_input("datac"), .dont_touch("on"))
    next1 (.dataa(A), .datab(s[0]), .datac(s[1]), .datad(s[2]), .combout(n[1]));
  cyclone10lp_lcell_comb #(.lut_mask(16'h2164), .sum_lutc_input("datac"), .dont_touch("on"))
    next2 (.dataa(A), .datab(s[0]), .datac(s[1]), .datad(s[2]), .combout(n[2]));
  cyclone10lp_lcell_comb #(.lut_mask(16'h9A9B), .sum_lutc_input("datac"), .dont_touch("on"))
    lut_out (.dataa(s[0]), .datab(s[1]), .datac(s[2]), .datad(C), .combout(Q));
  always @(posedge B) s <= n;
endmodule
