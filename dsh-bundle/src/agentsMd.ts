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

import { readFileSync } from "node:fs";
import { join } from "node:path";

/** 注入标记与包装形态（与 dsh-agent-instructions 原生措辞一致，便于归因）。 */
export const AGENTS_MD_SECTION_NAME = "fenix:agents-md";

/**
 * 读取 root 下的 AGENTS.md 并返回分区文本；无文件或空内容返回 ""
 * （renderPrompt 丢弃空 section，故未挂载体文件的工作区零影响）。
 * AGENTS.md 允许是软链（约定载体：AGENTS.md -> CLAUDE.md，读时经软链取正文）。
 */
export function agentsMdSectionText(root: string, readFile: (p: string) => string = (p) => readFileSync(p, "utf-8")): string {
  let body: string;
  try {
    body = readFile(join(root, "AGENTS.md"));
  } catch {
    return "";
  }
  if (!body.trim()) return "";
  return `<system-reminder>\nInstructions from: AGENTS.md\n\n${body.replace(/\s+$/, "")}\n</system-reminder>`;
}

/** 本插件消费的 systemPrompt 服务面（结构最小集，避免直接依赖 cordis 类型）。 */
export interface AgentsMdContext {
  inject(deps: string[], fn: (scope: AgentsMdScope) => void): unknown;
}

interface AgentsMdScope {
  systemPrompt: {
    section(section: { name: string; order: number; text: () => string }): unknown;
    getSectionOrder(name: string): number;
  };
}

/**
 * 注册 AGENTS.md 分区：text 在每次 system prompt assembly 时求值，读当前
 * 工作目录（headless spawn 已保证 cwd = 工作区）的 AGENTS.md。order 取官方
 * FILE_REFERENCE 档位（工作区文件引用语义）。
 */
export function registerAgentsMdSection(ctx: AgentsMdContext): void {
  ctx.inject(["systemPrompt"], (scope) => {
    scope.systemPrompt.section({
      name: AGENTS_MD_SECTION_NAME,
      order: scope.systemPrompt.getSectionOrder("FILE_REFERENCE"),
      text: () => agentsMdSectionText(process.cwd()),
    });
  });
}
