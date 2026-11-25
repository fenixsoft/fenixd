// 文案经 useIntl（i18n 修复轮 batch-S：本文件静态中文文案迁 i18n 目录）
import { useIntl } from '@umijs/max';
import { App, Button, Card, Form, Input, InputNumber, Select, Space, Switch, Typography } from 'antd';
import { useCallback, useMemo } from 'react';
import { restartProjectDaemon } from '@/services/dashboard';
import SyncFromUserButton from './SyncFromUserButton';
import { usePanelDirty } from '../panelDirty';
import { useGatedFormPanel } from '../useGatedFormPanel';
import type { Rule } from 'antd/es/form';
import type { ConfigData } from '@/services/dashboard';

const { Text } = Typography;

// ── 同族整数校验器单源（code-review item e5ba18ad6223）────────────────
// 两组注解表的「正整数 / 非负整数」校验器曾逐字内联重复十一份且写法已漂移
// （TRANSIENT 组多一层 v != null 前置——Number.isInteger(null) 本为 false，
// 语义等价），调词表/边界时易单侧漏改；比照 QualityPanel / TokenBudgetPanel
// 的 POSITIVE_INT_RULE / NON_NEGATIVE_INT_RULE 先例抽模块级单源（各面板
// 判据同族但文案/上下文不同，仍各自持有，不建共享模块）。
// i18n（batch-S）：校验文案渲染期取 intl——校验器改为工厂（t 注入），注解表
// 的 rule 字段相应改为工厂引用，组件内 useMemo 构建本地化副本（禁止模块顶层
// 求值译文，先例 src/utils/format.ts）。
type TranslateFn = (id: string, values?: Record<string, string | number>) => string;

const positiveIntRule = (t: TranslateFn): Rule => ({
  validator: (_: unknown, v: number | undefined | null) =>
    v != null && Number.isInteger(v) && v > 0
      ? Promise.resolve()
      : Promise.reject(new Error(t('settings.system.rules.positiveInt'))),
});
const nonNegativeIntRule = (t: TranslateFn): Rule => ({
  validator: (_: unknown, v: number | undefined | null) =>
    v != null && Number.isInteger(v) && v >= 0
      ? Promise.resolve()
      : Promise.reject(new Error(t('settings.system.rules.nonNegativeInt'))),
});

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
// e3a780766c83：input 形态随告警叙事三键（narrative_model 等）退役后已无消费
// 条目，比照下方 TransientFieldControl「联合按现状收窄，不预留未用形态」先例删除
type AdminFieldControl = 'switch' | 'select' | 'number';

const ADMIN_ANNOTATIONS: {
  key: string;
  label: string;
  note: string;
  /** 控件形态（AdminFieldControl），新增条目必填 */
  type: AdminFieldControl;
  /** 输入单位（addonAfter 附加框）；开关 / 下拉项无单位 */
  unit?: string;
  /** 校验规则工厂（i18n batch-S）：文案渲染期经 t 注入，组件内求值 */
  rule?: (t: TranslateFn) => Rule[];
}[] = [
  {
    key: 'enabled',
    type: 'switch',
    label: 'settings.system.admin.autoHeal.label',
    note: 'settings.system.admin.autoHeal.desc',
  },
  {
    key: 'interval_minutes',
    type: 'number',
    label: 'settings.system.admin.interval.label',
    unit: 'settings.system.unit.minutes',
    note: 'settings.system.admin.interval.desc',
    rule: (t) => [positiveIntRule(t)],
  },
  {
    key: 'escalation_cooldown_minutes',
    type: 'number',
    label: 'settings.system.admin.cooldown.label',
    unit: 'settings.system.unit.minutes',
    note: 'settings.system.admin.cooldown.desc',
    rule: (t) => [nonNegativeIntRule(t)],
  },
  {
    key: 'stuck_silence_minutes',
    type: 'number',
    label: 'settings.system.admin.stuckSilence.label',
    unit: 'settings.system.unit.minutes',
    note: 'settings.system.admin.stuckSilence.desc',
    rule: (t) => [nonNegativeIntRule(t)],
  },
  {
    key: 'merge_breaker_threshold',
    type: 'number',
    label: 'settings.system.admin.mergeBreaker.label',
    unit: 'settings.system.unit.times',
    note: 'settings.system.admin.mergeBreaker.desc',
    rule: (t) => [positiveIntRule(t)],
  },
  {
    key: 'shutdown_drain_seconds',
    type: 'number',
    label: 'settings.system.admin.drain.label',
    unit: 'settings.system.unit.seconds',
    note: 'settings.system.admin.drain.desc',
    rule: (t) => [nonNegativeIntRule(t)],
  },
  {
    key: 'bug_repair_mode',
    type: 'select',
    label: 'settings.system.admin.bugRepair.label',
    note: 'settings.system.admin.bugRepair.desc',
  },
  // consolidate-alerts-to-ops-page 4.4：告警叙事三键（narrative_enabled/
  // narrative_timeout_seconds/narrative_model）控件已随调查叙事生成链退役移除
  {
    key: 'self_heal_quiet_minutes',
    type: 'number',
    label: 'settings.system.admin.quietWindow.label',
    unit: 'settings.system.unit.minutes',
    note: 'settings.system.admin.quietWindow.desc',
    rule: (t) => [positiveIntRule(t)],
  },
];

// 系统分组单字段控件形态（code-review item 4b4856254978）：旧实现以嵌套三元链选择
// 控件，违反本项目前端「禁止嵌套三元」规则，抽模块级 helper 以 if/else 表达
// switch/select/number 三种形态。
// fbb06aa6f869：分派依据从 key 字符串等值改为注解项自带的 type 判别字段
// （AdminFieldControl：switch/select/number），新增字段漏加分派分支时
// 末尾穷举守卫编译报错，不再静默落数值框兜底。仅依赖注解字段本身，
// 无组件闭包依赖，故放模块级。i18n（batch-S）：label/unit/rule 已由组件本地化，
// select 选项文案经第二参 t 渲染期取 intl。
function renderAdminField(
  {
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
    rule?: Rule[];
  },
  t: TranslateFn,
) {
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
            { value: 'inplace', label: t('settings.system.admin.bugRepair.inplace') },
            { value: 'derive', label: t('settings.system.admin.bugRepair.derive') },
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
  /** 校验规则工厂（i18n batch-S）：文案渲染期经 t 注入，组件内求值 */
  rule?: (t: TranslateFn) => Rule[];
}[] = [
  {
    key: 'transient_backoff_schedule',
    type: 'input',
    label: 'settings.system.transient.backoff.label',
    unit: 'settings.system.unit.seconds',
    note: 'settings.system.transient.backoff.desc',
    rule: (t) => [{
      validator: (_: unknown, v: string | undefined | null) => {
        if (v == null || String(v).trim() === '') return Promise.resolve();
        // 先剥离空段再校验（code-review item da5d08818510）：尾逗号（"30,"）容忍，
        // 但全空段串（",,,"）字段非空却不含任何退避秒数，语义上等同关闭原地退避，
        // 与提示文案相悖，须显式报错
        const segs = String(v).split(',').map(p => p.trim()).filter(s => s !== '');
        return segs.length > 0 && segs.every(s => /^\d+$/.test(s) && Number(s) > 0)
          ? Promise.resolve()
          : Promise.reject(new Error(t('settings.system.rules.backoffSchedule')));
      },
    }],
  },
  {
    key: 'transient_redispatch_delay_seconds',
    type: 'number',
    label: 'settings.system.transient.redispatch.label',
    unit: 'settings.system.unit.seconds',
    note: 'settings.system.transient.redispatch.desc',
    rule: (t) => [nonNegativeIntRule(t)],
  },
  {
    key: 'transient_break_threshold',
    type: 'number',
    label: 'settings.system.transient.breakThreshold.label',
    unit: 'settings.system.unit.times',
    note: 'settings.system.transient.breakThreshold.desc',
    rule: (t) => [nonNegativeIntRule(t)],
  },
  {
    key: 'transient_break_window_seconds',
    type: 'number',
    label: 'settings.system.transient.breakWindow.label',
    unit: 'settings.system.unit.seconds',
    note: 'settings.system.transient.breakWindow.desc',
    rule: (t) => [nonNegativeIntRule(t)],
  },
  {
    key: 'transient_break_cooldown_seconds',
    type: 'number',
    label: 'settings.system.transient.breakCooldown.label',
    unit: 'settings.system.unit.seconds',
    note: 'settings.system.transient.breakCooldown.desc',
    rule: (t) => [nonNegativeIntRule(t)],
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
  rule?: Rule[];
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
    // 非法手写值不进 Select（口径同下方 harness：read_config 原文视图可透传
    // 非法枚举，Select 只出 inplace/derive 两合法值，缺省 inplace）
    bug_repair_mode: admin.bug_repair_mode === 'derive' ? 'derive' : 'inplace',
    stuck_silence_minutes: admin.stuck_silence_minutes ?? 120,
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
  const intl = useIntl();
  // 注解表文案本地化（i18n batch-S）：label/note/unit 是消息 id，rule 是工厂——
  // 此处构建运行时副本（label/note/unit 取译文、rule 求值为 Rule[]）再进渲染。
  // label/note/unit 的映射曾缺失致消息 id 原文直接当文案渲染
  // （code-review item 8eef1e7a016e），现与 rule 一并在此取译文
  const t = useCallback(
    (id: string, values?: Record<string, string | number>) => intl.formatMessage({ id }, values),
    [intl],
  );
  const adminAnnotations = useMemo(
    () =>
      ADMIN_ANNOTATIONS.map(({ rule, ...a }) => ({
        ...a,
        label: t(a.label),
        note: t(a.note),
        unit: a.unit ? t(a.unit) : undefined,
        rule: rule?.(t),
      })),
    [t],
  );
  const transientAnnotations = useMemo(
    () =>
      TRANSIENT_ANNOTATIONS.map(({ rule, ...a }) => ({
        ...a,
        label: t(a.label),
        note: t(a.note),
        unit: a.unit ? t(a.unit) : undefined,
        rule: rule?.(t),
      })),
    [t],
  );
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
      title: intl.formatMessage({ id: 'settings.system.restart.title' }),
      content: (
        <div style={{ whiteSpace: 'pre-wrap' }}>
          {intl.formatMessage({ id: 'settings.system.restart.confirmProject' }, { project })}
          {intl.formatMessage({ id: 'settings.system.restart.confirmBody' })}
        </div>
      ),
      okText: intl.formatMessage({ id: 'settings.system.restart.ok' }),
      cancelText: intl.formatMessage({ id: 'common.cancel' }),
      onOk: async () => {
        // 失败分支仅 message.error 后正常 resolve（code-review item 4b69df19efff）：
        // return Promise.reject 虽能让弹窗留着供重试，但 antd 会把 onOk 的拒绝再
        // 向外抛，应用无全局 unhandledrejection 兜底，console 落「Uncaught
        // (in promise)」错误条目；重试由用户重按「重启 Fenix Daemon」触发
        try {
          const res = await restartProjectDaemon(project);
          if (res?.ok) {
            message.success(intl.formatMessage({ id: 'settings.system.restart.requested' }));
          } else {
            message.error(intl.formatMessage({ id: 'settings.system.restart.failed' }, { msg: res?.error ?? intl.formatMessage({ id: 'common.unknownError' }) }));
          }
        } catch (err) {
          message.error(intl.formatMessage({ id: 'settings.system.restart.failed' }, { msg: err instanceof Error ? err.message : String(err) }));
        }
      },
    });
  };

  return (
    <div data-testid="system-panel">
      {/* 自省设置已拆至独立「自省」页签（SelfReviewPanel）：本页签单 Form 覆盖
          系统+瞬断治理两段，底部统一一个保存按钮（与其他页签一致：Card 外、右下对齐） */}
      <Form form={form} initialValues={initialValues} layout="vertical" onValuesChange={() => setDirty(true)}>
        <h3>{intl.formatMessage({ id: 'settings.system.title' })}</h3>
        <Text type="secondary">
          {intl.formatMessage({ id: 'settings.system.desc' })}
        </Text>
        <Card style={{ marginTop: 12 }}>
          {adminAnnotations.map(({ key, label, type, note, unit, rule }) => (
            // 行距由行内最后元素的下边距（24/8px）collapse 提供，此处不挂 inline
            // margin——否则末行会在卡底残留（global.less 的 :last-child 清零压不过
            // inline style）
            <div key={key}>
              {renderAdminField({ key, label, type, unit, rule }, t)}
              {note && <Text type="secondary">{note}</Text>}
            </div>
          ))}
        </Card>
        {/* add-harness-adapter-layer 6.3：agent 进程边界（agent.harness）分组。
            独立 Card：agent 段与 admin/agents 段键空间不同源，混进上方两组会
            让 label-note 的段名前缀失真 */}
        <h3 style={{ marginTop: 20 }}>{intl.formatMessage({ id: 'settings.system.harness.title' })}</h3>
        <Text type="secondary">
          {intl.formatMessage({ id: 'settings.system.harness.desc' })}
        </Text>
        <Card style={{ marginTop: 12 }}>
          <div>
            <Form.Item
              name="harness"
              label={
                <>
                  {intl.formatMessage({ id: 'settings.system.harness.label' })}
                  <span className="label-note">（agent.harness）</span>
                </>
              }
              data-testid="system-field-harness"
            >
              <Select
                data-testid="system-control-harness"
                style={{ width: '100%', maxWidth: 320 }}
                options={[
                  { value: 'claude', label: intl.formatMessage({ id: 'settings.system.harness.claude' }) },
                  { value: 'dsh', label: 'dsh' },
                ]}
              />
            </Form.Item>
            <Text type="secondary">
              {intl.formatMessage({ id: 'settings.system.harness.desc2' })}
            </Text>
          </div>
        </Card>
        {/* 瞬断治理（fix-provider-transient-backoff D6）：agents.transient_* 五键分组 */}
        <h3 style={{ marginTop: 20 }}>{intl.formatMessage({ id: 'settings.system.transient.title' })}</h3>
        <Text type="secondary">
          {intl.formatMessage({ id: 'settings.system.transient.desc' })}
        </Text>
        <Card style={{ marginTop: 12 }}>
          {transientAnnotations.map(({ key, label, type, note, unit, rule }) => (
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
            {intl.formatMessage({ id: 'settings.system.restart.title' })}
          </Button>
        ) : (
          <span />
        )}
        <Space>
          {project && onConfigSynced && (
            <SyncFromUserButton project={project} page="system" onSynced={onConfigSynced} />
          )}
          <Button type="primary" onClick={handleSave} loading={saving} disabled={saving} data-testid="system-save-btn">
            {intl.formatMessage({ id: 'common.save' })}
          </Button>
        </Space>
      </div>
    </div>
  );
}
