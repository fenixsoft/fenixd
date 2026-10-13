/**
 * approval.test.ts — 非交互审批策略单测。
 * 覆盖：cordis.patch.yml 的策略条目与 approvalPatchEntries() 全等（config-as-code
 * 防漂移）、assertUnattendedSafe 的放行/拒绝、常量值对齐 dsh 的 bypassPermissions
 * 等价物（sandbox danger-full-access + approval never）。
 */
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";
import yaml from "js-yaml";

import {
  approvalPatchEntries,
  assertUnattendedSafe,
  EXPECTED_APPROVAL_POLICY,
  EXPECTED_SANDBOX_MODE,
} from "../src/approval.ts";

const PATCH_PATH = fileURLToPath(new URL("../cordis.patch.yml", import.meta.url));

/** dsh 的 !!js 方言：表达式按惰性表示 {__jsExpr: <文本>} 构造（不求值）。 */
const JsExprType = new yaml.Type("tag:yaml.org,2002:js", {
  kind: "scalar",
  resolve: () => true,
  construct: (data: string) => ({ __jsExpr: String(data) }),
});
// js-yaml 4 无公开 createSchema：以 Schema(include JSON_SCHEMA) 扩展自定义 tag
const DshPatchSchema = new yaml.Schema({ include: [yaml.JSON_SCHEMA], explicit: [JsExprType] });

describe("策略常量（等价 bypassPermissions 的两块面）", () => {
  it("审批策略 = never（无人被询问，零交互阻塞）", () => {
    expect(EXPECTED_APPROVAL_POLICY).toBe("never");
  });

  it("沙箱模式 = danger-full-access（工具不触发升级询问）", () => {
    expect(EXPECTED_SANDBOX_MODE).toBe("danger-full-access");
  });
});

describe("cordis.patch.yml 与 approvalPatchEntries() 全等（config-as-code）", () => {
  const patchDoc = yaml.load(readFileSync(PATCH_PATH, "utf8"), { schema: DshPatchSchema }) as Array<
    Record<string, unknown>
  >;

  it("patch 里 sandbox-policy / approval 两条与代码单一来源逐字一致", () => {
    for (const expected of approvalPatchEntries()) {
      const actual = patchDoc.find((e) => e.id === expected.id);
      expect(actual, `patch 缺少 id=${expected.id} 条目`).toBeDefined();
      expect(actual).toEqual(expected);
    }
  });

  it("审批面语义正确：mode=danger-full-access 且 policy=never 同时成立", () => {
    const sandbox = patchDoc.find((e) => e.id === "sandbox-policy") as { config: { mode: string } };
    const approval = patchDoc.find((e) => e.id === "approval") as { config: { policy: string } };
    expect(sandbox.config.mode).toBe("danger-full-access");
    expect(approval.config.policy).toBe("never");
  });
});

describe("assertUnattendedSafe", () => {
  it("never 放行", () => {
    expect(assertUnattendedSafe("never")).toBe("never");
  });

  it("ask 拒绝（交互确认会阻塞无人值守运行）", () => {
    expect(() => assertUnattendedSafe("ask")).toThrow(/无人值守零交互阻塞/);
  });

  it("空值/未知值拒绝", () => {
    expect(() => assertUnattendedSafe("")).toThrow(/无人值守零交互阻塞/);
    expect(() => assertUnattendedSafe("yolo")).toThrow(/无人值守零交互阻塞/);
  });
});
