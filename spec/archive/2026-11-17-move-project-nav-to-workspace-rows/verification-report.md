# 验证报告：move-project-nav-to-workspace-rows

> ⚠️ 本报告由框架于 2026-11-09T09:00:39Z 自动合成（裁决 Agent 未写报告，已由框架合成），内容为结构化验证产物（report.json / .fenix-run-result.json）的忠实渲染。
> 报告时效标记（判定本报告是否属上一轮）：合成源轮次指纹：report.json@2026-11-09T09:00:39.170843+00:00+run-result@mtime1794214839226750314

## 结论：✅ 通过（verified）

**状态：verified — 12/12 场景通过，0 失败，0 错误（全部场景通过）**

全绿快道: 12/12 场景通过、0 失败 0 警告——无分类对象，跳过 judge 机械 verified

| 指标 | 数量 |
| --- | --- |
| 通过 | 12 |
| 失败 | 0 |
| 错误 | 0 |
| 产品 Bug | 0 |
| 本链增量 Token（输入） | 4.97M |
| 本链增量 Token（输出） | 0.12M |


## 场景结果

| 场景 | 描述 | 状态 | 失败断言 | 分类 |
| --- | --- | --- | --- | --- |
| bridge-vitest-contract-green | 宿主插件行为级单测全绿（tasks 3.4/4.2/5.1）：/root/dsh-plugins/fenix-dsh-dashboard-bridge vitest run 全量绿——srcContract 钉值更新面（FIXED_ENTRIES 收敛 5 项无 fenix-projects 条目（index.ts:43-53 退役）、每项目 fenix-project-<name> 主面板注册保留（index.ts:183）、#panel=fenix-projects 旧深链未注册吞语义）、名称导航判据四态单测（归一化路径相等优先命中 / title 精确相等回落 / 同名标题非同路径不命中 / 锚点缺失不装层，design.md D2 判据）、既有契约不回归（iframe src 逐字符、reconcileProjects 幂等、parseProjectNames 形状）；projectSync 对齐四态单测（新建注册不 startSession / 已存在跳过 / 删除项目不删工作区 / 拉取失败整轮跳过）。spec Scenario「新项目自动出现」的真实 workspaces.create 会持久写宿主 workspace.json registry（用户侧栏永久多行、对齐只增不删无法回收），不宜框架场景直打真实链路——该 Scenario 行为由本场景对齐四态单测承载、部署实拍由实现者 tasks 5.4 截图留痕。出处：spec.md「工作区行项目名称导航/项目工作区自动对齐」Requirement + tasks.md 3.4/4.2/5.1 + projectSync.ts:19（60s 周期）/index.ts:210（api/projects 轮询）。 | pass | 0/3 | - |
| bridge-retire-surface-clean | 宿主源码静态契约探针（tasks 2.1-2.3/3.1-3.2/4.1 落地面）：/root/dsh-plugins/fenix-dsh-dashboard-bridge/src/client 三文件逐项核验——①退役面全清：FIXED_ENTRIES 数组体无 'fenix-projects' 条目（5 条目：概览/指挥中心/配置/运维/帮助）、无 renderProjectGroup/projectRow 工厂/measureHeaderGeometry/浮层定位 machinery、无 fenix-projects-{header,list,group,section,rail-count,portal-host,empty} 任一退役 testid、index.ts 无 fenix-projects 主面板注册；②既有 polish 不回退：PROJECT_ROW_CSS 保留官方 regionArea 列表滚动条规则；③名称导航面在位：data-row-key 语义锚点（workspace: 前缀）、名称文本定位与匹配、projectPanelSelector 复用、stopPropagation/preventDefault 拦截语义、D2 归一化路径判据（分隔符统一/去尾斜杠 + title 回落）、再挂载策略（MutationObserver 或 ui.workspaces.list 订阅）、warn-only 降级；④对齐步在位：projectSync.ts 内 workspaces.create 调用、exists 判据过滤、拉取失败跳过分支。出处：spec.md 三 Requirement + design.md D1/D2/D3/D4 + tasks.md 2.1-2.3/3.1-3.2/4.1。 | pass | 0/8 | - |
| bridge-patch-mirror-auditable | 补丁镜像可评审可对账（tasks 1.1-1.2/6.1-6.2，本仓交付物硬校验）：spec/changes/move-project-nav-to-workspace-rows/plugin-patch/ 三件套齐备（BASELINE.md、fenix-dsh-dashboard-bridge.patch、baseline/ 下 5 个触达文件镜像，路径双探测：验证树相对路径缺席时回落主树 /root/fenixd 绝对路径以兼容 merge-back 时序）；BASELINE.md 含宿主 HEAD 40 位哈希与 status --porcelain 记录及快照清单；patch 为 unified diff 且仅触达声明 5 文件（src/client/{panels,index,projectSync}.ts(x) + tests/{srcContract,projectSync}.test.ts）；干净目录 patch -p1 --dry-run 回放成功、实际应用后与宿主 /root/dsh-plugins 现状逐字节一致（补丁=宿主改后态的忠实镜像，design.md D5 ④）。出处：tasks.md Deliverables 声明段 + 1.1/1.2/6.1/6.2 + design.md D5。 | pass | 0/5 | - |
| bridge-deployed-runtime-alive | 部署运行态探针（tasks 5.3 前半）：dsh-web systemd 服务 active（systemctl is-active）、宿主 3080 端口 HTTP 可达——从 /var/log/dsh-web.log 尾部取最新 token URL（形态 http://127.0.0.1:3080/?token=<64 位 base64url>，systemctl cat dsh-web ExecStart --port 3080 取证）登录请求返回 200 页面。部署是否生效到插件 bundle 由后续 dsh-web-ui 组场景实测；本场景只锚定「服务活着、新 token 可登录」的验证前置。环境依赖（dsh-web 服务存活）有 fallback: 无——服务失活属部署链未完成，如实失败转实现者补部署。 | pass | 0/4 | - |
| dsh-web-retire-no-project-entry | 侧栏「项目」入口退役无残留（spec Scenario「条目移除无残留」+「旧深链键静默退役」）：playwright 驱动真实 dsh web（运行时从 /var/log/dsh-web.log 取最新 token）——①固定条目区呈现 5 项（概览/指挥中心/配置/运维/帮助 文本可见），无 label 精确等于「项目」的条目；②插件注入分区 DOM 全无（data-testid 前缀 fenix-projects- 的元素计数为 0：portal-host/section/header/list/rail-count/group/empty 全形态）；③以 #panel=fenix-projects 旧深链打开页面：无未处理异常（pageerror 收集为空）、界面落既有兜底行为（工作区列表照常渲染）、无「项目」条目被该深链复活。出处：spec.md「侧栏项目入口退役」两 Scenario + index.ts:43-53（FIXED_ENTRIES 6→5）+ design.md D4（fenix-projects 主面板注册移除、未注册吞语义）。 | pass | 0/7 | - |
| bridge-build-lib-artifact | 插件构建产物契约（tasks 5.2）：pnpm build（tsdown）成功且宿主 lib/ 产物更新——产物内无退役符号字符串（'fenix-projects' 固定条目/分区 testid 族不再出现在 bundle 字符串面），保留每项目面板键形态（'fenix-project-' 前缀字符串在产物内，名称导航目标即它）与官方 regionArea 列表滚动条规则（既有 polish 维持，design.md D4）。出处：tasks.md 5.2 + design.md D4 退役面清单 + dsh-bridge-projects-section 能力页（lib/ symlink 即时映射部署半程）。 | pass | 0/4 | - |
| dsh-web-name-click-opens-project-panel | 工作区行名称点击打开项目详情（spec Scenario「名称点击打开项目详情」+「每项目主面板注册保留」，proposal cards 候选的替代交互面）：playwright 驱动真实 dsh web——定位 title 精确为 'fenixd' 的工作区行（[data-row-key^="workspace:"] 行内名称文本，dsh-client-ui-workspace lib/client.js ProjectRow 结构），记录行 aria-expanded 初值；点击行名称文本区 → 主面板出现 iframe 且 src 含深链 #/projects/fenixd（fenix-project-<name> main keyed 面板，encodeURIComponent('fenixd')='fenixd' 契约不变）、该行 aria-expanded 状态不变（名称点击 MUST NOT 触发展开/收缩）、无未处理异常；随后切换到官方条目再切回（反复名称导航 3 轮）→ 项目 iframe 仍唯一（count==1）、无重复注册泄漏、无未处理异常。出处：spec.md「工作区行项目名称导航」Scenario 1/Scenario 5（注册保留）+ index.ts:183/229（面板键与 projectPanelSelector）+ design.md D1。 | pass | 0/6 | - |
| dsh-web-icon-click-native-toggle | 行首图标点击维持原生展开/收缩（spec Scenario「行首图标点击展开收缩」）：playwright 驱动真实 dsh web——fenixd 工作区行行首图标区（span.slot.folder / span.slot.chevron，官方 hover folder→chevron 纯 CSS 交换既有形态）点击 → 行 aria-expanded 翻转（原生展开/收缩发生）、主面板不切换（无项目 iframe 出现、页面 hash/主面板形态不变）、无未处理异常；再次点击还原初值（回归点：双向 toggle）。插件拦截层 MUST NOT 覆盖图标区（design.md D1：行首图标区不遮挡）。出处：spec.md「工作区行项目名称导航」Scenario 2 + design.md D1 + lib/client.js（slot.folder/slot.chevron 结构）。 | pass | 0/6 | - |
| dsh-web-non-fenix-row-untouched | 非 fenix 工作区行零侵入与拦截不外溢（spec Scenario「非 fenix 工作区行零侵入」+「拦截不外溢」）：playwright 驱动真实 dsh web——先收集页面加载时插件真实请求的 api/projects URL（监听 request 取真实 prefix，不臆测），取其返回项目名集合为「fenix 项目」判定集；挑 title 不在集合内的工作区行为非 fenix 行 → ①整行点击 → aria-expanded 翻转（原生整行点击展开/收缩维持）、无项目 iframe 导航、无未处理异常；②fenixd 行行尾 rowActions 省略号菜单按钮点击 → 无导航发生（无项目 iframe/主面板不变）、无未处理异常（官方 rowActions stopPropagation 链未被名称拦截层捕获，tasks 3.3 projectSessionStarter 保留不动——不点击新会话确认项避免真实创建会话副作用）。出处：spec.md Scenario 3/Scenario 4 + design.md D2（路径优先判据消除同名标题误判）+ tasks.md 3.3。 | pass | 0/7 | - |
| dsh-web-anchor-drift-silent-degrade | 锚点漂移静默降级（spec Scenario「锚点漂移静默降级」）：playwright 驱动真实 dsh web——page.evaluate 抹除 fenixd 工作区行的 data-row-key 属性并触发工作区列表容器 childList 变更（append 即 remove 空节点，驱动 design.md D1 再挂载策略的重扫），等待重扫窗口 → 名称导航静默失效（点击 fenixd 行名称无项目 iframe 导航）、行维持原生行为（点击行体 aria-expanded 翻转）、全程无未处理异常（pageerror 为空；warn 级 console 允许——spec SHALL「静默不拦截、MUST NOT 产生控制台未处理异常」）；不做任何破坏性兜底（页面结构无插件注入的补救 DOM）。出处：spec.md Scenario 5 + design.md D1（锚点不可达→该行不装拦截层、warn-only、重扫前校验存活）+ proposal.md Impact（上游升级锚点漂移为可接受降级）。 | pass | 0/6 | - |
| dsh-web-project-removed-row-fallback | 删除项目行保留且名称点击回退原生（spec Scenario「删除项目行保留且不跳转」）：playwright 驱动真实 dsh web——route 层（仅本浏览器上下文、零持久副作用）拦截 api/projects 返回不含 fenixd 的项目列表（模拟上游移除，形状与真实应答一致 {projects:[{name,path,exists}]}）→ reload 后：fenixd 工作区行仍渲染（工作区行由 dsh registry 驱动、插件对齐只增不删）、点击其行名称不发生导航（无项目 iframe）、点击行体 aria-expanded 翻转（回退原生整行折叠，匹配判据不再命中→拦截层不装）、无未处理异常。不真实删除 fenixd 项目（会毁真实 daemon 项目状态）。出处：spec.md「项目工作区自动对齐」Scenario 2 + design.md D2（项目消失→判据不命中→拦截层不装→原生行为）+ design.md D3（对齐只增不删）。 | pass | 0/6 | - |
| dsh-web-projects-fetch-failure-skip-align | 项目列表拉取失败不误伤（spec Scenario「拉取失败不误伤」）：playwright 驱动真实 dsh web——route 层中断 api/projects（abort，模拟上游不可达/超时）→ reload 走启动即拉取失败路径（startProjectSync 启动即拉取，projectSync.ts:182）：api/projects 请求确实发出且失败（route 拦截计数>0）、本轮对齐整体跳过——工作区列表全部行维持原生渲染（不建不删）、无项目 main 面板注册（无项目 iframe 出现）、无未处理异常（pageerror 为空，插件侧仅 warn）。60s 周期与焦点重拉语义由场景 1 的 startProjectSync 单测承载，不等待真实周期。出处：spec.md Scenario 3（10s 超时判据不变、仅按既有纪律 warn）+ design.md D3（拉取失败/超时跳过整轮）+ projectSync.test.ts「启动即拉取」既有用例。 | pass | 0/5 | - |

## 本轮场景集变更

当前稳定场景集共 12 个（第 1 轮）。

- 首轮写入 12 个场景

