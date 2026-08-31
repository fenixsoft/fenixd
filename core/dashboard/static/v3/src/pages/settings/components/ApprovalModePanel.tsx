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

  // 初始化表单数据
  const initialValues = {
    approve_mode: config.gates.approve_mode || 'manual',
  };

  // 监听 config 变化，更新表单值
  useEffect(() => {
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
      <Card>
        <Form form={form} initialValues={initialValues} layout="vertical">
          <Form.Item
            name="approve_mode"
            label="审批模式"
            rules={[{ required: true, message: '请选择审批模式' }]}
          >
            <Radio.Group>
              <Radio value="manual">手动审批</Radio>
              <Radio value="auto">自动推送</Radio>
            </Radio.Group>
          </Form.Item>
          <Text type="secondary">
            手动审批：SPEC 完成后停留 done，等待人工推送。自动推送：SPEC 完成后自动推送。
          </Text>

          <Button type="primary" onClick={handleSave}>
            保存
          </Button>
        </Form>
      </Card>
    </div>
  );
}