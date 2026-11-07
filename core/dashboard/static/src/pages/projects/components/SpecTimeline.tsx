// SpecTimeline.tsx — SPEC 详情「运行时间轴」渲染（原 detail.tsx 内联 renderTimeline，
// code-review item fa5ce9f79354 抽出：主文件保留数据流与页签编排，state/admin/
// verify/run 四类节点与盒式卡片的渲染编排集中于此）。行为与抽取前严格等价：
// 原组件内闭包依赖（isMobile/name/cancelNotices 与终止 run/最大化运行记录/
// 打开验证报告回调）改为显式 props 注入。
//
// 复用运维记录页的时间轴控件（Timeline + 盒式卡片子项：头部时间+标签行，正文着色边框）。
import { Button, Collapse, Tag, theme, Timeline, Typography } from 'antd';
import { FullscreenOutlined } from '@ant-design/icons';
import { Fragment } from 'react';
import type { CSSProperties, ReactNode } from 'react';
import dayjs from 'dayjs';
import Markdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { statusMeta } from '@/services/dashboard';
import type { SpecDetail } from '@/services/dashboard';
import { ClaudeOutputPane, HarnessBrandProvider } from '@/components/claude-msg';
import { OutlinedTag } from '@/components/StatusTag';
import { SEV_LABEL } from '@/components/alert-shared';
import { fmtDuration } from '@/utils/duration';
// 状态语义色/角色映射共享常量（add-spec-topology-bigscreen 3.1 等价纯迁移）：
// 常量与纯函数单源自 utils/runVisual，渲染输出与迁移前严格等价
// （tests/runVisual.test.mjs 纯函数单测背书）；formatUsd 以 re-export 保持
// detail.tsx 既有 import 路径零改动。
import { agentLabel, arbiterOutcomeLabel, formatUsd, reasonTone, runDotColor } from '@/utils/runVisual';
import { ocrJoinNote } from '../qualityGates';
// 共享 markdownComponents 单源自 components/markdown-shared（code-review item
// af6c616d4e6c）：不再经 ./SpecDocModal re-export 中转，与 SpecDocModal 自身的
// 消费方式对齐
import { markdownComponents } from '@/components/markdown-shared';

type TimelineItem = NonNullable<SpecDetail['timeline']>[number];

// add-model-billing-cost-display（design D5）：金额格式化单源已迁
// utils/runVisual（add-spec-topology-bigscreen 3.1 等价纯迁移）；此处
// re-export 保持 detail.tsx 既有 import 路径（./components/SpecTimeline）零改动。
export { formatUsd };

// 回退原因含「verification report」时渲染为链接（点击打开验证报告弹窗）
const VERIFICATION_LINK_RE = /^(.*?)verification report(.*)$/i;

// ── Bento 色值（2026-11-06 用户指令：时间轴每个节点各自成磁贴，页签区卡
// 同步退出 bento 避免卡套卡；色值取自当日的 v2 域 token 表——该域 2026-11-07
// 已退役，独立存量）。圆角固定 12px 见 DESIGN.md 通用条款。
const OV_TILE_BORDER = '#eef2f7';
const OV_TILE_SHADOW =
  '0 1px 3px rgba(15, 23, 42, 0.05), 0 1px 2px rgba(15, 23, 42, 0.03)';

// remarkPlugins 提为模块级常量（code-review item 0a666cf57a47）：比照 SpecDocModal
// SPEC_DOC_REMARK_PLUGINS / KnowledgeTab KNOWLEDGE_REMARK_PLUGINS 先例复用同一引用，
// 避免每次渲染（SSE 增量刷新、父页状态变化引发的时间轴整体重渲染）新建数组
// 导致 react-markdown 对 run summary 重新 parse
const TIMELINE_REMARK_PLUGINS = [remarkGfm];

// arbiter 处置结论着色（add-arbiter-quality-display 任务 2.3）：自主处置绿
// （框架已收敛）、升级人工橙（待人工接管）；未知 kind 走中性 default Tag。
// 分支选择以 if/else 表达（code-review item 7471b4865219：禁止嵌套三元）。
function arbiterOutcomeTone(kind: string): string {
  if (kind === 'disposition') return 'green';
  if (kind === 'escalation') return 'orange';
  return 'default';
}

// 处置动作/升级理由行的字段标签（escalation 语义为「升级理由」，其余为
// 「处置动作」；同样 if/else 表达）。
function arbiterActionFieldLabel(kind: string): string {
  if (kind === 'escalation') return '升级理由';
  return '处置动作';
}

// 回退节点判定谓词（code-review item 77b2b6634542）：StateNode 的「↩ 状态回退」
// orange 徽标与主渲染 timeline.map 回调的圆点 colorWarning 着色共用此单一来源，
// 防止两处内联各自演化导致徽标与圆点着色不一致。判定口径：后端 backward 字段
// 单源，缺失时回退旧 !!reason 判定兼容存量/归档数据（语义固化，勿改口径）
function isRollbackNode(item: TimelineItem): boolean {
  return item.backward === true || (item.backward === undefined && !!item.reason);
}

// 状态转移节点的输出信息用默认黑色正文（此前 secondary 灰色不易读），链接分支保留可点
function ReasonText({ reason, onOpenReport }: { reason: string; onOpenReport: () => void }) {
  const m = reason.match(VERIFICATION_LINK_RE);
  if (!m) return <Typography.Text>{reason}</Typography.Text>;
  return (
    <Typography.Text>
      {m[1]}
      <a
        role="button"
        tabIndex={0}
        onClick={onOpenReport}
        onKeyDown={(e) => {
          // 键盘可达（code-review item 5a09c657773d）：裸 a 无 href 不进焦点序，
          // 比照告警展开/清除链接（item 5c90f027199a）补 role/tabIndex/onKeyDown，
          // Enter/Space 触发打开验证报告弹窗，preventDefault 防空格滚动页面
          if (e.key === 'Enter' || e.key === ' ') {
            e.preventDefault();
            onOpenReport();
          }
        }}
      >
        verification report
      </a>
      {m[2]}
    </Typography.Text>
  );
}

// ── 四类节点渲染组件（code-review item e71de07a25a4）：原 ~400 行内联 map 回调
// 拆为具名节点组件（StateNode/AdminNode/VerifyNode/RunNode），Timeline items 的
// map 回调只做 kind 分发、圆点着色与 props 组装；共享局部（cardBox/headRow/
// fmtTime/token）经 props 显式传入，各分支 JSX 与拆分前等价，渲染输出不变。
type TimelineNodeShared = {
  item: TimelineItem;
  cardBox: (urgent: boolean) => CSSProperties;
  headRow: CSSProperties;
  fmtTime: (v: string) => string;
  token: ReturnType<typeof theme.useToken>['token'];
};

// 状态节点：头部保留「状态转移」标签，from → to 中文标签（同 SPEC 列表 statusMeta）换行显示在内容区；
// 折叠节点携带 chain（完整状态序列）时全链展开渲染，中间状态不省略
// （fast-track 连跳 implemented→testing→verified→done→pushed 只显示一头一尾会掩盖真实途经状态）
// 回退方向单源后端 backward 字段（缺失时回退旧判定兼容存量/归档数据）：
// 带 reason 的前向节点（如恢复直写行的精确 error）不再挂「↩ 状态回退」徽标
function StateNode({
  item, cardBox, headRow, fmtTime, token, onOpenReport,
}: TimelineNodeShared & { onOpenReport: () => void }) {
  const isRollback = isRollbackNode(item);
  const chainStatuses: string[] = (item.chain && item.chain.length > 1)
    ? item.chain
    : [item.from || '', item.to || ''];
  const statusSeq = chainStatuses.map((s, i) => (
    <Fragment key={`${s}-${i}`}>
      {i > 0 && <Typography.Text type="secondary">→</Typography.Text>}
      <OutlinedTag tone={statusMeta(s || '').tone}>{s ? statusMeta(s).label : '?'}</OutlinedTag>
    </Fragment>
  ));
  // testing 停等注记（add-timeline-ocr-lane-visibility 任务 2.3）：最新
  // 「→ testing」节点在 ocr 门 running 时显示（后端仅对该节点下发 ocr_gate，
  // 其余状态 ocrJoinNote 返回 null 零渲染）；detail 为门禁合成同源辅助文案
  const ocrNote = ocrJoinNote(item.ocr_gate?.status);
  return (
    <div style={cardBox(false)}>
      <div style={headRow}>
        <Typography.Text type="secondary" style={{ fontSize: 12 }}>
          {fmtTime(item.time)}
        </Typography.Text>
        <Tag>状态转移</Tag>
        {isRollback && <Tag color="orange">↩ 状态回退</Tag>}
      </div>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
        {statusSeq}
      </div>
      {/* 立项原话展示块（add-timeline-origin-request 任务 3.2）：首个
          state 节点（含折叠链）携带非空 origin_request 时，在 from→to
          状态行下方渲染原文——样式与 run 节点 Agent 输出总结盒同源
          （token 边框/底色盒式卡片 + 默认正文色，用户定调弃用此前的
          次级灰色小字引用形态，顺带消除硬编码浅色在暗色主题下的
          亮色补丁）；多行原文 white-space: pre-wrap 保留换行完整显示；
          字段缺失或空字符串不渲染任何展示块结构。
          用户定调（2026-10-30）不限高不滚动，原文完整撑开展示
          （覆盖 design D3 的限高滚动兜底） */}
      {item.origin_request && (
        <div
          className="spec-origin-request-quote"
          style={{
            // 2026-11-06 用户指令：去描边（节点本体已是磁贴，盒式边框属双重
            // chrome），上边距 10→6
            marginTop: 6,
            padding: '8px 12px',
            background: token.colorBgContainer,
            fontSize: 13,
          }}
        >
          <Typography.Text style={{ whiteSpace: 'pre-wrap' }}>
            {item.origin_request}
          </Typography.Text>
        </div>
      )}
      {ocrNote && (
        <div style={{ whiteSpace: 'pre-wrap', marginTop: 10 }}>
          <Typography.Text type="warning" style={{ fontSize: 13 }}>
            {ocrNote}
            {item.ocr_gate?.detail ? `（${item.ocr_gate.detail}）` : ''}
          </Typography.Text>
        </div>
      )}
      {isRollback && (
        <div style={{ whiteSpace: 'pre-wrap', marginTop: 10 }}>
          <ReasonText reason={item.reason || '状态回退'} onOpenReport={onOpenReport} />
        </div>
      )}
    </div>
  );
}

// 运维事件节点（add-timeline-admin-events）：紧凑卡片——标题行
// （时间 + 运维处置/升级告警 Tag + severity 着色 + 状态 Tag）+ 摘要
// （description，与其他节点同口径：默认 14px、pre-wrap 可换行）。
// 不渲染 summary markdown 全文（完整四段总结仍由运维记录页承载）。
function AdminNode({ item, cardBox, headRow, fmtTime }: TimelineNodeShared) {
  const isEscalation = item.record_kind === 'escalation';
  const sev = String(item.severity || '');
  // severity 着色复用运维记录页语义：critical 红 / major 橙 / 其余灰
  // 分支选择以 if/else 表达（code-review item 93d38a7f6847）：嵌套三元
  // 违反前端「禁止嵌套三元」规则（先例：statusTag 7471b4865219）
  let sevColor: string;
  if (sev === 'critical') {
    sevColor = 'red';
  } else if (sev === 'major') {
    sevColor = 'orange';
  } else {
    sevColor = 'default';
  }
  // 状态 Tag：disposition 终态（resolved 等）绿「已解决」、pending 蓝「处置中」、
  // result 缺失中性「未知状态」（状态不明不宣示已解决）；
  // escalation handled 绿「已处理」、未处理橙
  const dispResult = String(item.result || '');
  const dispDone = !!dispResult && dispResult !== 'pending';
  // 分支选择以 if/else 表达（code-review item 7471b4865219）：嵌套三元
  // 违反前端「禁止嵌套三元」规则（先例：MessageItem avatarFor fd9e3ef421b4）
  let statusTag: ReactNode;
  if (isEscalation) {
    statusTag = item.handled
      ? <Tag color="green" style={{ marginInlineEnd: 0 }}>已处理</Tag>
      : <Tag color="orange" style={{ marginInlineEnd: 0 }}>未处理</Tag>;
  } else if (dispDone) {
    statusTag = <Tag color="green" style={{ marginInlineEnd: 0 }}>已解决</Tag>;
  } else if (dispResult) {
    statusTag = <Tag color="blue" style={{ marginInlineEnd: 0 }}>处置中</Tag>;
  } else {
    statusTag = <Tag style={{ marginInlineEnd: 0 }}>未知状态</Tag>;
  }
  return (
    <div style={cardBox(false)}>
      <div style={headRow}>
        <Typography.Text type="secondary" style={{ fontSize: 12 }}>
          {fmtTime(item.time)}
        </Typography.Text>
        <Tag>{isEscalation ? '升级告警' : '运维处置'}</Tag>
        <Tag color={sevColor} style={{ marginInlineEnd: 0 }}>
          {/* SEV_LABEL 查找用 hasOwnProperty 自有键防御（code-review item
              5f9331c7ecae，口径同 codeFixGuidance.isKnownReason）：后端下发
              'constructor' 等畸形 severity 时普通对象查找命中原型链继承键
              拿到函数，作为子节点渲染会抛运行时错 */}
          {Object.prototype.hasOwnProperty.call(SEV_LABEL, sev) ? SEV_LABEL[sev] : sev || '未知'}
        </Tag>
        {statusTag}
      </div>
      <Typography.Text style={{ whiteSpace: 'pre-wrap', display: 'block' }}>
        {item.description || ''}
      </Typography.Text>
    </div>
  );
}

// 验证执行节点（verify_engine 确定性执行，非 agent run）：原时间轴
// 不可见导致 testing→verified 连跳被误读为「跳过验证」
// （fix-provider-transient-backoff 事故）。节点不着红：有失败也可能
// 被 judge 判定通过（裁决权在 judge），失败数只在内容行文字着色。
// 橙=有失败/警告/env 受阻，绿=全过。
function VerifyNode({ item, cardBox, headRow, fmtTime, token }: TimelineNodeShared) {
  const vDur = item.duration_seconds != null ? fmtDuration(item.duration_seconds) : '';
  // 统计明细（N 场景/通过/失败/错误/警告）放内容区正文行：数字着色、
  // 0 值项省略，分隔符对齐列表页 VerifyCell 悬浮汇总口径；耗时放标题行
  // 数字着色走语义 token（code-review 180d01dc3edb，对齐 b64f38deac7d
  // token 化口径）：通过 colorSuccess、失败/错误 colorError、警告
  // colorWarning，随主题定制变化
  const statParts: ReactNode[] = [];
  if (item.total != null) statParts.push(<span key="total">{item.total} 场景</span>);
  if (item.passed != null) {
    statParts.push(<span key="passed" style={{ color: token.colorSuccess }}>通过 {item.passed}</span>);
  }
  if (!!item.failed) {
    statParts.push(<span key="failed" style={{ color: token.colorError }}>失败 {item.failed}</span>);
  }
  if (!!item.errors) {
    statParts.push(<span key="errors" style={{ color: token.colorError }}>错误 {item.errors}</span>);
  }
  if (!!item.warnings) {
    statParts.push(<span key="warnings" style={{ color: token.colorWarning }}>警告 {item.warnings}</span>);
  }
  return (
    <div style={cardBox(false)}>
      <div style={headRow}>
        <Typography.Text type="secondary" style={{ fontSize: 12 }}>
          {fmtTime(item.time)}
        </Typography.Text>
        <Typography.Text style={{ fontSize: 12 }}>验证执行</Typography.Text>
        {vDur && (
          <Typography.Text type="secondary" style={{ fontSize: 12 }}>
            耗时 {vDur}
          </Typography.Text>
        )}
      </div>
      {statParts.length > 0 && (
        <div style={{ fontSize: 14 }}>
          {statParts.map((node, i) => (
            <Fragment key={i}>
              {/* code-review 180d01dc3edb：分隔符走 colorTextQuaternary
                  （原 rgba(0,0,0,0.45) 在暗色主题深底上几乎不可见） */}
              {i > 0 && <span style={{ color: token.colorTextQuaternary }}> · </span>}
              {node}
            </Fragment>
          ))}
        </div>
      )}
      {item.env_error && (
        <div style={{ whiteSpace: 'pre-wrap', marginTop: 4 }}>
          <Typography.Text type="warning" style={{ fontSize: 12 }}>
            环境受阻：{item.env_error}
          </Typography.Text>
        </div>
      )}
    </div>
  );
}

// 运行节点：头部时间 + Agent 标签 + 状态/成本/重试/耗时标注 + 活跃 run「终止」
// 操作，正文承载终态原因、ocr 车道摘要、arbiter 处置台账联查块、ClaudeCode
// 总结 markdown 与「查看运行记录」折叠面板。
function RunNode({
  item, cardBox, headRow, fmtTime, token, isMobile, name, cancelNotices, onCancelRun, onViewRecord,
}: TimelineNodeShared & {
  isMobile: boolean;
  name: string;
  cancelNotices: Record<string, string>;
  onCancelRun: (runId: string) => void;
  onViewRecord: (runId: string, harness?: string) => void;
}) {
  const st = item.status || '';
  const isErr = st === 'error';
  // 门禁拒绝（add-timeline-gate-failure-display D5）：产物硬门失败终止本次
  // attempt 的独立终态，语义等同 error（失败）——不并入失败分支会落入下方
  // 绿色兜底，重现「门禁连续拒绝显示成一串顺利收工绿点」的误导
  const isGateBlocked = st === 'gate-blocked';
  // 原地重试弃置件（superseded）：本身不是失败终态（圆点/Tag 仍绿——失败归因由
  // 紧随其后的 gate-blocked 节点承担，避免同一次失败出现两个红节点），但带原因
  // 时由 reasonTone 渲染中性色「原地重试：」行，MUST NOT 呈现为无原因绿点
  const isFailed = isErr || isGateBlocked;
  const reasonView = reasonTone(st);
  // interrupted/cancelled：已终结但非崩溃（daemon 停机/启动清扫补写/
  // 人工取消），橙色区别于 error 红；不处理会落入 else 误显成功绿
  const isRunning = st === 'running' || st === 'empty';
  // 圆点着色五分支单源（add-spec-topology-bigscreen 3.1 等价迁移至
  // runDotColor：error/gate-blocked 红、interrupted/cancelled 橙、
  // stale 灰、running/empty 蓝、其余绿兜底——渲染输出与迁移前一致）
  const dotColor = runDotColor(st);
  const dur = item.duration_seconds != null ? fmtDuration(item.duration_seconds) : '';
  const isFix = item.spec && String(item.spec).startsWith('fix-');

  return (
    <div style={cardBox(isFailed)}>
      <div style={headRow}>
        <Typography.Text type="secondary" style={{ fontSize: 12 }}>
          {fmtTime(item.time)}
        </Typography.Text>
        <Typography.Text style={{ fontSize: 12 }}>{agentLabel(item)}</Typography.Text>
        {item.llm && <Tag color="blue" style={{ marginInlineEnd: 0 }}>{item.llm}</Tag>}
        {/* add-model-billing-cost-display：可计价 run 成本标注（样式同 llm Tag；
            不可计价节点不下发 cost_usd，不渲染，避免历史节点噪音） */}
        {item.cost_usd != null && (
          <Tag color="green" style={{ marginInlineEnd: 0 }}>{formatUsd(item.cost_usd)}</Tag>
        )}
        {(item.retry_count ?? 0) > 0 && (
          <Tag color="orange" style={{ marginInlineEnd: 0 }}>
            重试 {item.retry_count}{item.retry_max ? `/${item.retry_max}` : ''}
          </Tag>
        )}
        {/* 配色单一来源复用 dotColor（含 isAborted 橙色分支），与圆点语义一致 */}
        <Tag color={dotColor} style={{ marginInlineEnd: 0 }}>
          {isGateBlocked ? '门禁拒绝' : st || '未知状态'}
        </Tag>
        {isFix && <Tag color="orange">🔧 {item.spec}</Tag>}
        {dur && (
          <Typography.Text type="secondary" style={{ fontSize: 12 }}>
            耗时 {dur}
          </Typography.Text>
        )}
        {/* add-run-cancel（4.2）：活跃 run 提供「终止」操作，确认弹窗确认后才发起 */}
        {isRunning && item.run_id && (
          <Button
            size="small"
            danger
            type="text"
            onClick={() => onCancelRun(item.run_id!)}
          >
            终止
          </Button>
        )}
        {item.run_id && cancelNotices[item.run_id] && (
          <Typography.Text type="success" style={{ fontSize: 12 }}>
            {cancelNotices[item.run_id]}
          </Typography.Text>
        )}
      </div>
      {/* 终态原因（run 产物 error/interrupted/cancelled/superseded/
          gate-blocked 事件的人类可读原因）：不展开运行记录即可见死因；
          运行中/成功 run 下发空串不渲染。
          error 与门禁拒绝（gate-blocked）红色（同节点圆点语义）；门禁拒绝
          前缀与失败原因区分，便于一眼分清「产物门拒绝」与「运行崩了」；
          superseded 为被弃置的中间产物，中性色 + 「原地重试：」前缀；
          interrupted/cancelled 已终结非崩溃用橙色 */}
      {!!item.reason && (
        <div style={{ marginBottom: 8 }}>
          <Typography.Text type={reasonView.tone} style={{ fontSize: 13 }}>
            {reasonView.prefix}
            {item.reason}
          </Typography.Text>
        </div>
      )}
      {/* ocr 车道审查对象摘要（add-timeline-ocr-lane-visibility 任务 2.3）：
          转录 start 事件 message（分支与 from..to 审查区间）；缺失不渲染 */}
      {item.lane_summary && (
        <div style={{ marginBottom: 8 }}>
          <Typography.Text type="secondary" style={{ fontSize: 13 }}>
            {item.lane_summary}
          </Typography.Text>
        </div>
      )}
      {/* arbiter 处置台账联查块（add-arbiter-quality-display 任务 2.3）：
          命中台账条目的 arbiter run 节点渲染「结论 Tag（着色区分自主
          处置/升级人工）+ 根因摘要行 + 处置动作/升级理由摘要行」；
          字段缺失静默省略对应行；无 arbiter 字段的节点零渲染（与
          现状逐字节等价）。纯展示块，无任何交互形态。 */}
      {item.arbiter && (
        <div
          style={{
            marginBottom: 8,
            padding: '8px 12px',
            border: `1px solid ${token.colorBorderSecondary}`,
            borderRadius: 8,
            background: token.colorBgContainer,
            fontSize: 13,
          }}
        >
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
            <Tag color={arbiterOutcomeTone(item.arbiter.kind)} style={{ marginInlineEnd: 0 }}>
              {arbiterOutcomeLabel(item.arbiter.kind)}
            </Tag>
          </div>
          {!!item.arbiter.root_cause && (
            <div style={{ marginTop: 4, whiteSpace: 'pre-wrap' }}>
              <Typography.Text style={{ fontSize: 13 }}>
                根因：{item.arbiter.root_cause}
              </Typography.Text>
            </div>
          )}
          {!!item.arbiter.action_or_upgrade && (
            <div style={{ marginTop: 4, whiteSpace: 'pre-wrap' }}>
              <Typography.Text style={{ fontSize: 13 }}>
                {arbiterActionFieldLabel(item.arbiter.kind)}：{item.arbiter.action_or_upgrade}
              </Typography.Text>
            </div>
          )}
        </div>
      )}
      {/* ClaudeCode 最后一条总结（result 字段，markdown）：不展开运行记录即可掌握结论。
          2026-11-06 用户指令：去描边（节点本体已是磁贴）、上左右内边距收紧——
          padding 8px 12px → 0px 12px */}
      {item.summary && (
        <div
          style={{
            marginBottom: 8,
            padding: '0px 12px',
            background: token.colorBgContainer,
            fontSize: 13,
          }}
        >
          <Markdown remarkPlugins={TIMELINE_REMARK_PLUGINS} components={markdownComponents}>
            {item.summary}
          </Markdown>
        </div>
      )}
      {item.run_id && (
        <Collapse
          ghost
          size="small"
          items={[
            {
              key: 'run-stream',
              label: (
                <span style={{ display: 'inline-flex', alignItems: 'center', gap: 4 }}>
                  查看运行记录
                  <Button
                    type="text"
                    size="small"
                    title="最大化查看"
                    icon={<FullscreenOutlined />}
                    onClick={(e) => {
                      e.stopPropagation();
                      onViewRecord(item.run_id!, item.harness);
                    }}
                  />
                </span>
              ),
              // ClaudeOutputPane 依赖父容器高度约束，这里限高滚动避免时间轴被长运行拉穿
              children: (
                <div style={{ maxHeight: 480, overflow: 'auto', border: `1px solid ${token.colorBorderSecondary}`, borderRadius: 8, padding: isMobile ? 4 : 8, background: token.colorBgLayout }}>
                  {/* 品牌投影（add-harness-brand-projection 3.1）：内嵌 pane 与
                      最大化弹窗同口径注入 run 节点的 harness */}
                  <HarnessBrandProvider harness={item.harness}>
                    <ClaudeOutputPane runId={item.run_id!} project={name} />
                  </HarnessBrandProvider>
                </div>
              ),
            },
          ]}
        />
      )}
    </div>
  );
}

// add-model-billing-cost-display（design D5）：金额格式化（formatUsd）已等价
// 迁至 @/utils/runVisual（add-spec-topology-bigscreen 3.1），本文件经顶部
// import + re-export 单点转发，detail.tsx 既有 import 路径零改动。

export default function SpecTimeline({
  timeline,
  isMobile,
  name,
  cancelNotices,
  onCancelRun,
  onViewRecord,
  onOpenVerificationReport,
}: {
  timeline: TimelineItem[];
  isMobile: boolean;
  name: string;
  cancelNotices: Record<string, string>;
  onCancelRun: (runId: string) => void;
  onViewRecord: (runId: string, harness?: string) => void;
  onOpenVerificationReport: () => void;
}) {
    // 底色/边框历史口径（code-review item b64f38deac7d 曾将硬编码浅色
    // #fafafa/#fff/#f0f0f0 全部 token 化以消除暗色主题亮色补丁）；但 2026-11-06
    // Bento 磁贴形态指令（见下方 cardBox 注释）有意让非急态磁贴回用纯白底
    // '#ffffff' + 发丝边 OV_TILE_BORDER（'#eef2f7'），暗色主题下磁贴呈亮色
    // 补丁属有意取舍，勿据旧「token 化」口径改回；急态红边/红底仍走
    // colorError/colorErrorBg 语义 token。useToken 只能在组件内调用
    // （同 SessionPanel.tsx 惯例）
    const { token } = theme.useToken();
    const cardBox = (urgent: boolean): CSSProperties => ({
      padding: isMobile ? 8 : 12,
      // Bento 磁贴形态（2026-11-06 用户指令：节点各自成磁贴）：发丝边 + 12 圆角
      // + 软阴影 + 纯白底；urgent（失败 run / 门禁拒绝）保留警示描边与红软底——
      // 数据语义色不随视觉换轨
      borderRadius: 12,
      border: urgent ? `1px solid ${token.colorError}` : `1px solid ${OV_TILE_BORDER}`,
      background: urgent ? token.colorErrorBg : '#ffffff',
      boxShadow: OV_TILE_SHADOW,
    });
    const headRow: CSSProperties = {
      display: 'flex',
      alignItems: 'center',
      gap: 8,
      marginBottom: 8,
      flexWrap: 'wrap',
    };
    const fmtTime = (v: string) => {
      const d = dayjs(v);
      return d.isValid() ? d.format('YYYY-MM-DD HH:mm:ss') : v;
    };

    return (
      <Timeline
        items={timeline.map((item) => {
          // kind 分发（code-review item e71de07a25a4）：四类节点渲染拆为上方
          // 具名组件，map 回调只做 kind 分发、圆点着色与 props 组装；共享局部
          // 经 props 显式传入，各分支 JSX 与拆分前等价，渲染输出不变
          const shared = { item, cardBox, headRow, fmtTime, token };
          if (item.kind === 'state') {
            // 回退圆点走语义 token.colorWarning（code-review 180d01dc3edb，对齐
            // b64f38deac7d token 化口径）：与 StateNode 内「↩ 状态回退」orange
            // Tag 同语气；runDotColor 以 status 为输入、回退是方向语义非状态，
            // 故不直接复用
            const isRollback = isRollbackNode(item);
            return {
              color: isRollback ? token.colorWarning : 'gray',
              children: <StateNode {...shared} onOpenReport={onOpenVerificationReport} />,
            };
          }

          if (item.kind === 'admin') {
            return { color: 'blue', children: <AdminNode {...shared} /> };
          }

          // 验证执行节点圆点：橙=有失败/警告/env 受阻，绿=全过（口径详见
          // VerifyNode 头注）
          if (item.kind === 'verify') {
            const vFailed = (item.failed || 0) + (item.errors || 0);
            const hasIssue = vFailed > 0 || !!item.env_error;
            const vWarn = (item.warnings || 0) > 0;
            return {
              color: hasIssue || vWarn ? 'orange' : 'green',
              children: <VerifyNode {...shared} />,
            };
          }

          // 兜底守卫（add-timeline-admin-events）：以上各 kind 分支未处理的
          // 已知/未知 kind 一律降级为灰点（只留时间轴圆点，不渲染卡片体），
          // 不报错崩渲染
          if (item.kind !== 'run') {
            return { color: 'gray' };
          }

          // 运行节点：圆点着色五分支单源 runDotColor（详见 RunNode 头注）
          return {
            color: runDotColor(item.status || ''),
            children: (
              <RunNode
                {...shared}
                isMobile={isMobile}
                name={name}
                cancelNotices={cancelNotices}
                onCancelRun={onCancelRun}
                onViewRecord={onViewRecord}
              />
            ),
          };
        })}
      />
    );
}
