// A 9-bit counter (D2 clock, D1 enable) addresses a 512-word ROM; D5 shows bit {D3, D4} of the
// current word.  Edit romseq.hex and run `v2bit.py write`: the new contents are written without Quartus.
module top(input A, B, C, D, output Q);
  reg [8:0] a = 0;
  always @(posedge B) if (A) a <= a + 1;
  wire [8:0] q;
  m9k_rom #(.W(9), .D(512), .INIT("romseq.hex")) rom (.clk(B), .addr(a), .q(q));
  assign Q = C ? (D ? q[3] : q[2]) : (D ? q[1] : q[0]);
endmodule
