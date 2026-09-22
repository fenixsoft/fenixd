// QualityTab.tsx — 项目页「代码审查」分面（add-code-review-agent-and-quality-tab D7/5.2-5.10）
//
// 承载当前代码仓的 code-review 问题台账：
// - 可复选问题表格（严重度/问题/状态列，严重度与状态过滤排序）；
//   「问题」列两行堆叠：第一行 标题 + 文件:行（同行不换行）/ 第二行 内容
//   （内容最多两行，悬浮浮层显示全文）；
//   浮层用 Popover + Markdown 渲染（与「SPEC 开发」分面「名称」列的 Why 浮层同形制，
//   描述里的 `` `code` `` / 列表 / 表格按 Markdown 排版）
// - 右上角五个动作按钮（全库审查 / 当期审查 / 自动修复 / 生成修复 SPEC / 全部忽略）
//   「生成修复 SPEC」MUST 先弹确认框（含执行时间三档，2026-09-20 用户要求）；
//   时刻选择器与设置页「同意立项」共用 ScheduleFields（单一实现点）
// - 运行中真实进度条（done/total 百分比）+ 当前文件 + 取消按钮
// - 行操作：逐条「忽略」（open → ignored）、「清除归属」（in_spec → open）；
//   批量「全部忽略」= 把表格勾选的条目复制行操作的忽略语义（2026-09-20 用户要求）
//
// 配置归属（2026-09-19 用户决策）：本分面**只读触发与展示**，不再承载
// admin.code_review.enabled 开关——配置项归设置页「质量」页签统一管理
// （QualityPanel.tsx），分面承担的是「看结果 + 手动触发」。
//
// active 门控（对齐 SessionPanel）：仅在选中本分面时拉取数据与订阅 SSE，
// 未选中零请求（project-page-tabs 按需加载语义）。
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  App,
  Button,
  Card,
  Popover,
  Progress,
  Select,
  Space,
  Table,
  Tag,
  Typography,
} from 'antd';
import type { ColumnsType } from 'antd/es/table';
import Markdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { markdownComponents } from './SpecDocModal';
import {
  cancelRun,
  generateFixSpec,
  getCodeFixRunResult,
  getCodeReviewItems,
  getCodeReviewProgress,
  getConfig,
  setCodeReviewItemStatus,
  triggerCodeFixRun,
  triggerCodeReview,
} from '../../../services/dashboard';
import type { CodeFixRunResult, CodeReviewItem, CodeReviewProgress } from '../../../services/dashboard';
import CodeFixProgressCard from './CodeFixProgressCard';
import ScheduleFields, {
  describeStartAfter,
  isStartAfterValid,
  nextRunAtISO,
} from '../../../components/ScheduleFields';
import type { AcceptSchedule } from '../../../components/ScheduleFields';

interface QualityTabProps {
  project: string;
  active: boolean;
}

// 严重度排序权重（code-review item 2cde5d51a359）：spec 要求表格 MUST 支持按
// 严重度/状态过滤**与排序**，但严重度/状态列此前均无 sorter。
const SEVERITY_ORDER: Record<string, number> = {
  critical: 0,
  major: 1,
  minor: 2,
  info: 3,
};
const STATUS_ORDER: Record<string, number> = {
  open: 0,
  in_spec: 1,
  resolved: 2,
  ignored: 3,
};

const SEVERITY_COLOR: Record<string, string> = {
  critical: 'red',
  major: 'orange',
  minor: 'gold',
  info: 'blue',
};

const STATUS_TEXT: Record<string, string> = {
  open: 'open',
  in_spec: 'in_spec',
  resolved: 'resolved',
  ignored: 'ignored',
};

const STATUS_COLOR: Record<string, string> = {
  open: 'blue',
  in_spec: 'purple',
  resolved: 'green',
  ignored: 'default',
};

// ── 「问题」列单元格：两行堆叠 + 内容行悬浮浮层 ──────────────────────
// 行布局（2026-09-20 用户要求）：第一行 = 问题标题 + `文件:行`（同一行不换行，
// `文件:行` 过长时单行省略 + 原生 tooltip）；第二行 = 内容。
// 浮层形制对齐「SPEC 开发」分面「名称」列的 Why 浮层（Popover + Markdown 渲染）：
// 描述里常见 `` `code` `` / 列表 / 表格，纯文本 Tooltip 会原样显示反引号，
// 这里按 Markdown 排版。
// 宽度（2026-09-20 用户要求）：浮层宽度 = 所在「问题」列宽度的 80%——列宽随
// 视口自适应（无固定 width），故在悬浮时实测所在 td 宽度再换算，而非写死 px。
// 延迟（2026-09-20 用户要求）：鼠标悬停满 1s 才弹出浮层，快速划过不触发
// （避免浏览列表时浮层乱闪）；移出即时关闭并清除定时器。
const POPOVER_DELAY_MS = 1000;

function ProblemCell({ rec }: { rec: CodeReviewItem }) {
  const [open, setOpen] = useState(false);
  const [popoverWidth, setPopoverWidth] = useState<number>();
  const cellRef = useRef<HTMLDivElement>(null);
  const timerRef = useRef<number | null>(null);

  // 定时器统一清理：卸载 / 移出 / 重复进入都不会留下悬挂 timer
  const clearTimer = () => {
    if (timerRef.current !== null) {
      window.clearTimeout(timerRef.current);
      timerRef.current = null;
    }
  };

  const handleEnter = () => {
    clearTimer();
    // 宽度在延迟结束、真正弹出前实测（列宽可能因视口/内容变化）
    timerRef.current = window.setTimeout(() => {
      timerRef.current = null;
      const td = cellRef.current?.closest('td');
      const colWidth = td?.getBoundingClientRect().width ?? 0;
      if (colWidth > 0) setPopoverWidth(Math.round(colWidth * 0.8));
      setOpen(true);
    }, POPOVER_DELAY_MS);
  };

  const handleLeave = () => {
    clearTimer();
    setOpen(false);
  };

  useEffect(() => clearTimer, []);

  return (
    <div ref={cellRef}>
      <Space direction="vertical" size={2} style={{ width: '100%' }}>
        {/* 第一行：问题标题 + 文件:行（同一行，`文件:行` 过长时单行省略，
            不换行——用户 2026-09-20 要求） */}
        <div style={{ display: 'flex', alignItems: 'baseline', gap: 8, minWidth: 0 }}>
          <span style={{ fontWeight: 500, minWidth: 0 }}>{rec.title}</span>
          <Typography.Text
            code
            style={{ fontSize: 12, flex: '0 1 auto', minWidth: 0 }}
            ellipsis={{ tooltip: true }}
          >
            {rec.file}:{rec.line}
          </Typography.Text>
        </div>
        {/* 第二行：内容，最多两行，悬浮显示全文 */}
        <Popover
          open={open}
          placement="topLeft"
          content={
            <div
              style={{
                width: popoverWidth ? `${popoverWidth}px` : undefined,
                maxWidth: '80vw',
                fontSize: 13,
                lineHeight: 1.65,
              }}
            >
              <Markdown remarkPlugins={[remarkGfm]} components={markdownComponents}>
                {`[${rec.category}] ${rec.description}`}
              </Markdown>
            </div>
          }
        >
          <Typography.Paragraph
            type="secondary"
            style={{ fontSize: 12, marginBottom: 0 }}
            ellipsis={{ rows: 2, tooltip: false }}
            onMouseEnter={handleEnter}
            onMouseLeave={handleLeave}
          >
            [{rec.category}] {rec.description}
          </Typography.Paragraph>
        </Popover>
      </Space>
    </div>
  );
}

export default function QualityTab({ project, active }: QualityTabProps) {
  const { message, modal } = App.useApp();
  const [items, setItems] = useState<CodeReviewItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [selectedKeys, setSelectedKeys] = useState<React.Key[]>([]);
  const [severityFilter, setSeverityFilter] = useState<string | undefined>();
  const [statusFilter, setStatusFilter] = useState<string | undefined>('open');
  const [progress, setProgress] = useState<CodeReviewProgress | null>(null);
  const [generating, setGenerating] = useState(false);
  // 触发/取消请求进行中的 pending 门控（code-review item 133cba8a5748）：旧实现
  // 仅依据 progress 快照 disable 按钮、且 handleTrigger 只乐观写 runningRef 不
  // 置 progress，在「新一轮 run 已开始 / run 刚结束」窗口内可重复触发或取消到
  // 错误 review_id。用独立的 pending 态在这两个动作进行期间禁用按钮。
  const [actionPending, setActionPending] = useState(false);
  // 「自动修复」独立 pending 门控（add-code-fix-manual-trigger 4.1）：
  // 触发流程含最长 20s 的结果轮询，不复用 actionPending——否则轮询期间
  // 其余动作按钮被连带禁用 20s。
  const [fixRunPending, setFixRunPending] = useState(false);
  const pollTimerRef = useRef<number | null>(null);
  // 请求序号守卫（code-review item 103bd502bd1e）：loadItems 会被 SSE 回调、
  // 30s 心跳、轮询结束兜底与 filter 变化并发触发，较慢的早期响应会覆盖较新数据。
  const loadSeqRef = useRef(0);
  // 「已有任何数据」标记：后台刷新不置 loading，避免表格反复闪烁。
  const loadedOnceRef = useRef(false);

  // ── 数据拉取（active 门控：未选中零请求） ────────────────────────
  // opts.background：后台刷新（30s 心跳/SSE state|run_meta 帧/轮询完成兜底）
  // 置真——失败静默不弹 toast（code-review item 6e920015ea87）：瞬态后端故障
  // 不再每 30s（及每个 SSE 帧）弹「加载失败」直到恢复；仅用户动作（进入页签/
  // 切换过滤/手动触发后的刷新）报错。
  const loadItems = useCallback(async (opts?: { background?: boolean }) => {
    if (!active || !project) return;
    const seq = ++loadSeqRef.current;
    const firstLoad = !loadedOnceRef.current;
    try {
      // 仅首屏置 loading（code-review item 103bd502bd1e）：后台刷新不置，避免
      // 表格在 SSE/心跳驱动下反复闪烁。
      if (firstLoad) setLoading(true);
      const statuses = statusFilter ? [statusFilter] : undefined;
      const data = await getCodeReviewItems(project, statuses);
      if (seq !== loadSeqRef.current) return; // 过期响应丢弃（陈旧覆盖防护）
      setItems(data.items || []);
      loadedOnceRef.current = true;
    } catch (e) {
      if (seq !== loadSeqRef.current) return;
      if (!opts?.background) {
        message.error(`加载失败: ${e instanceof Error ? e.message : String(e)}`);
      }
    } finally {
      if (firstLoad && seq === loadSeqRef.current) setLoading(false);
    }
  }, [active, project, statusFilter, message]);

  // loadItems 的 ref 视图（code-review item 2723381276fb）：轮询 interval 这类
  // 长生命周期闭包经此读取最新 loader——statusFilter 变化会重建 loadItems，
  // interval 回调直呼创建时捕获的旧闭包会用旧过滤条件的结果覆盖正确过滤的列表。
  const loadItemsRef = useRef(loadItems);

  const loadProgress = useCallback(async () => {
    if (!active || !project) return;
    try {
      const p = await getCodeReviewProgress(project);
      setProgress(p);
      if (p.running) {
        // 运行中：轮询进度（2s），结束兜底刷新表格
        if (pollTimerRef.current !== null) return;
        pollTimerRef.current = window.setInterval(async () => {
          try {
            const p2 = await getCodeReviewProgress(project);
            setProgress(p2);
            if (!p2.running) {
              if (pollTimerRef.current !== null) {
                window.clearInterval(pollTimerRef.current);
                pollTimerRef.current = null;
              }
              // 运行结束：刷新问题表格（经 ref 取最新 loader，避免沿用创建
              // interval 时捕获的旧 statusFilter——见上方 loadItemsRef 注释；
              // 后台兜底刷新，失败静默）
              void loadItemsRef.current({ background: true });
            }
          } catch {
            // 轮询失败继续（下轮重试）
          }
        }, 2000);
      }
    } catch {
      // 进度读取失败静默（非关键路径）
    }
  }, [active, project, loadItems]);

  // 数据加载 effect（仅依赖 active/project/过滤条件）——与 SSE 订阅分离
  // （code-review item 797015d4ba47）：旧实现把 SSE/心跳与数据拉取放在同一
  // effect 且依赖 loadItems/loadProgress（二者又依赖 statusFilter），切换状态
  // 过滤时会重建 EventSource、重建心跳、清掉进度轮询，既造成连接抖动（/api/stream
  // 有连接数上限）也可能重置轮询状态机。
  useEffect(() => {
    if (!active || !project) return;
    void loadItems();
    void loadProgress();
  }, [active, project, loadItems, loadProgress]);

  // SSE 增量刷新订阅 + 心跳兜底（仅依赖 active/project，转义为 ref 读取最新
  // loader；loadItemsRef 声明在 loadProgress 之前供轮询回调共用）
  const loadProgressRef = useRef(loadProgress);
  useEffect(() => {
    loadItemsRef.current = loadItems;
    loadProgressRef.current = loadProgress;
  }, [loadItems, loadProgress]);

  useEffect(() => {
    if (!active || !project) return;
    let disposed = false;

    const es = new EventSource('/api/stream');
    es.onmessage = (ev: MessageEvent) => {
      if (disposed) return;
      let msg: { type?: string; project?: string } = {};
      try {
        msg = JSON.parse(ev.data);
      } catch {
        return;
      }
      // 订阅**后端真实存在**的事件（code-review item 1354814ba4bf）：旧实现监听
      // `code_review_updated` / `code_review_run_done`，但 core/dashboard/watcher.py
      // 只会广播 refresh / state / detail / run_events / run_meta / admin_activities
      // ——这两个事件全仓不存在，该「随 SSE 增量刷新」链路实际永不触发，数据新鲜度
      // 完全依赖 2s 轮询与 30s 心跳（心跳窗口内审查结果不刷新）。改为：
      // - `state`（watcher 的状态增量）中匹配本 project 的帧 → 刷新；
      // - `run_meta`（状态转换，低频）→ 刷新；
      // - 全局 `refresh` 心跳不在此消费（由下方 30s 心跳兜底，避免每 2s 全量重拉）。
      if (
        (msg.type === 'state' || msg.type === 'run_meta') &&
        (!msg.project || msg.project === project)
      ) {
        void loadItemsRef.current({ background: true });
        void loadProgressRef.current();
      }
    };
    es.onerror = () => {
      // EventSource 原生自动重连
    };

    // 心跳兜底：每 30s 刷新进度（运行中轮询已覆盖，此处只兜非运行态下的
    // 表格刷新——事件流不可达时数据仍保持新鲜）
    const heartbeat = window.setInterval(() => {
      if (!disposed) {
        void loadItemsRef.current({ background: true });
        void loadProgressRef.current();
      }
    }, 30000);

    return () => {
      disposed = true;
      es.close();
      window.clearInterval(heartbeat);
      if (pollTimerRef.current !== null) {
        window.clearInterval(pollTimerRef.current);
        pollTimerRef.current = null;
      }
    };
  }, [active, project]);

  // 未激活时清理轮询
  useEffect(() => {
    if (!active && pollTimerRef.current !== null) {
      window.clearInterval(pollTimerRef.current);
      pollTimerRef.current = null;
    }
  }, [active]);

  // ── 手动触发按钮（5.4） ────────────────────────────────────────
  const handleTrigger = async (scope: 'full' | 'window') => {
    const label = scope === 'full' ? '全库审查' : '当期审查';
    if (actionPending) return; // pending 门控（code-review item 133cba8a5748）
    setActionPending(true);
    try {
      await triggerCodeReview(project, scope);
      message.success(`${label} 已受理，daemon 将开始执行`);
      void loadProgress();
      void loadItems();
    } catch (e) {
      const errMsg = e instanceof Error ? e.message : String(e);
      if (errMsg.includes('已有审查在进行中')) {
        message.warning('已有审查在进行中');
      } else {
        message.error(`${label}失败: ${errMsg}`);
      }
    } finally {
      setActionPending(false);
    }
  };

  // ── 自动修复（add-code-fix-manual-trigger 4.1） ─────────────
  // 手动即临时授权：点击写文件信号，daemon 以 override_enabled=True 消费
  // （开关关闭也修这一批）。受理后 1s 间隔轮询判定结果（上限 20s），仅认
  // request_created 回链本次 requested_at 的结果；触发成功不额外操作——
  // CodeFixProgressCard 既有 2s 轮询自动接管进度展示。
  const handleTriggerFixRun = async () => {
    if (fixRunPending || actionPending) return; // pending 门控防连点
    setFixRunPending(true);
    try {
      const res = await triggerCodeFixRun(project);
      const wantedAt = res.requested_at;
      const deadline = Date.now() + 20_000;
      let result: CodeFixRunResult | null = null;
      while (Date.now() < deadline) {
        await new Promise((resolve) => setTimeout(resolve, 1000));
        try {
          const snap = await getCodeFixRunResult(project);
          if (snap.request_created && snap.request_created === wantedAt) {
            result = snap;
            break;
          }
        } catch {
          // 单轮读取失败不终止轮询（daemon 消费稍后补结果文件）
        }
      }
      if (result) {
        if (result.triggered) {
          message.success(result.message || '已投递一批自动修复，可在进度卡片查看进展');
        } else {
          // 拒绝原因（无待修条目/已有修复在跑/回归契约缺失等）由 daemon
          // 结果文件的 message 如实回显，不让用户对着无反应的按钮猜
          message.warning(result.message || `未能投递：${result.reason}`);
        }
      } else {
        message.info('触发结果尚未就绪，请稍后在进度卡片或 daemon 日志确认');
      }
    } catch (e) {
      const errMsg = e instanceof Error ? e.message : String(e);
      if (errMsg.includes('已有未消费的修复触发请求')) {
        message.warning(errMsg);
      } else {
        message.error(`自动修复失败: ${errMsg}`);
      }
    } finally {
      setFixRunPending(false);
    }
  };

  // ── 取消（5.5） ───────────────────────────────────────────────
  const handleCancel = async () => {
    // review_id 为空时给出可见反馈而非静默 return（code-review item 133cba8a5748：
    // 旧实现在按钮已渲染（progress.running 为真）却 review_id 缺失时什么都不做）。
    if (!progress?.review_id) {
      message.warning('进度信息尚未就绪（缺 review_id），请稍后重试');
      return;
    }
    if (actionPending) return;
    setActionPending(true);
    try {
      await cancelRun(project, progress.review_id);
      message.success('已受理取消请求，审查将停止');
    } catch (e) {
      message.error(`取消失败: ${e instanceof Error ? e.message : String(e)}`);
    } finally {
      setActionPending(false);
    }
  };

  // ── 生成修复 SPEC（5.6；2026-09-20 用户要求加确认框 + 执行时间） ──────
  //
  // 二次确认弹窗（Modal.confirm）里带执行时间三档选择，复用设置页「同意立项」
  // 的 ScheduleFields——两处的时刻语义（立即=null / 定时=UTC ISO / 手工激活
  // = 哨兵）必须同源。预填值取 self_evolution.spec_run_at（与设置页同一配置
  // 键），经 nextRunAtISO 换算成下一次到期时刻。
  const configStartAfter = async (): Promise<string | null> => {
    try {
      const cfg = await getConfig(project);
      return nextRunAtISO(cfg.self_evolution?.spec_run_at);
    } catch {
      // 配置读取失败不阻塞生成：按「立即执行」预填（用户仍可在弹窗里改）
      return null;
    }
  };

  // 弹窗重入门（code-review item 2639d933f356）：generating 在 onOk 内才置位，
  // 两次快速点击都能通过检查、各自 await configStartAfter 后各开一个确认框
  // （及两次 getConfig）。useRef 写读同帧原子：await 前先占住门，弹窗最终
  // 关闭再释放（afterClose 对 ok/cancel 两条路径都触发；onOk 校验失败保持
  // 弹窗打开期间门不释放，与「弹窗开着」一致）。
  const generateModalOpenRef = useRef(false);

  // 打开弹窗前把配置里的默认执行时刻算好（异步；算完再弹，避免弹窗内
  // 初始值闪一下从「立即」跳到「定时」）
  const handleGenerate = async () => {
    if (selectedKeys.length === 0 || generating || generateModalOpenRef.current) return;
    generateModalOpenRef.current = true;
    let initial: string | null;
    try {
      initial = await configStartAfter();
    } catch {
      // configStartAfter 内部已吞错，此处纯防御：取值失败释放重入门
      generateModalOpenRef.current = false;
      return;
    }
    const count = selectedKeys.length;
    const holder: AcceptSchedule = { startAfter: initial };
    modal.confirm({
      title: '生成修复 SPEC',
      width: 640,
      content: (
        <>
          <div style={{ marginBottom: 12 }}>
            将为选中的 {count} 条问题创建一个修复 SPEC 并进入流水线。
          </div>
          <ScheduleFields holder={holder} initial={initial} hint="该 SPEC 执行时间：" />
        </>
      ),
      okText: '生成',
      cancelText: '取消',
      onOk: async () => {
        // 哨兵 manual 不参与时刻校验（add-spec-manual-activation D11）；
        // 仅 ISO 定时需晚于当前时刻（与设置页「同意立项」同一判据）
        if (!isStartAfterValid(holder.startAfter)) {
          message.error('执行时间必须晚于当前时间');
          return Promise.reject(new Error('invalid start time'));
        }
        setGenerating(true);
        try {
          const result = await generateFixSpec(
            project,
            selectedKeys.map(String),
            holder.startAfter,
          );
          if (result.ok) {
            message.success(
              `已生成修复 SPEC：${result.spec_name}${describeStartAfter(holder.startAfter)}`,
            );
            setSelectedKeys([]);
            void loadItems();
          } else {
            message.error(result.error || '生成失败');
            // 失败时保留弹窗（用户看清文案再决定重试/改时刻）
            return Promise.reject(new Error(result.error || 'generate failed'));
          }
        } catch (e) {
          message.error(`生成失败: ${e instanceof Error ? e.message : String(e)}`);
          return Promise.reject(e instanceof Error ? e : new Error(String(e)));
        } finally {
          setGenerating(false);
        }
      },
      // 弹窗最终关闭（确定/取消两条路径）后释放重入门（见上方注释）
      afterClose: () => {
        generateModalOpenRef.current = false;
      },
    });
  };

  // ── 行操作（5.10）：忽略 / 清除归属 ─────────────────────────────
  const handleIgnore = async (item: CodeReviewItem) => {
    try {
      await setCodeReviewItemStatus(project, item.item_id, 'ignored');
      message.success('已忽略该问题');
      void loadItems();
    } catch (e) {
      message.error(`忽略失败: ${e instanceof Error ? e.message : String(e)}`);
    }
  };

  // ── 批量「全部忽略」（2026-09-20 用户要求）：把勾选条目全部置 ignored ──
  // 选中可能混入非 open 条目（in_spec/resolved），逐条忽略会让后端的
  // 「仅 open/ignored 可人工置入」约束报错；这里只对 open 条目发请求。
  // 用 Promise.allSettled 并发跑完整批，不因单条失败中断其余；结束后统一
  // 提示成功/失败计数并刷新列表（不做逐条 toast，避免刷屏）。
  const handleIgnoreAll = async () => {
    const targets = items.filter((it) => selectedKeys.includes(it.item_id) && it.status === 'open');
    if (targets.length === 0) {
      message.warning('选中条目中没有可忽略的 open 问题');
      return;
    }
    const results = await Promise.allSettled(
      targets.map((it) => setCodeReviewItemStatus(project, it.item_id, 'ignored')),
    );
    const failed = results.filter((r) => r.status === 'rejected').length;
    const ok = targets.length - failed;
    if (failed === 0) {
      message.success(`已忽略 ${ok} 条问题`);
    } else {
      message.warning(`已忽略 ${ok} 条，${failed} 条失败`);
    }
    setSelectedKeys([]);
    void loadItems();
  };

  const handleClearAttribution = async (item: CodeReviewItem) => {
    modal.confirm({
      title: '清除归属',
      content: `把「${item.title}」重置回 open 并清空所属修复 SPEC？`,
      okText: '清除',
      cancelText: '取消',
      onOk: async () => {
        try {
          await setCodeReviewItemStatus(project, item.item_id, 'open');
          message.success('已清除归属，条目回到默认列表');
          void loadItems();
        } catch (e) {
          message.error(`清除失败: ${e instanceof Error ? e.message : String(e)}`);
        }
      },
    });
  };

  // 过滤后的实际渲染行（useMemo 稳定身份，供表格与幽灵选中清理共用同一谓词）
  const filteredItems = useMemo(
    () =>
      items.filter(
        (it) =>
          (!severityFilter || it.severity === severityFilter) &&
          (!statusFilter || it.status === statusFilter),
      ),
    [items, severityFilter, statusFilter],
  );

  // 选中项与**实际渲染行**求交（code-review item 01f6207c6b11 + a4922e615ddf）：
  // 忽略/清除归属/后端流转为 resolved/in_spec、或严重度/状态过滤收窄后，旧
  // 选中 key 会残留为「幽灵选中」，使「已选 N 条」计数错误、并把不可见/
  // 已失效 item_id 提交给后端。旧实现只与服务端全量 items 求交且 deps 不含
  // 过滤器——severityFilter 收窄后现在不可见的键仍留在 selectedKeys 被提交；
  // 改为与 filteredItems 求交并把过滤值纳入依赖。
  useEffect(() => {
    setSelectedKeys((prev) => {
      const visible = new Set(filteredItems.map((it) => String(it.item_id)));
      const next = prev.filter((k) => visible.has(String(k)));
      return next.length === prev.length ? prev : next;
    });
  }, [filteredItems]);

  // 行操作渲染（code-review item ca92db5ea623 抽三元）：把原嵌套三元改为早返回。
  const renderOps = (rec: CodeReviewItem) => {
    if (rec.status === 'in_spec') {
      return (
        <Button size="small" type="link" onClick={() => void handleClearAttribution(rec)}>
          清除归属
        </Button>
      );
    }
    if (rec.status === 'open') {
      return (
        <Button size="small" type="link" danger onClick={() => void handleIgnore(rec)}>
          忽略
        </Button>
      );
    }
    return null;
  };

  const columns: ColumnsType<CodeReviewItem> = [
    {
      title: '严重度',
      dataIndex: 'severity',
      key: 'severity',
      width: 90,
      // critical > major > minor > info（code-review item 2cde5d51a359）
      sorter: (a: CodeReviewItem, b: CodeReviewItem) =>
        (SEVERITY_ORDER[a.severity] ?? 9) - (SEVERITY_ORDER[b.severity] ?? 9),
      render: (sev: string) => <Tag color={SEVERITY_COLOR[sev] || 'default'}>{sev}</Tag>,
    },
    {
      title: '问题',
      key: 'problem',
      render: (_: unknown, rec: CodeReviewItem) => <ProblemCell rec={rec} />,
    },
    {
      title: '状态',
      dataIndex: 'status',
      key: 'status',
      width: 100,
      sorter: (a: CodeReviewItem, b: CodeReviewItem) =>
        (STATUS_ORDER[a.status] ?? 9) - (STATUS_ORDER[b.status] ?? 9),
      render: (status: string) => (
        <Tag color={STATUS_COLOR[status] || 'default'}>{STATUS_TEXT[status] || status}</Tag>
      ),
    },
    {
      title: '操作',
      key: 'ops',
      width: 130,
      // 嵌套三元抽出为具名函数（code-review item ca92db5ea623）
      render: (_: unknown, rec: CodeReviewItem) => renderOps(rec),
    },
  ];

  const progressPercent =
    progress && progress.total > 0 ? Math.round((progress.done / progress.total) * 100) : 0;

  return (
    <Card variant="borderless">
      {/* 工具栏：左对齐（严重度/状态下拉框 + 已选计数），右对齐（三个动作按钮同排） */}
      <div
        style={{
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
          flexWrap: 'wrap',
          gap: 8,
          marginBottom: 8,
        }}
      >
        <Space wrap>
          <Select
            placeholder="严重度"
            allowClear
            style={{ width: 110 }}
            value={severityFilter}
            onChange={setSeverityFilter}
            options={[
              { value: 'critical', label: 'critical' },
              { value: 'major', label: 'major' },
              { value: 'minor', label: 'minor' },
              { value: 'info', label: 'info' },
            ]}
          />
          <Select
            placeholder="状态"
            style={{ width: 130 }}
            value={statusFilter}
            onChange={setStatusFilter}
            options={[
              { value: 'open', label: 'open（默认）' },
              { value: 'in_spec', label: 'in_spec' },
              { value: 'resolved', label: 'resolved' },
              { value: 'ignored', label: 'ignored' },
            ]}
          />
          <Typography.Text type="secondary" style={{ fontSize: 12 }}>
            已选 {selectedKeys.length} 条
          </Typography.Text>
        </Space>
        <Space wrap>
          {/* 三个触发按钮均为 primary（蓝底白字，用户 2026-09-22 要求，
              覆盖此前 2026-09-20 的「默认样式一致」约定）；
              「生成修复 SPEC」保持 primary（主操作按钮）；
              「全部忽略」为 primary + danger（红底白字，用户 2026-09-20 要求） */}
          <Button
            type="primary"
            disabled={progress?.running || actionPending}
            loading={actionPending}
            onClick={() => void handleTrigger('full')}
          >
            全库审查
          </Button>
          <Button
            type="primary"
            disabled={progress?.running || actionPending}
            loading={actionPending}
            onClick={() => void handleTrigger('window')}
          >
            当期审查
          </Button>
          {/* 「自动修复」（add-code-fix-manual-trigger）：手动触发即临时授权
              （开关关闭也修这一批），蓝底白字与相邻触发按钮一致；触发流程
              （含结果轮询）进行中呈 loading 态并防连点 */}
          <Button
            type="primary"
            disabled={actionPending}
            loading={fixRunPending}
            onClick={() => void handleTriggerFixRun()}
          >
            自动修复
          </Button>
          <Button
            type="primary"
            disabled={selectedKeys.length === 0}
            loading={generating}
            onClick={() => void handleGenerate()}
          >
            生成修复 SPEC{selectedKeys.length > 0 ? `（${selectedKeys.length}）` : ''}
          </Button>
          {/* 「全部忽略」：红底白字（type="primary" danger，用户 2026-09-20 要求），
              未勾选任何条目时禁用（selectedKeys 为空即无目标） */}
          <Button
            type="primary"
            danger
            disabled={selectedKeys.length === 0}
            onClick={() => void handleIgnoreAll()}
          >
            全部忽略{selectedKeys.length > 0 ? `（${selectedKeys.length}）` : ''}
          </Button>
        </Space>
      </div>

      {progress?.running ? (
        <Card size="small" style={{ marginBottom: 12, background: '#fafafa' }}>
          <Space direction="vertical" style={{ width: '100%' }} size={4}>
            <Space style={{ justifyContent: 'space-between', width: '100%' }}>
              <Typography.Text strong>
                审查进行中（{progress.review_kind || 'code-review'}）
              </Typography.Text>
              <Button size="small" loading={actionPending} onClick={() => void handleCancel()}>
                取消
              </Button>
            </Space>
            <Progress percent={progressPercent} status="active" />
            <Typography.Text type="secondary" style={{ fontSize: 12 }}>
              {progress.done}/{progress.total} 文件
              {progress.current ? ` · 当前：${progress.current}` : ''}
            </Typography.Text>
          </Space>
        </Card>
      ) : null}

      {/* 自动修复进度卡片（add-code-review-auto-fix，task 9.4）：与「审查进行中」
          卡片并存（两条进度各自独立读取/轮询，不共用响应字段）。active 门控沿用
          本分面约定（未选中零请求）；进入终态/收尾时回调刷新条目表格（核销/状态
          变化落台账后用户立即可见）。 */}
      <CodeFixProgressCard
        project={project}
        active={active}
        onSettled={() => void loadItems()}
      />

      <Table<CodeReviewItem>
        rowKey="item_id"
        loading={loading}
        dataSource={filteredItems}
        columns={columns}
        size="small"
        rowSelection={{
          selectedRowKeys: selectedKeys,
          onChange: (keys) => setSelectedKeys(keys),
        }}
        pagination={{ pageSize: 10, showSizeChanger: false, hideOnSinglePage: true }}
        locale={{ emptyText: '暂无未处理问题' }}
      />
    </Card>
  );
}