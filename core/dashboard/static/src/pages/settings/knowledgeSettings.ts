// 知识真相源开关的纯语义映射（add-knowledge-atlas + add-knowledge-atlas-maintenance）。
// 零依赖、无 React：与 qualityGates.ts 同型，供 node --test 原生 type-stripping
// 直测（tests/knowledgeSettings.test.mjs），面板组件只消费这里的映射结果。
// 2026-09-29 graphify 生成功能取消：graph_enabled 开关从设置页下线（后端键与
// 默认值保留、存量配置不动）。本模块映射仅覆盖 audit_enabled；knowledge.enabled
// 不经本模块，由 MiscSettingsPanel 经表单值（values.knowledge_enabled）直读直写
// （后端 _deep_merge_managed 对 knowledge 段逐键合并，enabled 不会被抹掉）。

/** 后端 knowledge.* 段中设置页消费的键（core/config.py get_knowledge_lane_config 的透传） */
export interface KnowledgeSection {
  audit_enabled?: boolean;
}

/** 面板开关状态：audit 车道布尔；缺省开启语义由 knowledgeSwitchesFromConfig 归一（非 false 一律视为开启） */
export interface KnowledgeSwitchState {
  auditEnabled: boolean;
}

/**
 * config.knowledge 段（可能缺失/后端旧版本未下发）→ 开关状态。
 * 与 core/config.py get_knowledge_config 同口径：缺省 True，非法值按缺省处理。
 */
export function knowledgeSwitchesFromConfig(section: unknown): KnowledgeSwitchState {
  const sec =
    typeof section === 'object' && section !== null
      ? (section as Record<string, unknown>)
      : {};
  return {
    auditEnabled: sec.audit_enabled !== false,
  };
}

/** 保存载荷：开关 → knowledge 段（局部段合并语义与 archive 段同型） */
export function knowledgeSectionFromSwitches(state: KnowledgeSwitchState): {
  knowledge: KnowledgeSection;
} {
  return {
    knowledge: {
      audit_enabled: state.auditEnabled,
    },
  };
}

// [fenix-ignore:fe0b741889ca] 条目所述「未使用的 key 参数」已在本分支早前批次（item 47d9e4700d3a，commit d78e0d15）移除，现行签名即无参函数，扩展位已在文档注释说明
/** 开关说明文案（单一来源，面板与测试共用）。当前仅 audit 车道，无参直取；
 * 引入第二个车道键时再参数化（code-review item 47d9e4700d3a）。 */
export function knowledgeSwitchDesc(): string {
  return '每日一次对 spec/knowledge/ 全量体检（悬空溯源、超行数、ADR 病灶、矛盾与重复），机械项自动修复提交，矛盾/重复转定向蒸馏重写；报告落 .fenix/knowledge_audit_report.md。';
}
