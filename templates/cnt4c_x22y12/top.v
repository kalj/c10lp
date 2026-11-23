// SPDX-License-Identifier: GPL-3.0-or-later
// tpatch.py template "cnt4c": a 4-bit carry-chain counter.  LE i (arithmetic mode):
//   dataa = s[i], datab = A (D1, enable; used by LE 0), datad = D (D4, held at 1: the sum reads
//   the mask's upper half only when d = 1), cin from LE i-1 (none for LE 0), sum -> register s[i]
//   (clock B = D2), cout -> LE i+1.  Q (D5) = C (D3) ? s[3] : s[2] through a plain LUT.
// Placeholders: LE 0 = 6688 (the standard counter LSB, which ignores the unconnected carry in);
// LEs 1..3 and the output LUT are asymmetric, so their input orders can be read from the base.
module fuzz_top(input wire A, B, C, D, output wire Q);
  (* noprune *) reg [3:0] s = 4'd0;
  wire [3:0] n;
  wire [3:0] c;
  cyclone10lp_lcell_comb #(.lut_mask(16'h6688), .sum_lutc_input("cin"), .dont_touch("on"))
    a0 (.dataa(s[0]), .datab(A), .datad(D), .cout(c[0]), .combout(n[0]));
  cyclone10lp_lcell_comb #(.lut_mask(16'h598C), .sum_lutc_input("cin"), .dont_touch("on"))
    a1 (.dataa(s[1]), .datab(A), .datad(D), .cin(c[0]), .cout(c[1]), .combout(n[1]));
  cyclone10lp_lcell_comb #(.lut_mask(16'h02C8), .sum_lutc_input("cin"), .dont_touch("on"))
    a2 (.dataa(s[2]), .datab(A), .datad(D), .cin(c[1]), .cout(c[2]), .combout(n[2]));
  cyclone10lp_lcell_comb #(.lut_mask(16'hFF23), .sum_lutc_input("cin"), .dont_touch("on"))
    a3 (.dataa(s[3]), .datab(A), .datad(D), .cin(c[2]), .cout(c[3]), .combout(n[3]));
  cyclone10lp_lcell_comb #(.lut_mask(16'h7B88), .sum_lutc_input("datac"), .dont_touch("on"))
    lut_out (.dataa(s[2]), .datab(s[3]), .datac(C), .datad(D), .combout(Q));
  always @(posedge B) s <= n;
endmodule
