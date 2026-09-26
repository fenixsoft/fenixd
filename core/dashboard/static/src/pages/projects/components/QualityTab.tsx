// QualityTab.tsx — 项目页「代码审查」分面（add-code-review-agent-and-quality-tab D7/5.2-5.10）
//
// 承载当前代码仓的 code-review 问题台账：
// - 可复选问题表格（严重度/问题/状态列，严重度与状态过滤排序）；
//   「问题」列两行堆叠：第一行 标题 + 文件:行（同行不换行）/ 第二行 内容
//   （内容最多两行，悬浮浮层显示全文）；
//   浮层用 Popover + Markdown 渲染（与「功能开发」分面「名称」列的 Why 浮层同形制，
//   描述里的 `` `code` `` / 列表 / 表格按 Markdown 排版）
// - 右上角五个动作按钮（全库审查 / 当期审查 / 自动修复 / 生成修复 SPEC / 全部忽略）
//   「生成修复 SPEC」MUST 先弹确认框（含执行时间三档，2026-09-20 用户要求）；
//   时刻选择器与设置页「同意立项」共用 ScheduleFields（单一实现点）
// - 运行中真实进度条（done/total 百分比）+ 当前文件 + 取消按钮
// - 表格无操作列（2026-09-24 用户要求：逐条「忽略/清除归属」入口随列下线）；
//   批量「全部忽略」= 把表格勾选的条目置 ignored（2026-09-20 用户要求）
//
// 配置归属（2026-09-19 用户决策）：本分面**只读触发与展示**，不再承载
// admin.code_review.enabled 开关——配置项归设置页「质量」页签统一管理
// （QualityPanel.tsx），分面承担的是「看结果 + 手动触发」。
//
// active 门控（对齐 SessionPanel）：仅在选中本分面时拉取数据与订阅 SSE，
// 未选中零请求（project-page-tabs 按需加载语义）。
import { useCallback, useEffect, useRef, useState } from 'react';
import {
  App,
  Button,
  Card,
  Popover,
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
  ApiError,
  cancelRun,
  generateFixSpec,
  getCodeFixRunResult,
  getCodeReviewItems,
  getCodeReviewProgress,
  getCodeReviewRunResult,
  getConfig,
  setCodeReviewItemStatus,
  STREAM_URL,
  triggerCodeFixRun,
  triggerCodeReview,
} from '../../../services/dashboard';
import type { CodeFixRunResult, CodeReviewItem, CodeReviewProgress, CodeReviewRunResult } from '../../../services/dashboard';
import CodeFixProgressCard from './CodeFixProgressCard';
import ProgressBarTile from './ProgressBarTile';
import ScheduleFields, {
  describeStartAfter,
  isStartAfterValid,
  nextRunAtISO,
} from '../../../components/ScheduleFields';
import type { AcceptSchedule } from '../../../components/ScheduleFields';
import { useIsMobile } from '../../../hooks/useIsMobile';

interface QualityTabProps {
  project: string;
  active: boolean;
}

// 严重度色系：high/medium/low 三档是 ocr scan 产出经 agent「原样透传」落台账
// 的漂移值（提示词 agents/code-review.md 契约四档 critical|major|minor|info，
// 归一责任在 agent，实测 fenixd 台账漂移 80/543 条），色系按后端读侧归一口径
// 对齐（high/medium→major 档 orange，low→minor 档 gold）。
// 排序权重表不在此维护：两列排序已下沉 server-side（2026-09-24 台账分页配套，
// 权重/白名单见 dashboard/data/code_review.py read_code_review_items）。
const SEVERITY_COLOR: Record<string, string> = {
  critical: 'red',
  high: 'orange',
  major: 'orange',
  medium: 'orange',
  minor: 'gold',
  low: 'gold',
  info: 'blue',
};

const STATUS_TEXT: Record<string, string> = {
  open: 'open',
  in_spec: 'in_spec',
  resolved: 'resolved',
  ignored: 'ignored',
};

// review_kind 英文枚举 → 中文文案（枚举值与 core/code_review.py 的
// review_kind 契约对齐；未收录值回退英文原样，与 STATUS_TEXT 同风格）
const REVIEW_KIND_TEXT: Record<string, string> = {
  scheduled: '周期审查',
  manual_full: '全库审查',
  manual_window: '当期审查',
};

// 条目表格 server-side 分页页大小（2026-09-24 用户要求：台账 resolved 上千行
// 不再一次全量拉取，过滤/分页下沉后端；与既有分页 UI 的 pageSize:10 一致）
const ITEMS_PAGE_SIZE = 10;

const STATUS_COLOR: Record<string, string> = {
  open: 'blue',
  in_spec: 'purple',
  resolved: 'green',
  ignored: 'default',
};

// ── 「问题」列单元格：两行堆叠 + 内容行悬浮浮层 ──────────────────────
// 行布局（2026-09-20 用户要求）：第一行 = 问题标题 + `文件:行`（同一行不换行，
// `文件:行` 过长时单行省略 + 原生 tooltip）；第二行 = 内容。
// 浮层形制对齐「功能开发」分面「名称」列的 Why 浮层（Popover + Markdown 渲染）：
// 描述里常见 `` `code` `` / 列表 / 表格，纯文本 Tooltip 会原样显示反引号，
// 这里按 Markdown 排版。
// 宽度（2026-09-20 用户要求）：浮层宽度 = 所在「问题」列宽度的 80%——列宽随
// 视口自适应（无固定 width），故在悬浮时实测所在 td 宽度再换算，而非写死 px。
// 延迟（2026-09-20 用户要求）：鼠标悬停满 1s 才弹出浮层，快速划过不触发
// （避免浏览列表时浮层乱闪）；移出即时关闭并清除定时器。
// 魔数收敛（code-review item ba13417eb1ff）：本组件用到的间隔/比例一律抽
// 具名模块常量，SSE 端点走 services/dashboard 的 STREAM_URL 单源。
const POPOVER_DELAY_MS = 1000;
// 浮层宽度 = 所在「问题」列 td 实测宽度的比例（见上方「宽度」注释）
const POPOVER_WIDTH_RATIO = 0.8;
// 运行中进度轮询间隔（运行结束即 clearInterval）
const PROGRESS_POLL_INTERVAL_MS = 2000;
// 心跳兜底刷新间隔（SSE 不可达时保底新鲜度，见下方 effect 注释）
const HEARTBEAT_REFRESH_INTERVAL_MS = 30000;
// 触发后「等结果」轮询预算（add-code-review-trigger-ack 3.3）：1s 间隔轮询
// run-result，超过即兜底提示并解禁（含 daemon 旧码未落结果文件的场景）
const ACK_RESULT_POLL_BUDGET_MS = 120_000;
// started 后「等启动」轮询预算（add-code-review-trigger-ack 3.4）：2s 间隔
// 轮询 progress 等 running=true，超过即「启动较慢」提示并解禁（30s 心跳兜底）
const ACK_START_POLL_BUDGET_MS = 60_000;

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
      if (colWidth > 0) setPopoverWidth(Math.round(colWidth * POPOVER_WIDTH_RATIO));
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
            不换行——用户 2026-09-20 要求）。标题同样 nowrap + 省略（code-review
            item f5f87cee3ace）：缺省 whiteSpace 下长标题会换行、挤压 `文件:行`，
            破坏单行布局契约；flex 收缩 + 省略后超长标题截断展示。 */}
        <div style={{ display: 'flex', alignItems: 'baseline', gap: 8, minWidth: 0 }}>
          <span
            style={{
              fontWeight: 500,
              flex: '0 1 auto',
              minWidth: 0,
              overflow: 'hidden',
              textOverflow: 'ellipsis',
              whiteSpace: 'nowrap',
            }}
          >
            {rec.title}
          </span>
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
            style={{ fontSize: 12, marginBottom: 0, wordBreak: 'break-word' }}
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

// 移动端（<768）堆叠卡形态的「问题」单元格：严重度/状态 Tag 行 → 标题
// （换行）→ 文件:行（换行）→ 描述全文（换行）。与桌面版 ProblemCell 的
// 差异：① 标题不再与文件:行挤同一行（nowrap 单行契约在 139px 列宽下
// 只剩 6~8 字）；② 描述直接全文展示——桌面版全文走悬浮 1s 的 Popover，
// 触屏设备没有 hover，该通道在移动端不可达。
function ProblemCellMobile({ rec }: { rec: CodeReviewItem }) {
  return (
    <Space direction="vertical" size={4} style={{ width: '100%' }}>
      <Space size={4} wrap>
        <Tag color={SEVERITY_COLOR[rec.severity] || 'default'} style={{ marginInlineEnd: 0 }}>
          {rec.severity}
        </Tag>
        <Tag color={STATUS_COLOR[rec.status] || 'default'} style={{ marginInlineEnd: 0 }}>
          {STATUS_TEXT[rec.status] || rec.status}
        </Tag>
      </Space>
      <Typography.Text style={{ fontWeight: 500, wordBreak: 'break-word' }}>
        {rec.title}
      </Typography.Text>
      <Typography.Text code type="secondary" style={{ fontSize: 12, wordBreak: 'break-all' }}>
        {rec.file}:{rec.line}
      </Typography.Text>
      <Typography.Paragraph
        type="secondary"
        style={{ fontSize: 12, marginBottom: 0, whiteSpace: 'pre-wrap', wordBreak: 'break-word' }}
      >
        [{rec.category}] {rec.description}
      </Typography.Paragraph>
    </Space>
  );
}

export default function QualityTab({ project, active }: QualityTabProps) {
  const { message, modal } = App.useApp();
  // <768 窄屏布局切换：台账表从「严重度/问题/状态」三列切换为单列堆叠卡
  // （390px 视口下「问题」列仅 139px，单行 nowrap 契约把标题压到 6~8 字；
  // 触屏无 hover，悬浮 Popover 全文通道不可达——2026-09-25 移动端实测）。
  const isMobile = useIsMobile();
  const [items, setItems] = useState<CodeReviewItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [selectedKeys, setSelectedKeys] = useState<React.Key[]>([]);
  const [severityFilter, setSeverityFilter] = useState<string | undefined>();
  const [statusFilter, setStatusFilter] = useState<string | undefined>('open');
  const [progress, setProgress] = useState<CodeReviewProgress | null>(null);
  // 条目表格 server-side 分页态（2026-09-24）：页码/过滤后总数；fixRunning
  // 来自 CodeFixProgressCard 的运行态上抛，供「自动修复」按钮门控。
  // total 为 undefined（后端未升级，返回无 total 的旧契约）时传给 antd 回退
  // 「按 dataSource 长度」的本地分页口径——旧后端下退化为一次性加载+本地翻页，
  // 新后端（daemon 重启后）起 server-side 生效。
  const [itemsPage, setItemsPage] = useState(1);
  const [itemsTotal, setItemsTotal] = useState<number | undefined>(undefined);
  // 排序 server-side（2026-09-24 台账分页配套）：severity/status 两列排序的
  // 字段/方向经 loadItems 下发后端，全量排序后再切片——客户端 sorter 在分页
  // 形态下只重排当页 10 行，排序语义失真。sortField 为 undefined 即取消排序，
  // 回退后端默认排序（severity 升序）；排序变化与过滤同约定回第 1 页。
  const [sortField, setSortField] = useState<'severity' | 'status' | undefined>();
  const [sortOrder, setSortOrder] = useState<'ascend' | 'descend' | undefined>();
  const [fixRunning, setFixRunning] = useState(false);
  const handleFixRunningChange = useCallback((r: boolean) => setFixRunning(r), []);
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
  // 触发成功重启信号（code-review item 62f764043d88）：CodeFixProgressCard
  // 随 Tab 常驻挂载、轮询停即死；触发成功递增本计数作为 restartKey 传入，
  // 重启其轮询以接管新修复链的进度展示（触发成功不额外操作的既有契约不变）。
  const [fixRunRestartTick, setFixRunRestartTick] = useState(0);
  const pollTimerRef = useRef<number | null>(null);
  // 自动修复 20s 轮询取消哨（code-review item 34247364a750）：卸载/切页签/
  // 切项目时由 SSE effect 清理置位（与 pollTimerRef 同点清理），轮询每轮与
  // 出消息前检查——不再对用户已离开的页面继续 1s 轮询 20s、也不向已卸载
  // 组件弹成功/失败 toast。
  const fixRunPollAbortedRef = useRef(false);
  // 审查触发受理等待轮询取消哨（add-code-review-trigger-ack 3.2）：复用
  // fixRunPollAbortedRef 模式——卸载/切页签/切项目时由 SSE effect 清理置位
  // （同点清理），两段等待轮询每轮与出消息前检查——不向已离开的页面继续
  // 轮询，也不向已卸载组件弹提示。
  const ackPollAbortedRef = useRef(false);
  // 受理等待独立门控态（add-code-review-trigger-ack 3.2）：触发后的两段等待
  // （等结果 120s + 等启动 60s）只禁用两个审查触发按钮，不并入
  // actionPending——后者语义是「HTTP 请求进行中」，会连带禁用取消与自动
  // 修复按钮。
  const [ackPending, setAckPending] = useState(false);
  // 忽略操作独立 pending 门控（code-review item 717b2251caaa）：行级忽略与
  // 批量「全部忽略」共用该门控——请求进行中禁用/呈 loading 入口按钮并防连点，
  // 避免 Promise.allSettled 期间对同一批 item_id 重复发请求、叠加多条 toast。
  const [ignorePending, setIgnorePending] = useState(false);
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
      // 过滤+排序+分页 server-side（2026-09-24）：status/severity/sort/page
      // 下发，返回当页行 + 过滤后总数。
      const data = await getCodeReviewItems(project, {
        statuses: statusFilter ? [statusFilter] : undefined,
        severity: severityFilter,
        sortBy: sortField,
        sortOrder: sortField ? (sortOrder === 'descend' ? 'desc' : 'asc') : undefined,
        page: itemsPage,
        pageSize: ITEMS_PAGE_SIZE,
      });
      if (seq !== loadSeqRef.current) return; // 过期响应丢弃（陈旧覆盖防护）
      setItems(data.items || []);
      setItemsTotal(typeof data.total === 'number' ? data.total : undefined);
      // 越界页收敛（仅 server-side total 可判定）：浏览中条目被核销/过滤致总
      // 页数缩水时收回末页，避免停在空页误读为无数据（setItemsPage 触发本
      // loader 重跑，seq 守卫防乱序）。
      if (typeof data.total === 'number') {
        const lastPage = Math.max(1, Math.ceil(data.total / ITEMS_PAGE_SIZE));
        if (itemsPage > lastPage) setItemsPage(lastPage);
      }
      loadedOnceRef.current = true;
    } catch (e) {
      if (seq !== loadSeqRef.current) return;
      if (!opts?.background) {
        message.error(`加载失败: ${e instanceof Error ? e.message : String(e)}`);
      }
    } finally {
      if (firstLoad && seq === loadSeqRef.current) setLoading(false);
    }
  }, [active, project, statusFilter, severityFilter, itemsPage, sortField, sortOrder, message]);

  // loadItems 的 ref 视图（code-review item 2723381276fb）：轮询 interval 这类
  // 长生命周期闭包经此读取最新 loader——statusFilter 变化会重建 loadItems，
  // interval 回调直呼创建时捕获的旧闭包会用旧过滤条件的结果覆盖正确过滤的列表。
  const loadItemsRef = useRef(loadItems);

  // 进度请求序号守卫（code-review item 665b617e8d6e）：与 loadItems 的
  // loadSeqRef 同款防护——loadProgress 会被数据加载 effect、SSE 帧、30s 心跳
  // 并发触发，切项目/切页签后旧项目的在飞响应晚到，无守卫时会把新项目
  // progress 覆盖回旧值（最多等 30s 心跳才自愈），且 running=true 时会在
  // SSE 清理之后重建闭包捕获旧 project 的 2s 轮询（占据 pollTimerRef 还会
  // 让新项目因「已有轮询」拿不到自己的轮询）。除每次调用自增外，SSE effect
  // 清理处也自增（卸载/active 翻转/project 切换），使切换前所有在飞响应
  // 一律过期——含切到非激活态（effect 早退不调用本函数）的窗口。
  const progressSeqRef = useRef(0);

  const loadProgress = useCallback(async () => {
    if (!active || !project) return;
    const seq = ++progressSeqRef.current;
    try {
      const p = await getCodeReviewProgress(project);
      if (seq !== progressSeqRef.current) return; // 过期响应丢弃（陈旧覆盖/旧轮询重建防护）
      setProgress(p);
      if (p.running) {
        // 运行中：轮询进度（2s），结束兜底刷新表格
        if (pollTimerRef.current !== null) return;
        pollTimerRef.current = window.setInterval(async () => {
          try {
            // 过期守卫（code-review item bcdc14169759）：cleanup（卸载/切项目/
            // 切页签）自增 progressSeqRef 并清 interval，但已发出的在飞轮询响应
            // 仍会晚到——每轮请求前快照序号、响应到达后复核，过期即丢弃，防旧
            // 项目进度覆盖新项目，也防旧 tick 的 !running 分支误清新项目的轮询。
            const tickSeq = progressSeqRef.current;
            const p2 = await getCodeReviewProgress(project);
            if (tickSeq !== progressSeqRef.current) return; // 过期响应丢弃（含 cleanup 后晚到）
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
        }, PROGRESS_POLL_INTERVAL_MS);
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

    const es = new EventSource(STREAM_URL);
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
    }, HEARTBEAT_REFRESH_INTERVAL_MS);

    return () => {
      disposed = true;
      es.close();
      window.clearInterval(heartbeat);
      // 清理即作废所有在飞进度响应（code-review item 665b617e8d6e）：与下方
      // pollTimerRef 清理同点（卸载/active 翻转/project 切换都走这里）——否则
      // 旧项目 running=true 的晚到响应会在本轮清理之后，经过期闭包重建捕获
      // 旧 project 的 2s 轮询。
      progressSeqRef.current += 1;
      if (pollTimerRef.current !== null) {
        window.clearInterval(pollTimerRef.current);
        pollTimerRef.current = null;
      }
      // 卸载/active 翻转/project 切换都会走本清理：连带置位自动修复轮询
      // 取消哨与审查触发受理等待取消哨（add-code-review-trigger-ack 3.2）
      fixRunPollAbortedRef.current = true;
      ackPollAbortedRef.current = true;
    };
  }, [active, project]);

  // 未激活时清理轮询
  useEffect(() => {
    if (!active && pollTimerRef.current !== null) {
      window.clearInterval(pollTimerRef.current);
      pollTimerRef.current = null;
    }
    if (!active) fixRunPollAbortedRef.current = true;
    if (!active) ackPollAbortedRef.current = true;
  }, [active]);

  // ── 手动触发按钮（5.4 + add-code-review-trigger-ack 3.2-3.4） ────
  // 触发改两段等待（design D5）：POST 200 只代表信号已写、不构成启动确认，
  // 不再弹「已受理」假承诺 toast。置独立 ackPending 门控（不复用
  // actionPending——其语义是「HTTP 请求进行中」，连带禁用取消/自动修复按钮）
  // 后：第 1 段 1s 间隔轮询 run-result（上限 120s）等 daemon 判定结果，仅认
  // requested_at 回链本次的记录；读到 started 进第 2 段 2s 间隔轮询 progress
  // 等 running=true（上限 60s）交由既有进度卡片接管。dropped/failed/两段
  // 超时各自明确反馈；任一段结束（含超时/失败）复位 ackPending；卸载/切
  // 页签/切项目置位哨兵立即停止轮询且不弹提示。
  const handleTrigger = async (scope: 'full' | 'window') => {
    const label = scope === 'full' ? '全库审查' : '当期审查';
    if (actionPending || ackPending) return; // pending 门控（code-review item 133cba8a5748）
    setActionPending(true);
    ackPollAbortedRef.current = false; // 本轮请求开启新哨（上一轮取消状态作废）
    let wantedAt: string | undefined;
    try {
      const res = await triggerCodeReview(project, scope);
      wantedAt = res.requested_at;
      // 经 ref 取最新 loader（code-review item 75c98014e626）：await 往返期间发生
      // 项目切换时，本闭包捕获的旧 loader 直呼会用旧项目刷新覆盖新视图——ref 视图
      // 随 loadItems/loadProgress 重建每轮同步为最新闭包（同 SSE/心跳刷新路径）。
      void loadProgressRef.current();
      void loadItemsRef.current({ background: false });
    } catch (e) {
      const errMsg = e instanceof Error ? e.message : String(e);
      // 业务拒绝按稳定错误码分支（code-review item fbdb437a22a0）：旧实现对
      // 后端中文文案做子串匹配，措辞一改即静默落入通用错误分支；错误码由
      // 后端 _coded_error 下发、ApiError.code 承载（同 RegressionTab 先例）
      if (e instanceof ApiError && e.code === 'code_review_running') {
        message.warning('已有审查在进行中');
      } else if (e instanceof ApiError && e.code === 'code_review_ack_pending') {
        // 受理窗口守卫（add-code-review-trigger-ack 2.3）：上一触发已被
        // daemon 受理但 run 尚未开始，窗口内重复触发被显式拒绝
        message.warning(errMsg);
      } else {
        message.error(`${label}失败: ${errMsg}`);
      }
    } finally {
      setActionPending(false);
    }
    if (!wantedAt) return; // 触发未受理（catch 分支已反馈），不进入受理等待态

    setAckPending(true);
    try {
      // 第 1 段：等结果（1s 间隔，上限 120s）
      const deadline = Date.now() + ACK_RESULT_POLL_BUDGET_MS;
      let result: CodeReviewRunResult | null = null;
      while (Date.now() < deadline) {
        if (ackPollAbortedRef.current) return; // 卸载/切走后停止轮询与提示
        await new Promise((resolve) => setTimeout(resolve, 1000));
        if (ackPollAbortedRef.current) return;
        try {
          const snap = await getCodeReviewRunResult(project);
          // 仅认 requested_at 回链本次的记录（上一轮残留 MUST NOT 弹提示）
          if (snap.requested_at && snap.requested_at === wantedAt) {
            result = snap;
            break;
          }
        } catch {
          // 单轮读取失败不终止轮询（daemon 消费稍后补结果文件）
        }
      }
      if (ackPollAbortedRef.current) return;
      if (!result) {
        // 120s 未读到本次结果（含 daemon 旧码在飞、结果文件不产生），兜底
        // 提示并解禁，不挂死在等待态
        message.info(`未收到「${label}」启动确认，请稍后在进度卡片或 daemon 日志确认`);
        return;
      }
      if (result.status === 'dropped') {
        // 拒绝原因由 daemon 结果文件的 message 如实回显，不让用户对着无反应
        // 的按钮猜；message 与 reason 皆缺省时兜底固定文案（勿渲染 undefined）
        message.warning(
          result.message ||
            (result.reason ? `审查触发被拒绝：${result.reason}` : '审查触发被拒绝'),
        );
        return;
      }
      if (result.status === 'failed') {
        message.error(
          result.message ||
            (result.reason ? `审查启动失败：${result.reason}` : '审查启动失败'),
        );
        return;
      }
      // status=started → 第 2 段：等启动（2s 间隔轮询 progress，上限 60s），
      // running=true 前不弹无信息量的中间提示
      const runDeadline = Date.now() + ACK_START_POLL_BUDGET_MS;
      let started = false;
      while (Date.now() < runDeadline) {
        if (ackPollAbortedRef.current) return;
        await new Promise((resolve) => setTimeout(resolve, 2000));
        if (ackPollAbortedRef.current) return;
        try {
          const p = await getCodeReviewProgress(project);
          // 过期守卫（code-review item bcdc14169759）：请求在飞期间发生卸载/
          // 切项目/切页签时，cleanup 置位的取消哨拦不住已发出的本轮响应——
          // 出消息前复核一次，防旧项目进度覆盖新项目（连带 Cancel 按钮拿到
          // 跨项目 review_id）。
          if (ackPollAbortedRef.current) return;
          setProgress(p);
          if (p.running) {
            started = true;
            break;
          }
        } catch {
          // 单轮读取失败继续（下轮重试）
        }
      }
      if (ackPollAbortedRef.current) return;
      if (started) {
        // running=true：既有「审查进行中」卡片与 2s 进度轮询自动接管
        // （loadProgress 见 running 起轮询，经 ref 取最新闭包，同 loadItemsRef）
        void loadProgressRef.current();
      } else {
        // run 仍可能稍后开始（既有 30s 心跳兜底刷新进度），明确提示并解禁
        message.info('审查已受理但启动较慢，请稍后在进度卡片或 daemon 日志确认');
      }
    } finally {
      setAckPending(false);
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
    fixRunPollAbortedRef.current = false; // 本轮请求开启新哨（上一轮取消状态作废）
    try {
      const res = await triggerCodeFixRun(project);
      setFixRunRestartTick((t) => t + 1); // 重启进度卡片轮询（见 fixRunRestartTick 注释）
      const wantedAt = res.requested_at;
      const deadline = Date.now() + 20_000;
      let result: CodeFixRunResult | null = null;
      while (Date.now() < deadline) {
        // 卸载/切走后停止轮询与提示（finally 复位 pending）
        if (fixRunPollAbortedRef.current) return;
        await new Promise((resolve) => setTimeout(resolve, 1000));
        if (fixRunPollAbortedRef.current) return;
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
      if (fixRunPollAbortedRef.current) return;
      if (result) {
        if (result.triggered) {
          message.success(result.message || '已投递一批自动修复，可在进度卡片查看进展');
        } else {
          // 拒绝原因（无待修条目/已有修复在跑/回归契约缺失等）由 daemon
          // 结果文件的 message 如实回显，不让用户对着无反应的按钮猜；
          // message 与 reason 皆缺省时兜底为固定文案（勿渲染 undefined）
          message.warning(
            result.message ||
              (result.reason ? `未能投递：${result.reason}` : '未能投递自动修复请求'),
          );
        }
      } else {
        message.info('触发结果尚未就绪，请稍后在进度卡片或 daemon 日志确认');
      }
    } catch (e) {
      const errMsg = e instanceof Error ? e.message : String(e);
      // 业务拒绝按稳定错误码分支（code-review item fbdb437a22a0）：409「已有
      // 未消费的修复触发请求」由后端 _coded_error 下发 code，不再对展示文案
      // 做子串匹配（措辞一改即静默落入通用错误分支）
      if (e instanceof ApiError && e.code === 'fix_run_request_pending') {
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

  // 勾选中 status==='open' 的条目数（code-review item 7530070b52fe +
  // b6fe254b5962）：「生成修复 SPEC」「全部忽略」按钮标签计数与弹窗内 count
  // （剔除非 open 后的 openKeys.length）、工具栏「已选 N 条」统一用本口径——
  // 原始勾选数混有 in_spec/resolved/ignored 条目时与实际处理数互相矛盾。
  const openSelectedCount = items.filter(
    (it) => selectedKeys.includes(it.item_id) && it.status === 'open',
  ).length;

  // 打开弹窗前把配置里的默认执行时刻算好（异步；算完再弹，避免弹窗内
  // 初始值闪一下从「立即」跳到「定时」）
  const handleGenerate = async () => {
    if (selectedKeys.length === 0 || generating || generateModalOpenRef.current) return;
    // 与 handleIgnoreAll 同一过滤口径（code-review item 1b5c5415dd5e）：幽灵
    // 选中清理只保证条目可见、不保证 status==='open'，非 open（in_spec/
    // resolved/ignored）条目不能进入修复 SPEC 流程，提交前先剔除。
    const openKeys = items
      .filter((it) => selectedKeys.includes(it.item_id) && it.status === 'open')
      .map((it) => String(it.item_id));
    if (openKeys.length === 0) {
      // 与 handleIgnoreAll 同款反馈（code-review item 7530070b52fe）：按钮
      // disabled 只看勾选数、勾选全是非 open 条目时仍可点，静默 return 会让
      // 用户对着无反应的按钮猜
      message.warning('选中条目中没有可生成修复 SPEC 的 open 问题');
      return;
    }
    generateModalOpenRef.current = true;
    let initial: string | null;
    try {
      initial = await configStartAfter();
    } catch {
      // configStartAfter 内部已吞错，此处纯防御：取值失败释放重入门
      generateModalOpenRef.current = false;
      return;
    }
    const count = openKeys.length;
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
          const result = await generateFixSpec(project, openKeys, holder.startAfter);
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

  // ── 批量「全部忽略」（2026-09-20 用户要求）：把勾选条目全部置 ignored ──
  // 选中可能混入非 open 条目（in_spec/resolved），逐条忽略会让后端的
  // 「仅 open/ignored 可人工置入」约束报错；这里只对 open 条目发请求。
  // 用 Promise.allSettled 并发跑完整批，不因单条失败中断其余；结束后统一
  // 提示成功/失败计数并刷新列表（不做逐条 toast，避免刷屏）。
  const handleIgnoreAll = async () => {
    if (ignorePending) return; // pending 门控防连点（code-review item 717b2251caaa）
    const targets = items.filter((it) => selectedKeys.includes(it.item_id) && it.status === 'open');
    if (targets.length === 0) {
      message.warning('选中条目中没有可忽略的 open 问题');
      return;
    }
    setIgnorePending(true);
    try {
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
    } finally {
      setIgnorePending(false);
    }
  };

  // 实际渲染行：status/severity 过滤已下沉 server-side（2026-09-24 分页配套，
  // 台账上千行不再全量拉取），本地不再二次过滤——渲染行即当页行；幽灵选中
  // 清理随之与当页行求交（翻页/过滤收窄即清掉不可见旧选中，语义与原先一致）。
  const filteredItems = items;

  // 选中项与**实际渲染行**求交（code-review item 01f6207c6b11 + a4922e615ddf）：
  // 后端流转为 resolved/in_spec、或过滤/翻页后，旧选中 key 会残留为「幽灵选中」，
  // 使「已选 N 条」计数错误、并把不可见 item_id 提交给后端。
  useEffect(() => {
    setSelectedKeys((prev) => {
      const visible = new Set(filteredItems.map((it) => String(it.item_id)));
      const next = prev.filter((k) => visible.has(String(k)));
      return next.length === prev.length ? prev : next;
    });
  }, [filteredItems]);

  const columns: ColumnsType<CodeReviewItem> = isMobile
    ? [
        // <768 窄屏：单列堆叠卡（勾选列由 rowSelection 自动保留，批量
        // 「生成修复 SPEC / 全部忽略」不受影响）；列头排序（server-side
        // 交互）在移动端不下发，过滤仍走工具栏两个下拉。
        {
          title: '问题',
          key: 'problem',
          render: (_: unknown, rec: CodeReviewItem) => <ProblemCellMobile rec={rec} />,
        },
      ]
    : [
        {
          title: '严重度',
          dataIndex: 'severity',
          key: 'severity',
          width: 90,
          // critical > major > minor > info（code-review item 2cde5d51a359）。
          // 排序 server-side（2026-09-24 台账分页配套）：sorter: true 只保留列头
          // 排序交互（antd 不再本地重排 dataSource），字段/方向经受控 sortOrder
          // + Table onChange 写入 state 后由 loadItems 下发后端——客户端 sorter
          // 在分页形态下只重排当页 10 行，排序语义失真。
          sorter: true,
          sortOrder: sortField === 'severity' ? sortOrder : undefined,
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
          // 排序 server-side（open → in_spec → resolved → ignored 次序即后端
          // STATUS_ORDER 白名单），受控方式同上方严重度列
          sorter: true,
          sortOrder: sortField === 'status' ? sortOrder : undefined,
          render: (status: string) => (
            <Tag color={STATUS_COLOR[status] || 'default'}>{STATUS_TEXT[status] || status}</Tag>
          ),
        },
        // 操作列已按用户 2026-09-24 要求整体移除（逐条「忽略/清除归属」入口随列
        // 下线；批量「全部忽略」入口保留在工具栏），对应 renderOps/handleIgnore/
        // handleClearAttribution 一并删除。
      ];

  // 旧 progressPercent 已删：进度条换 ProgressBarTile 后由 done/total 直驱
  // （2026-09-24 用户要求：与「自动修复代码问题」卡片同控件同观感），无百分
  // 比散置消费点。

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
            onChange={(v) => {
              setSeverityFilter(v);
              setItemsPage(1); // 过滤条件变化回第 1 页（server-side 过滤配套）
            }}
            // 只保留契约四档（用户 2026-09-26 要求）：漂移值 high/medium/low
            // 已在写侧+读侧归一（见 SEVERITY_COLOR 注释），不再作为过滤选项
            // [fenix-ignore:679043c64a68] high/medium/low 选项残留已在 fde342a2 修复，当前仅契约四档
            options={[
              { value: 'critical', label: 'critical' },
              { value: 'major', label: 'major' },
              { value: 'minor', label: 'minor' },
              { value: 'info', label: 'info' },
            ]}
          />
          <Select
            placeholder="状态"
            allowClear
            style={{ width: 190 }}
            value={statusFilter}
            onChange={(v) => {
              setStatusFilter(v);
              setItemsPage(1); // 过滤条件变化回第 1 页（server-side 过滤配套）
            }}
            // 状态中文解释（用户 2026-09-23 要求）：仅下拉选项文案，表格
            // Tag 仍走 STATUS_TEXT 英文短标签
            options={[
              { value: 'open', label: 'open（待处置）' },
              { value: 'in_spec', label: 'in_spec（已立项修复）' },
              { value: 'resolved', label: 'resolved（已修复）' },
              { value: 'ignored', label: 'ignored（已忽略）' },
            ]}
          />
          <Typography.Text type="secondary" style={{ fontSize: 12 }}>
            已选 {openSelectedCount} 条
          </Typography.Text>
        </Space>
        <Space wrap>
          {/* 三个触发按钮均为 primary（蓝底白字，用户 2026-09-22 要求，
              覆盖此前 2026-09-20 的「默认样式一致」约定）；
              「生成修复 SPEC」保持 primary（主操作按钮）；
              「全部忽略」为 primary + danger（红底白字，用户 2026-09-20 要求） */}
          {/* 两个审查触发按钮在受理等待态（ackPending）也禁用并呈 loading
              （add-code-review-trigger-ack 3.2）：等待期（最长 120s+60s）内
              重复点击被挡住，且触发后立即可见「正在等待启动」的反馈——
              ackPending 只作用于这两个按钮，取消/自动修复按钮不受影响 */}
          <Button
            type="primary"
            disabled={progress?.running || actionPending || ackPending}
            loading={actionPending || ackPending}
            onClick={() => void handleTrigger('full')}
          >
            全库审查
          </Button>
          <Button
            type="primary"
            disabled={progress?.running || actionPending || ackPending}
            loading={actionPending || ackPending}
            onClick={() => void handleTrigger('window')}
          >
            当期审查
          </Button>
          {/* 「自动修复」（add-code-fix-manual-trigger）：手动触发即临时授权
              （开关关闭也修这一批），蓝底白字与相邻触发按钮一致；触发流程
              （含结果轮询）进行中呈 loading 态并防连点。修复链在飞（fixRunning，
              CodeFixProgressCard 上抛）时同样禁用——与审查按钮在审查进行中
              禁用的语义对齐（2026-09-24 用户要求） */}
          <Button
            type="primary"
            disabled={actionPending || fixRunning}
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
            生成修复 SPEC{openSelectedCount > 0 ? `（${openSelectedCount}）` : ''}
          </Button>
          {/* 「全部忽略」：红底白字（type="primary" danger，用户 2026-09-20 要求），
              未勾选任何条目时禁用（selectedKeys 为空即无目标）；批量请求进行中
              呈 loading 态防连点（code-review item 717b2251caaa） */}
          <Button
            type="primary"
            danger
            disabled={selectedKeys.length === 0}
            loading={ignorePending}
            onClick={() => void handleIgnoreAll()}
          >
            全部忽略{openSelectedCount > 0 ? `（${openSelectedCount}）` : ''}
          </Button>
        </Space>
      </div>

      {progress?.running ? (
        <Card size="small" style={{ marginBottom: 12, background: '#fafafa' }}>
          <Space direction="vertical" style={{ width: '100%' }} size={4}>
            <Space style={{ justifyContent: 'space-between', width: '100%' }}>
              <Typography.Text strong>
                审查进行中（{REVIEW_KIND_TEXT[progress.review_kind || ''] || progress.review_kind || 'code-review'}）
              </Typography.Text>
              <Button size="small" loading={actionPending} onClick={() => void handleCancel()}>
                取消
              </Button>
            </Space>
            {/* 与「自动修复代码问题」卡片同控件（ProgressBarTile，2026-09-24
                用户要求观感一致）：大百分比 + 已完成 x/y + 渐变条 */}
            <ProgressBarTile done={progress.done} total={progress.total} status="active" />
            <Typography.Text type="secondary" style={{ fontSize: 12 }}>
              共 {progress.total} 个文件
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
        restartKey={fixRunRestartTick}
        onSettled={() => void loadItems()}
        onRunningChange={handleFixRunningChange}
      />

      <Table<CodeReviewItem>
        rowKey="item_id"
        loading={loading}
        dataSource={filteredItems}
        columns={columns}
        size="small"
        // tableLayout=fixed（2026-09-26 用户要求）：ignored 等过滤下存在 120 字符
        // 英文标题、70 字符无空格文件路径、900+ 字符描述，默认 auto 布局按内容
        // min-content 撑开列宽，单元格内的省略样式永不触发、表格被撑出容器。
        // 定宽后「问题」列吃剩余宽度，行内既有的 nowrap/ellipsis/line-clamp
        // 截断真正生效（形制对齐 RegressionTab / 项目列表，2026-09-25 移动端
        // 越界定调「改布局不改宽度」的同一机制）。
        tableLayout="fixed"
        rowSelection={{
          selectedRowKeys: selectedKeys,
          onChange: (keys) => setSelectedKeys(keys),
        }}
        pagination={{
          // server-side 分页（2026-09-24）：current/total 受控，翻页触发
          // loadItems 重取当页（itemsPage 在 loader deps 中）
          current: itemsPage,
          pageSize: ITEMS_PAGE_SIZE,
          total: itemsTotal,
          showSizeChanger: false,
          hideOnSinglePage: true,
          onChange: (p) => setItemsPage(p),
        }}
        onChange={(_pg, _filters, sorter, extra) => {
          // 排序变化（server-side 配套）：字段/方向写入受控态并回第 1 页，
          // loadItems 依赖 sortField/sortOrder 重建后重查。翻页/过滤走
          // action==='paginate'/'filter'——翻页仍由 pagination.onChange 接管，
          // 此处直接放行；第三击取消排序（order 为空）即回后端默认排序。
          if (extra.action !== 'sort') return;
          const s = Array.isArray(sorter) ? sorter[0] : sorter;
          if (
            s &&
            (s.columnKey === 'severity' || s.columnKey === 'status') &&
            (s.order === 'ascend' || s.order === 'descend')
          ) {
            setSortField(s.columnKey);
            setSortOrder(s.order);
          } else {
            setSortField(undefined);
            setSortOrder(undefined);
          }
          setItemsPage(1); // 排序条件变化回第 1 页（与过滤变化同约定）
        }}
        locale={{ emptyText: '暂无未处理问题' }}
      />
    </Card>
  );
}