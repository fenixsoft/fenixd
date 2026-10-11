import { Alert, App, Button, Card, Descriptions, Form, InputNumber, Select, Switch, TimePicker, Typography } from 'antd';
import dayjs from 'dayjs';
import { useEffect, useRef, useState } from 'react';
import type { ConfigData } from '@/services/dashboard';
import { autodraftRegression, getOcrStatus, getRegressionConfig, installOcr } from '@/services/dashboard';
import type { OcrStatus, RegressionConfigStatus } from '@/services/dashboard';
import SyncFromUserButton from './SyncFromUserButton';
import { SETTINGS_ACTIONS_ROW_STYLE } from '../styles';
import { usePanelDirty } from '../panelDirty';
import { useGatedFormPanel } from '../useGatedFormPanel';

const { Text } = Typography;

/** regression.cmd 可为 str（shell）或 list（argv）；展示统一成可读串 */
function formatCmd(cmd: string | string[]): string {
  return Array.isArray(cmd) ? cmd.join(' ') : cmd;
}

// ── 共享常量与校验器（code-review item 6562160caeaa）────────────────
// 「正整数」校验器旧实现为 timeout_sec / concurrency 逐字复制粘贴；effort
// 枚举与 600/4/low 缺省在回填 effect、校验器、<Select.Option>、help 文本
// 多处各写一份（实测已漂移一次：回填注释曾停留在缺省 2）——抽模块级单源。
const POSITIVE_INT_RULE = {
  validator: (_: unknown, v: number | undefined | null) =>
    v != null && Number.isInteger(v) && v > 0
      ? Promise.resolve()
      : Promise.reject(new Error('须为正整数')),
};

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

const EFFORT_RULE = {
  validator: (_: unknown, v: string | undefined | null) =>
    v && (EFFORT_OPTIONS as readonly string[]).includes(v)
      ? Promise.resolve()
      : Promise.reject(new Error('须为 low/medium/high')),
};

// code-review item 2f9799dac3b1：车道裁决模式枚举与批大小上下限比照
// EFFORT_RULE 抽模块级单源（同族校验器逐字复制粘贴曾实际漂移，见本文件头
// 注释），避免调档位/边界时再走老路。Select.Option 的档位文案逐档不同、
// 无法无结构改动地映射枚举，故仅校验器与 InputNumber min/max 走本单源。
const MODE_OPTIONS = ['gate', 'advisory'] as const;

const MODE_RULE = {
  validator: (_: unknown, v: string | undefined | null) =>
    v && (MODE_OPTIONS as readonly string[]).includes(v)
      ? Promise.resolve()
      : Promise.reject(new Error('须为 gate/advisory')),
};

const FIX_BATCH_SIZE_BOUNDS = { min: 1, max: 1000 } as const;

const BATCH_SIZE_RULE = {
  validator: (_: unknown, v: number | undefined | null) =>
    v !== null &&
    v !== undefined &&
    Number.isInteger(v) &&
    v >= FIX_BATCH_SIZE_BOUNDS.min &&
    v <= FIX_BATCH_SIZE_BOUNDS.max
      ? Promise.resolve()
      : Promise.reject(new Error('须为 1–1000 的整数')),
};

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
  onSave: (values: Partial<ConfigData>) => Promise<void>;
  /** 当前项目名；项目级作用域才显示「同步用户级设置」按钮 */
  project?: string;
  /** 同步成功后回填配置（父组件 setConfig 驱动表单刷新） */
  onConfigSynced?: (config: ConfigData) => void;
  /** 「手工编辑」：跳到「项目简介」页签的 verify.yaml 编辑框（父组件负责
   *  切页签与聚焦信号；未传则不显示该按钮） */
  onManualEdit?: () => void;
}

export default function QualityPanel({ config, onSave, project, onConfigSynced, onManualEdit }: QualityPanelProps) {
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

  useEffect(() => {
    let alive = true;
    getOcrStatus()
      .then((s) => {
        if (alive) setOcr(s);
      })
      .catch(() => {
        if (alive) setOcr({ installed: false, bin: null, version: null });
      });
    return () => {
      alive = false;
    };
  }, []);

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
    setInstalling(true);
    try {
      // 1) 安装调用（code-review item 52c15fcd9bc1）：必须先检查 res.ok——
      // 旧实现不看返回值，ok===false/version===null 时仍提示「安装成功」。
      let res;
      try {
        res = await installOcr();
      } catch (err) {
        message.error(`安装失败：${err instanceof Error ? err.message : String(err)}`);
        return;
      }
      if (!res.ok) {
        message.error(`安装失败：${res.error || 'npm 安装未成功'}`);
        return;
      }
      message.success(
        res.version ? `open-code-review 安装成功：${res.version}` : 'open-code-review 安装成功',
      );
      // 2) 安装成功后重新探测（独立 try）：探测失败不应把已成功的安装误报为失败、
      // 也不应让 ocr 停在 stale（否则开关永久置灰）。
      try {
        const fresh = await getOcrStatus();
        setOcr(fresh);
      } catch {
        // 探测失败：乐观标记为已安装（版本未知），至少解锁开关
        setOcr({ installed: true, bin: null, version: res.version ?? null });
      }
    } finally {
      installInFlight.current = false;
      setInstalling(false);
    }
  };

  // 「AI 自动生成」：同步生成 regression 段（后端 HTTP 线程内 headless claude
  // 起草 + 自证 + 落位 verify.yaml，返回即终态；约数分钟，按钮 loading 覆盖全程）
  const handleRegressionAutodraft = async () => {
    if (!project || regressionDraftInFlight.current) return;
    // 在途态（后端单飞锁，经 config 端点带回）：切页签卸载重建后本地 loading
    // 丢失的场景由它恢复；此时直接提示，不发无效请求（后端 409 兜底仍在）
    if (regressionCfg?.autodraft_in_flight) {
      message.info('AI 生成正在进行中，请稍候（切换页签不影响后台生成）');
      return;
    }
    regressionDraftInFlight.current = true;
    setRegressionDrafting(true);
    try {
      const res = await autodraftRegression(project);
      if (res.ok) {
        if (res.status === 'success') {
          message.success(res.message || '已生成 regression 段并写入 verify.yaml');
        } else {
          message.info(res.message || 'regression 段已配置，无需生成');
        }
        // 终态后重拉配置状态：success 时卡片从「缺失提示」切到已配置展示；
        // no_test_system 时幂等重拉（结果不变，无害）
        getRegressionConfig(project)
          .then((d) => {
            // 项目切换守卫（code-review item e884e5a8a3af）：重拉 resolve 时
            // 用户可能已切换项目（projectRef 已更新、闭包 project 未变），
            // 只回填仍是当前项目的响应
            if (projectRef.current === project) setRegressionCfg(d);
          })
          .catch(() => {
            /* 重拉失败不打断成功结论：下次进入页面 effect 会重拉 */
          });
      } else {
        message.error(res.error || 'AI 生成失败');
      }
    } catch (err) {
      message.error(`AI 生成失败：${err instanceof Error ? err.message : String(err)}`);
    } finally {
      regressionDraftInFlight.current = false;
      setRegressionDrafting(false);
    }
  };

  // 环境门控：ocr 未安装（或探测失败）时阻止「开启」——避免开启一个运行期必然
  // 降级跳过的开关。探测未返回（加载中）时对关闭态同样置灰，避免先开后关的
  // 闪变；已开启的 gate 不禁用，保证关闭路径始终可用（见上方 useWatch 注释）。
  const ocrReady = ocr?.installed === true;

  // ocr 环境状态行（code-review item 2f3f9bd1b013）：旧实现嵌套三元违反前端
  // 规则，抽 helper 以 if/else 表达「加载中 / 已装 / 未装」三分支。
  const renderOcrStatus = () => {
    if (ocr === null) {
      return <Text type="secondary">正在检测 open-code-review 环境…</Text>;
    }
    if (ocr.installed) {
      return (
        <Alert
          type="success"
          showIcon
          message="已安装 open-code-review"
          description={ocr.version || ocr.bin || '检测到 ocr 可执行文件'}
          // 下边距与卡片 body 上内边距（24px）对齐：Alert 自身无默认外边距，
          // 否则它会紧贴下方开关行，视觉上「上松下紧」。
          style={{ marginBottom: 24 }}
          data-testid="ocr-installed-alert"
        />
      );
    }
    return (
      <Alert
        type="warning"
        showIcon
        message="未检测到 open-code-review"
        description="代码质量审查依赖 ocr（@alibaba-group/open-code-review）。未安装时该开关不可开启，运行期也会按 unavailable 降级跳过。"
        action={
          <Button
            type="primary"
            size="small"
            loading={installing}
            onClick={handleInstall}
            data-testid="ocr-install-btn"
          >
            一键安装
          </Button>
        }
        data-testid="ocr-missing-alert"
      />
    );
  };

  return (
    <div>
      <h3>代码质量</h3>
      <Text type="secondary">实现阶段的代码质量门相关设置。</Text>
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
              收尾代码质量审查
              <span className="label-note">（verify.impl_code_review）</span>
            </span>
          </div>
          {!ocrReady && ocr !== null && (
            <Text type="warning" style={{ display: 'block', marginBottom: 8 }}>
              请先安装 open-code-review 后再开启此项。
            </Text>
          )}
          <Text type="secondary">
            开启后实现者会在全部 tasks.md 任务完成、提交之后、写结果文件之前调用
            ocr（bin/ocr_review.py）scan 全文件扫描本次改动，逐条评估发现并自行修正
            真实问题（误报可驳回）。需要环境已安装 ocr，未安装时自动按 unavailable
            降级跳过。
          </Text>

          {/* add-impl-code-review-tuning：三运行参数编辑控件（超时秒 / 并发 / 力度）。
              与 ocr 参数对应：timeout_sec 写入 run 级 ocr provider 配置（确定性生效）；
              --concurrency / --effort 经提示词命令示例承载（软约束，实现者须照抄命令串）。
              缺省回填 600 / 4 / low（后端 read_config / read_effective_config 恒回显缺省）。 */}
          <Form.Item
            name="impl_code_review_timeout_sec"
            label={
              <>
                审查超时<span className="label-note">（verify.impl_code_review_timeout_sec）</span>
              </>
            }
            rules={[POSITIVE_INT_RULE]}
            style={{ marginTop: 24 }}
          >
            <InputNumber
              min={1}
              precision={0}
              style={{ width: '100%' }}
              addonAfter="秒"
              data-testid="impl-code-review-timeout"
            />
          </Form.Item>
          <Text type="secondary">
            默认 {IMPL_REVIEW_DEFAULTS.timeoutSec}。ocr LLM 单请求超时（秒，含等待响应头）：不配置时 ocr 走其内置
            300s 默认，实测 8 路并发 + 300s 单请求超时会撞穿首字节等待导致大面积
            文件级 timeout。写入 run 级 ocr 配置（custom_providers.fenix-impl.timeout_sec），
            确定性生效。
          </Text>

          <Form.Item
            name="impl_code_review_concurrency"
            label={
              <>
                SPEC 审查并发<span className="label-note">（verify.impl_code_review_concurrency）</span>
              </>
            }
            rules={[POSITIVE_INT_RULE]}
            style={{ marginTop: 24 }}
          >
            <InputNumber
              min={1}
              precision={0}
              style={{ width: '100%' }}
              addonAfter="个"
              data-testid="impl-code-review-concurrency"
            />
          </Form.Item>
          <Text type="secondary">
            默认 {IMPL_REVIEW_DEFAULTS.concurrency}。SPEC/implement 任务内收尾审查的 ocr 并发子任务上限
            （--concurrency）：实测 8 路并发同时打同一 provider 网关会把首字节延迟放大到撞穿超时线；
            add-impl-ocr-parallel-lane 由 2 上调至 4（审查转异步车道后不再卡实现者收工，吞吐优先）。
            经提示词命令示例承载，实现者须照抄命令串才生效。
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
                全仓审查并发<span className="label-note">（verify.repo_code_review_concurrency）</span>
              </>
            }
            rules={[POSITIVE_INT_RULE]}
            style={{ marginTop: 24 }}
          >
            <InputNumber
              min={1}
              precision={0}
              style={{ width: '100%' }}
              addonAfter="个"
              data-testid="repo-code-review-concurrency"
            />
          </Form.Item>
          <Text type="secondary">
            默认 {REPO_REVIEW_DEFAULT_CONCURRENCY}。全仓审查（周期执行 + 手动全仓/窗口按钮）的并行审查度：
            同时在飞的审查子代理数上限与 ocr scan --concurrency 同键注入。两处并发源
            同时打同一 provider 账号，超限会放大 429 限流（2026-09-24 事故成因之一）。
          </Text>

          <Form.Item
            name="impl_code_review_effort"
            label={
              <>
                审查力度<span className="label-note">（verify.impl_code_review_effort）</span>
              </>
            }
            rules={[EFFORT_RULE]}
            style={{ marginTop: 24 }}
          >
            <Select data-testid="impl-code-review-effort">
              {EFFORT_OPTIONS.map((opt) => (
                <Select.Option key={opt} value={opt}>
                  {opt}
                </Select.Option>
              ))}
            </Select>
          </Form.Item>
          <Text type="secondary">
            默认 {IMPL_REVIEW_DEFAULTS.effort}。ocr 审查力度预设（--effort）：low 更快更省但 recall 偏低
            （precision 优先的刻意取舍），medium 为 ocr 官方默认，high 深度审查。
            经提示词命令示例承载，实现者须照抄命令串才生效。
          </Text>

          {/* add-impl-ocr-parallel-lane：join 双档模式选择（gate/advisory）。
              车道在实现分支合并后异步跑 ocr，tester 判定 verified 时 join 裁决：
              gate 档非 rejected findings 打回修复轮（上限 1 轮，超限转台账）；
              advisory 档 findings 一律写 code-review 台账、join 永不打回。 */}
          <Form.Item
            name="impl_code_review_mode"
            label={
              <>
                车道裁决模式<span className="label-note">（verify.impl_code_review_mode）</span>
              </>
            }
            rules={[MODE_RULE]}
            style={{ marginTop: 24 }}
          >
            <Select data-testid="impl-code-review-mode">
              <Select.Option value="gate">gate（打回修复）</Select.Option>
              <Select.Option value="advisory">advisory（仅台账）</Select.Option>
            </Select>
          </Form.Item>
          <Text type="secondary">
            默认 {QUALITY_DEFAULTS.mode}。实现分支合并后异步 ocr 车道的发现如何参与验证收口：gate
            档发现非 rejected findings 时把 spec 打回修复轮（最多 1 轮，超限全部
            转 code-review 台账后放行）；advisory 档 findings 只写台账、永不打回。
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
              周期性代码审查
              <span className="label-note">（admin.code_review.enabled）</span>
            </span>
          </div>
          <Text type="secondary">
            开启后于每日触发时点（admin.code_review.run_at，缺省同每日自省时点）自动派发
            code-review agent，审查窗口内开发 SPEC 的产品代码质量，问题沉淀到
            .fenix/code-review/items.jsonl 台账，供项目页「代码审查」分面展示与消费。
            需要环境已安装 ocr（未安装时审查仍以 LLM 逐文件执行，仅少了扫描加速）。
            手动触发（全仓库审查 / 当期提交审查）不受本开关约束。
          </Text>

          {/* add-code-review-run-at 4.2：触发时点（admin.code_review.run_at，
              HH:MM）——与自省时点解耦（错峰避免与自省链同刻齐发触发网关限流），
              未显式配置时后端回退 admin.self_review.run_at（回显恒为生效值）。
              与 SelfReviewPanel run_at 同形态：TimePicker HH:mm。 */}
          <Form.Item
            name="code_review_run_at"
            label={
              <>
                触发时点<span className="label-note">（admin.code_review.run_at，HH:MM）</span>
              </>
            }
            style={{ marginTop: 24 }}
            data-testid="code-review-field-run_at"
          >
            <TimePicker
              data-testid="code-review-run-at"
              format="HH:mm"
              allowClear={false}
              placeholder="缺省同每日自省时点"
              style={{ width: 160 }}
            />
          </Form.Item>
          <Text type="secondary">
            缺省同每日自省时点（admin.self_review.run_at）。独立配置可与自省错峰，
            避免周期审查与自省（连带分析链）同刻齐发触发 LLM 网关限流；非法值由
            后端拒绝不落盘。
          </Text>

          {/* add-code-review-scope-config：审查范围下拉（admin.code_review.scope）。
              文案与项目页手动触发按钮（全库审查 / 当期审查）语义对齐，不引入
              第三套叫法；保存并入既有 admin.code_review 受管段（见 handleSave）。 */}
          <Form.Item
            name="code_review_scope"
            label={
              <>
                审查范围<span className="label-note">（admin.code_review.scope）</span>
              </>
            }
            style={{ marginTop: 24 }}
          >
            <Select data-testid="code-review-scope">
              <Select.Option value="window">当期审查（window）</Select.Option>
              <Select.Option value="full">全库审查（full）</Select.Option>
            </Select>
          </Form.Item>
          <Text type="secondary">
            默认当期审查（{QUALITY_DEFAULTS.scope}）：只审窗口内变更的文件（窗口
            起点优先审查自身水位，缺省回退自省，add-code-review-run-at）。全库审查（full）与
            项目页「全库审查」按钮同语义，审查全仓受控源码文件，同样受
            admin.code_review.max_files 上限约束（超限截断）；两档共用同一套
            调度守卫（同自然日防重 / run_at / 开关）。
          </Text>

          {/* add-code-review-sharded-out 3.3：停滞告警阈值输入（分钟粒度、
              正整数校验，保存并入既有 admin.code_review 受管段写路径）。
              与 code_review_fix_batch_size 同形态：整宽 + addonAfter 单位。 */}
          <Form.Item
            name="code_review_stall_alert_minutes"
            label={
              <>
                停滞告警阈值
                <span className="label-note">（admin.code_review.stall_alert_minutes）</span>
              </>
            }
            rules={[POSITIVE_INT_RULE]}
            style={{ marginTop: 24 }}
          >
            <InputNumber
              data-testid="code-review-stall-alert-minutes"
              min={1}
              precision={0}
              addonAfter="分钟"
              style={{ width: '100%' }}
            />
          </Form.Item>
          <Text type="secondary">
            审查 run 进行中，若主产物与分片聚合进度（done）持续为零且已运行
            超过本阈值（分钟），框架落一条人工告警提示「疑似子代理等待收工
            模式」（单 run 至多一条）。缺省 {QUALITY_DEFAULTS.stallAlertMinutes}；非法值回退{' '}
            {QUALITY_DEFAULTS.stallAlertMinutes}。
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
              自动修复代码问题
              <span className="label-note">（admin.code_review_fix.enabled）</span>
            </span>
          </div>
          <Text type="secondary">
            开启后把审查台账 open 条目按批（每批 batch_size 条，缺省{' '}
            {QUALITY_DEFAULTS.fixBatchSize}）派
            code-fix agent 在独立 worktree 内修复并提交，每批必过全量回归
            （verify.yaml regression 段）才合回主树并把条目置 resolved；回归
            未通过自动重试一次，仍失败则保留现场待人工。无有效 regression 段时
            fail-closed 不合回。关闭（缺省）= 全链路零动作。进度见项目页
            「代码审查」分面。
          </Text>
          {/* 批大小与「审查超时/并发」同形态：整宽 + addonAfter 单位。旧实现
              maxWidth:240 会把 inline-flex label 里的裸文本节点压到 min-content
              （一字一行竖排，机制见 global.less 移动端 label 修复注释）。 */}
          <Form.Item
            name="code_review_fix_batch_size"
            label={
              <>
                每批条目数
                <span className="label-note">（admin.code_review_fix.batch_size）</span>
              </>
            }
            rules={[BATCH_SIZE_RULE]}
            style={{ marginTop: 24 }}
          >
            <InputNumber
              min={FIX_BATCH_SIZE_BOUNDS.min}
              max={FIX_BATCH_SIZE_BOUNDS.max}
              precision={0}
              style={{ width: '100%' }}
              addonAfter="条"
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
              非末批定向回归
              <span className="label-note">
                （admin.code_review_fix.targeted_regression）
              </span>
            </span>
          </div>
          <Text type="secondary">
            开启（缺省）后，自动修复链内非末批的批收尾回归按本批触碰面定向：
            项目 verify.yaml 的 regression.cmd 写 {'{test_targets}'} 占位符时，
            框架按本批改动文件映射测试路径注入执行（cmd 未声明占位符或映射为空
            时自动回退全量回归）；链内末批恒走全量回归兜底。关闭后全部批次均走
            全量回归。
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
              按严重度分级修复
              <span className="label-note">
                （admin.code_review_fix.severity_batch_gate_enabled）
              </span>
            </span>
          </div>
          <Text type="secondary">
            关闭（缺省）：当天发现的所有审查条目当天进入修复批，不按严重度
            挂起。开启后：severity 达到下方门限的条目保持当日批，低于门限的
            延后挂起、距首挂起锚达周批节奏天数后整组放行统一修复。
          </Text>
          <Form.Item
            name="code_review_fix_min_severity"
            label={
              <>
                立即修复门限
                <span className="label-note">
                  （admin.code_review_fix.min_immediate_severity）
                </span>
              </>
            }
            rules={[
              {
                validator: (_: unknown, v: string | undefined | null) =>
                  v && (SEVERITY_OPTIONS as readonly string[]).includes(v)
                    ? Promise.resolve()
                    : Promise.reject(new Error('须为 critical/major/minor/info')),
              },
            ]}
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
                周批节奏
                <span className="label-note">
                  （admin.code_review_fix.minor_batch_cadence）
                </span>
              </>
            }
            rules={[
              {
                validator: (_: unknown, v: number | undefined | null) =>
                  typeof v === 'number' && Number.isInteger(v) && v >= 1 && v <= 90
                    ? Promise.resolve()
                    : Promise.reject(new Error('须为 1–90 的整数（天）')),
              },
            ]}
          >
            <InputNumber
              min={1}
              max={90}
              precision={0}
              style={{ width: '100%' }}
              addonAfter="天"
              disabled={!severityGateOn}
              data-testid="code-review-fix-minor-cadence"
            />
          </Form.Item>
        </Card>
        {/* 回归测试：标题与说明置于卡片外，与上方「代码质量」节同构 */}
        <h3 style={{ marginTop: 32 }}>回归测试</h3>
        <Text type="secondary">周期性全量回归的执行相关设置。</Text>
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
                周期性全量回归
                <span className="label-note">（admin.regression.enabled）</span>
              </span>
            </div>
            <Text type="secondary" style={{ display: 'block', marginTop: 8 }}>
              开启后与每日自省同周期（admin.self_review.run_at 时点）自动执行一次
              全量回归（需项目 .fenix/verify.yaml 配置 regression 段），结果落到
              .fenix/regression/last-run.json，供项目页「测试回归」分面展示。
              同一自然日防重；与 implementer 收尾的全量套件互斥（主机级锁）。
              手动触发（项目页「立即执行全量回归」）不受本开关约束。
            </Text>
            <Text type="secondary" style={{ display: 'block', marginTop: 8 }}>
              长耗时用例阈值来自 verify.yaml 的 regression.long_test_threshold_seconds
              （缺省 {DEFAULT_LONG_TEST_THRESHOLD_SECONDS} 秒），属项目测试体系声明——请在「项目简介」面板的
              verify.yaml 编辑入口中调整，本卡片不提供第二个写入路径。
            </Text>

            {/* 项目作用域专属：verify.yaml regression 段配置状态（只读）+ AI 补段。
                用户级作用域不显示（verify.yaml 是项目级文件）。
                判定走后端 load_verify_contract（前端无 yaml 解析库，正则判段不可靠）。 */}
            {project && (
              <div style={{ marginTop: 16 }} data-testid="regression-config-section">
                {regressionCfgError ? (
                  <Alert
                    type="error"
                    showIcon
                    message="读取 verify.yaml regression 段失败"
                    description={regressionCfgError}
                  />
                ) : regressionCfg === null ? (
                  <Text type="secondary">正在读取 verify.yaml 的 regression 段…</Text>
                ) : regressionCfg.regression ? (
                  <>
                    <Text type="secondary">已配置回归段（.fenix/verify.yaml）：</Text>
                    <Descriptions size="small" column={1} bordered style={{ marginTop: 8 }}>
                      <Descriptions.Item label="执行命令">
                        <Text code>{formatCmd(regressionCfg.regression.cmd)}</Text>
                      </Descriptions.Item>
                      <Descriptions.Item label="结果文件">
                        <Text code>{regressionCfg.regression.output}</Text>
                      </Descriptions.Item>
                      <Descriptions.Item label="硬超时">
                        {regressionCfg.regression.timeout_seconds} 秒
                      </Descriptions.Item>
                      <Descriptions.Item label="长耗时阈值">
                        {regressionCfg.regression.long_test_threshold_seconds} 秒
                      </Descriptions.Item>
                    </Descriptions>
                  </>
                ) : !regressionCfg.exists ? (
                  <Alert
                    type="info"
                    showIcon
                    message="项目尚无 verify.yaml，未配置 regression 段"
                    description="开启周期性全量回归不会实际执行。点「AI 自动生成」将同步探测测试体系并起草验证契约（有测试体系时一并生成 regression 段），约数分钟；也可点「手工编辑」自行维护。"
                  />
                ) : (
                  <Alert
                    type="warning"
                    showIcon
                    message="未配置 regression 段"
                    description=".fenix/verify.yaml 存在但没有有效的 regression 段，开启周期性全量回归不会实际执行。点「AI 自动生成」同步探测测试体系后补写（不改动契约其它内容），约数分钟；也可点「手工编辑」自行维护。"
                  />
                )}
                <div style={{ marginTop: 12 }}>
                  {/* loading 双源：本地 drafting（本组件生命周期内）+ 后端单飞锁
                      在途态（切页签卸载重建后本地 state 丢失，重挂载拉 config 恢复）。
                      可选链：config 未加载完（null）时按钮先于数据渲染 */}
                  <Button
                    onClick={handleRegressionAutodraft}
                    loading={regressionDrafting || regressionCfg?.autodraft_in_flight === true}
                    data-testid="regression-autodraft-btn"
                  >
                    AI 自动生成
                  </Button>
                  {onManualEdit && (
                    <Button style={{ marginLeft: 8 }} onClick={onManualEdit} data-testid="regression-manual-edit-btn">
                      手工编辑
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
          保存
        </Button>
      </div>
    </div>
  );
}
