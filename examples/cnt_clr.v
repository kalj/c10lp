// A 24-bit counter on the 48 MHz clock K with an asynchronous clear from A (D1, active low): Q (D5) = its top bit,
// 2.861 Hz while A is high, held low while A is low.  The clear goes to the registers' CLRN through the LAB control
// mux, slot 0 (make npnr-cnt-clr).
module cnt_clr(input wire K, input wire A, output wire Q);
  reg [23:0] c = 0;
  always @(posedge K or negedge A) if (!A) c <= 0; else c <= c + 1;
  assign Q = c[23];
endmodule
