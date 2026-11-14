import { App, Button, Checkbox, Input, Modal, Select, Space, Typography } from 'antd';
import { DeleteOutlined, PlusOutlined } from '@ant-design/icons';
import { useEffect, useRef, useState } from 'react';
import { quickAssignConfig } from '@/services/dashboard';
import type { LlmProvider, QuickAssignResponse, QuickAssignResult } from '@/services/dashboard';
import { buildQuickAssignAssignment, buildQuickAssignTargets, type ChainRow } from '@/utils/agentModels';
import { anyPanelDirty } from '../panelDirty';
import { useIsMobile } from '@/hooks/useIsMobile';
// 状态/错误色取宿主对齐单源（theme.ts；DESIGN.md「配色单源」红线）
import { DSH_ERROR, DSH_SUCCESS, DSH_TEXT_SECONDARY, DSH_TEXT_TERTIARY } from '@/theme';

const { Text } = Typography;

/** 候选链行 + 前端渲染用稳定 id（code-review item a36ecf597353）：下标作 key
 * 时删中间行会使后续行键整体平移，antd Select 的非受控搜索态/焦点错位到相邻
 * 行。id 仅作 React key，不进提交载荷——buildQuickAssignAssignment 构造请求体
 * 时只挑 provider/model 字段。 */
interface QuickAssignRow extends ChainRow {
  id: number;
}

/** 单目标结果 → 用户可读标签（「用户级」/「项目 <名称>」） */
function targetLabel(r: QuickAssignResult): string {
  return r.scope === 'user' ? '用户级' : `项目 ${r.project}`;
}

// 弹窗内容拆出纯展示组件（default export 持状态并与 Modal 组装）：antd Modal
// 走 Portal，静态 SSR（renderToStaticMarkup）不落弹层内容——控件断言须能
// 直接渲染 body/footer，故模板编辑器/作用域区/结果与页脚按钮各为独立导出
// 的展示组件（props 全量注入，零内部状态）。
export interface QuickAssignModalBodyProps {
  project?: string;
  projects: string[];
  providers: LlmProvider[];
  roleModel: string;
  rows: QuickAssignRow[];
  includeCurrent: boolean;
  includeProjects: boolean;
  selectedProjects: string[];
  result: QuickAssignResponse | null;
  saving: boolean;
  onRoleModelChange: (v: string) => void;
  onRowChange: (index: number, patch: Partial<ChainRow>) => void;
  onAddRow: () => void;
  onRemoveRow: (index: number) => void;
  onIncludeCurrentChange: (v: boolean) => void;
  onIncludeProjectsChange: (v: boolean) => void;
  onSelectedProjectsChange: (v: string[]) => void;
}

/** 弹窗主体：分配模板编辑器 + 作用域选择 + 逐项目标结果（add-agent-model-quick-assign 5.1）。 */
export function QuickAssignModalBody({
  project,
  projects,
  providers,
  roleModel,
  rows,
  includeCurrent,
  includeProjects,
  selectedProjects,
  result,
  saving,
  onRoleModelChange,
  onRowChange,
  onAddRow,
  onRemoveRow,
  onIncludeCurrentChange,
  onIncludeProjectsChange,
  onSelectedProjectsChange,
}: QuickAssignModalBodyProps) {
  const isMobile = useIsMobile();
  const providerOptions = providers.map((p) => ({ value: p.name, label: p.name }));
  return (
    <>
      <div style={{ marginBottom: 8 }}>
        <Text strong>分配模板</Text>
        <div style={{ fontSize: 12, color: DSH_TEXT_TERTIARY, marginTop: 2 }}>
          将覆盖全部 Agent 角色的模型分配（原各角色分配被替换）；候选链行序即回退顺序。
        </div>
      </div>
      <div style={{ marginBottom: 12 }}>
        <Input
          data-testid="quick-assign-role-model"
          placeholder="角色默认模型（可选，留空不写缺省）"
          value={roleModel}
          onChange={(e) => onRoleModelChange(e.target.value)}
          style={{ marginBottom: 8 }}
        />
        {rows.map((row, index) => (
          <Space key={row.id} style={{ display: 'flex', marginBottom: 8 }} align="center">
            <Select
              data-testid={`quick-assign-row-provider-${index}`}
              style={{ width: isMobile ? 130 : 180 }}
              placeholder="Provider"
              value={row.provider || undefined}
              options={providerOptions}
              onChange={(v) => onRowChange(index, { provider: v || '' })}
              showSearch
            />
            <Input
              data-testid={`quick-assign-row-model-${index}`}
              style={{ width: isMobile ? 120 : 200 }}
              placeholder="模型（留空用 Provider 默认）"
              value={row.model}
              onChange={(e) => onRowChange(index, { model: e.target.value })}
            />
            <Button
              type="text"
              aria-label="删除此行"
              icon={<DeleteOutlined />}
              disabled={rows.length <= 1 || saving}
              onClick={() => onRemoveRow(index)}
            />
          </Space>
        ))}
        <Button
          type="dashed"
          block
          icon={<PlusOutlined />}
          data-testid="quick-assign-add-row"
          disabled={saving}
          onClick={onAddRow}
        >
          新增候选行
        </Button>
      </div>
      <div style={{ marginBottom: 8 }}>
        <Text strong>应用目标</Text>
      </div>
      <div style={{ marginBottom: 8 }}>
        <Checkbox
          data-testid="quick-assign-include-current"
          checked={includeCurrent}
          onChange={(e) => onIncludeCurrentChange(e.target.checked)}
        >
          本作用域（{project ? `项目 ${project}` : '用户级'}）
        </Checkbox>
      </div>
      <div style={{ marginBottom: 12 }}>
        <Checkbox
          data-testid="quick-assign-projects-toggle"
          checked={includeProjects}
          disabled={projects.length === 0}
          onChange={(e) => onIncludeProjectsChange(e.target.checked)}
        >
          指定项目
        </Checkbox>
        {includeProjects && projects.length > 0 && (
          <Select
            mode="multiple"
            data-testid="quick-assign-projects-select"
            style={{ width: '100%', marginTop: 8 }}
            placeholder="选择要写入的项目（可多选）"
            value={selectedProjects}
            options={projects.map((p) => ({ value: p, label: p }))}
            onChange={(v) => onSelectedProjectsChange(v)}
          />
        )}
      </div>
      {result && (
        <div data-testid="quick-assign-result">
          <Text strong>应用结果</Text>
          <div style={{ marginTop: 4 }}>
            {result.results.map((r, i) => (
              <div
                key={i}
                style={{
                  fontSize: 12,
                  color: r.ok ? DSH_SUCCESS : DSH_ERROR,
                  display: 'flex',
                  justifyContent: 'space-between',
                  gap: 8,
                  flexWrap: 'wrap',
                }}
              >
                <span>{`${targetLabel(r)}：${r.ok ? '成功' : '失败'}`}</span>
                {!r.ok && (
                  <span style={{ color: DSH_ERROR, flex: '1 1 auto', minWidth: 0 }}>
                    {r.error || '未知错误'}
                  </span>
                )}
              </div>
            ))}
            {result.ok && (
              <div style={{ fontSize: 12, color: DSH_TEXT_SECONDARY, marginTop: 4 }}>
                成功写入 {result.results.filter((r) => r.ok).length} 个目标，重启 daemon 后生效。
              </div>
            )}
          </div>
        </div>
      )}
    </>
  );
}

/** 弹窗页脚按钮（取消/应用）。无有效 provider 行或无目标时应用禁用
 * （spec「MUST NOT 发起写入」）；saving 时 loading + disabled 防重入。 */
export function QuickAssignModalFooter({
  canApply,
  saving,
  onCancel,
  onApply,
}: {
  canApply: boolean;
  saving: boolean;
  onCancel: () => void;
  onApply: () => void;
}) {
  return (
    <Space>
      <Button data-testid="quick-assign-cancel" disabled={saving} onClick={onCancel}>
        取消
      </Button>
      <Button
        type="primary"
        data-testid="quick-assign-apply"
        loading={saving}
        disabled={!canApply}
        onClick={onApply}
      >
        应用
      </Button>
    </Space>
  );
}

interface QuickAssignModalProps {
  open: boolean;
  /** 当前设置页作用域的项目名；用户级作用域为 undefined（决定「本作用域」标签与 source_scope） */
  project?: string;
  /** 已注册项目名列表（「指定项目」多选来源，来自 dashboard 项目列表） */
  projects: string[];
  /** 当前作用域有效 provider 定义（provider 下拉来源，与服务端补齐定义同域） */
  providers: LlmProvider[];
  onCancel: () => void;
  /** 应用结束（无论成败）回调：父组件按结果决定是否重载当前作用域配置 */
  onApplied: (result: QuickAssignResponse) => void;
}

/**
 * 「快速分配」弹窗（add-agent-model-quick-assign 5.1）：编辑一份分配模板
 * （角色级默认模型 + provider+模型候选链，与单角色分配同语义），应用时由
 * 后端把 ConfigLoader.KNOWN_AGENT_TYPES 全部角色的 agents.models 整体覆盖
 * 为该模板（原各角色分配被替换，不合并）。
 *
 * 应用前确认：目标含本作用域且面板存在未保存修改时，提示覆盖/丢弃确认
 * （spec「未保存修改先确认」），取消则不发起写入。防重入比照
 * SyncFromUserButton 的 inFlight ref 口径（setSaving 渲染间隙拦不住同帧双击）。
 *
 * 静态渲染约束（DESIGN.md）：本组件不引入任何 CSS 动画/过渡（quickAssign
 * 测试有源码检查守卫）；移动端 body 限高滚动、footer 按钮保持可达。
 */
export default function QuickAssignModal({
  open,
  project,
  projects,
  providers,
  onCancel,
  onApplied,
}: QuickAssignModalProps) {
  // 反馈与确认弹窗经 App.useApp() 取上下文实例：静态 message / Modal.confirm
  // 不消费 App/ConfigProvider 上下文（比照 SystemPanel item 6836d264fde4 口径），
  // 应用前覆盖确认的 modal 与 message 同取上下文实例（item 84564e6bbdbe）
  const { message, modal } = App.useApp();
  const isMobile = useIsMobile();

  // 模板编辑状态：角色级默认模型 + 候选链行（行序即回退顺序，至少保留一行）
  const [roleModel, setRoleModel] = useState('');
  // 行创建时经计数器发号稳定 id（useRef 计数即可，避免 crypto.randomUUID 兼容面）；
  // 初始值用惰性初始化，保证 makeRow 只在首次挂载时调用
  const nextRowId = useRef(1);
  const makeRow = (): QuickAssignRow => ({ id: nextRowId.current++, provider: '', model: '' });
  const [rows, setRows] = useState<QuickAssignRow[]>(() => [makeRow()]);
  // 作用域选择：本作用域（默认勾选）+ 指定项目（勾选联动多选，取消勾选清空已选）
  const [includeCurrent, setIncludeCurrent] = useState(true);
  const [includeProjects, setIncludeProjects] = useState(false);
  const [selectedProjects, setSelectedProjects] = useState<string[]>([]);
  // 应用结果（逐项目标展示；不自动关弹窗，用户看清成败后自行关闭）
  const [result, setResult] = useState<QuickAssignResponse | null>(null);
  const [saving, setSaving] = useState(false);
  // 重入守卫（SyncFromUserButton 同款 inFlight ref 口径）：state 写读存在
  // React 调度间隙，同帧双击会并发发出第二个写盘请求（spec「重复提交防护」）
  const inFlight = useRef(false);

  // 每次打开重置为初始模板（弹窗内临时模板，不做持久化——design Non-Goals）
  useEffect(() => {
    if (open) {
      setRoleModel('');
      setRows([makeRow()]);
      setIncludeCurrent(true);
      setIncludeProjects(false);
      setSelectedProjects([]);
      setResult(null);
      setSaving(false);
      inFlight.current = false;
    }
  }, [open]);

  // projects 异步收缩对账（code-review item dc9aefa16af2）：弹窗打开期间父组件
  // 重载 projects 列表收缩（某项目被注销）时，「指定项目」Select 整体不渲染，
  // 但 selectedProjects 仍保留已失效项目名且 targets 会把它们继续发往后端——
  // projects 变化即把已选集与可用列表求交集兜底（打开时的重置 effect 已清空
  // 选中，此处只兜打开后的收缩窗口）。
  useEffect(() => {
    setSelectedProjects((prev) => {
      const next = prev.filter((p) => projects.includes(p));
      return next.length === prev.length ? prev : next;
    });
  }, [projects]);

  const validRows = rows.filter((r) => (r?.provider || '').trim());
  const targets = buildQuickAssignTargets(
    includeCurrent,
    project,
    includeProjects ? selectedProjects : [],
  );
  // 无有效 provider 行或无目标时禁止应用（spec「MUST NOT 发起写入」）
  const canApply = validRows.length > 0 && targets.length > 0 && !saving;

  const doApply = async () => {
    if (inFlight.current) return;
    inFlight.current = true;
    setSaving(true);
    try {
      const payload = {
        assignment: buildQuickAssignAssignment(roleModel, rows),
        targets,
        // source_scope 与弹窗 provider 下拉同域（design D3/D6）：用户级
        // {"scope":"user"}、项目级 {"scope":"project","project":<当前项目>}
        source_scope: project ? { scope: 'project' as const, project } : { scope: 'user' as const },
      };
      const res = await quickAssignConfig(payload);
      setResult(res);
      onApplied(res);
    } catch {
      // 通用口径（对齐 SyncFromUserButton）：services 抛出的错误文本含传输/
      // 后端细节，不上 toast；settings 页 web 场景携带 no_console_error 断言，
      // 失败路径不落 console（曾留 console.error 致确定性误报）
      message.error('快速分配失败，请稍后重试');
    } finally {
      inFlight.current = false;
      setSaving(false);
    }
  };

  const handleApply = () => {
    if (!canApply) return;
    const includesCurrentScope = targets.some(
      (t) => t.scope === 'user' || (t.scope === 'project' && t.project === project),
    );
    // 应用前确认：目标含本作用域且当前面板有未保存修改 → 提示将覆盖/丢弃
    // （spec「未保存修改先确认」），取消则不发起写入
    if (includesCurrentScope && anyPanelDirty()) {
      // 上下文实例 modal（同 SystemPanel）：脱离静态 API 的主题上下文局限
      modal.confirm({
        title: '应用快速分配',
        content: '快速分配将覆盖全部角色的模型分配，并丢弃当前未保存的修改。确定继续？',
        okText: '应用',
        cancelText: '取消',
        onOk: doApply,
      });
      return;
    }
    void doApply();
  };

  return (
    <Modal
      title="快速分配"
      open={open}
      onCancel={onCancel}
      // saving 中同步禁用 X / ESC / mask 关闭（对齐 SyncFromUserButton 防旁路口径）
      closable={!saving}
      keyboard={!saving}
      maskClosable={!saving}
      width={isMobile ? 'calc(100vw - 32px)' : 560}
      centered
      data-testid="quick-assign-modal"
      styles={{
        // 移动端可完整滚动（task 6.4）：body 限高滚动、footer 常驻可达
        body: { maxHeight: 'calc(100vh - 220px)', overflowY: 'auto' },
      }}
      footer={
        <QuickAssignModalFooter
          canApply={canApply}
          saving={saving}
          onCancel={onCancel}
          onApply={handleApply}
        />
      }
    >
      <QuickAssignModalBody
        project={project}
        projects={projects}
        providers={providers}
        roleModel={roleModel}
        rows={rows}
        includeCurrent={includeCurrent}
        includeProjects={includeProjects}
        selectedProjects={selectedProjects}
        result={result}
        saving={saving}
        onRoleModelChange={setRoleModel}
        onRowChange={(index, patch) =>
          setRows((prev) => prev.map((r, i) => (i === index ? { ...r, ...patch } : r)))
        }
        onAddRow={() => {
          const row = makeRow();
          setRows((prev) => [...prev, row]);
        }}
        onRemoveRow={(index) => setRows((prev) => prev.filter((_, i) => i !== index))}
        onIncludeCurrentChange={setIncludeCurrent}
        onIncludeProjectsChange={(v) => {
          setIncludeProjects(v);
          if (!v) setSelectedProjects([]);
        }}
        onSelectedProjectsChange={setSelectedProjects}
      />
    </Modal>
  );
}
