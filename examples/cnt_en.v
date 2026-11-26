// A 24-bit counter on the 48 MHz clock K that counts while A (D1) is high; Q (D5) = its top bit, 2.861 Hz while
// counting, frozen otherwise.  The enable goes to the registers' ENA through the LAB control mux (make npnr-cnt-en).
module cnt_en(input wire K, input wire A, output wire Q);
  reg [23:0] c = 0;
  always @(posedge K) if (A) c <= c + 1;
  assign Q = c[23];
endmodule
