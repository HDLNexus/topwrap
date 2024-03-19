// Copyright (c) 2023-2024 Antmicro <www.antmicro.com>
// SPDX-License-Identifier: Apache-2.0

`timescale 1ns / 1ps

module ibuf (
    input  wire clk,
    input  wire rst,
    input  wire a,
    output reg z
);

  always@(posedge clk or posedge rst) begin : proc_input_buffer
    if (rst) begin
      z <= 1'b0;
    end else begin
      z <= a;
    end

  end

endmodule

