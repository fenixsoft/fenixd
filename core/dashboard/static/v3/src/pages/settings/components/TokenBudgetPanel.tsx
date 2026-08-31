import { Button, Card, Form, InputNumber, Typography } from 'antd';
import type { ConfigData } from '@/services/dashboard';

const { Text } = Typography;

interface TokenBudgetPanelProps {
  config: ConfigData;
  onSave: (values: Partial<ConfigData>) => Promise<void>;
}

export default function TokenBudgetPanel({ config, onSave }: TokenBudgetPanelProps) {
  const [form] = Form.useForm();

  // 初始化表单数据
  const initialValues = {
    token_budget_millions: config.agents.token_budget_millions || 50,
    daily_run_limit: config.agents.daily_run_limit || 50,
    impl_run_budget: config.agents.impl_run_budget || 4,
  };

  const handleSave = async () => {
    try {
      const values = await form.validateFields();
      await onSave({
        agents: {
          token_budget_millions: values.token_budget_millions,
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
      <h3>Token 预算</h3>
      <Card>
        <Form form={form} initialValues={initialValues} layout="vertical">
          <Form.Item
            name="token_budget_millions"
            label="Token 预算（百万）"
            rules={[{ required: true, message: '请输入 Token 预算' }]}
          >
            <InputNumber min={0} style={{ width: '100%' }} />
          </Form.Item>
          <Text type="secondary">
            0=关闭预算检查，默认 50 百万 Token。
          </Text>

          <Form.Item
            name="daily_run_limit"
            label="每日 Agent 运行限额"
            rules={[{ required: true, message: '请输入每日运行限额' }]}
          >
            <InputNumber min={0} style={{ width: '100%' }} />
          </Form.Item>
          <Text type="secondary">
            0=不限制每日运行次数。
          </Text>

          <Form.Item
            name="impl_run_budget"
            label="实现尝试预算"
            rules={[{ required: true, message: '请输入实现尝试预算' }]}
          >
            <InputNumber min={1} max={10} style={{ width: '100%' }} />
          </Form.Item>
          <Text type="secondary">
            每个 SPEC 的实现尝试预算，范围 1-10。
          </Text>

          <Button type="primary" onClick={handleSave}>
            保存
          </Button>
        </Form>
      </Card>
    </div>
  );
}