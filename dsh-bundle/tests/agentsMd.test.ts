/**
 * agentsMd.test.ts — AGENTS.md system-prompt 分区单测。
 * 覆盖：分区文本形态（标记 + 正文）、缺文件/空文件零贡献、软链正文透出、
 * 注册接线（inject(["systemPrompt"]) → section 注册，text 现读 cwd）。
 */
import { mkdtempSync, mkdirSync, symlinkSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { afterEach, describe, expect, it } from "vitest";

import { AGENTS_MD_SECTION_NAME, agentsMdSectionText, registerAgentsMdSection } from "../src/agentsMd.ts";

const dirs: string[] = [];
function tmpWs(): string {
  const d = mkdtempSync(join(tmpdir(), "agentsmd-"));
  dirs.push(d);
  return d;
}
afterEach(() => {
  // tmpdir 由 OS 清理，不逐个删（测试进程退出即弃）
});

describe("agentsMdSectionText（分区文本纯函数）", () => {
  it("有内容：含 Instructions from: AGENTS.md 标记与正文", () => {
    const text = agentsMdSectionText("/any", () => "FENIX-DSH-PROBE-MARKER-7f3a9: bundle carrier check");
    expect(text).toContain("Instructions from: AGENTS.md");
    expect(text).toContain("FENIX-DSH-PROBE-MARKER-7f3a9: bundle carrier check");
    expect(text.startsWith("<system-reminder>")).toBe(true);
  });

  it("文件不存在：返回空串（renderPrompt 丢弃空 section，零影响）", () => {
    expect(agentsMdSectionText("/any", () => {
      throw Object.assign(new Error("ENOENT"), { code: "ENOENT" });
    })).toBe("");
  });

  it("空文件/纯空白：返回空串", () => {
    expect(agentsMdSectionText("/any", () => "  \n\t\n")).toBe("");
  });

  it("尾部空白归一，正文逐字保留", () => {
    const text = agentsMdSectionText("/any", () => "# 规则\n\n- 主树只读\n");
    expect(text).toContain("# 规则\n\n- 主树只读\n</system-reminder>");
  });
});

describe("registerAgentsMdSection（dsh 装配接线）", () => {
  it("inject systemPrompt 并以 FILE_REFERENCE 档位注册 fenix:agents-md 分区", () => {
    const registered: Array<{ name: string; order: number; text: () => string }> = [];
    const injected: string[][] = [];
    const ctx = {
      inject(deps: string[], fn: (scope: unknown) => void): unknown {
        injected.push(deps);
        fn({
          systemPrompt: {
            section(s: { name: string; order: number; text: () => string }) {
              registered.push(s);
              return () => {};
            },
            getSectionOrder(name: string) {
              expect(name).toBe("FILE_REFERENCE");
              return 900;
            },
          },
        });
        return () => {};
      },
    };
    registerAgentsMdSection(ctx);
    expect(injected).toEqual([["systemPrompt"]]);
    expect(registered).toHaveLength(1);
    expect(registered[0].name).toBe(AGENTS_MD_SECTION_NAME);
    expect(registered[0].order).toBe(900);
  });

  it("text 在 assembly 时读当前 cwd 的 AGENTS.md（软链正文透出）", () => {
    const ws = tmpWs();
    writeFileSync(join(ws, "CLAUDE.md"), "FENIX-DSH-PROBE-MARKER-7f3a9: bundle carrier check");
    symlinkSync("CLAUDE.md", join(ws, "AGENTS.md"));

    let captured = "";
    const ctx = {
      inject(_deps: string[], fn: (scope: unknown) => void): unknown {
        fn({
          systemPrompt: {
            section(s: { text: () => string }) {
              const prev = process.cwd();
              process.chdir(ws);
              try {
                captured = s.text();
              } finally {
                process.chdir(prev);
              }
              return () => {};
            },
            getSectionOrder: () => 900,
          },
        });
        return () => {};
      },
    };
    registerAgentsMdSection(ctx);
    expect(captured).toContain("FENIX-DSH-PROBE-MARKER-7f3a9: bundle carrier check");
  });

  it("cwd 无 AGENTS.md 时 text 返回空串（不影响既有场景工作区）", () => {
    const ws = tmpWs();
    mkdirSync(join(ws, "keep"), { recursive: true });
    let captured = "sentinel";
    const ctx = {
      inject(_deps: string[], fn: (scope: unknown) => void): unknown {
        fn({
          systemPrompt: {
            section(s: { text: () => string }) {
              const prev = process.cwd();
              process.chdir(ws);
              try {
                captured = s.text();
              } finally {
                process.chdir(prev);
              }
              return () => {};
            },
            getSectionOrder: () => 900,
          },
        });
        return () => {};
      },
    };
    registerAgentsMdSection(ctx);
    expect(captured).toBe("");
  });
});
