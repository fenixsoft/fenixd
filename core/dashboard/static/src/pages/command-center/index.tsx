// index.tsx — 管理指挥中心（add-command-center 3.3；2026-11-04 用户指令
// 改版：黑改白 + 脱壳改内容区嵌入）。原 2026-10-28 脱壳全屏深色形态
// （layout:false + 页级暗色 ConfigProvider + html/body 纯黑注入）整体移除：
// 路由进 ProLayout 壳（routes.ts 去 layout:false，与全菜单一致的侧栏/顶栏/
// PageContainer 页头），配色继承 dashboard 根主题（app.tsx rootContainer →
// theme.ts dshAlignedTheme 白底单源；页面级配色常量在 shared.ts 换白底族）。
// 三 Tab（组织总览默认）各屏数据独立加载、独立错误降级（错误占位 + 重试，
// 互不拖垮）、60s 常量静默轮询（useScreen 单点）——交互与数据面零变化；
// Agent 卡随嵌入缩宽（shared.LANE_CARD_WIDTH）。

import { useCallback, useEffect, useRef, useState } from 'react';
import { useSearchParams } from '@umijs/max';
import { PageContainer } from '@ant-design/pro-components';
import { PageTitleBar } from '@/components/PageTitleBar';
import { Select, Space, Tabs } from 'antd';
import { TIME_WINDOW_OPTIONS, TimeWindow } from './shared';
import OrgGrid from './OrgGrid';
import PipelineBoard from './PipelineBoard';
import ExecutionLedger from './ExecutionLedger';

// 时间窗校验（URL ?window= 脏值回落 today）
const isTimeWindow = (v: string | null): v is TimeWindow =>
  TIME_WINDOW_OPTIONS.some((o) => o.value === v);

// spec 视图选中态（add-command-center-spec-view：spec_project, spec 二元组）
export interface SpecViewSelection {
  project: string;
  spec: string;
}

export default function CommandCenterPage() {
  // 默认 Tab = 组织总览（specs「导航与默认 Tab」Requirement）
  const [activeKey, setActiveKey] = useState('org');
  // 筛选条件入 URL（2026-10-28 用户定稿：?project=X&window=Y 深链直达即得
  // 特定视图；依赖服务端 SPA fallback——无扩展名非 api GET 路径回 index.html）。
  // 变更经 setSearchParams replace 写回（不刷历史栈）；初值仅读一次。
  const [searchParams, setSearchParams] = useSearchParams();
  // 最新 searchParams 暂存 ref（同 tick 双写竞态兜底）：下方三个 setter 闭包
  // 直读的 searchParams 是渲染期快照，同一 tick 内连续触发两个 setter 时，
  // 第二个会用旧快照构造参数冲掉第一个的写入；setter 统一从本 ref 构造新
  // 参数并在写后回填，链式写不再互冲。searchParams 变化（含浏览器侧导航）
  // 经 effect 同步回 ref。
  const latestParamsRef = useRef(searchParams);
  useEffect(() => {
    latestParamsRef.current = searchParams;
  }, [searchParams]);
  const urlProject = searchParams.get('project') ?? '';
  const urlWin: TimeWindow = isTimeWindow(searchParams.get('window'))
    ? (searchParams.get('window') as TimeWindow)
    : 'today';
  // 全局项目筛选（2026-10-28 页签右侧）：驱动组织总览/交付流水线/执行台账
  // 三屏（三端点均收 project），状态提升至宿主；各屏上报 projects 全集在此
  // 合并——任一屏到过数据即撑起下拉，不依赖先访组织总览
  // [fenix-ignore:89d7af3f7510] 初值仅读一次为有意取舍（上方注释已声明），浏览器侧导航（前进/后退/改地址栏）致 URL 与筛选 state 失同步是已声明边界
  const [project, setProjectState] = useState(urlProject);
  const [allProjects, setAllProjects] = useState<string[]>([]);
  // 上报合并（同引用短路防上报环；useCallback 稳定身份配下游 effect deps）
  const reportProjects = useCallback((list: string[]) => {
    setAllProjects((prev) => {
      const merged = [...new Set([...prev, ...list])].sort();
      return merged.length === prev.length ? prev : merged;
    });
  }, []);
  // 时间窗（今日/7日/全量）：仅组织总览有时间窗口径（流水线/台账端点无
  // window 语义），非总览页签隐藏该下拉，不留「显示但无效」的死控件
  const [orgWin, setOrgWinState] = useState<TimeWindow>(urlWin);
  // spec 视图选中态（add-command-center-spec-view 4.1：2026-10-30 用户定稿
  // 深链进 URL——`spec`（SPEC 名）+ `spec_project`（该 spec 所属项目）双参数
  // 写读单点，与 project/window 同款管理；刷新/分享直达。名单校验不过
  // （隐式退出规则）由 OrgGrid 在 org 数据到达后回调置 null 清参数）
  const urlSpec = searchParams.get('spec') ?? '';
  const urlSpecProject = searchParams.get('spec_project') ?? '';
  const [specView, setSpecViewState] = useState<SpecViewSelection | null>(
    urlSpec && urlSpecProject ? { project: urlSpecProject, spec: urlSpec } : null,
  );

  // 筛选变更同步写 URL（replace：不刷历史栈）。不用 setSearchParams 的
  // 函数式更新器——本 react-router 版本下它不生效（写出的 query 恒空，
  // 会把另一参数一并冲掉）；从 latestParamsRef 构造完整新参数，交叉保留
  // 其余参数，写后回填 ref——同 tick 连续触发两个 setter 时第二个也能读
  // 到第一个的写入（闭包 searchParams 是渲染期快照，双写会互冲）。
  const setProject = useCallback(
    (v: string) => {
      setProjectState(v);
      const next = new URLSearchParams(latestParamsRef.current);
      if (v) next.set('project', v);
      else next.delete('project');
      latestParamsRef.current = next;
      setSearchParams(next, { replace: true });
    },
    [setSearchParams],
  );
  const setOrgWin = useCallback(
    (v: TimeWindow) => {
      setOrgWinState(v);
      const next = new URLSearchParams(latestParamsRef.current);
      next.set('window', v);
      latestParamsRef.current = next;
      setSearchParams(next, { replace: true });
    },
    [setSearchParams],
  );
  // spec 视图选中态写 URL（add-command-center-spec-view 4.1）：置 null =
  // 显式/隐式退出，两参数一并清除；置值 = 深链入链（spec_project 恒随选中
  // 入链，跨项目同名消歧零歧义）
  const setSpecView = useCallback(
    (v: SpecViewSelection | null) => {
      setSpecViewState(v);
      const next = new URLSearchParams(latestParamsRef.current);
      if (v && v.spec && v.project) {
        next.set('spec', v.spec);
        next.set('spec_project', v.project);
      } else {
        next.delete('spec');
        next.delete('spec_project');
      }
      latestParamsRef.current = next;
      setSearchParams(next, { replace: true });
    },
    [setSearchParams],
  );

  return (
    <>
      {/* 统一标题栏声明（unified-page-title-bar 2.4）：「全部项目」+ 时间窗双
          Select 从页签行 tabBarExtraContent 迁 filters 槽位（standalone 顶栏
          右上角 / 行壳位行右端）；时间窗仅组织总览页签有意义的条件显隐随迁
          （filters 为 ReactNode，页内自行条件渲染），页签行不再渲染 extra 区 */}
      <PageTitleBar
        title="指挥中心"
        filters={
          <Space size={8}>
            <Select
              value={project}
              onChange={setProject}
              style={{ minWidth: 160 }}
              size="small"
              options={[
                { label: '全部项目', value: '' },
                ...allProjects.map((p) => ({ label: p, value: p })),
              ]}
            />
            {activeKey === 'org' ? (
              <Select
                value={orgWin}
                onChange={setOrgWin}
                style={{ minWidth: 96 }}
                size="small"
                options={TIME_WINDOW_OPTIONS}
              />
            ) : null}
          </Space>
        }
      />
      <PageContainer>
      {/* 滚动条浅色细杆（2026-11-04 嵌入改版）：仅 .cmdcenter-* 页内滚动容器
          作用域——嵌入后页面不再是独立文档，原 html/body 级注入会泄漏全
          应用，随暗色域整体退役；页内竖向/横向滚动条统一浅灰细杆（webkit
          细节 + Firefox scrollbar-width/scrollbar-color 兜底）。 */}
      <style>{`
        .cmdcenter-hscroll::-webkit-scrollbar, .cmdcenter-lanescroll::-webkit-scrollbar { width: 8px; height: 8px; }
        .cmdcenter-hscroll::-webkit-scrollbar-thumb, .cmdcenter-lanescroll::-webkit-scrollbar-thumb { background: rgba(0, 0, 0, 0.18); border-radius: 4px; }
        .cmdcenter-hscroll::-webkit-scrollbar-thumb:hover, .cmdcenter-lanescroll::-webkit-scrollbar-thumb:hover { background: rgba(0, 0, 0, 0.3); }
        .cmdcenter-hscroll, .cmdcenter-lanescroll { scrollbar-width: thin; scrollbar-color: rgba(0, 0, 0, 0.18) transparent; }
      `}</style>
      <div
        style={{
          // 页签上间距走页面 padding-top（8px）：Tabs 的 marginTop 会沿
          // 无边框父链 margin 塌陷，把 PageContainer 内容区顶带推低；
          // padding 阻断塌陷链。嵌入后页面自然随壳层文档流滚动，原
          // 100vh 裁死/border-box 框架整体退役——org/pipeline 屏的定高
          // 滚动容器在各屏内部自管（SCREEN_CHROME_OFFSET 口径）。
          paddingTop: 8,
        }}
      >
        {/* 页签上间距由外层 div 的 padding-top 承担（margin 塌陷防御，
            见外层注释） */}
        {/* 页签行迁出 extra 后不再渲染 tabBarExtraContent（过滤项已上移统一
            标题栏，见上方 PageTitleBar filters） */}
        <Tabs
          activeKey={activeKey}
          onChange={setActiveKey}
          items={[
            {
              key: 'org',
              label: '组织总览',
              children: (
                <OrgGrid
                  active={activeKey === 'org'}
                  project={project}
                  win={orgWin}
                  onProjects={reportProjects}
                  specView={specView}
                  onSpecViewChange={setSpecView}
                />
              ),
            },
            {
              key: 'pipeline',
              label: '交付流水线',
              children: (
                <PipelineBoard
                  active={activeKey === 'pipeline'}
                  project={project}
                  onProjects={reportProjects}
                />
              ),
            },
            {
              key: 'ledger',
              label: '执行台账',
              children: (
                <ExecutionLedger
                  active={activeKey === 'ledger'}
                  project={project}
                  onProjects={reportProjects}
                />
              ),
            },
          ]}
        />
      </div>
      </PageContainer>
    </>
  );
}
