import { DeleteOutlined, PauseCircleOutlined, PlayCircleOutlined } from '@ant-design/icons';
import { Alert, App, Button, Card, Popconfirm, Progress, Space, Tag, Typography } from 'antd';
import { useState } from 'react';
import type { ReactNode } from 'react';
import type { ProjectSummary, StatusTone } from '@/services/dashboard';
import { deleteProject, startProject, statusMeta, stopProject } from '@/services/dashboard';

const TRACK_LIGHT = '#e6f4ff';

const TONE_TO_TAG: Record<StatusTone, string> = {
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

function MiniStat({ label, value, color }: { label: string; value: ReactNode; color?: string }) {
  return (
    <div style={{ minWidth: 0 }}>
      <Typography.Text type="secondary" style={{ fontSize: 12 }}>
        {label}
      </Typography.Text>
      <div style={{ fontSize: 18, fontWeight: 600, color }}>{value}</div>
    </div>
  );
}

function ProjectCard({
  project,
  pending,
  onAction,
}: {
  project: ProjectSummary;
  pending: boolean;
  onAction: (name: string, action: 'start' | 'stop' | 'delete') => Promise<void>;
}) {
  if (!project.exists) {
    return (
      <Card
        size="small"
        style={{ borderColor: '#ffccc7' }}
        title={
          <Space wrap>
            {project.name}
            <Tag color="error">路径不存在</Tag>
          </Space>
        }
      >
        <Typography.Text type="secondary">{project.path}</Typography.Text>
      </Card>
    );
  }

  const running = project.daemon === 'running';
  const progress = pct(project.task_done, project.task_total);
  const statusTags = Object.entries(project.status_counts || {}).map(([st, n]) => {
    const m = statusMeta(st);
    return (
      <Tag key={st} color={TONE_TO_TAG[m.tone]}>
        {m.label} {n}
      </Tag>
    );
  });

  const softDeleteHint =
    `确认从监控移除项目「${project.name}」？\n\n` +
    '该项目 daemon 会被停止，但项目文件、STATE.md、openspec/、.fenix/ 等数据全部保留在磁盘。\n' +
    '此操作仅为"软删除"——可通过手工编辑 ~/.config/fenixd/dashboard.yaml，' +
    '从 ignored 列表中删除对应路径来恢复监控。';

  return (
    <Card
      size="small"
      title={
        <Space wrap size={4}>
          {project.name}
          <DaemonBadge daemon={project.daemon} />
          {project.discovered ? <Tag>自动发现</Tag> : null}
        </Space>
      }
    >
      <Typography.Paragraph type="secondary" style={{ marginBottom: 12, fontSize: 12 }} ellipsis>
        {project.path}
      </Typography.Paragraph>

      <div
        style={{
          display: 'flex',
          gap: 24,
          marginBottom: 12,
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
      </div>

      <div style={{ marginBottom: 12 }}>
        <Progress
          percent={progress}
          size="small"
          strokeColor="#1677ff"
          trailColor={TRACK_LIGHT}
          format={() => `${project.task_done}/${project.task_total} · ${progress}%`}
        />
      </div>

      {statusTags.length > 0 ? (
        <div style={{ marginBottom: 12, display: 'flex', flexWrap: 'wrap', gap: 4 }}>
          {statusTags}
        </div>
      ) : null}

      <Space size={8} onClick={(e) => e.stopPropagation()}>
        <Button
          size="small"
          icon={<PlayCircleOutlined />}
          disabled={running || pending}
          loading={pending}
          onClick={() => onAction(project.name, 'start')}
        >
          启动
        </Button>
        <Button
          size="small"
          icon={<PauseCircleOutlined />}
          disabled={!running || pending}
          onClick={() => onAction(project.name, 'stop')}
        >
          停止
        </Button>
        <Popconfirm
          title="移除项目监控"
          description={<div style={{ whiteSpace: 'pre-wrap', maxWidth: 320 }}>{softDeleteHint}</div>}
          okText="移除"
          okButtonProps={{ danger: true }}
          cancelText="取消"
          onConfirm={() => onAction(project.name, 'delete')}
          disabled={pending}
        >
          <Button size="small" danger icon={<DeleteOutlined />} disabled={pending}>
            删除
          </Button>
        </Popconfirm>
      </Space>
    </Card>
  );
}

export default function ProjectCards({
  projects,
  onChanged,
}: {
  projects: ProjectSummary[];
  onChanged: () => void;
}) {
  const { message } = App.useApp();
  const [pendingName, setPendingName] = useState('');

  const handleAction = async (name: string, action: 'start' | 'stop' | 'delete') => {
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
    <div
      style={{
        display: 'grid',
        gridTemplateColumns: 'repeat(auto-fill, minmax(340px, 1fr))',
        gap: 16,
      }}
    >
      {projects.map((p) => (
        <ProjectCard
          key={p.name}
          project={p}
          pending={pendingName === p.name}
          onAction={handleAction}
        />
      ))}
    </div>
  );
}
