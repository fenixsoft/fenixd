import { Button, Card, Form, Radio, Typography } from 'antd';
import { useEffect } from 'react';
import type { ConfigData } from '@/services/dashboard';

const { Text } = Typography;

interface ApprovalModePanelProps {
  config: ConfigData;
  onSave: (values: Partial<ConfigData>) => Promise<void>;
}

export default function ApprovalModePanel({ config, onSave }: ApprovalModePanelProps) {
  const [form] = Form.useForm();

  useEffect(() => {
    // 确保 approve_mode 有值，默认为 'manual'
    form.setFieldsValue({
      approve_mode: config.gates.approve_mode || 'manual',
    });
  }, [config.gates.approve_mode, form]);

  const handleSave = async () => {
    try {
      const values = await form.validateFields();
      await onSave({
        gates: {
          approve_mode: values.approve_mode,
        },
      });
    } catch (error) {
      console.error('Validation failed:', error);
    }
  };

  return (
    <div>
      <h3>审批模式</h3>
      <Text type="secondary">
        SPEC 到达 done 后的行为。auto 模式将自动执行 git push 到远端，请谨慎使用。
      </Text>
      <Card style={{ marginTop: 12 }}>
        <Form
          form={form}
          initialValues={{ approve_mode: config.gates.approve_mode || 'manual' }}
          layout="vertical"
        >
          <Form.Item
            name="approve_mode"
            rules={[{ required: true, message: '请选择审批模式' }]}
          >
            <Radio.Group>
              <div style={{ display: 'block', marginBottom: 16 }}>
                <Radio value="manual">
                  <strong>manual</strong> — 人工审批（默认）
                  <div>
                    <Text type="secondary">
                      SPEC 完成后停留在 done，等待 /fenix-approve 人工推送。
                    </Text>
                  </div>
                </Radio>
              </div>
              <div style={{ display: 'block' }}>
                <Radio value="auto">
                  <strong>auto</strong> — 自动推送
                  <div>
                    <Text type="secondary">
                      SPEC 完成后 daemon 自动执行 git push origin fenix/&lt;spec&gt;。
                    </Text>
                  </div>
                </Radio>
              </div>
            </Radio.Group>
          </Form.Item>
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
