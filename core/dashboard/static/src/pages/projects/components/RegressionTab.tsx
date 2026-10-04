// RegressionTab.tsx — 项目页「测试回归」分面（add-test-regression-tab 5.2/5.6）
//
// 承载全量回归结果视图（add-project-detail-tabs 预留的 `regression` key）：
// - active 门控：仅在选中本分面时拉取 `GET /api/regression/result`，未选中零
//   请求（对齐 QualityTab / SessionPanel 的按需加载语义）。
// - 三态渲染（spec test-regression-view Requirement 1）：
//   1) 全绿（passed）：概览卡片（cmd 测试路径 / 用例总数 / 通过数 / 执行时间 /
//      总耗时）+ 若 long_tests 非空仍展示长耗时用例表；
//   2) 存在失败/错误/超时/长耗时：概览之下渲染结果表格（用例名 / 文件:行 /
//      耗时 / 分类：失败、错误、超时、长耗时）；
//   3) 未执行/不可解析（never_run / parse_error）：引导态（尚未执行过全量
//      回归 / 结果不可解析 + 原因），MUST NOT 报错或显示空表。
// - 「立即执行全量回归」按钮：POST /api/regression/run（手动触发不受周期开关
//   约束；周期开关配置归设置页「质量」页签，本分面只读展示 + 手动触发）。
// - 「自动修复回归问题」按钮（add-regression-auto-fix）：可用性由快照机械判定
//   （有异常用例才可用），POST /api/regression/fix 写触发信号 → daemon 消费
//   （回归快照→code-fix 台账条目→修复批），轮询 fix-result 回链反馈。
// - 「立即执行错误/长耗时回归」按钮（add-regression-issues-rerun）：POST
//   /api/regression/run-issues 写 scope=issues 信号 → daemon 消费端按最近
//   快照算 failures+long_tests 的 nodeid 并集定向重跑（无法定向时 fail-closed
//   回退全量）；快照带 run_scope=="issues" 时概览卡展示「定向子集」标识。
//
// 运行中判据（task 5.6）：以服务端快照的 `running` 字段为准（marker 新鲜度
// 判定，见 core/regression.is_regression_running），MUST NOT 仅以 POST 受理
// 时点在前端本地计时——回归可跑 1800s，跨刷新后本地态丢失会让分面回落到
// 「上次结果」。运行中轮询快照（2s），running 回落即刷新结果。
import { useCallback, useEffect, useRef, useState } from 'react';
import dayjs from 'dayjs';
import {
  App,
  Button,
  Card,
  Descriptions,
  Progress,
  Space,
  Table,
  Tag,
  Tooltip,
  Typography,
} from 'antd';
import type { ColumnsType } from 'antd/es/table';
import {
  ApiError,
  fixRegression,
  getRegressionFixResult,
  getRegressionResult,
  isTriggerResultForRequest,
  triggerRegression,
  triggerRegressionIssues,
} from '../../../services/dashboard';
import type {
  RegressionFixRunResult,
  RegressionProgress,
  RegressionResult,
} from '../../../services/dashboard';
import { useIsMobile } from '../../../hooks/useIsMobile';
// 时长格式化单源（utils/duration.ts，对齐 list.tsx/detail.tsx 既有口径）；
// 该单源空值回退为 ''，本页展示用 '—'，在调用处以 `|| '—'` 表达
import { fmtDuration } from '@/utils/duration';

interface RegressionTabProps {
  project: string;
  active: boolean;
}

/** 执行时间显示（本地时区；快照为 UTC ISO；dayjs 统一格式——code-review
 * item 409fad9381a1：toLocaleString 输出随浏览器 locale 变化，与仓库其他
 * 页面（activities 等）的 YYYY-MM-DD HH:mm:ss 口径不齐；dayjs 解析失败
 * 返回 Invalid Date 而非抛异常，isValid 显式判后回退原文）。 */
function fmtExecTime(iso?: string) {
  if (!iso) return '—';
  const d = dayjs(iso);
  return d.isValid() ? d.format('YYYY-MM-DD HH:mm:ss') : iso;
}

// ── 分类 Tag：失败 / 错误 / 超时 / 长耗时（spec 三态渲染表列的「分类」）──
const KIND_COLOR: Record<string, string> = {
  failure: 'red',
  error: 'volcano',
  timeout: 'purple',
  long: 'gold',
};
// 分类中文文案单源（桌面结果表「分类」列与移动端堆叠卡共用）
const KIND_LABEL: Record<string, string> = {
  failure: '失败',
  error: '错误',
  timeout: '超时',
  long: '长耗时',
};

// ── 概览状态 Tag：颜色/文案查找表（code-review item a22a55ff970a：嵌套
// 三元违反项目风格规则，改查找表单源；failed 与未知态缺省 = 红 / 存在失败）──
const STATUS_TAG_COLOR: Record<string, string> = {
  passed: 'green',
  timeout: 'purple',
};
const STATUS_TAG_TEXT: Record<string, string> = {
  passed: '全部通过',
  timeout: '超时中止',
};

// ── 模块级命名常量（code-review item 5130098995b7）：2s 轮询（运行中与
// 等待启动两处）、结果表 pageSize、长耗时阈值展示缺省、概览卡底色原散落
// 多处硬编码——收敛命名单源，调参只改这里。
const POLL_INTERVAL_MS = 2000;
const RESULT_PAGE_SIZE = 10;
// ── 自动修复回链轮询（add-regression-auto-fix 4.2）：受理后 1s 间隔轮询
// fix-result（request_created 回链守卫 + 命中即停），上限 30s——超限提示
// daemon 未响应并恢复按钮（对齐 QualityTab getCodeFixRunResult 既有范式）。
const FIX_POLL_INTERVAL_MS = 1000;
const FIX_POLL_LIMIT_MS = 30_000;
// 快照缺失时的展示回退，与后端 RegressionSpec.long_test_threshold_seconds
// 缺省口径一致（改动须与 core/verify_contract.py 同步）
const DEFAULT_LONG_TEST_THRESHOLD_SECONDS = 8;
const OVERVIEW_CARD_BACKGROUND = '#fafafa';

// ── 触发按钮文案（code-review item c543cbb4b22b）：parse_error 与主分枝
// 各自复制的同一嵌套三元收敛为纯函数单源，增改状态只改这里；顺带消除
// 嵌套三元（同 a22a55ff970a 的项目风格结论）。
function triggerBtnLabel(running: boolean, awaitingStart: boolean): string {
  if (running) return '回归进行中…';
  if (awaitingStart) return '等待启动…';
  return '立即执行全量回归';
}

// ── 定向子集触发（add-regression-issues-rerun 5.2）────────────────────
// 按钮文案 / Tooltip 单源（spec：primary 蓝底白字，位于全量按钮左侧；
// 回退行为在 Tooltip 预告，映射失败静默感由消费端 warning 留痕兜底）。
export const ISSUES_BTN_TEXT = '立即执行错误/长耗时回归';
export const ISSUES_BTN_TOOLTIP = '只重跑失败/错误/长耗时的用例；无法定向时自动回退全量';
export const ISSUES_BTN_DISABLED_TOOLTIP = '无异常用例可重跑';
export const SUBSET_TAG_TEXT = '定向子集';

/** 定向子集按钮可用性机械判定（spec 口径）：快照 failures 或 long_tests
 * 非空（结果表存在可重跑行；「整体超时」伪行非用例、不计入——与
 * fixAvailable 的 timeout 分支刻意不同口径，超时无可重跑的具体用例）。 */
export function issuesAvailable(snapshot: RegressionResult | null | undefined): boolean {
  return (
    (snapshot?.failures?.length ?? 0) > 0 ||
    (snapshot?.long_tests?.length ?? 0) > 0
  );
}

/** 子集快照判定：run_scope == "issues"（仅子集改写实际生效时后端 stamp）。 */
export function isSubsetSnapshot(snapshot: RegressionResult | null | undefined): boolean {
  return snapshot?.run_scope === 'issues';
}

/** 子集快照口径说明（概览卡「定向子集」Tag 旁 secondary 文案；非子集快照
 * 返回空串不渲染——防子集计数被误读为全量，spec Scenario「子集快照标识」）。 */
export function subsetScopeNote(snapshot: RegressionResult | null | undefined): string {
  return isSubsetSnapshot(snapshot)
    ? '本快照为定向子集回归结果：用例总数/通过数按子集口径（只重跑失败/错误/长耗时用例），再执行一次全量回归即恢复全量口径。'
    : '';
}

/** 概览卡状态行（非运行中分支，add-regression-issues-rerun 5.2 抽为纯渲染
 * 单元，供前端测试断言「定向子集」标识）：状态 Tag + 子集快照 Tag。 */
export function statusTagRow(snapshot: RegressionResult | null) {
  const status = snapshot?.status ?? 'never_run';
  return (
    <Space size={8}>
      <Tag color={STATUS_TAG_COLOR[status] ?? 'red'}>
        {STATUS_TAG_TEXT[status] ?? '存在失败'}
      </Tag>
      {isSubsetSnapshot(snapshot) ? <Tag color="blue">{SUBSET_TAG_TEXT}</Tag> : null}
    </Space>
  );
}

/** 概览卡按钮行（add-regression-issues-rerun 5.2 抽为纯渲染单元，供前端
 * 测试以元素树断言形态与接线）：自动修复 → 定向子集（primary）→ 全量。
 * 三键禁用口径：running / awaitingStart / 任一回归动作在途（anyPending 交叉
 * 门控，code-review item 5cbfc2119f5a，对齐 QualityTab 交叉 pending 范式）全禁；
 * 定向子集另受可用性机械判定（不可用禁用，span+Tooltip 说明，对齐自动修复
 * 禁用态范式）。 */
export function overviewActions(opts: {
  snapshot: RegressionResult | null;
  running: boolean;
  awaitingStart: boolean;
  triggering: boolean;
  issuesTriggering: boolean;
  fixPending: boolean;
  onFix: () => void;
  onTriggerIssues: () => void;
  onTrigger: () => void;
}) {
  const { snapshot, running, awaitingStart } = opts;
  // 交叉 pending 门控（code-review item 5cbfc2119f5a）：任一回归动作 POST 在飞
  // （running/awaitingStart 尚未置位的受理窗口）即三键全禁，杜绝在飞窗口内
  // 并发下发两份触发信号——否则第二份只能靠后端 regression_already_running /
  // regression_request_pending 拒绝并弹 warning（对齐 QualityTab handleTrigger
  // 查 actionPending||ackPending、handleTriggerFixRun 查 fixRunPending||
  // actionPending 的既有范式）
  const anyPending = opts.triggering || opts.issuesTriggering || opts.fixPending;
  // 自动修复可用性（add-regression-auto-fix 既有口径：failures/long_tests
  // 非空或整体超时）——随按钮行一并收拢，行为与抽取前逐字节一致
  const fixAvailable =
    (snapshot?.failures?.length ?? 0) > 0 ||
    (snapshot?.long_tests?.length ?? 0) > 0 ||
    snapshot?.status === 'timeout';
  const issuesOk = issuesAvailable(snapshot);
  return (
    <div style={{ marginTop: 4, textAlign: 'right' }}>
      <Space>
        {/* 自动修复回归问题（add-regression-auto-fix）：可用性由快照机械
            判定；全绿禁用态悬停提示「无异常用例可修复」。disabled 按钮
            不触发悬停事件，按 antd 惯例外包一层 span 承载 Tooltip。 */}
        <Tooltip title={fixAvailable ? undefined : '无异常用例可修复'}>
          <span>
            <Button
              loading={opts.fixPending}
              disabled={!fixAvailable || running || awaitingStart || anyPending}
              onClick={opts.onFix}
            >
              自动修复回归问题
            </Button>
          </span>
        </Tooltip>
        {/* 定向子集回归（add-regression-issues-rerun）：primary 蓝底白字，
            位于全量按钮左侧；可用时 Tooltip 预告回退行为，不可用禁用态
            悬停提示「无异常用例可重跑」（同 span 承载范式） */}
        <Tooltip title={issuesOk ? ISSUES_BTN_TOOLTIP : ISSUES_BTN_DISABLED_TOOLTIP}>
          <span>
            <Button
              type="primary"
              loading={opts.issuesTriggering}
              disabled={!issuesOk || running || awaitingStart || anyPending}
              onClick={opts.onTriggerIssues}
            >
              {ISSUES_BTN_TEXT}
            </Button>
          </span>
        </Tooltip>
        <Button
          type="primary"
          loading={opts.triggering}
          disabled={running || awaitingStart || anyPending}
          onClick={opts.onTrigger}
        >
          {triggerBtnLabel(running, awaitingStart)}
        </Button>
      </Space>
    </div>
  );
}

// ── 运行中/等待启动进度视图 ──────────────────────────────────────────
// 三态（对齐后端 read_progress 口径）：percent 确定值 → 确定进度条
// （estimated 注明口径）；percent null（或等待 daemon 启动窗口）→
// 满条流动动画（antd active 状态）表达「进行中但进度未知」。
function RunningProgressView({
  progress,
  waiting,
}: {
  progress?: RegressionProgress | null;
  waiting?: boolean;
}) {
  const sub: string[] = [];
  if (waiting) {
    sub.push('已受理，等待 daemon 启动回归…');
  } else if (progress?.estimated) {
    sub.push('按上次总耗时估算');
  }
  if (!waiting && progress?.elapsed_seconds !== null && progress?.elapsed_seconds !== undefined) {
    sub.push(`已耗时 ${fmtDuration(progress.elapsed_seconds) || '—'}`);
  }
  return (
    <div>
      <Progress
        percent={progress?.percent ?? 100}
        showInfo={progress?.percent !== null && progress?.percent !== undefined}
        status="active"
        // 样式对齐 spec 详情页 ProgressBarTile：标准蓝绿渐变 + 默认尺寸 + 占满容器
        strokeColor={{ '0%': '#108ee9', '100%': '#87d068' }}
        // width:100% 压过 .ant-progress 的 inline 排版（否则与说明文字同行）
        style={{ width: '100%' }}
      />
      {sub.length > 0 ? (
        <Typography.Text type="secondary" style={{ fontSize: 12, display: 'block' }}>
          {sub.join(' · ')}
        </Typography.Text>
      ) : null}
    </div>
  );
}

// ── 结果表行结构单源（code-review item 7360ae15ac6c）：buildRows 返回类型、
// 函数内 rows 局部类型与组件内 ColumnsType 泛型统一引用此定义，列字段变更只改这里。
interface CaseRow {
  key: string;
  name: string;
  file: string;
  line: number;
  time: number;
  kind: string;
  message?: string;
}

/** 合并 failure/error 用例与长耗时用例为统一结果表（带分类列）。 */
function buildRows(snapshot: RegressionResult): Array<CaseRow> {
  const rows: Array<CaseRow> = [];
  for (const f of snapshot.failures ?? []) {
    rows.push({
      key: `f-${rows.length}`,
      name: f.name,
      file: f.file,
      line: f.line,
      time: f.time,
      kind: f.kind,
      message: f.message,
    });
  }
  // timeout：快照本身无独立用例表，以「整体超时」一行呈现（结果表 MUST 含
  // 超时行——spec Scenario「2 个失败用例 + 1 个超时 + 3 个长耗时用例」）。
  // file 置空串（「文件:行」列显示 —，code-review item 72c04148d4c9：旧实现
  // 把整段原始命令输出冒充 file 渲染进该列，误导）；output/reason 落概览卡
  // 的超时详情区（见下方渲染）。
  if (snapshot.status === 'timeout') {
    rows.push({
      key: `t-${rows.length}`,
      name: '（本次回归整体超时）',
      file: '',
      line: 0,
      time: snapshot.duration_seconds ?? 0,
      kind: 'timeout',
      message: snapshot.reason,
    });
  }
  // 长耗时独立于 failures（一个慢但通过的用例也在其中，design D6）
  for (const lt of snapshot.long_tests ?? []) {
    // 已在 failures 中展示的同一用例去重（名字+耗时一致判同用例）
    const dup = rows.some(
      (r) => r.kind !== 'timeout' && r.name === lt.name && r.time === lt.time,
    );
    if (dup) continue;
    rows.push({
      key: `l-${rows.length}`,
      name: lt.name,
      file: lt.file,
      line: lt.line,
      time: lt.time,
      kind: 'long',
    });
  }
  return rows;
}

export default function RegressionTab({ project, active }: RegressionTabProps) {
  const { message } = App.useApp();
  // <768 窄屏布局切换（hook 须在早退 return 之前调用）：异常用例表从
  // 「用例名/文件:行/耗时/分类」四列表格切换为单列堆叠卡——用例名与
  // 文件:行都是不可断行的长标识符，任何列宽微调都压不住表格 min-content
  // 出界（2026-09-25 移动端越界实测：整表 913px / 视口 390px）。
  const isMobile = useIsMobile();
  const [snapshot, setSnapshot] = useState<RegressionResult | null>(null);
  const [triggering, setTriggering] = useState(false);
  // 受理已提交、daemon 尚未 mark_running 的过渡态：点击受理到服务端 running
  // 置位之间有主循环消费时延，此窗口内以「等待启动」动画条给即时反馈，
  // 按钮（及重复触发）同步禁用；running 置位或 120s 超时自动退出。
  const [awaitingStart, setAwaitingStart] = useState(false);
  // 轮询止损后的可见错误态（code-review item 11f99f1d80c5）：running 轮询
  // 失败即永久停轮询（e419d82ceb2b 对请求风暴的合理止损），但本地快照仍是
  // running=true 的旧帧——主视图按 running 渲染「正在执行」、触发/修复按钮
  // 禁用，一次性 toast 消失后页面无错误痕迹也无恢复入口。止损时置位，在
  // running 渲染分支显示提示条；下一次成功快照（重进分面/切项目后的加载）
  // 即清除。
  const [pollFailed, setPollFailed] = useState(false);
  const pollTimerRef = useRef<number | null>(null);
  // 自动修复（add-regression-auto-fix）：触发在途 loading 态 + 回链轮询哨
  const [fixPending, setFixPending] = useState(false);
  const fixPollAbortedRef = useRef(false);
  // 定向子集触发（add-regression-issues-rerun）：在途 loading 态
  const [issuesTriggering, setIssuesTriggering] = useState(false);
  // 请求序号守卫（对齐 QualityTab）：轮询与手动刷新并发时较慢的早期响应
  // 不得覆盖较新数据。
  const seqRef = useRef(0);

  const loadResult = useCallback(async () => {
    if (!active || !project) return;
    const seq = ++seqRef.current;
    try {
      const data = await getRegressionResult(project);
      if (seq !== seqRef.current) return;
      setSnapshot(data);
      setPollFailed(false);
      // 运行中 → 轮询快照（2s）；回落即停止（task 5.6：以服务端 running 为准）
      if (data.running) {
        if (pollTimerRef.current === null) {
          pollTimerRef.current = window.setInterval(() => {
            void loadResultRef.current();
          }, POLL_INTERVAL_MS);
        }
      } else if (pollTimerRef.current !== null) {
        window.clearInterval(pollTimerRef.current);
        pollTimerRef.current = null;
      }
    } catch (e) {
      if (seq !== seqRef.current) return;
      // 轮询失败止损（code-review item e419d82ceb2b）：旧实现失败处不清
      // interval——持久后端错误时 running 轮询每 2s 持续打请求并重复弹同一
      // toast（请求风暴 + 刷屏）。失败即停 running 轮询并退出等待启动过渡态
      // （快照保留原值，重进分面/手动触发即恢复轮询）；等待启动窗口的
      // 120s 超时兜底因此不必等到期。
      if (pollTimerRef.current !== null) {
        window.clearInterval(pollTimerRef.current);
        pollTimerRef.current = null;
      }
      setAwaitingStart(false);
      // 止损同时置页面内可见错误态（11f99f1d80c5）：running 旧帧仍按「正在
      // 执行」渲染且按钮禁用，提示条是 toast 之外唯一的失败痕迹与恢复指引
      setPollFailed(true);
      message.error(`加载失败: ${e instanceof Error ? e.message : String(e)}`);
    }
  }, [active, project, message]);

  // 最新 loadResult 经 ref 供长生命周期 interval 调用（code-review item
  // 828b713abd5b）：running 轮询 interval 只在首次创建后跨渲染复用，回调若
  // 直接闭包捕获创建时渲染的 loadResult 会绑定当时的 project——running 期间
  // 切换项目（或 active/project 身份变化）后旧 interval 继续轮询上个项目、
  // 把其快照写进当前视图。经 ref 取最新闭包，轮询目标始终跟随当前
  // active/project。
  const loadResultRef = useRef(loadResult);
  useEffect(() => {
    loadResultRef.current = loadResult;
  }, [loadResult]);

  // 当前 project 身份哨（code-review item f538e7f059ec，与 loadResultRef 同
  // 口径）：handleFix 的回链轮询闭包捕获点击时的 project，最长 30s 轮询期间
  // 切换项目（本分面仍选中时 abort 哨不触发）后旧轮询仍打旧项目接口，其
  // 结果提示弹在当前视图会被误读为新项目的结果——经 ref 读取最新身份，
  // 变化即中止本轮轮询与提示（handler 的 finally 复位 fixPending）。
  const projectRef = useRef(project);
  useEffect(() => {
    projectRef.current = project;
  }, [project]);

  // 跨项目切换清态（code-review item 0efd50f9753f，口径同 CodeFixProgressCard
  // 1d0b747da6b2）：本组件随 Tab 常驻挂载，project 变化只重启 active 门控的
  // 加载 effect、不卸载组件，组件级 snapshot 会保留上一项目最后一次快照——
  // 新项目首个响应返回前（约一次请求往返），概览卡与结果表仍按旧项目渲染，
  // 「自动修复回归问题」按钮也按旧快照判定可用性，而此刻点击 handleFix 实际
  // 作用于新项目，提示与所见内容不一致。对 project 专门 effect 清空 snapshot
  // 与 awaitingStart，分面回落引导/加载态直至新项目数据到达。声明序在加载
  // effect 之前：project 变化时清空先于新请求响应执行，不会误清新项目刚取到
  // 的数据。
  useEffect(() => {
    setSnapshot(null);
    setAwaitingStart(false);
  }, [project]);

  // active 门控：进入分面加载，离开分面停止轮询（未选中零请求）
  useEffect(() => {
    if (!active || !project) return;
    void loadResult();
  }, [active, project, loadResult]);

  // 服务端 running 置位 → 等待启动过渡态结束（进度条接管）
  const running = snapshot?.running ?? false;
  useEffect(() => {
    if (running) setAwaitingStart(false);
  }, [running]);

  // 等待启动超时兜底：daemon 长时间未消费信号（如中途退出）不再无限等待
  useEffect(() => {
    if (!awaitingStart) return;
    const t = window.setTimeout(() => setAwaitingStart(false), 120_000);
    return () => window.clearTimeout(t);
  }, [awaitingStart]);

  // 等待启动窗口轮询：loadResult 的自轮询只在 running=true 时挂载，而受理
  // 到 daemon mark_running 之间有主循环消费时延——此窗口不轮询会让页面
  // 感知不到运行态置位（停在等待态直到超时）。2s 轮询直至 running 接管。
  useEffect(() => {
    if (!awaitingStart || !active) return;
    const t = window.setInterval(() => void loadResult(), POLL_INTERVAL_MS);
    return () => window.clearInterval(t);
  }, [awaitingStart, active, loadResult]);

  // 切离分面清理轮询
  useEffect(() => {
    if (!active) {
      if (pollTimerRef.current !== null) {
        window.clearInterval(pollTimerRef.current);
        pollTimerRef.current = null;
      }
      // 自动修复回链轮询同口径中止（handler 的 finally 复位 fixPending）
      fixPollAbortedRef.current = true;
      // 清理即作废在飞响应（code-review item 7fe09ea34122，对齐 QualityTab
      // 31c9cfb5cb4e 在清理处自增 loadSeqRef 的口径）：seqRef 只在下一次调用
      // loadResult 时自增，切离分面并不作废已发出的请求——在飞响应（尤其
      // 失败分支）晚到时 seq 仍是最新值，守卫放行，会把「加载失败」toast 与
      // pollFailed 落在用户已离开的分面上（成功分支还会写旧快照、重启轮询）。
      // 自增后切离前的在飞响应一律过期；重进分面 loadResult 重新取号，正常
      // 加载不受影响。
      seqRef.current += 1;
    }
  }, [active]);

  useEffect(() => {
    return () => {
      if (pollTimerRef.current !== null) {
        window.clearInterval(pollTimerRef.current);
        pollTimerRef.current = null;
      }
      // 自动修复回链轮询哨：卸载即中止（handleFix 轮询内逐步检查后退出）
      fixPollAbortedRef.current = true;
      // 卸载同口径作废在飞响应（7fe09ea34122）：卸载前已发出的 loadResult
      // 响应一律过期，不向已卸载组件写快照/落错误态/弹 toast
      seqRef.current += 1;
    };
  }, []);

  // ── 手动触发（spec「手动触发按钮」Scenario）──────────────────────
  const handleTrigger = async () => {
    // 交叉 pending 门控（code-review item 5cbfc2119f5a，对齐 QualityTab
    // handleTrigger 查 actionPending||ackPending 的范式）：只查本动作在途态
    // 拦不住「点全量后立刻点定向子集/自动修复」——POST 受理返回前
    // running/awaitingStart 尚未置位，任一回归动作在途即不再受理新触发
    if (triggering || issuesTriggering || fixPending) return;
    setTriggering(true);
    try {
      await triggerRegression(project);
      message.success('已受理，daemon 将开始执行全量回归');
      // 受理成功 → 等待启动过渡态（动画条即时反馈，running 置位后由
      // 真实进度接管；见 awaitingStart 注释）
      setAwaitingStart(true);
      // 触发成功立即刷新：新一轮运行中态（running=true）由服务端 marker 提供，
      // 轮询接管（task 5.6）。经 ref 调最新闭包（code-review item 7a7ce4f87987）：
      // POST 往返期间切换项目时，渲染期捕获的 loadResult 仍绑定旧 project，
      // seq 守卫拦不住「旧闭包后发先至」，旧项目快照会写进新项目视图——经
      // loadResultRef 取最新闭包，刷新目标始终跟随当前 active/project。
      void loadResultRef.current();
    } catch (e) {
      // 业务拒绝按稳定错误码分支（code-review item 934af264345f）：旧实现
      // 对后端中文消息做子串匹配，措辞/locale 改动静默落入通用错误分支。
      // 错误码由后端 _coded_error 下发、ApiError.code 承载。
      if (e instanceof ApiError && e.code === 'regression_already_running') {
        message.warning('已有回归在进行中');
        // 同 7a7ce4f87987：经 ref 取最新闭包，POST 往返期间切换项目后旧闭包
        // 后发先至，seq 守卫拦不住——刷新目标跟随当前 active/project
        void loadResultRef.current();
      } else if (e instanceof ApiError && e.code === 'regression_not_configured') {
        message.warning('该项目未配置全量回归（verify.yaml regression 段）');
      } else {
        const errMsg = e instanceof Error ? e.message : String(e);
        message.error(`触发失败: ${errMsg}`);
      }
    } finally {
      setTriggering(false);
    }
  };

  // ── 自动修复回归问题（add-regression-auto-fix 4.2）────────────────
  // 可用性由快照机械判定（有异常用例才可点）；点击写文件信号，daemon
  // 消费：读快照转换为 code-fix 台账条目并投递修复批。受理后 1s 间隔
  // 轮询判定结果（上限 30s），仅认 request_created 回链本次 requested_at
  // 的结果；触发成功指引「质量」页签既有 CodeFixProgressCard 看进展。
  const handleFix = async () => {
    // 交叉 pending 门控（同 handleTrigger，5cbfc2119f5a）：任一回归动作在途
    // 即不再受理；loading 防重复语义不变——在途时重复点击不产生第二个信号
    if (fixPending || triggering || issuesTriggering) return;
    setFixPending(true);
    fixPollAbortedRef.current = false; // 本轮请求开启新哨（上一轮取消状态作废）
    try {
      const res = await fixRegression(project);
      const wantedAt = res.requested_at;
      const deadline = Date.now() + FIX_POLL_LIMIT_MS;
      let result: RegressionFixRunResult | null = null;
      while (Date.now() < deadline) {
        // 卸载/切走后停止轮询与提示（finally 复位 pending）
        if (fixPollAbortedRef.current) return;
        // 轮询期间切换项目（f538e7f059ec）：闭包捕获的 project 仍是点击时的
        // 旧项目，其结果提示弹在当前视图会被误读为新项目的结果——身份已
        // 变化即中止本轮轮询与提示
        if (projectRef.current !== project) return;
        await new Promise((resolve) => setTimeout(resolve, FIX_POLL_INTERVAL_MS));
        if (fixPollAbortedRef.current) return;
        if (projectRef.current !== project) return;
        try {
          const snap = await getRegressionFixResult(project);
          if (isTriggerResultForRequest(snap, wantedAt)) {
            result = snap;
            break;
          }
        } catch {
          // 单轮读取失败不终止轮询（daemon 消费稍后补结果文件）
        }
      }
      if (fixPollAbortedRef.current) return;
      // 结果提示前再核对身份（f538e7f059ec）：轮询末次命中后切换项目，
      // 旧项目的成功/拒绝提示不得弹在当前（新项目）视图
      if (projectRef.current !== project) return;
      if (result) {
        if (result.triggered) {
          message.success(
            result.message || '已把回归问题转入修复台账，可在「质量」页签查看修复进展',
          );
        } else {
          // 拒绝原因（已有修复在跑/无 open 条目/回归契约缺失等）由 daemon
          // 结果文件的 message 如实回显；message 与 reason 皆缺省时兜底
          message.warning(
            result.message ||
              (result.reason ? `未能投递：${result.reason}` : '未能投递自动修复请求'),
          );
        }
      } else {
        // 轮询超限：恢复按钮（finally）并提示 daemon 未响应
        message.info('daemon 未响应，请确认 daemon 运行中');
      }
    } catch (e) {
      // 业务拒绝按稳定错误码分支（对齐既有 triggerRegression 范式，
      // code-review item 934af264345f：不做中文消息子串匹配）
      if (e instanceof ApiError && e.code === 'regression_never_run') {
        message.warning('最近一次回归快照缺失或不可解析，请先执行一次全量回归');
      } else if (e instanceof ApiError && e.code === 'regression_no_issues') {
        message.warning('最近一次回归无异常用例，无需修复');
      } else {
        const errMsg = e instanceof Error ? e.message : String(e);
        message.error(`自动修复失败: ${errMsg}`);
      }
    } finally {
      setFixPending(false);
    }
  };

  // ── 定向子集触发（add-regression-issues-rerun 5.2）────────────────
  // 受理范式对齐 handleTrigger：受理成功 → awaitingStart 过渡态 + 立即刷新
  // （轮询/进度条接管）；业务拒绝按稳定错误码分支（934af264345f），错误码
  // 面为 run-issues 端点专属五码 + 通用兜底。
  const handleTriggerIssues = async () => {
    // 交叉 pending 门控（同 handleTrigger，5cbfc2119f5a）：任一回归动作在途
    // 即不再受理，杜绝 POST 在飞窗口内并发下发两份触发信号
    if (issuesTriggering || triggering || fixPending) return;
    setIssuesTriggering(true);
    try {
      await triggerRegressionIssues(project);
      message.success('已受理，daemon 将只重跑失败/错误/长耗时的用例（无法定向时自动回退全量）');
      // 受理成功 → 等待启动过渡态（同 handleTrigger，running 置位后由真实
      // 进度接管）；经 ref 调最新闭包（7a7ce4f87987，切项目防旧闭包后发先至）
      setAwaitingStart(true);
      void loadResultRef.current();
    } catch (e) {
      if (e instanceof ApiError && e.code === 'regression_already_running') {
        message.warning('已有回归在进行中');
        void loadResultRef.current();
      } else if (e instanceof ApiError && e.code === 'regression_not_configured') {
        message.warning('该项目未配置全量回归（verify.yaml regression 段）');
      } else if (e instanceof ApiError && e.code === 'regression_never_run') {
        message.warning('最近一次回归快照缺失或不可解析，请先执行一次全量回归');
      } else if (e instanceof ApiError && e.code === 'regression_no_issues') {
        message.warning('最近一次回归无异常用例，无需定向重跑');
      } else if (e instanceof ApiError && e.code === 'regression_request_pending') {
        message.warning('已有未消费的回归触发请求（请稍后重试）');
      } else {
        const errMsg = e instanceof Error ? e.message : String(e);
        message.error(`触发失败: ${errMsg}`);
      }
    } finally {
      setIssuesTriggering(false);
    }
  };

  if (!active) return null;

  const status = snapshot?.status ?? 'never_run';

  // 轮询止损提示条（code-review item 11f99f1d80c5）：仅在 running 渲染分支
  // 显示——快照是 running 旧帧时触发/修复按钮均被禁用，此条是页面内唯一的
  // 失败痕迹与恢复指引；下一次成功快照使 running 回落后随之消失。
  const pollFailBanner =
    running && pollFailed ? (
      <Typography.Text type="danger" style={{ fontSize: 12 }}>
        进度读取失败，已停止自动刷新，可切出重进刷新
      </Typography.Text>
    ) : null;

  // ── 三态渲染（spec Requirement 1）─────────────────────────────
  // 状态机：
  //   never_run / parse_error（无有效结果）→ 引导态；
  //   其余（passed/failed/timeout，含 running 期间沿用旧快照）→ 概览 + 结果表。
  if (status === 'never_run') {
    return (
      <Card variant="borderless">
        <Space direction="vertical" style={{ width: '100%' }} size={16}>
          {running ? (
            <>
              <Typography.Text strong>全量回归正在执行中…</Typography.Text>
              <RunningProgressView progress={snapshot?.progress} />
              {pollFailBanner}
              <Typography.Text type="secondary">
                回归完成后此分面将展示结果。回归可运行较长时间，请稍候。
              </Typography.Text>
            </>
          ) : (
            <>
              <Typography.Text strong>尚未执行过全量回归</Typography.Text>
              <Typography.Text type="secondary">
                全量回归执行方式由项目 .fenix/verify.yaml 的 regression 段声明
                （cmd / output / 硬超时 / 长耗时阈值）。未配置时可在项目设置中编辑
                verify.yaml；配置完成后点击下方按钮手动触发一次。
              </Typography.Text>
              {awaitingStart ? <RunningProgressView waiting /> : null}
              <div style={{ textAlign: 'right' }}>
                {/* 交叉 pending 门控（code-review item f80503ee8385）：任一回归
                    动作在飞即禁用，对齐 overviewActions 三键 anyPending 与
                    handleTrigger 守卫口径，避免点击被守卫静默吞掉无反馈 */}
                <Button
                  type="primary"
                  loading={triggering}
                  disabled={awaitingStart || fixPending || issuesTriggering}
                  onClick={() => void handleTrigger()}
                >
                  {triggerBtnLabel(false, awaitingStart)}
                </Button>
              </div>
            </>
          )}
        </Space>
      </Card>
    );
  }

  if (status === 'parse_error') {
    return (
      <Card variant="borderless">
        <Space direction="vertical" style={{ width: '100%' }} size={16}>
          <Typography.Text strong>回归结果不可解析</Typography.Text>
          <Typography.Text type="secondary">
            {snapshot?.reason || 'JUnit XML 缺失或不可解析'}
          </Typography.Text>
          {running ? <RunningProgressView progress={snapshot?.progress} /> : null}
          {pollFailBanner}
          {awaitingStart ? <RunningProgressView waiting /> : null}
          <div style={{ textAlign: 'right' }}>
            {/* 交叉 pending 门控（code-review item f80503ee8385）：任一回归
                动作在飞即禁用，对齐 overviewActions 三键 anyPending 与
                handleTrigger 守卫口径，避免点击被守卫静默吞掉无反馈 */}
            <Button
              type="primary"
              loading={triggering}
              disabled={running || awaitingStart || fixPending || issuesTriggering}
              onClick={() => void handleTrigger()}
            >
              {triggerBtnLabel(running, awaitingStart)}
            </Button>
          </div>
        </Space>
      </Card>
    );
  }

  // 全绿 / 失败 / 超时：概览卡片 + （异常时）结果表
  const hasIssues =
    status !== 'passed' ||
    (snapshot?.failures?.length ?? 0) > 0 ||
    (snapshot?.long_tests?.length ?? 0) > 0;

  // 按钮行（自动修复/定向子集/全量）收拢在 overviewActions 纯渲染单元
  // （add-regression-issues-rerun 5.2）：可用性判定随行内聚，组件内不再
  // 重复展开

  const columns: ColumnsType<CaseRow> = isMobile
    ? [
        // <768 窄屏：单列堆叠卡——用例名（换行）、文件:行（换行）、分类 Tag +
        // 耗时同行。表格布局机制（tableLayout=fixed + 100% 宽）不变，四列
        // 内容的 min-content 出界问题随「改为堆叠」消除；分页/空态/行键
        // 仍由同一张 Table 承载。
        {
          title: '异常用例',
          key: 'case',
          render: (_: unknown, rec) => (
            <Space direction="vertical" size={4} style={{ width: '100%' }}>
              <Typography.Text style={{ wordBreak: 'break-all' }}>{rec.name}</Typography.Text>
              {rec.file ? (
                <Typography.Text code type="secondary" style={{ fontSize: 12, wordBreak: 'break-all' }}>
                  {rec.line > 0 ? `${rec.file}:${rec.line}` : rec.file}
                </Typography.Text>
              ) : null}
              <Space size={8}>
                <Tag color={KIND_COLOR[rec.kind] || 'default'} style={{ marginInlineEnd: 0 }}>
                  {KIND_LABEL[rec.kind] || rec.kind}
                </Tag>
                <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                  {rec.time !== null && rec.time !== undefined ? `${rec.time}s` : '—'}
                </Typography.Text>
              </Space>
            </Space>
          ),
        },
      ]
    : [
        {
          title: '用例名',
          dataIndex: 'name',
          key: 'name',
          ellipsis: true,
        },
        {
          title: '文件:行',
          key: 'loc',
          // 用例名列过宽：文件:行固定占表宽 30%（配 tableLayout=fixed，用例名吃剩余）
          width: '30%',
          render: (_: unknown, rec) => {
            if (!rec.file) return '—';
            const loc = rec.line > 0 ? `${rec.file}:${rec.line}` : rec.file;
            return (
              <Typography.Text code style={{ fontSize: 12 }} ellipsis={{ tooltip: loc }}>
                {loc}
              </Typography.Text>
            );
          },
        },
        {
          title: '耗时',
          dataIndex: 'time',
          key: 'time',
          width: 100,
          // 显式判空（code-review item 30024ba4279f）：项目 lint 禁止宽松相等
          render: (t: number) =>
            t !== null && t !== undefined ? `${t}s` : '—',
        },
        {
          title: '分类',
          dataIndex: 'kind',
          key: 'kind',
          width: 100,
          render: (kind: string) => (
            <Tag color={KIND_COLOR[kind] || 'default'}>{KIND_LABEL[kind] || kind}</Tag>
          ),
        },
      ];

  const rows = buildRows(snapshot!);

  return (
    <Card variant="borderless">
      {/* 概览卡片（spec「全绿概览」Scenario）：测试路径 / 用例总数 / 通过数 /
          执行时间 / 总耗时 */}
      <Card size="small" style={{ marginBottom: 12, background: OVERVIEW_CARD_BACKGROUND }}>
        <Space direction="vertical" size={8} style={{ width: '100%' }}>
          {running ? (
            <Space direction="vertical" size={4} style={{ width: '100%' }}>
              <Space>
                <Tag color="processing">运行中</Tag>
                <Typography.Text strong>全量回归正在执行…</Typography.Text>
              </Space>
              <RunningProgressView progress={snapshot?.progress} />
              {pollFailBanner}
            </Space>
          ) : (
            statusTagRow(snapshot)
          )}
          {/* 子集快照口径说明：防子集计数被误读为全量（用例总数按子集口径，
              单快照覆盖语义，再跑全量即恢复） */}
          {subsetScopeNote(snapshot) ? (
            <Typography.Text type="secondary" style={{ fontSize: 12 }}>
              {subsetScopeNote(snapshot)}
            </Typography.Text>
          ) : null}
          <Descriptions
            className="regression-overview-desc"
            size="small"
            column={{ xs: 1, sm: 2, md: 3 }}
            items={[
              {
                key: 'cmd',
                label: '测试路径',
                children: (
                  <Typography.Text code style={{ fontSize: 12 }} ellipsis={{ tooltip: snapshot?.cmd }}>
                    {snapshot?.cmd || '—'}
                  </Typography.Text>
                ),
              },
              {
                key: 'total',
                label: '用例总数',
                children: `${snapshot?.total ?? 0}`,
              },
              {
                key: 'passed',
                label: '通过数',
                children: `${snapshot?.passed ?? 0}`,
              },
              {
                key: 'failed',
                label: '失败/错误',
                children: `${(snapshot?.failed ?? 0) + (snapshot?.errors ?? 0)}`,
              },
              {
                key: 'skipped',
                label: '跳过',
                children: `${snapshot?.skipped ?? 0}`,
              },
              {
                key: 'time',
                label: '执行时间',
                children: fmtExecTime(snapshot?.started_at),
              },
              {
                key: 'duration',
                label: '总耗时',
                children: fmtDuration(snapshot?.duration_seconds) || '—',
              },
              {
                key: 'threshold',
                label: '长耗时阈值',
                children: `${snapshot?.long_test_threshold_seconds ?? DEFAULT_LONG_TEST_THRESHOLD_SECONDS}s`,
              },
            ]}
          />
          {status === 'timeout' && snapshot?.reason ? (
            <Typography.Text type="secondary" style={{ fontSize: 12 }}>
              原因：{snapshot.reason}
            </Typography.Text>
          ) : null}
          {/* 超时详情区（code-review item 72c04148d4c9）：原始命令输出不再冒充
              结果表的「文件:行」值，落此独立展示（默认折叠 4 行可展开） */}
          {status === 'timeout' && snapshot?.output ? (
            <Typography.Paragraph
              type="secondary"
              style={{ fontSize: 12, marginBottom: 0, whiteSpace: 'pre-wrap' }}
              ellipsis={{ rows: 4, expandable: true, symbol: '展开' }}
            >
              {`输出：${snapshot.output}`}
            </Typography.Paragraph>
          ) : null}
          {awaitingStart && !running ? <RunningProgressView waiting /> : null}
          {overviewActions({
            snapshot,
            running,
            awaitingStart,
            triggering,
            issuesTriggering,
            fixPending,
            onFix: () => void handleFix(),
            onTriggerIssues: () => void handleTriggerIssues(),
            onTrigger: () => void handleTrigger(),
          })}
        </Space>
      </Card>

      {/* 异常态结果表（spec「失败/超时/长耗时用例表」Scenario）：概览之下列出
          失败/错误/超时/长耗时用例；全绿且无长耗时用例时不渲染表格 */}
      {hasIssues && rows.length > 0 ? (
        <Table
          className="regression-result-table"
          rowKey="key"
          dataSource={rows}
          columns={columns}
          tableLayout="fixed"
          size="small"
          pagination={{
            pageSize: RESULT_PAGE_SIZE,
            showSizeChanger: false,
            hideOnSinglePage: true,
          }}
          locale={{ emptyText: '无异常用例' }}
        />
      ) : null}
    </Card>
  );
}
