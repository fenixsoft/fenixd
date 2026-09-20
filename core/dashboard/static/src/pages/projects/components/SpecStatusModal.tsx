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
import { useCallback, useEffect, useState } from 'react';
import {
  approveSpecPush,
  archiveSpec,
  freezeSpec,
  promoteSpec,
  reflowSpec,
  setSpecBudget,
  setSpecFreezeConfig,
  activateSpec,
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
  const [loading, setLoading] = useState(false);
  // 预算区状态
  const [budgetOverride, setBudgetOverride] = useState<number | null>(null);
  const [budgetSaving, setBudgetSaving] = useState(false);
  // 冻结管理状态
  const [freezeMode, setFreezeMode] = useState<'permanent' | 'scheduled'>('permanent');
  const [freezeUntil, setFreezeUntil] = useState<dayjs.Dayjs | null>(null);

  const frozen = isFrozen(summary);
  const terminal = isTerminal(summary);
  const done = summary?.status === 'done' || summary?.status === 'pushed';
  const drafted = summary?.status === 'drafted';
  const nonTerminal = summary && !terminal;
  // fix-impl-tasks-completion-gate P1′：task-gap 拦截滞留 verified 的可回炉判定
  const taskGapStuck = isTaskGapStuck(summary);

  // 打开时初始化预算覆盖值
  useEffect(() => {
    if (!open) return;
    setBudgetOverride(summary?.budget_override ?? null);
    // 初始化冻结管理状态
    if (summary?.frozen_until) {
      setFreezeMode('scheduled');
      setFreezeUntil(dayjs(summary.frozen_until));
    } else {
      setFreezeMode('permanent');
      setFreezeUntil(null);
    }
  }, [open, summary?.budget_override, summary?.frozen_until]);

  // ── 归档（终态 done/pushed） ───────────────────────
  const handleArchive = useCallback(() => {
    if (!summary) return;
    appModal.confirm({
      title: '归档 SPEC',
      content: (
        <div style={{ whiteSpace: 'pre-wrap' }}>
          {`确认归档 SPEC「${summary.name}」？\n\n`}
          将 `spec/changes/{summary.name}/` 移入归档目录
          （archive/YYYY-MM-DD-{summary.name}/），STATE.md 条目保留。
          {'\n'}归档后可随时在列表「已归档」视图查看。
        </div>
      ),
      okText: '归档',
      cancelText: '取消',
      onOk: async () => {
        setLoading(true);
        try {
          await archiveSpec(project, spec);
          message.success(`SPEC「${spec}」已归档`);
          onDone();
        } catch (err) {
          message.error(`归档失败：${err instanceof Error ? err.message : String(err)}`);
        } finally {
          setLoading(false);
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
        setLoading(true);
        try {
          await freezeSpec(project, spec);
          message.success(`SPEC「${spec}」已冻结，daemon 停止调度`);
          onDone();
        } catch (err) {
          message.error(`冻结失败：${err instanceof Error ? err.message : String(err)}`);
        } finally {
          setLoading(false);
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
        setLoading(true);
        try {
          await setSpecFreezeConfig(project, spec, 'unfreeze');
          message.success(`SPEC「${spec}」已解冻`);
          onDone();
        } catch (err) {
          message.error(`解冻失败：${err instanceof Error ? err.message : String(err)}`);
        } finally {
          setLoading(false);
        }
      },
    });
  }, [project, spec, onDone, message, appModal]);

  // ── 切换冻结模式（永久↔定时） ─────────────────────
  const handleFreezeConfig = useCallback(async () => {
    setLoading(true);
    try {
      if (freezeMode === 'scheduled') {
        if (!freezeUntil) {
          message.error('请选择定时解冻时间');
          setLoading(false);
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
      setLoading(false);
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
        setLoading(true);
        try {
          const result = await promoteSpec(project, spec);
          if (result.ok) {
            message.success(`SPEC「${spec}」已晋升 ready，等待调度`);
            onDone();
          } else {
            // lint 违规：关闭弹窗并在页面展示违规明细（SPEC 停留 drafted）
            const detail = result.violations?.join('；') || result.reason || result.error || '晋升失败';
            message.error(`晋升失败：${detail}`);
            onClose();
            onDone();
          }
        } catch (err) {
          message.error(`晋升失败：${err instanceof Error ? err.message : String(err)}`);
        } finally {
          setLoading(false);
        }
      },
    });
  }, [project, spec, onDone, message, appModal, onClose]);

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
        setLoading(true);
        try {
          await approveSpecPush(project, spec);
          message.success('已提交推送，daemon 执行中');
          onDone();
        } catch (err) {
          message.error(`审批推送失败：${err instanceof Error ? err.message : String(err)}`);
        } finally {
          setLoading(false);
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
        setLoading(true);
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
          setLoading(false);
        }
      },
    });
  }, [project, spec, summary, onDone, message, appModal]);

  // ── 预算保存（setSpecBudget） ──────────────────────
  const handleBudgetSave = useCallback(async () => {
    setLoading(true);
    setBudgetSaving(true);
    try {
      await setSpecBudget(project, spec, budgetOverride);
      message.success(budgetOverride !== null ? '已保存预算覆盖' : '已恢复跟随全局');
      onDone();
    } catch (err) {
      message.error(`保存失败：${err instanceof Error ? err.message : String(err)}`);
    } finally {
      setLoading(false);
      setBudgetSaving(false);
    }
  }, [project, spec, budgetOverride, onDone, message]);

  const handleBudgetReset = useCallback(async () => {
    setLoading(true);
    setBudgetSaving(true);
    try {
      await setSpecBudget(project, spec, null);
      setBudgetOverride(null);
      message.success('已恢复跟随全局');
      onDone();
    } catch (err) {
      message.error(`操作失败：${err instanceof Error ? err.message : String(err)}`);
    } finally {
      setLoading(false);
      setBudgetSaving(false);
    }
  }, [project, spec, onDone, message]);

  // ── 调度区：手工激活 / 激活（add-spec-manual-activation D10） ──────────
  const isManualPending = summary?.start_after === 'manual';
  const isReady = summary?.status === 'ready';

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
        setLoading(true);
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
          setLoading(false);
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
        setLoading(true);
        try {
          await setSpecStartAfter(project, spec, 'manual');
          message.success(`SPEC「${spec}」已设为待激活，daemon 停止自动调度`);
          onDone();
        } catch (err) {
          message.error(`操作失败：${err instanceof Error ? err.message : String(err)}`);
        } finally {
          setLoading(false);
        }
      },
    });
  }, [project, spec, onDone, message, appModal]);

  // 按状态无可用区块时直接返回 null（不应出现，菜单入口按状态屏蔽）
  if (!summary || open === false) return null;

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
              loading={loading}
            >
              审批推送
            </Button>
          </div>
        )}

        {/* ── 回炉区块（verified + task-gap 错误；fix-impl-tasks-completion-gate P1′） ── */}
        {taskGapStuck && (
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
            <Button danger onClick={handleReflow} loading={loading}>
              回炉并重新派发实现
            </Button>
          </div>
        )}

        {/* ── 归档区块（终态 done/pushed） ─────────────── */}
        {done && (
          <div style={{ marginBottom: 16 }}>
            <Typography.Text strong style={{ fontSize: 14 }}>归档</Typography.Text>
            <Typography.Paragraph type="secondary" style={{ margin: '4px 0 8px' }}>
              将目录移入 archive/YYYY-MM-DD-{spec}/，STATE.md 条目保留。归档后可在「已归档」视图查看。
            </Typography.Paragraph>
            <Button
              onClick={handleArchive}
              loading={loading}
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
                <Button danger onClick={handleFreeze} loading={loading}>
                  冻结 SPEC
                </Button>
              </>
            ) : (
              <>
                <div style={{ margin: '4px 0 8px' }}>
                  <Space size={4}>
                    <Typography.Text type="secondary">模式：</Typography.Text>
                    <Tag color={freezeMode === 'scheduled' ? 'blue' : 'default'}>
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
                    <Button danger onClick={handleUnfreeze} loading={loading}>
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
                      <Button type="primary" onClick={() => void handleFreezeConfig()} loading={loading}>
                        应用
                      </Button>
                    </Space>
                  )}
                  {freezeMode === 'permanent' && summary.frozen_until && (
                    <Button onClick={() => void handleFreezeConfig()} loading={loading}>
                      切换为永久冻结
                    </Button>
                  )}
                </Space>
              </>
            )}
          </div>
        )}

        {/* ── 调度区块（非终态，add-spec-manual-activation D10）── */}
        {nonTerminal && isReady && (
          <div style={{ marginBottom: 16 }}>
            <Divider style={{ margin: '4px 0 12px' }} />
            <Typography.Text strong style={{ fontSize: 14 }}>调度</Typography.Text>
            {isManualPending ? (
              <>
                <Typography.Paragraph type="secondary" style={{ margin: '4px 0 8px' }}>
                  该 SPEC 当前为待激活态（start_after: manual），daemon 不会自动调度。
                </Typography.Paragraph>
                <Button type="primary" onClick={handleActivate} loading={loading}>
                  激活（立即调度）
                </Button>
              </>
            ) : (
              <>
                <Typography.Paragraph type="secondary" style={{ margin: '4px 0 8px' }}>
                  将 start_after 设为 manual，daemon 停止自动调度，直到手动激活。
                </Typography.Paragraph>
                <Button onClick={handleSetManual} loading={loading}>
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
            <Button onClick={handlePromote} loading={loading}>
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
                <Typography.Text strong>{summary.budget_effective ?? 6}</Typography.Text>
              </Typography.Text>
            </div>
            <Space direction="vertical" style={{ width: '100%' }} size={8}>
              <div>
                <Typography.Text type="secondary" style={{ display: 'block', marginBottom: 4, fontSize: 12 }}>
                  覆盖值（1-{summary.budget_max ?? 100}，null=跟随全局当前 {summary.budget_effective ?? 6}）
                </Typography.Text>
                <InputNumber
                  min={1}
                  max={summary.budget_max ?? 100}
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
                  loading={budgetSaving}
                >
                  保存
                </Button>
                <Button
                  onClick={() => void handleBudgetReset()}
                  disabled={budgetOverride === null}
                  loading={budgetSaving}
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
