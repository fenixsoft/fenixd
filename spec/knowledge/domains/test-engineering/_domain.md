# 测试工程
> 最后更新：2026-11-10 11:20 UTC+8

测试工程：测试套件自身的结构、隔离、守卫与编写设计纪律，以及全量回归的声明、执行与展示。Docker 集成测试环境（一键编排、凭据注入与网络故障判别）也在此域。本域能力页清单如下。

## 能力页

| 能力页 | 简介 | 更新时间 |
| --- | --- | --- |
| [test-import-isolation](test-import-isolation.md) | 测试导入隔离 | 2026-10-03 04:59 |
| [test-incremental-selection](test-incremental-selection.md) | 测试增量选择 | 2026-10-03 04:59 |
| [test-callsite-migration](test-callsite-migration.md) | 测试调用点迁移 | 2026-10-03 04:59 |
| [test-double-fidelity](test-double-fidelity.md) | 测试替身保真度 | 2026-10-03 04:59 |
| [concurrent-suite-isolation](concurrent-suite-isolation.md) | 并发套件隔离（端口、临时目录与 basetemp） | 2026-11-04 15:41 |
| [test-authoring-discipline](test-authoring-discipline.md) | 测试编写设计规则（全局替换 try/finally 复原、假 spawn 按 cmd[0] 分发、常驻线程收割、用户级配置双隔离、夹具指向 archive、归档清单命中形态夹具实名、单测禁读构建产物、就地改写构建产物须快照回写） | 2026-11-10 11:20 |
| [per-test-timeout](per-test-timeout.md) | pytest 单用例超时硬门（10s 门 + 显式豁免清单） | 2026-10-03 05:13 |
| [fixture-project-governance](fixture-project-governance.md) | fixture 项目治理（含场景夹具 fixture=True 打标守卫） | 2026-10-27 16:48 |
| [regression-coverage](regression-coverage.md) | 语义回归覆盖 | 2026-10-03 04:59 |
| [test-regression-declaration](test-regression-declaration.md) | 回归声明 | 2026-10-03 04:59 |
| [test-regression-execution](test-regression-execution.md) | 回归执行 | 2026-10-03 04:59 |
| [test-regression-view](test-regression-view.md) | 回归视图页签 | 2026-10-07 03:30 |
| [regression-issues-rerun](regression-issues-rerun.md) | 定向子集回归触发链（错误/长耗时重跑） | 2026-10-07 03:30 |
| [callsite-arity-guard](callsite-arity-guard.md) | 校验函数调用点参数守卫 | 2026-10-03 04:59 |
| [integration-test-env](integration-test-env.md) | Docker 集成测试环境（run.sh 一键编排、镜像纯环境契约、双 harness 双轮、三插件面 GUI 验证、smoke 免凭据、.env 凭据注入与克隆源形态） | 2026-11-08 03:40 |
