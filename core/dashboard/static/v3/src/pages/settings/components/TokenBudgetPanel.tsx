import { Button, Card, Form, InputNumber, Typography } from 'antd';
import { useEffect } from 'react';
import type { ConfigData } from '@/services/dashboard';

const { Text } = Typography;

interface TokenBudgetPanelProps {
  config: ConfigData;
  onSave: (values: Partial<ConfigData>) => Promise<void>;
}

export default function TokenBudgetPanel({ config, onSave }: TokenBudgetPanelProps) {
  const [form] = Form.useForm();

  const initialValues = {
    token_budget_millions: config.agents.token_budget_millions ?? 50,
  };

  useEffect(() => {
    form.setFieldsValue({
      token_budget_millions: config.agents.token_budget_millions ?? 50,
    });
  }, [config.agents.token_budget_millions, form]);

  const handleSave = async () => {
    try {
      const values = await form.validateFields();
      await onSave({
        agents: {
          token_budget_millions: values.token_budget_millions,
        },
      });
    } catch (error) {
      console.error('Validation failed:', error);
    }
  };

  return (
    <div>
      <h3>Token 预算</h3>
      <Text type="secondary">
        单 SPEC 累计 input token 的预算上限（成本观测）。收工累计达到 80% 发提醒级告警、达到 100% 发升级级告警，不自动冻结，由人工决定是否处置。
      </Text>
      <Card style={{ marginTop: 12 }}>
        <Form form={form} initialValues={initialValues} layout="vertical">
          <Form.Item
            name="token_budget_millions"
            label={
              <>
                Token 预算<span className="label-note">（百万，0=关闭）</span>
              </>
            }
            rules={[{ required: true, message: '请输入 Token 预算' }]}
          >
            <InputNumber min={0} max={1000} step={1} style={{ width: '100%' }} />
          </Form.Item>
          <Text type="secondary">
            默认 50（百万 input token）。保存后约 30 秒内热加载生效；设为 0 表示关闭预算检查。
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
