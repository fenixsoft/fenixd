import { Button, Card, Form, InputNumber, Switch, Typography } from 'antd';
import type { ConfigData } from '@/services/dashboard';
import SyncFromUserButton from './SyncFromUserButton';
import { SETTINGS_ACTIONS_ROW_STYLE } from '../styles';
import { usePanelDirty } from '../panelDirty';
import { useGatedFormPanel } from '../useGatedFormPanel';

const { Text } = Typography;

// 表单值的单一构建来源（code-review item 3f4e251a395c）：initialValues 与
// 回填门控此前是两份逐字段重复的字面量，任一处增删字段或改默认值而其余
// 未同步，会导致回填 key 误判（首次渲染丢初值或永不回填/频繁回填）。
// 收敛为单个纯函数供两处共用。
// add-planner-efficiency（planner-generation-throttle）：planner 生成节流。
// 开关 = verify.planner_max_concurrent > 0；值为 0/缺省 = 不节流（默认关）。
const buildFormValues = (cfg: ConfigData) => {
  const throttleEnabled = (cfg.verify?.planner_max_concurrent ?? 0) > 0;
  const throttleValue = throttleEnabled
    ? (cfg.verify?.planner_max_concurrent ?? 1)
    : 1;
  return {
    // agents?. 防护（code-review item 60ae9a174a6c）：与上方 verify?. 及
    // MiscSettingsPanel 的 archive?. 同族口径——旧版本配置或接口降级响应
    // 可能缺 agents 段，直接访问会让面板首帧渲染抛 TypeError 白屏。
    max_concurrent: cfg.agents?.max_concurrent ?? 2,
    max_turns: cfg.agents?.max_turns ?? 400,
    run_timeout_seconds: cfg.agents?.run_timeout_seconds ?? 9000,
    planner_throttle: throttleEnabled,
    planner_max_concurrent: throttleValue,
  };
};

interface ParallelSettingsPanelProps {
  config: ConfigData;
  onSave: (values: Partial<ConfigData>) => Promise<void>;
  /** 当前项目名；项目级作用域才显示「同步用户级设置」按钮 */
  project?: string;
  /** 同步成功后回填配置（父组件 setConfig 驱动表单刷新） */
  onConfigSynced?: (config: ConfigData) => void;
}

export default function ParallelSettingsPanel({ config, onSave, project, onConfigSynced }: ParallelSettingsPanelProps) {
  const [form] = Form.useForm();
  // 用户编辑置脏：切页签/作用域前由 index 经 anyPanelDirty 弹丢弃确认
  // （code-review item 8a3eb01dc2b9）
  const { setDirty } = usePanelDirty();
  // 表单脚手架统一走 useGatedFormPanel（code-review item 5c5a259b8443）：
  // saving 重入守卫（原 item 25f88bae6330）、序列化比较回填门控（原 item
  // b97e73ffcda4）、校验/持久化分离的 handleSave（原 item 3243afb1df4e）由
  // hook 承载；本面板保留字段映射（buildFormValues）与保存载荷组装。
  const { saving, initialValues, handleSave } = useGatedFormPanel({
    form,
    buildValues: () => buildFormValues(config),
    backfillDeps: [config.agents, config.verify],
    onSave,
    buildPayload: (values): Partial<ConfigData> => ({
      agents: {
        max_concurrent: values.max_concurrent,
        max_turns: values.max_turns,
        run_timeout_seconds: values.run_timeout_seconds,
      },
      // 只提交本面板管理的键（code-review item 5d82bd4c6d76）：不展开
      // config.verify——项目作用域下它是 user+project 合并视图，展开会把
      // 用户级继承来的键冻结成项目级覆盖。后端 verify 分支为逐键合并，
      // 无需基底。
      verify: {
        planner_max_concurrent: values.planner_throttle
          ? values.planner_max_concurrent
          : 0,
      },
    }),
  });

  const plannerThrottleOn = Form.useWatch('planner_throttle', form);

  return (
    <div>
      <h3>并行</h3>
      <Text type="secondary">
        同时运行的 Agent 进程数上限。调度采用严格优先级并行：高优先级任务先执行；同一优先级内可并行至该上限；不同优先级不并行（低优先级等高优先级全部完成后才启动）。
      </Text>
      <Card style={{ marginTop: 12 }}>
        <Form form={form} initialValues={initialValues} layout="vertical" onValuesChange={() => setDirty(true)}>
          <Form.Item
            name="max_concurrent"
            label={
              <>
                并行<span className="label-note">（agents.max_concurrent）</span>
              </>
            }
            rules={[
              { required: true, message: '请输入并行度' },
              // 正整数校验（code-review item c19d483a2943，比照 MiscSettingsPanel
              // auto_threshold / StaleCodeSelfhealPanel idle_confirm_seconds 同族
              // 口径）：不能用 InputNumber 的 min/max 代替——blur 时会把越界值
              // 静默钳回边界，用户永远看不到非法输入被拦截的表单错误提示；
              // InputNumber 保留 min/max 仅作输入辅助。
              { type: 'integer', min: 1, message: '并行度必须为不小于 1 的正整数' },
            ]}
          >
            <InputNumber min={1} step={1} style={{ width: '100%' }} addonAfter="个" />
          </Form.Item>
          <Text type="secondary">默认 2。保存后约 30 秒内热加载生效。</Text>

          <Form.Item
            name="max_turns"
            label={
              <>
                单次 Agent 运行轮次上限<span className="label-note">（agents.max_turns）</span>
              </>
            }
            rules={[
              { required: true, message: '请输入轮次上限' },
              // 同上口径（code-review item c19d483a2943）：越界拦截走 rules，min 仅作输入辅助
              { type: 'integer', min: 1, message: '轮次上限必须为不小于 1 的正整数' },
            ]}
            style={{ marginTop: 24 }}
          >
            <InputNumber min={1} step={1} style={{ width: '100%' }} addonAfter="轮" />
          </Form.Item>
          <Text type="secondary">默认 400（上限而非目标值）。单个 Agent 运行轮次达到此值即被终止并触发重试。</Text>

          <Form.Item
            name="run_timeout_seconds"
            label={
              <>
                单次 Agent 运行时长上限<span className="label-note">（agents.run_timeout_seconds）</span>
              </>
            }
            rules={[
              { required: true, message: '请输入时长上限' },
              // 同上口径（code-review item c19d483a2943）：越界拦截走 rules，min 仅作输入辅助
              { type: 'integer', min: 60, message: '时长上限须为不小于 60 的整数秒' },
            ]}
            style={{ marginTop: 24 }}
          >
            <InputNumber min={60} step={60} style={{ width: '100%' }} addonAfter="秒" />
          </Form.Item>
          <Text type="secondary">默认 9000（2.5 小时）。单个 Agent 运行超时即终止并触发重试。以上两个参数应随你项目 SPEC 的规模大小而定。</Text>

          {/* add-planner-efficiency（planner-generation-throttle 2.3）：planner 生成节流。
              开关（默认关）+ 上限输入（1-10）+ 三点注解（限什么/作用/代价）。 */}
          <div className="switch-inline-row" style={{ marginTop: 24 }}>
            <Form.Item name="planner_throttle" valuePropName="checked" noStyle>
              <Switch data-testid="planner-throttle-switch" />
            </Form.Item>
            <span className="switch-inline-label">
              Planner 生成节流<span className="label-note">（verify.planner_max_concurrent）</span>
            </span>
          </div>
          <Text type="secondary">
            默认关闭（不节流）。开启后限制全框架同时在出题的 Planner 数量（上限为 1-10，默认 1）。多个
            Planner 并发访问 LLM 网关时，降低网关排队/长尾延迟出现的概率，但可能造成验证吞吐下降。
          </Text>
          {plannerThrottleOn ? (
            <Form.Item
              name="planner_max_concurrent"
              label={
                <>
                  同时出题 Planner 上限<span className="label-note">（verify.planner_max_concurrent）</span>
                </>
              }
              rules={[
                { required: true, message: '请输入上限' },
                // 同上口径（code-review item c19d483a2943）：越界拦截走 rules，min/max 仅作输入辅助
                { type: 'integer', min: 1, max: 10, message: '须为 1-10 的正整数' },
              ]}
              style={{ marginTop: 24 }}
            >
              <InputNumber min={1} max={10} step={1} style={{ width: '100%' }} addonAfter="个" />
            </Form.Item>
          ) : null}
        </Form>
      </Card>
      <div style={project ? SETTINGS_ACTIONS_ROW_STYLE : { textAlign: 'right', marginTop: 24 }}>
        {project && onConfigSynced && (
          <SyncFromUserButton project={project} page="parallel" onSynced={onConfigSynced} />
        )}
        <Button type="primary" onClick={handleSave} loading={saving} disabled={saving} data-testid="parallel-save">
          保存
        </Button>
      </div>
    </div>
  );
}