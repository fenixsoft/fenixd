import { Button, Card, Col, Form, Input, InputNumber, Popconfirm, Row, Space, Switch, Tooltip, Typography, message } from 'antd';
import { DownOutlined, HeartOutlined, MinusCircleOutlined, PlusOutlined, RightOutlined } from '@ant-design/icons';
import { useEffect, useRef, useState } from 'react';
import { checkLlmHealth } from '@/services/dashboard';
import type { ConfigData, LlmProvider, ProviderBillingPrice } from '@/services/dashboard';
import { toHealthDisplay, type HealthCheckDisplay } from '@/utils/llmHealth';

import SyncFromUserButton from './SyncFromUserButton';
import { SETTINGS_ACTIONS_ROW_STYLE } from '../styles';
import { usePanelDirty } from '../panelDirty';

const { Text } = Typography;

// env 对象 ↔ 编辑行数组（Form.List 需要数组形态）
interface EnvEntry {
  key: string;
  value: string;
}

// improve-provider-billing-config（task 3.3）：价格行编辑值（归属所在卡片，
// 无 provider 字段；四项单价允许空，保存时校验）
interface PriceRowValues {
  model?: string;
  input_per_million?: number | null;
  output_per_million?: number | null;
  cache_read_per_million?: number | null;
  cache_creation_per_million?: number | null;
}

interface ProviderRowValues extends Partial<LlmProvider> {
  envEntries?: EnvEntry[];
  billingEnabled?: boolean;
  prices?: PriceRowValues[];
}

interface FormValues {
  providers: ProviderRowValues[];
}

// 四项单价字段（顺序固定；Form.Item label 作标题栏，布局范式同「名称 / Base URL」行）
const PRICE_FIELDS: Array<{
  key: keyof PriceRowValues;
  label: string;
}> = [
  { key: 'input_per_million', label: '输入' },
  { key: 'output_per_million', label: '输出' },
  { key: 'cache_read_per_million', label: '缓存读' },
  { key: 'cache_creation_per_million', label: '缓存写' },
];

// 折叠区头部行样式（「启用计费」「自定义环境变量」共用）：整行可点切换展开
const COLLAPSE_HEADER_STYLE: React.CSSProperties = {
  display: 'flex',
  justifyContent: 'space-between',
  alignItems: 'center',
  cursor: 'pointer',
  userSelect: 'none',
  padding: '4px 0',
};

// 折叠箭头（展开 ↓ / 折叠 →）
function CollapseArrow({ open }: { open: boolean }) {
  return open ? (
    <DownOutlined style={{ color: '#999', fontSize: 12 }} />
  ) : (
    <RightOutlined style={{ color: '#999', fontSize: 12 }} />
  );
}

// 渲染后把活跃卡片 key 同步进 ref（供 handleSave 校验失败时一键展开折叠区）。
// 写 ref 必须落在 effect 内、渲染保持纯净（同 CodeFixProgressCard 约定：
// 渲染期写 ref 在并发渲染下可能带上被丢弃渲染的值）
function ActiveKeysSync({ keys, target }: { keys: number[]; target: { current: number[] } }) {
  useEffect(() => {
    target.current = keys;
  }, [target, keys]);
  return null;
}

function toEnvEntries(env?: Record<string, string>): EnvEntry[] {
  return Object.entries(env || {}).map(([key, value]) => ({ key, value }));
}

// 该卡片的内嵌价格行（billing.prices 直接回填，无 provider 字段）
function pricesForProvider(prices: PriceRowValues[] | undefined): PriceRowValues[] {
  return (prices || []).map((p) => ({ ...p }));
}

// provider 行 → 表单值单源构建（code-review item b5c2b4e67d3b，比照
// StaleCodeSelfhealPanel 的 buildScsFormValues 同族约定）：initialValues 与
// 回填 effect 原各内联一份完全相同的映射，行对象增删派生字段时漏改一处即
// 初值与回填值分叉——抽单源两处共用。
function buildProvidersFormValues(providers: LlmProvider[] | undefined) {
  return {
    providers: (providers || []).map((p) => ({
      ...p,
      envEntries: toEnvEntries(p.env),
      billingEnabled: p.billing?.enabled ?? false,
      prices: pricesForProvider(p.billing?.prices),
    })),
  };
}

// 完全空的价格行（无模型名且四项单价全空）——保存时先行剔除，避免阻塞校验
function isBlankPriceRow(r: PriceRowValues | undefined): boolean {
  if (!r) return true;
  if ((r.model || '').trim()) return false;
  return [r.input_per_million, r.output_per_million, r.cache_read_per_million, r.cache_creation_per_million]
    .every((v) => v == null || v === '');
}

function toProviders(values: FormValues): LlmProvider[] {
  // 剥离回填时 spread 进行对象的旧 env/billing 键（code-review item 6f3dd544086b）：
  // initialValues/回填 effect 用 { ...p, ... } 构造行对象，旧 env/billing 作为
  // inert 键留在 store 里并经 validateFields 回流；billing 下方无条件覆盖本无碍，
  // 但 env 仅在非空时覆盖——删空全部环境变量行后 env={} 会跳过赋值，rest.env
  // 仍是旧对象被整体写回，删除操作被静默吞掉。故解构时同步剥离两键。
  return values.providers.map(({ prices, envEntries, billingEnabled, env: _staleEnv, billing: _staleBilling, ...rest }) => {
    const env: Record<string, string> = {};
    (envEntries || []).forEach((e) => {
      const k = (e?.key || '').trim();
      const v = (e?.value || '').trim();
      // 保留空值条目（code-review item 2606c79ffa80）：键有值空是合法语义
      //（部分工具区分「未设置」与「空串」，如清空代理变量），旧条件 `k && v`
      // 会把它静默吞掉，保存成功但回读丢失；后端 env 仅要求值为 str
      //（core/config.py），空串合法。重复键已由 handleSave 保存前拦截，
      // 此处不存在静默覆盖。
      if (k) env[k] = v;
    });
    // improve-provider-billing-config（task 3.4）：价格行写入 providers[i].billing
    // 内嵌结构；卡片开关关闭时不携带生效价格行（enabled: false + 空 prices）。
    const cardPrices: ProviderBillingPrice[] = (prices || [])
      .filter((r) => !isBlankPriceRow(r))
      .map((r) => ({
        model: (r.model || '').trim(),
        // 保存前 validateFields 已保证四项单价必填，此处按数值提交
        input_per_million: r.input_per_million as number,
        output_per_million: r.output_per_million as number,
        cache_read_per_million: r.cache_read_per_million as number,
        cache_creation_per_million: r.cache_creation_per_million as number,
      }));
    // 旧 env/billing 已剥离（见上），env/billing 均无条件覆盖写入：
    // env={}（用户删空全部环境变量行）也必须落盘，否则删除操作静默失效
    //（item 6f3dd544086b 的缺陷本体）。
    return { ...rest, env, billing: { enabled: !!billingEnabled, prices: cardPrices } } as LlmProvider;
  });
}

interface LlmProviderPanelProps {
  config: ConfigData;
  onSave: (values: Partial<ConfigData>) => Promise<void>;
  /** 当前项目名；项目级作用域才显示「同步用户级设置」按钮 */
  project?: string;
  /** 同步成功后回填配置（父组件 setConfig 驱动表单刷新） */
  onConfigSynced?: (config: ConfigData) => void;
}

export default function LlmProviderPanel({ config, onSave, project, onConfigSynced }: LlmProviderPanelProps) {
  const [form] = Form.useForm();
  // 用户编辑置脏：切页签/作用域前由 index 经 anyPanelDirty 弹丢弃确认
  // （code-review item 8a3eb01dc2b9）
  const { setDirty } = usePanelDirty();
  // 观察整个 providers 数组以驱动每张卡片「启用计费」开关对价格区的显隐
  const providersWatch = Form.useWatch('providers', form);
  // 每卡片两个折叠区（环境变量 / 计费价格）的展开态，key=Form.List field.key
  // （稳定 id；删除卡片后残留条目无害）。默认全部折叠。
  const [envOpenMap, setEnvOpenMap] = useState<Record<number, boolean>>({});
  const [billingOpenMap, setBillingOpenMap] = useState<Record<number, boolean>>({});
  // 活跃卡片 key（由 ActiveKeysSync 渲染后写入）：校验失败时一键展开，
  // 让藏在折叠区的错误可见（折叠用 display 切换，字段恒注册，值与校验不受折叠影响）
  const activeKeysRef = useRef<number[]>([]);

  // 初始化表单数据（与回填 effect 共用 buildProvidersFormValues 单源）
  const initialValues = buildProvidersFormValues(config.llm.providers);

  // 监听 config 变化，更新表单值。回填门控（code-review item 5d6582ba9951，
  // 同 AgentModelPanel item 9f98edec21fa / ApprovalModePanel item a8786c075c4f）：
  // 无条件 setFieldsValue 会用外部 config 覆盖用户正在编辑、尚未保存的内容
  // （保存后重载/其它面板保存/同步用户级设置触发的刷新）。对回填产物做
  // 序列化比较，只在内容真正变化时回填。
  const lastProvidersBackfillRef = useRef('');
  useEffect(() => {
    const next = buildProvidersFormValues(config.llm.providers);
    const key = JSON.stringify(next);
    if (key === lastProvidersBackfillRef.current) return;
    lastProvidersBackfillRef.current = key;
    form.setFieldsValue(next);
  }, [config.llm.providers, form]);

  // 校验/拦截失败时展开全部折叠区——错误行（价格必填、重复 model）可能藏在
  // 折叠区内，不展开会让保存看起来「静默失败」
  const expandAllSections = () => {
    const allOpen: Record<number, boolean> = {};
    activeKeysRef.current.forEach((k) => {
      allOpen[k] = true;
    });
    setEnvOpenMap((m) => ({ ...m, ...allOpen }));
    setBillingOpenMap((m) => ({ ...m, ...allOpen }));
  };

  // 每张卡片的健康检测状态（key=Form.List field.key 稳定 id；仅保留最近一次
  // 结果，检测中 loading 禁重复点击——add-provider-health-check 4.1）
  const [healthMap, setHealthMap] = useState<
    Record<number, { loading: boolean; display?: HealthCheckDisplay }>
  >({});
  // 保存重入守卫（code-review item fe84991f84a0）：onSave 是异步，提交期间
  // 按钮可继续点击会发出重叠保存请求（并发写同一配置文件，结果取决于响应
  // 到达顺序）——saving 期间置 loading/disabled 并在入口短路。
  const [saving, setSaving] = useState(false);

  // 表单当前值直传（未保存修改即测）；Base URL / API Key / 默认模型名任一为空
  // 直接提示补齐、不发请求（spec「表单值不完整不发请求」）
  const runHealthCheck = async (field: { key: number; name: number }) => {
    const baseurl = (form.getFieldValue(['providers', field.name, 'baseurl']) || '').trim();
    const apikey = (form.getFieldValue(['providers', field.name, 'apikey']) || '').trim();
    const model = (form.getFieldValue(['providers', field.name, 'model']) || '').trim();
    const missing = [!baseurl && 'Base URL', !apikey && 'API Key', !model && '默认模型名'].filter(
      Boolean,
    );
    if (missing.length > 0) {
      message.warning(`健康检测前请先补齐该卡片的 ${missing.join('、')}`);
      return;
    }
    setHealthMap((m) => ({ ...m, [field.key]: { loading: true } }));
    try {
      const r = await checkLlmHealth({ baseurl, apikey, model });
      const display = toHealthDisplay(r);
      setHealthMap((m) => ({ ...m, [field.key]: { loading: false, display } }));
      if (r.ok) {
        message.success(`健康检测通过：${model} ${display.short}`);
      } else {
        message.error(`健康检测失败：${r.error_kind || ''}${r.error ? `（${r.error}）` : ''}`);
      }
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e);
      setHealthMap((m) => ({
        ...m,
        [field.key]: { loading: false, display: { kind: 'fail', short: '失败 · 请求异常', tooltip: msg } },
      }));
      message.error(`健康检测请求失败：${msg}`);
    }
  };

  const handleSave = async () => {
    if (saving) {
      return;
    }
    setSaving(true);
    try {
      // 先剔除完全空的价格行（占位行），避免其阻塞整体校验
      const snapshot = form.getFieldsValue(true);
      let pruned = false;
      (snapshot?.providers || []).forEach((p: ProviderRowValues, i: number) => {
        const rows = Array.isArray(p?.prices) ? p.prices : [];
        const kept = rows.filter((r) => !isBlankPriceRow(r));
        if (kept.length !== rows.length) {
          form.setFieldValue(['providers', i, 'prices'], kept);
          pruned = true;
        }
      });
      if (pruned) {
        form.validateFields().catch(() => {});
      }
      // 同卡片重复 model 前端拦截（先于必填校验执行：spec「重复时保存被拦截并提示」，
      // 即使新增重复行尚未填价也给出明确提示；后端同样校验，双保险）
      const dupCheck = form.getFieldsValue(true);
      const dupRows = dupCheck?.providers || [];
      for (let i = 0; i < dupRows.length; i++) {
        const p = dupRows[i] as ProviderRowValues;
        // 自定义环境变量重复键拦截（code-review item 2606c79ffa80）：多条同键
        // 条目经对象字面量赋值后仅最后一行生效，界面所见两行与实际落盘一行
        // 不一致——保存前显式拦截（口径同下方重复 model 拦截；后端 env 只做
        // str 类型校验不查重，此为前端专属防线）。所有卡片均校验：环境变量
        // 不随计费开关卸载，与价格行口径不同。
        const seenEnvKeys = new Set<string>();
        for (const e of Array.isArray(p?.envEntries) ? p.envEntries : []) {
          const k = (e?.key || '').trim();
          if (!k) continue;
          if (seenEnvKeys.has(k)) {
            message.error(
              `环境变量键重复：Provider「${p?.name || i + 1}」内存在重复的 ${k}，请合并或删除重复行后重试`
            );
            expandAllSections(); // 重复行可能在折叠区内，展开让用户可见可改
            return;
          }
          seenEnvKeys.add(k);
        }
        // 计费开关关闭的卡片跳过重复校验：此时价格 Form.List 已被条件卸载，
        // store 里 preserve 的隐藏行既不参与保存（validateFields 只含已注册
        // 字段，toProviders 落空 prices），用户也无界面路径查看/删除——若据此
        // 拦截保存，用户只能先打开开关才能修复。口径与实际保存保持一致。
        if (!p?.billingEnabled) continue;
        const cardPrices = (Array.isArray(p?.prices) ? p.prices : [])
          .filter((r) => !isBlankPriceRow(r));
        const seen = new Set<string>();
        for (const row of cardPrices) {
          const model = (row?.model || '').trim();
          if (!model) continue;
          if (seen.has(model)) {
            message.error(
              `价格行重复：Provider「${p?.name || i + 1}」内存在重复模型名 ${model}，请修改后重试`
            );
            expandAllSections(); // 重复行可能在折叠区内，展开让用户可见可改
            return;
          }
          seen.add(model);
        }
      }
      const values: FormValues = await form.validateFields();
      const providers = toProviders(values);
      // 分离「表单校验」与「保存持久化」（code-review item 25f889b81633，
      // 比照 AgentModelPanel 3086b7e96c4f）：onSave 拒绝（网络/500）此前被
      // 当作校验失败只落 console.error，用户点击保存毫无反应。持久化失败
      // 给显式 message.error 反馈。
      try {
        await onSave({ llm: { providers } });
      } catch (error) {
        message.error(`保存失败：${error instanceof Error ? error.message : String(error)}`);
      }
    } catch {
      // 校验失败：展开全部折叠区，让藏在折叠区的错误（如价格行必填）可见
      // （antd 已在表单内渲染提示；不落 console，避免触发 no_console_error 断言）
      expandAllSections();
    } finally {
      setSaving(false);
    }
  };

  return (
    <div>
      <h3>模型</h3>
      <Text type="secondary">定义可用的 LLM 提供者（Base URL / API Key / 默认模型）。</Text>
      <Form form={form} initialValues={initialValues} layout="vertical" onValuesChange={() => setDirty(true)} style={{ marginTop: 12 }}>
        <Form.List name="providers">
          {(fields, { add, remove }) => (
            <>
              {/* 渲染后收集活跃卡片 key（供 handleSave 校验失败时一键展开折叠区） */}
              <ActiveKeysSync keys={fields.map((f) => f.key)} target={activeKeysRef} />
              {fields.map((field, index) => {
                // 折叠态与概要计数（useWatch 驱动；field.key 为卡片稳定 id）
                const envOpen = !!envOpenMap[field.key];
                const billingOpen = !!billingOpenMap[field.key];
                const health = healthMap[field.key];
                const envCount = ((providersWatch?.[field.name]?.envEntries || []) as EnvEntry[]).filter(
                  (e) => (e?.key || '').trim(),
                ).length;
                const priceCount = ((providersWatch?.[field.name]?.prices || []) as PriceRowValues[]).filter(
                  (r) => !isBlankPriceRow(r),
                ).length;
                return (
                <Card
                  key={field.key}
                  style={{ marginBottom: 16 }}
                  title={`Provider ${index + 1}`}
                  extra={
                    <Space size={4}>
                      {/* 最近一次健康检测结果内联展示（成功绿/失败红，tooltip 完整错误） */}
                      {health?.display && (
                        <Tooltip title={health.display.tooltip}>
                          <Text
                            data-testid={`health-result-${index}`}
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
                      {/* 健康检测图标按钮：与模型分配页签行内按钮同款（心形+tooltip） */}
                      <Button
                        size="small"
                        type="text"
                        icon={<HeartOutlined />}
                        data-testid={`health-check-btn-${index}`}
                        title="健康检测"
                        aria-label="健康检测"
                        loading={!!health?.loading}
                        disabled={!!health?.loading}
                        onClick={() => runHealthCheck(field)}
                      />
                      <Popconfirm
                        title="确定删除此 Provider？"
                        onConfirm={() => remove(field.name)}
                        okText="删除"
                        cancelText="取消"
                      >
                        <Button type="text" danger icon={<MinusCircleOutlined />} />
                      </Popconfirm>
                    </Space>
                  }
                >
                  {/* 名称 / Base URL / API Key / 默认模型名：标签与输入框同行
                      （单项 horizontal 覆盖 Form 的 vertical），labelCol 固定宽
                      保证四行输入框左缘对齐、等宽拉伸 */}
                  <Row gutter={16}>
                    <Col xs={24} md={12}>
                      <Form.Item
                        name={[field.name, 'name']}
                        label="名称"
                        layout="horizontal"
                        labelCol={{ flex: '0 0 96px' }}
                        wrapperCol={{ flex: '1 1 0%' }}
                        rules={[{ required: true, message: '请输入 Provider 名称' }]}
                      >
                        <Input placeholder="例如：openai" />
                      </Form.Item>
                    </Col>
                    <Col xs={24} md={12}>
                      <Form.Item
                        name={[field.name, 'baseurl']}
                        label="Base URL"
                        layout="horizontal"
                        labelCol={{ flex: '0 0 96px' }}
                        wrapperCol={{ flex: '1 1 0%' }}
                        rules={[{ required: true, message: '请输入 Base URL' }]}
                      >
                        <Input placeholder="https://api.openai.com/v1" />
                      </Form.Item>
                    </Col>
                  </Row>
                  <Row gutter={16}>
                    <Col xs={24} md={12}>
                      <Form.Item
                        name={[field.name, 'apikey']}
                        label="API Key"
                        layout="horizontal"
                        labelCol={{ flex: '0 0 96px' }}
                        wrapperCol={{ flex: '1 1 0%' }}
                        rules={[{ required: true, message: '请输入 API Key' }]}
                      >
                        <Input.Password placeholder="sk-..." />
                      </Form.Item>
                    </Col>
                    <Col xs={24} md={12}>
                      <Form.Item
                        name={[field.name, 'model']}
                        label="默认模型名"
                        layout="horizontal"
                        labelCol={{ flex: '0 0 96px' }}
                        wrapperCol={{ flex: '1 1 0%' }}
                      >
                        <Input placeholder="deepseek-v4-flash" />
                      </Form.Item>
                    </Col>
                  </Row>
                  {/* 折叠区 1：自定义环境变量（默认折叠；display 切换保 Form.List
                      注册，折叠时值与校验不受影响——保存照常带上隐藏行） */}
                  <div
                    style={COLLAPSE_HEADER_STYLE}
                    onClick={() => setEnvOpenMap((m) => ({ ...m, [field.key]: !m[field.key] }))}
                    data-testid={`env-collapse-${index}`}
                  >
                    <span>
                      自定义环境变量
                      <span className="label-note">
                        （选填，运行时注入子进程，如 CLAUDE_CODE_MAX_CONTEXT_TOKENS=1000000）
                      </span>
                      {!envOpen && envCount > 0 && (
                        <span className="label-note" style={{ marginLeft: 8 }}>
                          已配置 {envCount} 项
                        </span>
                      )}
                    </span>
                    <CollapseArrow open={envOpen} />
                  </div>
                  <div style={{ display: envOpen ? undefined : 'none', marginBottom: 16, marginTop: 8 }}>
                    <Form.List name={[field.name, 'envEntries']}>
                      {(envFields, { add: addEnv, remove: removeEnv }) => (
                        <>
                          {envFields.map((envField) => (
                            <Row key={envField.key} gutter={8} align="middle" style={{ marginBottom: 8 }}>
                              <Col xs={11} md={12}>
                                <Form.Item name={[envField.name, 'key']} noStyle>
                                  <Input placeholder="参数名（如 CLAUDE_CODE_MAX_CONTEXT_TOKENS）" />
                                </Form.Item>
                              </Col>
                              <Col xs={10} md={11}>
                                <Form.Item name={[envField.name, 'value']} noStyle>
                                  <Input placeholder="值（如 1000000）" />
                                </Form.Item>
                              </Col>
                              <Col xs={3} md={1} style={{ textAlign: 'right' }}>
                                <Button
                                  type="text"
                                  danger
                                  icon={<MinusCircleOutlined />}
                                  aria-label={`删除环境变量 ${envField.name + 1}`}
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
                  </div>
                  {/* 折叠区 2：启用计费（task 3.2 开关 + 折叠箭头同行；开关开启
                      自动展开价格编辑区；点开关不触发折叠切换） */}
                  <div
                    style={COLLAPSE_HEADER_STYLE}
                    onClick={() => setBillingOpenMap((m) => ({ ...m, [field.key]: !m[field.key] }))}
                    data-testid={`billing-collapse-${index}`}
                  >
                    <span>
                      <Form.Item
                        name={[field.name, 'billingEnabled']}
                        valuePropName="checked"
                        noStyle
                      >
                        <Switch
                          data-testid={`billing-switch-${index}`}
                          onClick={(_, e) => e.stopPropagation()}
                          onChange={(checked) => {
                            // 开启计费：自动展开价格区；若无价格行则自动补一行
                            // （预填卡片默认模型名），免手工点击
                            if (!checked) return;
                            setBillingOpenMap((m) => ({ ...m, [field.key]: true }));
                            const prices = form.getFieldValue(['providers', field.name, 'prices']);
                            if (Array.isArray(prices) && prices.length > 0) return;
                            const cardModel = form.getFieldValue(['providers', field.name, 'model']) || '';
                            form.setFieldValue(['providers', field.name, 'prices'], [{ model: cardModel }]);
                          }}
                        />
                      </Form.Item>
                      <span style={{ marginLeft: 8 }}>
                        启用计费
                        <span className="label-note">
                          （开启后按实际 model@provider 与配置单价本地计算每 run 成本，价格单位 $/1M tokens）
                        </span>
                      </span>
                      {!billingOpen && priceCount > 0 && (
                        <span className="label-note" style={{ marginLeft: 8 }}>
                          已配置 {priceCount} 个模型
                        </span>
                      )}
                    </span>
                    <CollapseArrow open={billingOpen} />
                  </div>
                  {/* 价格编辑区：开关开启且折叠展开时可见。外层 display 保
                      Form.List 恒注册——折叠不丢行、校验照常（开关关闭仍条件
                      渲染，与旧语义一致：关=不带价格行保存） */}
                  <div style={{ display: billingOpen ? undefined : 'none' }}>
                    {!!(providersWatch?.[field.name]?.billingEnabled) && (
                      <Form.List name={[field.name, 'prices']}>
                        {(priceFields, { add: addPrice, remove: removePrice }) => (
                          <>
                            {priceFields.map((priceField, rowIndex) => (
                              <div
                                key={priceField.key}
                                className="billing-price-row"
                                style={{
                                  border: '1px solid #f0f0f0',
                                  borderRadius: 8,
                                  padding: '4px 12px 0',
                                  marginBottom: 12,
                                }}
                              >
                                <Row gutter={16} align="middle">
                                  <Col xs={23} md={23}>
                                    <Form.Item
                                      name={[priceField.name, 'model']}
                                      label="模型名"
                                      rules={[{ required: true, message: '模型名必填' }]}
                                    >
                                      <Input placeholder="模型名（如 deepseek-v4-flash）" />
                                    </Form.Item>
                                  </Col>
                                  {/* 删除符号占 1 格，其余宽度给模型名；行高 86（Form.Item 62
                                      + 底 margin 24）居中下 marginTop 6 使按钮与「模型名」
                                      输入框垂直居中对齐（按钮中心 = (86-32-6)/2+6+16 = 46） */}
                                  <Col xs={1} md={1} style={{ textAlign: 'right', marginTop: 6 }}>
                                    <Button
                                      type="text"
                                      danger
                                      icon={<MinusCircleOutlined />}
                                      aria-label={`删除价格行 ${rowIndex + 1}`}
                                      onClick={() => removePrice(priceField.name)}
                                    />
                                  </Col>
                                </Row>
                                <Row gutter={16}>
                                  {PRICE_FIELDS.map((f) => (
                                    <Col xs={12} md={12} key={f.key}>
                                      <Form.Item
                                        name={[priceField.name, f.key]}
                                        label={
                                          <>
                                            {f.label}
                                            <span className="label-note">($/1M tokens)</span>
                                          </>
                                        }
                                        rules={[{ required: true, message: `${f.label}单价必填` }]}
                                      >
                                        <InputNumber<number | string>
                                          min={0}
                                          step={0.01}
                                          placeholder="0.00"
                                          style={{ width: '100%' }}
                                          controls={false}
                                          changeOnBlur
                                          parser={(v) => (v == null ? '' : v.replace(/[^\d.]/g, ''))}
                                          title={`每百万 ${f.label} token 费用 ($/1M)`}
                                        />
                                      </Form.Item>
                                    </Col>
                                  ))}
                                </Row>
                              </div>
                            ))}
                            <Button
                              type="dashed"
                              onClick={() => {
                                // task 3.3：新增行自动预填卡片「默认模型名」（可修改）
                                const cardModel = form.getFieldValue(['providers', field.name, 'model']) || '';
                                addPrice({ model: cardModel });
                              }}
                              block
                              icon={<PlusOutlined />}
                            >
                              添加模型价格
                            </Button>
                          </>
                        )}
                      </Form.List>
                    )}
                  </div>
                </Card>
                );
              })}
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
        <div style={project ? SETTINGS_ACTIONS_ROW_STYLE : { textAlign: 'right', marginTop: 24 }}>
          {project && onConfigSynced && (
            <SyncFromUserButton project={project} page="llm" onSynced={onConfigSynced} />
          )}
          <Button type="primary" onClick={handleSave} loading={saving} disabled={saving}>
            保存
          </Button>
        </div>
      </Form>
    </div>
  );
}
