import { PageContainer } from '@ant-design/pro-components';
import { App, Button, Card, Menu, Select, Space, Typography } from 'antd';
import { useCallback, useEffect, useRef, useState } from 'react';
import { useIsMobile } from '@/hooks/useIsMobile';
import { getConfig, getOverview, saveConfig } from '@/services/dashboard';
import type { ConfigData, OverviewData } from '@/services/dashboard';
// PAGE_LABELS 单一来源移入无依赖共享模块（code-review item 6df16f377728）：
// 子组件不再从本文件反向导入，消除 index → panels → button → index 模块循环。
import { PAGE_LABELS } from './pageLabels';
import type { PageKey } from './pageLabels';
// 页签/作用域切换丢弃确认（code-review item 8a3eb01dc2b9）：活跃面板判脏
import { anyPanelDirty, snapshotPanelDirty } from './panelDirty';
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
// label 显式放宽为 string：下方项目级 push 的三个页签标签（自省/项目/Hook）
// 同取自 PAGE_LABELS，as const 后若沿用值字面量联合会把合法 push 误判为错
// （code-review item 32ab875ddc2e）；key 仍保持 PageKey 拼写检查。
const BASE_MENU_ITEMS: { key: PageKey; label: string }[] = [
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
  // 页面级提示（项目列表/配置加载、保存结果、自进化收集等）经 App.useApp()
  // 取上下文实例（code-review item ceed3c01bf6e）：静态 message 不经过
  // App/ConfigProvider 上下文，与本页各设置面板统一口径
  const { message } = App.useApp();
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
  // 质量页签「手工编辑」→「项目简介」页签聚焦信号（时间戳；0=无待处理信号；
  // 面板聚焦落地后经 onConsumed 回调复位——用后不复位会在面板卸载重挂载
  // （切走再切回页签/切项目重建）时拿旧时间戳重触发聚焦，code-review item
  // ff9fbfa71d51）
  const [verifyFocusSignal, setVerifyFocusSignal] = useState(0);

  // 加载项目列表（code-review item 5c15a853b040）：旧实现内联在空依赖 effect 里
  // 仅挂载时拉取一次，失败后 projects 停在空数组且无任何重试触发点，daemon 瞬时
  // 繁忙（503 server busy）会让项目级作用域在会话剩余时间内持续不可达，只能整页
  // 刷新。现提升为稳定回调，供作用域 Select 下拉展开时懒重拉（见下方 Select 的
  // onOpenChange）；loadingProjectsRef 写读同 ref 拦在飞重叠请求（同 savingRef
  // 口径：setSaving 渲染生效存在 React 调度间隙，state 拦不住同帧连点）。
  const loadingProjectsRef = useRef(false);
  const loadProjects = useCallback(async () => {
    if (loadingProjectsRef.current) return;
    loadingProjectsRef.current = true;
    try {
      const data: OverviewData = await getOverview();
      setProjects(data.projects.map((p) => p.name));
    } catch (e) {
      // 项目列表失败非阻断提示（code-review item 6776b8ee2ba9）：projects 停在
      // 空数组，作用域下拉只剩「用户级」，项目级页签与回归质量配置全部不可达，
      // 仅 console.error 会让用户误以为尚未注册任何项目。比照保存后刷新失败的
      // message.warning 口径提示，不与配置加载失败的 loadError 横幅混为一谈。
      message.warning(
        `项目列表加载失败，项目级作用域暂不可用：${e instanceof Error ? e.message : String(e)}`,
      );
    } finally {
      loadingProjectsRef.current = false;
    }
  }, [message]);
  useEffect(() => {
    loadProjects();
  }, [loadProjects]);

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
    // 未消费的聚焦信号随作用域切换作废（code-review item b49d23bf8dd1）：信号
    // 置位后面板尚未挂载消费（如保存重载 loading 期间）时切作用域，回落的
    // activeKey 下信号无人消费，残留会让之后打开「项目简介」页签拿旧时间戳
    // 误触发一次聚焦；切换发生即复位，保证信号只能被紧接着的跳转消费。
    setVerifyFocusSignal(0);
    // 项目级页签仅项目级存在：切回用户级时不能停留在已消失的页签上
    if (nextScope === 'user' && PROJECT_ONLY_KEYS.has(activeKey)) {
      setActiveKey('llm');
    }
  };

  // 处理保存操作（返回是否成功：自省页签（SelfReviewPanel）保存成功后还会连带提交 todo.md）
  // 保存与重载分离（code-review item f51b1468ca4f）：重载移出保存 try——
  // 瞬态重载失败不得把已成功的保存误报为「保存失败」，只给非致命刷新提示；
  // 重载完成时经 scopeRef/projectRef 比对币值，await 期间用户切换作用域/
  // 项目则丢弃旧作用域的迟到响应（不覆盖新作用域 config）。
  const handleSave = async (values: Partial<ConfigData>): Promise<boolean> => {
    const scopeAtStart = scope;
    const projectAtStart = project;
    // 判脏复位只覆盖被保存面板（code-review item 1b0adfd4fcaa）：在首个 await
    // 之前的同一同步段内快照在场面板，成功后仅复位这批面板——保存是多段异步
    // 链（写盘往返 + 重载），在飞期间经丢弃确认切页签新编辑的其他面板若被全量
    // 复位，其未保存编辑会在后续切换时静默丢弃。快照恰为发起保存时的活跃页签
    // 条目（面板按 activeKey 条件渲染），保存失败不复位、语义无损。
    const resetSavedPanelDirty = snapshotPanelDirty();
    try {
      await saveConfig(project, values);
    } catch (error) {
      const errorMessage = error instanceof Error ? error.message : String(error);
      message.error(`保存失败：${errorMessage}`);
      return false;
    }
    message.success('保存成功');
    // 已落盘的编辑不再是「未保存改动」（code-review item 8a3eb01dc2b9）：复位
    // 判脏，后续切页签/作用域不再对已保存的内容弹丢弃确认；仅复位发起保存时
    // 在场的被保存面板（item 1b0adfd4fcaa），在飞期间新编辑的其他页签保留脏标记。
    resetSavedPanelDirty();
    // 重新加载配置（失败不影响保存结论）
    try {
      const configData = await getConfig(project);
      if (scopeRef.current === scopeAtStart && projectRef.current === projectAtStart) {
        setConfig(configData);
      }
    } catch (e) {
      message.warning('已保存，但刷新配置失败，请切换作用域或刷新页面查看最新值');
    }
    return true;
  };

  // 项目级「同步用户级设置」回填守卫（code-review item 22a91265b49d）：各面板把
  // onConfigSynced 直连为 setConfig，而 SyncFromUserButton 的 runAction 在 await
  // syncConfigFromUser 返回后才回调；若在飞期间用户已切换作用域/项目（面板随即
  // 卸载，但闭包里的回调仍会执行），迟到的旧作用域 config 会覆盖新作用域刚加载
  // 的 config，用户在新作用域名下点保存即跨作用域写错配置。比照 handleSave 重载
  // 路径的币值比对（code-review item f51b1468ca4f）：本回调每次渲染重建、闭包
  // 捕获当时 scope/project，触发时与 scopeRef/projectRef 比对，已切换则丢弃迟到
  // 回包（静默丢弃，不提示，同先例口径）。
  const handleConfigSynced = (configData: ConfigData) => {
    if (scopeRef.current === scope && projectRef.current === project) {
      setConfig(configData);
    }
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
      // collect 契约是校验失败返回 null 而非 reject，但未禁止内部意外异常
      // （config 缺段、ref 转发链断裂）——异常穿透会逃逸为 onClick 的未处理
      // Promise 拒绝：saving 被 finally 复位，用户却零反馈，点击如同失效
      // （code-review item e15f483ca1ed）。对齐 handleSave 的 error 口径后中止。
      const parts = await Promise.all([
        staleSelfhealRef.current?.collect(),
        suggestionsRef.current?.collect(),
      ]).catch((error) => {
        message.error('收集自进化配置失败，保存已中止，请稍后重试');
        return null;
      });
      if (parts === null) return;
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
              // project 为空值兜底（code-review item 234fe8e987a2）：与下方
              // menuItems.push 的 project 真值门禁同口径，避免受控 Select 显示
              // project:undefined 且不匹配任何 option
              value={scope === 'project' && project ? `project:${project}` : USER_SCOPE}
              onChange={handleScopeSelect}
              // 懒重试通道（code-review item 5c15a853b040）：下拉展开且项目列表
              // 为空（挂载时拉取失败或尚未注册项目）则重拉一次，无需整页刷新
              onOpenChange={(open) => {
                if (open && projects.length === 0) loadProjects();
              }}
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
                // 未消费的聚焦信号随页签切换作废（code-review item b49d23bf8dd1）：
                // 目标非「项目简介」时信号已无人消费，残留会在之后打开该页签时
                // 拿旧时间戳误触发一次聚焦。
                if (key !== 'project-profile') setVerifyFocusSignal(0);
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
                    {config.scope === 'project'
                      ? '项目尚无配置文件，表单为默认值'
                      : '用户级配置文件不存在，表单为默认值'}
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
                    onConfigSynced={scope === 'project' ? handleConfigSynced : undefined}
                  />
                )}
                {activeKey === 'agents' && (
                  <AgentModelPanel
                    config={config}
                    onSave={handleSave}
                    project={scope === 'project' ? project : undefined}
                    onConfigSynced={scope === 'project' ? handleConfigSynced : undefined}
                  />
                )}
                {activeKey === 'parallel' && (
                  <ParallelSettingsPanel
                    config={config}
                    onSave={handleSave}
                    project={scope === 'project' ? project : undefined}
                    onConfigSynced={scope === 'project' ? handleConfigSynced : undefined}
                  />
                )}
                {activeKey === 'approval' && (
                  <ApprovalModePanel
                    config={config}
                    onSave={handleSave}
                    project={scope === 'project' ? project : undefined}
                    onConfigSynced={scope === 'project' ? handleConfigSynced : undefined}
                  />
                )}
                {activeKey === 'token' && (
                  <TokenBudgetPanel
                    config={config}
                    onSave={handleSave}
                    project={scope === 'project' ? project : undefined}
                    onConfigSynced={scope === 'project' ? handleConfigSynced : undefined}
                  />
                )}
                {activeKey === 'misc' && (
                  <MiscSettingsPanel
                    config={config}
                    onSave={handleSave}
                    project={scope === 'project' ? project : undefined}
                    onConfigSynced={scope === 'project' ? handleConfigSynced : undefined}
                  />
                )}
                {activeKey === 'verify' && (
                  <VerifyPanel
                    config={config}
                    onSave={handleSave}
                    project={scope === 'project' ? project : undefined}
                    onConfigSynced={scope === 'project' ? handleConfigSynced : undefined}
                  />
                )}
                {activeKey === 'quality' && (
                  <QualityPanel
                    config={config}
                    onSave={handleSave}
                    project={scope === 'project' ? project : undefined}
                    onConfigSynced={scope === 'project' ? handleConfigSynced : undefined}
                    onManualEdit={() => {
                      // 「手工编辑」：跳「项目简介」页签并聚焦 verify.yaml 编辑框。
                      // 作用域门禁（code-review item fa2e175e7e70）：不再依赖
                      // 「回归卡片仅项目作用域渲染该按钮」的跨组件隐含契约，
                      // scope/project 不满足时原地 no-op——否则会落在菜单无此
                      // 项目、选中态悬空的页签上（project-profile 以
                      // project=undefined 渲染）；守卫先于丢弃确认，不跳转不弹窗
                      if (scope !== 'project' || !project) return;
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
                    onConfigSynced={scope === 'project' ? handleConfigSynced : undefined}
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
                {/* project 门禁（code-review item fa2e175e7e70）：与 hook 分支
                    同口径，project 为空时不渲染，防面板以 project=undefined 落地 */}
                {activeKey === 'project-profile' && project && (
                  <ProjectProfilePanel
                    config={config}
                    onSave={handleSave}
                    project={project}
                    focusVerifySignal={verifyFocusSignal}
                    onConsumed={() => setVerifyFocusSignal(0)}
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
