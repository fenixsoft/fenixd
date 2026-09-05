import { Button, Card, Form, InputNumber, Switch, Typography } from 'antd';
import { useEffect } from 'react';
import type { ConfigData } from '@/services/dashboard';

const { Text } = Typography;

interface ParallelSettingsPanelProps {
  config: ConfigData;
  onSave: (values: Partial<ConfigData>) => Promise<void>;
}

export default function ParallelSettingsPanel({ config, onSave }: ParallelSettingsPanelProps) {
  const [form] = Form.useForm();

  // add-planner-efficiency（planner-generation-throttle）：planner 生成节流。
  // 开关 = verify.planner_max_concurrent > 0；值为 0/缺省 = 不节流（默认关）。
  const throttleEnabled = (config.verify?.planner_max_concurrent ?? 0) > 0;
  const throttleValue = throttleEnabled
    ? (config.verify?.planner_max_concurrent ?? 1)
    : 1;

  const initialValues = {
    max_concurrent: config.agents.max_concurrent ?? 2,
    max_turns: config.agents.max_turns ?? 300,
    run_timeout_seconds: config.agents.run_timeout_seconds ?? 3600,
    planner_throttle: throttleEnabled,
    planner_max_concurrent: throttleValue,
  };

  useEffect(() => {
    form.setFieldsValue({
      max_concurrent: config.agents.max_concurrent ?? 2,
      max_turns: config.agents.max_turns ?? 300,
      run_timeout_seconds: config.agents.run_timeout_seconds ?? 3600,
      planner_throttle: throttleEnabled,
      planner_max_concurrent: throttleValue,
    });
  }, [config.agents, config.verify, form, throttleEnabled, throttleValue]);

  const handleSave = async () => {
    try {
      const values = await form.validateFields();
      await onSave({
        agents: {
          max_concurrent: values.max_concurrent,
          max_turns: values.max_turns,
          run_timeout_seconds: values.run_timeout_seconds,
        },
        verify: {
          ...(config.verify || {}),
          planner_max_concurrent: values.planner_throttle
            ? values.planner_max_concurrent
            : 0,
        },
      });
    } catch (error) {
      console.error('Validation failed:', error);
    }
  };

  const plannerThrottleOn = Form.useWatch('planner_throttle', form);

  return (
    <div>
      <h3>并发度</h3>
      <Text type="secondary">
        同时运行的 Agent 进程数上限。调度采用严格优先级并行：高优先级任务先执行；同一优先级内可并行至该上限；不同优先级不并行（低优先级等高优先级全部完成后才启动）。
      </Text>
      <Card style={{ marginTop: 12 }}>
        <Form form={form} initialValues={initialValues} layout="vertical">
          <Form.Item
            name="max_concurrent"
            label={
              <>
                并发度<span className="label-note">（agents.max_concurrent）</span>
              </>
            }
            rules={[{ required: true, message: '请输入并行度' }]}
          >
            <InputNumber min={1} step={1} style={{ width: '100%' }} />
          </Form.Item>
          <Text type="secondary">默认 2。保存后约 30 秒内热加载生效。</Text>

          <Form.Item
            name="max_turns"
            label={
              <>
                单次 Agent 运行轮次上限<span className="label-note">（agents.max_turns）</span>
              </>
            }
            rules={[{ required: true, message: '请输入轮次上限' }]}
            style={{ marginTop: 24 }}
          >
            <InputNumber min={1} step={1} style={{ width: '100%' }} />
          </Form.Item>
          <Text type="secondary">默认 300（上限而非目标值）。单个 Agent 运行轮次达到此值即被终止并触发重试。</Text>

          <Form.Item
            name="run_timeout_seconds"
            label={
              <>
                单次运行时长上限<span className="label-note">（agents.run_timeout_seconds，秒）</span>
              </>
            }
            rules={[{ required: true, message: '请输入时长上限' }]}
            style={{ marginTop: 24 }}
          >
            <InputNumber min={60} step={60} style={{ width: '100%' }} />
          </Form.Item>
          <Text type="secondary">默认 3600（1 小时）。单个 Agent 运行超时即终止并触发重试。</Text>

          {/* add-planner-efficiency（planner-generation-throttle 2.3）：planner 生成节流。
              开关（默认关）+ 上限输入（1-10）+ 三点注解（限什么/作用/代价）。 */}
          <Form.Item
            name="planner_throttle"
            label={
              <>
                Planner 生成节流<span className="label-note">（verify.planner_max_concurrent）</span>
              </>
            }
            valuePropName="checked"
            style={{ marginTop: 24 }}
          >
            <Switch data-testid="planner-throttle-switch" />
          </Form.Item>
          <Text type="secondary">
            默认关闭（不节流）。① 开启后限制<strong>全框架同时在出题的 Planner 数量</strong>
            （上限为 1-10，默认 1）——超出者排队持有槽等待；② 作用：多个 Planner 并发
            同时访问 LLM 网关时，降低网关排队/长尾延迟（60-185s 停顿）出现的概率；
            ③ 代价：验证吞吐下降（排队中的 spec 等待更久，派发层并发语义不变）。
          </Text>
          {plannerThrottleOn ? (
            <Form.Item
              name="planner_max_concurrent"
              label={
                <>
                  同时出题 Planner 上限<span className="label-note">（verify.planner_max_concurrent）</span>
                </>
              }
              rules={[{ required: true, message: '请输入上限' }]}
              style={{ marginTop: 24 }}
            >
              <InputNumber min={1} max={10} step={1} style={{ width: '100%' }} />
            </Form.Item>
          ) : null}
        </Form>
      </Card>
      <div style={{ textAlign: 'right', marginTop: 24 }}>
        <Button type="primary" onClick={handleSave}>
          保存
        </Button>
      </div>
    </div>
  );
}