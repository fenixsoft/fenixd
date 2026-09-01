import { Button, Card, Col, Form, Input, Popconfirm, Row, Typography } from 'antd';
import { MinusCircleOutlined, PlusOutlined } from '@ant-design/icons';
import { useEffect } from 'react';
import type { ConfigData, LlmProvider } from '@/services/dashboard';

const { Text } = Typography;

// env 对象 ↔ 编辑行数组（Form.List 需要数组形态）
interface EnvEntry {
  key: string;
  value: string;
}

function toEnvEntries(env?: Record<string, string>): EnvEntry[] {
  return Object.entries(env || {}).map(([key, value]) => ({ key, value }));
}

function toProviders(values: { providers: Array<Partial<LlmProvider> & { envEntries?: EnvEntry[] }> }): LlmProvider[] {
  return values.providers.map(({ envEntries, ...rest }) => {
    const env: Record<string, string> = {};
    (envEntries || []).forEach((e) => {
      const k = (e?.key || '').trim();
      const v = (e?.value || '').trim();
      if (k && v) env[k] = v;
    });
    if (Object.keys(env).length > 0) rest.env = env;
    return rest as LlmProvider;
  });
}

interface LlmProviderPanelProps {
  config: ConfigData;
  onSave: (values: Partial<ConfigData>) => Promise<void>;
}

export default function LlmProviderPanel({ config, onSave }: LlmProviderPanelProps) {
  const [form] = Form.useForm();

  // 初始化表单数据
  const initialValues = {
    providers: (config.llm.providers || []).map((p) => ({ ...p, envEntries: toEnvEntries(p.env) })),
  };

  // 监听 config 变化，更新表单值
  useEffect(() => {
    form.setFieldsValue({
      providers: (config.llm.providers || []).map((p) => ({ ...p, envEntries: toEnvEntries(p.env) })),
    });
  }, [config.llm.providers, form]);

  const handleSave = async () => {
    try {
      const values = await form.validateFields();
      await onSave({
        llm: {
          providers: toProviders(values),
        },
      });
    } catch (error) {
      console.error('Validation failed:', error);
    }
  };

  return (
    <div>
      <h3>LLM Provider</h3>
      <Text type="secondary">定义可用的 LLM 提供者（Base URL / API Key / 默认模型）。</Text>
      <Form form={form} initialValues={initialValues} layout="vertical" style={{ marginTop: 12 }}>
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
                  <Row gutter={16}>
                    <Col span={12}>
                      <Form.Item
                        name={[field.name, 'name']}
                        label="名称"
                        rules={[{ required: true, message: '请输入 Provider 名称' }]}
                      >
                        <Input placeholder="例如：openai" />
                      </Form.Item>
                    </Col>
                    <Col span={12}>
                      <Form.Item
                        name={[field.name, 'baseurl']}
                        label="Base URL"
                        rules={[{ required: true, message: '请输入 Base URL' }]}
                      >
                        <Input placeholder="https://api.openai.com/v1" />
                      </Form.Item>
                    </Col>
                  </Row>
                  <Row gutter={16}>
                    <Col span={12}>
                      <Form.Item
                        name={[field.name, 'apikey']}
                        label="API Key"
                        rules={[{ required: true, message: '请输入 API Key' }]}
                      >
                        <Input.Password placeholder="sk-..." />
                      </Form.Item>
                    </Col>
                    <Col span={12}>
                      <Form.Item
                        name={[field.name, 'model']}
                        label="默认模型名"
                      >
                        <Input placeholder="deepseek-v4-flash" />
                      </Form.Item>
                    </Col>
                  </Row>
                  <Form.Item
                    label={
                      <>
                        自定义环境变量
                        <span className="label-note">
                          （选填，运行时注入子进程，如 CLAUDE_CODE_MAX_CONTEXT_TOKENS=1000000）
                        </span>
                      </>
                    }
                  >
                    <Form.List name={[field.name, 'envEntries']}>
                      {(envFields, { add: addEnv, remove: removeEnv }) => (
                        <>
                          {envFields.map((envField) => (
                            <Row key={envField.key} gutter={8} align="middle" style={{ marginBottom: 8 }}>
                              <Col span={12}>
                                <Form.Item name={[envField.name, 'key']} noStyle>
                                  <Input placeholder="参数名（如 CLAUDE_CODE_MAX_CONTEXT_TOKENS）" />
                                </Form.Item>
                              </Col>
                              <Col span={11}>
                                <Form.Item name={[envField.name, 'value']} noStyle>
                                  <Input placeholder="值（如 1000000）" />
                                </Form.Item>
                              </Col>
                              <Col span={1} style={{ textAlign: 'right' }}>
                                <Button
                                  type="text"
                                  danger
                                  icon={<MinusCircleOutlined />}
                                  onClick={() => removeEnv(envField.name)}
                                />
                              </Col>
                            </Row>
                          ))}
                          <Button type="dashed" onClick={() => addEnv()} block icon={<PlusOutlined />}>
                            添加参数
                          </Button>
                        </>
                      )}
                    </Form.List>
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
        <div style={{ textAlign: 'right' }}>
          <Button type="primary" onClick={handleSave}>
            保存
          </Button>
        </div>
      </Form>
    </div>
  );
}
