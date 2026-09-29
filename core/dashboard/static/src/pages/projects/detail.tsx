import { PageContainer } from '@ant-design/pro-components';
import { Alert, App, Badge, Button, Card, Checkbox, Collapse, Descriptions, Dropdown, Empty, Image, Input, Select, Space, Spin, Tabs, Tag, Timeline, Tooltip, Typography } from 'antd';
import { CloseOutlined, DownOutlined, ExclamationCircleFilled, FullscreenOutlined, InfoCircleFilled } from '@ant-design/icons';
import { Fragment, useCallback, useEffect, useRef, useState } from 'react';
import { history, useParams, useLocation } from '@umijs/max';
import dayjs from 'dayjs';
import Markdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { clearSpecError, getAlerts, getConfig, getHookAudit, getSpecDetail, getSpecs, markAlertHandled, saveConfig, STREAM_URL, statusMeta } from '@/services/dashboard';
import type { AlertItem, ConfigData, HookAuditRecord, HookConfig, HooksConfig, SpecDetail, SpecSummary } from '@/services/dashboard';
import HookManager from '@/components/HookManager';
import { markdownComponents } from './components/SpecDocModal';
import SpecDocModal from './components/SpecDocModal';
import type { DocType } from './components/SpecDocModal';
import RunRecordModal from './components/RunRecordModal';
import RunCancelModal from './components/RunCancelModal';
// 「任务进度」同款进度条控件 2026-09-23 抽出共享（CodeFixProgressCard 复用），原内联定义已删
import ProgressBarTile from './components/ProgressBarTile';
import { ClaudeOutputPane } from '@/components/claude-msg';
import { OutlinedTag } from '@/components/StatusTag';
import { useIsMobile } from '@/hooks/useIsMobile';
// 告警裁决交互共享 hook + 执行按钮（与 overview AlertBanner 同源，
// code-review item f86171cc149d）
import { AlertAdjudicationExec, useAlertAdjudication } from '@/hooks/useAlertAdjudication';
// 告警严重度标签/配色走告警展示单源（code-review item a6db9e33af09：本地副本
// 缺 warning 键与单源漂移，warning 告警在本页误渲染灰色标签）
import { SEV_COLOR, SEV_LABEL } from '@/components/alert-shared';
// 时长格式化与列表页「耗时」列共用单源（code-review item f8307715a795：
// 两页逐行重复实现抽公共模块，本页不再在组件体内每渲染重建）
import { fmtDuration } from '@/utils/duration';
import { fmtEvidence } from '@/utils/evidence';
import { fetchProposalWhy } from '@/utils/proposalWhy';
import { fmtInputTokens, fmtMillions } from '@/utils/tokens';
// add-quality-gates-visibility：六态渲染语义映射抽到纯函数模块（node:test 可
// 加载 .ts），本文件只做 JSX 套用
import {
  gateChecked,
  gateDetailText,
  gateSuffix,
  gateTextColor,
  normalizeGateItems,
  ocrJoinNote,
  shouldRenderGatesCard,
} from './qualityGates';

// 与 v2 static/app.js renderVerdict 保持同一判定逻辑：
// parse_verdict 的 status 串自带 emoji 前缀（如 "❌ 未通过（Bug Found）"），先剥离再判定，
// 避免与 AntD Tag 的配色语义重复；产品Bug>0 → error，环境问题>0 → warning，其余 → success。
const VERDICT_EMOJI_RE = /^[\s\u{1F300}-\u{1FAFF}\u{2600}-\u{27BF}\u{2190}-\u{21FF}\u{2B00}-\u{2BFF}\u{FE0F}\u{2705}\u{274C}\u{26A0}]+/u;

function verdictTone(v: NonNullable<SpecDetail['verdict']>): { color: 'success' | 'warning' | 'error'; label: string } {
  const s = v.summary || {};
  const num = (x: string | null | undefined) => parseInt(x || '', 10) || 0;
  const status = (v.status || '').replace(VERDICT_EMOJI_RE, '');
  if (num(s.product_bugs) > 0 || /未通过|Bug Found|失败/.test(status)) {
    return { color: 'error', label: '❌ 未通过' };
  }
  if (num(s.env_issues) > 0 || /环境|无法验证|不可达|unreachable/i.test(status)) {
    return { color: 'warning', label: '⚠️ 有环境差异' };
  }
  return { color: 'success', label: '✅ 通过' };
}

const VERDICT_COUNTS: Array<[keyof NonNullable<SpecDetail['verdict']>['summary'] & string, string]> = [
  ['passed', '通过'],
  ['failed', '失败'],
  ['errors', '错误'],
  ['product_bugs', '产品Bug'],
  ['env_issues', '环境问题'],
];

// 头部状态 Tag 的 tone→antd 预设色映射（code-review item 7d6e6be9876c：原先只
// 区分 good/critical，implementing(warning)/implemented·reviewing(aqua) 等一律
// 误染蓝色 processing）。键覆盖 services/dashboard STATUS_META 全部 6 种 tone，
// 色相与列表页 TONE_DOT / OutlinedTag 同语义（warning 橙、aqua 青、info 蓝）。
const TONE_TAG_COLOR: Record<string, string> = {
  muted: 'default',
  info: 'processing',
  warning: 'warning',
  critical: 'error',
  good: 'success',
  aqua: 'cyan',
};

// 断言类型中文标签（对齐 core/verify_engine/scenarios.py 三套词表；未收录值原样显示）
const ASSERTION_LABELS: Record<string, string> = {
  // web（18 种）
  element_visible: '元素可见',
  element_count: '元素数量',
  element_not_exist: '元素不存在',
  element_focused: '元素聚焦',
  element_enabled: '元素可用',
  no_click_interception: '点击不被拦截',
  no_overlap: '无元素重叠',
  in_viewport: '在视口内',
  z_index_order: '层叠顺序正确',
  text_match: '文本匹配',
  text_contains: '包含文本',
  attribute_match: '属性匹配',
  no_console_error: '无控制台报错',
  no_network_error: '无网络错误',
  no_auth_error: '无认证错误',
  dom_structure: 'DOM 结构正确',
  no_overflow: '无溢出',
  alignment: '对齐正常',
  // cli
  exit_code: '退出码',
  file_exists: '文件存在',
  output_match: '输出匹配',
  file_content: '文件内容',
  json_output: 'JSON 输出',
  dir_contains: '目录包含',
  // api
  status_code: '状态码',
  json_path: 'JSON 路径',
  response_header: '响应头',
  body_contains: '响应体包含',
  json_schema: 'JSON Schema',
  latency_under: '延迟上限',
  sse_event_matches: 'SSE 事件匹配',
  sse_event_count: 'SSE 事件数',
};

// 断言类型值 → 中文标签；bug.assertion 可能是「type + 附加说明」自由文本，命中前缀时仅替换前缀
function assertionLabel(type?: string): string {
  if (!type) return '?';
  if (ASSERTION_LABELS[type]) return ASSERTION_LABELS[type];
  const hit = Object.keys(ASSERTION_LABELS).find((k) => type.startsWith(k));
  return hit ? `${ASSERTION_LABELS[hit]} ${type.slice(hit.length)}` : type;
}

type AssertionResultItem = NonNullable<
  NonNullable<SpecDetail['scenarios']>[number]['assertion_results']
>[number];

// 断言行明细摘要：优先设计 label / 结果 message；通过断言常缺省这两者，
// 按引擎输出字段（core/verify_engine/assertions.py / api_assertions.py /
// cli_assertions.py 口径）分类型组装可读文本（字段驱动，不按 kind 分支）
function assertionDetail(a: AssertionResultItem): string {
  if (a.label) return a.label;
  if (a.message) return a.message;
  switch (a.type) {
    // ── web ──
    case 'element_count':
      return `期望 ${a.expected ?? 1} 个，实际 ${a.actual ?? '?'} 个`;
    case 'element_not_exist':
      return a.actual_count != null ? `页面残留 ${a.actual_count} 个` : '';
    case 'text_match': {
      const modeWord = a.mode === 'regex' ? '匹配正则' : a.mode === 'contains' ? '包含' : '等于';
      const actual = a.actual != null && a.actual !== '' ? `，实际「${a.actual}」` : '';
      return `${modeWord}「${a.expected ?? ''}」${actual}`;
    }
    case 'text_contains':
      return a.text ? `包含「${a.text}」` : '';
    case 'attribute_match': {
      const actual = a.actual != null ? `，实际「${a.actual}」` : '';
      return `${a.attribute || '属性'} ${a.expected != null ? `期望「${a.expected}」` : ''}${actual}`;
    }
    case 'no_console_error': {
      const filtered = (a.filtered_network || []).length;
      return `错误 ${(a.errors || []).length} 条${filtered ? `（已过滤网络类 ${filtered} 条）` : ''}`;
    }
    case 'no_network_error':
      return `错误请求 ${(a.errors || []).length} 条`;
    case 'no_auth_error': {
      const m = a.matched || [];
      return m.length ? `命中关键词: ${m.join('、')}` : '关键词 0 命中';
    }
    case 'dom_structure':
      return `${a.parent || '?'} ${a.relation === 'direct-child' ? '直接包含' : '包含'} ${a.child || '?'}`;
    case 'z_index_order':
      return `${a.selector || '?'} 的 z-index ${a.z_index_self ?? '?'} ${a.operator || '>'} ${a.z_index_compare ?? '?'}（对比 ${a.compare_selector || '?'}）`;
    // ── cli ──
    case 'exit_code':
      return `期望退出码 ${a.expected ?? 0}，实际 ${a.actual ?? '?'}`;
    case 'file_exists':
      return `${a.path || '?'} ${a.exists ? '存在' : '不存在'}`;
    case 'dir_contains':
      return `匹配 ${a.glob || '?'} 共 ${a.count ?? '?'} 个`;
    case 'output_match': {
      const streamWord = a.stream === 'stderr' ? 'stderr' : a.stream === 'stdout' ? 'stdout' : '输出';
      const neg = a.negate ? '（取反）' : '';
      const snippet = a.actual_snippet ? `，片段「${a.actual_snippet}」` : '';
      return `${streamWord} 匹配「${a.expected ?? ''}」${neg}${snippet}`;
    }
    case 'file_content':
      return `文件内容匹配「${a.expected ?? ''}」${a.negate ? '（取反）' : ''}`;
    case 'json_output': {
      const actual = a.actual !== undefined ? `，实际「${JSON.stringify(a.actual)}」` : '';
      return `JSON ${a.path || '?'} 期望「${JSON.stringify(a.expected)}」${actual}`;
    }
    // ── api ──
    case 'status_code':
      return `期望状态码 ${a.expected ?? '?'}，实际 ${a.actual ?? '?'}`;
    case 'json_path': {
      const actual = a.actual !== undefined ? `，实际「${JSON.stringify(a.actual)}」` : '';
      return `路径 ${a.path || '?'} 期望「${JSON.stringify(a.expected)}」${actual}`;
    }
    case 'response_header':
      return `头 ${a.header || '?'} 期望「${a.expected ?? ''}」，实际「${a.actual ?? ''}」`;
    case 'body_contains':
      return a.actual_snippet ? `包含「${a.expected ?? ''}」，命中「${a.actual_snippet}」` : `包含「${a.expected ?? ''}」`;
    case 'json_schema':
      return 'JSON Schema 校验';
    case 'latency_under':
      return `期望延迟 < ${a.expected ?? '?'}ms，实际 ${a.actual ?? '?'}ms`;
    case 'sse_event_matches':
      return `事件匹配「${a.expected ?? ''}」（命中 ${a.hit_count ?? 0} 条）`;
    case 'sse_event_count':
      return `期望事件 ≥ ${a.min ?? 1}，实际 ${a.actual ?? 0}`;
    // ── 字段驱动兜底（cli/api 无 selector；按实际存在字段摘要）──
    default: {
      if (a.selector) return a.selector;
      const bits: string[] = [];
      if (a.path) bits.push(`路径 ${a.path}`);
      if (a.header) bits.push(`头 ${a.header}`);
      if (a.expected !== undefined) bits.push(`期望「${JSON.stringify(a.expected)}」`);
      if (a.actual !== undefined && a.actual !== null && a.actual !== '')
        bits.push(`实际「${JSON.stringify(a.actual)}」`);
      return bits.join('，');
    }
  }
}

// 场景 kind 徽章（web/cli/api 视觉区分；multi-kind-report-compat）
const KIND_META: Record<string, { color: string; label: string }> = {
  web: { color: 'blue', label: 'web' },
  cli: { color: 'purple', label: 'cli' },
  api: { color: 'geekblue', label: 'api' },
};

function KindBadge({ kind }: { kind?: string }) {
  const meta = KIND_META[kind || 'web'] || { color: 'default', label: kind || 'web' };
  return <Tag color={meta.color} style={{ marginInlineEnd: 0 }}>{meta.label}</Tag>;
}

function VerdictPanel({ verdict }: { verdict: NonNullable<SpecDetail['verdict']> }) {
  const tone = verdictTone(verdict);
  const s = verdict.summary || {};
  const counts = VERDICT_COUNTS.filter(([k]) => s[k] != null).map(([k, label]) => `${label} ${s[k]}`);
  const status = (verdict.status || '').replace(VERDICT_EMOJI_RE, '');
  return (
    <div>
      <Space size={8} style={{ marginBottom: 8 }} wrap>
        <Tag color={tone.color}>{tone.label}</Tag>
        {status && <Typography.Text strong>{status}</Typography.Text>}
        {verdict.status_detail && <Typography.Text type="secondary">{verdict.status_detail}</Typography.Text>}
      </Space>
      {counts.length > 0 && (
        <div style={{ marginBottom: 8 }}>
          {counts.map((c) => (
            <Tag key={c}>{c}</Tag>
          ))}
        </div>
      )}
      {verdict.conclusion && (
        <div style={{ marginBottom: 0 }}>
          <Markdown remarkPlugins={[remarkGfm]} components={markdownComponents}>
            {verdict.conclusion}
          </Markdown>
        </div>
      )}
    </div>
  );
}

// Agent 中文名（与设置页 Agent 模型角色中文名对应；implementer 沿用「开发」）。
// agent_type 为泛型 'agent' 或缺失时，按 run_id 前缀（RUN_ID_PREFIX_LABEL）判别。
const AGENT_LABEL: Record<string, string> = {
  implementer: '开发 Agent',
  'impl-ocr': '代码审查 Agent',
  planner: '规划 Agent',
  'planner-plan': '生成场景 Agent',
  'planner-judge': '判定结果 Agent',
  'spec-review': '需求评审 Agent',
  'dispute-judge': '争议裁决 Agent',
  repair: '修复 Agent',
  verifier: '验证 Agent',
  tester: '测试 Agent',
  administrator: '运维 Agent',
};

// run_id 前缀兜底。⚠️ 必须按完整前缀匹配（不能用 split('-')[0]）：spec-review- /
// dispute-judge- / planner-plan- 等是多段前缀，首段 'spec'/'dispute'/'planner'
// 无法唯一归属；长的排前面，首个命中即止（impl-ocr- 必须排在 impl- 之前，
// 否则被 impl- 先命中、车道节点标签退回「开发 Agent」）。
const RUN_ID_PREFIX_LABEL: [prefix: string, label: string][] = [
  ['planner-judge-', '判定结果 Agent'],
  ['planner-plan-', '生成场景 Agent'],
  ['dispute-judge-', '争议裁决 Agent'],
  ['spec-review-', '需求评审 Agent'],
  ['impl-ocr-', '代码审查 Agent'],
  ['impl-', '开发 Agent'],
  ['repair-', '修复 Agent'],
  ['admin-', '运维 Agent'],
  ['test-', '测试 Agent'],
  ['verify-', '验证 Agent'],
];

function agentLabel(item: { agent_type?: string; run_id?: string }): string {
  const t = (item.agent_type || '').toLowerCase();
  // 泛型 'agent' 视同缺失（后端未识别出类型），继续走 run_id 前缀判别
  if (t && t !== 'agent' && AGENT_LABEL[t]) return AGENT_LABEL[t];
  const rid = (item.run_id || '').toLowerCase();
  for (const [prefix, label] of RUN_ID_PREFIX_LABEL) {
    if (rid.startsWith(prefix)) return label;
  }
  return AGENT_LABEL[t] || '未知 Agent';
}

/** run 终态原因行的呈现（add-timeline-gate-failure-display D5）：语气 + 前缀。
 *
 * 门禁拒绝（gate-blocked）与 error 同为失败（danger 红，前缀区分「门禁拒绝：」与
 * 「失败原因：」——一眼分清「产物门拒绝」与「运行崩了」）；superseded 是被弃置的
 * 中间产物（secondary + 「原地重试：」，失败归因由紧随其后的 gate-blocked 节点承担）；
 * 其余中止类（interrupted/cancelled）橙色 warning。未知状态落 warning/中止原因，
 * 与改动前行为一致。映射单一真源，渲染处 MUST NOT 再内联重复该条件链。 */
function reasonTone(
  st: string,
): { tone: 'danger' | 'warning' | 'secondary'; prefix: string } {
  if (st === 'gate-blocked') return { tone: 'danger', prefix: '门禁拒绝：' };
  if (st === 'error') return { tone: 'danger', prefix: '失败原因：' };
  if (st === 'superseded') return { tone: 'secondary', prefix: '原地重试：' };
  return { tone: 'warning', prefix: '中止原因：' };
}

// 回退原因含「verification report」时渲染为链接（点击打开验证报告弹窗）
const VERIFICATION_LINK_RE = /^(.*?)verification report(.*)$/i;

// 状态转移节点的输出信息用默认黑色正文（此前 secondary 灰色不易读），链接分支保留可点
function ReasonText({ reason, onOpenReport }: { reason: string; onOpenReport: () => void }) {
  const m = reason.match(VERIFICATION_LINK_RE);
  if (!m) return <Typography.Text>{reason}</Typography.Text>;
  return (
    <Typography.Text>
      {m[1]}
      <a onClick={onOpenReport}>verification report</a>
      {m[2]}
    </Typography.Text>
  );
}

// add-model-billing-cost-display（design D5）：金额格式化——统一 $x.xx；
// < $0.01 显示三位小数（$0.001），避免小额全零。仅展示口径，不做入账四舍五入。
function formatUsd(v: number): string {
  if (v > 0 && v < 0.01) return `$${v.toFixed(3)}`;
  return `$${v.toFixed(2)}`;
}

// fix-verify-verdict-visibility：被分类过滤（非 product-bug）失败场景的分类中文标签
// （对齐 verdict-evidence-taxonomy 分类：test-defect/flaky/env）
const FILTERED_FAILURE_LABELS: Record<string, string> = {
  'test-defect': '测试缺陷',
  flaky: '偶发',
  env: '环境问题',
};
const FILTERED_FAILURE_COLORS: Record<string, string> = {
  'test-defect': 'orange',
  flaky: 'purple',
  env: 'blue',
};

// 被裁决过滤的失败/错误场景摘要区块：消除「运行时间轴有失败 + 失败截图有图 +
// Bug 列表为空」的三页签矛盾——展示裁决结论（分类、理由、证据）。纯展示区块，
// 无交互（截图缩略图复用 Image 预览放大，与 Bug 卡片同款）。
function FilteredFailuresBlock({
  filtered,
  name,
  spec,
  collapsed,
}: {
  filtered: NonNullable<SpecDetail['filtered_failures']>;
  name: string;
  spec: string;
  collapsed: boolean;
}) {
  const body = (
    <div>
      {filtered.map((f, idx) => (
        <div
          key={idx}
          data-testid="filtered-failure-item"
          style={{
            padding: '8px 12px',
            marginBottom: 8,
            background: '#fafafa',
            border: '1px solid #f0f0f0',
            borderRadius: 6,
          }}
        >
          <Space size={8} wrap style={{ marginBottom: 4 }}>
            <Typography.Text strong>{f.scenario_id}</Typography.Text>
            <Tag color={FILTERED_FAILURE_COLORS[f.classification || ''] || 'default'} style={{ marginInlineEnd: 0 }}>
              {FILTERED_FAILURE_LABELS[f.classification || ''] || f.classification || '未分类'}
            </Tag>
            <Tag color={f.status === 'error' ? 'red' : 'default'} style={{ marginInlineEnd: 0 }}>
              {f.status === 'error' ? '错误' : '失败'}
            </Tag>
            {f.status_corrected && (
              <Tag color="green" style={{ marginInlineEnd: 0 }}>
                状态已修正
              </Tag>
            )}
          </Space>
          {f.evidence_summary ? (
            <Typography.Text type="secondary" style={{ display: 'block', fontSize: 13 }}>
              {f.evidence_summary}
            </Typography.Text>
          ) : null}
          {f.screenshots && f.screenshots.length > 0 && (
            <div style={{ marginTop: 8, display: 'flex', flexWrap: 'wrap', gap: 8 }}>
              {f.screenshots.map((file, sIdx) => (
                <Image
                  key={sIdx}
                  src={`/screenshots/${encodeURIComponent(name)}/${encodeURIComponent(spec)}/${encodeURIComponent(file)}`}
                  alt={`被过滤场景 ${f.scenario_id} 截图 ${sIdx + 1}`}
                  width={150}
                  height={100}
                  style={{
                    objectFit: 'cover',
                    border: '1px solid #d9d9d9',
                    borderRadius: 4,
                  }}
                  preview={{ mask: '点击查看' }}
                />
              ))}
            </div>
          )}
        </div>
      ))}
    </div>
  );

  if (collapsed) {
    // bugs 非空时摘要折叠为次级区块，避免双列表混淆
    return (
      <Collapse
        ghost
        size="small"
        data-testid="filtered-failures-collapse"
        style={{ marginTop: 16 }}
        items={[
          {
            key: 'filtered-failures',
            label: (
              <Typography.Text type="secondary" style={{ fontSize: 13 }}>
                被裁决过滤的失败场景（{filtered.length}）
              </Typography.Text>
            ),
            children: body,
          },
        ]}
      />
    );
  }

  return (
    <div data-testid="filtered-failures-block" style={{ marginTop: 16 }}>
      <Typography.Text strong style={{ display: 'block', marginBottom: 4 }}>
        被裁决过滤的失败场景（{filtered.length}）
      </Typography.Text>
      <Typography.Text type="secondary" style={{ display: 'block', marginBottom: 8, fontSize: 12 }}>
        以下失败/错误场景被裁决分类为测试缺陷/环境问题/偶发（非产品 Bug），故未进入 Bug 列表
      </Typography.Text>
      {body}
    </div>
  );
}

// ── spec 详情页 Hook 页签（add-spec-hooks）─────────────────────────
// 「生效中的 Hooks」= 全局 + 本 spec 合并（来源标注）；「本 spec 的 Hooks」
// = spec 级 CRUD（写入 hooks.specs.<spec>）；「最近执行」= 该 spec 审计。
function SpecHooksSection({ name, spec, readOnly = false }: { name: string; spec: string; readOnly?: boolean }) {
  const { message } = App.useApp();
  const [config, setConfig] = useState<ConfigData | null>(null);
  const [audit, setAudit] = useState<HookAuditRecord[]>([]);
  const [auditLoading, setAuditLoading] = useState(false);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    let cancelled = false;
    const load = async () => {
      setAuditLoading(true);
      try {
        const [cfg, aud] = await Promise.all([
          getConfig(name),
          getHookAudit(name, spec, 20),
        ]);
        if (!cancelled) {
          setConfig(cfg);
          setAudit(aud.audit ?? []);
        }
      } catch (e) {
        console.error('Failed to load spec hooks:', e);
        if (!cancelled) message.error(`加载 Hook 配置失败：${e instanceof Error ? e.message : e}`);
      } finally {
        if (!cancelled) setAuditLoading(false);
      }
    };
    load();
    return () => { cancelled = true; };
  }, [name, spec, message]);

  const hooksCfg: HooksConfig = config?.hooks ?? {};
  const globalHooks: HookConfig[] = Array.isArray(hooksCfg.global) ? hooksCfg.global : [];
  const specHooks: HookConfig[] = Array.isArray(hooksCfg.specs?.[spec]) ? hooksCfg.specs![spec] : [];

  // 生效合并视图（含来源标注）
  const effective = [
    ...globalHooks.map((hook) => ({ hook, source: 'global' as const })),
    ...specHooks.map((hook) => ({ hook, source: 'spec' as const })),
  ];

  const handleSave = async (nextSpecHooks: HookConfig[]) => {
    // config 为 null（首次加载中或加载失败）时阻断保存并提示重试/刷新
    // （code-review item a6c65167219a）
    if (!config) {
      message.error('Hook 配置尚未加载，无法保存，请稍后重试或刷新页面');
      return;
    }
    setSaving(true);
    try {
      // 基底用保存前重拉的最新配置，不用组件内 config 快照：后端对 hooks 段是
      // 「patch 存在即整体替换」语义，快照可能已过期（页面挂载/上次保存后，
      // 设置页或另一标签更新过项目级 hooks.global），以快照合并会静默回退他处
      // 的修改（code-review item bf045d7ed0b9）
      const latest = await getConfig(name);
      const latestHooks: HooksConfig = latest?.hooks ?? {};
      const cfg = await saveConfig(name, {
        hooks: {
          ...latestHooks,
          specs: { ...(latestHooks.specs || {}), [spec]: nextSpecHooks },
        },
      });
      setConfig(cfg);
      message.success('保存成功');
    } catch (e) {
      message.error(`保存失败：${e instanceof Error ? e.message : e}`);
    } finally {
      setSaving(false);
    }
  };

  return (
    <div style={{ padding: '20px 0' }}>
      <HookManager
        hooks={specHooks}
        onSave={handleSave}
        saving={saving}
        effective={effective}
        audit={audit}
        auditLoading={auditLoading}
        readOnly={readOnly}
      />
    </div>
  );
}

export default function SpecDetailPage() {
  const { name = '', spec = '' } = useParams<{ name: string; spec: string }>();
  const location = useLocation();
  const isMobile = useIsMobile();
  const [detail, setDetail] = useState<SpecDetail | null>(null);
  const [specAlerts, setSpecAlerts] = useState<AlertItem[]>([]);
  const [docModalOpen, setDocModalOpen] = useState(false);
  // SPEC 下拉快速切换：项目下所有 SPEC 列表（复用列表页 getSpecs，失败静默为空）
  const [specList, setSpecList] = useState<SpecSummary[]>([]);
  const [switchOpen, setSwitchOpen] = useState(false);
  const [recordRunId, setRecordRunId] = useState<string | null>(null);
  // add-run-cancel（4.2）：终止运行确认弹窗的目标 run_id + 受理后行内反馈
  const [cancelRunId, setCancelRunId] = useState<string | null>(null);
  // 已受理取消的行内反馈（run_id → 文案）；弹窗关闭后仍保留直至再次刷新
  const [cancelNotices, setCancelNotices] = useState<Record<string, string>>({});
  // 文档弹窗打开时定位的页签（时间轴报告链接 → 验证报告；项目信息「文档」→ 需求背景）
  const [docInitial, setDocInitial] = useState<DocType>('proposal');
  // 告警内容默认折叠（只显示标题），展开后的告警 id 集合
  const [expandedAlerts, setExpandedAlerts] = useState<Set<string>>(new Set());
  // add-human-adjudication-choices 5.2/5.3：告警内嵌选择题交互状态——
  // 选项值/note 按告警 id 分键；resolving 防重；执行结果/失败信息按告警留显。
  // 交互实体经共享 hook（与 overview AlertBanner 同源，code-review item
  // f86171cc149d），刷新回调在告警渲染处经执行按钮 onResolved 注入
  const adj = useAlertAdjudication();
  const {
    alertChoiceSels, setAlertChoiceSels, alertNotes, setAlertNotes,
    resolvingAlerts, alertResolveMsgs,
  } = adj;
  // 场景结果状态过滤（'' = 全部）
  const [scenarioFilter, setScenarioFilter] = useState<'pass' | 'warning' | 'fail' | 'error' | ''>('');
  // 任务背景描述 = proposal 文档 ## Why 段（spec 列表悬停同名内容），懒加载
  const [proposalWhy, setProposalWhy] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  // SPEC 下拉快速切换不重挂载本组件：事件回调（handleClearInfo / 告警裁决
  // onResolved）闭包里的 name/spec 是调用时刻的值，迟到响应会把旧 SPEC 详情
  // 整表写入已切换页面。effect 内同步的 ref 提供「当前路由值」，响应返回时
  // 比对不一致即整表丢弃（与主 effect 的 cancelled 守卫同一约定，
  // code-review item cae55cf05562）。同步放 effect（post-commit）而非渲染期
  // ——渲染必须保持纯净，与 SessionPanel activeRef / list.tsx specMapRef
  // 同一纪律（code-review item 35e26d047a50）
  const nameSpecRef = useRef({ name, spec });
  useEffect(() => {
    nameSpecRef.current = { name, spec };
  }, [name, spec]);

  const toggleAlert = (id: string) => {
    setExpandedAlerts((prev) => {
      const next = new Set(prev);
      if (next.has(id)) {
        next.delete(id);
      } else {
        next.add(id);
      }
      return next;
    });
  };

  useEffect(() => {
    if (!name || !spec) return;

    // SPEC 快速切换（renderSpecSwitch 内 history.push）不重挂载本组件，
    // scenarioFilter 等本地过滤态会跨 SPEC 残留：上一 SPEC 选中的「失败」
    // 过滤原样作用于新 SPEC 场景列表（列表页过滤粘性在 URL query、此处为
    // 隐式残留）。随 [name, spec] 变更归零（code-review item 3c54c109b5f6）；
    // expandedAlerts 按告警 id、cancelNotices 按 run_id 索引，失效键多为
    // 无害空读，不重置
    setScenarioFilter('');

    // SSE 热更新：后台刷新必须静默原位进行——不能走 setLoading（整页被
    // Spin 替换再重建，交互状态全丢、agent 运行期间页面持续闪烁）。
    // applyDetail 以 JSON 内容判等，数据无变化时跳过 setState 避免无谓重渲染。
    const lastDetailRef = { current: '' };
    const applyDetail = (data: SpecDetail) => {
      const serialized = JSON.stringify(data);
      if (serialized === lastDetailRef.current) return;
      lastDetailRef.current = serialized;
      setDetail(data);
    };

    // SPEC 下拉快速切换时本 effect 重挂载，cancelled 丢弃被取代作用的迟到
    // 响应，防止旧 SPEC 的详情经 getSpecDetail 写入新页面状态（同文件
    // fetchProposalWhy/getSpecs effect 同模式）
    let cancelled = false;

    // 详情轮询/确认心跳（SSE 触发的 throttledLoad → 本函数）统一经
    // getSpecDetail → request() 封装发出——本文件不直连 fetch。request() 的
    // ETag 条件请求通道（add-dashboard-paging-and-etag 3.1）对详情端点透明
    // 生效：数据源未变时服务端回 304，request() 原样返回缓存 JSON，
    // applyDetail 的内容判等照常短路 setState——心跳空转零 body 传输、零重渲染。
    const load = async (initial = false) => {
      try {
        if (initial) setLoading(true);
        const data = await getSpecDetail(name, spec);
        if (cancelled) return;
        applyDetail(data);
        // 拉取成功即复位错误，不限首载：首载失败进入整页错误 Alert 后 SSE
        // 心跳触发的后台 load 仍在跑，若只在首载清错页面将永远停在错误页、
        // 无法随数据恢复自愈（code-review item f11b7ed7d05a）
        setError('');
      } catch (e) {
        // 后台刷新失败静默保留旧视图，只有首次加载才呈现错误页
        if (initial && !cancelled) setError(e instanceof Error ? e.message : String(e));
      } finally {
        // 迟到响应不提前熄灭新 SPEC 首载的 Spin
        if (initial && !cancelled) setLoading(false);
      }
    };

    void load(true);

    // watcher 的 detail/state 事件自带完整详情可直接采用；
    // run_meta/refresh 只带轻量通知，节流后重拉 REST（与 list.tsx 同策略）。
    // 节流无尾沿补偿：500ms 窗口内到达的最后一条轻量通知被丢弃不补拉，但
    // refresh 为全局心跳兜底信号、事件流持续到来，最终一致性可恢复，仅存在
    // 一段滞后窗口。属信息级且自愈，不设尾沿定时器（code-review item
    // 6058215a190e）
    const REFRESH_THROTTLE_MS = 500;
    let lastRefresh = 0;
    const throttledLoad = () => {
      const now = Date.now();
      if (now - lastRefresh < REFRESH_THROTTLE_MS) return;
      lastRefresh = now;
      void load();
    };
    // SSE 端点走 services/dashboard 的 STREAM_URL 单源，不写字面量
    // （code-review item 2099376c1f44，同 list.tsx / QualityTab）
    const es = new EventSource(STREAM_URL);
    es.onmessage = (ev: MessageEvent) => {
      let msg: {
        type?: string; project?: string; spec?: string;
        data?: SpecDetail; details?: Record<string, SpecDetail>;
      } = {};
      try {
        msg = JSON.parse(ev.data);
      } catch {
        return;
      }
      if (msg.type === 'detail' && msg.project === name && msg.spec === spec && msg.data) {
        applyDetail(msg.data);
        return;
      }
      if (msg.type === 'state' && msg.project === name) {
        const d = msg.details?.[spec];
        if (d) {
          applyDetail(d);
          return;
        }
        // 本 SPEC 条目未变但项目有变化（如日志新增/其他 SPEC 变更）：
        // 时间轴取自日志，节流重拉兜底（与 list.tsx 同策略）
        throttledLoad();
      }
      // run_meta 负载带 project（watcher 仅在状态转换时广播）：只响应本项目，
      // 多项目宿主上其他项目的 run 转换不再触发本页重拉（code-review item
      // 844dd6f5108b）；refresh 是全局心跳/兜底信号，负载无 project，不过滤
      if ((msg.type === 'run_meta' && msg.project === name) || msg.type === 'refresh') {
        throttledLoad();
      }
    };
    return () => {
      cancelled = true;
      es.close();
    };
  }, [name, spec]);

  const { message } = App.useApp();

  // 本 SPEC 的人工升级告警（未处理），拉取失败静默不影响主视图
  const loadSpecAlerts = useCallback(() => {
    getAlerts()
      .then((d) => {
        // 迟到响应守卫：等待期间已切换 SPEC → 丢弃旧告警列表，不串页（与
        // handleClearInfo / 告警裁决 onResolved 对 setDetail 的守卫同型，
        // code-review item b11dfba1da23）
        if (nameSpecRef.current.name !== name || nameSpecRef.current.spec !== spec) return;
        setSpecAlerts((d.alerts || []).filter((a) => a.project === name && a.spec === spec));
      })
      .catch(() => {});
  }, [name, spec]);

  useEffect(() => {
    loadSpecAlerts();
  }, [loadSpecAlerts]);

  // 任务背景描述懒加载（proposal ## Why），spec 切换时重取
  useEffect(() => {
    let cancelled = false;
    if (!name || !spec) return;
    fetchProposalWhy(name, spec).then((text) => {
      if (!cancelled) setProposalWhy(text);
    });
    return () => {
      cancelled = true;
    };
  }, [name, spec]);

  // 下拉快速切换数据源：项目变化时拉一次 SPEC 列表（复用列表页 getSpecs）。
  // 下拉是低频辅助信息，不为其建立 SSE 通道；失败时静默保持为空（箭头不展示），不影响详情页主体。
  useEffect(() => {
    let cancelled = false;
    if (!name) return;
    getSpecs(name)
      .then((d) => {
        if (!cancelled) setSpecList(d.specs || []);
      })
      .catch(() => {
        if (!cancelled) setSpecList([]);
      });
    return () => {
      cancelled = true;
    };
  }, [name]);

  const statusInfo = statusMeta(detail?.status || '');

  // 下拉快速切换项：项目下除当前 SPEC 外的其他未归档 SPEC（只有当前一个时不展示箭头）。
  // archived 缺省（旧后端）按未归档处理，与列表页 !!s.archived 过滤语义一致。
  const otherSpecs = specList.filter((s) => s.name !== spec && !s.archived);

  // 下拉快速切换面板（表格形式）：SPEC 名称（过长截断 + 悬停提示） + 状态标签（statusMeta 同列表页语义）。
  // 面板宽度上限 360px 且移动端不超出视口（max-width: calc(100vw - 32px)），内容区限高滚动。
  const renderSpecSwitch = () => (
    <div
      className="spec-quick-switch-panel"
      style={{
        width: 360,
        maxWidth: 'calc(100vw - 32px)',
        background: '#fff',
        border: '1px solid #f0f0f0',
        borderRadius: 8,
        boxShadow: '0 6px 16px 0 rgba(0, 0, 0, 0.08), 0 3px 6px -4px rgba(0, 0, 0, 0.12)',
        overflow: 'hidden',
      }}
    >
      <div style={{ maxHeight: '60vh', overflow: 'auto', padding: 4 }}>
        {otherSpecs.map((s) => {
          const m = statusMeta(s.status || '');
          return (
            <div
              key={s.name}
              className="spec-quick-switch-row"
              onClick={() => {
                setSwitchOpen(false);
                history.push(`/projects/${name}/${s.name}`);
              }}
              style={{
                display: 'flex',
                alignItems: 'center',
                gap: 12,
                padding: '8px 10px',
                borderRadius: 6,
                cursor: 'pointer',
                color: 'inherit',
              }}
            >
              <Typography.Text ellipsis={{ tooltip: s.name }} style={{ flex: 1, minWidth: 0, fontSize: 13 }}>
                {s.name}
              </Typography.Text>
              {/* 执行模式列：与标题旁模式标记同语义（fast-track 单 run 全包，存量无 mode 字段按完整模式） */}
              <Tag
                color={s.mode === 'fast-track' ? 'cyan' : 'default'}
                style={{ marginInlineEnd: 0, fontSize: 12, lineHeight: '18px', paddingInline: 5, paddingBlock: 0 }}
              >
                {s.mode === 'fast-track' ? '快速模式' : '完整模式'}
              </Tag>
              <OutlinedTag tone={m.tone}>{m.label}</OutlinedTag>
            </div>
          );
        })}
      </div>
    </div>
  );

  // 位置由顶栏全局面包屑指示；这里关闭 PageContainer 默认左上面包屑
  const headerCfg = {
    title: (
      <Space size={8} align="baseline" wrap>
        <span>{spec}</span>
        {/* add-fast-track-mode（task 7.2）：执行模式标记——fast-track 单 run 全包，
            其余（含存量无 mode 字段的 spec）统一展示「完整模式」，可辨识两条路径 */}
        <Tag color={detail?.mode === 'fast-track' ? 'cyan' : 'default'} style={{ marginInlineEnd: 0 }}>
          {detail?.mode === 'fast-track' ? '快速模式' : '完整模式'}
        </Tag>
        {detail?.status && (
          <Tag color={TONE_TAG_COLOR[statusInfo.tone] || 'default'}>{statusInfo.label}</Tag>
        )}
        {otherSpecs.length > 0 && (
          <Dropdown trigger={['click']} placement="bottomLeft" popupRender={renderSpecSwitch} open={switchOpen} onOpenChange={setSwitchOpen}>
            <Button
              type="text"
              size="small"
              icon={<DownOutlined />}
              title="切换 SPEC"
              aria-label="切换 SPEC"
              style={{ paddingInline: 4, minWidth: 24, minHeight: 24 }}
            />
          </Dropdown>
        )}
      </Space>
    ),
    onBack: () => {
      // 返回列表优先历史回退：列表页过滤态承载在 URL query 上
      // （add-spec-list-filter-stickiness），push 裸 URL 会新开无参历史条目，
      // 列表重挂载时过滤归零；仅直达打开（无应用内历史）时兜底 push。
      // 币值守卫（code-review item 1c4f3c30258d）：window.history.length 是
      // 会话级计数——外链/重定向链进入时 length>1 但上一条目在应用外，
      // history.back() 会退出 dashboard 或落在无关页面；react-router v6 的
      // location.key !== 'default' 才表示本条目由应用路由推入（存在应用内
      // 上一条目），刷新后 key 复位为 default，此时兜底 push 不会退出应用。
      if (location.key !== 'default') history.back();
      else history.push(`/projects/${name}`);
    },
  };

  // 参数缺失防御（code-review item 5aa57e968aad）：路由匹配成功但 name/spec
  // 为空时主加载 effect 直接 return、loading 初值 true 无人复位，页面会永久
  // 停在整页 Spin。守卫须放在全部 hook 之后（条件 return 前置会破坏 hook 顺
  // 序，同 ClaudeOutputPane），以参数缺失提示兜底，不让 loading 悬挂。
  if (!name || !spec) {
    return (
      <PageContainer breadcrumbRender={false} header={headerCfg}>
        <Alert type="warning" showIcon message="参数缺失" description="URL 缺少项目名或 SPEC 名，请从项目列表重新进入。" />
      </PageContainer>
    );
  }

  if (loading) {
    return (
      <PageContainer breadcrumbRender={false} header={headerCfg}>
        <div style={{ textAlign: 'center', padding: '50px 0' }}>
          <Spin size="large" />
        </div>
      </PageContainer>
    );
  }

  if (error) {
    return (
      <PageContainer breadcrumbRender={false} header={headerCfg}>
        <Alert type="error" showIcon message="加载失败" description={error} />
      </PageContainer>
    );
  }

  // 格式化函数见 @/utils/tokens（fmtMillions / fmtInputTokens）

  // 告警标记人工已处理（同 overview 横幅）；成功后刷新本 SPEC 告警
  const handleMarkAlertHandled = async (a: AlertItem) => {
    try {
      await markAlertHandled(a.project, a.id);
      message.success('已标记处理');
    } catch (err) {
      message.error(`标记失败：${err instanceof Error ? err.message : String(err)}`);
    }
    loadSpecAlerts();
  };

  // 清除 spec 信息（同列表页清除 error）；成功后重拉详情使信息条消失。
  // 清除与刷新分开捕获：「清除失败」只在 clearSpecError 本身失败时出现，清除已
  // 成功后刷新失败不得误报为清除失败、诱导重复提交（code-review item 898eb44cb047）
  const handleClearInfo = async () => {
    try {
      await clearSpecError(name, spec);
    } catch (err) {
      message.error(`清除失败：${err instanceof Error ? err.message : String(err)}`);
      return;
    }
    message.success('已清除');
    try {
      const fresh = await getSpecDetail(name, spec);
      // 迟到响应守卫：等待期间已切换到另一 SPEC → 丢弃旧详情，不串页
      if (nameSpecRef.current.name !== name || nameSpecRef.current.spec !== spec) return;
      setDetail(fresh);
    } catch (err) {
      message.warning(`已清除，但刷新详情失败：${err instanceof Error ? err.message : String(err)}`);
    }
  };

  const openDocModal = (doc: DocType) => {
    setDocInitial(doc);
    setDocModalOpen(true);
  };

  // 计算任务进度
  const taskGroups = detail?.tasks || [];
  const allTasks = taskGroups.flatMap((g) => g.tasks || []);
  const completedTasks = allTasks.filter((t) => t.done).length;
  const totalTasks = allTasks.length;

  // 渲染时间轴内容 — 复用运维记录页的时间轴控件（Timeline + 盒式卡片子项：头部时间+标签行，正文着色边框）
  const renderTimeline = () => {
    const timeline = detail?.timeline || [];
    if (!timeline.length) {
      return <Empty description="暂无运行时间轴" />;
    }

    const cardBox = (urgent: boolean): React.CSSProperties => ({
      padding: isMobile ? 8 : 12,
      borderRadius: 8,
      border: urgent ? '1px solid #ff4d4f' : '1px solid #f0f0f0',
      background: urgent ? '#fff2f0' : '#fafafa',
    });
    const headRow: React.CSSProperties = {
      display: 'flex',
      alignItems: 'center',
      gap: 8,
      marginBottom: 8,
      flexWrap: 'wrap',
    };
    const fmtTime = (v: string) => {
      const d = dayjs(v);
      return d.isValid() ? d.format('YYYY-MM-DD HH:mm:ss') : v;
    };

    return (
      <Timeline
        items={timeline.map((item) => {
          if (item.kind === 'state') {
            // 状态节点：头部保留「状态转移」标签，from → to 中文标签（同 SPEC 列表 statusMeta）换行显示在内容区；
            // 折叠节点携带 chain（完整状态序列）时全链展开渲染，中间状态不省略
            // （fast-track 连跳 implemented→testing→verified→done→pushed 只显示一头一尾会掩盖真实途经状态）
            // 回退方向单源后端 backward 字段（缺失时回退旧判定兼容存量/归档数据）：
            // 带 reason 的前向节点（如恢复直写行的精确 error）不再挂「↩ 状态回退」徽标
            const isRollback = item.backward === true || (item.backward === undefined && !!item.reason);
            const chainStatuses: string[] = (item.chain && item.chain.length > 1)
              ? item.chain
              : [item.from || '', item.to || ''];
            const statusSeq = chainStatuses.map((s, i) => (
              <Fragment key={`${s}-${i}`}>
                {i > 0 && <Typography.Text type="secondary">→</Typography.Text>}
                <OutlinedTag tone={statusMeta(s || '').tone}>{s ? statusMeta(s).label : '?'}</OutlinedTag>
              </Fragment>
            ));
            // testing 停等注记（add-timeline-ocr-lane-visibility 任务 2.3）：最新
            // 「→ testing」节点在 ocr 门 running 时显示（后端仅对该节点下发 ocr_gate，
            // 其余状态 ocrJoinNote 返回 null 零渲染）；detail 为门禁合成同源辅助文案
            const ocrNote = ocrJoinNote(item.ocr_gate?.status);
            return {
              color: isRollback ? '#ec835a' : 'gray',
              children: (
                <div style={cardBox(false)}>
                  <div style={headRow}>
                    <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                      {fmtTime(item.time)}
                    </Typography.Text>
                    <Tag>状态转移</Tag>
                    {isRollback && <Tag color="orange">↩ 状态回退</Tag>}
                  </div>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
                    {statusSeq}
                  </div>
                  {ocrNote && (
                    <div style={{ whiteSpace: 'pre-wrap', marginTop: 10 }}>
                      <Typography.Text type="warning" style={{ fontSize: 13 }}>
                        {ocrNote}
                        {item.ocr_gate?.detail ? `（${item.ocr_gate.detail}）` : ''}
                      </Typography.Text>
                    </div>
                  )}
                  {isRollback && (
                    <div style={{ whiteSpace: 'pre-wrap', marginTop: 10 }}>
                      <ReasonText reason={item.reason || '状态回退'} onOpenReport={() => openDocModal('verification')} />
                    </div>
                  )}
                </div>
              ),
            };
          }

          if (item.kind === 'admin') {
            // 运维事件节点（add-timeline-admin-events）：紧凑卡片——标题行
            // （时间 + 运维处置/升级告警 Tag + severity 着色 + 状态 Tag）+ 摘要
            // （description，与其他节点同口径：默认 14px、pre-wrap 可换行）。
            // 不渲染 summary markdown 全文（完整四段总结仍由运维记录页承载）。
            const isEscalation = item.record_kind === 'escalation';
            const sev = String(item.severity || '');
            // severity 着色复用运维记录页语义：critical 红 / major 橙 / 其余灰
            const sevColor = sev === 'critical' ? 'red' : sev === 'major' ? 'orange' : 'default';
            // 状态 Tag：disposition 终态（resolved 等）绿「已解决」、pending 蓝「处置中」；
            // escalation handled 绿「已处理」、未处理橙
            const dispResult = String(item.result || '');
            const dispDone = dispResult !== 'pending';
            const statusTag = isEscalation
              ? (item.handled
                ? <Tag color="green" style={{ marginInlineEnd: 0 }}>已处理</Tag>
                : <Tag color="orange" style={{ marginInlineEnd: 0 }}>未处理</Tag>)
              : (dispDone
                ? <Tag color="green" style={{ marginInlineEnd: 0 }}>已解决</Tag>
                : <Tag color="blue" style={{ marginInlineEnd: 0 }}>处置中</Tag>);
            return {
              color: 'blue',
              children: (
                <div style={cardBox(false)}>
                  <div style={headRow}>
                    <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                      {fmtTime(item.time)}
                    </Typography.Text>
                    <Tag>{isEscalation ? '升级告警' : '运维处置'}</Tag>
                    <Tag color={sevColor} style={{ marginInlineEnd: 0 }}>
                      {SEV_LABEL[sev] || sev || '未知'}
                    </Tag>
                    {statusTag}
                  </div>
                  <Typography.Text style={{ whiteSpace: 'pre-wrap', display: 'block' }}>
                    {item.description || ''}
                  </Typography.Text>
                </div>
              ),
            };
          }

          // 验证执行节点（verify_engine 确定性执行，非 agent run）：原时间轴
          // 不可见导致 testing→verified 连跳被误读为「跳过验证」
          // （fix-provider-transient-backoff 事故）。节点不着红：有失败也可能
          // 被 judge 判定通过（裁决权在 judge），失败数只在内容行文字着色。
          // 橙=有失败/警告/env 受阻，绿=全过。
          if (item.kind === 'verify') {
            const vFailed = (item.failed || 0) + (item.errors || 0);
            const hasIssue = vFailed > 0 || !!item.env_error;
            const vWarn = (item.warnings || 0) > 0;
            const vDur = item.duration_seconds != null ? fmtDuration(item.duration_seconds) : '';
            // 统计明细（N 场景/通过/失败/错误/警告）放内容区正文行：数字着色、
            // 0 值项省略，分隔符对齐列表页 VerifyCell 悬浮汇总口径；耗时放标题行
            const statParts: React.ReactNode[] = [];
            if (item.total != null) statParts.push(<span key="total">{item.total} 场景</span>);
            if (item.passed != null) {
              statParts.push(<span key="passed" style={{ color: '#52c41a' }}>通过 {item.passed}</span>);
            }
            if (!!item.failed) {
              statParts.push(<span key="failed" style={{ color: '#ff4d4f' }}>失败 {item.failed}</span>);
            }
            if (!!item.errors) {
              statParts.push(<span key="errors" style={{ color: '#ff4d4f' }}>错误 {item.errors}</span>);
            }
            if (!!item.warnings) {
              statParts.push(<span key="warnings" style={{ color: '#faad14' }}>警告 {item.warnings}</span>);
            }
            return {
              color: hasIssue || vWarn ? 'orange' : 'green',
              children: (
                <div style={cardBox(false)}>
                  <div style={headRow}>
                    <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                      {fmtTime(item.time)}
                    </Typography.Text>
                    <Typography.Text style={{ fontSize: 12 }}>验证执行</Typography.Text>
                    {vDur && (
                      <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                        耗时 {vDur}
                      </Typography.Text>
                    )}
                  </div>
                  {statParts.length > 0 && (
                    <div style={{ fontSize: 14 }}>
                      {statParts.map((node, i) => (
                        <Fragment key={i}>
                          {i > 0 && <span style={{ color: 'rgba(0, 0, 0, 0.45)' }}> · </span>}
                          {node}
                        </Fragment>
                      ))}
                    </div>
                  )}
                  {item.env_error && (
                    <div style={{ whiteSpace: 'pre-wrap', marginTop: 4 }}>
                      <Typography.Text type="warning" style={{ fontSize: 12 }}>
                        环境受阻：{item.env_error}
                      </Typography.Text>
                    </div>
                  )}
                </div>
              ),
            };
          }

          // 未知 kind 守卫（add-timeline-admin-events）：state/admin/run 之外不渲染
          // 卡片体（脏数据降级只留时间轴圆点），不报错崩渲染
          if (item.kind !== 'run') {
            return { color: 'gray' };
          }

          // 运行节点
          const st = item.status || '';
          const isErr = st === 'error';
          // 门禁拒绝（add-timeline-gate-failure-display D5）：产物硬门失败终止本次
          // attempt 的独立终态，语义等同 error（失败）——不并入失败分支会落入下方
          // 绿色兜底，重现「门禁连续拒绝显示成一串顺利收工绿点」的误导
          const isGateBlocked = st === 'gate-blocked';
          // 原地重试弃置件（superseded）：本身不是失败终态（圆点/Tag 仍绿——失败归因由
          // 紧随其后的 gate-blocked 节点承担，避免同一次失败出现两个红节点），但带原因
          // 时由 reasonTone 渲染中性色「原地重试：」行，MUST NOT 呈现为无原因绿点
          const isFailed = isErr || isGateBlocked;
          const reasonView = reasonTone(st);
          // interrupted/cancelled：已终结但非崩溃（daemon 停机/启动清扫补写/
          // 人工取消），橙色区别于 error 红；不处理会落入 else 误显成功绿
          const isAborted = st === 'interrupted' || st === 'cancelled';
          const isRunning = st === 'running' || st === 'empty';
          // stale（fix-retry-orphan-active-runs）：弃置/断尾——原地重试换文件
          // 弃置或进程被杀无终态，读侧 mtime 兜底判定；灰色区别于 running 蓝 /
          // error 红，归入非在飞非错误分支。未知 status 行为不变（绿兜底）
          const dotColor = isFailed ? 'red' : isAborted ? 'orange' : st === 'stale' ? 'gray' : isRunning ? 'blue' : 'green';
          const dur = item.duration_seconds != null ? fmtDuration(item.duration_seconds) : '';
          const isFix = item.spec && String(item.spec).startsWith('fix-');

          return {
            color: dotColor,
            children: (
              <div style={cardBox(isFailed)}>
                <div style={headRow}>
                  <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                    {fmtTime(item.time)}
                  </Typography.Text>
                  <Typography.Text style={{ fontSize: 12 }}>{agentLabel(item)}</Typography.Text>
                  {item.llm && <Tag color="blue" style={{ marginInlineEnd: 0 }}>{item.llm}</Tag>}
                  {/* add-model-billing-cost-display：可计价 run 成本标注（样式同 llm Tag；
                      不可计价节点不下发 cost_usd，不渲染，避免历史节点噪音） */}
                  {item.cost_usd != null && (
                    <Tag color="green" style={{ marginInlineEnd: 0 }}>{formatUsd(item.cost_usd)}</Tag>
                  )}
                  {!!item.retry_count && item.retry_count > 0 && (
                    <Tag color="orange" style={{ marginInlineEnd: 0 }}>
                      重试 {item.retry_count}{item.retry_max ? `/${item.retry_max}` : ''}
                    </Tag>
                  )}
                  {/* 配色单一来源复用 dotColor（含 isAborted 橙色分支），与圆点语义一致 */}
                  <Tag color={dotColor} style={{ marginInlineEnd: 0 }}>
                    {isGateBlocked ? '门禁拒绝' : st || '未知状态'}
                  </Tag>
                  {isFix && <Tag color="orange">🔧 {item.spec}</Tag>}
                  {dur && (
                    <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                      耗时 {dur}
                    </Typography.Text>
                  )}
                  {/* add-run-cancel（4.2）：活跃 run 提供「终止」操作，确认弹窗确认后才发起 */}
                  {isRunning && item.run_id && (
                    <Button
                      size="small"
                      danger
                      type="text"
                      onClick={() => setCancelRunId(item.run_id!)}
                    >
                      终止
                    </Button>
                  )}
                  {item.run_id && cancelNotices[item.run_id] && (
                    <Typography.Text type="success" style={{ fontSize: 12 }}>
                      {cancelNotices[item.run_id]}
                    </Typography.Text>
                  )}
                </div>
                {/* 终态原因（run 产物 error/interrupted/cancelled/superseded/
                    gate-blocked 事件的人类可读原因）：不展开运行记录即可见死因；
                    运行中/成功 run 下发空串不渲染。
                    error 与门禁拒绝（gate-blocked）红色（同节点圆点语义）；门禁拒绝
                    前缀与失败原因区分，便于一眼分清「产物门拒绝」与「运行崩了」；
                    superseded 为被弃置的中间产物，中性色 + 「原地重试：」前缀；
                    interrupted/cancelled 已终结非崩溃用橙色 */}
                {!!item.reason && (
                  <div style={{ marginBottom: 8 }}>
                    <Typography.Text type={reasonView.tone} style={{ fontSize: 13 }}>
                      {reasonView.prefix}
                      {item.reason}
                    </Typography.Text>
                  </div>
                )}
                {/* ocr 车道审查对象摘要（add-timeline-ocr-lane-visibility 任务 2.3）：
                    转录 start 事件 message（分支与 from..to 审查区间）；缺失不渲染 */}
                {item.lane_summary && (
                  <div style={{ marginBottom: 8 }}>
                    <Typography.Text type="secondary" style={{ fontSize: 13 }}>
                      {item.lane_summary}
                    </Typography.Text>
                  </div>
                )}
                {/* ClaudeCode 最后一条总结（result 字段，markdown）：不展开运行记录即可掌握结论 */}
                {item.summary && (
                  <div
                    style={{
                      marginBottom: 8,
                      padding: '8px 12px',
                      border: '1px solid #f0f0f0',
                      borderRadius: 8,
                      background: '#fff',
                      fontSize: 13,
                    }}
                  >
                    <Markdown remarkPlugins={[remarkGfm]} components={markdownComponents}>
                      {item.summary}
                    </Markdown>
                  </div>
                )}
                {item.run_id && (
                  <Collapse
                    ghost
                    size="small"
                    items={[
                      {
                        key: 'run-stream',
                        label: (
                          <span style={{ display: 'inline-flex', alignItems: 'center', gap: 4 }}>
                            查看运行记录
                            <Button
                              type="text"
                              size="small"
                              title="最大化查看"
                              icon={<FullscreenOutlined />}
                              onClick={(e) => {
                                e.stopPropagation();
                                setRecordRunId(item.run_id!);
                              }}
                            />
                          </span>
                        ),
                        // ClaudeOutputPane 依赖父容器高度约束，这里限高滚动避免时间轴被长运行拉穿
                        children: (
                          <div style={{ maxHeight: 480, overflow: 'auto', border: '1px solid #f0f0f0', borderRadius: 8, padding: isMobile ? 4 : 8, background: '#fafafa' }}>
                            <ClaudeOutputPane runId={item.run_id!} project={name} />
                          </div>
                        ),
                      },
                    ]}
                  />
                )}
              </div>
            ),
          };
        })}
      />
    );
  };

  // 页签配置
  const tabItems = [
    {
      key: 'timeline',
      label: '运行时间轴',
      children: (
        <div style={{ padding: '20px 0' }} className="spec-detail-timeline">
          {renderTimeline()}
        </div>
      ),
    },
    {
      key: 'scenarios',
      label: (
        <span>
          场景结果
          <Badge count={detail?.scenarios?.length ?? 0} style={{ marginLeft: 4, marginTop: -5 }} />
        </span>
      ),
      children: (
        <div style={{ padding: '20px 0' }}>
          {detail?.scenarios?.length ? (
            <div>
              {/* 状态过滤条（点击筛选，再点取消；计数取自场景数组本身） */}
              <div style={{ marginBottom: 16 }}>
                <Space size={8} wrap>
                  {(
                    [
                      { key: 'pass', label: '通过', color: 'success' },
                      { key: 'warning', label: '警告', color: 'warning' },
                      { key: 'fail', label: '失败', color: 'error' },
                      { key: 'error', label: '错误', color: 'error' },
                    ] as const
                  ).map((c) => {
                    const active = scenarioFilter === c.key;
                    return (
                      <Tag
                        key={c.key}
                        color={active ? c.color : 'default'}
                        style={{ cursor: 'pointer' }}
                        onClick={() => setScenarioFilter(active ? '' : c.key)}
                      >
                        {c.label} {detail.scenarios.filter((s) => s.status === c.key).length}
                      </Tag>
                    );
                  })}
                </Space>
              </div>

              {/* 场景卡片列表（v1 scenarioCard 同款：状态 + 场景 ID + 描述 + 失败步骤/断言明细） */}
              {(scenarioFilter
                ? detail.scenarios.filter((s) => s.status === scenarioFilter)
                : detail.scenarios
              ).map((scenario, idx) => {
                const failedSteps = (scenario.step_results || []).filter((s) => !s.success);
                const assertions = scenario.assertion_results || [];
                return (
                  <Card
                    // SSE 增量刷新可能在既有条目之间增删（场景重跑），索引 key 会
                    // 按位置错位复用节点；kind 缺省按 web 拼前缀保证跨 kind 唯一
                    // （code-review item 92d9f4c54ba9）
                    key={`${scenario.kind || 'web'}-${scenario.scenario_id}`}
                    size="small"
                    style={{ marginBottom: 12 }}
                    title={
                      <Space size={8}>
                        <Tag
                          color={
                            scenario.status === 'pass'
                              ? 'success'
                              : scenario.status === 'warning'
                                ? 'warning'
                                : 'error'
                          }
                        >
                          {scenario.status === 'pass'
                            ? '✅ 通过'
                            : scenario.status === 'warning'
                              ? '⚠️ 警告'
                              : scenario.status === 'fail'
                                ? '✗ 失败'
                                : '✗ 错误'}
                        </Tag>
                        <KindBadge kind={scenario.kind} />
                        <Typography.Text strong>{scenario.scenario_id}</Typography.Text>
                      </Space>
                    }
                  >
                    {/* 场景内容放正文，14px */}
                    {scenario.description && (
                      <Typography.Text style={{ fontSize: 14, display: 'block', marginBottom: 8 }}>
                        {scenario.description}
                      </Typography.Text>
                    )}

                    {/* 失败步骤明细（仅未成功步骤，v1 同款） */}
                    {failedSteps.length > 0 && (
                      <div style={{ marginBottom: assertions.length ? 8 : 0 }}>
                        <Typography.Text style={{ display: 'block', marginBottom: 4 }}>
                          失败步骤:
                        </Typography.Text>
                        {failedSteps.map((step, sIdx) => (
                          <div
                            key={sIdx}
                            style={{
                              padding: '4px 8px',
                              marginBottom: 4,
                              background: '#fff2f0',
                              border: '1px solid #ffccc7',
                              borderRadius: 4,
                            }}
                          >
                            <Typography.Text type="danger">
                              ✗ {step.action || '?'} {step.description || ''} {step.error || step.detail || ''}
                            </Typography.Text>
                          </div>
                        ))}
                      </div>
                    )}

                    {/* 断言明细（失败标红，v1 同款） */}
                    {assertions.length > 0 && (
                      <div>
                        <Typography.Text style={{ display: 'block', marginBottom: 4 }}>
                          断言:
                        </Typography.Text>
                        {assertions.map((a, aIdx) => {
                          const ok = a.pass !== false;
                          return (
                            <div
                              key={aIdx}
                              style={{
                                padding: '4px 8px',
                                marginBottom: 4,
                                background: ok ? '#f6ffed' : '#fff2f0',
                                border: `1px solid ${ok ? '#b7eb8f' : '#ffccc7'}`,
                                borderRadius: 4,
                              }}
                            >
                              <Typography.Text type={ok ? undefined : 'danger'}>
                                {ok ? '✓' : '✗'}{' '}
                                <Tooltip title={`断言类型: ${a.type || '?'}`}>
                                  {assertionLabel(a.type)}
                                </Tooltip>
                                : {assertionDetail(a)}{' '}
                                {ok ? '' : `— ${a.message || a.detail || a.error || ''}`}
                              </Typography.Text>
                            </div>
                          );
                        })}
                      </div>
                    )}
                  </Card>
                );
              })}
            </div>
          ) : detail?.report?.error ? (
            <Empty description="report.json 损坏或不可读" />
          ) : (
            <Empty description="暂无场景结果" />
          )}
        </div>
      ),
    },
    {
      key: 'bugs',
      label: (
        <span>
          Bug 列表
          <Badge count={detail?.bugs?.length ?? 0} style={{ marginLeft: 4, marginTop: -5 }} />
        </span>
      ),
      children: (
        <div style={{ padding: '20px 0' }}>
          {detail?.bugs && detail.bugs.length > 0 ? (
            <div>
              {detail.bugs.map((bug, idx) => (
                <Card
                  key={idx}
                  size="small"
                  style={{ marginBottom: 12 }}
                  title={
                    <Space size={8}>
                      <Tag
                        color={
                          bug.severity === 'critical'
                            ? 'error'
                            : bug.severity === 'major'
                              ? 'orange'
                              : bug.severity === 'minor'
                                ? 'default'
                                : 'blue'
                        }
                      >
                        {bug.severity || 'major'}
                      </Tag>
                      <Typography.Text type="secondary">{bug.source || 'report'}</Typography.Text>
                    </Space>
                  }
                >
                  <Typography.Paragraph style={{ marginBottom: 8 }}>
                    {bug.description}
                  </Typography.Paragraph>

                  {/* 关联场景 */}
                  {bug.scenario && (
                    <div style={{ marginBottom: 8 }}>
                      <Typography.Text type="secondary">关联场景: </Typography.Text>
                      <Typography.Text>{bug.scenario}</Typography.Text>
                    </div>
                  )}

                  {/* 断言类型 */}
                  {bug.assertion && (
                    <div style={{ marginBottom: 8 }}>
                      <Typography.Text type="secondary">断言类型: </Typography.Text>
                      <Tooltip title={assertionLabel(bug.assertion) !== bug.assertion ? bug.assertion : ''}>
                        <Typography.Text>{assertionLabel(bug.assertion)}</Typography.Text>
                      </Tooltip>
                    </div>
                  )}

                  {/* 证据 */}
                  {bug.evidence && (
                    <div
                      style={{
                        padding: '8px 12px',
                        marginBottom: 8,
                        background: '#f5f5f5',
                        borderRadius: 4,
                        fontFamily: 'monospace',
                        fontSize: 13,
                      }}
                    >
                      <Typography.Text>{bug.evidence}</Typography.Text>
                    </div>
                  )}

                  {/* 截图缩略图 */}
                  {bug.screenshots && bug.screenshots.length > 0 && (
                    <div style={{ marginTop: 8, display: 'flex', flexWrap: 'wrap', gap: 8 }}>
                      {bug.screenshots.map((file, sIdx) => (
                        <Image
                          key={sIdx}
                          src={`/screenshots/${encodeURIComponent(name)}/${encodeURIComponent(spec)}/${encodeURIComponent(file)}`}
                          alt={`Bug ${idx + 1} 截图 ${sIdx + 1}`}
                          width={150}
                          height={100}
                          style={{
                            objectFit: 'cover',
                            border: '1px solid #d9d9d9',
                            borderRadius: 4,
                          }}
                          preview={{ mask: '点击预览' }}
                        />
                      ))}
                    </div>
                  )}
                </Card>
              ))}
              {/* fix-verify-verdict-visibility：bugs 非空时被过滤场景摘要折叠为次级区块 */}
              {detail?.filtered_failures && detail.filtered_failures.length > 0 && (
                <FilteredFailuresBlock
                  filtered={detail.filtered_failures}
                  name={name}
                  spec={spec}
                  collapsed
                />
              )}
            </div>
          ) : (
            <div>
              {/* filtered_failures 为空时行为与现状完全一致：仅「无遗留 Bug」空态 */}
              <Empty description="无遗留 Bug" />
              {detail?.filtered_failures && detail.filtered_failures.length > 0 && (
                <FilteredFailuresBlock
                  filtered={detail.filtered_failures}
                  name={name}
                  spec={spec}
                  collapsed={false}
                />
              )}
            </div>
          )}
        </div>
      ),
    },
    {
      key: 'screenshots',
      label: (
        <span>
          测试截图
          <Badge count={detail?.screenshots?.length ?? 0} style={{ marginLeft: 4, marginTop: -5 }} />
        </span>
      ),
      children: (
        <div style={{ padding: '20px 0' }}>
          {detail?.screenshots && detail.screenshots.length > 0 ? (
            <div>
              <div style={{ marginBottom: 12 }}>
                <Typography.Text type="secondary">
                  共 {detail.screenshots.length} 张截图（点击放大）
                </Typography.Text>
              </div>
              <Image.PreviewGroup
                items={detail.screenshots.map((s) => ({
                  src: `/screenshots/${encodeURIComponent(name)}/${encodeURIComponent(spec)}/${encodeURIComponent(s.file)}`,
                  alt: s.file,
                }))}
              >
                <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8 }}>
                  {detail.screenshots.map((s, idx) => (
                    <Image
                      key={idx}
                      src={`/screenshots/${encodeURIComponent(name)}/${encodeURIComponent(spec)}/${encodeURIComponent(s.file)}`}
                      alt={s.file}
                      width={150}
                      height={100}
                      style={{
                        objectFit: 'cover',
                        border: '1px solid #d9d9d9',
                        borderRadius: 4,
                        cursor: 'pointer',
                      }}
                      preview={{
                        mask: '点击预览',
                      }}
                    />
                  ))}
                </div>
              </Image.PreviewGroup>
            </div>
          ) : (
            <Empty description="暂无截图" />
          )}
        </div>
      ),
    },
    // Hook 页签始终展示：pushed（终态）spec 仍可查看执行记录，
    // 只是订阅配置转只读（新增/编辑/启停禁用，见 HookManager readOnly）
    {
      key: 'hooks',
      label: <span>Hook</span>,
      children: <SpecHooksSection name={name} spec={spec} readOnly={detail?.status === 'pushed'} />,
    },
  ];

  return (
    <PageContainer breadcrumbRender={false} header={headerCfg}>
      {/* 项目信息（置顶）：基础元信息 + 累计 Token 消耗（只展示输入/输出，成本不回传不准不算）+ 耗时/成本 */}
      <Card
        title={
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
            <span>项目信息</span>
            <Typography.Link onClick={() => openDocModal('proposal')} className="touch-expand">文档</Typography.Link>
          </div>
        }
        size="small"
        style={{ marginBottom: 16 }}
      >
        {/* spec-detail-desc：三列等宽分配（global.less 中 table-layout:fixed），移动端单列不适用 */}
        <Descriptions className="spec-detail-desc" column={{ xs: 1, sm: 2, md: 3 }} size="small">
          <Descriptions.Item label="优先级">
            <span>P{detail?.priority ?? '?'}</span>
          </Descriptions.Item>
          <Descriptions.Item label="创建时间">
            {detail?.created ? dayjs(detail.created).format('YYYY-MM-DD HH:mm:ss') : '—'}
          </Descriptions.Item>
          <Descriptions.Item label="更新时间">
            {detail?.updated ? dayjs(detail.updated).format('YYYY-MM-DD HH:mm:ss') : '—'}
          </Descriptions.Item>
          <Descriptions.Item label="依赖">
            {detail?.depends_on || '无依赖'}
          </Descriptions.Item>
          <Descriptions.Item label="输入 Token">
            {detail?.token_usage ? fmtInputTokens(detail.token_usage) : '—'}
          </Descriptions.Item>
          <Descriptions.Item label="输出 Token">
            {detail?.token_usage ? fmtMillions(detail.token_usage.tokens_out) : '—'}
          </Descriptions.Item>
          {/* add-spec-detail-duration：耗时与列表页「耗时」列同源同口径（后端
              _spec_total_duration 共享实现），格式同列表 fmtDuration */}
          <Descriptions.Item label="耗时">
            {detail ? fmtDuration(detail.total_duration ?? 0) : '—'}
          </Descriptions.Item>
          {/* add-model-billing-cost-display + 成本恒显示：computed_usd 非空 → 金额
              （含未计价 run 提示）；计价表为空（后端不下发 cost_summary）或全部
              run 不可计价 → 「成本不可用」，绝不显示 $0.00；detail 未加载完显示
              — 防止加载瞬间闪「成本不可用」 */}
          <Descriptions.Item label="成本">
            {!detail ? (
              '—'
            ) : detail.cost_summary?.computed_usd != null ? (
              <>
                <Typography.Text>{formatUsd(detail.cost_summary.computed_usd)}</Typography.Text>
                {detail.cost_summary.unpriced_runs > 0 && (
                  <Typography.Text type="secondary" style={{ marginLeft: 4 }}>
                    （含 {detail.cost_summary.unpriced_runs} 个未计价 run）
                  </Typography.Text>
                )}
              </>
            ) : (
              <Typography.Text type="secondary">成本不可用</Typography.Text>
            )}
          </Descriptions.Item>
        </Descriptions>
      </Card>

      {/* 告警与信息：仅在有内容时展示（spec.error 语义是需知会的信息而非错误，按 info 样式渲染）。
          标题统一 14px、图标固定 16px（覆盖 antd 带 description 时 16px 标题/24px 图标的默认样式）；
          告警内容默认折叠，右侧箭头展开；操作统一为右侧 X 清除链接 */}
      {(detail?.error || specAlerts.length > 0) && (
        <div style={{ marginBottom: 16, display: 'flex', flexDirection: 'column', gap: 8 }}>
          {specAlerts.map((a) => {
            const evidenceText = fmtEvidence(a.evidence);
            const hasContent = !!(a.recommended_action || evidenceText);
            const expanded = expandedAlerts.has(a.id);
            /* add-human-adjudication-choices 5.2：带 choices 的告警渲染裁决
               选择题（Select + note + 执行）；无 choices 保持「知道了」形态 */
            const adjudicable = Array.isArray(a.choices) && a.choices.length > 0;
            const selChoiceId = alertChoiceSels[a.id] || '';
            const selChoice = (a.choices || []).find((c) => c.id === selChoiceId);
            const resolving = resolvingAlerts.has(a.id);
            const resolveMsg = alertResolveMsgs[a.id];
            return (
              <Alert
                key={a.id}
                className="spec-detail-alert"
                type={a.severity === 'critical' ? 'error' : 'warning'}
                showIcon
                icon={<ExclamationCircleFilled style={{ fontSize: 16 }} />}
                /* padding 钉在收缩态基准值上：展开/收起外边距恒定，箭头与叉号不移位 */
                style={{ padding: '8px 12px' }}
                message={
                  <Space size={6} wrap>
                    <span style={{ fontSize: 14 }}>告警：{a.description || a.action_taken || '人工升级告警'}</span>
                    <Tag color={SEV_COLOR[a.severity || ''] || 'default'} style={{ marginInlineEnd: 0 }}>
                      {SEV_LABEL[a.severity || ''] || a.severity || '未知'}
                    </Tag>
                  </Space>
                }
                description={
                  hasContent || adjudicable || resolveMsg ? (
                    <>
                      {hasContent && (
                        /* description 常驻（折叠时仅 display:none）：Alert 始终保持 with-description
                           变体，展开/收起不再触发布局切换导致箭头与叉号移位 */
                        <div style={expanded ? { fontSize: 12, whiteSpace: 'pre-wrap', marginTop: 8 } : { display: 'none' }}>
                          {a.recommended_action && (
                            <div>
                              <Typography.Text type="secondary">建议：{a.recommended_action}</Typography.Text>
                            </div>
                          )}
                          {evidenceText && (
                            <div>
                              <Typography.Text type="secondary">证据：{evidenceText}</Typography.Text>
                            </div>
                          )}
                        </div>
                      )}
                      {adjudicable && (
                        /* 裁决控件常驻（不随折叠隐藏）：wrap 布局适配窄屏。
                           执行按钮（含 destructive 二次确认门）经共享控件，
                           确认门与 overview AlertBanner 同源（item f86171cc149d）*/
                        <div style={{ marginTop: 8, display: 'flex', flexWrap: 'wrap', alignItems: 'center', gap: 6 }}>
                          <Select
                            size="small"
                            style={{ minWidth: 220, flex: '1 1 220px' }}
                            placeholder="选择裁决项"
                            value={selChoiceId || undefined}
                            onChange={(v) => setAlertChoiceSels((m) => ({ ...m, [a.id]: v }))}
                            disabled={resolving}
                            options={(a.choices || []).map((c) => ({ value: c.id, label: c.label, title: c.desc }))}
                          />
                          <Input
                            size="small"
                            style={{ width: 200, flex: '1 1 160px' }}
                            maxLength={200}
                            placeholder="处置依据（可选）"
                            value={alertNotes[a.id] || ''}
                            onChange={(e) => setAlertNotes((m) => ({ ...m, [a.id]: e.target.value }))}
                            disabled={resolving}
                          />
                          <AlertAdjudicationExec
                            alert={a}
                            adj={adj}
                            /* 裁决成功后重拉告警列表与 spec 详情（处置闭环回显） */
                            onResolved={() => {
                              loadSpecAlerts();
                              getSpecDetail(name, spec)
                                .then((d) => {
                                  // 迟到响应守卫：等待期间已切换 SPEC → 丢弃旧详情，不串页
                                  if (nameSpecRef.current.name !== name || nameSpecRef.current.spec !== spec) return;
                                  setDetail(d);
                                })
                                .catch(() => {});
                            }}
                          />
                        </div>
                      )}
                      {selChoice?.desc && adjudicable && (
                        <div style={{ marginTop: 4, fontSize: 12 }}>
                          <Typography.Text type="secondary">{selChoice.desc}</Typography.Text>
                        </div>
                      )}
                      {resolveMsg && (
                        <div style={{ marginTop: 4, fontSize: 12, whiteSpace: 'pre-wrap' }}>
                          <Typography.Text type={resolveMsg.tone === 'error' ? 'danger' : 'secondary'}>
                            {resolveMsg.text}
                          </Typography.Text>
                        </div>
                      )}
                    </>
                  ) : undefined
                }
                action={
                  <Space size={12}>
                    {hasContent && (
                      <a onClick={() => toggleAlert(a.id)} title={expanded ? '收起' : '展开'}>
                        <DownOutlined rotate={expanded ? 180 : 0} />
                      </a>
                    )}
                    <Typography.Link onClick={() => void handleMarkAlertHandled(a)} title="清除">
                      <CloseOutlined />
                    </Typography.Link>
                  </Space>
                }
              />
            );
          })}
          {detail?.error && (
            <Alert
              type="info"
              showIcon
              icon={<InfoCircleFilled style={{ fontSize: 16 }} />}
              message={<span style={{ fontSize: 14 }}>信息：{detail.error}</span>}
              action={
                <Typography.Link onClick={() => void handleClearInfo()} title="清除">
                  <CloseOutlined />
                </Typography.Link>
              }
            />
          )}
        </div>
      )}

      {/* 任务清单（overview 任务进度同款控件 + 分组勾选） */}
      <Card title="任务清单" size="small" style={{ marginBottom: 16 }}>
        {taskGroups.length > 0 ? (
          <>
            <ProgressBarTile done={completedTasks} total={totalTasks} />
            {/* run 层实时线索（fix-implementer-task-progress D3）：tasks.md 快照
                落后于 run 实际推进时叠加显示，不再静止 0/N */}
            {detail?.run_progress && detail.run_progress.done > completedTasks ? (
              <Typography.Text
                type="warning"
                data-testid="run-progress-hint"
                style={{ display: 'block', marginTop: 6, fontSize: 12 }}
              >
                run {detail.run_progress.done}/{detail.run_progress.total} 已汇报
              </Typography.Text>
            ) : null}
            {detail?.run_progress?.current?.length ? (
              <Typography.Text
                type="warning"
                data-testid="run-progress-current"
                style={{ display: 'block', marginTop: 6, fontSize: 12 }}
              >
                run 进行中 {detail.run_progress.current.join('、')}
              </Typography.Text>
            ) : null}
            {/* 存活心跳（2026-09-15 原地补充）：run_progress 依赖 TaskCreate/
                TaskUpdate；该工具族虽经 CLAUDE_CODE_ENABLE_TODO_TOOLS=1 恢复，
                但实现期间 agent 未必立刻建 Task、历史 run 也可能无事件。run_activity
                用「产物是否仍在写」提供不依赖任务工具的存活线索，仅在无更细粒度
                线索（current）时兜底显示，避免误读成「卡死」。 */}
            {!detail?.run_progress?.current?.length && detail?.run_activity?.active ? (
              <Typography.Text
                type="warning"
                data-testid="run-activity-active"
                style={{ display: 'block', marginTop: 6, fontSize: 12 }}
              >
                run 进行中
              </Typography.Text>
            ) : null}
            {proposalWhy ? (
              <div
                style={{
                  fontSize: 13,
                  lineHeight: 1.65,
                  color: 'rgba(0, 0, 0, 0.65)',
                  marginBottom: 10,
                }}
              >
                <Markdown remarkPlugins={[remarkGfm]} components={markdownComponents}>
                  {proposalWhy}
                </Markdown>
              </div>
            ) : null}
            {taskGroups.map((group, idx) => (
              <div key={idx} style={{ marginBottom: idx === taskGroups.length - 1 ? 0 : 12 }}>
                <Typography.Text strong style={{ display: 'block', marginBottom: 10 }}>
                  {group.title} ({group.done}/{group.total})
                </Typography.Text>
                {group.tasks.map((task, taskIdx) => (
                  <div key={taskIdx} style={{ display: 'flex', alignItems: 'flex-start', marginBottom: 10 }}>
                    <Checkbox checked={task.done} disabled style={{ marginRight: 8 }} />
                    <Typography.Text
                      style={{
                        color: task.done ? undefined : '#999',
                      }}
                    >
                      <code style={{ marginRight: 6 }}>{task.id}</code>
                      {task.desc}
                    </Typography.Text>
                  </div>
                ))}
              </div>
            ))}
          </>
        ) : detail?.tasks_note ? (
          // tasks.md 存在但未解析出任务分组（task-track R3）：warning 空态，
          // 与无 tasks.md 文件的 secondary 空态可区分
          <Typography.Text type="warning" data-testid="tasks-note-warning">
            {detail.tasks_note}
            <br />
            可检查 SPEC 的 tasks.md 分组标题格式
          </Typography.Text>
        ) : (
          <Typography.Text type="secondary">暂无任务清单</Typography.Text>
        )}
      </Card>

      {/* 质量门禁（add-quality-gates-visibility）：统一 6 道门禁勾选列表。
          drafted/ready 且无门禁文件不渲染本 Card（早期 spec 无门禁可言）；
          其余状态文件不可见时显示空态兜底 */}
      {shouldRenderGatesCard(detail?.status, !!detail?.quality_gates?.exists) ? (
        <Card title="质量门禁" size="small" style={{ marginBottom: 16 }} data-testid="quality-gates-card">
          {detail?.quality_gates?.exists ? (
            <>
              <ProgressBarTile
                done={detail.quality_gates.done}
                total={detail.quality_gates.total}
              />
              {detail.quality_gates.current ? (
                <Typography.Text type="secondary" style={{ display: 'block', marginBottom: 8 }}>
                  当前：{detail.quality_gates.current}
                </Typography.Text>
              ) : null}
              {normalizeGateItems(detail.quality_gates.items).map((item, idx) => (
                <div
                  key={item.id || idx}
                  data-testid="quality-gate-item"
                  style={{ display: 'flex', alignItems: 'flex-start', marginBottom: 10 }}
                >
                  <Checkbox checked={gateChecked(item)} disabled style={{ marginRight: 8 }} />
                  <Typography.Text
                    style={{
                      color: gateTextColor(item),
                    }}
                  >
                    {item.desc}
                    {gateSuffix(item)}
                  </Typography.Text>
                  {gateDetailText(item) ? (
                    <Typography.Text type="secondary" style={{ marginLeft: 8, fontSize: 12 }}>
                      {gateDetailText(item)}
                    </Typography.Text>
                  ) : null}
                </div>
              ))}
            </>
          ) : (
            <Typography.Text type="secondary">暂无质量门禁记录</Typography.Text>
          )}
        </Card>
      ) : null}

      {/* 验证进度（overview 任务进度同款控件 + 当前步骤） */}
      <Card title="验证进度" size="small" style={{ marginBottom: 16 }}>
        {detail?.verify_progress?.exists ? (
          <>
            {detail.verify_progress.error && (
              <Alert type="error" showIcon message="进度文件损坏" style={{ marginBottom: 8 }} />
            )}
            <ProgressBarTile done={detail.verify_progress.done} total={detail.verify_progress.total} />
            {detail.verify_progress.current && (
              <Typography.Text type="secondary">当前：{detail.verify_progress.current}</Typography.Text>
            )}
          </>
        ) : detail?.generation ? (
          /* verification-phase-progress：场景生成阶段（执行未开始）展示出题进度 */
          <>
            <Typography.Text type="secondary">场景生成中（出题）</Typography.Text>
            <ProgressBarTile done={detail.generation.done} total={detail.generation.total} />
          </>
        ) : (
          <Typography.Text type="secondary">暂无验证进度</Typography.Text>
        )}
      </Card>

      {/* 验证结论 */}
      <Card title="验证结论" size="small" style={{ marginBottom: 16 }}>
        {detail?.verdict?.exists ? (
          <VerdictPanel verdict={detail.verdict} />
        ) : (
          <Typography.Text type="secondary">暂无验证结论</Typography.Text>
        )}
        {/* add-planready-artifact-gate D4：降级标注一行提示（报告 degrade_annotation
            字段条件渲染；无字段不渲染）。新验证流程 planner 阶段失败降级 legacy 时
            合成报告携带该标注，前端据此透出降级事实与代价。 */}
        {detail?.report?.degrade_annotation && (
          <Alert
            type="warning"
            showIcon
            data-testid="degrade-annotation"
            style={{ marginTop: 12 }}
            message={
              <span>
                ⚠️ 降级说明：本报告由框架合成（新验证流程 planner 阶段失败：
                {detail.report.degrade_annotation.reason || '未知原因'}；被降级轮次{' '}
                {detail.report.degrade_annotation.run_id || '未知 run'} 烧{' '}
                {detail.report.degrade_annotation.duration_seconds != null
                  ? `${(detail.report.degrade_annotation.duration_seconds / 60).toFixed(1)}min`
                  : '时长未知'}
                {detail.report.degrade_annotation.cost_usd != null
                  ? ` / $${detail.report.degrade_annotation.cost_usd.toFixed(2)}`
                  : ''}
                ）
              </span>
            }
          />
        )}
      </Card>

      {/* 页签区 */}
      <Card className="spec-detail-card">
        <Tabs items={tabItems} />
      </Card>

      {/* SPEC 文档弹窗（时间轴报告链接 → 验证报告；项目信息「文档」→ 需求背景） */}
      <SpecDocModal
        project={name}
        spec={spec}
        open={docModalOpen}
        onClose={() => setDocModalOpen(false)}
        initialDoc={docInitial}
      />

      {/* 运行记录最大化弹窗（时间轴「查看运行记录」旁全屏入口） */}
      <RunRecordModal runId={recordRunId} project={name} onClose={() => setRecordRunId(null)} />

      {/* add-run-cancel（4.2）：终止运行确认弹窗，受理后行内反馈 */}
      <RunCancelModal
        project={name}
        runId={cancelRunId}
        onClose={() => setCancelRunId(null)}
        onAccepted={(rid) =>
          setCancelNotices((prev) => ({ ...prev, [rid]: '取消请求已受理' }))
        }
      />
    </PageContainer>
  );
}