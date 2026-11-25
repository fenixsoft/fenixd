// 文案经 useIntl（i18n 修复轮 batch-S：本文件静态中文文案迁 i18n 目录）
import { useIntl } from '@umijs/max';
import { Alert, App, Button, Card, Descriptions, Form, InputNumber, Select, Switch, TimePicker, Typography } from 'antd';
import dayjs from 'dayjs';
import { useCallback, useEffect, useRef, useState } from 'react';
import type { ConfigData } from '@/services/dashboard';
import { autodraftRegression, getOcrStatus, getRegressionConfig, installOcr } from '@/services/dashboard';
import type { OcrStatus, RegressionConfigStatus } from '@/services/dashboard';
import SyncFromUserButton from './SyncFromUserButton';
import { SETTINGS_ACTIONS_ROW_STYLE } from '../styles';
import { usePanelDirty } from '../panelDirty';
import { useGatedFormPanel } from '../useGatedFormPanel';

const { Text } = Typography;

/** list（argv）参数的 shell 引用（code-review item 7b7453b3c4d5）：安全字符集
 *  与包裹规则同 Python shlex.quote（后端 code_fix.py 注入 {test_targets} 时同款），
 *  空串与含空白/引号/shell 元字符的参数一律单引号包裹，内嵌单引号按 '"'"' 惯例
 *  转义——「执行命令」展示串可安全复制回终端重跑而不失真。 */
function shellQuoteArg(arg: string): string {
  const shellSafe = /^[A-Za-z0-9_@%+=:,./-]*$/;
  return arg !== '' && shellSafe.test(arg) ? arg : `'${arg.replace(/'/g, `'"'"'`)}'`;
}

/** regression.cmd 可为 str（shell）或 list（argv）；展示统一成可读串。
 *  list 形态逐参数经 shellQuoteArg 引用后拼接（str 形态本身即 shell 串，原样展示）。 */
function formatCmd(cmd: string | string[]): string {
  return Array.isArray(cmd) ? cmd.map(shellQuoteArg).join(' ') : cmd;
}

// ── 共享常量与校验器（code-review item 6562160caeaa）────────────────
// 「正整数」校验器旧实现为 timeout_sec / concurrency 逐字复制粘贴；effort
// 枚举与 600/4/low 缺省在回填 effect、校验器、<Select.Option>、help 文本
// 多处各写一份（实测已漂移一次：回填注释曾停留在缺省 2）——抽模块级单源。
// i18n（batch-S）：校验文案渲染期取 intl——校验器改工厂（t 注入），调用点
// 组件内求值（禁止模块顶层求值译文，先例 src/utils/format.ts）。
type TranslateFn = (id: string, values?: Record<string, string | number>) => string;

const positiveIntRule = (t: TranslateFn): Rule => ({
  validator: (_: unknown, v: number | undefined | null) =>
    v != null && Number.isInteger(v) && v > 0
      ? Promise.resolve()
      : Promise.reject(new Error(t('settings.quality.rules.positiveInt'))),
});

// 缺省值与后端 read_config / read_effective_config 恒回显值一致（改动时须
// 与 core/verify_contract.py 同步）
const IMPL_REVIEW_DEFAULTS = {
  timeoutSec: 600,
  concurrency: 4,
  effort: 'low',
} as const;

// add-code-review-concurrency-and-429-resilience：全仓审查并发缺省（与
// ConfigLoader.get_repo_code_review_concurrency 缺省同源；模板示例值=缺省值）
const REPO_REVIEW_DEFAULT_CONCURRENCY = 4;

// code-review item 71bf8e4d539a：周期审查/自动修复四项缺省单源——回填与
// help 文案统一引用本常量。回填值会被 handleSave 原样持久化，散落字面量在
// 后端缺省调整时会走本文件头注释的老路：用户开一次设置页再保存即把旧缺省
// 固化进配置（漂移后果比纯展示更重）。
const QUALITY_DEFAULTS = {
  scope: 'window',
  stallAlertMinutes: 15,
  fixBatchSize: 20,
  mode: 'gate',
  // add-code-review-run-at：触发时点回填缺省（后端恒回显生效值——缺省回退
  // admin.self_review.run_at，其文档缺省 02:00；仅作后端响应缺键的兜底）
  runAt: '02:00',
  // severity 分级门限缺省（与后端 get_code_review_fix_config 同源，
  // evo-add-codefix-severity-batch-gate；2026-10-11 总开关缺省翻转）
  minSeverity: 'major',
  minorCadence: 7,
} as const;

const EFFORT_OPTIONS = ['low', 'medium', 'high'] as const;

// severity 门限词表（与后端 _SEVERITY_GATE_RANK 同源，四档）
const SEVERITY_OPTIONS = ['critical', 'major', 'minor', 'info'] as const;

// 长耗时用例阈值缺省（与 core/verify_contract.py RegressionSpec 及项目页
// RegressionTab 的同名常量同源）：帮助文案引用单源，避免数值再漂移
const DEFAULT_LONG_TEST_THRESHOLD_SECONDS = 8;

const effortRule = (t: TranslateFn): Rule => ({
  validator: (_: unknown, v: string | undefined | null) =>
    v && (EFFORT_OPTIONS as readonly string[]).includes(v)
      ? Promise.resolve()
      : Promise.reject(new Error(t('settings.quality.rules.effort'))),
});

// code-review item 2f9799dac3b1：车道裁决模式枚举与批大小上下限比照
// EFFORT_RULE 抽模块级单源（同族校验器逐字复制粘贴曾实际漂移，见本文件头
// 注释），避免调档位/边界时再走老路。Select.Option 的档位文案逐档不同、
// 无法无结构改动地映射枚举，故仅校验器与 InputNumber min/max 走本单源。
const MODE_OPTIONS = ['gate', 'advisory'] as const;

const modeRule = (t: TranslateFn): Rule => ({
  validator: (_: unknown, v: string | undefined | null) =>
    v && (MODE_OPTIONS as readonly string[]).includes(v)
      ? Promise.resolve()
      : Promise.reject(new Error(t('settings.quality.rules.mode'))),
});

const FIX_BATCH_SIZE_BOUNDS = { min: 1, max: 1000 } as const;

const batchSizeRule = (t: TranslateFn): Rule => ({
  validator: (_: unknown, v: number | undefined | null) =>
    v !== null &&
    v !== undefined &&
    Number.isInteger(v) &&
    v >= FIX_BATCH_SIZE_BOUNDS.min &&
    v <= FIX_BATCH_SIZE_BOUNDS.max
      ? Promise.resolve()
      : Promise.reject(new Error(t('settings.quality.rules.batchSize'))),
});

// code-review item 620d75c88dd9：severity 门限枚举与周批节奏上下限比照
// BATCH_SIZE_RULE 抽模块级单源——cadence 的 1–90 边界旧实现内联散写在
// validator 与 InputNumber min/max 两处，同族校验器逐字复制粘贴曾实际漂移
// （见本文件头注释），调词表/上限时易单侧漂移。
const severityRule = (t: TranslateFn): Rule => ({
  validator: (_: unknown, v: string | undefined | null) =>
    v && (SEVERITY_OPTIONS as readonly string[]).includes(v)
      ? Promise.resolve()
      : Promise.reject(new Error(t('settings.quality.rules.severity'))),
});

const CADENCE_BOUNDS = { min: 1, max: 90 } as const;

const minorCadenceRule = (t: TranslateFn): Rule => ({
  validator: (_: unknown, v: number | undefined | null) =>
    typeof v === 'number' &&
    Number.isInteger(v) &&
    v >= CADENCE_BOUNDS.min &&
    v <= CADENCE_BOUNDS.max
      ? Promise.resolve()
      : Promise.reject(new Error(t('settings.quality.rules.minorCadence'))),
});

// 表单值的单一构建来源（code-review item 5ba46a1b4d6c，同族 ParallelSettingsPanel
// item 3f4e251a395c / ApprovalModePanel item 3f618ddb51cb 口径）：字段映射旧实现
// 只写在回填 effect 一处，<Form> 未传 initialValues——控件首帧空显（InputNumber
// 空框、Select 无选中项），须等回填 effect 跑完才显示真实配置（一帧缺省闪变）。
// 收敛为单个纯函数：产物同时喂 initialValues（首帧直出）与回填 effect（门控
// 回填），增删字段/调缺省只改一处。
const buildFormValues = (config: ConfigData) => {
  return {
    impl_code_review: config.verify?.impl_code_review === true,
    // add-impl-code-review-tuning：三运行参数回填缺省（IMPL_REVIEW_DEFAULTS
    // 单源——后端 read_config / read_effective_config 恒回显缺省，前端回填
    // 与之一致；既有开关「缺省不回显」约定不变：impl_code_review 缺席仍为关）
    impl_code_review_timeout_sec:
      config.verify?.impl_code_review_timeout_sec ?? IMPL_REVIEW_DEFAULTS.timeoutSec,
    // add-impl-ocr-parallel-lane（任务 1.2）：后端缺省 2→4，回填与之一致
    impl_code_review_concurrency:
      config.verify?.impl_code_review_concurrency ?? IMPL_REVIEW_DEFAULTS.concurrency,
    // add-code-review-concurrency-and-429-resilience：全仓审查并发回填缺省 4
    // （后端 read_config / read_effective_config 恒回显，前端回填与之一致）
    repo_code_review_concurrency:
      config.verify?.repo_code_review_concurrency ?? REPO_REVIEW_DEFAULT_CONCURRENCY,
    impl_code_review_effort: config.verify?.impl_code_review_effort ?? IMPL_REVIEW_DEFAULTS.effort,
    // add-impl-ocr-parallel-lane：join 双档模式回填缺省 gate（后端恒回显，
    // 前端回填与之一致）
    impl_code_review_mode: config.verify?.impl_code_review_mode ?? QUALITY_DEFAULTS.mode,
    // 周期性代码审查（2026-09-19 从项目页「代码审查」分面迁来）：
    // 开关是项目级配置（admin.code_review.enabled），归设置页而非项目页
    code_review_enabled: config.code_review?.enabled === true,
    // add-code-review-scope-config：审查范围（admin.code_review.scope），
    // 配置缺失回显 window（后端 get_code_review_config 缺省同源）
    code_review_scope: config.code_review?.scope ?? QUALITY_DEFAULTS.scope,
    // add-code-review-sharded-out 3.3：停滞告警阈值（admin.code_review.
    // stall_alert_minutes），配置缺失回显 15（后端 get_code_review_config
    // 缺省同源）
    code_review_stall_alert_minutes:
      config.code_review?.stall_alert_minutes ?? QUALITY_DEFAULTS.stallAlertMinutes,
    // add-code-review-run-at：触发时点（admin.code_review.run_at）回显生效值
    //（后端 get_code_review_config 缺省回退自省 run_at 后恒有值）
    code_review_run_at: dayjs(config.code_review?.run_at ?? QUALITY_DEFAULTS.runAt, 'HH:mm'),
    // add-test-regression-tab：周期性全量回归开关（admin.regression.enabled）
    // 缺省 false；分面只读展示 + 手动触发，配置归设置页「质量」页签
    regression_enabled: config.regression?.enabled === true,
    // add-code-review-auto-fix：自动修复开关 + 批大小（回填缺省 false/20）
    // add-codefix-affinity-batching 4.3：定向回归开关（缺省 true——配置
    // 缺席或非法均视为开，与后端 get_code_review_fix_config 缺省同源）
    code_review_fix_enabled: config.code_review_fix?.enabled === true,
    code_review_fix_batch_size: config.code_review_fix?.batch_size ?? QUALITY_DEFAULTS.fixBatchSize,
    code_review_fix_targeted_regression:
      config.code_review_fix?.targeted_regression !== false,
    // severity 分级门限（2026-10-11）：总开关缺省关闭（当天内容当天处理）；
    // 门限/节奏两键后端恒回显缺省（读侧 fail-open 归一），前端回填同源
    code_review_fix_severity_gate:
      config.code_review_fix?.severity_batch_gate_enabled === true,
    code_review_fix_min_severity:
      config.code_review_fix?.min_immediate_severity ?? QUALITY_DEFAULTS.minSeverity,
    code_review_fix_minor_cadence:
      config.code_review_fix?.minor_batch_cadence ?? QUALITY_DEFAULTS.minorCadence,
  };
};

interface QualityPanelProps {
  config: ConfigData;
  onSave: (values: Partial<ConfigData>) => Promise<boolean>;
  /** 当前项目名；项目级作用域才显示「同步用户级设置」按钮 */
  project?: string;
  /** 同步成功后回填配置（父组件 setConfig 驱动表单刷新） */
  onConfigSynced?: (config: ConfigData) => void;
  /** 「手工编辑」：跳到「项目简介」页签的 verify.yaml 编辑框（父组件负责
   *  切页签与聚焦信号；未传则不显示该按钮） */
  onManualEdit?: () => void;
}

export default function QualityPanel({ config, onSave, project, onConfigSynced, onManualEdit }: QualityPanelProps) {
  const intl = useIntl();
  const t = useCallback(
    (id: string, values?: Record<string, string | number>) => intl.formatMessage({ id }, values),
    [intl],
  );
  const [form] = Form.useForm();
  // 反馈提示经 App.useApp() 取上下文实例（code-review item 0d5a482c07a7）：
  // 静态 message 不经过 App/ConfigProvider 上下文，与其余设置面板口径统一
  const { message } = App.useApp();
  // 用户编辑置脏：切页签/作用域前由 index 经 anyPanelDirty 弹丢弃确认
  // （code-review item 8a3eb01dc2b9）
  const { setDirty } = usePanelDirty();
  // 表单脚手架统一走 useGatedFormPanel（code-review item 5c5a259b8443）：
  // savingRef 重入守卫（原 item 66e48a34144b / b780337cdc73，「先置位再校验」
  // 口径见原 item 2a72f9839b69，hook 入口先置位后 await）、序列化比较回填门控
  // （原 item 241f4f2d452a）、校验/持久化分离的 handleSave 由 hook 承载（持久化
  // 异常兜底 catch 的可达性分析见原 item 330164f11711，已并入 hook 注释）；
  // 本面板保留字段映射（buildFormValues）与四段配置的保存载荷组装。
  const { saving, initialValues, handleSave } = useGatedFormPanel({
    form,
    buildValues: () => buildFormValues(config),
    backfillDeps: [config.verify, config.code_review, config.code_review_fix, config.regression],
    onSave,
    // code-review item 05f17ff15417：下方四段各只含本面板受管键、整段提交是
    // 有意为之——后端 write_config 为按键深合并而非按段替换（核实坐标：
    // core/dashboard/data/config_admin.py:2114 调 _deep_merge_managed，起点
    // copy.deepcopy(raw)；verify 段 :1121-1175 逐键合并，admin.code_review 经
    // _apply_guarded_subkeys :996-1009 从 existing dict 逐键守卫，admin.
    // code_review_fix :1235-1266 与 admin.regression :1271-1280 同款
    // dict(existing) 起步——段内他处受管键不受本面板保存影响）。若后端合并
    // 语义改为按段覆盖，此处须同步改为读取-合并-回写。
    buildPayload: (values): Partial<ConfigData> => ({
      // add-impl-code-review-gate：收尾代码质量审查开关（键路径不变，仅移至质量页签）
      verify: {
        impl_code_review: values.impl_code_review === true,
        // add-impl-code-review-tuning：三运行参数序列化（表单回填后恒有值；
        // 正整数/枚举由表单校验先行把关，后端 write_config 再权威兜底）
        impl_code_review_timeout_sec: values.impl_code_review_timeout_sec,
        impl_code_review_concurrency: values.impl_code_review_concurrency,
        // add-code-review-concurrency-and-429-resilience：全仓审查并发序列化
        // （与 impl 键并列、分别保存，后端 write_config 权威兜底正整数）
        repo_code_review_concurrency: values.repo_code_review_concurrency,
        impl_code_review_effort: values.impl_code_review_effort,
        // add-impl-ocr-parallel-lane：join 双档模式序列化（表单回填后恒有值，
        // 白名单枚举由表单校验先行把关，后端 write_config 再权威兜底）
        impl_code_review_mode: values.impl_code_review_mode,
      },
      // add-code-review-agent-and-quality-tab：周期性代码审查开关
      // （2026-09-19 从项目页「代码审查」分面迁到设置页「质量」页签）
      // add-code-review-scope-config：审查范围并入同段写回（表单回填后
      // 恒有值，枚举由 Select 选项约束，后端 get_code_review_config 权威兜底）
      code_review: {
        enabled: values.code_review_enabled === true,
        scope: values.code_review_scope,
        // add-code-review-sharded-out 3.3：停滞告警阈值（表单回填后恒有值，
        // 正整数由表单校验把关，后端 write_config 权威兜底）
        stall_alert_minutes: values.code_review_stall_alert_minutes,
        // add-code-review-run-at：触发时点序列化（TimePicker 恒有值；HH:MM
        // 由控件格式约束，后端 write_config 权威兜底合法 HH:MM）
        run_at: values.code_review_run_at?.format('HH:mm'),
      },
      // add-test-regression-tab：周期性全量回归开关（admin.regression.enabled，
      // 缺省 false；与 code_review 同周期：admin.self_review.run_at 时点）
      regression: {
        enabled: values.regression_enabled === true,
      },
      // add-code-review-auto-fix：自动修复开关 + 批大小（与开关同处一个
      // <Form> 实例内，validateFields 恒返回两字段；1–1000 由表单校验把关，
      // 后端 write_config 权威兜底）
      // add-codefix-affinity-batching 4.3：定向回归开关并入同段写回
      // （Switch 恒有 bool 值；后端 write_config 权威兜底严格 bool）
      code_review_fix: {
        enabled: values.code_review_fix_enabled === true,
        batch_size: values.code_review_fix_batch_size,
        targeted_regression: values.code_review_fix_targeted_regression === true,
        // severity 分级门限三键（2026-10-11）：Switch/Select/InputNumber 表单
        // 回填后恒有值（枚举由 Select 选项约束、正整数由校验把关，后端
        // write_config 权威兜底）
        severity_batch_gate_enabled: values.code_review_fix_severity_gate === true,
        min_immediate_severity: values.code_review_fix_min_severity,
        minor_batch_cadence: values.code_review_fix_minor_cadence,
      },
    }),
  });
  // 环境门只拦「开启」不拦「关闭」（code-review item 1bcde4921884）：ocr 未
  // 就绪时若把开关一律禁用，已配 verify.impl_code_review:true 的项目从此无法
  // 在 UI 关掉该 gate（禁用开关不可切换，handleSave 还会原样重提 true）。
  const implCodeReviewOn = Form.useWatch('impl_code_review', form) === true;
  // severity 分级门限总开关（2026-10-11）：关闭时门限/节奏两控件置灰
  //（值仍随表单提交，后端在开关关闭时不消费——与 implCodeReviewOn 的
  //「只拦开启」不同：这里两键离开关无意义，置灰防误配）
  const severityGateOn = Form.useWatch('code_review_fix_severity_gate', form) === true;
  // ocr 环境探测状态：null=加载中；未安装时开关置灰并给出「一键安装」
  const [ocr, setOcr] = useState<OcrStatus | null>(null);
  // 探测失败标记（code-review item 734b69fd30ff）：getOcrStatus 网络异常/接口
  // 故障与「确实未安装」不可混谈——失败态单独标记，状态行文案区分并提供
  // 「重新探测」而非一键安装（探测接口故障时装不上也解不了）。开关置灰仍按
  // installed:false fail-closed（口径不变，见下方 ocrReady）。
  const [ocrProbeFailed, setOcrProbeFailed] = useState(false);
  // 重新探测触发器：自增使挂载 effect 重跑（探测逻辑单源留在 effect 内，
  // alive 守卫与卸载清理随之复用）
  const [ocrProbeTick, setOcrProbeTick] = useState(0);
  const [installing, setInstalling] = useState(false);
  // 安装重入同帧加固（code-review item 7e689f7abd2d，比照 useGatedFormPanel 的
  // savingRef（原 item b780337cdc73）/ regressionDraftInFlight 口径）：setInstalling 渲染生效存在
  // React 调度间隙，state 短路拦不住同帧双击（或确认弹窗双触发）——installOcr
  // 是慢请求，同帧连点会发出两个并发 install 请求（后端幂等性未核实）。经 ref
  // 写读同帧原子拦截，state 只负责按钮 loading 视觉反馈。
  const installInFlight = useRef(false);
  // 项目作用域：verify.yaml regression 段配置状态（null=加载中/未加载）
  const [regressionCfg, setRegressionCfg] = useState<RegressionConfigStatus | null>(null);
  const [regressionCfgError, setRegressionCfgError] = useState<string | null>(null);
  const [regressionDrafting, setRegressionDrafting] = useState(false);
  // 补段请求同步防重入锁（同 ProjectProfilePanel 的 autodraftInFlight 约定：loading
  // 渲染生效存在调度间隙，useRef 写读同帧原子）
  const regressionDraftInFlight = useRef(false);
  // 当前 project prop 镜像 ref（code-review item e884e5a8a3af，与
  // SelfReviewPanel item 522b3bd7ae53 同形态）：autodraft 终态后的滞后重拉
  // 闭包捕获的是发起时的 project（数分钟请求期间用户可切换项目），完成时经
  // ref 判等丢弃已被项目切换取代的响应——初始拉取 effect 的 alive 守卫拦
  // 不到这条链路，否则旧项目 regression 段/在途态会覆盖新项目视图。
  const projectRef = useRef(project);
  useEffect(() => {
    projectRef.current = project;
  }, [project]);

  // 卸载判活守卫（code-review item 1228ded8194b，比照 SuggestedImprovementsPanel
  // 的 mountedRef 口径）：本设置页面板按 activeKey 条件渲染、切页签即卸载，而
  // handleInstall（installOcr 慢请求）与 handleRegressionAutodraft（后端 headless
  // 起草约数分钟）在多段 await 之后才写 state——各 setState 点统一挂判活守卫，
  // 不让响应/收口打到已卸载实例（React 19 下虽为无害 no-op，仍恢复同族防御口径）。
  const mountedRef = useRef(true);
  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
    };
  }, []);

  useEffect(() => {
    let alive = true;
    getOcrStatus()
      .then((s) => {
        if (alive) setOcr(s);
      })
      .catch(() => {
        // fail-closed 保留（按未安装置灰），但 probeFailed 让状态行区分
        // 「探测失败」与「未安装」，不再一律引导重复安装
        if (alive) {
          setOcr({ installed: false, bin: null, version: null });
          setOcrProbeFailed(true);
        }
      });
    return () => {
      alive = false;
    };
  }, [ocrProbeTick]);

  // 项目作用域：拉取 verify.yaml 的 regression 段配置状态（切换项目重拉；
  // alive 守卫丢弃被取代的旧响应）
  useEffect(() => {
    if (!project) {
      setRegressionCfg(null);
      setRegressionCfgError(null);
      return;
    }
    let alive = true;
    setRegressionCfg(null);
    setRegressionCfgError(null);
    getRegressionConfig(project)
      .then((d) => {
        if (alive) setRegressionCfg(d);
      })
      .catch((e) => {
        if (alive) setRegressionCfgError(e instanceof Error ? e.message : String(e));
      });
    return () => {
      alive = false;
    };
  }, [project]);

  const handleInstall = async () => {
    if (installInFlight.current) return;
    installInFlight.current = true;
    if (mountedRef.current) setInstalling(true);
    try {
      // 1) 安装调用（code-review item 52c15fcd9bc1）：必须先检查 res.ok——
      // 旧实现不看返回值，ok===false/version===null 时仍提示「安装成功」。
      let res;
      try {
        res = await installOcr();
      } catch (err) {
        message.error(t('settings.quality.installFailed', { msg: err instanceof Error ? err.message : String(err) }));
        return;
      }
      if (!res.ok) {
        message.error(t('settings.quality.installFailed', { msg: res.error || t('settings.quality.installNpmFailed') }));
        return;
      }
      message.success(
        res.version
          ? t('settings.quality.installSuccess', { version: res.version })
          : t('settings.quality.installSuccessPlain'),
      );
      // 2) 安装成功后重新探测（独立 try）：探测失败不应把已成功的安装误报为失败、
      // 也不应让 ocr 停在 stale（否则开关永久置灰）。
      try {
        const fresh = await getOcrStatus();
        if (mountedRef.current) setOcr(fresh);
      } catch {
        // 探测失败：乐观标记为已安装（版本未知），至少解锁开关
        if (mountedRef.current)
          setOcr({ installed: true, bin: null, version: res.version ?? null });
      }
    } finally {
      installInFlight.current = false;
      if (mountedRef.current) setInstalling(false);
    }
  };

  // 重新探测（code-review item 734b69fd30ff）：探测失败态的入口——清空状态回
  // 「正在检测」并自增 tick 重跑挂载 effect（探测逻辑单源），不直接引导安装
  const handleReprobe = () => {
    setOcr(null);
    setOcrProbeFailed(false);
    setOcrProbeTick((t) => t + 1);
  };

  // 「AI 自动生成」：同步生成 regression 段（后端 HTTP 线程内 headless claude
  // 起草 + 自证 + 落位 verify.yaml，返回即终态；约数分钟，按钮 loading 覆盖全程）
  const handleRegressionAutodraft = async () => {
    if (!project || regressionDraftInFlight.current) return;
    // 在途态（后端单飞锁，经 config 端点带回）：切页签卸载重建后本地 loading
    // 丢失的场景由它恢复；此时直接提示，不发无效请求（后端 409 兜底仍在）
    if (regressionCfg?.autodraft_in_flight) {
      message.info(t('settings.quality.autodraftInFlightMsg'));
      return;
    }
    regressionDraftInFlight.current = true;
    if (mountedRef.current) setRegressionDrafting(true);
    try {
      const res = await autodraftRegression(project);
      if (res.ok) {
        if (res.status === 'success') {
          message.success(res.message || t('settings.quality.autodraftDone'));
        } else {
          message.info(res.message || t('settings.quality.autodraftAlreadyConfigured'));
        }
        // 终态后重拉配置状态：success 时卡片从「缺失提示」切到已配置展示；
        // no_test_system 时幂等重拉（结果不变，无害）
        getRegressionConfig(project)
          .then((d) => {
            // 项目切换守卫（code-review item e884e5a8a3af）：重拉 resolve 时
            // 用户可能已切换项目（projectRef 已更新、闭包 project 未变），
            // 只回填仍是当前项目的响应；mountedRef 判活（item 1228ded8194b）
            // 再挡一层已卸载实例的回填
            if (mountedRef.current && projectRef.current === project) setRegressionCfg(d);
          })
          .catch(() => {
            /* 重拉失败不打断成功结论：下次进入页面 effect 会重拉 */
          });
      } else {
        message.error(res.error || t('settings.quality.autodraftFailed'));
      }
    } catch (err) {
      message.error(t('settings.quality.autodraftFailedWith', { msg: err instanceof Error ? err.message : String(err) }));
    } finally {
      regressionDraftInFlight.current = false;
      if (mountedRef.current) setRegressionDrafting(false);
    }
  };

  // 环境门控：ocr 未安装（或探测失败）时阻止「开启」——避免开启一个运行期必然
  // 降级跳过的开关。探测未返回（加载中）时对关闭态同样置灰，避免先开后关的
  // 闪变；已开启的 gate 不禁用，保证关闭路径始终可用（见上方 useWatch 注释）。
  const ocrReady = ocr?.installed === true;

  // ocr 环境状态行（code-review item 2f3f9bd1b013）：旧实现嵌套三元违反前端
  // 规则，抽 helper 以 if/else 表达「加载中 / 已装 / 探测失败 / 未装」四分支
  //（探测失败分支为 item 734b69fd30ff 新增，见上方 ocrProbeFailed 注释）。
  const renderOcrStatus = () => {
    if (ocr === null) {
      return <Text type="secondary">{t('settings.quality.ocrChecking')}</Text>;
    }
    if (ocr.installed) {
      return (
        <Alert
          type="success"
          showIcon
          message={t('settings.quality.ocrInstalledTitle')}
          description={ocr.version || ocr.bin || t('settings.quality.ocrDetectedBinary')}
          // 下边距与卡片 body 上内边距（24px）对齐：Alert 自身无默认外边距，
          // 否则它会紧贴下方开关行，视觉上「上松下紧」。
          style={{ marginBottom: 24 }}
          data-testid="ocr-installed-alert"
        />
      );
    }
    if (ocrProbeFailed) {
      return (
        <Alert
          type="error"
          showIcon
          message={t('settings.quality.ocrProbeFailedTitle')}
          description={t('settings.quality.ocrProbeFailedDesc')}
          action={
            <Button size="small" onClick={handleReprobe} data-testid="ocr-reprobe-btn">
              {t('settings.quality.ocrReprobe')}
            </Button>
          }
          data-testid="ocr-probe-error-alert"
        />
      );
    }
    return (
      <Alert
        type="warning"
        showIcon
        message={t('settings.quality.ocrMissingTitle')}
        description={t('settings.quality.ocrMissingDesc')}
        action={
          <Button
            type="primary"
            size="small"
            loading={installing}
            onClick={handleInstall}
            data-testid="ocr-install-btn"
          >
            {t('settings.quality.ocrInstall')}
          </Button>
        }
        data-testid="ocr-missing-alert"
      />
    );
  };

  // verify.yaml regression 段配置状态行（code-review item e90818824d7d）：旧实现
  // 嵌套三元违反前端规则，比照 renderOcrStatus 抽 helper 以 if/else 表达
  //「读取失败 / 读取中 / 已配置 / 无 verify.yaml / 未配置 regression 段」五分支。
  const renderRegressionConfigStatus = () => {
    if (regressionCfgError) {
      return (
        <Alert
          type="error"
          showIcon
          message={t('settings.quality.regStatusReadFailed')}
          description={regressionCfgError}
        />
      );
    }
    if (regressionCfg === null) {
      return <Text type="secondary">{t('settings.quality.regStatusReading')}</Text>;
    }
    if (regressionCfg.regression) {
      return (
        <>
          <Text type="secondary">{t('settings.quality.regStatusConfigured')}</Text>
          <Descriptions size="small" column={1} bordered style={{ marginTop: 8 }}>
            <Descriptions.Item label={t('settings.quality.regCmd')}>
              <Text code>{formatCmd(regressionCfg.regression.cmd)}</Text>
            </Descriptions.Item>
            <Descriptions.Item label={t('settings.quality.regOutput')}>
              <Text code>{regressionCfg.regression.output}</Text>
            </Descriptions.Item>
            <Descriptions.Item label={t('settings.quality.regTimeout')}>
              {regressionCfg.regression.timeout_seconds} {t('settings.quality.unit.seconds')}
            </Descriptions.Item>
            <Descriptions.Item label={t('settings.quality.regLongThreshold')}>
              {regressionCfg.regression.long_test_threshold_seconds} {t('settings.quality.unit.seconds')}
            </Descriptions.Item>
          </Descriptions>
        </>
      );
    }
    if (!regressionCfg.exists) {
      return (
        <Alert
          type="info"
          showIcon
          message={t('settings.quality.regNoVerifyYaml')}
          description={t('settings.quality.regNoVerifyYamlDesc')}
        />
      );
    }
    return (
      <Alert
        type="warning"
        showIcon
        message={t('settings.quality.regNoSection')}
        description={t('settings.quality.regNoSectionDesc')}
      />
    );
  };

  return (
    <div>
      <h3>{t('settings.quality.title')}</h3>
      <Text type="secondary">{t('settings.quality.desc')}</Text>
      {/* 统一 Form 包裹全部卡片（fix-verify-bug 2026-09-21）：旧实现把
          周期代码审查 / 周期全量回归两个开关放在 <Form> 外的 <div> 容器里，
          rc-field-form 的 Form.Item 只在 <form> 内注册字段——validateFields()
          不返回脱管字段，handleSave 恒提交 enabled:false（视觉开启但后端未
          持久化，api-regression-config-persisted 验证实测确证）。 */}
      <Form
        form={form}
        initialValues={initialValues}
        layout="vertical"
        onValuesChange={() => setDirty(true)}
        style={{ marginTop: 16 }}
      >
        <Card style={{ marginTop: 12 }}>
          {/* 环境状态行：已装 → 绿色提示；未装 → 橙色提示 + 一键安装按钮
              （渲染逻辑抽 renderOcrStatus，见其注释） */}
          {renderOcrStatus()}
          {/* 开关行与其它设置页一致：开关在前、名称紧随同行（.switch-inline-row） */}
          <div className="switch-inline-row">
            <Form.Item name="impl_code_review" valuePropName="checked" noStyle>
              <Switch
                data-testid="impl-code-review-switch"
                disabled={!ocrReady && !implCodeReviewOn}
              />
            </Form.Item>
            <span className="switch-inline-label">
              {t('settings.quality.implReview.label')}
              <span className="label-note">（verify.impl_code_review）</span>
            </span>
          </div>
          {!ocrReady && ocr !== null && (
            <Text type="warning" style={{ display: 'block', marginBottom: 8 }}>
              {ocrProbeFailed
                ? t('settings.quality.implReview.probeFailedHint')
                : t('settings.quality.implReview.installFirstHint')}
            </Text>
          )}
          <Text type="secondary">
            {t('settings.quality.implReview.desc')}
          </Text>

          {/* add-impl-code-review-tuning：三运行参数编辑控件（超时秒 / 并发 / 力度）。
              与 ocr 参数对应：timeout_sec 写入 run 级 ocr provider 配置（确定性生效）；
              --concurrency / --effort 经提示词命令示例承载（软约束，实现者须照抄命令串）。
              缺省回填 600 / 4 / low（后端 read_config / read_effective_config 恒回显缺省）。 */}
          <Form.Item
            name="impl_code_review_timeout_sec"
            label={
              <>
                {t('settings.quality.timeout.label')}
                <span className="label-note">（verify.impl_code_review_timeout_sec）</span>
              </>
            }
            rules={[positiveIntRule(t)]}
            style={{ marginTop: 24 }}
          >
            <InputNumber
              min={1}
              precision={0}
              style={{ width: '100%' }}
              addonAfter={t('settings.quality.unit.seconds')}
              data-testid="impl-code-review-timeout"
            />
          </Form.Item>
          <Text type="secondary">
            {t('settings.quality.timeout.desc', { default: IMPL_REVIEW_DEFAULTS.timeoutSec })}
          </Text>

          <Form.Item
            name="impl_code_review_concurrency"
            label={
              <>
                {t('settings.quality.concurrency.label')}
                <span className="label-note">（verify.impl_code_review_concurrency）</span>
              </>
            }
            rules={[positiveIntRule(t)]}
            style={{ marginTop: 24 }}
          >
            <InputNumber
              min={1}
              precision={0}
              style={{ width: '100%' }}
              addonAfter={t('settings.misc.unit.items')}
              data-testid="impl-code-review-concurrency"
            />
          </Form.Item>
          <Text type="secondary">
            {t('settings.quality.concurrency.desc', { default: IMPL_REVIEW_DEFAULTS.concurrency })}
          </Text>

          {/* add-code-review-concurrency-and-429-resilience：全仓审查并发——
              一个键同时约束全仓审查 run（manual_full/manual_window/scheduled）
              的两处并发源：① 提示词侧审查子代理并行扇出上限（波内并行、波次
              滚动推进）；② ocr scan --concurrency（ocr 内置缺省 8，2026-09-24
              429 限流事故的并发来源之一）。与 SPEC 审查并发并列展示、分别保存。 */}
          <Form.Item
            name="repo_code_review_concurrency"
            label={
              <>
                {t('settings.quality.repoConcurrency.label')}
                <span className="label-note">（verify.repo_code_review_concurrency）</span>
              </>
            }
            rules={[positiveIntRule(t)]}
            style={{ marginTop: 24 }}
          >
            <InputNumber
              min={1}
              precision={0}
              style={{ width: '100%' }}
              addonAfter={t('settings.misc.unit.items')}
              data-testid="repo-code-review-concurrency"
            />
          </Form.Item>
          <Text type="secondary">
            {t('settings.quality.repoConcurrency.desc', { default: REPO_REVIEW_DEFAULT_CONCURRENCY })}
          </Text>

          <Form.Item
            name="impl_code_review_effort"
            label={
              <>
                {t('settings.quality.effort.label')}
                <span className="label-note">（verify.impl_code_review_effort）</span>
              </>
            }
            rules={[effortRule(t)]}
            style={{ marginTop: 24 }}
          >
            <Select
              data-testid="impl-code-review-effort"
              options={EFFORT_OPTIONS.map((opt) => ({ value: opt, label: opt }))}
            />
          </Form.Item>
          <Text type="secondary">
            {t('settings.quality.effort.desc', { default: IMPL_REVIEW_DEFAULTS.effort })}
          </Text>

          {/* add-impl-ocr-parallel-lane：join 双档模式选择（gate/advisory）。
              车道在实现分支合并后异步跑 ocr，tester 判定 verified 时 join 裁决：
              gate 档非 rejected findings 打回修复轮（上限 1 轮，超限转台账）；
              advisory 档 findings 一律写 code-review 台账、join 永不打回。 */}
          <Form.Item
            name="impl_code_review_mode"
            label={
              <>
                {t('settings.quality.mode.label')}
                <span className="label-note">（verify.impl_code_review_mode）</span>
              </>
            }
            rules={[modeRule(t)]}
            style={{ marginTop: 24 }}
          >
            <Select
              data-testid="impl-code-review-mode"
              options={[
                { value: 'gate', label: t('settings.quality.mode.gate') },
                { value: 'advisory', label: t('settings.quality.mode.advisory') },
              ]}
            />
          </Form.Item>
          <Text type="secondary">
            {t('settings.quality.mode.desc', { default: QUALITY_DEFAULTS.mode })}
          </Text>

          {/* 周期性代码审查开关（2026-09-19 从项目页「代码审查」分面迁到本页签）：
              它是项目级配置（admin.code_review.enabled），与手动触发按钮的性质不同
              ——分面负责「看结果 + 手动触发」，配置归设置页统一管理。
              与「收尾代码质量审查」同属代码质量范畴，故并入本卡片而非独立成卡。
              注：本条改动在 merge-back 中两次因「先 stash 后 merge」被丢弃，本卡片
              由 admin 处置（stash_pop_conflict）从 stash 找回，见 admin_disposition。 */}
          <div className="switch-inline-row" style={{ marginTop: 24 }}>
            <Form.Item name="code_review_enabled" valuePropName="checked" noStyle>
              <Switch data-testid="code-review-enabled-switch" />
            </Form.Item>
            <span className="switch-inline-label">
              {t('settings.quality.crEnabled.label')}
              <span className="label-note">（admin.code_review.enabled）</span>
            </span>
          </div>
          <Text type="secondary">
            {t('settings.quality.crEnabled.desc')}
          </Text>

          {/* add-code-review-run-at 4.2：触发时点（admin.code_review.run_at，
              HH:MM）——与自省时点解耦（错峰避免与自省链同刻齐发触发网关限流），
              未显式配置时后端回退 admin.self_review.run_at（回显恒为生效值）。
              与 SelfReviewPanel run_at 同形态：TimePicker HH:mm。 */}
          <Form.Item
            name="code_review_run_at"
            label={
              <>
                {t('settings.quality.runAt.label')}
                <span className="label-note">（admin.code_review.run_at，HH:MM）</span>
              </>
            }
            style={{ marginTop: 24 }}
            data-testid="code-review-field-run_at"
          >
            <TimePicker
              data-testid="code-review-run-at"
              format="HH:mm"
              allowClear={false}
              placeholder={t('settings.quality.runAt.placeholder')}
              style={{ width: 160 }}
            />
          </Form.Item>
          <Text type="secondary">
            {t('settings.quality.runAt.desc')}
          </Text>

          {/* add-code-review-scope-config：审查范围下拉（admin.code_review.scope）。
              文案与项目页手动触发按钮（全库审查 / 当期审查）语义对齐，不引入
              第三套叫法；保存并入既有 admin.code_review 受管段（见 handleSave）。 */}
          <Form.Item
            name="code_review_scope"
            label={
              <>
                {t('settings.quality.scope.label')}
                <span className="label-note">（admin.code_review.scope）</span>
              </>
            }
            style={{ marginTop: 24 }}
          >
            <Select
              data-testid="code-review-scope"
              options={[
                { value: 'window', label: t('settings.quality.scope.window') },
                { value: 'full', label: t('settings.quality.scope.full') },
              ]}
            />
          </Form.Item>
          <Text type="secondary">
            {t('settings.quality.scope.desc', { default: QUALITY_DEFAULTS.scope })}
          </Text>

          {/* add-code-review-sharded-out 3.3：停滞告警阈值输入（分钟粒度、
              正整数校验，保存并入既有 admin.code_review 受管段写路径）。
              与 code_review_fix_batch_size 同形态：整宽 + addonAfter 单位。 */}
          <Form.Item
            name="code_review_stall_alert_minutes"
            label={
              <>
                {t('settings.quality.stall.label')}
                <span className="label-note">（admin.code_review.stall_alert_minutes）</span>
              </>
            }
            rules={[positiveIntRule(t)]}
            style={{ marginTop: 24 }}
          >
            <InputNumber
              data-testid="code-review-stall-alert-minutes"
              min={1}
              precision={0}
              addonAfter={t('settings.system.unit.minutes')}
              style={{ width: '100%' }}
            />
          </Form.Item>
          <Text type="secondary">
            {t('settings.quality.stall.desc', { default: QUALITY_DEFAULTS.stallAlertMinutes })}
          </Text>

          {/* 自动修复代码问题（add-code-review-auto-fix，task 9.2）：2026-09-22
              自独立卡片并入本卡，位于「周期性代码审查」之后（spec code-fix-config
              位置约束同步改为「同卡其后」）。同一 <Form> 实例内（脱管字段
              validateFields 不返回 → 恒提交缺省，见上方统一 Form 注释）。 */}
          <div className="switch-inline-row" style={{ marginTop: 24 }}>
            <Form.Item name="code_review_fix_enabled" valuePropName="checked" noStyle>
              <Switch data-testid="code-review-fix-enabled-switch" />
            </Form.Item>
            <span className="switch-inline-label">
              {t('settings.quality.fix.label')}
              <span className="label-note">（admin.code_review_fix.enabled）</span>
            </span>
          </div>
          <Text type="secondary">
            {t('settings.quality.fix.desc', { default: QUALITY_DEFAULTS.fixBatchSize })}
          </Text>
          {/* 批大小与「审查超时/并发」同形态：整宽 + addonAfter 单位。旧实现
              maxWidth:240 会把 inline-flex label 里的裸文本节点压到 min-content
              （一字一行竖排，机制见 global.less 移动端 label 修复注释）。 */}
          <Form.Item
            name="code_review_fix_batch_size"
            label={
              <>
                {t('settings.quality.batchSize.label')}
                <span className="label-note">（admin.code_review_fix.batch_size）</span>
              </>
            }
            rules={[batchSizeRule(t)]}
            style={{ marginTop: 24 }}
          >
            <InputNumber
              min={FIX_BATCH_SIZE_BOUNDS.min}
              max={FIX_BATCH_SIZE_BOUNDS.max}
              precision={0}
              style={{ width: '100%' }}
              addonAfter={t('settings.quality.unit.entries')}
              data-testid="code-review-fix-batch-size"
            />
          </Form.Item>
          {/* add-codefix-affinity-batching 4.3：批收尾回归两段式开关
              （admin.code_review_fix.targeted_regression，缺省 true）。
              与 code_review_fix_enabled 同形态：switch-inline-row + 说明文案。 */}
          <div className="switch-inline-row" style={{ marginTop: 24 }}>
            <Form.Item
              name="code_review_fix_targeted_regression"
              valuePropName="checked"
              noStyle
            >
              <Switch data-testid="code-review-fix-targeted-regression-switch" />
            </Form.Item>
            <span className="switch-inline-label">
              {t('settings.quality.targeted.label')}
              <span className="label-note">
                （admin.code_review_fix.targeted_regression）
              </span>
            </span>
          </div>
          <Text type="secondary">
            {t('settings.quality.targeted.descA')}
            <code>{'{test_targets}'}</code>
            {t('settings.quality.targeted.descB')}
          </Text>

          {/* severity 分级门限（evo-add-codefix-severity-batch-gate；2026-10-11
              总开关缺省翻转为关 + 补 Dashboard 界面）。与上方开关同形态：
              switch-inline-row + 说明文案；门限/节奏两控件随开关置灰。 */}
          <div className="switch-inline-row" style={{ marginTop: 24 }}>
            <Form.Item
              name="code_review_fix_severity_gate"
              valuePropName="checked"
              noStyle
            >
              <Switch data-testid="code-review-fix-severity-gate-switch" />
            </Form.Item>
            <span className="switch-inline-label">
              {t('settings.quality.severityGate.label')}
              <span className="label-note">
                （admin.code_review_fix.severity_batch_gate_enabled）
              </span>
            </span>
          </div>
          <Text type="secondary">
            {t('settings.quality.severityGate.desc')}
          </Text>
          <Form.Item
            name="code_review_fix_min_severity"
            label={
              <>
                {t('settings.quality.minSeverity.label')}
                <span className="label-note">
                  （admin.code_review_fix.min_immediate_severity）
                </span>
              </>
            }
            rules={[severityRule(t)]}
            style={{ marginTop: 24 }}
          >
            <Select
              options={SEVERITY_OPTIONS.map((s) => ({ value: s, label: s }))}
              disabled={!severityGateOn}
              data-testid="code-review-fix-min-severity"
            />
          </Form.Item>
          <Form.Item
            name="code_review_fix_minor_cadence"
            label={
              <>
                {t('settings.quality.cadence.label')}
                <span className="label-note">
                  （admin.code_review_fix.minor_batch_cadence）
                </span>
              </>
            }
            rules={[minorCadenceRule(t)]}
          >
            <InputNumber
              min={CADENCE_BOUNDS.min}
              max={CADENCE_BOUNDS.max}
              precision={0}
              style={{ width: '100%' }}
              addonAfter={t('settings.chain.unit.days')}
              disabled={!severityGateOn}
              data-testid="code-review-fix-minor-cadence"
            />
          </Form.Item>
        </Card>
        {/* 回归测试：标题与说明置于卡片外，与上方「代码质量」节同构 */}
        <h3 style={{ marginTop: 32 }}>{t('settings.quality.regression.title')}</h3>
        <Text type="secondary">{t('settings.quality.regression.desc')}</Text>
        {/* add-test-regression-tab：周期性全量回归开关（admin.regression.enabled）。
            与 code_review 同层同形态：开关归设置页，项目页「测试回归」分面只读
            展示 + 手动触发。开启前提 = 项目 .fenix/verify.yaml 有有效 regression 段
            （无段时周期检查点跳过、不派发空跑）；长耗时阈值归 verify.yaml 声明
            （regression.long_test_threshold_seconds 缺省 8），本卡片只读说明其来源，
            MUST NOT 另开第二个阈值写入路径（双写会让阈值来源分叉，design R4）——
            编辑入口复用既有 GET/POST /api/verify-yaml（项目设置「项目简介」面板）。 */}
        <Card style={{ marginTop: 12 }}>
          <div>
            <div className="switch-inline-row">
              <Form.Item name="regression_enabled" valuePropName="checked" noStyle>
                <Switch data-testid="regression-enabled-switch" />
              </Form.Item>
              <span className="switch-inline-label">
                {t('settings.quality.regression.switch')}
                <span className="label-note">（admin.regression.enabled）</span>
              </span>
            </div>
            <Text type="secondary" style={{ display: 'block', marginTop: 8 }}>
              {t('settings.quality.regression.switchDesc')}
            </Text>
            <Text type="secondary" style={{ display: 'block', marginTop: 8 }}>
              {t('settings.quality.regression.thresholdDesc', { default: DEFAULT_LONG_TEST_THRESHOLD_SECONDS })}
            </Text>

            {/* 项目作用域专属：verify.yaml regression 段配置状态（只读）+ AI 补段。
                用户级作用域不显示（verify.yaml 是项目级文件）。
                判定走后端 load_verify_contract（前端无 yaml 解析库，正则判段不可靠）。 */}
            {project && (
              <div style={{ marginTop: 16 }} data-testid="regression-config-section">
                {renderRegressionConfigStatus()}
                <div style={{ marginTop: 12 }}>
                  {/* loading 双源：本地 drafting（本组件生命周期内）+ 后端单飞锁
                      在途态（切页签卸载重建后本地 state 丢失，重挂载拉 config 恢复）。
                      可选链：config 未加载完（null）时按钮先于数据渲染 */}
                  <Button
                    onClick={handleRegressionAutodraft}
                    loading={regressionDrafting || regressionCfg?.autodraft_in_flight === true}
                    data-testid="regression-autodraft-btn"
                  >
                    {t('settings.quality.autodraftBtn')}
                  </Button>
                  {onManualEdit && (
                    <Button style={{ marginLeft: 8 }} onClick={onManualEdit} data-testid="regression-manual-edit-btn">
                      {t('settings.quality.manualEdit')}
                    </Button>
                  )}
                </div>
              </div>
            )}
          </div>
        </Card>
      </Form>
      <div style={project ? SETTINGS_ACTIONS_ROW_STYLE : { textAlign: 'right', marginTop: 24 }}>
        {project && onConfigSynced && (
          <SyncFromUserButton project={project} page="quality" onSynced={onConfigSynced} />
        )}
        <Button type="primary" onClick={handleSave} loading={saving} disabled={saving} data-testid="quality-save">
          {t('common.save')}
        </Button>
      </div>
    </div>
  );
}
