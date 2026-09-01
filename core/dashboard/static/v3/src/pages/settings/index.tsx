import { PageContainer } from '@ant-design/pro-components';
import { Card, Menu, Select, Space, Typography, message } from 'antd';
import { useEffect, useState } from 'react';
import { getConfig, getOverview, saveConfig } from '@/services/dashboard';
import type { ConfigData, OverviewData } from '@/services/dashboard';
import LlmProviderPanel from './components/LlmProviderPanel';
import AgentModelPanel from './components/AgentModelPanel';
import ParallelSettingsPanel from './components/ParallelSettingsPanel';
import ApprovalModePanel from './components/ApprovalModePanel';
import TokenBudgetPanel from './components/TokenBudgetPanel';

const { Text } = Typography;

const MENU_ITEMS = [
  { key: 'llm', label: 'LLM Provider' },
  { key: 'agents', label: 'Agent 模型分配' },
  { key: 'parallel', label: '并行度设置' },
  { key: 'approval', label: '审批模式' },
  { key: 'token', label: 'Token 预算' },
];

// 作用域 Select 的值编码：'user' 或 'project:<name>'
const USER_SCOPE = 'user';

function decodeScopeValue(value: string): { scope: 'user' | 'project'; project?: string } {
  if (value.startsWith('project:')) {
    return { scope: 'project', project: value.slice('project:'.length) };
  }
  return { scope: 'user' };
}

export default function SettingsPage() {
  const [activeKey, setActiveKey] = useState('llm');
  const [scope, setScope] = useState<'user' | 'project'>('user');
  const [project, setProject] = useState<string | undefined>(undefined);
  const [config, setConfig] = useState<ConfigData | null>(null);
  const [projects, setProjects] = useState<string[]>([]);
  const [loading, setLoading] = useState(false);

  // 加载项目列表
  useEffect(() => {
    const loadProjects = async () => {
      try {
        const data: OverviewData = await getOverview();
        setProjects(data.projects.map((p) => p.name));
      } catch (e) {
        console.error('Failed to load projects:', e);
      }
    };
    loadProjects();
  }, []);

  // 加载配置
  useEffect(() => {
    const loadConfig = async () => {
      setLoading(true);
      try {
        const configData = await getConfig(project);
        setConfig(configData);
      } catch (e) {
        console.error('Failed to load config:', e);
      } finally {
        setLoading(false);
      }
    };
    loadConfig();
  }, [project, scope]); // 添加 scope 依赖，确保作用域切换时重新加载配置

  // 处理作用域选择（'user' 或 'project:<name>'）
  const handleScopeSelect = (value: string) => {
    const { scope: nextScope, project: nextProject } = decodeScopeValue(value);
    setScope(nextScope);
    setProject(nextProject);
  };

  // 处理保存操作
  const handleSave = async (values: Partial<ConfigData>) => {
    try {
      await saveConfig(project, values);
      message.success('保存成功');
      // 重新加载配置
      const configData = await getConfig(project);
      setConfig(configData);
    } catch (error) {
      const errorMessage = error instanceof Error ? error.message : String(error);
      message.error(`保存失败：${errorMessage}`);
      console.error('Failed to save config:', error);
    }
  };

  return (
    <PageContainer
      header={{
        title: '设置',
        extra: (
          <Space>
            <Text>作用域：</Text>
            <Select
              value={scope === 'user' ? USER_SCOPE : `project:${project}`}
              onChange={handleScopeSelect}
              style={{ width: 200 }}
              options={[
                { value: USER_SCOPE, label: '用户级' },
                ...projects.map((p) => ({ value: `project:${p}`, label: `项目级：${p}` })),
              ]}
            />
          </Space>
        ),
      }}
    >
      <Card bordered={false} className="settings-page">
        <div style={{ display: 'flex', minHeight: 500 }}>
          {/* 左侧菜单 */}
          <div style={{ width: 224, borderRight: '1px solid #f0f0f0' }}>
            <Menu
              mode="inline"
              selectedKeys={[activeKey]}
              onClick={({ key }) => setActiveKey(key)}
              items={MENU_ITEMS}
              style={{ height: '100%', borderRight: 0 }}
            />
          </div>
          {/* 右侧面板 */}
          <div style={{ flex: 1, padding: 24, marginTop: -30 }}>
            {loading && <div>加载中...</div>}
            {!loading && config && (
              <>
                {/* 配置状态提示 */}
                {!config.raw_exists && (
                  <div style={{ marginBottom: 16, color: '#faad14' }}>
                    项目尚无配置文件，表单为默认值
                  </div>
                )}
                {config.error && (
                  <div style={{ marginBottom: 16, color: '#ff4d4f' }}>
                    配置加载错误：{config.error}
                  </div>
                )}
                {activeKey === 'llm' && (
                  <LlmProviderPanel config={config} onSave={handleSave} />
                )}
                {activeKey === 'agents' && (
                  <AgentModelPanel config={config} onSave={handleSave} />
                )}
                {activeKey === 'parallel' && (
                  <ParallelSettingsPanel config={config} onSave={handleSave} />
                )}
                {activeKey === 'approval' && (
                  <ApprovalModePanel config={config} onSave={handleSave} />
                )}
                {activeKey === 'token' && (
                  <TokenBudgetPanel config={config} onSave={handleSave} />
                )}
              </>
            )}
          </div>
        </div>
      </Card>
    </PageContainer>
  );
}
