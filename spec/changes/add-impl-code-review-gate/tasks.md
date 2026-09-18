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
- [ ] 1.2 `.fenix/config.template.yaml`：`verify` 段增 `impl_code_review: false`，相邻加中文注释说明「实现阶段末尾的代码质量审查开关（调用 ocr）」（该文件已被 git 显式跟踪，改动静默生效于模板交付）

## 2. 配置读写链路（impl-code-review-setting）

- [ ] 2.1 `core/dashboard/data/config_admin.py`：写路径**前置校验**——在既有 `verify.*` 前置校验块（`if isinstance(config_patch.get("verify"), dict):`，即 `static_scope` / `deps_mode` 枚举校验所在块）内增 `impl_code_review` 分支：非 `None` 且**非严格 bool**（`not isinstance(v, bool)`）→ 返回 `fail("verify.impl_code_review must be a boolean: ...")`，**不落盘**。语义与同段 `static_scope` / `deps_mode` 的「非法枚举值直接拒绝」**完全一致**（既有实测：`write_config({"verify": {"deps_mode": "symlink"}})` 返回 `ok=False`，见 `tests/test_dashboard_data.py:72`）；merge 层只应用合法值（见 2.2）
- [ ] 2.2 `core/dashboard/data/config_admin.py`：写路径 merge + 读路径回显——(a) 在合并层（`if "verify" in patch and isinstance(patch["verify"], dict):` 块内）增：`isinstance(patch["verify"].get("impl_code_review"), bool)` 时写 `merged["verify"]["impl_code_review"]`（校验层已拒绝非法值，此处只做合法值应用）；(b) 读路径在 `verify_raw` 回显块与 `verify_eff` 有效值回显块**两处**均增：**仅当值为严格 bool 时才回显**（`isinstance(v, bool)`），**缺省（未配置）MUST NOT 填充该键**——与同段 `planner_max_concurrent` 的「缺省不回显」同款（`tests/test_dashboard_data.py:84` 断言缺省 `NotIn`），从而不破坏既有严格相等断言（`tests/test_dashboard_data.py:59`、`tests/test_system_settings_config.py:229` 断言 `verify` 段恰为 `{"static_scope","deps_mode"}` 两键）。前端以 `=== true` 归一显示为「关闭」（见 3.3），满足「缺省呈现为关闭、不得显示未知/空值」
- [ ] 2.3 `core/dashboard/data/config_admin.py`：在 `_SOURCE_KEYS` 登记的 `verify.*` 键组内（`"verify.deps_mode"` 之后）增 `"verify.impl_code_review"`；并在 `_managed_key_sources` 的 `verify_src` 判定块内增 `if isinstance(verify_src.get("impl_code_review"), bool): sources["verify.impl_code_review"] = "project"`——两处齐备，前端「继承自用户级」来源标注对该键才生效（`_SOURCE_KEYS` 只决定 sources 字典的键集合，取值仍由 `_managed_key_sources` 写）
- [ ] 2.4 `core/dashboard/data/config_admin.py`：`_SYNC_PAGE_KEYS` 的 `"verify"` 页键组增 `impl_code_review`（`"verify": {"verify": ["static_scope", "deps_mode", "impl_code_review"]}`）——「同步用户级设置」按钮按页白名单取键，未登记则该键无法从用户级一键同步到项目级（与同节 `planner_max_concurrent` 在 `"parallel"` 页登记同款先例）；既有同步测试（`tests/test_dashboard_data.py:2139`）只写 `static_scope`/`deps_mode` 两个键，`picked` 取值不受影响，零回归

## 3. 前端「验证」页签开关（impl-code-review-setting）

- [ ] 3.1 `core/dashboard/static/src/services/dashboard.ts`：`VerifyConfig` 接口增可选字段 `impl_code_review?: boolean`（附注释：实现阶段末尾代码质量审查开关，缺省 false）
- [ ] 3.2 `core/dashboard/static/src/pages/settings/components/VerifyPanel.tsx`：在既有两个 Form.Item 之后新增一个 `Form.Item`（`valuePropName="checked"`）承载 `Switch` 或 `Radio.Group`（二选一，与面板既有风格一致即可），标签含 `<span className="label-note">（verify.impl_code_review）</span>`，说明文案讲清「开启后实现者会在收尾阶段调用 ocr 审查本次改动并自行修正真实问题，需要环境已安装 ocr，未安装时自动跳过」
- [ ] 3.3 `VerifyPanel.tsx`：`useEffect` 回填处增 `impl_code_review: config.verify?.impl_code_review === true`（缺省 false，不得呈现为空或 undefined）；`handleSave` 的 `verify` patch 对象内增 `impl_code_review: values.impl_code_review === true`

## 4. run 级 ocr provider 注入（impl-code-review-gate）

- [ ] 4.1 `bin/ocr_review.py`（新建）：可执行包装器——读环境变量 `FENIX_OCR_HOME`（run 级 HOME）与 `FENIX_OCR_BIN`（底层 ocr 可执行路径，缺省 `"ocr"`）；`FENIX_OCR_HOME` 非空时把子进程 `HOME` 设为它，然后以 **`os.execvp(底层 ocr, [底层 ocr] + sys.argv[1:])`** 替换进程，**透传全部 argv 与退出码**。**MUST 用 `execvp`（带 PATH 搜索）而非 `execv`**：`os.execv` 不搜索 `PATH`，当 `FENIX_OCR_BIN` 取缺省裸名 `"ocr"` 时必然抛 `FileNotFoundError`（本机实测：`os.execv("ocr", ...)` → `[Errno 2] No such file or directory`，而 `shutil.which("ocr")` → `/usr/bin/ocr`）——那会把「ocr 已装」误判成「环境不可用」并静默降级为放行，直接废掉本能力。模块 docstring 须说明：为何必须重定向 HOME（ocr 的 `~/.opencodereview/config.json` 会静默压制 `OCR_LLM_*` 环境变量，实测证据见 design D2）；`FENIX_OCR_HOME` 为空时直接透传执行（不设 HOME），使包装器在无注入环境下仍可用；包装器**不创建** HOME 目录也不落任何日志（HOME 不存在时底层 `ocr` 自身报错退出，由实现者按 `unavailable` 降级）。脚本须带 `#!/usr/bin/env python3` shebang 且文件权限为可执行（`chmod +x`）
- [ ] 4.2 `core/agent_runner/runner.py`：新增私有方法 `_write_run_ocr_config(provider, model) -> Optional[Path]`——入参为已选定的 provider dict **与本轮实际生效的模型名 `model`**（即 `_execute_agent_inner` 内 `model_override`，与 fenix 记账同源的那个模型；MUST NOT 只取 `provider["model"]`——provider 条目自带模型可能与本轮元素级模型不同），返回 run 级 HOME 目录路径（失败返回 None）。实现：在既有 `_ensure_agent_config_dir(provider["name"])` 目录下建 `ocrcfg/` 子目录，写 `.opencodereview/config.json`，内容为 `{"provider": "fenix-impl", "custom_providers": {"fenix-impl": {"api_key": provider["apikey"], "url": provider["baseurl"], "protocol": "anthropic", "model": model}}}`。两点实测约束：
  - **provider 名用固定的非常见名 `"fenix-impl"`**，MUST NOT 直接用 provider 名——ocr 内置预设名（`anthropic` / `deepseek` / `dashscope` / …，见 `ocr llm providers`）与自定义名撞名时解析会走错分支；固定名同时让第 7.4 条测试可精确断言。
  - **`url` 原样透传 `provider["baseurl"]`，MUST NOT 追加或改写版本后缀**：实测 `ocr` 自己会在 URL 后拼 `/v1/messages`（本机 probe：配 `http://127.0.0.1:18099` → 请求 `/v1/messages`；配 `http://127.0.0.1:18099/v1` → 请求 `/v1/messages`；配 `.../anthropic` → 请求 `/anthropic/v1/messages`）。本项目真实 provider 里 `aliyun`（`.../apps/anthropic`）、`bigmodel.cn`、`deepseek`（`.../anthropic`）的 baseurl 本就不以 `/v1` 结尾，若按「归一化为以 /v1 结尾」自行追加会得到 `.../anthropic/v1/v1/messages` 这类坏 URL。
  写入失败记 WARNING 并返回 None（不抛、不阻塞派发）。同时新增只读方法 `_ocr_home_for_provider(provider_name)` 供派发处取路径。**返回值 MUST 是那个直接包含 `.opencodereview/` 的 `ocrcfg/` 目录本身**（即 `<项目根>/.fenix/agent-config/<provider>/ocrcfg`），MUST NOT 返回其父目录——ocr 只认 `$HOME/.opencodereview/config.json`，HOME 若指到父目录则配置文件永远读不到，审查会静默退化为按 `ANTHROPIC_*` 环境变量选端点（非注入设计的确定性路径）。第 7.4 条测试须钉住该不变量。**写入 MUST 用 tempfile + `os.replace` 原子替换**（`_ensure_agent_config_dir` 同款手法）：同名 provider 的并发 run 会写同一路径，非原子写会让另一 run 的 `ocr` 读到半截 JSON
- [ ] 4.3 `core/agent_runner/runner.py`：在 `_execute_agent_inner` 的 env 注入处（`if provider is not None:` 分支内、既有 `for k, v in (provider.get("env") or {}).items()` 之后）增：开关为 true 且 provider 非空时调用 `_write_run_ocr_config(provider, model)`，成功则 `env_overrides["FENIX_OCR_HOME"] = str(ocr_home)`；并注入 `env_overrides["FENIX_OCR_BIN"]`——值取模块级常量 `DEFAULT_OCR_BIN = "ocr"`（**不新增配置键**，保持配置面最小；包装器以 `execvp` 解析 PATH 故裸名可用）。**此处 MUST 传分支内已生效的模型变量**：成功路径下该分支刚把 `model_override = model` 赋值（`runner.py:1878`），故直接传 `model_override` 即与 fenix 记账同源；后续若 `_run_claude` 因 provider 链切换改写生效模型，审查配置的 model 会与最终记账模型不一致——属已知可接受偏差（审查配置与记账同源是目标，非强制逐次一致）。任一环节异常 MUST 被捕获降级为 WARNING（审查环境缺失不得影响实现 run 主体）。开关读取经 `ConfigLoader.get_impl_code_review_enabled(self.config)`。**同处一并注入 `env_overrides["OCR_NO_UPDATE"] = "1"`**：`ocr` 的 node 启动器（`bin/ocr.js`）在 `HOME` 重定向到 run 级目录后会按 18 分钟冷却写 `last-update-check` 并 `detached` 拉起 `scripts/update.js` 去联网查新版本——实现者反复调用会在每个 run 的 HOME 下留下游离更新请求（多余网络流量 + 非确定性行为）；该环境变量被启动器原生支持，是零成本的关闭开关

## 5. 收尾审查任务注入（impl-code-review-gate）

- [ ] 5.1 `core/agent_runner/prompt_builder.py`：新增方法 `_impl_code_review_section(self, spec_name: str) -> str`——开关关闭时返回空串（零注入，保证提示词逐字节不变）。开启时返回一段中文说明，MUST 覆盖：触发时机（全部 tasks.md 任务完成并提交之后、写 `.fenix-run-result.json` 之前）；审查范围（本次实现分支相对基线的 diff，用 `bin/ocr_review.py review --from <base> --to HEAD` merge-base 模式，实现者可自行选择更合适的等价形态）；工具为 `bin/ocr_review.py` 包装器（**MUST NOT 直接调 `ocr`**，因为 provider 配置由 run 级注入承载）；评估义务（逐条判断真实问题 vs 误报，**修正真实问题的裁量权归实现者**，误报可驳回但须给理由）；成本控制（建议传 `--max-tokens-budget` 或 `--effort` 限制单次审查开销）；报告落盘路径（`.fenix/verify-progress/<spec>/code-review.json`）与 `code_review` 段格式；环境不可用时的降级动作（写 `status: "unavailable"` + 非空 `reason` 后照常收工，不得因审查失败而判 run 失败）。spec 名经 `{spec_name}` 占位语义传入。**注意**：`code-review.json` 是**框架侧规整契约**（`status` / `llm` / `findings` / 逐条 `disposition`），与 `ocr` 原始 JSON 报告**不同构**——实测 `ocr review --format json --output <file>` 的顶层键为 `status`（值 `"complete"` / `"failed"`）/ `llm` / `comments`（发现数组，逐条含 `path` / `start_line` / `category` / `severity` / `content`）/ `summary` / `manifest`。故注入段 MUST 告知实现者「把 `ocr` 原始报告的发现数组规整为 `findings`，并对 `status` 做值映射（`"complete"` → `"completed"`；底层非零退出/`"failed"` → `"unavailable"` + 非空 `reason`）」，MUST 保持原始报告副本（如 `<报告同目录>/code-review-raw.json`）以便审计；具体键名以实现者现场跑出的报告为准，不得凭猜测硬编码
- [ ] 5.2 `prompt_builder.py`：在 `_build_prompt` **统一收尾处**注入——即 `prompt += self._noninteractive_contract_section()` 与 `prompt += self._project_extra_section(...)` 两行之间，加 `if agent_type in ("implementer", "fast-track"): prompt += self._impl_code_review_section(spec_name)`。**MUST NOT 在 implementer / fast-track 两个分支各自追加**：`_noninteractive_contract_section()` 是在分支之外（两个分支的 `elif` 链收尾之后）无条件调用一次的（`prompt_builder.py:394`），在分支内追加会把审查段排到非交互契约段**之前**，既违反 spec「位于非交互契约段之后」的段序要求，又与「新增 agent 类型进白名单即生效、统一收尾注入」的既有约定分叉。统一收尾处注入天然满足「非交互契约段之后、项目级附加段之前」，两车道经 agent_type 白名单同时覆盖，开关关闭时 `_impl_code_review_section` 返回空串（`""`）——`prompt += ""` 逐字节不变

## 6. 审查报告产物硬门（impl-code-review-gate）

- [ ] 6.1 `core/agent_runner/result_gate.py`：新增私有函数 `_check_impl_code_review_artifact(runner, spec_name, wt_path, data) -> str | None`——开关关闭时立即返回 None（零校验）。开启时校验：报告 `<wt_path>/.fenix/verify-progress/<spec>/code-review.json` 存在且为合法 JSON 对象；`status` ∈ {`"completed"`, `"unavailable"`}；`status == "unavailable"` 时 `reason` MUST 为非空字符串（空/缺失 → 判失败，失败原因须点明「unavailable 必须附非空原因」）；`status == "completed"` 时 `findings` MUST 为列表、`data["code_review"]` MUST 存在且其逐条处置条数 MUST 等于 `findings` 条数、每条处置的 `disposition` ∈ {`"fixed"`, `"rejected"`, `"deferred"`} 且后两者 MUST 附非空 `reason`。所有失败原因 MUST 含报告路径与具体缺口（供实现者据此修），格式与既有硬门文案风格一致（「exit 0 但 …（implementer 产物硬门）: <path>」）
- [ ] 6.2 `result_gate.py`：在 `_check_impl_result_artifact` 内接入 6.1——置于 `status == "error"` 早退**之后**、任务完成度判据之前，**仅对「实现者自报本轮成功」的收口调用**：即 `status == "success"`，或 `status == "partial"` 但 `parse_unattainable(data)` 的合法项已覆盖全部未勾任务（等价于本轮全部任务实际做完、只是申报形态差异）。`status == "partial"` 且仍存在未勾任务、未被 unattainable 覆盖时 MUST NOT 调用（末轮诚实申报不因缺审查报告被拦，见 spec「末轮零误拦边界」）。返回非 None 即作为该函数的失败原因返回。MUST NOT 改动既有各判据的顺序与语义（尤其 `unattainable` 解析与 task 类降级计数逻辑）

## 7. 测试（impl-code-review-gate / impl-code-review-setting）

- [ ] 7.1 `tests/test_impl_code_review_gate.py`（新建）：配置读取器用例——缺失/非 bool/`verify` 节缺失均返回 False；严格 `True` 返回 True；项目级 true + 用户级无 → True
- [ ] 7.2 同文件：`bin/ocr_review.py` 包装器用例——以临时可执行 stub 冒充底层 ocr，断言 `FENIX_OCR_HOME` 生效时子进程 `HOME` 被改写、argv 逐项透传、退出码透传；`FENIX_OCR_HOME` 为空时 `HOME` 不被改写；**另断言 `FENIX_OCR_BIN` 未设（走缺省裸名 `"ocr"`）时能解析到 PATH 上的同名可执行**（在 PATH 前置的临时目录放一个 stub `ocr`，断言包装器真的 exec 到它而非抛 `FileNotFoundError`——`execv`/`execvp` 之差正是本条要钉住的回归）
- [ ] 7.3 同文件：硬门用例——开关关闭时报告缺失不判失败；开关开启时报告缺失 / JSON 非法 / `status` 越界 / `findings` 与处置条数不匹配 / `rejected` 缺 reason / `unavailable` 缺 reason 六种形态分别判失败且原因含缺口描述；`status: "unavailable"` 带非空 reason 放行；`completed` 且逐条处置齐全放行；**`status: "partial"` 且仍有未勾任务（未申报 unattainable）时缺失报告 MUST 放行**（末轮零误拦边界）
- [ ] 7.4 同文件：run 级 ocr 配置写入用例——`_write_run_ocr_config` 落盘的 JSON 含该 provider 的 url/apikey 与**传入的 model 实参**（断言 model 取自入参而非 `provider["model"]`），`provider` 与 `custom_providers` 的键名恰为固定名 `"fenix-impl"`（与 ocr 内置预设名不撞）；**返回路径 P MUST 满足 `(P / ".opencodereview" / "config.json").is_file()`**（HOME 必须直接含配置，见 4.2 不变量）；且写入不触碰 `$HOME/.opencodereview/`（用 monkeypatch 主树 HOME 断言用户全局文件未被读写）
- [ ] 7.5 `tests/test_agent_prompt_files.py`（扩展）：开关关闭时 implementer 与 fast-track 提示词均不含 `bin/ocr_review.py`；开关开启时两者均含收尾审查段（含报告路径与 `code-review.json` 字样）
- [ ] 7.6 `tests/test_system_settings_config.py`（扩展）与 `tests/test_dashboard_data.py`（扩展）：`verify.impl_code_review` 写入后读回为 True；写非法值（非 bool）被拒绝且不落盘（与 `deps_mode` 非法值同款，见 `tests/test_dashboard_data.py:72`）；**缺省时读回 MUST NOT 含该键**（防破坏既有严格相等断言 `tests/test_dashboard_data.py:59` / `tests/test_system_settings_config.py:229`），且 `sources["verify.impl_code_review"]` 可查（显式写入后为 `"project"`）
- [ ] 7.7 全量回归：`python3 bin/run_full_suite.py --timeout 3600` 通过（基线既有失败不在本次范围，须在结果文件中列明）
