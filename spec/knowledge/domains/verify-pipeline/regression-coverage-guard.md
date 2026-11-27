# prepare↔regression 回归收编一致性预检

<!-- knowledge: capability=regression-coverage-guard rev=1
     sources=spec/archive/2026-11-27-evo-add-regression-coverage-guard -->

验证契约（`.fenix/verify.yaml`）的装配段↔回归声明段一致性预检：prepare 装配的被测包必须在 regression 声明面有测试落点，让「契约段位扩编做一半」在配置装载面即发声，而非等消费期事故考古。

## 规则

- **交叉比对挂契约装载路径**：契约解析/校验时对 prepare 段 install/build 步骤声明的包目录集合与 regression 段 cmd 文本引用集做交叉比对；prepare 装配了某包而 regression cmd 全文无该包引用时，发 `regression_coverage_gap` WARNING，不阻断契约加载、不触发 replan——配置面软告警与消费期回归硬门（回归通过才合回）分工。
- **包目录识别为形态启发式，保守跳过**：只识别 `--dir <pkg> install`（含尾随 flags）与 `--dir <pkg> run build` 两个装配变体，兼容 `--dir=<pkg>` 紧贴形态；其余命令词（test/exec/add 等）不是装配步骤不取，`.`/`..` 根目录不视为被测包（regression cmd 文本极易天然含 `.`，纳入会反向误判）。识别不出形态（如纯 pytest cmd 契约）即跳过比对——误报比漏报更伤，会稀释真缺口告警。
- **regression 段缺省保守跳过**：regression 段整体未配置（模板明文合法引导态：分面显示、不派发、零报错）或整段无效时跳过比对、不发声——本检查只治「regression 已配置但收编不全」，全量缺省归引导态治理面；畸形 cmd 形态同样保守跳过。
- **对称契约零输出**：prepare 装配的每个包目录都在 regression cmd 中被引用时无任何 WARNING，加载行为零变化。
- **缺口告警带定向情报**：WARNING 附缺口包清单与 regression 段行号指引（对契约原文做锚点扫描定位，复用装载路径既有单次 read_text，不引 yaml Mark），文案载明补法——新增被测插件进 prepare（install/build）时 MUST 同步在 regression 注册 install+test 条目（`--frozen-lockfile --prefer-offline` 形态，先例为同文件既有插件条目）。
- **模板双向指引**：verify_contract_template.yaml 的 regression 段【收编一致性】注记与 prepare 段 cwd 字段说明均载同步注册要求——收编指引在作者起草/扩编当下可见，不依赖事后检查。
- **不动项目运行时文件与 worktree 供给**：项目侧 `.fenix/verify.yaml` 为 gitignored 运行时文件，缺口补齐由人工/项目侧执行；fix worktree 的依赖供给覆盖不到插件目录属独立结构性课题，本预检不代改、不扩 sub_dirs。

## 代码锚点

- 交叉比对与包目录启发式：`core/verify_contract.py`（`_check_regression_coverage` / `_extract_prepare_package_dirs`，挂契约装载路径）
- 模板收编指引：`core/verify_contract_template.yaml`
- 守卫测试：`tests/test_regression_coverage_gap.py`

## 溯源

- 2026-11-16 evo-add-regression-coverage-guard（spec/archive/2026-11-27-evo-add-regression-coverage-guard/） — 新建本能力页：prepare↔regression 一致性预检（装载面 WARNING 不阻断、两变体形态启发式、缺口清单+行号指引）与模板双向收编指引；起因是 dsh-plugins 契约扩编只进 prepare 漏收编 regression 段，合入 main 的 63 条 fixed 插件面修复零回归验证
