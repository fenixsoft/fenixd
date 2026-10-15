/**
 * SpecStatusModal.tsx — 「修改状态」弹窗（add-spec-status-modal-budget / spec-status-actions-modal /
 * add-spec-approve-push-modal）。
 *
 * 按当前状态条件渲染五个区块（审批推送/归档/冻结/晋升/预算），走既有后端 API，
 * 零新状态语义。受控 props：project/spec/open/onClose/summary/onDone。
 *
 * 审批推送区块（done 态专用，pushed 不渲染）：确认后写 .fenix/approve_push_request.json
 * 文件信号，daemon 主循环拾取后调 pm_engine.approve_push 执行推送——main 先行+
 * 分支尽力，成功后 SPEC 推进 pushed 终态；失败走既有退避重试，超限升级 push_failed 告警。
 *
 * 冻结态判定：status === 'blocked' && （后端 summary.frozen 为真 || error 以
 * 「用户指令冻结：」开头）。自动冻结（内容完整性闸门 / 预算闸门 / env 阻塞）
 * 只写结构化 frozen 字段 + 自有文案，故 MUST 以后端字段为准——此前只认文本
 * 前缀，三种自动冻结在弹窗里一律显示为「未冻结」，而点击「冻结 SPEC」会经
 * freeze_spec 覆写 error，把预算/环境诊断信息冲掉。预算区块由 nonTerminal
 * 独立控制，与冻结态无关，照常可用。
 */

import {
  Alert,
  App,
  Button,
  DatePicker,
  Divider,
  InputNumber,
  Modal,
  Radio,
  Space,
  Tag,
  Typography,
} from 'antd';
import dayjs from 'dayjs';
import { useCallback, useEffect, useRef, useState } from 'react';
import {
  approveSpecPush,
  archiveSpec,
  freezeSpec,
  promoteSpec,
  reflowSpec,
  setSpecBudget,
  setSpecFreezeConfig,
  activateSpec,
  resumeSpec,
  setSpecStartAfter,
} from '@/services/dashboard';
import type { SpecSummary } from '@/services/dashboard';

/** 存量文本契约回退（结构化 frozen 字段缺席时的兼容路径）。 */
const FREEZE_ERROR_PREFIX = '用户指令冻结：';
const TERMINAL = new Set(['done', 'pushed']);

interface SpecStatusModalProps {
  project: string;
  spec: string;
  open: boolean;
  onClose: () => void;
  summary: SpecSummary | null;
  onDone: () => void;
}

/** 判断 spec 是否处于冻结态（后端单点判定：结构化字段优先，文本前缀回退）。 */
const isFrozen = (summary: SpecSummary | null) =>
  summary?.status === 'blocked' &&
  (summary.frozen === true || (summary.error || '').startsWith(FREEZE_ERROR_PREFIX));

/** 终态判定（done/pushed）。 */
const isTerminal = (summary: SpecSummary | null) =>
  TERMINAL.has(summary?.status || '');

/** task-gap 缺口结论前缀（fix-impl-tasks-completion-gate P1′：回炉区块的渲染判据）。 */
const TASK_GAP_ERROR_PREFIX = 'task-gap:';

/** 预算兜底默认值（summary 字段缺席时的回退，与后端默认一致）。 */
const BUDGET_EFFECTIVE_FALLBACK = 6;
const BUDGET_MAX_FALLBACK = 100;

/** task-gap 拦截滞留判定：status=verified 且 error 以 task-gap: 开头。 */
const isTaskGapStuck = (summary: SpecSummary | null) =>
  summary?.status === 'verified' &&
  (summary.error || '').startsWith(TASK_GAP_ERROR_PREFIX);

export default function SpecStatusModal({
  project,
  spec,
  open,
  onClose,
  summary,
  onDone,
}: SpecStatusModalProps) {
  const { message, modal: appModal } = App.useApp();
  // 各区块按钮的 pending 动作 key（单值：同一时刻弹窗内只有一个确认动作在跑），
  // 按钮按 key 判定自身 loading——此前是单一 loading 被所有区块共用，多个区块
  // 同时渲染（done 态同显审批推送+归档；taskGapStuck/cancelledHold 非终态同显
  // 回炉或恢复+冻结+调度）时点任一按钮会让其余区块按钮一起转圈。
  // 在飞期间其余写动作按钮统一 disabled（code-review item 4011bc5fcc60），使
  // 「同一时刻只有一个确认动作在跑」在 UI 层成立而非仅注释声明。
  const [pendingAction, setPendingAction] = useState<string | null>(null);
  // 预算区状态（预算动作同样走 pendingAction 单值，防与冻结等并发写竞速）
  const [budgetOverride, setBudgetOverride] = useState<number | null>(null);
  // 冻结管理状态
  const [freezeMode, setFreezeMode] = useState<'permanent' | 'scheduled'>('permanent');
  const [freezeUntil, setFreezeUntil] = useState<dayjs.Dayjs | null>(null);
  // 晋升 lint 违规明细（null=无；非 null 时逐条内联渲染在晋升区块）
  const [promoteViolations, setPromoteViolations] = useState<string[] | null>(null);

  const frozen = isFrozen(summary);
  const terminal = isTerminal(summary);
  const drafted = summary?.status === 'drafted';
  const nonTerminal = summary && !terminal;
  // fix-impl-tasks-completion-gate P1′：task-gap 拦截滞留 verified 的可回炉判定
  const taskGapStuck = isTaskGapStuck(summary);
  // add-cancelled-spec-resume-action D4：取消保持态（人工取消 run 的有意等待）
  // 的「恢复运行」区块渲染判据——终态之外才可恢复。
  const cancelledHold = summary?.cancelled_hold === true;

  // 打开时初始化预算覆盖值。仅在 open false→true 的瞬间执行：summary 来自 SSE
  // 增量 patch 的 specMap，弹窗开着期间 frozen_until/budget_override 因后台动作
  // 变化会触发依赖更新，若随依赖重跑初始化会把用户未保存的预算编辑打回服务端
  // 值、并清空正在阅读的晋升 lint 违规明细。
  const prevOpenRef = useRef(false);
  useEffect(() => {
    if (open && !prevOpenRef.current) {
      setBudgetOverride(summary?.budget_override ?? null);
      setPromoteViolations(null);
      // 初始化冻结管理状态
      if (summary?.frozen_until) {
        setFreezeMode('scheduled');
        setFreezeUntil(dayjs(summary.frozen_until));
      } else {
        setFreezeMode('permanent');
        setFreezeUntil(null);
      }
    }
    prevOpenRef.current = open;
  }, [open, summary]);

  // ── 归档（终态 done/pushed） ───────────────────────
  const handleArchive = useCallback(() => {
    if (!summary) return;
    appModal.confirm({
      title: '归档 SPEC',
      content: (
        <div style={{ whiteSpace: 'pre-wrap' }}>
          {`确认归档 SPEC「${summary.name}」？\n\n`}
          将 <Typography.Text code>spec/changes/{summary.name}/</Typography.Text> 移入归档目录
          （<Typography.Text code>archive/YYYY-MM-DD-{summary.name}/</Typography.Text>），STATE.md 条目保留。
          {'\n'}归档后可随时在列表「已归档」视图查看。
        </div>
      ),
      okText: '归档',
      cancelText: '取消',
      onOk: async () => {
        setPendingAction('archive');
        try {
          await archiveSpec(project, spec);
          message.success(`SPEC「${spec}」已归档`);
          onDone();
        } catch (err) {
          message.error(`归档失败：${err instanceof Error ? err.message : String(err)}`);
        } finally {
          setPendingAction(null);
        }
      },
    });
  }, [project, spec, summary, onDone, message, appModal]);

  // ── 冻结（非终态：未冻结→冻结） ────────────────────
  const handleFreeze = useCallback(() => {
    appModal.confirm({
      title: '冻结 SPEC',
      content: (
        <div style={{ whiteSpace: 'pre-wrap' }}>
          {`确认冻结 SPEC「${spec}」？\n\n冻结后 daemon 停止调度该 SPEC，直到手动解冻或切换为定时解冻。`}
        </div>
      ),
      okText: '冻结',
      okButtonProps: { danger: true },
      cancelText: '取消',
      onOk: async () => {
        setPendingAction('freeze');
        try {
          // add-freeze-stop-inflight-agents 6.3：冻结成功后若返回
          // stopped_agents > 0 提示已停止的在跑 agent 计数与续做语义；
          // 为 0 或缺省时不提示（无在跑 agent，交互与现状一致）。
          const result = await freezeSpec(project, spec);
          if (result?.stopped_agents) {
            message.success(
              `SPEC「${spec}」已冻结：已停止 ${result.stopped_agents} 个在跑 agent，进度已留存，解冻后可续做`,
            );
          } else {
            message.success(`SPEC「${spec}」已冻结，daemon 停止调度`);
          }
          onDone();
        } catch (err) {
          message.error(`冻结失败：${err instanceof Error ? err.message : String(err)}`);
        } finally {
          setPendingAction(null);
        }
      },
    });
  }, [project, spec, onDone, message, appModal]);

  // ── 解冻（已冻结→立即解冻） ────────────────────────
  const handleUnfreeze = useCallback(() => {
    appModal.confirm({
      title: '解冻 SPEC',
      content: `确认立即解冻 SPEC「${spec}」？解冻后恢复到冻结前的状态。`,
      okText: '解冻',
      cancelText: '取消',
      onOk: async () => {
        setPendingAction('unfreeze');
        try {
          await setSpecFreezeConfig(project, spec, 'unfreeze');
          message.success(`SPEC「${spec}」已解冻`);
          onDone();
        } catch (err) {
          message.error(`解冻失败：${err instanceof Error ? err.message : String(err)}`);
        } finally {
          setPendingAction(null);
        }
      },
    });
  }, [project, spec, onDone, message, appModal]);

  // ── 切换冻结模式（永久↔定时） ─────────────────────
  const handleFreezeConfig = useCallback(async () => {
    setPendingAction('freeze-config');
    try {
      if (freezeMode === 'scheduled') {
        if (!freezeUntil) {
          message.error('请选择定时解冻时间');
          setPendingAction(null);
          return;
        }
        if (!freezeUntil.isValid()) {
          message.error('解冻时间无效，请重新选择');
          setPendingAction(null);
          return;
        }
        if (freezeUntil.isBefore(dayjs())) {
          message.error('解冻时间不能早于当前时刻，请重新选择');
          setPendingAction(null);
          return;
        }
        await setSpecFreezeConfig(project, spec, 'scheduled', freezeUntil.toISOString());
        message.success('已设置定时解冻，到期 daemon 自动恢复');
      } else {
        await setSpecFreezeConfig(project, spec, 'permanent');
        message.success('已切换为永久冻结（人工解冻）');
      }
      onDone();
    } catch (err) {
      message.error(`操作失败：${err instanceof Error ? err.message : String(err)}`);
    } finally {
      setPendingAction(null);
    }
  }, [project, spec, freezeMode, freezeUntil, onDone, message]);

  // ── 晋升（drafted→ready） ─────────────────────────
  const handlePromote = useCallback(() => {
    appModal.confirm({
      title: '晋升 ready',
      content: (
        <div style={{ whiteSpace: 'pre-wrap' }}>
          {`确认将 SPEC「${spec}」从 drafted 晋升为 ready？\n\n`}
          晋升将执行声明软化与 lint 检查；lint 违规时 SPEC 停留 drafted
          并在 STATE 写入错误明细。
        </div>
      ),
      okText: '晋升',
      cancelText: '取消',
      onOk: async () => {
        setPendingAction('promote');
        try {
          const result = await promoteSpec(project, spec);
          if (result.ok) {
            message.success(`SPEC「${spec}」已晋升 ready，等待调度`);
            onDone();
          } else {
            // lint 违规：SPEC 停留 drafted（STATE 已写入错误明细）。不关闭弹窗，
            // 违规明细逐条内联渲染在晋升区块（Alert 列表），用户可对照 STATE
            // 中的错误定位声明问题后再手动关闭；后端未返回明细时回退展示
            // reason/error。
            setPromoteViolations(
              result.violations?.length
                ? result.violations
                : [result.reason || result.error || '晋升失败（后端未返回违规明细）'],
            );
            message.error('晋升失败：存在 lint 违规，明细见晋升区块');
          }
        } catch (err) {
          message.error(`晋升失败：${err instanceof Error ? err.message : String(err)}`);
        } finally {
          setPendingAction(null);
        }
      },
    });
  }, [project, spec, onDone, message, appModal]);

  // ── 审批推送（done，add-spec-approve-push-modal） ──────────
  // done 态的唯一闭环动作：确认后写 .fenix/approve_push_request.json 文件信号，
  // daemon 主循环（≤2s）拾取并调 pm_engine.approve_push 执行推送（main 先行+
  // 分支尽力、SHA 去重、退避重试、归档收口全部沿用既有语义）；推送成功后 SPEC
  // 推进 pushed 终态。状态非 done（pushed 幂等/其他非法）或 daemon 未运行/
  // 已有进行中信号时后端 403/409，此处展示后端 error 文案。
  const handleApprovePush = useCallback(() => {
    if (!summary) return;
    appModal.confirm({
      title: '审批推送 SPEC',
      content: (
        <div style={{ whiteSpace: 'pre-wrap' }}>
          {`确认审批推送 SPEC「${summary.name}」？\n\n`}
          将由 daemon 执行推送：main 分支先行、feature 分支尽力（远端 origin）。
          成功后 SPEC 推进到 pushed 终态；推送失败走既有退避重试，超限升级
          push_failed 人工告警。
        </div>
      ),
      okText: '审批推送',
      cancelText: '取消',
      onOk: async () => {
        setPendingAction('approve-push');
        try {
          await approveSpecPush(project, spec);
          message.success('已提交推送，daemon 执行中');
          onDone();
        } catch (err) {
          message.error(`审批推送失败：${err instanceof Error ? err.message : String(err)}`);
        } finally {
          setPendingAction(null);
        }
      },
    });
  }, [project, spec, summary, onDone, message, appModal]);

  // ── 回炉（verified + task-gap 错误，fix-impl-tasks-completion-gate P1′） ──
  // task-gap 拦截（verified→done 任务完成度门禁检出未完成任务）滞留 verified 的
  // SPEC 的唯一闭环动作：确认后调用 /api/spec-task-reflow 把 SPEC 复位为 ready，
  // 由 daemon 重新派发实现者承接剩余任务。危险操作（等于用新预算重跑同一件事），
  // 确认文案必须明示「将重新派发实现」。被拒绝（非 task-gap 形态/冻结/幂等重复）
  // 时展示后端返回的拒绝原因，SPEC 状态保持不变。
  const handleReflow = useCallback(() => {
    if (!summary) return;
    const err = summary.error || '';
    const gapNote = err.startsWith(TASK_GAP_ERROR_PREFIX)
      ? `（${err.slice(TASK_GAP_ERROR_PREFIX.length)}）`
      : '';
    appModal.confirm({
      title: '回炉 SPEC（重新派发实现）',
      content: (
        <div style={{ whiteSpace: 'pre-wrap' }}>
          {`确认将 SPEC「${summary.name}」复位为 ready？\n\n`}
          该 SPEC 因任务书未完成被 task-gap 门禁拦截停留在 verified，剩余任务
          仍为未完成状态{gapNote}。
          {'\n'}
          回炉会把 SPEC 复位为 ready 并清空错误，随后 daemon 将重新派发实现者
          承接剩余任务（消耗新的实现尝试预算）。
        </div>
      ),
      okText: '回炉',
      okButtonProps: { danger: true },
      cancelText: '取消',
      onOk: async () => {
        setPendingAction('reflow');
        try {
          const result = await reflowSpec(project, spec);
          if (result.ok) {
            message.success(`SPEC「${spec}」已复位 ready，等待重新派发实现`);
            onDone();
          } else {
            // 被后端拒绝（非 task-gap 形态/冻结/幂等重复等）：展示明确拒绝原因
            const reason = result.reason || result.error || '回炉被拒绝';
            message.error(`回炉被拒绝：${reason}`);
          }
        } catch (err) {
          message.error(`回炉失败：${err instanceof Error ? err.message : String(err)}`);
        } finally {
          setPendingAction(null);
        }
      },
    });
  }, [project, spec, summary, onDone, message, appModal]);

  // ── 恢复运行（取消保持态，add-cancelled-spec-resume-action D4） ──────────
  // 取消保持态（_cancelled_hold: true）是「有意等待」：全部自动恢复链路对其
  // 跳过，本区块是其唯一界面出口。确认后调用 /api/spec-resume 复位 ready：
  // 有保留分支时按保留分支续做（不丢已提交成果），无可保留分支时降级全新重派
  // （degraded=true 独立提示）。恢复=立即派发实现，消耗一次实现尝试预算，
  // 确认文案必须明示。被拒绝（非保持态/冻结/终态）时展示后端拒绝原因。
  const handleResume = useCallback(() => {
    if (!summary) return;
    appModal.confirm({
      title: '恢复运行 SPEC',
      content: (
        <div style={{ whiteSpace: 'pre-wrap' }}>
          {`确认恢复运行 SPEC「${summary.name}」？\n\n`}
          该 SPEC 因 run 被人工取消而挂起等待。恢复将复位为 ready 并即时唤醒派发：
          有保留分支时在保留分支上续做（已提交成果不丢失）；无可保留分支时
          降级为全新重派。
          {'\n'}恢复会消耗一次实现尝试预算。
        </div>
      ),
      okText: '恢复运行',
      okButtonProps: { danger: true },
      cancelText: '取消',
      onOk: async () => {
        setPendingAction('resume');
        try {
          const result = await resumeSpec(project, spec);
          if (result.ok) {
            if (result.degraded) {
              message.warning(
                `SPEC「${spec}」无可保留分支，已降级全新重派：${result.reason || ''}`,
              );
            } else {
              message.success(`SPEC「${spec}」已复位 ready，daemon 将在保留分支上续做`);
            }
            // 即时唤醒信号写出失败：成功/降级两分支均须如实告知
            // （降级消息本身不携带「由下次扫描派发」语义，单独提示）
            if (result.warning) {
              message.warning(result.warning);
            }
            onDone();
          } else {
            message.error(`恢复被拒绝：${result.reason || '该 SPEC 并非取消保持态'}`);
          }
        } catch (err) {
          message.error(`恢复失败：${err instanceof Error ? err.message : String(err)}`);
        } finally {
          setPendingAction(null);
        }
      },
    });
  }, [project, spec, summary, onDone, message, appModal]);

  // ── 预算保存（setSpecBudget） ──────────────────────
  const handleBudgetSave = useCallback(async () => {
    setPendingAction('budget-save');
    try {
      await setSpecBudget(project, spec, budgetOverride);
      message.success(budgetOverride !== null ? '已保存预算覆盖' : '已恢复跟随全局');
      onDone();
    } catch (err) {
      message.error(`保存失败：${err instanceof Error ? err.message : String(err)}`);
    } finally {
      setPendingAction(null);
    }
  }, [project, spec, budgetOverride, onDone, message]);

  const handleBudgetReset = useCallback(async () => {
    setPendingAction('budget-reset');
    try {
      await setSpecBudget(project, spec, null);
      setBudgetOverride(null);
      message.success('已恢复跟随全局');
      onDone();
    } catch (err) {
      message.error(`操作失败：${err instanceof Error ? err.message : String(err)}`);
    } finally {
      setPendingAction(null);
    }
  }, [project, spec, onDone, message]);

  // ── 调度区：手工激活 / 激活（add-spec-manual-activation D10） ──────────
  const isManualPending = summary?.start_after === 'manual';

  const handleActivate = useCallback(() => {
    appModal.confirm({
      title: '激活 SPEC',
      content: (
        <div style={{ whiteSpace: 'pre-wrap' }}>
          {`确认激活 SPEC「${spec}」？\n\n`}
          激活后 start_after 由 manual 置为 null，daemon 将立即拾取并进入调度。
        </div>
      ),
      okText: '激活',
      okButtonProps: { type: 'primary' },
      cancelText: '取消',
      onOk: async () => {
        setPendingAction('activate');
        try {
          const result = await activateSpec(project, spec);
          if (result.ok) {
            // fix-scheduling-kick-single-slot D3：激活成功但即时唤醒信号写出失败时
            // 如实告知（MUST NOT 无条件宣称「daemon 将立即拾取」）
            if (result.warning) {
              message.warning(result.warning);
            } else {
              message.success(`SPEC「${spec}」已激活，daemon 将立即拾取`);
            }
            onDone();
          } else {
            message.error(`激活被拒绝：${result.reason || '该 SPEC 并非待激活态'}`);
          }
        } catch (err) {
          message.error(`激活失败：${err instanceof Error ? err.message : String(err)}`);
        } finally {
          setPendingAction(null);
        }
      },
    });
  }, [project, spec, onDone, message, appModal]);

  const handleSetManual = useCallback(() => {
    appModal.confirm({
      title: '设为待激活',
      content: (
        <div style={{ whiteSpace: 'pre-wrap' }}>
          {`确认将 SPEC「${spec}」设为待激活？\n\n`}
          设为待激活后 start_after 为 manual，daemon 停止自动调度该 SPEC，
          直到在 Dashboard「修改状态」弹窗或 CLI 手动激活。
        </div>
      ),
      okText: '设为待激活',
      cancelText: '取消',
      onOk: async () => {
        setPendingAction('set-manual');
        try {
          await setSpecStartAfter(project, spec, 'manual');
          message.success(`SPEC「${spec}」已设为待激活，daemon 停止自动调度`);
          onDone();
        } catch (err) {
          message.error(`操作失败：${err instanceof Error ? err.message : String(err)}`);
        } finally {
          setPendingAction(null);
        }
      },
    });
  }, [project, spec, onDone, message, appModal]);

  // Modal 常挂载（code-review item 4dec1650864f）：关闭只交给 open prop，让 antd
  // 走标准关闭流程播放淡出动画（与 SpecDocModal 一致）。summary 为空时各区块
  // 均按状态条件渲染（不应出现，菜单入口按状态屏蔽），无空转副作用；内部状态
  // 由 destroyOnHidden 清理。
  return (
    <Modal
      title={`修改状态 · ${spec}`}
      open={open}
      onCancel={onClose}
      footer={null}
      destroyOnHidden
      width={520}
    >
      <Space direction="vertical" style={{ width: '100%' }} size={0}>
        {/* ── 审批推送区块（done 专用，pushed 不渲染；add-spec-approve-push-modal D5：
            done 态首要意图是审批推送（闭环动作），故置于归档区块之前） ── */}
        {summary?.status === 'done' && (
          <div style={{ marginBottom: 16 }}>
            <Typography.Text strong style={{ fontSize: 14 }}>审批推送</Typography.Text>
            <Typography.Paragraph type="secondary" style={{ margin: '4px 0 8px' }}>
              审批后由 daemon 执行推送：main 分支先行、feature 分支尽力（远端 origin）。
              成功后 SPEC 推进到 pushed 终态；推送失败走既有退避重试，超限升级 push_failed 人工告警。
            </Typography.Paragraph>
            <Button
              type="primary"
              onClick={handleApprovePush}
              loading={pendingAction === 'approve-push'}
              disabled={pendingAction !== null && pendingAction !== 'approve-push'}
            >
              审批推送
            </Button>
          </div>
        )}

        {/* ── 恢复运行区块（取消保持态非终态；add-cancelled-spec-resume-action D4） ── */}
        {cancelledHold && nonTerminal && (
          <div style={{ marginBottom: 16 }}>
            <Typography.Text strong style={{ fontSize: 14 }}>恢复运行</Typography.Text>
            <Typography.Paragraph type="secondary" style={{ margin: '4px 0 8px' }}>
              该 SPEC 因 run 被人工取消而处于取消保持态，daemon 全部自动恢复链路
              对其跳过，需显式恢复。恢复将复位为 ready 并即时唤醒派发：有保留
              分支时在保留分支上续做（已提交成果不丢失）；无可保留分支时降级为
              全新重派。恢复会消耗一次实现尝试预算。
            </Typography.Paragraph>
            <Button
              danger
              onClick={handleResume}
              loading={pendingAction === 'resume'}
              disabled={pendingAction !== null && pendingAction !== 'resume'}
            >
              恢复运行
            </Button>
          </div>
        )}

        {/* ── 回炉区块（verified + task-gap 错误；fix-impl-tasks-completion-gate P1′） ── */}
        {/* summary 空值守卫为类型收窄所需（taskGapStuck 派生自 summary，语义等价） */}
        {taskGapStuck && summary && (
          <div style={{ marginBottom: 16 }}>
            <Typography.Text strong style={{ fontSize: 14 }}>回炉（重新派发实现）</Typography.Text>
            <Typography.Paragraph type="secondary" style={{ margin: '4px 0 8px' }}>
              该 SPEC 因任务书存在未完成任务被 task-gap 门禁拦截，停留在 verified
              无法自动推进。回炉将复位为 ready 并由 daemon 重新派发实现者承接剩余
              任务（缺口任务仍为未完成状态，将消耗新的实现尝试预算）。
            </Typography.Paragraph>
            {summary.error && (
              <Typography.Paragraph type="secondary" style={{ margin: '0 0 8px', fontSize: 12 }}>
                缺口结论：{summary.error}
              </Typography.Paragraph>
            )}
            <Button
              danger
              onClick={handleReflow}
              loading={pendingAction === 'reflow'}
              disabled={pendingAction !== null && pendingAction !== 'reflow'}
            >
              回炉并重新派发实现
            </Button>
          </div>
        )}

        {/* ── 归档区块（终态 done/pushed） ─────────────── */}
        {terminal && (
          <div style={{ marginBottom: 16 }}>
            <Typography.Text strong style={{ fontSize: 14 }}>归档</Typography.Text>
            <Typography.Paragraph type="secondary" style={{ margin: '4px 0 8px' }}>
              将目录移入 archive/YYYY-MM-DD-{spec}/，STATE.md 条目保留。归档后可在「已归档」视图查看。
            </Typography.Paragraph>
            <Button
              onClick={handleArchive}
              loading={pendingAction === 'archive'}
              disabled={pendingAction !== null && pendingAction !== 'archive'}
            >
              归档 SPEC
            </Button>
          </div>
        )}

        {/* ── 冻结区块（非终态） ─────────────────────── */}
        {nonTerminal && (
          <div style={{ marginBottom: 16 }}>
            <Divider style={{ margin: '4px 0 12px' }} />
            <Typography.Text strong style={{ fontSize: 14 }}>冻结</Typography.Text>
            {!frozen ? (
              <>
                <Typography.Paragraph type="secondary" style={{ margin: '4px 0 8px' }}>
                  未冻结。冻结后 daemon 停止调度该 SPEC，直到手动解冻。
                </Typography.Paragraph>
                <Button
                  danger
                  onClick={handleFreeze}
                  loading={pendingAction === 'freeze'}
                  disabled={pendingAction !== null && pendingAction !== 'freeze'}
                >
                  冻结 SPEC
                </Button>
              </>
            ) : (
              <>
                <div style={{ margin: '4px 0 8px' }}>
                  <Space size={4}>
                    <Typography.Text type="secondary">模式：</Typography.Text>
                    <Tag color={summary.frozen_until ? 'blue' : 'default'}>
                      {summary.frozen_until ? '定时解冻' : '永久冻结（人工解冻）'}
                    </Tag>
                  </Space>
                </div>
                {summary.frozen_until && (
                  <Typography.Paragraph type="secondary" style={{ margin: '0 0 8px', fontSize: 12 }}>
                    目标时间：{dayjs(summary.frozen_until).format('YYYY-MM-DD HH:mm')}
                    （本地），到期 daemon 自动解冻
                  </Typography.Paragraph>
                )}
                {summary.error && (
                  <Typography.Paragraph type="secondary" style={{ margin: '0 0 8px', fontSize: 12 }}>
                    冻结原因：{summary.error}
                  </Typography.Paragraph>
                )}
                <Space direction="vertical" style={{ width: '100%' }} size={8}>
                  <Space>
                    <Button
                      danger
                      onClick={handleUnfreeze}
                      loading={pendingAction === 'unfreeze'}
                      disabled={pendingAction !== null && pendingAction !== 'unfreeze'}
                    >
                      立即解冻
                    </Button>
                  </Space>
                  <Radio.Group
                    value={freezeMode}
                    onChange={(e) => setFreezeMode(e.target.value as 'permanent' | 'scheduled')}
                    options={[
                      { label: '永久冻结', value: 'permanent' },
                      { label: '定时解冻', value: 'scheduled' },
                    ]}
                  />
                  {freezeMode === 'scheduled' && (
                    <Space>
                      <DatePicker
                        showTime
                        style={{ width: 260 }}
                        value={freezeUntil}
                        onChange={(d) => setFreezeUntil(d)}
                        placeholder="选择自动解冻时间"
                      />
                      <Button
                        type="primary"
                        onClick={() => void handleFreezeConfig()}
                        loading={pendingAction === 'freeze-config'}
                        disabled={pendingAction !== null && pendingAction !== 'freeze-config'}
                      >
                        应用
                      </Button>
                    </Space>
                  )}
                  {freezeMode === 'permanent' && summary.frozen_until && (
                    <Button
                      onClick={() => void handleFreezeConfig()}
                      loading={pendingAction === 'freeze-config'}
                      disabled={pendingAction !== null && pendingAction !== 'freeze-config'}
                    >
                      切换为永久冻结
                    </Button>
                  )}
                </Space>
              </>
            )}
          </div>
        )}

        {/* ── 调度区块（非终态，add-spec-manual-activation D10）──
            D10 原限定 status==='ready'——reviewing 态诞生（add-spec-review-gate）且
            start_after 门下沉 drafted/reviewing 派发口（fix-start-after-premature-pickup）
            后，manual 哨兵可合法存在于任意非终态；后端 activate/start-after 本就只拒
            终态（admin_actions.py），故放宽为 nonTerminal 对齐后端契约（2026-09-22 热修）。 */}
        {nonTerminal && (
          <div style={{ marginBottom: 16 }}>
            <Divider style={{ margin: '4px 0 12px' }} />
            <Typography.Text strong style={{ fontSize: 14 }}>调度</Typography.Text>
            {isManualPending ? (
              <>
                <Typography.Paragraph type="secondary" style={{ margin: '4px 0 8px' }}>
                  该 SPEC 当前为待激活态（start_after: manual），daemon 不会自动调度。
                </Typography.Paragraph>
                <Button
                  type="primary"
                  onClick={handleActivate}
                  loading={pendingAction === 'activate'}
                  disabled={pendingAction !== null && pendingAction !== 'activate'}
                >
                  激活（立即调度）
                </Button>
              </>
            ) : (
              <>
                <Typography.Paragraph type="secondary" style={{ margin: '4px 0 8px' }}>
                  将 start_after 设为 manual，daemon 停止自动调度，直到手动激活。
                  不影响正在执行的 run（与冻结一致，只挡后续派发）。
                </Typography.Paragraph>
                <Button
                  onClick={handleSetManual}
                  loading={pendingAction === 'set-manual'}
                  disabled={pendingAction !== null && pendingAction !== 'set-manual'}
                >
                  设为待激活
                </Button>
              </>
            )}
          </div>
        )}

        {/* ── 晋升区块（drafted） ───────────────────── */}
        {drafted && (
          <div style={{ marginBottom: 16 }}>
            <Divider style={{ margin: '4px 0 12px' }} />
            <Typography.Text strong style={{ fontSize: 14 }}>晋升</Typography.Text>
            <Typography.Paragraph type="secondary" style={{ margin: '4px 0 8px' }}>
              将 SPEC 从 drafted 晋升为 ready。晋升将执行声明软化与 lint 检查；lint 违规时 SPEC 停留 drafted 并在 STATE 写入错误明细。
            </Typography.Paragraph>
            {promoteViolations !== null && (
              <Alert
                type="error"
                showIcon
                style={{ marginBottom: 8 }}
                message="晋升被 lint 拦截（SPEC 停留 drafted），违规明细："
                description={
                  <div style={{ maxHeight: 220, overflowY: 'auto' }}>
                    {promoteViolations.map((v, i) => (
                      <Typography.Paragraph
                        key={i}
                        style={{ margin: '0 0 4px', fontSize: 12, whiteSpace: 'pre-wrap', wordBreak: 'break-all' }}
                      >
                        {`${i + 1}. ${v}`}
                      </Typography.Paragraph>
                    ))}
                  </div>
                }
              />
            )}
            <Button
              onClick={handlePromote}
              loading={pendingAction === 'promote'}
              disabled={pendingAction !== null && pendingAction !== 'promote'}
            >
              晋升 ready
            </Button>
          </div>
        )}

        {/* ── 预算区块（非终态） ───────────────────── */}
        {nonTerminal && (
          <div>
            <Divider style={{ margin: '4px 0 12px' }} />
            <Typography.Text strong style={{ fontSize: 14 }}>实现尝试预算</Typography.Text>
            <div style={{ margin: '4px 0 8px' }}>
              <Typography.Text>
                已用 <Typography.Text strong>{summary.budget_used ?? 0}</Typography.Text>
                {' / 有效预算 '}
                <Typography.Text strong>{summary.budget_effective ?? BUDGET_EFFECTIVE_FALLBACK}</Typography.Text>
              </Typography.Text>
            </div>
            <Space direction="vertical" style={{ width: '100%' }} size={8}>
              <div>
                <Typography.Text type="secondary" style={{ display: 'block', marginBottom: 4, fontSize: 12 }}>
                  覆盖值（1-{summary.budget_max ?? BUDGET_MAX_FALLBACK}，null=跟随全局当前 {summary.budget_effective ?? BUDGET_EFFECTIVE_FALLBACK}）
                </Typography.Text>
                <InputNumber
                  min={1}
                  max={summary.budget_max ?? BUDGET_MAX_FALLBACK}
                  step={1}
                  style={{ width: 120 }}
                  value={budgetOverride}
                  onChange={(v) => setBudgetOverride(v)}
                  placeholder="跟随全局"
                />
              </div>
              <Space>
                <Button
                  type="primary"
                  onClick={() => void handleBudgetSave()}
                  loading={pendingAction === 'budget-save'}
                  disabled={pendingAction !== null && pendingAction !== 'budget-save'}
                >
                  保存
                </Button>
                <Button
                  onClick={() => void handleBudgetReset()}
                  disabled={budgetOverride === null || (pendingAction !== null && pendingAction !== 'budget-reset')}
                  loading={pendingAction === 'budget-reset'}
                >
                  恢复跟随全局
                </Button>
              </Space>
            </Space>
          </div>
        )}
      </Space>
    </Modal>
  );
}
