import { Button, Card, Form, InputNumber, Switch, Typography } from 'antd';
import { useEffect } from 'react';
import type { ConfigData } from '@/services/dashboard';
import SelfReviewPanel from './SelfReviewPanel';

const { Text } = Typography;

interface SystemPanelProps {
  config: ConfigData;
  onSave: (values: Partial<ConfigData>) => Promise<void>;
  /** 项目名；透传给自省面板（todo.md 编辑区仅项目级作用域显示） */
  project?: string;
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
    note: '同一 spec 同类困境信号的唤起冷却：冷却期内不重复唤起，避免同一问题反复烧钱。',
    rule: [{
      validator: (_: unknown, v: number | undefined | null) =>
        v != null && v >= 0 ? Promise.resolve() : Promise.reject(new Error('须为非负数')),
    }],
  },
  {
    key: 'merge_breaker_threshold',
    label: 'merge 熔断阈值',
    note: 'merge 熔断阈值：同一 spec merge-back 连续失败达该次数仍滞留时触发熔断信号（缺省沿用 agents 同名键=2）。',
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
];

export default function SystemPanel({ config, onSave, project }: SystemPanelProps) {
  const [form] = Form.useForm();

  const admin = config.admin ?? {};

  useEffect(() => {
    form.setFieldsValue({
      enabled: admin.enabled ?? true,
      interval_minutes: admin.interval_minutes ?? 5,
      escalation_cooldown_minutes: admin.escalation_cooldown_minutes ?? 15,
      merge_breaker_threshold: admin.merge_breaker_threshold ?? 2,
      shutdown_drain_seconds: admin.shutdown_drain_seconds ?? 1800,
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [config.admin, form]);

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
        },
      });
    } catch {
      // 校验失败：antd 已在表单内渲染 explain-error 提示
    }
  };

  return (
    <div data-testid="system-panel">
      <h3>系统</h3>
      <Text type="secondary">
        系统级行为（自愈监视器、重启排水等）的设置界面。保存后约 30 秒经配置热更新生效。
      </Text>
      <Card style={{ marginTop: 12 }}>
        <Form form={form} layout="vertical">
          {ADMIN_ANNOTATIONS.map(({ key, label, note, rule }) => (
            <div key={key} style={{ marginBottom: 4 }}>
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
        </Form>
      </Card>
      <div style={{ textAlign: 'right', marginTop: 24 }}>
        <Button type="primary" onClick={handleSave} data-testid="system-save-btn">
          保存
        </Button>
      </div>
      {/* 自省设置并入系统页签（原独立「自省」页签已移除），衔接在系统设置之后；
          两面板各自独立 Form 与保存按钮（字段名有重叠，不可合并为单 Form） */}
      <div style={{ marginTop: 32 }}>
        <SelfReviewPanel config={config} onSave={onSave} project={project} />
      </div>
    </div>
  );
}