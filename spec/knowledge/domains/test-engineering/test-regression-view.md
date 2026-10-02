<!-- knowledge: capability=test-regression-view rev=1 sources=spec/archive/2026-09-25-add-test-regression-tab -->

# 测试回归分面与配置

dashboard 项目页「测试回归」分面的结果展示规则，以及设置页「质量」页签的周期性全量回归配置通道。

## 现行规则

- 项目页「测试回归」分面（`regression` key）由独立组件承载，active 门控——仅选中该分面时拉取数据，未选中零请求；数据来自 `GET /api/regression/result?project=<name>`。
- 分面按快照状态渲染三种形态：全绿（`passed`）为概览卡片——测试路径（`cmd`）、用例总数、通过数、执行时间（本地时区）、总耗时，`long_tests` 非空时仍展示长耗时用例表；存在失败/错误/超时/长耗时用例时在概览下渲染结果表格，列至少含用例名、文件:行、耗时、分类；`never_run`/`parse_error` 为引导态（未执行过全量回归 / 结果不可解析 + 原因），不报错、不显示空表。
- 分面不承载「是否周期执行」开关配置（归设置页「质量」页签），但提供「立即执行全量回归」手动触发按钮（`POST /api/regression/run`），成功后提示已受理并进入运行中态（轮询快照更新）。
- 只读 API `GET /api/regression/result`：返回快照全字段（status、计数、耗时、failures、long_tests、阈值等）；项目不存在 → 404；快照缺失 → `{status: "never_run"}`；快照损坏 → `{status: "parse_error", reason: <非空>}`；不因快照问题抛 500。
- 设置页「质量」页签的周期性全量回归配置卡片（与「周期性代码审查」同层）：承载 `admin.regression.enabled` 开关（缺省 false，键缺失回显为关闭）；长耗时阈值（`regression.long_test_threshold_seconds`）以只读方式说明来源，编辑经既有 `GET/POST /api/verify-yaml` 端点入口，不为该阈值另开第二写入路径（双写会让来源分叉）。
- `admin.regression.enabled` 的读写经既有 `GET/POST /api/config` 通道，保存后持久化并回显；该键须在 `core/dashboard/data/config_admin.py` 的 `_SOURCE_KEYS` 登记并纳入写路径 patch 合并（对齐 `admin.code_review` 的四处同款改造），否则前端提交的键被静默丢弃、开关保存后不回显。

## 溯源

- 2026-09-25 add-test-regression-tab（spec/archive/2026-09-25-add-test-regression-tab） — 新增「测试回归」分面三形态渲染与手动触发、只读结果 API 的容错语义、设置页质量页签周期回归配置与 _SOURCE_KEYS 登记要求
