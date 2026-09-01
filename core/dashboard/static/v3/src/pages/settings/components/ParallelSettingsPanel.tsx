import { Button, Card, Form, InputNumber, Typography } from 'antd';
import { useEffect } from 'react';
import type { ConfigData } from '@/services/dashboard';

const { Text } = Typography;

interface ParallelSettingsPanelProps {
  config: ConfigData;
  onSave: (values: Partial<ConfigData>) => Promise<void>;
}

export default function ParallelSettingsPanel({ config, onSave }: ParallelSettingsPanelProps) {
  const [form] = Form.useForm();

  const initialValues = {
    max_concurrent: config.agents.max_concurrent ?? 2,
    max_turns: config.agents.max_turns ?? 300,
    run_timeout_seconds: config.agents.run_timeout_seconds ?? 3600,
    daily_run_limit: config.agents.daily_run_limit ?? 50,
    impl_run_budget: config.agents.impl_run_budget ?? 4,
  };

  useEffect(() => {
    form.setFieldsValue({
      max_concurrent: config.agents.max_concurrent ?? 2,
      max_turns: config.agents.max_turns ?? 300,
      run_timeout_seconds: config.agents.run_timeout_seconds ?? 3600,
      daily_run_limit: config.agents.daily_run_limit ?? 50,
      impl_run_budget: config.agents.impl_run_budget ?? 4,
    });
  }, [config.agents, form]);

  const handleSave = async () => {
    try {
      const values = await form.validateFields();
      await onSave({
        agents: {
          max_concurrent: values.max_concurrent,
          max_turns: values.max_turns,
          run_timeout_seconds: values.run_timeout_seconds,
          daily_run_limit: values.daily_run_limit,
          impl_run_budget: values.impl_run_budget,
        },
      });
    } catch (error) {
      console.error('Validation failed:', error);
    }
  };

  return (
    <div>
      <h3>并行度设置</h3>
      <Text type="secondary">
        同时运行的 Agent 进程数上限。调度采用严格优先级并行：高优先级任务先执行；同一优先级内可并行至该上限；不同优先级不并行（低优先级等高优先级全部完成后才启动）。
      </Text>
      <Card style={{ marginTop: 12 }}>
        <Form form={form} initialValues={initialValues} layout="vertical">
          <Form.Item
            name="max_concurrent"
            label={
              <>
                并行度<span className="label-note">（agents.max_concurrent）</span>
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

          <Form.Item
            name="daily_run_limit"
            label={
              <>
                每日 Agent 运行限额<span className="label-note">（agents.daily_run_limit，0 = 不限）</span>
              </>
            }
            rules={[{ required: true, message: '请输入每日运行限额' }]}
            style={{ marginTop: 24 }}
          >
            <InputNumber min={0} step={1} style={{ width: '100%' }} />
          </Form.Item>
          <Text type="secondary">
            默认 50。单个 UTC 自然日内所有 Agent 类型成功运行的累计上限（实现/验证/管理共用一个池），达到后当日停止派发，UTC 次日 0 点自动归零。设为 0 表示不限制。
          </Text>

          <Form.Item
            name="impl_run_budget"
            label={
              <>
                实现尝试预算<span className="label-note">（agents.impl_run_budget，1-10）</span>
              </>
            }
            rules={[{ required: true, message: '请输入实现尝试预算' }]}
            style={{ marginTop: 24 }}
          >
            <InputNumber min={1} max={10} step={1} style={{ width: '100%' }} />
          </Form.Item>
          <Text type="secondary">
            默认 4。每 SPEC 跨修复周期的实现 run 启动次数上限（含首次实现与每轮修复重派）。达到上限即冻结该 SPEC 并交人工裁决，需人工调大预算或推进状态。合法范围 1-10。
          </Text>
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
