// SessionPanel.tsx — 项目级自由会话内联分面面板（add-project-detail-tabs D2）
//
// 由项目级会话全屏 Modal 迁移（Modal 外壳 → 「会话接入」分面内联容器），会话行为契约零变更：
// 打开流程：GET 拉全量缓冲 → EventSource(STREAM_URL) → hello 分支用服务端
// cid 注册 watch → 再 GET 重拉一次（兜住注册前窗口），与 ClaudeOutputPane 同构。
// 会话不存在（首次进入）→ 显示「开始会话」空态，点击后显式 POST /api/session/start。
// 分面无会话项目不注册 watch（注册必然 404 → console.error，污染 no_console_error
// 断言；验证 BUG-01 实证，迁移源为合入 main 的 5f5d5846 修复形态）。
// 切离分面（active=false）：unregister watch + eventSource.close() + 清空本地状态，
// 切回分面时重新执行 loadAll() 接回；MUST NOT 终止会话进程本身。
import { useEffect, useMemo, useRef, useState } from 'react';
import type { CSSProperties } from 'react';
import {
  App,
  Button,
  Spin,
  Typography,
  theme,
} from 'antd';
import { MessageOutlined } from '@ant-design/icons';
import {
  fetchSessionCommands,
  fetchSessionFiles,
  getSession,
  sendSessionMessage,
  startSession,
  stopSession,
  registerSessionWatch,
  unregisterSessionWatch,
  STREAM_URL,
} from '@/services/dashboard';
import type { SessionEvent } from '@/services/dashboard';
import { ClaudeMessageList, runEventsToChatMessages } from '@/components/claude-msg';
import { SessionComposer } from '@/components/claude-composer';
import { useIsMobile } from '@/hooks/useIsMobile';
import {
  PAGE_CHROME_OFFSET_DESKTOP,
  PAGE_CHROME_OFFSET_MOBILE,
} from '@/utils/pageChrome';

// SSE 断流兜底轮询间隔（code-review item 2303508d27ff）：服务端连接数满时
// /api/stream 返回 503（core/dashboard/routes/sse_routes.py
// dashboard-connection-limit D6），浏览器 EventSource 对非 200 响应会永久
// 停止重连，此后会话事件（消息回显、session_ended）永不到达。onerror 置
// 失败态并降级为低频 REST 快照轮询，间隔对齐 list.tsx HEARTBEAT_MS 量级；
// onopen（连接恢复）即清除失败态并停轮询。
const STREAM_FALLBACK_MS = 30000;
// watch 注册失败退避重试（code-review item a67da3eb2778）：注册因瞬态网络/
// 服务端错误失败时只记日志的话，EventSource 连接未断就不会重连、hello 不会
// 再来，本连接内不再有任何注册机会，会话事件静默丢失。有限次固定间隔重试，
// 全部耗尽置「实时推送不可用」失败态并同样降级轮询（与 SSE 断流共用提示位）。
const WATCH_RETRY_MAX = 3;
const WATCH_RETRY_INTERVAL_MS = 5000;
// 本地事件保留上限（code-review item 28d5d8c4adc8）：对齐服务端事件环形缓冲
// deque(maxlen=4000)（core/dashboard/session_manager.py SESSION_EVENT_BUFFER）
// 并留 200 余量——余量容纳快照合并（applySnapshotCarried）前插保留的窗口外
// 早期事件，避免上限边界反复触顶回裁抖动。裁剪收口见 trimLocalEvents。
const MAX_LOCAL_EVENTS = 4200;

interface SessionPanelProps {
  project: string;
  /** 「会话接入」分面是否被选中：激活时拉取会话状态并订阅事件流，切离即释放订阅 */
  active: boolean;
}

// 静态布局样式常量（code-review item d42f28cde496）：内联对象原在渲染体每
// 渲染重建。分面高度 = 视口 − 页面 chrome，纯 CSS 计算（无 JS 量算）：
// 内联分面的父链（ant-pro 布局 / antd Tabs 内部 holder）不被拉伸到视口高度，
// 故 flex:1 撑不满——必须显式给出视口填充高度，否则回落到内容高度（旧的
// minHeight 480 独占），输入区停在视口中部（本项目实测：1000px 视口停在 670）。
// 桌面：顶部 190 = 布局顶栏 56 + 页头 72 + Tabs 导航 46 + Tabs 内容上边距 16；
// 底部 32 = 内容容器 padding-bottom。两者在 375~1920 宽 / 700~1440 高下实测恒定。
// 超短视口（<542）由 minHeight 保底，退化为页面滚动。
// 移动端（add-session-composer 3.2 / D5）：ProLayout 形态不同
// （global.less 收紧 padding-inline 为 12，页头余量更小），222 常数不适用，
// 独立常数 + dvh 组合（dvh 随浏览器工具栏收展，较 vh 贴地）；常数按 390×844
// 实测校准（顶栏 56 + Tabs 46 + 上边距 16 + 底部 padding 12 + 余量 38）。
const PANEL_LAYOUT_STYLE: CSSProperties = {
  display: 'flex',
  flexDirection: 'column',
  height: `calc(100vh - ${PAGE_CHROME_OFFSET_DESKTOP}px)`,
  minHeight: 320,
};
const PANEL_LAYOUT_STYLE_MOBILE: CSSProperties = {
  display: 'flex',
  flexDirection: 'column',
  // 390×844 实测（Task 4.1，playwright + stub claude serve 实例）：详情页
  // 头部+分面页签在移动端占 222px，留 12px 底部呼吸 → 234。首版推定 168
  // 实测偏小，页面出现 54px 纵向溢出（898 vs 844）。
  height: `calc(100dvh - ${PAGE_CHROME_OFFSET_MOBILE}px)`,
  minHeight: 320,
};
// 空态/错误分支的紧凑呈现容器（add-session-composer 3.2：弃用视口垂直+水平
// 居中的悬空布局，改顶部左对齐紧凑排布）
const COMPACT_NOTE_STYLE: CSSProperties = {
  display: 'flex',
  flexDirection: 'column',
  alignItems: 'flex-start',
  gap: 8,
  padding: '16px 2px',
};
// 空态（尚未接入会话）容器（2026-09-26 用户定调恢复居中：在面板内水平+垂直
// 居中，非 3.2 曾废弃的视口悬空居中）。flex:1 占满面板剩余高度才有垂直居中的
// 支点；minHeight:0 防内容溢出撑破（同 MESSAGE_AREA_STYLE 的教训）。
const EMPTY_STATE_STYLE: CSSProperties = {
  display: 'flex',
  flexDirection: 'column',
  flex: 1,
  minHeight: 0,
  alignItems: 'center',
  justifyContent: 'center',
  gap: 8,
  padding: '16px 2px',
};
const LOADING_ROW_STYLE: CSSProperties = {
  display: 'flex',
  alignItems: 'center',
  gap: 8,
  padding: '16px 2px',
};
// display:flex 必须显式给出（2026-09-25 缺陷修复）：本容器默认 block，子级
// ClaudeMessageList 的 flex-1 / min-h-0 / overflow-y-auto 在 block 容器里全部
// 失效——列表涨到内容高度，向下溢出与输入区重叠、撑出页面级滚动条把输入区
// 滚走（长会话 100% 复现）。flex 容器化后子级被约束在本区域内自行滚动。
const MESSAGE_AREA_STYLE: CSSProperties = {
  flex: 1,
  minHeight: 0,
  position: 'relative',
  display: 'flex',
  flexDirection: 'column',
};
const TRUNCATED_BAR_STYLE: CSSProperties = {
  position: 'absolute',
  top: 8,
  left: 0,
  right: 0,
  textAlign: 'center',
};
// 截断提示条文字样式（code-review item 22baafa4128a）：原内联在渲染体每渲染
// 重建，且硬编码 '#fff' 与主题耦合（暗色主题下是白底补丁）。静态部分提为模块级
// 常量并入 TRUNCATED_BAR_STYLE 派生约定；背景色须用 antd token colorBgContainer
// 随主题，而 useToken 只能在组件内调用（同 app.tsx HeaderTitle 惯例），故含
// token 的部分在组件内经 useMemo 合成，渲染体只引用不重建。
const TRUNCATED_TEXT_STYLE_BASE: CSSProperties = {
  fontSize: 12,
  padding: '0 8px',
};
// 实时更新不可用提示条（code-review items 2303508d27ff / a67da3eb2778 共用
// 提示位）：SSE 断流或 watch 注册重试耗尽时的降级提示，置于面板顶部、
// 不遮消息区与输入区
const STREAM_DOWN_BAR_STYLE: CSSProperties = {
  display: 'flex',
  alignItems: 'center',
  gap: 8,
  padding: '4px 2px',
};

export default function SessionPanel({ project, active }: SessionPanelProps) {
  const { message } = App.useApp();
  const isMobile = useIsMobile();
  const [events, setEvents] = useState<SessionEvent[]>([]);
  const [loading, setLoading] = useState(false);
  const [sending, setSending] = useState(false);
  // 停止请求在途防重（code-review item 4c0da5acbb6f）：ended 要等 stopSession
  // 响应返回才置位，网络往返窗口内连点会并发发出多次 stop 请求（首次成功
  // 移除会话后后续请求命中服务端无会话判定而报错）。在途期间禁用按钮，
  // finally 复位——失败也复位，保留重试能力。
  const [stopping, setStopping] = useState(false);
  // 发送/停止重入守卫（code-review item 3ea48a0e30b5，比照 HooksPanel/
  // useGatedFormPanel 的 savingRef 口径）：setSending/setStopping 渲染生效存在
  // React 调度间隙，防重若只靠 sending/stopping state（SessionComposer 按钮
  // disabled 同样消费这两个 state），间隙内连点或 Enter 连发会并发发出两次
  // sendSessionMessage/stopSession 请求；经 sendingRef/stoppingRef 写读同帧
  // 原子短路，state 只负责按钮视觉反馈。
  const sendingRef = useRef(false);
  const stoppingRef = useRef(false);
  // 启动重入守卫（code-review item 038d04ea5c2e，同上 sendingRef/stoppingRef
  // 口径）：handleStart 只靠 setLoading(true) 的渲染反馈间接防重，「开始会话」
  // 空态按钮未接 loading disabled，调度间隙内连点可并发发出两次 startSession。
  const startRef = useRef(false);
  const [ended, setEnded] = useState(false);
  const [started, setStarted] = useState(false); // 会话是否已启动（session: null 时空态）
  const [truncated, setTruncated] = useState(false);
  const [error, setError] = useState('');
  // 实时更新不可用失败态（code-review items 2303508d27ff / a67da3eb2778 共用
  // 提示位）：SSE 断流（含 503 永久停止重连）或 watch 注册重试耗尽时置位，
  // 面板顶部提示「实时更新不可用」；恢复路径（SSE onopen / watch 注册成功）
  // 复位（watch 注册成功路径仅 SSE 处于连接态时复位，见下方 sseConnectedRef）。
  // effect 重建（切回分面/切项目）时无条件复位。
  const [streamDown, setStreamDown] = useState(false);
  // SSE 连接态镜像（code-review item 32630a523c16）：streamDown 两个置位根因
  // （SSE 断流 / watch 注册重试耗尽）的恢复信号不同——SSE 的恢复只有 onopen。
  // onerror/onopen 各自写入本 ref，watch 重试成功路径读它决定能否清失败态：
  // 失败态若先由 onerror 置位（SSE 仍断流、兜底轮询在跑），随后的 REST 注册
  // 成功不代表事件通道恢复，不得清除提示，等 onopen 再清。
  const sseConnectedRef = useRef(false);
  // 补全候选（add-session-composer 3.1/3.2）：端点封装已吞错降级为空数组
  const [slashCommands, setSlashCommands] = useState<string[]>([]);
  const [skills, setSkills] = useState<string[]>([]);
  const [files, setFiles] = useState<string[]>([]);
  // 事件 uuid 去重集合：GET 全量重拉时清空重建，SSE 增量跳过已见项；
  // 无 uuid 的事件（stderr / session_ended 本地合成）不进集合
  const seenUuidsRef = useRef<Set<string>>(new Set());
  // 事件列表镜像 ref（code-review item 1371d6ca978a）：afterHello 第二次重拉
  // 跑在 effect 闭包里，闭包捕获的 events state 是挂载时快照（stale closure）
  // 读不到窗口内 SSE 增量——经本 ref 读取替换前的实时列表，供快照合并补回。
  // events state 的变更点（syncEvents / appendEvents / applySnapshotCarried 的
  // carried 前插合并与 trimLocalEvents 收口裁剪）均同步维护本 ref。
  const eventsRef = useRef<SessionEvent[]>([]);
  // cid 由服务端在 SSE hello 中分配（design D3：自造 cid 会静默失效）。初值必须为
  // null——分面未激活时无任何订阅可注销；若预置自造 cid，下方 [active] 清理
  // effect 会在挂载当帧发出 DELETE /api/session/watch（服务端查不到该 cid 对应
  // 会话）→ 404 → 控制台错误，污染所有访问项目列表页的 no_console_error 断言
  // （2026-09-18 admin 处置 add-spec-manual-activation 时实证）。
  const cidRef = useRef<string | null>(null);
  const sessionIdRef = useRef<string | null>(null);
  // watch 是否实际注册过：无会话项目（空态）跳过注册但 hello 仍分配 cid，
  // 若照 cid 无条件注销会对「从未注册的 cid」发 DELETE /api/session/watch →
  // 服务端无会话返回 404 → console.error，污染所有访问项目页的
  // no_console_error 断言（本项目验证实测）。仅注册过才注销。
  const watchRegisteredRef = useRef(false);
  // 重试入口（code-review item ca2aab0e3956）：effect 内 loadAll 闭包经本 ref
  // 暴露给 error 分支「重试」按钮——旧实现只清 error，不重跑失败的加载，
  // 用户掉回空/旧面板而无任何重试发生。
  const reloadRef = useRef<(() => void) | null>(null);
  // watch 注册失败重试入口（code-review item 87c796fb6050）：effect 内的
  // scheduleWatchRetry 闭包经本 ref 暴露给组件级 handleStart——空态启动会话
  // 后的补注册失败只记日志的话，EventSource 不断线则 hello 不再来，本连接
  // 内再无注册机会，本会话事件静默丢失。与 afterHello 失败共用同一有限次
  // 退避重试（重试目标取注册时刻的 cidRef.current，即当前连接 hello 分配的
  // cid，非失效闭包捕获）。
  const scheduleWatchRetryRef = useRef<(() => void) | null>(null);
  // 分面激活态镜像（code-review item 58ec4693e77c）：handleStart 等事件回调
  // 跨 await 续跑时，闭包捕获的 active 是点击当帧快照——用户点「开始会话」后
  // 立即切离分面，切离清理 effect 已清空 sessionIdRef/ended 等状态并释放订阅，
  // 续跑若照旧写入会把活跃状态回落到非激活面板（直到下次激活 loadAll 重置才
  // 自愈）。经本 ref 读取最新激活态，供 handleStart 在各 await 后校验，失配
  // 即中止后续注册与状态写入。
  const activeRef = useRef(active);
  useEffect(() => {
    activeRef.current = active;
  }, [active]);
  // 项目名镜像（code-review item cefe51c864ea）：切离/卸载注销 watch 的 effect
  // 依赖仅 [active]（下方 eslint-disable），project 不在依赖中——分面保持激活
  // 跨项目切换（list.tsx 的 project 来自 useParams、组件不重挂载）时该 effect
  // 不重跑，闭包 project 停留旧项目，切离/卸载时会对旧项目名配 cidRef 中新
  // 项目的 cid 发 DELETE /api/session/watch，服务端查不到 → 注销静默失效
  // （rejection 被调用点吞掉）、旧项目 watch 无人注销。经本 ref 读取最新
  // 项目名，与 cid 同源（与上方 activeRef 同一规避模式）。
  const projectRef = useRef(project);
  useEffect(() => {
    projectRef.current = project;
  }, [project]);

  // 快照应用串行链（code-review item e3b97bedcb43：自主 effect 局部闭包提升到
  // 组件级）：原链只在主 effect 内可见，handleStart 的快照拉取不经该链——用户
  // 在激活后立即点「开始会话」时，afterHello 在途的旧快照（GET 发起于
  // startSession 完成之前）可晚于 handleStart 的快照应用，applySnapshot 整表
  // 替换把面板翻回空态（started=false、events 清空）、uuid 去重集合按旧快照
  // 重建，窗口内事件丢失，需用户再次点击才恢复。链提升后，effect 内 loadAll /
  // afterHello 与 handleStart 的快照统一经本链按发起顺序串行落盘。
  const loadChainRef = useRef<Promise<void>>(Promise.resolve());
  const enqueueSnapshotLoad = (task: () => Promise<void>): Promise<void> => {
    // 返回挂接 catch 之前的 promise：任务自身的失败（handleStart 的 getSession
    // 报错）仍沿返回值抛给调用方的既有 catch（→ setError）；链本体经 catch 续接，
    // 单次失败不断链（loadAll / afterHello 的任务内部自吞错，行为不变）。
    const run = loadChainRef.current.then(task);
    loadChainRef.current = run.catch(() => {});
    return run;
  };

  const syncEvents = (next: SessionEvent[]) => {
    // 全量重拉：以快照 uuids 重建去重集合（code-review item 12c190b15530）——
    // 旧实现只 clear，重拉后到达的 SSE session_events 帧若携带快照中已有的
    // 事件（「reload 兜注册窗口」设计必然制造的重叠）会被再次 append 成重复
    // 消息。重建集合后 SSE 增量照旧跳过已见项（design D6）。
    seenUuidsRef.current = new Set(
      next
        .map((ev) => (ev ? (ev.uuid as string | undefined) : undefined))
        .filter((u): u is string => Boolean(u)),
    );
    eventsRef.current = next;
    setEvents(next);
  };

  const appendEvents = (incoming: SessionEvent[]) => {
    const seen = seenUuidsRef.current;
    const fresh: SessionEvent[] = [];
    for (const ev of incoming) {
      if (!ev) continue;
      const uuid = ev.uuid as string | undefined;
      if (uuid) {
        if (seen.has(uuid)) continue;
        seen.add(uuid);
      }
      fresh.push(ev);
    }
    if (fresh.length > 0) {
      eventsRef.current = [...eventsRef.current, ...fresh];
      // 追加后的统一收口裁剪（上限内为 no-op，不触发额外渲染）
      trimLocalEvents();
      setEvents(eventsRef.current);
    }
  };

  // 本地保留事件数上限裁剪（code-review item 28d5d8c4adc8）：eventsRef/
  // seenUuidsRef 原本只增不减——applySnapshotCarried 刻意前插保留已滑出服务端
  // 窗口的早期事件（item 51f0857322b5 的正确性取舍），长会话（daemon 可连续
  // 运行数日）下客户端内存与列表无上限增长，chatMessages 的 useMemo 以 events
  // 为键，每帧 SSE 对全量重跑 runEventsToChatMessages 的成本随之线性上升。
  // 取舍：本地只保留与服务端环形窗（SESSION_EVENT_BUFFER = 4000）同量级的
  // 最近事件，超限从最旧端裁剪、不重排，carried 合并的时序语义不受影响——
  // 被裁事件均已滑出服务端 4000 窗口，不会再经后续快照/SSE 复现，可安全同步
  // 从 seenUuidsRef 删除其 uuid，使去重集合与列表同界。增长点只有 appendEvents
  // （SSE / 尾补回）与 applySnapshotCarried（前插合并），两处落盘后各自调用
  // 本 helper 统一收口。
  const trimLocalEvents = () => {
    const current = eventsRef.current;
    if (current.length <= MAX_LOCAL_EVENTS) return;
    const overflow = current.length - MAX_LOCAL_EVENTS;
    for (let i = 0; i < overflow; i++) {
      const ev = current[i];
      const uuid = ev ? (ev.uuid as string | undefined) : undefined;
      if (uuid) seenUuidsRef.current.delete(uuid);
    }
    eventsRef.current = current.slice(overflow);
    setEvents(eventsRef.current);
  };

  // 快照应用单源（code-review item a4bbea6af729）：会话状态更新块曾在
  // loadAll / afterHello / handleStart 三处复制粘贴，易漂移——抽单一 helper。
  // 会话存在 → 记 cid、置已启动、全量替换事件；不存在 → 空态。
  // 返回快照是否命中会话终态（code-review item d8e51da1b3c9）：即下方终态
  // 扫描的判定结果（空态恒 false），供 afterHello 注册 watch 前判断——
  // 终态会话跳过注册（注册毫无意义且竞态窗口内必 404）。
  const applySnapshot = (data: Awaited<ReturnType<typeof getSession>>): boolean => {
    if (data.session) {
      sessionIdRef.current = data.session.id;
      setStarted(true);
      // 快照终态扫描（code-review item 216ac3c40493）：与下方 onmessage 的
      // session_ended 增量扫描单源化——会话可能在分面切离期间被停止/空闲
      // 回收/进程退出，快照事件缓冲已含 session_ended（服务端 _terminate
      // 先 append 终态再移除会话），只置 false 会让输入区与停止按钮误恢复
      // 可用；命中终态时同步清 watchRegisteredRef（服务端会话已移除，此后
      // 注销 watch 必 404）。
      const snapshotEnded = (data.events || []).some(
        (e) => e?.type === 'session_ended',
      );
      setEnded(snapshotEnded);
      if (snapshotEnded) watchRegisteredRef.current = false;
      syncEvents(data.events || []);
      setTruncated(Boolean(data.truncated));
      setError('');
      return snapshotEnded;
    } else {
      // 会话未启动：空态，等待「开始会话」。清 error（item 232d40e20d0c）：
      // 成功获取快照即代表当前真实状态——此前瞬态故障（如重连前 afterHello
      // 失败）落下的「加载失败」不清除会永久遮住空态入口。
      sessionIdRef.current = null;
      // 快照确认无会话 → 同步复位 watch 注册标记（与上方终态分支同口径）：
      // 项目切换不重挂载本组件（list.tsx 的 project 来自 useParams、activeTab
      // 持久化，active 恒 true），主 effect 清理只关 EventSource 不清标记——
      // 残留的 true 会让切离分面时对无会话的新项目发 DELETE /api/session/watch
      // → 404 → console.error，污染 no_console_error 断言。
      watchRegisteredRef.current = false;
      setStarted(false);
      syncEvents([]);
      setTruncated(false);
      setError('');
      return false;
    }
  };

  // 快照应用（carried 合并形态，code-review item b2ce2f362979）：与 applySnapshot
  // 并列，事件应用由整表替换改为「服务端快照为主序、本地已有而快照缺失的事件
  // 按与快照窗口的时序关系拆分补回：早于快照首事件的（长会话环形缓冲滑出的
  // 早期事件，item 51f0857322b5）前插回快照之前，其余经 appendEvents 尾补回
  // （uuid 并回去重集合）」。SSE 每事件只推一次，
  // 快照 GET 发起后被服务端快照遗漏、却在快照应用前经 SSE append 的事件，整表
  // 替换会把它从渲染列表抹掉、seenUuidsRef 按 snapshot 重建后其 uuid 一并移除
  // （下次重连/重拉前不再出现）。afterHello 第二次重拉（code-review item
  // 1371d6ca978a）与 handleStart 的快照拉取共用本实现，消除单点修复导致的路径
  // 漂移。无 uuid 事件（stderr / session_ended 合成）无法去重且快照含同类事件，
  // 维持全量重拉丢弃的既有语义，不补回。
  const applySnapshotCarried = (data: Awaited<ReturnType<typeof getSession>>) => {
    // 调用点均在 data.session 存在时进入；空会话委托 applySnapshot 兜底
    if (!data.session) {
      applySnapshot(data);
      return;
    }
    const snapshotEvents = data.events || [];
    const snapshotUuids = new Set(
      snapshotEvents
        .map((ev) => (ev ? (ev.uuid as string | undefined) : undefined))
        .filter((u): u is string => Boolean(u)),
    );
    // carried 须在 applySnapshot（内部 syncEvents 整表替换 eventsRef）前取样
    const local = eventsRef.current;
    // 时序边界（code-review item 51f0857322b5）：服务端缓冲是
    // deque(maxlen=4000) 环形缓冲（session_manager.py SESSION_EVENT_BUFFER），
    // 长会话下早期事件已从快照滑出而本地列表仍保有窗口外近期事件（eventsRef
    // 已设 MAX_LOCAL_EVENTS 上限、超限裁最旧端，item 28d5d8c4adc8），carried 若一律尾
    // 追加，会把最老的滑出事件排到最新消息之后且每次重连都维持错序。快照是
    // 服务端事件序列的连续尾窗、本地到达序与之同序，故以「快照首事件 uuid
    // 在本地列表中的下标」为边界：carried 中位于该下标之前的事件早于快照
    // 窗口（前插回快照之前），位于其后的才是快照 GET 发起后经 SSE 先行到达、
    // 快照未涵盖的窗口内事件（保持尾补回）。快照为空或首事件 uuid 在本地
    // 找不到（如服务端重启后的新会话代际）时 boundary=-1，全部按尾补回——
    // 不误删本地已有事件，保持断线窗口合并语义。
    const firstUuid = snapshotEvents.find((ev) => Boolean(ev && ev.uuid))?.uuid;
    const boundary = firstUuid
      ? local.findIndex((ev) => (ev ? (ev.uuid as string | undefined) : undefined) === firstUuid)
      : -1;
    const older: SessionEvent[] = [];
    const newer: SessionEvent[] = [];
    for (let i = 0; i < local.length; i++) {
      const ev = local[i];
      const uuid = ev ? (ev.uuid as string | undefined) : undefined;
      if (!uuid || snapshotUuids.has(uuid)) continue;
      if (boundary >= 0 && i < boundary) older.push(ev);
      else newer.push(ev);
    }
    applySnapshot(data);
    // 早期滑出事件插回快照之前（appendEvents 只会尾追加，须手工前插），
    // uuid 并回去重集合（与 appendEvents 的登记同口径）
    if (older.length > 0) {
      const seen = seenUuidsRef.current;
      for (const olderEv of older) {
        const u = olderEv.uuid as string | undefined;
        if (u) seen.add(u);
      }
      const merged = [...older, ...eventsRef.current];
      eventsRef.current = merged;
      setEvents(merged);
      // 前插保留的窗口外事件可使本地列表超出上限：合并后的统一收口裁剪
      // （尾追加路径由 appendEvents 内部收口），uuid 随裁剪同步收缩
      trimLocalEvents();
    }
    appendEvents(newer);
    // 终态复扫（code-review item 1c9e0dab5454）：快照 GET 发起后、应用前经 SSE
    // 先行到达的 session_ended 落在 newer 中，而上方 applySnapshot 的快照终态
    // 扫描只看快照缓冲（不含该事件），会把已判终态的 ended 回退为 false，输入
    // 区/停止按钮误恢复可用，直到下一次快照/轮询才自愈。与 onmessage 增量扫描
    // 同口径补扫 newer，命中即复置终态并清 watch 注册标记（服务端会话已移除）。
    if (newer.some((e) => e?.type === 'session_ended')) {
      setEnded(true);
      watchRegisteredRef.current = false;
    }
  };

  // 拉全量 + 建立 SSE（分面激活时执行；切离后重新接回）
  useEffect(() => {
    if (!active || !project) return;
    let disposed = false;
    setStreamDown(false);
    // 新连接在 onopen 前不算连接态（跨 effect 运行残留的 true 会让 watch 重试
    // 成功路径误判 SSE 已恢复而提前清失败态）
    sseConnectedRef.current = false;

    // ── SSE 断流降级（code-review item 2303508d27ff）──
    // onerror 只靠「原生自动重连」不够：非 200 响应（连接数满 503 等）会让
    // 浏览器永久停止重连，本组件又无 list.tsx / overview 的心跳轮询兜底。
    // 置失败态（界面提示「实时更新不可用」）+ 低频 REST 快照轮询（复用组件级
    // 快照串行链，carried 合并不丢窗口内事件）；onopen 清失败态并停轮询。
    let pollTimer: ReturnType<typeof setInterval> | null = null;
    const stopStreamFallback = () => {
      if (pollTimer) {
        clearInterval(pollTimer);
        pollTimer = null;
      }
    };
    const pollSnapshot = () => {
      // 静默重拉（不动 loading，避免每次轮询闪 Spin）；任务内部自吞错，
      // 失败等下一轮，不置 error（error 分支会替换整块对话视图）
      void enqueueSnapshotLoad(async () => {
        try {
          const data = await getSession(project);
          if (disposed) return;
          if (data.session) applySnapshotCarried(data);
          else applySnapshot(data);
        } catch {
          // 兜底轮询失败：保持失败态，等下一轮
        }
      });
    };
    const startStreamFallback = () => {
      // 幂等：断线重连风暴中 onerror 可连发，只起一个轮询
      if (pollTimer) return;
      pollSnapshot();
      pollTimer = setInterval(pollSnapshot, STREAM_FALLBACK_MS);
    };

    // ── watch 注册失败退避重试（code-review item a67da3eb2778）──
    // afterHello 注册失败只记日志的话，连接存活期内（hello 不再来）再无任何
    // 注册机会。有限次固定间隔重试，cid 取注册时刻的 cidRef.current（断线
    // 重连后是新连接的 cid）；成功即复位计数与失败态并 carried 重拉一次
    // （兜住注册失败期间的窗口，同 afterHello 的 design D6 口径）；全部耗尽
    // 置「实时推送不可用」失败态并降级轮询，与 SSE 断流共用提示位。
    let watchRetryCount = 0;
    let watchRetryTimer: ReturnType<typeof setTimeout> | null = null;
    const clearWatchRetryTimer = () => {
      if (watchRetryTimer) {
        clearTimeout(watchRetryTimer);
        watchRetryTimer = null;
      }
    };
    const scheduleWatchRetry = () => {
      if (disposed) return;
      if (watchRetryCount >= WATCH_RETRY_MAX) {
        setStreamDown(true);
        startStreamFallback();
        return;
      }
      watchRetryCount += 1;
      clearWatchRetryTimer();
      watchRetryTimer = setTimeout(() => {
        watchRetryTimer = null;
        if (disposed) return;
        const liveCid = cidRef.current;
        if (!liveCid) return;
        void enqueueSnapshotLoad(async () => {
          try {
            if (disposed) return;
            await registerSessionWatch(projectRef.current, liveCid);
            // 置位口径与 afterHello 相同（await 返回后无条件置位）
            watchRegisteredRef.current = true;
            if (disposed) return;
            watchRetryCount = 0;
            // 仅 SSE 处于连接态才清失败态（code-review item 32630a523c16）：
            // 失败态若先由 onerror 置位（SSE 仍断流、兜底轮询在跑），REST 注册
            // 成功不代表事件通道恢复，无条件清除会抹掉降级提示、与「已降级为
            // 低频刷新」的告知语义相悖——保持失败态与轮询，等 onopen（SSE 真恢复
            // 信号）再清；失败态纯由 watch 重试置位（SSE 连接正常）时照旧立即清除。
            if (sseConnectedRef.current) setStreamDown(false);
            const again = await getSession(projectRef.current);
            if (disposed) return;
            // 空会话兜底（code-review item 48682b16b4cc）：会话恰在注册成功与
            // 本 GET 之间被服务端整体摘除（session_ended 事件未被 watch 收到）时，
            // 不复位会让面板滞留 started=true 旧状态直到下一次快照才自愈；
            // 与 pollSnapshot 的空会话复位口径对齐
            if (again.session) applySnapshotCarried(again);
            else applySnapshot(again);
          } catch (e) {
            if (disposed) return;
            console.error('Failed to register session watch (retry):', e);
            scheduleWatchRetry();
          }
        });
      }, WATCH_RETRY_INTERVAL_MS);
    };
    // 经 ref 暴露给组件级回调（code-review item 87c796fb6050）：handleStart
    // 空态补注册失败与 afterHello 同口径走有限次退避重试
    scheduleWatchRetryRef.current = scheduleWatchRetry;

    // 快照加载串行化（code-review item 112623f4c6ed）：挂载时 loadAll 与
    // hello 触发的 afterHello 重载并发执行、各自带全量快照调 syncEvents、无
    // 排序守卫——早发出者后返回时旧快照覆盖新快照，中间送达的事件从渲染
    // 列表丢失。经 promise 链按发起顺序串行应用快照（后应用的必然是更晚
    // 发起的加载，包含更新的服务端状态）。链本体在组件级（loadChainRef，
    // item e3b97bedcb43）：handleStart 的快照应用须并入同一链。


    const loadAll = () =>
      enqueueSnapshotLoad(async () => {
        try {
          setLoading(true);
          const data = await getSession(project);
          if (disposed) return;
          applySnapshot(data);
        } catch (e) {
          if (!disposed) setError(e instanceof Error ? e.message : String(e));
        } finally {
          if (!disposed) setLoading(false);
        }
      });

    // 注册 watch 后重拉一次（兜住注册前的窗口）。
    // 无会话项目（空态）不注册 watch：注册必然 404 → console.error，
    // 污染 web 场景 no_console_error 断言（验证 BUG-01 实证）。
    // 错误分支「重试」按钮的重跑入口（code-review item ca2aab0e3956）
    reloadRef.current = () => {
      void loadAll();
    };

    const afterHello = (cid: string) =>
      enqueueSnapshotLoad(async () => {
        try {
          const data = await getSession(project);
          if (disposed) return;
          const snapshotEnded = applySnapshot(data);
          // 终态会话跳过 watch 注册（code-review item d8e51da1b3c9）：快照含
          // session_ended 时服务端已移除会话（_terminate 先 append 终态再摘除），
          // 注册毫无意义；且服务端在 GET 响应生成后、本 POST 到达前完成摘除的
          // 竞态窗口内注册必 404 → console.error，污染 no_console_error 断言
          // （与 onmessage / applySnapshot 的终态扫描同口径）。
          if (data.session && !snapshotEnded) {
            // 新 hello（断线重连）到来即作废在途的重试安排并复位计数
            // （a67da3eb2778）：本轮注册是最新尝试，旧定时器继续跑会重复注册
            clearWatchRetryTimer();
            watchRetryCount = 0;
            // 会话存在：用服务端 hello 分配的 cid 注册 watch
            try {
              await registerSessionWatch(project, cid);
              watchRegisteredRef.current = true;
            } catch (e) {
              console.error('Failed to register session watch:', e);
              // 安排有限次退避重试（旧实现只记日志：EventSource 不断线
              // hello 不再来，本连接内再无注册机会，会话事件静默丢失）
              scheduleWatchRetry();
            }
            // 注册后重拉一次（兜住注册前的窗口，design D6）。
            // carried 合并而非整表替换（code-review item 1371d6ca978a）：本 GET
            // 发起后被服务端快照遗漏、却在快照应用前经 SSE append 的事件不被
            // 抹掉；合并实现单源于 applySnapshotCarried（item b2ce2f362979），
            // 与 handleStart 复用。
            const again = await getSession(project);
            if (disposed) return;
            // 空会话兜底（code-review item 48682b16b4cc）：会话恰在两次 GET 之间
            // 被服务端整体摘除（无 session_ended 事件或未被 watch 收到）时，
            // 不复位会让面板滞留 started=true 旧状态直到下一次快照才自愈；
            // 与 pollSnapshot 的空会话复位口径对齐
            if (again.session) {
              applySnapshotCarried(again);
            } else {
              applySnapshot(again);
            }
          }
          // 无会话（空态）或快照已判终态：跳过注册，避免 404 + console.error
        } catch (e) {
          if (!disposed) setError(e instanceof Error ? e.message : String(e));
        }
      });

    void loadAll();

    const es = new EventSource(STREAM_URL);
    // 连接（重新）建立：清除断流失败态并停兜底轮询（2303508d27ff 的恢复路径）
    es.onopen = () => {
      if (disposed) return;
      sseConnectedRef.current = true;
      setStreamDown(false);
      stopStreamFallback();
    };
    es.onmessage = (ev: MessageEvent) => {
      if (disposed) return;
      let msg: { type?: string; cid?: string; session_id?: string; events?: SessionEvent[] } = {};
      try {
        msg = JSON.parse(ev.data);
      } catch {
        return;
      }
      // 服务端在 hello 分配连接 cid——watch 注册必须用它
      if (msg.type === 'hello' && msg.cid) {
        cidRef.current = msg.cid;
        void afterHello(msg.cid!);
        return;
      }
      const sid = sessionIdRef.current;
      if (!sid) return;
      if (msg.type === 'session_events' && msg.session_id === sid && msg.events) {
        // 终态事件先置状态（输入区禁用）
        for (const e of msg.events) {
          // 空元素守卫与 appendEvents 同口径（code-review item b4e12a0fc804）：
          // 单帧混入 null/undefined 时跳过该元素而非抛 TypeError 中断本帧
          // 后续事件的 append
          if (!e) continue;
          if (e.type === 'session_ended') {
            setEnded(true);
            // 会话已终止（用户停止 / 空闲超时回收 / 进程退出）：服务端会话
            // 已移除，此后注销 watch 必 404（服务端无会话判定）→ 标记未注册，
            // 切离分面不再发 DELETE，避免污染 no_console_error 断言
            watchRegisteredRef.current = false;
          }
        }
        appendEvents(msg.events);
      }
    };
    es.onerror = () => {
      // 原生自动重连只覆盖瞬态断线；非 200 响应（连接数满 503 等）会让浏览器
      // 永久停止重连——置失败态并降级低频快照轮询兜底（2303508d27ff），
      // 连接恢复由 onopen 清除失败态并停轮询
      if (disposed) return;
      // 旧连接的 watch 随连接消亡（服务端断连即摘除整个连接），注册标记指向
      // 已失效 cid，理应同步失效（code-review item df599f756da6）：不复位的话，
      // 重连后新 cid 注册成功前用户切离分面，会按旧 cid 发 DELETE watch——
      // unwatch 对不存在连接虽静默 no-op（core/dashboard/sse.py），但会话已被
      // 服务端摘除时路由层先判无会话返回 404 → console.error，污染
      // no_console_error 断言。重连重新注册不受影响：hello → afterHello 按
      // 新 cid 无条件注册，不读本标记。
      sseConnectedRef.current = false;
      watchRegisteredRef.current = false;
      setStreamDown(true);
      startStreamFallback();
    };

    return () => {
      disposed = true;
      reloadRef.current = null;
      scheduleWatchRetryRef.current = null;
      stopStreamFallback();
      clearWatchRetryTimer();
      es.close();
    };
  }, [active, project]);

  // 切离分面：注销 watch（需服务端 cid）+ 清空本地状态，切回重新接回；
  // 仅释放订阅，MUST NOT 终止会话进程本身
  useEffect(() => {
    if (!active) {
      const cid = cidRef.current;
      // 异步注销，不阻塞切面；仅对实际注册过的 watch 注销——
      // 无会话项目从未注册，注销未注册 cid 会 404（服务端无会话判定）
      if (watchRegisteredRef.current && cid && projectRef.current) {
        void unregisterSessionWatch(projectRef.current, cid).catch(() => {});
        watchRegisteredRef.current = false;
      }
      // 注销后清空：active→false 转换路径下方清理函数已先行注销（标记已否），
      // cid 不清会在再次切离时被重复 DELETE（404）
      cidRef.current = null;
      // 切离时清空本地状态，切回重新接回（events/started 由 loadAll 重置）；
      // 输入草稿在 SessionComposer 内按 project 键持久化，切离不清（spec：
      // 切页签草稿保留）
      sessionIdRef.current = null;
      setEnded(false);
      // ref 与 state 同步复位（code-review item 3ea48a0e30b5）：在飞请求的
      // finally 也会复位 ref，但晚于切离时刻——切回分面立即重发会被残留的
      // ref 误拦，与上方 setSending/setStopping(false) 同口径就地清掉。
      sendingRef.current = false;
      stoppingRef.current = false;
      startRef.current = false;
      setSending(false);
      setStopping(false);
      // loading 复位（code-review item 9c07fe612f2d）：loadAll 的 finally 以
      // !disposed 守卫复位，切离中断的在途加载不再回落——不补复位的话，
      // inactive 期间（面板仍被渲染的形态）会持续显示「加载会话...」
      setLoading(false);
    }
    // 卸载守卫（code-review item e71b2c2de7cf）：组件在 active===true 且已注册
    // watch 时被销毁，本 effect 主体不会「再跑」（React 卸载只执行清理函数，
    // 旧注释声称的「卸载时本 effect 会再跑」不成立）——服务端订阅泄漏，只剩
    // 显式 !active 转换才释放。清理函数覆盖 unmount（及 active 翻转重建）：
    // 仅注销实际注册过的 watch，并先行清标记，防 active→false 路径主体重复
    // DELETE（404 污染 no_console_error 断言）。
    return () => {
      if (watchRegisteredRef.current) {
        const cid = cidRef.current;
        watchRegisteredRef.current = false;
        if (cid && projectRef.current) {
          void unregisterSessionWatch(projectRef.current, cid).catch(() => {});
        }
      }
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [active]);

  // 开始会话：显式创建（唯一允许启动进程的端点），成功后拉全量。
  // 各 await 后的切离守卫（code-review item 58ec4693e77c）：经 activeRef 校验
  // 分面仍激活，失配即中止——切离清理 effect 已释放订阅并清空状态，续跑不得
  // 回写 sessionIdRef/started、注册 watch 或应用快照（提前 return 仍走 finally
  // 复位 loading，不悬置加载态）。
  const handleStart = async () => {
    // 重入守卫（code-review item 038d04ea5c2e，与 sendingRef/stoppingRef 同
    // 口径）：state 驱动的防重存在 React 调度间隙（L169-176 论述），间隙内
    // 连点会并发发出两次 startSession；经 ref 写读同帧原子短路，各 await 后
    // 的提前 return 仍走 finally 复位。
    if (startRef.current) return;
    startRef.current = true;
    // 跨项目切换守卫（code-review item 794f1b8ac9be）：activeRef 只覆盖切离/
    // 卸载，分面保持激活的跨项目切换（list.tsx 的 project 来自 useParams、
    // 组件不重挂载）不拦——各 await 之间闭包 project 停留发起帧，会以旧项目
    // 名注册 watch（切离注销按 projectRef.current 新项目名必 404，服务端订阅
    // 残留）、拉旧项目快照写入已显示新项目的面板（短暂串显）。发起帧捕获
    // 项目名，各 await 后失配即中止（同切离守卫口径：提前 return 仍走
    // finally 复位 loading）。
    const startProject = projectRef.current;
    const projectStale = () => projectRef.current !== startProject;
    try {
      setLoading(true);
      const res = await startSession(startProject);
      if (!activeRef.current || projectStale()) return;
      sessionIdRef.current = res.session.id;
      setStarted(true);
      setEnded(false);
      // 会话由无变有：此前空态 when hello 到达时 afterHello 跳过了 watch 注册
      // （无会话注册必然 404），若此刻不补注册，SSE 将永不推送本会话事件——
      // 发送消息后用户消息不回显、消息流无反馈（本项目验证实测）。用当前
      // hello 分配的连接 cid 补注册；EventSource 自动重连后 afterHello 也会
      // 以新 cid 兜底注册（会话已存在分支），二者不冲突。
      if (!watchRegisteredRef.current && cidRef.current && sessionIdRef.current) {
        try {
          await registerSessionWatch(projectRef.current, cidRef.current);
          // 注册返回前已切离/已切换项目：不置注册标记（非激活面板不得标记
          // 持有订阅；旧项目名注册的 watch 切离时按新项目名注销必 404）
          if (!activeRef.current || projectStale()) return;
          watchRegisteredRef.current = true;
        } catch (e) {
          console.error('Failed to register session watch:', e);
          // 补注册失败与 afterHello 同口径重试（code-review item 87c796fb6050）：
          // EventSource 不断线则 hello 不再来，只记日志则本连接内再无注册
          // 机会，本会话事件静默丢失；经主 effect 暴露的共享重试入口有限次
          // 退避重试（重试目标取注册时刻 cidRef.current，耗尽降级轮询兜底）。
          // effect 未挂载（分面未激活）时入口为 null，可选调用静默跳过。
          scheduleWatchRetryRef.current?.();
        }
      }
      // carried 合并而非整表替换（code-review item b2ce2f362979）：startSession
      // 响应返回（sessionIdRef 已置位、watch 已补注册，SSE 帧可先行 append）到
      // 本 GET 快照落定之间存在竞态窗口，整表替换会把窗口内未进入服务端快照的
      // 事件永久丢弃且 uuid 被去重集合剔除；与 afterHello 第二次重拉共用
      // applySnapshotCarried。经组件级串行链应用（code-review item e3b97bedcb43）：
      // 排队在途的 afterHello 旧快照之后落盘，避免其晚到时整表替换把面板翻回
      // 空态（后应用的必然是更晚发起的加载）。
      await enqueueSnapshotLoad(async () => {
        // 任务可能排队在 afterHello 旧快照之后延后执行：发起前再校验一次
        if (!activeRef.current || projectStale()) return;
        const data = await getSession(projectRef.current);
        // 快照返回前已切离/已切换项目：不应用快照（避免非激活面板重新持有
        // 一份活跃状态、旧项目快照串显到新项目面板）
        if (!activeRef.current || projectStale()) return;
        if (data.session) {
          applySnapshotCarried(data);
        } else {
          // 空会话兜底（code-review item 1ae2f19b442c）：startSession 成功后、
          // 快照 GET 前会话被服务端整体摘除（如进程启动即崩）时，不复位会让
          // 面板滞留 started=true 旧状态、输入区可编辑但发送必败，直到下一次
          // 快照才自愈；与 pollSnapshot / watch 重试成功路径 / afterHello
          // 第二次重拉的三处空会话复位口径对齐
          applySnapshot(data);
        }
      });
      // 快照落定前已切离/已切换项目：不回写状态（同上）；正常路径清 error
      if (!activeRef.current || projectStale()) return;
      setError('');
    } catch (e) {
      // 失败前已切离/已切换项目：不落错误（同上方各 await 后守卫口径，旧项目
      // 的错误文案与「重试」按钮不得串显到新项目面板；finally 复位 loading 保留）
      if (!activeRef.current || projectStale()) return;
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      startRef.current = false;
      setLoading(false);
    }
  };

  // 发送（add-session-composer 3.2）：改由 SessionComposer 的发送单点回调，
  // 文本参数化；失败 reject 让 composer 还原草稿（成功清空由 composer 处理）。
  const handleSend = async (text: string) => {
    const t = text.trim();
    if (!t || sendingRef.current || ended) return;
    sendingRef.current = true;
    if (!sessionIdRef.current) {
      message.error('会话尚未启动');
      sendingRef.current = false;
      throw new Error('会话尚未启动');
    }
    // 跨项目切换守卫（code-review item 8984465fd469，同 handleStart 口径）：
    // 分面保持激活的跨项目切换（list.tsx 的 project 来自 useParams、组件
    // 不重挂载）不触发任何清理——await 往返期间切到另一项目，闭包 project
    // 停留发起帧，resolve 会让 composer 清空草稿（消息已落旧项目会话，新
    // 项目面板却无任何反馈）。发起帧捕获项目名，返回后失配即 reject：
    // composer 还原草稿（reject 经其调用方吞掉，不弹「发送失败」——消息
    // 实际已送达旧项目）。
    const startProject = projectRef.current;
    setSending(true);
    try {
      await sendSessionMessage(startProject, t);
    } catch (e) {
      // 瞬态发送失败经 message.error 呈现（同 handleStop 口径），不落 error
      // state——error 分支会替换整块对话视图+输入区（转录被隐藏、无法就地
      // 重试，code-review item b1609f78d29c）。rethrow 让 composer 把输入
      // 还原为发送前文本（失败不丢用户输入）。
      // 失败前已切离/已切换项目：不弹错误 toast（同 handleStart catch 守卫
      // 口径，旧项目的「发送失败」文案不得串显到新项目面板）；仍 rethrow 让
      // composer 还原草稿（reject 经其调用方吞掉，不弹「发送失败」）。
      if (!activeRef.current || projectRef.current !== startProject) {
        throw e instanceof Error ? e : new Error(String(e));
      }
      message.error(`发送失败：${e instanceof Error ? e.message : String(e)}`);
      throw e instanceof Error ? e : new Error(String(e));
    } finally {
      sendingRef.current = false;
      setSending(false);
    }
    // await 返回后已切离/已切换项目：不 resolve（见上方守卫说明，resolve
    // 会清空 composer 草稿），以 reject 终止、不落任何本地状态
    if (!activeRef.current || projectRef.current !== startProject) {
      throw new Error('会话面板已切换项目');
    }
  };

  const handleStop = async () => {
    if (stoppingRef.current || ended) return;
    stoppingRef.current = true;
    // 跨项目切换守卫（code-review item 8984465fd469，同 handleStart 口径）：
    // await 往返期间切换项目后回写 ended 会把新项目面板短暂打入终态
    // （输入区禁用），摘 watchRegisteredRef 标记还会让新项目会话的 watch
    // 切离时漏注销——失配即不回写任何本地状态。
    const startProject = projectRef.current;
    setStopping(true);
    try {
      await stopSession(startProject);
      if (!activeRef.current || projectRef.current !== startProject) return;
      setEnded(true);
      // 会话已终止：服务端会话已移除，后续注销 watch 必 404——
      // 标记未注册，切离分面不再发 DELETE（避免污染 no_console_error 断言）
      watchRegisteredRef.current = false;
    } catch (e) {
      // 失败前已切离/已切换项目：不弹错误 toast（同 handleStart catch 守卫
      // 口径，旧项目的「停止失败」文案不得串显到新项目面板）。
      if (!activeRef.current || projectRef.current !== startProject) return;
      message.error(`停止失败：${e instanceof Error ? e.message : String(e)}`);
    } finally {
      stoppingRef.current = false;
      setStopping(false);
    }
  };

  // 补全候选拉取（add-session-composer 3.1）：会话在飞时拉 commands/files。
  // init 事件在进程启动后数百 ms 才到，首拉可能拿到空数组——3s 后补拉一次
  // （幂等覆盖）；端点封装吞错，空数组即无候选，不打断输入。
  useEffect(() => {
    if (!active || !project || !started) return;
    let disposed = false;
    let retryTimer: ReturnType<typeof setTimeout> | null = null;
    const load = () => {
      void fetchSessionCommands(project).then((c) => {
        if (disposed) return;
        setSlashCommands(c.slash_commands);
        setSkills(c.skills);
      });
      void fetchSessionFiles(project).then((f) => {
        if (!disposed) setFiles(f);
      });
    };
    load();
    retryTimer = setTimeout(load, 3000);
    return () => {
      disposed = true;
      if (retryTimer) clearTimeout(retryTimer);
    };
  }, [active, project, started]);

  // 事件→消息转换结果缓存（code-review item 6b5bd3346ec3）：与 ClaudeOutputPane
  // 同模式用 useMemo 缓存 runEventsToChatMessages。renderBody 是渲染期辅助函数
  // 且含早返回分支，hook 必须提升到组件顶层（无条件执行，遵守 hooks 规则），
  // 结果传入 renderBody 使用——否则每次渲染（含 loading/error 分支切换、父组件
  // 级联渲染）都对全部事件重跑转换，长会话下是可感知的重复开销。
  const chatMessages = useMemo(() => runEventsToChatMessages(events), [events]);

  // 截断提示条文字样式（code-review item 22baafa4128a）：含 token 的样式不能
  // 是纯模块级字面量，在组件内取 token 合成并 useMemo 缓存（token 引用稳定，
  // 不随渲染重建），供 renderBody 的截断分支引用
  const { token } = theme.useToken();
  const truncatedTextStyle = useMemo<CSSProperties>(
    () => ({ ...TRUNCATED_TEXT_STYLE_BASE, background: token.colorBgContainer }),
    [token],
  );

  // 渲染分支抽具名 helper（code-review item d42f28cde496）：渲染体原为
  // loading→error→!started→默认会话视图的链式嵌套三元（项目规则禁止），
  // 分支语义不可读；改 if/else 早返回，样式引用模块级常量。
  const renderBody = () => {
    if (loading) {
      return (
        <div style={LOADING_ROW_STYLE}>
          <Spin size="small" />
          <Typography.Text type="secondary">加载会话...</Typography.Text>
        </div>
      );
    }
    if (error) {
      return (
        <div style={COMPACT_NOTE_STYLE}>
          <Typography.Text type="danger">加载失败: {error}</Typography.Text>
          {/* 重试 = 清 error + 重跑加载路径（code-review item ca2aab0e3956：
              loadAll 经 reloadRef 从 effect 内暴露；旧实现只清 error，
              不发生任何实际重试） */}
          <Button
            onClick={() => {
              setError('');
              reloadRef.current?.();
            }}
          >
            重试
          </Button>
        </div>
      );
    }
    if (!started) {
      return (
        <div style={EMPTY_STATE_STYLE}>
          <Typography.Text type="secondary">尚未接入会话</Typography.Text>
          <Button type="primary" icon={<MessageOutlined />} onClick={() => void handleStart()}>
            开始会话
          </Button>
        </div>
      );
    }
    return (
      <>
        <div style={MESSAGE_AREA_STYLE}>
          <ClaudeMessageList messages={chatMessages} showThinking />
          {truncated ? (
            <div style={TRUNCATED_BAR_STYLE}>
              <Typography.Text type="secondary" style={truncatedTextStyle}>
                更早的消息已省略
              </Typography.Text>
            </div>
          ) : null}
        </div>
        {/* 输入区由 session-composer 控件承载（dashboard-live-session delta：
            发送/停止/终态禁用接既有逻辑；草稿持久化在控件内部按 project 键） */}
        <SessionComposer
          project={project}
          sending={sending}
          disabled={ended}
          onSend={handleSend}
          onStop={() => void handleStop()}
          stopping={stopping}
          canStop={started && !ended}
          slashCommands={slashCommands}
          skills={skills}
          files={files}
        />
      </>
    );
  };

  return (
    <div style={isMobile ? PANEL_LAYOUT_STYLE_MOBILE : PANEL_LAYOUT_STYLE}>
      {/* 实时更新不可用提示条（items 2303508d27ff / a67da3eb2778 共用提示位）：
          SSE 断流（503 等永久停止重连）或 watch 注册重试耗尽时可见降级提示 */}
      {streamDown ? (
        <div style={STREAM_DOWN_BAR_STYLE}>
          <Typography.Text type="warning">
            实时更新不可用：会话消息可能延迟，已降级为低频刷新
          </Typography.Text>
        </div>
      ) : null}
      {renderBody()}
    </div>
  );
}