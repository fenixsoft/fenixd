/**
 * 建议改进项面板（add-framework-self-evolution 7.2-7.5）
 *
 * 设置页「自进化」页签下的第二张卡片。展示跨项目建议改进项表格，
 * 支持配置自进化开关 / 每轮上限、查看分析结论与草稿、同意立项 / 拒绝。
 *
 * 7.2: 顶部配置（用户级可写 / 项目级只读 + 全局键提示）
 * 7.3: 表格（列序：项目 / 日期 / 类别 / 问题 / 评估结论 / 状态 / 操作）
 * 7.4: 操作列「更多」下拉（复用 projects/list.tsx 形态）+ 二次确认弹窗
 * 7.5: 查看分析结论（弹窗）/ 查看草稿（弹窗 + 四文档页签）+ 接受拒绝反馈
 * 7.6: 表头排序 + 状态（默认待决策）/项目/日期过滤条 + 多选与批量同意/拒绝
 * 7.7: 操作列「删除」（硬删条目）+ 批量删除；类别列 Tag 渲染
 */
import { Alert, Button, Card, DatePicker, Dropdown, Empty, Form, InputNumber, message, Modal, Select, Space, Spin, Switch, Table, Tabs, Tag, Tooltip, Typography } from 'antd';
import { MoreOutlined } from '@ant-design/icons';
import Markdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import type { Dayjs } from 'dayjs';
import type { MenuProps } from 'antd';
import { forwardRef, useCallback, useEffect, useImperativeHandle, useMemo, useRef, useState } from 'react';
import type { Key } from 'react';
import type { ConfigData, EvolutionItem, EvolutionDoc } from '@/services/dashboard';
import type { SelfEvolutionSectionHandle } from './selfEvolutionSection';
import { MaximizeTitle, useMaximizeModal } from '@/components/useMaximizeModal';
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

// add-evolution-item-management：默认只看待决策条目（可操作的那批），
// 状态选择器可清空以查看全部
const DEFAULT_STATUS_FILTER = 'pending';

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
// 「查看分析结论」「查看 SPEC 草稿」原为 Drawer，形态与 projects 列表页的
// 「文档」弹窗不一致（且用裸 Markdown，正文表格无边框）。此处统一改为中心
// 弹窗：复用 SpecDocModal 导出的 markdownComponents 与 useMaximizeModal，
// 加载中 / 失败可重试 / 空 / 正文四态同构。
const DOC_MODAL_OPTIONS = {
  defaultWidth: '80%',
  defaultBodyHeight: 'calc(80vh - 80px)',
  extraBodyStyle: { display: 'flex', flexDirection: 'column', overflow: 'hidden' },
  centered: true,
} as const;

// 草稿四文档页签文案（沿用原按钮文案，不改）
const EVOLUTION_DOC_LABELS: Record<EvolutionDoc, string> = {
  proposal: 'Proposal',
  design: 'Design',
  tasks: 'Tasks',
  spec: 'Spec',
};

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

// ── 评估结论摘要（7.3）──────────────────────────────────────────────

function verdictSummary(item: EvolutionItem): string {
  const v = item.verdict;
  if (!v) return '';
  const parts: string[] = [];
  if (v.problem_exists) parts.push(`问题${v.problem_exists === 'yes' ? '成立' : v.problem_exists === 'partial' ? '部分成立' : '不成立'}`);
  if (v.suggestion_sound) parts.push(`建议${v.suggestion_sound === 'yes' ? '合理' : v.suggestion_sound === 'partial' ? '部分合理' : '不合理'}`);
  parts.push(v.worth_spec ? '✓ 值得立项' : '— 不需要');
  return parts.join(' / ');
}

// ── 禁用规则（7.4）────────────────────────────────────────────────

const ACTIONS = [
  { key: 'analysis', label: '查看分析结论' },
  { key: 'draft', label: '查看 SPEC 草稿' },
  { key: 'accept', label: '同意' },
  { key: 'reject', label: '拒绝', danger: true },
  { key: 'delete', label: '删除', danger: true },
] as const;

function getActionDisabled(status: string): Record<string, boolean> {
  // analyzed / draft_failed：禁用「查看 SPEC 草稿」与「同意」；
  // analyzed 另禁用「拒绝」（仅可查看结论）；
  // accepted / auto_accepted / rejected：禁用「同意」与「拒绝」；
  // pending / accept_failed：全部可用（accept_failed 可重试同意、可拒绝）。
  // delete 不设状态门（任意状态可删），恒可用。
  const analyzed = status === 'analyzed';
  const draftFailed = status === 'draft_failed';
  const decided = status === 'accepted' || status === 'auto_accepted' || status === 'rejected';
  return {
    analysis: false,
    draft: analyzed || draftFailed,
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
  const initialValues = useMemo(() => ({
    auto_accept: se?.auto_accept ?? DEFAULT_AUTO_ACCEPT,
    max_items_per_run: se?.max_items_per_run ?? DEFAULT_MAX_ITEMS,
  }), [se?.auto_accept, se?.max_items_per_run]);

  useEffect(() => {
    form.setFieldsValue(initialValues);
  }, [initialValues, form]);

  useImperativeHandle(
    ref,
    () => ({
      collect: async () => {
        // 项目级作用域下两键为只读全局键：不收集（父页签仅提交陈旧自愈节）
        if (!isUserScope) return {};
        try {
          const values = await form.validateFields();
          return {
            self_evolution: {
              auto_accept: values.auto_accept,
              max_items_per_run: values.max_items_per_run,
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

  const loadItems = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await getEvolutionItems(project);
      if (mountedRef.current) setItems(data.items || []);
    } catch (e: any) {
      if (mountedRef.current) {
        const msg = e?.message || '加载失败';
        setError(msg);
        setItems([]);
      }
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
  // 状态默认「待决策」——打开页签先看待决策那批（可操作项），选择器可清空看全部。

  const [filterStatus, setFilterStatus] = useState<string | undefined>(DEFAULT_STATUS_FILTER);
  const [filterProject, setFilterProject] = useState<string | undefined>();
  const [filterDateRange, setFilterDateRange] = useState<[Dayjs, Dayjs] | null>(null);

  const projectOptions = useMemo(() => distinctOptions(items, (i) => i.project), [items]);
  const statusOptions = useMemo(
    () => distinctOptions(items, (i) => i.status, (s) => EVOLUTION_STATUS_LABELS[s] || s),
    [items],
  );

  // 状态处于默认值时不算「已过滤」（否则重置按钮恒亮）
  const hasFilter = Boolean(filterProject || filterDateRange) || filterStatus !== DEFAULT_STATUS_FILTER;

  const resetFilters = () => {
    setFilterStatus(DEFAULT_STATUS_FILTER);
    setFilterProject(undefined);
    setFilterDateRange(null);
  };

  const filteredItems = useMemo(() => {
    const start = filterDateRange?.[0]?.format('YYYY-MM-DD');
    const end = filterDateRange?.[1]?.format('YYYY-MM-DD');
    return items.filter((item) => {
      if (filterStatus && item.status !== filterStatus) return false;
      if (filterProject && item.project !== filterProject) return false;
      // date_section 为 'YYYY-MM-DD'，缺值时不被日期条件排除
      if (start && item.date_section && item.date_section < start) return false;
      if (end && item.date_section && item.date_section > end) return false;
      return true;
    });
  }, [items, filterStatus, filterProject, filterDateRange]);

  // ── 多选与批量（7.6）────────────────────────────────────────────

  const [selectedRowKeys, setSelectedRowKeys] = useState<Key[]>([]);
  const [batchRunning, setBatchRunning] = useState(false);

  // 过滤条件变化即清空选中：否则「先全选、再改过滤」会让批量作用到看不见的行上
  useEffect(() => {
    setSelectedRowKeys([]);
  }, [filterStatus, filterProject, filterDateRange]);

  /** 执行一条 accept/reject/delete，异常收敛为失败结果（单条菜单与批量共用）。 */
  const execOne = async (
    item: EvolutionItem,
    action: BatchAction,
  ): Promise<{ ok: boolean; status?: string; spec_name?: string; error?: string }> => {
    try {
      if (action === 'accept') return await acceptEvolutionItem(item.id);
      if (action === 'reject') return await rejectEvolutionItem(item.id);
      return await deleteEvolutionItem(item.id);
    } catch (e: any) {
      return { ok: false, error: e?.message || '请求失败' };
    }
  };

  // ── 查看分析结论（7.5，弹窗）────────────────────────────────────

  const [analysisVisible, setAnalysisVisible] = useState(false);
  const [analysisContent, setAnalysisContent] = useState('');
  const [analysisLoading, setAnalysisLoading] = useState(false);
  const [analysisError, setAnalysisError] = useState<string | null>(null);
  // 记住来源条目：弹窗标题与「点击重试」都依赖它（原实现只存标题串）
  const [analysisItem, setAnalysisItem] = useState<EvolutionItem | null>(null);

  const openAnalysis = async (item: EvolutionItem) => {
    setAnalysisVisible(true);
    setAnalysisItem(item);
    setAnalysisContent('');
    setAnalysisError(null);
    setAnalysisLoading(true);
    try {
      const data = await getEvolutionAnalysis(item.id);
      if (!mountedRef.current) return;
      if (!data.found) {
        setAnalysisError('分析结论不存在');
      } else {
        setAnalysisContent(data.content || '（空）');
      }
    } catch (e: any) {
      if (mountedRef.current) setAnalysisError(e?.message || '加载失败');
    } finally {
      if (mountedRef.current) setAnalysisLoading(false);
    }
  };

  // ── 查看 SPEC 草稿（7.5）────────────────────────────────────────

  const [draftVisible, setDraftVisible] = useState(false);
  const [draftItem, setDraftItem] = useState<EvolutionItem | null>(null);
  const [draftDoc, setDraftDoc] = useState<EvolutionDoc>('proposal');
  const [draftContent, setDraftContent] = useState('');
  const [draftLoading, setDraftLoading] = useState(false);
  const [draftError, setDraftError] = useState<string | null>(null);
  const [draftFound, setDraftFound] = useState(true);

  const loadDraft = useCallback(async (item: EvolutionItem, doc: EvolutionDoc) => {
    setDraftLoading(true);
    setDraftError(null);
    setDraftFound(true);
    try {
      const data = await getEvolutionDraft(item.id, doc);
      if (!mountedRef.current) return;
      if (!data.found) {
        setDraftFound(false);
        setDraftContent('');
      } else {
        setDraftFound(true);
        setDraftContent(data.content || '（空）');
      }
    } catch (e: any) {
      if (mountedRef.current) {
        const msg = e?.message || '加载失败';
        if (msg.includes('400') || msg.includes('非法')) {
          setDraftError(msg);
        } else {
          setDraftError(msg);
        }
      }
    } finally {
      if (mountedRef.current) setDraftLoading(false);
    }
  }, []);

  const openDraft = async (item: EvolutionItem) => {
    setDraftVisible(true);
    setDraftItem(item);
    setDraftDoc('proposal');
    loadDraft(item, 'proposal');
  };

  useEffect(() => {
    if (draftVisible && draftItem) loadDraft(draftItem, draftDoc);
  }, [draftVisible, draftItem, draftDoc, loadDraft]);

  // ── 接受 / 拒绝（7.5 二次确认）──────────────────────────────────

  const handleAccept = (item: EvolutionItem) => {
    Modal.confirm({
      title: '同意立项',
      content: `确定对「${item.title}」点击同意？将为该条目创建 SPEC 并进入流水线。`,
      okText: '同意',
      cancelText: '取消',
      onOk: async () => {
        const result = await execOne(item, 'accept');
        if (result.ok) {
          message.success(`已立项：${result.spec_name || item.title}`);
        } else {
          message.error(result.error || '接受失败');
        }
        loadItems();
      },
    });
  };

  const handleReject = (item: EvolutionItem) => {
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
        }
        loadItems();
      },
    });
  };

  // ── 删除（7.7）─────────────────────────────────────────────────
  //
  // 硬删：记录移出 items.jsonl、草稿目录一并清理，不写墓碑。todo.md 里该条记录
  // 仍在，下一轮分析 run 可能把它重新入库——确认弹窗须向用户明示。

  const handleDelete = (item: EvolutionItem) => {
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
        }
        loadItems();
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
        const failures: { title: string; error: string }[] = [];
        try {
          // 串行：后端写 items.jsonl 用文件锁、接受路径还逐条 git commit
          for (const item of runnable) {
            const result = await execOne(item, action);
            if (result.ok) {
              succeeded += 1;
            } else {
              failures.push({ title: item.title, error: result.error || '失败' });
            }
          }
        } finally {
          setBatchRunning(false);
        }
        setSelectedRowKeys([]);
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
                  <li key={f.title}>
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
        if (a.key === 'analysis') openAnalysis(item);
        else if (a.key === 'draft') openDraft(item);
        else if (a.key === 'accept') handleAccept(item);
        else if (a.key === 'reject') handleReject(item);
        else if (a.key === 'delete') handleDelete(item);
      },
    }));
  };

  // ── 弹窗最大化（7.5：两个弹窗各自独立的最大化状态）──────────────

  const { modalProps: analysisModalProps, maximizeButton: analysisMaximizeButton } =
    useMaximizeModal(DOC_MODAL_OPTIONS);
  const { modalProps: draftModalProps, maximizeButton: draftMaximizeButton } =
    useMaximizeModal(DOC_MODAL_OPTIONS);

  // ── 表格列（7.3）──────────────────────────────────────────────────

  const columns = [
    {
      title: '项目', dataIndex: 'project', key: 'project', width: 100, ellipsis: true,
      sorter: (a: EvolutionItem, b: EvolutionItem) => a.project.localeCompare(b.project),
    },
    {
      title: '日期', dataIndex: 'date_section', key: 'date_section', width: 110,
      // date_section 为 'YYYY-MM-DD'，字典序即时间序
      sorter: (a: EvolutionItem, b: EvolutionItem) => a.date_section.localeCompare(b.date_section),
    },
    {
      title: '类别', dataIndex: 'section', key: 'section', width: 90,
      sorter: (a: EvolutionItem, b: EvolutionItem) => a.section.localeCompare(b.section),
      // 参照 SPEC 列表页「模式」列：Tag 渲染 + marginInlineEnd:0 收紧列宽
      render: (s: string) => (
        <Tag color={SECTION_TAG_COLORS[s]} style={{ marginInlineEnd: 0 }}>{s}</Tag>
      ),
    },
    {
      title: '问题', dataIndex: 'title', key: 'title', ellipsis: true,
      // 问题列不设 width：它吃掉剩余宽度，设了 sorter 后表头才有空间放排序箭头
      sorter: (a: EvolutionItem, b: EvolutionItem) => a.title.localeCompare(b.title),
      render: (t: string) => <Text style={{ whiteSpace: 'nowrap' }}>{t}</Text>,
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

  return (
    <div data-testid="suggested-improvements-panel">
      {/* 标题与功能注解提到卡片外（与上方「代码陈旧自愈」卡片同构） */}
      <h3>建议改进项</h3>
      <Text type="secondary">
        每日自省后，框架汇总各项目 todo.md「浪费 / 失误 / 可改进」小节中的候选条目，
        交由分析 run 逐条复核（问题是否成立、建议是否合理、是否值得立项）：值得立项的
        生成 SPEC 草稿进入下方条目列表，由你在此处同意或拒绝，也可开启自动接受。
      </Text>

      {/* 7.2: 配置卡片 */}
      <Card style={{ marginTop: 12, marginBottom: 16 }}>
        <Form form={form} initialValues={initialValues} layout="vertical" disabled={!isUserScope}>
          {!isUserScope && (
            <Text type="secondary" style={{ display: 'block', marginBottom: 12 }}>
              全局键（auto_accept / max_items_per_run），请在用户级作用域修改。
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
            <InputNumber min={1} max={MAX_ITEMS_UPPER} precision={0} style={{ width: 160 }} addonAfter="条" />
          </Form.Item>
          <Text type="secondary">
            缺省 20（1-200）。单轮分析 run 最多复核的条目数：超出部分保持待决策，
            由下一轮的增量水位继续处理，用来给每轮的 LLM 成本封顶。
          </Text>
        </Form>
      </Card>

      {/* 7.3: 表格（移出卡片：小节标题与表格直接置于页签流内，与上方「建议改进项」
          标题同构；仍保留移动端横向滚动 + 操作列 fixed right） */}
      <h3 style={{ marginTop: 20 }}>条目列表</h3>

      {/* 7.6: 过滤条（第一行）+ 批量操作（第二行，右对齐）
          刻意分两行：过滤控件与三个批量按钮同排时总宽超出面板可用宽度，
          会把「批量同意」挤出可视区（实测被裁） */}
      <div style={{ marginBottom: 12 }}>
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8, alignItems: 'center', marginBottom: 8 }}>
        <Select
          placeholder="状态"
          allowClear
          style={{ width: 140 }}
          value={filterStatus}
          onChange={setFilterStatus}
          options={statusOptions}
          data-testid="evolution-filter-status"
        />
        <Select
          placeholder="项目"
          allowClear
          style={{ width: 140 }}
          value={filterProject}
          onChange={setFilterProject}
          options={projectOptions}
          data-testid="evolution-filter-project"
        />
        <DatePicker.RangePicker
          value={filterDateRange}
          onChange={(range) => setFilterDateRange(range as [Dayjs, Dayjs] | null)}
          placeholder={['起始日期', '结束日期']}
          data-testid="evolution-filter-date"
        />
        {hasFilter && (
          <Button type="link" onClick={resetFilters} data-testid="evolution-filter-reset">
            重置
          </Button>
        )}
        </div>
        <div style={{ display: 'flex', gap: 8, justifyContent: 'flex-end' }}>
        <Button
          disabled={selectedRowKeys.length === 0 || batchRunning}
          loading={batchRunning}
          onClick={() => runBatch('accept')}
          data-testid="evolution-batch-accept"
        >
          批量同意{selectedRowKeys.length > 0 ? `(${selectedRowKeys.length})` : ''}
        </Button>
        <Button
          danger
          disabled={selectedRowKeys.length === 0 || batchRunning}
          onClick={() => runBatch('reject')}
          data-testid="evolution-batch-reject"
        >
          批量拒绝{selectedRowKeys.length > 0 ? `(${selectedRowKeys.length})` : ''}
        </Button>
        <Button
          danger
          disabled={selectedRowKeys.length === 0 || batchRunning}
          onClick={() => runBatch('delete')}
          data-testid="evolution-batch-delete"
        >
          批量删除{selectedRowKeys.length > 0 ? `(${selectedRowKeys.length})` : ''}
        </Button>
        </div>
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
        locale={{ emptyText: hasFilter ? '没有符合过滤条件的条目' : '暂无建议改进项' }}
      />

      {/* 7.5: 查看分析结论弹窗（形态对齐 SPEC 列表页「文档」弹窗） */}
      <Modal
        title={
          <MaximizeTitle
            text={analysisItem ? `分析结论 — ${analysisItem.title}` : '分析结论'}
            button={analysisMaximizeButton}
          />
        }
        open={analysisVisible}
        onCancel={() => setAnalysisVisible(false)}
        footer={null}
        {...analysisModalProps}
      >
        <MarkdownBody
          loading={analysisLoading}
          error={analysisError}
          emptyText="（空）"
          content={analysisContent}
          onRetry={() => analysisItem && openAnalysis(analysisItem)}
        />
      </Modal>

      {/* 7.5: 查看 SPEC 草稿弹窗（四文档页签，形态对齐「文档」弹窗） */}
      <Modal
        title={
          <MaximizeTitle
            text={draftItem ? `SPEC 草稿 — ${draftItem.title}` : 'SPEC 草稿'}
            button={draftMaximizeButton}
          />
        }
        open={draftVisible}
        onCancel={() => setDraftVisible(false)}
        footer={null}
        {...draftModalProps}
      >
        <Tabs
          activeKey={draftDoc}
          onChange={(key) => setDraftDoc(key as EvolutionDoc)}
          items={EVOLUTION_DOCS.map((doc) => ({
            key: doc,
            label: EVOLUTION_DOC_LABELS[doc],
          }))}
        />
        <div style={{ flex: 1, minHeight: 0 }}>
          <MarkdownBody
            loading={draftLoading}
            error={draftError}
            emptyText={draftFound ? '（空）' : '草稿文档不存在或已被接受删除。'}
            content={draftContent}
            onRetry={() => draftItem && loadDraft(draftItem, draftDoc)}
          />
        </div>
      </Modal>
    </div>
  );
});

export default SuggestedImprovementsPanel;
