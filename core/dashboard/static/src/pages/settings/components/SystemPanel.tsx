import { Button, Card, Form, InputNumber, Select, Switch, Typography } from 'antd';
import { useEffect } from 'react';
import type { ConfigData } from '@/services/dashboard';

const { Text } = Typography;

interface SystemPanelProps {
  config: ConfigData;
  onSave: (values: Partial<ConfigData>) => Promise<boolean>;
}

const ADMIN_ANNOTATIONS: {
  key: string;
  label: string;
  note: string;
  rule?: object[];
}[] = [
  {
    key: 'enabled',
    label: '自动自愈',
    note: '自动自愈总开关：关闭后困境（卡死/反复失败/预算耗尽）不再自动唤起 Administrator 处置，界面手动运维调用不受影响。',
  },
  {
    key: 'interval_minutes',
    label: '巡检周期（分钟）',
    note: '自愈监视器巡检周期：每这么久扫描一次困境信号；也参与卡顿判定的宽限期计算（间隔×2）。',
    rule: [{
      validator: (_: unknown, v: number | undefined | null) =>
        v != null && v > 0 ? Promise.resolve() : Promise.reject(new Error('须为正数')),
    }],
  },
  {
    key: 'escalation_cooldown_minutes',
    label: '唤起冷却（分钟）',
    note: '同一 SPEC 同类困境信号的唤起冷却：冷却期内不重复唤起，避免同一问题反复烧钱。',
    rule: [{
      validator: (_: unknown, v: number | undefined | null) =>
        v != null && v >= 0 ? Promise.resolve() : Promise.reject(new Error('须为非负数')),
    }],
  },
  {
    key: 'merge_breaker_threshold',
    label: 'merge 熔断阈值',
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
    label: '重启排水窗口（秒）',
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
  rule?: object[];
}[] = [
  {
    key: 'transient_backoff_schedule',
    label: '原地退避序列（秒）',
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
    label: '重派等待（秒）',
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
    label: '熔断阈值（次数）',
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
    label: '熔断窗口（秒）',
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
    label: '熔断冷却（秒）',
    note: '触发全局熔断后冻结新 run 派发的时长。缺省 600。',
    rule: [{
      validator: (_: unknown, v: number | undefined | null) =>
        v != null && Number.isInteger(v) && (v as number) >= 0
          ? Promise.resolve()
          : Promise.reject(new Error('须为非负整数')),
    }],
  },
];

export default function SystemPanel({ config, onSave }: SystemPanelProps) {
  const [form] = Form.useForm();

  const admin = config.admin ?? {};
  // 瞬断治理（fix-provider-transient-backoff D6）：agents.transient_* 五键
  const transient = config.agents ?? {};

  // 自省字段（self_review.*）已拆至独立「自省」页签（SelfReviewPanel）
  const initialValues = {
    enabled: admin.enabled ?? true,
    interval_minutes: admin.interval_minutes ?? 5,
    escalation_cooldown_minutes: admin.escalation_cooldown_minutes ?? 60,
    merge_breaker_threshold: admin.merge_breaker_threshold ?? 2,
    shutdown_drain_seconds: admin.shutdown_drain_seconds ?? 1800,
    bug_repair_mode: admin.bug_repair_mode ?? 'inplace',
    transient_backoff_schedule: transient.transient_backoff_schedule ?? '30,60,120',
    transient_redispatch_delay_seconds: transient.transient_redispatch_delay_seconds ?? 600,
    transient_break_threshold: transient.transient_break_threshold ?? 3,
    transient_break_window_seconds: transient.transient_break_window_seconds ?? 600,
    transient_break_cooldown_seconds: transient.transient_break_cooldown_seconds ?? 600,
  };

  useEffect(() => {
    form.setFieldsValue(initialValues);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [config.admin, config.agents, form]);

  const handleSave = async () => {
    try {
      const values = await form.validateFields();
      await onSave({
        admin: {
          enabled: values.enabled,
          interval_minutes: values.interval_minutes,
          escalation_cooldown_minutes: values.escalation_cooldown_minutes,
          merge_breaker_threshold: values.merge_breaker_threshold,
          shutdown_drain_seconds: values.shutdown_drain_seconds,
          bug_repair_mode: values.bug_repair_mode,
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
    } catch {
      // 校验失败：antd 已在表单内渲染 explain-error 提示
      return;
    }
  };

  return (
    <div data-testid="system-panel">
      {/* 自省设置已拆至独立「自省」页签（SelfReviewPanel）：本页签单 Form 覆盖
          系统+瞬断治理两段，底部统一一个保存按钮（与其他页签一致：Card 外、右下对齐） */}
      <Form form={form} initialValues={initialValues} layout="vertical">
        <h3>系统</h3>
        <Text type="secondary">
          系统级行为（自愈监视器、重启排水等）的设置界面。保存后约 30 秒经配置热更新生效。
        </Text>
        <Card style={{ marginTop: 12 }}>
          {ADMIN_ANNOTATIONS.map(({ key, label, note, rule }) => (
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
                    style={{ width: 260 }}
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
                    style={{ width: 220 }}
                    step={1}
                    precision={0}
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
          {TRANSIENT_ANNOTATIONS.map(({ key, label, note, rule }) => (
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
                  <InputNumber
                    data-testid={`system-control-${key}`}
                    style={{ width: 220 }}
                    stringMode
                    placeholder="30,60,120"
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
                    style={{ width: 220 }}
                    step={1}
                    precision={0}
                  />
                </Form.Item>
              )}
              {note && <Text type="secondary">{note}</Text>}
            </div>
          ))}
        </Card>
      </Form>
      <div style={{ textAlign: 'right', marginTop: 24 }}>
        <Button type="primary" onClick={handleSave} data-testid="system-save-btn">
          保存
        </Button>
      </div>
    </div>
  );
}
