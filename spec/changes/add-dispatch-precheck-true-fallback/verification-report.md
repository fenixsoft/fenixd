# 验证报告：add-dispatch-precheck-true-fallback

> ⚠️ 本报告由框架于 2026-11-08T13:13:02Z 自动合成（裁决 Agent 未写报告，已由框架合成），内容为结构化验证产物（report.json / .fenix-run-result.json）的忠实渲染。
> 报告时效标记（判定本报告是否属上一轮）：合成源轮次指纹：report.json@2026-11-08T13:13:02.608917+00:00+run-result@mtime1794143582654186358

## 结论：✅ 通过（verified）

**状态：verified — 9/9 场景通过，0 失败，0 错误（全部场景通过）**

全绿快道: 9/9 场景通过、0 失败 0 警告——无分类对象，跳过 judge 机械 verified

| 指标 | 数量 |
| --- | --- |
| 通过 | 9 |
| 失败 | 0 |
| 错误 | 0 |
| 产品 Bug | 0 |
| 本链增量 Token（输入） | 3.68M |
| 本链增量 Token（输出） | 0.05M |


## 场景结果

| 场景 | 描述 | 状态 | 失败断言 | 分类 |
| --- | --- | --- | --- | --- |
| bundle-vitest-modelconfig-boundary | dsh-bundle modelConfig 插件形态划界单测全绿：无 patch 回落形态（config.model 整体缺席）不抛 StartupError 且 headless-runner 依赖服务可用、部分 config.model（null/空串/缺要素）仍 fail-fast、显式链校验路径行为与重构前一致——spec harness-default-fallback「无分配时按 harness 自身配置启动（对称回落）」bundle 侧与「回落 WARN 观察钩子」bundle 留痕的单测验收（tasks 1.3）。环境依赖（npm registry 可达）；有 fallback: pnpm 本地 store 缓存（--prefer-offline 命中即零外网）。声明：design.md:51 候选「link」为 pnpm link: 协议文字、非 UI 交互元素，declared_display 登记。 | pass | 0/4 | - |
| adapter-fallback-regression-suite | fenixd 侧对称回落既有回归全绿（output_match 用例行按本机 -v 真实输出照抄）：dsh 无分配 spawn 无 --patch 无桥接、claude 无分配环境继承、部分链 DshSpawnConfigError、进程×adapter 一次性 WARN 去重与文案语义、provider_source=harness-default 归因、显式链不触发 WARN——覆盖 spec harness-default-fallback「对称回落」「回落 WARN 每进程仅一次」「显式链字节级不变」的 Python 侧（tasks 4.1 更新后仍须绿）。 | pass | 0/9 | - |
| precheck-unittest-suite | 派发前置自检专项单测文件（tasks 2.5 交付）存在且全绿：自检短路+归因标记断言、可达放行零噪音、启动告警进程内去重、[harness-cli-unavailable] 不计入 instant-fail-storm/repeated-failures、自愈幂等追加+restart_request 落位、binary 全目录缺失不盲写——覆盖 spec dispatch-precheck「派发前置 harness 可达性自检」「升级信号豁免」「PATH 缺陷自愈闭环」的单测验收通道。 | pass | 0/3 | - |
| path-hygiene-unittest-suite | systemd env PATH 卫生专项单测文件（tasks 3.4 交付）存在且全绿：最小 PATH 补齐+留痕断言、完整 PATH 逐字节不变、unit 模板含保底行、迁移摘要 PATH 卫生结论行（tasks 3.3 的单测验收通道）——覆盖 spec systemd-env-path-hygiene 三个 Requirement 的单测面。 | pass | 0/3 | - |
| precheck-attribution-marker-probe | 行为级探针（harness 不可达路径实跑）：DshAdapter.check_health 对不可达 binary 抛 HarnessHealthError 且错误文案带 [harness-cli-unavailable] 归因标记（tasks 2.1「接入同一归因避免双口径」）；静态锚点：runner.py 与 dsh_adapter.py 均含标记字面量（归因管道落位证据）。覆盖 spec dispatch-precheck「harness 不可达失败归因标记」。 | pass | 0/5 | - |
| capture-env-baseline-union-probe | 行为级探针（最小 PATH 子进程实捕 env 候选稿）：capture_env_candidate 捕获 systemd 最小 PATH 进程时把缺失基线目录（~/.local/bin 展开为绝对路径）追加至 PATH 值尾部且候选稿留痕「追加」；捕获完整基线 PATH 进程时产物不变（无追加注释、PATH 原样、键集照常返回）；PATH 值不含字面 ~（systemd 不展开）。覆盖 spec systemd-env-path-hygiene「env 候选稿 PATH 基线并集」两 Scenario。 | pass | 0/9 | - |
| unit-template-fallback-path-probe | 行为级探针：render_project_unit 渲染的 unit 含 Environment=PATH= 保底行（含 ~/.local/bin 展开绝对路径），生效行（非 # 注释行）无字面 ~（字面 ~ 目录项会使保底 PATH 静默失效；注释行 systemd 不解析、其中 ~ 无语义，豁免），EnvironmentFile=- 覆盖行保留（env 文件在场时照常覆盖保底行，systemd 加载顺序语义不变）。覆盖 spec systemd-env-path-hygiene「unit 模板内置保底 PATH」。 | pass | 0/5 | - |
| adjacent-regression-green | 被修改模块的相邻回归文件全绿（出题时本机实测：systemd_hosting+harness_dsh_adapter 109 passed、agent_runner 22 passed）：systemd_hosting（capture/render 改动面）、harness_dsh_adapter（adapter 改动面）、agent_runner（runner 前置自检插入面）——实现改写不得破坏既有行为面（proposal 回归红线）。 | pass | 0/2 | - |
| bundle-dist-fallback-probe | dist 构建后以 node 直探 assertModelExplicit 形态划界（D1 行为级验收，独立于用例名）：config.model 整体缺席（undefined）不抛错；null/非对象/缺 model/要素为空仍抛「模型未显式配置」（笔误防护）；三要素齐备原样恒等返回（显式链回归红线）。覆盖 spec harness-default-fallback「无分配时按 harness 自身配置启动」与「显式链形态不受回落语义改写（回归红线）」。 | pass | 0/10 | - |

## 本轮场景集变更

当前稳定场景集共 9 个（第 1 轮）。

- 首轮写入 9 个场景

