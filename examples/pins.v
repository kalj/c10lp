// The Vidor's test inputs D1..D4 (A..D) into D5 (Q) through three registered LEs: Q = (A ^ B) | (C & D), one clock
// later.  Every input reaches its LUT over the pin path library (make npnr-pins).
module pins(input wire K, input wire A, input wire B, input wire C, input wire D, output wire Q);
  reg r1 = 0, r2 = 0, q = 0;
  always @(posedge K) begin
    r1 <= A ^ B;
    r2 <= C & D;
    q <= r1 | r2;
  end
  assign Q = q;
endmodule
