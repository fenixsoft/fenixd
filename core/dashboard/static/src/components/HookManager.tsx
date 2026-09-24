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

function shortId(): string {
  return 'h-' + Math.random().toString(36).slice(2, 8);
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

  const handleDelete = useCallback(
    (idx: number) => {
      const next = hooks.filter((_, i) => i !== idx);
      onSave(next);
    },
    [hooks, onSave],
  );

  const handleToggle = useCallback(
    (idx: number, checked: boolean) => {
      const next = hooks.map((h, i) => (i === idx ? { ...h, enabled: checked } : h));
      onSave(next);
    },
    [hooks, onSave],
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
    .catch(() => {
      // 校验不通过时 validateFields 会 reject，静默吞掉避免 unhandled rejection（错误已由表单字段提示）
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
            disabled={readOnly}
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
                <Button type="link" size="small" icon={<EditOutlined />} onClick={() => handleEdit(idx)} />
              </Tooltip>
              <Popconfirm title="确定删除？" onConfirm={() => handleDelete(idx)} okText="删除" cancelText="取消">
                <Button type="link" size="small" danger icon={<DeleteOutlined />} />
              </Popconfirm>
            </Space>
          )
        ),
      },
    ];
    return cols;
    // eslint-disable-next-line react-hooks/exhaustive-deps — handlers 已 useCallback 化并列入依赖（item 0383473dd260）
  }, [hooks, form, handleToggle, handleEdit, handleDelete, readOnly]);

  // ── 生效合并表格列（仅 spec 详情页）────────────────────────────

  // 生效合并表格列（仅 spec 详情页）。
  // 列宽口径：事件列实测 732px 收缩为 1/4（183）；腾出的宽度连同动作列
  // 原有宽度由动作列与参数列等宽平分（各 360），固定列总宽守恒。
  const effectiveColumns = [
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
  ];

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
          <Button type="primary" onClick={handleAdd}>
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
          dataSource={hooks.map((h, i) => ({ ...h, key: h.id || i, idx: i }))}
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
                      disabled={readOnly}
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
                      <Button type="link" size="small" icon={<EditOutlined />} onClick={() => handleEdit(realIdx)}>
                        编辑
                      </Button>
                      <Popconfirm title="确定删除？" onConfirm={() => handleDelete(realIdx)} okText="删除" cancelText="取消">
                        <Button type="link" size="small" danger icon={<DeleteOutlined />}>
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
          dataSource={hooks.map((h, i) => ({ ...h, key: h.id || i }))}
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
        destroyOnClose
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
