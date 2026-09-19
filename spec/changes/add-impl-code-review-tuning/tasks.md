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
- [ ] 1.4 三读取器各自独立（一者非法不影响另两者）；在既有 `get_impl_code_review_enabled` 同区域添加，docstring 说明回退语义。

## 2. run 级 ocr 配置注入（core/agent_runner/runner.py）

- [ ] 2.1 `_write_run_ocr_config`：在 `custom_providers["fenix-impl"]` 条目中新增 `"timeout_sec"`，取值 `ConfigLoader.get_impl_code_review_timeout_sec(self.config)`；与既有字段同批原子写入（沿用现有 tempfile + `os.replace`，不新增独立写路径）。
- [ ] 2.2 更新 `_write_run_ocr_config` docstring，说明 `timeout_sec` 的来源、语义（ocr LLM 单请求超时，秒）与缺省。

## 3. 提示词命令承载（core/agent_runner/prompt_builder.py）

- [ ] 3.1 `_impl_code_review_section`：命令示例注入 `--concurrency <n>` 与 `--effort <v>`，取值来自 `get_impl_code_review_concurrency` / `get_impl_code_review_effort`；保持 `--format json --output` 等既有串不变。
- [ ] 3.2 同段更新「成本控制」条：明确并发与力度的取值来自配置（用户可调），并保持 MUST NOT 传 `--max-tokens-budget` / `--max-tokens` 的既有约束文案。
- [ ] 3.3 更新 `_impl_code_review_section` docstring，覆盖新增的并发/力度注入。

## 4. Dashboard 后端（core/dashboard/data/config_admin.py）

- [ ] 4.1 受管键清单新增 `"verify.impl_code_review_timeout_sec"` / `"verify.impl_code_review_concurrency"` / `"verify.impl_code_review_effort"`（与既有 `verify.impl_code_review` 相邻，附注释）。
- [ ] 4.2 sources 标注：三键在 `verify` 节显式定义时标注 `"project"`（严格类型判定，缺省/非法不标）。
- [ ] 4.3 有效配置回显：三键按缺省填充后回显（缺省 `600`/`2`/`"low"`），与既有 `impl_code_review` 回显同处。
- [ ] 4.4 保存合并链路：三键支持合并写回（缺失不填充、非法值按既有校验策略处理），MUST NOT 影响其它 `verify.*` 键。

## 5. Dashboard 前端（质量页签）

- [ ] 5.1 `core/dashboard/static/src/services/dashboard.ts`：`ConfigData` 的 `verify` 段补 `impl_code_review_timeout_sec?: number` / `impl_code_review_concurrency?: number` / `impl_code_review_effort?: 'low' | 'medium' | 'high'`，附注释。
- [ ] 5.2 `QualityPanel.tsx`：在既有「收尾代码质量审查」开关下方新增三项编辑控件——超时（数字输入，单位"秒"，正整数校验）、并发（数字输入，正整数校验）、力度（下拉 `low`/`medium`/`high`）；回填缺省 `600`/`2`/`low`；`handleSave` 序列化三键。
- [ ] 5.3 三控件加 `data-testid`（`impl-code-review-timeout` / `impl-code-review-concurrency` / `impl-code-review-effort`）供测试与验证定位；保存行为遵循既有作用域（项目级/用户级）与既有保存链路。

## 6. 配置模板与文档

- [ ] 6.1 `.fenix/config.template.yaml` 的 `verify` 段新增三键（`impl_code_review_timeout_sec: 600` / `impl_code_review_concurrency: 2` / `impl_code_review_effort: low`），各附注释说明语义、缺省与合法值。
- [ ] 6.2 `docs/help/09-config.md`：文档化三键（语义 / 缺省 / 合法取值范围 / 与 `ocr` 参数的对应关系）。
- [ ] 6.3 `docs/help/08-dashboard.md`：在质量页签小节描述新增的三项设置。

## 7. 测试

- [ ] 7.1 新增 `tests/test_impl_code_review_tuning.py`：覆盖三读取器的缺省回退 / 非法值回退 / 合法透传 / 项目级覆盖 / 三读取器互不牵连（对齐 spec「配置读取器」四个 Scenario）。
- [ ] 7.2 同文件：覆盖 `_write_run_ocr_config` 注入 `timeout_sec`（落盘 JSON 断言 `custom_providers["fenix-impl"]["timeout_sec"]`，含显式值与缺省值两例）。
- [ ] 7.3 同文件：覆盖 `_impl_code_review_section` 命令串含 `--concurrency` / `--effort`（含显式值与缺省值两例）、不含 `--max-tokens-budget`，以及开关关闭时零注入。
- [ ] 7.4 扩展 `tests/test_dashboard_quality_ocr.py`（或同域既有测试）：覆盖 config_admin 三键登记 / sources 标注 / 缺省回显。
- [ ] 7.5 运行定向测试与有界全量回归 `python3 bin/run_full_suite.py --timeout 3600`，按 `--baseline main` 归类存量/引入失败，零引入回归后提交。

## 8. 收尾

- [ ] 8.1 逐项勾选 tasks.md 全部任务，写 `.fenix-run-result.json`（`status: success` + `completed_tasks` 与勾选一一对应）。
- [ ] 8.2 执行收尾代码质量审查（`bin/ocr_review.py`，用本次生效的并发/力度参数），规整结果写入 `.fenix/verify-progress/add-impl-code-review-tuning/code-review.json` + 原始报告副本，并在结果文件顶层 `code_review` 段登记 `dispositions`。
