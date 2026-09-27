# ADR-092：归因分级由框架机械计算，截图健康算法标签

date: 2026-09-15
status: accepted

## Context

judge 无截图时的错误归因可被硬编码常量、指纹缓存、白屏基线三层固化，implementer 两轮修无可修、inconclusive 循环多轮烧钱且 admin 全程失明。实证结论：judge 自律不可依赖（后处理增强可被绕过）；白屏检测不得依赖模型多模态能力——模型读标签不读图。

## Decision

- 截图健康判定算法化：独立纯函数模块（像素 std + 主色占比 + 低对比度指标），截图落盘时打标签并入场景 evidence；标签阈值集中为模块常量便于调参；异常 warning 跳过不阻断截图主流程。
- 归因分级不由 judge 自报：judge 只输出归因文本 + 引用的证据引用列表，框架校验器在报告落盘前按「场景 evidence 构成 + 归因引用」机械算级（evidence-backed / speculative / pending-visual）并执行门禁——全部归因为 speculative → 抑制 bug-found 打回，转重验一次或待人工复核；evidence 含 blank_screenshot 而归因未引用或归因到数据层 → 判 env 方向并改写为 evidence-backed(env)。分级结果持久化进 report.json。
- 批量硬编码归因防御：落盘前对全部场景归因文本归一化查重，≥3 场景逐字相同 → 拒绝落盘记 error，要求逐场景归因后重合成。
- 基线防污染：视觉基线固化前先过截图标签，命中 blank / low-contrast → 拒绝固化并记 baseline_rejected，本轮视觉断言按环境存疑；后续干净截图正常建立。
- 缓存归因复用打标（cached_from_previous_round + 来源轮次），纯缓存归因视同 speculative 口径参与分级合并。
- inconclusive 循环达阈值（连续 blocked-env 轮数，缺省 4）必唤起 Administrator（复用 STORED_SIGNAL 通道）；计数不清零则暂停自动重验语义闭环，人工处置是唯一出路。

## Consequences

- 假归因无法跨轮固化、无法批量套用、无法污染基线。
- 归因分级过严的代价 = 多一次重验：evidence-backed 的引用门槛定义为最低成本动作（引用失败断言文本，judge 本就输出该文本）；门禁只抑制「纯推测打回」，不抑制有断言文本支撑的打回。
- 批量查重门槛 ≥3 且要求逐字相同，误伤时重合成即可，不烧预算；基线拒绝固化导致的长 warning 在干净截图后自愈。
