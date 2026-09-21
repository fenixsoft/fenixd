import { Card, Form, InputNumber, Switch, Typography } from 'antd';
import { forwardRef, useEffect, useImperativeHandle } from 'react';
import type { ConfigData } from '@/services/dashboard';
import type { SelfEvolutionSectionHandle } from './selfEvolutionSection';

const { Text } = Typography;

// add-stale-code-selfheal：陈旧自愈配置节缺省与 ConfigLoader 缺省一致
// （enabled=true / idle_confirm_seconds=120）
const DEFAULT_IDLE_SECONDS = 120;
const MAX_IDLE_SECONDS = 86400;

interface StaleCodeSelfhealPanelProps {
  config: ConfigData;
}

// 保存按钮已上提到自进化页签底部（全页唯一），本卡片经 ref 暴露 collect()，
// 由父页签在唯一点击事件里与「建议改进项」卡片一起校验并合并提交。
const StaleCodeSelfhealPanel = forwardRef<
  SelfEvolutionSectionHandle,
  StaleCodeSelfhealPanelProps
>(function StaleCodeSelfhealPanel({ config }, ref) {
  const [form] = Form.useForm();
  const scs = config.stale_code_selfheal;

  const initialValues = {
    enabled: scs?.enabled ?? true,
    idle_confirm_seconds: scs?.idle_confirm_seconds ?? DEFAULT_IDLE_SECONDS,
  };

  useEffect(() => {
    form.setFieldsValue(initialValues);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [config.stale_code_selfheal, form]);

  useImperativeHandle(
    ref,
    () => ({
      collect: async () => {
        try {
          const values = await form.validateFields();
          return {
            stale_code_selfheal: {
              enabled: values.enabled,
              idle_confirm_seconds: values.idle_confirm_seconds,
            },
          };
        } catch {
          // 校验失败：antd 已在表单内渲染 explain-error 提示
          return null;
        }
      },
    }),
    [form],
  );

  return (
    <div data-testid="stale-code-selfheal-panel">
      <Form form={form} initialValues={initialValues} layout="vertical">
        <h3>新代码自动装载</h3>
        <Text type="secondary">
          本项目是可自我改进的。daemon 进程持有的是启动时刻的代码副本，本机制把「检测到代码陈旧」接到「空闲时自动重启」上。当连续空闲达到
          阈值后由 daemon 写 <code>.fenix/restart_request</code>，supervisor 执行优雅重启使新代码生效。
        </Text>
        <Card style={{ marginTop: 12 }}>
          <div className="switch-inline-row">
            <Form.Item name="enabled" valuePropName="checked" noStyle>
              <Switch data-testid="stale-code-selfheal-control-enabled" />
            </Form.Item>
            <span className="switch-inline-label">
              启用空闲自动重启<span className="label-note">（stale_code_selfheal.enabled）</span>
            </span>
          </div>
          <Text type="secondary">
            缺省开启。关闭后仍检测并展示陈旧状态与告警，但不再自动触发重启
            （需要人工 touch <code>.fenix/restart_request</code> 或重启 daemon）。
            未受 supervisor 托管的项目不会自愈（写了也无人消费），陈旧告警维持，
            等待经 Dashboard「安装托管」或 /fenix-setup 恢复托管。
          </Text>

          <Form.Item
            name="idle_confirm_seconds"
            label={
              <>
                连续空闲确认秒数
                <span className="label-note">（stale_code_selfheal.idle_confirm_seconds）</span>
              </>
            }
            style={{ marginTop: 24 }}
            rules={[
              { required: true, message: '请输入连续空闲确认秒数' },
              {
                type: 'number',
                min: 1,
                max: MAX_IDLE_SECONDS,
                message: `须为 1-${MAX_IDLE_SECONDS} 的正整数秒`,
              },
            ]}
            data-testid="stale-code-selfheal-field-idle_confirm_seconds"
          >
            <InputNumber
              min={1}
              max={MAX_IDLE_SECONDS}
              precision={0}
              style={{ width: '100%' }}
              addonAfter="秒"
            />
          </Form.Item>
          <Text type="secondary">
            缺省 120 秒。「空闲」= 无活跃 agent run（planner / implementer / verifier /
            judge 全部形态）且无 admin 处置在途任务；任一活跃信号出现立即清零重新计时。
            自动重启引入的新代码若无法启动，supervisor 会在连续 3 次 60 秒内崩溃后
            熔断停止拉起并告警，不会无限重启。
          </Text>
        </Card>
      </Form>
    </div>
  );
});

export default StaleCodeSelfhealPanel;
