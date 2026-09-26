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
import { Alert, Button, Card, DatePicker, Dropdown, Empty, Form, InputNumber, message, Modal, Radio, Select, Space, Spin, Switch, Table, Tabs, Tag, TimePicker, Tooltip, Typography } from 'antd';
import { LeftOutlined, MoreOutlined, RightOutlined } from '@ant-design/icons';
import Markdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import dayjs from 'dayjs';
import type { Dayjs } from 'dayjs';
import type { MenuProps } from 'antd';
import { forwardRef, useCallback, useEffect, useImperativeHandle, useMemo, useRef, useState } from 'react';
import type { CSSProperties, Key } from 'react';
import type { ConfigData, EvolutionItem, EvolutionDoc } from '@/services/dashboard';
import type { SelfEvolutionSectionHandle } from './selfEvolutionSection';
import { MaximizeTitle, useMaximizeModal } from '@/components/useMaximizeModal';
import ScheduleFields, {
  describeStartAfter,
  isStartAfterValid,
  nextRunAtISO,
} from '@/components/ScheduleFields';
import type { AcceptSchedule } from '@/components/ScheduleFields';
import { markdownComponents } from '@/pages/projects/components/SpecDocModal';
import {
  EVOLUTION_STATUS_LABELS,
  EVOLUTION_DOCS,
  getEvolutionItems,
  getEvolutionAnalysis,
  getEvolutionDraft,
  acceptEvolutionItem,
  rejectEvolutionItem,
  deleteEvolutionItem,
  clearAllEvolutionTodo,
} from '@/services/dashboard';

const { Text } = Typography;

/** 状态排序次序：待人工处理的排前，终态排后（非字母序）。 */
const STATUS_SORT_ORDER: Record<string, number> = {
  pending: 0,
  draft_failed: 1,
  accept_failed: 2,
  analyzed: 3,
  accepted: 4,
  auto_accepted: 5,
  rejected: 6,
};

/** 类别列 Tag 配色（参考 SPEC 列表页「模式」列的 Tag 写法）。 */
const SECTION_TAG_COLORS: Record<string, string> = {
  浪费: 'red',
  失误: 'orange',
  可改进: 'blue',
};

type BatchAction = 'accept' | 'reject' | 'delete';

/** 条目在当前状态下被禁用的原因（无禁用返回 null），供批量跳过汇报使用。 */
function actionDisabledReason(status: string, action: BatchAction): string | null {
  if (action === 'delete') return null; // 删除不设状态门：任意状态可删
  const dis = getActionDisabled(status);
  if (!dis[action]) return null;
  if (status === 'analyzed') return '不需要立项（无草稿）';
  if (status === 'draft_failed') return '草稿生成失败';
  return '已决策';
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
  proposal: '需求背景',
  design: '详细设计',
  tasks: '任务清单',
  spec: '测试场景清单',
};

/** 有草稿时「查看」弹窗的第一个页签文案。 */
const ANALYSIS_TAB_LABEL = '分析结论';

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
        message="加载失败"
        description={
          <>
            <div>{error}</div>
            {onRetry && (
              <Button type="link" style={{ padding: 0 }} onClick={onRetry}>
                点击重试
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
  yes: '成立',
  partial: '部分成立',
};
const VERDICT_SUGGESTION_LABELS: Record<string, string> = {
  yes: '合理',
  partial: '部分合理',
};

function verdictSummary(item: EvolutionItem): string {
  const v = item.verdict;
  if (!v) return '';
  const parts: string[] = [];
  if (v.problem_exists) {
    parts.push(`问题${VERDICT_PROBLEM_LABELS[v.problem_exists] ?? '不成立'}`);
  }
  if (v.suggestion_sound) {
    parts.push(`建议${VERDICT_SUGGESTION_LABELS[v.suggestion_sound] ?? '不合理'}`);
  }
  parts.push(v.worth_spec ? '✓ 值得立项' : '— 不需要');
  return parts.join(' / ');
}

// ── 禁用规则（7.4）────────────────────────────────────────────────

const ACTIONS = [
  { key: 'view', label: '查看' },
  { key: 'accept', label: '同意' },
  { key: 'reject', label: '拒绝', danger: true },
  { key: 'delete', label: '删除', danger: true },
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
  if (tab === 'analysis') return '分析结论不存在';
  if (docSource === 'spec') return '文档读自 SPEC 位置，对应文档不存在。';
  return '草稿文档不存在或已被接受删除。';
}

function getActionDisabled(status: string): Record<string, boolean> {
  // 「查看」不设状态门：分析结论恒可查看，有无草稿由弹窗自行分支（原「查看
  // SPEC 草稿」在 analyzed / draft_failed 下禁用，合并后该门随之取消）；
  // analyzed（不需要立项）：仅可查看，禁用「同意」「拒绝」；
  // draft_failed：无草稿可立项，禁用「同意」，仍可拒绝；
  // accepted / auto_accepted / rejected：禁用「同意」与「拒绝」；
  // pending / accept_failed：全部可用（accept_failed 可重试同意、可拒绝）。
  // delete 不设状态门（任意状态可删），恒可用。
  const analyzed = status === 'analyzed';
  const draftFailed = status === 'draft_failed';
  const decided = status === 'accepted' || status === 'auto_accepted' || status === 'rejected';
  return {
    view: false,
    accept: analyzed || draftFailed || decided,
    reject: analyzed || decided,
    delete: false,
  };
}

// ── 组件 ─────────────────────────────────────────────────────────────

// 保存按钮已上提到自进化页签底部（全页唯一），本卡片经 ref 暴露 collect()，
// 由父页签在唯一点击事件里与「代码陈旧自愈」卡片一起校验并合并提交。
const SuggestedImprovementsPanel = forwardRef<
  SelfEvolutionSectionHandle,
  SuggestedImprovementsPanelProps
>(function SuggestedImprovementsPanel({ config, scope, project }, ref) {
  const [form] = Form.useForm();
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

  // 返回本次加载到的条目数组：动作成功后的「转到下一条」要在刷新后的数据里按
  // id 找回目标——旧 items 里目标仍带着动作前的状态，直接复用会渲染出陈旧禁用态。
  const loadItems = useCallback(async (): Promise<EvolutionItem[]> => {
    setLoading(true);
    setError(null);
    try {
      const next = (await getEvolutionItems(project)).items || [];
      if (mountedRef.current) setItems(next);
      return next;
    } catch (e) {
      if (mountedRef.current) {
        const msg = errText(e, '加载失败');
        setError(msg);
        setItems([]);
      }
      return [];
    } finally {
      if (mountedRef.current) setLoading(false);
    }
  }, [project]);

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
  }, [scope, project]);
  useEffect(() => {
    if (hasAppliedDefaultFilter.current) return;
    if (items.length === 0) return; // 空数据（加载中/无数据）不落默认
    hasAppliedDefaultFilter.current = true;
    setFilterStatus(items.some((i) => i.status === 'pending') ? 'pending' : undefined);
  }, [items]);

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

  /** 执行一条 accept/reject/delete，异常收敛为失败结果（单条菜单与批量共用）。

   * ``startAfter`` 仅在 action='accept' 时有意义：新 SPEC 的定时拾取时刻
   * （UTC ISO），null = 立即执行。 */
  const execOne = async (
    item: EvolutionItem,
    action: BatchAction,
    startAfter?: string | null,
  ): Promise<{ ok: boolean; status?: string; spec_name?: string; error?: string }> => {
    try {
      if (action === 'accept') return await acceptEvolutionItem(item.id, startAfter ?? null);
      if (action === 'reject') return await rejectEvolutionItem(item.id);
      return await deleteEvolutionItem(item.id);
    } catch (e) {
      return { ok: false, error: errText(e, '请求失败') };
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
    setViewLoading(true);
    setViewError(null);
    try {
      const data = tab === 'analysis'
        ? await getEvolutionAnalysis(item.id)
        : await getEvolutionDraft(item.id, tab);
      // 序号落后 = 已有更新的请求接管视图，本响应过期丢弃
      if (!mountedRef.current || reqSeq !== viewReqSeqRef.current) return;
      if (!data.found) {
        setViewContent('');
      } else {
        setViewContent(data.content || '（空）');
      }
    } catch (e) {
      if (mountedRef.current && reqSeq === viewReqSeqRef.current) setViewError(errText(e, '加载失败'));
    } finally {
      // 过期请求不复位 loading：新请求仍在飞，由它自己的 finally 收口
      if (mountedRef.current && reqSeq === viewReqSeqRef.current) setViewLoading(false);
    }
  }, []);

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
  // 成功回调走 nextAfterAction（有下一条则转过去、否则关窗），失败时不调，
  // 弹窗原样留着——用户看清错误文案再决定重试还是翻页。操作列菜单不传回调。

  const handleAccept = (item: EvolutionItem, onDone?: () => void) => {
    // 本次执行时刻按配置预填（spec_run_at 为空 = 立即），弹窗里可临时改
    const holder: AcceptSchedule = { startAfter: configStartAfter() };
    Modal.confirm({
      title: '同意立项',
      width: 640,
      content: (
        <>
          <div style={{ marginBottom: 12 }}>确定对「{item.title}」点击同意？</div>
          <ScheduleFields holder={holder} initial={holder.startAfter} />
        </>
      ),
      okText: '同意',
      cancelText: '取消',
      onOk: async () => {
        // 哨兵 manual 不参与时刻校验（见 D11）；仅 ISO 定时需晚于当前时刻
        if (!isStartAfterValid(holder.startAfter)) {
          message.error('执行时间必须晚于当前时间');
          return Promise.reject(new Error('invalid start time'));
        }
        const result = await execOne(item, 'accept', holder.startAfter);
        if (result.ok) {
          message.success(
            `已立项：${result.spec_name || item.title}${describeStartAfter(holder.startAfter)}`,
          );
        } else {
          message.error(result.error || '接受失败');
          // 失败时拒绝 resolve，Modal.confirm 不自动关闭，弹窗原样留着（同 555-557 行注释）
          return Promise.reject(new Error(result.error || 'accept failed'));
        }
        const next = await loadItems();
        if (result.ok) nextAfterAction(next, item, onDone);
      },
    });
  };

  const handleReject = (item: EvolutionItem, onDone?: () => void) => {
    Modal.confirm({
      title: '拒绝',
      content: `确定拒绝「${item.title}」？草稿将被删除且不可恢复。`,
      okText: '拒绝',
      cancelText: '取消',
      okButtonProps: { danger: true },
      onOk: async () => {
        const result = await execOne(item, 'reject');
        if (result.ok) {
          message.success('已拒绝');
        } else {
          message.error(result.error || '拒绝失败');
          // 失败时拒绝 resolve，Modal.confirm 不自动关闭，弹窗原样留着（同 555-557 行注释）
          return Promise.reject(new Error(result.error || 'reject failed'));
        }
        const next = await loadItems();
        if (result.ok) nextAfterAction(next, item, onDone);
      },
    });
  };

  // ── 删除（7.7）─────────────────────────────────────────────────
  //
  // 硬删：记录移出 items.jsonl、草稿目录一并清理，不写墓碑。todo.md 里该条记录
  // 仍在，下一轮分析 run 可能把它重新入库——确认弹窗须向用户明示。

  const handleDelete = (item: EvolutionItem, onDone?: () => void) => {
    Modal.confirm({
      title: '删除条目',
      content: (
        <>
          <div>确定删除「{item.title}」？该条目将从列表移除，已生成的草稿一并删除。</div>
          <Text type="secondary">
            该条目对应的 todo.md 记录仍然存在，可能在下一轮分析 run 中重新入库。
          </Text>
        </>
      ),
      okText: '删除',
      cancelText: '取消',
      okButtonProps: { danger: true },
      onOk: async () => {
        const result = await execOne(item, 'delete');
        if (result.ok) {
          message.success('已删除');
        } else {
          message.error(result.error || '删除失败');
          // 失败时拒绝 resolve，Modal.confirm 不自动关闭，弹窗原样留着（同 555-557 行注释）
          return Promise.reject(new Error(result.error || 'delete failed'));
        }
        const next = await loadItems();
        if (result.ok) nextAfterAction(next, item, onDone);
      },
    });
  };

  // ── 批量同意 / 拒绝 / 删除（7.6）────────────────────────────────
  //
  // 后端只有逐条接口，批量在前端串行执行：并发写 items.jsonl 与逐条 git commit
  // 会互相冲突，故刻意不用 Promise.all。状态不允许操作的条目先在前端筛掉
  // （删除不设状态门，故删除路径恒无跳过项），确认弹窗预告「将处理 N 条 /
  // 跳过 M 条（按原因分组）」，执行后按成功/跳过/失败三类汇报，失败明细另用
  // Modal 列出。

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
      message.warning('选中的条目当前状态均不可操作，无可执行项');
      return;
    }

    const verb = action === 'accept' ? '同意' : action === 'reject' ? '拒绝' : '删除';
    const isDestructive = action !== 'accept';
    // 批量同意无逐条弹窗，执行时刻直接取配置（spec_run_at），并在确认弹窗里
    // 明示——否则「配了定时却被批量绕开」会让人以为设置没生效
    const batchStartAfter = action === 'accept' ? configStartAfter() : null;
    Modal.confirm({
      title: `批量${verb}`,
      content: (
        <>
          <div>
            将对 <b>{runnable.length}</b> 条执行「{verb}」
            {skippedCount > 0 && <>，跳过 <b>{skippedCount}</b> 条</>}。
          </div>
          {skippedCount > 0 && (
            <Text type="secondary">
              跳过原因：
              {[...skipReasons.entries()].map(([r, n]) => `${r} ${n} 条`).join('、')}
            </Text>
          )}
          {action === 'accept' && (
            <div style={{ marginTop: 8 }}>
              <Text type="secondary">
                执行时间：
                {batchStartAfter
                  ? `${dayjs(batchStartAfter).format('YYYY-MM-DD HH:mm')}（按设置页 SPEC 执行时间）`
                  : '创建后立即执行'}
              </Text>
            </div>
          )}
          {action === 'delete' && (
            <div style={{ marginTop: 8 }}>
              <Text type="secondary">
                删除后这些条目对应的 todo.md 记录仍在，可能在下一轮分析 run 中重新入库。
              </Text>
            </div>
          )}
        </>
      ),
      okText: verb,
      cancelText: '取消',
      okButtonProps: isDestructive ? { danger: true } : undefined,
      onOk: async () => {
        setBatchRunning(true);
        let succeeded = 0;
        // 携带 item.id 作 key（code-review item 4d4f1e78b97b）：不同项目条目的
        // title 可能相同，以 title 作 React key 会冲突导致明细错位
        const failures: { id: string; title: string; error: string }[] = [];
        try {
          // 串行：后端写 items.jsonl 用文件锁、接受路径还逐条 git commit
          for (const item of runnable) {
            const result = await execOne(item, action, batchStartAfter);
            if (result.ok) {
              succeeded += 1;
            } else {
              failures.push({ id: item.id, title: item.title, error: result.error || '失败' });
            }
          }
        } finally {
          // unmount 守卫（code-review item ab67eda51983）：批量运行中用户导航
          // 离开（面板卸载）时，多 await 之后的 state 更新不得打到已卸载组件
          // ——与 loadItems/loadView 的 mountedRef 口径一致。
          if (mountedRef.current) setBatchRunning(false);
        }
        if (mountedRef.current) setSelectedRowKeys([]);
        await loadItems();

        const parts = [`成功 ${succeeded} 条`];
        if (skippedCount > 0) parts.push(`跳过 ${skippedCount} 条`);
        if (failures.length > 0) parts.push(`失败 ${failures.length} 条`);
        const summary = parts.join('，');
        if (failures.length > 0) {
          message.warning(summary);
          Modal.error({
            title: '部分条目处理失败',
            width: 560,
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
      },
    });
  };

  // ── 操作菜单（7.4：Dropdown + MoreOutlined + Button type="link"）────────

  const menuItems = (item: EvolutionItem): MenuProps['items'] => {
    const dis = getActionDisabled(item.status);
    return ACTIONS.map((a) => ({
      key: a.key,
      label: a.label,
      disabled: dis[a.key],
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

  const { modalProps: viewModalProps, maximizeButton: viewMaximizeButton } =
    useMaximizeModal(DOC_MODAL_OPTIONS);

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
    filterStatus,
    filterProject,
    filterDateRange,
  });
  useEffect(() => {
    latestViewStateRef.current = {
      viewVisible,
      viewIndex,
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
    const { viewVisible: visibleNow, viewIndex: idxNow,
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
    const target = idx >= 0 ? seq[idx + 1] : seq[idxNow];
    // 只有「查看」弹窗开着时才在窗内翻页——操作列菜单发起的同名动作没有
    // 弹窗可翻，保持原行为（仅刷新表格）。
    if (target && visibleNow) {
      setViewItem(target);
      setViewTab('analysis'); // 与首次打开同构：页签回到分析结论
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
      title: '项目', dataIndex: 'project', key: 'project', width: 100, ellipsis: true,
      sorter: (a: EvolutionItem, b: EvolutionItem) => (a.project || '').localeCompare(b.project || ''),
    },
    {
      title: '日期', dataIndex: 'date_section', key: 'date_section', width: 110,
      // date_section 为 'YYYY-MM-DD'，字典序即时间序
      sorter: (a: EvolutionItem, b: EvolutionItem) =>
        (a.date_section || '').localeCompare(b.date_section || ''),
    },
    {
      title: '类别', dataIndex: 'section', key: 'section', width: 90,
      sorter: (a: EvolutionItem, b: EvolutionItem) => (a.section || '').localeCompare(b.section || ''),
      // 参照 SPEC 列表页「模式」列：Tag 渲染 + marginInlineEnd:0 收紧列宽
      render: (s: string) => (
        <Tag color={SECTION_TAG_COLORS[s]} style={{ marginInlineEnd: 0 }}>{s}</Tag>
      ),
    },
    {
      title: '问题', dataIndex: 'title', key: 'title', ellipsis: true,
      // 问题列不设 width：它吃掉剩余宽度，设了 sorter 后表头才有空间放排序箭头
      sorter: (a: EvolutionItem, b: EvolutionItem) => (a.title || '').localeCompare(b.title || ''),
      // 问题标题即「查看」入口（等价操作列的 更多 → 查看）：读条目的第一动作就是
      // 点标题，不必先展开下拉。可点击样式沿用 SPEC 列表页名称列（蓝字 + pointer）
      render: (t: string, r: EvolutionItem) => (
        <span
          onClick={() => openView(r)}
          style={{ whiteSpace: 'nowrap', cursor: 'pointer', color: '#1677ff' }}
          data-testid={`evolution-item-title-${r.id}`}
        >
          {t}
        </span>
      ),
    },
    {
      title: '评估结论', key: 'verdict', width: 180,
      render: (_: unknown, r: EvolutionItem) => (
        <Tooltip title={r.verdict?.rationale || ''}>
          <Text type="secondary" style={{ fontSize: 12 }}>{verdictSummary(r)}</Text>
        </Tooltip>
      ),
    },
    {
      title: '状态', dataIndex: 'status', key: 'status', width: 110,
      // 语义序（待处理在前、终态在后）而非字母序；未知状态排最后
      sorter: (a: EvolutionItem, b: EvolutionItem) =>
        (STATUS_SORT_ORDER[a.status] ?? 99) - (STATUS_SORT_ORDER[b.status] ?? 99),
      render: (s: string) => {
        const colorMap: Record<string, string> = {
          pending: 'gold',
          analyzed: 'default',
          draft_failed: 'error',
          accepted: 'success',
          auto_accepted: 'success',
          rejected: 'default',
          accept_failed: 'error',
        };
        return <Tag color={colorMap[s] || 'default'}>{EVOLUTION_STATUS_LABELS[s] || s}</Tag>;
      },
    },
    {
      title: '操作', key: 'actions', width: 80,
      fixed: 'right' as const,
      onCell: () => ({ style: { paddingInline: 0 } }),
      render: (_: unknown, record: EvolutionItem) => (
        <Dropdown
          menu={{ items: menuItems(record) }}
          placement="bottomRight"
          trigger={['click']}
        >
          <Button type="link" size="small" icon={<MoreOutlined />}>更多</Button>
        </Dropdown>
      ),
    },
  ];

  /** 清空所有项目的 .fenix/todo.md（全局动作，项目级作用域不可用）。 */
  const handleClearAllTodo = () => {
    Modal.confirm({
      title: '清理所有项目自省内容',
      width: 520,
      content: (
        <>
          <p style={{ marginTop: 0 }}>
            将把<strong>所有项目</strong>的 <code>.fenix/todo.md</code> 清空为
            空文件。该文件是各项目每日自省的产物，清空后不可从界面恢复
            （已提交部分可从各项目 git 历史找回，未提交的改动会丢失）。
          </p>
          <p style={{ marginBottom: 0 }}>
            下方<strong>条目列表不受影响</strong>：它读的是
            <code> .fenix/evolution/items.jsonl</code>，与 todo.md 是两条独立
            数据。本操作也不会代为提交 git。
          </p>
        </>
      ),
      okText: '清空',
      okButtonProps: { danger: true },
      cancelText: '取消',
      onOk: async () => {
        // unmount 守卫：与 setBatchRunning/loadItems/loadView 的 mountedRef 口径一致。
        if (mountedRef.current) setClearingTodo(true);
        try {
          const result = await clearAllEvolutionTodo();
          const parts = [`已清空 ${result.cleared.length} 个项目`];
          if (result.skipped.length > 0) parts.push(`跳过 ${result.skipped.length} 个`);
          if (result.failed.length > 0) parts.push(`失败 ${result.failed.length} 个`);
          const text = parts.join('，');
          if (result.failed.length > 0) {
            message.error(
              `${text}：${result.failed.map((f) => `${f.project}(${f.error})`).join('；')}`,
            );
          } else {
            message.success(text);
          }
        } catch (e) {
          message.error(errText(e, '清理失败'));
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
      <h3>可改进项</h3>
      <Text type="secondary">
        每日自省后，框架汇总各项目 todo.md「浪费 / 失误 / 可改进」小节中的候选条目，
        交由分析 Agent 逐条复核（问题是否成立、建议是否合理、是否值得立项）。值得立项的
        生成 SPEC 草稿进入下方条目列表，由你在此处同意或拒绝，也可开启自动接受。
      </Text>

      {/* 7.2: 配置卡片 */}
      <Card style={{ marginTop: 12, marginBottom: 16 }}>
        <Form form={form} initialValues={initialValues} layout="vertical" disabled={!isUserScope}>
          {!isUserScope && (
            <Text type="secondary" style={{ display: 'block', marginBottom: 12 }}>
              全局键（auto_accept / max_items_per_run / spec_run_at），请在用户级作用域修改。
            </Text>
          )}
          <div className="switch-inline-row">
            <Form.Item name="auto_accept" valuePropName="checked" noStyle>
              <Switch data-testid="self-evolution-control-auto-accept" />
            </Form.Item>
            <span className="switch-inline-label">
              允许框架自改进<span className="label-note">（self_evolution.auto_accept）</span>
            </span>
          </div>
          <Text type="secondary">
            缺省关闭。开启后分析 run 落地即对全部待决策且值得立项的条目自动走接受路径
            （记为自动接受），框架自行立项并进入开发；关闭时草稿停留在下表等待人工
            「同意」。项目级作用域下本项只读。
          </Text>

          {/* SPEC 执行时间：立项后何时开始跑。UI 上是「模式 + 时刻」两字段，
              配置里折叠成单键 spec_run_at（null / "HH:mm"）。
              外层 Form.Item 只提供 label 与行距（无 name），两个真字段以 noStyle
              并排——时刻控件必须紧跟选项同行，换行会让「这段文字属于哪个选项」
              变得含糊 */}
          <Form.Item
            label={
              <>
                SPEC 执行时间<span className="label-note">（self_evolution.spec_run_at）</span>
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
                  <Radio value="immediate">创建后立即执行</Radio>
                  <Radio value="scheduled">在指定时间执行</Radio>
                </Radio.Group>
              </Form.Item>
              {specRunMode === 'scheduled' && (
                <Form.Item
                  name="spec_run_at"
                  noStyle
                  // 表单内以 "HH:mm" 字符串存取（配置同形态），控件收发 dayjs
                  normalize={(v: Dayjs | null) => (v ? v.format('HH:mm') : null)}
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
            缺省「创建后立即执行」（存量配置无此键即为此档）。选「在指定时间执行」后，
            每日该时刻生效：立项产生的 SPEC 记下 STATE 的 start_after（下一个该时刻），
            到点前一律不派发给 implementer / verifier，到点由调度自动拾取。时刻按本机
            时区解释；「同意立项」弹窗里可对本次临时改。项目级作用域下本项只读。
          </Text>

          <Form.Item
            name="max_items_per_run"
            label={
              <>
                每轮分析条目上限<span className="label-note">（self_evolution.max_items_per_run）</span>
              </>
            }
            style={{ marginTop: 24 }}
            rules={[{
              type: 'number', min: 1, max: MAX_ITEMS_UPPER,
              message: `须为 1-${MAX_ITEMS_UPPER} 的整数`,
            }]}
          >
            <InputNumber min={1} max={MAX_ITEMS_UPPER} precision={0} style={{ width: '100%' }} addonAfter="条" />
          </Form.Item>
          <Text type="secondary">
            缺省 20（1-200）。单轮分析 run 最多复核的条目数。超出部分保持待决策，
            由下一轮的增量水位继续处理，用来给每轮的 LLM 成本封顶。
          </Text>
        </Form>

        {/* 全局动作：清空所有项目的 todo.md。
            置于 Form 之外——antd 的 Form disabled 只作用于表单控件，普通 Button
            放进去不会随项目级作用域禁用；这里显式用 isUserScope 控制（「所有项目」
            本就是全局范围，与卡片其余配置项的项目级只读语义一致）。 */}
        <div style={{ marginTop: 24, borderTop: '1px solid #f0f0f0', paddingTop: 16 }}>
          <Button
            type="primary"
            danger
            disabled={!isUserScope || clearingTodo}
            loading={clearingTodo}
            onClick={handleClearAllTodo}
            data-testid="self-evolution-clear-todo"
          >
            清理所有项目自省内容
          </Button>
          <Text type="secondary" style={{ display: 'block', marginTop: 8 }}>
            把所有项目的 <code>.fenix/todo.md</code> 清空为空文件。仅清理这一份自省
            文本——下方条目列表（读 <code>items.jsonl</code>）不受影响，也不代为提交
            git。清空后这些仓库会处于未提交状态，由下一次每日自省一并提交。
            项目级作用域下不可用。
          </Text>
        </div>
      </Card>

      {/* 7.3: 表格（移出卡片：小节标题与表格直接置于页签流内，与上方「建议改进项」
          标题同构；仍保留移动端横向滚动 + 操作列 fixed right） */}
      <h3 style={{ marginTop: 20 }}>
        条目列表
        {/* 已选计数放标题行：工具栏那一行宽度吃紧，按钮文案随计数变长会把
            第三个按钮挤到下一行（实测 800px 可用宽放不下「批量同意(18)」×3） */}
        {selectedRowKeys.length > 0 && (
          <Text type="secondary" style={{ fontSize: 13, fontWeight: 400, marginLeft: 8 }}>
            已选 {selectedRowKeys.length} 条
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
          placeholder="状态"
          allowClear
          style={{ width: 96 }}
          value={filterStatus}
          onChange={setFilterStatus}
          options={statusOptions}
          data-testid="evolution-filter-status"
        />
        <Select
          placeholder="项目"
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
          placeholder={['起始日期', '结束日期']}
          style={{ width: 200 }}
          data-testid="evolution-filter-date"
        />
        {hasFilter && (
          <Button type="link" onClick={resetFilters} data-testid="evolution-filter-reset">
            重置
          </Button>
        )}
        <span style={{ flex: 1 }} />
        <Button
          disabled={selectedRowKeys.length === 0 || batchRunning}
          loading={batchRunning}
          onClick={() => runBatch('accept')}
          style={{ minWidth: 96 }}
          data-testid="evolution-batch-accept"
        >
          批量同意
        </Button>
        <Button
          danger
          disabled={selectedRowKeys.length === 0 || batchRunning}
          onClick={() => runBatch('reject')}
          style={{ minWidth: 96 }}
          data-testid="evolution-batch-reject"
        >
          批量拒绝
        </Button>
        {/* 删除 = 实心红底白字，与「查看」弹窗底部的删除按钮同款（拒绝保持描边红字） */}
        <Button
          type="primary"
          danger
          disabled={selectedRowKeys.length === 0 || batchRunning}
          onClick={() => runBatch('delete')}
          style={{ minWidth: 96 }}
          data-testid="evolution-batch-delete"
        >
          批量删除
        </Button>
      </div>

      {error && <div style={{ marginBottom: 12, color: '#ff4d4f' }}>加载失败：{error}</div>}
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
        locale={{ emptyText: items.length > 0 ? '没有符合过滤条件的条目' : '暂无建议改进项' }}
      />

      {/* 7.5: 查看弹窗（无草稿=仅分析结论；有草稿=分析结论 + 草稿文档页签，
          形态对齐 SPEC 列表页「文档」弹窗） */}
      <Modal
        title={
          <MaximizeTitle
            text={viewItem ? viewItem.title : '查看'}
            button={viewMaximizeButton}
          />
        }
        open={viewVisible}
        onCancel={closeView}
        footer={
          /* antd footer 缺省右对齐：操作区落在弹窗右下角。
             拒绝 = 描边红字（danger），删除 = 实心红底白字（danger + primary），
             两者破坏性层级不同，须一眼可分 */
          <Space>
            <Button
              disabled={viewActionDisabled.accept}
              onClick={() => viewItem && handleAccept(viewItem, closeView)}
            >
              同意
            </Button>
            <Button
              danger
              disabled={viewActionDisabled.reject}
              onClick={() => viewItem && handleReject(viewItem, closeView)}
            >
              拒绝
            </Button>
            <Button
              type="primary"
              danger
              disabled={viewActionDisabled.delete}
              onClick={() => viewItem && handleDelete(viewItem, closeView)}
            >
              删除
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
            title={canPrev ? '上一条' : '已是第一条'}
            aria-label="上一条"
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
            title={canNext ? '下一条' : '已是最后一条'}
            aria-label="下一条"
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
              { key: 'analysis', label: ANALYSIS_TAB_LABEL },
              ...EVOLUTION_DOCS.map((doc) => ({
                key: doc,
                label: EVOLUTION_DOC_LABELS[doc],
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
