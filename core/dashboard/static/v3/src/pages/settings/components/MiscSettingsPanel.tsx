import { Button, Card, Form, InputNumber, Typography } from 'antd';
import { useEffect } from 'react';
import type { ConfigData } from '@/services/dashboard';

const { Text } = Typography;

interface MiscSettingsPanelProps {
  config: ConfigData;
  onSave: (values: Partial<ConfigData>) => Promise<void>;
}

export default function MiscSettingsPanel({ config, onSave }: MiscSettingsPanelProps) {
  const [form] = Form.useForm();

  useEffect(() => {
    form.setFieldsValue({
      keep: config.runs?.keep ?? 50,
    });
  }, [config.runs, form]);

  const handleSave = async () => {
    try {
      const values = await form.validateFields();
      await onSave({
        runs: {
          keep: values.keep,
        },
      });
    } catch (error) {
      console.error('Validation failed:', error);
    }
  };

  return (
    <div>
      <h3>其他</h3>
      <Text type="secondary">不属于其它分类的杂项设置。</Text>
      <Card style={{ marginTop: 12 }}>
        <Form form={form} layout="vertical">
          <Form.Item
            name="keep"
            label={
              <>
                运行产物保留数量<span className="label-note">（runs.keep）</span>
              </>
            }
            rules={[{ required: true, message: '请输入保留数量' }]}
          >
            <InputNumber min={1} step={10} style={{ width: '100%' }} />
          </Form.Item>
          <Text type="secondary">
            默认 50。每个项目保留的最近运行产物文件数；超出的产物自动移入{' '}
            <code>.fenix/runs/archive/</code> 归档（不删除），运行时间轴、运行历史与耗时统计仍可回看归档记录。保存后立即生效。
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
