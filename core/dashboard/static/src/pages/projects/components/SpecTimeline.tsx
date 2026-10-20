// SpecTimeline.tsx — SPEC 详情「运行时间轴」渲染（原 detail.tsx 内联 renderTimeline，
// code-review item fa5ce9f79354 抽出：主文件保留数据流与页签编排，state/admin/
// verify/run 四类节点与盒式卡片的渲染编排集中于此）。行为与抽取前严格等价：
// 原组件内闭包依赖（isMobile/name/cancelNotices 与终止 run/最大化运行记录/
// 打开验证报告回调）改为显式 props 注入。
//
// 复用运维记录页的时间轴控件（Timeline + 盒式卡片子项：头部时间+标签行，正文着色边框）。
import { Button, Collapse, Tag, Timeline, Typography } from 'antd';
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
import { ocrJoinNote } from '../qualityGates';
import { markdownComponents } from './SpecDocModal';

type TimelineItem = NonNullable<SpecDetail['timeline']>[number];

// Agent 中文名（与设置页 Agent 模型角色中文名对应；implementer 沿用「开发」）。
// agent_type 为泛型 'agent' 或缺失时，按 run_id 前缀（RUN_ID_PREFIX_LABEL）判别。
const AGENT_LABEL: Record<string, string> = {
  implementer: '开发 Agent',
  'impl-ocr': '代码审查 Agent',
  planner: '规划 Agent',
  'planner-plan': '生成场景 Agent',
  'planner-judge': '判定结果 Agent',
  'spec-review': '需求评审 Agent',
  'dispute-judge': '争议裁决 Agent',
  repair: '修复 Agent',
  verifier: '验证 Agent',
  tester: '测试 Agent',
  administrator: '运维 Agent',
};

// run_id 前缀兜底。⚠️ 必须按完整前缀匹配（不能用 split('-')[0]）：spec-review- /
// dispute-judge- / planner-plan- 等是多段前缀，首段 'spec'/'dispute'/'planner'
// 无法唯一归属；长的排前面，首个命中即止（impl-ocr- 必须排在 impl- 之前，
// 否则被 impl- 先命中、车道节点标签退回「开发 Agent」）。
const RUN_ID_PREFIX_LABEL: [prefix: string, label: string][] = [
  ['planner-judge-', '判定结果 Agent'],
  ['planner-plan-', '生成场景 Agent'],
  ['dispute-judge-', '争议裁决 Agent'],
  ['spec-review-', '需求评审 Agent'],
  ['impl-ocr-', '代码审查 Agent'],
  ['impl-', '开发 Agent'],
  ['repair-', '修复 Agent'],
  ['admin-', '运维 Agent'],
  ['test-', '测试 Agent'],
  ['verify-', '验证 Agent'],
];

function agentLabel(item: { agent_type?: string; run_id?: string }): string {
  const t = (item.agent_type || '').toLowerCase();
  // 泛型 'agent' 视同缺失（后端未识别出类型），继续走 run_id 前缀判别
  if (t && t !== 'agent' && AGENT_LABEL[t]) return AGENT_LABEL[t];
  const rid = (item.run_id || '').toLowerCase();
  for (const [prefix, label] of RUN_ID_PREFIX_LABEL) {
    if (rid.startsWith(prefix)) return label;
  }
  return AGENT_LABEL[t] || '未知 Agent';
}

/** run 终态原因行的呈现（add-timeline-gate-failure-display D5）：语气 + 前缀。
 *
 * 门禁拒绝（gate-blocked）与 error 同为失败（danger 红，前缀区分「门禁拒绝：」与
 * 「失败原因：」——一眼分清「产物门拒绝」与「运行崩了」）；superseded 是被弃置的
 * 中间产物（secondary + 「原地重试：」，失败归因由紧随其后的 gate-blocked 节点承担）；
 * 其余中止类（interrupted/cancelled）橙色 warning。未知状态落 warning/中止原因，
 * 与改动前行为一致。映射单一真源，渲染处 MUST NOT 再内联重复该条件链。 */
function reasonTone(
  st: string,
): { tone: 'danger' | 'warning' | 'secondary'; prefix: string } {
  if (st === 'gate-blocked') return { tone: 'danger', prefix: '门禁拒绝：' };
  if (st === 'error') return { tone: 'danger', prefix: '失败原因：' };
  if (st === 'superseded') return { tone: 'secondary', prefix: '原地重试：' };
  return { tone: 'warning', prefix: '中止原因：' };
}

// 回退原因含「verification report」时渲染为链接（点击打开验证报告弹窗）
const VERIFICATION_LINK_RE = /^(.*?)verification report(.*)$/i;

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

// add-model-billing-cost-display（design D5）：金额格式化——统一 $x.xx；
// < $0.01 显示三位小数（$0.001），避免小额全零。仅展示口径，不做入账四舍五入。
// detail.tsx 头部信息区/降级注记仍消费本函数（code-review item fa5ce9f79354
// 抽取时随时间轴 helper 迁入，回导入避免两处重复实现）
export function formatUsd(v: number): string {
  if (v > 0 && v < 0.01) return `$${v.toFixed(3)}`;
  return `$${v.toFixed(2)}`;
}

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
    const cardBox = (urgent: boolean): CSSProperties => ({
      padding: isMobile ? 8 : 12,
      borderRadius: 8,
      border: urgent ? '1px solid #ff4d4f' : '1px solid #f0f0f0',
      background: urgent ? '#fff2f0' : '#fafafa',
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
          if (item.kind === 'state') {
            // 状态节点：头部保留「状态转移」标签，from → to 中文标签（同 SPEC 列表 statusMeta）换行显示在内容区；
            // 折叠节点携带 chain（完整状态序列）时全链展开渲染，中间状态不省略
            // （fast-track 连跳 implemented→testing→verified→done→pushed 只显示一头一尾会掩盖真实途经状态）
            // 回退方向单源后端 backward 字段（缺失时回退旧判定兼容存量/归档数据）：
            // 带 reason 的前向节点（如恢复直写行的精确 error）不再挂「↩ 状态回退」徽标
            const isRollback = item.backward === true || (item.backward === undefined && !!item.reason);
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
            return {
              color: isRollback ? '#ec835a' : 'gray',
              children: (
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
                      <ReasonText reason={item.reason || '状态回退'} onOpenReport={onOpenVerificationReport} />
                    </div>
                  )}
                </div>
              ),
            };
          }

          if (item.kind === 'admin') {
            // 运维事件节点（add-timeline-admin-events）：紧凑卡片——标题行
            // （时间 + 运维处置/升级告警 Tag + severity 着色 + 状态 Tag）+ 摘要
            // （description，与其他节点同口径：默认 14px、pre-wrap 可换行）。
            // 不渲染 summary markdown 全文（完整四段总结仍由运维记录页承载）。
            const isEscalation = item.record_kind === 'escalation';
            const sev = String(item.severity || '');
            // severity 着色复用运维记录页语义：critical 红 / major 橙 / 其余灰
            const sevColor = sev === 'critical' ? 'red' : sev === 'major' ? 'orange' : 'default';
            // 状态 Tag：disposition 终态（resolved 等）绿「已解决」、pending 蓝「处置中」、
            // result 缺失中性「未知状态」（状态不明不宣示已解决）；
            // escalation handled 绿「已处理」、未处理橙
            const dispResult = String(item.result || '');
            const dispDone = !!dispResult && dispResult !== 'pending';
            const statusTag = isEscalation
              ? (item.handled
                ? <Tag color="green" style={{ marginInlineEnd: 0 }}>已处理</Tag>
                : <Tag color="orange" style={{ marginInlineEnd: 0 }}>未处理</Tag>)
              : (dispDone
                ? <Tag color="green" style={{ marginInlineEnd: 0 }}>已解决</Tag>
                : dispResult
                  ? <Tag color="blue" style={{ marginInlineEnd: 0 }}>处置中</Tag>
                  : <Tag style={{ marginInlineEnd: 0 }}>未知状态</Tag>);
            return {
              color: 'blue',
              children: (
                <div style={cardBox(false)}>
                  <div style={headRow}>
                    <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                      {fmtTime(item.time)}
                    </Typography.Text>
                    <Tag>{isEscalation ? '升级告警' : '运维处置'}</Tag>
                    <Tag color={sevColor} style={{ marginInlineEnd: 0 }}>
                      {SEV_LABEL[sev] || sev || '未知'}
                    </Tag>
                    {statusTag}
                  </div>
                  <Typography.Text style={{ whiteSpace: 'pre-wrap', display: 'block' }}>
                    {item.description || ''}
                  </Typography.Text>
                </div>
              ),
            };
          }

          // 验证执行节点（verify_engine 确定性执行，非 agent run）：原时间轴
          // 不可见导致 testing→verified 连跳被误读为「跳过验证」
          // （fix-provider-transient-backoff 事故）。节点不着红：有失败也可能
          // 被 judge 判定通过（裁决权在 judge），失败数只在内容行文字着色。
          // 橙=有失败/警告/env 受阻，绿=全过。
          if (item.kind === 'verify') {
            const vFailed = (item.failed || 0) + (item.errors || 0);
            const hasIssue = vFailed > 0 || !!item.env_error;
            const vWarn = (item.warnings || 0) > 0;
            const vDur = item.duration_seconds != null ? fmtDuration(item.duration_seconds) : '';
            // 统计明细（N 场景/通过/失败/错误/警告）放内容区正文行：数字着色、
            // 0 值项省略，分隔符对齐列表页 VerifyCell 悬浮汇总口径；耗时放标题行
            const statParts: ReactNode[] = [];
            if (item.total != null) statParts.push(<span key="total">{item.total} 场景</span>);
            if (item.passed != null) {
              statParts.push(<span key="passed" style={{ color: '#52c41a' }}>通过 {item.passed}</span>);
            }
            if (!!item.failed) {
              statParts.push(<span key="failed" style={{ color: '#ff4d4f' }}>失败 {item.failed}</span>);
            }
            if (!!item.errors) {
              statParts.push(<span key="errors" style={{ color: '#ff4d4f' }}>错误 {item.errors}</span>);
            }
            if (!!item.warnings) {
              statParts.push(<span key="warnings" style={{ color: '#faad14' }}>警告 {item.warnings}</span>);
            }
            return {
              color: hasIssue || vWarn ? 'orange' : 'green',
              children: (
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
                          {i > 0 && <span style={{ color: 'rgba(0, 0, 0, 0.45)' }}> · </span>}
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
              ),
            };
          }

          // 未知 kind 守卫（add-timeline-admin-events）：state/admin/run 之外不渲染
          // 卡片体（脏数据降级只留时间轴圆点），不报错崩渲染
          if (item.kind !== 'run') {
            return { color: 'gray' };
          }

          // 运行节点
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
          const isAborted = st === 'interrupted' || st === 'cancelled';
          const isRunning = st === 'running' || st === 'empty';
          // stale（fix-retry-orphan-active-runs）：弃置/断尾——原地重试换文件
          // 弃置或进程被杀无终态，读侧 mtime 兜底判定；灰色区别于 running 蓝 /
          // error 红，归入非在飞非错误分支。未知 status 行为不变（绿兜底）
          const dotColor = isFailed ? 'red' : isAborted ? 'orange' : st === 'stale' ? 'gray' : isRunning ? 'blue' : 'green';
          const dur = item.duration_seconds != null ? fmtDuration(item.duration_seconds) : '';
          const isFix = item.spec && String(item.spec).startsWith('fix-');

          return {
            color: dotColor,
            children: (
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
                {/* ClaudeCode 最后一条总结（result 字段，markdown）：不展开运行记录即可掌握结论 */}
                {item.summary && (
                  <div
                    style={{
                      marginBottom: 8,
                      padding: '8px 12px',
                      border: '1px solid #f0f0f0',
                      borderRadius: 8,
                      background: '#fff',
                      fontSize: 13,
                    }}
                  >
                    <Markdown remarkPlugins={[remarkGfm]} components={markdownComponents}>
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
                          <div style={{ maxHeight: 480, overflow: 'auto', border: '1px solid #f0f0f0', borderRadius: 8, padding: isMobile ? 4 : 8, background: '#fafafa' }}>
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
            ),
          };
        })}
      />
    );
}
