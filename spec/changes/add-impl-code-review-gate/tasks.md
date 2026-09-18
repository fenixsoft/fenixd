## Deliverables

```yaml
- path: core/config.py
  kind: modify
- path: core/dashboard/data/config_admin.py
  kind: modify
- path: .fenix/config.template.yaml
  kind: modify
- path: core/dashboard/static/src/services/dashboard.ts
  kind: modify
- path: core/dashboard/static/src/pages/settings/components/VerifyPanel.tsx
  kind: modify
- path: core/agent_runner/prompt_builder.py
  kind: modify
- path: core/agent_runner/runner.py
  kind: modify
- path: core/agent_runner/result_gate.py
  kind: modify
- path: bin/ocr_review.py
  kind: new
- path: tests/test_impl_code_review_gate.py
  kind: new
- path: tests/test_agent_prompt_files.py
  kind: modify
- path: tests/test_system_settings_config.py
  kind: modify
- path: tests/test_dashboard_data.py
  kind: modify
- path: core/dashboard/static/dist/index.html
  kind: reference
```

> 说明：`core/dashboard/static/dist/index.html`（及同目录其余 dist 资产）为前端
> 构建产物，`.gitignore:30` 命中，声明为 `reference`，不进交付物硬校验；验证
> 契约的 prepare 阶段会 `npm run build` 重建。
>
> 人工前置（不进任务门禁）：目标机器需能执行 `ocr` 命令
> （`npm install -g @alibaba-group/open-code-review`）。未安装时功能按降级
> 路径放行，故不阻塞实现与验证。

## 1. 配置键与读取器（impl-code-review-setting）

- [ ] 1.1 `core/config.py`：新增类方法 `get_impl_code_review_enabled(config: Dict[str, Any]) -> bool`——读 `config["verify"]["impl_code_review"]`，**仅当值为 `True`（严格 bool，`1`/`"yes"` 等非 bool 一律不算）时返回 True**，其余（缺失 / 非 bool / `verify` 节缺失或非字典）一律返回 `False`。docstring 须写明缺省 false 与 fail-open 语义（脏值不中断派发），并说明该键支持用户级默认 + 项目级覆盖（合并由既有 config 加载链完成，本读取器只看合并后的结果）
- [ ] 1.2 `.fenix/config.template.yaml`：`verify` 段增 `impl_code_review: false`，相邻加中文注释说明「实现阶段末尾的代码质量审查开关（调用 ocr）」

## 2. 配置读写链路（impl-code-review-setting）

- [ ] 2.1 `core/dashboard/data/config_admin.py`：写路径 merge——在既有 `verify.*` 合并分支（`if "verify" in patch ...`）内增 `impl_code_review` 分支：**仅接受严格 bool**（`isinstance(v, bool)`），合法即写入 `merged["verify"]["impl_code_review"]`，非法静默忽略（与同段 `static_scope` / `deps_mode` 的「非法值静默忽略」一致）
- [ ] 2.2 `core/dashboard/data/config_admin.py`：读路径回显——在 `verify_raw` 回显块与 `verify_eff` 有效值回显块**两处**均增 `impl_code_review`（严格 bool 才回显），保证「写了能读回来」且项目级/用户级两条读链一致
- [ ] 2.3 `core/dashboard/data/config_admin.py`：在 `_SOURCE_KEYS` 登记的 `verify.*` 键组内增 `"verify.impl_code_review"`，使前端「继承自用户级」来源标注对该键生效

## 3. 前端「验证」页签开关（impl-code-review-setting）

- [ ] 3.1 `core/dashboard/static/src/services/dashboard.ts`：`VerifyConfig` 接口增可选字段 `impl_code_review?: boolean`（附注释：实现阶段末尾代码质量审查开关，缺省 false）
- [ ] 3.2 `core/dashboard/static/src/pages/settings/components/VerifyPanel.tsx`：在既有两个 Form.Item 之后新增一个 `Form.Item`（`valuePropName="checked"`）承载 `Switch` 或 `Radio.Group`（二选一，与面板既有风格一致即可），标签含 `<span className="label-note">（verify.impl_code_review）</span>`，说明文案讲清「开启后实现者会在收尾阶段调用 ocr 审查本次改动并自行修正真实问题，需要环境已安装 ocr，未安装时自动跳过」
- [ ] 3.3 `VerifyPanel.tsx`：`useEffect` 回填处增 `impl_code_review: config.verify?.impl_code_review === true`（缺省 false，不得呈现为空或 undefined）；`handleSave` 的 `verify` patch 对象内增 `impl_code_review: values.impl_code_review === true`

## 4. run 级 ocr provider 注入（impl-code-review-gate）

- [ ] 4.1 `bin/ocr_review.py`（新建）：可执行包装器——读环境变量 `FENIX_OCR_HOME`（run 级 HOME）与 `FENIX_OCR_BIN`（底层 ocr 可执行路径，缺省 `"ocr"`）；`FENIX_OCR_HOME` 非空时把子进程 `HOME` 设为它，然后以 `os.execv(底层 ocr, [底层 ocr] + sys.argv[1:])` 替换进程，**透传全部 argv 与退出码**。模块 docstring 须说明：为何必须重定向 HOME（ocr 的 `~/.opencodereview/config.json` 会静默压制 `OCR_LLM_*` 环境变量，实测证据见 design D2）；`FENIX_OCR_HOME` 为空时直接透传执行（不设 HOME），使包装器在无注入环境下仍可用。脚本须带 `#!/usr/bin/env python3` shebang 且文件权限为可执行（`chmod +x`）
- [ ] 4.2 `core/agent_runner/runner.py`：新增私有方法 `_write_run_ocr_config(provider) -> Optional[Path]`——入参为已选定的 provider dict；返回 run 级 HOME 目录路径（失败返回 None）。实现：在既有 `_ensure_agent_config_dir(provider["name"])` 目录下建 `ocrcfg/` 子目录，写 `.opencodereview/config.json`，内容为 `{"provider": "<name>", "custom_providers": {"<name>": {"api_key": provider["apikey"], "url": <baseurl> 归一化为以 /v1 结尾>, "protocol": "anthropic", "model": model}}}`。**provider 名 MUST 用非常见预设名之外的名字**（如 `"fenix-impl"`），避免与 ocr 内置预设 provider 撞名导致解析走错分支；写入失败记 WARNING 并返回 None（不抛、不阻塞派发）。同时新增只读方法 `_ocr_home_for_provider(provider_name)` 供派发处取路径
- [ ] 4.3 `core/agent_runner/runner.py`：在 `_execute_agent_inner` 的 env 注入处（`if provider is not None:` 分支内、既有 `for k, v in (provider.get("env") or {}).items()` 之后）增：开关为 true 且 provider 非空时调用 `_write_run_ocr_config(provider)`，成功则 `env_overrides["FENIX_OCR_HOME"] = str(ocr_home)`；并注入 `env_overrides["FENIX_OCR_BIN"]`——值取模块级常量 `DEFAULT_OCR_BIN = "ocr"`（**不新增配置键**，保持配置面最小）。任一环节异常 MUST 被捕获降级为 WARNING（审查环境缺失不得影响实现 run 主体）。开关读取经 `ConfigLoader.get_impl_code_review_enabled(self.config)`

## 5. 收尾审查任务注入（impl-code-review-gate）

- [ ] 5.1 `core/agent_runner/prompt_builder.py`：新增方法 `_impl_code_review_section(self, spec_name: str) -> str`——开关关闭时返回空串（零注入，保证提示词逐字节不变）。开启时返回一段中文说明，MUST 覆盖：触发时机（全部 tasks.md 任务完成并提交之后、写 `.fenix-run-result.json` 之前）；审查范围（本次实现分支相对基线的 diff，用 `bin/ocr_review.py review --from <base> --to HEAD` merge-base 模式，实现者可自行选择更合适的等价形态）；工具为 `bin/ocr_review.py` 包装器（**MUST NOT 直接调 `ocr`**，因为 provider 配置由 run 级注入承载）；评估义务（逐条判断真实问题 vs 误报，**修正真实问题的裁量权归实现者**，误报可驳回但须给理由）；成本控制（建议传 `--max-tokens-budget` 或 `--effort` 限制单次审查开销）；报告落盘路径（`.fenix/verify-progress/<spec>/code-review.json`）与 `code_review` 段格式；环境不可用时的降级动作（写 `status: "unavailable"` + 非空 `reason` 后照常收工，不得因审查失败而判 run 失败）。spec 名经 `{spec_name}` 占位语义传入
- [ ] 5.2 `prompt_builder.py`：在 `implementer` 分支与 `fast-track` 分支**各**追加 `prompt += self._impl_code_review_section(spec_name)`——位置 MUST 在 `_noninteractive_contract_section()` 之后、`_project_extra_section()` 之前（即两分支各自的动态段之后、函数收尾的统一非交互契约段与项目级附加段之间；实现时按实际控制流就近放置，确保两车道都注入且不破坏「项目级附加段位于 prompt 末尾」的既有约定）

## 6. 审查报告产物硬门（impl-code-review-gate）

- [ ] 6.1 `core/agent_runner/result_gate.py`：新增私有函数 `_check_impl_code_review_artifact(runner, spec_name, wt_path, data) -> str | None`——开关关闭时立即返回 None（零校验）。开启时校验：报告 `<wt_path>/.fenix/verify-progress/<spec>/code-review.json` 存在且为合法 JSON 对象；`status` ∈ {`"completed"`, `"unavailable"`}；`status == "unavailable"` 时 `reason` MUST 为非空字符串（空/缺失 → 判失败，失败原因须点明「unavailable 必须附非空原因」）；`status == "completed"` 时 `findings` MUST 为列表、`data["code_review"]` MUST 存在且其逐条处置条数 MUST 等于 `findings` 条数、每条处置的 `disposition` ∈ {`"fixed"`, `"rejected"`, `"deferred"`} 且后两者 MUST 附非空 `reason`。所有失败原因 MUST 含报告路径与具体缺口（供实现者据此修），格式与既有硬门文案风格一致（「exit 0 但 …（implementer 产物硬门）: <path>」）
- [ ] 6.2 `result_gate.py`：在 `_check_impl_result_artifact` 内接入 6.1——置于 `status == "error"` 早退**之后**、任务完成度判据之前，仅对 `status ∈ {success, partial}` 调用；返回非 None 即作为该函数的失败原因返回。MUST NOT 改动既有各判据的顺序与语义（尤其 `unattainable` 解析与 task 类降级计数逻辑）

## 7. 测试（impl-code-review-gate / impl-code-review-setting）

- [ ] 7.1 `tests/test_impl_code_review_gate.py`（新建）：配置读取器用例——缺失/非 bool/`verify` 节缺失均返回 False；严格 `True` 返回 True；项目级 true + 用户级无 → True
- [ ] 7.2 同文件：`bin/ocr_review.py` 包装器用例——以临时可执行 stub 冒充底层 ocr，断言 `FENIX_OCR_HOME` 生效时子进程 `HOME` 被改写、argv 逐项透传、退出码透传；`FENIX_OCR_HOME` 为空时 `HOME` 不被改写
- [ ] 7.3 同文件：硬门用例——开关关闭时报告缺失不判失败；开关开启时报告缺失 / JSON 非法 / `status` 越界 / `findings` 与处置条数不匹配 / `rejected` 缺 reason / `unavailable` 缺 reason 六种形态分别判失败且原因含缺口描述；`status: "unavailable"` 带非空 reason 放行；`completed` 且逐条处置齐全放行
- [ ] 7.4 同文件：run 级 ocr 配置写入用例——`_write_run_ocr_config` 落盘的 JSON 含该 provider 的 url/apikey/model，provider 名不与 ocr 内置预设同名，且写入不触碰 `$HOME/.opencodereview/`（用 monkeypatch 主树 HOME 断言用户全局文件未被读写）
- [ ] 7.5 `tests/test_agent_prompt_files.py`（扩展）：开关关闭时 implementer 与 fast-track 提示词均不含 `bin/ocr_review.py`；开关开启时两者均含收尾审查段（含报告路径与 `code-review.json` 字样）
- [ ] 7.6 `tests/test_system_settings_config.py`（扩展）与 `tests/test_dashboard_data.py`（扩展）：`verify.impl_code_review` 写入后读回为 True；写非法值（非 bool）被静默忽略保留原值；缺省时读回为 False 且来源标注可查
- [ ] 7.7 全量回归：`python3 bin/run_full_suite.py --timeout 3600` 通过（基线既有失败不在本次范围，须在结果文件中列明）
