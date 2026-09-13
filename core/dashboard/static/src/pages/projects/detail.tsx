import { PageContainer } from '@ant-design/pro-components';
import { Alert, App, Badge, Button, Card, Checkbox, Collapse, Descriptions, Dropdown, Empty, Image, Progress, Space, Spin, Tabs, Tag, Timeline, Tooltip, Typography } from 'antd';
import { CloseOutlined, DownOutlined, ExclamationCircleFilled, FullscreenOutlined, InfoCircleFilled } from '@ant-design/icons';
import { Fragment, useCallback, useEffect, useRef, useState } from 'react';
import { history, useParams } from '@umijs/max';
import dayjs from 'dayjs';
import Markdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { clearSpecError, getAlerts, getConfig, getHookAudit, getSpecDetail, getSpecs, markAlertHandled, saveConfig, statusMeta } from '@/services/dashboard';
import type { AlertItem, ConfigData, HookAuditRecord, HookConfig, HooksConfig, SpecDetail, SpecSummary } from '@/services/dashboard';
import HookManager from '@/components/HookManager';
import { markdownComponents } from './components/SpecDocModal';
import SpecDocModal from './components/SpecDocModal';
import type { DocType } from './components/SpecDocModal';
import RunRecordModal from './components/RunRecordModal';
import RunCancelModal from './components/RunCancelModal';
import { ClaudeOutputPane } from '@/components/claude-msg';
import { OutlinedTag } from '@/components/StatusTag';
import { useIsMobile } from '@/hooks/useIsMobile';
import { fetchProposalWhy } from '@/utils/proposalWhy';
import { fmtInputTokens, fmtMillions } from '@/utils/tokens';

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
      const actual = a.actual !== undefined ? `，实际「${JSON.stringify(a.actual) ?? a.actual}」` : '';
      return `JSON ${a.path || '?'} 期望「${JSON.stringify(a.expected) ?? a.expected}」${actual}`;
    }
    // ── api ──
    case 'status_code':
      return `期望状态码 ${a.expected ?? '?'}，实际 ${a.actual ?? '?'}`;
    case 'json_path': {
      const actual = a.actual !== undefined ? `，实际「${JSON.stringify(a.actual) ?? a.actual}」` : '';
      return `路径 ${a.path || '?'} 期望「${JSON.stringify(a.expected) ?? a.expected}」${actual}`;
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
      if (a.expected !== undefined) bits.push(`期望「${JSON.stringify(a.expected) ?? a.expected}」`);
      if (a.actual !== undefined && a.actual !== null && a.actual !== '')
        bits.push(`实际「${JSON.stringify(a.actual) ?? a.actual}」`);
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

// overview「任务进度」同款进度条控件：大百分比 + 已完成 x/y + 渐变进度条（验证进度/任务清单共用）
function ProgressBarTile({ done, total }: { done: number; total: number }) {
  const p = total > 0 ? Math.round((done / total) * 100) : 0;
  return (
    <>
      <div style={{ display: 'flex', alignItems: 'baseline', justifyContent: 'space-between', margin: '4px 0 10px', flexWrap: 'wrap' }}>
        <span style={{ fontSize: 28, fontWeight: 600, lineHeight: '40px' }}>{p}%</span>
        <span>
          <Typography.Text type="secondary">已完成 </Typography.Text>
          <Typography.Text strong>
            {done} / {total}
          </Typography.Text>
        </span>
      </div>
      <Progress
        percent={p}
        strokeColor={{ '0%': '#108ee9', '100%': '#87d068' }}
        status="active"
        style={{ marginBottom: 12 }}
      />
    </>
  );
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

// 告警严重度标签/配色（与 overview AlertBanner 同语义）
const SEV_LABEL: Record<string, string> = { critical: '严重', major: '较高', warning: '警告', minor: '一般' };
const SEV_COLOR: Record<string, string> = { critical: 'red', major: 'orange', minor: 'blue' };

// Agent 中文名（与设置页 Agent 模型角色中文名对应；implementer 沿用「开发」）。
// agent_type 为泛型 'agent' 或缺失时，按 run_id 前缀（admin-/impl-/test-/verify-）判别。
const AGENT_LABEL: Record<string, string> = {
  implementer: '开发 Agent',
  planner: '规划 Agent',
  'planner-plan': '生成场景 Agent',
  'planner-judge': '判定结果 Agent',
  verifier: '验证 Agent',
  tester: '测试 Agent',
  administrator: '运维 Agent',
};

const RUN_ID_PREFIX_LABEL: Record<string, string> = {
  impl: '开发 Agent',
  admin: '运维 Agent',
  test: '测试 Agent',
  verify: '验证 Agent',
};

function agentLabel(item: { agent_type?: string; run_id?: string }): string {
  const t = (item.agent_type || '').toLowerCase();
  if (t && AGENT_LABEL[t]) return AGENT_LABEL[t];
  const prefix = (item.run_id || '').toLowerCase().split('-')[0];
  if (prefix && RUN_ID_PREFIX_LABEL[prefix]) return RUN_ID_PREFIX_LABEL[prefix];
  return t || '未知 Agent';
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
    setSaving(true);
    try {
      const cfg = await saveConfig(name, {
        hooks: {
          ...hooksCfg,
          specs: { ...(hooksCfg.specs || {}), [spec]: nextSpecHooks },
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
  // 场景结果状态过滤（'' = 全部）
  const [scenarioFilter, setScenarioFilter] = useState<'pass' | 'warning' | 'fail' | 'error' | ''>('');
  // 任务背景描述 = proposal 文档 ## Why 段（spec 列表悬停同名内容），懒加载
  const [proposalWhy, setProposalWhy] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

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

    const load = async (initial = false) => {
      try {
        if (initial) setLoading(true);
        const data = await getSpecDetail(name, spec);
        applyDetail(data);
        if (initial) setError('');
      } catch (e) {
        // 后台刷新失败静默保留旧视图，只有首次加载才呈现错误页
        if (initial) setError(e instanceof Error ? e.message : String(e));
      } finally {
        if (initial) setLoading(false);
      }
    };

    void load(true);

    // watcher 的 detail/state 事件自带完整详情可直接采用；
    // run_meta/refresh 只带轻量通知，节流后重拉 REST（与 list.tsx 同策略）。
    const REFRESH_THROTTLE_MS = 500;
    let lastRefresh = 0;
    const throttledLoad = () => {
      const now = Date.now();
      if (now - lastRefresh < REFRESH_THROTTLE_MS) return;
      lastRefresh = now;
      void load();
    };
    const es = new EventSource('/api/stream');
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
      if (msg.type === 'run_meta' || msg.type === 'refresh') {
        throttledLoad();
      }
    };
    return () => es.close();
  }, [name, spec]);

  const { message } = App.useApp();

  // 本 SPEC 的人工升级告警（未处理），拉取失败静默不影响主视图
  const loadSpecAlerts = useCallback(() => {
    getAlerts()
      .then((d) => {
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

  // 下拉快速切换项：项目下除当前 SPEC 外的其他 SPEC（只有当前一个时不展示箭头）
  const otherSpecs = specList.filter((s) => s.name !== spec);

  // 下拉快速切换面板（表格形式）：SPEC 名称（过长截断 + 悬停提示） + 状态标签（statusMeta 同列表页语义）。
  // 面板宽度上限 300px 且移动端不超出视口（max-width: calc(100vw - 32px)），内容区限高滚动。
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
          <Tag color={statusInfo.tone === 'good' ? 'success' : statusInfo.tone === 'critical' ? 'error' : 'processing'}>
            {statusInfo.label}
          </Tag>
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
    onBack: () => history.push(`/projects/${name}`),
  };

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

  // 清除 spec 信息（同列表页清除 error）；成功后重拉详情使信息条消失
  const handleClearInfo = async () => {
    try {
      await clearSpecError(name, spec);
      message.success('已清除');
      setDetail(await getSpecDetail(name, spec));
    } catch (err) {
      message.error(`清除失败：${err instanceof Error ? err.message : String(err)}`);
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

  // 格式化时长
  const fmtDuration = (seconds: number) => {
    if (seconds == null || Number.isNaN(seconds)) return '';
    let s = Math.max(0, Math.round(seconds));
    if (s < 60) return `${s}秒`;
    const m = Math.floor(s / 60);
    s %= 60;
    if (m < 60) return s ? `${m}分${s}秒` : `${m}分`;
    return `${Math.floor(m / 60)}时${m % 60}分${s ? `${s}秒` : ''}`;
  };

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
          // interrupted/cancelled：已终结但非崩溃（daemon 停机/启动清扫补写/
          // 人工取消），橙色区别于 error 红；不处理会落入 else 误显成功绿
          const isAborted = st === 'interrupted' || st === 'cancelled';
          const isRunning = st === 'running' || st === 'empty';
          // stale（fix-retry-orphan-active-runs）：弃置/断尾——原地重试换文件
          // 弃置或进程被杀无终态，读侧 mtime 兜底判定；灰色区别于 running 蓝 /
          // error 红，归入非在飞非错误分支
          const dotColor = isErr ? 'red' : isAborted ? 'orange' : st === 'stale' ? 'gray' : isRunning ? 'blue' : 'green';
          const dur = item.duration_seconds != null ? fmtDuration(item.duration_seconds) : '';
          const isFix = item.spec && String(item.spec).startsWith('fix-');

          return {
            color: dotColor,
            children: (
              <div style={cardBox(isErr)}>
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
                  <Tag color={isErr ? 'red' : st === 'stale' ? 'gray' : isRunning ? 'blue' : 'green'} style={{ marginInlineEnd: 0 }}>
                    {st || '未知状态'}
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
                  {cancelNotices[item.run_id!] && (
                    <Typography.Text type="success" style={{ fontSize: 12 }}>
                      {cancelNotices[item.run_id!]}
                    </Typography.Text>
                  )}
                </div>
                {/* 终态原因（run 产物 error/interrupted/cancelled 事件的人类可读原因）：
                    不展开运行记录即可见死因；运行中/成功 run 下发空串不渲染。
                    error 红色，interrupted/cancelled 已终结非崩溃用橙色（同节点圆点语义） */}
                {!!item.reason && (
                  <div style={{ marginBottom: 8 }}>
                    <Typography.Text type={isErr ? 'danger' : 'warning'} style={{ fontSize: 13 }}>
                      {isErr ? '失败原因：' : '中止原因：'}
                      {item.reason}
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
                    key={idx}
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
          失败截图
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
            const hasContent = !!(a.recommended_action || a.evidence);
            const expanded = expandedAlerts.has(a.id);
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
                  hasContent ? (
                    /* description 常驻（折叠时仅 display:none）：Alert 始终保持 with-description
                       变体，展开/收起不再触发布局切换导致箭头与叉号移位 */
                    <div style={expanded ? { fontSize: 12, whiteSpace: 'pre-wrap', marginTop: 8 } : { display: 'none' }}>
                      {a.recommended_action && (
                        <div>
                          <Typography.Text type="secondary">建议：{a.recommended_action}</Typography.Text>
                        </div>
                      )}
                      {a.evidence && (
                        <div>
                          <Typography.Text type="secondary">证据：{a.evidence}</Typography.Text>
                        </div>
                      )}
                    </div>
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
                        textDecoration: task.done ? 'line-through' : 'none',
                        color: task.done ? '#999' : 'inherit',
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