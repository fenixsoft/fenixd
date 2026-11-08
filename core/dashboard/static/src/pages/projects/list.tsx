import { ClockCircleOutlined } from '@ant-design/icons';
import { PageContainer } from '@ant-design/pro-components';
import { PageTitleBar, TitleBarNum } from '@/components/PageTitleBar';
import {
  Alert,
  App,
  Button,
  Card,
  DatePicker,
  Drawer,
  Dropdown,
  Input,
  List,
  Modal,
  Popover,
  Progress,
  Radio,
  Segmented,
  Select,
  Slider,
  Space,
  Table,
  Tabs,
  Tag,
  theme,
  Tooltip,
  Typography,
} from 'antd';
import type { ColumnsType } from 'antd/es/table';
import type { MenuProps } from 'antd';
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import type { CSSProperties, Key, ReactNode } from 'react';
import { history, useParams, useSearchParams } from '@umijs/max';
import { useIsMobile } from '@/hooks/useIsMobile';
import dayjs from 'dayjs';
import Markdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { markdownComponents } from './components/SpecDocModal';
import { getSpecDetail, getSpecs } from '@/services/dashboard';
// 宿主对齐状态色单源（theme.ts；DESIGN.md「宿主对齐基线」）
import { DSH_INTERACTIVE_ACTIVE, DSH_LINK, DSH_PRIMARY, SPEC_LIST_MOBILE_BG } from '@/theme';
import {
  clearSpecError,
  deleteSpec,
  reReviewSpec,
  setSpecPriority,
  setSpecStartAfter,
  statusMeta,
  STREAM_URL,
} from '@/services/dashboard';
import type { SpecDetail, SpecSummary } from '@/services/dashboard';
// 时长格式化与详情页共用单源（code-review item f8307715a795）
import { fmtDuration } from '@/utils/duration';
// 刷新/心跳节奏常量与详情页共用单源（code-review item 73395d34f3de）
import { HEARTBEAT_MS, REFRESH_THROTTLE_MS } from '@/utils/refreshPolicy';
import { fetchProposalWhy } from '@/utils/proposalWhy';
// 评审 blocked 前缀与 v2 specDetail 共用单源（code-review item 801f9399dba8）
import { SPEC_REVIEW_BLOCKED_PREFIXES } from '@/utils/specReview';
// SPEC 中文标题关键字命中单源（add-spec-chinese-title 2.2）
import { specKeywordHit } from './specTitle';
// 整行点击守卫与路径单源（add-spec-subtitle-and-row-click task 2.1）
import { rowClickHitsExpandIcon, specDetailPath } from './specRowClick';
import SpecDocModal from './components/SpecDocModal';
import AdminInvokeModal from './components/AdminInvokeModal';
import SpecStatusModal from './components/SpecStatusModal';
import QualityTab from './components/QualityTab';
import RegressionTab from './components/RegressionTab';
import ArchitectureTab from './components/ArchitectureTab';
import KnowledgeTab from './components/KnowledgeTab';
// add-quality-gates-visibility：阶段→完成度/配色映射抽到纯函数模块（node:test
// 可加载 .ts），list.tsx 原地 import 替换本地定义，调用点零改动
import {
  pct,
  renderPercent,
  strokeColorFor,
  trailColorFor,
  GATES_STROKE,
} from './progressPhase';
// 「快速/完整模式」标记单源已收敛为本页 ModePill（定义见下；
// add-spec-list-mobile-style D2），ModeTag 仅剩 detail.tsx 使用
// add-spec-list-filter-stickiness：过滤状态 ↔ URL 查询参数白名单与 fail-safe
// 解析（纯函数单测见 tests/listFilters.test.mjs）
import {
  LIST_STATUSES,
  parseListFilters,
} from './listFilters';
import type { ListTab, ListTypeFilter as TypeFilter } from './listFilters';

// dashboard-sse-refresh：增量 patch 去重窗口（同 spec 1s 内多事件只应用最新）
const PATCH_COALESCE_MS = 1000;
// 搜索/筛选输入防抖
const SEARCH_DEBOUNCE_MS = 300;

// remarkPlugins 提为模块级常量（code-review item eb6fed2eec3a，比照 SpecDocModal
// SPEC_DOC_REMARK_PLUGINS 先例）：名称列/验证列两处 Markdown 共用同一数组标识，
// 避免 SSE 增量 patch / 心跳整表重渲染下每单元格重建数组触发整篇重新 parse
const LIST_REMARK_PLUGINS = [remarkGfm];

// ── Bento 色值（2026-11-06 用户指令：桌面 SPEC 表格对齐 v2 projects 台账
// 呈现；色值取自当日的 v2 域 token 表——该域 2026-11-07 已退役，此处值为
// 独立存量）。磁贴/表头/发丝线样式镜像在 global.less `.ov-bento` /
// `.ov-bento-table`（圆角固定 12px，DESIGN.md 通用条款）。
const OV_TEXT = '#1e293b';
const OV_TEXT_TERTIARY = '#64748b';
const OV_ERROR = '#dc2626';
const OV_WARNING = '#d97706';
const OV_INFO = '#2563eb'; // v2 语义 info tone 前景
const OV_INFO_SOFT = '#eff6ff';
const OV_MUTED_SOFT = '#f1f5f9';
// add-spec-list-mobile-style：移动卡磁贴/分隔/信息行镜像色（原型 T 常量同源，
// 镜像纪律同上——V2_TILE_BORDER / V2 border slate-200 / warning 软底 + amber-800）
const OV_HAIRLINE = '#eef2f7';
const OV_BORDER = '#e2e8f0';
const OV_AMBER_SOFT = '#fffbeb';
const OV_AMBER_TEXT = '#92400e';
// 移动状态 chips 激活态计数（DSH_PRIMARY 黑底上的降透白，原型 chip-active
// .chip-n 同值 rgba 62%）；仅 SpecCardList 移动编排块消费
const OV_ON_PRIMARY_DIM = 'rgba(255, 255, 255, 0.62)';
// 移动卡「加载更多」页大小（add-spec-list-mobile-style 2.3）：与桌面 Table
// 分页 pageSize 20 同值语义（每页条数不变，仅呈现换加载更多）
const SPEC_CARD_PAGE_SIZE = 20;

/** 三点操作图标（镜像 v2 DotsIcon；操作列 Dropdown 触发器，与 overview 台账同款）。 */
function DotsIcon() {
  return (
    <svg width={14} height={14} viewBox="0 0 14 14" fill="currentColor" aria-hidden>
      <circle cx={2.6} cy={7} r={1.2} />
      <circle cx={7} cy={7} r={1.2} />
      <circle cx={11.4} cy={7} r={1.2} />
    </svg>
  );
}

/** 语义胶囊徽标（镜像 v2 shared.tsx V2Pill filled 形态：999 胶囊 + tone 软底）。
 * tone 键域对齐 statusMeta 的 StatusTone，muted 兜底。 */
function Pill({ tone = 'muted', children, style, dot }: { tone?: string; children: ReactNode; style?: CSSProperties; dot?: boolean }) {
  const pair =
    tone === 'critical'
      ? [OV_ERROR, '#fef2f2']
      : tone === 'warning'
        ? [OV_WARNING, '#fffbeb']
        : tone === 'good'
          ? ['#16a34a', '#f0fdf4']
          : tone === 'info'
            ? [OV_INFO, OV_INFO_SOFT]
            : tone === 'aqua'
              ? ['#0891b2', '#ecfeff']
              : [OV_TEXT_TERTIARY, OV_MUTED_SOFT];
  return (
    <Tag
      style={{
        marginInlineEnd: 0,
        borderRadius: 999,
        fontSize: 12,
        paddingInline: 9,
        color: pair[0],
        background: pair[1],
        borderColor: 'transparent',
        fontWeight: 500,
        // 色点形态（add-spec-list-mobile-style 1.2：移动卡状态胶囊带色点）：
        // 点位与文字需要 flex 对齐，仅在 dot 时切换布局，桌面胶囊渲染零变化
        ...(dot ? { display: 'inline-flex', alignItems: 'center', gap: 4 } : null),
        ...style,
      }}
    >
      {dot ? <span aria-hidden style={{ flex: '0 0 auto', width: 6, height: 6, borderRadius: 999, background: pair[0] }} /> : null}
      {children}
    </Tag>
  );
}

/** 模式胶囊（v2 台账形态：快速=橙 warning 软底 / 标准=灰 muted 软底）。桌面
 * 「模式」列与移动卡片共用（add-spec-list-mobile-style D2：移动端不另造色对，
 * 同桌面列 Pill 单源）。 */
function ModePill({ mode }: { mode?: string | null }) {
  return <Pill tone={mode === 'fast-track' ? 'warning' : 'muted'}>{mode === 'fast-track' ? '快速' : '标准'}</Pill>;
}

function progressText(progress: number) {
  return progress >= 100 ? '已完成' : `${progress}%`;
}

// code-review item c3df4a612450：排序键与单元格渲染同源——gen 推导与渲染体
// 完全一致（verify 且执行未开始、有落盘出题数时按出题进度），统一走
// renderPercent，消除「生成阶段按用户不可见的 verify 0/0 指标排序」错位。
// code-review item e1f8a359480d：阶段感知推导收敛为单点 phaseProgressOf，
// 桌面「任务进度」列、移动端卡片与排序键三方共用——旧实现移动端卡片恒用
// task_done/task_total，verify/generation/gates 阶段与桌面显示不一致
// （verify 阶段在移动端看似已完成）。
type PhaseProgress = {
  percent: number;
  /** 阶段名（出题/门禁/验证/实现）：桌面「任务进度」列与移动卡片同源呈现 */
  label: string;
  /** 计数文案：gates 门禁 / verify / impl 任务，与 percent 同源；gen 出题分支
   * 不带「出题」前缀（阶段名 label 已承载，呈现层不再各自去前缀） */
  counter: string;
  isVerify: boolean;
  isGates: boolean;
  gen: { done: number; total: number } | null;
};

function phaseProgressOf(record: SpecSummary): PhaseProgress {
  // 阶段感知（add-task-progress-verify-phase）：仅 testing（progress_phase
  // = "verify"）切验证进度，implementing 收尾 / ocr 车道在飞（progress_phase
  // = "gates"，判定单点在后端）切门禁完成度，其余维持 impl 任务完成度。
  const isVerify = record.progress_phase === 'verify';
  const isGates = record.progress_phase === 'gates';
  // verification-phase-progress：执行未开始（verify_total=0）而后端已统计到
  // 出题落盘数时，进度条展示场景生成进度——出题是验证链主要耗时，不能让
  // 进度条在生成阶段长期停在 0/0。
  const gen =
    isVerify && record.verify_total === 0 && record.generation && record.generation.total > 0
      ? record.generation
      : null;
  // 阶段名与去前缀计数并入单源（code-review item 2d64a13ea499）：桌面列与
  // 移动卡片直接消费，新增阶段只需改此处，呈现层不再各自推导
  const label = gen ? '出题' : isGates ? '门禁' : isVerify ? '验证' : '实现';
  let counter: string;
  if (isGates) {
    counter = `${record.gates_done ?? 0}/${record.gates_total ?? 0}`;
  } else if (isVerify) {
    counter = gen ? `${gen.done}/${gen.total}` : `${record.verify_done}/${record.verify_total}`;
  } else {
    counter = `${record.task_done}/${record.task_total}`;
  }
  return { percent: renderPercent(record, gen), label, counter, isVerify, isGates, gen };
}

function progressSortPct(record: SpecSummary): number {
  return phaseProgressOf(record).percent;
}

// ── 设置拾取时间：过去时刻一律置灰 ──────────────────────────────
// 拾取时间语义为「到该时刻后 daemon 才拾取」，故只能是未来；过去时刻无意义。
// disabledDate 置灰「今天之前」的日期（今天全天可选，当天已过时刻由 disabledTime
// 精确置灰）。判定用 isSame/isBefore 而非 d < startOf('day')，避免毫秒边界误伤。
function disablePastDate(d: dayjs.Dayjs | null) {
  return !!d && d.isBefore(dayjs().startOf('day'));
}

// disabledTime 置灰当天已流逝的小时/分钟/秒；当选中日不是今天时返回空（不限制）。
// 返回结构对齐 antd 6 的 getDisabledHours/getDisabledMinutes/getDisabledSeconds 约定。
function disablePastTime(picked: dayjs.Dayjs | null) {
  const now = dayjs();
  if (!picked || !picked.isSame(now, 'day')) return {};
  return {
    disabledHours: () => rangeArray(0, now.hour()),
    disabledMinutes: (hour: number) => (hour === now.hour() ? rangeArray(0, now.minute()) : []),
    disabledSeconds: (hour: number, minute: number) =>
      hour === now.hour() && minute === now.minute() ? rangeArray(0, now.second()) : [],
  };
}

function rangeArray(start: number, endExclusive: number) {
  const out: number[] = [];
  for (let i = start; i < endExclusive; i += 1) out.push(i);
  return out;
}

// ── 名称列 Why 悬浮提示（对齐 v1 why-hint：悬停 200ms 拉取 proposal 的 ## Why 段） ──
// 提取与缓存逻辑在 src/utils/proposalWhy.ts（任务详情页「任务背景描述」共用）

// ── 悬浮拉取装置（code-review item c7f6a8ebf9d8）：SpecNameCell / VerifyCell
// 曾各自复制 alive/hovered/timer 三件套 + 逐行相同的卸载清理 + 200ms 防抖
// onEnter/onLeave（注释互相引用「同款」），历史修复（2d5f6ca39f91 /
// 3ab32340dfeb / 23afb102a432 / a75e0d5abef0）每条都要双处落补丁。收敛为共享
// hook 单点维护，两个单元格只差取数函数与浮层渲染；回写真值结果，「有结论
// 才弹」之类的过滤并入取数函数。
function useHoverFetch<T>(fetcher: () => Promise<T | null>) {
  const [open, setOpen] = useState(false);
  const [value, setValue] = useState<T | null>(null);
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  // 在飞 promise 守卫（code-review item 23afb102a432 / a75e0d5abef0）：卸载只
  // 清防抖 timer，200ms 已过、fetch 在飞时 promise 仍会回写 setState——行（或
  // 整表）已消失后为已不存在的 spec 开 popover。alive 标志丢弃卸载后的回写；
  // 挂载时复位以兼容 StrictMode 模拟卸载-重挂载（ref 不随重挂载重置）。
  const aliveRef = useRef(true);
  // 悬浮结束哨（code-review item 3ab32340dfeb）：onLeave 只清防抖 timer，已在
  // 飞的 fetch 响应回来仍会回写 setState——鼠标早已离开后浮层凭空弹出且无触
  // 发方再关闭。回写前同时校验「未卸载」与「仍在悬浮」。
  const hoveredRef = useRef(false);

  // 卸载清理（code-review item 2d5f6ca39f91）：悬停启动的 200ms 定时器若在
  // 触发前组件被卸载（列表刷新/行删除/切 Tab），其回调仍会回写 setState，
  // 造成卸载后 setState。统一在卸载时清掉。
  useEffect(() => {
    aliveRef.current = true;
    return () => {
      aliveRef.current = false;
      if (timerRef.current) clearTimeout(timerRef.current);
    };
  }, []);

  const onEnter = () => {
    hoveredRef.current = true;
    // 重复 enter 先清既有防抖定时器（code-review item 80985f592aff）：鼠标未
    // 离开而行内 DOM 被 React 重建（行刷新/SSE patch 触发重挂）时 mouseenter
    // 二次触发，直接覆盖 timerRef 会令旧定时器失去引用无法取消，叠出两次
    // fetch。清理口径与 onLeave / 卸载路径一致。
    if (timerRef.current) clearTimeout(timerRef.current);
    timerRef.current = setTimeout(() => {
      // fetcher 错误语义自洽（code-review item 6795829c24e2）：失败静默不弹。
      // 现状两个消费方均内部吞错返回 null 无触发路径，此处防御后续接入会
      // reject 的取数函数产生 unhandled rejection 污染 no_console_error 断言
      void fetcher().then(
        (v) => {
          if (!aliveRef.current || !hoveredRef.current) return;
          if (v) {
            setValue(v);
            setOpen(true);
          }
        },
        () => {},
      );
    }, 200);
  };
  const onLeave = () => {
    hoveredRef.current = false;
    if (timerRef.current) clearTimeout(timerRef.current);
    setOpen(false);
  };

  return { open, value, onEnter, onLeave };
}

function SpecNameCell({ project, record, dense }: { project: string; record: SpecSummary; dense?: boolean }) {
  // 可点击名称文字色（code-review item 0bcd835938ef 曾改走 colorPrimary，
  // 615f6f350d58 同口径）：宿主对齐改造（2026-11-03）后主色为黑系 #0f1115，
  // 可点击语义改走 dsh 链接蓝 DSH_LINK（theme.ts 单源，dsw alias-link），
  // 与 antd colorLink 驱动的链接元素同色
  const { token } = theme.useToken();
  // 防抖/哨卫/卸载清理走共享 useHoverFetch（code-review item c7f6a8ebf9d8），
  // 本单元格只差取数函数（proposal ## Why 段）与浮层渲染
  const { open, value: why, onEnter, onLeave } = useHoverFetch<string>(
    () => fetchProposalWhy(project, record.name),
  );

  const handleClick = () => {
    // 编码与 index.tsx 同形跳转口径一致（code-review item d075831bfba5）：项目名
    // 源于目录名不限字符集，含 #/?/% 时裸拼接会路由错乱（# 截断为 hash）。
    // 路径单源 specDetailPath（add-spec-subtitle-and-row-click task 2.1）：
    // 与整行点击行导航同源同目标，不拦截、连跳同路由无害
    history.push(specDetailPath(project, record.name));
  };

  return (
    <div style={{ minWidth: 0 }}>
      <Popover
        open={open && !!why}
        placement="topLeft"
        content={
          <div style={{ maxWidth: 420, fontSize: 13, lineHeight: 1.65 }}>
            <Markdown remarkPlugins={LIST_REMARK_PLUGINS} components={markdownComponents}>{why}</Markdown>
          </div>
        }
      >
        <span
          onMouseEnter={onEnter}
          onMouseLeave={onLeave}
          onClick={handleClick}
          role="button"
          tabIndex={0}
          onKeyDown={(e) => {
            // 键盘可达（code-review item 3e07fb4c2b30）：Enter/Space 触发跳转，
            // 口径对齐 ProjectCards 项目名跳转（item b5ed7707672e）
            if (e.key === 'Enter' || e.key === ' ') {
              e.preventDefault();
              handleClick();
            }
          }}
          className={dense ? 'ov-ellipsis' : undefined}
          title={dense ? record.name : undefined}
          style={
            // dense=v2 台账形态（2026-11-06 用户指令）：13.5px 半粗 + 深色单行省略
            //（镜像 v2 projectDetail 名称列）；缺省保持链接蓝 16px（移动卡片同款）
            dense
              ? { cursor: 'pointer', fontSize: 13.5, fontWeight: 600, color: OV_TEXT, display: 'block' }
              : { cursor: 'pointer', fontSize: 16, fontWeight: 600, color: DSH_LINK }
          }
        >
          {record.name}
        </span>
      </Popover>
      {/* add-spec-chinese-title：英文名主行下方的中文标题副标题行（12px、
          tertiary 文字色、单行省略）。副标题不承载点击与悬停交互（Why 悬浮
          仅挂在主行 span 上），title 缺失/空不渲染（保持既有单行形态）；
          桌面表格与移动卡片共用本单元格，树形缩进随主行同级对齐。 */}
      {record.title ? (
        <div
          className="spec-title-sub"
          style={{
            fontSize: 12,
            lineHeight: '18px',
            color: token.colorTextTertiary,
            whiteSpace: 'nowrap',
            overflow: 'hidden',
            textOverflow: 'ellipsis',
            maxWidth: '100%',
          }}
        >
          {record.title}
        </div>
      ) : null}
    </div>
  );
}

// ── 验证列悬浮提示（悬浮显示验证结论，形式同名称 Why 提示） ──

const verdictCache = new Map<
  string,
  { promise: Promise<SpecDetail['verdict'] | null>; at: number }
>();

// 短 TTL（30s）：页面长生命周期下，重验证 run（或任何碰该 spec 的 SSE patch）
// 后永久缓存会让 hover 一直显示陈旧裁决/结论（code-review item 2c54c970f681）。
const VERDICT_CACHE_TTL_MS = 30_000;

function fetchVerdict(project: string, spec: string): Promise<SpecDetail['verdict'] | null> {
  const key = `${project}│${spec}`;
  const cached = verdictCache.get(key);
  const now = Date.now();
  if (cached && now - cached.at < VERDICT_CACHE_TTL_MS) return cached.promise;
  verdictCache.delete(key);
  const p = getSpecDetail(project, spec)
    .then((d) => d.verdict ?? null)
    .catch(() => {
      // 失败结果不入缓存（code-review item a31792c774de）：旧实现把 .catch→null
      // 的 Promise 一并缓存，一次网络抖动就让该 spec 之后永远拿不到 verdict。
      // 失败时剔除缓存项，下次 hover 重试。
      verdictCache.delete(key);
      return null;
    });
  // 写入前顺手清扫过期条目（code-review item e315d824f67a）：模块级缓存无容量
  // 上限，过期条目原本只能靠同 key 再次 hover 覆盖删除，长生命周期页面下 hover
  // 过大量 spec 后 Map 单调增长（promise 及其持有的 verdict 响应对象滞留）。
  // Map 迭代中删除条目安全；刚写入的新条目 at=now 不会被本轮误删。
  for (const [k, v] of verdictCache) {
    if (now - v.at >= VERDICT_CACHE_TTL_MS) verdictCache.delete(k);
  }
  verdictCache.set(key, { promise: p, at: now });
  return p;
}

function VerifyCell({ project, record, pill }: { project: string; record: SpecSummary; pill?: boolean }) {
  // 占位符文字色走 token（code-review item 615f6f350d58）：原 rgba(0,0,0,0.45)
  // 硬编码在暗色主题下近乎不可见，colorTextQuaternary 随主题自适应
  const { token } = theme.useToken();
  // 防抖/哨卫/卸载清理走共享 useHoverFetch（code-review item c7f6a8ebf9d8，与
  // SpecNameCell 同款）；「有结论才弹」过滤并入取数函数（v.exists 之外返回
  // null，hook 不回写），行为与原内联实现一致
  const { open, value: verdict, onEnter, onLeave } = useHoverFetch<NonNullable<SpecDetail['verdict']>>(
    () => fetchVerdict(project, record.name).then((v) => (v && v.exists ? v : null)),
  );

  // fix-verify-progress-fasttrack：无任何验证数据（verify_total 为 0）时渲染占位
  // ——桌面 v2 形态（pill=true，2026-11-06 用户指令）为「未执行」灰胶囊（中文限定
  // 词，合 DESIGN.md null 口径），移动卡片维持「—」文本占位；两形态都不伪装 0/0。
  if (!record.verify_total) {
    return pill ? (
      <Pill tone="muted">未执行</Pill>
    ) : (
      <span style={{ fontSize: 13, color: token.colorTextQuaternary }}>—</span>
    );
  }

  const sum = verdict?.summary;
  return (
    <Popover
      open={open && !!verdict?.exists}
      placement="topLeft"
      content={
        <div style={{ maxWidth: 420, fontSize: 13, lineHeight: 1.65 }}>
          <div>
            <Typography.Text strong>验证结论：</Typography.Text>
            <Typography.Text strong>{verdict?.status}</Typography.Text>
          </div>
          {verdict?.status_detail ? (
            <div style={{ whiteSpace: 'pre-wrap' }}>{verdict.status_detail}</div>
          ) : null}
          {verdict?.conclusion ? (
            <Markdown remarkPlugins={LIST_REMARK_PLUGINS} components={markdownComponents}>
              {verdict.conclusion}
            </Markdown>
          ) : null}
          {sum ? (
            <Typography.Text type="secondary">
              通过 {sum.passed ?? 0} · 失败 {sum.failed ?? 0} · 错误 {sum.errors ?? 0}
              {sum.product_bugs != null ? ` · 产品 bug ${sum.product_bugs}` : ''}
            </Typography.Text>
          ) : null}
        </div>
      }
    >
      <span
        onMouseEnter={onEnter}
        onMouseLeave={onLeave}
        // 键盘可达（code-review item aa30f83d0d76）：本单元格不承载点击交互，
        // 悬浮结论详情是唯一信息路径——focus/blur 复用 onEnter/onLeave，让纯
        // 键盘用户也能读到验证结论（可达性口径对齐 SpecNameCell item
        // 3e07fb4c2b30）；不加 role/onKeyDown，避免暗示可点击。
        tabIndex={0}
        onFocus={onEnter}
        onBlur={onLeave}
        // 可点击文字色走 token（code-review item 0bcd835938ef，同 SpecNameCell）；
        // pill=v2 台账形态（2026-11-06 用户指令）：n/m 计数入灰蓝胶囊（进行中蓝/
        // 完毕灰，镜像 v2 VerifyCell），悬浮/键盘焦点路径不变
        style={
          pill
            ? { cursor: 'pointer', display: 'inline-flex' }
            : { cursor: 'pointer', fontSize: 13, fontWeight: 600, color: DSH_LINK }
        }
      >
        {pill ? (
          <Pill tone={record.verify_done < record.verify_total ? 'info' : 'muted'}>
            {record.verify_done}/{record.verify_total}
          </Pill>
        ) : (
          <>
            {record.verify_done}/{record.verify_total}
          </>
        )}
      </span>
    </Popover>
  );
}

// done/pushed 为终态不再调整优先级；其余状态优先级可点击，样式与验证列一致
const PRIORITY_TERMINAL = new Set(['done', 'pushed']);

// ── 定时拾取标记（add-spec-scheduling-controls D6） ──
// start_after 未到期的 spec 渲染「定时」Tag：目标时间本地渲染 + 分钟级倒计时。
// 倒计时在渲染时刻用 dayjs() 求值，随列表既有刷新节奏（30s 心跳 / SSE 增量 /
// visibilitychange）更新，不另起秒级定时器（design D6）。
function ScheduledPickupTag({ record, pill }: { record: SpecSummary; pill?: boolean }) {
  const sa = record.start_after;
  if (!sa) return null;
  const target = dayjs(sa);
  if (!target.isValid()) return null;
  const diffMin = Math.round(target.diff(dayjs(), 'minute', true));
  if (diffMin < 0) return null; // 已到期：交调度器正常拾取，不再展示等待标记
  const targetLocal = target.format('MM-DD HH:mm');
  const tip = `定时拾取 · ${targetLocal}（本地）启动，约 ${diffMin} 分钟后被 daemon 拾取`;
  const label = diffMin <= 1 ? '即将调度' : `${diffMin}分后`;
  return (
    <Tooltip title={tip}>
      {/* pill 形态（add-spec-list-mobile-style 1.2）：移动卡等待标记组改灰软底
          胶囊（spec.md：独立灰软底胶囊）；桌面 Tag 形态零改动 */}
      {pill ? (
        <Pill tone="muted">{label}</Pill>
      ) : (
        <Tag icon={<ClockCircleOutlined />} color="blue" style={{ marginInlineEnd: 0 }}>
          {label}
        </Tag>
      )}
    </Tooltip>
  );
}

// add-spec-manual-activation D9：start_after == 'manual'（手工激活哨兵）的 spec
// 渲染橙色「待激活」Tag——永不到期、待人工激活。不加状态门槛（渲染只看字段，
// 避免 drafted 态漏标；若后续语义变化不误伤）。ScheduledPickupTag 对 'manual'
// 由 dayjs('manual') Invalid Date 自然返回 null，二者不冲突。
function ManualActivationTag({ record, pill }: { record: SpecSummary; pill?: boolean }) {
  if (record.start_after !== 'manual') return null;
  return (
    <Tooltip title="已设为手工激活，需人工激活后才会被拾取">
      {pill ? (
        // 灰软底胶囊（add-spec-list-mobile-style 1.2，同 StatusWaitGroup pill 契约）
        <Pill tone="muted">待激活</Pill>
      ) : (
        <Tag color="orange" style={{ marginInlineEnd: 0 }}>
          待激活
        </Tag>
      )}
    </Tooltip>
  );
}

// add-spec-manual-activation D9：ready 且有前置依赖的 spec 渲染「前置依赖」Tag
// （hover 展示依赖名列表）。判据依赖后端规范化：record.depends_on 经
// _normalize_depends_on 归一，无依赖为 null/undefined——MUST NOT 用裸真值判定
// （STATE.md 里 `depends_on: null` 解析回字面量字符串 "null"，227/244 条存量
// entry 为此形态，裸真值会全线误标）。仅 ready 展示（用户明确要求：ready 时才
// 提示「为什么就绪却不派发」）；其它状态的依赖信息属详情页职责。
function DependencyTag({ record, pill }: { record: SpecSummary; pill?: boolean }) {
  if (record.status !== 'ready') return null;
  const deps = record.depends_on;
  if (!deps) return null;
  return (
    <Tooltip title={`前置依赖：${deps}`}>
      {pill ? (
        <Pill tone="muted">前置依赖</Pill>
      ) : (
        <Tag color="geekblue" style={{ marginInlineEnd: 0 }}>
          前置依赖
        </Tag>
      )}
    </Tooltip>
  );
}

// 状态列等待标记集：定时拾取 + 待激活 + 前置依赖（桌面与移动端共用）。
// pill：移动卡灰软底胶囊形态（add-spec-list-mobile-style 1.2），桌面缺省 Tag 不变
function StatusWaitGroup({ record, pill }: { record: SpecSummary; pill?: boolean }) {
  return (
    <>
      <ScheduledPickupTag record={record} pill={pill} />
      <ManualActivationTag record={record} pill={pill} />
      <DependencyTag record={record} pill={pill} />
    </>
  );
}

function PriorityCell({
  record,
  onEdit,
  editable = true,
}: {
  record: SpecSummary;
  onEdit: (record: SpecSummary) => void;
  // 归档视图门控（code-review item 740a46d99bf6）：archivedOnly 下
  // specMenuItems 已移除全部调度条目（归档 SPEC 不得重排），内联单元格
  // 点击 MUST 复用同一门——不可编辑时渲染纯文本（与终态分支同形），
  // 不再绕过菜单仍开优先级弹窗。
  editable?: boolean;
}) {
  // 可点击文字色走 token（code-review item 0bcd835938ef，同 SpecNameCell）；
  // useToken MUST 在早退分支之前调用（hook 规则）
  const { token } = theme.useToken();
  if (!editable || PRIORITY_TERMINAL.has(record.status || '')) {
    return <span>P{record.priority ?? '?'}</span>;
  }
  return (
    <span
      onClick={() => onEdit(record)}
      role="button"
      tabIndex={0}
      onKeyDown={(e) => {
        // 键盘可达（code-review item 3ff7b6d80f6f）：Enter/Space 触发优先级
        // 弹窗，口径对齐 SpecNameCell（item 3e07fb4c2b30）
        if (e.key === 'Enter' || e.key === ' ') {
          e.preventDefault();
          onEdit(record);
        }
      }}
      style={{ cursor: 'pointer', fontSize: 13, fontWeight: 600, color: DSH_LINK }}
    >
      P{record.priority ?? '?'}
    </span>
  );
}

/**
 * buildTree 输出节点（code-review item f693a3125b78）：SpecSummary + 归并树
 * children 子节点。树形由前端内存构造（后端 /api/specs 不返回 children），
 * 声明为独立导出类型，buildTree 返回边界与 SpecCardListProps.data 边界统一
 * 使用——避免 children 字段在类型边界被丢弃、下游读 n.children 与声明类型漂移。
 */
export type SpecSummaryNode = SpecSummary & { children?: SpecSummaryNode[] };

/**
 * fix-* 规格归并成树（对齐 v1）：fix-fix-a 的父是 fix-a（若存在），再是 a；
 * 无父 fix 归入顶层。
 */
function buildTree(specs: SpecSummary[]): SpecSummaryNode[] {
  const byName = new Map(specs.map((s) => [s.name, s]));
  const childrenMap = new Map<string, string[]>();
  const roots: SpecSummaryNode[] = [];
  specs.forEach((s) => {
    if (!s.name.startsWith('fix-')) {
      roots.push(s);
      return;
    }
    let candidate = s.name;
    let parent: string | null = null;
    while (candidate.startsWith('fix-')) {
      const up = candidate.slice(4);
      if (byName.has(up)) {
        parent = up;
        break;
      }
      candidate = up;
    }
    // 显式 null/undefined 判等（code-review item 95013c6683be，宽松相等被 lint 禁止）
    if (parent === null || parent === undefined) {
      roots.push(s);
    } else {
      const arr = childrenMap.get(parent) || [];
      arr.push(s.name);
      childrenMap.set(parent, arr);
    }
  });
  const attach = (s: SpecSummary): SpecSummaryNode => {
    const kids = childrenMap.get(s.name);
    return kids ? { ...s, children: kids.map((n) => attach(byName.get(n)!)) } : { ...s };
  };
  return roots.map(attach);
}

interface SpecCardListProps {
  data: SpecSummaryNode[];
  project: string;
  loading: boolean;
  onDocView: (spec: string) => void;
  onMenu: (record: SpecSummary, key: string) => void;
  menuItems: (record: SpecSummary) => MenuProps['items'];
  onClearError: (record: SpecSummary) => void;
}

// 移动端（<768px）卡片形态（add-spec-list-mobile-style 重绘，UI 真相源
// specs/dashboard-spec-table/prototype/index.html）：白磁贴（12px 圆角发丝边）
// 内发丝线分卡，镜像桌面 .ov-bento 磁贴语态（D1 不逐卡开卡框）；卡 = 英文名主行
// → 中文标题次行 → 语义胶囊行 → 阶段进度区 → 元信息行 → 验证行 → 信息行；
// fix-* 子卡缩进 26px + └ 前缀灰符；整卡点击进详情（specDetailPath 单源）。
// 仅在 md 断点以下渲染，桌面 Table 分支不受影响。
function SpecCardList({ data, project, loading, onDocView, onMenu, menuItems, onClearError }: SpecCardListProps) {
  // token 消费（验证行 ✓/⚠ 色与 caption 三阶灰随主题；移动卡状态胶囊色点走
  // Pill pair 前景色，不再各自取 useToneDot）
  const { token } = theme.useToken();
  type FlatNode = { record: SpecSummary; level: number };
  const flat = useMemo<FlatNode[]>(() => {
    const out: FlatNode[] = [];
    const walk = (nodes: SpecSummaryNode[], level: number) => {
      nodes.forEach((n) => {
        out.push({ record: n, level });
        if (n.children) walk(n.children, level + 1);
      });
    };
    walk(data, 0);
    return out;
  }, [data]);

  // 分页改磁贴底部「加载更多」（任务 2.3）：pageSize 20 语义保持（数据层分页
  // 不变），替代 antd List 分页器；过滤/树变化时回到首页
  const [visibleCount, setVisibleCount] = useState(SPEC_CARD_PAGE_SIZE);
  useEffect(() => {
    setVisibleCount(SPEC_CARD_PAGE_SIZE);
  }, [data]);
  const shown = useMemo(() => flat.slice(0, visibleCount), [flat, visibleCount]);

  return (
    <div
      className="spec-card-tile"
      // 磁贴形态镜像 .ov-bento（global.less 同值：白底 + #eef2f7 发丝边 + 12px
      // 圆角 + V2_TILE_SHADOW 软阴影）；样式走 JSX 内联不新增 less（D6）
      style={{
        background: '#ffffff',
        border: `1px solid ${OV_HAIRLINE}`,
        borderRadius: 12,
        boxShadow: '0 1px 3px rgba(15, 23, 42, 0.05), 0 1px 2px rgba(15, 23, 42, 0.03)',
        overflow: 'hidden',
      }}
    >
      <List
        split={false}
        loading={loading}
        dataSource={shown}
        // 按行数据身份复用节点（code-review item add168d205dc）：SSE patch 删除
        // 行后避免按索引复用，行状态随正确行走（与桌面 Table rowKey 对齐）
        rowKey={(n) => n.record.name}
        renderItem={({ record, level }) => {
          const m = statusMeta(record.status || '');
          const created = record.created ? dayjs(record.created) : null;
          // 阶段感知进度（code-review item e1f8a359480d）：与桌面「任务进度」列
          // 共用 phaseProgressOf 单源，两侧口径一致
          const prog = phaseProgressOf(record);
          const terminal = PRIORITY_TERMINAL.has(record.status || '');
          // 草稿 / impl 阶段无任务清单 → 口径不可得显「—」（D3：0 与口径不可得
          // 分离，MUST NOT 显示假 0）；verify/gates 阶段 0/0 是真实阶段口径照常显示
          const noTasks = !prog.isVerify && !prog.isGates && (record.task_total ?? 0) === 0;
          return (
            <List.Item
              data-testid="spec-mobile-card"
              data-spec={record.name}
              // 整卡点击进详情（specDetailPath 单源）；行内交互（⋮ 菜单/清除按钮）
              // 各自 stopPropagation 不被吞
              onClick={() => history.push(specDetailPath(project, record.name))}
              style={{
                display: 'block',
                padding: '12px 14px',
                // fix-* 子卡缩进 26px + 名称行 └ 前缀灰符（树形语义，buildTree 单源不变）
                paddingLeft: level > 0 ? 26 : 14,
                cursor: 'pointer',
                background: 'transparent',
              }}
            >
              {/* 英文名主行：14px/600 单行省略（tap 目标为整卡） */}
              <div
                className="spec-card-name"
                title={record.name}
                style={{
                  fontSize: 14,
                  fontWeight: 600,
                  color: OV_TEXT,
                  lineHeight: '20px',
                  overflow: 'hidden',
                  textOverflow: 'ellipsis',
                  whiteSpace: 'nowrap',
                  minWidth: 0,
                }}
              >
                {level > 0 ? (
                  <span aria-hidden style={{ color: token.colorTextQuaternary, fontWeight: 400, marginRight: 2 }}>
                    └
                  </span>
                ) : null}
                {record.name}
              </div>
              {/* 中文标题次行：12px 三阶灰单行省略；title 缺失不渲染（缺失=无该行） */}
              {record.title ? (
                <div
                  className="spec-card-cn"
                  style={{
                    marginTop: 2,
                    fontSize: 12,
                    lineHeight: '18px',
                    color: OV_TEXT_TERTIARY,
                    overflow: 'hidden',
                    textOverflow: 'ellipsis',
                    whiteSpace: 'nowrap',
                  }}
                >
                  {record.title}
                </div>
              ) : null}
              {/* 语义胶囊行：状态 tone 色对带色点 + 等待标记灰软底 + 模式胶囊 + ⋮ 更多 */}
              <div className="spec-card-pills" style={{ display: 'flex', alignItems: 'center', gap: 6, marginTop: 8, flexWrap: 'wrap', minWidth: 0 }}>
                <Pill tone={m.tone} dot>
                  {m.label}
                </Pill>
                <StatusWaitGroup record={record} pill />
                {/* 模式胶囊单源 ModePill（与桌面模式列同源）；存量无 mode 字段
                    按缺省 full 展示「标准」 */}
                <ModePill mode={record.mode} />
                <span style={{ marginLeft: 'auto', flex: '0 0 auto' }} onClick={(e) => e.stopPropagation()}>
                  <Dropdown
                    menu={{
                      // 「查看文档」并入首项（与桌面操作列同构，入口恒可见）；
                      // 菜单其余项仍由 onMenu 单点承载（specMenuItems 含归档收敛）
                      items: [{ key: 'doc', label: '查看文档' }, ...(menuItems(record) || [])],
                      onClick: ({ key, domEvent }) => {
                        domEvent.stopPropagation();
                        if (key === 'doc') {
                          onDocView(record.name);
                          return;
                        }
                        onMenu(record, key);
                      },
                    }}
                    placement="bottomRight"
                    trigger={['click']}
                  >
                    {/* 32px 触控目标（spec.md THEN：⋮ 更多 32px 触控目标） */}
                    <Button type="text" size="small" icon={<DotsIcon />} aria-label="更多操作" style={{ minWidth: 32, height: 32 }} />
                  </Dropdown>
                </span>
              </div>
              {/* 阶段进度区：终态卡省略（D3 不重复画 100% 条）；草稿/无任务计数
                  显「—」；其余 阶段名 + 「计数 · 百分比」同行在上 + ramp 色条
                  （progressPhase 单源 strokeColorFor/trailColorFor，禁另写色表） */}
              {terminal ? null : noTasks ? (
                <div className="spec-card-progress-empty" style={{ display: 'flex', alignItems: 'center', gap: 10, marginTop: 9, fontSize: 12, color: OV_TEXT_TERTIARY }}>
                  <span>任务进度</span>
                  <span className="ov-num">—</span>
                </div>
              ) : (
                <div className="spec-card-progress" style={{ marginTop: 10 }}>
                  <div style={{ display: 'flex', alignItems: 'baseline', justifyContent: 'space-between', gap: 8 }}>
                    <span style={{ fontSize: 12, color: OV_TEXT_TERTIARY }}>{prog.label}</span>
                    <span className="ov-num" data-testid="spec-card-progress-count" style={{ fontSize: 12, color: OV_TEXT_TERTIARY }}>
                      {prog.counter} · {progressText(prog.percent)}
                    </span>
                  </div>
                  <div
                    style={{
                      marginTop: 5,
                      height: 6,
                      borderRadius: 999,
                      background: trailColorFor(!!prog.gen, prog.isVerify, prog.isGates),
                      overflow: 'hidden',
                    }}
                  >
                    <div
                      style={{
                        height: '100%',
                        borderRadius: 999,
                        width: `${prog.percent}%`,
                        background: strokeColorFor(!!prog.gen, prog.isVerify, prog.isGates),
                      }}
                    />
                  </div>
                </div>
              )}
              {/* 元信息行：优先级 | 创建时间 | 耗时（12px tabular-nums 竖线分隔）；
                  run 活跃追加「● 运行中」（success 色，静态） */}
              <div
                className="ov-num spec-card-meta"
                style={{ display: 'flex', alignItems: 'center', gap: 10, marginTop: 9, fontSize: 12, color: OV_TEXT_TERTIARY, flexWrap: 'wrap' }}
              >
                <span>P{record.priority ?? '?'}</span>
                <span aria-hidden style={{ color: OV_BORDER }}>|</span>
                <span>{created && created.isValid() ? created.format('YYYY-MM-DD HH:mm') : '—'}</span>
                <span aria-hidden style={{ color: OV_BORDER }}>|</span>
                <span>耗时 {fmtDuration(record.total_duration)}</span>
                {record.run_activity?.active ? (
                  <span data-testid="spec-card-running" style={{ color: token.colorSuccess }}>● 运行中</span>
                ) : null}
              </div>
              {/* 验证行：异常 ⚠ 红（悬浮提示保留）/ 通过 ✓ 绿 / 进行中 n/m 三阶灰；
                  无验证数据不渲染（缺失=无该行） */}
              {record.verify_error ? (
                <Tooltip title={record.verify_error}>
                  <div className="spec-card-verify-bad" style={{ display: 'flex', alignItems: 'center', gap: 6, marginTop: 8, fontSize: 12, color: token.colorError }}>
                    <span>⚠</span>
                    <span>验证异常</span>
                  </div>
                </Tooltip>
              ) : record.verify_total > 0 ? (
                <div className="spec-card-verify" style={{ display: 'flex', alignItems: 'center', gap: 6, marginTop: 8, fontSize: 12 }}>
                  {record.verify_done >= record.verify_total ? (
                    <>
                      <span style={{ color: token.colorSuccess }}>✓</span>
                      <span style={{ color: OV_TEXT_TERTIARY }}>
                        验证 {record.verify_done}/{record.verify_total} 通过
                      </span>
                    </>
                  ) : (
                    <span style={{ color: OV_TEXT_TERTIARY }}>
                      验证 {record.verify_done}/{record.verify_total}
                    </span>
                  )}
                </div>
              ) : null}
              {/* 信息行：amber 软底圆角条、橙「信息」前缀、摘要单行省略 + 清除
                  （信息清除既有契约保留，dashboard-spec-table 清除链路不变） */}
              {record.error ? (
                <div
                  className="spec-card-info-row"
                  style={{ display: 'flex', alignItems: 'center', gap: 6, marginTop: 8, background: OV_AMBER_SOFT, borderRadius: 6, padding: '6px 8px' }}
                >
                  <span style={{ fontSize: 12, color: OV_WARNING, flex: '0 0 auto' }}>信息</span>
                  <span
                    style={{ flex: 1, minWidth: 0, fontSize: 12, color: OV_AMBER_TEXT, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}
                  >
                    {record.error}
                  </span>
                  <Button
                    size="small"
                    onClick={(e) => {
                      e.stopPropagation();
                      onClearError(record);
                    }}
                  >
                    清除
                  </Button>
                </div>
              ) : null}
            </List.Item>
          );
        }}
      />
      {/* 磁贴底部「加载更多」+ 计数 caption（原型 loadmore-wrap 形态）；空表 /
          加载中不渲染（防「共 0 条」闪烁） */}
      {!loading && flat.length > 0 ? (
        <div style={{ padding: '12px 14px', borderTop: `1px solid ${OV_HAIRLINE}` }}>
          <Button
            block
            size="middle"
            data-testid="spec-load-more"
            disabled={shown.length >= flat.length}
            onClick={() => setVisibleCount((c) => c + SPEC_CARD_PAGE_SIZE)}
          >
            加载更多
          </Button>
          <div className="ov-num" style={{ textAlign: 'center', marginTop: 8, fontSize: 11, color: token.colorTextQuaternary }} data-testid="spec-load-caption">
            共 {flat.length} 条 · 已显示 {Math.min(visibleCount, flat.length)} 条
          </div>
        </div>
      ) : null}
    </div>
  );
}

// ── 「功能开发」分面视图（code-review item 99be1f625d52）──────────────────
// 过滤条 + 桌面表格/移动卡片编排 + 列定义抽为 DevTab 子组件：主组件
// SpecListPage 只保留数据流（SSE patch 队列 / URL 过滤写回 / 展开树闩锁）、
// 弹窗状态与全部动作 handler，经 props 下行（回调收窄为 (record) => void、
// state 与 setter 直传，形态与 SpecCardListProps 同款），行为零变化。
interface DevTabProps {
  project: string;
  isMobile: boolean;
  /** 加载失败提示：非空时本分面顶部渲染 Alert */
  error: string;
  q: string;
  onQueryChange: (q: string) => void;
  statusList: string[];
  onStatusListChange: (v: string[]) => void;
  type: TypeFilter;
  onTypeChange: (v: TypeFilter) => void;
  archivedOnly: boolean;
  onArchivedOnlyChange: (v: boolean) => void;
  tree: SpecSummaryNode[];
  loading: boolean;
  expandedKeys: readonly Key[];
  onExpandedKeysChange: (keys: readonly Key[]) => void;
  onDocView: (spec: string) => void;
  onEditPriority: (record: SpecSummary) => void;
  onMenu: (record: SpecSummary, key: string) => void;
  menuItems: (record: SpecSummary) => MenuProps['items'];
  onClearError: (record: SpecSummary) => void;
  /** 状态 chips 计数（add-spec-list-mobile-style 2.1）：keyword/type/archived
   * 过滤后（不含状态过滤）按状态计数，与 statusTotal 同源于 SpecListPage
   * preStatus 集合——chips 徽标反映「选该状态会看到多少条」 */
  statusCounts: Record<string, number>;
  statusTotal: number;
}

// 移动端排序键（add-spec-list-mobile-style 2.2/D4）：键集合与桌面表头一致
type MobileSortKey = 'name' | 'priority' | 'progress' | 'created';

function DevTab({
  project,
  isMobile,
  error,
  q,
  onQueryChange,
  statusList,
  onStatusListChange,
  type,
  onTypeChange,
  archivedOnly,
  onArchivedOnlyChange,
  tree,
  loading,
  expandedKeys,
  onExpandedKeysChange,
  onDocView,
  onEditPriority,
  onMenu,
  menuItems,
  onClearError,
  statusCounts,
  statusTotal,
}: DevTabProps) {
  // 行底色/状态点/验证中文案色走 token（code-review item 615f6f350d58）：
  // useToken 只能在组件内调用
  const { token } = theme.useToken();

  // 移动筛选编排呈现态（add-spec-list-mobile-style 2.2）：Drawer 开合与排序键
  // 不入 URL（过滤 stickiness 白名单契约不变——类型/归档仍走既有 state 写回，
  // 排序为移动端呈现态，桌面无此控件）
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [sortKey, setSortKey] = useState<MobileSortKey>('created');
  // 排序（D4：键集合与桌面表头一致——名称/优先级/进度/创建时间）。创建时间=
  // 现产默认排序（created 倒序，即 tree 原序）零变化；其余键对树根排序，
  // children 随父移动（fix-* 子树保持挂在父下）
  const sortedTree = useMemo(() => {
    if (sortKey === 'created') return tree;
    const cmp =
      sortKey === 'name'
        ? (a: SpecSummary, b: SpecSummary) => a.name.localeCompare(b.name)
        : sortKey === 'priority'
          ? (a: SpecSummary, b: SpecSummary) => (a.priority ?? 999) - (b.priority ?? 999)
          : (a: SpecSummary, b: SpecSummary) => progressSortPct(a) - progressSortPct(b);
    return [...tree].sort(cmp);
  }, [tree, sortKey]);
  // 状态 chips（任务 2.1）：全部 + 各状态 + 计数徽标（激活态黑底白字走
  // DSH_PRIMARY 单源，镜像 overview Radio 黑底白字惯例）
  const statusChips = useMemo(
    () => [
      { key: 'all', label: '全部', n: statusTotal },
      ...LIST_STATUSES.map((k) => ({ key: k, label: statusMeta(k).label, n: statusCounts[k] ?? 0 })),
    ],
    [statusCounts, statusTotal],
  );

  // 九列 width 合计归一 100%（code-review item dafbe62b7e29）：原合计 110%
  // （12+9+28+7+13+15+8+8+10），tableLayout='fixed' 且未启用 scroll.x 时超
  // 额定宽依赖浏览器按比例归一；等比缩到 11+8+25+6+12+14+8+8+8=100 后，
  // 2026-11-06 用户指令再收窄：状态/模式两列等宽 7%（原 11/8），腾出 4 给
  // 名称列（25→29），现合计 7+7+30+6+12+14+8+8+8=100，列宽视觉权重不变。
  // （code-review item 9c4225623333：29% 实算合计 99，名称列补足 1% 至 30
  // 恢复归一不变量）
  const columns: ColumnsType<SpecSummary> = [
    {
      title: '状态',
      dataIndex: 'status',
      key: 'status',
      // 状态/模式两列等宽收窄（2026-11-06 用户指令；腾出宽度给名称列）
      width: '7%',
      sorter: (a: SpecSummary, b: SpecSummary) => (a.status || '').localeCompare(b.status || ''),
      onHeaderCell: () => ({ style: { whiteSpace: 'nowrap', paddingInline: 8 } }),
      onCell: () => ({ style: { whiteSpace: 'nowrap', paddingInline: 8 } }),
      render: (v: string | null, record: SpecSummary) => {
        const m = statusMeta(v || '');
        // v2 台账形态（2026-11-06 用户指令）：状态从「色点+文字」改语义胶囊
        // （镜像 v2 V2StatusPill）；等待标记组（定时/待激活/前置依赖）保留
        return (
          <Space size={4} wrap>
            <Pill tone={m.tone}>{m.label}</Pill>
            <StatusWaitGroup record={record} />
          </Space>
        );
      },
    },
    {
      title: '模式',
      dataIndex: 'mode',
      key: 'mode',
      width: '7%',
      sorter: (a: SpecSummary, b: SpecSummary) => (a.mode || '').localeCompare(b.mode || ''),
      onHeaderCell: () => ({ style: { whiteSpace: 'nowrap', paddingInline: 8 } }),
      onCell: () => ({ style: { whiteSpace: 'nowrap', paddingInline: 8 } }),
      // add-fast-track-mode（task 7.2）：执行模式标记——桌面表格改 v2 胶囊形态
      //（2026-11-06 用户指令，镜像 v2 MODE_LABEL：fast-track=快速/full=标准）；
      // 移动卡片与详情页仍走单源 ModeTag（504cf2d4b647），存量无 mode 字段按
      // 缺省 full 展示「标准」等价标记
      render: (v: string | null | undefined) => (
        // add-spec-list-mobile-style D2：模式胶囊抽 ModePill 单源（桌面列与
        // 移动卡共用），渲染形态与本列原内联实现一致
        <ModePill mode={v} />
      ),
    },
    {
      title: '名称',
      dataIndex: 'name',
      key: 'name',
      width: '30%',
      sorter: (a: SpecSummary, b: SpecSummary) => a.name.localeCompare(b.name),
      render: (_: string, record: SpecSummary) => (
        // dense：v2 台账名称形态（13.5px 半粗深色单行省略），悬浮 Why 提示/键盘
        // 跳转不变；移动卡片走缺省链接蓝形态
        <SpecNameCell project={project} record={record} dense />
      ),
    },
    {
      title: '优先级',
      dataIndex: 'priority',
      key: 'priority',
      width: '6%',
      sorter: (a: SpecSummary, b: SpecSummary) => (a.priority ?? 999) - (b.priority ?? 999),
      // 表头不换行（v2 台账形态单行表头；6% 定宽下三字头会折行）
      onHeaderCell: () => ({ style: { whiteSpace: 'nowrap', paddingInline: 8 } }),
      render: (_: number | null, record: SpecSummary) => (
        <PriorityCell
          record={record}
          editable={!archivedOnly}
          onEdit={onEditPriority}
        />
      ),
    },
    {
      title: '创建时间',
      dataIndex: 'created',
      key: 'created',
      width: '12%',
      sorter: (a: SpecSummary, b: SpecSummary) => (a.created || '').localeCompare(b.created || ''),
      render: (v: string | null) => {
        const d = v ? dayjs(v) : null;
        // v2 台账形态（2026-11-06 用户指令）：等宽数字 + 三阶灰（12.5px），
        // 精度保持完整时间戳不随视觉收缩
        return d && d.isValid() ? (
          <span className="ov-num" style={{ fontSize: 12.5, color: OV_TEXT_TERTIARY }}>
            {d.format('YYYY-MM-DD HH:mm:ss')}
          </span>
        ) : (
          <span className="ov-num" style={{ color: OV_TEXT_TERTIARY }}>—</span>
        );
      },
    },
    {
      title: '任务进度',
      key: 'task',
      width: '14%',
      // add-task-progress-verify-phase：排序键跟随显示值——verify 阶段按验证完成度，
      // impl 阶段按任务完成度，消除「显示 A 排序按 B」错位。
      // code-review item c3df4a612450：gen 出题阶段排序键同步 renderPercent
      // （含 generation 分支），与单元格显示值一致。
      sorter: (a: SpecSummary, b: SpecSummary) => progressSortPct(a) - progressSortPct(b),
      render: (_: unknown, record: SpecSummary) => {
        // 阶段感知推导单点在 phaseProgressOf（code-review item e1f8a359480d）：
        // 与移动端卡片、排序键共用，本列不再各自内联 gen/计数分支。
        const { percent: p, label, counter, isVerify, isGates, gen } = phaseProgressOf(record);
        // run 层实时线索（fix-implementer-task-progress D3）：tasks.md 快照落后于
        // run 实际推进（subject 无编号 / agent 未勾 tasks.md）时叠加 run 完成度，
        // 任一数据源失效都不再呈现静止的 0/N；快照已覆盖时不重复打扰。
        // 仅 impl 分支参与渲染——verify 阶段 impl run 已结束，线索无意义。
        const rp = record.run_progress;
        const runAhead = !!rp && rp.done > record.task_done;
        // run-progress-current：done=0 阶段也有进行中任务的观感
        const runCurrent = rp?.current && rp.current.length > 0 ? rp.current : null;
        // 存活心跳（2026-09-15 原地补充）：run_progress 依赖 TaskCreate/TaskUpdate；
        // 该工具族虽经 CLAUDE_CODE_ENABLE_TODO_TOOLS=1 恢复，实现期间 agent 未必
        // 立刻建 Task、历史 run 也可能无事件。run_activity 用「产物是否仍在写」
        // 提供不依赖任务工具的存活线索，仅在无更细粒度线索（current）时兜底显示。
        const runActive = !isVerify && !runCurrent && !!record.run_activity?.active;
        // v2 台账形态（2026-11-06 用户指令）：阶段名 + 「计数 · 百分比」同行在
        // 进度条上方（镜像 v2 PhaseProgressCell 版式）；阶段名 label 与 gen 出题
        // 分支去前缀计数均来自 phaseProgressOf 单源（2d64a13ea499，移动卡片同源）。
        // 配色不走 v2 ramp：进度条阶段 ramp（progressPhase.ts）是 DESIGN.md 登记
        // 的数据编码色豁免，底轨随阶段同 ramp 的「空条可辨」语义优先保留。
        return (
          <div style={{ minWidth: 0 }}>
            <div style={{ display: 'flex', alignItems: 'baseline', justifyContent: 'space-between', gap: 8 }}>
              <span style={{ fontSize: 12, color: OV_TEXT_TERTIARY }}>{label}</span>
              {/* add-quality-gates-visibility：gates 阶段计数=门禁完成度，
                  run 层线索（run_progress/存活心跳）不渲染——门禁完成度由
                  落盘文件与后端合成驱动，run 任务汇报与门禁无对应关系。
                  计数文案统一来自 phaseProgressOf 的 counter（阶段已分流）。
                  2026-11-06 用户指令：计数与左侧阶段名同款（12px 三阶灰常规
                  字重），不走 v2 的深色半粗形态 */}
              <span className="ov-num" style={{ fontSize: 12, color: OV_TEXT_TERTIARY }} data-testid="task-progress-cell">
                {counter} ·{' '}
                {/* 完成态文案与移动端卡片同口径（code-review item cf0a2e1103b9）：
                    progress >= 100 显示「已完成」，两形态不再分叉 */}
                {progressText(p)}
              </span>
            </div>
            {/* 底轨随阶段同 ramp：verify 阶段 0/0 空条靠底轨读出「淡绿=验证未开始」，
                否则与 impl 蓝色空条同观感，误读成任务没完成（add-task-progress-verify-phase 补充）。 */}
            <div style={{ marginTop: 6 }}>
              <Progress
                percent={p}
                size="small"
                showInfo={false}
                strokeColor={strokeColorFor(!!gen, isVerify, isGates)}
                trailColor={trailColorFor(!!gen, isVerify, isGates)}
              />
            </div>
            {!isVerify && !isGates && (runAhead || runCurrent || runActive) ? (
              // run 层线索与计数换行分离（与 verify_current/gates_current 同款
              // 二行结构统一）；marginLeft 4 保留 run 已汇报与进行中并存时的间距
              <div style={{ fontSize: 12, lineHeight: '18px', marginTop: 2 }}>
                {runAhead && rp ? (
                  <Typography.Text type="warning">
                    run {rp.done}/{rp.total} 已汇报
                  </Typography.Text>
                ) : null}
                {runCurrent ? (
                  <Typography.Text type="warning" style={{ marginLeft: 4 }}>
                    进行中 {runCurrent.join('、')}
                  </Typography.Text>
                ) : null}
                {runActive ? (
                  <Typography.Text type="warning" data-testid="run-activity-active">
                    进行中
                  </Typography.Text>
                ) : null}
              </div>
            ) : null}
            {isVerify && record.verify_current ? (
              // 验证进行中文案走 colorSuccess（code-review item 615f6f350d58）：
              // 与状态点 good tone 同源，暗色随 token
              <div style={{ fontSize: 12, lineHeight: '18px', marginTop: 2, color: token.colorSuccess }}>
                {record.verify_current}
              </div>
            ) : null}
            {isGates && record.gates_current ? (
              // add-quality-gates-visibility：gates 阶段辅助文案（running 门或
              // failed 归因，后端非空才返回），橙字与进度条同色系（复用常量防漂移）
              <div style={{ fontSize: 12, lineHeight: '18px', marginTop: 2, color: GATES_STROKE }}>
                {record.gates_current}
              </div>
            ) : null}
          </div>
        );
      },
    },
    {
      title: '验证',
      key: 'verify',
      width: '8%',
      sorter: (a: SpecSummary, b: SpecSummary) =>
        pct(a.verify_done, a.verify_total) - pct(b.verify_done, b.verify_total),
      render: (_: unknown, record: SpecSummary) =>
        // v2 台账形态（2026-11-06 用户指令）：验证异常=红胶囊（悬浮提示保留）、
        // 计数=灰蓝胶囊（进行中蓝/完毕灰，悬浮结论 Popover 路径在 VerifyCell
        // pill 分支内不变）
        record.verify_error ? (
          <Tooltip title={record.verify_error}>
            <Pill tone="critical">验证异常</Pill>
          </Tooltip>
        ) : (
          <VerifyCell project={project} record={record} pill />
        ),
    },
    {
      title: '耗时',
      dataIndex: 'total_duration',
      key: 'duration',
      width: '8%',
      align: 'right',
      // 空值兜底（code-review item 826c6a25ac54）：total_duration 可选，
      // 直接相减得 NaN 使排序不可预期；?? 0 归一。
      sorter: (a: SpecSummary, b: SpecSummary) =>
        (a.total_duration ?? 0) - (b.total_duration ?? 0),
      // v2 台账形态（2026-11-06 用户指令）：右对齐 + 等宽数字
      render: (v: number) => (
        <span className="ov-num" style={{ fontSize: 12.5, color: OV_TEXT }}>
          {fmtDuration(v)}
        </span>
      ),
    },
    {
      title: '操作',
      key: 'actions',
      width: '8%',
      align: 'right',
      // v2 台账形态（2026-11-06 用户指令）：触发器改三点图标（与 overview 台账
      // 操作列同款），「文档」并入菜单首项——文档入口仍恒可见可达（dashboard-
      // spec-table 契约的入口位随用户指令迁移）；菜单其余项仍由 onMenu 单点承载
      render: (_: unknown, record: SpecSummary) => (
        <Space size={4} onClick={(e) => e.stopPropagation()}>
          <Dropdown
            menu={{
              items: [{ key: 'doc', label: '文档' }, ...(menuItems(record) || [])],
              onClick: ({ key, domEvent }) => {
                domEvent.stopPropagation();
                if (key === 'doc') {
                  onDocView(record.name);
                  return;
                }
                onMenu(record, key);
              },
            }}
            placement="bottomRight"
            trigger={['click']}
          >
            <Button type="text" size="small" icon={<DotsIcon />} aria-label="更多操作" />
          </Dropdown>
        </Space>
      ),
    },
  ];

  return (
    <>
      {error ? (
        <Alert type="error" showIcon style={{ marginBottom: 16 }} message="SPEC 列表加载失败" description={error} />
      ) : null}
      {isMobile ? (
        // 移动筛选编排（add-spec-list-mobile-style 任务 2.1-2.4）：内容区背景
        // 白底（theme.ts SPEC_LIST_MOBILE_BG 单源；2026-11-07 用户指令由
        // #E3E3E3 灰改白，DESIGN.md 修正案条款已同步）+
        // 搜索行 + 状态 chips 横滚 + 磁贴卡列表 + 筛选底部 Drawer。负 margin
        // 与 global.less <768 children-container padding-inline:12 对应（两处
        // 同改），背景铺满内容区。桌面分支（下方）零改动。
        <div
          className="spec-mobile-content"
          style={{ background: SPEC_LIST_MOBILE_BG, margin: '0 -12px', padding: '12px 12px 24px' }}
        >
          <div style={{ display: 'flex', gap: 8, marginBottom: 8 }}>
            <Input.Search
              placeholder="搜索英文名 / 中文标题"
              allowClear
              value={q}
              onChange={(e) => onQueryChange(e.target.value)}
              style={{ flex: 1 }}
            />
            <Button data-testid="spec-filter-trigger" style={{ height: 32, minWidth: 32, paddingInline: 10 }} onClick={() => setDrawerOpen(true)}>
              筛选
            </Button>
          </div>
          {/* 状态筛选横向滚动 chips（原型 chips-row 形态）：全部 + 各状态 +
              计数徽标；激活黑底白字（DSH_PRIMARY 单源），再点取消回「全部」。
              specKeywordHit 命中语义不在此处（SpecListPage filtered 单源零改动） */}
          <div className="spec-status-chips" style={{ display: 'flex', gap: 8, overflowX: 'auto', paddingBottom: 2, marginBottom: 10 }}>
            {statusChips.map((c) => {
              const active = c.key === 'all' ? statusList.length === 0 : statusList.includes(c.key);
              return (
                <span
                  key={c.key}
                  data-testid={`status-chip-${c.key}`}
                  onClick={() => onStatusListChange(c.key === 'all' || active ? [] : [c.key])}
                  style={{
                    flex: '0 0 auto',
                    height: 30,
                    padding: '0 12px',
                    borderRadius: 999,
                    border: `1px solid ${active ? DSH_PRIMARY : OV_BORDER}`,
                    background: active ? DSH_PRIMARY : '#ffffff',
                    color: active ? '#ffffff' : OV_TEXT_TERTIARY,
                    fontSize: 12,
                    display: 'inline-flex',
                    alignItems: 'center',
                    cursor: 'pointer',
                    userSelect: 'none',
                  }}
                >
                  {c.label}
                  <span
                    // 主色黑底上的降透白计数（原型 chip-active .chip-n 同值）
                    style={{ marginLeft: 5, fontSize: 11, color: active ? OV_ON_PRIMARY_DIM : token.colorTextQuaternary, fontVariantNumeric: 'tabular-nums' }}
                  >
                    {c.n}
                  </span>
                </span>
              );
            })}
          </div>
          <SpecCardList
            data={sortedTree}
            project={project}
            loading={loading}
            onDocView={onDocView}
            onMenu={onMenu}
            menuItems={menuItems}
            onClearError={onClearError}
          />
          {/* 筛选底部 Drawer（任务 2.2）：类型/归档/排序三组 Segmented，选择
              即时生效，「查看结果」仅收起 Drawer（原型同构） */}
          <Drawer
            data-testid="spec-filter-drawer"
            title="筛选与排序"
            placement="bottom"
            open={drawerOpen}
            onClose={() => setDrawerOpen(false)}
            // antd v6 现行 API（styles.wrapper；design Risks：不用弃用 height 参数）
            styles={{ wrapper: { height: 380 }, body: { paddingBottom: 24 } }}
            footer={
              <Button block type="primary" data-testid="spec-filter-apply" onClick={() => setDrawerOpen(false)}>
                查看结果
              </Button>
            }
          >
            <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
              <div>
                <div style={{ fontSize: 12, color: OV_TEXT_TERTIARY, marginBottom: 8 }}>类型</div>
                {/* 类型过滤语义与现产一致（任务 2.2 约束句）：全部/进行中/已完成
                    进度语义（ListTypeFilter 值域单源 listFilters.ts），仅呈现换
                    Segmented 承载（spec.md「全部/开发/fix-*」标签为原型假数据
                    表述，与现产语义约束冲突处以约束句为准） */}
                <Segmented
                  block
                  value={type}
                  onChange={(v) => onTypeChange(v as TypeFilter)}
                  options={[
                    { label: '全部', value: '' },
                    { label: '进行中', value: 'active' },
                    { label: '已完成', value: 'completed' },
                  ]}
                />
              </div>
              <div>
                <div style={{ fontSize: 12, color: OV_TEXT_TERTIARY, marginBottom: 8 }}>归档</div>
                <Segmented
                  block
                  value={archivedOnly ? 'archived' : 'open'}
                  onChange={(v) => onArchivedOnlyChange(v === 'archived')}
                  options={[
                    { label: '未归档', value: 'open' },
                    { label: '已归档', value: 'archived' },
                  ]}
                />
              </div>
              <div>
                <div style={{ fontSize: 12, color: OV_TEXT_TERTIARY, marginBottom: 8 }}>排序</div>
                <Segmented
                  block
                  value={sortKey}
                  onChange={(v) => setSortKey(v as MobileSortKey)}
                  options={[
                    { label: '名称', value: 'name' },
                    { label: '优先级', value: 'priority' },
                    { label: '进度', value: 'progress' },
                    { label: '创建时间', value: 'created' },
                  ]}
                />
              </div>
            </div>
          </Drawer>
        </div>
      ) : (
        <>
      <Card variant="borderless" className="projects-page">
        <div
          style={{
            marginBottom: 16,
            display: 'flex',
            flexWrap: 'wrap',
            alignItems: 'center',
            gap: 8,
          }}
        >
          <Space wrap size={8}>
            <Input.Search
              placeholder="搜索名称…"
              allowClear
              value={q}
              onChange={(e) => onQueryChange(e.target.value)}
              style={{ width: 200 }}
            />
            <Select
              mode="multiple"
              showSearch={false}
              allowClear
              placeholder="全部状态"
              maxTagCount="responsive"
              value={statusList}
              onChange={onStatusListChange}
              style={{ minWidth: 200, maxWidth: 300 }}
              options={LIST_STATUSES.map((k) => ({ value: k, label: statusMeta(k).label }))}
            />
            <Radio.Group
              className="ov-radio-dark"
              optionType="button"
              size="middle"
              value={type}
              onChange={(e) => onTypeChange(e.target.value as TypeFilter)}
              options={[
                { label: '全部', value: '' },
                { label: '进行中', value: 'active' },
                { label: '已完成', value: 'completed' },
              ]}
            />
          </Space>
          {/* add-spec-archive：归档状态切换（未归档默认 / 已归档），与类型过滤同层客户端过滤；靠右显示。
              两过滤组激活态黑底白字走 .ov-radio-dark 覆写类（2026-11-06 用户指令
              「参考 overview 的 radio 控件样式」，DESIGN.md 一般域条款单源） */}
          <Radio.Group
            className="ov-radio-dark"
            style={{ marginLeft: 'auto' }}
            optionType="button"
            size="middle"
            value={archivedOnly}
            onChange={(e) => onArchivedOnlyChange(Boolean(e.target.value))}
            options={[
              { label: '未归档', value: false },
              { label: '已归档', value: true },
            ]}
          />
        </div>
        {/* add-spec-list-mobile-style 任务 2.5：桌面分支零改动——原 isMobile
            三元摘除（移动卡迁至 Card 外移动编排块），桌面内容逐字保留。 */}
        {/* Bento 台账磁贴（2026-11-06 用户指令：桌面表格对齐 v2 projects 表格
            边框——白磁贴发丝边 + 透明表头 + 发丝线行分隔 + 首列缩进，样式镜像
            在 global.less .ov-bento / .ov-bento-table）。antd Table 控件与其
            功能（表头排序/分页/树形展开/信息子行）原样保留，不替换为 v2 自绘表。 */}
        <div className="ov-bento">
            <div className="ov-bento-table">
          <Table
            rowKey="name"
            tableLayout="fixed"
            // 未完成（非 done/pushed 终态）行加浅底：内联样式落在 tr 上，
            // antd 的 cell 级 hover 背景（cell-row-hover）不受影响照常生效。
            // 底色走 DSH_INTERACTIVE_ACTIVE（宿主对齐改造 2026-11-03，替代原
            // colorPrimaryBg——615f6f350d58 时的主色是蓝 #1677ff，Bg 派生浅蓝；
            // 主色改黑系 #0f1115 后 antd 调色板对暗种子生成暗色 ramp，整行近黑，
            // 改取 dsh 侧栏选中行的冷灰交互底 #2631481a（theme.ts 单源）；
            // 2026-11-04 用户裁决改蓝调 rgb(99 136 211 / 10%)，值随单源更新）
            onRow={(record) => ({
              // add-spec-subtitle-and-row-click（task 2.1）：整行点击进详情
              // （镜像 overview 台账 onRow 范式：整行 cursor pointer + 路由跳
              // 转；SPEC 列表无 error 抑制语义，行恒可点）。事件目标守卫
              // （design D3，单源 specRowClick.ts）：展开钮（fix-* 树展开与
              // error 信息行展开共用 antd 展开图标类）命中不导航；操作列交互
              // 单元格既有 stopPropagation 单元格守卫零改动命中；展开行内容
              // 渲染于行外 ant-table-expanded-row，不在 onRow 命中面；名称
              // 链接自有跳转与本行导航同目标不额外拦截（连跳同路由无害）。
              onClick: (e) => {
                if (rowClickHitsExpandIcon(e)) return;
                history.push(specDetailPath(project, record.name));
              },
              style: {
                cursor: 'pointer',
                ...(PRIORITY_TERMINAL.has(record.status || '')
                  ? {}
                  : { backgroundColor: DSH_INTERACTIVE_ACTIVE }),
              },
            })}
            columns={columns}
            dataSource={tree}
            loading={loading}
            pagination={{ pageSize: 20, showSizeChanger: true, showTotal: (t) => `共 ${t} 条` }}
            expandable={{
              columnWidth: 28,
              expandedRowKeys: expandedKeys,
              onExpandedRowsChange: onExpandedKeysChange,
              // 额外信息（error）行内下方展开，含清除按钮（对齐 v1 spec-info-row）
              expandedRowRender: (record: SpecSummary) =>
                record.error ? (
                  <div style={{ display: 'flex', alignItems: 'flex-start', gap: 8 }}>
                    <Tag color="orange" style={{ marginInlineEnd: 0 }}>
                      信息
                    </Tag>
                    <Typography.Text style={{ flex: 1 }}>{record.error}</Typography.Text>
                    <Button size="small" onClick={() => void onClearError(record)}>
                      清除
                    </Button>
                  </div>
                ) : null,
              rowExpandable: (record: SpecSummary) => !!record.error,
            }}
          />
            </div>
          </div>
      </Card>
        </>
      )}
    </>
  );
}

export default function SpecListPage() {
  const { name = '' } = useParams<{ name: string }>();
  const isMobile = useIsMobile();
  // 行底色/状态点/验证中文案色的 token 消费随「功能开发」分面视图下沉
  // DevTab（code-review item 99be1f625d52），主组件不再直接读 token
  const { message, modal } = App.useApp();
  // add-spec-list-filter-stickiness：过滤状态持久化到 URL 查询参数（replace 写回）
  const [searchParams, setSearchParams] = useSearchParams();
  // 读侧（D1）：挂载时惰性初始化一次性解析 URL（useState 惰性函数只在首渲染
  // 执行），后续渲染不再读 URL 覆盖用户操作；此后 UI 由 state 驱动、变更写回
  const [initialFilters] = useState(() => parseListFilters(searchParams));
  // dashboard-sse-refresh D3：本地 spec 摘要表（Map<spec_name, summary>），
  // 首屏 /api/specs 全量建立，此后 SSE 增量事件 patch 单行（含新增/删除）。
  const [specMap, setSpecMap] = useState<Record<string, SpecSummary>>({});
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(true);
  // 读侧恢复（1.2）：URL q 同时灌入输入框回显（q）与生效过滤值（debouncedQ），
  // 不出现「先闪全量列表、300ms 后才过滤」的中间态
  const [q, setQ] = useState(initialFilters.q);
  // 搜索/筛选输入防抖 ≥300ms（3.4），本地表过滤；本地空才回退后端
  const [debouncedQ, setDebouncedQ] = useState(initialFilters.q);
  const [statusList, setStatusList] = useState<string[]>(initialFilters.statusList);
  const [type, setType] = useState<TypeFilter>(initialFilters.type);
  // add-spec-archive：归档状态过滤（false=未归档默认，true=已归档）
  const [archivedOnly, setArchivedOnly] = useState(initialFilters.archivedOnly);
  const lastRefreshRef = useRef(0);

  // 增量 patch 队列：同 spec 1s 内多事件只应用最新（3.1 去重合并）。
  const pendingPatchesRef = useRef<Record<string, { summary: SpecSummary | null; seq: number }>>({});
  const patchTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  // 整表 load 与 SSE patch 的时序守卫（code-review item 5509401e08f0）：load 响应
  // 是请求时刻的服务端快照，若请求在飞期间有 patch 被 flush 应用，晚到的旧快照
  // 会把较新的增量行覆盖回旧值（loadSeqRef 只排多次 load 之间、不感知 patch）。
  // 每条 patch 入队时领单调序号，flush 时把已应用条目按序号记入日志；load 响应
  // 落地时把序号晚于本次请求的日志条目重新合并进快照再写表，增量不再被回退。
  // 日志在每次 load 发起时按本次请求序号裁剪，规模以两次 load 间的事件数为上界。
  const patchSeqRef = useRef(0);
  const patchLogRef = useRef<Array<{ seq: number; spec: string; summary: SpecSummary | null }>>([]);
  const specMapRef = useRef(specMap);
  // 「已成功加载」闩锁（code-review item f8144e4ed721）：区分「首屏未载入/加载
  // 失败」与「已成功加载但为空」两种空表情形，零 SPEC 项目成功加载后不再随搜索
  // 防抖节拍反复回退重拉 /api/specs。
  const specLoadedRef = useRef(false);
  // 渲染期副作用消除（code-review item b81c73214b46）：原在渲染体直接写
  // specMapRef.current = specMap，属 render side effect（并发渲染/StrictMode
  // 下可能 ref 与本次渲染不一致）；改在 effect 中同步。
  useEffect(() => {
    specMapRef.current = specMap;
  }, [specMap]);

  // 文档弹窗（对齐 v1 docmodal：背景/设计/任务清单 三页签）
  const [docView, setDocView] = useState<string | null>(null);

  // 调整优先级弹窗
  const [priorityEdit, setPriorityEdit] = useState<{ spec: string; value: number } | null>(null);

  // 呼叫 Admin 介入弹窗
  const [adminInvoke, setAdminInvoke] = useState<{ spec: string } | null>(null);

  // add-spec-scheduling-controls：设置拾取时间弹窗（非终态 spec）
  const [startAfterEdit, setStartAfterEdit] = useState<{ spec: string; manual?: boolean } | null>(null);
  const [saDate, setSaDate] = useState<dayjs.Dayjs | null>(null);
  // add-spec-status-modal-budget：修改状态弹窗（归档/冻结/晋升/预算 四区块收敛入口）
  const [statusModal, setStatusModal] = useState<{ spec: string } | null>(null);

  // add-project-detail-tabs D1：项目页分面选中态（功能开发/代码审查/测试回归/
  // 架构蓝图/项目知识）；add-spec-list-filter-stickiness 改写：选中态持久化到
  // URL `tab` 参数（合法值见 listFilters.ts LIST_TABS，缺省 dev 且缺省不写参），
  // 读侧恢复复用既有 active 门控
  const [activeTab, setActiveTab] = useState<ListTab>(initialFilters.tab);

  // 加载币值守卫（code-review item 95bc1b23a7b7）：本路由组件在 /projects/:name
  // 下复用不重挂载，name 变化会重建 load 重新拉取，但旧项目在飞请求不会被丢弃；
  // 30s 心跳 + visibilitychange + run_meta + SSE 多路触发也让同项目内存在重叠
  // load。每次调用递增序号作为币值，响应落地前比对仍是最新一次才写 specMap/
  // error，较慢的旧响应（旧项目的整表数据/错误）不再覆盖新数据（对照
  // settings/index.tsx 同款问题的 cancelled 守卫，code-review item 56756944dd6e）。
  const loadSeqRef = useRef(0);
  const load = useCallback(async () => {
    if (!name) return;
    const seq = ++loadSeqRef.current;
    // 本次请求发出前已入队的 patch 不参与合并（快照必然不旧于它们）；只合并
    // 请求在飞期间入队（seq 更大）的 patch，同时据此裁剪日志
    const atPatchSeq = patchSeqRef.current;
    patchLogRef.current = patchLogRef.current.filter((e) => e.seq > atPatchSeq);
    try {
      const d = await getSpecs(name);
      if (loadSeqRef.current !== seq) return;
      if (d.error) {
        setError(d.error);
      } else {
        const next: Record<string, SpecSummary> = {};
        for (const s of d.specs || []) next[s.name] = s;
        // 快照落地前重放「请求在飞期间应用」的 patch（code-review item
        // 5509401e08f0）：旧快照不再把较新增量行覆盖回旧值或抹掉新增行。
        // 仍在挂起未 flush 的 patch 无需在此处理——其定时器到点后自会叠加在本表之上。
        for (const e of patchLogRef.current) {
          if (e.summary === null) delete next[e.spec];
          else next[e.spec] = e.summary;
        }
        setSpecMap(next);
        setError('');
        // 成功加载（含空表）即闩锁，后续防抖回退不再触发（code-review item f8144e4ed721）
        specLoadedRef.current = true;
      }
    } catch (e) {
      if (loadSeqRef.current !== seq) return;
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      // loading 只由最新一次请求收口，过期响应不抢（新请求自己会复位）
      if (loadSeqRef.current === seq) setLoading(false);
    }
  }, [name]);

  // 刷新挂起的增量 patch（1s 去重窗口到期后统一应用）
  const flushPatches = useCallback(() => {
    patchTimerRef.current = null;
    const patches = pendingPatchesRef.current;
    pendingPatchesRef.current = {};
    // 已应用的 patch 记入日志供在飞 load 响应合并（见 patchLogRef 注释）。
    // flush 定时器互斥且每批收尽此前入队事件，故日志追加序与 seq 单调序一致，
    // 响应侧按序覆盖即得同 spec 最新值。
    for (const [spec, p] of Object.entries(patches)) {
      patchLogRef.current.push({ seq: p.seq, spec, summary: p.summary });
    }
    setSpecMap((prev) => {
      const next = { ...prev };
      let changed = false;
      for (const [spec, p] of Object.entries(patches)) {
        if (p.summary === null) {
          // 删除标记：summary:null → 从本地表移除该行
          if (spec in next) {
            delete next[spec];
            changed = true;
          }
        } else if (next[spec] !== p.summary) {
          next[spec] = p.summary;
          changed = true;
        }
      }
      return changed ? next : prev;
    });
  }, []);

  // 入队一条增量 patch；同 spec 在 1s 窗口内只保留最新值（并领单调序号，
  // 供 load 响应区分「请求发出前/后」的 patch）
  const enqueuePatch = useCallback((spec: string, summary: SpecSummary | null) => {
    pendingPatchesRef.current[spec] = { summary, seq: ++patchSeqRef.current };
    // 显式 null/undefined 判等（code-review item 95013c6683be，宽松相等被 lint 禁止）
    if (patchTimerRef.current === null || patchTimerRef.current === undefined) {
      patchTimerRef.current = setTimeout(flushPatches, PATCH_COALESCE_MS);
    }
  }, [flushPatches]);

  // SSE 增量驱动：state 事件入 patch 队列；run_meta 节流兜底重拉；refresh 不
  // 处理（由 30s 心跳兜底）
  useEffect(() => {
    void load();
    const es = new EventSource(STREAM_URL);
    es.onmessage = (ev: MessageEvent) => {
      let msg: {
        type?: string;
        project?: string;
        specs?: Array<{ spec?: string; summary?: SpecSummary | null }>;
      } = {};
      try {
        msg = JSON.parse(ev.data);
      } catch {
        return;
      }
      if (msg.type === 'state' && msg.project === name) {
        // 增量形态：specs 为 [{spec, summary|null}]，逐条入 patch 队列
        const items = msg.specs || [];
        for (const item of items) {
          if (item && typeof item.spec === 'string') {
            // 区分「summary 显式为 null（契约上的删除标记）」与「字段缺失」
            // （code-review item 318a841d2c70）：旧写法 `item.summary ?? null`
            // 把二者并入同一语义，后端某次事件因序列化/字段裁剪缺失 summary 时
            // 会把该行误删（列表行流式消失）。缺字段 → 跳过该条，不动本地表。
            if ('summary' in item) {
              enqueuePatch(item.spec, item.summary ?? null);
            }
          }
        }
        return;
      }
      if (msg.type === 'run_meta' && msg.project === name) {
        // run_meta（低频：仅状态转换）不携带摘要增量，节流兜底重拉校准
        // （实时任务进度/耗时字段随之刷新；refresh 为 watcher 2s 心跳，不触发
        // 全量重拉——降为 30s 兜底心跳，见下）。只响应本项目：多项目宿主上
        // 其他项目的 run 转换不再触发本页全量重拉（code-review item
        // decdb246e859，对齐 detail.tsx 同款过滤 item 844dd6f5108b）。
        const now = Date.now();
        if (now - lastRefreshRef.current < REFRESH_THROTTLE_MS) return;
        lastRefreshRef.current = now;
        void load();
      }
    };
    return () => {
      es.close();
      // 清理时 MUST 把 ref 置回 null 并清空待处理队列（code-review item
      // cf865713d17b）：旧实现只 clearTimeout 不置 null，而 enqueuePatch 仅在
      // `patchTimerRef.current === null || === undefined` 时创建新定时器——该 effect 一旦因路由
      // 切换（name 变化 → load 变化）重建，ref 便永久留着一个已清除的非 null id，
      // 此后所有 SSE 增量 patch 都不再被调度刷新（pendingPatchesRef 无限累积、
      // 界面停止增量更新）。同时陈旧队列若不清空，会在后续 flush 时被应用到
      // 新项目的 specMap，造成跨项目行污染。
      if (patchTimerRef.current) clearTimeout(patchTimerRef.current);
      patchTimerRef.current = null;
      pendingPatchesRef.current = {};
    };
  }, [load, name, enqueuePatch]);

  // 30s 兜底心跳 + visibilitychange 立即校准（3.3）：SSE 断线 / 丢帧时列表仍刷新
  useEffect(() => {
    const hb = setInterval(() => void load(), HEARTBEAT_MS);
    const onVisible = () => {
      if (document.visibilityState === 'visible') void load();
    };
    document.addEventListener('visibilitychange', onVisible);
    return () => {
      clearInterval(hb);
      document.removeEventListener('visibilitychange', onVisible);
    };
  }, [load]);

  // 搜索/筛选输入防抖：≥300ms 后在本地表内过滤；本地表为空时才回退后端请求
  useEffect(() => {
    const t = setTimeout(() => {
      setDebouncedQ(q);
      // 本地表空且尚未成功加载（首屏未载入/加载失败）→ 回退请求 /api/specs；
      // 已成功加载但为空（零 SPEC 项目）不再重拉（code-review item f8144e4ed721）
      if (q.trim() && !specLoadedRef.current && Object.keys(specMapRef.current).length === 0) {
        void load();
      }
    }, SEARCH_DEBOUNCE_MS);
    return () => clearTimeout(t);
  }, [q, load]);

  // add-spec-list-filter-stickiness（2.1/2.2）：写侧——过滤状态任一变化时以
  // replace 语义写回 URL（不新增历史条目、路由路径 /projects/:name 不变、
  // 不触发重挂载）。缺省值不写参（tab=dev / q 空 / statusList 空 / type 空 /
  // 未归档均移除对应参数），默认视图下 URL 恢复无参干净形态；挂载后首跑即把
  // 脏参数清洗为干净形态（D3 解析即消毒）。q 只跟随 debouncedQ 节拍落 URL
  // （D4），输入框逐字符不写；setSearchParams 为稳定引用，不入 deps。
  useEffect(() => {
    const next = new URLSearchParams();
    if (activeTab !== 'dev') next.set('tab', activeTab);
    if (debouncedQ.trim()) next.set('q', debouncedQ.trim());
    if (statusList.length > 0) next.set('status', statusList.join(','));
    if (type) next.set('type', type);
    if (archivedOnly) next.set('archived', '1');
    setSearchParams(next, { replace: true });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [debouncedQ, statusList, type, archivedOnly, activeTab]);

  const filtered = useMemo(() => {
    const kw = debouncedQ.trim().toLowerCase();
    // 本地表渲染：与 /api/specs 全量口径一致按 created 倒序（新增 spec 插序）
    return Object.values(specMap)
      .filter((s) => {
        // add-spec-chinese-title：名称关键字在英文名包含匹配外 OR 命中中文
        // 标题（大小写不敏感，任一命中即保留；id/name 关系下标题参与匹配
        // 的唯一例外，匹配语义单源 specTitle.specKeywordHit）
        if (kw && !specKeywordHit(s.name, s.title, kw)) return false;
        if (statusList.length && !statusList.includes(s.status || '')) return false;
        // 进度过滤：口径与行高亮一致，PRIORITY_TERMINAL（done/pushed）为已完成，其余为进行中
        if (type === 'active' && PRIORITY_TERMINAL.has(s.status || '')) return false;
        if (type === 'completed' && !PRIORITY_TERMINAL.has(s.status || '')) return false;
        // add-spec-archive：默认展示未归档（archivedOnly=false），切换后仅展示已归档
        if (!!s.archived !== archivedOnly) return false;
        return true;
      })
      .sort((a, b) => (b.created || '').localeCompare(a.created || ''));
  }, [specMap, debouncedQ, statusList, type, archivedOnly]);

  const tree = useMemo(() => buildTree(filtered), [filtered]);

  // 移动端状态 chips 计数（add-spec-list-mobile-style 2.1）：kw + 类型 + 归档
  // 过滤后、状态过滤前的子集——chip 计数含义为「当前其余条件下该状态还剩几条」
  // （原型 chips 同语义，点选某状态后其余 chip 计数不归零）；桌面分支零消费
  const preStatus = useMemo(() => {
    const kw = debouncedQ.trim().toLowerCase();
    return Object.values(specMap).filter((s) => {
      if (kw && !specKeywordHit(s.name, s.title, kw)) return false;
      if (type === 'active' && PRIORITY_TERMINAL.has(s.status || '')) return false;
      if (type === 'completed' && !PRIORITY_TERMINAL.has(s.status || '')) return false;
      if (!!s.archived !== archivedOnly) return false;
      return true;
    });
  }, [specMap, debouncedQ, type, archivedOnly]);
  const statusCounts = useMemo(() => {
    const c: Record<string, number> = {};
    for (const s of preStatus) c[s.status || ''] = (c[s.status || ''] || 0) + 1;
    return c;
  }, [preStatus]);

  // 受控展开：数据到达时默认全部展开（树形子级 + error 信息行可见），用户可手动收起
  const [expandedKeys, setExpandedKeys] = useState<readonly Key[]>([]);
  // 仅在**首次**数据到达时初始化展开状态（code-review item b229013a3316）：`tree`
  // 由 filtered→specMap 派生，任何 SSE 增量 patch / 30s 心跳重拉都会产生新引用，
  // 旧实现 `[tree]` 依赖会在流式更新期间反复把用户手工收起的树弹开，且与受控
  // 展开 onExpandedRowsChange 互相打架。用 ref 标记首次初始化。
  const expandedInitRef = useRef(false);
  // 已见节点记忆（code-review item 81b677017e09）：error 信息行走
  // expandedRowRender，可见性受 expandedKeys 控制。闩锁置位后 SSE patch 新增的
  // spec（新建任务/修复子任务）也要默认展开，但不能把用户已手动收起的行强制
  // 弹开——区分「新增节点」与「被用户收起的已见行」需要记忆已纳入展开集合的
  // 节点名，增量合并只并入从未见过的 keys。
  const seenKeysRef = useRef<Set<Key>>(new Set());
  // 项目切换复位闩锁（code-review item 9dd9b3c6679b）：本路由组件在同一路径
  // /projects/:name 下复用不重挂载，expandedInitRef 是锚定不到项目的一次性
  // 闩锁——name 变化时不复位则新项目树保持折叠、expandedKeys 残留上一项目的
  // spec 名。复位后由下方 init effect 在新项目 tree 首次到达时重新展开。
  useEffect(() => {
    expandedInitRef.current = false;
    // 已见节点记忆随项目复位：残留上一项目的 spec 名会把新项目同名 spec
    // 误判为「已见」而拒绝展开（code-review item 81b677017e09）。
    seenKeysRef.current.clear();
    setExpandedKeys([]);
    // specLoadedRef 闩锁随项目复位（code-review item f8144e4ed721）
    specLoadedRef.current = false;
    // 跨项目数据残留（code-review item 3d02af5ed12e）：specMap 持有上一项目的
    // 整表数据，load 的失败分支（d.error/catch）只 setError 不清表，币值守卫
    // 也只拦旧响应落地、不主动清旧数据——不复位则新项目加载返回前（或加载
    // 失败时）表格、「共 N 个 SPEC」计数与移动端卡片一直显示上一项目的 SPEC。
    // 函数式守卫避免首挂载空表时的无谓 re-render（同 flushPatches 惯例）。
    setSpecMap((prev) => (Object.keys(prev).length > 0 ? {} : prev));
    // 上一项目的加载失败提示不残留到新项目（code-review item 8685bdb6a737）：
    // load 的失败分支只 setError 不清，切换后 A 的错误 Alert 会一直显示到
    // 新项目响应落地。
    setError('');
    // 切换间隙呈现加载态而非空表（code-review item 3c3752ef9d70）：load 不设
    // setLoading(true)（初始态与完成收口各一次），specMap 清空后到新项目响应
    // 落地前表格/移动端卡片/「共 N 个 SPEC」会以无 Spin 空态呈现，被误读为
    // 新项目没有 SPEC。置 true 由 load 的 finally 收口（币值守卫保证只归最新请求）。
    setLoading(true);
    // 各弹窗状态随项目切换一并复位（code-review item f1753df2b38b）：本路由组件
    // 在 /projects/:name 下复用不重挂载，弹窗状态不复位则切换到新项目后残留的
    // open 弹窗（statusModal 等）因数据为 null 暂时不可见，一旦新项目存在同名
    // spec（或用户再导航回原项目）就会未经用户操作自动重现。
    setStatusModal(null);
    setDocView(null);
    setPriorityEdit(null);
    setStartAfterEdit(null);
    setAdminInvoke(null);
  }, [name]);
  useEffect(() => {
    if (tree.length === 0) return;
    // 树归属门控（code-review item e6881ebd1b26）：name 变更的复位 effect 与
    // SSE flush 的 setSpecMap 同批提交时，本 effect 会以旧项目的 tree 执行——
    // 闩锁刚被复位又被置回、旧 keys 记入已见，新项目同名 spec 被判「已见」
    // 不再默认展开、error 信息行保持折叠。specLoadedRef 只在当前项目 load
    // 成功落地时置位、随复位清 false：false 即 tree 快照不属于当前 name，
    // 跳过本次展开处理，等新项目数据落地后正常初始化
    if (!specLoadedRef.current) return;
    // 递归收集全树所有节点名（code-review item 6869f19d419c）：三层归并树
    // （fix-fix-a→fix-a→a）只收根名会漏掉中间层，其子级默认折叠隐藏；叶子名
    // 也要收——error 信息行走 expandedRowRender，同受这组 keys 控制。
    const keys: Key[] = [];
    const walk = (nodes: SpecSummaryNode[]) => {
      nodes.forEach((n) => {
        keys.push(n.name);
        if (n.children) walk(n.children);
      });
    };
    walk(tree);
    if (!expandedInitRef.current) {
      // 首棵树到达：全展开（既有行为，b229013a3316 闩锁语义不变）
      expandedInitRef.current = true;
      keys.forEach((k) => seenKeysRef.current.add(k));
      setExpandedKeys(keys);
      return;
    }
    // 闩锁置位后的增量合并（code-review item 81b677017e09）：SSE patch 新增的
    // spec 原实现进不了 expandedKeys，其 error 信息行保持折叠不可见。只把从未
    // 见过的节点 keys 并入展开集合——新增行默认展开；用户已手动收起的行是
    // 「已见」节点、不在 fresh 内，不被强制重开（b229013a3316 语义保持）。
    const fresh = keys.filter((k) => !seenKeysRef.current.has(k));
    if (fresh.length === 0) return;
    keys.forEach((k) => seenKeysRef.current.add(k));
    setExpandedKeys((prev) => {
      const merged = new Set(prev);
      for (const k of fresh) merged.add(k);
      // 返回原引用避免无谓 re-render（同 flushPatches 惯例）
      return merged.size === prev.length ? prev : [...merged];
    });
  }, [tree]);

  const handleClearError = async (record: SpecSummary) => {
    try {
      await clearSpecError(name, record.name);
      void load();
    } catch (err) {
      // 面向用户的错误提示（code-review item 61a4afa41eab）：旧实现仅
      // console.error，用户误以为操作已生效。
      message.error(`清除错误失败：${err instanceof Error ? err.message : String(err)}`);
    }
  };

  const handleDeleteSpec = (record: SpecSummary) => {
    modal.confirm({
      title: '删除 SPEC',
      content: (
        <div style={{ whiteSpace: 'pre-wrap' }}>
          {`确认删除 SPEC「${record.name}」？\n\n`}
          软删除：STATE.md 移除该条目，spec/changes/{record.name}/ 目录移入 archive 归档。
          {'\n'}归档路径：spec/archive/{record.name}-&lt;时间戳&gt;/
          {/* add-freeze-stop-inflight-agents 6.4：说明先停后删语义（纯文案） */}
          {'\n'}若有在跑的 agent 会先停止并留存进度。
        </div>
      ),
      okText: '删除',
      okButtonProps: { danger: true },
      cancelText: '取消',
      onOk: async () => {
        // try/catch（code-review item 61a4afa41eab）：旧实现无捕获，deleteSpec
        // 失败会产生未处理 Promise 拒绝且弹窗无提示。
        try {
          // add-freeze-stop-inflight-agents 6.2：受理结果处理——该 spec 有在跑
          // agent 时后端异步受理（202 + accepted=true + stopping=N），前端提示
          // 「已受理，正在停止 N 个进行中的 agent」并保持 load() 轮询（spec 行
          // 在停止+删除完成后自然消失）；无在跑 agent 时走既有同步删除路径。
          const result = await deleteSpec(name, record.name);
          if (result?.accepted && result.stopping) {
            message.info(
              `已受理，正在停止 ${result.stopping} 个进行中的 agent`,
            );
          } else {
            // 同步删除成功（无在跑 agent，200 {ok: true}）——显式成功反馈
            message.success(`SPEC「${record.name}」已删除`);
          }
          void load();
        } catch (err) {
          message.error(`删除 SPEC 失败：${err instanceof Error ? err.message : String(err)}`);
        }
      },
    });
  };

  const handleReReview = (record: SpecSummary) => {
    // add-spec-review-gate D8：重新评审入口——仅 error 前缀命中
    // SPEC_REVIEW_BLOCKED_PREFIXES（与后端 re_review 白名单同源）的
    // blocked SPEC 显示本入口；后端仍会复核开放条件（非 blocked/冻结/
    // 前缀不符任一拒绝），失败时展示后端返回的拒绝原因。
    modal.confirm({
      title: '重新评审 SPEC',
      content: (
        <div style={{ whiteSpace: 'pre-wrap' }}>
          {`确认重新评审 SPEC「${record.name}」？\n\n`}
          将把 SPEC 从 blocked 移回 reviewing，并由评审 Agent 重新执行方案评审。
          {'\n'}（仅评审相关 blocked 可重新评审；冻结 SPEC 与担责放行请走「修改状态」）
        </div>
      ),
      okText: '重新评审',
      cancelText: '取消',
      onOk: async () => {
        try {
          await reReviewSpec(name, record.name);
          message.success(`SPEC「${record.name}」已重新进入评审`);
          void load();
        } catch (err) {
          // 后端拒绝（非 blocked / 冻结 / 前缀不符等）→ 展示明确拒绝原因
          message.error(`重新评审失败：${err instanceof Error ? err.message : String(err)}`);
        }
      },
    });
  };

  const handlePriorityOk = async () => {
    if (!priorityEdit) return;
    try {
      await setSpecPriority(name, priorityEdit.spec, priorityEdit.value);
      setPriorityEdit(null);
      void load();
    } catch (err) {
      // 面向用户的错误提示（code-review item 61a4afa41eab）
      message.error(`调整优先级失败：${err instanceof Error ? err.message : String(err)}`);
    }
  };

  const handleAdminInvoke = (record: SpecSummary) => {
    setAdminInvoke({ spec: record.name });
  };

  // ── 设置拾取时间（add-spec-scheduling-controls D6 / add-spec-manual-activation 7.6）──
  const openStartAfterModal = (record: SpecSummary) => {
    // 哨兵 manual 时 MUST NOT 走 dayjs()——dayjs('manual') 为 Invalid Date，
    // DatePicker 显示异常，且 toISOString() 会抛 RangeError。降级为「预填 null +
    // 提示当前为待激活态，请用『修改状态』弹窗的『激活』按钮或重新选择时间」。
    if (record.start_after === 'manual') {
      setSaDate(null);
      message.info('该 SPEC 当前为待激活态（start_after: manual）——请用「修改状态」弹窗的「激活」按钮，或在此重新选择时间');
      // manual 标记：未选时间直接「确定」须被拦截，MUST NOT 静默把哨兵清成
      // null（code-review item 3371bb27c96a）
      setStartAfterEdit({ spec: record.name, manual: true });
      return;
    }
    // 预填既有定时（ISO → 本地时区展示）；无定时则为 null（清除路径）
    setSaDate(record.start_after ? dayjs(record.start_after) : null);
    setStartAfterEdit({ spec: record.name });
  };

  const handleStartAfterOk = async () => {
    if (!startAfterEdit) return;
    try {
      // manual 哨兵态未选时间直接确定会以 null 提交，静默清除哨兵并立即恢复
      // 被 daemon 拾取（code-review item 3371bb27c96a）——提交侧拦截，退出
      // 待激活态只能走「修改状态」弹窗的「激活」或在此重新选择时间
      if (startAfterEdit.manual && !saDate) {
        message.error('待激活 SPEC 须先选择拾取时间；退出待激活态请用「修改状态」弹窗的「激活」按钮');
        return;
      }
      // DatePicker 输入为本地时区；dayjs.toISOString() 输出 UTC ISO8601（Z 后缀）
      // 哨兵安全降级：非法/不存在日期 MUST NOT 静默把哨兵清成 null，拒绝提交并提示
      if (saDate && !saDate.isValid()) {
        message.error('所选时间无效，请重新选择');
        return;
      }
      // 兜底：拾取时间只能是未来（过去时刻不可拾取）。禁选已挡住日历入口，
      // 但仍可经键盘输入或弹窗跨分钟滞留绕过，故提交侧再校验一次。
      if (saDate && !saDate.isAfter(dayjs())) {
        message.error('拾取时间必须晚于当前时间，请重新选择');
        return;
      }
      const value = saDate ? saDate.toISOString() : null;
      const result = await setSpecStartAfter(name, startAfterEdit.spec, value);
      // fix-scheduling-kick-single-slot D3：清空定时成功但即时唤醒信号写出失败时
      // 如实告知（MUST NOT 无条件宣称「立即恢复调度」）
      // [fenix-ignore:df8a6acd2788] 路由层已把 scheduling_kick 失败折算为响应体 warning（spec_routes.py _api_spec_start_after，契约测试 test_clear_start_after_write_failure_warning 锁定），前端读 result.warning 正确
      if (!saDate && result.warning) {
        message.warning(result.warning);
      } else {
        message.success(saDate ? '已设置定时拾取时间' : '已清除定时，立即恢复调度');
      }
      setStartAfterEdit(null);
      void load();
    } catch (err) {
      message.error(`设置失败：${err instanceof Error ? err.message : String(err)}`);
    }
  };

  const specMenuItems = (record: SpecSummary) => {
    const terminal = PRIORITY_TERMINAL.has(record.status || '');
    // add-spec-archive：已归档视图操作收敛——隐藏调度类操作（优先级/冻结/归档），
    // 仅保留查看类（删除保留与否依实现；归档 SPEC 不可再调度，全部调度项移除）
    if (archivedOnly) {
      return [
        { type: 'divider' as const },
        { key: 'delete', label: '删除 SPEC', danger: true },
      ];
    }
    // add-spec-status-modal-budget D2：菜单收敛——状态类操作（晋升/冻结/解冻/
    // 冻结管理/归档）全部并入「修改状态」弹窗，保留 admin/priority/pickup-time/delete。
    // 终态置灰仅作用于 priority/pickup-time（现状语义）；「修改状态」终态仍可点
    // （归档区块可用）。
    // add-spec-scheduling-controls：非终态 spec 可设置定时拾取（start_after）
    // add-spec-review-gate D8（code-review item 1b64add9823d）：评审相关
    // blocked（error 前缀命中 SPEC_REVIEW_BLOCKED_PREFIXES，与后端
    // re_review 白名单同源）判据收敛单点，消除双前缀重复子句
    const reviewBlocked =
      record.status === 'blocked' &&
      SPEC_REVIEW_BLOCKED_PREFIXES.some((p) => (record.error || '').startsWith(p));
    return [
      { key: 'status', label: '修改状态' },
      // add-spec-review-gate D8：评审相关 blocked 增「重新评审」入口
      //（非评审类 blocked 不显示）
      ...(reviewBlocked ? [{ key: 're-review', label: '重新评审' }] : []),
      { key: 'admin', label: '呼叫 Admin 介入' },
      { key: 'priority', label: '调整优先级', disabled: terminal },
      // add-spec-scheduling-controls：非终态 spec 可设置定时拾取（start_after）
      { key: 'pickup-time', label: '设置拾取时间', disabled: terminal },
      { type: 'divider' as const },
      { key: 'delete', label: '删除 SPEC', danger: true },
    ];
  };

  const onSpecMenu = (record: SpecSummary, key: string) => {
    if (key === 'status') {
      setStatusModal({ spec: record.name });
    } else if (key === 'admin') {
      void handleAdminInvoke(record);
    } else if (key === 'priority') {
      setPriorityEdit({ spec: record.name, value: record.priority ?? 5 });
    } else if (key === 'pickup-time') {
      openStartAfterModal(record);
    } else if (key === 'delete') {
      handleDeleteSpec(record);
    } else if (key === 're-review') {
      handleReReview(record);
    }
  };

  // 四分面移动边距 16px（2026-11-07 用户指令「代码审查、测试回归、架构蓝图、
  // 项目知识的左右边距也设置为 16px」）：页签卡 body 缺省 24 + 容器 12 = 每侧
  // 36，四分面经负 margin 抵消卡体 20（容器 12 + 余 4 = 每侧 16）。功能开发
  // （DevTab 自带 -12 全幅编排，抵的是容器 12）不在此列、零改动；
  // 桌面不包裹零影响
  const facetWrap = (node: ReactNode) =>
    isMobile ? <div style={{ margin: '0 -20px' }}>{node}</div> : node;

  return (
    <>
      {/* 统一标题栏声明（unified-page-title-bar 2.3）：返回箭头 + 「{项目名} +
          共 N 个 SPEC」随标题迁入控件（原型中 fenixd 为示例项目名的具象值，
          此处渲染当前路由项目名）；onBack 行为不变 */}
      <PageTitleBar
        back={() => history.push('/overview')}
        title={
          <Space size={8} align="baseline" style={{ minWidth: 0 }}>
            <span>{name}</span>
            <Typography.Text type="secondary" style={{ fontSize: 14, fontWeight: 400 }}>
              共 <TitleBarNum>{Object.keys(specMap).length}</TitleBarNum> 个 SPEC
            </Typography.Text>
          </Space>
        }
      />
      <PageContainer title={false} breadcrumbRender={false} pageHeaderRender={false}>
      {/* add-project-detail-tabs D1：项目页分面 Tabs——「功能开发」（默认）/
          「代码审查」/「测试回归」/「架构蓝图」/「项目知识」；add-spec-list-filter-stickiness：
          选中态持久化到 URL `tab`（replace 写回、缺省不写参） */}
      <Tabs
        activeKey={activeTab}
        onChange={setActiveTab}
        items={[
          {
            key: 'dev',
            label: '功能开发',
            children: (
              // 「功能开发」分面视图抽为 DevTab（code-review item 99be1f625d52）：
              // 过滤条/表格/移动卡片编排与列定义随子件下沉，主组件只保留数据流
              // 与动作 handler，经 props 下行
              <DevTab
                project={name}
                isMobile={isMobile}
                error={error}
                q={q}
                onQueryChange={setQ}
                statusList={statusList}
                onStatusListChange={setStatusList}
                type={type}
                onTypeChange={setType}
                archivedOnly={archivedOnly}
                onArchivedOnlyChange={setArchivedOnly}
                tree={tree}
                loading={loading}
                expandedKeys={expandedKeys}
                onExpandedKeysChange={setExpandedKeys}
                onDocView={setDocView}
                onEditPriority={(r) => setPriorityEdit({ spec: r.name, value: r.priority ?? 5 })}
                onMenu={onSpecMenu}
                menuItems={specMenuItems}
                onClearError={handleClearError}
                statusCounts={statusCounts}
                statusTotal={preStatus.length}
              />
            ),
          },
          {
            key: 'quality',
            label: '代码审查',
            // add-code-review-agent-and-quality-tab：承载代码审查质量视图——
            // QualityTab active 门控：仅在选中本分面时拉取数据与订阅事件流。
            // 卡片由 QualityTab 自身渲染（与「功能开发」分面同层，避免嵌套 Card 双倍内边距）
            children: facetWrap(<QualityTab project={name} active={activeTab === 'quality'} />),
          },
          {
            key: 'regression',
            label: '测试回归',
            // add-test-regression-tab：承载全量回归结果视图。RegressionTab
            // active 门控：仅在选中本分面时拉取 GET /api/regression/result，
            // 未选中零请求（对齐 QualityTab 按需加载语义）
            children: facetWrap(<RegressionTab project={name} active={activeTab === 'regression'} />),
          },
          {
            key: 'architecture',
            label: '架构蓝图',
            // add-project-architecture-tab：承载 archify 按需生成的项目架构图。
            // ArchitectureTab active 门控：仅在选中本分面时拉取
            // GET /api/architecture/status，未选中零请求（对齐
            // QualityTab/RegressionTab 按需加载语义）；不自动触发生成
            children: facetWrap(<ArchitectureTab project={name} active={activeTab === 'architecture'} />),
          },
          {
            key: 'knowledge',
            label: '项目知识',
            // add-knowledge-atlas 4.2：承载知识真相源只读视图（位于「架构蓝图」
            // 之后）。KnowledgeTab active 门控：仅在选中本分面时
            // 拉取 GET /api/knowledge/index，未选中零请求（对齐按需加载语义）
            children: facetWrap(<KnowledgeTab project={name} active={activeTab === 'knowledge'} />),
          },
        ]}
      />

      <SpecDocModal
        project={name}
        spec={docView}
        open={!!docView}
        onClose={() => setDocView(null)}
      />

      <AdminInvokeModal
        project={name}
        spec={adminInvoke?.spec || ''}
        open={!!adminInvoke}
        onClose={() => setAdminInvoke(null)}
      />

      <Modal
        title="调整优先级"
        open={!!priorityEdit}
        onOk={handlePriorityOk}
        onCancel={() => setPriorityEdit(null)}
        okText="确定"
        cancelText="取消"
      >
        <Space direction="vertical" style={{ width: '100%' }} size={4}>
          <span>
            优先级（P1 最高，P9 最低）：当前 <strong>P{priorityEdit?.value ?? 5}</strong>
          </span>
          <Slider
            min={1}
            max={9}
            step={1}
            value={priorityEdit?.value ?? 5}
            tooltip={{ formatter: (v) => `P${v}` }}
            marks={{ 1: 'P1', 3: 'P3', 5: 'P5', 7: 'P7', 9: 'P9' }}
            onChange={(v) =>
              setPriorityEdit((p) => (p ? { ...p, value: typeof v === 'number' ? v : p.value } : p))
            }
          />
        </Space>
      </Modal>

      {/* add-spec-scheduling-controls：设置拾取时间弹窗（非终态 spec） */}
      <Modal
        title="设置拾取时间"
        open={!!startAfterEdit}
        // manual 哨兵态未选定时间前禁用「确定」，防误点静默清除哨兵（提交侧
        // handleStartAfterOk 另有拦截兜底）
        okButtonProps={{ disabled: !!startAfterEdit?.manual && !saDate }}
        onOk={handleStartAfterOk}
        onCancel={() => setStartAfterEdit(null)}
        okText="确定"
        cancelText="取消"
      >
        <Space direction="vertical" style={{ width: '100%' }} size={12}>
          <Typography.Text type="secondary">
            在此时间点之前，daemon 不会拾取该 SPEC（保持当前状态等待调度）。以本地时区选择，
            提交后转为 UTC 存储；也可清除定时使其立即恢复调度。
          </Typography.Text>
          <DatePicker
            showTime
            style={{ width: '100%' }}
            value={saDate}
            onChange={(d) => setSaDate(d)}
            disabledDate={disablePastDate}
            disabledTime={disablePastTime}
            placeholder="选择拾取时间"
          />
          <Button danger type="link" style={{ paddingInline: 0 }} disabled={!saDate} onClick={() => setSaDate(null)}>
            清除定时（立即恢复调度）
          </Button>
        </Space>
      </Modal>

      {/* add-spec-status-modal-budget D1：修改状态弹窗（归档/冻结/晋升/预算四区块，
          桌面与移动端共用 specMenuItems 的 status 入口） */}
      <SpecStatusModal
        project={name}
        spec={statusModal?.spec || ''}
        open={!!statusModal}
        summary={statusModal ? (specMap[statusModal.spec] ?? null) : null}
        onClose={() => setStatusModal(null)}
        onDone={() => void load()}
      />

    </PageContainer>
    </>
  );
}
