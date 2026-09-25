import { Button, Card, Form, InputNumber, Switch, Typography, message } from 'antd';
import { useEffect, useRef } from 'react';
import type { ConfigData } from '@/services/dashboard';
import SyncFromUserButton from './SyncFromUserButton';
import { SETTINGS_ACTIONS_ROW_STYLE } from '../styles';

const { Text } = Typography;

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

  // add-planner-efficiency（planner-generation-throttle）：planner 生成节流。
  // 开关 = verify.planner_max_concurrent > 0；值为 0/缺省 = 不节流（默认关）。
  const throttleEnabled = (config.verify?.planner_max_concurrent ?? 0) > 0;
  const throttleValue = throttleEnabled
    ? (config.verify?.planner_max_concurrent ?? 1)
    : 1;

  const initialValues = {
    max_concurrent: config.agents.max_concurrent ?? 2,
    max_turns: config.agents.max_turns ?? 400,
    run_timeout_seconds: config.agents.run_timeout_seconds ?? 9000,
    planner_throttle: throttleEnabled,
    planner_max_concurrent: throttleValue,
  };

  // 回填门控（code-review item b97e73ffcda4，比照 MiscSettingsPanel 0a2bd3f20fcd /
  // AgentModelPanel 9f98edec21fa）：无条件 setFieldsValue 会在保存往返、同步按钮
  // onConfigSynced 触发父组件 setConfig 时，用外部 config 覆盖本面板用户正在编辑、
  // 尚未保存的输入。改为序列化比较，只在内容真变化时回填。
  const lastBackfillRef = useRef('');
  useEffect(() => {
    const next = {
      max_concurrent: config.agents.max_concurrent ?? 2,
      max_turns: config.agents.max_turns ?? 400,
      run_timeout_seconds: config.agents.run_timeout_seconds ?? 9000,
      planner_throttle: throttleEnabled,
      planner_max_concurrent: throttleValue,
    };
    const key = JSON.stringify(next);
    if (key === lastBackfillRef.current) return;
    lastBackfillRef.current = key;
    form.setFieldsValue(next);
  }, [config.agents, config.verify, form, throttleEnabled, throttleValue]);

  const handleSave = async () => {
    // 分离「表单校验」与「保存持久化」（code-review item 3243afb1df4e，比照
    // MiscSettingsPanel 9125d4a7f7b4 / AgentModelPanel 3086b7e96c4f）：旧实现
    // 两者混在同一 try/catch 且静默吞掉，onSave 拒绝（网络失败/500）时用户
    // 点击「保存」后无任何反馈，与同族已修复面板口径漂移。
    let values;
    try {
      values = await form.validateFields();
    } catch {
      // 校验失败：antd 已在表单内渲染行内错误提示，无需额外日志（避免触发
      // 验证场景的 no_console_error 断言，比照 MiscSettingsPanel 口径）。
      return;
    }
    try {
      await onSave({
        agents: {
          max_concurrent: values.max_concurrent,
          max_turns: values.max_turns,
          run_timeout_seconds: values.run_timeout_seconds,
        },
        verify: {
          ...(config.verify || {}),
          planner_max_concurrent: values.planner_throttle
            ? values.planner_max_concurrent
            : 0,
        },
      });
    } catch (error) {
      // 保存持久化失败：给用户显式反馈而非静默
      message.error(`保存失败：${error instanceof Error ? error.message : String(error)}`);
    }
  };

  const plannerThrottleOn = Form.useWatch('planner_throttle', form);

  return (
    <div>
      <h3>并行</h3>
      <Text type="secondary">
        同时运行的 Agent 进程数上限。调度采用严格优先级并行：高优先级任务先执行；同一优先级内可并行至该上限；不同优先级不并行（低优先级等高优先级全部完成后才启动）。
      </Text>
      <Card style={{ marginTop: 12 }}>
        <Form form={form} initialValues={initialValues} layout="vertical">
          <Form.Item
            name="max_concurrent"
            label={
              <>
                并行<span className="label-note">（agents.max_concurrent）</span>
              </>
            }
            rules={[{ required: true, message: '请输入并行度' }]}
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
            rules={[{ required: true, message: '请输入轮次上限' }]}
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
            rules={[{ required: true, message: '请输入时长上限' }]}
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
            默认关闭（不节流）。开启后限制全框架同时在出题的 Planner 数量（上限为 1-10，默认 1）多个 Planner 
            并发同时访问 LLM 网关时，降低网关排队/长尾延迟出现的概率，但可能造成验证吞吐下降。
          </Text>
          {plannerThrottleOn ? (
            <Form.Item
              name="planner_max_concurrent"
              label={
                <>
                  同时出题 Planner 上限<span className="label-note">（verify.planner_max_concurrent）</span>
                </>
              }
              rules={[{ required: true, message: '请输入上限' }]}
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
        <Button type="primary" onClick={handleSave} data-testid="settings-save">
          保存
        </Button>
      </div>
    </div>
  );
}