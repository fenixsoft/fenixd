// claude code 输出面板（自含控件）：拉取 run 尾部事件 + SSE 增量订阅，
// 以 claudecodeui 的富消息形态渲染（Markdown / 代码高亮 / 思考折叠 / 工具卡片）。
// 数据拉取逻辑与 pages/projects/components/RunStream.tsx 同源。
//
// add-run-record-readability：头部「显示思考过程」开关（默认关闭，3.2）与
// 「显示尾部 N / 共 M 条事件」计数 + 「加载更早事件」向前分页（D5）。
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { App, Button, Spin, Switch, Typography } from 'antd';
import { getRunTail, registerRunWatch } from '@/services/dashboard';
import type { RunEvent } from '@/services/dashboard';

import { runEventsToChatMessages } from './runEvents';
import ClaudeMessageList from './ClaudeMessageList';

interface ClaudeOutputPaneProps {
  runId: string;
  project: string;
  tail?: number;
  /** 事件数变化回调（供外层在标题处显示"共 N 条事件"）。上报流事件总数
   * （与面板头部「共 M 条事件」同源），首拉返回前退化为已加载条数——
   * 「加载更早事件」只增大已加载窗口、不改变总数，外层标题不随分页漂移 */
  onEventsCount?: (count: number) => void;
  /** run 终态回调：done / error / interrupted / cancelled / missing /
   * frozen-terminated（item ce8a84164320：REST 初载 / hello 重同步直报的后端
   * classify 原始串；SSE 增量路径已由 TERMINAL_EVENT_STATUS 转译为
   * interrupted）（供外层恢复输入与按钮状态） */
  onRunStatus?: (status: string) => void;
}

// 对界去重共用核心（code-review item 6d06358498b2）：prepend/append 两镜像实现
// 的公共部分收敛于此——serializeSegment 做端部序列化（单次 O(n)，code-review
// item 700e560a4062 口径，旧实现对每个重叠候选反复 stringify 最坏 ~n²/2 次卡
// 主线程），longestSuffixPrefixOverlap 求「a 的后缀 == b 的前缀」的最长重叠
// 长度；两个入口各自只保留端部方向选择与切片剔除逻辑。
function serializeSegment(events: RunEvent[], start: number, count: number): string[] {
  const serialized: string[] = new Array(count);
  for (let i = 0; i < count; i++) {
    serialized[i] = JSON.stringify(events[start + i]);
  }
  return serialized;
}

// 返回最大 overlap ∈ [0, maxOverlap] 使 aSer 的后 overlap 项逐条等于 bSer 的前
// overlap 项（aSer/bSer 均恰含 maxOverlap 项序列化端部）；无重叠返回 0。
function longestSuffixPrefixOverlap(aSer: string[], bSer: string[], maxOverlap: number): number {
  for (let overlap = maxOverlap; overlap > 0; overlap--) {
    let matched = true;
    for (let i = 0; i < overlap; i++) {
      if (aSer[maxOverlap - overlap + i] !== bSer[i]) {
        matched = false;
        break;
      }
    }
    if (matched) return overlap;
  }
  return 0;
}

// 前置拼接对界去重（design D5）：live run 在客户端发起窗口请求与后端切片读取
// 之间可能又追加了 G 条 → 后端窗口整体后移 G 条，窗口尾部与已加载头部重叠。
// 取「older 的后缀 == loaded 的前缀」的最长重叠段剔除（归档 run 无追加、重叠为
// 0，原样前置拼接）；头部缺口接受近似，不引入事件唯一 ID（Non-Goals）。
function prependWithoutOverlap(older: RunEvent[], loaded: RunEvent[]): RunEvent[] {
  const maxOverlap = Math.min(older.length, loaded.length);
  if (maxOverlap === 0) return older;
  // 只需 older 的后缀 maxOverlap 项参与比对
  const olderTails = serializeSegment(older, older.length - maxOverlap, maxOverlap);
  const loadedHeads = serializeSegment(loaded, 0, maxOverlap);
  const overlap = longestSuffixPrefixOverlap(olderTails, loadedHeads, maxOverlap);
  return overlap > 0 ? older.slice(0, older.length - overlap) : older;
}

// 尾部追加对界去重（code-review item 289e589fb89b）：SSE hello 重同步窗口
//（流上最后 tail 条）与已加载列表按「newer 的前缀 == loaded 的后缀」的最长
// 重叠段剔除，只把真正新增的尾部追加进来——保留用户「加载更早事件」拉到的
// 前缀历史（旧实现整体替换，每次重连都把已加载前缀塌缩回尾窗、计数跳变）。
// 流轮转/截断走 reset 分支整体重拉，不经本函数。与 prependWithoutOverlap 互为
// 镜像（前置方向的 D5 对界），共用上方核心。
function appendWithoutOverlap(newer: RunEvent[], loaded: RunEvent[]): RunEvent[] {
  const maxOverlap = Math.min(newer.length, loaded.length);
  if (maxOverlap === 0) return newer;
  const loadedTails = serializeSegment(loaded, loaded.length - maxOverlap, maxOverlap);
  const newerHeads = serializeSegment(newer, 0, maxOverlap);
  const overlap = longestSuffixPrefixOverlap(loadedTails, newerHeads, maxOverlap);
  return overlap > 0 ? newer.slice(overlap) : newer;
}

// 增量分支终态事件 → status 映射（code-review item 6ec9d7211411）：覆盖
// runEvents.ts 的终态渲染集合（error/interrupted/cancelled 终态渲染）+
// session_ended 会话终态 + 写侧系统强制终止终态（item ce8a84164320）。原先只
// 认 result/error——run 中途被取消/daemon 停机补写 interrupted/cancelled 而
// 无 result/error 时，EventSource 不断链就不重连、收不到 hello 重同步的真实
// status，外层（AdminInvokeModal 的 handleRunStatus 依赖 interrupted/cancelled
// 解除「处置进行中」锁定）按钮永久禁用。session_ended（会话进程退出/被杀）、
// frozen-terminated（spec 冻结终止，轮询环对在飞 run 生效，含 admin run）、
// stall-budget-terminated（停滞判停终止）对在飞 run 等价中断，均映射为外层
// 已识别的 interrupted，不扩 onRunStatus 的既有字符串回调契约。gate-blocked /
// superseded 刻意不纳入（item ce8a84164320 取舍）：superseded 是原地重试弃置
// 旧产物的中间弃置件（重试走新产物文件、可能仍在飞），gate-blocked 是门禁
// 失败收口而非「在飞 run 被中断」——映射为 interrupted 会误解锁仍在飞的重试
// 链路，admin 调用方语义未定前不入映射。
// Map 而非对象字面量（code-review item aaf2897625a6）：`ev.type in obj` 沿
// Object.prototype 原型链查找，'toString'/'constructor' 等键也会命中而误判终态；
// Map 的 has/get 不走原型链，与下方 TERMINAL_RUN_STATUSES 的 Set.has 口径对齐。
const TERMINAL_EVENT_STATUS = new Map<string, string>([
  ['result', 'done'],
  ['error', 'error'],
  ['interrupted', 'interrupted'],
  ['cancelled', 'cancelled'],
  ['session_ended', 'interrupted'],
  ['frozen-terminated', 'interrupted'],
  ['stall-budget-terminated', 'interrupted'],
]);

// REST 拉取返回的 run status 终态集合（空态分支判定用），与 onRunStatus 契约
// 词表对齐：frozen-terminated（item ce8a84164320 扩展）REST 初载/重同步直报原
// 始串——不入集则零事件冻结终止 run 恒停在「等待输出」转圈（外层
// AdminInvokeModal 已按同一串解锁按钮，两处口径须一致）：
// 空态分支据其区分「已终态但零事件」与「等待输出」（code-review item 97dcdc581245）
const TERMINAL_RUN_STATUSES = new Set([
  'done',
  'error',
  'interrupted',
  'cancelled',
  'missing',
  'frozen-terminated',
  // stall-budget-terminated（item 87adf6f381d5）：与 SSE 增量路径的
  // TERMINAL_EVENT_STATUS 词表对齐——事件产物被轮转/清理的零事件停滞判停 run
  // 不入集会恒停在「等待输出」转圈
  'stall-budget-terminated',
]);

// watch 注册失败的退避重试上限（code-review item 11f787b2d13c）：按 1s/2s/4s
// 至多重试 3 次，覆盖瞬时故障（短暂 5xx）；耗尽后保持既有 console.error 口径，
// 照旧走 hello 分支的尾部重拉兜底
const MAX_WATCH_RETRIES = 3;

export default function ClaudeOutputPane({
  runId,
  project,
  tail = 300,
  onEventsCount,
  onRunStatus,
}: ClaudeOutputPaneProps) {
  const [events, setEvents] = useState<RunEvent[]>([]);
  const [totalEvents, setTotalEvents] = useState(0);
  // 最近一次 run status（与 onRunStatus 上报同源记录）：空态分支据其区分
  // 「已终态但零事件」与「等待输出」（code-review item 97dcdc581245）
  const [runStatus, setRunStatus] = useState('');
  const [loading, setLoading] = useState(true);
  const [loadingMore, setLoadingMore] = useState(false);
  const [error, setError] = useState('');
  // 分页失败/零进展的瞬时反馈（code-review item 1717797b5fc1）：初载路径有
  // error 态兜底，「加载更早事件」此前只 console.error，点击无任何可见反馈
  const { message } = App.useApp();
  // 显示思考过程开关：默认关闭（thinking 占比 14-19% 且恒为折叠态，关闭后
  // 不再以「已思考数秒」噪声行打断工具聚合）；无正文兜底见 runEvents
  const [thinkingVisible, setThinkingVisible] = useState(false);
  const isMountedRef = useRef(true);
  // 响应币值守卫（code-review item 5dbf7b6044bf）：detail.tsx / AdminRunModal.tsx
  // 等无 key 调用点在 runId 切换时复用本组件实例（不卸载），仅 isMountedRef
  // 拦不住旧 run 的在飞响应——请求时捕获 runId/project，响应回来与最新值比对，
  // 不匹配即丢弃（防止上一 run 的事件前置/覆盖进新 run 列表）。
  const activeRunIdRef = useRef(runId);
  const activeProjectRef = useRef(project);
  // 尾部快照落地序号守卫（code-review item e6c332a1dc8f）：初载 loadTail 与
  // SSE hello 重同步两条 getRunTail 可并发在途，初载响应若晚于重同步落地，
  // 整体替换写回会用更旧快照覆盖列表，丢掉重同步/run_events 增量已写入的
  // 事件——此后连接稳定不再触发 hello 重同步、也无 reset，丢失不可自愈。
  // 按派发序记账，只允许比「最新已落地快照」更新的响应写回（过期响应整包
  // 丢弃，total/status 同源一并止损）；较新请求失败时不推进已落地序号，
  // 初载响应仍可正常兜底。
  const tailSnapSeqRef = useRef(0);
  const tailSnapAppliedRef = useRef(0);
  // watch 注册重试的在途退避定时器句柄集合（code-review item 11f787b2d13c）：SSE
  // effect 清理时统一撤销，卸载/切 run 后不再触发在途重试。Set 收集（code-review
  // item c8d342a52519）：同连接自动重连后的 hello 会再触发一轮注册重试，单句柄
  // 会被后一轮覆盖、先到的退避定时器失去撤销保护——逐句柄登记/摘除，清理时全撤。
  const watchRetryTimersRef = useRef<Set<ReturnType<typeof setTimeout>>>(new Set());

  useEffect(() => {
    isMountedRef.current = true;
    return () => {
      isMountedRef.current = false;
    };
  }, []);

  // status 上报统一入口：向本组件同步记录一份，供空态分支判断 run 是否已终态
  const reportStatus = useCallback(
    (status: string) => {
      setRunStatus(status);
      onRunStatus?.(status);
    },
    [onRunStatus],
  );

  useEffect(() => {
    activeRunIdRef.current = runId;
    activeProjectRef.current = project;
    // 无 key 复用实例切换 run 时清掉上一 run 的 per-run 状态（与 activeRunIdRef
    // 币值守卫同源，code-review item 97dcdc581245）：events/totalEvents/error
    // 不清时，新 run 的 hello 重同步（appendWithoutOverlap 以 prev 为基准）
    // 先于初载落地会把新 run 尾窗拼进上一 run 残留列表，随后初载快照因序号
    // 较小被门槛整包丢弃、连接稳定后无重拉/重置路径自愈（item 7a4bcd0858f1）。
    // tailSnapAppliedRef 一并归零，序号门槛不从上一 run 带过来（tailSnapSeqRef
    // 是单调派发计数器，保持递增即可排序新 run 各快照的先后）；loadingMore
    // 复位防上一 run 在途分页响应不再匹配 reqRunId 时「加载更早事件」永久 loading。
    setRunStatus('');
    setEvents([]);
    setTotalEvents(0);
    setError('');
    setLoadingMore(false);
    tailSnapAppliedRef.current = 0;
  }, [runId, project]);

  // 拉取尾部事件
  useEffect(() => {
    if (!runId || !project) return;

    const reqRunId = runId;
    const reqProject = project;
    const loadTail = async () => {
      const snapSeq = ++tailSnapSeqRef.current;
      try {
        setLoading(true);
        const data = await getRunTail(reqRunId, reqProject, tail);
        // 过期快照（item e6c332a1dc8f）：更新的重同步快照已落地时整包丢弃，
        // 防止整体替换回退列表
        if (snapSeq <= tailSnapAppliedRef.current) return;
        if (isMountedRef.current && activeRunIdRef.current === reqRunId && activeProjectRef.current === reqProject) {
          tailSnapAppliedRef.current = snapSeq;
          setEvents(data.events || []);
          setTotalEvents(data.total_events || 0);
          setError('');
          reportStatus(data.status || '');
        }
      } catch (e) {
        if (isMountedRef.current && activeRunIdRef.current === reqRunId && activeProjectRef.current === reqProject) {
          setError(e instanceof Error ? e.message : String(e));
        }
      } finally {
        // loading 复位与数据写回同一三重币值守卫（code-review item 6a3e881e5091）：
        // 跨项目同名 run 切换后，旧 run 迟到的初载 finally 若只按 runId 宽口径，
        // 会提前复位新 run 仍在途请求的 loading（界面闪「等待输出…」空态）；新
        // run 初载自身的 finally 会复位 loading，此处收窄不关闭复位路径
        if (isMountedRef.current && activeRunIdRef.current === reqRunId && activeProjectRef.current === reqProject) {
          setLoading(false);
        }
      }
    };

    void loadTail();
    // reportStatus 刻意不入依赖（code-review item aa6c0683def4）：它随 [onRunStatus]
    // 变化，而 AdminInvokeModal 以内联函数传 onRunStatus 且其 eventCount 高频
    // setState，列入依赖会逐事件重拉尾部并闪 loading 遮罩
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [runId, project, tail]);

  // 向前分页（design D5）：以 offset_from_end=当前已加载条数重拉并前置拼接，
  // SSE 增量只追加尾部互不冲突；已加载 ≥ total 时按钮禁用
  const loadOlder = useCallback(async () => {
    if (!runId || !project || loadingMore) return;
    const reqRunId = runId;
    const reqProject = project;
    // 派发即记账（item f9b3f56a1e32，同初载/hello/reset 快照守卫）：分页写回
    // 是前置拼接 + total 回写，在途期间产物被轮转/截断触发 reset 重拉（整体
    // 替换）时，迟到的分页响应会把轮转前的旧窗口拼进重置后列表、stale total
    // 覆盖新计数——与重拉快照按同一序号排序，过期响应整包丢弃。刻意不推进
    // tailSnapAppliedRef：分页写回非整体替换快照，推进会把晚于本页派发、仍在
    // 途的重同步快照（含其中的终态 status 上报）误判为过期丢弃。
    const snapSeq = ++tailSnapSeqRef.current;
    setLoadingMore(true);
    try {
      const data = await getRunTail(reqRunId, reqProject, tail, events.length);
      // 过期分页响应（item f9b3f56a1e32）：更新的重拉/重同步快照已落地时整包
      // 丢弃，防旧窗口前置拼进重置后列表
      if (snapSeq <= tailSnapAppliedRef.current) return;
      if (isMountedRef.current && activeRunIdRef.current === reqRunId && activeProjectRef.current === reqProject) {
        setTotalEvents(data.total_events || 0);
        reportStatus(data.status || '');
        const older = prependWithoutOverlap(data.events || [], events);
        if (older.length > 0) {
          setEvents((prev) => [...older, ...prev]);
        } else if (events.length < (data.total_events || 0)) {
          // 零进展提示（code-review item 1717797b5fc1）：快进流下后端窗口整体
          // 滑过已加载前缀 → 去重后无新内容，events.length 不增长、canLoadOlder
          // 仍为 true，静默重试会让用户反复点击同一窗口
          message.info('本轮未取到更早事件（窗口已被追加推过），请稍后重试');
        }
      }
    } catch (e) {
      console.error('Failed to load earlier events:', e);
      // 失败反馈（code-review item 1717797b5fc1）：分页失败此前只落 console，
      // 用户侧表现为点了没反应
      message.error(`加载更早事件失败：${e instanceof Error ? e.message : String(e)}`);
    } finally {
      // loading 重置与数据写回同一币值守卫（code-review item 612025308c19）：
      // 跨项目同名 run 切换后，旧 run 迟到的分页 finally 若只按 runId 宽口径，
      // 会误重置新一次点击触发的 loadingMore（按钮 loading 提前消失）；切 run
      // 场景的复位已由 [runId, project] effect 无条件兜底（item 97dcdc581245），
      // 此处收窄不关闭重置路径
      if (isMountedRef.current && activeRunIdRef.current === reqRunId && activeProjectRef.current === reqProject) {
        setLoadingMore(false);
      }
    }
  }, [runId, project, tail, events, loadingMore]);

  // run watch 注册移入 SSE onmessage 的 hello 分支（需要服务端分配的连接 cid）

  // 监听 SSE 事件（run_events）
  useEffect(() => {
    if (!runId || !project) return;

    const eventSource = new EventSource('/api/stream');

    // watch 注册失败有限次退避重试（code-review item 11f787b2d13c）：注册失败时
    // 后端 sse.broadcast 只投递给 watched_runs 命中的连接，本连接收不到该 run 的
    // run_events 增量；而 EventSource 在连接本身健康时不会重连、也就不会再收到
    // hello 补注册，live run 增量从此静默丢失（面板冻结在注册失败时刻的快照）。
    // 故按 1s/2s/4s 退避至多重试 MAX_WATCH_RETRIES 次；重试经挂载/币值守卫，
    // 耗尽或已卸载/切 run 时保持既有 console.error 口径并返回（不抛出，调用方
    // 照旧走尾部重拉兜底）。定时器句柄记入 watchRetryTimersRef 供 effect 清理撤销。
    const registerWatchWithRetry = async (cid: string): Promise<void> => {
      for (let attempt = 0; ; attempt++) {
        try {
          await registerRunWatch(runId, project, cid);
          return;
        } catch (e) {
          if (
            attempt >= MAX_WATCH_RETRIES ||
            !isMountedRef.current ||
            activeRunIdRef.current !== runId ||
            activeProjectRef.current !== project
          ) {
            console.error('Failed to register run watch:', e);
            return;
          }
          console.error(`Failed to register run watch (attempt ${attempt + 1}), retrying:`, e);
          await new Promise<void>((resolve) => {
            // 句柄登记入 Set（item c8d342a52519）：并发多轮注册重试互不覆盖，
            // 到期自摘防集合无界增长
            const timer = setTimeout(() => {
              watchRetryTimersRef.current.delete(timer);
              resolve();
            }, 1000 * 2 ** attempt);
            watchRetryTimersRef.current.add(timer);
          });
        }
      }
    };

    eventSource.onmessage = (ev: MessageEvent) => {
      if (!isMountedRef.current) return;

      let msg: { type?: string; cid?: string; run_id?: string; events?: RunEvent[]; reset?: boolean } = {};
      try {
        msg = JSON.parse(ev.data);
      } catch {
        return;
      }

      // 服务端在 hello 中分配连接 cid —— watch 注册必须用它，否则 _conns.get(cid)
      // 匹配不到连接、订阅静默失效（自造 cid 是无效的）
      if (msg.type === 'hello' && msg.cid) {
        // 派发即记账（item e6c332a1dc8f）：重同步快照与初载快照按同一序号
        // 排序，晚落地的过期一方整包丢弃
        const snapSeq = ++tailSnapSeqRef.current;
        void (async () => {
          // 失败退避重试（code-review item 11f787b2d13c）：重试耗尽不抛出，
          // 照旧走下方尾部重拉兜底
          await registerWatchWithRetry(msg.cid!);
          // 注册后重拉一次尾部：兜底「run 在 watch 注册前已结束」或「SSE 断线
          // 重连期间错过终态事件」的场景，否则外层永远收不到完成回调。
          // 重同步改为尾部追加合并（code-review item 289e589fb89b）：整体替换
          // 会在每次 hello（含 EventSource 自动重连）把「加载更早事件」拉到的
          // 前缀历史塌缩回尾窗、计数跳变；appendWithoutOverlap 只补真正新增的
          // 尾部。币值守卫防旧 run 的迟到响应污染新 run（item 5dbf7b6044bf）。
          try {
            const data = await getRunTail(runId, project, tail);
            if (snapSeq <= tailSnapAppliedRef.current) return; // 过期快照，丢弃
            if (isMountedRef.current && activeRunIdRef.current === runId && activeProjectRef.current === project) {
              tailSnapAppliedRef.current = snapSeq;
              setTotalEvents(data.total_events || 0);
              // 重拉成功即脱离错误态（code-review item ccb026b72fe7）：初载
              // loadTail 失败已 setError 时，渲染被 error 短路，重同步数据虽
              // 已写回仍显示「加载失败」，只能整页刷新
              setError('');
              reportStatus(data.status || '');
              const newerEvents = data.events || [];
              setEvents((prev) => {
                const newer = appendWithoutOverlap(newerEvents, prev);
                return newer.length > 0 ? [...prev, ...newer] : prev;
              });
            }
          } catch (e) {
            console.error('Failed to resync run tail:', e);
          }
        })();
        return;
      }

      if (msg.type === 'run_events' && msg.run_id === runId) {
        if (msg.reset) {
          // 产物被轮转/截断：重新拉取完整尾部（整体替换合理：旧列表已失效）
          // 派发即记账（item e6c332a1dc8f，同 hello 重同步）：reset 重拉与初载/
          // 重同步快照按同一序号排序，晚落地的过期一方整包丢弃——否则 reset 重拉
          // 与重连 hello 重同步并发在途且 reset 快照晚落地时，会以更旧窗口整体
          // 替换列表并回退 total/status，此后连接稳定即无自愈路径
          const snapSeq = ++tailSnapSeqRef.current;
          void (async () => {
            try {
              const data = await getRunTail(runId, project, tail);
              if (snapSeq <= tailSnapAppliedRef.current) return; // 过期快照，丢弃
              if (isMountedRef.current && activeRunIdRef.current === runId && activeProjectRef.current === project) {
                tailSnapAppliedRef.current = snapSeq;
                setEvents(data.events || []);
                setTotalEvents(data.total_events || 0);
                // 重拉成功清错误态（code-review item ccb026b72fe7，同 hello 重同步）
                setError('');
                reportStatus(data.status || '');
              }
            } catch (e) {
              console.error('Failed to reload tail:', e);
            }
          })();
        } else if (msg.events && msg.events.length > 0) {
          const incoming = msg.events;
          // 增量追加前对界去重（code-review item a36d72e0b207）：SSE 层在重连
          // 边界可能向同一连接重复投递同批事件（服务端广播与重拉竞态），直接
          // 追加会让同一条事件重复渲染且 total 双计。与 hello 重同步共用
          // appendWithoutOverlap 对界核心，只把真正新增的尾部追加进来。
          // appended 用本批闭包变量传给下方 totalEvents updater——updater 必须
          // 是纯函数（StrictMode/并发重放会在其中顺手 setState 双计），React 按
          // 入队顺序执行同批 updater，此处重放时 prev 不变、结果幂等。
          let appended = 0;
          setEvents((prev) => {
            const newer = appendWithoutOverlap(incoming, prev);
            appended = newer.length;
            return newer.length > 0 ? [...prev, ...newer] : prev;
          });
          // 增量同步推进总数（code-review item 7ae6c2b659c2）：watcher 的
          // run_events 只带增量 events 不带 total，不推进会让「共 M 条」停在
          // 最近一次 REST 拉取值——live run 流入条数超过 stale total 后
          // canLoadOlder（events.length < totalEvents）恒 false，「加载更早
          // 事件」被错误禁用而更早历史仍在。按剔除重叠后的实际追加条数记账
          //（item a36d72e0b207），重复投递整批被剔除时 total 不动。reset/
          // 重同步路径整体重拉 total，不经本分支。
          setTotalEvents((prev) => prev + appended);
          for (const ev of incoming) {
            const status = TERMINAL_EVENT_STATUS.get(ev.type);
            if (status) {
              reportStatus(status);
              break;
            }
          }
        }
      }
    };

    eventSource.onerror = () => {
      // EventSource 原生自动重连
    };

    return () => {
      // 撤销在途的 watch 注册重试定时器（code-review item 11f787b2d13c）：
      // 卸载/切 run 后不再触发在途重试；逐句柄撤销（item c8d342a52519），
      // 并发多轮注册重试的退避定时器一并清掉
      for (const timer of watchRetryTimersRef.current) {
        clearTimeout(timer);
      }
      watchRetryTimersRef.current.clear();
      eventSource.close();
    };
    // reportStatus 刻意不入依赖（code-review item aa6c0683def4，理由同初载
    // effect）：onRunStatus 引用不稳定时列入依赖会逐事件关闭重建 EventSource
    // 并重注册 watch，代价更高
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [runId, project, tail]);

  // 事件数变化通知外层（必须在条件 return 之前调用 hook，否则 loading 翻转时
  // hook 数量变化触发 "Rendered more hooks" 崩溃）。上报流事件总数（与头部
  // 「共 M 条」同源）：分页只增大已加载窗口，上报 events.length 会让外层
  // 「共 N 条事件」在「加载更早事件」后与头部计数相左（code-review item
  // 9ba6bf8be09c）。首拉返回前两者同为 0，totalEvents 兜底 events.length
  useEffect(() => {
    onEventsCount?.(totalEvents || events.length);
  }, [totalEvents, events, onEventsCount]);

  const messages = useMemo(
    () => runEventsToChatMessages(events, thinkingVisible),
    [events, thinkingVisible],
  );

  const canLoadOlder = totalEvents > 0 && events.length < totalEvents;

  // 参数缺失防御（code-review item ff5beae43de6）：runId/project 为空时首拉
  // effect 直接 return、loading 初值 true 无人复位，组件会永久停在「加载运行
  // 记录」Spin。守卫须放在全部 hook 之后（条件 return 前置会破坏 hook 顺序），
  // 直接不渲染，不误入「等待输出」空态。
  if (!runId || !project) return null;

  if (loading) {
    return (
      <div className="flex h-full items-center justify-center">
        <Spin size="small" />
        <Typography.Text type="secondary" style={{ marginLeft: 8 }}>
          加载运行记录...
        </Typography.Text>
      </div>
    );
  }

  if (error) {
    return (
      <div className="flex h-full items-center justify-center">
        <Typography.Text type="danger">加载失败: {error}</Typography.Text>
      </div>
    );
  }

  // run 定位成功但尚未产出事件：未终态时明确提示 loading；已终态（done/error/
  // interrupted/cancelled/missing/frozen-terminated/stall-budget-terminated，
  // 含事件产物被轮转/清理的零事件历史 run）改静态提示，不再永久停在「等待输出」
  // 转圈（code-review item 97dcdc581245）
  if (events.length === 0) {
    const isTerminalStatus = TERMINAL_RUN_STATUSES.has(runStatus);
    return (
      <div className="flex h-full flex-col items-center justify-center">
        {!isTerminalStatus && <Spin size="small" />}
        <Typography.Text type="secondary" style={{ marginTop: isTerminalStatus ? 0 : 12 }}>
          {isTerminalStatus ? '该 run 无事件记录' : 'Administrator 已唤起，等待输出…'}
        </Typography.Text>
      </div>
    );
  }

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="flex flex-shrink-0 flex-wrap items-center gap-x-3 gap-y-1 border-b border-border/60 px-3 py-1.5 text-xs text-muted-foreground">
        <span>
          显示尾部 {events.length} / 共 {totalEvents} 条事件
        </span>
        <Button
          size="small"
          disabled={!canLoadOlder}
          loading={loadingMore}
          onClick={() => void loadOlder()}
        >
          加载更早事件
        </Button>
        <span className="ml-auto flex items-center gap-1.5">
          显示思考过程
          <Switch size="small" checked={thinkingVisible} onChange={setThinkingVisible} />
        </span>
      </div>
      <ClaudeMessageList messages={messages} showThinking={thinkingVisible} />
    </div>
  );
}
