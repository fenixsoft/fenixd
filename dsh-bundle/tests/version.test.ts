/**
 * version.test.ts — 版本钉扎静态一致面单测。
 * 把「PINNED_DSH_VERSION 与 package.json peerDependencies 逐字一致」从口头约定
 * 固化为 CI 可校验的不变量：升级时只改其中一处即在此失败，不再推迟到安装期
 * peer 检查或启动期 fail-fast 才暴露（version.ts 头注「双层防线」的前提）。
 */
import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";

import { PINNED_DSH_VERSION } from "../src/version.ts";

const packageJson = JSON.parse(readFileSync(new URL("../package.json", import.meta.url), "utf-8")) as {
  peerDependencies: Record<string, string>;
};

describe("版本钉扎一致面", () => {
  it("PINNED_DSH_VERSION 与 package.json peerDependencies[@deepseek-ai/dsh] 逐字一致", () => {
    expect(packageJson.peerDependencies["@deepseek-ai/dsh"]).toBe(PINNED_DSH_VERSION);
  });
});
