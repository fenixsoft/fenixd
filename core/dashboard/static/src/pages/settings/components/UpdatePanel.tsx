import { App, Alert, Button, Card, Descriptions, Input, Progress, Radio, Space, Spin, Tag, Timeline, Typography } from 'antd';
import dayjs from 'dayjs';
import { useCallback, useEffect, useRef, useState } from 'react';
import { useIntl } from '@umijs/max';
import {
  ApiError,
  applyUpdate,
  checkUpdate,
  getUpdateMirror,
  getUpdateStatus,
  setUpdateMirror,
} from '@/services/dashboard';
import type {
  UpdateApplyState,
  UpdateMirrorData,
  UpdateStatusData,
  UpdateTargetStatus,
} from '@/services/dashboard';
// 文案经 useIntl/getIntl（i18n 修复轮 batch-A：本文件静态中文文案迁 i18n 目录）
import { intlText } from '@/utils/intlText.ts';

// 节标题说明用（2026-11-28 设置页同构改版引入裸 <Text>）。MUST 解构——裸
// 标识符 Text 在浏览器运行时解析到 DOM 全局 Text 接口，JSX 经自动运行时
// 以函数调用（jsx(Text, …)）触发「Please use the 'new' operator」白屏，
// 原组件只用 Typography.Text 全限定形态故此前未暴露
const { Text } = Typography;

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

// 预设 id → i18n 文案键（引擎 UPDATE_MIRROR_PRESETS 的 id 单源对齐；未知 id
// 回退显示原始 id，后端扩预设而前端未发版时不白屏）
const MIRROR_LABEL: Record<string, string> = {
  official: 'ops.update.mirror.preset.official',
  ghfast: 'ops.update.mirror.preset.ghfast',
  ghproxy: 'ops.update.mirror.preset.ghproxy',
};

/** 「自动更新」页签（add-auto-update 3.2；2026-11-28 用户指令自运维页迁入
 *  设置页——运维页职责是「基于 fenix 框架开发的工程」的运维，fenix 自身
 *  更新归设置页）：框架/插件版本、检查与应用编排状态、「立即检查」「一键
 *  更新」两动作。半自动边界：检查自动、应用 MUST 经 Modal.confirm 用户确认
 *  后触发（spec 更新状态展示 Requirement）。 */
export default function UpdatePanel({ isMobile }: { isMobile?: boolean }) {
  const { message, modal } = App.useApp();
  const intl = useIntl();
  const [data, setData] = useState<UpdateStatusData | null>(null);
  const [loading, setLoading] = useState(true);
  const [checking, setChecking] = useState(false);
  const [applying, setApplying] = useState(false);
  // 下载源（自选官方/镜像）：一次性读侧（非轮询；保存后本地同步归一值）
  const [mirrorData, setMirrorData] = useState<UpdateMirrorData | null>(null);
  const [mirrorSaving, setMirrorSaving] = useState(false);
  // 自定义镜像输入草稿（选中「自定义」Radio 时显示；初值=当前生效值）
  const [customDraft, setCustomDraft] = useState('');
  // 「自定义」Radio 是纯 UI 选择态（不落盘，待「保存」按钮）——Radio.Group
  // 受控值由 mirrorData 推导，选自定义必须走独立开关，否则点选后被推导值
  // 顶回、输入框永远不出现（真机 playwright 抓出）
  const [customActive, setCustomActive] = useState(false);
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

  useEffect(() => {
    // 读侧失败静默（下载源区不渲染即可，不打断更新卡主链路）
    // 自定义草稿同步灌入当前值：config 里存着不匹配预设的手工镜像时 Radio
    // 推导为「自定义」，输入框必须显示该值而非空白（否则用户看不出当前
    // 生效的是什么都——客户端真机截图抓出）
    getUpdateMirror()
      .then((d) => {
        setMirrorData(d);
        setCustomDraft(d.mirror || '');
      })
      .catch(() => {});
  }, []);

  // 当前 Radio 选中值：自定义开关打开 → custom；否则命中预设 id → 预设；
  // 非空但未命中 → 自定义；空 → 官方
  const mirrorRadio = customActive
    ? 'custom'
    : mirrorData
      ? mirrorData.presets.find((p) => p.url === mirrorData.mirror)?.id
        ?? (mirrorData.mirror ? 'custom' : 'official')
      : undefined;

  const applyMirror = useCallback(async (value: string) => {
    setMirrorSaving(true);
    try {
      const res = await setUpdateMirror(value);
      // 回显服务端归一化值（trim/去尾斜杠），保证 Radio 命中预设
      setMirrorData((prev) => (prev ? { ...prev, mirror: res.mirror } : prev));
      message.success(intl.formatMessage({ id: 'ops.update.mirror.saved' }));
    } catch (e) {
      message.error(
        intl.formatMessage(
          { id: 'ops.update.mirror.saveFailed' },
          { reason: e instanceof ApiError ? e.message : intl.formatMessage({ id: 'ops.update.networkError' }) },
        ),
      );
    } finally {
      setMirrorSaving(false);
    }
  }, [intl, message]);

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
    // queued / running：阶段进度 + 下载字节进度条（progress 仅进行中由后端透出）
    const pg = data?.progress ?? null;
    const fmtMb = (n?: number | null) =>
      n == null ? '' : `${(n / 1024 / 1024).toFixed(1)} MB`;
    return (
      <Card size="small" style={{ marginTop: 16 }} title={
        <Space><Spin size="small" />{intl.formatMessage({ id: 'ops.update.running' }, { phase: intl.formatMessage({ id: a.phase === 'queued' ? 'ops.update.phase.queued' : 'ops.update.phase.running' }) })}</Space>
      }>
        {data?.apply_stale && (
          <Alert
            type="warning"
            showIcon
            message={intl.formatMessage({ id: 'ops.update.staleHint' })}
            style={{ marginBottom: 16 }}
            data-testid="update-apply-stale"
          />
        )}
        {pg && (
          <div style={{ marginBottom: 16 }} data-testid="update-download-progress">
            <Progress
              percent={pg.total != null && pg.percent != null ? pg.percent : 0}
              status="active"
              size="small"
            />
            <Text type="secondary" style={{ fontSize: 12 }}>
              {pg.stage === 'verify'
                ? intl.formatMessage({ id: 'ops.update.verifying' }, { asset: pg.asset })
                : intl.formatMessage({ id: 'ops.update.downloading' }, {
                  asset: pg.asset,
                  done: fmtMb(pg.downloaded),
                  total: pg.total != null ? fmtMb(pg.total) : '?',
                  percent: pg.percent != null ? pg.percent : '--',
                })}
            </Text>
          </div>
        )}
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
      {/* 设置页面板同构（MiscSettingsPanel 先例）：h3 节标题 + 次要说明置于
          卡外，内容收纳进 Card——原运维页裸排布局（Alert/Descriptions 直接铺
          页面）迁入设置页后按同域口径收拢；apply 编排状态（成功/失败 Alert、
          进行中 Timeline 卡）保持在主卡之后堆叠呈现 */}
      <h3>{intl.formatMessage({ id: 'ops.update.sectionTitle' })}</h3>
      <Text type="secondary">{intl.formatMessage({ id: 'ops.update.sectionDesc' })}</Text>
      <Card style={{ marginTop: 12 }}>
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
        {/* 下载源自选（2026-11-28 用户指令）：官方/镜像预设 Radio + 自定义
            输入。只读侧失败不渲染本区（mirrorData null）；保存写用户级
            config.yaml 的 update.mirror，对下一次「一键更新」即时生效 */}
        {mirrorData && (
          <div style={{ marginTop: 16 }}>
            <Typography.Text strong>
              {intl.formatMessage({ id: 'ops.update.mirror.title' })}
            </Typography.Text>
            <div style={{ marginTop: 8 }}>
              <Radio.Group
                value={mirrorRadio}
                disabled={mirrorSaving}
                onChange={(e) => {
                  const id = String(e.target.value);
                  if (id === 'custom') {
                    setCustomDraft(mirrorData.mirror);
                    setCustomActive(true);
                    return; // 自定义不即存，待「保存」按钮
                  }
                  setCustomActive(false);
                  const preset = mirrorData.presets.find((p) => p.id === id);
                  if (preset) void applyMirror(preset.url);
                }}
              >
                <Space wrap size={16}>
                  {mirrorData.presets.map((p) => (
                    <Radio key={p.id} value={p.id}>
                      {intl.formatMessage({ id: MIRROR_LABEL[p.id] ?? 'ops.update.mirror.preset.custom' })}
                    </Radio>
                  ))}
                  <Radio value="custom">
                    {intl.formatMessage({ id: 'ops.update.mirror.preset.custom' })}
                  </Radio>
                </Space>
              </Radio.Group>
              {mirrorRadio === 'custom' && (
                <Space style={{ marginTop: 8, display: 'flex' }} wrap>
                  <Input
                    value={customDraft}
                    onChange={(e) => setCustomDraft(e.target.value)}
                    placeholder="https://<mirror>/https://github.com"
                    style={{ width: 360, maxWidth: '100%' }}
                    disabled={mirrorSaving}
                  />
                  <Button
                    loading={mirrorSaving}
                    onClick={() => void applyMirror(customDraft.trim())}
                  >
                    {intl.formatMessage({ id: 'ops.update.mirror.save' })}
                  </Button>
                </Space>
              )}
            </div>
            <Typography.Text type="secondary" style={{ display: 'block', marginTop: 8, fontSize: 12 }}>
              {intl.formatMessage({ id: 'ops.update.mirror.desc' })}
            </Typography.Text>
          </div>
        )}
        <Space
          // 2026-11-28 批注 round 2（uidebug dashboard 会话 #1）：动作行靠右
          // 对齐——Space 默认 inline-flex 收缩贴左，改块级 flex + flex-end
          // 把「立即检查」等动作推到面板右缘（与台账/表格动作惯例一致）。
          style={{ marginTop: 16, display: 'flex', justifyContent: 'flex-end' }}
          wrap
        >
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
        {/* 状态文件与配置键指引（设置页 label-note 同款口径：给出台账路径，
            不展开字段——字段速查见 docs/help/13-self-update.md） */}
        <Typography.Text type="secondary" style={{ display: 'block', marginTop: 16, fontSize: 12 }}>
          {intl.formatMessage({ id: 'ops.update.statusFileNote' })}
        </Typography.Text>
      </Card>
      {renderApplyState(apply)}
    </div>
  );
}
