import { PageContainer } from '@ant-design/pro-components';
import { Card, Menu, Select, Space, Typography, message } from 'antd';
import { useEffect, useState } from 'react';
import { useIsMobile } from '@/hooks/useIsMobile';
import { getConfig, getOverview, saveConfig } from '@/services/dashboard';
import type { ConfigData, OverviewData } from '@/services/dashboard';
import LlmProviderPanel from './components/LlmProviderPanel';
import AgentModelPanel from './components/AgentModelPanel';
import ParallelSettingsPanel from './components/ParallelSettingsPanel';
import ApprovalModePanel from './components/ApprovalModePanel';
import TokenBudgetPanel from './components/TokenBudgetPanel';
import MiscSettingsPanel from './components/MiscSettingsPanel';
import VerifyPanel from './components/VerifyPanel';
import ProjectProfilePanel from './components/ProjectProfilePanel';
import PromptsPanel from './components/PromptsPanel';
import SystemPanel from './components/SystemPanel';
import SelfReviewPanel from './components/SelfReviewPanel';
import HooksPanel from './components/HooksPanel';

const { Text } = Typography;

const BASE_MENU_ITEMS = [
  { key: 'llm', label: '模型' },
  { key: 'agents', label: '模型分配' },
  { key: 'prompts', label: '提示词' },
  { key: 'parallel', label: '并行' },
  { key: 'token', label: '预算' },
  { key: 'verify', label: '验证' },
  { key: 'approval', label: '审批' },
  { key: 'misc', label: '归档' },
  { key: 'system', label: '系统' },
  { key: 'self-review', label: '自省' },
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
  const isMobile = useIsMobile();
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
    // Hook 页签仅项目级存在：切回用户级时不能停留在已消失的页签上
    if (nextScope === 'user' && activeKey === 'hook') {
      setActiveKey('llm');
    }
  };

  // 处理保存操作（返回是否成功：系统页签保存成功后还会连带提交 todo.md）
  const handleSave = async (values: Partial<ConfigData>): Promise<boolean> => {
    try {
      await saveConfig(project, values);
      message.success('保存成功');
      // 重新加载配置
      const configData = await getConfig(project);
      setConfig(configData);
      return true;
    } catch (error) {
      const errorMessage = error instanceof Error ? error.message : String(error);
      message.error(`保存失败：${errorMessage}`);
      console.error('Failed to save config:', error);
      return false;
    }
  };

  // 运行时构造菜单：项目级作用域时追加项目简介页签；
  // Hook 为项目级设置，随项目级作用域出现并置于菜单最末
  const menuItems = [...BASE_MENU_ITEMS];
  if (scope === 'project' && project) {
    menuItems.push({ key: 'project-profile', label: project });
    menuItems.push({ key: 'hook', label: 'Hook' });
  }

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
        {/* 移动端菜单置顶横排，面板全宽；桌面保持左竖菜单布局不变 */}
        <div
          style={
            isMobile
              ? { display: 'flex', flexDirection: 'column' }
              : { display: 'flex', minHeight: 500 }
          }
        >
          {/* 左侧菜单 */}
          <div
            style={
              isMobile
                ? { borderBottom: '1px solid #f0f0f0' }
                : { width: 224, borderRight: '1px solid #f0f0f0' }
            }
          >
            <Menu
              mode={isMobile ? 'horizontal' : 'inline'}
              selectedKeys={[activeKey]}
              onClick={({ key }) => setActiveKey(key)}
              items={menuItems}
              style={
                isMobile
                  ? { borderBottom: 0, overflowX: 'auto' }
                  : { height: '100%', borderRight: 0 }
              }
            />
          </div>
          {/* 右侧面板 */}
          <div
            style={
              isMobile
                ? { flex: 1, minWidth: 0, padding: '12px 16px 24px' }
                : { flex: 1, padding: 24, marginTop: -30 }
            }
          >
            {loading && <div>加载中...</div>}
            {/* 提示词页签不依赖 config（读取 agents/*.md 与 .fenix/agents/），独立于配置守卫渲染 */}
            {!loading && activeKey === 'prompts' && (
              <PromptsPanel project={scope === 'project' ? project : undefined} />
            )}
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
                {activeKey === 'misc' && (
                  <MiscSettingsPanel config={config} onSave={handleSave} />
                )}
                {activeKey === 'verify' && (
                  <VerifyPanel config={config} onSave={handleSave} />
                )}
                {activeKey === 'hook' && project && (
                  <HooksPanel config={config} onSave={handleSave} project={project} />
                )}
                {activeKey === 'system' && (
                  <SystemPanel config={config} onSave={handleSave} />
                )}
                {activeKey === 'self-review' && (
                  <SelfReviewPanel
                    config={config}
                    onSave={handleSave}
                    project={scope === 'project' ? project : undefined}
                  />
                )}
                {activeKey === 'project-profile' && (
                  <ProjectProfilePanel config={config} onSave={handleSave} project={project} />
                )}
              </>
            )}
          </div>
        </div>
      </Card>
    </PageContainer>
  );
}
