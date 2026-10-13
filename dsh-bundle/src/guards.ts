/**
 * guards.ts — 三守卫插件（挂 dsh 工具执行管道 tools/pre-execute waterfall）。
 *
 * 语义对齐 .fenix/hooks/ 下三个 PreToolUse 脚本（判定逻辑逐条复刻）：
 * 1. 主树写守卫（block-main-tree-write.py）：消费 FENIX_RUN_PROJECT_ROOT /
 *    FENIX_RUN_WORKTREE 两个 env，拦截 write/edit 对主树的写入；无 env 直通。
 * 2. 读图拦截（block-image-read.py）：read 工具目标为图片扩展名时阻断（模型
 *    不支持图像输入，图片内容块进对话即整会话 400）。
 * 3. 场景批处理（planner-scenario-batching.py）：write 场景文件 test_scenarios.json
 *    首次落盘必须是骨架（任一场景带 steps/assertions 即拦）。
 *
 * 守卫先于审批生效：tools/pre-execute waterfall 在工具分发与审批裁决之前运行，
 * 本插件以 prepend 注册抢占；deny 直接物化为 isError 工具结果回给模型，审批
 * 全放行（approval never + danger-full-access）不影响拦截路径。
 *
 * 纯判定函数与 dsh 装配分离：单测零 dsh 依赖。
 */

import { existsSync } from "node:fs";

// ── 纯逻辑：三守卫判定 ─────────────────────────────────────────────────────

export interface GuardEnv {
  /** FENIX_RUN_WORKTREE —— 本次 run 的 worktree 绝对路径；空 = 非 fenixd 派发。 */
  worktree?: string;
  /** FENIX_RUN_PROJECT_ROOT —— 项目根（主树）绝对路径。 */
  projectRoot?: string;
}

export interface GuardDecision {
  blocked: boolean;
  reason?: string;
}

/** claude block-image-read.py 的 IMAGE_EXT。 */
export const IMAGE_EXTENSIONS: readonly string[] = [".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp", ".avif"];

/** claude block-main-tree-write.py 的写类工具（Write/Edit/NotebookEdit）→ dsh 对应 write/edit。 */
export const MAIN_TREE_WRITE_TOOLS: readonly string[] = ["write", "edit"];

function within(child: string, parent: string): boolean {
  return child === parent || child.startsWith(parent + "/");
}

function normalize(p: string): string {
  // 逐段消解 . / ..（等价 python os.path.normpath 的语义面）
  const parts: string[] = [];
  for (const seg of p.split("/")) {
    if (seg === "" || seg === ".") continue;
    if (seg === "..") {
      parts.pop();
      continue;
    }
    parts.push(seg);
  }
  return "/" + parts.join("/");
}

/**
 * 主树写守卫：对 write/edit 的 file_path 判定（对齐 block-main-tree-write.py）。
 * - 两个 env 任一为空 → 直通（非 fenixd 派发场景，不误伤）；
 * - 相对路径 → 相对 CWD（spawn 已保证 = worktree）解析，放行；
 * - 落在 worktree 内 → 放行；
 * - 落在主树 .fenix/verify-progress/（--add-dir 授权的进度目录）→ 放行；
 * - 其余主树路径 → 拦截并给纠偏处方（「主树只读」语义）；
 * - 主树之外（/tmp 等）→ 不归本防线管，放行。
 */
export function mainTreeWriteDecision(filePath: string, env: GuardEnv): GuardDecision {
  const worktree = (env.worktree ?? "").trim();
  const projectRoot = (env.projectRoot ?? "").trim();
  if (!worktree || !projectRoot) return { blocked: false };

  if (!filePath) return { blocked: false };
  // 相对路径 → 相对 CWD 解析，天然安全
  if (!filePath.startsWith("/")) return { blocked: false };

  const norm = normalize(filePath);
  if (within(norm, normalize(worktree))) return { blocked: false };
  if (within(norm, normalize(`${projectRoot}/.fenix/verify-progress`))) return { blocked: false };
  if (within(norm, normalize(projectRoot))) {
    const rel = norm.slice(normalize(projectRoot).length + 1);
    return {
      blocked: true,
      reason:
        `写主树被拦截：本 run 的专属工作区是 worktree（当前工作目录），主树只读。` +
        `请把文件写到 worktree 内的相对路径 \`${rel}\`（即当前目录下的 ${rel}）。` +
        `上下文中出现的主树绝对路径（如 skill 基路径）只是部署位置参考，不是交付落点。`,
    };
  }
  return { blocked: false };
}

/**
 * 读图拦截：read 工具目标为图片扩展名时阻断（对齐 block-image-read.py 的
 * Read matcher 语义：按扩展名判定，大小写不敏感）。
 */
export function imageReadDecision(filePath: string): GuardDecision {
  if (!filePath) return { blocked: false };
  const dot = filePath.lastIndexOf(".");
  const ext = dot === -1 ? "" : filePath.slice(dot).toLowerCase();
  if (!IMAGE_EXTENSIONS.includes(ext)) return { blocked: false };
  return {
    blocked: true,
    reason: "当前模型不支持图像输入，已阻止读取图片文件（截图请作为证据文件保存，勿查看）",
  };
}

/**
 * 场景批处理：write 工具写 test_scenarios.json 时校验「首次落盘必须是骨架」
 * （对齐 planner-scenario-batching.py）。
 * - 文件已存在（骨架已落）→ 放行（后续全量重写属分批补全）；
 * - 内容不可解析（非 JSON/非场景数组）→ 放行（fail-open，引擎验收门兜底）；
 * - 任一场景带非空 steps/assertions → 拦截（首次全量落盘违反分批节奏）。
 */
export function scenarioBatchingDecision(
  filePath: string,
  content: string,
  fileExists: boolean,
): GuardDecision {
  if (!filePath.endsWith("test_scenarios.json")) return { blocked: false };
  if (fileExists) return { blocked: false };

  let data: unknown;
  try {
    data = JSON.parse(content);
  } catch {
    return { blocked: false };
  }
  if (typeof data === "object" && data !== null && !Array.isArray(data)) {
    data = (data as { scenarios?: unknown }).scenarios;
  }
  if (!Array.isArray(data)) return { blocked: false };

  const hasFleshed = data.some(
    (sc) =>
      typeof sc === "object" &&
      sc !== null &&
      (Array.isArray((sc as { steps?: unknown }).steps) && (sc as { steps: unknown[] }).steps.length > 0 ||
       Array.isArray((sc as { assertions?: unknown }).assertions) && (sc as { assertions: unknown[] }).assertions.length > 0),
  );
  if (!hasFleshed) return { blocked: false };

  return {
    blocked: true,
    reason:
      "分批落盘规则：test_scenarios.json 首次落盘必须是骨架" +
      "（全部场景的 id/kind/description，steps/assertions 置空数组），" +
      "随后再分批重写补全 steps/assertions。请先重写为骨架，" +
      "框架据文件增长向用户展示出题进度。",
  };
}

/** 守卫分发入口：对一次工具调用按工具名路由到三个守卫（任一命中即拦）。 */
export function evaluatePreToolCall(
  toolName: string,
  args: Record<string, unknown>,
  env: GuardEnv,
  fileExists: (path: string) => boolean = existsSync,
): GuardDecision {
  const filePath = typeof args.file_path === "string" ? args.file_path : "";

  if (MAIN_TREE_WRITE_TOOLS.includes(toolName)) {
    const hit = mainTreeWriteDecision(filePath, env);
    if (hit.blocked) return hit;
  }
  if (toolName === "read") {
    const hit = imageReadDecision(filePath);
    if (hit.blocked) return hit;
  }
  if (toolName === "write") {
    const content = typeof args.content === "string" ? args.content : "";
    const hit = scenarioBatchingDecision(filePath, content, fileExists(filePath));
    if (hit.blocked) return hit;
  }
  return { blocked: false };
}

// ── dsh 装配：tools/pre-execute 守卫 ───────────────────────────────────────

export interface PreToolExec {
  name: string;
  arguments: Record<string, unknown>;
}

export type PreToolDecision = { kind: "allow" } | { kind: "deny"; reason: string; info?: { name: string; code: string } };

/**
 * 注册三守卫：tools/pre-execute waterfall，prepend 抢在其它监听者（含
 * hooks 桥与审批链）之前。env 在每次调用时读取（与 claude hook 的 spawn 注入
 * 语义一致），deny 物化为模型可见的错误结果，工具体不执行。
 */
export function registerGuards(ctx: {
  on(event: "tools/pre-execute", listener: (exec: PreToolExec, next: () => Promise<PreToolDecision>) => Promise<PreToolDecision>, options?: { prepend?: boolean }): unknown;
}): void {
  ctx.on(
    "tools/pre-execute",
    async (exec, next) => {
      const env: GuardEnv = {
        worktree: process.env.FENIX_RUN_WORKTREE,
        projectRoot: process.env.FENIX_RUN_PROJECT_ROOT,
      };
      const decision = evaluatePreToolCall(exec.name, exec.arguments ?? {}, env);
      if (decision.blocked) {
        return {
          kind: "deny",
          reason: decision.reason ?? "fenix guard denied",
          info: { name: exec.name, code: "FENIX_GUARD_DENIED" },
        };
      }
      return next();
    },
    { prepend: true },
  );
}
