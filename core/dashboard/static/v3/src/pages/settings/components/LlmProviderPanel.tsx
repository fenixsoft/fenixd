import { Button, Card, Form, Input, Popconfirm, Space, Typography } from 'antd';
import { MinusCircleOutlined, PlusOutlined } from '@ant-design/icons';
import { useEffect } from 'react';
import type { ConfigData, LlmProvider } from '@/services/dashboard';

const { Text } = Typography;

interface LlmProviderPanelProps {
  config: ConfigData;
  onSave: (values: Partial<ConfigData>) => Promise<void>;
}

export default function LlmProviderPanel({ config, onSave }: LlmProviderPanelProps) {
  const [form] = Form.useForm();

  // 初始化表单数据
  const initialValues = {
    providers: config.llm.providers || [],
  };

  // 监听 config 变化，更新表单值
  useEffect(() => {
    form.setFieldsValue({
      providers: config.llm.providers || [],
    });
  }, [config.llm.providers, form]);

  const handleSave = async () => {
    try {
      const values = await form.validateFields();
      await onSave({
        llm: {
          providers: values.providers,
        },
      });
    } catch (error) {
      console.error('Validation failed:', error);
    }
  };

  return (
    <div>
      <h3>LLM Provider</h3>
      <Form form={form} initialValues={initialValues} layout="vertical">
        <Form.List name="providers">
          {(fields, { add, remove }) => (
            <>
              {fields.map((field, index) => (
                <Card
                  key={field.key}
                  style={{ marginBottom: 16 }}
                  title={`Provider ${index + 1}`}
                  extra={
                    <Popconfirm
                      title="确定删除此 Provider？"
                      onConfirm={() => remove(field.name)}
                      okText="删除"
                      cancelText="取消"
                    >
                      <Button type="text" danger icon={<MinusCircleOutlined />} />
                    </Popconfirm>
                  }
                >
                  <Form.Item
                    {...field}
                    name={[field.name, 'name']}
                    label="名称"
                    rules={[{ required: true, message: '请输入 Provider 名称' }]}
                  >
                    <Input placeholder="例如：openai" />
                  </Form.Item>
                  <Form.Item
                    {...field}
                    name={[field.name, 'baseurl']}
                    label="Base URL"
                    rules={[{ required: true, message: '请输入 Base URL' }]}
                  >
                    <Input placeholder="https://api.openai.com/v1" />
                  </Form.Item>
                  <Form.Item
                    {...field}
                    name={[field.name, 'apikey']}
                    label="API Key"
                    rules={[{ required: true, message: '请输入 API Key' }]}
                  >
                    <Input.Password placeholder="sk-..." />
                  </Form.Item>
                  <Form.Item
                    {...field}
                    name={[field.name, 'default_model']}
                    label="默认模型"
                  >
                    <Input placeholder="例如：gpt-4" />
                  </Form.Item>
                </Card>
              ))}
              <Button
                type="dashed"
                onClick={() => add()}
                block
                icon={<PlusOutlined />}
                style={{ marginBottom: 16 }}
              >
                新增 Provider
              </Button>
            </>
          )}
        </Form.List>
        <Button type="primary" onClick={handleSave}>
          保存
        </Button>
      </Form>
    </div>
  );
}