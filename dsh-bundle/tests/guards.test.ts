/**
 * guards.test.ts — 三守卫单测。
 * 覆盖：三类拦截命中、放行路径、无 env 不误伤、守卫先于审批生效
 * （pre-execute prepend 注册 + deny 决策形状）。
 */
import { afterEach, describe, expect, it } from "vitest";

import {
  evaluatePreToolCall,
  imageReadDecision,
  mainTreeWriteDecision,
  registerGuards,
  scenarioBatchingDecision,
  type GuardEnv,
} from "../src/guards.ts";

const ENV: GuardEnv = {
  worktree: "/root/fenixd/.claude/worktrees/impl-xxx",
  projectRoot: "/root/fenixd",
};

// ── 主树写守卫 ─────────────────────────────────────────────────────────────

describe("主树写守卫（block-main-tree-write.py 语义）", () => {
  it("worktree 内放行", () => {
    expect(mainTreeWriteDecision("/root/fenixd/.claude/worktrees/impl-xxx/src/a.ts", ENV)).toEqual({ blocked: false });
  });

  it("相对路径放行（相对 CWD=worktree 解析）", () => {
    expect(mainTreeWriteDecision("src/relative.ts", ENV)).toEqual({ blocked: false });
  });

  it("主树 .fenix/verify-progress/ 白名单放行", () => {
    expect(mainTreeWriteDecision("/root/fenixd/.fenix/verify-progress/add-fenix-dsh-bundle/qg.json", ENV)).toEqual({
      blocked: false,
    });
  });

  it("其余主树路径拦截，错误含「主树只读」与纠偏处方", () => {
    const hit = mainTreeWriteDecision("/root/fenixd/core/foo.py", ENV);
    expect(hit.blocked).toBe(true);
    expect(hit.reason).toContain("主树只读");
    expect(hit.reason).toContain("core/foo.py");
  });

  it("主树外路径（/tmp 等）不归本防线管，放行", () => {
    expect(mainTreeWriteDecision("/tmp/probe.txt", ENV)).toEqual({ blocked: false });
  });

  it("无 env（任一为空）不误伤：全部放行", () => {
    expect(mainTreeWriteDecision("/root/fenixd/core/foo.py", {})).toEqual({ blocked: false });
    expect(mainTreeWriteDecision("/root/fenixd/core/foo.py", { worktree: "", projectRoot: "/root/fenixd" })).toEqual({
      blocked: false,
    });
    expect(mainTreeWriteDecision("/root/fenixd/core/foo.py", { worktree: "/wt", projectRoot: "" })).toEqual({
      blocked: false,
    });
  });

  it(".. 穿越不绕过判定", () => {
    expect(
      mainTreeWriteDecision("/root/fenixd/.claude/worktrees/impl-xxx/../../core/foo.py", ENV).blocked,
      // 归一后落回主树 core/
    ).toBe(true);
  });

  it("worktree 自身路径放行；主树前缀相同也不误判", () => {
    expect(mainTreeWriteDecision("/root/fenixd/.claude/worktrees/impl-xxx", ENV)).toEqual({ blocked: false });
  });
});

// ── 读图拦截 ───────────────────────────────────────────────────────────────

describe("读图拦截（block-image-read.py 语义）", () => {
  it.each(["a.png", "b.jpg", "c.jpeg", "d.webp", "e.gif", "f.bmp", "g.avif", "H.PNG"])(
    "图片扩展名 %s 拦截（大小写不敏感）",
    (file) => {
      const hit = imageReadDecision(`/shots/${file}`);
      expect(hit.blocked).toBe(true);
      expect(hit.reason).toContain("不支持图像输入");
    },
  );

  it.each(["a.py", "b.md", "c.json", "noext", "d.pngx"])("非图片目标 %s 放行", (file) => {
    expect(imageReadDecision(`/src/${file}`)).toEqual({ blocked: false });
  });
});

// ── 场景批处理 ─────────────────────────────────────────────────────────────

describe("场景批处理（planner-scenario-batching.py 语义）", () => {
  const skeleton = JSON.stringify({
    scenarios: [
      { id: "s1", kind: "ui", description: "骨架场景一", steps: [], assertions: [] },
      { id: "s2", kind: "api", description: "骨架场景二", steps: [], assertions: [] },
    ],
  });
  const fleshed = JSON.stringify({
    scenarios: [
      { id: "s1", kind: "ui", description: "带肉场景", steps: [{ action: "click" }], assertions: [] },
    ],
  });

  it("首次落盘骨架放行", () => {
    expect(scenarioBatchingDecision("spec/changes/x/test_scenarios.json", skeleton, false)).toEqual({ blocked: false });
  });

  it("首次落盘带肉场景拦截并给分批处方", () => {
    const hit = scenarioBatchingDecision("test_scenarios.json", fleshed, false);
    expect(hit.blocked).toBe(true);
    expect(hit.reason).toContain("分批落盘");
    expect(hit.reason).toContain("骨架");
  });

  it("文件已存在（骨架已落）后全量重写放行", () => {
    expect(scenarioBatchingDecision("test_scenarios.json", fleshed, true)).toEqual({ blocked: false });
  });

  it("内容不可解析（非 JSON/非场景数组）fail-open 放行", () => {
    expect(scenarioBatchingDecision("test_scenarios.json", "not-json{{", false)).toEqual({ blocked: false });
    expect(scenarioBatchingDecision("test_scenarios.json", JSON.stringify({ a: 1 }), false)).toEqual({ blocked: false });
  });

  it("非场景文件不受管", () => {
    expect(scenarioBatchingDecision("other.json", fleshed, false)).toEqual({ blocked: false });
  });

  it("场景对象经 scenarios 键包裹的字典形态同样识别", () => {
    const wrapped = JSON.stringify({ version: 2, scenarios: [{ id: "s1", steps: [{ a: 1 }], assertions: [] }] });
    expect(scenarioBatchingDecision("test_scenarios.json", wrapped, false).blocked).toBe(true);
  });
});

// ── 分发与装配 ─────────────────────────────────────────────────────────────

describe("evaluatePreToolCall：按工具名路由", () => {
  it("write 落主树 → 拦", () => {
    expect(
      evaluatePreToolCall("write", { file_path: "/root/fenixd/core/x.py", content: "x" }, ENV, () => false).blocked,
    ).toBe(true);
  });

  it("edit 落主树 → 拦；read 图片 → 拦；write 带肉场景 → 拦", () => {
    expect(evaluatePreToolCall("edit", { file_path: "/root/fenixd/core/x.py" }, ENV).blocked).toBe(true);
    expect(evaluatePreToolCall("read", { file_path: "/shots/a.png" }, ENV).blocked).toBe(true);
    expect(
      evaluatePreToolCall(
        "write",
        {
          file_path: "test_scenarios.json",
          content: JSON.stringify({ scenarios: [{ id: "s", steps: [{}], assertions: [] }] }),
        },
        ENV,
        () => false,
      ).blocked,
    ).toBe(true);
  });

  it("放行路径互不误伤：read 非图片不受主树守卫影响（read 不是写类工具）", () => {
    expect(evaluatePreToolCall("read", { file_path: "/root/fenixd/core/x.py" }, ENV).blocked).toBe(false);
  });

  it("bash 等其它工具不受三守卫管（claude hook 面只覆盖 Write/Edit/Read）", () => {
    expect(evaluatePreToolCall("bash", { command: "cat /root/fenixd/core/x.py" }, ENV).blocked).toBe(false);
  });
});

describe("registerGuards：pre-execute 装配", () => {
  interface Captured {
    listener: (exec: { name: string; arguments: Record<string, unknown> }, next: () => Promise<unknown>) => Promise<unknown>;
    options?: { prepend?: boolean };
  }

  function capture() {
    const captured: Captured = {} as Captured;
    const ctx = {
      on: (_event: string, listener: Captured["listener"], options?: { prepend?: boolean }) => {
        captured.listener = listener;
        captured.options = options;
      },
    };
    registerGuards(ctx as never);
    return captured;
  }

  afterEach(() => {
    delete process.env.FENIX_RUN_WORKTREE;
    delete process.env.FENIX_RUN_PROJECT_ROOT;
  });

  it("以 prepend 注册（守卫先于审批/其它监听者生效）", () => {
    expect(capture().options?.prepend).toBe(true);
  });

  it("命中拦截：deny 决策含 reason 与 FENIX_GUARD_DENIED 码，不调 next", async () => {
    process.env.FENIX_RUN_WORKTREE = ENV.worktree!;
    process.env.FENIX_RUN_PROJECT_ROOT = ENV.projectRoot!;
    const { listener } = capture();
    let nextCalled = false;
    const decision = (await listener(
      { name: "write", arguments: { file_path: "/root/fenixd/core/x.py", content: "x" } },
      async () => {
        nextCalled = true;
        return { kind: "allow" };
      },
    )) as { kind: string; reason?: string; info?: { code: string } };
    expect(decision.kind).toBe("deny");
    expect(decision.reason).toContain("主树只读");
    expect(decision.info?.code).toBe("FENIX_GUARD_DENIED");
    expect(nextCalled).toBe(false);
  });

  it("无 env 直通：next() 被调用（放行）", async () => {
    const { listener } = capture();
    const decision = (await listener({ name: "write", arguments: { file_path: "/root/fenixd/core/x.py" } }, async () => ({
      kind: "allow",
    }))) as { kind: string };
    expect(decision.kind).toBe("allow");
  });

  it("env 在调用时读取（spawn 注入语义），补设 env 后主树拦截生效", async () => {
    const { listener } = capture();
    const next = async () => ({ kind: "allow" });
    // 读图拦截与 env 无关：无 env 也拦
    const imageDeny = (await listener({ name: "read", arguments: { file_path: "/shots/a.png" } }, next)) as {
      kind: string;
    };
    expect(imageDeny.kind).toBe("deny");
    // 主树写守卫依赖 env：无 env 放行，补设后拦
    const call = { name: "write", arguments: { file_path: "/root/fenixd/core/x.py" } };
    const before = (await listener(call, next)) as { kind: string };
    expect(before.kind).toBe("allow");
    process.env.FENIX_RUN_WORKTREE = ENV.worktree!;
    process.env.FENIX_RUN_PROJECT_ROOT = ENV.projectRoot!;
    const after = (await listener(call, next)) as { kind: string };
    expect(after.kind).toBe("deny");
  });
});
