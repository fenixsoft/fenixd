import { App, Button, Card, Col, Form, Input, Row, Select, Space, Tooltip, Typography } from 'antd';
import {
  CopyOutlined,
  HeartOutlined,
  HolderOutlined,
  MinusCircleOutlined,
  PlusOutlined,
  SnippetsOutlined,
} from '@ant-design/icons';
import { useEffect, useRef, useState } from 'react';
import { checkLlmHealth } from '@/services/dashboard';
import type { AgentModelAssignment, AgentsConfig, AgentsModels, ConfigData } from '@/services/dashboard';
import { cloneRoleValue, type RoleValue } from '@/utils/agentModels';
import { resolveHealthCheckParams, toHealthDisplay, type HealthCheckDisplay } from '@/utils/llmHealth';

import SyncFromUserButton from './SyncFromUserButton';
import { SETTINGS_ACTIONS_ROW_STYLE } from '../styles';
import { usePanelDirty } from '../panelDirty';
import { useGatedFormPanel } from '../useGatedFormPanel';

const { Text } = Typography;

// 与后端 KNOWN_AGENT_TYPES 严格一致（含 code-review/code-fix/knowledge-distiller
// 共 12 个角色，勿增删；code-review item f62e36d1531f：旧注释写 9 个，已漂移——
// 后端新增角色时此处必须同步，tests/test_agent_prompt_files.py 有守卫）
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
  // add-knowledge-atlas：knowledge-distiller（归档蒸馏车道），SPEC 归档后由
  // commit_archive_move 单点派发；模型链 agents.models.knowledge-distiller →
  // 回退默认网关（无中间回退级）
  { key: 'knowledge-distiller', label: 'Knowledge-Distiller（知识蒸馏）' },
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

// config.agents → 表单值单一构造点（code-review item 6c1f14c01b5c）：
// initialValues 与 useEffect 原各自展开同一份键清单，增删键会漂移——抽
// buildFormValues 供两处复用。
function buildFormValues(agents: AgentsConfig) {
  return {
    roleList: toRoleList(agents.models),
    subagentModelOverride: (agents as Record<string, unknown>).subagent_model_override || '',
  };
}

// 渲染后把各角色「rows」Form.List 的 fields 快照写进 ref（比照 LlmProviderPanel
// 的 ActiveKeysSync：写 ref 必须落在 effect 内、渲染保持纯净——渲染期写 ref 在
// 并发渲染下可能带上被丢弃渲染的值，handlePaste 会按陈旧快照清理 healthRows、
// 把健康徽标条目清错行）。fields 含稳定 field.key：handlePaste 是事件回调、拿
// 不到内层 List 的 fields，清理条目须按「行位置 → key」映射
// （code-review item 46bf16b0f8df）
function RowFieldsSync({
  index,
  fields,
  target,
}: {
  index: number;
  fields: Array<{ key: number }>;
  target: { current: Record<number, Array<{ key: number }>> };
}) {
  useEffect(() => {
    target.current[index] = fields;
  }, [target, index, fields]);
  return null;
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
  const { message } = App.useApp();
  const [form] = Form.useForm();
  // 用户编辑置脏：切页签/作用域前由 index 经 anyPanelDirty 弹丢弃确认
  // （code-review item 8a3eb01dc2b9）
  const { setDirty } = usePanelDirty();
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

  // 行内健康检测（add-provider-health-check 4.2）：每行独立状态，loading 防行内
  // 并发重复、行间互不影响。键用 `${index}-${rowField.key}` 组合串（code-review
  // item 0f5501b57f78）：纯位置串会随行删除/拖拽换序把检测结论按位置错配；但裸
  // field.key 也不够——12 个角色 Card 的内层 Form.List 是独立实例、各自 keyRef
  // 从 0 递增，角色间同位置的 field.key 相同，检测状态会错配到其他角色卡的同
  // 位置行（item d4d61f25f4d4）。角色前缀保证跨实例唯一；field.key 部分保证
  // 同卡内删除行时同步清除条目、换序时键随行走、不随位置迁移错配。
  const [healthRows, setHealthRows] = useState<
    Record<string, { loading: boolean; display?: HealthCheckDisplay }>
  >({});

  // 行内健康检测同帧重入守卫（code-review item abd644ca22c4，比照 QualityPanel
  // 的 installInFlight / useGatedFormPanel 的 savingRef 口径）：healthRows 的
  // loading state 渲染生效存在 React 调度间隙，拦不住同帧双击——checkLlmHealth
  // 是慢请求（含网关往返超时），同帧连点会并发发出多个检测请求（重复 toast +
  // last-write-wins 的检测结论）。按 rowKey 记录在飞行、入口写读同帧原子短路；
  // healthRows 的 loading 仍保留，仅作按钮 loading/disabled 视觉反馈。
  const healthCheckInFlight = useRef<Set<string>>(new Set());

  // 各角色「rows」Form.List 的 fields 快照（render 期捕获）：handlePaste 是
  // 事件回调、拿不到内层 List 的稳定 field.key，粘贴覆盖后清理 healthRows 须
  // 按「行位置 → key」映射定位条目（code-review item 46bf16b0f8df）。
  const rowFieldsRef = useRef<Record<number, Array<{ key: number }>>>({});

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
    // setFieldValue 只发 valueUpdate 通知、不回调 onValuesChange，本面板判脏完全
    // 依赖 onValuesChange 显式置脏（panelDirty.ts）——程序化写值后须补置脏，
    // 否则自动填充的修改切页签时不弹丢弃确认、随卸载静默丢失
    // （code-review item ad4ec63bd751）
    setDirty(true);
  };

  // 行内健康检测：检测目标按运行期同款链解析（design D6 / spec「模型分配页签
  // 行内图标按钮」）——模型 = 行内模型 → 角色级默认 → Provider 默认；baseurl/
  // apikey 按行内所选 Provider 名解析。config.llm.providers（props，当前作用域
  // 已保存配置）同时充当表单当前值与回退源：本页签只编辑角色分配、不编辑
  // Provider 本体，两者同源；解析失败提示原因、不发请求。
  const runRowHealthCheck = async (index: number, rIdx: number, rowKey: string) => {
    const rv = form.getFieldValue(['roleList', index]) as RoleValue | undefined;
    const row = (rv?.rows || [])[rIdx];
    const resolved = resolveHealthCheckParams({
      formProviders: providers,
      savedProviders: providers,
      providerName: row?.provider,
      rowModel: row?.model,
      roleModel: rv?.roleModel,
    });
    if ('error' in resolved) {
      message.warning(resolved.error);
      return;
    }
    // 同帧短路（item abd644ca22c4）：前置参数解析是同步代码、无调度间隙，守卫
    // 紧贴请求发起即可；ref 写读同帧原子，命中 = 该行已有检测在飞，直接 return
    if (healthCheckInFlight.current.has(rowKey)) return;
    healthCheckInFlight.current.add(rowKey);
    setHealthRows((m) => ({ ...m, [rowKey]: { loading: true } }));
    try {
      const r = await checkLlmHealth(resolved);
      const display = toHealthDisplay(r);
      setHealthRows((m) => ({ ...m, [rowKey]: { loading: false, display } }));
      if (r.ok) {
        message.success(`健康检测通过：${resolved.model} ${display.short}`);
      } else {
        message.error(`健康检测失败：${r.error_kind || ''}${r.error ? `（${r.error}）` : ''}`);
      }
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e);
      setHealthRows((m) => ({
        ...m,
        [rowKey]: { loading: false, display: { kind: 'fail', short: '失败 · 请求异常', tooltip: msg } },
      }));
      message.error(`健康检测请求失败：${msg}`);
    } finally {
      healthCheckInFlight.current.delete(rowKey);
    }
  };

  // 清除单行健康检测条目（按 handlePaste 同款「provider/生效模型变化即清」口径）：
  // 检测结论是特定 provider+模型组合的一次性结论，行内原位改 Provider 或模型名后
  // 旧徽标（可能是绿色「已验证」）不再代表当前组合，须清掉避免错配误导
  // （code-review item 495527f13465）
  const clearHealthRow = (rowKey: string) => {
    setHealthRows((m) => {
      if (!(rowKey in m)) return m;
      const next = { ...m };
      delete next[rowKey];
      return next;
    });
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
    const before = form.getFieldValue(['roleList', index]) as RoleValue | undefined;
    const pasted = {
      ...cloneRoleValue(clipboard.value),
      roleKey: AGENT_ROLES[index]?.key,
    };
    form.setFieldValue(['roleList', index], pasted);
    // 粘贴整值替换时 rc-field-form 的 keyManager 按位置复用行 key（keys 只在
    // add/remove/move 时更新，外部 setFieldValue 不重建），而 healthRows 按
    // 组合键缓存「该 key 上一次检测的 provider+model」结论——被覆盖行的旧
    // 徽标（可能是绿色「已验证」）会错配到粘贴后的新组合上。与删除行口径一致：
    // 替换前后 provider 与生效模型（行内 model → 角色级缺省）不一致、或被裁剪
    // 掉的旧行，清除该 key 的条目（code-review item 46bf16b0f8df）。
    const oldRows = before?.rows || [];
    const newRows = pasted.rows || [];
    const oldRoleModel = (before?.roleModel || '').trim();
    const newRoleModel = (pasted.roleModel || '').trim();
    const staleKeys = (rowFieldsRef.current[index] || [])
      .map((f, rIdx) => ({ key: f.key, oldRow: oldRows[rIdx], newRow: newRows[rIdx] }))
      .filter(
        ({ oldRow, newRow }) =>
          (oldRow?.provider || '').trim() !== (newRow?.provider || '').trim() ||
          ((oldRow?.model || '').trim() || oldRoleModel) !==
            ((newRow?.model || '').trim() || newRoleModel),
      )
      // rowFieldsRef 存裸 field.key，healthRows 键带角色前缀（见 healthRows 注释）
      .map(({ key }) => `${index}-${key}`);
    if (staleKeys.length > 0) {
      setHealthRows((m) => {
        if (!staleKeys.some((k) => k in m)) return m;
        const next = { ...m };
        staleKeys.forEach((k) => {
          delete next[k];
        });
        return next;
      });
    }
    // setFieldValue 不触发 onValuesChange，判脏不置位会导致粘贴内容切页签时
    // 被静默丢弃（无丢弃确认），写值后显式置脏（code-review item ad4ec63bd751）
    setDirty(true);
    message.success(
      `已粘贴「${clipboard.label}」的模型分配到「${AGENT_ROLES[index]?.label ?? `角色 ${index + 1}`}」`,
    );
  };

  // 表单脚手架统一走 useGatedFormPanel（code-review item 5c5a259b8443）：
  // savingRef 重入守卫（原 item d0faa2345d54 / 38bd12fc895c）、序列化比较回填
  // 门控（原 item 9f98edec21fa）、校验/持久化分离的 handleSave（原 item
  // 3086b7e96c4f）由 hook 承载；本面板保留字段映射（buildFormValues / toModels）
  // 与角色链可用模型校验（checkValues）。
  const { saving, initialValues, handleSave } = useGatedFormPanel({
    form,
    buildValues: () => buildFormValues(config.agents),
    backfillDeps: [config.agents],
    onSave,
    buildPayload: (values): Partial<ConfigData> => ({
      agents: {
        models: toModels(values.roleList),
        subagent_model_override: (values.subagentModelOverride || '').trim(),
      },
    }),
    // v1 improve-failover-model-mapping-ui D4 校验：已配置的链不允许整链无可用模型
    checkValues: (values) => {
      const roleList: RoleValue[] = values.roleList;
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
        // 只判 allRowsHaveModel（code-review item bc1ba7979cf5）：roleDefault
        // 非空时 every 的或链恒真，旧写法 `!roleDefault && !allRowsHaveModel`
        // 的前半永不成立——语义与 `!allRowsHaveModel` 等价，去掉死条件免误导。
        if (!allRowsHaveModel) {
          missing.push(AGENT_ROLES[index]?.label ?? `角色 ${index + 1}`);
        }
      });
      if (missing.length > 0) {
        return `保存失败：${missing.join('、')} 无可用模型（角色级缺省与逐行模型均为空，且 Provider 也无默认模型）`;
      }
      return undefined; // 通过：显式收口（noImplicitReturns）
    },
  });

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
      <Form form={form} initialValues={initialValues} layout="vertical" onValuesChange={() => setDirty(true)} style={{ marginTop: 12 }}>
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
                          {/* 行 fields 快照经 RowFieldsSync 在 effect 内写入 rowFieldsRef
                              （渲染保持纯净，见 RowFieldsSync 注释）；清理 healthRows 仍按
                              「行位置 → key」映射（code-review item 46bf16b0f8df） */}
                          <RowFieldsSync index={index} fields={rowFields} target={rowFieldsRef} />
                          {rowFields.map((rowField, rIdx) => {
                            const curProvider = ((watchList[index]?.rows || [])[rIdx]?.provider || '').trim();
                            const rowId = `${index}-${rIdx}`;
                            const dragging = dragReady === rowId;
                            // 悬停指示线与 onDrop 落点同一套角色校验（code-review item
                            // b0e132f22074）：跨角色卡片的换序会被 onDrop 静默拒绝，
                            // 指示线不应高亮这类非法落点，避免视觉反馈与行为矛盾。
                            const dragFromRole = dragReady === null ? null : Number(dragReady.split('-')[0]);
                            const isOverTarget =
                              dragOver === rowId && dragReady !== null && dragReady !== rowId && dragFromRole === index;
                            // 健康状态按「角色前缀 + 稳定 field.key」组合键取
                            // （跨角色卡唯一；同卡内不随删除/换序的位置迁移错配）
                            const health = healthRows[`${index}-${rowField.key}`];
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
                                      onChange={(val) => {
                                        // 切 Provider 后旧健康结论错配到新组合，先清条目
                                        // （code-review item 495527f13465）
                                        clearHealthRow(`${index}-${rowField.key}`);
                                        autofillProviderDefault(index, rIdx, val as string);
                                      }}
                                    />
                                  </Form.Item>
                                </Col>
                                <Col flex="auto">
                                  <Form.Item name={[rowField.name, 'model']} noStyle>
                                    <Input
                                      // 改模型名即生效模型变化，旧健康结论失效，清条目
                                      // （code-review item 495527f13465）
                                      onChange={() => clearHealthRow(`${index}-${rowField.key}`)}
                                      placeholder={
                                        roleModel
                                          ? `留空用角色级缺省 ${roleModel}`
                                          // 无角色级缺省时按保存校验口径提示
                                          //（逐行须自带模型或依赖 Provider 默认
                                          // 模型；code-review item 7c607abbfc9b）
                                          : '模型名（留空用 Provider 默认模型）'
                                      }
                                    />
                                  </Form.Item>
                                </Col>
                                {/* 最近一次健康检测结果内联展示（口径同模型页签 4.1） */}
                                <Col flex="0 0 auto" style={{ maxWidth: 150 }}>
                                  {health?.display && (
                                    <Tooltip title={health.display.tooltip}>
                                      <Text
                                        data-testid={`health-row-result-${rowId}`}
                                        style={{
                                          color: health.display.kind === 'ok' ? '#52c41a' : '#ff4d4f',
                                          fontSize: 12,
                                          whiteSpace: 'nowrap',
                                        }}
                                      >
                                        {health.display.short}
                                      </Text>
                                    </Tooltip>
                                  )}
                                </Col>
                                {/* 健康检测图标按钮：32px 列，置于删除图标之前（spec 4.2） */}
                                <Col flex="32px" style={{ textAlign: 'right' }}>
                                  <Button
                                    type="text"
                                    size="small"
                                    icon={<HeartOutlined />}
                                    data-testid={`health-row-btn-${rowId}`}
                                    title="健康检测"
                                    aria-label="健康检测"
                                    loading={!!health?.loading}
                                    disabled={!!health?.loading}
                                    onClick={() => runRowHealthCheck(index, rIdx, `${index}-${rowField.key}`)}
                                  />
                                </Col>
                                <Col flex="32px" style={{ textAlign: 'right' }}>
                                  <Button
                                    type="text"
                                    danger
                                    icon={<MinusCircleOutlined />}
                                    title="删除此行"
                                    onClick={() => {
                                      removeRow(rIdx);
                                      // 清除被删行的健康检测条目（code-review item
                                      // 0f5501b57f78）：组合键不随位置迁移被覆盖，
                                      // 须显式清除
                                      clearHealthRow(`${index}-${rowField.key}`);
                                    }}
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
              {/* 保存按钮行复用统一常量（code-review item 7c1311483b0a）：与其余六个
                  设置面板同一写法，项目/非项目两分支间距一致，避免视觉漂移 */}
              <div style={project ? SETTINGS_ACTIONS_ROW_STYLE : { textAlign: 'right', marginTop: 24 }}>
                {project && onConfigSynced && (
                  <SyncFromUserButton project={project} page="agents" onSynced={onConfigSynced} />
                )}
                <Button type="primary" onClick={handleSave} loading={saving} disabled={saving}>
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
