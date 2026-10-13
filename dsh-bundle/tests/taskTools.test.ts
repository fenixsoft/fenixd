/**
 * taskTools.test.ts — Task 工具族单测。
 * 覆盖：1 基创建序、状态流转（pending→in_progress→completed）、并发更新、
 * 参数校验失败路径、会话隔离、注册面（四工具名与参数形状对齐 claude 语义）。
 */
import { describe, expect, it } from "vitest";

import {
  registerTaskTools,
  TaskStore,
  type FenixTask,
} from "../src/taskTools.ts";

const S = "session-a";

describe("TaskStore：1 基创建序", () => {
  it("同一会话内连续创建三条，taskId 依次为 1、2、3", () => {
    const store = new TaskStore();
    expect(store.create(S, { subject: "任务一" }).taskId).toBe(1);
    expect(store.create(S, { subject: "任务二" }).taskId).toBe(2);
    expect(store.create(S, { subject: "任务三" }).taskId).toBe(3);
  });

  it("新创建的任务 status 恒为 pending，字段缺省为空串/空对象", () => {
    const store = new TaskStore();
    const task = store.create(S, { subject: "只有标题" });
    expect(task).toMatchObject({ taskId: 1, subject: "只有标题", status: "pending", description: "", activeForm: "", metadata: {} });
  });

  it("不同会话的状态表互相隔离，各自从 1 起号", () => {
    const store = new TaskStore();
    store.create(S, { subject: "A1" });
    store.create("session-b", { subject: "B1" });
    expect(store.get(S, 1).subject).toBe("A1");
    expect(store.get("session-b", 1).subject).toBe("B1");
    expect(store.list(S)).toHaveLength(1);
    expect(store.list("session-b")).toHaveLength(1);
  });

  it("reset 清空会话状态表，再创建从 1 重新起号", () => {
    const store = new TaskStore();
    store.create(S, { subject: "旧任务" });
    store.reset(S);
    expect(store.list(S)).toHaveLength(0);
    expect(store.create(S, { subject: "新任务" }).taskId).toBe(1);
  });
});

describe("TaskStore：状态流转", () => {
  it("pending→in_progress→completed 全链", () => {
    const store = new TaskStore();
    store.create(S, { subject: "推进任务" });
    expect(store.update(S, { taskId: 1, status: "in_progress" }).status).toBe("in_progress");
    expect(store.update(S, { taskId: 1, status: "completed" }).status).toBe("completed");
  });

  it("单字段更新不改其它字段；metadata 可整体替换", () => {
    const store = new TaskStore();
    store.create(S, { subject: "原标题", description: "原描述", metadata: { a: 1 } });
    const updated = store.update(S, { taskId: 1, subject: "新标题" });
    expect(updated.subject).toBe("新标题");
    expect(updated.description).toBe("原描述");
    expect(updated.metadata).toEqual({ a: 1 });
    expect(store.update(S, { taskId: 1, metadata: { b: 2 } }).metadata).toEqual({ b: 2 });
  });
});

describe("TaskStore：并发更新", () => {
  it("同一任务被交错更新时各字段按调用序最终一致", async () => {
    const store = new TaskStore();
    store.create(S, { subject: "并发任务" });
    // 模拟并发：多个 update promise 交错提交（JS 单线程下按微任务序串行落库）
    const ops = [
      () => store.update(S, { taskId: 1, status: "in_progress" }),
      () => store.update(S, { taskId: 1, subject: "改名" }),
      () => store.update(S, { taskId: 1, status: "completed" }),
      () => store.update(S, { taskId: 1, activeForm: "收尾中" }),
    ];
    await Promise.all(ops.map((op, i) => new Promise((r) => setTimeout(r, i % 2)).then(op)));
    const final = store.get(S, 1);
    expect(final.status).toBe("completed");
    expect(final.subject).toBe("改名");
    expect(final.activeForm).toBe("收尾中");
    expect(store.list(S)).toHaveLength(1);
  });

  it("多任务并存时按 taskId 精确命中，不串号", () => {
    const store = new TaskStore();
    store.create(S, { subject: "甲" });
    store.create(S, { subject: "乙" });
    store.create(S, { subject: "丙" });
    store.update(S, { taskId: 2, status: "completed" });
    expect(store.get(S, 1).status).toBe("pending");
    expect(store.get(S, 2).status).toBe("completed");
    expect(store.get(S, 3).status).toBe("pending");
  });
});

describe("TaskStore：参数校验失败路径", () => {
  const store = new TaskStore();
  store.create(S, { subject: "存在" });

  it("空 subject 拒绝", () => {
    expect(() => store.create(S, { subject: "" })).toThrow(/subject/);
    expect(() => store.create(S, {} as never)).toThrow(/subject/);
  });

  it("非法 status 拒绝并回显词表", () => {
    expect(() => store.update(S, { taskId: 1, status: "done" as never })).toThrow(/pending\|in_progress\|completed/);
  });

  it("未知 taskId 拒绝（not found）", () => {
    expect(() => store.update(S, { taskId: 99, status: "completed" })).toThrow(/not found/);
    expect(() => store.get(S, 99)).toThrow(/not found/);
  });

  it("taskId 非 1 基正整数拒绝", () => {
    expect(() => store.update(S, { taskId: 0, status: "completed" })).toThrow(/taskId/);
    expect(() => store.get(S, 1.5)).toThrow(/taskId/);
  });

  it("metadata 非对象拒绝", () => {
    expect(() => store.create(S, { subject: "x", metadata: [1, 2] as never })).toThrow(/metadata/);
  });

  it("TaskUpdate 空更新（无任何字段）拒绝", () => {
    expect(() => store.update(S, { taskId: 1 })).toThrow(/至少需要一个更新字段/);
  });
});

// ── 注册面：四工具名与参数形状 ─────────────────────────────────────────────

interface CapturedTool {
  name: string;
  description: string;
  parameters: Record<string, { type: string; required?: boolean; enum?: string[] }>;
  execute: (args: unknown, exec: { agent?: { id?: string } | null }) => unknown;
  output: { render: (args: unknown, value: unknown) => Array<{ type: string; text: string }> };
}

function captureRegisteredTools(): CapturedTool[] {
  const captured: CapturedTool[] = [];
  registerTaskTools({ tools: { register: (d) => captured.push(d as CapturedTool) } });
  return captured;
}

describe("registerTaskTools：注册面", () => {
  const tools = captureRegisteredTools();

  it("恰好注册 TaskCreate/TaskUpdate/TaskGet/TaskList 四工具", () => {
    expect(tools.map((t) => t.name)).toEqual(["TaskCreate", "TaskUpdate", "TaskGet", "TaskList"]);
  });

  it("TaskCreate 的 subject 必填、status 不由调用方指定（创建即 pending）", () => {
    const create = tools[0];
    expect(create.parameters.subject).toMatchObject({ type: "string", required: true });
    expect(create.parameters.metadata?.type).toBe("object");
    expect(create.parameters.status).toBeUndefined();
  });

  it("TaskUpdate 的 taskId 必填、status 枚举对齐 claude 词表", () => {
    const update = tools[1];
    expect(update.parameters.taskId).toMatchObject({ type: "number", required: true });
    expect(update.parameters.status?.enum).toEqual(["pending", "in_progress", "completed"]);
  });

  it("execute 链路：创建→更新→读取走同一会话状态表", () => {
    const [create, update, get, list] = tools;
    const exec = { agent: { id: "exec-session" } };
    const created = create.execute({ subject: "链路任务" }, exec) as { taskId: number; status: string };
    expect(created).toEqual({ taskId: 1, subject: "链路任务", status: "pending" });
    const updated = update.execute({ taskId: 1, status: "completed" }, exec) as { status: string };
    expect(updated.status).toBe("completed");
    expect((get.execute({ taskId: 1 }, exec) as FenixTask).subject).toBe("链路任务");
    expect((list.execute({}, exec) as { count: number }).count).toBe(1);
  });

  it("execute 校验失败路径与纯逻辑一致（缺 subject 抛错）", () => {
    const create = tools[0];
    expect(() => create.execute({ subject: "" }, { agent: { id: "s" } })).toThrow(/subject/);
  });

  it("output.render 产出人类可读文本", () => {
    const [create] = tools;
    const lines = create.output.render({}, { taskId: 3, subject: "渲染任务", status: "pending" });
    expect(lines[0].text).toContain("Task 3 created successfully");
    expect(lines[0].text).toContain("渲染任务");
  });
});
