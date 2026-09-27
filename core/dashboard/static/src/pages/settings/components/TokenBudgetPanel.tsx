import { Button, Card, Form, InputNumber, Switch, Typography, message } from 'antd';
import { useEffect, useRef, useState } from 'react';
import type { ConfigData } from '@/services/dashboard';
import SyncFromUserButton from './SyncFromUserButton';
import { SETTINGS_ACTIONS_ROW_STYLE } from '../styles';
import { usePanelDirty } from '../panelDirty';

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

// 九字段表单映射单源（config 取值 ?? AGENTS_DEFAULTS）：initialValues 与回填 effect
// 共用，新增预算字段只改此处，避免两份映射漏改一处导致初值与回填值分叉
function buildAgentsFormValues(agents: ConfigData['agents']) {
  return {
    token_budget_millions: agents.token_budget_millions ?? AGENTS_DEFAULTS.tokenBudgetMillions,
    daily_run_limit: agents.daily_run_limit ?? AGENTS_DEFAULTS.dailyRunLimit,
    impl_run_budget: agents.impl_run_budget ?? AGENTS_DEFAULTS.implRunBudget,
    impl_run_budget_max: agents.impl_run_budget_max ?? AGENTS_DEFAULTS.implRunBudgetMax,
    verify_redo_budget: agents.verify_redo_budget ?? AGENTS_DEFAULTS.verifyRedoBudget,
    max_same_cause_redispatches: agents.max_same_cause_redispatches ?? AGENTS_DEFAULTS.maxSameCauseRedispatches,
    scale_precheck_enabled: agents.scale_precheck?.enabled ?? AGENTS_DEFAULTS.scalePrecheckEnabled,
    scale_precheck_higher: agents.scale_precheck?.higher_threshold ?? AGENTS_DEFAULTS.scalePrecheckHigher,
    scale_precheck_full: agents.scale_precheck?.full_threshold ?? AGENTS_DEFAULTS.scalePrecheckFull,
  };
}

interface TokenBudgetPanelProps {
  config: ConfigData;
  onSave: (values: Partial<ConfigData>) => Promise<void>;
  /** 当前项目名；项目级作用域才显示「同步用户级设置」按钮 */
  project?: string;
  /** 同步成功后回填配置（父组件 setConfig 驱动表单刷新） */
  onConfigSynced?: (config: ConfigData) => void;
}

export default function TokenBudgetPanel({ config, onSave, project, onConfigSynced }: TokenBudgetPanelProps) {
  const [form] = Form.useForm();
  // 用户编辑置脏：切页签/作用域前由 index 经 anyPanelDirty 弹丢弃确认
  // （code-review item 8a3eb01dc2b9）
  const { setDirty } = usePanelDirty();
  // 保存重入守卫（code-review item 53b14fb31196，比照 ApprovalModePanel
  // 589c1c98c5a4）：onSave 是异步，提交期间按钮可继续点击会发出重叠保存请求
  // （并发写同一配置文件，结果取决于响应到达顺序）——saving 期间置
  // loading/disabled 并在入口短路。
  const [saving, setSaving] = useState(false);
  // 规模预检开关（agents.scale_precheck.enabled）：关闭时隐藏两阈值输入
  const scalePrecheckOn = Form.useWatch('scale_precheck_enabled', form);

  const initialValues = buildAgentsFormValues(config.agents);

  // 回填门控（code-review item cbec8303669f，比照 MiscSettingsPanel 0a2bd3f20fcd /
  // AgentModelPanel 9f98edec21fa）：无条件 setFieldsValue 会在保存往返或「同步用户级
  // 设置」刷新 config 时，用外部值覆盖用户在保存请求在飞期间继续输入、尚未保存的
  // 内容。改为序列化比较，只在内容真变化时回填。
  const lastBackfillRef = useRef('');
  useEffect(() => {
    const next = buildAgentsFormValues(config.agents);
    const key = JSON.stringify(next);
    if (key === lastBackfillRef.current) return;
    lastBackfillRef.current = key;
    form.setFieldsValue(next);
  }, [config.agents, form]);

  const handleSave = async () => {
    if (saving) {
      return;
    }
    setSaving(true);
    try {
      const values = await form.validateFields();
      // 分离「表单校验」与「保存持久化」（code-review item def003cd8cff，比照
      // ApprovalModePanel 568b0ff8cce2 口径）：校验失败 antd 已在表单内渲染提示，
      // 静默返回；onSave 持久化失败（网络/500）拆独立 try/catch 显式反馈，避免
      // 用户误以为配置已保存。
      try {
        await onSave({
          agents: {
            token_budget_millions: values.token_budget_millions,
            daily_run_limit: values.daily_run_limit,
            impl_run_budget: values.impl_run_budget,
            impl_run_budget_max: values.impl_run_budget_max,
            verify_redo_budget: values.verify_redo_budget,
            max_same_cause_redispatches: values.max_same_cause_redispatches,
            scale_precheck: {
              enabled: values.scale_precheck_enabled,
              higher_threshold: values.scale_precheck_higher,
              full_threshold: values.scale_precheck_full,
            },
          },
        });
      } catch (error) {
        // 保存持久化失败（网络/500）：给用户显式反馈而非静默
        message.error(`保存失败：${error instanceof Error ? error.message : String(error)}`);
      }
    } catch {
      // 校验失败：antd 已在表单内渲染提示，不落 console
    } finally {
      setSaving(false);
    }
  };

  return (
    <div>
      <h3>预算</h3>
      <Text type="secondary">Token 预算、每日 Agent 运行限额与实现尝试预算等成本控制项。</Text>
      {/* 单一 Form 承载两张卡片：同一保存按钮提交两节配置 */}
      <Form form={form} initialValues={initialValues} layout="vertical" onValuesChange={() => setDirty(true)}>
      <Card style={{ marginTop: 12 }}>
          <Form.Item
            name="token_budget_millions"
            label={
              <>
                Token 预算<span className="label-note">（agents.token_budget_millions，百万，0=关闭）</span>
              </>
            }
            rules={[{ required: true, message: '请输入 Token 预算' }]}
          >
            <InputNumber min={0} max={1000} step={1} style={{ width: '100%' }} addonAfter="百万" />
          </Form.Item>
          <Text type="secondary">
            默认 50（百万 input token）。保存后约 30 秒内热加载生效；设为 0 表示关闭预算检查。单 SPEC 累计 input token 达到 80% 与 100% 均发警告级告警（100% 档标题为「预算 100% 警告」），不自动冻结，由人工决定是否处置。
          </Text>

          <Form.Item
            name="daily_run_limit"
            label={
              <>
                每日 Agent 运行限额<span className="label-note">（agents.daily_run_limit，0 = 不限）</span>
              </>
            }
            rules={[{ required: true, message: '请输入每日运行限额' }]}
            style={{ marginTop: 24 }}
          >
            <InputNumber min={0} step={1} style={{ width: '100%' }} addonAfter="次" />
          </Form.Item>
          <Text type="secondary">
            默认 50。单个 UTC 自然日内所有 Agent 类型成功运行的累计上限（实现/验证/管理共用一个池），达到后当日停止派发，UTC 次日 0 点自动归零。设为 0 表示不限制。
          </Text>

          <Form.Item
            name="impl_run_budget"
            label={
              <>
                实现尝试预算<span className="label-note">（agents.impl_run_budget）</span>
              </>
            }
            dependencies={['impl_run_budget_max']}
            rules={[
              { required: true, message: '请输入实现尝试预算' },
              ({ getFieldValue }) => ({
                validator(_, value) {
                  const budgetMax = getFieldValue('impl_run_budget_max');
                  if (value == null || budgetMax == null || value <= budgetMax) {
                    return Promise.resolve();
                  }
                  return Promise.reject(new Error('实现尝试预算须不大于实现尝试预算上限'));
                },
              }),
            ]}
            style={{ marginTop: 24 }}
          >
            <InputNumber min={1} max={1000} step={1} style={{ width: '100%' }} addonAfter="次" />
          </Form.Item>
          <Text type="secondary">
            默认 6。每 SPEC 跨修复周期的实现 run 启动次数上限（含首次实现与每轮修复重派）。达到上限即冻结该 SPEC 并交人工裁决，需人工调大预算或推进状态。合法范围 1 至「实现尝试预算上限」（下方可配，缺省 100，硬天花板 1000），不可超过上限。
          </Text>

          <Form.Item
            name="impl_run_budget_max"
            label={
              <>
                实现尝试预算上限<span className="label-note">（agents.impl_run_budget_max，1-1000）</span>
              </>
            }
            rules={[{ required: true, message: '请输入实现尝试预算上限' }]}
            style={{ marginTop: 24 }}
          >
            <InputNumber min={1} max={1000} step={1} style={{ width: '100%' }} addonAfter="次" />
          </Form.Item>
          <Text type="secondary">
            默认 100。per-spec 预算覆盖值与上面的全局实现尝试预算均按此上限夹紧；上限键自身硬天花板 1000。调大它可让长链条 SPEC 在机制摩擦后仍有修复轮次余额。
          </Text>

          <Form.Item
            name="verify_redo_budget"
            label={
              <>
                重启重验预算<span className="label-note">（agents.verify_redo_budget，1-10）</span>
              </>
            }
            rules={[{ required: true, message: '请输入重启重验预算' }]}
            style={{ marginTop: 24 }}
          >
            <InputNumber min={1} max={10} step={1} style={{ width: '100%' }} addonAfter="次" />
          </Form.Item>
          <Text type="secondary">
            默认 3。daemon 重启恢复路径（testing → implemented 重派 verify）的累计重验次数上限。达上限即冻结该 SPEC 并交人工裁决（人工解冻后计数清零），防止「毒 SPEC 借反复重启无限重验」烧 token。合法范围 1-10。
          </Text>

          <Form.Item
            name="max_same_cause_redispatches"
            label={
              <>
                同因重派熔断阈值<span className="label-note">（agents.max_same_cause_redispatches，1-100）</span>
              </>
            }
            rules={[{ required: true, message: '请输入同因重派熔断阈值' }]}
            style={{ marginTop: 24 }}
          >
            <InputNumber min={1} max={100} step={1} style={{ width: '100%' }} addonAfter="次" />
          </Form.Item>
          <Text type="secondary">
            默认 3。同一 SPEC 连续以<b>同一归因</b>（归一化指纹：剔除 run_id / 时间戳 / worktree 路径后的失败文案）判失败重派达该阈值 → 冻结转人工处置并发人工升级告警，不再自动重派（替代「清零重试计数后照样重派」的空转）。每轮原因都在变化时计数不累积，不会误熔断真实需要多轮修复的 SPEC。
          </Text>
      </Card>

      {/* 规模预检：标题与注释置于卡片外，与上方「预算」节同构 */}
      <h3 style={{ marginTop: 32 }}>规模预检</h3>
      <Text type="secondary">
        默认开启。fast-track SPEC 派发前先按下方口径估算规模分，据分值决定是否提高超时续期预算或改走完整模式。
        关闭后本预检完全不执行：既不提高 extension 预算，也不把 fast-track 自动降级为完整模式。
      </Text>
      <Card style={{ marginTop: 12 }}>
          <div className="switch-inline-row">
            <Form.Item name="scale_precheck_enabled" valuePropName="checked" noStyle>
              <Switch data-testid="scale-precheck-switch" />
            </Form.Item>
            <span className="switch-inline-label">
              启用规模预检<span className="label-note">（agents.scale_precheck.enabled）</span>
            </span>
          </div>

          <Text type="secondary" style={{ display: 'block', marginTop: 16 }}>
            规模分算法：<b>未勾选任务数 × 1 + 交付物文件数 × 2</b>。任务数取自 SPEC 的 tasks.md 中未勾选（
            <code>- [ ]</code>）的条目；交付物文件数取自 tasks.md「## Deliverables」声明段中 kind 为
            modify / new / delete 的条目（kind 为 reference 的引用项不计）。派发时点任务尚未开工，故此时未勾选数等于任务总数。
          </Text>

          {scalePrecheckOn ? (
            <>
              <Form.Item
                name="scale_precheck_higher"
                label={
                  <>
                    higher 档阈值<span className="label-note">（agents.scale_precheck.higher_threshold）</span>
                  </>
                }
                rules={[{ required: true, message: '请输入 higher 档阈值' }]}
                style={{ marginTop: 24 }}
              >
                <InputNumber min={1} max={10000} step={1} style={{ width: '100%' }} addonAfter="分" />
              </Form.Item>
              <Text type="secondary">
                默认 30。分值<b>大于</b>此值（严格大于，等于不升档）时进入 higher 档：SPEC 仍走 fast-track 单 run，
                但超时监督的单 run 续期次数上限增加 2 次（缺省 2 → 4），使大任务面 SPEC 获得更充足的超时预算。
                例如默认值下 30 分仍属 normal 档，31 分才进入 higher 档。
              </Text>

              <Form.Item
                name="scale_precheck_full"
                label={
                  <>
                    full 档阈值<span className="label-note">（agents.scale_precheck.full_threshold）</span>
                  </>
                }
                dependencies={['scale_precheck_higher']}
                rules={[
                  { required: true, message: '请输入 full 档阈值' },
                  ({ getFieldValue }) => ({
                    validator(_, value) {
                      const higher = getFieldValue('scale_precheck_higher');
                      if (value == null || higher == null || value > higher) {
                        return Promise.resolve();
                      }
                      return Promise.reject(new Error('full 档阈值须大于 higher 档阈值'));
                    },
                  }),
                ]}
                style={{ marginTop: 24 }}
              >
                <InputNumber min={1} max={10000} step={1} style={{ width: '100%' }} addonAfter="分" />
              </Form.Item>
              <Text type="secondary">
                默认 45。分值<b>大于</b>此值（严格大于）时判定为 full 档：该 SPEC 的 .spec.yaml 中 mode 会被自动改写为
                full 并改走完整模式（implementer + 独立验证全链），不再按 fast-track 单 run 派发。此改写是持久的，
                后续派发均按完整模式进行。必须大于 higher 档阈值。
              </Text>
            </>
          ) : null}
      </Card>
      </Form>

      <div style={project ? SETTINGS_ACTIONS_ROW_STYLE : { textAlign: 'right', marginTop: 24 }}>
        {project && onConfigSynced && (
          <SyncFromUserButton project={project} page="token" onSynced={onConfigSynced} />
        )}
        <Button type="primary" onClick={handleSave} loading={saving} disabled={saving}>
          保存
        </Button>
      </div>
    </div>
  );
}
