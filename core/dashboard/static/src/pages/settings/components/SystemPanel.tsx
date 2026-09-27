import { Button, Card, Form, Input, InputNumber, Modal, Select, Space, Switch, Typography, message } from 'antd';
import { useEffect, useRef } from 'react';
import { restartProjectDaemon } from '@/services/dashboard';
import SyncFromUserButton from './SyncFromUserButton';
import { usePanelDirty } from '../panelDirty';
import type { ConfigData } from '@/services/dashboard';

const { Text } = Typography;

interface SystemPanelProps {
  config: ConfigData;
  onSave: (values: Partial<ConfigData>) => Promise<boolean>;
  /** 当前作用域项目名；undefined = 用户级作用域（重启/同步按钮隐藏） */
  project?: string;
  /** 同步成功后回填配置（父组件 setConfig 驱动表单刷新） */
  onConfigSynced?: (config: ConfigData) => void;
}

const ADMIN_ANNOTATIONS: {
  key: string;
  label: string;
  note: string;
  /** 输入单位（addonAfter 附加框）；开关 / 下拉项无单位 */
  unit?: string;
  rule?: object[];
}[] = [
  {
    key: 'enabled',
    label: '自动自愈',
    note: '自动自愈总开关：关闭后困境（卡死/反复失败/预算耗尽）不再自动唤起 Administrator 处置，界面手动运维调用不受影响。',
  },
  {
    key: 'interval_minutes',
    label: '巡检周期',
    unit: '分钟',
    note: '自愈监视器巡检周期：每这么久扫描一次困境信号；也参与卡顿判定的宽限期计算（间隔×2）。',
    rule: [{
      validator: (_: unknown, v: number | undefined | null) =>
        v != null && v > 0 ? Promise.resolve() : Promise.reject(new Error('须为正数')),
    }],
  },
  {
    key: 'escalation_cooldown_minutes',
    label: '唤起冷却',
    unit: '分钟',
    note: '同一 SPEC 同类困境信号的唤起冷却：冷却期内不重复唤起，避免同一问题反复烧钱。',
    rule: [{
      validator: (_: unknown, v: number | undefined | null) =>
        v != null && v >= 0 ? Promise.resolve() : Promise.reject(new Error('须为非负数')),
    }],
  },
  {
    key: 'stuck_silence_minutes',
    label: 'stuck 处置后静默期',
    unit: '分钟',
    note: 'stuck 信号成功处置（resolved / partially-resolved）后的静默窗口：窗口内同 SPEC stuck 信号不复发，避免处置成功后短期反复触发。0=不静默。',
    rule: [{
      validator: (_: unknown, v: number | undefined | null) =>
        v != null && v >= 0 ? Promise.resolve() : Promise.reject(new Error('须为非负数')),
    }],
  },
  {
    key: 'merge_breaker_threshold',
    label: 'merge 熔断阈值',
    unit: '次',
    note: 'merge 熔断阈值：同一 SPEC merge-back 连续失败达该次数仍滞留时触发熔断信号（缺省沿用 agents 同名键=2）。',
    rule: [{
      validator: (_: unknown, v: number | undefined | null) =>
        Number.isInteger(v) && (v as number) > 0
          ? Promise.resolve()
          : Promise.reject(new Error('须为正整数')),
    }],
  },
  {
    key: 'shutdown_drain_seconds',
    label: '重启排水窗口',
    unit: '秒',
    note: '计划性重启排水窗口（秒）：restart_request 后等在跑任务自然收工的上限，0=立即快速停机（在飞任务标记中断、重启后续做）；supervisor 强杀等待=本值+120s。',
    rule: [{
      validator: (_: unknown, v: number | undefined | null) =>
        Number.isInteger(v) && (v as number) >= 0
          ? Promise.resolve()
          : Promise.reject(new Error('须为非负整数')),
    }],
  },
  {
    key: 'bug_repair_mode',
    label: '验证失败修复方式',
    note: '验证裁决 bug-found 后的修复方式：原地打回（inplace，缺省）对父 SPEC 直接注入「验证修复」任务段重修；派生 fix SPEC（derive）创建/复用 fix-* 子 SPEC 并自动闭环重验。',
  },
];

// 瞬断治理（fix-provider-transient-backoff D6）：键名 = agents.transient_*，
// 与后端 ConfigLoader.get_transient_config 缺省一致（30,60,120 / 600 / 3 / 600 / 600）。
const TRANSIENT_ANNOTATIONS: {
  key: string;
  label: string;
  note: string;
  /** 输入单位（addonAfter 附加框） */
  unit?: string;
  rule?: object[];
}[] = [
  {
    key: 'transient_backoff_schedule',
    label: '原地退避序列',
    unit: '秒',
    note: '网关瞬断（model 拒绝 / 5xx / 断连）首败后同 provider 原地退避的秒序列，逗号分隔，长度=单 attempt 内原地重试上限。留空关闭原地退避。',
    rule: [{
      validator: (_: unknown, v: string | undefined | null) => {
        if (v == null || String(v).trim() === '') return Promise.resolve();
        return String(v).split(',').every(p => {
          const s = p.trim();
          if (!s) return true;
          return /^\d+$/.test(s) && Number(s) > 0;
        })
          ? Promise.resolve()
          : Promise.reject(new Error('须为逗号分隔的正整数秒'));
      },
    }],
  },
  {
    key: 'transient_redispatch_delay_seconds',
    label: '重派等待',
    unit: '秒',
    note: '瞬断终态（[provider-transient] 标记）后排程延迟重派秒数，不写 retries exhausted。缺省 600。',
    rule: [{
      validator: (_: unknown, v: number | undefined | null) =>
        v != null && Number.isInteger(v) && (v as number) >= 0
          ? Promise.resolve()
          : Promise.reject(new Error('须为非负整数')),
    }],
  },
  {
    key: 'transient_break_threshold',
    label: '熔断阈值',
    unit: '次',
    note: '全局同错误指纹在窗口内出现次数达此值触发全局派发冻结；0=关闭熔断。缺省 3。',
    rule: [{
      validator: (_: unknown, v: number | undefined | null) =>
        v != null && Number.isInteger(v) && (v as number) >= 0
          ? Promise.resolve()
          : Promise.reject(new Error('须为非负整数')),
    }],
  },
  {
    key: 'transient_break_window_seconds',
    label: '熔断窗口',
    unit: '秒',
    note: '全局同错误指纹计数的滑动窗口秒数。缺省 600。',
    rule: [{
      validator: (_: unknown, v: number | undefined | null) =>
        v != null && Number.isInteger(v) && (v as number) >= 0
          ? Promise.resolve()
          : Promise.reject(new Error('须为非负整数')),
    }],
  },
  {
    key: 'transient_break_cooldown_seconds',
    label: '熔断冷却',
    unit: '秒',
    note: '触发全局熔断后冻结新 run 派发的时长。缺省 600。',
    rule: [{
      validator: (_: unknown, v: number | undefined | null) =>
        v != null && Number.isInteger(v) && (v as number) >= 0
          ? Promise.resolve()
          : Promise.reject(new Error('须为非负整数')),
    }],
  },
];

// admin.* + agents.transient_* 十二字段表单映射单源（config 取值 ?? 缺省）：
// initialValues 与回填 effect 共用，避免两份映射漏改一处导致初值与回填值分叉
function buildSystemFormValues(config: ConfigData) {
  const admin = config.admin ?? {};
  // 瞬断治理（fix-provider-transient-backoff D6）：agents.transient_* 五键
  const agentsSection = config.agents ?? {};
  // 自省字段（self_review.*）已拆至独立「自省」页签（SelfReviewPanel）
  return {
    enabled: admin.enabled ?? true,
    interval_minutes: admin.interval_minutes ?? 5,
    escalation_cooldown_minutes: admin.escalation_cooldown_minutes ?? 60,
    merge_breaker_threshold: admin.merge_breaker_threshold ?? 2,
    shutdown_drain_seconds: admin.shutdown_drain_seconds ?? 1800,
    bug_repair_mode: admin.bug_repair_mode ?? 'inplace',
    stuck_silence_minutes: admin.stuck_silence_minutes ?? 120,
    transient_backoff_schedule: agentsSection.transient_backoff_schedule ?? '30,60,120',
    transient_redispatch_delay_seconds: agentsSection.transient_redispatch_delay_seconds ?? 600,
    transient_break_threshold: agentsSection.transient_break_threshold ?? 3,
    transient_break_window_seconds: agentsSection.transient_break_window_seconds ?? 600,
    transient_break_cooldown_seconds: agentsSection.transient_break_cooldown_seconds ?? 600,
  };
}

export default function SystemPanel({ config, onSave, project, onConfigSynced }: SystemPanelProps) {
  const [form] = Form.useForm();
  // 用户编辑置脏：切页签/作用域前由 index 经 anyPanelDirty 弹丢弃确认
  // （code-review item 8a3eb01dc2b9）
  const { setDirty } = usePanelDirty();

  // 重启 Fenix Daemon（项目级作用域才显示）：确认后写 restart_request，supervisor
  // 排水（admin.shutdown_drain_seconds）后优雅重启，dashboard 不直接杀进程
  const handleRestart = () => {
    if (!project) return;
    Modal.confirm({
      title: '重启 Fenix Daemon',
      content: (
        <div style={{ whiteSpace: 'pre-wrap' }}>
          {`确认重启项目「${project}」的 Fenixd daemon？\n\n`}
          写入 restart_request 后由 supervisor 优雅重启：在跑任务先排水收工
          （上限 = admin.shutdown_drain_seconds），期间新 SPEC 不派发。
        </div>
      ),
      okText: '重启',
      cancelText: '取消',
      onOk: async () => {
        try {
          const res = await restartProjectDaemon(project);
          if (res?.ok) {
            message.success('重启请求已写入，daemon 将排水后自动重启');
          } else {
            message.error(`重启失败：${res?.error ?? '未知错误'}`);
            // 失败时拒绝 resolve，Modal.confirm 不自动关闭，弹窗原样留着供直接重试
            return Promise.reject(new Error(res?.error ?? 'restart failed'));
          }
        } catch (err) {
          message.error(`重启失败：${err instanceof Error ? err.message : String(err)}`);
          return Promise.reject(err instanceof Error ? err : new Error(String(err)));
        }
      },
    });
  };

  const initialValues = buildSystemFormValues(config);

  // 回填门控（code-review item 5be7cabc4d91，比照 TokenBudgetPanel cbec8303669f）：
  // 无条件 setFieldsValue 会在保存往返或「同步用户级设置」刷新 config 时，用外部值
  // 覆盖用户在保存请求在飞期间继续输入、尚未保存的内容。改为序列化比较，只在内容
  // 真变化时回填。
  const lastBackfillRef = useRef('');
  useEffect(() => {
    const next = buildSystemFormValues(config);
    const key = JSON.stringify(next);
    if (key === lastBackfillRef.current) return;
    lastBackfillRef.current = key;
    form.setFieldsValue(next);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [config.admin, config.agents, form]);

  const handleSave = async () => {
    // 分离「表单校验」与「保存持久化」（code-review item 834f22222a24）：与
    // AgentModelPanel.handleSave 对齐——两段混在同一静默 catch 会把校验失败
    // 与持久化失败混为一谈，且丢弃 onSave 的 Promise<boolean> 结果。
    let values;
    try {
      values = await form.validateFields();
    } catch {
      // 校验失败：antd 已在表单内渲染 explain-error 提示，不落 console
      return;
    }
    try {
      const ok = await onSave({
        admin: {
          enabled: values.enabled,
          interval_minutes: values.interval_minutes,
          escalation_cooldown_minutes: values.escalation_cooldown_minutes,
          merge_breaker_threshold: values.merge_breaker_threshold,
          shutdown_drain_seconds: values.shutdown_drain_seconds,
          bug_repair_mode: values.bug_repair_mode,
          stuck_silence_minutes: values.stuck_silence_minutes,
        },
        agents: {
          transient_backoff_schedule:
            typeof values.transient_backoff_schedule === 'string'
              ? values.transient_backoff_schedule.trim()
              : String(values.transient_backoff_schedule ?? ''),
          transient_redispatch_delay_seconds: values.transient_redispatch_delay_seconds,
          transient_break_threshold: values.transient_break_threshold,
          transient_break_window_seconds: values.transient_break_window_seconds,
          transient_break_cooldown_seconds: values.transient_break_cooldown_seconds,
        },
      });
      // ok=false 时父级 handleSave 已 message.error 具体原因，此处不重复 toast
      if (!ok) return;
    } catch (error) {
      // 持久化异常兜底：父级当前自带失败 toast，此 catch 保证其反馈路径调整
      // （onSave 不再自带 toast）时也不退化为无声失败
      message.error(`保存失败：${error instanceof Error ? error.message : String(error)}`);
    }
  };

  return (
    <div data-testid="system-panel">
      {/* 自省设置已拆至独立「自省」页签（SelfReviewPanel）：本页签单 Form 覆盖
          系统+瞬断治理两段，底部统一一个保存按钮（与其他页签一致：Card 外、右下对齐） */}
      <Form form={form} initialValues={initialValues} layout="vertical" onValuesChange={() => setDirty(true)}>
        <h3>系统</h3>
        <Text type="secondary">
          系统级行为（自愈监视器、重启排水等）的设置界面。保存后约 30 秒经配置热更新生效。
        </Text>
        <Card style={{ marginTop: 12 }}>
          {ADMIN_ANNOTATIONS.map(({ key, label, note, unit, rule }) => (
            // 行距由行内最后元素的下边距（24/8px）collapse 提供，此处不挂 inline
            // margin——否则末行会在卡底残留（global.less 的 :last-child 清零压不过
            // inline style）
            <div key={key}>
              {key === 'enabled' ? (
                <div className="switch-inline-row" data-testid={`system-field-${key}`}>
                  <Form.Item name={key} valuePropName="checked" noStyle>
                    <Switch data-testid={`system-control-${key}`} />
                  </Form.Item>
                  <span className="switch-inline-label">
                    {label}
                    <span className="label-note">（admin.{key}）</span>
                  </span>
                </div>
              ) : key === 'bug_repair_mode' ? (
                <Form.Item
                  name={key}
                  label={
                    <>
                      {label}
                      <span className="label-note">（admin.{key}）</span>
                    </>
                  }
                  data-testid={`system-field-${key}`}
                >
                  <Select
                    data-testid={`system-control-${key}`}
                    style={{ width: '100%' }}
                    options={[
                      { value: 'inplace', label: '原地打回（inplace）' },
                      { value: 'derive', label: '派生 fix SPEC（derive）' },
                    ]}
                  />
                </Form.Item>
              ) : (
                <Form.Item
                  name={key}
                  label={
                    <>
                      {label}
                      <span className="label-note">（admin.{key}）</span>
                    </>
                  }
                  rules={rule}
                  data-testid={`system-field-${key}`}
                >
                  <InputNumber
                    data-testid={`system-control-${key}`}
                    style={{ width: '100%' }}
                    step={1}
                    precision={0}
                    addonAfter={unit}
                  />
                </Form.Item>
              )}
              {note && <Text type="secondary">{note}</Text>}
            </div>
          ))}
        </Card>
        {/* 瞬断治理（fix-provider-transient-backoff D6）：agents.transient_* 五键分组 */}
        <h3 style={{ marginTop: 20 }}>瞬断治理</h3>
        <Text type="secondary">
          provider 网关瞬时故障（model 拒绝 / 5xx / 断连）的退避与熔断策略。保存后约 30 秒经配置热更新生效。
        </Text>
        <Card style={{ marginTop: 12 }}>
          {TRANSIENT_ANNOTATIONS.map(({ key, label, note, unit, rule }) => (
            <div key={key} style={{ marginBottom: 4 }}>
              {key === 'transient_backoff_schedule' ? (
                <Form.Item
                  name={key}
                  label={
                    <>
                      {label}
                      <span className="label-note">（agents.{key}）</span>
                    </>
                  }
                  rules={rule}
                  data-testid={`system-field-${key}`}
                >
                  {/* 逗号分隔序列须用文本框：InputNumber 的默认 parser 会剥离逗号，
                      "30,60,120" 会被静默并成 "3060120" 恰好骗过单段校验 */}
                  <Input
                    data-testid={`system-control-${key}`}
                    style={{ width: '100%' }}
                    placeholder="30,60,120"
                    addonAfter={unit}
                  />
                </Form.Item>
              ) : (
                <Form.Item
                  name={key}
                  label={
                    <>
                      {label}
                      <span className="label-note">（agents.{key}）</span>
                    </>
                  }
                  rules={rule}
                  data-testid={`system-field-${key}`}
                >
                  <InputNumber
                    data-testid={`system-control-${key}`}
                    style={{ width: '100%' }}
                    step={1}
                    precision={0}
                    addonAfter={unit}
                  />
                </Form.Item>
              )}
              {note && <Text type="secondary">{note}</Text>}
            </div>
          ))}
        </Card>
      </Form>
      <div
        style={{
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
          marginTop: 24,
        }}
      >
        {/* 左：重启 Fenix Daemon（项目级显示，danger 标示危险操作）；右：同步用户级设置 + 保存 */}
        {project ? (
          <Button type="primary" danger onClick={handleRestart} data-testid="system-restart-btn">
            重启 Fenix Daemon
          </Button>
        ) : (
          <span />
        )}
        <Space>
          {project && onConfigSynced && (
            <SyncFromUserButton project={project} page="system" onSynced={onConfigSynced} />
          )}
          <Button type="primary" onClick={handleSave} data-testid="system-save-btn">
            保存
          </Button>
        </Space>
      </div>
    </div>
  );
}
