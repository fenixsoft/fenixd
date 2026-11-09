/**
 * session-title.test.ts — 确定性标题装配单测 + 组装冒烟（task 1.3 以本文件集成
 * 用例承载，不新增未列管文件）。
 *
 * 单测覆盖（task 1.1 + 2026-11-09 缺陷修正）：正常派生 / 超限截断（含多字节
 * 边界不劈字符）/ 单 key 回退 / 双缺不抛错不命名 / 幂等（非内置兜底来源不覆盖）/
 * rename 抛错吞掉（监听器抛错会否决会话创建，插件 MUST 吞掉）。
 *
 * **announce 追加闸契约（2026-11-09 端到端实证）**：dsh-session 的 announce()
 * 在同步派发 session/created 期间置 announcement="dispatching"，会话流只读
 * （append 闸关闭）——监听器内**同步** rename 必抛「cannot append before
 * session/created completes」。故 rename MUST 经 queueMicrotask 推迟到派发
 * 循环同步结束（announcement=complete）之后落盘；单测以 dispatching 旗标
 * 复刻该语义，并断言同步期内零写入。
 *
 * 集成冒烟：临时 DSH_HOME + link: 挂载 + --dump-config 断言 session-title 行
 * limits 覆盖与 fenix-session-title 插件条目在场（形态同 dsh_adapter 健康检查
 * 的 dump-config 探测）；dsh 二进制缺席时明确 skip 留痕。peer 版本不符时按 CLI
 * 指引在隔离 DSH_HOME 内授予显式 allow-version 豁免（一次性冒烟环境，不改
 * bundle 钉扎）。
 */
import { execFileSync } from "node:child_process";
import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { afterEach, describe, expect, it } from "vitest";

import {
  DEFAULT_MAX_TITLE_BYTES,
  deriveSessionTitle,
  registerSessionTitle,
  type SessionTitleContext,
  type SessionTitleScope,
} from "../src/session-title.ts";

const REPO_ROOT = resolve(fileURLToPath(new URL("../..", import.meta.url)));
const BUNDLE_DIR = join(REPO_ROOT, "dsh-bundle");

// ── deriveSessionTitle（纯派生）─────────────────────────────────────────────

describe("deriveSessionTitle", () => {
  it("正常派生：两 basename 以「 · 」连接", () => {
    expect(
      deriveSessionTitle({
        FENIX_RUN_PROJECT_ROOT: "/root/cloud-phone",
        FENIX_RUN_WORKTREE: "/root/cloud-phone/.claude/worktrees/impl-code-review-fix-1794159697",
      }),
    ).toBe("cloud-phone · impl-code-review-fix-1794159697");
  });

  it("单 key 回退：仅 PROJECT_ROOT / 仅 WORKTREE 各取自身 basename", () => {
    expect(deriveSessionTitle({ FENIX_RUN_PROJECT_ROOT: "/root/cloud-phone" })).toBe("cloud-phone");
    expect(deriveSessionTitle({ FENIX_RUN_WORKTREE: "/tmp/impl-x-123/" })).toBe("impl-x-123");
  });

  it("双缺不抛错：返回 null（不命名，交由内置兜底）", () => {
    expect(deriveSessionTitle({})).toBeNull();
    expect(deriveSessionTitle({ FENIX_RUN_PROJECT_ROOT: "", FENIX_RUN_WORKTREE: "" })).toBeNull();
  });

  it("超限截断：整题 UTF-8 字节数 ≤ maxTitleBytes，多字节边界不劈字符", () => {
    const env = {
      FENIX_RUN_PROJECT_ROOT: "/root/云上工程目录名超长示例",
      FENIX_RUN_WORKTREE: "/" + "w".repeat(200),
    };
    const title = deriveSessionTitle(env, DEFAULT_MAX_TITLE_BYTES)!;
    expect(Buffer.byteLength(title, "utf-8")).toBeLessThanOrEqual(DEFAULT_MAX_TITLE_BYTES);
    expect(title).toContain(" · ");
    // 低代理对开头的残尾字符不存在（不劈开代理对）。
    const tail = title.codePointAt(title.length - 1)!;
    expect(tail < 0xdc00 || tail > 0xdfff).toBe(true);
    // 自定义上限同样生效。
    expect(deriveSessionTitle(env, 10)!.length).toBeLessThanOrEqual(10);
  });

  it("env 值非字符串按缺席处理（派生不抛错）", () => {
    expect(deriveSessionTitle({ FENIX_RUN_PROJECT_ROOT: undefined as unknown as string })).toBeNull();
  });
});

// ── registerSessionTitle（装配接线）────────────────────────────────────────

interface Harness {
  ctx: SessionTitleContext;
  fireCreated(session: unknown): void;
  renames: Array<{ session: unknown; title: string }>;
  warns: string[];
  setExisting(snapshot: { title: string; source: { kind: string } } | undefined): void;
}

/** 最小宿主桩：inject 直调、session/created 监听器可手动触发。 */
function makeHarness(serviceOverride?: Partial<SessionTitleScope["sessionTitle"]>): Harness {
  const listeners: Array<(session: unknown) => void> = [];
  const renames: Array<{ session: unknown; title: string }> = [];
  const warns: string[] = [];
  let existing: { title: string; source: { kind: string } } | undefined;
  const scope: SessionTitleScope = {
    sessionTitle: {
      get: () => existing,
      rename: (session: unknown, title: string) => {
        renames.push({ session, title });
        return undefined;
      },
      ...serviceOverride,
    },
  };
  const ctx: SessionTitleContext = {
    inject: (_deps, fn) => fn(scope),
    on: (_event, listener) => {
      listeners.push(listener);
      return undefined;
    },
    logger: { warn: (...args: unknown[]) => void warns.push(args.join(" ")) },
  };
  return {
    ctx,
    renames,
    warns,
    setExisting: (snap) => void (existing = snap),
    fireCreated: (session: unknown) => listeners.forEach((l) => l(session)),
  };
}

const SESSION = { id: "session-1" };

/** 微任务清空：两跳队列，确保监听器排入的延迟任务已执行完毕。 */
const flush = (): Promise<void> =>
  new Promise<void>((resolve) => queueMicrotask(() => queueMicrotask(resolve)));

describe("registerSessionTitle", () => {
  it("env 齐备：session/created 后 rename（异步落盘，同步派发期内不得写）", async () => {
    const h = makeHarness();
    registerSessionTitle(h.ctx, {
      env: { FENIX_RUN_PROJECT_ROOT: "/root/cloud-phone", FENIX_RUN_WORKTREE: "/wt/impl-x-1" },
    });
    h.fireCreated(SESSION);
    // 同步派发期内零写入（dsh announce 期间会话流只读，同步 rename 必抛）。
    expect(h.renames).toEqual([]);
    await flush();
    expect(h.renames).toEqual([{ session: SESSION, title: "cloud-phone · impl-x-1" }]);
  });

  it("双缺 env：不命名、rename 未被调用、监听器不抛错", async () => {
    const h = makeHarness();
    expect(() => {
      registerSessionTitle(h.ctx, { env: {} });
    }).not.toThrow();
    expect(() => h.fireCreated(SESSION)).not.toThrow();
    await flush();
    expect(h.renames).toEqual([]);
  });

  it("幂等：已有 user/provider 源标题不覆盖；fallback 源覆盖", async () => {
    const env = { FENIX_RUN_PROJECT_ROOT: "/root/cloud-phone", FENIX_RUN_WORKTREE: "/wt/impl-x-2" };
    // user 源（此前本插件 rename 或真实用户改名）→ skip。
    const h1 = makeHarness();
    registerSessionTitle(h1.ctx, { env });
    h1.setExisting({ title: "旧标题", source: { kind: "user" } });
    h1.fireCreated(SESSION);
    await flush();
    expect(h1.renames).toEqual([]);
    // provider 源 → skip。
    const h2 = makeHarness();
    registerSessionTitle(h2.ctx, { env });
    h2.setExisting({ title: "LLM 题", source: { kind: "provider" } });
    h2.fireCreated(SESSION);
    await flush();
    expect(h2.renames).toEqual([]);
    // fallback 源（内置兜底）→ 覆盖为确定性标题。
    const h3 = makeHarness();
    registerSessionTitle(h3.ctx, { env });
    h3.setExisting({ title: "fallback 题", source: { kind: "fallback" } });
    h3.fireCreated(SESSION);
    await flush();
    expect(h3.renames).toEqual([{ session: SESSION, title: "cloud-phone · impl-x-2" }]);
    // 无标题（首次创建）→ 命名。
    const h4 = makeHarness();
    registerSessionTitle(h4.ctx, { env });
    h4.fireCreated(SESSION);
    await flush();
    expect(h4.renames).toHaveLength(1);
  });

  it("rename 抛错：吞掉并 WARN 留痕，不向 session/created 传播（不否决会话创建）", async () => {
    const h = makeHarness({
      get: () => undefined,
      rename: () => {
        throw new Error("session not live");
      },
    });
    registerSessionTitle(h.ctx, {
      env: { FENIX_RUN_PROJECT_ROOT: "/root/cloud-phone", FENIX_RUN_WORKTREE: "/wt/impl-x-3" },
    });
    expect(() => h.fireCreated(SESSION)).not.toThrow();
    await flush();
    expect(h.warns.join("\n")).toContain("会话确定性标题写入失败");
  });

  it("dsh announce 追加闸契约：同步派发期间 rename 必抛 → 推迟到派发完成后落盘", async () => {
    // 复刻 dsh-session announce() 语义（2026-11-09 端到端实证）：dispatching
    // 期间 append 闸关闭，同步 rename 抛「cannot append before session/created
    // completes」；派发循环同步结束后闸开。插件监听器 MUST 推迟到此后写。
    let dispatching = false;
    const renamed: string[] = [];
    const h = makeHarness({
      get: () => undefined,
      rename: (session: unknown, title: string) => {
        if (dispatching) {
          throw new Error(
            `session "${(session as { id: string }).id}" cannot append before session/created completes`,
          );
        }
        renamed.push(title);
        return undefined;
      },
    });
    registerSessionTitle(h.ctx, {
      env: { FENIX_RUN_PROJECT_ROOT: "/root/cloud-phone", FENIX_RUN_WORKTREE: "/wt/impl-x-4" },
    });
    dispatching = true;
    expect(() => h.fireCreated(SESSION)).not.toThrow();
    dispatching = false; // announce 循环同步结束 → announcement=complete
    await flush();
    expect(renamed).toEqual(["cloud-phone · impl-x-4"]);
    expect(h.warns.join("\n")).not.toContain("会话确定性标题写入失败"); // 正常路径零告警
  });
});

// ── 组装冒烟（task 1.3 承载；dsh 二进制缺席时 skip 留痕）───────────────────

const dshBin = (() => {
  try {
    return execFileSync("which", ["dsh"], { encoding: "utf-8" }).trim();
  } catch {
    return "";
  }
})();

describe("组装冒烟（dump-config）", () => {
  afterEach(() => {
    // tmpdir 由 OS 兜底清理；此处尽早回收（pnpm link 目录极小）。
  });

  it.skipIf(!dshBin)("临时 DSH_HOME + link 挂载 → dump-config 断言标题装配", { timeout: 180_000 }, () => {
    const home = mkdtempSync(join(tmpdir(), "dsh-title-smoke-"));
    const env = { ...process.env, DSH_HOME: home };
    try {
      const run = (args: string[], timeoutMs: number): string =>
        execFileSync(dshBin, args, { env, encoding: "utf-8", timeout: timeoutMs, stdio: ["ignore", "pipe", "pipe"] });
      // 1) 首次创建 profile（复用 shipped headless 模板）。
      run(["--profile", "fenix-title-smoke", "--from-default-profile", "headless", "--dump-config"], 60_000);
      // 2) link: 挂载 bundle；peer 版本不符（系统 dsh 高于钉扎）时按 CLI 指引
      //    在隔离 DSH_HOME 内授予显式豁免后重试（不改 bundle 钉扎纪律）。
      const add = () => run(["plugin", "--profile", "fenix-title-smoke", "add", `link:${BUNDLE_DIR}`], 120_000);
      try {
        add();
      } catch (err) {
        const text = err instanceof Error ? String((err as { stdout?: string }).stdout ?? err.message) : String(err);
        if (!text.includes("incompatible")) throw err;
        run(
          [
            "plugin", "--profile", "fenix-title-smoke", "allow-version",
            "fenix-dsh-bundle@0.1.0", "--dsh-version", "0.2.2-rc.1", "--accept-risk",
          ],
          60_000,
        );
        add();
      }
      // 3) dump-config 断言：session-title 行 limits 已被本 bundle 覆盖为
      //    8/96/120，且 fenix-session-title 插件条目在场。
      const dump = run(["--profile", "fenix-title-smoke", "--dump-config"], 60_000);
      expect(dump).toContain("id: session-title");
      expect(dump).toContain("fallbackMaxWords: 8");
      expect(dump).toContain("fallbackMaxBytes: 96");
      expect(dump).toContain("maxTitleBytes: 120");
      expect(dump).toContain("id: fenix-session-title");
    } finally {
      rmSync(home, { recursive: true, force: true });
    }
  });

  it.skipIf(dshBin)("dsh 二进制缺席：明确 skip 留痕", () => {
    // which dsh 失败 → 本用例唯一到达路径；留痕即 spec 1.3 的「明确 skip」。
    expect(dshBin).toBe("");
  });
});
