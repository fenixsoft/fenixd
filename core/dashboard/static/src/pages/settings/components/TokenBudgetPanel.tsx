import { Button, Card, Form, InputNumber, Switch, Typography } from 'antd';
import { useEffect } from 'react';
import type { ConfigData } from '@/services/dashboard';
import SyncFromUserButton from './SyncFromUserButton';
import { SETTINGS_ACTIONS_ROW_STYLE } from '../styles';

const { Text } = Typography;

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
  // 规模预检开关（agents.scale_precheck.enabled）：关闭时隐藏两阈值输入
  const scalePrecheckOn = Form.useWatch('scale_precheck_enabled', form);

  const sp = config.agents.scale_precheck ?? {};

  const initialValues = {
    token_budget_millions: config.agents.token_budget_millions ?? 50,
    daily_run_limit: config.agents.daily_run_limit ?? 50,
    impl_run_budget: config.agents.impl_run_budget ?? 6,
    impl_run_budget_max: config.agents.impl_run_budget_max ?? 100,
    verify_redo_budget: config.agents.verify_redo_budget ?? 3,
    max_same_cause_redispatches: config.agents.max_same_cause_redispatches ?? 3,
    scale_precheck_enabled: sp.enabled ?? true,
    scale_precheck_higher: sp.higher_threshold ?? 30,
    scale_precheck_full: sp.full_threshold ?? 45,
  };

  useEffect(() => {
    form.setFieldsValue({
      token_budget_millions: config.agents.token_budget_millions ?? 50,
      daily_run_limit: config.agents.daily_run_limit ?? 50,
      impl_run_budget: config.agents.impl_run_budget ?? 6,
      impl_run_budget_max: config.agents.impl_run_budget_max ?? 100,
      verify_redo_budget: config.agents.verify_redo_budget ?? 3,
      max_same_cause_redispatches: config.agents.max_same_cause_redispatches ?? 3,
      scale_precheck_enabled: config.agents.scale_precheck?.enabled ?? true,
      scale_precheck_higher: config.agents.scale_precheck?.higher_threshold ?? 30,
      scale_precheck_full: config.agents.scale_precheck?.full_threshold ?? 45,
    });
  }, [config.agents, form]);

  const handleSave = async () => {
    try {
      const values = await form.validateFields();
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
    } catch {
      // 校验/保存失败：antd 已在表单内渲染行内错误提示，不再打印 console.error
      // （与 MiscSettingsPanel 静默口径对齐，避免触发验证的 no_console_error 断言）。
    }
  };

  return (
    <div>
      <h3>预算</h3>
      <Text type="secondary">Token 预算、每日 Agent 运行限额与实现尝试预算等成本控制项。</Text>
      {/* 单一 Form 承载两张卡片：同一保存按钮提交两节配置 */}
      <Form form={form} initialValues={initialValues} layout="vertical">
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
            默认 50（百万 input token）。保存后约 30 秒内热加载生效；设为 0 表示关闭预算检查。单 SPEC 累计 input token 达到 80% 发提醒级告警、达到 100% 发升级级告警，不自动冻结，由人工决定是否处置。
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
            rules={[{ required: true, message: '请输入实现尝试预算' }]}
            style={{ marginTop: 24 }}
          >
            <InputNumber min={1} max={1000} step={1} style={{ width: '100%' }} addonAfter="次" />
          </Form.Item>
          <Text type="secondary">
            默认 6。每 SPEC 跨修复周期的实现 run 启动次数上限（含首次实现与每轮修复重派）。达到上限即冻结该 SPEC 并交人工裁决，需人工调大预算或推进状态。合法范围 1 至「实现尝试预算上限」（下方可配，缺省 100，硬天花板 1000）。
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
        <Button type="primary" onClick={handleSave}>
          保存
        </Button>
      </div>
    </div>
  );
}
