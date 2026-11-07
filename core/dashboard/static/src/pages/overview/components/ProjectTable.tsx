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
import { history } from '@umijs/max';
import { useIsMobile } from '@/hooks/useIsMobile';
import type { ProjectSummary } from '@/services/dashboard';
import { deleteProject, installHosting, startProject, statusMeta, stopProject } from '@/services/dashboard';
// 百分比帮助函数单源（code-review item d7d303f389f6）：收敛到 @/utils/percent
import { pct } from '@/utils/percent';

// ── 台账色值（2026-11-06 对齐 v2 时取值，v2 域 2026-11-07 已退役，独立存量）──
const OV_RAMP_IMPLEMENTING = '#2563eb';
const OV_HAIRLINE = '#eef2f7';
const OV_ERROR = '#dc2626';
const OV_WARNING = '#d97706'; // = V2_WARNING
const OV_TEXT = '#1e293b'; // = V2_TEXT
const OV_TEXT_SECONDARY = '#475569'; // = V2_TEXT_SECONDARY
const OV_TEXT_TERTIARY = '#64748b'; // = V2_TEXT_TERTIARY
const OV_TEXT_QUATERNARY = '#94a3b8'; // = V2_TEXT_QUATERNARY

// 胶囊徽标 tone 键 → [前景色, 软底色]（源 = theme.tsx V2_TONE，两处同改；键域
// 与 statusMeta 的 StatusTone 对齐，muted 兜底）
const OV_TONE: Record<string, [string, string]> = {
  info: ['#2563eb', '#eff6ff'],
  warning: ['#d97706', '#fffbeb'],
  critical: ['#dc2626', '#fef2f2'],
  good: ['#16a34a', '#f0fdf4'],
  aqua: ['#0891b2', '#ecfeff'],
  muted: ['#64748b', '#f1f5f9'],
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
  if (p.error) {
    return (
      <div style={{ minWidth: 0 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
          <span style={{ fontSize: 14, fontWeight: 600 }}>{p.name}</span>
          <Pill tone="critical">项目错误</Pill>
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
          <Pill tone="warning">运行中·未托管</Pill>
        ) : (
          <Pill tone="good">运行中</Pill>
        )
      ) : p.daemon === 'stopped' ? (
        <Pill tone="warning">未运行</Pill>
      ) : null}
      {p.discovered ? <Pill tone="muted">自动发现</Pill> : null}
      {pending ? <Tag color="processing" style={{ marginInlineEnd: 0 }}>处理中…</Tag> : null}
    </div>,
    <div key="path" className="ov-num" style={{ fontSize: 12, color: OV_TEXT_QUATERNARY, marginTop: 5 }}>
      {p.path}
    </div>,
    // 长注释：桌面换行全显（pre-wrap，表格 fixed 布局防撑坏）；移动卡片单行省略
    p.exists === false ? (
      <div key="missing" style={{ fontSize: 12, color: OV_ERROR, marginTop: 4 }}>
        路径不存在 — {p.path}
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
        {p.description || '暂无简介'}
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
  const mobile = useIsMobile();
  // 在飞操作按项目名记账（Set 而非单槽字符串）：并发操作标记互不覆盖，
  // 各自 settle 只摘除自己；菜单项据此禁用，防 pending 期间重复下发
  const [pending, setPending] = useState<Set<string>>(new Set());
  const [statusFilter, setStatusFilter] = useState<StatusFilter>('all');
  const [keyword, setKeyword] = useState('');

  // 搜索口径对齐 v2 台账（name/path/description 三字段包含命中；原版仅 name）
  const filtered = projects.filter((p) => {
    if (statusFilter === 'running' && p.daemon !== 'running') return false;
    if (statusFilter === 'stopped' && p.daemon === 'running') return false;
    const kw = keyword.trim().toLowerCase();
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
      message.loading({ content: `正在移除项目「${name}」…`, key, duration: 0 });
      try {
        await deleteProject(name);
        message.success({ content: `已移除项目「${name}」`, key });
      } catch (err) {
        message.error({
          content: `项目「${name}」移除失败：${err instanceof Error ? err.message : String(err)}`,
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
        message.success(`项目「${name}」已启动`);
      } else if (action === 'install') {
        await installHosting(name);
        message.success(`项目「${name}」已安装 supervisor 托管`);
      } else {
        await stopProject(name);
        message.success(`项目「${name}」已停止`);
      }
      onChanged();
    } catch (err) {
      message.error(`项目「${name}」操作失败：${err instanceof Error ? err.message : String(err)}`);
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
      title: '移除项目监控',
      content: (
        <div style={{ whiteSpace: 'pre-wrap' }}>
          {`确认从监控移除项目「${project.name}」？\n\n`}
          该项目 daemon 会被停止，但项目文件、STATE.md、spec/、.fenix/ 等数据全部保留在磁盘。
          {'\n'}此操作仅为"软删除"，可通过手工编辑 ~/.config/fenixd/dashboard.yaml，
          从 ignored 列表中删除对应路径来恢复监控。
        </div>
      ),
      okText: '移除',
      okButtonProps: { danger: true },
      cancelText: '取消',
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
        { key: 'enter', label: '进入' },
        { key: 'delete', icon: <DeleteOutlined />, label: '删除', danger: true, disabled: busy },
      ];
    }
    const running = project.daemon === 'running';
    const items = project.exists
      ? [
          { key: 'start', icon: <PlayCircleOutlined />, label: '启动', disabled: running || busy },
          { key: 'stop', icon: <PauseCircleOutlined />, label: '停止', disabled: !running || busy },
          // fix-supervisor-hosting-chain 5.3：unmanaged 项目提供「安装托管」
          // 一次性修复路径（停止裸 daemon → 经 supervisor 重启）
          ...(project.hosting === 'unmanaged'
            ? [{ key: 'install', icon: <ToolOutlined />, label: '安装托管', disabled: busy }]
            : []),
          { type: 'divider' as const },
        ]
      : [];
    return [...items, { key: 'delete', icon: <DeleteOutlined />, label: '删除', danger: true, disabled: busy }];
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
      <Button type="text" size="small" icon={mobile ? <DotsIcon /> : <MoreOutlined />} aria-label="更多操作" />
    </Dropdown>
  );

  if (!projects.length) {
    return (
      <Card>
        <Alert
          type="info"
          showIcon
          message="尚未注册任何项目"
          description="在任意 Fenixd 项目内执行 /fenix-dashboard 即可注册监控。"
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
          <span style={{ fontSize: 16, fontWeight: 700 }}>项目清单</span>
          <span className="ov-num" style={{ fontSize: 12, color: OV_TEXT_QUATERNARY }}>
            {projects.length} 个 · 运行中 {runCount}
          </span>
        </div>
        <Input.Search
          placeholder="搜索项目"
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
                {renderDropdown(p)}
              </div>
              {!rowUnavailable(p) ? (
                <>
                  <div style={{ display: 'flex', gap: 14, marginTop: 8 }}>
                    <span className="ov-num" style={{ fontSize: 12, color: OV_TEXT_TERTIARY }}>
                      SPEC <span style={{ fontWeight: 700, color: OV_TEXT }}>{p.spec_count}</span>
                    </span>
                    <span className="ov-num" style={{ fontSize: 12, color: OV_TEXT_TERTIARY }}>
                      问题{' '}
                      <span style={{ fontWeight: 700, color: p.problems > 0 ? OV_ERROR : OV_TEXT }}>{p.problems}</span>
                    </span>
                    <span className="ov-num" style={{ fontSize: 12, color: OV_TEXT_TERTIARY }}>
                      活跃{' '}
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
            <div style={{ fontSize: 12, color: OV_TEXT_TERTIARY, padding: '12px 0' }}>无匹配项目</div>
          ) : null}
        </div>
      </div>
    );
  }

  // ── 桌面形态（镜像 v2 ProjectPanel：台账表格磁贴）──
  const columns: ColumnsType<ProjectSummary> = [
    {
      title: '项目',
      dataIndex: 'name',
      render: (_, p) => <ProjectCell p={p} pending={pending.has(p.name)} />,
    },
    {
      title: 'SPEC 数',
      dataIndex: 'spec_count',
      width: 96,
      align: 'center',
      render: (v, p) => (rowUnavailable(p) ? <DashCell /> : <NumCell v={v} />),
    },
    {
      title: '任务进度',
      dataIndex: 'task_total',
      width: 220,
      render: (_, p) =>
        rowUnavailable(p) ? (
          <DashCell />
        ) : (
          <div style={{ minWidth: 0 }}>
            <div style={{ display: 'flex', alignItems: 'baseline', justifyContent: 'space-between', gap: 8 }}>
              <span style={{ fontSize: 12, color: OV_TEXT_TERTIARY }}>任务进度</span>
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
      title: '问题/阻塞',
      dataIndex: 'problems',
      width: 108,
      align: 'center',
      render: (v, p) => (rowUnavailable(p) ? <DashCell /> : <NumCell v={v} color={v > 0 ? OV_ERROR : undefined} />),
    },
    {
      title: '活跃运行',
      dataIndex: 'active_runs',
      width: 108,
      align: 'center',
      render: (v, p) => (rowUnavailable(p) ? <DashCell /> : <NumCell v={v} color={v > 0 ? OV_WARNING : undefined} />),
    },
    {
      title: '操作',
      key: 'actions',
      width: 72,
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
        <span style={{ fontSize: 16, fontWeight: 700 }}>项目清单</span>
        <span className="ov-num" style={{ fontSize: 12, color: OV_TEXT_QUATERNARY }}>
          共 {projects.length} 个 · 运行中 {runCount}
        </span>
        <span style={{ flex: 1 }} />
        <Input.Search
          placeholder="搜索项目"
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
            { label: '全部', value: 'all' },
            { label: '运行中', value: 'running' },
            { label: '未运行', value: 'stopped' },
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
          scroll={{ x: 1060 }}
          // 过滤无命中也要有空态（code-review item 4cc2d91e005b）
          locale={{ emptyText: '无匹配项目，请调整搜索关键词或状态筛选' }}
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
