// overview 项目台账表格（2026-11-06 用户指令：项目清单呈现对齐 v2 overview
// 台账磁贴，桌面=表格形态、移动=堆叠项目卡，复制自 pages/v2/overview.tsx
// ProjectPanel 两形态——该域 2026-11-07 已退役，本组件为独立存量）。样式规则
// 落 global.less `.ov-*` 作用域。行为层保留本页既有契约不随视觉切换：
// 乐观删除 + 侧边栏菜单同步（onProjectRemoved/onProjectSettle）、在飞记账
// pending、错误态/exists 语义（fix-dashboard-fault-isolation）、跳转本产项目页
// /projects/:name（原版页面语义不变）。
import {
  DeleteOutlined,
  MoreOutlined,
  PauseCircleOutlined,
  PlayCircleOutlined,
  ToolOutlined,
} from '@ant-design/icons';
import { Alert, App, Button, Card, Dropdown, Input, Progress, Radio, Space, Table, Tag } from 'antd';
import type { ColumnsType } from 'antd/es/table';
import { useState } from 'react';
import type { ReactNode } from 'react';
// 文案经 useIntl（add-framework-i18n-zh-en 3.4：本页自有静态中文文案迁 i18n 目录）
import { history, useIntl } from '@umijs/max';
import { useIsMobile } from '@/hooks/useIsMobile';
import { useMediaQuery } from '@/hooks/useMediaQuery';
import type { ProjectSummary } from '@/services/dashboard';
import { deleteProject, installHosting, startProject, statusMeta, stopProject } from '@/services/dashboard';
// 百分比帮助函数单源（code-review item d7d303f389f6）：收敛到 @/utils/percent
import { pct } from '@/utils/percent';
// 跨页 Bento 色值单源（theme.ts；item b4f39b38d814 上收，与 detail/list 两页共用）
// dashboard-dark-theme 4.2：theme.ts 常量消费改引 global.less 主题 CSS 变量
// （值源 theme.ts 档位镜像：浅档与原字面值逐字节一致、深档=D2 映射；var()
// 形态使切档零 React 参与即时生效，同名局部常量保持既有消费点字面不变）。
const OV_HAIRLINE = 'var(--fenix-hairline)';
const OV_TEXT_TERTIARY = 'var(--fenix-ov-text-tertiary)';

// ── 台账色值（2026-11-06 对齐 v2 时取值，v2 域 2026-11-07 已退役，独立存量）──
const OV_RAMP_IMPLEMENTING = 'var(--fenix-ov-info)';
const OV_ERROR = 'var(--fenix-ov-error)';
const OV_WARNING = 'var(--fenix-ov-warning)'; // = V2_WARNING
const OV_TEXT = 'var(--fenix-ov-text)'; // = V2_TEXT
const OV_TEXT_SECONDARY = 'var(--fenix-ov-text-secondary)'; // = V2_TEXT_SECONDARY
// （OV_TEXT_TERTIARY 已上收 @/theme 跨页单源，item b4f39b38d814）
const OV_TEXT_QUATERNARY = 'var(--fenix-ov-text-quaternary)'; // = V2_TEXT_QUATERNARY

// 台账列宽双档（2026-11-16 用户指令：页面缩小时大部分空间从项目列出，其余各列
// 适当贡献一点）：宽档（viewport ≥1200，antd xl）维持原值不动（PC 端零影响）；
// 窄档（<1200，即 umi screen-md/sm/xs/lg）其余五列收到可读下限合计 510
// （较宽档让出 94px），项目列仍无宽度吃剩余。下限可读性核算：
// SPEC 数表头 ≈52+16pad=68 ≤80；问题/阻塞表头 ≈62+16=78 ≤92；
// 任务进度数字行 48+91+gap8+pad16 ≈163 ≤190；操作 icon 24+16=40 ≤56。
const NARROW_LEDGER_QUERY = '(max-width: 1199.98px)';
const LEDGER_WIDTHS = {
  wide: { spec: 96, progress: 220, problems: 108, activeRuns: 108, actions: 72 },
  narrow: { spec: 80, progress: 190, problems: 92, activeRuns: 92, actions: 56 },
} as const;

// 胶囊徽标 tone 键 → [前景色, 软底色]（源 = theme.tsx V2_TONE，两处同改；键域
// 与 statusMeta 的 StatusTone 对齐，muted 兜底）
// dashboard-dark-theme 4.3：取值改引主题 CSS 变量（浅档与原字面值逐字节一致、
// 深档=D2 映射软底 alpha 派生；Pill 显式 style 直落 CSS，var 即时随档）。
const OV_TONE: Record<string, [string, string]> = {
  info: ['var(--fenix-ov-info)', 'var(--fenix-ov-info-soft)'],
  warning: ['var(--fenix-ov-warning)', 'var(--fenix-pill-warning-soft)'],
  critical: ['var(--fenix-ov-error)', 'var(--fenix-pill-critical-soft)'],
  good: ['var(--fenix-pill-good)', 'var(--fenix-pill-good-soft)'],
  aqua: ['var(--fenix-pill-aqua)', 'var(--fenix-pill-aqua-soft)'],
  muted: ['var(--fenix-ov-text-tertiary)', 'var(--fenix-ov-muted-soft)'],
};

/** 语义胶囊徽标（Bento 语言：999 胶囊 + tone 软底；镜像 v2 shared.tsx V2Pill
 * filled 形态，本页只用 filled）。 */
function Pill({ tone = 'muted', children }: { tone?: string; children: ReactNode }) {
  const pair = OV_TONE[tone] || OV_TONE.muted;
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
      }}
    >
      {children}
    </Tag>
  );
}

/** 三点操作图标（镜像 v2 DotsIcon；表格「操作」列 Dropdown 触发器）。 */
function DotsIcon() {
  return (
    <svg width={14} height={14} viewBox="0 0 14 14" fill="currentColor" aria-hidden>
      <circle cx={2.6} cy={7} r={1.2} />
      <circle cx={7} cy={7} r={1.2} />
      <circle cx={11.4} cy={7} r={1.2} />
    </svg>
  );
}

type StatusFilter = 'all' | 'running' | 'stopped';

/** 项目单元格：名称行（运行态胶囊 + 自动发现/处理中）+ 路径 + 长简介 + 状态胶囊。
 * 移动形态简介单行省略（卡片等宽不横撑）；桌面表格保持 pre-wrap 全显。
 * 错误态呈警示胶囊 + 错误文案（fix-dashboard-fault-isolation：不渲染 daemon
 * 徽标/状态胶囊误导）；exists=false 呈「路径不存在」危险文案。 */
function ProjectCell({ p, pending, mobile }: { p: ProjectSummary; pending?: boolean; mobile?: boolean }) {
  const intl = useIntl();
  if (p.error) {
    return (
      <div style={{ minWidth: 0 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
          <span style={{ fontSize: 14, fontWeight: 600 }}>{p.name}</span>
          <Pill tone="critical">{intl.formatMessage({ id: 'overview.ledger.projectError' })}</Pill>
        </div>
        <div className="ov-num" style={{ fontSize: 12, color: OV_TEXT_QUATERNARY, marginTop: 5 }}>
          {p.path}
        </div>
        <div className="ov-ellipsis" style={{ fontSize: 12, color: OV_ERROR, marginTop: 4 }} title={p.error}>
          {p.error}
        </div>
      </div>
    );
  }
  const kids = [
    <div key="id" style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
      <span
        style={{ fontSize: 14, fontWeight: 600, cursor: 'pointer' }}
        role="button"
        tabIndex={0}
        onClick={(e) => {
          e.stopPropagation();
          history.push(`/projects/${encodeURIComponent(p.name)}`);
        }}
        onKeyDown={(e) => {
          // 键盘可达（code-review item b5ed7707672e）：Enter/Space 触发跳转
          if (e.key === 'Enter' || e.key === ' ') {
            e.preventDefault();
            history.push(`/projects/${encodeURIComponent(p.name)}`);
          }
        }}
      >
        {p.name}
      </span>
      {p.daemon === 'running' ? (
        p.hosting === 'unmanaged' ? (
          <Pill tone="warning">{intl.formatMessage({ id: 'overview.ledger.runningUnmanaged' })}</Pill>
        ) : (
          <Pill tone="good">{intl.formatMessage({ id: 'common.status.running' })}</Pill>
        )
      ) : p.daemon === 'stopped' ? (
        <Pill tone="warning">{intl.formatMessage({ id: 'overview.ledger.stopped' })}</Pill>
      ) : null}
      {p.discovered ? <Pill tone="muted">{intl.formatMessage({ id: 'overview.ledger.discovered' })}</Pill> : null}
      {pending ? <Tag color="processing" style={{ marginInlineEnd: 0 }}>{intl.formatMessage({ id: 'overview.ledger.processing' })}</Tag> : null}
    </div>,
    <div key="path" className="ov-num" style={{ fontSize: 12, color: OV_TEXT_QUATERNARY, marginTop: 5 }}>
      {p.path}
    </div>,
    // 长注释：桌面换行全显（pre-wrap，表格 fixed 布局防撑坏）；移动卡片单行省略
    p.exists === false ? (
      <div key="missing" style={{ fontSize: 12, color: OV_ERROR, marginTop: 4 }}>
        {intl.formatMessage({ id: 'overview.ledger.pathMissing' }, { path: p.path })}
      </div>
    ) : (
      <div
        key="desc"
        className={mobile ? 'ov-ellipsis' : undefined}
        style={
          mobile
            ? { fontSize: 12, color: OV_TEXT_TERTIARY, marginTop: 4 }
            : { fontSize: 12, color: OV_TEXT_TERTIARY, marginTop: 4, whiteSpace: 'pre-wrap', lineHeight: '20px' }
        }
        title={mobile ? p.description || undefined : undefined}
      >
        {p.description || intl.formatMessage({ id: 'overview.ledger.noDescription' })}
      </div>
    ),
  ];
  const tags = Object.entries(p.status_counts || {}).map(([st, n]) => {
    const meta = statusMeta(st);
    return <Pill key={st} tone={meta.tone}>{`${meta.label} ${n}`}</Pill>;
  });
  if (tags.length) {
    kids.push(
      <div key="tags" style={{ display: 'flex', flexWrap: 'wrap', gap: 4, marginTop: 7 }}>
        {tags}
      </div>,
    );
  }
  return <div style={{ minWidth: 0 }}>{kids}</div>;
}

function NumCell({ v, color }: { v: number; color?: string }) {
  return (
    <span className="ov-num" style={{ fontSize: 16, fontWeight: 700, color: color || OV_TEXT }}>
      {v}
    </span>
  );
}

function DashCell() {
  return (
    <span className="ov-num" style={{ color: OV_TEXT_QUATERNARY, fontSize: 16 }}>
      —
    </span>
  );
}

/** 不可读数据行（错误态 / exists=false）：数据列统一「—」，不伪装 0（对齐 v2
 * null 口径红线与原版错误态语义）。 */
function rowUnavailable(p: ProjectSummary): boolean {
  return Boolean(p.error) || p.exists === false;
}

export default function ProjectTable({
  projects,
  onChanged,
  onProjectRemoved,
  onProjectSettle,
}: {
  projects: ProjectSummary[];
  onChanged: () => void;
  onProjectRemoved?: (name: string) => void;
  onProjectSettle?: (name: string) => void;
}) {
  const { message, modal } = App.useApp();
  const intl = useIntl();
  const mobile = useIsMobile();
  // 窄桌面档（<1200）：台账其余列让位下限（见 LEDGER_WIDTHS 注释），与移动分
  // 支（<768 堆叠卡）正交；useMediaQuery 首帧同步取值无闪动
  const narrowLedger = useMediaQuery(NARROW_LEDGER_QUERY);
  // 在飞操作按项目名记账（Set 而非单槽字符串）：并发操作标记互不覆盖，
  // 各自 settle 只摘除自己；菜单项据此禁用，防 pending 期间重复下发
  const [pending, setPending] = useState<Set<string>>(new Set());
  const [statusFilter, setStatusFilter] = useState<StatusFilter>('all');
  const [keyword, setKeyword] = useState('');

  // 搜索口径对齐 v2 台账（name/path/description 三字段包含命中；原版仅 name）。
  // 运行态筛选仅桌面消费（code-review item 255445d64ba6）：移动形态不渲染筛选
  // chips（原型 m-overview 无筛选行），若仍消费桌面残留筛选值，窗口缩窄后卡片
  // 会被隐形裁剪且无任何控件或提示可发现/复位——移动分支仅按 keyword 过滤
  const kw = keyword.trim().toLowerCase();
  const filtered = projects.filter((p) => {
    if (!mobile) {
      if (statusFilter === 'running' && p.daemon !== 'running') return false;
      if (statusFilter === 'stopped' && p.daemon === 'running') return false;
    }
    if (kw) {
      return (
        p.name.toLowerCase().includes(kw) ||
        (p.path || '').toLowerCase().includes(kw) ||
        (p.description || '').toLowerCase().includes(kw)
      );
    }
    return true;
  });

  const runCount = projects.filter((p) => p.daemon === 'running').length;

  const runAction = async (name: string, action: 'start' | 'stop' | 'delete' | 'install') => {
    // 删除走乐观路径：后端 DELETE 同步等 stop_daemon 轮询（上限 30s），若等返回
    // 再刷新，列表/菜单会滞留十几秒——先本地摘除（列表经 onProjectRemoved、菜单经
    // initialState），后端完成后 onChanged() 校准；失败也经 onChanged() 回滚摘除。
    if (action === 'delete') {
      // 删除同样记账在飞（code-review item f060e4a1ac86）：乐观摘除行后菜单仍可能
      // 经其它入口（列表快速刷新、错误行恢复）触发，pending 记账 + 菜单项 disabled
      // 防在飞期间对同一项目并发下发 DELETE
      setPending((prev) => new Set(prev).add(name));
      onProjectRemoved?.(name);
      const key = `del-${name}`;
      message.loading({ content: intl.formatMessage({ id: 'overview.ledger.removing' }, { name }), key, duration: 0 });
      try {
        await deleteProject(name);
        message.success({ content: intl.formatMessage({ id: 'overview.ledger.removed' }, { name }), key });
      } catch (err) {
        message.error({
          content: intl.formatMessage(
            { id: 'overview.ledger.removeFailed' },
            { name, err: err instanceof Error ? err.message : String(err) },
          ),
          key,
        });
      } finally {
        // 先解除在飞标记（pending 记账 + 父级删除标记），再刷新——load() 恢复采用
        // 服务端真值（成功=确认移除；失败=回滚乐观摘除，项目重新出现）
        setPending((prev) => {
          const next = new Set(prev);
          next.delete(name);
          return next;
        });
        onProjectSettle?.(name);
        onChanged();
      }
      return;
    }
    setPending((prev) => new Set(prev).add(name));
    try {
      if (action === 'start') {
        await startProject(name);
        message.success(intl.formatMessage({ id: 'overview.ledger.started' }, { name }));
      } else if (action === 'install') {
        await installHosting(name);
        message.success(intl.formatMessage({ id: 'overview.ledger.hostingInstalled' }, { name }));
      } else {
        await stopProject(name);
        message.success(intl.formatMessage({ id: 'overview.ledger.stoppedMsg' }, { name }));
      }
      onChanged();
    } catch (err) {
      message.error(
        intl.formatMessage(
          { id: 'overview.ledger.actionFailed' },
          { name, err: err instanceof Error ? err.message : String(err) },
        ),
      );
      // 失败也校准（code-review item 081eba8b7d85）：统一 30s 超时下失败响应可能实际
      // 已生效（如响应超时但 start 已完成），与 delete 分支「失败也经 onChanged()
      // 回滚/校准」口径对齐，立即用服务端真值刷新而非等 30s 心跳
      onChanged();
    } finally {
      setPending((prev) => {
        const next = new Set(prev);
        next.delete(name);
        return next;
      });
    }
  };

  const confirmDelete = (project: ProjectSummary) => {
    modal.confirm({
      title: intl.formatMessage({ id: 'overview.ledger.removeConfirmTitle' }),
      content: (
        <div style={{ whiteSpace: 'pre-wrap' }}>
          {intl.formatMessage({ id: 'overview.ledger.removeConfirmQuestion' }, { name: project.name })}
          {intl.formatMessage({ id: 'overview.ledger.removeConfirmBody1' })}
          {'\n'}
          {intl.formatMessage({ id: 'overview.ledger.removeConfirmBody2' })}
        </div>
      ),
      okText: intl.formatMessage({ id: 'overview.ledger.removeConfirmOk' }),
      okButtonProps: { danger: true },
      cancelText: intl.formatMessage({ id: 'common.cancel' }),
      // 不返回 promise：立即关弹窗，移除在后台进行（项目行已乐观消失）
      onOk: () => {
        void runAction(project.name, 'delete');
      },
    });
  };

  const menuItems = (project: ProjectSummary) => {
    const busy = pending.has(project.name);
    // fix-dashboard-fault-isolation 3.3：错误态项目（摘要带非空 error）内容不可读，
    // 禁 start/stop/install 操作，仅保留「进入」与「删除」（删除 = 软删除逃生通道）。
    // 删除项统一 disabled: busy（code-review item f060e4a1ac86）：delete 已入
    // 在飞记账，防在飞期间重复下发
    if (project.error) {
      return [
        { key: 'enter', label: intl.formatMessage({ id: 'overview.ledger.enter' }) },
        { key: 'delete', icon: <DeleteOutlined />, label: intl.formatMessage({ id: 'common.delete' }), danger: true, disabled: busy },
      ];
    }
    const running = project.daemon === 'running';
    // exists 用 === false 严格判定（code-review item dd8894b24e80）：字段缺省
    // （undefined）按存在处理，与 ProjectCell / rowUnavailable 同口径，防版本
    // 代差下操作菜单被误裁剪
    const items = project.exists === false
      // exists=false 保留「进入」（code-review item 2a2daa7c5e50）：行点击（桌面
      // onRow / 移动卡片 onClick / ProjectCell 名称）不拦截 exists=false 仍可进入
      // /projects/:name，菜单裁掉「进入」会让两入口口径不一致——与上方错误态
      // 分支同款（start/stop/install 裁剪不变，仅删 divider）
      ? [{ key: 'enter', label: intl.formatMessage({ id: 'overview.ledger.enter' }) }]
      : [
          { key: 'start', icon: <PlayCircleOutlined />, label: intl.formatMessage({ id: 'overview.ledger.start' }), disabled: running || busy },
          { key: 'stop', icon: <PauseCircleOutlined />, label: intl.formatMessage({ id: 'overview.ledger.stop' }), disabled: !running || busy },
          // fix-supervisor-hosting-chain 5.3：unmanaged 项目提供「安装托管」
          // 一次性修复路径（停止裸 daemon → 经 supervisor 重启）
          ...(project.hosting === 'unmanaged'
            ? [{ key: 'install', icon: <ToolOutlined />, label: intl.formatMessage({ id: 'overview.ledger.installHosting' }), disabled: busy }]
            : []),
          { type: 'divider' as const },
        ];
    return [...items, { key: 'delete', icon: <DeleteOutlined />, label: intl.formatMessage({ id: 'common.delete' }), danger: true, disabled: busy }];
  };

  const onMenuClick = (project: ProjectSummary, key: string, domEvent?: { stopPropagation(): void }) => {
    // 菜单点击不触发行跳转（v2 台账同款 stopPropagation）
    domEvent?.stopPropagation();
    if (key === 'enter') {
      history.push(`/projects/${encodeURIComponent(project.name)}`);
    } else if (key === 'delete') {
      confirmDelete(project);
    } else if (key === 'start' || key === 'stop' || key === 'install') {
      void runAction(project.name, key as 'start' | 'stop' | 'install');
    }
  };

  const renderDropdown = (project: ProjectSummary) => (
    <Dropdown
      menu={{
        items: menuItems(project),
        onClick: ({ key, domEvent }) => onMenuClick(project, key, domEvent),
      }}
      placement="bottomRight"
      trigger={['click']}
    >
      <Button type="text" size="small" icon={mobile ? <DotsIcon /> : <MoreOutlined />} aria-label={intl.formatMessage({ id: 'overview.ledger.moreActions' })} />
    </Dropdown>
  );

  if (!projects.length) {
    return (
      <Card>
        <Alert
          type="info"
          showIcon
          message={intl.formatMessage({ id: 'overview.ledger.empty' })}
          description={intl.formatMessage({ id: 'overview.ledger.emptyDesc' })}
        />
      </Card>
    );
  }

  // ── 移动形态（镜像 v2 ProjectPanel mobile：堆叠项目卡，操作收敛卡头更多菜单；
  //    原型 m-overview 无运行态筛选行，移动端不渲染 chips——桌面 chips 照常）──
  if (mobile) {
    return (
      <div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
          <span style={{ fontSize: 16, fontWeight: 700 }}>{intl.formatMessage({ id: 'overview.ledger.title' })}</span>
          <span className="ov-num" style={{ fontSize: 12, color: OV_TEXT_QUATERNARY }}>
            {intl.formatMessage({ id: 'overview.ledger.countRunning' }, { count: projects.length, running: runCount })}
          </span>
        </div>
        <Input.Search
          placeholder={intl.formatMessage({ id: 'overview.ledger.searchPlaceholder' })}
          size="small"
          allowClear
          style={{ width: '100%', marginTop: 10 }}
          value={keyword}
          onChange={(e) => setKeyword(e.target.value)}
        />
        <div style={{ marginTop: 12, display: 'flex', flexDirection: 'column', gap: 12 }}>
          {filtered.map((p) => (
            <div
              key={p.name}
              className="ov-bento"
              style={{ padding: '14px 16px', cursor: p.error ? 'default' : 'pointer', minWidth: 0 }}
              onClick={() => {
                if (!p.error) history.push(`/projects/${encodeURIComponent(p.name)}`);
              }}
            >
              <div style={{ display: 'flex', alignItems: 'flex-start', gap: 8 }}>
                <div style={{ flex: 1, minWidth: 0 }}>
                  <ProjectCell p={p} pending={pending.has(p.name)} mobile />
                </div>
                {/* 阻断点击冒泡到卡片根 div（code-review item 829beaddb799）：与桌面
                    操作列 Space stopPropagation 同口径，否则点「更多操作」即触发
                    卡片跳转、菜单永远打不开 */}
                <Space size={4} onClick={(e) => e.stopPropagation()}>{renderDropdown(p)}</Space>
              </div>
              {!rowUnavailable(p) ? (
                <>
                  <div style={{ display: 'flex', gap: 14, marginTop: 8 }}>
                    <span className="ov-num" style={{ fontSize: 12, color: OV_TEXT_TERTIARY }}>
                      SPEC <span style={{ fontWeight: 700, color: OV_TEXT }}>{p.spec_count}</span>
                    </span>
                    <span className="ov-num" style={{ fontSize: 12, color: OV_TEXT_TERTIARY }}>
                      {intl.formatMessage({ id: 'overview.ledger.problemsLabel' })}{' '}
                      <span style={{ fontWeight: 700, color: p.problems > 0 ? OV_ERROR : OV_TEXT }}>{p.problems}</span>
                    </span>
                    <span className="ov-num" style={{ fontSize: 12, color: OV_TEXT_TERTIARY }}>
                      {intl.formatMessage({ id: 'overview.ledger.activeLabel' })}{' '}
                      <span style={{ fontWeight: 700, color: p.active_runs > 0 ? OV_WARNING : OV_TEXT }}>{p.active_runs}</span>
                    </span>
                  </div>
                  <div style={{ marginTop: 8 }}>
                    <Progress
                      percent={pct(p.task_done, p.task_total)}
                      size="small"
                      strokeColor={OV_RAMP_IMPLEMENTING}
                      railColor={OV_HAIRLINE}
                      showInfo={false}
                    />
                  </div>
                  <div className="ov-num" style={{ fontSize: 12, color: OV_TEXT_TERTIARY, marginTop: 4 }}>
                    {p.task_done}/{p.task_total} · {pct(p.task_done, p.task_total)}%
                  </div>
                </>
              ) : null}
            </div>
          ))}
          {!filtered.length ? (
            <div style={{ fontSize: 12, color: OV_TEXT_TERTIARY, padding: '12px 0' }}>{intl.formatMessage({ id: 'overview.ledger.noMatch' })}</div>
          ) : null}
        </div>
      </div>
    );
  }

  // ── 桌面形态（镜像 v2 ProjectPanel：台账表格磁贴）──
  const ledgerWidths = narrowLedger ? LEDGER_WIDTHS.narrow : LEDGER_WIDTHS.wide;
  const columns: ColumnsType<ProjectSummary> = [
    {
      title: intl.formatMessage({ id: 'overview.ledger.colProject' }),
      dataIndex: 'name',
      render: (_, p) => <ProjectCell p={p} pending={pending.has(p.name)} />,
    },
    {
      title: intl.formatMessage({ id: 'overview.ledger.colSpecCount' }),
      dataIndex: 'spec_count',
      width: ledgerWidths.spec,
      align: 'center',
      render: (v, p) => (rowUnavailable(p) ? <DashCell /> : <NumCell v={v} />),
    },
    {
      title: intl.formatMessage({ id: 'overview.kpi.taskProgress' }),
      dataIndex: 'task_total',
      width: ledgerWidths.progress,
      render: (_, p) =>
        rowUnavailable(p) ? (
          <DashCell />
        ) : (
          <div style={{ minWidth: 0 }}>
            <div style={{ display: 'flex', alignItems: 'baseline', justifyContent: 'space-between', gap: 8 }}>
              <span style={{ fontSize: 12, color: OV_TEXT_TERTIARY }}>{intl.formatMessage({ id: 'overview.kpi.taskProgress' })}</span>
              <span className="ov-num" style={{ fontSize: 12, fontWeight: 600 }}>
                {p.task_done}/{p.task_total} · {pct(p.task_done, p.task_total)}%
              </span>
            </div>
            <div style={{ marginTop: 6 }}>
              <Progress
                percent={pct(p.task_done, p.task_total)}
                size="small"
                strokeColor={OV_RAMP_IMPLEMENTING}
                railColor={OV_HAIRLINE}
                showInfo={false}
              />
            </div>
          </div>
        ),
    },
    {
      title: intl.formatMessage({ id: 'overview.ledger.colProblems' }),
      dataIndex: 'problems',
      width: ledgerWidths.problems,
      align: 'center',
      render: (v, p) => (rowUnavailable(p) ? <DashCell /> : <NumCell v={v} color={v > 0 ? OV_ERROR : undefined} />),
    },
    {
      title: intl.formatMessage({ id: 'overview.ledger.colActiveRuns' }),
      dataIndex: 'active_runs',
      width: ledgerWidths.activeRuns,
      align: 'center',
      render: (v, p) => (rowUnavailable(p) ? <DashCell /> : <NumCell v={v} color={v > 0 ? OV_WARNING : undefined} />),
    },
    {
      title: intl.formatMessage({ id: 'common.actions' }),
      key: 'actions',
      width: ledgerWidths.actions,
      align: 'right',
      render: (_, p) => <Space size={4} onClick={(e) => e.stopPropagation()}>{renderDropdown(p)}</Space>,
    },
  ];

  return (
    <div className="ov-bento">
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          gap: 12,
          flexWrap: 'wrap',
          padding: '14px 20px',
          borderBottom: `1px solid ${OV_HAIRLINE}`,
        }}
      >
        <span style={{ fontSize: 16, fontWeight: 700 }}>{intl.formatMessage({ id: 'overview.ledger.title' })}</span>
        <span className="ov-num" style={{ fontSize: 12, color: OV_TEXT_QUATERNARY }}>
          {intl.formatMessage({ id: 'overview.ledger.countRunningTotal' }, { count: projects.length, running: runCount })}
        </span>
        <span style={{ flex: 1 }} />
        <Input.Search
          placeholder={intl.formatMessage({ id: 'overview.ledger.searchPlaceholder' })}
          size="small"
          allowClear
          style={{ width: 200 }}
          value={keyword}
          onChange={(e) => setKeyword(e.target.value)}
        />
        {/* 运行态筛选：antd 并排按钮组（原版样式，2026-11-06 用户指令撤退独立
            胶囊形态）；激活项黑底白字走 global.less .ov-radio-dark 覆写类
           （DESIGN.md 一般域条款，projects 过滤组同款） */}
        <Radio.Group
          className="ov-radio-dark"
          optionType="button"
          size="small"
          value={statusFilter}
          onChange={(e) => setStatusFilter(e.target.value as StatusFilter)}
          options={[
            { label: intl.formatMessage({ id: 'overview.ledger.filterAll' }), value: 'all' },
            { label: intl.formatMessage({ id: 'common.status.running' }), value: 'running' },
            { label: intl.formatMessage({ id: 'overview.ledger.stopped' }), value: 'stopped' },
          ]}
        />
      </div>
      <div className="ov-bento-table">
        <Table
          columns={columns}
          dataSource={filtered}
          rowKey="name"
          pagination={false}
          size="middle"
          // 横向滚动下限按视口双档（2026-11-16 用户指令两连：小宽度下避免横向
          // 滚动条、页面缩小时其余列适当贡献而项目列吃大头）——原 1060 给无宽度
          // 的项目列预留 456px 最小宽，小视口容器放不下即出横向滚动条。
          // 宽档（viewport ≥1200）：scroll.x=890=固定列 604 + 项目列最小 286，
          //   容器 ≥890 表格按 100% 铺满、项目列吃剩余，宽视口观感不变；
          // 窄档（<1200，screen-md/sm/xs/lg）：其余列收到可读下限合计 510
          //   （LEDGER_WIDTHS.narrow，让出 94px），scroll.x=700=510+项目列最小
          //   190（名称/胶囊行换行、路径 12px 约 165px 放得下），无滚动条容器
          //   下限扩到 700px——覆盖 994px 视口 sider 展开态容器 706。
          scroll={{ x: narrowLedger ? 700 : 890 }}
          // 过滤无命中也要有空态（code-review item 4cc2d91e005b）
          locale={{ emptyText: intl.formatMessage({ id: 'overview.ledger.emptyFiltered' }) }}
          rowClassName={() => 'ov-project-row'}
          onRow={(rec) => ({
            onClick: () => {
              if (!rec.error) history.push(`/projects/${encodeURIComponent(rec.name)}`);
            },
            style: { cursor: rec.error ? 'default' : 'pointer' },
          })}
        />
      </div>
    </div>
  );
}
