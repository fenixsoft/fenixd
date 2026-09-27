import { PageContainer } from '@ant-design/pro-components';
import { Button, Card, Menu, Select, Space, Typography, message } from 'antd';
import { useEffect, useRef, useState } from 'react';
import { useIsMobile } from '@/hooks/useIsMobile';
import { getConfig, getOverview, saveConfig } from '@/services/dashboard';
import type { ConfigData, OverviewData } from '@/services/dashboard';
// PAGE_LABELS 单一来源移入无依赖共享模块（code-review item 6df16f377728）：
// 子组件不再从本文件反向导入，消除 index → panels → button → index 模块循环。
import { PAGE_LABELS } from './pageLabels';
// 页签/作用域切换丢弃确认（code-review item 8a3eb01dc2b9）：活跃面板判脏
import { anyPanelDirty, resetPanelDirty } from './panelDirty';
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

// 菜单标签统一从 PAGE_LABELS 派生（code-review item d996f0d0aac5）：旧实现
// 标签字面在 BASE_MENU_ITEMS 与下方项目级 menuItems.push 各写一份，本文件
// 从不读取 PAGE_LABELS——标签编辑会在菜单与 SyncFromUserButton 等消费方
// 之间漂移。现标签单点取自共享模块，本数组只声明页签顺序与键。
const BASE_MENU_ITEMS = [
  { key: 'llm', label: PAGE_LABELS.llm },
  { key: 'agents', label: PAGE_LABELS.agents },
  { key: 'prompts', label: PAGE_LABELS.prompts },
  { key: 'parallel', label: PAGE_LABELS.parallel },
  { key: 'token', label: PAGE_LABELS.token },
  { key: 'verify', label: PAGE_LABELS.verify },
  // add-quality-tab：收尾代码质量审查自「验证」页迁出为独立页签（键路径不变）
  { key: 'quality', label: PAGE_LABELS.quality },
  { key: 'approval', label: PAGE_LABELS.approval },
  { key: 'misc', label: PAGE_LABELS.misc },
  { key: 'system', label: PAGE_LABELS.system },
  // add-framework-self-evolution：页签「自愈」改名「自进化」（内部 key 同步改名，
  // 默认选中态与其它页签不受影响）
  { key: 'self-evolution', label: PAGE_LABELS['self-evolution'] },
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
  // 最新 scope/project 镜像 ref（code-review item f51b1468ca4f）：保存后重载
  // 完成时与发起保存时的值比对，用户已切换作用域/项目则丢弃过时重载结果。
  const scopeRef = useRef(scope);
  const projectRef = useRef(project);
  useEffect(() => {
    scopeRef.current = scope;
    projectRef.current = project;
  }, [scope, project]);
  // 加载失败显式态（code-review item eae893169197）：旧实现仅 console.error，
  // config 停在 null，除 prompts 外的页签统统渲染空白面板，用户无从判断原因。
  const [loadError, setLoadError] = useState<string | null>(null);
  // 自进化页签：两张配置卡片各自暴露的收集句柄，供页签底部唯一「保存」按钮触发
  const staleSelfhealRef = useRef<SelfEvolutionSectionHandle>(null);
  const suggestionsRef = useRef<SelfEvolutionSectionHandle>(null);
  // 自进化保存重入守卫（code-review item d64feaab59a4）：对齐其余页签保存
  // 按钮的 saving 口径（SelfReview/TokenBudget/Verify/ProjectProfile 均为
  // saving 期间置 loading/disabled 并在入口短路），覆盖 collect 校验 →
  // 保存 → 重载整条异步链；setSaving 渲染生效存在 React 调度间隙（同
  // ProjectProfilePanel autodraft 的双击穿透实证），经 savingRef 写读同帧
  // 原子拦住连点，state 只负责按钮视觉反馈。
  const [saving, setSaving] = useState(false);
  const savingRef = useRef(false);
  // 质量页签「手工编辑」→「项目简介」页签聚焦信号（时间戳；0=无待处理信号）
  const [verifyFocusSignal, setVerifyFocusSignal] = useState(0);

  // 加载项目列表
  useEffect(() => {
    const loadProjects = async () => {
      try {
        const data: OverviewData = await getOverview();
        setProjects(data.projects.map((p) => p.name));
      } catch (e) {
        console.error('Failed to load projects:', e);
        // 项目列表失败非阻断提示（code-review item 6776b8ee2ba9）：projects 停在
        // 空数组，作用域下拉只剩「用户级」，项目级页签与回归质量配置全部不可达，
        // 仅 console.error 会让用户误以为尚未注册任何项目。比照保存后刷新失败的
        // message.warning 口径提示，不与配置加载失败的 loadError 横幅混为一谈。
        message.warning(
          `项目列表加载失败，项目级作用域暂不可用：${e instanceof Error ? e.message : String(e)}`,
        );
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

  // 页签/作用域切换丢弃确认（code-review item 8a3eb01dc2b9）：右侧面板按
  // activeKey 条件渲染，切页签/切作用域即卸载当前面板、未保存的编辑随之丢弃。
  // 与 PromptsPanel 的切项目确认（f2830281595d）统一口径：切换前活跃面板有
  // 未保存改动则先询问，拒绝则原地不动（Menu/Select 均受控，取消不掉显示态）。
  const confirmDiscardPanelEdits = (): boolean => {
    if (!anyPanelDirty()) return true;
    return window.confirm('当前页签的修改尚未保存，切换将丢弃，确定继续？');
  };

  // 处理作用域选择（'user' 或 'project:<name>'）
  const handleScopeSelect = (value: string) => {
    const { scope: nextScope, project: nextProject } = decodeScopeValue(value);
    // 同值选择不触发切换（rc-select 不回调，防御性兜底），避免误弹丢弃确认
    if (nextScope === scope && nextProject === project) return;
    // 切换会重载配置并卸载当前面板：有未保存改动先确认再放行
    if (!confirmDiscardPanelEdits()) return;
    setScope(nextScope);
    setProject(nextProject);
    // 项目级页签仅项目级存在：切回用户级时不能停留在已消失的页签上
    if (nextScope === 'user' && PROJECT_ONLY_KEYS.has(activeKey)) {
      setActiveKey('llm');
    }
  };

  // 处理保存操作（返回是否成功：系统页签保存成功后还会连带提交 todo.md）
  // 保存与重载分离（code-review item f51b1468ca4f）：重载移出保存 try——
  // 瞬态重载失败不得把已成功的保存误报为「保存失败」，只给非致命刷新提示；
  // 重载完成时经 scopeRef/projectRef 比对币值，await 期间用户切换作用域/
  // 项目则丢弃旧作用域的迟到响应（不覆盖新作用域 config）。
  const handleSave = async (values: Partial<ConfigData>): Promise<boolean> => {
    const scopeAtStart = scope;
    const projectAtStart = project;
    try {
      await saveConfig(project, values);
    } catch (error) {
      const errorMessage = error instanceof Error ? error.message : String(error);
      message.error(`保存失败：${errorMessage}`);
      console.error('Failed to save config:', error);
      return false;
    }
    message.success('保存成功');
    // 已落盘的编辑不再是「未保存改动」（code-review item 8a3eb01dc2b9）：复位
    // 判脏，后续切页签/作用域不再对已保存的内容弹丢弃确认。
    resetPanelDirty();
    // 重新加载配置（失败不影响保存结论）
    try {
      const configData = await getConfig(project);
      if (scopeRef.current === scopeAtStart && projectRef.current === projectAtStart) {
        setConfig(configData);
      }
    } catch (e) {
      console.error('Failed to reload config after save:', e);
      message.warning('已保存，但刷新配置失败，请切换作用域或刷新页面查看最新值');
    }
    return true;
  };

  // 自进化页签唯一保存入口：两张卡片各自校验并收集本节配置，合并后一次提交
  // （任一卡片校验失败即中止；项目级作用域下建议改进项为只读、返回空补丁，
  // 故只提交在当前作用域可写的陈旧自愈节）。
  const handleSelfEvolutionSave = async () => {
    // 重入守卫（code-review item d64feaab59a4）：本入口是 collect 校验 →
    // handleSave 写盘 → getConfig 重载的多段异步链，在飞窗口为全页保存入口
    // 中最长；saving 期间连点直接短路，不发重复写盘请求、不重复弹「保存成功」。
    if (savingRef.current) return;
    savingRef.current = true;
    setSaving(true);
    try {
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
    } finally {
      // 各中止路径与在飞链结束统一复位；ref 同帧复位先于 state 渲染生效
      savingRef.current = false;
      setSaving(false);
    }
  };

  // 运行时构造菜单：自省与项目简介均为项目级页签，随项目级作用域出现；
  // Hook 为项目级设置置于菜单最末。项目简介页签固定名「项目」，不随项目名变长
  const menuItems = [...BASE_MENU_ITEMS];
  if (scope === 'project' && project) {
    // 标签同样取自 PAGE_LABELS 单源（code-review item d996f0d0aac5）
    menuItems.push({ key: 'self-review', label: PAGE_LABELS['self-review'] });
    menuItems.push({ key: 'project-profile', label: PAGE_LABELS['project-profile'] });
    menuItems.push({ key: 'hook', label: PAGE_LABELS.hook });
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
              onClick={({ key }) => {
                // 切页签即卸载当前面板：有未保存改动先确认（item 8a3eb01dc2b9）
                if (key !== activeKey && !confirmDiscardPanelEdits()) return;
                setActiveKey(key);
              }}
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
                    onManualEdit={() => {
                      // 「手工编辑」：跳「项目简介」页签并聚焦 verify.yaml 编辑框。
                      // 回归卡片仅项目作用域渲染，此处 activeKey 必为合法项目级页签
                      // 跳转同样丢弃当前页签未保存编辑，先经同款确认（item 8a3eb01dc2b9）
                      if (!confirmDiscardPanelEdits()) return;
                      setActiveKey('project-profile');
                      setVerifyFocusSignal(Date.now());
                    }}
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
                        loading={saving}
                        disabled={saving}
                        data-testid="settings-save"
                      >
                        保存
                      </Button>
                    </div>
                  </>
                )}
                {activeKey === 'project-profile' && (
                  <ProjectProfilePanel
                    config={config}
                    onSave={handleSave}
                    project={project}
                    focusVerifySignal={verifyFocusSignal}
                  />
                )}
              </>
            )}
          </div>
        </div>
      </Card>
    </PageContainer>
  );
}
