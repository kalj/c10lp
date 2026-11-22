// SPDX-License-Identifier: GPL-3.0-or-later
// tpatch.py template "cnt8": 8 state bits, 18 LUTs, spans more than one LAB.
//   nx_i:  n[i] = f(a = s[i], b = s[i-1] (s[7] for i = 0), c = k[i-1] (C = D3 for i = 0), d = A = D1)
//   ch_i:  k[i] = f(a = s[i], b = k[i-1] (C for i = 0), c = A, d = D = D4)        (chain, i = 0..6)
//   elo/ehi: e = f(s[0..3]) / f(s[4..7]);  lut_out: Q (D5) = f(e[0], e[1], A, D)
//   s <= n on the rising edge of B (D2); power-up 0.
// Placeholder masks are random asymmetric ones (lutpos.unique_perm_mask); tpatch.py rewrites them.
module fuzz_top(input wire A, B, C, D, output wire Q);
  reg  [7:0] s;
  wire [7:0] n;
  wire [6:0] k;
  wire [1:0] e;
  cyclone10lp_lcell_comb #(.lut_mask(16'h5D49), .sum_lutc_input("datac"), .dont_touch("on"))
    nx0 (.dataa(s[0]), .datab(s[7]), .datac(C), .datad(A), .combout(n[0]));
  cyclone10lp_lcell_comb #(.lut_mask(16'h73EA), .sum_lutc_input("datac"), .dont_touch("on"))
    nx1 (.dataa(s[1]), .datab(s[0]), .datac(k[0]), .datad(A), .combout(n[1]));
  cyclone10lp_lcell_comb #(.lut_mask(16'h2127), .sum_lutc_input("datac"), .dont_touch("on"))
    nx2 (.dataa(s[2]), .datab(s[1]), .datac(k[1]), .datad(A), .combout(n[2]));
  cyclone10lp_lcell_comb #(.lut_mask(16'h70B2), .sum_lutc_input("datac"), .dont_touch("on"))
    nx3 (.dataa(s[3]), .datab(s[2]), .datac(k[2]), .datad(A), .combout(n[3]));
  cyclone10lp_lcell_comb #(.lut_mask(16'h3CA2), .sum_lutc_input("datac"), .dont_touch("on"))
    nx4 (.dataa(s[4]), .datab(s[3]), .datac(k[3]), .datad(A), .combout(n[4]));
  cyclone10lp_lcell_comb #(.lut_mask(16'hE0C9), .sum_lutc_input("datac"), .dont_touch("on"))
    nx5 (.dataa(s[5]), .datab(s[4]), .datac(k[4]), .datad(A), .combout(n[5]));
  cyclone10lp_lcell_comb #(.lut_mask(16'h59D3), .sum_lutc_input("datac"), .dont_touch("on"))
    nx6 (.dataa(s[6]), .datab(s[5]), .datac(k[5]), .datad(A), .combout(n[6]));
  cyclone10lp_lcell_comb #(.lut_mask(16'h6347), .sum_lutc_input("datac"), .dont_touch("on"))
    nx7 (.dataa(s[7]), .datab(s[6]), .datac(k[6]), .datad(A), .combout(n[7]));
  cyclone10lp_lcell_comb #(.lut_mask(16'hC720), .sum_lutc_input("datac"), .dont_touch("on"))
    ch0 (.dataa(s[0]), .datab(C), .datac(A), .datad(D), .combout(k[0]));
  cyclone10lp_lcell_comb #(.lut_mask(16'hD30C), .sum_lutc_input("datac"), .dont_touch("on"))
    ch1 (.dataa(s[1]), .datab(k[0]), .datac(A), .datad(D), .combout(k[1]));
  cyclone10lp_lcell_comb #(.lut_mask(16'h88C7), .sum_lutc_input("datac"), .dont_touch("on"))
    ch2 (.dataa(s[2]), .datab(k[1]), .datac(A), .datad(D), .combout(k[2]));
  cyclone10lp_lcell_comb #(.lut_mask(16'hA0F5), .sum_lutc_input("datac"), .dont_touch("on"))
    ch3 (.dataa(s[3]), .datab(k[2]), .datac(A), .datad(D), .combout(k[3]));
  cyclone10lp_lcell_comb #(.lut_mask(16'hC853), .sum_lutc_input("datac"), .dont_touch("on"))
    ch4 (.dataa(s[4]), .datab(k[3]), .datac(A), .datad(D), .combout(k[4]));
  cyclone10lp_lcell_comb #(.lut_mask(16'h2ED5), .sum_lutc_input("datac"), .dont_touch("on"))
    ch5 (.dataa(s[5]), .datab(k[4]), .datac(A), .datad(D), .combout(k[5]));
  cyclone10lp_lcell_comb #(.lut_mask(16'h02F5), .sum_lutc_input("datac"), .dont_touch("on"))
    ch6 (.dataa(s[6]), .datab(k[5]), .datac(A), .datad(D), .combout(k[6]));
  cyclone10lp_lcell_comb #(.lut_mask(16'hB375), .sum_lutc_input("datac"), .dont_touch("on"))
    elo (.dataa(s[0]), .datab(s[1]), .datac(s[2]), .datad(s[3]), .combout(e[0]));
  cyclone10lp_lcell_comb #(.lut_mask(16'h5A3C), .sum_lutc_input("datac"), .dont_touch("on"))
    ehi (.dataa(s[4]), .datab(s[5]), .datac(s[6]), .datad(s[7]), .combout(e[1]));
  cyclone10lp_lcell_comb #(.lut_mask(16'h0A9D), .sum_lutc_input("datac"), .dont_touch("on"))
    lut_out (.dataa(e[0]), .datab(e[1]), .datac(A), .datad(D), .combout(Q));
  always @(posedge B) s <= n;
endmodule
