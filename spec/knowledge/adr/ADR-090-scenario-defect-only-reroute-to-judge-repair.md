# ADR-090：纯场景缺陷改道门，实现轮预算不修场景

date: 2026-09-15
status: accepted

## Context

judge 将场景缺陷连锁失败误归 test-defect 却申报 bug-found 时，框架 bug-found 分支全程不读 classification，实现轮整轮烧在修场景文件上（单次事故两个实现轮 $88+）。judge prompt 的路由约定无框架兜底。改道两类错误的代价不对称：漏掉真 bug 有恢复路径（改道后重验仍失败 → 二次裁决正常放行），误拦真 bug 无路径。

## Decision

- 改道门挂框架 bug-found 分支（持有 report/verdict 上下文的验证层），判定依据 report.json 的 classification 分布：failed 全部**显式** test-defect/flaky 且 product-bug=0 才改道；None/未知值一律不改道。保守取向与「推测级归因不得打回」同源哲学——宁可多一轮重验不可烧实现轮修场景。
- 改道动作 = 定向重派 judge 一次，复用既有 scenario-repaired 通道收口；不新增「场景修复 agent」（judge 已有同源知识 + 本轮执行证据，重派成本远低于实现轮）。改道重派与 scenario-repaired 重入共用修复预算，防两通道叠加无限重入；耗尽升级人工，spec 保持 testing。
- 静态缺陷扫描只产情报不拦截执行：检出即拦会让验证空转（重跑不修场景必然复发），且执行证据恰是 judge 修复的依据。扫描 fail-open，findings 落盘轮级临时文件 + judge prompt 情报段注入，不参与门禁判定。
- 扫描器数据驱动模式表（模式 = 表项：rule_id / 适用 kind / 匹配函数），初始只收确定性规则（字面端口 ≠ serving 端口、双汉字选择器）；新增模式 = 加表项不动扫描器主体，误报项可随时摘除。
- prompt 路由指引前移到分类定义处（不留在文末协议段），并显式声明「修复已裁决场景合法、冻结 diff 记账保护、不视为冻结违规」。

## Consequences

- 纯场景缺陷不再消耗实现轮预算；judge 误标真 bug 的代价上限 = 多一轮重验（有意接受）。
- 语义级「seed 夹具完整性」「选择器运行时存在性」不可静态判定，静态扫描永不承担该职责；修复主体恒为 judge，机械改写场景文件被排除（stdin 形态各异易碎）。
- 场景修复预算总量有界，judge 能力上限的失败可见（告警附失败清单与 judge 申报记录），不再静默烧实现轮。
