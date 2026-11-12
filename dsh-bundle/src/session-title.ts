/**
 * session-title.ts — dsh 会话确定性标题装配（spec: add-dsh-session-title-archive）。
 *
 * fenixd 以 dsh harness 派发的 headless agent 会话在 dsh web 列表显示「未命名」。
 * 本插件在会话启动期（session/created）以 spawn env 派生确定性标题，经
 * ctx.sessionTitle.rename() 落会话 header——写入走会话自身 header 写路径
 * （同进程），不依赖 dsh web 在线。
 *
 * 命名入口选型（design D1，按安装版 SDK typings 定案）：**rename()**——落
 * header 且 source=user 语义把标题 pin 住（dsh-session-title「user 源 pins the
 * session」）：后续首条 human message 不再调度 dsh-base 挂载的 session-title-llm
 * LLM provider，对 fenix 系统提示词 boilerplate 生成标题的额外 LLM 调用与延迟
 * 被天然省去。provider 接口（register + automatic cadence）为异步消息流设计，
 * 对「启动期一次性命名」不贴合，不采用。
 *
 * 落盘时机（2026-11-09 缺陷修正）：dsh announce() 同步派发 session/created 期间
 * 会话流只读（append 闸关闭），同步 rename 必抛「cannot append before
 * session/created completes」——故 rename 经 queueMicrotask 推迟到派发循环同步
 * 结束后执行；微任务仍先于 headless run() 续行与首条消息兜底，pin 语义不变。
 *
 * 派生规则（design D1）：`<PROJECT_ROOT basename> · <WORKTREE basename>`；
 * 任一 env 缺席回退另一 key 的 basename；两者全缺不命名（交由 dsh-session-title
 * 内置兜底），不抛错不阻塞会话创建。超 maxTitleBytes（120，UTF-8 字节）截断。
 *
 * 幂等：session/created 在 resume（种子重放）路径同样触发——已有标题且来源非
 * 内置兜底（source.kind !== "fallback"，即此前本插件 rename 落下的 user 源或
 * provider 源）时不覆盖。
 *
 * 失败安全：session/created 监听器（含 queueMicrotask 延迟任务）内的抛错一律
 * 吞掉走 logger.warn——同步抛错会否决会话创建并回滚（dsh-session「A
 * synchronous throw vetoes and rolls back」），绝不阻塞会话启动。
 */

import { basename } from "node:path";
import { truncateUtf8ByBytes } from "./utf8.ts";

/** fenixd spawn env 注入的两个路径键（守卫同源，见 core/agent_runner/harness）。 */
export const FENIX_RUN_PROJECT_ROOT_ENV = "FENIX_RUN_PROJECT_ROOT";
export const FENIX_RUN_WORKTREE_ENV = "FENIX_RUN_WORKTREE";

/** 标题分隔符（spec 格式 `<工程basename> · <worktreebasename>`）。 */
export const SESSION_TITLE_SEPARATOR = " · ";

/** 装配面 maxTitleBytes（cordis.patch.yml session-title 行同值，UTF-8 字节）。 */
export const DEFAULT_MAX_TITLE_BYTES = 120;

/** 本插件消费的 spawn env 形态（测试可注入子集）。 */
export type EnvLike = Record<string, string | undefined>;

/** dsh-session-title 快照的结构最小集（避免直接依赖 cordis/dsh 类型）。 */
export interface SessionTitleSnapshotLike {
  title: string;
  source: { kind: "fallback" | "provider" | "user" };
}

/** 本插件消费的 sessionTitle 服务面（get/rename 两入口）。 */
export interface SessionTitleServiceFace {
  /** 读会话最新标题快照；无标题（含首次创建）返回 undefined。 */
  get(session: unknown): SessionTitleSnapshotLike | undefined;
  /** 以 user 源接受显式标题（pin 住；对 headless 启动期命名即终态）。 */
  rename(session: unknown, title: string): unknown;
}

export interface SessionTitleScope {
  sessionTitle: SessionTitleServiceFace;
}

/** 本插件消费的 dsh 上下文面（结构最小集，形态同 agentsMd.ts）。 */
export interface SessionTitleContext {
  inject(deps: string[], fn: (scope: SessionTitleScope) => void): unknown;
  on(event: "session/created", listener: (session: unknown) => void): unknown;
  /** 宿主诊断通道（cordis LoggerService）：可选，缺省时静默。 */
  logger?: { warn(...args: unknown[]): unknown };
}

export interface RegisterSessionTitleOptions {
  /** spawn env（缺省 process.env；测试注入隔离子集）。 */
  env?: EnvLike;
  /** 截断上限（缺省 DEFAULT_MAX_TITLE_BYTES，与装配面 maxTitleBytes 同值）。 */
  maxTitleBytes?: number;
}

/**
 * 从 spawn env 派生确定性标题：两 basename 以「 · 」连接、按 UTF-8 字节截断至
 * maxTitleBytes；任一 env 缺席回退另一 key；两者全缺返回 null（不命名）。
 * 派生本身不抛错（env 值非字符串按缺席处理）。
 */
export function deriveSessionTitle(
  env: EnvLike = process.env,
  maxTitleBytes: number = DEFAULT_MAX_TITLE_BYTES,
): string | null {
  const parts: string[] = [];
  const project = env?.[FENIX_RUN_PROJECT_ROOT_ENV];
  const worktree = env?.[FENIX_RUN_WORKTREE_ENV];
  if (typeof project === "string" && project.length > 0) parts.push(basename(project));
  if (typeof worktree === "string" && worktree.length > 0) parts.push(basename(worktree));
  if (parts.length === 0) return null;
  return truncateUtf8ByBytes(parts.join(SESSION_TITLE_SEPARATOR), maxTitleBytes);
}

/** cordis 插件名（patch 行 id 同名，见 cordis.patch.yml）。 */
export const name = "fenix-session-title";

/**
 * 插件入口（patch 行 name: fenix-dsh-bundle/session-title 加载本模块时调用）。
 * 环境注入（options）仅供单测经 registerSessionTitle 直用，装配态恒读真实
 * process.env。
 */
export function apply(ctx: SessionTitleContext): void {
  registerSessionTitle(ctx);
}

/**
 * 注册确定性标题装配：inject(["sessionTitle"]) 后挂 session/created 监听器，
 * 每个新进入（或 resume 重放）的会话按幂等规则命名。所有异常吞掉并 WARN
 * ——监听器同步抛错会否决会话创建（dsh-session 语义），标题缺失绝不可阻塞
 * agent run 启动。
 */
export function registerSessionTitle(ctx: SessionTitleContext, options?: RegisterSessionTitleOptions): void {
  const env = options?.env ?? process.env;
  const maxTitleBytes = options?.maxTitleBytes ?? DEFAULT_MAX_TITLE_BYTES;
  ctx.inject(["sessionTitle"], (scope) => {
    ctx.on("session/created", (session: unknown) => {
      // dsh announce() 在同步派发 session/created 期间置 announcement=
      // "dispatching"，会话流只读（append 闸关闭）——此刻同步 rename 必抛
      // 「cannot append before session/created completes」（2026-11-09 端到端
      // 实证，曾致标题全程静默失效）。推迟到微任务：announce 循环同步走完、
      // 闸开后再落盘；微任务仍先于 headless run() 续行与首条消息兜底，user
      // pin 语义不受影响。
      queueMicrotask(() => {
        try {
          const title = deriveSessionTitle(env, maxTitleBytes);
          // env 全缺：不命名，标题交由 dsh-session-title 内置兜底（spec 场景）。
          if (!title) return;
          // 幂等：非内置兜底来源（本插件此前的 user 源 / provider 源）不覆盖。
          const existing = scope.sessionTitle.get(session);
          if (existing && existing.source?.kind !== "fallback") return;
          scope.sessionTitle.rename(session, title);
        } catch (err) {
          // 延迟任务内抛错同样不可外泄（否决/污染 run 启动）——吞掉并 WARN。
          ctx.logger?.warn(
            `[fenix-dsh-bundle] 会话确定性标题写入失败（已忽略，不影响会话创建）：` +
              `${err instanceof Error ? err.message : String(err)}`,
          );
        }
      });
    });
  });
}
