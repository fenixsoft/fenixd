import { PageContainer } from '@ant-design/pro-components';
import { Card, ConfigProvider, Menu, Select, Space, Typography, theme, message } from 'antd';
import { useEffect, useState } from 'react';
import { history } from '@umijs/max';
import { getConfig, getOverview, saveConfig } from '@/services/dashboard';
import type { ConfigData, OverviewData } from '@/services/dashboard';
import LlmProviderPanel from './components/LlmProviderPanel';
import AgentModelPanel from './components/AgentModelPanel';
import ParallelSettingsPanel from './components/ParallelSettingsPanel';
import ApprovalModePanel from './components/ApprovalModePanel';
import TokenBudgetPanel from './components/TokenBudgetPanel';
import ThemePanel from './components/ThemePanel';

const { Text } = Typography;

const MENU_ITEMS = [
  { key: 'llm', label: 'LLM Provider' },
  { key: 'agents', label: 'Agent 模型分配' },
  { key: 'parallel', label: '并行度设置' },
  { key: 'approval', label: '审批模式' },
  { key: 'token', label: 'Token 预算' },
  { key: 'theme', label: '界面风格' },
];

// 从 location 解析 URL query（兼容 hash 路由模式与 search 模式）
function parseSearchParams(location: { search?: string; hash?: string }): URLSearchParams {
  if (location.search) {
    return new URLSearchParams(location.search);
  }
  const hash = location.hash || '';
  const questionMarkIndex = hash.indexOf('?');
  if (questionMarkIndex >= 0) {
    return new URLSearchParams(hash.substring(questionMarkIndex + 1));
  }
  return new URLSearchParams();
}

export default function SettingsPage() {
  const [activeKey, setActiveKey] = useState('llm');

  // 从 URL query 解析初始状态（支持 hash 路由模式）
  const getInitialScope = () => {
    const params = parseSearchParams(history.location);
    return (params.get('scope') as 'user' | 'project') || 'user';
  };
  const getInitialProject = () => {
    const params = parseSearchParams(history.location);
    return params.get('project') || undefined;
  };

  const [scope, setScope] = useState<'user' | 'project'>(getInitialScope());
  const [project, setProject] = useState<string | undefined>(getInitialProject());
  const [config, setConfig] = useState<ConfigData | null>(null);
  const [projects, setProjects] = useState<string[]>([]);
  const [loading, setLoading] = useState(false);
  const [currentTheme, setCurrentTheme] = useState<'light' | 'dark'>(
    (localStorage.getItem('fenix.theme') as 'light' | 'dark') || 'dark',
  );

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

  // 更新 URL 参数
  useEffect(() => {
    const params = new URLSearchParams();
    if (scope === 'project' && project) {
      params.set('scope', 'project');
      params.set('project', project);
    } else {
      params.set('scope', 'user');
    }
    history.push(`/settings?${params.toString()}`);
  }, [scope, project]);

  // 监听 URL 变化（浏览器前进/后退按钮）
  useEffect(() => {
    const unlisten = history.listen((location) => {
      const params = parseSearchParams(location);
      const newScope = (params.get('scope') as 'user' | 'project') || 'user';
      const newProject = params.get('project') || undefined;

      // 只有当 URL 参数与当前状态不同时才更新
      if (newScope !== scope) {
        setScope(newScope);
      }
      if (newProject !== project) {
        setProject(newProject);
      }
    });
    return () => unlisten();
  }, [scope, project]);

  // 处理作用域切换
  const handleScopeChange = (value: 'user' | 'project') => {
    setScope(value);
    if (value === 'user') {
      setProject(undefined);
    } else if (projects.length > 0 && !project) {
      setProject(projects[0]);
    }
  };

  // 处理项目切换
  const handleProjectChange = (value: string) => {
    setProject(value);
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

  // 处理主题切换
  const handleThemeChange = (theme: 'light' | 'dark') => {
    setCurrentTheme(theme);
  };

  return (
    <ConfigProvider
      theme={{
        algorithm: currentTheme === 'dark' ? theme.darkAlgorithm : theme.defaultAlgorithm,
      }}
    >
      <PageContainer
        header={{
          title: '设置',
          breadcrumb: {
            items: [{ title: '设置' }],
          },
          extra: (
            <Space>
              <Text>作用域：</Text>
              <Select
                value={scope}
                onChange={handleScopeChange}
                style={{ width: 120 }}
                options={[
                  { value: 'user', label: '用户级' },
                  { value: 'project', label: '项目级' },
                ]}
              />
              {scope === 'project' && (
                <Select
                  value={project}
                  onChange={handleProjectChange}
                  placeholder="选择项目"
                  style={{ width: 200 }}
                  options={projects.map((p) => ({ value: p, label: p }))}
                />
              )}
            </Space>
          ),
        }}
      >
        <Card bordered={false}>
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
            <div style={{ flex: 1, padding: 24 }}>
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
                  {activeKey === 'theme' && (
                    <ThemePanel onThemeChange={handleThemeChange} />
                  )}
                  {/* 继承标注 */}
                  {config.sources && Object.keys(config.sources).length > 0 && (
                    <div style={{ marginTop: 24 }}>
                      <h4>配置来源</h4>
                      <ul>
                        {Object.entries(config.sources).map(([key, source]) => (
                          <li key={key}>
                            {key}: {source === 'user' ? '继承自用户级' : '项目级'}
                          </li>
                        ))}
                      </ul>
                    </div>
                  )}
                </>
              )}
            </div>
          </div>
        </Card>
      </PageContainer>
    </ConfigProvider>
  );
}
