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
  triggerRegression,
} from '../../../services/dashboard';
import type {
  RegressionFixRunResult,
  RegressionProgress,
  RegressionResult,
} from '../../../services/dashboard';
import { useIsMobile } from '../../../hooks/useIsMobile';

interface RegressionTabProps {
  project: string;
  active: boolean;
}

function fmtDuration(sec?: number | null) {
  // 显式判空（code-review item 30024ba4279f）：项目 lint 禁止宽松相等
  if (sec === null || sec === undefined || Number.isNaN(sec)) return '—';
  const s = Math.max(0, Math.round(sec));
  if (s < 60) return `${s}秒`;
  const m = Math.floor(s / 60);
  const rest = s % 60;
  if (m < 60) return rest ? `${m}分${rest}秒` : `${m}分`;
  return `${Math.floor(m / 60)}时${m % 60}分${rest ? `${rest}秒` : ''}`;
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
    sub.push(`已耗时 ${fmtDuration(progress.elapsed_seconds)}`);
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
  const pollTimerRef = useRef<number | null>(null);
  // 自动修复（add-regression-auto-fix）：触发在途 loading 态 + 回链轮询哨
  const [fixPending, setFixPending] = useState(false);
  const fixPollAbortedRef = useRef(false);
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
    };
  }, []);

  // ── 手动触发（spec「手动触发按钮」Scenario）──────────────────────
  const handleTrigger = async () => {
    if (triggering) return;
    setTriggering(true);
    try {
      await triggerRegression(project);
      message.success('已受理，daemon 将开始执行全量回归');
      // 受理成功 → 等待启动过渡态（动画条即时反馈，running 置位后由
      // 真实进度接管；见 awaitingStart 注释）
      setAwaitingStart(true);
      // 触发成功立即刷新：新一轮运行中态（running=true）由服务端 marker 提供，
      // 轮询接管（task 5.6）
      void loadResult();
    } catch (e) {
      // 业务拒绝按稳定错误码分支（code-review item 934af264345f）：旧实现
      // 对后端中文消息做子串匹配，措辞/locale 改动静默落入通用错误分支。
      // 错误码由后端 _coded_error 下发、ApiError.code 承载。
      if (e instanceof ApiError && e.code === 'regression_already_running') {
        message.warning('已有回归在进行中');
        void loadResult();
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
    if (fixPending) return; // loading 防重复：在途时重复点击不产生第二个信号
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
        await new Promise((resolve) => setTimeout(resolve, FIX_POLL_INTERVAL_MS));
        if (fixPollAbortedRef.current) return;
        try {
          const snap = await getRegressionFixResult(project);
          if (snap.request_created && snap.request_created === wantedAt) {
            result = snap;
            break;
          }
        } catch {
          // 单轮读取失败不终止轮询（daemon 消费稍后补结果文件）
        }
      }
      if (fixPollAbortedRef.current) return;
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

  if (!active) return null;

  const status = snapshot?.status ?? 'never_run';

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
                <Button
                  type="primary"
                  loading={triggering}
                  disabled={awaitingStart}
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
          {awaitingStart ? <RunningProgressView waiting /> : null}
          <div style={{ textAlign: 'right' }}>
            <Button
              type="primary"
              loading={triggering}
              disabled={running || awaitingStart}
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

  // 自动修复按钮可用性（add-regression-auto-fix，spec 机械判定口径）：
  // 快照存在且问题列表非空（failures 非空 / long_tests 非空 / 整体超时）。
  // 回归进行中/等待启动期间快照即将被覆盖，与触发按钮同口径禁用。
  const fixAvailable =
    (snapshot?.failures?.length ?? 0) > 0 ||
    (snapshot?.long_tests?.length ?? 0) > 0 ||
    status === 'timeout';

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
            </Space>
          ) : (
            <Tag color={STATUS_TAG_COLOR[status] ?? 'red'}>
              {STATUS_TAG_TEXT[status] ?? '存在失败'}
            </Tag>
          )}
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
                children: fmtDuration(snapshot?.duration_seconds),
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
          <div style={{ marginTop: 4, textAlign: 'right' }}>
            <Space>
              {/* 自动修复回归问题（add-regression-auto-fix）：可用性由快照机械
                  判定；全绿禁用态悬停提示「无异常用例可修复」。disabled 按钮
                  不触发悬停事件，按 antd 惯例外包一层 span 承载 Tooltip。 */}
              <Tooltip title={fixAvailable ? undefined : '无异常用例可修复'}>
                <span>
                  <Button
                    loading={fixPending}
                    disabled={!fixAvailable || running || awaitingStart}
                    onClick={() => void handleFix()}
                  >
                    自动修复回归问题
                  </Button>
                </span>
              </Tooltip>
              <Button
                type="primary"
                loading={triggering}
                disabled={running || awaitingStart}
                onClick={() => void handleTrigger()}
              >
                {triggerBtnLabel(running, awaitingStart)}
              </Button>
            </Space>
          </div>
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
