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
 * 冻结态判定：status === 'blocked' && error.startsWith('用户指令冻结：')，
 * 与 list.tsx isFrozen 同源。非冻结 blocked（如预算耗尽冻结）在冻结区显示
 * 「冻结」操作（幂等 no-op）且预算区照常可用——预算耗尽冻结正是本能力的主要场景。
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
  setSpecBudget,
  setSpecFreezeConfig,
} from '@/services/dashboard';
import type { SpecSummary } from '@/services/dashboard';

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

/** 判断 spec 是否处于人工冻结态（error 以冻结前缀开头）。 */
const isFrozen = (summary: SpecSummary | null) =>
  summary?.status === 'blocked' &&
  (summary.error || '').startsWith(FREEZE_ERROR_PREFIX);

/** 终态判定（done/pushed）。 */
const isTerminal = (summary: SpecSummary | null) =>
  TERMINAL.has(summary?.status || '');

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
                  覆盖值（1-10，null=跟随全局当前 {summary.budget_effective ?? 6}）
                </Typography.Text>
                <InputNumber
                  min={1}
                  max={10}
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
