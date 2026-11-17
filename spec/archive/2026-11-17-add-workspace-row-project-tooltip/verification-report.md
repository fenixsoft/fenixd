# 验证报告：add-workspace-row-project-tooltip

> ⚠️ 本报告由框架于 2026-11-10T04:39:26Z 自动合成（裁决 Agent 未写报告，已由框架合成），内容为结构化验证产物（report.json / .fenix-run-result.json）的忠实渲染。
> 报告时效标记（判定本报告是否属上一轮）：合成源轮次指纹：report.json@2026-11-10T04:39:25.884039+00:00+run-result@mtime1794285565935546754

## 结论：✅ 通过（verified）

**状态：verified — 13/13 场景通过，0 失败，0 错误（全部场景通过）**

全绿快道: 13/13 场景通过、0 失败 0 警告——无分类对象，跳过 judge 机械 verified

| 指标 | 数量 |
| --- | --- |
| 通过 | 13 |
| 失败 | 0 |
| 错误 | 0 |
| 产品 Bug | 0 |
| 本链增量 Token（输入） | 4.14M |
| 本链增量 Token（输出） | 0.05M |


## 场景结果

| 场景 | 描述 | 状态 | 失败断言 | 分类 |
| --- | --- | --- | --- | --- |
| bridge-vitest-tooltip-suite-green | 宿主插件行为级单测全绿（tasks 2.2/3.4/4.1）：/root/dsh-plugins/fenix-dsh-dashboard-bridge vitest run 全量绿——投影解析新面（parseProjectSummaries 四类 fixture：正常摘要 / 缺失 description / exists:false 降级项 / 字段全缺 null 口径，projectSync.test.ts）与 wsTooltip 契约面（srcContract.test.ts「工作区行项目富提示契约面」：锚属性 data-fenix-wstip / testid fenix-wstip-card / 延迟 500ms / 宽 300 / STATUS_PILL_MAX 4、状态→tone 映射与暗面派生色钉值、深卡样式逐值含零 animation/transition 红线、shouldRenderRichTip 回退三分支、tipCardSpec 内容契约、statusPillsOf 折叠 +N）；既有契约不回归（名称导航判据、reconcileProjects、parseProjectNames、对齐四态）。出处：tasks.md 2.1/2.2/3.1-3.4/4.1 + spec.md 全部 Scenario 的纯判定面承载 + wsTooltip.ts:50-94（STATUS_TONE_MAP/TONE_DARK 钉值单源）。 | pass | 0/3 | - |
| bridge-patch-mirror-auditable | 补丁镜像可评审可对账（tasks 5.1，本仓交付物硬校验）：spec/changes/add-workspace-row-project-tooltip/plugin-patch/ 三件套齐备（BASELINE.md、fenix-dsh-dashboard-bridge.patch、baseline/ 下 4 个拟触达文件镜像，路径双探测：验证树相对路径缺席时回落主树 /root/fenixd 绝对路径以兼容 merge-back 时序）；BASELINE.md 含宿主 HEAD 40 位哈希、porcelain 记录与快照清单；patch 为 unified diff 且触达 5 文件——4 个修改面（src/client/projectSync.ts、src/client/panels.tsx、tests/projectSync.test.ts、tests/srcContract.test.ts）+ 1 个新增面 src/client/wsTooltip.ts（git 风格 --- /dev/null → +++ b/... 新文件形态）；干净目录 patch -p1 --dry-run 回放成功、实际应用后与宿主 /root/dsh-plugins/fenix-dsh-dashboard-bridge 现状逐字节一致（补丁=宿主改后态的忠实镜像，design.md D5 ④）。出处：tasks.md Deliverables 声明段 + 1.1/1.2/5.1 + design.md D5。 | pass | 0/6 | - |
| dsh-web-deployed-runtime-alive | 部署运行态探针（tasks 4.2 中段前置）：dsh-web systemd 服务 active（systemctl is-active）、宿主 3080 端口 HTTP 可达——从 /var/log/dsh-web.log 尾部取最新 token URL（形态 http://127.0.0.1:3080/?token=<64 位 base64url>，systemctl cat dsh-web ExecStart --port 3080 取证）登录请求返回 200 页面。部署是否生效到插件 bundle 由后续 ws-tip-* 组场景实测；本场景只锚定「服务活着、新 token 可登录」的验证前置。环境依赖（dsh-web 服务存活）有 fallback: 无——服务失活属部署链未完成，如实失败转实现者补部署。出处：tasks.md 4.2 + design.md D5 实施序 ③。 | pass | 0/4 | - |
| bridge-lib-artifact-tooltip-contract | 插件构建产物契约（tasks 4.2 前半）：pnpm build（tsdown，lib/ 产物经 symlink 即时映射宿主部署半程）成功且 lib/ bundle 字符串面含本 SPEC 新增契约——富卡 testid fenix-wstip-card 与锚属性 data-fenix-wstip、投影解析 parseProjectSummaries/shouldRenderRichTip、空口径文案「暂无简介」、运行态胶囊文案「运行中·未托管」、深卡底色 #2C2C2E、数值 tabular-nums、统计行「任务 / 活跃 Agent」文案；既有面不回退（fenix-project- 面板键前缀、regionArea 列表滚动条规则、fenix-wsnav-overlay 拦截层 testid）。出处：tasks.md 4.2 + design.md D2/D3 + wsTooltip.ts:26-109（常量单源）。 | pass | 0/5 | - |
| ws-tip-hover-rich-card-real-data | 悬停显示富提示（spec Scenario「悬停显示富提示」正向主链路，真实 /api/projects 端点数据不打 mock）：playwright 驱动真实 dsh web（token 从 /var/log/dsh-web.log 取）——定位 title 精确为 fenixd 的工作区行（[data-row-key^="workspace:"] 行内 [data-testid=fenix-wsnav-overlay] 拦截层）hover 超 500ms 延迟窗 → 行右侧浮出深卡富提示：data-testid=fenix-wstip-card 在场可见、data-fenix-wstip=fenixd 锚属性、自上而下含名称标题（#fff 14px）、运行态胶囊（真实 fenixd daemon=running → 「运行中」good）、路径行 /root/fenixd、简介行、非零状态胶囊组（≥1 枚）、统计行格式 `任务 <数字>/<数字> 个 · 活跃 Agent <数字> 个` 且数值 tabular-nums；深卡样式逐值断言（dsh 原生 tooltip 实测规格）：底 rgb(44,44,46)=#2C2C2E、圆角 16px、宽 300px、次文本色 rgb(207,211,214)=#cfd3d6、position fixed、pointer-events none；定位在拦截层 rect 右侧（卡 left ≥ 拦截层 right，design.md D2 锚定口径）；mouseleave 即收（卡 display:none）；全程无未处理异常。出处：spec.md Scenario 1 + wsTooltip.ts:96-109/231-274（renderTipCard 结构）+ 实测预检 2026-11-10。 | pass | 0/9 | - |
| ws-tip-empty-null-placeholders | 空口径与「—」不伪装（spec Scenario「简介一行截断与空口径」空支 +「任务与活跃 Agent 统计行」null 支 +「状态胶囊组」全零支）：playwright 驱动真实 dsh web，route 层（仅本浏览器上下文、零持久副作用）mock /api/projects 返回受控投影——description 缺失、daemon/hosting 缺失、status_counts 全零、task_done/task_total/active_runs 全 null、discovered:true、exists:true、path=/root/fenixd（命中既有工作区，对齐步零动作）→ reload 后 hover 显示富提示：①简介行显示「暂无简介」且为弱化色（rgba(207,211,214,.55) 相位）；②统计行显示「任务 — 个 · 活跃 Agent — 个」（null→「—」不伪装 0）；③无运行态胶囊（daemon 缺失不渲染，文本不含「运行中/未运行」）；④「自动发现」胶囊在场（discovered:true → muted）；⑤状态胶囊组整段不渲染（全零 → 卡内 span 仅标题+自动发现 2 枚）；全程无未处理异常。出处：spec.md Scenario 2/3/4 + wsTooltip.ts:116-124/143-165/201-214（daemonPillOf/statusPillsOf/tipCardSpec 判定）。 | pass | 0/8 | - |
| ws-tip-long-description-ellipsis | 长简介单行截断（spec Scenario「简介一行截断与空口径」超长支）：playwright 驱动真实 dsh web，route 层 mock /api/projects 返回 description 为 200+ 汉字超长文本（含唯一标记前缀）的 fenixd 投影 → reload 后 hover 显示富提示：简介行仅显示一行——clientHeight ≈ 单行高（line-height 16px ±2px）、scrollWidth > clientWidth（内容确被截断）、computed white-space nowrap / overflow hidden / text-overflow ellipsis（CSS ellipsis 生效）；非简介区（名称/路径）不受影响；全程无未处理异常。出处：spec.md Scenario 2 超长支 + wsTooltip.ts:248-251（descCss ellipsis 三件套）。 | pass | 0/7 | - |
| ws-tip-status-pills-fold-plus-n | 状态胶囊组渲染与 +N 折叠（spec Scenario「状态胶囊组」非零支/超 4 折叠支）：playwright 驱动真实 dsh web，route 层 mock /api/projects 两相位——相位一 status_counts 六非零 {ready:2,reviewing:1,implementing:3,verified:4,blocked:1,done:5}（STATUS_LABEL_MAP 键序 ready→reviewing→implementing→verified→blocked→done）→ 胶囊折叠为前 4 枚 + 摘要：卡内胶囊文本序恰为 ['就绪 2','评审中 1','实现中 3','已验证 4','+2']（第 5/6 非零 done/blocked 折入 +2，muted 摘要胶囊仅显 +N 不带计数）；相位二 status_counts 三非零 {ready:1,testing:2,pushed:3} → 全显无折叠 ['就绪 1','验证中 2','已推送 3']；胶囊形态断言（首枚）：border-radius 999px、font-size 12px；两相位均无零值状态胶囊混入；全程无未处理异常。出处：spec.md Scenario 3 + wsTooltip.ts:134-165（STATUS_PILL_MAX/statusPillsOf 键序折叠）+ srcContract 钉值。 | pass | 0/6 | - |
| ws-tip-non-fenix-row-zero-intrusion | 非 fenix 行零侵入（spec Scenario「非 fenix 行零侵入」）：playwright 驱动真实 dsh web，route 层 mock /api/projects 仅返回 fenixd 一行（其余真实工作区行必然不在插件数据源内，判据确定性优于请求监听推断；fenixd path 命中既有工作区，对齐步零动作）→ reload 后：fenixd 行拦截层在场（对照组）；挑一个 title 非 fenixd 的工作区行：行内 [data-fenix-wsnav] 拦截层计数 0（无导航层注入）、hover 其名称文本 800ms+（超 500ms 延迟窗）无 fenix-wstip-card 出现（无富提示、无额外 DOM 注入）、整行点击 aria-expanded 翻转（原生展开/收缩照常）；全程无未处理异常。出处：spec.md Scenario 5 + panels.tsx:383-424（ensureOverlay 仅命中行装层）。 | pass | 0/6 | - |
| ws-tip-click-still-navigates | 点击行为不变（spec Scenario「点击行为不变」）：playwright 驱动真实 dsh web（真实端点数据）——fenixd 行 hover 显示富提示期间点击行名称区（富卡 pointer-events:none 不吞点击，场景 ws-tip-hover-rich-card-real-data 已断样式）：主面板出现 iframe 且 src 含深链 #/projects/fenixd（fenix-project-fenixd main keyed 面板，既有导航契约不变）、页面 hash 含 fenix-project-fenixd；导航后项目 iframe 唯一（count==1，无重复注册泄漏）；全程无未处理异常。出处：spec.md Scenario 6 + wsTooltip.ts:105-109（TIP_CARD_CSS pointer-events:none）+ panels.tsx:397-401（拦截层 click 导航链不变）。 | pass | 0/7 | - |
| ws-tip-native-tip-mutex | 原生提示互斥与插件侧消解（spec Scenario「原生提示互斥」）：playwright 驱动真实 dsh web（真实端点数据）——fenixd 行 hover 显示富提示后：①body 直子浮层扫描：除 [data-fenix-wstip] 富卡自身外，无可见 position:fixed/absolute 且 textContent 含 fenixd 的浮层节点（原生三行提示与富提示不得同时可见）；②消解观察器行为面（wsTooltip.ts createNativeTipSuppressor 手段②）：富提示激活期向 body 直子注入 position:fixed 且含 fenixd 文本的模拟原生提示节点 → 400ms 内被置 display:none（命中隐藏）、注入不含 fenixd 文本的对照节点 → 不被误伤（保持可见）、富卡自身不受观察器影响；③leave 后注入节点不再被隐藏（消解观察器已停，display 恢复语义）；全程无未处理异常（pageerror 为空；warn 级允许——静默降级纪律 warn-only）。出处：spec.md Scenario 7 + wsTooltip.ts:293-348（createNativeTipSuppressor）+ panels.tsx:412-417（手段① mouseover/out/move stopPropagation）。 | pass | 0/7 | - |
| ws-tip-invalid-data-fallback-native | 数据失效回退原生（spec Scenario「数据失效回退原生」）：playwright 驱动真实 dsh web，route 层 mock /api/projects 两相位——相位一 fenixd exists:false（降级项，parseProjectPath 返回 null、行匹配走标题兜底仍装拦截层）；相位二 exists:true 但 error:"describe failed"（非空降级标记）→ 两相位均 reload 后 hover 拦截层超延迟窗：无 fenix-wstip-card 出现（不渲染残缺富提示，该行回退 dsh 原生提示）、拦截层仍在场（导航链不受数据降级影响）、全程无未处理异常。出处：spec.md Scenario 8 + wsTooltip.ts:167-175（shouldRenderRichTip 三分支）+ projectSync.ts:171-217（exists/error 降级标记投影）。 | pass | 0/6 | - |
| ws-tip-static-redline-scroll-hide | 静态渲染红线与滚动即收（spec Scenario「静态渲染红线」+「mouseleave/滚动/行卸载即收」）：playwright 驱动真实 dsh web（真实端点数据）——①显隐循环 2 轮（hover 显 → 离开收 → 再 hover 显）幂等：每轮富卡 computed animationName 为 none、transitionDuration 为 0s（零 CSS animation/transition，纯 display 切换）、style.cssText 无 animation/transition 字面；②滚动即收：富卡可见期间 document.dispatchEvent(new Event('scroll'))（scroll guard capture 链）→ 300ms 内富卡隐藏；③富卡显隐仅 display 值切换（block/none），无 opacity/visibility 过渡痕迹；全程无未处理异常。出处：spec.md Scenario 9 + wsTooltip.ts:364-374（onScroll capture guard）+ TIP_CARD_CSS 零动画声明（srcContract 钉值）。 | pass | 0/5 | - |

## 本轮场景集变更

当前稳定场景集共 13 个（第 1 轮）。

- 首轮写入 13 个场景

