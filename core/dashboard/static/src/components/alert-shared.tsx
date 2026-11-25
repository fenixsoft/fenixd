import dayjs from 'dayjs';
import { useState } from 'react';
import type { ReactNode } from 'react';
import { Button, Modal, Space, Tag, Typography } from 'antd';
import Markdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import type { AlertItem } from '@/services/dashboard';
import { markdownComponents } from '@/components/markdown-shared';
import { fmtEvidence } from '@/utils/evidence';
import { MaximizeTitle, useMaximizeModal } from '@/components/useMaximizeModal';
// 文案经 useIntl/getIntl（i18n 修复轮 batch-A：本文件静态中文文案迁 i18n 目录）
// ——映射表/纯函数经 utils/intlText.ts 取值：SEV/CAUSE/SIGNAL 映射表改 getter
// 存消息 id（访问期翻译=渲染期取值，键枚举/hasOwnProperty 语义不变，消费方
// 零改动），组件内文案渲染期 intlText 直取。
import { intlText } from '@/utils/intlText.ts';

/**
 * 告警展示单源（code-review item 5478d16d70c7）：SEV 常量、告警标题、明细字段
 * 与时间格式化此前在 overview/AlertBanner 与 pages/activities 各写一份且已漂移
 * （SEV_COLOR 缺 warning 键、fmtDate 空值占位一处 '' 一处 '—'），收敛到本模块。
 * 两个 surface 的历史布局差异经 variant 参数保留，不改任一页现有视觉行为：
 * - 'banner'（overview 横幅）：spec 以 📌 前缀并入明细首行、时间省年份；
 * - 'page'（activities 页）：标题带 spec 蓝标签、明细字段分行、完整年月日。
 */
export type AlertSurfaceVariant = 'banner' | 'page';

/** 严重度 → 展示标签（info 供后端 info 级信号，如 code_fix_wip_gate_deferred） */
export const SEV_LABEL: Record<string, string> = {
  get critical() { return intlText('components.alert.sev.critical'); },
  get major() { return intlText('components.alert.sev.major'); },
  get warning() { return intlText('components.alert.sev.warning'); },
  get minor() { return intlText('components.alert.sev.minor'); },
  get info() { return intlText('components.alert.sev.info'); },
};

/** 严重度 → antd Tag 配色（取两份历史实现的超集，补齐横幅侧缺失的 warning 键；info 用 default 灰最弱档） */
export const SEV_COLOR: Record<string, string> = { critical: 'red', major: 'orange', warning: 'gold', minor: 'blue', info: 'default' };

/**
 * 根因 → 展示标签（add-provider-validation-alert-governance 4.3）：与后端
 * ALERT_CAUSES 封闭枚举同词表；缺省/未知值回退「未知」——cause 字段缺席的
 * 存量记录（回填前的旧账本）不臆造归因。
 */
export const CAUSE_LABEL: Record<string, string> = {
  get 'model-chain'() { return intlText('components.alert.cause.modelChain'); },
  get 'harness-cli'() { return intlText('components.alert.cause.harnessCli'); },
  get 'init-stray'() { return intlText('components.alert.cause.initStray'); },
  get contract() { return intlText('components.alert.cause.contract'); },
  get 'daemon-error'() { return intlText('components.alert.cause.daemonError'); },
  get unknown() { return intlText('components.alert.cause.unknown'); },
};

/** 根因 → antd Tag 配色（同色系低饱和：根因是辅助筛选面，不与严重度抢视觉） */
export const CAUSE_COLOR: Record<string, string> = {
  'model-chain': 'purple',
  'harness-cli': 'volcano',
  'init-stray': 'orange',
  contract: 'gold',
  'daemon-error': 'magenta',
  unknown: 'default',
};

/**
 * 信号类型代号 → 展示名（2026-11-13 用户指令：运维页事件代号改显示名，让
 * 用户看懂运维 agent 处置的是什么问题）。词表=activities SIGNAL_LABEL 全集
 * 迁入 + 后端全量 escalation signal_type 字面（core/pm_engine/verification/
 * escalation.py、judge_gate.py、pipeline.py、dispatch/fast_track.py、
 * admin_monitor.py、agent_runner/provider_circuit.py、worktree_manager/
 * stray_wip.py 等发射点普查）；未收录代号回退原码（前端不臆造语义）。
 * activities/index.tsx 旧本地 SIGNAL_LABEL 已并表至此（单源纪律）。
 * i18n 修复轮 batch-A：值改 getter 存消息 id（键=signal_type 代号原样），
 * 经 intlText 访问期取值，键枚举语义不变。
 */
export const SIGNAL_TYPE_LABEL: Record<string, string> = {
  // 看门狗/状态机族（原 activities SIGNAL_LABEL 全集）
  get blocked_stuck() { return intlText('components.alert.signal.blocked_stuck'); },
  get stuck() { return intlText('components.alert.signal.stuck'); },
  get flapping() { return intlText('components.alert.signal.flapping'); },
  get dispatch_stalled() { return intlText('components.alert.signal.dispatch_stalled'); },
  get merge_streak() { return intlText('components.alert.signal.merge_streak'); },
  get 'manual-intervention'() { return intlText('components.alert.signal.manual-intervention'); },
  get repeated_failures() { return intlText('components.alert.signal.repeated_failures'); },
  get verify_fail_escalation() { return intlText('components.alert.signal.verify_fail_escalation'); },
  get ready_stuck() { return intlText('components.alert.signal.ready_stuck'); },
  get family_explosion() { return intlText('components.alert.signal.family_explosion'); },
  get daemon_errors() { return intlText('components.alert.signal.daemon_errors'); },
  get stash_pop_conflict() { return intlText('components.alert.signal.stash_pop_conflict'); },
  get mergeback_wip_overlap() { return intlText('components.alert.signal.mergeback_wip_overlap'); },
  get verify_uniform_failure() { return intlText('components.alert.signal.verify_uniform_failure'); },
  // 验证裁决族（pm_engine/verification/*）
  get inconclusive_loop() { return intlText('components.alert.signal.inconclusive_loop'); },
  get judge_rerun_cap() { return intlText('components.alert.signal.judge_rerun_cap'); },
  get judge_round_rerun_cap() { return intlText('components.alert.signal.judge_round_rerun_cap'); },
  get verdict_result_unreadable() { return intlText('components.alert.signal.verdict_result_unreadable'); },
  get verdict_evidence_invalid() { return intlText('components.alert.signal.verdict_evidence_invalid'); },
  get verdict_dedup_resynthesis_exhausted() { return intlText('components.alert.signal.verdict_dedup_resynthesis_exhausted'); },
  get attribution_evidence_insufficient() { return intlText('components.alert.signal.attribution_evidence_insufficient'); },
  get verifier_infra_death() { return intlText('components.alert.signal.verifier_infra_death'); },
  get verify_env_blocked() { return intlText('components.alert.signal.verify_env_blocked'); },
  get verify_redo_exhausted() { return intlText('components.alert.signal.verify_redo_exhausted'); },
  get verify_repeat_failure() { return intlText('components.alert.signal.verify_repeat_failure'); },
  get infra_reclassify() { return intlText('components.alert.signal.infra_reclassify'); },
  get scenario_defect_reroute_stoploss() { return intlText('components.alert.signal.scenario_defect_reroute_stoploss'); },
  get scenario_defect_reroute_exhausted() { return intlText('components.alert.signal.scenario_defect_reroute_exhausted'); },
  // 派发/实现族（dispatch、budget、state_machine）
  get redispatch_loop_detected() { return intlText('components.alert.signal.redispatch_loop_detected'); },
  get impl_budget_exhausted() { return intlText('components.alert.signal.impl_budget_exhausted'); },
  get impl_budget_exempt_loop() { return intlText('components.alert.signal.impl_budget_exempt_loop'); },
  get spec_content_missing() { return intlText('components.alert.signal.spec_content_missing'); },
  get spec_delivered_no_content() { return intlText('components.alert.signal.spec_delivered_no_content'); },
  get instant_fail_storm() { return intlText('components.alert.signal.instant_fail_storm'); },
  get provider_ref_invalid() { return intlText('components.alert.signal.provider_ref_invalid'); },
  get lane_env_unavailable() { return intlText('components.alert.signal.lane_env_unavailable'); },
  get 'quality-gates-form-drift'() { return intlText('components.alert.signal.quality-gates-form-drift'); },
  // 评审族（pm_engine/spec_review、arbiter.py L95-96 语义注释）
  get 'spec-review-incomplete'() { return intlText('components.alert.signal.spec-review-incomplete'); },
  get 'spec-review-rejected'() { return intlText('components.alert.signal.spec-review-rejected'); },
  // 运行器熔断族（agent_runner/provider_circuit）
  get signal_kill_storm() { return intlText('components.alert.signal.signal_kill_storm'); },
  get signal_kill_recovered() { return intlText('components.alert.signal.signal_kill_recovered'); },
  get hook_failure() { return intlText('components.alert.signal.hook_failure'); },
  // 工作树/主树游离改动族（worktree_manager/stray_wip、mergeback）
  get mergeback_wip_orphan_stuck() { return intlText('components.alert.signal.mergeback_wip_orphan_stuck'); },
  get maintree_stray_wip_stale() { return intlText('components.alert.signal.maintree_stray_wip_stale'); },
  get maintree_untracked_stray_stale() { return intlText('components.alert.signal.maintree_untracked_stray_stale'); },
  get maintree_untracked_stray_first_sight() { return intlText('components.alert.signal.maintree_untracked_stray_first_sight'); },
  get maintree_untracked_stray_escalated() { return intlText('components.alert.signal.maintree_untracked_stray_escalated'); },
  get whitelist_untracked() { return intlText('components.alert.signal.whitelist_untracked'); },
  get ghost_entry_reclaimed() { return intlText('components.alert.signal.ghost_entry_reclaimed'); },
  get host_change_rollback_obligation() { return intlText('components.alert.signal.host_change_rollback_obligation'); },
  // 管理/运维动作族（admin_monitor、code_fix、escalation 分诊）
  get admin_dispatch_programming_error() { return intlText('components.alert.signal.admin_dispatch_programming_error'); },
  get admin_reset_programming_error() { return intlText('components.alert.signal.admin_reset_programming_error'); },
  get warning_stale_triage() { return intlText('components.alert.signal.warning_stale_triage'); },
  get code_fix_night_quiet_window() { return intlText('components.alert.signal.code_fix_night_quiet_window'); },
  get code_fix_switch_window_deferred() { return intlText('components.alert.signal.code_fix_switch_window_deferred'); },
  get code_fix_zero_progress_paused() { return intlText('components.alert.signal.code_fix_zero_progress_paused'); },
};

/**
 * 信号类型显示值（2026-11-13 用户指令单点入口）：有中文名显中文，未收录
 * 代号回退原码不臆造；空值占位与 fmtDate 同款 '—'。
 */
export function signalTypeLabel(code?: string | null): string {
  if (!code) return '—';
  return SIGNAL_TYPE_LABEL[code] || code;
}

/**
 * 时间格式化。空值统一占位 '—'（此前漂移：横幅 ''、activities '—'）；
 * withYear=false 供横幅窄空间用 MM-DD 起头（历史布局差异，经参数保留）。
 */
export function fmtDate(v?: string, { withYear = true }: { withYear?: boolean } = {}) {
  if (!v) return '—';
  const d = dayjs(v);
  return d.isValid() ? d.format(withYear ? 'YYYY-MM-DD HH:mm:ss' : 'MM-DD HH:mm:ss') : v;
}

// 已解决徽标（code-review item 9e55d00cb91b）：旧实现以三层嵌套三元链分别
// 选择配色与文案，违反本项目前端「禁止嵌套三元」规则（比照 SystemPanel.tsx
// renderAdminField 的整改先例），抽模块级 helper 以 if/else 表达。仅依赖
// item.handled_by 字段本身，无组件闭包依赖，故放模块级；分派顺序与兜底值
// 与原实现逐字一致。
// add-alert-self-heal-marking 5.3：auto-self-heal（自愈闭环）独立徽标配色与
// 文案，区别于既有 auto-resolve（自动解决）。词表外未知值显示原文、仅空值
// 兜底「人工处理」（与 SEV_LABEL 未知值口径一致，避免后端新增自动化变体被
// 误标成人工处置）。
// add-provider-validation-alert-governance 4.3：superseded（同根因批量失效）
// 独立徽标——灰态弱化呈现，区别于解决/自愈等终态，配合「已失效」折叠组与
// 撤销入口表达「可人工恢复未处理」。
function handledBadgeColor(item: AlertItem): string {
  if (item.handled_by === 'superseded') return 'default';
  if (item.handled_by === 'auto-resolve') return 'cyan';
  if (item.handled_by === 'auto-self-heal') return 'green';
  return 'geekblue';
}

function handledBadgeText(item: AlertItem): string {
  if (item.handled_by === 'superseded') return intlText('components.alert.badge.superseded');
  if (item.handled_by === 'auto-resolve') return intlText('components.alert.badge.autoResolve');
  if (item.handled_by === 'auto-self-heal') return intlText('components.alert.badge.selfHeal');
  return item.handled_by || intlText('components.alert.badge.manual');
}

/** 告警标题：SEV 标签 +（已解决时）解决方式 + 项目 +（page 变体）spec + 时间 */
export function AlertTitle({
  item,
  resolved,
  variant,
}: {
  item: AlertItem;
  resolved?: boolean;
  variant: AlertSurfaceVariant;
}) {
  const isPage = variant === 'page';
  return (
    <Space wrap size={6}>
      <Tag color={SEV_COLOR[item.severity || ''] || 'default'} style={{ marginInlineEnd: 0 }}>
        {SEV_LABEL[item.severity || ''] || item.severity || intlText('common.status.unknown')}
      </Tag>
      {resolved ? (
        <Tag style={{ marginInlineEnd: 0 }} color={handledBadgeColor(item)}>
          {handledBadgeText(item)}
        </Tag>
      ) : null}
      {item.cause ? (
        <Tag
          style={{ marginInlineEnd: 0 }}
          color={CAUSE_COLOR[item.cause] || 'default'}
          data-testid="alert-cause-tag"
        >
          {intlText('components.alert.causeTag', { cause: CAUSE_LABEL[item.cause] || item.cause })}
        </Tag>
      ) : null}
      {item.project ? <Tag style={{ marginInlineEnd: 0 }}>{item.project}</Tag> : null}
      {isPage && item.spec ? <Tag style={{ marginInlineEnd: 0 }} color="blue">{item.spec}</Tag> : null}
      <Typography.Text type="secondary" style={{ fontSize: 12 }}>
        {fmtDate(resolved ? item.handled_at || item.created : item.created, { withYear: !isPage })}
      </Typography.Text>
    </Space>
  );
}

/** 该告警是否携带正式调查报告（sidecar model 有值；null=失败/熔断终态机械说明）。
 * 类型谓词收窄（code-review item 4e415b5643db）：true 分支向调用方承诺 narrative
 * 必有且 text 为 string（剥掉 optional 外壳），调用方据此免 `!` 非空断言；
 * 运行时判定逻辑不变（text + model 双 truthy）。 */
export function hasNarrativeReport(
  item: AlertItem,
): item is AlertItem & { narrative: { text: string } } {
  return !!(item.narrative?.text && item.narrative.model);
}

/**
 * 告警操作按钮竖排列（查看调查报告 / 执行 / 标记已处理同列）：竖向排布、
 * 按钮随最宽者拉伸等宽（align-items stretch），作为单个元素传入 antd
 * List.Item 的 actions（antd 本身只做横向排布，竖排语义由本容器承载）。
 */
export function AlertActionColumn({ children }: { children: ReactNode }) {
  return (
    <div
      style={{
        display: 'flex',
        flexDirection: 'column',
        gap: 8,
        alignItems: 'stretch',
        minWidth: 88,
      }}
    >
      {children}
    </div>
  );
}

/**
 * 调查报告弹窗入口（原三段式内联叙事区块，add-adjudication-alert-narrative 4.1
 * → 弹窗化改造）：四段式调查报告动辄数千字，内联 320px 小框滚动不利于阅读，
 * 改为「查看调查报告」入口按钮 + 居中 Modal 全文阅读。
 * - 按钮纯文字无图标（与执行/标记已处理同列竖排、等宽，见 AlertActionColumn）；
 * - Modal 默认即视口 80% × 80%（width 80vw / body 高 80vh），可最大化占满
 *   视口、移动端自动全屏（useMaximizeModal 既有模式）；
 * - 纯展示、Modal 内不可交互（报告仅为可读性增强，不承载任何机器语义）；
 * - 安全前提：narrative.text 为 AI 生成内容，无注入风险依赖 react-markdown
 *   默认不执行原始 HTML（跳过 raw HTML 节点、链接经 SafeLink 渲染），且共享
 *   映射 markdownComponents（components/markdown-shared）不放行 raw HTML
 *   ——后者不得引入 rehype-raw，否则静默放开 HTML 注入面；
 * - AI 免责声明移入弹窗底部随全文同读（入口按钮窄空间不重复占位）。
 */
export function AlertReportButton({ text }: { text: string }) {
  const [open, setOpen] = useState(false);
  const { modalProps, maximizeButton, isFullscreen } = useMaximizeModal({
    defaultWidth: '80vw',
    defaultBodyHeight: '80vh',
    centered: true,
    extraBodyStyle: { overflowY: 'auto' },
  });
  return (
    <>
      <Button size="small" onClick={() => setOpen(true)}>
        {intlText('components.alert.viewReport')}
      </Button>
      <Modal
        open={open}
        onCancel={() => setOpen(false)}
        footer={null}
        title={<MaximizeTitle text={intlText('components.alert.reportTitle')} isFullscreen={isFullscreen} button={maximizeButton} />}
        {...modalProps}
      >
        <div style={{ fontSize: 13 }}>
          <Markdown remarkPlugins={[remarkGfm]} components={markdownComponents}>
            {text}
          </Markdown>
        </div>
        <Typography.Text type="secondary" style={{ fontSize: 12, display: 'block', marginTop: 12 }}>
          {intlText('components.alert.reportDisclaimer')}
        </Typography.Text>
      </Modal>
    </>
  );
}

// 描述行（code-review item 9e55d00cb91b）：旧实现以嵌套三元链按 variant ×
// 字段有无选形态，违反本项目前端「禁止嵌套三元」规则（比照 SystemPanel.tsx
// renderAdminField 的整改先例），抽模块级 helper 以 if/else 表达。分派结果与
// 原实现逐字一致：page 有描述才独占一行渲染，banner 并入 📌 spec 前缀（两
// 字段均空则不渲染）。仅依赖入参（item+isPage），无组件闭包依赖，故放模块级。
function renderDescriptionLine(item: AlertItem, isPage: boolean): ReactNode {
  if (isPage) {
    if (item.description) return <div>{item.description}</div>;
    return null;
  }
  if (item.spec || item.description) {
    return <div>{item.spec ? `📌 ${item.spec} ` : ''}{item.description}</div>;
  }
  return null;
}

/**
 * 告警明细字段区（描述/叙事/证据/处置/建议/解决依据），六段行单源只写一份，
 * 布局差异按 variant 保留、isPage 仅在真实差异点分支（两变体渲染输出逐字等价）：
 * - 描述行：page 有描述才独占一行渲染，banner 并入 📌 spec 前缀（两字段均空则不渲染）；
 * - 叙事行：仅承载历史终态机械说明（退役前生成失败/熔断跳过的侧车）；
 *   正式调查报告的「查看调查报告」入口在操作按钮列（AlertReportButton +
 *   AlertActionColumn）；调查叙事生成链已退役（consolidate-alerts-to-ops-page
 *   3.3），「调查生成中」占位与 narrative_pending 语义随之移除；
 * - 证据行：page 外包一层 div，banner 直接内联；
 * - 处置/建议：page 文案在 Typography 外作同级文本节点，banner 并入 Typography 内。
 */
export function AlertLines({ item, variant }: { item: AlertItem; variant: AlertSurfaceVariant }) {
  const isPage = variant === 'page';
  const evidenceText = fmtEvidence(item.evidence);
  const resolveNote = item.resolve_note ? (
    <div>
      <Typography.Text type="secondary">{intlText('components.alert.resolveNote', { note: item.resolve_note })}</Typography.Text>
    </div>
  ) : null;
  const descriptionLine = renderDescriptionLine(item, isPage);
  const evidenceLine = evidenceText ? (
    <Typography.Text type="secondary">{intlText('components.alert.evidenceLine', { evidence: evidenceText })}</Typography.Text>
  ) : null;
  return (
    // pre-wrap 保留字段内的 \n / \t 格式（JSON 存储层未丢失，HTML 默认会折叠成空格）
    <div style={{ fontSize: 12, whiteSpace: 'pre-wrap' }}>
      {descriptionLine}
      {item.narrative?.text && !hasNarrativeReport(item) ? (
        // 历史终态机械说明（退役前生成失败/熔断跳过的侧车，sidecar model=null，
        // 一句话）：内联灰字即可，不值得一次弹窗点击。正式调查报告的「查看
        // 调查报告」入口在操作按钮列（AlertReportButton），不在明细区渲染。
        <div data-testid="alert-narrative-failed" style={{ margin: '4px 0' }}>
          <Typography.Text type="secondary" style={{ fontSize: 12 }}>
            {item.narrative.text}
          </Typography.Text>
        </div>
      ) : null}
      {isPage ? (evidenceLine ? <div>{evidenceLine}</div> : null) : evidenceLine}
      {item.action_taken ? (
        <div>
          <Typography.Text type="secondary">{intlText('ops.activity.actionsTaken')}{!isPage && item.action_taken}</Typography.Text>
          {isPage && item.action_taken}
        </div>
      ) : null}
      {item.recommended_action ? (
        <div>
          <Typography.Text type="secondary">{intlText('ops.activity.recommended')}{!isPage && item.recommended_action}</Typography.Text>
          {isPage && item.recommended_action}
        </div>
      ) : null}
      {resolveNote}
    </div>
  );
}
