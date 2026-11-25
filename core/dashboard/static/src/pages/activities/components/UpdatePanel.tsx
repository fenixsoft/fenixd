import { App, Alert, Button, Card, Descriptions, Space, Spin, Tag, Timeline, Typography } from 'antd';
import dayjs from 'dayjs';
import { useCallback, useEffect, useRef, useState } from 'react';
import { useIntl } from '@umijs/max';
import {
  ApiError,
  applyUpdate,
  checkUpdate,
  getUpdateStatus,
} from '@/services/dashboard';
import type {
  UpdateApplyState,
  UpdateStatusData,
  UpdateTargetStatus,
} from '@/services/dashboard';
// 文案经 useIntl/getIntl（i18n 修复轮 batch-A：本文件静态中文文案迁 i18n 目录）
import { intlText } from '@/utils/intlText.ts';

// 轮询间隔：常态 30s（对齐 ChainPanel 节拍）；apply 编排进行中加速 2s，
// 让阶段推进（下载/校验/停起/换装）近实时可见
const REFRESH_MS = 30000;
const APPLY_REFRESH_MS = 2000;

// 形态标识（spec：artifact 可一键更新；source 显示 git pull 指引、无更新按钮）
const FORM_META: Record<string, { label: string; color: string }> = {
  get artifact() { return { label: intlText('ops.update.form.artifact'), color: 'blue' }; },
  get source() { return { label: intlText('ops.update.form.source'), color: 'purple' }; },
  get unknown() { return { label: intlText('ops.update.form.unknown'), color: 'default' }; },
};

function formTag(form?: string | null) {
  if (!form) return null;
  const meta = FORM_META[form] ?? FORM_META.unknown;
  return <Tag color={meta.color}>{meta.label}</Tag>;
}

function availabilityTag(target?: UpdateTargetStatus | null) {
  if (!target) return null;
  if (target.form === 'source') return null; // 源码形态无可更新判定
  if (!target.remote_version) return null;
  return target.update_available
    ? <Tag color="orange">{intlText('ops.update.avail.updateable', { version: target.remote_version })}</Tag>
    : <Tag color="green">{intlText('ops.update.avail.latest')}</Tag>;
}

function fmtTs(v?: string | null) {
  if (!v) return '—';
  const d = dayjs(v);
  return d.isValid() ? d.format('YYYY-MM-DD HH:mm:ss') : v;
}

/** 更新卡页签（add-auto-update 3.2）：框架/插件版本、检查与应用编排状态、
 *  「立即检查」「一键更新」两动作。半自动边界：检查自动、应用 MUST 经
 *  Modal.confirm 用户确认后触发（spec 更新状态展示 Requirement）。 */
export default function UpdatePanel({ isMobile }: { isMobile?: boolean }) {
  const { message, modal } = App.useApp();
  const intl = useIntl();
  const [data, setData] = useState<UpdateStatusData | null>(null);
  const [loading, setLoading] = useState(true);
  const [checking, setChecking] = useState(false);
  const [applying, setApplying] = useState(false);
  // apply 进行中期的加速轮询标记（phase 落终态后回到常态节拍）
  const applyActive =
    data?.apply?.phase === 'queued' || data?.apply?.phase === 'running';

  const load = useCallback(async () => {
    try {
      const st = await getUpdateStatus();
      setData(st);
    } catch {
      // 轮询失败静默保留旧数据（下次轮询自愈）；首载失败展示空态提示
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
    const timer = setInterval(() => void load(), applyActive ? APPLY_REFRESH_MS : REFRESH_MS);
    return () => clearInterval(timer);
  }, [load, applyActive]);

  const handleCheck = useCallback(async () => {
    setChecking(true);
    try {
      const res = await checkUpdate();
      setData(res.status);
      if (res.ok) {
        message.success(intl.formatMessage({ id: 'ops.update.checkDone' }));
      } else {
        message.warning(intl.formatMessage({ id: 'ops.update.checkFailed' }, { reason: res.error ?? intl.formatMessage({ id: 'ops.update.unknownReason' }) }));
      }
    } catch (e) {
      message.error(intl.formatMessage({ id: 'ops.update.checkRequestFailed' }, { reason: e instanceof ApiError ? e.message : intl.formatMessage({ id: 'ops.update.networkError' }) }));
    } finally {
      setChecking(false);
    }
  }, [intl, message]);

  const handleApply = useCallback(() => {
    modal.confirm({
      title: intl.formatMessage({ id: 'ops.update.confirmTitle' }),
      content: (
        <>
          {intl.formatMessage({ id: 'ops.update.confirmBody' })}
        </>
      ),
      okText: intl.formatMessage({ id: 'ops.update.startUpdate' }),
      cancelText: intl.formatMessage({ id: 'common.cancel' }),
      onOk: async () => {
        setApplying(true);
        try {
          await applyUpdate();
          message.success(intl.formatMessage({ id: 'ops.update.acceptQueued' }));
          await load();
        } catch (e) {
          if (e instanceof ApiError && e.code === 'update-locked') {
            message.warning(intl.formatMessage({ id: 'ops.update.alreadyRunning' }));
          } else {
            message.error(intl.formatMessage({ id: 'ops.update.acceptFailed' }, { reason: e instanceof ApiError ? e.message : intl.formatMessage({ id: 'ops.update.networkError' }) }));
          }
        } finally {
          setApplying(false);
        }
      },
    });
  }, [intl, modal, message, load]);

  if (loading && !data) {
    return (
      <div style={{ textAlign: 'center', padding: 48 }}>
        <Spin size="large" />
      </div>
    );
  }

  const fw = data?.framework ?? null;
  const plugins = data?.plugins ?? null;
  const apply = data?.apply ?? null;
  const canApply = Boolean(
    fw?.form === 'artifact' && fw.update_available && !applyActive,
  );

  const renderApplyState = (a: UpdateApplyState | null | undefined) => {
    if (!a || a.phase === 'idle') return null;
    if (a.phase === 'success') {
      return (
        <Alert
          type="success"
          showIcon
          message={intl.formatMessage({ id: 'ops.update.done' }, { version: a.version ?? '' })}
          description={
            <>
              <div>{intl.formatMessage({ id: 'ops.update.rollbackKept' }, { dir: a.old_dir ? String(a.old_dir).split('/').pop() : '' })}</div>
              {a.plugins?.status === 'success' && (
                <div>{intl.formatMessage({ id: 'ops.update.pluginsUpdated' }, { version: a.plugins.version })}</div>
              )}
              {a.plugins?.status === 'skipped' && <div>{a.plugins.detail}</div>}
              {a.plugins_error && (
                <div style={{ color: '#cf1322' }}>{intl.formatMessage({ id: 'ops.update.pluginsFailed' }, { err: a.plugins_error })}</div>
              )}
              <Typography.Text type="warning">
                {intl.formatMessage({ id: 'ops.update.refreshHint' })}
              </Typography.Text>
            </>
          }
          style={{ marginTop: 16 }}
        />
      );
    }
    if (a.phase === 'failed') {
      return (
        <Alert
          type="error"
          showIcon
          message={a.failed_stage
            ? intl.formatMessage({ id: 'ops.update.applyFailedStage' }, { stage: a.failed_stage })
            : intl.formatMessage({ id: 'ops.update.applyFailed' })}
          description={
            <>
              <div>{a.error}</div>
              {a.rollback && (
                <div>
                  {a.rollback_restored
                    ? intl.formatMessage({ id: 'ops.update.rollbackDone' })
                    : intl.formatMessage({ id: 'ops.update.rollbackIncomplete' })}
                </div>
              )}
              {a.plugins_error && <div>{intl.formatMessage({ id: 'ops.update.pluginsSide' }, { err: a.plugins_error })}</div>}
            </>
          }
          style={{ marginTop: 16 }}
        />
      );
    }
    // queued / running：阶段进度
    return (
      <Card size="small" style={{ marginTop: 16 }} title={
        <Space><Spin size="small" />{intl.formatMessage({ id: 'ops.update.running' }, { phase: intl.formatMessage({ id: a.phase === 'queued' ? 'ops.update.phase.queued' : 'ops.update.phase.running' }) })}</Space>
      }>
        <Timeline
          items={(a.stages ?? []).map((s) => ({
            color: s.ok ? 'green' : 'red',
            children: (
              <>
                <Typography.Text strong>{s.stage}</Typography.Text>
                {s.detail && (
                  <Typography.Paragraph type="secondary" style={{ marginBottom: 0 }} ellipsis>
                    {s.detail}
                  </Typography.Paragraph>
                )}
              </>
            ),
          }))}
        />
      </Card>
    );
  };

  return (
    <div data-testid="update-panel">
      {!data?.checked ? (
        <Alert
          type="info"
          showIcon
          message={intl.formatMessage({ id: 'ops.update.neverChecked' })}
          description={intl.formatMessage({ id: 'ops.update.neverCheckedHint' })}
          style={{ marginBottom: 16 }}
        />
      ) : null}
      {fw?.form === 'source' ? (
        <Alert
          type="info"
          showIcon
          message={intl.formatMessage({ id: 'ops.update.sourceFormBanner' })}
          description={intl.formatMessage({ id: 'ops.update.sourceFormHint' })}
          style={{ marginBottom: 16 }}
        />
      ) : null}
      {data?.last_error ? (
        <Alert
          type="warning"
          showIcon
          message={intl.formatMessage({ id: 'ops.update.lastCheckFailed' })}
          description={data.last_error}
          style={{ marginBottom: 16 }}
        />
      ) : null}
      <Descriptions
        size="small"
        column={isMobile ? 1 : 2}
        bordered
        items={[
          {
            key: 'fw', label: intl.formatMessage({ id: 'ops.update.fwLabel' }),
            children: (
              <Space wrap>
                <Typography.Text strong>{fw?.local_version ?? '—'}</Typography.Text>
                {fw?.remote_version && <span>← {fw.remote_version}</span>}
                {formTag(fw?.form)}
                {availabilityTag(fw)}
              </Space>
            ),
          },
          {
            key: 'plugins', label: intl.formatMessage({ id: 'ops.update.pluginsLabel' }),
            children: (
              <Space wrap>
                <Typography.Text strong>{plugins?.local_version ?? '—'}</Typography.Text>
                {plugins?.remote_version && <span>← {plugins.remote_version}</span>}
                {formTag(plugins?.form)}
                {availabilityTag(plugins)}
              </Space>
            ),
          },
          {
            key: 'last_check', label: intl.formatMessage({ id: 'ops.update.lastCheck' }),
            children: fmtTs(data?.last_check_at ?? null),
          },
          {
            key: 'next', label: intl.formatMessage({ id: 'ops.update.autoCheck' }),
            children: data?.next_check_after
              ? intl.formatMessage({ id: 'ops.update.backoffNext' }, { time: fmtTs(data.next_check_after) })
              : intl.formatMessage({ id: 'ops.update.scheduleEnabled' }),
          },
        ]}
      />
      <Space style={{ marginTop: 16 }} wrap>
        <Button onClick={() => void handleCheck()} loading={checking}>
          {intl.formatMessage({ id: 'ops.update.checkNow' })}
        </Button>
        {fw?.form === 'artifact' && (
          <Button
            type="primary"
            data-testid="update-apply-btn"
            disabled={!canApply}
            loading={applying}
            onClick={handleApply}
          >
            {intl.formatMessage({ id: 'ops.update.applyNow' })}
          </Button>
        )}
        {fw?.form === 'artifact' && !fw.update_available && (
          <Typography.Text type="secondary">{intl.formatMessage({ id: 'ops.update.upToDateNoApply' })}</Typography.Text>
        )}
      </Space>
      {renderApplyState(apply)}
    </div>
  );
}
