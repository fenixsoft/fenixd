/**
 * version.test.ts — dsh 版本下限一致面 + 下限比较语义单测。
 * 把「MIN_DSH_VERSION 与 package.json peerDependencies 下限一致」从口头约定
 * 固化为 CI 可校验的不变量：升级时只改其中一处即在此失败，不再推迟到安装期
 * peer 检查或启动期 fail-fast 才暴露（version.ts 头注「双层防线」的前提）。
 * 同时钉住下限比较的边界形态：更高 rc / 正式版放行，低版本与 rc.0 之下拒绝。
 */
import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";

import { MIN_DSH_VERSION, assertDshCompatible, compareDshVersion } from "../src/version.ts";

const packageJson = JSON.parse(readFileSync(new URL("../package.json", import.meta.url), "utf-8")) as {
  peerDependencies: Record<string, string>;
};

describe("版本下限一致面", () => {
  it("peerDependencies[@deepseek-ai/dsh] = `>=MIN_DSH_VERSION`（下限制）", () => {
    expect(packageJson.peerDependencies["@deepseek-ai/dsh"]).toBe(`>=${MIN_DSH_VERSION}`);
  });

  it("编译锚依赖（dsh-app-boot / dsh-tools）仍逐字钉在下限版本", () => {
    // 这两个是 Bundle 编译期 API 锚（随 Bundle 分发，不代表宿主兼容面）；
    // 升级锚走独立 SPEC，与运行时下限解耦但同步起步。
    expect(packageJson.peerDependencies["@deepseek-ai/dsh-app-boot"]).toBe(MIN_DSH_VERSION);
    expect(packageJson.peerDependencies["@deepseek-ai/dsh-tools"]).toBe(MIN_DSH_VERSION);
  });
});

describe("compareDshVersion 下限比较语义", () => {
  it("更高 rc 放行（rc.5 > rc.1）", () => {
    expect(compareDshVersion("0.2.2-rc.5", "0.2.2-rc.1")).toBeGreaterThan(0);
  });

  it("正式版放行（0.2.2 > 任意 0.2.2-rc.N；semver 前序）", () => {
    expect(compareDshVersion("0.2.2", "0.2.2-rc.1")).toBeGreaterThan(0);
    expect(compareDshVersion("0.2.2", "0.2.2-rc.99")).toBeGreaterThan(0);
  });

  it("等于下限放行", () => {
    expect(compareDshVersion("0.2.2-rc.1", "0.2.2-rc.1")).toBe(0);
  });

  it("低于下限拒绝（0.2.1 / 0.2.2-rc.0）", () => {
    expect(compareDshVersion("0.2.1", "0.2.2-rc.1")).toBeLessThan(0);
    expect(compareDshVersion("0.2.2-rc.0", "0.2.2-rc.1")).toBeLessThan(0);
  });

  it("主/次段升级放行，降级拒绝", () => {
    expect(compareDshVersion("0.3.0", "0.2.2-rc.1")).toBeGreaterThan(0);
    expect(compareDshVersion("1.0.0", "0.2.2-rc.1")).toBeGreaterThan(0);
    expect(compareDshVersion("0.1.9", "0.2.2-rc.1")).toBeLessThan(0);
  });

  it("未知形态 fail-fast（不宽松猜测）", () => {
    expect(() => compareDshVersion("0.2", "0.2.2-rc.1")).toThrow(/无法解析/);
    expect(() => compareDshVersion("latest", "0.2.2-rc.1")).toThrow(/无法解析/);
  });
});

describe("assertDshCompatible 兜底层", () => {
  it("下限之上（含更高 rc/正式版）通过并返回当前版本", () => {
    expect(assertDshCompatible("0.2.2-rc.5")).toBe("0.2.2-rc.5");
    expect(assertDshCompatible("0.2.2")).toBe("0.2.2");
    expect(assertDshCompatible("0.2.2-rc.1")).toBe("0.2.2-rc.1");
  });

  it("低于下限抛明确版本错误", () => {
    expect(() => assertDshCompatible("0.2.2-rc.0")).toThrow(/版本下限不满足.*>= 0\.2\.2-rc\.1/);
  });
});
