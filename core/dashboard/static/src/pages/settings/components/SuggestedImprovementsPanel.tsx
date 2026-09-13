/**
 * 建议改进项面板（add-framework-self-evolution 7.2-7.5）
 *
 * 设置页「自进化」页签下的第二张卡片。展示跨项目建议改进项表格，
 * 支持配置自进化开关 / 每轮上限、查看分析结论与草稿、同意立项 / 拒绝。
 *
 * 7.2: 顶部配置（用户级可写 / 项目级只读 + 全局键提示）
 * 7.3: 表格（列序：项目 / 日期 / 类别 / 问题 / 评估结论 / 状态 / 操作）
 * 7.4: 操作列「更多」下拉（复用 projects/list.tsx 形态）+ 二次确认弹窗
 * 7.5: 查看分析结论（Drawer）/ 查看草稿（Drawer + 四文档切换）+ 接受拒绝反馈
 */
import { Button, Card, Dropdown, Drawer, Form, InputNumber, message, Modal, Space, Spin, Switch, Table, Tag, Tooltip, Typography } from 'antd';
import { MoreOutlined } from '@ant-design/icons';
import Markdown from 'react-markdown';
import type { MenuProps } from 'antd';
import { forwardRef, useCallback, useEffect, useImperativeHandle, useMemo, useRef, useState } from 'react';
import type { ConfigData, EvolutionItem, EvolutionDoc } from '@/services/dashboard';
import type { SelfEvolutionSectionHandle } from './selfEvolutionSection';
import {
  EVOLUTION_STATUS_LABELS,
  EVOLUTION_DOCS,
  getEvolutionItems,
  getEvolutionAnalysis,
  getEvolutionDraft,
  acceptEvolutionItem,
  rejectEvolutionItem,
} from '@/services/dashboard';

const { Text } = Typography;

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
] as const;

function getActionDisabled(status: string): Record<string, boolean> {
  // analyzed / draft_failed：禁用「查看 SPEC 草稿」与「同意」；
  // analyzed 另禁用「拒绝」（仅可查看结论）；
  // accepted / auto_accepted / rejected：禁用「同意」与「拒绝」；
  // pending / accept_failed：全部可用（accept_failed 可重试同意、可拒绝）。
  const analyzed = status === 'analyzed';
  const draftFailed = status === 'draft_failed';
  const decided = status === 'accepted' || status === 'auto_accepted' || status === 'rejected';
  return {
    analysis: false,
    draft: analyzed || draftFailed,
    accept: analyzed || draftFailed || decided,
    reject: analyzed || decided,
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

  // ── 查看分析结论（7.5）──────────────────────────────────────────

  const [analysisVisible, setAnalysisVisible] = useState(false);
  const [analysisContent, setAnalysisContent] = useState('');
  const [analysisLoading, setAnalysisLoading] = useState(false);
  const [analysisError, setAnalysisError] = useState<string | null>(null);
  const [analysisTitle, setAnalysisTitle] = useState('');

  const openAnalysis = async (item: EvolutionItem) => {
    setAnalysisVisible(true);
    setAnalysisTitle(`分析结论 — ${item.title}`);
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
        try {
          const result = await acceptEvolutionItem(item.id);
          if (result.ok) {
            message.success(`已立项：${result.spec_name || item.title}`);
          } else {
            message.error(result.error || '接受失败');
          }
        } catch (e: any) {
          message.error(e?.message || '接受失败');
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
        try {
          const result = await rejectEvolutionItem(item.id);
          if (result.ok) {
            message.success('已拒绝');
          } else {
            message.error(result.error || '拒绝失败');
          }
        } catch (e: any) {
          message.error(e?.message || '拒绝失败');
        }
        loadItems();
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
      },
    }));
  };

  // ── 表格列（7.3）──────────────────────────────────────────────────

  const columns = [
    { title: '项目', dataIndex: 'project', key: 'project', width: 100, ellipsis: true },
    { title: '日期', dataIndex: 'date_section', key: 'date_section', width: 110 },
    { title: '类别', dataIndex: 'section', key: 'section', width: 70 },
    {
      title: '问题', dataIndex: 'title', key: 'title', ellipsis: true,
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

      {/* 7.3: 表格（移动端横向滚动 + 操作列 fixed right） */}
      <Card title="条目列表">
        {error && <div style={{ marginBottom: 12, color: '#ff4d4f' }}>加载失败：{error}</div>}
        <Table
          dataSource={items}
          columns={columns}
          rowKey="id"
          loading={loading}
          scroll={{ x: 800 }}
          pagination={items.length > 20 ? { pageSize: 20, showSizeChanger: false } : false}
          locale={{ emptyText: '暂无建议改进项' }}
        />
      </Card>

      {/* 7.5: 查看分析结论 Drawer */}
      <Drawer
        title={analysisTitle}
        open={analysisVisible}
        onClose={() => setAnalysisVisible(false)}
        width={640}
      >
        {analysisLoading && <Spin />}
        {analysisError && <div style={{ color: '#ff4d4f' }}>{analysisError}</div>}
        {!analysisLoading && !analysisError && analysisVisible && (
          analysisContent ? (
            <Markdown>{analysisContent}</Markdown>
          ) : (
            <Text type="secondary">（空）</Text>
          )
        )}
      </Drawer>

      {/* 7.5: 查看 SPEC 草稿 Drawer（四文档切换） */}
      <Drawer
        title={draftItem ? `SPEC 草稿 — ${draftItem.title}` : 'SPEC 草稿'}
        open={draftVisible}
        onClose={() => setDraftVisible(false)}
        width={640}
        extra={
          <Space size={4} wrap>
            {EVOLUTION_DOCS.map((doc) => (
              <Button
                key={doc}
                type={draftDoc === doc ? 'primary' : 'default'}
                size="small"
                onClick={() => setDraftDoc(doc)}
              >
                {doc === 'proposal' ? 'Proposal' : doc === 'design' ? 'Design'
                  : doc === 'tasks' ? 'Tasks' : 'Spec'}
              </Button>
            ))}
          </Space>
        }
      >
        {draftLoading && <Spin />}
        {draftError && <div style={{ color: '#ff4d4f' }}>{draftError}</div>}
        {!draftLoading && !draftError && !draftFound && (
          <Text type="secondary">草稿文档不存在或已被接受删除。</Text>
        )}
        {!draftLoading && !draftError && draftFound && draftVisible && (
          draftContent ? (
            <Markdown>{draftContent}</Markdown>
          ) : (
            <Text type="secondary">（空）</Text>
          )
        )}
      </Drawer>
    </div>
  );
});

export default SuggestedImprovementsPanel;
