import { PageContainer } from '@ant-design/pro-components';
import { Button, Card, Menu, Select, Space, Typography, message } from 'antd';
import { useEffect, useRef, useState } from 'react';
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
import QualityPanel from './components/QualityPanel';
import ProjectProfilePanel from './components/ProjectProfilePanel';
import PromptsPanel from './components/PromptsPanel';
import SystemPanel from './components/SystemPanel';
import SelfReviewPanel from './components/SelfReviewPanel';
import HooksPanel from './components/HooksPanel';
import StaleCodeSelfhealPanel from './components/StaleCodeSelfhealPanel';
import SuggestedImprovementsPanel from './components/SuggestedImprovementsPanel';
import type { SelfEvolutionSectionHandle } from './components/selfEvolutionSection';

const { Text } = Typography;

// 页签 key → 标签 单一来源（code-review item e0b8f3aefec7）：供
// SyncFromUserButton 等子组件复用，避免手工副本漂移。BASE_MENU_ITEMS 由其派生。
export const PAGE_LABELS: Record<string, string> = {
  llm: '模型',
  agents: '模型分配',
  prompts: '提示词',
  parallel: '并行',
  token: '预算',
  verify: '验证',
  quality: '质量',
  approval: '审批',
  misc: '归档',
  system: '系统',
  'self-evolution': '自进化',
  'self-review': '自省',
  'project-profile': '项目',
  hook: 'Hook',
};

const BASE_MENU_ITEMS = [
  { key: 'llm', label: '模型' },
  { key: 'agents', label: '模型分配' },
  { key: 'prompts', label: '提示词' },
  { key: 'parallel', label: '并行' },
  { key: 'token', label: '预算' },
  { key: 'verify', label: '验证' },
  // add-quality-tab：收尾代码质量审查自「验证」页迁出为独立页签（键路径不变）
  { key: 'quality', label: '质量' },
  { key: 'approval', label: '审批' },
  { key: 'misc', label: '归档' },
  { key: 'system', label: '系统' },
  // add-framework-self-evolution：页签「自愈」改名「自进化」（内部 key 同步改名，
  // 默认选中态与其它页签不受影响）
  { key: 'self-evolution', label: '自进化' },
];

  // 作用域 Select 的值编码：'user' 或 'project:<name>'
const USER_SCOPE = 'user';

// 仅项目级存在的页签：切回用户级作用域时若停留在这些页签上，菜单项会消失、
// 选中态悬空（渲染出 project 为 undefined 的面板），必须回落到通用页签。
// 新增项目级页签时同步登记此集合（QUALITY: code-review item 66123be10772）。
const PROJECT_ONLY_KEYS = new Set(['self-review', 'project-profile', 'hook']);

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
  // 加载失败显式态（code-review item eae893169197）：旧实现仅 console.error，
  // config 停在 null，除 prompts 外的页签统统渲染空白面板，用户无从判断原因。
  const [loadError, setLoadError] = useState<string | null>(null);
  // 自进化页签：两张配置卡片各自暴露的收集句柄，供页签底部唯一「保存」按钮触发
  const staleSelfhealRef = useRef<SelfEvolutionSectionHandle>(null);
  const suggestionsRef = useRef<SelfEvolutionSectionHandle>(null);

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
    // 取消/忽略守卫（code-review item 56756944dd6e）：快速切换项目（或作用域）会
    // 触发重叠请求，较慢的早期响应可能在较新响应之后 resolve，把 config 覆盖成
    // 上一个项目的陈旧数据。用 cancelled 标志在 effect 被取代时丢弃结果。
    let cancelled = false;
    const loadConfig = async () => {
      setLoading(true);
      setLoadError(null);
      try {
        const configData = await getConfig(project);
        if (cancelled) return;
        setConfig(configData);
      } catch (e) {
        if (cancelled) return;
        const msg = e instanceof Error ? e.message : String(e);
        console.error('Failed to load config:', e);
        // 失败即清空旧 config（code-review item 35bce3eaab39）：保留旧作用域的
        // config 会在错误横幅下继续渲染上一份配置面板，用户可编辑/保存过时值
        //（把上个项目/作用域的配置写进新作用域）。清空后失败路径只渲染错误态。
        setConfig(null);
        setLoadError(msg);
      } finally {
        if (!cancelled) setLoading(false);
      }
    };
    loadConfig();
    return () => {
      cancelled = true;
    };
  }, [project, scope]); // 添加 scope 依赖，确保作用域切换时重新加载配置

  // 处理作用域选择（'user' 或 'project:<name>'）
  const handleScopeSelect = (value: string) => {
    const { scope: nextScope, project: nextProject } = decodeScopeValue(value);
    setScope(nextScope);
    setProject(nextProject);
    // 项目级页签仅项目级存在：切回用户级时不能停留在已消失的页签上
    if (nextScope === 'user' && PROJECT_ONLY_KEYS.has(activeKey)) {
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

  // 自进化页签唯一保存入口：两张卡片各自校验并收集本节配置，合并后一次提交
  // （任一卡片校验失败即中止；项目级作用域下建议改进项为只读、返回空补丁，
  // 故只提交在当前作用域可写的陈旧自愈节）。
  const handleSelfEvolutionSave = async () => {
    const parts = await Promise.all([
      staleSelfhealRef.current?.collect(),
      suggestionsRef.current?.collect(),
    ]);
    // ref 未挂载 ≠ 空收集（code-review item 51a0f171bc8c）：ref 未挂（卡片
    // 未渲染/面板卸载）时 ``?.collect()`` 得 undefined——旧空检查只拒 null
    // 哨兵，undefined 落入 ``?? {}`` 被当空数据合并：(a) 两 ref 都未挂时
    // 用户看到「没有需要保存的变更」尽管啥也没收集；(b) 部分 ref 在场时真
    // 数据与「未收集」混为一谈。undefined（面板未就绪）与 null（校验失败）
    // 分开提示，均中止保存。
    if (parts.some((p) => p === undefined)) {
      message.warning('自进化面板未就绪，无法收集本节配置，请稍后重试');
      return;
    }
    // 校验失败/无变更不再静默返回（code-review item 57ca856f0531）：旧实现两处
    // 裸 return 使用户以为已保存，实际什么都没发生。
    if (parts.some((p) => p === null)) {
      message.warning('请先修正表单校验错误');
      return;
    }
    const merged = parts.reduce<Partial<ConfigData>>(
      (acc, p) => ({ ...acc, ...(p ?? {}) }),
      {},
    );
    if (Object.keys(merged).length === 0) {
      message.info('没有需要保存的变更');
      return;
    }
    await handleSave(merged);
  };

  // 运行时构造菜单：自省与项目简介均为项目级页签，随项目级作用域出现；
  // Hook 为项目级设置置于菜单最末。项目简介页签固定名「项目」，不随项目名变长
  const menuItems = [...BASE_MENU_ITEMS];
  if (scope === 'project' && project) {
    menuItems.push({ key: 'self-review', label: '自省' });
    menuItems.push({ key: 'project-profile', label: '项目' });
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
                ? {
                    // 移动端：外层承载横向滚动。Menu 本体 width: max-content 使
                    // rc-overflow 测得的容器宽度=内容宽度，页签永不折叠成
                    // aria-hidden（原实现溢出 7 个页签不可达），全部页签留在
                    // 正常流内可横向滚动触达
                    overflowX: 'auto',
                    WebkitOverflowScrolling: 'touch',
                    borderBottom: '1px solid #f0f0f0',
                  }
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
                  ? { borderBottom: 0, width: 'max-content', minWidth: '100%' }
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
            {/* 加载失败回退 UI（code-review item eae893169197）：旧实现失败后
                config 恒为 null，非 prompts 页签全部渲染空白面板而用户无从判断。 */}
            {!loading && loadError && (
              <div style={{ color: '#ff4d4f', padding: '12px 0' }}>
                配置加载失败：{loadError}
              </div>
            )}
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
                  <LlmProviderPanel
                    config={config}
                    onSave={handleSave}
                    project={scope === 'project' ? project : undefined}
                    onConfigSynced={scope === 'project' ? setConfig : undefined}
                  />
                )}
                {activeKey === 'agents' && (
                  <AgentModelPanel
                    config={config}
                    onSave={handleSave}
                    project={scope === 'project' ? project : undefined}
                    onConfigSynced={scope === 'project' ? setConfig : undefined}
                  />
                )}
                {activeKey === 'parallel' && (
                  <ParallelSettingsPanel
                    config={config}
                    onSave={handleSave}
                    project={scope === 'project' ? project : undefined}
                    onConfigSynced={scope === 'project' ? setConfig : undefined}
                  />
                )}
                {activeKey === 'approval' && (
                  <ApprovalModePanel
                    config={config}
                    onSave={handleSave}
                    project={scope === 'project' ? project : undefined}
                    onConfigSynced={scope === 'project' ? setConfig : undefined}
                  />
                )}
                {activeKey === 'token' && (
                  <TokenBudgetPanel
                    config={config}
                    onSave={handleSave}
                    project={scope === 'project' ? project : undefined}
                    onConfigSynced={scope === 'project' ? setConfig : undefined}
                  />
                )}
                {activeKey === 'misc' && (
                  <MiscSettingsPanel
                    config={config}
                    onSave={handleSave}
                    project={scope === 'project' ? project : undefined}
                    onConfigSynced={scope === 'project' ? setConfig : undefined}
                  />
                )}
                {activeKey === 'verify' && (
                  <VerifyPanel
                    config={config}
                    onSave={handleSave}
                    project={scope === 'project' ? project : undefined}
                    onConfigSynced={scope === 'project' ? setConfig : undefined}
                  />
                )}
                {activeKey === 'quality' && (
                  <QualityPanel
                    config={config}
                    onSave={handleSave}
                    project={scope === 'project' ? project : undefined}
                    onConfigSynced={scope === 'project' ? setConfig : undefined}
                  />
                )}
                {activeKey === 'hook' && project && (
                  <HooksPanel config={config} onSave={handleSave} project={project} />
                )}
                {activeKey === 'system' && (
                  <SystemPanel
                    config={config}
                    onSave={handleSave}
                    project={scope === 'project' ? project : undefined}
                    onConfigSynced={scope === 'project' ? setConfig : undefined}
                  />
                )}
                {activeKey === 'self-review' && (
                  <SelfReviewPanel
                    config={config}
                    onSave={handleSave}
                    project={scope === 'project' ? project : undefined}
                  />
                )}
                {activeKey === 'self-evolution' && (
                  <>
                    {/* 第一张卡片：既有「代码陈旧自愈」面板（标题/控件/配置键不变） */}
                    <StaleCodeSelfhealPanel ref={staleSelfhealRef} config={config} />
                    {/* 第二张卡片：新增「建议改进项」面板（接收 scope 与 project） */}
                    <SuggestedImprovementsPanel
                      ref={suggestionsRef}
                      config={config}
                      scope={scope}
                      project={project}
                    />
                    {/* 页签唯一「保存」按钮：置于页面最下方、右对齐（与其它页签一致） */}
                    <div style={{ textAlign: 'right', marginTop: 24 }}>
                      <Button
                        type="primary"
                        onClick={handleSelfEvolutionSave}
                        data-testid="settings-save"
                      >
                        保存
                      </Button>
                    </div>
                  </>
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
