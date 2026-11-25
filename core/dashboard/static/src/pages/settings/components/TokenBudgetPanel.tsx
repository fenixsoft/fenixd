import { Button, Card, Form, InputNumber, Switch, Typography } from 'antd';
import { getIntl, useIntl } from '@umijs/max';
import type { ConfigData } from '@/services/dashboard';
import SyncFromUserButton from './SyncFromUserButton';
import { SETTINGS_ACTIONS_ROW_STYLE } from '../styles';
import { usePanelDirty } from '../panelDirty';
import { useGatedFormPanel } from '../useGatedFormPanel';

const { Text } = Typography;

// ── 预算/规模预检九项缺省单源（code-review item a4fa6d9dffbd）────────
// initialValues 与回填 effect 曾各写一份字面量（50/50/6/100/3/3/true/30/45），
// 只改其一时初次渲染值与配置缺失时的回填值即分叉——比照 QualityPanel 的
// IMPL_REVIEW_DEFAULTS / QUALITY_DEFAULTS 先例抽模块级常量，缺省调整只改此处。
const AGENTS_DEFAULTS = {
  tokenBudgetMillions: 50,
  dailyRunLimit: 50,
  implRunBudget: 6,
  implRunBudgetMax: 100,
  verifyRedoBudget: 3,
  maxSameCauseRedispatches: 3,
  scalePrecheckEnabled: true,
  scalePrecheckHigher: 30,
  scalePrecheckFull: 45,
} as const;

// ── 预算字段整数校验（code-review item 7010dc857eca，比照 QualityPanel
// POSITIVE_INT_RULE / SystemPanel「precision={0} + 整数校验器」族内口径）──
// 六个预算 InputNumber 语义均为整数（次数 / 百万 token），仅 min/max 拦不住
// 小数：输入 2.5 可通过 validateFields 原样写进配置。抽两条规则复用：
// min=1 的四个「次数」字段用正整数；token_budget_millions 与 daily_run_limit
// 以 0 表关闭/不限，放行 0、仍拒小数。
const POSITIVE_INT_RULE = {
  validator: (_: unknown, v: number | undefined | null) =>
    v != null && Number.isInteger(v) && v > 0
      ? Promise.resolve()
      : Promise.reject(new Error(getIntl().formatMessage({ id: 'settings.token.rule.positiveInt' }))),
};
const NON_NEGATIVE_INT_RULE = {
  validator: (_: unknown, v: number | undefined | null) =>
    v != null && Number.isInteger(v) && v >= 0
      ? Promise.resolve()
      : Promise.reject(new Error(getIntl().formatMessage({ id: 'settings.token.rule.nonNegativeInt' }))),
};

// 九字段表单映射单源（config 取值 ?? AGENTS_DEFAULTS）：initialValues 与回填 effect
// 共用，新增预算字段只改此处，避免两份映射漏改一处导致初值与回填值分叉
function buildAgentsFormValues(agents: ConfigData['agents']) {
  // agents?. 防护（code-review item bf63df93837f，比照 ParallelSettingsPanel
  // 的 item 60ae9a174a6c 同族口径）：旧版本配置或接口降级响应可能缺 agents 段，
  // 首帧 useState(buildValues) 即执行本函数，直接解引用会抛 TypeError 白屏；
  // 缺段时全字段落 AGENTS_DEFAULTS，与 ParallelSettingsPanel 行为一致。
  return {
    token_budget_millions: agents?.token_budget_millions ?? AGENTS_DEFAULTS.tokenBudgetMillions,
    daily_run_limit: agents?.daily_run_limit ?? AGENTS_DEFAULTS.dailyRunLimit,
    impl_run_budget: agents?.impl_run_budget ?? AGENTS_DEFAULTS.implRunBudget,
    impl_run_budget_max: agents?.impl_run_budget_max ?? AGENTS_DEFAULTS.implRunBudgetMax,
    verify_redo_budget: agents?.verify_redo_budget ?? AGENTS_DEFAULTS.verifyRedoBudget,
    max_same_cause_redispatches: agents?.max_same_cause_redispatches ?? AGENTS_DEFAULTS.maxSameCauseRedispatches,
    scale_precheck_enabled: agents?.scale_precheck?.enabled ?? AGENTS_DEFAULTS.scalePrecheckEnabled,
    scale_precheck_higher: agents?.scale_precheck?.higher_threshold ?? AGENTS_DEFAULTS.scalePrecheckHigher,
    scale_precheck_full: agents?.scale_precheck?.full_threshold ?? AGENTS_DEFAULTS.scalePrecheckFull,
  };
}

interface TokenBudgetPanelProps {
  config: ConfigData;
  onSave: (values: Partial<ConfigData>) => Promise<boolean>;
  /** 当前项目名；项目级作用域才显示「同步用户级设置」按钮 */
  project?: string;
  /** 同步成功后回填配置（父组件 setConfig 驱动表单刷新） */
  onConfigSynced?: (config: ConfigData) => void;
}

export default function TokenBudgetPanel({ config, onSave, project, onConfigSynced }: TokenBudgetPanelProps) {
  const intl = useIntl();
  const [form] = Form.useForm();
  // 用户编辑置脏：切页签/作用域前由 index 经 anyPanelDirty 弹丢弃确认
  // （code-review item 8a3eb01dc2b9）
  const { setDirty } = usePanelDirty();
  // 表单脚手架统一走 useGatedFormPanel（code-review item 5c5a259b8443）：
  // savingRef 重入守卫（原 item 53b14fb31196）、序列化比较回填门控（原 item
  // cbec8303669f）、校验/持久化分离的 handleSave（原 item def003cd8cff /
  // 0abd04f38c76 的「父级兜底 toast、子层不重复报错」口径——hook 在 onSave
  // resolve(false) 时不重复提示）由 hook 承载；本面板保留字段映射
  // （buildAgentsFormValues）与保存载荷组装。
  const { saving, initialValues, handleSave } = useGatedFormPanel({
    form,
    buildValues: () => buildAgentsFormValues(config.agents),
    backfillDeps: [config.agents],
    onSave,
    buildPayload: (values): Partial<ConfigData> => {
      // 规模预检开关关闭时两阈值输入被条件卸载，validateFields 只返回已注册
      // 字段（两键为 undefined，序列化后 scale_precheck 只剩 {"enabled": false}，
      // 后端整体替换会把自定义阈值抹成缺省——code-review item 98ad925ee64a）。
      // 经 getFieldsValue(true) 取含已卸载字段在内的 store 值兜底：开关开启时
      // 与 values 同值，关闭时为最近一次已知阈值。
      const store = form.getFieldsValue(true);
      return {
        agents: {
          token_budget_millions: values.token_budget_millions,
          daily_run_limit: values.daily_run_limit,
          impl_run_budget: values.impl_run_budget,
          impl_run_budget_max: values.impl_run_budget_max,
          verify_redo_budget: values.verify_redo_budget,
          max_same_cause_redispatches: values.max_same_cause_redispatches,
          scale_precheck: {
            enabled: values.scale_precheck_enabled,
            // [fenix-ignore:91af39ea54f7] 首次加载即关闭不丢值：回填 effect 挂载即 setFieldsValue 把两阈值（配置原值??缺省）无条件写入 store（不受字段挂载限制），而 getFieldsValue(true) 在 rc-field-form 1.38.2 直接返回整个 store，保存仍回写配置现值
            higher_threshold: values.scale_precheck_higher ?? store.scale_precheck_higher,
            full_threshold: values.scale_precheck_full ?? store.scale_precheck_full,
          },
        },
      };
    },
  });
  // 规模预检开关（agents.scale_precheck.enabled）：关闭时隐藏两阈值输入
  const scalePrecheckOn = Form.useWatch('scale_precheck_enabled', form);

  return (
    <div>
      <h3>{intl.formatMessage({ id: 'settings.token.title' })}</h3>
      <Text type="secondary">{intl.formatMessage({ id: 'settings.token.desc' })}</Text>
      {/* 单一 Form 承载两张卡片：同一保存按钮提交两节配置 */}
      <Form form={form} initialValues={initialValues} layout="vertical" onValuesChange={() => setDirty(true)}>
      <Card style={{ marginTop: 12 }}>
          <Form.Item
            name="token_budget_millions"
            label={
              <>
                {intl.formatMessage({ id: 'settings.token.tokenBudget.label' })}<span className="label-note">{intl.formatMessage({ id: 'settings.token.tokenBudget.note' })}</span>
              </>
            }
            rules={[
              { required: true, message: intl.formatMessage({ id: 'settings.token.tokenBudget.required' }) },
              NON_NEGATIVE_INT_RULE,
              // 上界拦截走 rules（code-review item a4e49b74dbf4，比照 ParallelSettingsPanel
              // 同族口径）：不能用 InputNumber 的 max 代替——blur 时会把越界值静默钳回
              // 边界，用户永远看不到非法输入被拦截的表单错误提示；max 保留作输入辅助。
              { type: 'integer', min: 0, max: 1000, message: intl.formatMessage({ id: 'settings.token.tokenBudget.range' }) },
            ]}
          >
            <InputNumber min={0} max={1000} step={1} precision={0} style={{ width: '100%' }} addonAfter={intl.formatMessage({ id: 'settings.token.unit.millions' })} />
          </Form.Item>
          <Text type="secondary">
            {intl.formatMessage({ id: 'settings.token.tokenBudget.desc' })}
          </Text>

          <Form.Item
            name="daily_run_limit"
            label={
              <>
                {intl.formatMessage({ id: 'settings.token.dailyRunLimit.label' })}<span className="label-note">{intl.formatMessage({ id: 'settings.token.dailyRunLimit.note' })}</span>
              </>
            }
            rules={[
              { required: true, message: intl.formatMessage({ id: 'settings.token.dailyRunLimit.required' }) },
              NON_NEGATIVE_INT_RULE,
              // 同上口径（code-review item a4e49b74dbf4）：上界拦截走 rules，max 仅作输入辅助
              { type: 'integer', min: 0, max: 100000, message: intl.formatMessage({ id: 'settings.token.dailyRunLimit.range' }) },
            ]}
            style={{ marginTop: 24 }}
          >
            <InputNumber min={0} max={100000} step={1} precision={0} style={{ width: '100%' }} addonAfter={intl.formatMessage({ id: 'settings.token.unit.runs' })} />
          </Form.Item>
          <Text type="secondary">
            {intl.formatMessage({ id: 'settings.token.dailyRunLimit.desc' })}
          </Text>

          <Form.Item
            name="impl_run_budget"
            label={
              <>
                {intl.formatMessage({ id: 'settings.token.implRunBudget.label' })}<span className="label-note">（agents.impl_run_budget）</span>
              </>
            }
            dependencies={['impl_run_budget_max']}
            rules={[
              { required: true, message: intl.formatMessage({ id: 'settings.token.implRunBudget.required' }) },
              POSITIVE_INT_RULE,
              ({ getFieldValue }) => ({
                validator(_, value) {
                  const budgetMax = getFieldValue('impl_run_budget_max');
                  if (value == null || budgetMax == null || value <= budgetMax) {
                    return Promise.resolve();
                  }
                  return Promise.reject(new Error(intl.formatMessage({ id: 'settings.token.implRunBudget.maxError' })));
                },
              }),
            ]}
            style={{ marginTop: 24 }}
          >
            <InputNumber min={1} max={1000} step={1} precision={0} style={{ width: '100%' }} addonAfter={intl.formatMessage({ id: 'settings.token.unit.runs' })} />
          </Form.Item>
          <Text type="secondary">
            {intl.formatMessage({ id: 'settings.token.implRunBudget.desc' })}
          </Text>

          <Form.Item
            name="impl_run_budget_max"
            label={
              <>
                {intl.formatMessage({ id: 'settings.token.implRunBudgetMax.label' })}<span className="label-note">（agents.impl_run_budget_max，1-1000）</span>
              </>
            }
            // 反向依赖（code-review item 7376981b5b9b）：上方「预算」字段仅单向
            // 依赖本字段校验「预算 ≤ 上限」；反方向先填大预算再改小上限时，
            // 本字段自身校验仍通过、可保存出 budget > max 组合（保存后被后端
            // 静默夹紧且无提示），故本字段反向依赖预算做对向一致性校验
            dependencies={['impl_run_budget']}
            rules={[
              { required: true, message: intl.formatMessage({ id: 'settings.token.implRunBudgetMax.required' }) },
              POSITIVE_INT_RULE,
              // 同上口径（code-review item a4e49b74dbf4）：上界拦截走 rules，max 仅作输入辅助
              { type: 'integer', min: 1, max: 1000, message: intl.formatMessage({ id: 'settings.token.implRunBudgetMax.range' }) },
              ({ getFieldValue }) => ({
                validator(_, value) {
                  const budget = getFieldValue('impl_run_budget');
                  if (value == null || budget == null || value >= budget) {
                    return Promise.resolve();
                  }
                  return Promise.reject(new Error(intl.formatMessage({ id: 'settings.token.implRunBudgetMax.minError' })));
                },
              }),
            ]}
            style={{ marginTop: 24 }}
          >
            <InputNumber min={1} max={1000} step={1} precision={0} style={{ width: '100%' }} addonAfter={intl.formatMessage({ id: 'settings.token.unit.runs' })} />
          </Form.Item>
          <Text type="secondary">
            {intl.formatMessage({ id: 'settings.token.implRunBudgetMax.desc' })}
          </Text>

          <Form.Item
            name="verify_redo_budget"
            label={
              <>
                {intl.formatMessage({ id: 'settings.token.verifyRedoBudget.label' })}<span className="label-note">（agents.verify_redo_budget，1-10）</span>
              </>
            }
            rules={[
              { required: true, message: intl.formatMessage({ id: 'settings.token.verifyRedoBudget.required' }) },
              POSITIVE_INT_RULE,
              // 同上口径（code-review item a4e49b74dbf4）：上界拦截走 rules，max 仅作输入辅助
              { type: 'integer', min: 1, max: 10, message: intl.formatMessage({ id: 'settings.token.verifyRedoBudget.range' }) },
            ]}
            style={{ marginTop: 24 }}
          >
            <InputNumber min={1} max={10} step={1} precision={0} style={{ width: '100%' }} addonAfter={intl.formatMessage({ id: 'settings.token.unit.runs' })} />
          </Form.Item>
          <Text type="secondary">
            {intl.formatMessage({ id: 'settings.token.verifyRedoBudget.desc' })}
          </Text>

          <Form.Item
            name="max_same_cause_redispatches"
            label={
              <>
                {intl.formatMessage({ id: 'settings.token.sameCauseRedispatch.label' })}<span className="label-note">（agents.max_same_cause_redispatches，1-100）</span>
              </>
            }
            rules={[
              { required: true, message: intl.formatMessage({ id: 'settings.token.sameCauseRedispatch.required' }) },
              POSITIVE_INT_RULE,
              // 同上口径（code-review item a4e49b74dbf4）：上界拦截走 rules，max 仅作输入辅助
              { type: 'integer', min: 1, max: 100, message: intl.formatMessage({ id: 'settings.token.sameCauseRedispatch.range' }) },
            ]}
            style={{ marginTop: 24 }}
          >
            <InputNumber min={1} max={100} step={1} precision={0} style={{ width: '100%' }} addonAfter={intl.formatMessage({ id: 'settings.token.unit.runs' })} />
          </Form.Item>
          <Text type="secondary">
            {intl.formatMessage({ id: 'settings.token.sameCauseRedispatch.descPrefix' })}
            <b>{intl.formatMessage({ id: 'settings.token.sameCauseRedispatch.sameCause' })}</b>
            {intl.formatMessage({ id: 'settings.token.sameCauseRedispatch.descSuffix' })}
          </Text>
      </Card>

      {/* 规模预检：标题与注释置于卡片外，与上方「预算」节同构 */}
      <h3 style={{ marginTop: 32 }}>{intl.formatMessage({ id: 'settings.token.scalePrecheck.title' })}</h3>
      <Text type="secondary">
        {intl.formatMessage({ id: 'settings.token.scalePrecheck.desc' })}
      </Text>
      <Card style={{ marginTop: 12 }}>
          <div className="switch-inline-row">
            <Form.Item name="scale_precheck_enabled" valuePropName="checked" noStyle>
              <Switch data-testid="scale-precheck-switch" />
            </Form.Item>
            <span className="switch-inline-label">
              {intl.formatMessage({ id: 'settings.token.scalePrecheck.enableLabel' })}<span className="label-note">（agents.scale_precheck.enabled）</span>
            </span>
          </div>

          <Text type="secondary" style={{ display: 'block', marginTop: 16 }}>
            {intl.formatMessage({ id: 'settings.token.scalePrecheck.formulaPrefix' })}
            <b>{intl.formatMessage({ id: 'settings.token.scalePrecheck.formula' })}</b>
            {intl.formatMessage({ id: 'settings.token.scalePrecheck.formulaMid' })}
            <code>- [ ]</code>
            {intl.formatMessage({ id: 'settings.token.scalePrecheck.formulaTail' })}
          </Text>

          {scalePrecheckOn ? (
            <>
              <Form.Item
                name="scale_precheck_higher"
                label={
                  <>
                    {intl.formatMessage({ id: 'settings.token.scalePrecheckHigher.label' })}<span className="label-note">（agents.scale_precheck.higher_threshold）</span>
                  </>
                }
                // 反向依赖（code-review item 7376981b5b9b）：下方 full 字段仅单向
                // 依赖本字段校验「full > higher」；反方向先填小 full 再改大 higher
                // 时不重校验会漏拦 higher ≥ full 组合，故本字段反向依赖 full 做
                // 对向一致性校验
                dependencies={['scale_precheck_full']}
                rules={[
                  { required: true, message: intl.formatMessage({ id: 'settings.token.scalePrecheckHigher.required' }) },
                  POSITIVE_INT_RULE,
                  // 同上口径（code-review item 5caf752e76e9）：上界拦截走 rules，max 仅作输入辅助
                  { type: 'integer', min: 1, max: 10000, message: intl.formatMessage({ id: 'settings.token.scalePrecheckHigher.range' }) },
                  ({ getFieldValue }) => ({
                    validator(_, value) {
                      const full = getFieldValue('scale_precheck_full');
                      if (value == null || full == null || value < full) {
                        return Promise.resolve();
                      }
                      return Promise.reject(new Error(intl.formatMessage({ id: 'settings.token.scalePrecheckHigher.maxError' })));
                    },
                  }),
                ]}
                style={{ marginTop: 24 }}
              >
                <InputNumber min={1} max={10000} step={1} precision={0} style={{ width: '100%' }} addonAfter={intl.formatMessage({ id: 'settings.token.unit.points' })} />
              </Form.Item>
              <Text type="secondary">
                {intl.formatMessage({ id: 'settings.token.scalePrecheckHigher.descPrefix' })}
                <b>{intl.formatMessage({ id: 'settings.token.scalePrecheck.greaterThan' })}</b>
                {intl.formatMessage({ id: 'settings.token.scalePrecheckHigher.descSuffix' })}
              </Text>

              <Form.Item
                name="scale_precheck_full"
                label={
                  <>
                    {intl.formatMessage({ id: 'settings.token.scalePrecheckFull.label' })}<span className="label-note">（agents.scale_precheck.full_threshold）</span>
                  </>
                }
                dependencies={['scale_precheck_higher']}
                rules={[
                  { required: true, message: intl.formatMessage({ id: 'settings.token.scalePrecheckFull.required' }) },
                  POSITIVE_INT_RULE,
                  // 同上口径（code-review item 5caf752e76e9）：上界拦截走 rules，max 仅作输入辅助
                  { type: 'integer', min: 1, max: 10000, message: intl.formatMessage({ id: 'settings.token.scalePrecheckFull.range' }) },
                  ({ getFieldValue }) => ({
                    validator(_, value) {
                      const higher = getFieldValue('scale_precheck_higher');
                      if (value == null || higher == null || value > higher) {
                        return Promise.resolve();
                      }
                      return Promise.reject(new Error(intl.formatMessage({ id: 'settings.token.scalePrecheckFull.minError' })));
                    },
                  }),
                ]}
                style={{ marginTop: 24 }}
              >
                <InputNumber min={1} max={10000} step={1} precision={0} style={{ width: '100%' }} addonAfter={intl.formatMessage({ id: 'settings.token.unit.points' })} />
              </Form.Item>
              <Text type="secondary">
                {intl.formatMessage({ id: 'settings.token.scalePrecheckFull.descPrefix' })}
                <b>{intl.formatMessage({ id: 'settings.token.scalePrecheck.greaterThan' })}</b>
                {intl.formatMessage({ id: 'settings.token.scalePrecheckFull.descSuffix' })}
              </Text>
            </>
          ) : null}
      </Card>
      </Form>

      <div style={project ? SETTINGS_ACTIONS_ROW_STYLE : { textAlign: 'right', marginTop: 24 }}>
        {project && onConfigSynced && (
          <SyncFromUserButton project={project} page="token" onSynced={onConfigSynced} />
        )}
        <Button type="primary" onClick={handleSave} loading={saving} disabled={saving} data-testid="token-save">
          {intl.formatMessage({ id: 'settings.token.save' })}
        </Button>
      </div>
    </div>
  );
}
