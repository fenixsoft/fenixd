import { Button, Card, Form, Input, Select, Space, Typography } from 'antd';
import type { ConfigData } from '@/services/dashboard';

const { Text } = Typography;

interface AgentModelPanelProps {
  config: ConfigData;
  onSave: (values: Partial<ConfigData>) => Promise<void>;
}

// 已知的 Agent 角色列表（来自 v1 KNOWN_AGENT_TYPES）
const AGENT_ROLES = [
  'planner',
  'implementer',
  'verifier',
  'reviewer',
  'coordinator',
  'researcher',
  'writer',
  'designer',
  'optimizer',
  'debugger',
];

export default function AgentModelPanel({ config, onSave }: AgentModelPanelProps) {
  const [form] = Form.useForm();

  // 初始化表单数据
  const initialValues = {
    models: config.agents.models || {},
  };

  const handleSave = async () => {
    try {
      const values = await form.validateFields();
      await onSave({
        agents: {
          models: values.models,
        },
      });
    } catch (error) {
      console.error('Validation failed:', error);
    }
  };

  // 获取可用的 Provider 列表
  const providers = config.llm.providers || [];

  return (
    <div>
      <h3>Agent 模型分配</h3>
      {providers.length === 0 ? (
        <div style={{ color: '#faad14', marginBottom: 16 }}>
          请先在 LLM Provider 子项添加 Provider
        </div>
      ) : (
        <Form form={form} initialValues={initialValues} layout="vertical">
          {AGENT_ROLES.map((role) => (
            <Card key={role} style={{ marginBottom: 16 }} title={role}>
              <Form.Item
                name={['models', role, 'provider']}
                label="Provider"
                rules={[{ required: true, message: '请选择 Provider' }]}
              >
                <Select
                  placeholder="选择 Provider"
                  options={providers.map((p) => ({
                    value: p.name,
                    label: p.name,
                  }))}
                />
              </Form.Item>
              <Form.Item
                name={['models', role, 'model']}
                label="模型"
              >
                <Input placeholder="留空使用 Provider 默认模型" />
              </Form.Item>
            </Card>
          ))}
          <Button type="primary" onClick={handleSave}>
            保存
          </Button>
        </Form>
      )}
    </div>
  );
}