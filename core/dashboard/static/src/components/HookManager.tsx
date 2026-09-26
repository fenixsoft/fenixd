/**
 * HookManager — 共享 hook 管理组件（add-spec-hooks）。
 *
 * 功能：
 *  1. hook 列表（含可选来源列「全局/本 spec」、启停 Switch）
 *  2. 新增/编辑 Modal（事件多选 Select、动作下拉、按动作类型显隐参数
 *     url / command / message / timeout_seconds / target）
 *  3. 最近执行记录列表（时间 / 动作 / 结果 Tag / 耗时 / 摘要）
 *
 * 本组件不直接调用 API——通过 props 管理数据，由页面（设置页 / spec 详情页）
 * 统一读写 config hooks 段，避免跨组件状态碎片。
 */

import { DeleteOutlined, EditOutlined } from '@ant-design/icons';
import {
  App, Button, Form, Input, InputNumber, List, Modal, Popconfirm, Select, Space, Switch, Table, Tag, Tooltip, Typography,
} from 'antd';
import dayjs from 'dayjs';
import { useCallback, useState, useMemo } from 'react';
import { useIsMobile } from '@/hooks/useIsMobile';
import { HOOK_ACTION_LABELS } from '@/services/dashboard';
import type { HookAction, HookAuditRecord, HookConfig } from '@/services/dashboard';

const { Text, Title } = Typography;

const ALL_EVENTS: string[] = [
  'drafted', 'ready', 'reviewing', 'implementing', 'implemented',
  'testing', 'verified', 'bug-found', 'blocked', 'done', 'pushed',
];

const EVENT_LABELS: Record<string, string> = {
  drafted: '草稿',
  ready: '就绪',
  // add-spec-review-gate D1：reviewing 状态可被 hook 订阅（状态 diff 驱动）
  reviewing: '评审中',
  implementing: '实现中',
  implemented: '已实现',
  testing: '验证中',
  verified: '已验证',
  'bug-found': '有Bug',
  blocked: '阻塞',
  done: '完成',
  pushed: '已推送',
  // 项目级伪事件（fix-hook-all-specs-done）：全部 SPEC 均处 done/pushed 终态时触发，
  // 仅全局作用域（HookManager allowProjectEvent）可选，spec 级订阅被后端忽略
  'all-done': '全部SPEC完成',
};

const AUDIT_STATUS_COLORS: Record<string, string> = {
  success: 'green',
  failure: 'red',
  noop: 'blue',
  skipped: 'default',
};

const AUDIT_STATUS_LABELS: Record<string, string> = {
  success: '成功',
  failure: '失败',
  noop: '无操作',
  skipped: '跳过',
};

// 碰撞防护（code-review item b5e257b67e9e）：纯 Math.random 6 字符无唯一性
// 保证，id 碰撞后果是 React key 告警与渲染复用异常；改用「时间戳 + 会话内
// 单调计数器」保证确定唯一。不用 crypto.randomUUID——非安全上下文（http
// 访问 dashboard）下不可用，会直接抛错。
let shortIdSeq = 0;
function shortId(): string {
  return `h-${Date.now().toString(36)}-${(shortIdSeq += 1).toString(36)}`;
}

function paramSummary(h: HookConfig): string {
  switch (h.action) {
    case 'webhook': return h.url || '';
    case 'shell': return h.command || '';
    case 'commit':
    case 'commit-push': return h.message || '';
    case 'restart-dashboard': return h.target || '';
    default: return '';
  }
}

// ── Props ──────────────────────────────────────────────────────────

export interface HookManagerProps {
  /** 被管理作用域的 hooks（settings 传 hooks.global；spec 传 hooks.specs[spec]） */
  hooks: HookConfig[];
  /** 保存回调：传入更新后的列表（由页面 patch config.hooks 再调 saveConfig） */
  onSave: (next: HookConfig[]) => Promise<void> | void;
  saving?: boolean;
  /** 生效合并视图（可选，来源标注列）——spec 详情页传入；含此 prop 时额外渲染合并表 */
  effective?: Array<{ hook: HookConfig; source: 'global' | 'spec' }>;
  /** 最近执行记录（spec 面板已按 spec 过滤；全局面板跨 spec） */
  audit: HookAuditRecord[];
  auditLoading?: boolean;
  /** 是否隐藏生效合并视图（settings 全局面板无需） */
  hideEffective?: boolean;
  /** 终态只读：禁用所有编辑/删除操作，隐藏新增按钮 */
  readOnly?: boolean;
  /** 是否开放项目级伪事件 all-done（fix-hook-all-specs-done）：仅全局面板为 true */
  allowProjectEvent?: boolean;
}

// ── 组件 ──────────────────────────────────────────────────────────

export default function HookManager({
  hooks,
  onSave,
  saving,
  effective,
  audit,
  auditLoading,
  hideEffective,
  readOnly,
  allowProjectEvent,
}: HookManagerProps) {
  const [editIdx, setEditIdx] = useState<number | null>(null);
  const [modalOpen, setModalOpen] = useState(false);
  const [form] = Form.useForm();
  const { message } = App.useApp();
  const isMobile = useIsMobile();

  const editingAction = Form.useWatch('action', form);

  // 保存窗口并发门控（code-review item 00869eda38f3）：启停/删除/编辑新增都从
  // hooks prop 同步算 next 再交 onSave 异步落盘，saving 期间父组件尚未回写
  // hooks prop，此窗口内再操作会基于旧列表计算、后落盘者整体覆盖丢失前一笔
  // （快速停用两行/连删两行）。落盘期间禁用全部变更入口——两个调用方的
  // saving 均贯穿保存全程（HTTP 往返 + config 回写同批完成），门控无隙
  // （对齐 QualityTab ignorePending 门控模式）。
  const opLocked = readOnly || !!saving;

  const handleAdd = () => {
    setEditIdx(null);
    form.resetFields();
    form.setFieldsValue({ enabled: true, events: [], action: 'commit' });
    setModalOpen(true);
  };

  // 事件处理 useCallback 化（code-review item 0383473dd260）：columns 的
  // useMemo 闭包捕获这三个函数——不固定引用并列入依赖时，父组件更新 onSave
  // 引用而 hooks 未变会导致表格按钮持有旧 onSave 闭包（写入过期 props）。
  const handleEdit = useCallback(
    (idx: number) => {
      setEditIdx(idx);
      const h = hooks[idx];
      form.setFieldsValue({
        events: h.events,
        action: h.action,
        enabled: h.enabled !== false,
        url: h.url || '',
        command: h.command || '',
        message: h.message || '',
        timeout_seconds: h.timeout_seconds,
        target: h.target || '',
      });
      setModalOpen(true);
    },
    [hooks, form],
  );

  // 删除/启停与 handleSubmit 同款错误口径（code-review item c31395922dc3）：
  // 同步调用丢弃 Promise 时保存失败无任何反馈且可能 unhandled rejection；
  // 组件内无本地乐观更新（hooks 由父组件回写），失败仅补错误提示即可
  const handleDelete = useCallback(
    async (idx: number) => {
      const next = hooks.filter((_, i) => i !== idx);
      try {
        await onSave(next);
      } catch (e) {
        message.error(`保存失败：${e instanceof Error ? e.message : e}`);
      }
    },
    [hooks, onSave, message],
  );

  const handleToggle = useCallback(
    async (idx: number, checked: boolean) => {
      const next = hooks.map((h, i) => (i === idx ? { ...h, enabled: checked } : h));
      try {
        await onSave(next);
      } catch (e) {
        message.error(`保存失败：${e instanceof Error ? e.message : e}`);
      }
    },
    [hooks, onSave, message],
  );

  const handleSubmit = () => {
    form.validateFields().then(async (values) => {
      const entry: HookConfig = {
        id: editIdx !== null ? hooks[editIdx].id : shortId(),
        enabled: values.enabled !== false,
        events: values.events,
        action: values.action,
        url: values.url || undefined,
        command: values.command || undefined,
        message: values.message || undefined,
        timeout_seconds: values.timeout_seconds || undefined,
        target: values.target || undefined,
      };
      let next: HookConfig[];
      if (editIdx !== null) {
        next = hooks.map((h, i) => (i === editIdx ? entry : h));
      } else {
        next = [...hooks, entry];
      }
      // 等 onSave 完成再关 Modal（code-review item aae592c70283）：destroyOnClose
      // + preserve=false 下提前关闭会销毁表单丢用户编辑内容；失败保持打开可重试
      try {
        await onSave(next);
        setModalOpen(false);
      } catch (e) {
        message.error(`保存失败：${e instanceof Error ? e.message : e}`);
      }
    })
    .catch((e) => {
      // 校验不通过时 validateFields 会 reject（带 errorFields 属性，错误已由表单字段提示），
      // 静默吞掉避免 unhandled rejection；其余为 .then 回调内的运行时异常（如弹窗打开期间
      // hooks prop 收缩致 editIdx 越界），不能同路静默——补日志并给出保存失败提示（口径对齐 handleDelete/handleToggle）
      if (e && typeof e === 'object' && 'errorFields' in e) return;
      console.error('[HookManager] 保存 hook 失败', e);
      message.error(`保存失败：${e instanceof Error ? e.message : e}`);
    });
  };

  // ── 列表表格列 ──────────────────────────────────────────────────

  const columns = useMemo(() => {
    const cols = [
      {
        title: '事件',
        dataIndex: 'events',
        key: 'events',
        width: '18.6%',
        render: (events: string[]) => (
          <Space wrap size={4}>
            {events.map((ev) => (
              <Tag key={ev} color="blue">
                {EVENT_LABELS[ev] || ev}
              </Tag>
            ))}
          </Space>
        ),
      },
      {
        title: '动作',
        dataIndex: 'action',
        key: 'action',
        width: '41.3%',
        render: (a: HookAction | string) => HOOK_ACTION_LABELS[a as HookAction] || a,
      },
      {
        title: '参数',
        dataIndex: 'action',
        key: 'param',
        width: '25.6%',
        // 换行渲染（对齐执行记录摘要列口径）：ellipsis+maxWidth 会截断长
        // webhook URL/command；配合 tableLayout fixed 定宽，超宽文本换行展示
        render: (_: unknown, record: HookConfig) => (
          <Text
            type="secondary"
            style={{ display: 'block', whiteSpace: 'pre-wrap', wordBreak: 'break-all' }}
          >
            {paramSummary(record)}
          </Text>
        ),
      },
      {
        title: '启停',
        dataIndex: 'enabled',
        key: 'enabled',
        width: '6.8%',
        render: (_: unknown, __: HookConfig, idx: number) => (
          <Switch
            size="small"
            disabled={opLocked}
            checked={hooks[idx].enabled !== false}
            onChange={(checked) => handleToggle(idx, checked)}
          />
        ),
      },
      {
        title: '操作',
        key: 'actions',
        width: '7.6%',
        // 终态只读（与移动端口径一致）：隐藏编辑/删除，仅留禁用的启停 Switch
        render: (_: unknown, __: HookConfig, idx: number) => (
          readOnly ? null : (
            <Space size={4}>
              <Tooltip title="编辑">
                <Button type="link" size="small" icon={<EditOutlined />} disabled={opLocked} onClick={() => handleEdit(idx)} />
              </Tooltip>
              <Popconfirm title="确定删除？" onConfirm={() => handleDelete(idx)} okText="删除" cancelText="取消">
                <Button type="link" size="small" danger icon={<DeleteOutlined />} disabled={opLocked} />
              </Popconfirm>
            </Space>
          )
        ),
      },
    ];
    return cols;
    // eslint-disable-next-line react-hooks/exhaustive-deps — handlers 已 useCallback 化并列入依赖（item 0383473dd260）
  }, [hooks, form, handleToggle, handleEdit, handleDelete, readOnly, opLocked]);

  // ── 生效合并表格列（仅 spec 详情页）────────────────────────────

  // 生效合并表格列（仅 spec 详情页）。
  // 列宽口径：事件列实测 732px 收缩为 1/4（183）；腾出的宽度连同动作列
  // 原有宽度由动作列与参数列等宽平分（各 360），固定列总宽守恒。
  // 与主表格 columns 同口径 memo 化（item de988bb5e41f）：列定义仅依赖模块级
  // 常量（EVENT_LABELS/HOOK_ACTION_LABELS/paramSummary），依赖数组为空即可
  const effectiveColumns = useMemo(() => [
    {
      title: '来源',
      dataIndex: 'source',
      key: 'source',
      width: 80,
      render: (s: string) => (
        <Tag color={s === 'global' ? 'orange' : 'purple'}>{s === 'global' ? '全局' : '本 SPEC'}</Tag>
      ),
    },
    {
      title: '事件',
      dataIndex: 'hook.events',
      key: 'events',
      width: 183,
      render: (_: unknown, r: { hook: HookConfig }) => (
        <Space wrap size={4}>
          {r.hook.events.map((ev) => (
            <Tag key={ev} color="blue">
              {EVENT_LABELS[ev] || ev}
            </Tag>
          ))}
        </Space>
      ),
    },
    {
      title: '动作',
      dataIndex: 'hook.action',
      key: 'action',
      width: 360,
      render: (_: unknown, r: { hook: HookConfig }) => HOOK_ACTION_LABELS[r.hook.action as HookAction] || r.hook.action,
    },
    {
      title: '参数',
      key: 'param',
      width: 360,
      render: (_: unknown, r: { hook: HookConfig }) => (
        <Text type="secondary" ellipsis style={{ maxWidth: 320 }}>
          {paramSummary(r.hook)}
        </Text>
      ),
    },
    {
      title: '状态',
      key: 'enabled',
      width: 72,
      render: (_: unknown, r: { hook: HookConfig }) => (
        <Tag color={r.hook.enabled !== false ? 'green' : 'default'}>
          {r.hook.enabled !== false ? '启用' : '停用'}
        </Tag>
      ),
    },
  ], []);

  return (
    <div>
      {/* ── 生效合并视图（spec 详情页，含来源标注） ───────────── */}
      {!hideEffective && effective && effective.length > 0 && (
        <>
          <Title level={5} style={{ marginTop: 0 }}>生效中的 Hooks</Title>
          {isMobile ? (
            <List
              dataSource={effective.map((e, i) => ({ ...e, key: i }))}
              pagination={false}
              size="small"
              renderItem={(item: { hook: HookConfig; source: 'global' | 'spec'; key: number }) => (
                <List.Item>
                  <div style={{ width: '100%', minWidth: 0 }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
                      <Tag color={item.source === 'global' ? 'orange' : 'purple'}>
                        {item.source === 'global' ? '全局' : '本 SPEC'}
                      </Tag>
                      <Space wrap size={4}>
                        {item.hook.events.map((ev) => (
                          <Tag key={ev} color="blue">{EVENT_LABELS[ev] || ev}</Tag>
                        ))}
                      </Space>
                    </div>
                    <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginTop: 4, flexWrap: 'wrap' }}>
                      <Text strong>{HOOK_ACTION_LABELS[item.hook.action as HookAction] || item.hook.action}</Text>
                      <Tag color={item.hook.enabled !== false ? 'green' : 'default'}>
                        {item.hook.enabled !== false ? '启用' : '停用'}
                      </Tag>
                    </div>
                    {paramSummary(item.hook) && (
                      <Text type="secondary" style={{ display: 'block', marginTop: 4, wordBreak: 'break-all' }}>
                        {paramSummary(item.hook)}
                      </Text>
                    )}
                  </div>
                </List.Item>
              )}
            />
          ) : (
            <Table
              dataSource={effective.map((e, i) => ({ ...e, key: i }))}
              columns={effectiveColumns}
              pagination={false}
              size="small"
              rowKey="key"
              tableLayout="fixed"
              scroll={{ x: 'max-content' }}
              style={{ marginBottom: 24 }}
            />
          )}
        </>
      )}

      {/* ── Hook CRUD 列表 ──────────────────────────────────── */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 8 }}>
        <Title level={5} style={{ marginTop: 0 }}>Hook 列表</Title>
        {!readOnly && (
          <Button type="primary" onClick={handleAdd} disabled={opLocked}>
            新增 Hook
          </Button>
        )}
      </div>
      {hooks.length === 0 ? (
        <Text type="secondary">暂无 Hook 订阅</Text>
      ) : isMobile ? (
        <List
          // 直接携带原始下标 idx（code-review item b1b8c06516be）：按 id 反查在
          // 无 id/重复 id 的 hook 上会永远命中第一条，误操作错误条目
          dataSource={hooks.map((h, i) => ({ ...h, key: `${h.id || 'idx'}-${i}`, idx: i }))}
          pagination={false}
          size="small"
          renderItem={(item: HookConfig & { key: string | number; idx: number }) => {
            const realIdx = item.idx;
            return (
              <List.Item>
                <div style={{ width: '100%', minWidth: 0 }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
                    <Space wrap size={4}>
                      {item.events.map((ev) => (
                        <Tag key={ev} color="blue">{EVENT_LABELS[ev] || ev}</Tag>
                      ))}
                    </Space>
                    <Switch
                      size="small"
                      disabled={opLocked}
                      checked={item.enabled !== false}
                      onChange={(checked) => handleToggle(realIdx, checked)}
                    />
                  </div>
                  <div style={{ marginTop: 4 }}>
                    <Text strong>{HOOK_ACTION_LABELS[item.action as HookAction] || item.action}</Text>
                  </div>
                  {paramSummary(item) && (
                    <Text type="secondary" style={{ display: 'block', marginTop: 4, wordBreak: 'break-all' }}>
                      {paramSummary(item)}
                    </Text>
                  )}
                  {!readOnly && (
                    <Space style={{ marginTop: 8 }}>
                      <Button type="link" size="small" icon={<EditOutlined />} disabled={opLocked} onClick={() => handleEdit(realIdx)}>
                        编辑
                      </Button>
                      <Popconfirm title="确定删除？" onConfirm={() => handleDelete(realIdx)} okText="删除" cancelText="取消">
                        <Button type="link" size="small" danger icon={<DeleteOutlined />} disabled={opLocked}>
                          删除
                        </Button>
                      </Popconfirm>
                    </Space>
                  )}
                  {readOnly && (
                    <Text type="secondary" style={{ display: 'block', marginTop: 8, fontSize: 12 }}>
                      SPEC 已推送（终态），订阅不再变化，仅供查看
                    </Text>
                  )}
                </div>
              </List.Item>
            );
          }}
        />
      ) : (
        <Table
          dataSource={hooks.map((h, i) => ({ ...h, key: `${h.id || 'idx'}-${i}` }))}
          columns={columns}
          pagination={false}
          size="small"
          rowKey="key"
          tableLayout="fixed"
          // 不用 scroll max-content；tableLayout fixed + 全列百分比定宽
          // （事件 18.6 / 动作 41.3 / 参数 25.6 / 启停 6.8 / 操作 7.6，
          // 1440 实测基准：参数列收到原弹性的 60%，40% 按原宽比例给事件/动作），
          // 各列随容器等比伸缩，长 URL/command 在参数列内换行
        />
      )}

      {/* ── 新增/编辑 Modal ─────────────────────────────────── */}
      <Modal
        title={editIdx !== null ? '编辑 Hook' : '新增 Hook'}
        open={modalOpen}
        onOk={handleSubmit}
        onCancel={() => setModalOpen(false)}
        okText={saving ? '保存中...' : '保存'}
        confirmLoading={saving}
        destroyOnHidden
        width={520}
      >
        <Form form={form} layout="vertical" preserve={false}>
          <Form.Item name="events" label="订阅事件" rules={[{ required: true, message: '请选择至少一个事件' }]}>
            <Select
              mode="multiple"
              placeholder="选择事件类型"
              options={(allowProjectEvent ? [...ALL_EVENTS, 'all-done'] : ALL_EVENTS)
                .map((ev) => ({ value: ev, label: `${EVENT_LABELS[ev] || ev}（${ev}）` }))}
            />
          </Form.Item>
          <Form.Item name="action" label="动作" rules={[{ required: true }]}>
            <Select
              options={Object.entries(HOOK_ACTION_LABELS).map(([k, v]) => ({ value: k, label: v }))}
            />
          </Form.Item>
          <Form.Item name="enabled" label="启用" valuePropName="checked">
            <Switch />
          </Form.Item>

          {/* ── 按动作类型显隐参数 ────────────────────────── */}
          {editingAction === 'webhook' && (
            <Form.Item
              name="url"
              label="Webhook URL"
              rules={[{ required: true, message: '请输入 POST 目标 URL' }]}
            >
              <Input placeholder="https://example.com/hook" />
            </Form.Item>
          )}
          {editingAction === 'shell' && (
            <Form.Item
              name="command"
              label="Shell 命令"
              rules={[{ required: true, message: '请输入 bash -c 执行的命令' }]}
            >
              <Input.TextArea placeholder="echo $FENIX_HOOK_EVENT > /tmp/hook.log" autoSize={{ minRows: 2, maxRows: 5 }} />
            </Form.Item>
          )}
          {(editingAction === 'commit' || editingAction === 'commit-push') && (
            <Form.Item name="message" label="提交信息模板（可选）" extra="变量：{spec} {event}；缺省 [fenix] hook: {spec} {event}">
              <Input placeholder="例如：[fenix] hook: {spec} {event}" />
            </Form.Item>
          )}
          {(editingAction === 'shell' || editingAction === 'webhook') && (
            <Form.Item name="timeout_seconds" label="超时（秒，可选）" extra={editingAction === 'webhook' ? '缺省 10' : '缺省 60'}>
              <InputNumber min={1} max={3600} style={{ width: '100%' }} addonAfter="秒" />
            </Form.Item>
          )}
          {editingAction === 'restart-dashboard' && (
            <Form.Item name="target" label="目标 tmux 会话（可选）" extra="缺省 fenix-dashboard">
              <Input placeholder="fenix-dashboard" />
            </Form.Item>
          )}
        </Form>
      </Modal>

      {/* ── 最近执行记录 ──────────────────────────────────────── */}
      <Title level={5} style={{ marginTop: 24 }}>最近执行</Title>
      {audit.length === 0 ? (
        <Text type="secondary">暂无执行记录</Text>
      ) : isMobile ? (
        <List
          dataSource={audit.map((a, i) => ({ ...a, key: a.ts + '-' + i }))}
          pagination={false}
          size="small"
          renderItem={(item: HookAuditRecord & { key: string }) => (
            <List.Item>
              <div style={{ width: '100%', minWidth: 0 }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
                  <Text type="secondary" style={{ fontSize: 12 }}>
                    {(() => { const d = dayjs(item.ts); return d.isValid() ? d.format('YYYY-MM-DD HH:mm:ss') : item.ts; })()}
                  </Text>
                  <Tag color={AUDIT_STATUS_COLORS[item.status] || 'default'}>
                    {AUDIT_STATUS_LABELS[item.status] || item.status}
                  </Tag>
                </div>
                <div style={{ marginTop: 4, wordBreak: 'break-all' }}>
                  <Text strong>{HOOK_ACTION_LABELS[item.action as HookAction] || item.action}</Text>
                  <Text type="secondary" style={{ marginLeft: 8 }}>
                    {item.spec}{item.duration_ms != null ? ` · ${item.duration_ms}ms` : ''}
                  </Text>
                </div>
                {item.detail && (
                  <Text type="secondary" style={{ display: 'block', marginTop: 4, whiteSpace: 'pre-wrap', wordBreak: 'break-all', fontSize: 12 }}>
                    {item.detail}
                  </Text>
                )}
              </div>
            </List.Item>
          )}
        />
      ) : (
        <Table
          dataSource={audit.map((a, i) => ({ ...a, key: a.ts + '-' + i }))}
          pagination={false}
          size="small"
          rowKey="key"
          tableLayout="fixed"
          // 列宽为显式百分比分配（用户指定 colgroup：时间12/SPEC18/动作12/
          // 结果5/耗时5/摘要48）；不用 scroll max-content，max-content 定宽
          // 会被 detail 单行（命令输出 ≤2KB）撑爆整表
          columns={[
            {
              title: '时间',
              dataIndex: 'ts',
              key: 'ts',
              width: '12%',
              render: (ts: string) => {
                // dayjs 解析失败不抛异常而是返回 Invalid Date，须显式判 isValid
                const d = dayjs(ts);
                return d.isValid() ? d.format('YYYY-MM-DD HH:mm:ss') : ts;
              },
            },
            { title: 'SPEC', dataIndex: 'spec', key: 'spec', width: '18%' },
            {
              title: '动作',
              dataIndex: 'action',
              key: 'action',
              width: '12%',
              render: (a: string) => HOOK_ACTION_LABELS[a as HookAction] || a,
            },
            {
              title: '结果',
              dataIndex: 'status',
              key: 'status',
              width: '5%',
              render: (s: string) => (
                <Tag color={AUDIT_STATUS_COLORS[s] || 'default'}>
                  {AUDIT_STATUS_LABELS[s] || s}
                </Tag>
              ),
            },
            {
              title: '耗时',
              dataIndex: 'duration_ms',
              key: 'duration_ms',
              width: '5%',
              render: (ms: number) => ms != null ? `${ms}ms` : '—',
            },
            {
              title: '摘要',
              dataIndex: 'detail',
              key: 'detail',
              width: '48%',
              // 换行渲染（与移动端视图口径一致）；列宽由 colgroup 百分比定，
              // 不再需要 maxWidth 钳制
              render: (d: string) => (
                <Text
                  type="secondary"
                  style={{ display: 'block', whiteSpace: 'pre-wrap', wordBreak: 'break-all' }}
                >
                  {d || '—'}
                </Text>
              ),
            },
          ]}
        />
      )}
    </div>
  );
}
