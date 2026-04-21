import { describe, it, expect } from "vitest";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { IRSchema, validateIRIntegrity } from "../schema.js";

describe("IR Schema", () => {
  it("validates the minimal example", () => {
    const raw = JSON.parse(
      readFileSync(
        join(__dirname, "..", "..", "..", "..", "docs", "examples", "minimal-ir.json"),
        "utf-8"
      )
    );
    const result = IRSchema.safeParse(raw);
    if (!result.success) {
      console.error(JSON.stringify(result.error.format(), null, 2));
    }
    expect(result.success).toBe(true);
  });

  it("integrity check passes on minimal example", () => {
    const raw = JSON.parse(
      readFileSync(
        join(__dirname, "..", "..", "..", "..", "docs", "examples", "minimal-ir.json"),
        "utf-8"
      )
    );
    const ir = IRSchema.parse(raw);
    const errors = validateIRIntegrity(ir);
    expect(errors).toEqual([]);
  });

  it("integrity check catches dangling transition target", () => {
    const raw = JSON.parse(
      readFileSync(
        join(__dirname, "..", "..", "..", "..", "docs", "examples", "minimal-ir.json"),
        "utf-8"
      )
    );
    const ir = IRSchema.parse(raw);
    // 存在しない screen id に向ける
    ir.transitions[0]!.to = "00000000-0000-0000-0000-000000000000";
    const errors = validateIRIntegrity(ir);
    expect(errors.length).toBeGreaterThan(0);
    expect(errors[0]).toContain("not found");
  });
});
