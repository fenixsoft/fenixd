import {
  DeleteOutlined,
  FolderOutlined,
  MoreOutlined,
  PauseCircleOutlined,
  PlayCircleOutlined,
} from '@ant-design/icons';
import { Alert, App, Avatar, Button, Card, Dropdown, List, Progress, Radio, Space, Tag, Typography } from 'antd';
import { useState } from 'react';
import { history } from '@umijs/max';
import type { ProjectSummary } from '@/services/dashboard';
import { deleteProject, startProject, statusMeta, stopProject } from '@/services/dashboard';

type StatusFilter = 'all' | 'running' | 'stopped';

const TRACK_LIGHT = '#e6f4ff';

const TONE_TO_TAG: Record<string, string> = {
  muted: 'default',
  info: 'blue',
  warning: 'orange',
  critical: 'red',
  good: 'green',
  aqua: 'cyan',
};

function pct(done: number, total: number) {
  return total > 0 ? Math.round((done / total) * 100) : 0;
}

function DaemonBadge({ daemon }: { daemon: string }) {
  if (daemon === 'running') {
    return (
      <Tag color="success" title="fenixd daemon 运行中">
        运行中
      </Tag>
    );
  }
  if (daemon === 'stopped') {
    return (
      <Tag color="warning" title="fenixd daemon 未运行">
        未运行
      </Tag>
    );
  }
  return null;
}

function MiniStat({ label, value, color }: { label: string; value: React.ReactNode; color?: string }) {
  return (
    <div style={{ minWidth: 0 }}>
      <Typography.Text type="secondary" style={{ fontSize: 12 }}>
        {label}
      </Typography.Text>
      <div style={{ fontSize: 16, fontWeight: 600, color }}>{value}</div>
    </div>
  );
}

export default function ProjectCards({
  projects,
  onChanged,
}: {
  projects: ProjectSummary[];
  onChanged: () => void;
}) {
  const { message, modal } = App.useApp();
  const [pendingName, setPendingName] = useState('');
  const [statusFilter, setStatusFilter] = useState<StatusFilter>('all');

  const filtered = projects.filter((p) => {
    if (statusFilter === 'all') return true;
    if (statusFilter === 'running') return p.daemon === 'running';
    return p.daemon !== 'running';
  });

  const runAction = async (name: string, action: 'start' | 'stop' | 'delete') => {
    setPendingName(name);
    try {
      if (action === 'delete') {
        await deleteProject(name);
        message.success(`已移除项目「${name}」`);
      } else if (action === 'start') {
        await startProject(name);
        message.success(`项目「${name}」已启动`);
      } else {
        await stopProject(name);
        message.success(`项目「${name}」已停止`);
      }
      onChanged();
    } catch (err) {
      message.error(`项目「${name}」操作失败：${err instanceof Error ? err.message : String(err)}`);
    } finally {
      setPendingName('');
    }
  };

  const confirmDelete = (project: ProjectSummary) => {
    modal.confirm({
      title: '移除项目监控',
      content: (
        <div style={{ whiteSpace: 'pre-wrap' }}>
          {`确认从监控移除项目「${project.name}」？\n\n`}
          该项目 daemon 会被停止，但项目文件、STATE.md、openspec/、.fenix/ 等数据全部保留在磁盘。
          {'\n'}此操作仅为"软删除"——可通过手工编辑 ~/.config/fenixd/dashboard.yaml，
          从 ignored 列表中删除对应路径来恢复监控。
        </div>
      ),
      okText: '移除',
      okButtonProps: { danger: true },
      cancelText: '取消',
      onOk: () => runAction(project.name, 'delete'),
    });
  };

  const menuItems = (project: ProjectSummary) => {
    const running = project.daemon === 'running';
    const items = project.exists
      ? [
          { key: 'start', icon: <PlayCircleOutlined />, label: '启动', disabled: running },
          { key: 'stop', icon: <PauseCircleOutlined />, label: '停止', disabled: !running },
          { type: 'divider' as const },
        ]
      : [];
    return [...items, { key: 'delete', icon: <DeleteOutlined />, label: '删除', danger: true }];
  };

  const onMenuClick = (project: ProjectSummary, key: string) => {
    if (key === 'delete') {
      confirmDelete(project);
    } else if (key === 'start' || key === 'stop') {
      void runAction(project.name, key);
    }
  };

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

  return (
    <Card
      variant="borderless"
      title="项目清单"
      extra={
        <Radio.Group
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
      }
      styles={{ body: { paddingBlock: 0 } }}
    >
      <List
        itemLayout="horizontal"
        dataSource={filtered}
        renderItem={(project) => {
          const running = project.daemon === 'running';
          const progress = pct(project.task_done, project.task_total);
          const statusTags = Object.entries(project.status_counts || {}).map(([st, n]) => {
            const m = statusMeta(st);
            return (
              <Tag key={st} color={TONE_TO_TAG[m.tone]} style={{ marginInlineEnd: 0 }}>
                {m.label} {n}
              </Tag>
            );
          });
          return (
            <List.Item
              actions={[
                <Button
                  key="enter"
                  type="link"
                  size="small"
                  style={{ paddingInline: 0 }}
                  onClick={() => history.push('/projects')}
                >
                  进入
                </Button>,
                <Dropdown
                  key="more"
                  menu={{ items: menuItems(project), onClick: ({ key }) => onMenuClick(project, key) }}
                  placement="bottomRight"
                  trigger={['click']}
                >
                  <Button type="link" size="small" icon={<MoreOutlined />}>
                    更多
                  </Button>
                </Dropdown>,
              ]}
            >
              <List.Item.Meta
                avatar={<Avatar shape="square" icon={<FolderOutlined />} />}
                title={
                  <Space wrap size={4}>
                    {project.name}
                    <DaemonBadge daemon={project.daemon} />
                    {project.discovered ? <Tag style={{ marginInlineEnd: 0 }}>自动发现</Tag> : null}
                    {pendingName === project.name ? (
                      <Tag color="processing" style={{ marginInlineEnd: 0 }}>
                        处理中…
                      </Tag>
                    ) : null}
                  </Space>
                }
                description={
                  project.exists ? (
                    <div>
                      <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                        {project.path}
                      </Typography.Text>
                      {statusTags.length > 0 ? (
                        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4, marginTop: 4 }}>
                          {statusTags}
                        </div>
                      ) : null}
                    </div>
                  ) : (
                    <Typography.Text type="danger">路径不存在 — {project.path}</Typography.Text>
                  )
                }
              />
              {project.exists ? (
                <div
                  style={{
                    display: 'flex',
                    alignItems: 'center',
                    gap: 24,
                    paddingInline: 24,
                    flexWrap: 'wrap',
                  }}
                >
                  <MiniStat label="SPEC 数" value={project.spec_count} />
                  <MiniStat
                    label="问题/阻塞"
                    value={project.problems}
                    color={project.problems > 0 ? '#ff4d4f' : undefined}
                  />
                  <MiniStat
                    label="活跃运行"
                    value={project.active_runs}
                    color={project.active_runs > 0 ? '#faad14' : undefined}
                  />
                  <div style={{ width: 150 }}>
                    <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                      任务进度
                    </Typography.Text>
                    <Progress
                      percent={progress}
                      size="small"
                      strokeColor="#1677ff"
                      trailColor={TRACK_LIGHT}
                      format={() => `${project.task_done}/${project.task_total} · ${progress}%`}
                    />
                  </div>
                </div>
              ) : null}
            </List.Item>
          );
        }}
      />
    </Card>
  );
}
