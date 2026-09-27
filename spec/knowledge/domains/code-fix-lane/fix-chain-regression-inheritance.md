# 修复链回归继承

<!-- knowledge: capability=fix-chain-regression-inheritance rev=1
     sources=spec/archive/2026-09-02-improve-verify-adjudication -->

fix 链各轮必须背负其来源场景：父 SPEC 的失败/未执行回归场景注入子 fix 并强制闭环，防验证覆盖逐轮缩水。

## 规则

- 框架在创建或重置 fix SPEC 时，读取父 SPEC 最新 report.json 中 status 为 `fail` 或从未出现于该报告的场景清单，写入 fix SPEC 目录下的回归场景清单文件（含父 SPEC 名、场景 id、失败摘要），并在 proposal.md/tasks.md 中声明这些场景为必测项。
- 多级 fix 继承并集：fix-P 自身验证失败又派生 fix-fix-P 时，继承的回归清单包含 P 与 fix-P 两轮的失败/未执行场景并集，而非仅最近一轮。
- 放行强制闭环：fix SPEC 推进到 `done`/`pushed` 前，除通用进度与质量门禁外，必须校验其继承的每个回归场景在本轮 report.json 中均已执行且通过；任一缺失或失败则阻止推进，并在 error 字段写明缺口场景 id。
- Administrator 可显式豁免某场景：豁免操作落盘留痕（标记「人工确认不需复测」及理由），被豁免场景视为闭环、不再构成放行阻塞，豁免记录可在告警与日志中追溯。

## 溯源

- 2026-09-02 2026-09-02-improve-verify-adjudication — 新建本页：父 SPEC 回归场景注入、多级并集继承、done/pushed 前回归闭环闸门与 administrator 显式豁免留痕。
