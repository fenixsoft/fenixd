import { Button, Card, Col, Divider, Form, Input, InputNumber, Popconfirm, Row, Select, Switch, Typography, message } from 'antd';
import { MinusCircleOutlined, PlusOutlined } from '@ant-design/icons';
import { useEffect } from 'react';
import type { ConfigData, LlmBillingPrice, LlmProvider } from '@/services/dashboard';

const { Text } = Typography;

// env 对象 ↔ 编辑行数组（Form.List 需要数组形态）
interface EnvEntry {
  key: string;
  value: string;
}

// add-model-billing-cost-display（task 4.2）：价格行编辑值（四项单价允许空，保存时校验）
interface PriceRowValues {
  provider?: string;
  model?: string;
  input_per_million?: number | null;
  output_per_million?: number | null;
  cache_read_per_million?: number | null;
  cache_creation_per_million?: number | null;
}

interface ProviderRowValues extends Partial<LlmProvider> {
  envEntries?: EnvEntry[];
  prices?: PriceRowValues[];
}

interface FormValues {
  billingEnabled?: boolean;
  providers: ProviderRowValues[];
}

// 四项单价字段（顺序固定；label 用于占位与列头提示）
const PRICE_FIELDS: Array<{
  key: keyof LlmBillingPrice;
  label: string;
}> = [
  { key: 'input_per_million', label: '输入' },
  { key: 'output_per_million', label: '输出' },
  { key: 'cache_read_per_million', label: '缓存读' },
  { key: 'cache_creation_per_million', label: '缓存写' },
];

function toEnvEntries(env?: Record<string, string>): EnvEntry[] {
  return Object.entries(env || {}).map(([key, value]) => ({ key, value }));
}

// 该 provider 的既有价格行（按 provider 分组回填对应卡片；孤儿行不展示，防丢行）
function pricesForProvider(prices: LlmBillingPrice[] | undefined, providerName: string): PriceRowValues[] {
  return (prices || []).filter((p) => p.provider === providerName).map((p) => ({ ...p }));
}

// 完全空的价格行（无模型名且四项单价全空）——保存时先行剔除，避免阻塞校验
function isBlankPriceRow(r: PriceRowValues | undefined): boolean {
  if (!r) return true;
  if ((r.model || '').trim()) return false;
  return [r.input_per_million, r.output_per_million, r.cache_read_per_million, r.cache_creation_per_million]
    .every((v) => v == null || v === '');
}

function toProviders(values: FormValues): LlmProvider[] {
  return values.providers.map(({ prices, envEntries, ...rest }) => {
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
  const billingEnabled = Form.useWatch('billingEnabled', form);

  // 价格行 provider Select 选项（取自 llm.providers，从源头防拼错）
  const providerOptions = (config.llm.providers || []).map((p) => ({ value: p.name, label: p.name }));

  // 初始化表单数据
  const initialValues = {
    billingEnabled: config.llm.billing?.enabled ?? false,
    providers: (config.llm.providers || []).map((p) => ({
      ...p,
      envEntries: toEnvEntries(p.env),
      prices: pricesForProvider(config.llm.billing?.prices, p.name),
    })),
  };

  // 监听 config 变化，更新表单值
  useEffect(() => {
    form.setFieldsValue({
      billingEnabled: config.llm.billing?.enabled ?? false,
      providers: (config.llm.providers || []).map((p) => ({
        ...p,
        envEntries: toEnvEntries(p.env),
        prices: pricesForProvider(config.llm.billing?.prices, p.name),
      })),
    });
  }, [config.llm.providers, config.llm.billing, form]);

  const handleSave = async () => {
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
      const values: FormValues = await form.validateFields();
      const providers = toProviders(values);
      // 平铺所有卡片的价格行 → llm.billing.prices
      const priceRows = (values.providers || []).flatMap((p) => p.prices || []).map((r) => ({
        provider: (r.provider || '').trim(),
        model: (r.model || '').trim(),
        input_per_million: r.input_per_million,
        output_per_million: r.output_per_million,
        cache_read_per_million: r.cache_read_per_million,
        cache_creation_per_million: r.cache_creation_per_million,
      }));
      // 重复 provider+model 前端拦截（后端同样校验，双保险）
      const seen = new Set<string>();
      for (const row of priceRows) {
        const key = `${row.provider}@${row.model}`;
        if (seen.has(key)) {
          message.error(`价格行重复：${row.provider}@${row.model}，请修改后重试`);
          return;
        }
        seen.add(key);
      }
      await onSave({
        llm: {
          providers,
          billing: {
            enabled: !!values.billingEnabled,
            prices: priceRows,
          },
        },
      });
    } catch (error) {
      console.error('Validation failed:', error);
    }
  };

  return (
    <div>
      <h3>模型</h3>
      <Text type="secondary">定义可用的 LLM 提供者（Base URL / API Key / 默认模型）。</Text>
      <Form form={form} initialValues={initialValues} layout="vertical" style={{ marginTop: 12 }}>
        <Form.Item
          name="billingEnabled"
          label={
            <>
              启用计费信息
              <span className="label-note">
                （可选；开启后按实际 model@provider 与配置单价本地计算每 run 成本，价格单位 $/1M tokens）
              </span>
            </>
          }
          valuePropName="checked"
          style={{ marginBottom: 16 }}
        >
          <Switch data-testid="billing-enabled-switch" />
        </Form.Item>
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
                    <Col xs={24} md={12}>
                      <Form.Item
                        name={[field.name, 'name']}
                        label="名称"
                        rules={[{ required: true, message: '请输入 Provider 名称' }]}
                      >
                        <Input placeholder="例如：openai" />
                      </Form.Item>
                    </Col>
                    <Col xs={24} md={12}>
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
                    <Col xs={24} md={12}>
                      <Form.Item
                        name={[field.name, 'apikey']}
                        label="API Key"
                        rules={[{ required: true, message: '请输入 API Key' }]}
                      >
                        <Input.Password placeholder="sk-..." />
                      </Form.Item>
                    </Col>
                    <Col xs={24} md={12}>
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
                  {/* add-model-billing-cost-display（spec「开关开启出现价格区」）：
                      计费开关开启时每个 Provider 卡片内出现「添加模型价格」行编辑区 */}
                  {!!billingEnabled && (
                    <>
                      <Divider style={{ margin: '12px 0' }} orientation="left">
                        <span className="label-note">计费价格（$/1M tokens，四项单价必填）</span>
                      </Divider>
                      <Form.List name={[field.name, 'prices']}>
                        {(priceFields, { add: addPrice, remove: removePrice }) => (
                          <>
                            {priceFields.map((priceField) => (
                              <Row
                                key={priceField.key}
                                gutter={8}
                                align="middle"
                                style={{ marginBottom: 8 }}
                                className="billing-price-row"
                              >
                                <Col xs={24} md={5}>
                                  <Form.Item
                                    name={[priceField.name, 'provider']}
                                    rules={[{ required: true, message: '选择 Provider' }]}
                                  >
                                    <Select
                                      options={providerOptions}
                                      placeholder="Provider"
                                      showSearch
                                    />
                                  </Form.Item>
                                </Col>
                                <Col xs={24} md={5}>
                                  <Form.Item
                                    name={[priceField.name, 'model']}
                                    rules={[{ required: true, message: '模型名必填' }]}
                                  >
                                    <Input placeholder="模型名（如 deepseek-v4-flash）" />
                                  </Form.Item>
                                </Col>
                                {PRICE_FIELDS.map((f) => (
                                  <Col xs={12} md={3} key={f.key}>
                                    <Form.Item
                                      name={[priceField.name, f.key]}
                                      rules={[{ required: true, message: `${f.label}单价必填` }]}
                                    >
                                      <InputNumber
                                        min={0}
                                        step={0.01}
                                        placeholder={f.label}
                                        style={{ width: '100%' }}
                                        controls={false}
                                        title={`每百万 ${f.label} token 费用 ($/1M)`}
                                      />
                                    </Form.Item>
                                  </Col>
                                ))}
                                <Col xs={12} md={3} style={{ textAlign: 'right' }}>
                                  <Button
                                    type="text"
                                    danger
                                    icon={<MinusCircleOutlined />}
                                    onClick={() => removePrice(priceField.name)}
                                  />
                                </Col>
                              </Row>
                            ))}
                            <Button
                              type="dashed"
                              onClick={() => {
                                const cardProvider = form.getFieldValue(['providers', field.name, 'name']);
                                addPrice({ provider: cardProvider || providerOptions[0]?.value || '' });
                              }}
                              block
                              icon={<PlusOutlined />}
                            >
                              添加模型价格
                            </Button>
                          </>
                        )}
                      </Form.List>
                    </>
                  )}
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