/**
 * taskTools.ts — Task 工具族插件（TaskCreate/TaskUpdate/TaskGet/TaskList）。
 *
 * 成对契约（design）：fenixd 的 prompt 契约段要求 agent 调用 TaskCreate/TaskUpdate，
 * 读侧 run_task_track.py 解析 tool_use block——本插件让 dsh 通道的写侧成立。
 *
 * 语义对齐 claude：
 * - 签名关键字段 subject / status / metadata；status 枚举 pending|in_progress|completed；
 * - taskId 遵循 1 基创建序（run_task_track.py 硬约定），会话内单调递增不复用；
 * - 状态存于「会话内状态表」：按发起 agent（会话）隔离的内存 Map——本 Bundle
 *   在 headless 无人值守车道运行，会话即一次 run，进程生命周期与会话一致。
 *
 * 事件发射（tool_call / tool_result）由 dsh agent-loop 对任意工具调用统一追加，
 * headless --json 投影为 {type:"tool_call", callId, tool:"TaskCreate", input:{...}}——
 * 工具名与参数形状即投影表输入，本文件只保证注册名与参数字段对齐 claude。
 *
 * 纯逻辑（TaskStore 等）与 dsh 装配（registerTaskTools）分离：单测零 dsh 依赖。
 */

import { defineTool } from "@deepseek-ai/dsh-tools";

// ── 纯逻辑：任务状态表 ─────────────────────────────────────────────────────

export type TaskStatus = "pending" | "in_progress" | "completed";

export const TASK_STATUSES: readonly TaskStatus[] = ["pending", "in_progress", "completed"];

export interface FenixTask {
  taskId: number;
  subject: string;
  description: string;
  activeForm: string;
  metadata: Record<string, unknown>;
  status: TaskStatus;
}

export interface TaskCreateInput {
  subject: string;
  description?: string;
  activeForm?: string;
  metadata?: Record<string, unknown>;
}

export interface TaskUpdateInput {
  taskId: number;
  status?: TaskStatus;
  subject?: string;
  description?: string;
  activeForm?: string;
  metadata?: Record<string, unknown>;
}

export class TaskStore {
  /** 会话（agent）id → 该会话的任务表；taskId 从 1 递增，不复用。 */
  private readonly sessions = new Map<string, FenixTask[]>();

  private table(sessionId: string): FenixTask[] {
    let table = this.sessions.get(sessionId);
    if (!table) {
      table = [];
      this.sessions.set(sessionId, table);
    }
    return table;
  }

  /** 丢弃会话状态表（无任务时也清键，防跨 run 残留）。 */
  reset(sessionId: string = "default"): void {
    this.sessions.delete(sessionId);
  }

  /** 是否仍持有任何会话键（含空表，语义对齐 reset 的「无任务也清键」）；供启动期校验。 */
  isPristine(): boolean {
    return this.sessions.size === 0;
  }

  create(sessionId: string, input: TaskCreateInput): FenixTask {
    const subject = requireNonEmptyString(input?.subject, "subject");
    const task: FenixTask = {
      taskId: this.table(sessionId).length + 1,
      subject,
      description: optionalString(input.description),
      activeForm: optionalString(input.activeForm),
      metadata: input.metadata === undefined ? {} : requirePlainObject(input.metadata, "metadata"),
      status: "pending",
    };
    this.table(sessionId).push(task);
    return task;
  }

  update(sessionId: string, input: TaskUpdateInput): FenixTask {
    const taskId = requireInteger(input?.taskId, "taskId");
    const hasField =
      input.status !== undefined ||
      input.subject !== undefined ||
      input.description !== undefined ||
      input.activeForm !== undefined ||
      input.metadata !== undefined;
    if (!hasField) {
      throw new Error("TaskUpdate 至少需要一个更新字段（status/subject/description/activeForm/metadata）");
    }
    const task = this.get(sessionId, taskId);
    if (input.status !== undefined) {
      if (!TASK_STATUSES.includes(input.status)) {
        throw new Error(`status 必须是 ${TASK_STATUSES.join("|")} 之一，收到 ${JSON.stringify(input.status)}`);
      }
      task.status = input.status;
    }
    if (input.subject !== undefined) task.subject = requireNonEmptyString(input.subject, "subject");
    if (input.description !== undefined) task.description = optionalString(input.description);
    if (input.activeForm !== undefined) task.activeForm = optionalString(input.activeForm);
    if (input.metadata !== undefined) task.metadata = requirePlainObject(input.metadata, "metadata");
    return task;
  }

  get(sessionId: string, taskId: number): FenixTask {
    const id = requireInteger(taskId, "taskId");
    const task = this.table(sessionId).find((t) => t.taskId === id);
    if (!task) {
      throw new Error(`Task with taskId ${id} not found`);
    }
    return task;
  }

  list(sessionId: string): FenixTask[] {
    return [...this.table(sessionId)];
  }
}

function requireNonEmptyString(value: unknown, field: string): string {
  if (typeof value !== "string" || value.trim() === "") {
    throw new Error(`${field} 必须是非空字符串，收到 ${JSON.stringify(value ?? null)}`);
  }
  return value;
}

function optionalString(value: unknown): string {
  return typeof value === "string" ? value : "";
}

function requirePlainObject(value: unknown, field: string): Record<string, unknown> {
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    throw new Error(`${field} 必须是对象，收到 ${JSON.stringify(value ?? null)}`);
  }
  return value as Record<string, unknown>;
}

function requireInteger(value: unknown, field: string): number {
  if (typeof value !== "number" || !Number.isInteger(value) || value < 1) {
    throw new Error(`${field} 必须是 1 基正整数，收到 ${JSON.stringify(value ?? null)}`);
  }
  return value;
}

// ── dsh 装配：注册四工具 ───────────────────────────────────────────────────

/** 会话内共享的单例状态表（跨多次 register 复用同一进程状态无意义，取模块级单例）。 */
const sharedStore = new TaskStore();

function sessionIdOf(exec: { agent?: { id?: string } | null }): string {
  return exec.agent?.id ?? "default";
}

/** 注册 TaskCreate/TaskUpdate/TaskGet/TaskList 四工具（签名对齐 claude 语义）。 */
export function registerTaskTools(ctx: { tools: { register(definition: unknown): unknown } }): void {
  // 启动期校验：「进程单会话」假设的显式化（见文件头注——headless 车道会话即一次 run）。
  // 模块级单例只在进程生命周期覆盖单次 run 的前提下安全；dsh 侧无会话/run 终态事件，
  // reset() 无生产调用方。若进程模型变为同进程串行多 run 而重装配本插件，上一 run 的
  // 任务清单与 1 基 taskId 序列会经 sharedStore 泄漏进下一 run（读侧 run_task_track.py
  // 按 taskId 关联的记账随之串号）——此处立即抛错显式暴露，而不是静默串号。
  if (!sharedStore.isPristine()) {
    throw new Error(
      "TaskStore 存在跨 run 任务残留：本 Bundle 依赖「进程单会话」假设，同进程二次装配即假设被打破；" +
        "重装配前请先调用 TaskStore.reset(sessionId) 清理上一 run 的任务表。",
    );
  }
  ctx.tools.register(
    defineTool({
      name: "TaskCreate",
      description:
        "创建一条任务并登记进当前会话的任务清单。taskId 由系统按 1 基创建序分配，" +
        "创建后 status 为 pending。应先用 TaskCreate 声明全部任务，再以 TaskUpdate 推进状态。",
      parameters: {
        subject: { type: "string", required: true, description: "任务的一句话标题（祈使句）" },
        description: { type: "string", description: "任务要做什么的完整描述" },
        activeForm: { type: "string", description: "进行中时 spinner 展示的现在进行时短语" },
        metadata: { type: "object", additionalProperties: true, description: "任意附加元数据（键值对象）" },
      },
      output: {
        schema: {
          type: "object",
          additionalProperties: false,
          properties: {
            taskId: { type: "number" },
            subject: { type: "string" },
            status: { type: "string" },
          },
        },
        render: (_args: unknown, value: { taskId: number; subject: string; status: string }) => [
          { type: "text", text: `Task ${value.taskId} created successfully: ${value.subject} (status: ${value.status})` },
        ],
      },
      execute(args: TaskCreateInput, exec: { agent?: { id?: string } | null }) {
        const task = sharedStore.create(sessionIdOf(exec), args);
        return { taskId: task.taskId, subject: task.subject, status: task.status };
      },
    }),
  );

  ctx.tools.register(
    defineTool({
      name: "TaskUpdate",
      description:
        "更新一条任务：推进状态（pending→in_progress→completed）、改标题/描述/metadata。" +
        "完成瞬间应立即置 completed，不得攒批到收尾。",
      parameters: {
        taskId: { type: "number", required: true, description: "要更新的任务 id（1 基创建序）" },
        status: { type: "string", enum: [...TASK_STATUSES], description: "新状态" },
        subject: { type: "string", description: "新标题" },
        description: { type: "string", description: "新描述" },
        activeForm: { type: "string", description: "进行中时 spinner 展示的短语" },
        metadata: { type: "object", additionalProperties: true, description: "合并/替换的元数据对象" },
      },
      output: {
        schema: {
          type: "object",
          additionalProperties: false,
          properties: {
            taskId: { type: "number" },
            status: { type: "string" },
            subject: { type: "string" },
          },
        },
        render: (_args: unknown, value: { taskId: number; status: string; subject: string }) => [
          { type: "text", text: `Task ${value.taskId} updated: status=${value.status} subject=${value.subject}` },
        ],
      },
      execute(args: TaskUpdateInput, exec: { agent?: { id?: string } | null }) {
        const task = sharedStore.update(sessionIdOf(exec), args);
        return { taskId: task.taskId, status: task.status, subject: task.subject };
      },
    }),
  );

  ctx.tools.register(
    defineTool({
      name: "TaskGet",
      description: "按 taskId 取一条任务的完整字段。",
      parameters: {
        taskId: { type: "number", required: true, description: "任务 id（1 基创建序）" },
      },
      output: {
        schema: {
          type: "object",
          additionalProperties: true,
          properties: { taskId: { type: "number" } },
        },
        render: (_args: unknown, value: FenixTask) => [
          { type: "text", text: JSON.stringify(value) },
        ],
      },
      execute(args: { taskId: number }, exec: { agent?: { id?: string } | null }) {
        return sharedStore.get(sessionIdOf(exec), args.taskId);
      },
    }),
  );

  ctx.tools.register(
    defineTool({
      name: "TaskList",
      description: "列出当前会话的全部任务（按 taskId 升序）。",
      parameters: {},
      output: {
        schema: {
          type: "object",
          additionalProperties: false,
          properties: {
            count: { type: "number" },
            tasks: { type: "array", items: { type: "object", additionalProperties: true } },
          },
        },
        render: (_args: unknown, value: { tasks: FenixTask[] }) => [
          {
            type: "text",
            text:
              value.tasks.length === 0
                ? "[]（当前会话暂无任务）"
                : value.tasks
                    .map((t) => `${t.taskId}. [${t.status}] ${t.subject}${t.activeForm ? `（${t.activeForm}）` : ""}`)
                    .join("\n"),
          },
        ],
      },
      execute(_args: Record<string, never>, exec: { agent?: { id?: string } | null }) {
        const tasks = sharedStore.list(sessionIdOf(exec));
        return { count: tasks.length, tasks };
      },
    }),
  );
}
