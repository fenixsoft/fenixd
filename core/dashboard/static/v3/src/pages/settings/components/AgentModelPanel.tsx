import { Button, Card, Col, Form, Input, Row, Select, Space, Typography, message } from 'antd';
import {
  ArrowDownOutlined,
  ArrowUpOutlined,
  MinusCircleOutlined,
  PlusOutlined,
} from '@ant-design/icons';
import { useEffect } from 'react';
import type { AgentModelAssignment, AgentsModels, ConfigData } from '@/services/dashboard';

const { Text } = Typography;

// 与 v1 KNOWN_AGENT_TYPES 严格一致（5 个角色，勿增删）
const AGENT_ROLES = [
  { key: 'implementer', label: 'Implementer（执行）' },
  { key: 'planner-plan', label: 'Planner Plan（生成场景）' },
  { key: 'planner-judge', label: 'Planner Judge（判定结果）' },
  { key: 'verifier', label: 'Verifier（验证）' },
  { key: 'administrator', label: 'Administrator（运维）' },
];

interface ChainRow {
  provider: string;
  model: string;
}

interface RoleValue {
  roleModel: string;
  rows: ChainRow[];
}

// 后端 normalize_agent_models 输出 → 编辑器行（str / 对象 / 混合数组统一为 {provider, model}）
function toRoleList(models: AgentsModels = {}): RoleValue[] {
  return AGENT_ROLES.map(({ key }) => {
    const m: AgentModelAssignment | undefined = models[key];
    const raw = (m && m.provider) || [];
    const rows = (Array.isArray(raw) ? raw : [raw])
      .map((r) =>
        typeof r === 'string'
          ? { provider: r, model: '' }
          : { provider: (r && r.provider) || '', model: (r && r.model) || '' },
      )
      .filter((r) => r.provider !== '');
    return {
      roleModel: (m && m.model) || '',
      rows,
    };
  });
}

// 编辑器状态 → agents.models patch（仅收集已选 provider 的行；未配置的角色不写）
function toModels(roleList: RoleValue[] = []): AgentsModels {
  const models: AgentsModels = {};
  roleList.forEach((rv, index) => {
    const key = AGENT_ROLES[index]?.key;
    if (!key) return;
    const roleModel = (rv?.roleModel || '').trim();
    const chain = (rv?.rows || [])
      .map((r) => ({ provider: (r?.provider || '').trim(), model: (r?.model || '').trim() }))
      .filter((r) => r.provider);
    if (chain.length === 0 && !roleModel) return;
    const entry: AgentModelAssignment = { provider: chain };
    if (roleModel) entry.model = roleModel;
    models[key] = entry;
  });
  return models;
}

interface AgentModelPanelProps {
  config: ConfigData;
  onSave: (values: Partial<ConfigData>) => Promise<void>;
}

export default function AgentModelPanel({ config, onSave }: AgentModelPanelProps) {
  const [form] = Form.useForm();
  const providers = config.llm.providers || [];

  const initialValues = { roleList: toRoleList(config.agents.models) };

  useEffect(() => {
    form.setFieldsValue({ roleList: toRoleList(config.agents.models) });
  }, [config.agents.models, form]);

  // 监听表单值：行内 Provider 选项回显保真 + 模型输入框 placeholder 随角色级缺省联动
  const watchList: RoleValue[] = Form.useWatch('roleList', form) || [];

  const providerOptions = (current: string) => {
    const names = providers.map((p) => p.name);
    if (current && !names.includes(current)) {
      names.unshift(current);
    }
    return names.map((n) => ({ value: n, label: n }));
  };

  const handleSave = async () => {
    try {
      const values = await form.validateFields();
      const roleList: RoleValue[] = values.roleList;
      // v1 improve-failover-model-mapping-ui D4 校验：已配置的链不允许整链无可用模型
      const providerDefaults: Record<string, string> = {};
      providers.forEach((p) => {
        if (p.name) providerDefaults[p.name] = p.model || '';
      });
      const missing: string[] = [];
      roleList.forEach((rv, index) => {
        if (!rv?.rows || rv.rows.length === 0) return;
        const roleDefault = (rv.roleModel || '').trim();
        const allRowsHaveModel = rv.rows.every((r) => {
          const p = (r?.provider || '').trim();
          if (!p) return true; // 空 provider 行保存时丢弃
          return !!((r?.model || '').trim() || roleDefault || providerDefaults[p]);
        });
        if (!roleDefault && !allRowsHaveModel) {
          missing.push(AGENT_ROLES[index].label);
        }
      });
      if (missing.length > 0) {
        message.error(
          `保存失败：${missing.join('、')} 无可用模型（角色级缺省与逐行模型均为空，且 Provider 也无默认模型）`,
        );
        return;
      }
      await onSave({ agents: { models: toModels(roleList) } });
    } catch (error) {
      console.error('Validation failed:', error);
    }
  };

  return (
    <div>
      <h3>Agent 模型分配</h3>
      <Text type="secondary">
        为每种 Agent 角色分配 Provider 与模型。模型名留空时使用所选 Provider 的默认模型。
      </Text>
      {providers.length === 0 && (
        <div style={{ color: '#faad14', marginTop: 12 }}>
          ⚠ 当前作用域没有可用的 LLM Provider，无法为 Agent 分配模型。请先在上方「LLM Provider
          列表」添加 Provider 并保存，再回来分配；或切换到项目级配置（选择项目后进入配置页）进行分配。
        </div>
      )}
      <Form form={form} initialValues={initialValues} layout="vertical" style={{ marginTop: 12 }}>
        <Form.List name="roleList">
          {(fields) => (
            <>
              {fields.map((field, index) => {
                const role = AGENT_ROLES[index];
                const rv = watchList[index];
                const roleModel = (rv?.roleModel || '').trim();
                return (
                  <Card key={field.key} style={{ marginBottom: 16 }} title={role.label}>
                    <Form.Item
                      name={[field.name, 'roleModel']}
                      label={
                        <>
                          角色级默认模型
                          <span className="label-note">（留空表示无全链缺省，逐元素必须自带模型）</span>
                        </>
                      }
                    >
                      <Input placeholder="模型名（如 deepseek-v4-flash），可选" />
                    </Form.Item>
                    <Form.List name={[field.name, 'rows']}>
                      {(rowFields, { add: addRow, remove: removeRow, move: moveRow }) => (
                        <>
                          {rowFields.map((rowField, rIdx) => {
                            const curProvider = ((watchList[index]?.rows || [])[rIdx]?.provider || '').trim();
                            return (
                              <Row key={rowField.key} gutter={8} align="middle" style={{ marginBottom: 8 }}>
                                <Col flex="64px">
                                  <Space size={0}>
                                    <Button
                                      type="text"
                                      size="small"
                                      icon={<ArrowUpOutlined />}
                                      title="上移"
                                      disabled={rIdx === 0}
                                      onClick={() => moveRow(rIdx, rIdx - 1)}
                                    />
                                    <Button
                                      type="text"
                                      size="small"
                                      icon={<ArrowDownOutlined />}
                                      title="下移"
                                      disabled={rIdx === rowFields.length - 1}
                                      onClick={() => moveRow(rIdx, rIdx + 1)}
                                    />
                                  </Space>
                                </Col>
                                <Col flex="220px">
                                  <Form.Item name={[rowField.name, 'provider']} noStyle>
                                    <Select
                                      placeholder="-- 选择 Provider --"
                                      options={providerOptions(curProvider)}
                                      style={{ width: '100%' }}
                                    />
                                  </Form.Item>
                                </Col>
                                <Col flex="auto">
                                  <Form.Item name={[rowField.name, 'model']} noStyle>
                                    <Input
                                      placeholder={
                                        roleModel
                                          ? `留空用角色级缺省 ${roleModel}`
                                          : '模型名（留空用角色级缺省）'
                                      }
                                    />
                                  </Form.Item>
                                </Col>
                                <Col flex="32px" style={{ textAlign: 'right' }}>
                                  <Button
                                    type="text"
                                    danger
                                    icon={<MinusCircleOutlined />}
                                    title="删除此行"
                                    onClick={() => removeRow(rIdx)}
                                  />
                                </Col>
                              </Row>
                            );
                          })}
                          <Button
                            type="dashed"
                            onClick={() => addRow({ provider: '', model: '' })}
                            block
                            icon={<PlusOutlined />}
                          >
                            添加 Provider 行
                          </Button>
                        </>
                      )}
                    </Form.List>
                  </Card>
                );
              })}
              <div style={{ textAlign: 'right' }}>
                <Button type="primary" onClick={handleSave}>
                  保存
                </Button>
              </div>
            </>
          )}
        </Form.List>
      </Form>
    </div>
  );
}
