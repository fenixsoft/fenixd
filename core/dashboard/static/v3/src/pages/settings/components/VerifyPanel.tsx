import { Button, Card, Form, Radio, Typography } from 'antd';
import { useEffect } from 'react';
import type { ConfigData } from '@/services/dashboard';

const { Text } = Typography;

interface VerifyPanelProps {
  config: ConfigData;
  onSave: (values: Partial<ConfigData>) => Promise<void>;
}

export default function VerifyPanel({ config, onSave }: VerifyPanelProps) {
  const [form] = Form.useForm();

  useEffect(() => {
    form.setFieldsValue({
      static_scope: config.verify?.static_scope || 'main',
    });
  }, [config.verify, form]);

  const handleSave = async () => {
    try {
      const values = await form.validateFields();
      await onSave({
        verify: {
          static_scope: values.static_scope,
        },
      });
    } catch (error) {
      console.error('Validation failed:', error);
    }
  };

  return (
    <div>
      <h3>验证契约</h3>
      <Text type="secondary">
        静态验证契约（.fenix/verify.yaml）的被测实例服务范围。两种范围都会在
        每轮验证前执行契约的 prepare 构建步骤，并把验证场景 URL 全量改写到
        本次启动的实例（BASE_URL 注入，场景永远打新鲜实现）。
      </Text>
      <Card style={{ marginTop: 12 }}>
        <Form form={form} layout="vertical">
          <Form.Item
            name="static_scope"
            label={
              <>
                static 服务范围<span className="label-note">（verify.static_scope）</span>
              </>
            }
            rules={[{ required: true, message: '请选择服务范围' }]}
          >
            <Radio.Group>
              <div style={{ display: 'block', marginBottom: 16 }}>
                <Radio value="main">
                  <strong>main</strong> — 主树起服务（方案 1，默认）
                  <div>
                    <Text type="secondary">
                      在主树构建并启动被测实例。实现合并进主树后产物必然新鲜，
                      与现有运行实例共享，资源占用最小。
                    </Text>
                  </div>
                </Radio>
              </div>
              <div style={{ display: 'block' }}>
                <Radio value="worktree">
                  <strong>worktree</strong> — worktree 起服务（方案 2）
                  <div>
                    <Text type="secondary">
                      在专用 serving worktree 内构建并启动服务，与主树运行实例
                      完全隔离（验证流量不影响主实例）。每次 HEAD 变化自动重建
                      worktree 与产物，node_modules 自动从主树链入。
                    </Text>
                  </div>
                </Radio>
              </div>
            </Radio.Group>
          </Form.Item>
          <Button type="primary" onClick={handleSave}>
            保存
          </Button>
        </Form>
      </Card>
    </div>
  );
}
