# 实现期收尾代码审查（总开关与报告契约）

<!-- knowledge: capability=impl-code-review-gate rev=2
     sources=spec/archive/2026-09-23-add-impl-code-review-gate,spec/archive/2026-09-26-add-impl-ocr-parallel-lane -->

`verify.impl_code_review` 开启时，实现收尾存在一次代码质量审查（ocr 经仓库包装器 `bin/ocr_review.py` 执行，该包装器承载 run 级 provider 配置）。审查由框架侧 ocr 车道在 merge-back 后与测试验证并行执行（见 [impl-ocr-parallel-lane](impl-ocr-parallel-lane.md)），实现者与 fast-track run 的收工义务不含内联审查。

## 规则

- 开关语义与设置页见 [impl-code-review-setting](impl-code-review-setting.md)；调优参数见 [impl-code-review-tuning](impl-code-review-tuning.md)；结果判读与打回见 [impl-ocr-join-gate](impl-ocr-join-gate.md)。
- run 级 provider 注入：审查复用分配给本次实现 run 的那一个 provider（provider 名 / baseurl / apikey / model 与实现 run 一致），成本与 fenix 的 provider 记账同源。
  - 注入经 run 级隔离实现：框架为本 run 写一份专属 HOME 目录下的 `.opencodereview/config.json`，把该 HOME 经环境变量传给包装器 `bin/ocr_review.py`（包装器把 HOME 指向该目录后 exec `ocr`）。
  - 不读写用户全局 `~/.opencodereview/`，不覆盖用户既有 ocr 配置；多个 run 并发时各 run 的 ocr 配置相互隔离、不串扰。
  - 包装器透传 `ocr` 的退出码，供据以区分「审查失败」与「审查通过」。
- 报告契约：审查结果落盘 `.fenix/verify-progress/<spec>/code-review.json`，至少含：
  - `status`：`completed`（审查成功执行）| `unavailable`（环境不可用）；
  - `llm`：本次审查实际使用的 provider 名与 model；
  - `findings`：规整后的发现清单（逐条含文件路径、严重度、描述）。
- 报告是框架的规整契约，不假定审查工具原生报告同构（原生顶层为 `status`/`llm`/`comments`/`summary`/`manifest`）：原生发现数组规整进 `findings`；原生 `"complete"` 映射 `"completed"`，底层非零退出或 `"failed"` 映射 `"unavailable"` + 非空 `reason`；保留原生报告副本（同目录 `code-review-raw.json`）供审计。
- 报告经既有 worktree → 主树的产物回拷机制归档，spec 归档后仍可追溯。
- 环境不可用降级：`ocr` 未安装 / provider 不可达 / 当前目录非 git 仓库 / 审查过程异常终止时，记录 `status: "unavailable"` 与非空 `reason`，按正常流程收工；不判失败、不重派、不消耗重试预算。
- 空 `reason` 的 `unavailable` 判登记非法（防「一律写 unavailable 绕过审查」）。
- findings 的「真实问题 vs 误报」驳回裁量归实现者（修复轮提示词注入 findings 清单与 disposition 处置契约：`fixed`/`rejected`/`deferred`，`rejected`/`deferred` 须附非空 `reason`），不要求机械修正全部发现；join 门只做机械分类。
- 实现 run 的产物硬门不含审查报告校验项；报告的消费统一在 testing 出口 join 门。

## 溯源

- 2026-09-23 add-impl-code-review-gate（spec/archive/2026-09-23-add-impl-code-review-gate） — 新建实现收尾代码审查：内联审查段注入、run 级 ocr provider 注入（专属 HOME 隔离）、报告落盘契约与原生报告规整、同 run 产物硬门、环境不可用降级。
- 2026-09-26 add-impl-ocr-parallel-lane（spec/archive/2026-09-26-add-impl-ocr-parallel-lane） — 内联收尾审查义务与同 run 产物硬门废除（`code_review` 段/dispositions 不再是硬门校验项），审查改由框架侧 ocr 车道并行执行、报告由框架写入、消费移至 testing 出口 join 门；run 级 provider 注入与降级语义由车道沿用。
