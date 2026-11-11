import { PageContainer } from '@ant-design/pro-components';
import { PageTitleBar } from '@/components/PageTitleBar';
import { App, Button, Card, Menu, Select, Space, Typography } from 'antd';
import { useCallback, useEffect, useRef, useState } from 'react';
import type { RefObject } from 'react';
import { useIsMobile } from '@/hooks/useIsMobile';
import { isEmbedMode } from '@/utils/embedMount';
import { getConfig, getOverview, saveConfig } from '@/services/dashboard';
import type { ConfigData, OverviewData, QuickAssignResponse } from '@/services/dashboard';
// PAGE_LABELS 单一来源移入无依赖共享模块（code-review item 6df16f377728）：
// 子组件不再从本文件反向导入，消除 index → panels → button → index 模块循环。
import { PAGE_LABELS } from './pageLabels';
import type { PageKey } from './pageLabels';
// 页签/作用域切换丢弃确认（code-review item 8a3eb01dc2b9）：活跃面板判脏
import {
  anyPanelDirty,
  snapshotPanelDirty,
  VERIFY_SAVE_OWNER,
  BRANCH_GC_SAVE_OWNER,
} from './panelDirty';
// 提示文字状态色取宿主对齐单源（theme.ts；DESIGN.md「宿主对齐基线」+ 配色单源红线）
import { DSH_ERROR, DSH_WARNING } from '@/theme';
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
import BranchGcPanel from './components/BranchGcPanel';
// add-arbiter-lane：全局决策者车道面板（arbiter 四键 + 运行时状态）
import ArbiterPanel from './components/ArbiterPanel';
// add-escalation-chain-admin-arbiter 5.3：处置链面板（chain 四键 + 运行时水位）
// ——原独立「处置链」页签已并入「仲裁」页签堆叠呈现
import ChainPanel from './components/ChainPanel';
import SuggestedImprovementsPanel from './components/SuggestedImprovementsPanel';
import type { SettingsSectionHandle } from './components/settingsSection';
// 页签底部保存按钮行布局单源（code-review item 2051fbd81007）：自进化/仲裁两
// 个堆叠页签的保存按钮行不再各自内联，与其他面板保存行同取此常量
import { SETTINGS_ACTIONS_ROW_STYLE } from './styles';

const { Text } = Typography;

// 左侧菜单列 sticky 钉住偏移（2026-11-05 用户指令「菜单/目录不能滚走」）：菜单
// 本体钉在固定标题带下缘——standalone = ProLayout 顶栏 56（fixed，标题承载于
// 顶栏插槽）；embed = 统一标题栏行壳位 60（PageTitleBar sticky top:0 +
// minHeight 60，本列钉其下）。仅定位用途（sticky top），不吃高度链——与已退役
// 的 SETTINGS_FRAME_OFFSET 定高偏移（旧 56/60，见 git 历史）数值巧合、职责
// 不同。口径同帮助页 HELP_TOC_STICKY_TOP，改顶栏/行壳位高度须回校两处。
const SETTINGS_MENU_STICKY_TOP = isEmbedMode() ? 60 : 56;

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
  // add-arbiter-lane：全局决策者车道配置页签；处置链配置原为独立页签
  // （add-escalation-chain-admin-arbiter 5.3），现并入本页签面板堆叠呈现
  { key: 'arbiter', label: PAGE_LABELS.arbiter },
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
  const staleSelfhealRef = useRef<SettingsSectionHandle>(null);
  const suggestionsRef = useRef<SettingsSectionHandle>(null);
  // 仲裁页签同款（2026-11-05 用户指令「只保留最下面一个保存按钮」）：Arbiter
  // 与 Chain 两面板的收集句柄，页签底部唯一保存按钮合并提交（原两面板各带
  // 保存钮，堆叠页出现两个「保存」）
  const arbiterSectionRef = useRef<SettingsSectionHandle>(null);
  const chainSectionRef = useRef<SettingsSectionHandle>(null);
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
    // [fenix-ignore:f9165022c4ac] info 级风格权衡：window.confirm 与 PromptsPanel 切项目确认（item f2830281595d）既有口径一致，改 App.useApp() modal.confirm 需把同步布尔判定重构为异步回调且破坏该统一口径，不值得改
    return window.confirm('当前页签的修改尚未保存，切换将丢弃，确定继续？');
  };

  // 处理作用域选择（'user' 或 'project:<name>'）
  const handleScopeSelect = (value: string) => {
    const { scope: nextScope, project: nextProject } = decodeScopeValue(value);
    // 同值选择不触发切换（rc-select 不回调，防御性兜底），避免误弹丢弃确认
    if (nextScope === scope && nextProject === project) return;
    // 切换会重载配置并卸载当前面板：有未保存改动先确认再放行
    if (!confirmDiscardPanelEdits()) return;
    // 放行即复位在场面板脏标记（code-review item 0d7c5ba5af5c）：面板按
    // activeKey 条件渲染，停留同页签切作用域/项目时面板实例并不卸载，其
    // dirtyRef 随实例存续；旧作用域的未保存编辑既经确认丢弃、新配置回填后
    // 表单已显示新值，不复位则此后该面板每次切页签都会对已不存在的改动误弹
    // 丢弃确认（直到面板真正卸载注销才自愈）。快照+同步执行恰覆盖当前在册
    // 的在场面板，不会波及其他页签；probe 型面板 reset 本为 no-op，其脏状态
    // 由加载回填的草稿/基线归零口径负责，不受影响。
    snapshotPanelDirty()();
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
  // dirtyOwner（code-review item 4a1439f602af）：发起保存的面板标识，仅 verify
  // 页签双保存入口传（见下方快照注释）；其余调用方不传
  const handleSave = async (
    values: Partial<ConfigData>,
    dirtyOwner?: string,
  ): Promise<boolean> => {
    const scopeAtStart = scope;
    const projectAtStart = project;
    // 判脏复位只覆盖被保存面板（code-review item 1b0adfd4fcaa）：在首个 await
    // 之前的同一同步段内快照在场面板，成功后仅复位这批面板——保存是多段异步
    // 链（写盘往返 + 重载），在飞期间经丢弃确认切页签新编辑的其他面板若被全量
    // 复位，其未保存编辑会在后续切换时静默丢弃。快照恰为发起保存时的活跃页签
    // 条目（面板按 activeKey 条件渲染），保存失败不复位、语义无损。
    // 同页签多保存入口按发起者收窄（code-review item 4a1439f602af）：verify
    // 页签同时挂 VerifyPanel 与 BranchGcPanel、各有独立保存按钮且各自只提交
    // 本面板字段，全量快照会把「保存其一时另一面板快照前已置脏」的条目一并
    // 复位，其未保存编辑失去切页签丢弃确认保护、随后切换被静默丢弃——传
    // dirtyOwner 仅快照发起面板条目，双按钮各清各的；其余页签单保存入口或
    // collect 合并提交（自进化/仲裁），不传保持全量快照语义。
    const resetSavedPanelDirty = snapshotPanelDirty(dirtyOwner);
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
    // 在场的被保存面板（item 1b0adfd4fcaa），在飞期间新编辑的其他页签保留脏标记
    // （同页签另一保存入口快照前的既有脏亦保留，item 4a1439f602af）。
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

  // 快速分配应用回调（add-agent-model-quick-assign 5.3）：弹窗内已逐项展示
  // 结果；本回调负责成功提示（含「重启 daemon 后生效」口径）与当前作用域
  // 重载——若 results 含本作用域成功项（用户级作用域下的 user 目标，或项目
  // 级作用域下 project===当前项目的目标），先武装快照（首个 await 前的同一
  // 同步段，同 handleSave 快照口径）→ getConfig 重载 → setConfig → 复位面板
  // 判脏。复位后移到重载成功并比对币值通过之后（code-review item
  // 46bf698756cb）：新配置回填后旧编辑已不成立，对齐 handleSave 的已落盘
  // 复位时序——旧实现先复位后重载，重载失败只弹 warning、config 停留旧值，
  // 未保存编辑仍在而脏标记已被清零，切页签不再弹丢弃确认、面板卸载即静默
  // 丢弃这批编辑。重载完成经 scopeRef/projectRef 币值守卫丢弃迟到回包（沿用
  // handleSave 同款守卫，守卫不过不复位——该路径判脏已由 handleScopeSelect
  // 的切换确认口径处理）；重载失败沿用既有「已保存，但刷新配置失败…」
  // warning、脏标记原样保留。仅指定项目成功则只提示成功、不重载当前表单
  // （spec「仅指定项目时不重载当前表单」）。
  const handleQuickAssignApplied = async (result: QuickAssignResponse) => {
    const results = result?.results || [];
    const okCount = results.filter((r) => r.ok).length;
    if (okCount > 0) {
      message.success(`配置已保存，重启 daemon 后生效（快速分配成功写入 ${okCount} 个目标）`);
    }
    const currentScopeOk = results.some((r) => {
      if (!r.ok) return false;
      return scope === 'project'
        ? r.scope === 'project' && r.project === project
        : r.scope === 'user';
    });
    if (!currentScopeOk) return;
    const scopeAtStart = scope;
    const projectAtStart = project;
    // 先武装快照不立即复位（code-review item 46bf698756cb）：复位推迟到重载
    // 成功之后执行；快照后新置脏的再编辑经 lastDirtyAt 门禁保留（panelDirty
    // 在飞保存再编辑守卫同款口径）
    const resetPanelDirty = snapshotPanelDirty();
    try {
      const configData = await getConfig(project);
      if (scopeRef.current === scopeAtStart && projectRef.current === projectAtStart) {
        setConfig(configData);
        resetPanelDirty();
      }
    } catch {
      message.warning('已保存，但刷新配置失败，请切换作用域或刷新页面查看最新值');
    }
  };

  // 堆叠页签两段式保存入口工厂（code-review item 2f264f982565）：自进化与仲裁
  // 两个保存入口此前整段复制同一约 30 行流程——savingRef 置位、Promise.all
  // 收集、undefined/null 双守卫、reduce 合并、空补丁提示、finally 复位逐句
  // 相同，仅 ref 对与两处提示文案不同（「请先修正表单校验错误」「没有需要
  // 保存的变更」两段文案两入口本就同文，随工厂自然单源）。提取后两个入口各
  // 一行调用，与 useGatedFormPanel 收敛六面板同族脚手架的先例同口径：守卫
  // 口径或文案调整单点生效，未来堆叠页签再增加直接接入不再翻倍复制。
  const createStackedTabSave = (
    refs: RefObject<SettingsSectionHandle | null>[],
    labels: { collectError: string; notReady: string },
  ) => {
    return async () => {
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
        const parts = await Promise.all(
          refs.map((ref) => ref.current?.collect()),
        ).catch(() => {
          message.error(labels.collectError);
          return null;
        });
        if (parts === null) return;
        // ref 未挂载 ≠ 空收集（code-review item 51a0f171bc8c）：ref 未挂（卡片
        // 未渲染/面板卸载）时 ``?.collect()`` 得 undefined——undefined（面板
        // 未就绪）与 null（校验失败）分开提示，均中止保存。
        if (parts.some((p) => p === undefined)) {
          message.warning(labels.notReady);
          return;
        }
        // 校验失败不再静默返回（code-review item 57ca856f0531）：旧实现裸
        // return 使用户以为已保存，实际什么都没发生。
        if (parts.some((p) => p === null)) {
          message.warning('请先修正表单校验错误');
          return;
        }
        // 上方 undefined/null 双守卫已中止空元素，无需再做空值兜底
        const merged = parts.reduce<Partial<ConfigData>>(
          (acc, p) => ({ ...acc, ...p }),
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
  };

  // 自进化页签唯一保存入口：两张卡片各自校验并收集本节配置，合并后一次提交
  // （任一卡片校验失败即中止；项目级作用域下建议改进项为只读、返回空补丁，
  // 故只提交在当前作用域可写的陈旧自愈节）。
  const handleSelfEvolutionSave = createStackedTabSave(
    [staleSelfhealRef, suggestionsRef],
    {
      collectError: '收集自进化配置失败，保存已中止，请稍后重试',
      notReady: '自进化面板未就绪，无法收集本节配置，请稍后重试',
    },
  );

  // 仲裁页签唯一保存入口（handleSelfEvolutionSave 同款两段式：两面板各自
  // validateFields 收集 → 合并为一次提交，任一校验失败即中止并提示）。复用
  // 同一对 saving/savingRef：两页签互斥渲染，state 语义不交叉。
  const handleArbiterTabSave = createStackedTabSave(
    [arbiterSectionRef, chainSectionRef],
    {
      collectError: '收集仲裁配置失败，保存已中止，请稍后重试',
      notReady: '仲裁面板未就绪，无法收集配置，请稍后重试',
    },
  );

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
    <>
      {/* 统一标题栏声明（unified-page-title-bar 2.2）：标题进顶栏（standalone）/
          内容区首行（embed/移动端），「作用域」Select 迁 filters 槽位——standalone
          落顶栏右上角（原面包屑位置），行壳位落行右端 */}
      <PageTitleBar
        // 标题与菜单同名单源改「配置」（2026-11-05 用户指令，避让 dsh web「设置」）
        title="配置"
        filters={
          <Space>
            {/* 「作用域：」标签移动端不渲染（2026-11-07 用户指令）：顶栏窄幅下
                标签+下拉会挤得标题行换行；桌面保持原样 */}
            {!isMobile && (
              <Text type="secondary" style={{ fontSize: 13 }}>
                作用域：
              </Text>
            )}
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
              // 宽度移动档 130（2026-11-07 用户指令「下拉框宽度缩小」，对齐
              // v2/settings.tsx 移动档同值），桌面 200 不变
              style={{ width: isMobile ? 130 : 200 }}
              options={[
                { value: USER_SCOPE, label: '用户级' },
                ...projects.map((p) => ({ value: `project:${p}`, label: `项目级：${p}` })),
              ]}
            />
          </Space>
        }
      />
      <PageContainer title={false} breadcrumbRender={false} pageHeaderRender={false}>
      <Card
        bordered={false}
        className="settings-page"
      >
        {/* 移动端菜单置顶横排，面板全宽；桌面保持左竖菜单布局不变。
            卡体随内容自然增高，页面纵向滚动统一走文档级（2026-11-05 用户指令
            「全站滚动条范围统一」，同 overview/projects/activities 口径；原
            2026-11-04 整卡定高 + 右栏 overflowY 内滚形态已整体退役）。
            桌面左菜单本体 sticky 钉住不随页面滚走（同日用户指令
            「菜单/目录不能滚走」，见 SETTINGS_MENU_STICKY_TOP）。 */}
        <div
          style={
            isMobile
              ? { display: 'flex', flexDirection: 'column' }
              : { display: 'flex' }
          }
        >
          {/* 左侧菜单列：外壳撑满列高（右缘分隔线全长），菜单本体 sticky 钉住
              （2026-11-05 用户指令「菜单/目录不能滚走」）；顶带 16 随本体走钉位 */}
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
            <div
              style={
                isMobile
                  ? undefined
                  : {
                      // 菜单本体 sticky 钉在标题带下缘（SETTINGS_MENU_STICKY_TOP
                      // 口径见其注释）；页面滚动走文档级，长菜单超出视口时菜单
                      // 自滚兜底（overflowY auto 仅此 fallback 生效，右栏无内滚）。
                      // 顶带 16（2026-11-05 用户指令）随本体走，钉位后仍垫呼吸。
                      position: 'sticky',
                      top: SETTINGS_MENU_STICKY_TOP,
                      maxHeight: `calc(100vh - ${SETTINGS_MENU_STICKY_TOP}px - 16px)`,
                      paddingTop: 16,
                      overflowY: 'auto',
                    }
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
                    // 原 height:'100%' 随定高形态退役：本体高度即菜单自然高度
                    : { borderRight: 0 }
                }
              />
            </div>
          </div>
          {/* 右侧面板 */}
          <div
            style={
              isMobile
                ? // 左右 4（2026-11-07 用户指令「配置页面的左右边距也改为 16px」：
                  // 外层 children-container 12 + 本面板 4 = 每侧合计 16；原 16
                  // 时每侧 28）。桌面右 16/左 24 惯例不变
                  { flex: 1, minWidth: 0, padding: '12px 4px 24px' }
                : {
                    // 右栏随文档滚动（2026-11-05 用户指令「全站滚动条范围统一」，
                    // 原 overflowY 内滚已退役）。右内边距 16（2026-11-05 用户指令
                    // 「各页签右间距统一」——原右 0 + .ant-form padding-right:16
                    // 的双源口径使非 Form 面板（提示词/项目/Hook）内容直顶滚动条，
                    // 现右呼吸单源上收到本栏，Form 与非 Form 面板右缘对齐同一
                    // 16px；原 global.less 的 .ant-form 规则已随之退役）；左 24
                    // 保留（面板-菜单列间距）；顶带 8（2026-11-05 用户指令，原 24）
                    // + 底 24 维持纵向节奏。
                    flex: 1,
                    minWidth: 0,
                    padding: '8px 16px 24px 24px',
                  }
            }
          >
            {loading && <div>加载中...</div>}
            {/* 加载失败回退 UI（code-review item eae893169197）：旧实现失败后
                config 恒为 null，非 prompts 页签全部渲染空白面板而用户无从判断。 */}
            {!loading && loadError && (
              <div style={{ color: DSH_ERROR, padding: '12px 0' }}>
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
                  <div style={{ marginBottom: 16, color: DSH_WARNING }}>
                    {config.scope === 'project'
                      ? '项目尚无配置文件，表单为默认值'
                      : '用户级配置文件不存在，表单为默认值'}
                  </div>
                )}
                {config.error && (
                  <div style={{ marginBottom: 16, color: DSH_ERROR }}>
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
                    projects={projects}
                    onQuickAssignApplied={handleQuickAssignApplied}
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
                  <>
                    <VerifyPanel
                      config={config}
                      // 保存入口标识（code-review item 4a1439f602af）：与本面板
                      // usePanelDirty 登记的 owner 同值配对，保存只复位自身脏
                      // 条目，不清同页签 BranchGcPanel 快照前已置脏的未保存编辑
                      onSave={(v) => handleSave(v, VERIFY_SAVE_OWNER)}
                      project={scope === 'project' ? project : undefined}
                      onConfigSynced={scope === 'project' ? handleConfigSynced : undefined}
                    />
                    {/* add-merged-branch-gc：已合并分支 GC 面板（worktree.branch_gc
                        两键），与验证/worktree 维护设置同页签呈现；独立 Form 与
                        保存按钮，保存走同一 handleSave 写回通道。owner 配对口径
                        同上方 VerifyPanel（code-review item 4a1439f602af） */}
                    <BranchGcPanel
                      config={config}
                      onSave={(v) => handleSave(v, BRANCH_GC_SAVE_OWNER)}
                    />
                  </>
                )}
                {activeKey === 'arbiter' && (
                  // add-arbiter-lane：全局决策者车道面板（arbiter 四键 + 运行时
                  // 状态只读摘要）。处置链面板并入本页签堆叠（add-escalation-chain-
                  // admin-arbiter 5.3）。两面板经 ref 暴露 collect()（StaleCodeSelfheal
                  // 同款句柄模式），保存收口为页签底部唯一「保存」按钮合并提交
                  // （2026-11-05 用户指令：原两面板各带保存钮，堆叠页出现两个「保存」）
                  <>
                    <ArbiterPanel
                      ref={arbiterSectionRef}
                      config={config}
                      project={scope === 'project' ? project : undefined}
                    />
                    {/* add-escalation-chain-admin-arbiter 5.3：处置链面板（chain
                        四键配额/复位窗/黑名单 + 运行时水位 30s 轮询） */}
                    <ChainPanel
                      ref={chainSectionRef}
                      config={config}
                      project={scope === 'project' ? project : undefined}
                    />
                    {/* 页签唯一「保存」按钮：置于页面最下方、右对齐（自进化页签同款） */}
                    <div style={SETTINGS_ACTIONS_ROW_STYLE}>
                      <Button
                        type="primary"
                        onClick={handleArbiterTabSave}
                        loading={saving}
                        disabled={saving}
                        data-testid="arbiter-save"
                      >
                        保存
                      </Button>
                    </div>
                  </>
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
                    <div style={SETTINGS_ACTIONS_ROW_STYLE}>
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
    </>
  );
}
