import { Button, Card, Col, Form, Input, Row, Select, Space, Typography, message } from 'antd';
import {
  CopyOutlined,
  HolderOutlined,
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

// 后端 normalize_agent_models 输出 → 编辑器行（str / 对象 / 混合数组统一为 {provider, model}；
// 行内自带 roleKey，保存时按 key 映射回后端，不依赖「第 i 项 == 第 i 角色」下标不变量）
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
      roleKey: key,
      roleModel: (m && m.model) || '',
      rows,
    };
  });
}

// 编辑器状态 → agents.models patch（仅收集已选 provider 的行；未配置的角色不写）。
// 按 roleKey 映射（code-review item 042e1dc46cb4）：按下标映射依赖「表单第 i 项
// == AGENT_ROLES 第 i 项」的隐式不变量，角色表调整/外部 setFieldsValue 注入/后端
// merge 回填使顺序或长度漂移时，某角色的模型会被静默写到错误的后端键上。缺
// roleKey 的行（异常注入形态）回落下标，索引越界则跳过。
function toModels(roleList: RoleValue[] = []): AgentsModels {
  const models: AgentsModels = {};
  roleList.forEach((rv, index) => {
    const key = rv?.roleKey || AGENT_ROLES[index]?.key;
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

  // 行拖拽排序（原生 HTML5 DnD，零依赖）：
  // - dragReady：当前「按住手柄」的行（`${roleIndex}-${rowIndex}`）——行默认
  //   draggable=false，仅按住手柄时启用，避免输入框/下拉的正常选词被拖拽劫持
  // - dragOver：拖动中悬停的目标行（同结构），用于落位高亮
  const [dragReady, setDragReady] = useState<string | null>(null);
  const [dragOver, setDragOver] = useState<string | null>(null);

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

  // 把剪贴板内容覆盖到某角色（角色级默认模型与全部 Provider 行一起替换）。
  // roleKey 重写为目标卡片的 key：粘贴体携带的是源角色的 key，不改写会把
  // 本卡（B 角色）的分配经 roleKey 直写进源角色（A）的后端键。
  const handlePaste = (index: number) => {
    if (!clipboard) return;
    form.setFieldValue(['roleList', index], {
      ...cloneRoleValue(clipboard.value),
      roleKey: AGENT_ROLES[index]?.key,
    });
    message.success(
      `已粘贴「${clipboard.label}」的模型分配到「${AGENT_ROLES[index]?.label ?? `角色 ${index + 1}`}」`,
    );
  };

  const handleSave = async () => {
    // 分离「表单校验」与「保存持久化」（code-review item 3086b7e96c4f）：旧实现
    // 两者混在同一 try/catch 且只 console.error，把校验失败与网络/500 混为一谈，
    // 对纯校验失败可能违反 no_console_error 断言，onSave 拒绝时也无用户反馈。
    let values;
    try {
      values = await form.validateFields();
    } catch {
      // 校验失败：antd 已在表单内渲染提示，不落 console
      return;
    }
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
    try {
      await onSave({
        agents: {
          models: toModels(roleList),
          subagent_model_override: (values.subagentModelOverride || '').trim(),
        },
      });
    } catch (error) {
      // 保存持久化失败：给用户显式反馈而非静默
      message.error(`保存失败：${error instanceof Error ? error.message : String(error)}`);
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
                            const rowId = `${index}-${rIdx}`;
                            const dragging = dragReady === rowId;
                            const isOverTarget = dragOver === rowId && dragReady !== null && dragReady !== rowId;
                            return (
                              <Row
                                key={rowField.key}
                                gutter={8}
                                align="middle"
                                style={{
                                  marginBottom: 8,
                                  // 拖动中的源行淡显；悬停目标行顶部插入指示线。
                                  // 注意 draggable 放手柄 span 上——antd Row 不透传
                                  // draggable 到 DOM（实测被吞），手柄是原生元素可靠；
                                  // dragstart 自手柄冒泡到本行处理器。
                                  opacity: dragging ? 0.5 : undefined,
                                  boxShadow: isOverTarget ? 'inset 0 2px 0 #1677ff' : undefined,
                                  borderRadius: isOverTarget ? 4 : undefined,
                                }}
                                onDragStart={(e) => {
                                  e.dataTransfer.effectAllowed = 'move';
                                  // Firefox 需要 setData 才会进入拖拽
                                  e.dataTransfer.setData('text/plain', rowId);
                                }}
                                onDragOver={(e) => {
                                  if (dragReady === null || dragReady === rowId) return;
                                  e.preventDefault(); // 允许成为 drop 目标
                                  e.dataTransfer.dropEffect = 'move';
                                  setDragOver(rowId);
                                }}
                                onDrop={(e) => {
                                  e.preventDefault();
                                  const fromId = dragReady;
                                  setDragReady(null);
                                  setDragOver(null);
                                  if (!fromId || fromId === rowId) return;
                                  const [fromRole, fromRow] = fromId.split('-').map(Number);
                                  // 只允许同角色卡片内换序（跨卡片行分属不同 Form.List）
                                  if (fromRole !== index) return;
                                  moveRow(fromRow, rIdx);
                                }}
                                onDragEnd={() => {
                                  // 拖拽取消/落点无效时也要复位（drop 不总触发）
                                  setDragReady(null);
                                  setDragOver(null);
                                }}
                              >
                                <Col flex="32px" style={{ textAlign: 'center' }}>
                                  <span
                                    title="拖动调整顺序"
                                    aria-label={`拖动调整第 ${rIdx + 1} 行顺序`}
                                    draggable={dragging}
                                    style={{
                                      cursor: dragging ? 'grabbing' : 'grab',
                                      color: '#999',
                                      padding: '4px 6px',
                                      userSelect: 'none',
                                    }}
                                    onMouseDown={() => setDragReady(rowId)}
                                    onMouseUp={() => setDragReady(null)}
                                  >
                                    <HolderOutlined />
                                  </span>
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
