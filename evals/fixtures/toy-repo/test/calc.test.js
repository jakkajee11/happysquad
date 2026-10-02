import { test } from "node:test";
import assert from "node:assert/strict";
import { add, sub } from "../src/calc.js";
import { slowOnce } from "../src/slow.js";

test("slow gate (first run only)", () => {
  slowOnce();
});

test("add", () => {
  assert.equal(add(2, 3), 5);
});

test("sub", () => {
  assert.equal(sub(5, 3), 2);
});
