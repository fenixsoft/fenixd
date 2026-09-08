import { Button, Card, Form, Radio, Switch, Typography } from 'antd';
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
    // 确保字段有值，使用配置值或默认值
    form.setFieldsValue({
      auto_promote_draft: config.gates.auto_promote_draft ?? true,
      approve_mode: config.gates.approve_mode || 'manual',
    });
  }, [config.gates.approve_mode, config.gates.auto_promote_draft, form]);

  const handleSave = async () => {
    try {
      const values = await form.validateFields();
      await onSave({
        gates: {
          auto_promote_draft: values.auto_promote_draft,
          approve_mode: values.approve_mode,
        },
      });
    } catch (error) {
      console.error('Validation failed:', error);
    }
  };

  return (
    <div>
      <h3>审批</h3>
      <Text type="secondary">
        SPEC 到达 done 后的行为。auto 模式将自动执行 git push 到远端，请谨慎使用。
      </Text>
      <Card style={{ marginTop: 12 }}>
        <Form
          form={form}
          initialValues={{
            auto_promote_draft: config.gates.auto_promote_draft ?? true,
            approve_mode: config.gates.approve_mode || 'manual',
          }}
          layout="vertical"
        >
          {/* 草稿自动晋升开关（add-draft-promotion-gate D5） */}
          <Form.Item
            name="auto_promote_draft"
            label="草稿自动晋升"
            valuePropName="checked"
            extra="开启时 SPEC 注册后立即自动进入调度；关闭后 SPEC 停留草稿态，供人工阅读，确认后在项目页手动放行"
          >
            <Switch />
          </Form.Item>
          <Form.Item
            name="approve_mode"
            rules={[{ required: true, message: '请选择审批模式' }]}
          >
            <Radio.Group>
              <div style={{ display: 'block', marginBottom: 16 }}>
                <Radio value="manual">
                  <strong>manual</strong> — 人工审批（推荐）
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
