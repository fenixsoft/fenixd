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

  // 初始化表单数据
  const initialValues = {
    max_concurrent: config.agents.max_concurrent || 2,
    max_turns: config.agents.max_turns || 300,
    run_timeout_seconds: config.agents.run_timeout_seconds || 3600,
  };

  // 监听 config 变化，更新表单值
  useEffect(() => {
    form.setFieldsValue({
      max_concurrent: config.agents.max_concurrent || 2,
      max_turns: config.agents.max_turns || 300,
      run_timeout_seconds: config.agents.run_timeout_seconds || 3600,
    });
  }, [config.agents.max_concurrent, config.agents.max_turns, config.agents.run_timeout_seconds, form]);

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
      <h3>并行度设置</h3>
      <Card>
        <Form form={form} initialValues={initialValues} layout="vertical">
          <Form.Item
            name="max_concurrent"
            label="并行度"
            rules={[{ required: true, message: '请输入并行度' }]}
          >
            <InputNumber min={1} style={{ width: '100%' }} />
          </Form.Item>
          <Text type="secondary">
            严格优先级并行语义：同时运行的 Agent 数量上限。热加载生效。
          </Text>

          <Form.Item
            name="max_turns"
            label="单次运行轮次上限"
            rules={[{ required: true, message: '请输入轮次上限' }]}
          >
            <InputNumber min={1} style={{ width: '100%' }} />
          </Form.Item>
          <Text type="secondary">
            单次运行的最大轮次数。热加载生效。
          </Text>

          <Form.Item
            name="run_timeout_seconds"
            label="单次运行时长上限（秒）"
            rules={[{ required: true, message: '请输入时长上限' }]}
          >
            <InputNumber min={1} style={{ width: '100%' }} />
          </Form.Item>
          <Text type="secondary">
            单次运行的最大时长（秒）。热加载生效。
          </Text>

          <Button type="primary" onClick={handleSave}>
            保存
          </Button>
        </Form>
      </Card>
    </div>
  );
}