// A 24-bit counter on the 48 MHz clock K with a synchronous clear from A (D1, active high): Q (D5) = its top bit,
// 2.861 Hz while A is low, held low while A is high.  Yosys folds a behavioural sync clear into the LUTs, so the
// registers are dffeas instances with .sclr(A): the clear goes to SCLR through the LAB control mux, slot 2
// (make npnr-cnt-sclr).
module cnt_sclr(input wire K, input wire A, output wire Q);
  wire [23:0] c;
  wire [23:0] n = c + 1;
  genvar i;
  generate for (i = 0; i < 24; i = i + 1) begin : r
    dffeas f (.d(n[i]), .clk(K), .q(c[i]), .ena(1'b1), .clrn(1'b1), .prn(1'b1), .sclr(A), .aload(1'b0), .asdata(1'b0),
              .sload(1'b0));
  end endgenerate
  assign Q = c[23];
endmodule
