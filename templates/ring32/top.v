// SPDX-License-Identifier: GPL-3.0-or-later
// tpatch.py template "ring32": 32 state bits, 43 LUTs, several LABs.
//   nx_i: n[i] = f(a = s[i], b = s[i-1 mod 32], c = s[i+11 mod 32], d = A (D1) for even i, C (D3) for odd i)
//   ob_j: o[j] = f(s[4j..4j+3]);  pa/pb: p = f(o[0..3]) / f(o[4..7]);  lut_out: Q = f(p[0], p[1], C, D)
//   s <= n on the rising edge of B (D2); power-up 0.  Placeholder masks are random asymmetric ones.
module fuzz_top(input wire A, B, C, D, output wire Q);
  reg  [31:0] s;
  wire [31:0] n;
  wire [7:0]  o;
  wire [1:0]  p;
  cyclone10lp_lcell_comb #(.lut_mask(16'h15A1), .sum_lutc_input("datac"), .dont_touch("on"))
    nx0 (.dataa(s[0]), .datab(s[31]), .datac(s[11]), .datad(A), .combout(n[0]));
  cyclone10lp_lcell_comb #(.lut_mask(16'hB703), .sum_lutc_input("datac"), .dont_touch("on"))
    nx1 (.dataa(s[1]), .datab(s[0]), .datac(s[12]), .datad(C), .combout(n[1]));
  cyclone10lp_lcell_comb #(.lut_mask(16'h6D02), .sum_lutc_input("datac"), .dont_touch("on"))
    nx2 (.dataa(s[2]), .datab(s[1]), .datac(s[13]), .datad(A), .combout(n[2]));
  cyclone10lp_lcell_comb #(.lut_mask(16'hDB23), .sum_lutc_input("datac"), .dont_touch("on"))
    nx3 (.dataa(s[3]), .datab(s[2]), .datac(s[14]), .datad(C), .combout(n[3]));
  cyclone10lp_lcell_comb #(.lut_mask(16'h2EC1), .sum_lutc_input("datac"), .dont_touch("on"))
    nx4 (.dataa(s[4]), .datab(s[3]), .datac(s[15]), .datad(A), .combout(n[4]));
  cyclone10lp_lcell_comb #(.lut_mask(16'h43F2), .sum_lutc_input("datac"), .dont_touch("on"))
    nx5 (.dataa(s[5]), .datab(s[4]), .datac(s[16]), .datad(C), .combout(n[5]));
  cyclone10lp_lcell_comb #(.lut_mask(16'h93BC), .sum_lutc_input("datac"), .dont_touch("on"))
    nx6 (.dataa(s[6]), .datab(s[5]), .datac(s[17]), .datad(A), .combout(n[6]));
  cyclone10lp_lcell_comb #(.lut_mask(16'h2CAC), .sum_lutc_input("datac"), .dont_touch("on"))
    nx7 (.dataa(s[7]), .datab(s[6]), .datac(s[18]), .datad(C), .combout(n[7]));
  cyclone10lp_lcell_comb #(.lut_mask(16'h0B98), .sum_lutc_input("datac"), .dont_touch("on"))
    nx8 (.dataa(s[8]), .datab(s[7]), .datac(s[19]), .datad(A), .combout(n[8]));
  cyclone10lp_lcell_comb #(.lut_mask(16'h420F), .sum_lutc_input("datac"), .dont_touch("on"))
    nx9 (.dataa(s[9]), .datab(s[8]), .datac(s[20]), .datad(C), .combout(n[9]));
  cyclone10lp_lcell_comb #(.lut_mask(16'h18FA), .sum_lutc_input("datac"), .dont_touch("on"))
    nx10 (.dataa(s[10]), .datab(s[9]), .datac(s[21]), .datad(A), .combout(n[10]));
  cyclone10lp_lcell_comb #(.lut_mask(16'h3A5F), .sum_lutc_input("datac"), .dont_touch("on"))
    nx11 (.dataa(s[11]), .datab(s[10]), .datac(s[22]), .datad(C), .combout(n[11]));
  cyclone10lp_lcell_comb #(.lut_mask(16'h7FB0), .sum_lutc_input("datac"), .dont_touch("on"))
    nx12 (.dataa(s[12]), .datab(s[11]), .datac(s[23]), .datad(A), .combout(n[12]));
  cyclone10lp_lcell_comb #(.lut_mask(16'h218E), .sum_lutc_input("datac"), .dont_touch("on"))
    nx13 (.dataa(s[13]), .datab(s[12]), .datac(s[24]), .datad(C), .combout(n[13]));
  cyclone10lp_lcell_comb #(.lut_mask(16'hB48F), .sum_lutc_input("datac"), .dont_touch("on"))
    nx14 (.dataa(s[14]), .datab(s[13]), .datac(s[25]), .datad(A), .combout(n[14]));
  cyclone10lp_lcell_comb #(.lut_mask(16'hA40B), .sum_lutc_input("datac"), .dont_touch("on"))
    nx15 (.dataa(s[15]), .datab(s[14]), .datac(s[26]), .datad(C), .combout(n[15]));
  cyclone10lp_lcell_comb #(.lut_mask(16'h2BF6), .sum_lutc_input("datac"), .dont_touch("on"))
    nx16 (.dataa(s[16]), .datab(s[15]), .datac(s[27]), .datad(A), .combout(n[16]));
  cyclone10lp_lcell_comb #(.lut_mask(16'h1E9A), .sum_lutc_input("datac"), .dont_touch("on"))
    nx17 (.dataa(s[17]), .datab(s[16]), .datac(s[28]), .datad(C), .combout(n[17]));
  cyclone10lp_lcell_comb #(.lut_mask(16'h9E4D), .sum_lutc_input("datac"), .dont_touch("on"))
    nx18 (.dataa(s[18]), .datab(s[17]), .datac(s[29]), .datad(A), .combout(n[18]));
  cyclone10lp_lcell_comb #(.lut_mask(16'h5E2A), .sum_lutc_input("datac"), .dont_touch("on"))
    nx19 (.dataa(s[19]), .datab(s[18]), .datac(s[30]), .datad(C), .combout(n[19]));
  cyclone10lp_lcell_comb #(.lut_mask(16'h3361), .sum_lutc_input("datac"), .dont_touch("on"))
    nx20 (.dataa(s[20]), .datab(s[19]), .datac(s[31]), .datad(A), .combout(n[20]));
  cyclone10lp_lcell_comb #(.lut_mask(16'h992E), .sum_lutc_input("datac"), .dont_touch("on"))
    nx21 (.dataa(s[21]), .datab(s[20]), .datac(s[0]), .datad(C), .combout(n[21]));
  cyclone10lp_lcell_comb #(.lut_mask(16'h8FD8), .sum_lutc_input("datac"), .dont_touch("on"))
    nx22 (.dataa(s[22]), .datab(s[21]), .datac(s[1]), .datad(A), .combout(n[22]));
  cyclone10lp_lcell_comb #(.lut_mask(16'hD825), .sum_lutc_input("datac"), .dont_touch("on"))
    nx23 (.dataa(s[23]), .datab(s[22]), .datac(s[2]), .datad(C), .combout(n[23]));
  cyclone10lp_lcell_comb #(.lut_mask(16'hA627), .sum_lutc_input("datac"), .dont_touch("on"))
    nx24 (.dataa(s[24]), .datab(s[23]), .datac(s[3]), .datad(A), .combout(n[24]));
  cyclone10lp_lcell_comb #(.lut_mask(16'h9159), .sum_lutc_input("datac"), .dont_touch("on"))
    nx25 (.dataa(s[25]), .datab(s[24]), .datac(s[4]), .datad(C), .combout(n[25]));
  cyclone10lp_lcell_comb #(.lut_mask(16'hC65B), .sum_lutc_input("datac"), .dont_touch("on"))
    nx26 (.dataa(s[26]), .datab(s[25]), .datac(s[5]), .datad(A), .combout(n[26]));
  cyclone10lp_lcell_comb #(.lut_mask(16'h664B), .sum_lutc_input("datac"), .dont_touch("on"))
    nx27 (.dataa(s[27]), .datab(s[26]), .datac(s[6]), .datad(C), .combout(n[27]));
  cyclone10lp_lcell_comb #(.lut_mask(16'h49CE), .sum_lutc_input("datac"), .dont_touch("on"))
    nx28 (.dataa(s[28]), .datab(s[27]), .datac(s[7]), .datad(A), .combout(n[28]));
  cyclone10lp_lcell_comb #(.lut_mask(16'h1985), .sum_lutc_input("datac"), .dont_touch("on"))
    nx29 (.dataa(s[29]), .datab(s[28]), .datac(s[8]), .datad(C), .combout(n[29]));
  cyclone10lp_lcell_comb #(.lut_mask(16'hCF19), .sum_lutc_input("datac"), .dont_touch("on"))
    nx30 (.dataa(s[30]), .datab(s[29]), .datac(s[9]), .datad(A), .combout(n[30]));
  cyclone10lp_lcell_comb #(.lut_mask(16'h5968), .sum_lutc_input("datac"), .dont_touch("on"))
    nx31 (.dataa(s[31]), .datab(s[30]), .datac(s[10]), .datad(C), .combout(n[31]));
  cyclone10lp_lcell_comb #(.lut_mask(16'hC939), .sum_lutc_input("datac"), .dont_touch("on"))
    ob0 (.dataa(s[0]), .datab(s[1]), .datac(s[2]), .datad(s[3]), .combout(o[0]));
  cyclone10lp_lcell_comb #(.lut_mask(16'h4E45), .sum_lutc_input("datac"), .dont_touch("on"))
    ob1 (.dataa(s[4]), .datab(s[5]), .datac(s[6]), .datad(s[7]), .combout(o[1]));
  cyclone10lp_lcell_comb #(.lut_mask(16'hF1C1), .sum_lutc_input("datac"), .dont_touch("on"))
    ob2 (.dataa(s[8]), .datab(s[9]), .datac(s[10]), .datad(s[11]), .combout(o[2]));
  cyclone10lp_lcell_comb #(.lut_mask(16'h44E5), .sum_lutc_input("datac"), .dont_touch("on"))
    ob3 (.dataa(s[12]), .datab(s[13]), .datac(s[14]), .datad(s[15]), .combout(o[3]));
  cyclone10lp_lcell_comb #(.lut_mask(16'hD892), .sum_lutc_input("datac"), .dont_touch("on"))
    ob4 (.dataa(s[16]), .datab(s[17]), .datac(s[18]), .datad(s[19]), .combout(o[4]));
  cyclone10lp_lcell_comb #(.lut_mask(16'h75C1), .sum_lutc_input("datac"), .dont_touch("on"))
    ob5 (.dataa(s[20]), .datab(s[21]), .datac(s[22]), .datad(s[23]), .combout(o[5]));
  cyclone10lp_lcell_comb #(.lut_mask(16'h50C3), .sum_lutc_input("datac"), .dont_touch("on"))
    ob6 (.dataa(s[24]), .datab(s[25]), .datac(s[26]), .datad(s[27]), .combout(o[6]));
  cyclone10lp_lcell_comb #(.lut_mask(16'hAE45), .sum_lutc_input("datac"), .dont_touch("on"))
    ob7 (.dataa(s[28]), .datab(s[29]), .datac(s[30]), .datad(s[31]), .combout(o[7]));
  cyclone10lp_lcell_comb #(.lut_mask(16'h359D), .sum_lutc_input("datac"), .dont_touch("on"))
    pa (.dataa(o[0]), .datab(o[1]), .datac(o[2]), .datad(o[3]), .combout(p[0]));
  cyclone10lp_lcell_comb #(.lut_mask(16'hCD3D), .sum_lutc_input("datac"), .dont_touch("on"))
    pb (.dataa(o[4]), .datab(o[5]), .datac(o[6]), .datad(o[7]), .combout(p[1]));
  cyclone10lp_lcell_comb #(.lut_mask(16'hDC92), .sum_lutc_input("datac"), .dont_touch("on"))
    lut_out (.dataa(p[0]), .datab(p[1]), .datac(C), .datad(D), .combout(Q));
  always @(posedge B) s <= n;
endmodule
