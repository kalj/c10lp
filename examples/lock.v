// A combination lock, the second real design: Q (D5) goes high once D1..D4 (A..D) have stepped through
// 0001 -> 0011 -> 0111 -> 1111 (one pin changing per step, so the test bench's pin-by-pin updates never show a wrong
// code to the 48 MHz state machine); any other code on the way resets it.  make npnr-lock.
module lock(input wire K, input wire A, input wire B, input wire C, input wire D, output wire Q);
  wire [3:0] in = {D, C, B, A};
  reg [2:0] s = 0;
  always @(posedge K)
    case (s)
      3'd0: if (in == 4'b0001) s <= 3'd1;
      3'd1: if (in == 4'b0011) s <= 3'd2; else if (in != 4'b0001) s <= 3'd0;
      3'd2: if (in == 4'b0111) s <= 3'd3; else if (in != 4'b0011) s <= 3'd0;
      3'd3: if (in == 4'b1111) s <= 3'd4; else if (in != 4'b0111) s <= 3'd0;
      default: if (in != 4'b1111) s <= 3'd0;
    endcase
  reg q = 0;
  always @(posedge K) q <= (s == 3'd4);
  assign Q = q;
endmodule
