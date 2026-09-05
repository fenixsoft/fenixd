import { Button, Card, Col, Form, Input, InputNumber, Popconfirm, Row, Switch, Typography, message } from 'antd';
import { MinusCircleOutlined, PlusOutlined } from '@ant-design/icons';
import { useEffect } from 'react';
import type { ConfigData, LlmProvider, ProviderBillingPrice } from '@/services/dashboard';

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

function toEnvEntries(env?: Record<string, string>): EnvEntry[] {
  return Object.entries(env || {}).map(([key, value]) => ({ key, value }));
}

// 该卡片的内嵌价格行（billing.prices 直接回填，无 provider 字段）
function pricesForProvider(prices: PriceRowValues[] | undefined): PriceRowValues[] {
  return (prices || []).map((p) => ({ ...p }));
}

// 完全空的价格行（无模型名且四项单价全空）——保存时先行剔除，避免阻塞校验
function isBlankPriceRow(r: PriceRowValues | undefined): boolean {
  if (!r) return true;
  if ((r.model || '').trim()) return false;
  return [r.input_per_million, r.output_per_million, r.cache_read_per_million, r.cache_creation_per_million]
    .every((v) => v == null || v === '');
}

function toProviders(values: FormValues): LlmProvider[] {
  return values.providers.map(({ prices, envEntries, billingEnabled, ...rest }) => {
    const env: Record<string, string> = {};
    (envEntries || []).forEach((e) => {
      const k = (e?.key || '').trim();
      const v = (e?.value || '').trim();
      if (k && v) env[k] = v;
    });
    if (Object.keys(env).length > 0) rest.env = env;
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
    rest.billing = { enabled: !!billingEnabled, prices: cardPrices };
    return rest as LlmProvider;
  });
}

interface LlmProviderPanelProps {
  config: ConfigData;
  onSave: (values: Partial<ConfigData>) => Promise<void>;
}

export default function LlmProviderPanel({ config, onSave }: LlmProviderPanelProps) {
  const [form] = Form.useForm();
  // 观察整个 providers 数组以驱动每张卡片「启用计费」开关对价格区的显隐
  const providersWatch = Form.useWatch('providers', form);

  // 初始化表单数据
  const initialValues = {
    providers: (config.llm.providers || []).map((p) => ({
      ...p,
      envEntries: toEnvEntries(p.env),
      billingEnabled: p.billing?.enabled ?? false,
      prices: pricesForProvider(p.billing?.prices),
    })),
  };

  // 监听 config 变化，更新表单值
  useEffect(() => {
    form.setFieldsValue({
      providers: (config.llm.providers || []).map((p) => ({
        ...p,
        envEntries: toEnvEntries(p.env),
        billingEnabled: p.billing?.enabled ?? false,
        prices: pricesForProvider(p.billing?.prices),
      })),
    });
  }, [config.llm.providers, form]);

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
      // 同卡片重复 model 前端拦截（先于必填校验执行：spec「重复时保存被拦截并提示」，
      // 即使新增重复行尚未填价也给出明确提示；后端同样校验，双保险）
      const dupCheck = form.getFieldsValue(true);
      const dupRows = dupCheck?.providers || [];
      for (let i = 0; i < dupRows.length; i++) {
        const p = dupRows[i] as ProviderRowValues;
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
            return;
          }
          seen.add(model);
        }
      }
      const values: FormValues = await form.validateFields();
      const providers = toProviders(values);
      await onSave({ llm: { providers } });
    } catch (error) {
      console.error('Validation failed:', error);
    }
  };

  return (
    <div>
      <h3>模型</h3>
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
                  {/* improve-provider-billing-config（task 3.2）：卡片级「启用计费」开关，
                      价格编辑区仅该卡片开关开启时出现；文字紧随开关同行 */}
                  <Form.Item style={{ marginBottom: 16 }}>
                    <Form.Item
                      name={[field.name, 'billingEnabled']}
                      valuePropName="checked"
                      noStyle
                    >
                      <Switch
                        data-testid={`billing-switch-${index}`}
                        onChange={(checked) => {
                          // 开启计费时若无价格行则自动补一行（预填卡片默认模型名），免手工点击
                          if (!checked) return;
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
                  </Form.Item>
                  {!!(providersWatch?.[field.name]?.billingEnabled) && (
                    <>
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
