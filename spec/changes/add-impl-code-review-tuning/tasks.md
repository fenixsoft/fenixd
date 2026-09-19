# Tasks: add-impl-code-review-tuning

## Deliverables

```yaml
- path: core/config.py
  kind: modify
- path: .fenix/config.template.yaml
  kind: modify
- path: core/agent_runner/runner.py
  kind: modify
- path: core/agent_runner/prompt_builder.py
  kind: modify
- path: core/dashboard/data/config_admin.py
  kind: modify
- path: core/dashboard/static/src/pages/settings/components/QualityPanel.tsx
  kind: modify
- path: core/dashboard/static/src/services/dashboard.ts
  kind: modify
- path: docs/help/08-dashboard.md
  kind: modify
- path: docs/help/09-config.md
  kind: modify
- path: tests/test_impl_code_review_tuning.py
  kind: new
```

## 1. 配置读取器（core/config.py）

- [ ] 1.1 新增 `ConfigLoader.get_impl_code_review_timeout_sec(config) -> int`：读取 `verify.impl_code_review_timeout_sec`；缺省 `600`；仅接受**正整数 int**（`bool` 不算 int），其余（缺失/非 dict/str/float/≤0）一律回退 `600`；不抛异常。
- [ ] 1.2 新增 `ConfigLoader.get_impl_code_review_concurrency(config) -> int`：读取 `verify.impl_code_review_concurrency`；缺省 `2`；语义与 1.1 同（仅正整数 int，非法回退缺省）。
- [ ] 1.3 新增 `ConfigLoader.get_impl_code_review_effort(config) -> str`：读取 `verify.impl_code_review_effort`；缺省 `"low"`；合法值恰为 `"low"`/`"medium"`/`"high"`，其余一律回退 `"low"`；不抛异常。
- [ ] 1.4 三读取器各自独立（一者非法不影响另两者）；在既有 `get_impl_code_review_enabled`（`core/config.py`）同区域添加，docstring 说明回退语义。
- [ ] 1.5 三键 MUST NOT 被加入 `resolve_config` 的缺省填充列表（保持「键缺失 → 读取器回退」单一路径，避免 defaults 与读取器缺省双源漂移；对齐 `get_impl_code_review_enabled` 现状）。docstring 内注明该约定。

## 2. run 级 ocr 配置注入（core/agent_runner/runner.py）

- [ ] 2.1 `_write_run_ocr_config`：在 `custom_providers["fenix-impl"]` 条目中新增 `"timeout_sec"`，取值 `ConfigLoader.get_impl_code_review_timeout_sec(self.config)`；与既有字段同批原子写入（沿用现有 tempfile + `os.replace`，不新增独立写路径）。
- [ ] 2.2 更新 `_write_run_ocr_config` docstring，说明 `timeout_sec` 的来源、语义（ocr LLM 单请求超时，秒）与缺省。
- [ ] 2.3 落地实测核对（可选但推荐）：本地起一个只接受 TCP 连接、不回包的端点，令 `timeout_sec: 20` 指向它，确认 `retry_report.requests[*].attempts[*].duration_to_headers_ms` ≈ 20000 而非 300000（证明注入为**确定性生效**而非仅落盘）；核对完清理临时目录，禁止提交探针产物。
- [ ] 2.4 确认 run 级 ocr `config.json` 的**写者唯一**：全仓检索 `custom_providers` / `.opencodereview` / `ocrcfg`，除 `runner._write_run_ocr_config` 外不得存在第二处写者（若存在且不写 `timeout_sec`，该通道下的 run 会退回 300s 默认——属真实缺口，须一并注入或记入风险）。检索结论写入实现结果文件留痕。

## 3. 提示词命令承载（core/agent_runner/prompt_builder.py）

- [ ] 3.1 `_impl_code_review_section`：命令示例注入 `--concurrency <n>` 与 `--effort <v>`，取值来自 `get_impl_code_review_concurrency` / `get_impl_code_review_effort`；保持 `--format json --output` 等既有串不变。
- [ ] 3.2 同段更新「成本控制」条：明确并发与力度的取值来自配置（用户可调），并保持 MUST NOT 传 `--max-tokens-budget` / `--max-tokens` 的既有约束文案。
- [ ] 3.2b **消除与既有文案的矛盾**：`prompt_builder.py:578-579` 现文为「改用 `--effort low\|medium\|high` 控制审查深度；若确需限制规模，用 `--exclude` 排除生成物/夹具等非本次改动文件，而非砍预算」——**裸露的 `--effort` 令牌**在注入 `--effort <配置值>` 后仍成立，但措辞会让实现者以为 effort 需自行选择而覆盖配置值。该条 MUST 改写为「审查力度已由框架经 `--effort <值>` 注入（用户可配置 `verify.impl_code_review_effort`），MUST NOT 自行改写该取值」，否则新键对实现者形成隐性失效。该改写在开关关闭时仍在段内——受「开关关闭零注入」Scenario 约束，MUST 仅修改开关开启分支的字符串常量，不影响关闭分支返回空串。
- [ ] 3.3 更新 `_impl_code_review_section` docstring，覆盖新增的并发/力度注入。

## 4. Dashboard 后端（core/dashboard/data/config_admin.py）

- [ ] 4.1 受管键清单新增 `"verify.impl_code_review_timeout_sec"` / `"verify.impl_code_review_concurrency"` / `"verify.impl_code_review_effort"`（与既有 `verify.impl_code_review` 相邻，附注释）。
  - **落点澄清**：逐键清单是 `_SOURCE_KEYS`（`config_admin.py:46-110`，`verify.impl_code_review` 在 `:82`），`_MANAGED_KEYS`（`:22`）只列**节级**键 `["llm","agents","gates","runs","verify","hooks"]`，MUST NOT 往里加子键。`_SOURCE_KEYS` 缺登记 → `sources` 无该键且 `tests/test_dashboard_data_modules_contract.py:53` 的常量可达性契约与各 `sources[...]` 断言失配。
- [ ] 4.1b 「同步用户级设置」白名单同步：`_SYNC_PAGE_KEYS["quality"]["verify"]`（`config_admin.py:1525`）现为 `["impl_code_review"]`，MUST 扩为含三新键（`["impl_code_review", "impl_code_review_timeout_sec", "impl_code_review_concurrency", "impl_code_review_effort"]`）。缺此步时「同步用户级设置」按钮会**静默漏同步**三键（功能对用户不可见）。既有断言 `tests/test_dashboard_data.py:147` 为 `assertIn("impl_code_review", ...)`，扩列表不破坏它。
- [ ] 4.2 sources 标注：三键在 `verify` 节显式定义时标注 `"project"`（严格类型判定，缺省/非法不标）。
- [ ] 4.3 有效配置回显：三键按缺省填充后回显（缺省 `600`/`2`/`"low"`），与既有 `impl_code_review` 回显同处。
  - 落点共 4 处、MUST 手写镜像并保持同式（本模块无读/写/生效回显三镜像的单点抽取）：`read_config` 的项目级显式回显段（`config_admin.py:191-192` 邻位）、`read_config` 的缺省段（`config_admin.py:318-320`）、`read_effective_config` 的缺省段（`config_admin.py:530-535`）与生效回显段（`config_admin.py:642-644`）；缺省段 MUST 含 `impl_code_review_timeout_sec: 600` / `impl_code_review_concurrency: 2` / `impl_code_review_effort: "low"`。
  - 注意两个键与既有 `impl_code_review` **回显语义相反**（后者缺省不回显）：三新键**恒回显缺省值**（spec「缺省回显」Scenario），`impl_code_review` 缺省时仍 MUST 缺席。任一镜像漏改都会使该断言在 `read_config` 或 `read_effective_config` 侧失败。
- [ ] 4.4 保存合并链路：三键支持合并写回（缺失不填充、非法值按既有校验策略处理），MUST NOT 影响其它 `verify.*` 键。

## 5. Dashboard 前端（质量页签）

- [ ] 5.1 `core/dashboard/static/src/services/dashboard.ts`：`ConfigData` 的 `verify` 段补 `impl_code_review_timeout_sec?: number` / `impl_code_review_concurrency?: number` / `impl_code_review_effort?: 'low' | 'medium' | 'high'`，附注释。
- [ ] 5.2 `QualityPanel.tsx`：在既有「收尾代码质量审查」开关下方新增三项编辑控件——超时（数字输入，单位"秒"，正整数校验）、并发（数字输入，正整数校验）、力度（下拉 `low`/`medium`/`high`）；回填缺省 `600`/`2`/`low`；`handleSave` 序列化三键。
- [ ] 5.3 三控件加 `data-testid`（`impl-code-review-timeout` / `impl-code-review-concurrency` / `impl-code-review-effort`）供测试与验证定位；保存行为遵循既有作用域（项目级/用户级）与既有保存链路。
- [ ] 5.4 **保持既有开关「缺省不回显」约定**：`config.verify.impl_code_review` 缺席时开关仍渲染为关（`!== true` 即 false），三新键的缺省回显 MUST 只覆盖新键——`tests/test_dashboard_data.py:59,68`、`tests/test_system_settings_config.py:229,242` 对 `verify` 段做**整字典相等**断言，`tests/test_dashboard_data.py:108` 对 `sources["verify.impl_code_review"]` 断言存在且为 `"user"`；三新键 MUST 登记进 `_SOURCE_KEYS`（缺省 `"user"`），但**不得**改变 `impl_code_review` 的「缺省不回显 + sources 恒在」现状，也不得改动上述既有断言。
- [ ] 5.5 保存路径对称性：`config_admin.write_config` 的 `verify` 前置校验段与 merge 段 MUST 各自补三键（正整数 / 枚举校验；非 `None` 且非法 → `fail(...)` 拒绝；合法值按既有 `impl_code_review` 同款条件合并）。漏任一段即出现「界面可填、保存被静默丢弃」或「覆盖回读镜像」缺口（`gates.promote_mode` / `spec_review_mode` 曾因漏 merge 分支被静默丢弃，见 `config_admin.py:746-757` 的修复注释）。

## 6. 配置模板与文档

- [ ] 6.1 `.fenix/config.template.yaml` 的 `verify` 段新增三键（`impl_code_review_timeout_sec: 600` / `impl_code_review_concurrency: 2` / `impl_code_review_effort: low`），各附注释说明语义、缺省与合法值。
- [ ] 6.2 `docs/help/09-config.md`：文档化三键（语义 / 缺省 / 合法取值范围 / 与 `ocr` 参数的对应关系）；并更新文末「设置页可编辑键」速查表的**质量行**（`docs/help/09-config.md:394`，现仅列 `verify.impl_code_review`）以含三新键。
- [ ] 6.3 `docs/help/08-dashboard.md`：在质量页签小节（`docs/help/08-dashboard.md:57`）描述新增的三项设置，含「`--concurrency` / `--effort` 经提示词命令示例承载、实现者须照抄」这一软约束说明，避免用户误以为二者是硬性生效开关。

## 7. 测试

- [ ] 7.1 新增 `tests/test_impl_code_review_tuning.py`：覆盖三读取器的缺省回退 / 非法值回退 / 合法透传 / 项目级覆盖 / 三读取器互不牵连（对齐 spec「配置读取器」四个 Scenario）。
- [ ] 7.2 同文件：覆盖 `_write_run_ocr_config` 注入 `timeout_sec`（落盘 JSON 断言 `custom_providers["fenix-impl"]["timeout_sec"]`，含显式值与缺省值两例）。
- [ ] 7.3 同文件：覆盖 `_impl_code_review_section` 命令串含 `--concurrency` / `--effort`（含显式值与缺省值两例）、不含 `--max-tokens-budget`，以及开关关闭时零注入。**开关关闭零注入的断言口径**：`_impl_code_review_section` MUST 在开关关闭时**提前返回**（不调用 `get_impl_code_review_concurrency` / `_effort`），断言方式为在关闭用例中 patch 两读取器抛 `AssertionError`、或断言 `f(spec) == ""`（现有实现 `prompt_builder.py:548-556` 即先读开关再构造字符串，注入段 MUST 在其后拼接以保住该结构）。
- [ ] 7.3b 同文件：断言 3.2b 改写后的成本控制文案与新命令示例**不冲突**——段内不得再出现「自行选择 effort」类措辞（防注入值被实现者覆盖的回归）。
- [ ] 7.4 扩展 `tests/test_dashboard_quality_ocr.py`（或同域既有测试）：覆盖 config_admin 三键登记 / sources 标注 / 缺省回显 / 写读回环 / 非法值拒绝（正整数与枚举）/ `_SYNC_PAGE_KEYS["quality"]` 含三键。
- [ ] 7.4b **既有断言不变式**：`tests/test_dashboard_data.py:59,68` 与 `tests/test_system_settings_config.py:229,242` 对 `verify` 段的整字典相等断言、`tests/test_dashboard_data.py:108` 对 `sources["verify.impl_code_review"] == "user"` 的断言 MUST 继续通过（三键缺省值已计入整字典比对）。若实现选择了「缺省不回显三新键」的替代方案，须同步更新这些断言并在 tasks 留痕——默认方案为恒回显缺省。
- [ ] 7.5 运行定向测试与有界全量回归 `python3 bin/run_full_suite.py --timeout 3600`，按 `--baseline main` 归类存量/引入失败，零引入回归后提交。

## 8. 收尾

- [ ] 8.1 逐项勾选 tasks.md 全部任务，写 `.fenix-run-result.json`（`status: success` + `completed_tasks` 与勾选一一对应）。
- [ ] 8.2 执行收尾代码质量审查（`bin/ocr_review.py`，用本次生效的并发/力度参数），规整结果写入 `.fenix/verify-progress/add-impl-code-review-tuning/code-review.json` + 原始报告副本，并在结果文件顶层 `code_review` 段登记 `dispositions`。
  - **`status: "partial"` 的映射口径**：本轮审查若出现个别文件失败，ocr 原始报告顶层 `status` 为 `"partial"`（实测 `add-code-review-agent-and-quality-tab` 的报告即如此，`message: "Review partially complete: 2 finding(s); 9 of 22 selected item(s) failed."`），而提示词（`prompt_builder.py:586-592`）只固化 `complete`→`completed` / `failed`→`unavailable` 的映射。`partial` MUST 按 `completed` 登记（保留 `findings` 逐条处置对账；映射为 `unavailable` 会跳过处置对账、白丢已产出的 findings），并在 `reason`/备注中记明失败文件数。该口径同时 MUST 写入本 SPEC 的收尾审查产物。
