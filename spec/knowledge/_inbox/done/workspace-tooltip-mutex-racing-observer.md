# tooltip 互斥：竞速型观察器失效模式（workspace-row 富提示）

## 背景

dsh web 侧栏工作区行富提示浮层（SPEC `add-workspace-row-project-tooltip`，
宿主仓 `fenix-dsh-dashboard-bridge/src/client/wsTooltip.ts`）需要与宿主原生
tooltip 互斥：fenix 行 hover 时只显示插件富卡。落地版实现为「富提示 show()
时才 start 一个 MutationObserver 隐藏原生 portal 节点」——用户报告两卡重叠。

## 结论（当前事实）

- **竞速型观察器是反模式**：当宿主节点 A 与插件均在同一延迟（本例同为
  500ms）后渲染互斥目标时，"目标出现后才挂观察器" 必然错过其 add 事件，
  事后隐藏逻辑永不触发。互斥手段必须**常驻**：插件安装期即挂
  `MutationObserver`（body childList+subtree），对存量 `body.children` 先做
  一轮兜底扫描（观察器启动前已 open 的 portal 节点不会再报 add）。
- **命中名单须与拦截层存亡严格同步**：常驻消解器的隐藏判定 keyed by
  「已装层项目名集合」（`installedNames`），只在有拦截层的行生效（非 fenix
  行零侵入不误伤）；项目移除走 `refresh()` 解Hide（删除行保留、回退原生），
  卸载走 `stop()` 全解。名单写入/删除点 = 拦截层换层/新挂/按名移除/全清。
- **本插件富卡自排除**：富卡经 `data-fenix-wstip` 属性标记，消解器对该属性
  跳过（富卡 textContent 同样含项目名，否则自吞）。
- **stopPropagation 拦不住 mouseenter 型原生监听**：宿主 tooltip 若用原生
  `mouseenter` 事件（非 React 合成 onMouseEnter 的 mouseover/out 代理），
  拦截层上的 `stopPropagation` 无法阻止其触发——第一道防线只对合成 hover
  链有效，互斥必须由第二道防线（常驻消解）兜底，不能假设①必奏效。

## 证据

- 缺陷实测：hover fenixd 行 1s 后 `_portal_bgejw_96`（body 直子原生 tooltip
  包装）display:flex 与富卡 display:block 同显；两卡同为 500ms 延迟竞速。
- 修复后复验（playwright 活站）：fenix 行 hover → 原生 `display:none` +
  富卡独显；非 fenix 行（nongit）→ 原生照常 `display:contents` + 富卡 0；
  换行（fenixd→fenix-server）无残卡。
- 代码：`src/client/wsTooltip.ts`（常驻消解器 + 控制器解耦）、
  `src/client/panels.tsx`（installedNames 接线）；镜像见 SPEC 目录
  `plugin-patch/`（BASELINE.md 追加修复段）。
- dsh web 侧栏工作区行 `data-row-key="workspace:<uuid>"` **不含项目名**，
  按名定位行须匹配行内叶子 span 文本，不能 `key.includes(name)`。
