// index.tsx — 管理指挥中心（add-command-center 3.3；2026-10-28 用户定稿
// 取消顶栏标题/退出按钮、取消「裁决收件箱」页签（AdjudicationInbox 组件
// 一并移除，裁决走主 dashboard 既有告警入口）——页面即纯大屏）。
//
// 脱壳全屏深色页面：路由 /command-center 以 layout:false 关闭 ProLayout
// 框架壳（与协作图谱/拓扑大屏同款），三 Tab（组织总览默认）各屏数据独立
// 加载、独立错误降级（错误占位 + 重试，互不拖垮——specs「导航与默认 Tab」
// 「独立降级」Requirement），60s 常量静默轮询（design D5，useScreen 单点）。
// 深色 antd token 与协作图谱大屏同一色系（design D6：样式作为场景复用，
// 不新增样式配置）。

import { useCallback, useState } from 'react';
import { useSearchParams } from '@umijs/max';
import { ConfigProvider, Select, Space, Tabs, theme } from 'antd';
import { TEXT_MAIN, TIME_WINDOW_OPTIONS, TimeWindow } from './shared';
import OrgGrid from './OrgGrid';
import PipelineBoard from './PipelineBoard';
import ExecutionLedger from './ExecutionLedger';

// 时间窗校验（URL ?window= 脏值回落 today）
const isTimeWindow = (v: string | null): v is TimeWindow =>
  TIME_WINDOW_OPTIONS.some((o) => o.value === v);

export default function CommandCenterPage() {
  // 默认 Tab = 组织总览（specs「导航与默认 Tab」Requirement）
  const [activeKey, setActiveKey] = useState('org');
  // 筛选条件入 URL（2026-10-28 用户定稿：?project=X&window=Y 深链直达即得
  // 特定视图；依赖服务端 SPA fallback——无扩展名非 api GET 路径回 index.html）。
  // 变更经 setSearchParams replace 写回（不刷历史栈）；初值仅读一次。
  const [searchParams, setSearchParams] = useSearchParams();
  const urlProject = searchParams.get('project') ?? '';
  const urlWin: TimeWindow = isTimeWindow(searchParams.get('window'))
    ? (searchParams.get('window') as TimeWindow)
    : 'today';
  // 全局项目筛选（2026-10-28 页签右侧）：驱动组织总览/交付流水线/执行台账
  // 三屏（三端点均收 project），状态提升至宿主；各屏上报 projects 全集在此
  // 合并——任一屏到过数据即撑起下拉，不依赖先访组织总览
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

  // 筛选变更同步写 URL（replace：不刷历史栈）。不用 setSearchParams 的
  // 函数式更新器——本 react-router 版本下它不生效（写出的 query 恒空，
  // 会把另一参数一并冲掉）；闭包直读 searchParams 构造完整新参数，交叉
  // 保留另一参数。searchParams 进 deps 保证闭包新鲜。
  const setProject = useCallback(
    (v: string) => {
      setProjectState(v);
      const next = new URLSearchParams(searchParams);
      if (v) next.set('project', v);
      else next.delete('project');
      setSearchParams(next, { replace: true });
    },
    [searchParams, setSearchParams],
  );
  const setOrgWin = useCallback(
    (v: TimeWindow) => {
      setOrgWinState(v);
      const next = new URLSearchParams(searchParams);
      next.set('window', v);
      setSearchParams(next, { replace: true });
    },
    [searchParams, setSearchParams],
  );

  return (
    <ConfigProvider
      theme={{
        algorithm: theme.darkAlgorithm,
        token: { colorBgBase: '#000000', colorPrimary: '#40a9ff', borderRadius: 8 },
      }}
    >
      {/* 滚动条配色 + 纯黑底（2026-10-28 用户定稿）：本页挂载期间生效——
          html/body 归零 margin 且纯黑（消除 body 默认 margin 露出的顶部
          白条），滚动条深色蓝系（纵向 body 页面滚动 + 横向
          .cmdcenter-hscroll 五线滚动 + .cmdcenter-lanescroll 流水线赛道内
          纵向滚动）；卸载即移除，不污染 dashboard 亮色页。webkit 细节 +
          Firefox scrollbar-color 兜底。 */}
      <style>{`
        html, body { margin: 0; background: #000; }
        body::-webkit-scrollbar { width: 10px; height: 10px; }
        body::-webkit-scrollbar-track { background: #000; }
        body::-webkit-scrollbar-thumb { background: rgba(59, 110, 165, 0.55); border-radius: 5px; }
        body::-webkit-scrollbar-thumb:hover { background: rgba(94, 150, 210, 0.75); }
        html { scrollbar-color: rgba(59, 110, 165, 0.55) #000; }
        .cmdcenter-hscroll::-webkit-scrollbar, .cmdcenter-lanescroll::-webkit-scrollbar { width: 10px; height: 10px; }
        .cmdcenter-hscroll::-webkit-scrollbar-track, .cmdcenter-lanescroll::-webkit-scrollbar-track { background: rgba(0, 0, 0, 0.6); }
        .cmdcenter-hscroll::-webkit-scrollbar-thumb, .cmdcenter-lanescroll::-webkit-scrollbar-thumb { background: rgba(59, 110, 165, 0.55); border-radius: 5px; }
        .cmdcenter-hscroll::-webkit-scrollbar-thumb:hover, .cmdcenter-lanescroll::-webkit-scrollbar-thumb:hover { background: rgba(94, 150, 210, 0.75); }
        .cmdcenter-hscroll, .cmdcenter-lanescroll { scrollbar-color: rgba(59, 110, 165, 0.55) rgba(0, 0, 0, 0.6); }
        /* 深色 scrollbar-color 是继承属性，会沿 html→body→portal 漏进 Modal
           （运行记录弹窗亮色内容配深色滚动条很突兀，2026-10-29 用户反馈）——
           在 Modal 包装层重置回 auto，其子树继承即回归原生样式 */
        .ant-modal-wrap { scrollbar-color: auto; }
      `}</style>
      <div
        style={{
          // 组织总览/交付流水线页签=定高应用框（100vh 裁死 + border-box 把
          // padding 计入，滚动全部走容器内滚动条，杜绝第二根竖向滚动条；
          // 流水线为 2026-10-28 用户定稿：赛道内滚，body 不滚）；其余页签
          // 保持自由页面滚动
          ...(activeKey === 'org' || activeKey === 'pipeline'
            ? { height: '100vh', overflow: 'hidden', boxSizing: 'border-box' as const }
            : { minHeight: '100vh' }),
          background: '#000',
          padding: '8px 20px 0',
          color: TEXT_MAIN,
        }}
      >
        {/* 页签上间距走页面 padding-top（8px）：Tabs 的 marginTop 会沿
            无边框父链 margin 塌陷，把整页推下 8px（顶部白条根因） */}
        <Tabs
          activeKey={activeKey}
          onChange={setActiveKey}
          tabBarExtraContent={{
            right: (
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
            ),
          }}
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
    </ConfigProvider>
  );
}
