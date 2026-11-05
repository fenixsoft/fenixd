// /v2/settings — v2 配置页（redesign-dashboard-v2-ui 2.4）。
//
// UI 真相源：spec/changes/redesign-dashboard-v2-ui/prototype/settings.html
// （标题带 + 作用域切换 + 左侧菜单磁贴 + LLM Provider 表格面板与开关行）。
// 数据消费既有配置端点（getConfig/saveConfig/checkLlmHealth）；开关注入真实
// config 键（knowledge / stale_code_selfheal / self_evolution，缺省值与后端
// 一致）。原型「编辑/新增 Provider」在 v2 域承载为跳转现产配置页（编辑表单
// 单源在 /settings，v2 不复制第二份编辑链路）；其余菜单分面为占位说明。
import { Alert, App, Button, Select, Space, Spin, Switch, Table } from 'antd';
import type { ColumnsType } from 'antd/es/table';
import { useCallback, useEffect, useMemo, useState } from 'react';
import { useNavigate } from '@umijs/max';
import {
  checkLlmHealth,
  getConfig,
  getOverview,
  saveConfig,
} from '@/services/dashboard';
import type { ConfigData, LlmProvider } from '@/services/dashboard';
import { V2Page, V2Pill, V2TitleBand } from './shared';
import { V2_HAIRLINE, V2_TEXT, V2_TEXT_QUATERNARY, V2_TEXT_TERTIARY } from './theme';

// 左侧菜单分面（原型 MENU；v2 域当前仅 llm 分面有实体面板，其余占位说明）
const MENU: Array<[string, string]> = [
  ['llm', '模型与网关'],
  ['agents', '角色模型'],
  ['prompts', '提示词'],
  ['parallel', '并行调度'],
  ['token', 'Token 与计费'],
  ['verify', '验证管线'],
  ['quality', '质量门禁'],
  ['approval', '审批推送'],
  ['arbiter', '仲裁'],
  ['self-evolution', '自进化'],
  ['system', '系统'],
];

type HealthState = { loading: boolean; ok?: boolean; text?: string };

function LlmPanel({ cfg, project, onChanged }: { cfg: ConfigData; project?: string; onChanged: () => void }) {
  const navigate = useNavigate();
  const { message } = App.useApp();
  const providers = cfg.llm?.providers || [];
  // 行内健康检测状态（provider.name → 检测中/结果）
  const [health, setHealth] = useState<Record<string, HealthState>>({});

  const runHealth = async (p: LlmProvider) => {
    setHealth((s) => ({ ...s, [p.name]: { loading: true } }));
    try {
      const res = await checkLlmHealth({ baseurl: p.baseurl, apikey: p.apikey, model: p.model || '' });
      setHealth((s) => ({
        ...s,
        [p.name]: {
          loading: false,
          ok: res.ok,
          text: res.ok ? `正常 ${Math.round(res.latency_ms)}ms` : res.error || '失败',
        },
      }));
    } catch (e) {
      setHealth((s) => ({
        ...s,
        [p.name]: { loading: false, ok: false, text: e instanceof Error ? e.message : String(e) },
      }));
    }
  };

  const columns: ColumnsType<LlmProvider> = [
    {
      title: 'Provider',
      dataIndex: 'name',
      render: (v: string) => <span style={{ fontSize: 13, fontWeight: 600 }}>{v}</span>,
    },
    {
      title: '网关地址',
      dataIndex: 'baseurl',
      render: (v: string) => (
        <span className="v2-num" style={{ fontSize: 12, color: V2_TEXT_TERTIARY }}>{v}</span>
      ),
    },
    {
      title: '默认模型',
      dataIndex: 'model',
      render: (v?: string) =>
        v ? <span className="v2-num" style={{ fontSize: 13 }}>{v}</span> : <span className="v2-num" style={{ color: V2_TEXT_QUATERNARY }}>—</span>,
    },
    {
      title: '健康',
      key: 'health',
      width: 170,
      render: (_, p) => {
        const st = health[p.name];
        if (!st || st.loading || st.ok === undefined) return <V2Pill tone="muted">未检测</V2Pill>;
        return st.ok ? <V2Pill tone="good">{st.text}</V2Pill> : <V2Pill tone="critical">{st.text}</V2Pill>;
      },
    },
    {
      title: '操作',
      key: 'act',
      width: 190,
      align: 'right',
      render: (_, p) => (
        <Space size={8}>
          <Button size="small" loading={health[p.name]?.loading} onClick={() => void runHealth(p)}>
            健康检测
          </Button>
          {/* 编辑表单单源在现产配置页（v2 域不复制第二份编辑链路） */}
          <Button size="small" onClick={() => navigate('/settings')}>
            编辑
          </Button>
        </Space>
      ),
    },
  ];

  return (
    <div className="v2-bento" data-proto-id="st-panel-llm" style={{ flex: 1, minWidth: 0, padding: '4px 20px 16px' }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 12, padding: '14px 0 6px' }}>
        <span style={{ fontSize: 16, fontWeight: 700 }}>模型与网关</span>
        <span style={{ flex: 1 }} />
        <Button type="primary" size="small" onClick={() => navigate('/settings')}>
          新增 Provider
        </Button>
      </div>
      <div className="v2-bento-table">
        <Table
          columns={columns}
          dataSource={providers}
          rowKey="name"
          pagination={false}
          size="middle"
          locale={{ emptyText: '未配置 Provider' }}
        />
      </div>
      <div data-proto-id="st-panel-llm-extra" style={{ borderTop: `1px solid ${V2_HAIRLINE}`, marginTop: 12, paddingTop: 8 }}>
        <SwitchRow
          label="知识真相源总开关"
          desc="spec/knowledge 知识目录的消费与投递链路总开关（缺省开）"
          checked={cfg.knowledge?.enabled ?? true}
          project={project}
          onToggle={(v) => saveConfig(project, { knowledge: { ...(cfg.knowledge || {}), enabled: v } })}
          onDone={() => {
            message.success('已保存');
            onChanged();
          }}
        />
        <SwitchRow
          label="知识维护车道"
          desc="inbox 消费 / 域页维护等自动化维护车道开关（缺省开）"
          checked={cfg.knowledge?.audit_enabled ?? true}
          project={project}
          onToggle={(v) => saveConfig(project, { knowledge: { ...(cfg.knowledge || {}), audit_enabled: v } })}
          onDone={() => {
            message.success('已保存');
            onChanged();
          }}
        />
        <SwitchRow
          label="代码陈旧自愈"
          desc="陈旧 worktree + 托管项目连续空闲达阈值后自动请求重启（缺省开）"
          checked={cfg.stale_code_selfheal?.enabled ?? true}
          project={project}
          onToggle={(v) => saveConfig(project, { stale_code_selfheal: { ...(cfg.stale_code_selfheal || {}), enabled: v } })}
          onDone={() => {
            message.success('已保存');
            onChanged();
          }}
        />
        <SwitchRow
          label="自进化自动接受"
          desc="允许框架自改进：自动接受全部判定值得立项的条目（缺省关）"
          checked={cfg.self_evolution?.auto_accept ?? false}
          project={project}
          onToggle={(v) => saveConfig(project, { self_evolution: { ...(cfg.self_evolution || {}), auto_accept: v } })}
          onDone={() => {
            message.success('已保存');
            onChanged();
          }}
        />
      </div>
    </div>
  );
}

/** 开关行（原型 Row 形态；真实 config 键 + saveConfig 持久化）。 */
function SwitchRow({
  label,
  desc,
  checked,
  project,
  onToggle,
  onDone,
}: {
  label: string;
  desc: string;
  checked: boolean;
  project?: string;
  onToggle: (v: boolean) => Promise<unknown>;
  onDone: () => void;
}) {
  const { message } = App.useApp();
  const [busy, setBusy] = useState(false);
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 14, padding: '10px 0', borderBottom: `1px solid ${V2_HAIRLINE}` }}>
      <div style={{ minWidth: 0 }}>
        <div style={{ fontSize: 13, fontWeight: 600 }}>{label}</div>
        <div style={{ fontSize: 12, color: V2_TEXT_TERTIARY, marginTop: 2 }}>{desc}</div>
      </div>
      <span style={{ flex: 1 }} />
      <Switch
        size="small"
        checked={checked}
        loading={busy}
        onChange={async (v) => {
          setBusy(true);
          try {
            await onToggle(v);
            onDone();
          } catch (e) {
            message.error(`保存失败：${e instanceof Error ? e.message : String(e)}`);
          } finally {
            setBusy(false);
          }
        }}
        aria-label={`${label}（${project ? '项目级' : '用户级'}）`}
      />
    </div>
  );
}

function PlaceholderPanel({ label }: { label: string }) {
  const navigate = useNavigate();
  return (
    <div className="v2-bento" style={{ flex: 1, minWidth: 0, padding: '28px 22px' }}>
      <div style={{ fontSize: 14, fontWeight: 600 }}>{label}分面</div>
      <div style={{ fontSize: 12, color: V2_TEXT_TERTIARY, marginTop: 6 }}>
        该分面在 v2 域尚未展开，完整编辑请走现产配置页。
      </div>
      <Button size="small" style={{ marginTop: 12 }} onClick={() => navigate('/settings')}>
        打开现产配置页
      </Button>
    </div>
  );
}

export default function V2SettingsPage() {
  // 作用域：undefined=用户级，否则项目名
  const [scope, setScope] = useState<string | undefined>(undefined);
  const [projects, setProjects] = useState<string[]>([]);
  const [cfg, setCfg] = useState<ConfigData | null>(null);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(true);
  const [menu, setMenu] = useState('llm');

  const load = useCallback(async (s: string | undefined) => {
    setLoading(true);
    try {
      const c = await getConfig(s);
      setCfg(c);
      setError('');
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load(scope);
  }, [load, scope]);

  useEffect(() => {
    // 项目级作用域候选来自真实项目清单
    getOverview()
      .then((ov) => setProjects((ov.projects || []).map((p) => p.name)))
      .catch(() => setProjects([]));
  }, []);

  const scopeOptions = useMemo(
    () => [
      { value: 'user', label: '用户级' },
      ...projects.map((p) => ({ value: p, label: `项目级：${p}` })),
    ],
    [projects],
  );

  const activeLabel = MENU.find(([k]) => k === menu)?.[1] || '';

  return (
    <V2Page>
      <V2TitleBand
        title="配置"
        subtitle="网关、角色、调度与门禁的集中配置"
        right={
          <Select
            size="small"
            style={{ width: 190 }}
            value={scope || 'user'}
            onChange={(v) => setScope(v === 'user' ? undefined : v)}
            options={scopeOptions}
          />
        }
      />
      {error ? (
        <Alert type="error" showIcon style={{ marginTop: 16 }} message="配置加载失败" description={error} />
      ) : null}
      <div data-proto-id="st-layout" style={{ display: 'flex', gap: 16, marginTop: 18, alignItems: 'flex-start' }}>
        <div className="v2-bento" data-proto-id="st-menu" style={{ width: 230, flexShrink: 0, padding: 10 }}>
          {MENU.map(([k, label]) => (
            <div
              key={k}
              role="button"
              tabIndex={0}
              onClick={() => setMenu(k)}
              onKeyDown={(e) => {
                if (e.key === 'Enter' || e.key === ' ') setMenu(k);
              }}
              style={{
                padding: '8px 12px',
                borderRadius: 8,
                fontSize: 13,
                cursor: 'pointer',
                fontWeight: menu === k ? 600 : 400,
                color: menu === k ? V2_TEXT : V2_TEXT_TERTIARY,
                background: menu === k ? '#f1f5f9' : 'transparent',
              }}
            >
              {label}
            </div>
          ))}
        </div>
        {loading && !cfg ? (
          <div className="v2-bento" style={{ flex: 1, padding: 48, textAlign: 'center' }}>
            <Spin size="large" />
          </div>
        ) : cfg ? (
          menu === 'llm' ? (
            <LlmPanel cfg={cfg} project={scope} onChanged={() => void load(scope)} />
          ) : (
            <PlaceholderPanel label={activeLabel} />
          )
        ) : null}
      </div>
    </V2Page>
  );
}
