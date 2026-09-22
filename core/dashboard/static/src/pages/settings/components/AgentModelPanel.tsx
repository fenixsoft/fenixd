import { Button, Card, Col, Form, Input, Row, Select, Space, Typography, message } from 'antd';
import {
  ArrowDownOutlined,
  ArrowUpOutlined,
  CopyOutlined,
  MinusCircleOutlined,
  PlusOutlined,
  SnippetsOutlined,
} from '@ant-design/icons';
import { useEffect, useState } from 'react';
import type { AgentModelAssignment, AgentsModels, ConfigData } from '@/services/dashboard';
import { cloneRoleValue, type RoleValue } from '@/utils/agentModels';

import SyncFromUserButton, { SETTINGS_ACTIONS_ROW_STYLE } from './SyncFromUserButton';

const { Text } = Typography;

// 与后端 KNOWN_AGENT_TYPES 严格一致（含 code-review 共 11 个角色，勿增删；
// code-review item f62e36d1531f：旧注释写 9 个，已漂移）
const AGENT_ROLES = [
  { key: 'implementer', label: 'Implementer（执行）' },
  { key: 'planner-plan', label: 'Planner Plan（生成场景）' },
  { key: 'planner-judge', label: 'Planner Judge（判定结果）' },
  { key: 'verifier', label: 'Verifier（验证）' },
  { key: 'administrator', label: 'Administrator（运维）' },
  // evolution（框架自进化）复用本条模型链（agents.models.self-review → 回退 administrator），
  // 后端不设 agents.models.evolution 键，故不单独成 card
  { key: 'self-review', label: 'Self-Review（自省）/ Evolution（自改进）' },
  { key: 'fast-track', label: 'Fast-Track（快速通道）' },
  { key: 'spec-review', label: 'Spec Review（方案评审）' },
  { key: 'dispute-judge', label: 'Dispute Judge（交付物终审）' },
  // add-code-review-agent-and-quality-tab：code-review（周期性仓库级代码审查），
  // 独立模型链（agents.models.code-review → 回退 self-review → administrator）
  { key: 'code-review', label: 'Code-Review（代码审查）' },
  // add-code-review-auto-fix：code-fix（自动修复车道），模型链复用 code-review
  // （agents.models.code-fix → 回退 code-review → self-review → administrator）
  { key: 'code-fix', label: 'Code-Fix（自动修复）' },
];

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
  /** 当前项目名；项目级作用域才显示「同步用户级设置」按钮 */
  project?: string;
  /** 同步成功后回填配置（父组件 setConfig 驱动表单刷新） */
  onConfigSynced?: (config: ConfigData) => void;
}

export default function AgentModelPanel({ config, onSave, project, onConfigSynced }: AgentModelPanelProps) {
  const [form] = Form.useForm();
  const providers = config.llm.providers || [];

  // 「复制/粘贴」临时剪贴板：存放某个角色当前的分配（角色级默认模型 + Provider 行链）。
  // 仅存活于本组件生命周期（刷新即失效），用于把一份配置快速套用到其他角色。
  const [clipboard, setClipboard] = useState<{ label: string; value: RoleValue } | null>(null);

  const initialValues = {
    roleList: toRoleList(config.agents.models),
    subagentModelOverride: (config.agents as Record<string, unknown>).subagent_model_override || '',
  };

  useEffect(() => {
    form.setFieldsValue({
      roleList: toRoleList(config.agents.models),
      subagentModelOverride: (config.agents as Record<string, unknown>).subagent_model_override || '',
    });
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

  // 选中 Provider 后模型名留空 → 自动填入该 Provider 的默认模型（显式化运行期
  // 的「留空回退 Provider 默认」解析值）；已手填不覆盖，无默认模型则保持留空。
  const autofillProviderDefault = (roleIndex: number, rowIndex: number, providerName: string) => {
    if (!providerName) return;
    const rows = form.getFieldValue(['roleList', roleIndex, 'rows']);
    if (!Array.isArray(rows)) return;
    const row = rows[rowIndex];
    if (!row || (row.model || '').trim()) return;
    const def = (providers.find((p) => p.name === providerName) || {}).model;
    if (!def) return;
    // 只写目标字段路径（code-review item a65a4acb0953）：旧实现读整份 rows 后
    // 全量写回（读-改-写），若期间用户在其它行输入/勾选 Provider（或其它自动
    // 填充并发执行），会以快照覆盖这些更新。form.setFieldValue 支持嵌套路径
    // 数组成员，直接定位该行 model 字段避免整数组替换。
    form.setFieldValue(['roleList', roleIndex, 'rows', rowIndex, 'model'], def);
  };

  // 复制某角色的当前分配到剪贴板（深拷贝，之后编辑该卡片不影响副本）
  const handleCopy = (index: number) => {
    const cur = form.getFieldValue(['roleList', index]) as RoleValue | undefined;
    // 下标空值防护（code-review item 2863ab0c2d54）：Form.List 项数可能多于
    // AGENT_ROLES（角色表删减/外部 setFieldsValue 注入），裸下标解引用会抛
    // TypeError 使整个设置页白屏。
    const roleLabel = AGENT_ROLES[index]?.label ?? `角色 ${index + 1}`;
    setClipboard({ label: roleLabel, value: cloneRoleValue(cur) });
    message.success(`已复制「${roleLabel}」的模型分配`);
  };

  // 把剪贴板内容覆盖到某角色（角色级默认模型与全部 Provider 行一起替换）
  const handlePaste = (index: number) => {
    if (!clipboard) return;
    form.setFieldValue(['roleList', index], cloneRoleValue(clipboard.value));
    message.success(
      `已粘贴「${clipboard.label}」的模型分配到「${AGENT_ROLES[index]?.label ?? `角色 ${index + 1}`}」`,
    );
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
          missing.push(AGENT_ROLES[index]?.label ?? `角色 ${index + 1}`);
        }
      });
      if (missing.length > 0) {
        message.error(
          `保存失败：${missing.join('、')} 无可用模型（角色级缺省与逐行模型均为空，且 Provider 也无默认模型）`,
        );
        return;
      }
      await onSave({
        agents: {
          models: toModels(roleList),
          subagent_model_override: (values.subagentModelOverride || '').trim(),
        },
      });
    } catch (error) {
      console.error('Validation failed:', error);
    }
  };

  return (
    <div>
      <h3>模型分配</h3>
      <Text type="secondary">
        为每种 Agent 角色分配 Provider 与模型。模型名留空时使用所选 Provider 的默认模型。
      </Text>
      {providers.length === 0 && (
        <div style={{ color: '#faad14', marginTop: 12 }}>
          ⚠ 当前作用域没有可用的 LLM Provider，无法为 Agent 分配模型。请先在上方「模型
          页签」添加 Provider 并保存，再回来分配；或切换到项目级配置（选择项目后进入配置页）进行分配。
        </div>
      )}
      <Form form={form} initialValues={initialValues} layout="vertical" style={{ marginTop: 12 }}>
        <Form.Item
          name="subagentModelOverride"
          label="子代理模型覆盖（Subagent Model Override）"
          tooltip="非空时，直连 Provider 车道的隔离 settings.json 的 env 子代理 tier 映射（CLAUDE_CODE_SUBAGENT_MODEL 等）使用该值而非 provider 默认模型。留空 = 使用 provider model。"
        >
          <Input placeholder="模型名（如 deepseek-v4-flash），留空使用 Provider 默认" />
        </Form.Item>
        <Form.List name="roleList">
          {(fields) => (
            <>
              {fields.map((field, index) => {
                const role = AGENT_ROLES[index] ?? { key: `role-${index}`, label: `角色 ${index + 1}` };
                const rv = watchList[index] ?? {};
                const roleModel = (rv?.roleModel || '').trim();
                return (
                  <Card
                    key={field.key}
                    style={{ marginBottom: 16 }}
                    title={role.label}
                    extra={
                      <Space size={0}>
                        <Button
                          type="text"
                          icon={<CopyOutlined />}
                          title="复制本角色的模型分配"
                          aria-label="复制本角色的模型分配"
                          onClick={() => handleCopy(index)}
                        />
                        <Button
                          type="text"
                          icon={<SnippetsOutlined />}
                          title={
                            clipboard
                              ? `粘贴「${clipboard.label}」的模型分配`
                              : '剪贴板为空，请先复制某个角色的模型分配'
                          }
                          aria-label="粘贴模型分配"
                          disabled={!clipboard}
                          onClick={() => handlePaste(index)}
                        />
                      </Space>
                    }
                  >
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
                                      onChange={(val) => autofillProviderDefault(index, rIdx, val as string)}
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
              <div style={project ? { ...SETTINGS_ACTIONS_ROW_STYLE, marginTop: 12 } : { textAlign: 'right' }}>
                {project && onConfigSynced && (
                  <SyncFromUserButton project={project} page="agents" onSynced={onConfigSynced} />
                )}
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
