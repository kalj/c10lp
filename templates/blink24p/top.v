// SPDX-License-Identifier: GPL-3.0-or-later
// tpatch.py template "blink24p": blink24 with a hand-chosen placement: groups 0-3 in LAB X9Y3, groups 4-7 and lut_out in X10Y3, so only c[3] crosses between LABs (slot 30 -> +1 neighbour link).
// PIN_E2, driven by the SAMD21; input only).  Bits are in 8 groups of 3 with a carry chain:
//   group j (bits 3j..3j+2), carry in cin = 1 for j = 0, else c[j-1]:
//     n[b]  = f(s[b], cin, the other two bits of the group)     (3 LUTs per group)
//     c[j]  = f(cin, s[3j], s[3j+1], s[3j+2])                    (j = 0..6)
//   Q (D5) = f(s[23], s[21], s[19], 1).    Power-up 0.
// B, C, D (D2..D4) are unused inputs.  Placeholder masks are random asymmetric ones.
module fuzz_top(input wire A, B, C, D, input wire K, output wire Q);
  reg  [23:0] s;
  wire [23:0] n;
  wire [6:0]  c;
  cyclone10lp_lcell_comb #(.lut_mask(16'h809D), .sum_lutc_input("datac"), .dont_touch("on"))
    n0 (.dataa(s[0]), .datab(1'b1), .datac(s[1]), .datad(s[2]), .combout(n[0]));
  cyclone10lp_lcell_comb #(.lut_mask(16'h66C1), .sum_lutc_input("datac"), .dont_touch("on"))
    n1 (.dataa(s[1]), .datab(1'b1), .datac(s[0]), .datad(s[2]), .combout(n[1]));
  cyclone10lp_lcell_comb #(.lut_mask(16'hCBAA), .sum_lutc_input("datac"), .dont_touch("on"))
    n2 (.dataa(s[2]), .datab(1'b1), .datac(s[0]), .datad(s[1]), .combout(n[2]));
  cyclone10lp_lcell_comb #(.lut_mask(16'h051D), .sum_lutc_input("datac"), .dont_touch("on"))
    cy0 (.dataa(1'b1), .datab(s[0]), .datac(s[1]), .datad(s[2]), .combout(c[0]));
  cyclone10lp_lcell_comb #(.lut_mask(16'h281F), .sum_lutc_input("datac"), .dont_touch("on"))
    n3 (.dataa(s[3]), .datab(c[0]), .datac(s[4]), .datad(s[5]), .combout(n[3]));
  cyclone10lp_lcell_comb #(.lut_mask(16'h7A76), .sum_lutc_input("datac"), .dont_touch("on"))
    n4 (.dataa(s[4]), .datab(c[0]), .datac(s[3]), .datad(s[5]), .combout(n[4]));
  cyclone10lp_lcell_comb #(.lut_mask(16'hD3AB), .sum_lutc_input("datac"), .dont_touch("on"))
    n5 (.dataa(s[5]), .datab(c[0]), .datac(s[3]), .datad(s[4]), .combout(n[5]));
  cyclone10lp_lcell_comb #(.lut_mask(16'h46AE), .sum_lutc_input("datac"), .dont_touch("on"))
    cy1 (.dataa(c[0]), .datab(s[3]), .datac(s[4]), .datad(s[5]), .combout(c[1]));
  cyclone10lp_lcell_comb #(.lut_mask(16'h7949), .sum_lutc_input("datac"), .dont_touch("on"))
    n6 (.dataa(s[6]), .datab(c[1]), .datac(s[7]), .datad(s[8]), .combout(n[6]));
  cyclone10lp_lcell_comb #(.lut_mask(16'h883D), .sum_lutc_input("datac"), .dont_touch("on"))
    n7 (.dataa(s[7]), .datab(c[1]), .datac(s[6]), .datad(s[8]), .combout(n[7]));
  cyclone10lp_lcell_comb #(.lut_mask(16'hC8D6), .sum_lutc_input("datac"), .dont_touch("on"))
    n8 (.dataa(s[8]), .datab(c[1]), .datac(s[6]), .datad(s[7]), .combout(n[8]));
  cyclone10lp_lcell_comb #(.lut_mask(16'h13B0), .sum_lutc_input("datac"), .dont_touch("on"))
    cy2 (.dataa(c[1]), .datab(s[6]), .datac(s[7]), .datad(s[8]), .combout(c[2]));
  cyclone10lp_lcell_comb #(.lut_mask(16'h1E73), .sum_lutc_input("datac"), .dont_touch("on"))
    n9 (.dataa(s[9]), .datab(c[2]), .datac(s[10]), .datad(s[11]), .combout(n[9]));
  cyclone10lp_lcell_comb #(.lut_mask(16'hABCC), .sum_lutc_input("datac"), .dont_touch("on"))
    n10 (.dataa(s[10]), .datab(c[2]), .datac(s[9]), .datad(s[11]), .combout(n[10]));
  cyclone10lp_lcell_comb #(.lut_mask(16'h9B06), .sum_lutc_input("datac"), .dont_touch("on"))
    n11 (.dataa(s[11]), .datab(c[2]), .datac(s[9]), .datad(s[10]), .combout(n[11]));
  cyclone10lp_lcell_comb #(.lut_mask(16'h750B), .sum_lutc_input("datac"), .dont_touch("on"))
    cy3 (.dataa(c[2]), .datab(s[9]), .datac(s[10]), .datad(s[11]), .combout(c[3]));
  cyclone10lp_lcell_comb #(.lut_mask(16'hA323), .sum_lutc_input("datac"), .dont_touch("on"))
    n12 (.dataa(s[12]), .datab(c[3]), .datac(s[13]), .datad(s[14]), .combout(n[12]));
  cyclone10lp_lcell_comb #(.lut_mask(16'h37AC), .sum_lutc_input("datac"), .dont_touch("on"))
    n13 (.dataa(s[13]), .datab(c[3]), .datac(s[12]), .datad(s[14]), .combout(n[13]));
  cyclone10lp_lcell_comb #(.lut_mask(16'h6C8A), .sum_lutc_input("datac"), .dont_touch("on"))
    n14 (.dataa(s[14]), .datab(c[3]), .datac(s[12]), .datad(s[13]), .combout(n[14]));
  cyclone10lp_lcell_comb #(.lut_mask(16'h7D25), .sum_lutc_input("datac"), .dont_touch("on"))
    cy4 (.dataa(c[3]), .datab(s[12]), .datac(s[13]), .datad(s[14]), .combout(c[4]));
  cyclone10lp_lcell_comb #(.lut_mask(16'hF26B), .sum_lutc_input("datac"), .dont_touch("on"))
    n15 (.dataa(s[15]), .datab(c[4]), .datac(s[16]), .datad(s[17]), .combout(n[15]));
  cyclone10lp_lcell_comb #(.lut_mask(16'h5B59), .sum_lutc_input("datac"), .dont_touch("on"))
    n16 (.dataa(s[16]), .datab(c[4]), .datac(s[15]), .datad(s[17]), .combout(n[16]));
  cyclone10lp_lcell_comb #(.lut_mask(16'hC685), .sum_lutc_input("datac"), .dont_touch("on"))
    n17 (.dataa(s[17]), .datab(c[4]), .datac(s[15]), .datad(s[16]), .combout(n[17]));
  cyclone10lp_lcell_comb #(.lut_mask(16'h19DA), .sum_lutc_input("datac"), .dont_touch("on"))
    cy5 (.dataa(c[4]), .datab(s[15]), .datac(s[16]), .datad(s[17]), .combout(c[5]));
  cyclone10lp_lcell_comb #(.lut_mask(16'h24AC), .sum_lutc_input("datac"), .dont_touch("on"))
    n18 (.dataa(s[18]), .datab(c[5]), .datac(s[19]), .datad(s[20]), .combout(n[18]));
  cyclone10lp_lcell_comb #(.lut_mask(16'h8CFD), .sum_lutc_input("datac"), .dont_touch("on"))
    n19 (.dataa(s[19]), .datab(c[5]), .datac(s[18]), .datad(s[20]), .combout(n[19]));
  cyclone10lp_lcell_comb #(.lut_mask(16'hB27D), .sum_lutc_input("datac"), .dont_touch("on"))
    n20 (.dataa(s[20]), .datab(c[5]), .datac(s[18]), .datad(s[19]), .combout(n[20]));
  cyclone10lp_lcell_comb #(.lut_mask(16'h4A37), .sum_lutc_input("datac"), .dont_touch("on"))
    cy6 (.dataa(c[5]), .datab(s[18]), .datac(s[19]), .datad(s[20]), .combout(c[6]));
  cyclone10lp_lcell_comb #(.lut_mask(16'h5F41), .sum_lutc_input("datac"), .dont_touch("on"))
    n21 (.dataa(s[21]), .datab(c[6]), .datac(s[22]), .datad(s[23]), .combout(n[21]));
  cyclone10lp_lcell_comb #(.lut_mask(16'h6261), .sum_lutc_input("datac"), .dont_touch("on"))
    n22 (.dataa(s[22]), .datab(c[6]), .datac(s[21]), .datad(s[23]), .combout(n[22]));
  cyclone10lp_lcell_comb #(.lut_mask(16'h331C), .sum_lutc_input("datac"), .dont_touch("on"))
    n23 (.dataa(s[23]), .datab(c[6]), .datac(s[21]), .datad(s[22]), .combout(n[23]));
  cyclone10lp_lcell_comb #(.lut_mask(16'hF746), .sum_lutc_input("datac"), .dont_touch("on"))
    lut_out (.dataa(s[23]), .datab(s[21]), .datac(s[19]), .datad(1'b1), .combout(Q));
  always @(posedge K) s <= n;
endmodule
