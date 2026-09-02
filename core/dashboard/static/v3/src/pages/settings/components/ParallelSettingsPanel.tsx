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
  };

  useEffect(() => {
    form.setFieldsValue({
      max_concurrent: config.agents.max_concurrent ?? 2,
      max_turns: config.agents.max_turns ?? 300,
      run_timeout_seconds: config.agents.run_timeout_seconds ?? 3600,
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
        },
      });
    } catch (error) {
      console.error('Validation failed:', error);
    }
  };

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
