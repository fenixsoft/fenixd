/**
 * agentsMd.ts — 工作区 AGENTS.md 经 system-prompt 分区装载（spec「AGENTS.md
 * 约定载体」：Bundle MUST 经 system-prompt 分区装载工作区 AGENTS.md 内容，
 * 使 ADR-269 门禁裁定在 dsh 通道与 claude 通道注入等价）。
 *
 * dsh 原生 dsh-agent-instructions 以 durable user 消息（<system-reminder>）注入
 * AGENTS.md，不进 LLM 请求的 system 字段；本分区把同一份内容送进 system prompt
 * （每次 assembly 现读现取，随工作区内容即时更新）。两通道并存：原生通道服务
 * dsh 生态约定，本分区服务 spec 的 system-prompt 契约。
 */

import { Buffer } from "node:buffer";
import { readFileSync } from "node:fs";
import { join } from "node:path";

/** 注入标记与包装形态（与 dsh-agent-instructions 原生措辞一致，便于归因）。 */
export const AGENTS_MD_SECTION_NAME = "fenix:agents-md";

/**
 * 注入长度上限（宽松档，UTF-8 字节）：AGENTS.md 超过该值时按字符截断并在尾部
 * 注明，防载体异常膨胀（如误粘贴大段日志）把每次模型请求的 system prompt 无界
 * 撑大。正常大小的 AGENTS.md 远低于此档位，行为不受影响。
 */
export const AGENTS_MD_MAX_BYTES = 128 * 1024;

/**
 * 二分求 UTF-8 字节数 ≤ maxBytes 的最长字符前缀（按 UTF-16 码元二分，若恰落在
 * 代理对中间则回退一个码元，不劈开字符）。
 */
function truncateUtf8ByBytes(text: string, maxBytes: number): string {
  let lo = 0;
  let hi = text.length;
  while (lo < hi) {
    const mid = (lo + hi + 1) >>> 1;
    if (Buffer.byteLength(text.slice(0, mid), "utf-8") <= maxBytes) lo = mid;
    else hi = mid - 1;
  }
  if (lo > 0 && lo < text.length && text.charCodeAt(lo - 1) >= 0xd800 && text.charCodeAt(lo - 1) < 0xdc00) lo -= 1;
  return text.slice(0, lo);
}

/**
 * 读取 root 下的 AGENTS.md 并返回分区文本；无文件或空内容返回 ""
 * （renderPrompt 丢弃空 section，故未挂载体文件的工作区零影响）。
 * AGENTS.md 允许是软链（约定载体：AGENTS.md -> CLAUDE.md，读时经软链取正文）。
 * 超过 AGENTS_MD_MAX_BYTES 时按字符截断并在尾部注明（防异常膨胀挤占上下文）。
 * 错误形态区分：ENOENT（载体未挂）维持静默零注入；其它异常（EACCES/EISDIR/
 * 软链循环等）在宿主 logger 可得时留一条可归因的 warning——通道缺省（裸 ctx/
 * 单测）时宁可舍弃诊断也不写 stderr（通道选择同 approval.ts warnUnreadable）。
 */
export function agentsMdSectionText(
  root: string,
  readFile: (p: string) => string = (p) => readFileSync(p, "utf-8"),
  logger?: { warn(...args: unknown[]): unknown },
): string {
  const path = join(root, "AGENTS.md");
  let body: string;
  try {
    body = readFile(path);
  } catch (err) {
    if ((err as { code?: unknown } | null | undefined)?.code !== "ENOENT") {
      logger?.warn(
        `[fenix-dsh-bundle] 读取 AGENTS.md 失败（${path}）：` +
          `${err instanceof Error ? err.message : String(err)}；本轮分区不注入。`,
      );
    }
    return "";
  }
  if (!body.trim()) return "";
  // 宽松长度上限：超限时按字符截断并加尾注，避免全量内容随每次请求挤占上下文且无告警。
  if (Buffer.byteLength(body, "utf-8") > AGENTS_MD_MAX_BYTES) {
    body = `${truncateUtf8ByBytes(body, AGENTS_MD_MAX_BYTES)}\n（AGENTS.md 超过上限 ${AGENTS_MD_MAX_BYTES} 字节，已截断）`;
  }
  // 正文中的闭合标记须转义（仅补一个反斜杠，语义仍可读），否则会提前终结
  // <system-reminder> 包裹，其后内容脱离注入语境。
  const safe = body.replace(/<\/system-reminder>/g, "<\\/system-reminder>").replace(/\s+$/, "");
  return `<system-reminder>\nInstructions from: AGENTS.md\n\n${safe}\n</system-reminder>`;
}

/** 本插件消费的 systemPrompt 服务面（结构最小集，避免直接依赖 cordis 类型）。 */
export interface AgentsMdContext {
  inject(deps: string[], fn: (scope: AgentsMdScope) => void): unknown;
  /** 宿主诊断通道（cordis LoggerService，形态同 approval.ts）：可选，缺省时静默。 */
  logger?: { warn(...args: unknown[]): unknown };
}

interface AgentsMdScope {
  systemPrompt: {
    section(section: { name: string; order: number; text: () => string }): unknown;
    getSectionOrder(name: string): number;
  };
}

/**
 * 注册 AGENTS.md 分区：text 在每次 system prompt assembly 时求值；root 缺省时
 * 读当前工作目录（隐式依赖 headless spawn 保证 cwd = 工作区），显式传 root 可
 * 在非 headless 或 chdir 后的装配场景固定工作区根。order 取官方 FILE_REFERENCE
 * 档位（工作区文件引用语义），宿主未提供该档位时 fail-fast。
 */
export function registerAgentsMdSection(ctx: AgentsMdContext, root?: string): void {
  ctx.inject(["systemPrompt"], (scope) => {
    const order = scope.systemPrompt.getSectionOrder("FILE_REFERENCE");
    if (!Number.isFinite(order)) {
      throw new Error(
        `systemPrompt.getSectionOrder("FILE_REFERENCE") 必须返回有限数值，收到 ${String(order ?? null)}（宿主缺该档位？）`,
      );
    }
    scope.systemPrompt.section({
      name: AGENTS_MD_SECTION_NAME,
      order,
      text: () => agentsMdSectionText(root ?? process.cwd(), undefined, ctx.logger),
    });
  });
}
