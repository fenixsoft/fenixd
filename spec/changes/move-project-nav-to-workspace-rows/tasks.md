## Deliverables

```yaml
- path: spec/changes/move-project-nav-to-workspace-rows/plugin-patch/BASELINE.md
  kind: new
- path: spec/changes/move-project-nav-to-workspace-rows/plugin-patch/fenix-dsh-dashboard-bridge.patch
  kind: new
- path: spec/changes/move-project-nav-to-workspace-rows/plugin-patch/baseline/fenix-dsh-dashboard-bridge/src/client/panels.tsx
  kind: new
- path: spec/changes/move-project-nav-to-workspace-rows/plugin-patch/baseline/fenix-dsh-dashboard-bridge/src/client/index.ts
  kind: new
- path: spec/changes/move-project-nav-to-workspace-rows/plugin-patch/baseline/fenix-dsh-dashboard-bridge/src/client/projectSync.ts
  kind: new
- path: spec/changes/move-project-nav-to-workspace-rows/plugin-patch/baseline/fenix-dsh-dashboard-bridge/tests/srcContract.test.ts
  kind: new
- path: spec/changes/move-project-nav-to-workspace-rows/plugin-patch/baseline/fenix-dsh-dashboard-bridge/tests/projectSync.test.ts
  kind: new
```

> 跨仓交付形态见 design.md D5：实现面在 `/root/dsh-plugins` 宿主主树直改（用户裁决落仓 fenixd，偏离声明见 design.md D5 偏离声明段）；本仓交付物为基线快照 + 补丁镜像。宿主触达文件为 `/root/dsh-plugins/fenix-dsh-dashboard-bridge/` 下 src/client/{panels,index,projectSync}.ts(x) 与 tests/{srcContract,projectSync}.test.ts 共 5 文件——绝对路径不可进声明段（等同未声明），故以本段注记与 design.md/proposal.md Impact 记载为准，宿主改动本体以补丁镜像交付。

## 1. 基线快照（跨仓只读，最先执行）

- [ ] 1.1 记录宿主基线：`git -C /root/dsh-plugins rev-parse HEAD` 与 `git -C /root/dsh-plugins status --porcelain` 原样写入 `plugin-patch/BASELINE.md`（含快照文件清单、宿主未提交态属 2026-11-03 徽标改造的备忘、恢复路径说明）
- [ ] 1.2 只读复制拟触达 5 文件（src/client/{panels,index,projectSync}.ts(x)、tests/{srcContract,projectSync}.test.ts）当前内容至 `plugin-patch/baseline/` 镜像路径，`diff -r` 校验快照与宿主逐字节一致

## 2. 侧栏项目入口退役（宿主 /root/dsh-plugins 直改）

- [ ] 2.1 panels.tsx：`FIXED_ENTRIES` 6→5（移除 `fenix-projects`）；删除分区 machinery（`renderProjectGroup`、`projectRow` 工厂、`measureHeaderGeometry`、浮层定位、窄轨计数徽标、分区标题拦截层）及 `projectGroupStore` 中 expanded/activeProject 残余引用
- [ ] 2.2 panels.tsx：`PROJECT_ROW_CSS` 清理——保留官方 regionArea 列表滚动条规则与仍被引用键，删除分区列表失效选择器
- [ ] 2.3 index.ts：移除 `fenix-projects` 主面板注册与 sidebar.panellist 注入项（保留每项目 `fenix-project-<name>` keyed 面板注册与 `deepLinkPanels` 契约）

## 3. 工作区行名称导航实现（宿主直改）

- [ ] 3.1 新增名称导航模块（落位约束：新增逻辑 MUST 落在既有触达 5 文件内——与 `resolveWorkspaceIdForProject`/`projectPanelSelector` 同域置 index.ts 或 panels.tsx，MUST NOT 新增源文件，以保持 Deliverables 基线清单、6.1 触达面与 design.md D5 适用范围一致）：D2 匹配判据（归一化路径相等优先、title==项目名精确相等回落）× `ui.workspaces.list.getSnapshot().items` 枚举，产出「项目↔行」映射
- [ ] 3.2 命中行 `span.projectText` 名称文本 rect 上挂透明拦截层（absolute + stopPropagation + preventDefault → 复用 `projectPanelSelector(ctx)(name)`），图标区不遮挡；锚点链仅 data-row-key 前缀 `workspace:` + 名称文本两步，不可达即该行不装拦截层并 warn 一次，无未处理异常；拦截层为命令式外挂 DOM，MUST 按 design.md D1 再挂载策略在宿主重渲染后补挂（重扫前校验锚点与既有拦截层存活，warn-only）
- [ ] 3.3 `projectSessionStarter` 保留不动（行尾新会话/菜单按钮属官方 rowActions，验证其 stopPropagation 链未被拦截层捕获）
- [ ] 3.4 tests/srcContract.test.ts：新增名称导航判据单测（归一化路径优先命中、title 回落、同名标题非同路径不命中、锚点缺失不装层四态），落既有触达文件内不新增测试文件

## 4. 项目工作区自动对齐实现（宿主直改）

- [ ] 4.1 projectSync.ts：60s 同步回调内追加对齐步——`parseProjectPath` 过滤 `exists:true` 项目 × 工作区快照（3.1 同序判据）求差，缺失者 `workspaces.create({path})`（不 startSession）；拉取失败/超时（10s 判据不变）跳过整轮；只增不改不删，失败路径 warn
- [ ] 4.2 tests/projectSync.test.ts：新增对齐单测（新建/已存在跳过/删除项目不删工作区/拉取失败整轮跳过四态）

## 5. 测试、构建与实拍验证

- [ ] 5.1 tests/srcContract.test.ts：钉值更新（固定条目集合=5、每项目主面板注册契约、`#panel=fenix-projects` 未注册吞语义），`pnpm -C /root/dsh-plugins/fenix-dsh-dashboard-bridge exec vitest run` 全量绿
- [ ] 5.2 `pnpm -C /root/dsh-plugins/fenix-dsh-dashboard-bridge build`（tsdown）成功且 lib/ 产物更新
- [ ] 5.3 部署验证链：`systemctl restart dsh-web` → 从 `/var/log/dsh-web.log` 取新 token URL → playwright 命名会话（-s 隔离）重登
- [ ] 5.4 playwright 逐 Scenario 实拍（截图落 /root/fenixd/.history/，覆盖 spec.md 全部 11 个 Scenario）：名称点击开面板且不折叠/图标点击仅折叠/非 fenix 行零侵入/菜单·新会话·右键·拖拽照常/条目 5 项无残留/`#panel=fenix-projects` 旧深链不异常/新项目自动出现/删除项目行保留不跳转/名称反复切换主面板注册不重复不泄漏/锚点漂移模拟（evaluate 抹除 `data-row-key` 后行维持原生、无未处理异常）/拉取失败模拟（中断 `api/projects` 路由后本轮对齐跳过、侧栏状态无变化）
- [ ] 5.5 控制台零未处理异常核查（名称导航与对齐两条错误路径均 warn-only）

## 6. 补丁镜像与收尾（本仓）

- [ ] 6.1 `diff -ruN plugin-patch/baseline/ <宿主现状>` 生成 `plugin-patch/fenix-dsh-dashboard-bridge.patch`（仅拟触达 5 文件），并在干净目录 `patch -p1 --dry-run` 回放校验可应用
- [ ] 6.2 BASELINE.md 补记改后状态摘要（触达文件与改动要点、验证结论一行），确认 plugin-patch/ 与 Deliverables 声明逐条对齐
