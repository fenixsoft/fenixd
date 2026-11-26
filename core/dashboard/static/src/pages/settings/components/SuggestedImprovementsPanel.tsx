/**
 * 建议改进项面板（add-framework-self-evolution 7.2-7.5）
 *
 * 设置页「自进化」页签下的第二张卡片。展示跨项目建议改进项表格，
 * 支持配置自进化开关 / 每轮上限、查看分析结论与草稿、同意立项 / 拒绝。
 *
 * 7.2: 顶部配置（用户级可写 / 项目级只读 + 全局键提示）
 * 7.3: 表格（列序：项目 / 日期 / 类别 / 问题 / 评估结论 / 状态 / 操作）
 * 7.4: 操作列「更多」下拉（复用 projects/list.tsx 形态）+ 二次确认弹窗
 * 7.5: 查看（单弹窗：分析结论 + 草稿文档页签）+ 接受拒绝反馈
 * 7.6: 表头排序 + 状态（默认待决策）/项目/日期过滤条 + 多选与批量同意/拒绝
 * 7.7: 操作列「删除」（硬删条目）+ 批量删除；类别列 Tag 渲染
 */
// 文案经 useIntl（i18n 修复轮 batch-S：本文件静态中文文案迁 i18n 目录）
import { useIntl } from '@umijs/max';
import { Alert, App, Button, Card, DatePicker, Dropdown, Empty, Form, InputNumber, Modal, Progress, Radio, Select, Space, Spin, Switch, Table, Tabs, Tag, TimePicker, Tooltip, Typography } from 'antd';
import { LeftOutlined, MoreOutlined, RightOutlined } from '@ant-design/icons';
import Markdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import dayjs from 'dayjs';
import type { Dayjs } from 'dayjs';
import type { MenuProps } from 'antd';
import { forwardRef, useCallback, useEffect, useImperativeHandle, useMemo, useRef, useState } from 'react';
import type { CSSProperties, Key } from 'react';
import type { ConfigData, EvolutionItem, EvolutionDoc, EvolutionAcceptJobStatus } from '@/services/dashboard';
import type { SettingsSectionHandle } from './settingsSection';
import { MaximizeTitle, useMaximizeModal } from '@/components/useMaximizeModal';
// 可点击标题色取宿主对齐链接蓝（theme.ts 单源；同 SPEC 列表页名称列口径）
// dashboard-dark-theme 4.2：theme.ts 常量消费改引 global.less 主题 CSS 变量
// （值源 theme.ts 档位镜像：浅档与原字面值逐字节一致、深档=D2 映射；var()
// 形态使切档零 React 参与即时生效，同名局部常量保持既有消费点字面不变）。
const DSH_BORDER_SECONDARY = 'var(--fenix-border-secondary)';
const DSH_ERROR = 'var(--fenix-error)';
const DSH_LINK = 'var(--fenix-link)';
import ScheduleFields, {
  describeStartAfter,
  isStartAfterValid,
  nextRunAtISO,
} from '@/components/ScheduleFields';
import type { AcceptSchedule } from '@/components/ScheduleFields';
import { markdownComponents } from '@/pages/projects/components/SpecDocModal';
import { usePanelDirty } from '../panelDirty';
import {
  EVOLUTION_STATUS_LABELS,
  EVOLUTION_DOCS,
  ApiError,
  getEvolutionItems,
  getEvolutionAnalysis,
  getEvolutionDraft,
  acceptEvolutionItemAsync,
  getEvolutionAcceptStatus,
  rejectEvolutionItem,
  deleteEvolutionItem,
  clearAllEvolutionTodo,
} from '@/services/dashboard';

const { Text } = Typography;

/**
 * 状态轴单源（code-review item 315ccdc0f28f）：排序、状态列配色、决策动作
 * 可执行性与批量跳过原因收敛一处，新增状态只改这里；文案沿用 services 的
 * EVOLUTION_STATUS_LABELS。
 */
type EvolutionStatusMeta = {
  /** 语义序：待人工处理的排前，终态排后（非字母序）。 */
  order: number;
  /** 状态列 Tag 配色。 */
  color: string;
  /** 仍可执行的决策动作；缺省 = 不可同意也不可拒绝（终态）。 */
  decidable?: readonly ('accept' | 'reject')[];
  /** 决策动作被禁用时批量跳过汇报的原因（i18n 后为消息 id，渲染期 formatMessage）；
   *  未登记状态回落 UNKNOWN_STATUS_DISABLED_REASON。 */
  disabledReason?: string;
};

const STATUS_META: Record<string, EvolutionStatusMeta> = {
  pending: { order: 0, color: 'gold', decidable: ['accept', 'reject'] },
  draft_failed: { order: 1, color: 'error', decidable: ['reject'], disabledReason: 'settings.evolution.skip.draftFailed' },
  accept_failed: { order: 2, color: 'error', decidable: ['accept', 'reject'] },
  analyzed: { order: 3, color: 'default', disabledReason: 'settings.evolution.skip.noDraftNeeded' },
  accepted: { order: 4, color: 'success', disabledReason: 'settings.evolution.skip.decided' },
  auto_accepted: { order: 5, color: 'success', disabledReason: 'settings.evolution.skip.decided' },
  rejected: { order: 6, color: 'default', disabledReason: 'settings.evolution.skip.decided' },
};

/** 后端新增终态而前端未同步（版本代差）时的决策禁用原因（消息 id）。 */
const UNKNOWN_STATUS_DISABLED_REASON = 'settings.evolution.skip.unknown';

/** 类别列 Tag 配色（参考 SPEC 列表页「模式」列的 Tag 写法）。 */
const SECTION_TAG_COLORS: Record<string, string> = {
  浪费: 'red',
  失误: 'orange',
  可改进: 'blue',
};

type BatchAction = 'accept' | 'reject' | 'delete';

// 批量动作动词映射（code-review item 8694f259d40f：旧实现嵌套三元链，
// 项目前端规则禁止，改为模块级映射常量取值）。
// i18n（batch-S）：动词与跳过原因改为消息 id，渲染期 formatMessage 求值
//（禁止模块顶层求值译文，先例 src/utils/format.ts）。
const BATCH_VERB: Record<BatchAction, string> = {
  accept: 'settings.evolution.action.accept',
  reject: 'settings.evolution.action.reject',
  delete: 'settings.evolution.action.delete',
};

/** 条目在当前状态下被禁用的原因（无禁用返回 null，值为消息 id），供批量跳过汇报使用。 */
function actionDisabledReason(status: string, action: BatchAction): string | null {
  if (action === 'delete') return null; // 删除不设状态门：任意状态可删
  const dis = getActionDisabled(status);
  if (!dis[action]) return null;
  return STATUS_META[status]?.disabledReason ?? UNKNOWN_STATUS_DISABLED_REASON;
}

/** 从当前数据现算去重选项——避免出现「选了必然 0 条」的死选项。 */
function distinctOptions(
  items: EvolutionItem[],
  pick: (item: EvolutionItem) => string,
  label?: (value: string) => string,
) {
  const seen = new Set<string>();
  const out: { value: string; label: string }[] = [];
  for (const item of items) {
    const value = pick(item);
    if (!value || seen.has(value)) continue;
    seen.add(value);
    out.push({ value, label: label ? label(value) : value });
  }
  return out;
}

// ── 弹窗形态（对齐 SPEC 列表页「文档」按钮）──────────────────────────
//
// 「查看分析结论」「查看 SPEC 草稿」合并为单一「查看」入口：条目无草稿时只
// 展示分析结论（不渲染页签），有草稿时分析结论作第一个页签、其后接草稿文档。
// 形态与 projects 列表页的「文档」弹窗一致：复用 SpecDocModal 导出的
// markdownComponents 与 useMaximizeModal，加载中 / 失败可重试 / 空 / 正文
// 四态同构。底部另有「同意 / 拒绝 / 删除」操作区，可直接在弹窗内决策。

// 整窗几何：标题栏 + 底部操作区 + 弹窗容器内边距三项合计（antd v6 实测，
// 720px 视口下 116px）不参与正文高度。还原态正文 = 整窗 85vh − 116px；
// 最大化态由共享 hook 按 calc(100vh − 80px − footerHeight) 算，故 footerHeight
// 取 116 − 80 = 36，让两态扣掉的是同一份非正文高度。
const MODAL_CHROME_HEIGHT = 116;
const MODAL_FOOTER_HEIGHT = MODAL_CHROME_HEIGHT - 80;

const DOC_MODAL_OPTIONS = {
  defaultWidth: '80%',
  defaultBodyHeight: `calc(85vh - ${MODAL_CHROME_HEIGHT}px)`,
  extraBodyStyle: { display: 'flex', flexDirection: 'column', overflow: 'hidden' },
  centered: true,
  footerHeight: MODAL_FOOTER_HEIGHT,
} as const;

/** 「查看」弹窗的页签键：analysis = 分析结论，其余为草稿文档。 */
type ViewTab = 'analysis' | EvolutionDoc;

/**
 * 草稿文档页签文案——按文件与 SPEC 详情页「文档」弹窗（SpecDocModal）逐一对齐，
 * 保证同一份文档在两处叫同一个名字：
 * proposal.md → 需求背景 / design.md → 详细设计 / tasks.md → 任务清单 /
 * specs/<capability>/spec.md → 测试场景清单（草稿无验证报告，故无该页签）。
 */
const EVOLUTION_DOC_LABELS: Record<EvolutionDoc, string> = {
  proposal: 'settings.evolution.tab.proposal',
  design: 'settings.evolution.tab.design',
  tasks: 'settings.evolution.tab.tasks',
  spec: 'settings.evolution.tab.spec',
};

/** 有草稿时「查看」弹窗的第一个页签文案（消息 id）。 */
const ANALYSIS_TAB_LABEL = 'settings.evolution.tab.analysis';

/** Markdown 四态正文：加载中 / 失败可重试 / 空 / 正文（两处弹窗共用）。 */
function MarkdownBody({
  loading,
  error,
  emptyText,
  content,
  onRetry,
}: {
  loading: boolean;
  error: string | null;
  emptyText: string;
  content: string;
  onRetry?: () => void;
}) {
  const intl = useIntl();
  if (loading) {
    return (
      <div style={{ textAlign: 'center', padding: 32 }}>
        <Spin />
      </div>
    );
  }
  if (error) {
    return (
      <Alert
        type="error"
        message={intl.formatMessage({ id: 'settings.evolution.loadFailed' })}
        description={
          <>
            <div>{error}</div>
            {onRetry && (
              <Button type="link" style={{ padding: 0 }} onClick={onRetry}>
                {intl.formatMessage({ id: 'settings.evolution.clickRetry' })}
              </Button>
            )}
          </>
        }
      />
    );
  }
  if (!content) {
    return <Empty description={emptyText} />;
  }
  return (
    <div style={{ height: '100%', overflow: 'auto', fontSize: 13, lineHeight: 1.65 }}>
      <Markdown remarkPlugins={[remarkGfm]} components={markdownComponents}>
        {content}
      </Markdown>
    </div>
  );
}

// ── 配置（7.2）──────────────────────────────────────────────────────

interface SuggestedImprovementsPanelProps {
  config: ConfigData;
  scope: 'user' | 'project';
  project?: string;
}

const DEFAULT_AUTO_ACCEPT = false;
const DEFAULT_MAX_ITEMS = 20;
const MAX_ITEMS_UPPER = 200;
/** 「在指定时间执行」刚被选中、还没挑时刻时的预填值（用户可改）。 */
const DEFAULT_SPEC_RUN_AT = '02:00';

// accept 轮询对非 404 错误的容错次数（code-review item 0c6d650a2768）：连续
// N 次查询失败才按失败收敛——单次瞬时错误（frp 隧道抖动、瞬时 5xx、网络
// 超时）期间后端任务可能仍在执行并最终成功，立即判失败会把可能已成功的
// 条目计入失败清单并引导重复 accept；404（任务记录确定性不存在，重试同样
// 必失败）不在此列，立即收敛。
const ACCEPT_POLL_ERROR_TOLERANCE = 3;

// 错误消息收窄（code-review item d0500faecda8）：catch (e: any) 违反 TS any
// 规则且在 loadItems/execOne/loadView/handleClearAllTodo 重复——统一改为
// unknown 捕获 + 本助手收窄。语义与旧 `e?.message || fallback` 完全一致：
// 携带 string message 的对象取 message，其余（含 thrown 标量/undefined）
// 回落占位文案。
const errText = (e: unknown, fallback: string): string => {
  const msg = (e as { message?: unknown } | null | undefined)?.message;
  return typeof msg === 'string' && msg ? msg : fallback;
};

// ── 评估结论摘要（7.3）──────────────────────────────────────────────

// 结论三态 → 中文映射（code-review item 6ac78de43384：旧实现嵌套三元链，
// 项目前端规则禁止；未登记值按否定态兜底）。
const VERDICT_PROBLEM_LABELS: Record<string, string> = {
  yes: 'settings.evolution.verdict.problemYes',
  partial: 'settings.evolution.verdict.problemPartial',
};
const VERDICT_SUGGESTION_LABELS: Record<string, string> = {
  yes: 'settings.evolution.verdict.suggestionYes',
  partial: 'settings.evolution.verdict.suggestionPartial',
};

function verdictSummary(item: EvolutionItem, formatMessage: (id: string, values?: Record<string, string | number>) => string): string {
  const v = item.verdict;
  if (!v) return '';
  const parts: string[] = [];
  if (v.problem_exists) {
    parts.push(formatMessage('settings.evolution.verdict.problem', {
      label: VERDICT_PROBLEM_LABELS[v.problem_exists]
        ? formatMessage(VERDICT_PROBLEM_LABELS[v.problem_exists])
        : formatMessage('settings.evolution.verdict.problemNo'),
    }));
  }
  if (v.suggestion_sound) {
    parts.push(formatMessage('settings.evolution.verdict.suggestion', {
      label: VERDICT_SUGGESTION_LABELS[v.suggestion_sound]
        ? formatMessage(VERDICT_SUGGESTION_LABELS[v.suggestion_sound])
        : formatMessage('settings.evolution.verdict.suggestionNo'),
    }));
  }
  parts.push(formatMessage(v.worth_spec ? 'settings.evolution.verdict.worthYes' : 'settings.evolution.verdict.worthNo'));
  return parts.join(' / ');
}

// ── 禁用规则（7.4）────────────────────────────────────────────────

const ACTIONS = [
  { key: 'view', label: 'settings.evolution.action.view' },
  { key: 'accept', label: 'settings.evolution.action.accept' },
  { key: 'reject', label: 'settings.evolution.action.reject', danger: true },
  { key: 'delete', label: 'settings.evolution.action.delete', danger: true },
] as const;

/** 行过滤谓词单源（code-review item 7ea5eaa7b3c8）：filteredItems 与
 *  nextAfterAction 旧实现逐字重复，两拷贝漂移（date_section/缺值语义微妙）
 *  会让「下一项」跳转与表格显示不一致——抽单谓词两处复用。
 *  date_section 为 'YYYY-MM-DD'，缺值时不被日期条件排除。 */
function matchesFilter(
  item: EvolutionItem,
  filters: { status?: string; project?: string; dateRange: [Dayjs, Dayjs] | null },
): boolean {
  const start = filters.dateRange?.[0]?.format('YYYY-MM-DD');
  const end = filters.dateRange?.[1]?.format('YYYY-MM-DD');
  if (filters.status && item.status !== filters.status) return false;
  if (filters.project && item.project !== filters.project) return false;
  if (start && item.date_section && item.date_section < start) return false;
  if (end && item.date_section && item.date_section > end) return false;
  return true;
}

/** 查看弹窗空态文案（code-review item 6ac78de43384：旧实现嵌套三元链
 *  拍平为 if 链——分析结论缺失与草稿缺失是两回事）。 */
function viewEmptyTextFor(tab: ViewTab, docSource: EvolutionItem['doc_source']): string {
  if (tab === 'analysis') return 'settings.evolution.empty.analysis';
  if (docSource === 'spec') return 'settings.evolution.empty.docFromSpec';
  return 'settings.evolution.empty.draftMissing';
}

function getActionDisabled(status: string): Record<string, boolean> {
  // 「查看」不设状态门：分析结论恒可查看，有无草稿由弹窗自行分支（原「查看
  // SPEC 草稿」在 analyzed / draft_failed 下禁用，合并后该门随之取消）；
  // delete 不设状态门（任意状态可删），恒可用。
  // 「同意」「拒绝」按 STATUS_META[status].decidable 放行——fail-closed
  // （code-review item 315ccdc0f28f）：仅对登记为可决策的状态开放（pending /
  // accept_failed 全可，draft_failed 仅可拒绝），未知状态（后端新增终态而
  // 前端未同步的版本代差）默认禁用，不靠后端接口报错兜底。
  const decidable = STATUS_META[status]?.decidable;
  return {
    view: false,
    accept: !decidable?.includes('accept'),
    reject: !decidable?.includes('reject'),
    delete: false,
  };
}

// ── 组件 ─────────────────────────────────────────────────────────────

// 保存按钮已上提到自进化页签底部（全页唯一），本卡片经 ref 暴露 collect()，
// 由父页签在唯一点击事件里与「代码陈旧自愈」卡片一起校验并合并提交。
const SuggestedImprovementsPanel = forwardRef<
  SettingsSectionHandle,
  SuggestedImprovementsPanelProps
>(function SuggestedImprovementsPanel({ config, scope, project }, ref) {
  const [form] = Form.useForm();
  // 反馈提示与确认/错误弹窗经 App.useApp() 取上下文实例（code-review item
  // 5fa659aaf869）：静态 message 不经过 App/ConfigProvider 上下文（antd v5
  // 会提示 Static function can not consume context），与其余设置面板口径统一；
  // 确认弹窗的 modal 同取上下文实例（比照 SystemPanel item 6836d264fde4 /
  // QuickAssignModal item 84564e6bbdbe 口径），替换原「命令式 API 维持现状」
  const { message, modal } = App.useApp();
    // i18n（batch-S）：文案渲染期经 useIntl 求值（t 为 formatMessage 简写）
    const intl = useIntl();
    const t = useCallback(
      (id: string, values?: Record<string, string | number>) => intl.formatMessage({ id }, values),
      [intl],
    );
  // 用户编辑置脏：切页签/作用域前由 index 经 anyPanelDirty 弹丢弃确认
  // （code-review item 8a3eb01dc2b9）；项目级作用域整表 disabled 不会触发
  const { setDirty } = usePanelDirty();
  const se = config.self_evolution;
  const isUserScope = scope === 'user';

  // 配置初始值（7.2：读值取 self_evolution；保存 MUST NOT 带 project 参数）
  //
  // spec_run_at 在配置里是「null 或 HH:mm」单键，UI 上是「模式 Radio + 时刻」
  // 两个表单字段：spec_run_mode 只活在表单里，提交时折叠回单键（见 collect）。
  const initialValues = useMemo(() => ({
    auto_accept: se?.auto_accept ?? DEFAULT_AUTO_ACCEPT,
    max_items_per_run: se?.max_items_per_run ?? DEFAULT_MAX_ITEMS,
    spec_run_mode: se?.spec_run_at ? 'scheduled' : 'immediate',
    spec_run_at: se?.spec_run_at ?? DEFAULT_SPEC_RUN_AT,
  }), [se?.auto_accept, se?.max_items_per_run, se?.spec_run_at]);

  // [fenix-ignore:37123e376118] 回填产物是三个原始值 deps 的 useMemo 派生，config 刷新只换 self_evolution 对象身份时 deps 不变、不触发 setFieldsValue，与 LlmProviderPanel 的「内容变化才回填」门控语义等价（那边回填载荷含对象/数组才需 stringify 比较）。
  useEffect(() => {
    form.setFieldsValue(initialValues);
  }, [initialValues, form]);

  // 表单内选的执行模式：决定 TimePicker 是否显示
  const specRunMode = Form.useWatch('spec_run_mode', form);

  useImperativeHandle(
    ref,
    () => ({
      collect: async () => {
        // 项目级作用域下三键为只读全局键：不收集（父页签仅提交陈旧自愈节）
        if (!isUserScope) return {};
        try {
          const values = await form.validateFields();
          return {
            self_evolution: {
              auto_accept: values.auto_accept,
              max_items_per_run: values.max_items_per_run,
              // 模式折叠回单键：选「立即」写 null（显式关掉定时，不能省略键，
              // 否则合并白名单会保留旧时刻）
              spec_run_at: values.spec_run_mode === 'scheduled'
                ? (values.spec_run_at || DEFAULT_SPEC_RUN_AT)
                : null,
            },
          };
        } catch {
          // antd 表单校验失败已在表单内渲染
          return null;
        }
      },
    }),
    [form, isUserScope],
  );

  // ── 表格数据（7.3）──────────────────────────────────────────────

  const [items, setItems] = useState<EvolutionItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const mountedRef = useRef(true);
  // items 归属标记（code-review item 22ce653d70d5）：切换作用域后新请求返回前，
  // items 仍持有上一作用域的数据，复位 effect 与缺省过滤 effect 在同一轮提交内
  // 先后执行，旧数据非空即把一次性门置 true 并按旧条目落定 filterStatus——
  // 新数据到达后门已闭不再重推，新作用域会恒带着按旧数据算出的过滤。回填时
  // 记录归属键，落默认前先核对归属，归属不匹配（旧作用域数据）不落定。
  const itemsScopeRef = useRef('');

  // 过期响应守卫（code-review item 3383961be73c）：作用域/项目切换走的是同一
  // 组件实例的 effect 重跑，cleanup 后 mountedRef 复回 true，仅凭 mountedRef
  // 判活挡不住「旧作用域请求后到」——旧项目条目会短暂写进新作用域视图（比照
  // loadView 的 viewReqSeqRef 口径）。每次发起自增请求序号，响应时序号已落后
  // 即整体丢弃（不写 items/itemsScopeRef/loading）。
  const itemsReqSeqRef = useRef(0);

  // project prop 的镜像（比照 ProjectProfilePanel 916d9186a619 / QualityPanel
  // e884e5a8a3af 的 projectRef 币值对账口径；写 ref 落在 effect 内、渲染保持
  // 纯净）：单条同意是异步+轮询的长请求，动作收尾的 loadItems 以点击时刻闭包
  // 的旧 project 发起，且发起时机晚于新作用域的 effect 重载——彼时请求序号
  // 反而最新，仅 reqSeq 判等挡不住，写入点须再对数据归属作用域判等
  // （code-review item 2e98a9d2c804）。
  const projectRef = useRef(project);
  useEffect(() => {
    projectRef.current = project;
  }, [project]);

  // 返回本次加载到的条目数组：动作成功后的「转到下一条」要在刷新后的数据里按
  // id 找回目标——旧 items 里目标仍带着动作前的状态，直接复用会渲染出陈旧禁用态。
  const loadItems = useCallback(async (): Promise<EvolutionItem[]> => {
    const reqSeq = ++itemsReqSeqRef.current;
    // unmount 守卫（code-review item 001e54a6465c）：批量/单条动作的 onOk 在多段
    // await 之后才调用本函数，期间面板可能已卸载（切走页签），入口 setState 不得
    // 打到已卸载实例——与下方响应写入点的 mountedRef 口径一致
    if (mountedRef.current) {
      setLoading(true);
      setError(null);
    }
    try {
      const next = (await getEvolutionItems(project)).items || [];
      // 序号落后 = 已有更新的请求（新作用域）接管列表，本响应过期整体丢弃；
      // 序号最新仍须作用域币值对账（code-review item 2e98a9d2c804）：动作收尾
      // 的本次调用发起于新作用域 effect 重载之后、序号反而最新，数据归属作用域
      // 与镜像不符即整体丢弃（不写 items/itemsScopeRef），并按空清单返回让
      // 动作收尾按「无下一条」收敛，不把旧作用域条目喂给弹窗翻页
      if (mountedRef.current && reqSeq === itemsReqSeqRef.current) {
        if (projectRef.current !== project) return [];
        // 回填时记录数据归属的作用域键（code-review item 22ce653d70d5）：
        // 供缺省过滤落定前核对归属，见下方 itemsScopeRef 注释
        itemsScopeRef.current = project ?? '';
        setItems(next);
      }
      return next;
    } catch (e) {
      // 作用域不符的失败响应同样整体丢弃（code-review item 2e98a9d2c804）：
      // 旧作用域的失败提示与「跨作用域残留清空」都不得落到新作用域视图上
      if (
        mountedRef.current
        && projectRef.current === project
        && reqSeq === itemsReqSeqRef.current
      ) {
        const msg = errText(e, t('settings.evolution.loadFailed'));
        setError(msg);
        // 刷新失败不清空已有列表（code-review item e735721e599d）：单条动作成功
        // 后的刷新、切页签回来等场景一次瞬时失败不应清掉用户正在浏览（可能已
        // 筛选、已勾选）的条目，只置错误提示（表格上方附「重试」按钮）。清空
        // 降级仅限当前没有本作用域数据时——itemsScopeRef 只在成功回填时记录
        // 归属键，与之不符说明是首次加载失败或跨作用域残留，仍整体清空。
        if (itemsScopeRef.current !== (project ?? '')) setItems([]);
      }
      return [];
    } finally {
      // 过期请求不复位 loading：新请求仍在飞，由它自己的 finally 收口。
      // 作用域不符的丢弃响应（2e98a9d2c804）仍按序号最新复位 loading：
      // loading 是请求槽位状态而非作用域数据，此时已无更新的在飞请求，
      // 不复位会让表格转圈卡死
      if (mountedRef.current && reqSeq === itemsReqSeqRef.current) setLoading(false);
    }
  }, [project, intl]);

  useEffect(() => {
    mountedRef.current = true;
    loadItems();
    return () => { mountedRef.current = false; };
  }, [loadItems]);

  // ── 过滤（纯前端：选区项全部已在内存，不重复打接口）────────────────
  //
  // 两个下拉的选项从当前数据现算 distinct 值，避免出现「选了必然 0 条」的死选项；
  // 日期按 date_section（todo.md 小节日期，ISO 串，字典序即时间序）做闭区间。
  // 缺省视图见下方导数规则：存在待决策条目则聚焦待决策，否则不做任何过滤。

  const [filterStatus, setFilterStatus] = useState<string | undefined>();
  const [filterProject, setFilterProject] = useState<string | undefined>();
  const [filterDateRange, setFilterDateRange] = useState<[Dayjs, Dayjs] | null>(null);

  // 缺省状态下拉只在首个非空数据集落定一次（code-review item b53ce5d316fb）：
  // 旧实现在每次 items 身份变化（accept/reject/delete 后 loadItems）都重推
  // 默认过滤，用户刻意选的过滤（如状态=已拒绝）被静默替换回 pending，与
  // 「保留用户选择」意图相悖。加 hasAppliedDefaultFilter 一次性门控后，
  // 缺省过滤只在初始加载应用，之后由用户全权掌管（resetFilters 可显式复位）。
  const hasAppliedDefaultFilter = useRef(false);
  useEffect(() => {
    // scope/project 变化而组件被复用时重置一次性门，让新作用域重新落默认
    hasAppliedDefaultFilter.current = false;
    // 项目/日期过滤同轮复位（code-review item 13a40d66481c）：filterProject
    // 残留旧作用域值时 matchesFilter 会把新作用域条目整体排除（表格假空态）；
    // filterStatus 不在此复位——由缺省过滤 effect 随新作用域数据重新落定
    setFilterProject(undefined);
    setFilterDateRange(null);
  }, [scope, project]);
  useEffect(() => {
    if (hasAppliedDefaultFilter.current) return;
    if (items.length === 0) return; // 空数据（加载中/无数据）不落默认
    // 归属核对：items 还是上一作用域回填的旧数据（本作用域请求未返回）时不落定
    if (itemsScopeRef.current !== (project ?? '')) return;
    hasAppliedDefaultFilter.current = true;
    setFilterStatus(items.some((i) => i.status === 'pending') ? 'pending' : undefined);
  }, [items, project]);

  const projectOptions = useMemo(() => distinctOptions(items, (i) => i.project), [items]);
  const statusOptions = useMemo(() => {
    const opts = distinctOptions(items, (i) => i.status, (s) => EVOLUTION_STATUS_LABELS[s] || s);
    // 当前选中值必须始终在选项里：否则「缺省待决策但一条待决策都没有」时，
    // antd 找不到匹配项会直接把原始值（pending）当标签渲染出来
    if (filterStatus && !opts.some((o) => o.value === filterStatus)) {
      opts.unshift({
        value: filterStatus,
        label: EVOLUTION_STATUS_LABELS[filterStatus] || filterStatus,
      });
    }
    return opts;
  }, [items, filterStatus]);

  const hasFilter = Boolean(filterStatus || filterProject || filterDateRange);

  const resetFilters = () => {
    setFilterStatus(undefined);
    setFilterProject(undefined);
    setFilterDateRange(null);
  };

  const filteredItems = useMemo(
    () =>
      items.filter((item) =>
        matchesFilter(item, {
          status: filterStatus,
          project: filterProject,
          dateRange: filterDateRange,
        }),
      ),
    [items, filterStatus, filterProject, filterDateRange],
  );

  // ── 多选与批量（7.6）────────────────────────────────────────────

  const [selectedRowKeys, setSelectedRowKeys] = useState<Key[]>([]);
  const [batchRunning, setBatchRunning] = useState(false);
  // 在飞的具体批量动作：转圈只应出现在真正执行的那个按钮上（否则执行批量拒绝
  // 时转圈的会是「批量同意」，动作错位）
  const [batchAction, setBatchAction] = useState<BatchAction | null>(null);
  // 批量执行进度（2026-11-16 用户要求界面应有处理进度显示）：done/total 计数
  // + 当前正在处理的条目标题，批量运行中在表格上方常驻展示
  const [batchProgress, setBatchProgress] = useState<{
    done: number;
    total: number;
    current: string;
  } | null>(null);
  // 「清理所有项目自省内容」：全局动作，与条目多选/批量无关，单独一个在飞标志
  const [clearingTodo, setClearingTodo] = useState(false);

  // 过滤条件变化即清空选中：否则「先全选、再改过滤」会让批量作用到看不见的行上
  useEffect(() => {
    setSelectedRowKeys([]);
  }, [filterStatus, filterProject, filterDateRange]);

  // items 刷新后修剪选中键（code-review item 2c1de18c3a8c）：单条动作（查看
  // 弹窗底部 / 操作列菜单）成功后只 loadItems 不清选中，被删条目的 id 会残留在
  // selectedRowKeys 里——标题行「已选 N 条」按 length 统计会把已不存在的行也
  // 计入，与表格实际勾选数不一致。无键消失时原样返回原数组，不触发多余重渲染。
  useEffect(() => {
    setSelectedRowKeys((keys) => {
      const kept = keys.filter((k) => items.some((i) => i.id === k));
      return kept.length === keys.length ? keys : kept;
    });
  }, [items]);

  /** 异步接受 + 轮询终态（2026-11-16 批量同意超时事故）。

   * 单条 accept 慢时 >30s（copytree + git 提交 + STATE 注册 + todo 回写），
   * 同步请求会撞客户端 30s 超时 / frp 隧道 502，且「响应丢了 ≠ 失败」——
   * 后端可能已成功，旧实现把它报成失败、条目又从「待决策」视图消失，用户
   * 以为处理逻辑丢了条目。改为：POST async:true 仅入队立即返回，随后每 2s
   * 轮询 accept-status 直到 phase=done——每次 HTTP 交互都短，且必然拿到
   * 真实终态。300s 上限只是兜底：超限时后端任务仍在跑、必然落终态，文案
   * 引导用户以列表刷新为准。``retry``：draft_failed 条目原地重入（服务端
   * 锁内清失败原因置回 pending 再走接受链）。
   */
  const acceptWithPoll = async (
    itemId: string,
    startAfter?: string | null,
    retry?: boolean,
  ): Promise<{ ok: boolean; status?: string; spec_name?: string; error?: string }> => {
    try {
      await acceptEvolutionItemAsync(itemId, startAfter ?? null, retry);
    } catch (e) {
      return { ok: false, error: errText(e, t('settings.evolution.accept.submitFailed')) };
    }
    const deadline = Date.now() + 300_000;
    // 非 404 轮询错误的连续失败计数（code-review item 0c6d650a2768）：
    // 查询成功即清零，连续 ACCEPT_POLL_ERROR_TOLERANCE 次才按失败收敛
    let pollErrors = 0;
    while (Date.now() < deadline) {
      // 先睡再查：入队到后台 worker 真正起跑有间隙，入队后立刻查必是 running
      await new Promise((resolve) => setTimeout(resolve, 2000));
      // 卸载即停轮（code-review item dcc24afb86a4）：本面板按页签条件渲染，
      // 用户在轮询期间切走页签即卸载，继续按 2s 间隔空转到 300s 上限只是无谓
      // 的后端压力与网络占用（同文件 loadItems 入口/写入点的 mountedRef 口径）。
      // 与超时分支同形收敛（任务仍在服务端执行，返回后刷新列表见真章）；
      // 调用链收尾的 setState 已有 mountedRef 守卫兜底，提前返回不改变其口径。
      // 作用域切换不卸载实例（cleanup 后复回 true，且 cleanup 与重挂同步相邻
      // 执行），不会在此误停
      if (!mountedRef.current) {
        return {
          ok: false,
          error: t('settings.evolution.accept.leftPanel'),
        };
      }
      let job: EvolutionAcceptJobStatus;
      try {
        job = await getEvolutionAcceptStatus(itemId);
        pollErrors = 0;
      } catch (e) {
        // 404（服务重启丢任务表）= 任务记录确定性不存在，重试同样必失败，
        // 立即按失败收敛、不死轮询；其余错误（frp 隧道抖动、瞬时 5xx/网络
        // 超时）可能只是瞬时的——后端任务可能仍在执行并最终成功，单次即判
        // 失败会让前端把可能已成功的条目计入失败清单并引导重复 accept。
        // 给有限容错：连续 ACCEPT_POLL_ERROR_TOLERANCE 次失败才收敛，
        // 期间继续轮询（300s 兜底上限不变）。
        if (e instanceof ApiError && e.status === 404) {
          return { ok: false, error: errText(e, t('settings.evolution.accept.pollFailed')) };
        }
        pollErrors += 1;
        if (pollErrors >= ACCEPT_POLL_ERROR_TOLERANCE) {
          return { ok: false, error: errText(e, t('settings.evolution.accept.pollFailed')) };
        }
        continue;
      }
      if (job.phase === 'done') {
        const r = job.result || {};
        return { ok: Boolean(r.ok), status: r.status, spec_name: r.spec_name, error: r.error };
      }
    }
    return {
      ok: false,
      error: t('settings.evolution.accept.timeout'),
    };
  };

  /** 执行一条 accept/reject/delete，异常收敛为失败结果（单条菜单与批量共用）。

   * ``startAfter`` 仅在 action='accept' 时有意义：新 SPEC 的定时拾取时刻
   * （UTC ISO），null = 立即执行。accept 走异步+轮询（acceptWithPoll），
   * 拒绝/删除为轻量同步接口、无超时风险，维持原路径。 */
  const execOne = async (
    item: EvolutionItem,
    action: BatchAction,
    startAfter?: string | null,
    retry?: boolean,
  ): Promise<{ ok: boolean; status?: string; spec_name?: string; error?: string }> => {
    try {
      if (action === 'accept') return await acceptWithPoll(item.id, startAfter ?? null, retry);
      if (action === 'reject') return await rejectEvolutionItem(item.id);
      return await deleteEvolutionItem(item.id);
    } catch (e) {
      return { ok: false, error: errText(e, t('settings.evolution.execFailed')) };
    }
  };

  /** 本作用域配置下的默认执行时刻（UTC ISO；null = 立即执行）。 */
  const configStartAfter = () => nextRunAtISO(se?.spec_run_at);

  // ── 查看（7.5，单弹窗：分析结论 + 草稿文档页签）──────────────────
  //
  // 页面加载时带下来的 item.has_draft（后端按草稿目录是否存在现算）决定形态：
  // 无草稿（不需要立项 / 草稿生成失败 / 已决策且草稿已清）→ 不渲染页签，只展示
  // 分析结论；有草稿 → 分析结论作首个页签，其后接草稿四文档。
  // 分析结论与草稿共用一份加载态：任一时刻只有一个页签可见，切换页签即重载。

  const [viewVisible, setViewVisible] = useState(false);
  const [viewItem, setViewItem] = useState<EvolutionItem | null>(null);
  const [viewTab, setViewTab] = useState<ViewTab>('analysis');
  const [viewContent, setViewContent] = useState('');
  const [viewLoading, setViewLoading] = useState(false);
  const [viewError, setViewError] = useState<string | null>(null);
  // （code-review item 758f448e9b38：原 viewFound state 三处写入但渲染树从不
  // 读取——空/缺失态实际由 viewContent+viewEmptyText 推导，死 state 每次切
  // tab 多一次渲染，已删。）

  // 页签渲染条件（合并 evo-item-retention-doc-tracking 3.3 的数据驱动语义）：
  // 草稿目录在（has_draft）或草稿已删但可从 SPEC 位置读回（doc_source 非 null）时，
  // 均渲染草稿文档页签；两者皆无（analyzed / 无 spec_name 的已拒绝等）只留分析结论。
  const hasDoc = Boolean(viewItem?.has_draft)
    || (viewItem?.doc_source !== null && viewItem?.doc_source !== undefined);

  // 过期响应守卫（code-review item 8a59ec4e6c54）：viewItem/viewTab 快速切换
  // 会并发多个 loadView，仅 mountedRef 判活挡不住「较早发起的请求最后返回」——
  // 旧页签内容会写进 viewContent 而页签已停在别处。每次发起自增请求序号，
  // 响应时序号已落后即整体丢弃（不写 viewContent/viewError/viewLoading）。
  const viewReqSeqRef = useRef(0);

  const loadView = useCallback(async (item: EvolutionItem, tab: ViewTab) => {
    const reqSeq = ++viewReqSeqRef.current;
    // unmount 守卫（code-review item 9c6bc5add459）：与 loadItems 入口同款口径
    // ——同为「加载即写 state」的函数，入口 setState 统一挂 mountedRef 守卫，
    // 消除两函数防御粒度差
    if (mountedRef.current) {
      setViewLoading(true);
      setViewError(null);
    }
    try {
      const data = tab === 'analysis'
        ? await getEvolutionAnalysis(item.id)
        : await getEvolutionDraft(item.id, tab);
      // 序号落后 = 已有更新的请求接管视图，本响应过期丢弃
      if (!mountedRef.current || reqSeq !== viewReqSeqRef.current) return;
      if (!data.found) {
        setViewContent('');
      } else {
        setViewContent(data.content || t('settings.evolution.emptyContent'));
      }
    } catch (e) {
      if (mountedRef.current && reqSeq === viewReqSeqRef.current) setViewError(errText(e, t('settings.evolution.loadFailed')));
    } finally {
      // 过期请求不复位 loading：新请求仍在飞，由它自己的 finally 收口
      if (mountedRef.current && reqSeq === viewReqSeqRef.current) setViewLoading(false);
    }
  }, [intl]);

  const openView = (item: EvolutionItem) => {
    setViewVisible(true);
    setViewItem(item);
    setViewTab('analysis'); // 恒定落在分析结论页
  };

  useEffect(() => {
    if (viewVisible && viewItem) loadView(viewItem, viewTab);
  }, [viewVisible, viewItem, viewTab, loadView]);

  // 空态文案随页签而变：分析结论缺失与草稿缺失是两回事
  const viewEmptyText = viewEmptyTextFor(viewTab, viewItem?.doc_source);

  // ── 接受 / 拒绝（7.5 二次确认）──────────────────────────────────
  //
  // 成功回调走 nextAfterAction（有下一条则转过去、否则关窗），失败时不调：
  // message 报错后让 onOk 正常返回、弹窗随即关闭（code-review item
  // b150b78eb115——旧实现 return Promise.reject 维持开窗，antd ActionButton
  // 会把该 rejection 再向外抛出，落成 console 的「Uncaught (in promise)」，
  // 违反同族面板 no_console_error 口径；关窗丢的只是窗内执行时间选择，
  // 重开按配置预填重选，查看弹窗仍停在原条目可一键重试）。操作列菜单不传回调。

  const handleAccept = (item: EvolutionItem, onDone?: () => void) => {
    // 本次执行时刻按配置预填（spec_run_at 为空 = 立即），弹窗里可临时改
    const holder: AcceptSchedule = { startAfter: configStartAfter() };
    modal.confirm({
      title: t('settings.evolution.accept.title'),
      width: 640,
      content: (
        <>
          <div style={{ marginBottom: 12 }}>{t('settings.evolution.accept.confirm', { title: item.title })}</div>
          <ScheduleFields holder={holder} initial={holder.startAfter} />
        </>
      ),
      okText: t('settings.evolution.action.accept'),
      cancelText: t('common.cancel'),
      onOk: async () => {
        // 哨兵 manual 不参与时刻校验（见 D11）；仅 ISO 定时需晚于当前时刻
        if (!isStartAfterValid(holder.startAfter)) {
          message.error(t('settings.evolution.accept.invalidTime'));
          // 校验失败同样关窗（见小节头注释）：重开时按配置预填重选
          return;
        }
        const result = await execOne(item, 'accept', holder.startAfter);
        if (result.ok) {
          message.success(
            t('settings.evolution.accept.success', {
              name: result.spec_name || item.title,
              suffix: describeStartAfter(holder.startAfter),
            }),
          );
        } else {
          message.error(result.error || t('settings.evolution.accept.failed'));
          // 失败即关窗（见小节头注释），错误文案经 message 呈现
          return;
        }
        const next = await loadItems();
        // 此处 result.ok 恒真（非 ok 已在上方提前返回）
        nextAfterAction(next, item, onDone);
      },
    });
  };

  const handleReject = (item: EvolutionItem, onDone?: () => void) => {
    modal.confirm({
      title: t('settings.evolution.action.reject'),
      content: t('settings.evolution.reject.confirm', { title: item.title }),
      okText: t('settings.evolution.action.reject'),
      cancelText: t('common.cancel'),
      okButtonProps: { danger: true },
      onOk: async () => {
        const result = await execOne(item, 'reject');
        if (result.ok) {
          message.success(t('settings.evolution.reject.done'));
        } else {
          message.error(result.error || t('settings.evolution.reject.failed'));
          // 失败即关窗（见小节头注释），错误文案经 message 呈现
          return;
        }
        const next = await loadItems();
        // 此处 result.ok 恒真（非 ok 已在上方提前返回）
        nextAfterAction(next, item, onDone);
      },
    });
  };

  // ── 删除（7.7）─────────────────────────────────────────────────
  //
  // 硬删：记录移出 items.jsonl、草稿目录一并清理，不写墓碑。todo.md 里该条记录
  // 仍在，下一轮分析 run 可能把它重新入库——确认弹窗须向用户明示。

  const handleDelete = (item: EvolutionItem, onDone?: () => void) => {
    modal.confirm({
      title: t('settings.evolution.delete.title'),
      content: (
        <>
          <div>{t('settings.evolution.delete.confirm', { title: item.title })}</div>
          <Text type="secondary">
            {t('settings.evolution.delete.todoRemains')}
          </Text>
        </>
      ),
      okText: t('settings.evolution.action.delete'),
      cancelText: t('common.cancel'),
      okButtonProps: { danger: true },
      onOk: async () => {
        const result = await execOne(item, 'delete');
        if (result.ok) {
          message.success(t('settings.evolution.delete.done'));
        } else {
          message.error(result.error || t('settings.evolution.delete.failed'));
          // 失败即关窗（见小节头注释），错误文案经 message 呈现
          return;
        }
        const next = await loadItems();
        // 此处 result.ok 恒真（非 ok 已在上方提前返回）
        nextAfterAction(next, item, onDone);
      },
    });
  };

  // ── 批量同意 / 拒绝 / 删除（7.6）────────────────────────────────
  //
  // 后端只有逐条接口，批量在前端串行执行：并发写 items.jsonl 与逐条 git commit
  // 会互相冲突，故刻意不用 Promise.all。状态不允许操作的条目先在前端筛掉
  // （删除不设状态门，故删除路径恒无跳过项），确认弹窗预告「将处理 N 条 /
  // 跳过 M 条（按原因分组）」，执行后按成功/跳过/失败三类汇报，失败明细另用
  // Modal 列出并附「重试失败项」按钮。
  //
  // 2026-11-16 超时事故改造：accept 单条改异步+轮询（execOne→acceptWithPoll，
  // 详见其注释）；批量执行段抽出 executeBatch（失败清单重跑与勾选解耦）；
  // 执行中在表格上方常驻进度条（done/total + 当前条目）。

  /** 批量执行核心：对给定条目清单串行执行动作并汇总汇报。

   * 与 runBatch 的选择读取/预筛/确认弹窗解耦——失败明细「重试失败项」重跑的
   * 是失败清单本身（此时条目可能是 draft_failed 等被预筛拦下的状态，重试
   * 语义必须绕过预筛直接执行，accept 附 retry 标记走服务端原地重入）。 */
  const executeBatch = async (
    action: BatchAction,
    runnable: EvolutionItem[],
    opts?: { skippedCount?: number },
  ): Promise<void> => {
    const skippedCount = opts?.skippedCount ?? 0;
    // unmount 守卫（code-review item 0af3924642db）：确认弹窗由 antd 静态
    // 方法挂在 body 门户，弹窗停留期间面板可能已卸载，此时仍可点「确定」，
    // 入口 setState 不得打到已卸载实例——与下方 finally 收口及 loadItems/
    // loadView 的 mountedRef 口径一致
    if (mountedRef.current) {
      setBatchAction(action);
      setBatchRunning(true);
      setBatchProgress({ done: 0, total: runnable.length, current: runnable[0]?.title || '' });
    }
    let succeeded = 0;
    // 携带 item.id 作 key（code-review item 4d4f1e78b97b）：不同项目条目的
    // title 可能相同，以 title 作 React key 会冲突导致明细错位
    const failures: { id: string; title: string; error: string }[] = [];
    try {
      // 串行：后端写 items.jsonl 用文件锁、接受路径还逐条 git commit
      for (let idx = 0; idx < runnable.length; idx++) {
        const item = runnable[idx];
        if (mountedRef.current) {
          setBatchProgress({ done: idx, total: runnable.length, current: item.title });
        }
        // 执行时刻逐条现算（code-review item 3535e67816d4：确认弹窗停留跨过
        // 配置时刻后预填值已成过去时刻，现算顺延到下一个周期；item
        // 83d8c3332b16：批量串行且单条 accept 轮询最长 300 秒，整批只算一次
        // 会让长批量尾段提交的 start_after 落进过去时刻，故下沉到每条执行前
        // 取新鲜值，与单条路径 handleAccept 的每次点击现算同语义）
        const result = await execOne(
          item,
          action,
          action === 'accept' ? configStartAfter() : null,
          action === 'accept',
        );
        if (result.ok) {
          succeeded += 1;
        } else {
          failures.push({ id: item.id, title: item.title, error: result.error || t('settings.evolution.batch.failedShort') });
        }
        if (mountedRef.current) {
          setBatchProgress({ done: idx + 1, total: runnable.length, current: item.title });
        }
      }
    } finally {
      // unmount 守卫（code-review item ab67eda51983）：批量运行中用户导航
      // 离开（面板卸载）时，多 await 之后的 state 更新不得打到已卸载组件
      // ——与 loadItems/loadView 的 mountedRef 口径一致。
      if (mountedRef.current) {
        setBatchRunning(false);
        setBatchAction(null);
        setBatchProgress(null);
      }
    }
    if (mountedRef.current) setSelectedRowKeys([]);
    await loadItems();

    const parts = [t('settings.evolution.batch.succeeded', { count: succeeded })];
    if (skippedCount > 0) parts.push(t('settings.evolution.batch.skipped', { count: skippedCount }));
    if (failures.length > 0) parts.push(t('settings.evolution.batch.failed', { count: failures.length }));
    // 连接标点随语言包（code-review item 67f425056fe5）：不在组件里硬编码
    // 语言相关标点，避免英文界面渲染出「3 succeeded，1 skipped」式中英混排
    const summary = parts.join(t('settings.evolution.summarySep'));
    // unmount 守卫（沿用 ab67eda51983 口径）：批量串行执行含后端文件锁与
    // 逐条 git commit，用户中途导航离开后收尾提示不得打到已卸载实例
    if (mountedRef.current) {
      if (failures.length > 0) {
        message.warning(summary);
        const failedIds = new Set(failures.map((f) => f.id));
        const failedItems = runnable.filter((i) => failedIds.has(i.id));
        modal.error({
          title: t('settings.evolution.batch.failTitle'),
          width: 560,
          okText: t('settings.evolution.batch.retryFailed', { count: failures.length }),
          cancelText: t('common.close'),
          // onOk 返回 Promise：antd 保持弹窗开启直到重试跑完（进度条在表格
          // 上方同步展示）；重试仅 accept 带 retry 标记（draft_failed 原地
          // 重入），reject/delete 失败重跑同一路径
          onOk: () => executeBatch(action, failedItems),
          content: (
            <ul style={{ paddingLeft: 18, marginBottom: 0 }}>
              {failures.map((f) => (
                <li key={f.id}>
                  <Text>{f.title}</Text>
                  <Text type="secondary"> — {f.error}</Text>
                </li>
              ))}
            </ul>
          ),
        });
      } else {
        message.success(summary);
      }
    }
  };

  const runBatch = (action: BatchAction) => {
    const targets = filteredItems.filter((i) => selectedRowKeys.includes(i.id));
    if (targets.length === 0) return;

    const runnable: EvolutionItem[] = [];
    const skipReasons = new Map<string, number>();
    for (const item of targets) {
      const reason = actionDisabledReason(item.status, action);
      if (reason) {
        skipReasons.set(reason, (skipReasons.get(reason) || 0) + 1);
      } else {
        runnable.push(item);
      }
    }
    const skippedCount = targets.length - runnable.length;

    if (runnable.length === 0) {
      message.warning(t('settings.evolution.batch.allSkipped'));
      return;
    }

    const verb = BATCH_VERB[action];
    const isDestructive = action !== 'accept';
    // 批量同意无逐条弹窗，执行时刻直接取配置（spec_run_at），并在确认弹窗里
    // 明示——否则「配了定时却被批量绕开」会让人以为设置没生效。
    // 预览值在开窗时定格；实际提交值在 onOk 现算（code-review item
    // 3535e67816d4）：弹窗停留跨过配置时刻后预填值已成过去时刻，现算顺延到
    // 下一个周期，避免把过去时刻提交为 start_after。
    const batchStartAfterPreview = action === 'accept' ? configStartAfter() : null;
    modal.confirm({
      title: t('settings.evolution.batch.title', { action: t(verb) }),
      content: (
        <>
          <div>
            {skippedCount > 0
              ? t('settings.evolution.batch.willRunSkipped', { count: runnable.length, action: t(verb), skipped: skippedCount })
              : t('settings.evolution.batch.willRun', { count: runnable.length, action: t(verb) })}
          </div>
          {skippedCount > 0 && (
            <Text type="secondary">
              {t('settings.evolution.batch.skipReasons')}
              {[...skipReasons.entries()].map(([r, n]) => t('settings.evolution.batch.skipCount', { reason: t(r), count: n })).join('、')}
            </Text>
          )}
          {action === 'accept' && (
            <div style={{ marginTop: 8 }}>
              <Text type="secondary">
                {t('settings.evolution.batch.runAt')}
                {batchStartAfterPreview
                  ? t('settings.evolution.batch.runAtScheduled', { time: dayjs(batchStartAfterPreview).format('YYYY-MM-DD HH:mm') })
                  : t('components.scheduleFields.optionImmediate')}
              </Text>
            </div>
          )}
          {action === 'delete' && (
            <div style={{ marginTop: 8 }}>
              <Text type="secondary">
                {t('settings.evolution.batch.deleteNote')}
              </Text>
            </div>
          )}
        </>
      ),
      okText: t(verb),
      cancelText: t('common.cancel'),
      okButtonProps: isDestructive ? { danger: true } : undefined,
      onOk: async () => {
        // 执行段收敛到 executeBatch（失败清单重跑复用同一段代码；执行时刻
        // 在其内部现算，见 code-review item 3535e67816d4 注释）
        await executeBatch(action, runnable, { skippedCount });
      },
    });
  };

  // ── 操作菜单（7.4：Dropdown + MoreOutlined + Button type="link"）────────

  const menuItems = (item: EvolutionItem): MenuProps['items'] => {
    const dis = getActionDisabled(item.status);
    // 批量在飞时整组菜单项一并禁用（code-review item 10ff05c46ff6）：单条
    // 决策不得与批量串行写并发，否则逐条完成后的 loadItems 会自增请求序号，
    // 把批量收尾的刷新当过期丢弃，列表短暂滞后于批量结果汇报
    return ACTIONS.map((a) => ({
      key: a.key,
      label: t(a.label),
      disabled: dis[a.key] || batchRunning,
      danger: 'danger' in a ? a.danger : undefined,
      onClick: () => {
        if (a.key === 'view') openView(item);
        else if (a.key === 'accept') handleAccept(item);
        else if (a.key === 'reject') handleReject(item);
        else if (a.key === 'delete') handleDelete(item);
      },
    }));
  };

  // ── 弹窗最大化（7.5）────────────────────────────────────────────

  const {
    modalProps: viewModalProps,
    maximizeButton: viewMaximizeButton,
    isFullscreen: viewIsFullscreen,
  } = useMaximizeModal(DOC_MODAL_OPTIONS);

  // 弹窗底部操作区：与操作列菜单同源判禁用（同一条目状态），动作完成后关闭
  // 弹窗——条目已改状态，留在弹窗里看的是上一状态的禁用态与草稿页签
  const closeView = () => setViewVisible(false);
  const viewActionDisabled = getActionDisabled(viewItem?.status || '');

  // ── 弹窗内上一条 / 下一条（屏幕左右两侧，形如看图控件的翻页）──────────
  //
  // 跳转范围 = 当前表格的过滤结果 filteredItems（与表格所见同一序列），
  // 这样「筛出待决策条目 → 逐条查看决策」是一条连续动线。当前条目不在
  // 过滤结果里（理论上不会，查看入口就在表格行上）时两侧均禁用。

  const viewIndex = viewItem
    ? filteredItems.findIndex((i) => i.id === viewItem.id)
    : -1;
  const canPrev = viewIndex > 0;
  const canNext = viewIndex >= 0 && viewIndex < filteredItems.length - 1;

  // 最新视图状态 ref（code-review item 8786ca79694a）：nextAfterAction 在
  // await loadItems() 之后的决策点读取视图状态，须读最新提交值而非点击时
  // 渲染的闭包快照（期间用户可能已关窗/翻页/改过滤）；每轮提交后同步。
  const latestViewStateRef = useRef({
    viewVisible,
    viewIndex,
    viewItem,
    filterStatus,
    filterProject,
    filterDateRange,
  });
  useEffect(() => {
    latestViewStateRef.current = {
      viewVisible,
      viewIndex,
      viewItem,
      filterStatus,
      filterProject,
      filterDateRange,
    };
  });

  const goRelative = (delta: -1 | 1) => {
    if (viewIndex < 0) return;
    const target = filteredItems[viewIndex + delta];
    if (target) openView(target); // 与首次打开同构：页签回到分析结论
  };

  /** 弹窗内一次决策成功后的去向：列表还有下一条就留在弹窗里转过去，否则关窗。

   * ``items`` 是动作后刚刷新的数据——按 id 找回目标条目（而非复用旧对象），
   * 让弹窗里的按钮禁用态与草稿页签反映刷新后的真实状态。查看弹窗是受控的，
   * 换 ``viewItem`` 即可在同一扇窗里翻页，无需「先关再开」（那样会与 antd
   * 确认弹窗的关闭时机抢同一帧）。同一次动作会改掉当前条目状态，若它仍留在
   * 过滤结果里，目标仍排在自己之后：先按 id 定位当前条目、再取其后一条；
   * 当前条目已不在（状态改变被过滤掉，如「待决策」筛选下同意后的条目）时按下标
   * 兜底——下一行恰好顶到原位置上。``onDone`` 保留给动作列菜单等调用方自定义
   * 收尾（不传则关窗）。 */
  const nextAfterAction = (
    items: EvolutionItem[],
    current: EvolutionItem,
    onDone?: () => void,
  ) => {
    // 决策点重读最新视图状态（code-review item 8786ca79694a）：本函数在点击
    // 时渲染中创建，却在 await loadItems() 之后才执行——期间用户可能已关窗、
    // 翻页或改过滤，闭包捕获的 viewVisible/viewIndex/过滤值已过时，「窗内
    // 翻页 vs 关窗」决策与回退 seq[viewIndex] 可能出错。统一经 ref 取最新
    // 提交态。
    const { viewVisible: visibleNow, viewIndex: idxNow, viewItem: viewingNow,
      filterStatus: statusNow, filterProject: projectNow,
      filterDateRange: dateRangeNow } = latestViewStateRef.current;
    const seq = items.filter((item) =>
      // 过滤谓词与 filteredItems 同源（item 7ea5eaa7b3c8）：跳转序列恒与
      // 表格所见一致
      matchesFilter(item, {
        status: statusNow,
        project: projectNow,
        dateRange: dateRangeNow,
      }),
    );
    const idx = seq.findIndex((i) => i.id === current.id);
    // 当前条目仍在过滤结果里 → 取其后的那一条；已被过滤掉（状态变了，例如
    // 「待决策」筛选下同意后的条目）→ 后续条目整体前移一格，原下标处就是它的
    // 后继（也是用户眼里原来位于下方的那一行）。
    //
    // 「原下标」只在用户仍停在动作条目上时成立：在飞窗口内已翻到别的条目时
    // （viewingNow ≠ current），current 被移除会令其后继再前移一格，原下标处
    // 反而是所看条目的下一条——兜底改按最新查看条目在 seq 里的位置取后继
    // （它也被过滤冲掉时才退回 idxNow）。
    let fallbackIdx = idxNow;
    if (idx < 0 && viewingNow && viewingNow.id !== current.id) {
      const viewIdx = seq.findIndex((i) => i.id === viewingNow.id);
      if (viewIdx >= 0) fallbackIdx = viewIdx + 1;
    }
    const target = idx >= 0 ? seq[idx + 1] : seq[fallbackIdx];
    // 只有「查看」弹窗开着时才在窗内翻页——操作列菜单发起的同名动作没有
    // 弹窗可翻，保持原行为（仅刷新表格）。
    if (target && visibleNow) {
      // unmount 守卫（code-review item 0af3924642db）：本函数在决策请求 +
      // loadItems 刷新的多段 await 之后才执行，期间面板可能已卸载，state
      // 更新不得打到已卸载实例——与 loadItems/loadView 的 mountedRef 口径一致
      if (mountedRef.current) {
        setViewItem(target);
        setViewTab('analysis'); // 与首次打开同构：页签回到分析结论
      }
      return;
    }
    (onDone ?? closeView)();
  };

  // 掩码是半透明黑，按钮取同色系半透明黑底 + 白图标（antd Image 预览同款观感）
  const navButtonStyle: CSSProperties = {
    position: 'fixed',
    top: '50%',
    transform: 'translateY(-50%)',
    zIndex: 1100,
    width: 44,
    height: 44,
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
    background: 'rgba(0, 0, 0, 0.45)',
    border: 'none',
    color: '#fff',
    fontSize: 18,
  };

  // ── 表格列（7.3）──────────────────────────────────────────────────

  // 文本列 sorter 空值回退：后端 read_evolution_items 用 rec.get() 取值，
  // 键缺失时为 null（matchesFilter 对 date_section 缺值同样短路豁免）
  const columns = [
    {
      title: t('settings.evolution.col.project'), dataIndex: 'project', key: 'project', width: 100, ellipsis: true,
      sorter: (a: EvolutionItem, b: EvolutionItem) => (a.project || '').localeCompare(b.project || ''),
    },
    {
      title: t('settings.evolution.col.date'), dataIndex: 'date_section', key: 'date_section', width: 110,
      // date_section 为 'YYYY-MM-DD'，字典序即时间序
      sorter: (a: EvolutionItem, b: EvolutionItem) =>
        (a.date_section || '').localeCompare(b.date_section || ''),
    },
    {
      title: t('settings.evolution.col.section'), dataIndex: 'section', key: 'section', width: 90,
      sorter: (a: EvolutionItem, b: EvolutionItem) => (a.section || '').localeCompare(b.section || ''),
      // 参照 SPEC 列表页「模式」列：Tag 渲染 + marginInlineEnd:0 收紧列宽
      // 空值短路（code-review item 388e1808eaa7）：section 键缺失为 null 时
      // 不渲染空胶囊 Tag，与上方 sorter 的 `|| ''` 豁免口径一致
      render: (s: string) => (s ? (
        <Tag color={SECTION_TAG_COLORS[s]} style={{ marginInlineEnd: 0 }}>{s}</Tag>
      ) : null),
    },
    {
      title: t('settings.evolution.col.title'), dataIndex: 'title', key: 'title', ellipsis: true,
      // 问题列不设 width：它吃掉剩余宽度，设了 sorter 后表头才有空间放排序箭头
      sorter: (a: EvolutionItem, b: EvolutionItem) => (a.title || '').localeCompare(b.title || ''),
      // 问题标题即「查看」入口（等价操作列的 更多 → 查看）：读条目的第一动作就是
      // 点标题，不必先展开下拉。可点击样式沿用 SPEC 列表页名称列（蓝字 + pointer）
      // 形参名不可与组件内翻译简写 t 撞名（code-review item f5b3df3a5039）：
      // 同名会遮蔽 t('...')，后续在此补翻译会把标题文本当消息 id 查表
      render: (title: string, r: EvolutionItem) => (
        <span
          onClick={() => openView(r)}
          style={{ whiteSpace: 'nowrap', cursor: 'pointer', color: DSH_LINK }}
          data-testid={`evolution-item-title-${r.id}`}
        >
          {title}
        </span>
      ),
    },
    {
      title: t('settings.evolution.col.verdict'), key: 'verdict', width: 180,
      render: (_: unknown, r: EvolutionItem) => (
        <Tooltip title={r.verdict?.rationale || ''}>
          <Text type="secondary" style={{ fontSize: 12 }}>{verdictSummary(r, t)}</Text>
        </Tooltip>
      ),
    },
    {
      title: t('settings.evolution.col.status'), dataIndex: 'status', key: 'status', width: 110,
      // 语义序（待处理在前、终态在后）而非字母序；未知状态排最后
      sorter: (a: EvolutionItem, b: EvolutionItem) =>
        (STATUS_META[a.status]?.order ?? 99) - (STATUS_META[b.status]?.order ?? 99),
      render: (s: string) => (
        <Tag color={STATUS_META[s]?.color || 'default'}>{EVOLUTION_STATUS_LABELS[s] || s}</Tag>
      ),
    },
    {
      title: t('settings.evolution.col.actions'), key: 'actions', width: 80,
      fixed: 'right' as const,
      onCell: () => ({ style: { paddingInline: 0 } }),
      render: (_: unknown, record: EvolutionItem) => (
        <Dropdown
          menu={{ items: menuItems(record) }}
          placement="bottomRight"
          trigger={['click']}
        >
          <Button type="link" size="small" icon={<MoreOutlined />}>{t('common.more')}</Button>
        </Dropdown>
      ),
    },
  ];

  /** 清空所有项目的 .fenix/todo.md（全局动作，项目级作用域不可用）。 */
  const handleClearAllTodo = () => {
    modal.confirm({
      title: t('settings.evolution.clearAll.title'),
      width: 520,
      content: (
        <>
          <p style={{ marginTop: 0 }}>
            {t('settings.evolution.clearAll.p1WillClear')}
            <strong>{t('settings.evolution.clearAll.allProjects')}</strong>
            {t('settings.evolution.clearAll.p1OfWithSpace')}
            <code>.fenix/todo.md</code>
            {t('settings.evolution.clearAll.p1Tail')}
          </p>
          <p style={{ marginBottom: 0 }}>
            {t('settings.evolution.clearAll.p2Lead')}
            <strong>{t('settings.evolution.clearAll.listUnaffected')}</strong>
            {t('settings.evolution.clearAll.p2Reads')}
            <code> .fenix/evolution/items.jsonl</code>
            {t('settings.evolution.clearAll.p2Tail')}
          </p>
        </>
      ),
      okText: t('settings.evolution.clearAll.ok'),
      okButtonProps: { danger: true },
      cancelText: t('common.cancel'),
      onOk: async () => {
        // unmount 守卫：与 setBatchRunning/loadItems/loadView 的 mountedRef 口径一致。
        if (mountedRef.current) setClearingTodo(true);
        try {
          const result = await clearAllEvolutionTodo();
          const parts = [t('settings.evolution.clearAll.cleared', { count: result.cleared.length })];
          if (result.skipped.length > 0) parts.push(t('settings.evolution.clearAll.skipped', { count: result.skipped.length }));
          if (result.failed.length > 0) parts.push(t('settings.evolution.clearAll.failed', { count: result.failed.length }));
          const text = parts.join(t('settings.evolution.summarySep'));
          if (result.failed.length > 0) {
            message.error(
              `${text}${t('settings.evolution.clearAll.failedPrefix')}${result.failed.map((f) => `${f.project}(${f.error})`).join(t('settings.evolution.clearAll.failedSep'))}`,
            );
          } else {
            message.success(text);
          }
        } catch (e) {
          message.error(errText(e, t('settings.evolution.clearAll.cleanupFailed')));
        } finally {
          // 清空全项目 todo.md 较慢，await 返回时面板可能已卸载
          if (mountedRef.current) setClearingTodo(false);
        }
      },
    });
  };

  return (
    <div data-testid="suggested-improvements-panel">
      {/* 标题与功能注解提到卡片外（与上方「代码陈旧自愈」卡片同构） */}
      <h3>{t('settings.evolution.title')}</h3>
      <Text type="secondary">
        {t('settings.evolution.intro')}
      </Text>

      {/* 7.2: 配置卡片 */}
      <Card style={{ marginTop: 12, marginBottom: 16 }}>
        <Form form={form} initialValues={initialValues} layout="vertical" disabled={!isUserScope} onValuesChange={() => setDirty(true)}>
          {!isUserScope && (
            <Text type="secondary" style={{ display: 'block', marginBottom: 12 }}>
              {t('settings.evolution.globalKeysHint')}
            </Text>
          )}
          <div className="switch-inline-row">
            <Form.Item name="auto_accept" valuePropName="checked" noStyle>
              <Switch data-testid="self-evolution-control-auto-accept" />
            </Form.Item>
            <span className="switch-inline-label">
              {t('settings.evolution.autoAccept.label')}<span className="label-note">（self_evolution.auto_accept）</span>
            </span>
          </div>
          <Text type="secondary">
            {t('settings.evolution.autoAccept.desc')}
          </Text>

          {/* SPEC 执行时间：立项后何时开始跑。UI 上是「模式 + 时刻」两字段，
              配置里折叠成单键 spec_run_at（null / "HH:mm"）。
              外层 Form.Item 只提供 label 与行距（无 name），两个真字段以 noStyle
              并排——时刻控件必须紧跟选项同行，换行会让「这段文字属于哪个选项」
              变得含糊 */}
          <Form.Item
            label={
              <>
                {t('settings.evolution.specRun.label')}<span className="label-note">（self_evolution.spec_run_at）</span>
              </>
            }
            style={{ marginTop: 24 }}
          >
            <Space size={16}>
              <Form.Item name="spec_run_mode" noStyle>
                <Radio.Group
                  data-testid="self-evolution-control-spec-run-mode"
                  onChange={(e) => {
                    // 切到「指定时间」而时刻还空着时预填缺省，避免出现空控件
                    if (e.target.value === 'scheduled'
                        && !form.getFieldValue('spec_run_at')) {
                      form.setFieldValue('spec_run_at', DEFAULT_SPEC_RUN_AT);
                    }
                  }}
                >
                  <Radio value="immediate">{t('components.scheduleFields.optionImmediate')}</Radio>
                  <Radio value="scheduled">{t('components.scheduleFields.optionScheduled')}</Radio>
                </Radio.Group>
              </Form.Item>
              {specRunMode === 'scheduled' && (
                <Form.Item
                  name="spec_run_at"
                  noStyle
                  // 表单内以 "HH:mm" 字符串存取（配置同形态），控件收发 dayjs。
                  // 删空输入文本会以 null 触发 onChange（allowClear 挡不住），
                  // 此时回写上一值：否则 collect 以 || DEFAULT 折叠，配置被静默
                  // 改成缺省时刻
                  normalize={(v: Dayjs | null, prev: string | null) => (v ? v.format('HH:mm') : prev ?? null)}
                  getValueProps={(v: string | null) => ({ value: v ? dayjs(v, 'HH:mm') : null })}
                >
                  {/* allowClear=false：noStyle 字段不渲染校验文案，若允许清空会
                      变成静默回退缺省时刻，不如不给清空入口 */}
                  <TimePicker
                    format="HH:mm"
                    minuteStep={5}
                    needConfirm={false}
                    allowClear={false}
                    style={{ width: 120 }}
                    data-testid="self-evolution-control-spec-run-at"
                  />
                </Form.Item>
              )}
            </Space>
          </Form.Item>
          <Text type="secondary">
            {t('settings.evolution.specRun.desc')}
          </Text>

          <Form.Item
            name="max_items_per_run"
            label={
              <>
                {t('settings.evolution.maxItems.label')}<span className="label-note">（self_evolution.max_items_per_run）</span>
              </>
            }
            style={{ marginTop: 24 }}
            rules={[
              { required: true, message: t('settings.evolution.maxItems.required') },
              {
                type: 'number', min: 1, max: MAX_ITEMS_UPPER,
                message: t('settings.evolution.maxItems.range', { max: MAX_ITEMS_UPPER }),
              },
            ]}
          >
            <InputNumber min={1} max={MAX_ITEMS_UPPER} precision={0} style={{ width: '100%' }} addonAfter={t('settings.evolution.unit.items')} />
          </Form.Item>
          <Text type="secondary">
            {t('settings.evolution.maxItems.desc')}
          </Text>
        </Form>

        {/* 全局动作：清空所有项目的 todo.md。
            置于 Form 之外——antd 的 Form disabled 只作用于表单控件，普通 Button
            放进去不会随项目级作用域禁用；这里显式用 isUserScope 控制（「所有项目」
            本就是全局范围，与卡片其余配置项的项目级只读语义一致）。 */}
        <div style={{ marginTop: 24, borderTop: `1px solid ${DSH_BORDER_SECONDARY}`, paddingTop: 16 }}>
          <Button
            type="primary"
            danger
            disabled={!isUserScope || clearingTodo}
            loading={clearingTodo}
            onClick={handleClearAllTodo}
            data-testid="self-evolution-clear-todo"
          >
            {t('settings.evolution.clearAll.title')}
          </Button>
          <Text type="secondary" style={{ display: 'block', marginTop: 8 }}>
            {t('settings.evolution.clearAll.btnDescA')}
            <code>.fenix/todo.md</code>
            {t('settings.evolution.clearAll.btnDescB')}
            <code>items.jsonl</code>
            {t('settings.evolution.clearAll.btnDescC')}
          </Text>
        </div>
      </Card>

      {/* 7.3: 表格（移出卡片：小节标题与表格直接置于页签流内，与上方「建议改进项」
          标题同构；仍保留移动端横向滚动 + 操作列 fixed right） */}
      <h3 style={{ marginTop: 20 }}>
        {t('settings.evolution.list.title')}
        {/* 已选计数放标题行：工具栏那一行宽度吃紧，按钮文案随计数变长会把
            第三个按钮挤到下一行（实测 800px 可用宽放不下「批量同意(18)」×3） */}
        {selectedRowKeys.length > 0 && (
          <Text type="secondary" style={{ fontSize: 13, fontWeight: 400, marginLeft: 8 }}>
            {t('settings.evolution.list.selected', { count: selectedRowKeys.length })}
          </Text>
        )}
      </h3>

      {/* 7.6: 过滤条（左）+ 批量操作（右），同一行
          宽度预算：面板可用宽约 848px——状态 96 + 项目 96 + 日期 200 +
          重置 60 + 三个批量按钮 324（含计数，固定宽度）+ 间距 ≈ 816 一行放得下。
          批量按钮 MUST 定宽：文案带计数时（批量同意(18)）若随内容变宽会把第三个
          按钮挤到下一行。窗口更窄时由 flexWrap 兜底换行（不裁切）。 */}
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8, alignItems: 'center', marginBottom: 12 }}>
        <Select
          placeholder={t('settings.evolution.filter.status')}
          allowClear
          style={{ width: 96 }}
          value={filterStatus}
          onChange={setFilterStatus}
          options={statusOptions}
          data-testid="evolution-filter-status"
        />
        <Select
          placeholder={t('settings.evolution.filter.project')}
          allowClear
          style={{ width: 96 }}
          value={filterProject}
          onChange={setFilterProject}
          options={projectOptions}
          data-testid="evolution-filter-project"
        />
        <DatePicker.RangePicker
          value={filterDateRange}
          onChange={(range) => setFilterDateRange(range as [Dayjs, Dayjs] | null)}
          placeholder={[t('settings.evolution.filter.dateStart'), t('settings.evolution.filter.dateEnd')]}
          style={{ width: 200 }}
          data-testid="evolution-filter-date"
        />
        {hasFilter && (
          <Button type="link" onClick={resetFilters} data-testid="evolution-filter-reset">
            {t('common.reset')}
          </Button>
        )}
        <span style={{ flex: 1 }} />
        <Button
          disabled={selectedRowKeys.length === 0 || batchRunning}
          loading={batchRunning && batchAction === 'accept'}
          onClick={() => runBatch('accept')}
          style={{ minWidth: 96 }}
          data-testid="evolution-batch-accept"
        >
          {t('settings.evolution.batch.btnAccept')}
        </Button>
        <Button
          danger
          disabled={selectedRowKeys.length === 0 || batchRunning}
          loading={batchRunning && batchAction === 'reject'}
          onClick={() => runBatch('reject')}
          style={{ minWidth: 96 }}
          data-testid="evolution-batch-reject"
        >
          {t('settings.evolution.batch.btnReject')}
        </Button>
        {/* 删除 = 实心红底白字，与「查看」弹窗底部的删除按钮同款（拒绝保持描边红字） */}
        <Button
          type="primary"
          danger
          disabled={selectedRowKeys.length === 0 || batchRunning}
          loading={batchRunning && batchAction === 'delete'}
          onClick={() => runBatch('delete')}
          style={{ minWidth: 96 }}
          data-testid="evolution-batch-delete"
        >
          {t('settings.evolution.batch.btnDelete')}
        </Button>
      </div>

      {/* 批量执行进度（2026-11-16 用户要求界面应有处理进度显示）：逐条串行
          执行时展示 N/M 与当前条目标题；批量结束后随 batchRunning 复位消失 */}
      {batchRunning && batchProgress && (
        <div style={{ marginBottom: 12 }} data-testid="evolution-batch-progress">
          <Progress
            percent={Math.round((batchProgress.done / Math.max(batchProgress.total, 1)) * 100)}
            size="small"
            status="active"
          />
          <Text type="secondary" style={{ fontSize: 12 }}>
            {t('settings.evolution.batch.progress', {
              action: batchAction ? t(BATCH_VERB[batchAction]) : '',
              done: batchProgress.done,
              total: batchProgress.total,
            })}
            {batchProgress.current ? `${t('settings.evolution.batch.progressSep')}${batchProgress.current}` : ''}
          </Text>
        </div>
      )}

      {error && (
        <div style={{ marginBottom: 12, color: DSH_ERROR }}>
          {t('settings.evolution.loadFailedWith', { error })}
          {/* 重试复用 loadItems（code-review item e735721e599d）：刷新失败保留
              列表后，用户不必切作用域或刷新页面即可恢复数据 */}
          <Button type="link" style={{ padding: 0, marginLeft: 8 }} onClick={() => loadItems()}>
            {t('common.retry')}
          </Button>
        </div>
      )}
      {/* scroll.x 保持 800：加复选框列后若上调（如 860），表格最小宽度 + 面板
          内边距会超过设置页面板可用宽度，把整页撑出横向滚动条 */}
      <Table
        dataSource={filteredItems}
        columns={columns}
        rowKey="id"
        loading={loading}
        rowSelection={{
          selectedRowKeys,
          onChange: (keys) => setSelectedRowKeys(keys),
        }}
        scroll={{ x: 800 }}
        pagination={filteredItems.length > 20 ? { pageSize: 20, showSizeChanger: false } : false}
        locale={{ emptyText: items.length > 0 ? t('settings.evolution.emptyFiltered') : t('settings.evolution.emptyAll') }}
      />

      {/* 7.5: 查看弹窗（无草稿=仅分析结论；有草稿=分析结论 + 草稿文档页签，
          形态对齐 SPEC 列表页「文档」弹窗） */}
      <Modal
        title={
          <MaximizeTitle
            text={viewItem ? viewItem.title : t('settings.evolution.view.title')}
            button={viewMaximizeButton}
            isFullscreen={viewIsFullscreen}
          />
        }
        open={viewVisible}
        onCancel={closeView}
        footer={
          /* antd footer 缺省右对齐：操作区落在弹窗右下角。
             拒绝 = 描边红字（danger），删除 = 实心红底白字（danger + primary），
             两者破坏性层级不同，须一眼可分。
             batchRunning 并入 disabled（code-review item 10ff05c46ff6）：批量
             串行在飞时单条决策不得并发写，与操作列菜单同口径 */
          <Space>
            <Button
              disabled={viewActionDisabled.accept || batchRunning}
              onClick={() => viewItem && handleAccept(viewItem, closeView)}
            >
              {t('settings.evolution.action.accept')}
            </Button>
            <Button
              danger
              disabled={viewActionDisabled.reject || batchRunning}
              onClick={() => viewItem && handleReject(viewItem, closeView)}
            >
              {t('settings.evolution.action.reject')}
            </Button>
            <Button
              type="primary"
              danger
              disabled={viewActionDisabled.delete || batchRunning}
              onClick={() => viewItem && handleDelete(viewItem, closeView)}
            >
              {t('settings.evolution.action.delete')}
            </Button>
          </Space>
        }
        {...viewModalProps}
      >
        {/* 上一条 / 下一条：屏幕左右两侧浮层（看图控件形态），跳转范围为当前
            表格过滤结果；关闭弹窗时随 wrap 的 display:none 一并隐藏。
            禁用态靠外层 opacity 表达——内联 color 会压掉 antd 的禁用色 */}
        <div style={{ ...navButtonStyle, left: 16, opacity: canPrev ? 1 : 0.3 }}>
          <Button
            type="text"
            shape="circle"
            size="large"
            icon={<LeftOutlined />}
            disabled={!canPrev}
            onClick={() => goRelative(-1)}
            title={canPrev ? t('settings.evolution.nav.prev') : t('settings.evolution.nav.first')}
            aria-label={t('settings.evolution.nav.prev')}
            style={{ color: 'inherit', width: '100%', height: '100%' }}
            data-testid="evolution-view-prev"
          />
        </div>
        <div style={{ ...navButtonStyle, right: 16, opacity: canNext ? 1 : 0.3 }}>
          <Button
            type="text"
            shape="circle"
            size="large"
            icon={<RightOutlined />}
            disabled={!canNext}
            onClick={() => goRelative(1)}
            title={canNext ? t('settings.evolution.nav.next') : t('settings.evolution.nav.last')}
            aria-label={t('settings.evolution.nav.next')}
            style={{ color: 'inherit', width: '100%', height: '100%' }}
            data-testid="evolution-view-next"
          />
        </div>
        {/* 无草稿时不渲染页签：只剩分析结论一项，页签是多余的 */}
        {hasDoc && (
          <Tabs
            activeKey={viewTab}
            onChange={(key) => setViewTab(key as ViewTab)}
            items={[
              { key: 'analysis', label: t(ANALYSIS_TAB_LABEL) },
              ...EVOLUTION_DOCS.map((doc) => ({
                key: doc,
                label: t(EVOLUTION_DOC_LABELS[doc]),
              })),
            ]}
          />
        )}
        <div style={{ flex: 1, minHeight: 0 }} data-testid="evolution-view-body">
          <MarkdownBody
            loading={viewLoading}
            error={viewError}
            emptyText={viewEmptyText}
            content={viewContent}
            onRetry={() => viewItem && loadView(viewItem, viewTab)}
          />
        </div>
      </Modal>
    </div>
  );
});

export default SuggestedImprovementsPanel;
