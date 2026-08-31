// Fenix Dashboard v3 API 封装 — 复用 v1 后端（/api/*，同源直连，开发期经 umi proxy）

export type DaemonHealth = string;

export interface ProjectSummary {
  name: string;
  path: string;
  daemon: DaemonHealth;
  spec_count: number;
  status_counts: Record<string, number>;
  task_done: number;
  task_total: number;
  problems: number;
  active_runs: number;
  scenario_count: number;
  updated: number;
  exists?: boolean;
  discovered?: boolean;
  error?: string;
}

export interface OverviewTotals {
  spec_count: number;
  task_done: number;
  task_total: number;
  problems: number;
  active_runs: number;
  status_counts: Record<string, number>;
}

export interface OverviewData {
  projects: ProjectSummary[];
  totals: OverviewTotals;
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(path, init);
  if (!res.ok) {
    let msg = `HTTP ${res.status}`;
    try {
      const body = await res.json();
      if (body?.error) msg = body.error;
    } catch {
      // 非 JSON 错误体，保留 HTTP 状态码信息
    }
    throw new Error(msg);
  }
  return res.json() as Promise<T>;
}

export async function getOverview(): Promise<OverviewData> {
  return request<OverviewData>('/api/overview');
}

export function startProject(name: string) {
  return request(`/api/projects/${encodeURIComponent(name)}/start`, { method: 'POST' });
}

export function stopProject(name: string) {
  return request(`/api/projects/${encodeURIComponent(name)}/stop`, { method: 'POST' });
}

export function deleteProject(name: string) {
  return request(`/api/projects/${encodeURIComponent(name)}`, { method: 'DELETE' });
}

// ── SPEC 状态元数据（中文标签 + 语义色，与 v1 STATUS_META 对齐） ──

export type StatusTone = 'muted' | 'info' | 'warning' | 'critical' | 'good' | 'aqua';

export const STATUS_META: Record<string, { label: string; tone: StatusTone }> = {
  drafted: { label: '草稿', tone: 'muted' },
  ready: { label: '就绪', tone: 'info' },
  implementing: { label: '实现中', tone: 'warning' },
  implemented: { label: '已实现', tone: 'aqua' },
  testing: { label: '验证中', tone: 'info' },
  verified: { label: '已验证', tone: 'good' },
  'bug-found': { label: '有Bug', tone: 'critical' },
  blocked: { label: '阻塞', tone: 'critical' },
  done: { label: '完成', tone: 'good' },
  pushed: { label: '已推送', tone: 'good' },
};

export function statusMeta(status: string): { label: string; tone: StatusTone } {
  return STATUS_META[status] || { label: status || '未知', tone: 'muted' };
}
