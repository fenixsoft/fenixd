// SessionPanel.tsx — 项目级自由会话内联分面面板（add-project-detail-tabs D2）
//
// 由项目级会话全屏 Modal 迁移（Modal 外壳 → 「会话接入」分面内联容器），会话行为契约零变更：
// 打开流程：GET 拉全量缓冲 → EventSource('/api/stream') → hello 分支用服务端
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
} from '@/services/dashboard';
import type { SessionEvent } from '@/services/dashboard';
import { ClaudeMessageList, runEventsToChatMessages } from '@/components/claude-msg';
import { SessionComposer } from '@/components/claude-composer';
import { useIsMobile } from '@/hooks/useIsMobile';

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
  height: 'calc(100vh - 222px)',
  minHeight: 320,
};
const PANEL_LAYOUT_STYLE_MOBILE: CSSProperties = {
  display: 'flex',
  flexDirection: 'column',
  // 390×844 实测（Task 4.1，playwright + stub claude serve 实例）：详情页
  // 头部+分面页签在移动端占 222px，留 12px 底部呼吸 → 234。首版推定 168
  // 实测偏小，页面出现 54px 纵向溢出（898 vs 844）。
  height: 'calc(100dvh - 234px)',
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
  const [ended, setEnded] = useState(false);
  const [started, setStarted] = useState(false); // 会话是否已启动（session: null 时空态）
  const [truncated, setTruncated] = useState(false);
  const [error, setError] = useState('');
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
  // events state 仅有 syncEvents / appendEvents 两个变更点，两处同步维护本 ref。
  const eventsRef = useRef<SessionEvent[]>([]);
  const eventSourceRef = useRef<EventSource | null>(null);
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
      setEvents(eventsRef.current);
    }
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
    // 长会话下早期事件已从快照滑出而 eventsRef 只增不减，carried 若一律尾
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
    }
    appendEvents(newer);
  };

  // 拉全量 + 建立 SSE（分面激活时执行；切离后重新接回）
  useEffect(() => {
    if (!active || !project) return;
    let disposed = false;

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
            // 会话存在：用服务端 hello 分配的 cid 注册 watch
            try {
              await registerSessionWatch(project, cid);
              watchRegisteredRef.current = true;
            } catch (e) {
              console.error('Failed to register session watch:', e);
            }
            // 注册后重拉一次（兜住注册前的窗口，design D6）。
            // carried 合并而非整表替换（code-review item 1371d6ca978a）：本 GET
            // 发起后被服务端快照遗漏、却在快照应用前经 SSE append 的事件不被
            // 抹掉；合并实现单源于 applySnapshotCarried（item b2ce2f362979），
            // 与 handleStart 复用。
            const again = await getSession(project);
            if (disposed) return;
            if (again.session) {
              applySnapshotCarried(again);
            }
          }
          // 无会话（空态）或快照已判终态：跳过注册，避免 404 + console.error
        } catch (e) {
          if (!disposed) setError(e instanceof Error ? e.message : String(e));
        }
      });

    void loadAll();

    const es = new EventSource('/api/stream');
    eventSourceRef.current = es;
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
      // EventSource 原生自动重连
    };

    return () => {
      disposed = true;
      reloadRef.current = null;
      es.close();
      eventSourceRef.current = null;
    };
  }, [active, project]);

  // 切离分面：注销 watch（需服务端 cid）+ 清空本地状态，切回重新接回；
  // 仅释放订阅，MUST NOT 终止会话进程本身
  useEffect(() => {
    if (!active) {
      const cid = cidRef.current;
      // 异步注销，不阻塞切面；仅对实际注册过的 watch 注销——
      // 无会话项目从未注册，注销未注册 cid 会 404（服务端无会话判定）
      if (watchRegisteredRef.current && cid && project) {
        void unregisterSessionWatch(project, cid).catch(() => {});
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
      setSending(false);
      setStopping(false);
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
        if (cid && project) {
          void unregisterSessionWatch(project, cid).catch(() => {});
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
    try {
      setLoading(true);
      const res = await startSession(project);
      if (!activeRef.current) return;
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
          await registerSessionWatch(project, cidRef.current);
          // 注册返回前已切离：不置注册标记（非激活面板不得标记持有订阅）
          if (!activeRef.current) return;
          watchRegisteredRef.current = true;
        } catch (e) {
          console.error('Failed to register session watch:', e);
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
        const data = await getSession(project);
        // 快照返回前已切离：不应用快照（避免非激活面板重新持有一份活跃状态）
        if (!activeRef.current) return;
        if (data.session) {
          applySnapshotCarried(data);
        }
      });
      // 快照落定前已切离：不回写状态（同上）；正常路径清 error
      if (!activeRef.current) return;
      setError('');
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  };

  // 发送（add-session-composer 3.2）：改由 SessionComposer 的发送单点回调，
  // 文本参数化；失败 reject 让 composer 还原草稿（成功清空由 composer 处理）。
  const handleSend = async (text: string) => {
    const t = text.trim();
    if (!t || sending || ended) return;
    if (!sessionIdRef.current) {
      message.error('会话尚未启动');
      throw new Error('会话尚未启动');
    }
    setSending(true);
    try {
      await sendSessionMessage(project, t);
    } catch (e) {
      // 瞬态发送失败经 message.error 呈现（同 handleStop 口径），不落 error
      // state——error 分支会替换整块对话视图+输入区（转录被隐藏、无法就地
      // 重试，code-review item b1609f78d29c）。rethrow 让 composer 把输入
      // 还原为发送前文本（失败不丢用户输入）。
      message.error(`发送失败：${e instanceof Error ? e.message : String(e)}`);
      throw e instanceof Error ? e : new Error(String(e));
    } finally {
      setSending(false);
    }
  };

  const handleStop = async () => {
    if (stopping || ended) return;
    setStopping(true);
    try {
      await stopSession(project);
      setEnded(true);
      // 会话已终止：服务端会话已移除，后续注销 watch 必 404——
      // 标记未注册，切离分面不再发 DELETE（避免污染 no_console_error 断言）
      watchRegisteredRef.current = false;
    } catch (e) {
      message.error(`停止失败：${e instanceof Error ? e.message : String(e)}`);
    } finally {
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
              <Typography.Text type="secondary" style={{ fontSize: 12, background: '#fff', padding: '0 8px' }}>
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

  return <div style={isMobile ? PANEL_LAYOUT_STYLE_MOBILE : PANEL_LAYOUT_STYLE}>{renderBody()}</div>;
}