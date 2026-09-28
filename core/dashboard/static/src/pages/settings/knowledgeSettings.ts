// 知识真相源维护开关的纯语义映射（add-knowledge-atlas-maintenance 任务 1.2）。
// 零依赖、无 React：与 qualityGates.ts 同型，供 node --test 原生 type-stripping
// 直测（tests/knowledgeSettings.test.mjs），面板组件只消费这里的映射结果。

/** 后端 knowledge.* 段形状（core/config.py get_knowledge_lane_config 的透传） */
export interface KnowledgeSection {
  audit_enabled?: boolean;
  graph_enabled?: boolean;
}

/** 面板开关状态：两个布尔值；缺省开启语义由 knowledgeSwitchesFromConfig 归一（非 false 一律视为开启） */
export interface KnowledgeSwitchState {
  auditEnabled: boolean;
  graphEnabled: boolean;
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
    graphEnabled: sec.graph_enabled !== false,
  };
}

/** 保存载荷：两开关 → knowledge 段（局部段合并语义与 archive 段同型） */
export function knowledgeSectionFromSwitches(state: KnowledgeSwitchState): {
  knowledge: KnowledgeSection;
} {
  return {
    knowledge: {
      audit_enabled: state.auditEnabled,
      graph_enabled: state.graphEnabled,
    },
  };
}

/** 开关说明文案（单一来源，面板与测试共用） */
export function knowledgeSwitchDesc(key: 'audit' | 'graph'): string {
  if (key === 'audit') {
    return '每日一次对 spec/knowledge/ 全量体检（悬空溯源、超行数、ADR 病灶、矛盾与重复），机械项自动修复提交，矛盾/重复转定向蒸馏重写；报告落 .fenix/knowledge_audit_report.md。';
  }
  // 安装提示与 core/knowledge_audit.py run_graph 的 fail-open 日志为同一句的双副本，改包名/措辞须两处同步；graphifyy（双 y）非笔误，安装后的 CLI 探测名为 graphify。
  return '每日一次运行 Graphify 生成知识关系图（spec/knowledge/graph/），点亮「项目知识」页签的图渲染位。graphify 未安装时自动降级跳过（人工安装：uv tool install graphifyy）。';
}
