import { App, Alert, Button, Card, Descriptions, Space, Spin, Tag, Timeline, Typography } from 'antd';
import dayjs from 'dayjs';
import { useCallback, useEffect, useRef, useState } from 'react';
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

// 轮询间隔：常态 30s（对齐 ChainPanel 节拍）；apply 编排进行中加速 2s，
// 让阶段推进（下载/校验/停起/换装）近实时可见
const REFRESH_MS = 30000;
const APPLY_REFRESH_MS = 2000;

// 形态标识（spec：artifact 可一键更新；source 显示 git pull 指引、无更新按钮）
const FORM_META: Record<string, { label: string; color: string }> = {
  artifact: { label: '制品安装', color: 'blue' },
  source: { label: '源码形态', color: 'purple' },
  unknown: { label: '未知', color: 'default' },
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
    ? <Tag color="orange">可更新 → {target.remote_version}</Tag>
    : <Tag color="green">已是最新</Tag>;
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
        message.success('检查完成');
      } else {
        message.warning(`检查失败：${res.error ?? '未知原因'}`);
      }
    } catch (e) {
      message.error(`检查请求失败：${e instanceof ApiError ? e.message : '网络异常'}`);
    } finally {
      setChecking(false);
    }
  }, [message]);

  const handleApply = useCallback(() => {
    modal.confirm({
      title: '确认一键更新？',
      content: (
        <>
          将下载最新制品并停机换装（停 daemon 与 dashboard → 原子换装 → 自动拉起），
          期间在飞 run 会被拒绝执行，过程约数分钟；失败自动回滚当前版本。
        </>
      ),
      okText: '开始更新',
      cancelText: '取消',
      onOk: async () => {
        setApplying(true);
        try {
          await applyUpdate();
          message.success('更新编排已受理，进度见下方状态');
          await load();
        } catch (e) {
          if (e instanceof ApiError && e.code === 'update-locked') {
            message.warning('更新编排已在进行中，请等待当前编排结束');
          } else {
            message.error(`更新受理失败：${e instanceof ApiError ? e.message : '网络异常'}`);
          }
        } finally {
          setApplying(false);
        }
      },
    });
  }, [modal, message, load]);

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
          message={`更新完成：${a.version ?? ''}`}
          description={
            <>
              <div>已保留一代回滚副本（{a.old_dir ? String(a.old_dir).split('/').pop() : ''}），如需回退见 docs/help/13-self-update.md。</div>
              {a.plugins?.status === 'success' && (
                <div>dsh-plugins 已更新至 {a.plugins.version}；desktop profile 需按文档手动半步。</div>
              )}
              {a.plugins?.status === 'skipped' && <div>{a.plugins.detail}</div>}
              {a.plugins_error && (
                <div style={{ color: '#cf1322' }}>插件边失败：{a.plugins_error}</div>
              )}
              <Typography.Text type="warning">
                若页面资源异常，请刷新浏览器；dashboard 服务已重启加载新前端。
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
          message={`更新失败${a.failed_stage ? `（阶段：${a.failed_stage}）` : ''}`}
          description={
            <>
              <div>{a.error}</div>
              {a.rollback && (
                <div>
                  {a.rollback_restored
                    ? '已自动回滚到更新前版本，服务已恢复。'
                    : '回滚未完成：请按 docs/help/13-self-update.md 手动恢复。'}
                </div>
              )}
              {a.plugins_error && <div>插件边：{a.plugins_error}</div>}
            </>
          }
          style={{ marginTop: 16 }}
        />
      );
    }
    // queued / running：阶段进度
    return (
      <Card size="small" style={{ marginTop: 16 }} title={
        <Space><Spin size="small" />更新进行中（{a.phase === 'queued' ? '已受理待启动' : '执行中'}）</Space>
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
          message="尚未执行过更新检查"
          description="点击「立即检查」发起首次检查；daemon 也会按配置周期自动检查（默认每日一次）。"
          style={{ marginBottom: 16 }}
        />
      ) : null}
      {fw?.form === 'source' ? (
        <Alert
          type="info"
          showIcon
          message="当前为源码形态安装（git clone），不参与制品自动更新"
          description="请在框架目录执行 git pull 更新；更新引擎仅服务制品形态安装。"
          style={{ marginBottom: 16 }}
        />
      ) : null}
      {data?.last_error ? (
        <Alert
          type="warning"
          showIcon
          message="最近一次检查失败"
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
            key: 'fw', label: 'fenixd 框架',
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
            key: 'plugins', label: 'dsh-plugins 插件',
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
            key: 'last_check', label: '最近检查',
            children: fmtTs(data?.last_check_at ?? null),
          },
          {
            key: 'next', label: '自动检查',
            children: data?.next_check_after
              ? `退避重试中（下次 ${fmtTs(data.next_check_after)}）`
              : '周期检查已启用（默认每 24 小时）',
          },
        ]}
      />
      <Space style={{ marginTop: 16 }} wrap>
        <Button onClick={() => void handleCheck()} loading={checking}>
          立即检查
        </Button>
        {fw?.form === 'artifact' && (
          <Button
            type="primary"
            data-testid="update-apply-btn"
            disabled={!canApply}
            loading={applying}
            onClick={handleApply}
          >
            一键更新
          </Button>
        )}
        {fw?.form === 'artifact' && !fw.update_available && (
          <Typography.Text type="secondary">已是最新，无需更新</Typography.Text>
        )}
      </Space>
      {renderApplyState(apply)}
    </div>
  );
}
