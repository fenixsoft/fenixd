# 缺陷修复模式配置

<!-- knowledge: capability=bug-repair-mode-config rev=1
     sources=spec/archive/2026-09-12-add-bug-repair-mode-config -->

`admin.bug_repair_mode`：验证失败修复方式的显式配置，覆盖参数定义、校验、Dashboard UI 与热更新生效。

## 规则

- 取值限 `inplace`（原地打回）或 `derive`（派生 fix-* 子 SPEC）；参数未配置时缺省 `inplace`，验证失败处置走原地打回路径。
- 配置校验拒绝非法取值（非字符串或非上述两个枚举值），拒绝方式与既有 `admin.*` 参数护栏一致，非法配置不生效。
- Dashboard 设置页系统页签展示「验证失败修复方式」配置项：未配置时显示缺省值「原地打回」（非空白或未定义）；修改后写入 `admin.bug_repair_mode` 并持久化，刷新页面后回显所选值。
- 前端类型定义与后端配置结构同步，防 TS 类型缺失复发。
- 随既有配置热更新机制（30s mtime 检测）生效：下一次 bug-found 事件按最新有效值分流，不得在引擎初始化时缓存该值；运行中切换模式无需 daemon 重启。

## 溯源

- 2026-09-12 2026-09-12-add-bug-repair-mode-config — 新建本页：inplace/derive 枚举与缺省值、非法取值校验护栏、系统页签展示与修改持久化、30s 热更新生效语义。
