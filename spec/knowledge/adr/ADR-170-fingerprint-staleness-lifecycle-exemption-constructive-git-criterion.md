# ADR-170：产物指纹陈旧判定须区分陈旧与生命周期迁移——豁免用构造性 git 判据，终态呈现确定性收口

date: 2026-09-28
status: accepted

## Context

读侧产物校验以 `(branch, merge_base, head_commit)` 指纹拒采信陈旧报告，初衷是修复轮 head 前移后不采信过期评审。但正常生命周期迁移会合法移动 git 锚点：merge-back 把实现分支合入 main 后 `merge-base(branch, main)` 构造性前移到分支尖自身，产物记录的评审基线必然失配；SPEC 终态后 main 持续前进，框架回归快照指纹必然陈旧，且 run 内自查键按新契约缺位。实证（2026-09-23，spec `add-code-fix-batch-failure-selfheal`，pushed）：ocr 产物 status=completed、branch/head 全等、仅 merge_base 失配，门禁恒 pending——结构性必现，任何成功 push 的 spec 该门恒 pending，终态 SPEC 的门禁面板系统性误导用户，而验证结论本身不受影响。

## Decision

- 指纹陈旧判定必须区分「数据陈旧」与「生命周期推进」：产物记录的基线是历史事实而非陈旧，merge-back 等正常迁移不得触发不可见。
- 豁免判据用构造性 git 事实，禁用 STATE 状态枚举：`merge-base(branch, main) == rev-parse(branch)` 数学上等价于「分支尖是 main 的祖先」= 分支已完整合入，不依赖状态字段，规避状态与 git 事实漂移时的双真源问题。
- 豁免最小化，只豁免被迁移影响的比对项：merge-back 豁免只跳过 merge_base 比对，branch 与 head_commit 全等仍强制——head 前移（修复轮重审）的拒采信语义不变；非豁免路径行为逐字节不变。
- SPEC 终态（verified/done/pushed）后门禁呈现确定性收口：终态豁免优先级高于一切数据源，固定 reason 文案（模块常量）、计入 done，不随后续 main 推进或回归重跑摆动；终态集合与流水线内 passed 集合有意分离——implemented/testing 仍在流水线内（可能修复轮、回归重跑），显示实时状态，verified 起进入收尾、跟踪责任移交主树；新状态引入必须同步豁免集合（与「新状态引入须排查前端 status 枚举」同源纪律）。
- 测试锚定真实指纹形态（嵌套 fingerprint 子对象，对齐写侧），豁免与非豁免路径各有用例锁定。

## Consequences

- 终态 SPEC 的 6 道门禁全部呈现确定性终态，无恒 pending 误导；不放宽任何真实拒采信语义——head 前移仍拒 stale、非终态数据源优先级与逐字节行为不变，读侧显示缺陷与门禁判定质量严格分离。
- 判据自证安全：merge-base==head 即 head 是 main 祖先，不存在「分支未合入却命中豁免」的形态，豁免不可能被滥用为洗白通道。
- 代价：豁免集合与终态集合成为维护点——新增终态状态或新增指纹锚定产物时须同步复核，否则重现同类盲区；豁免逻辑落在读侧，写侧与落盘契约零改动。
