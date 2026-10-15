import { App, Button, Card, Form, Input, InputNumber, Select, Space, Switch, Typography } from 'antd';
import { restartProjectDaemon } from '@/services/dashboard';
import SyncFromUserButton from './SyncFromUserButton';
import { usePanelDirty } from '../panelDirty';
import { useGatedFormPanel } from '../useGatedFormPanel';
import type { ConfigData } from '@/services/dashboard';

const { Text } = Typography;

interface SystemPanelProps {
  config: ConfigData;
  onSave: (values: Partial<ConfigData>) => Promise<boolean>;
  /** 当前作用域项目名；undefined = 用户级作用域（重启/同步按钮隐藏） */
  project?: string;
  /** 同步成功后回填配置（父组件 setConfig 驱动表单刷新） */
  onConfigSynced?: (config: ConfigData) => void;
}

// 控件形态判别（code-review item fbb06aa6f869）：判别信息内聚到注解项 type 字段，
// renderAdminField 按其分派而非 key 字符串等值链——新增条目必须声明形态，
// 漏加分派分支时 helper 末尾的穷举守卫编译报错，不再静默落 InputNumber 兜底
type AdminFieldControl = 'switch' | 'input' | 'select' | 'number';

const ADMIN_ANNOTATIONS: {
  key: string;
  label: string;
  note: string;
  /** 控件形态（AdminFieldControl），新增条目必填 */
  type: AdminFieldControl;
  /** 输入单位（addonAfter 附加框）；开关 / 下拉项无单位 */
  unit?: string;
  rule?: object[];
}[] = [
  {
    key: 'enabled',
    type: 'switch',
    label: '自动自愈',
    note: '自动自愈总开关：关闭后困境（卡死/反复失败/预算耗尽）不再自动唤起 Administrator 处置，界面手动运维调用不受影响。',
  },
  {
    key: 'interval_minutes',
    type: 'number',
    label: '巡检周期',
    unit: '分钟',
    note: '自愈监视器巡检周期：每这么久扫描一次困境信号；也参与卡顿判定的宽限期计算（间隔×2）。',
    rule: [{
      validator: (_: unknown, v: number | undefined | null) =>
        Number.isInteger(v) && (v as number) > 0
          ? Promise.resolve()
          : Promise.reject(new Error('须为正整数')),
    }],
  },
  {
    key: 'escalation_cooldown_minutes',
    type: 'number',
    label: '唤起冷却',
    unit: '分钟',
    note: '同一 SPEC 同类困境信号的唤起冷却：冷却期内不重复唤起，避免同一问题反复烧钱。',
    rule: [{
      validator: (_: unknown, v: number | undefined | null) =>
        Number.isInteger(v) && (v as number) >= 0
          ? Promise.resolve()
          : Promise.reject(new Error('须为非负整数')),
    }],
  },
  {
    key: 'stuck_silence_minutes',
    type: 'number',
    label: 'stuck 处置后静默期',
    unit: '分钟',
    note: 'stuck 信号成功处置（resolved / partially-resolved）后的静默窗口：窗口内同 SPEC stuck 信号不复发，避免处置成功后短期反复触发。0=不静默。',
    rule: [{
      validator: (_: unknown, v: number | undefined | null) =>
        Number.isInteger(v) && (v as number) >= 0
          ? Promise.resolve()
          : Promise.reject(new Error('须为非负整数')),
    }],
  },
  {
    key: 'merge_breaker_threshold',
    type: 'number',
    label: 'merge 熔断阈值',
    unit: '次',
    note: 'merge 熔断阈值：同一 SPEC merge-back 连续失败达该次数仍滞留时触发熔断信号（未配置时沿用 agents 同名键，再缺省 2）。注意：本页签任意一次保存都会把回显解析值落为显式 admin.merge_breaker_threshold，此后 agents 同名键的调整不再传导到本项。',
    rule: [{
      validator: (_: unknown, v: number | undefined | null) =>
        Number.isInteger(v) && (v as number) > 0
          ? Promise.resolve()
          : Promise.reject(new Error('须为正整数')),
    }],
  },
  {
    key: 'shutdown_drain_seconds',
    type: 'number',
    label: '重启排水窗口',
    unit: '秒',
    note: '计划性重启排水窗口（秒）：restart_request 后等在跑任务自然收工的上限，0=立即快速停机（在飞任务标记中断、重启后续做）；supervisor 强杀等待=本值+120s。',
    rule: [{
      validator: (_: unknown, v: number | undefined | null) =>
        Number.isInteger(v) && (v as number) >= 0
          ? Promise.resolve()
          : Promise.reject(new Error('须为非负整数')),
    }],
  },
  {
    key: 'bug_repair_mode',
    type: 'select',
    label: '验证失败修复方式',
    note: '验证裁决 bug-found 后的修复方式：原地打回（inplace，缺省）对父 SPEC 直接注入「验证修复」任务段重修；派生 fix SPEC（derive）创建/复用 fix-* 子 SPEC 并自动闭环重验。',
  },
  {
    key: 'narrative_enabled',
    type: 'switch',
    label: '告警叙事',
    note: '转人工裁决告警的三段式叙事开关：开启后告警落盘时同步生成「发生了什么/为什么需要你决策/决策选项」人类可读说明（缺省开启）。关闭后零 LLM 调用、零额外延迟；生成失败自动兜底为既有机械文案，告警照常落盘。',
  },
  {
    key: 'narrative_timeout_seconds',
    type: 'number',
    label: '叙事超时',
    unit: '秒',
    note: '告警叙事同步调用的硬超时（秒）：超时上限内告警保证落盘（超时按生成失败兜底）。转人工是低频事件，缺省 60 秒。',
    rule: [{
      validator: (_: unknown, v: number | undefined | null) =>
        Number.isInteger(v) && (v as number) > 0
          ? Promise.resolve()
          : Promise.reject(new Error('须为正整数')),
    }],
  },
  {
    key: 'narrative_model',
    type: 'input',
    label: '叙事模型',
    note: '告警叙事使用的模型名：留空按回退链复用 admin.agent_model，仍为空时复用框架默认网关模型。',
  },
  {
    key: 'self_heal_quiet_minutes',
    type: 'number',
    label: '告警自愈安静窗口',
    unit: '分钟',
    note: '基础设施瞬态族告警（daemon_errors 指纹风暴 / run_infra_failure 熔断 / evo 分析失败 / 处置收敛升级）签名安静多久后自动标「已自愈」转已处理（缺省 1440，盖过跨日同刻复发节律）。',
    rule: [{
      validator: (_: unknown, v: number | undefined | null) =>
        Number.isInteger(v) && (v as number) > 0
          ? Promise.resolve()
          : Promise.reject(new Error('须为正整数')),
    }],
  },
];

// 系统分组单字段控件形态（code-review item 4b4856254978）：旧实现以嵌套三元链选择
// 控件，违反本项目前端「禁止嵌套三元」规则，抽模块级 helper 以 if/else 表达四种形态。
// fbb06aa6f869：分派依据从 key 字符串等值改为注解项自带的 type 判别字段
// （AdminFieldControl：switch/input/select/number），新增字段漏加分派分支时
// 末尾穷举守卫编译报错，不再静默落数值框兜底。仅依赖注解字段本身，
// 无组件闭包依赖，故放模块级。
function renderAdminField({
  key,
  label,
  type,
  unit,
  rule,
}: {
  key: string;
  label: string;
  type: AdminFieldControl;
  unit?: string;
  rule?: object[];
}) {
  if (type === 'switch') {
    return (
      <div className="switch-inline-row" data-testid={`system-field-${key}`}>
        <Form.Item name={key} valuePropName="checked" noStyle>
          <Switch data-testid={`system-control-${key}`} />
        </Form.Item>
        <span className="switch-inline-label">
          {label}
          <span className="label-note">（admin.{key}）</span>
        </span>
      </div>
    );
  }
  if (type === 'input') {
    return (
      <Form.Item
        name={key}
        label={
          <>
            {label}
            <span className="label-note">（admin.{key}）</span>
          </>
        }
        data-testid={`system-field-${key}`}
      >
        {/* 模型名是自由文本（官方 Claude / 网关模型名）：文本框而非
            InputNumber；空串=清除覆盖、按回退链取模型（与后端回显
            语义一致） */}
        <Input
          data-testid={`system-control-${key}`}
          style={{ width: '100%' }}
          placeholder="留空 = 复用 admin.agent_model → 框架默认"
        />
      </Form.Item>
    );
  }
  if (type === 'select') {
    return (
      <Form.Item
        name={key}
        label={
          <>
            {label}
            <span className="label-note">（admin.{key}）</span>
          </>
        }
        data-testid={`system-field-${key}`}
      >
        <Select
          data-testid={`system-control-${key}`}
          style={{ width: '100%' }}
          options={[
            { value: 'inplace', label: '原地打回（inplace）' },
            { value: 'derive', label: '派生 fix SPEC（derive）' },
          ]}
        />
      </Form.Item>
    );
  }
  if (type === 'number') {
    return (
      <Form.Item
        name={key}
        label={
          <>
            {label}
            <span className="label-note">（admin.{key}）</span>
          </>
        }
        rules={rule}
        data-testid={`system-field-${key}`}
      >
        <InputNumber
          data-testid={`system-control-${key}`}
          style={{ width: '100%' }}
          step={1}
          precision={0}
          addonAfter={unit}
        />
      </Form.Item>
    );
  }
  // 穷举守卫（code-review item fbb06aa6f869）：AdminFieldControl 新增形态未在
  // 上方分派时，type 收窄结果含新字面量、赋给 never 编译报错，遗漏由静默兜底
  // 变成可查错误
  const _exhaustive: never = type;
  return _exhaustive;
}

// 瞬断组控件形态判别（code-review item 72ce7ba8c2ef）：比照 admin 组
// AdminFieldControl 的注解驱动口径，判别信息内聚到注解项 type 字段；
// 本组现只有文本/数值两形态，联合按现状收窄，不预留未用形态
type TransientFieldControl = 'input' | 'number';

// 瞬断治理（fix-provider-transient-backoff D6）：键名 = agents.transient_*，
// 与后端 ConfigLoader.get_transient_config 缺省一致（30,60,120 / 600 / 3 / 600 / 600）。
const TRANSIENT_ANNOTATIONS: {
  key: string;
  label: string;
  note: string;
  /** 控件形态（TransientFieldControl），新增条目必填 */
  type: TransientFieldControl;
  /** 输入单位（addonAfter 附加框） */
  unit?: string;
  rule?: object[];
}[] = [
  {
    key: 'transient_backoff_schedule',
    type: 'input',
    label: '原地退避序列',
    unit: '秒',
    note: '网关瞬断（model 拒绝 / 5xx / 断连）首败后同 provider 原地退避的秒序列，逗号分隔，长度=单 attempt 内原地重试上限。留空关闭原地退避。',
    rule: [{
      validator: (_: unknown, v: string | undefined | null) => {
        if (v == null || String(v).trim() === '') return Promise.resolve();
        // 先剥离空段再校验（code-review item da5d08818510）：尾逗号（"30,"）容忍，
        // 但全空段串（",,,"）字段非空却不含任何退避秒数，语义上等同关闭原地退避，
        // 与提示文案相悖，须显式报错
        const segs = String(v).split(',').map(p => p.trim()).filter(s => s !== '');
        return segs.length > 0 && segs.every(s => /^\d+$/.test(s) && Number(s) > 0)
          ? Promise.resolve()
          : Promise.reject(new Error('须为逗号分隔的正整数秒'));
      },
    }],
  },
  {
    key: 'transient_redispatch_delay_seconds',
    type: 'number',
    label: '重派等待',
    unit: '秒',
    note: '瞬断终态（[provider-transient] 标记）后排程延迟重派秒数，不写 retries exhausted。缺省 600。',
    rule: [{
      validator: (_: unknown, v: number | undefined | null) =>
        v != null && Number.isInteger(v) && (v as number) >= 0
          ? Promise.resolve()
          : Promise.reject(new Error('须为非负整数')),
    }],
  },
  {
    key: 'transient_break_threshold',
    type: 'number',
    label: '熔断阈值',
    unit: '次',
    note: '全局同错误指纹在窗口内出现次数达此值触发全局派发冻结；0=关闭熔断。缺省 3。',
    rule: [{
      validator: (_: unknown, v: number | undefined | null) =>
        v != null && Number.isInteger(v) && (v as number) >= 0
          ? Promise.resolve()
          : Promise.reject(new Error('须为非负整数')),
    }],
  },
  {
    key: 'transient_break_window_seconds',
    type: 'number',
    label: '熔断窗口',
    unit: '秒',
    note: '全局同错误指纹计数的滑动窗口秒数。缺省 600。',
    rule: [{
      validator: (_: unknown, v: number | undefined | null) =>
        v != null && Number.isInteger(v) && (v as number) >= 0
          ? Promise.resolve()
          : Promise.reject(new Error('须为非负整数')),
    }],
  },
  {
    key: 'transient_break_cooldown_seconds',
    type: 'number',
    label: '熔断冷却',
    unit: '秒',
    note: '触发全局熔断后冻结新 run 派发的时长。缺省 600。',
    rule: [{
      validator: (_: unknown, v: number | undefined | null) =>
        v != null && Number.isInteger(v) && (v as number) >= 0
          ? Promise.resolve()
          : Promise.reject(new Error('须为非负整数')),
    }],
  },
];

// 瞬断分组单字段控件形态（code-review item 72ce7ba8c2ef）：比照 renderAdminField
// 的 type 判别 + 末尾穷举守卫，替换旧实现按 key 字符串等值的二分派——新增条目
// 必须声明形态，漏加分派分支时编译报错，不再静默落数值框兜底。不直接复用
// renderAdminField：本组 label-note 段名前缀是 agents.*（区别于 admin 组），
// 文本形态的 placeholder 语义也不同，仅比照其分派机制。仅依赖注解字段本身，
// 无组件闭包依赖，放模块级。
function renderTransientField({
  key,
  label,
  type,
  unit,
  rule,
}: {
  key: string;
  label: string;
  type: TransientFieldControl;
  unit?: string;
  rule?: object[];
}) {
  if (type === 'input') {
    return (
      <Form.Item
        name={key}
        label={
          <>
            {label}
            <span className="label-note">（agents.{key}）</span>
          </>
        }
        rules={rule}
        data-testid={`system-field-${key}`}
      >
        {/* 逗号分隔序列须用文本框：InputNumber 的默认 parser 会剥离逗号，
            "30,60,120" 会被静默并成 "3060120" 恰好骗过单段校验 */}
        <Input
          data-testid={`system-control-${key}`}
          style={{ width: '100%' }}
          placeholder="30,60,120"
          addonAfter={unit}
        />
      </Form.Item>
    );
  }
  if (type === 'number') {
    return (
      <Form.Item
        name={key}
        label={
          <>
            {label}
            <span className="label-note">（agents.{key}）</span>
          </>
        }
        rules={rule}
        data-testid={`system-field-${key}`}
      >
        <InputNumber
          data-testid={`system-control-${key}`}
          style={{ width: '100%' }}
          step={1}
          precision={0}
          addonAfter={unit}
        />
      </Form.Item>
    );
  }
  // 穷举守卫（口径同 renderAdminField 的 fbb06aa6f869）：TransientFieldControl
  // 新增形态未在上方分派时，type 收窄结果含新字面量、赋给 never 编译报错
  const _exhaustive: never = type;
  return _exhaustive;
}

// 系统页签表单值类型（code-review item 776c2c624d2c）：字段名与 ADMIN_ANNOTATIONS /
// TRANSIENT_ANNOTATIONS 的 key 一一对应，数值字段经 InputNumber + 校验器保证非空，
// 文本字段恒为 string。values 显式标注本类型后字段名拼错进入编译期检查。
interface SystemFormValues {
  enabled: boolean;
  interval_minutes: number;
  escalation_cooldown_minutes: number;
  merge_breaker_threshold: number;
  shutdown_drain_seconds: number;
  bug_repair_mode: 'inplace' | 'derive';
  stuck_silence_minutes: number;
  narrative_enabled: boolean;
  narrative_timeout_seconds: number;
  narrative_model: string;
  self_heal_quiet_minutes: number;
  transient_backoff_schedule: string;
  transient_redispatch_delay_seconds: number;
  transient_break_threshold: number;
  transient_break_window_seconds: number;
  transient_break_cooldown_seconds: number;
  // add-harness-adapter-layer 6.3：agent 进程边界（agent.harness，区别于
  // agents 段）。Select 只出两合法值；存量为非法手写值时按缺省 claude 回显
  harness: 'claude' | 'dsh';
}

// admin.* + agents.transient_* 全字段表单映射单源（config 取值 ?? 缺省）：
// initialValues 与回填 effect 共用，避免两份映射漏改一处导致初值与回填值分叉
function buildSystemFormValues(config: ConfigData): SystemFormValues {
  const admin = config.admin ?? {};
  // 瞬断治理（fix-provider-transient-backoff D6）：agents.transient_* 五键
  const agentsSection = config.agents ?? {};
  // 自省字段（self_review.*）已拆至独立「自省」页签（SelfReviewPanel）
  return {
    enabled: admin.enabled ?? true,
    interval_minutes: admin.interval_minutes ?? 5,
    escalation_cooldown_minutes: admin.escalation_cooldown_minutes ?? 60,
    merge_breaker_threshold: admin.merge_breaker_threshold ?? 2,
    shutdown_drain_seconds: admin.shutdown_drain_seconds ?? 1800,
    bug_repair_mode: admin.bug_repair_mode ?? 'inplace',
    stuck_silence_minutes: admin.stuck_silence_minutes ?? 120,
    // add-adjudication-alert-narrative：告警叙事三键（缺省与后端
    // _ADMIN_DEFAULTS / config.template.yaml 同源）
    narrative_enabled: admin.narrative_enabled ?? true,
    narrative_timeout_seconds: admin.narrative_timeout_seconds ?? 60,
    narrative_model: admin.narrative_model ?? '',
    // add-alert-self-heal-marking 5.2：告警自愈安静窗口（缺省与后端
    // _ADMIN_DEFAULTS / config.template.yaml 同源 1440）
    self_heal_quiet_minutes: admin.self_heal_quiet_minutes ?? 1440,
    transient_backoff_schedule: agentsSection.transient_backoff_schedule ?? '30,60,120',
    transient_redispatch_delay_seconds: agentsSection.transient_redispatch_delay_seconds ?? 600,
    transient_break_threshold: agentsSection.transient_break_threshold ?? 3,
    transient_break_window_seconds: agentsSection.transient_break_window_seconds ?? 600,
    transient_break_cooldown_seconds: agentsSection.transient_break_cooldown_seconds ?? 600,
    // add-harness-adapter-layer 6.3：非法手写值不进 Select（后端 read_effective_config
    // 已归一，此处再守一层，防 read_config 原文视图透传非法值撑爆受控选项）
    harness: config.agent?.harness === 'dsh' ? 'dsh' : 'claude',
  };
}

export default function SystemPanel({ config, onSave, project, onConfigSynced }: SystemPanelProps) {
  const [form] = Form.useForm<SystemFormValues>();
  // 反馈提示经 App.useApp() 取上下文实例（code-review item afa35698f8fd）：
  // 静态 message 不经过 App/ConfigProvider 上下文，与其余设置面板口径统一；
  // 重启确认的 modal 同取上下文实例（code-review item 6836d264fde4）：静态
  // Modal.confirm 与静态 message 同一局限（不消费 App/ConfigProvider 上下文），
  // handleRestart 的 onOk 闭包在组件渲染作用域内，可直接捕获
  const { message, modal } = App.useApp();
  // 用户编辑置脏：切页签/作用域前由 index 经 anyPanelDirty 弹丢弃确认
  // （code-review item 8a3eb01dc2b9）
  const { setDirty } = usePanelDirty();
  // 表单脚手架统一走 useGatedFormPanel（code-review item 5c5a259b8443）：
  // savingRef 重入守卫（原口径见 item 8ccf20511320）、序列化比较回填门控
  // （原 item 5be7cabc4d91）、校验/持久化分离的 handleSave（原 item
  // 834f22222a24）均由 hook 承载，本面板只保留字段映射（buildSystemFormValues）
  // 与保存载荷组装。
  const { saving, initialValues, handleSave } = useGatedFormPanel<SystemFormValues>({
    form,
    buildValues: () => buildSystemFormValues(config),
    backfillDeps: [config.admin, config.agents, config.agent],
    onSave,
    buildPayload: (values): Partial<ConfigData> => ({
      admin: {
        enabled: values.enabled,
        interval_minutes: values.interval_minutes,
        escalation_cooldown_minutes: values.escalation_cooldown_minutes,
        merge_breaker_threshold: values.merge_breaker_threshold,
        shutdown_drain_seconds: values.shutdown_drain_seconds,
        bug_repair_mode: values.bug_repair_mode,
        stuck_silence_minutes: values.stuck_silence_minutes,
        // add-adjudication-alert-narrative：叙事三键走既有保存通道
        // （后端 config_admin 受管键白名单：回显/合并/校验三处已同步）
        narrative_enabled: values.narrative_enabled,
        narrative_timeout_seconds: values.narrative_timeout_seconds,
        narrative_model:
          typeof values.narrative_model === 'string'
            ? values.narrative_model.trim()
            : String(values.narrative_model ?? ''),
        // add-alert-self-heal-marking 5.2：自愈安静窗口走既有保存通道
        // （后端 config_admin 受管键白名单：回显/合并/校验/同步四处已同步）
        self_heal_quiet_minutes: values.self_heal_quiet_minutes,
      },
      agents: {
        transient_backoff_schedule:
          typeof values.transient_backoff_schedule === 'string'
            ? values.transient_backoff_schedule.trim()
            : String(values.transient_backoff_schedule ?? ''),
        transient_redispatch_delay_seconds: values.transient_redispatch_delay_seconds,
        transient_break_threshold: values.transient_break_threshold,
        transient_break_window_seconds: values.transient_break_window_seconds,
        transient_break_cooldown_seconds: values.transient_break_cooldown_seconds,
      },
      // add-harness-adapter-layer 6.3：agent.harness 走既有保存通道（后端
      // config_admin 受管键白名单：回显/合并/校验三处同词表消费
      // VALID_HARNESS_VALUES；dsh 已随 add-dsh-adapter-integration 部署，
      // 保存被接受，派发前置健康检查拦截不满足项——文案不写死部署状态断言，
      // 部署态变化由相应 SPEC 同步更新本段）
      agent: { harness: values.harness },
    }),
  });

  // 重启 Fenix Daemon（项目级作用域才显示）：确认后写 restart_request，supervisor
  // 排水（admin.shutdown_drain_seconds）后优雅重启，dashboard 不直接杀进程
  const handleRestart = () => {
    if (!project) return;
    modal.confirm({
      title: '重启 Fenix Daemon',
      content: (
        <div style={{ whiteSpace: 'pre-wrap' }}>
          {`确认重启项目「${project}」的 Fenixd daemon？\n\n`}
          写入 restart_request 后由 supervisor 优雅重启：在跑任务先排水收工
          （上限 = admin.shutdown_drain_seconds），期间新 SPEC 不派发。
        </div>
      ),
      okText: '重启',
      cancelText: '取消',
      onOk: async () => {
        // 失败分支仅 message.error 后正常 resolve（code-review item 4b69df19efff）：
        // return Promise.reject 虽能让弹窗留着供重试，但 antd 会把 onOk 的拒绝再
        // 向外抛，应用无全局 unhandledrejection 兜底，console 落「Uncaught
        // (in promise)」错误条目；重试由用户重按「重启 Fenix Daemon」触发
        try {
          const res = await restartProjectDaemon(project);
          if (res?.ok) {
            message.success('重启请求已写入，daemon 将排水后自动重启');
          } else {
            message.error(`重启失败：${res?.error ?? '未知错误'}`);
          }
        } catch (err) {
          message.error(`重启失败：${err instanceof Error ? err.message : String(err)}`);
        }
      },
    });
  };

  return (
    <div data-testid="system-panel">
      {/* 自省设置已拆至独立「自省」页签（SelfReviewPanel）：本页签单 Form 覆盖
          系统+瞬断治理两段，底部统一一个保存按钮（与其他页签一致：Card 外、右下对齐） */}
      <Form form={form} initialValues={initialValues} layout="vertical" onValuesChange={() => setDirty(true)}>
        <h3>系统</h3>
        <Text type="secondary">
          系统级行为（自愈监视器、重启排水等）的设置界面。保存后约 30 秒经配置热更新生效。
        </Text>
        <Card style={{ marginTop: 12 }}>
          {ADMIN_ANNOTATIONS.map(({ key, label, type, note, unit, rule }) => (
            // 行距由行内最后元素的下边距（24/8px）collapse 提供，此处不挂 inline
            // margin——否则末行会在卡底残留（global.less 的 :last-child 清零压不过
            // inline style）
            <div key={key}>
              {renderAdminField({ key, label, type, unit, rule })}
              {note && <Text type="secondary">{note}</Text>}
            </div>
          ))}
        </Card>
        {/* add-harness-adapter-layer 6.3：agent 进程边界（agent.harness）分组。
            独立 Card：agent 段与 admin/agents 段键空间不同源，混进上方两组会
            让 label-note 的段名前缀失真 */}
        <h3 style={{ marginTop: 20 }}>Agent 进程边界</h3>
        <Text type="secondary">
          派发子进程（实现 / 验证 / 修复等车道）的命令构造边界。保存后约 30 秒经配置热更新生效，在飞 run 不受影响。
        </Text>
        <Card style={{ marginTop: 12 }}>
          <div>
            <Form.Item
              name="harness"
              label={
                <>
                  执行适配器
                  <span className="label-note">（agent.harness）</span>
                </>
              }
              data-testid="system-field-harness"
            >
              <Select
                data-testid="system-control-harness"
                style={{ width: '100%', maxWidth: 320 }}
                options={[
                  { value: 'claude', label: 'claude（缺省）' },
                  { value: 'dsh', label: 'dsh' },
                ]}
              />
            </Form.Item>
            <Text type="secondary">
              dsh adapter 已部署（add-dsh-adapter-integration）：选择后保存即生效。派发前置健康检查会校验 dsh 版本白名单与 fenix Bundle 挂载，不满足时拦截派发并给出修复指引；切换/回切步骤见 docs/help/dsh-harness-runbook.md。
            </Text>
          </div>
        </Card>
        {/* 瞬断治理（fix-provider-transient-backoff D6）：agents.transient_* 五键分组 */}
        <h3 style={{ marginTop: 20 }}>瞬断治理</h3>
        <Text type="secondary">
          provider 网关瞬时故障（model 拒绝 / 5xx / 断连）的退避与熔断策略。保存后约 30 秒经配置热更新生效。
        </Text>
        <Card style={{ marginTop: 12 }}>
          {TRANSIENT_ANNOTATIONS.map(({ key, label, type, note, unit, rule }) => (
            // 行距机制与上方系统分组一致（见 ADMIN_ANNOTATIONS 处注释）：不挂 inline margin
            <div key={key}>
              {renderTransientField({ key, label, type, unit, rule })}
              {note && <Text type="secondary">{note}</Text>}
            </div>
          ))}
        </Card>
      </Form>
      <div
        style={{
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
          marginTop: 24,
        }}
      >
        {/* 左：重启 Fenix Daemon（项目级显示，danger 标示危险操作）；右：同步用户级设置 + 保存 */}
        {project ? (
          <Button type="primary" danger onClick={handleRestart} data-testid="system-restart-btn">
            重启 Fenix Daemon
          </Button>
        ) : (
          <span />
        )}
        <Space>
          {project && onConfigSynced && (
            <SyncFromUserButton project={project} page="system" onSynced={onConfigSynced} />
          )}
          <Button type="primary" onClick={handleSave} loading={saving} disabled={saving} data-testid="system-save-btn">
            保存
          </Button>
        </Space>
      </div>
    </div>
  );
}
