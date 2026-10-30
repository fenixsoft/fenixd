# 主树白名单文件脱落巡检（negation 放行未跟踪告警）

<!-- knowledge: capability=whitelist-tracked-patrol rev=1
     sources=spec/archive/2026-10-30-evo-whitelist-tracked-patrol -->

主树盘点对「被 .gitignore `!` 放行（negation）规则命中却不在 git 索引中」的文件发独立脱落告警——negation 放行即声明入库意图，放行而未跟踪几乎必然是白名单脱落事故；与 tracked 散件流（[maintree-stray-wip-sweep](maintree-stray-wip-sweep.md)）、untracked 散件流（[stray-untracked-escalation](stray-untracked-escalation.md)）平行，为同一 sweeper 内的第三条独立检测流。

## 规则

### 检测流与豁免边界

- 白名单入库约定：被 `!` 规则放行（如 `!.fenix/verify.yaml`、`!.fenix/todo.md`）即声明该文件随仓库入库，白名单文件不是散件。
- 检测复用 git check-ignore 批量明细通道取 negation 放行规则命中的路径，再与 `git ls-files` 求交过滤：命中放行规则且不在索引中的路径即为 `whitelist_untracked` 候选；仍在索引中的放行文件（正常 tracked 白名单）零告警。
- negation 豁免语义不变：放行文件不计入 untracked 散件计数与散件告警口径；脱落流独立于散件流、不改散件流语义，两流互不污染。
- check-ignore 批量明细不可用（detail 缺失）时白名单流整流保守放弃：当轮不告警、不留异常痕、注册表保持原状，条目留待下轮，与 tracked/untracked 流的保守放弃语义同款。

### 指纹去重与复位

- 去重沿用指纹注册表口径、独立分账：指纹 = 放行-未跟踪路径排序集 + 逐文件内容 sha256（untracked 形态不可复用 tracked 散件的 diff 指纹）；同指纹只发一次，不因周期盘点重复唤起。
- 白名单文件内容演化即换新指纹、重新告警，演化不被旧指纹吞掉；git add 恢复入库后集合消失、注册表条目自动复位，同脱落形态（同内容同指纹）再现可再报。

### 信号接入唤起（四处登记）

- `whitelist_untracked` severity major，接入自动唤起须四处同步登记，缺一即不唤起：SIGNAL_SEVERITY（登记 severity）、SIGNAL_RECOMMENDATION（登记处置指引，告警写入方与唤起记录 recommended_action 同查此表）、STORED_SIGNAL_TYPES（收录，未收录则记录落 store 后无人摄取）、spec-less 伴生表 SPEC_LESS_STORED_SIGNAL_TYPES（本信号为项目级盘点、记录无 spec，摄取循环据 evidence「项目名=」段解析还原项目名）。
- evidence 以「项目名=」开头并含「文件清单(N):」段（与散件执行器共用同一清单解析单源）与放行规则快照；文案写明「negation 放行即声明入库意图、放行+未跟踪＝白名单脱落」。
- 处置建议二选一：git add 恢复入库，或删除放行规则承认其为运行时文件；框架只告警唤起人工/裁决处置，不自动执行 git add 类修复。
- 摄取唤起成功后源记录 mark_escalated 留痕，二次摄取不重复唤起。

### 约定互引

- 「白名单文件应随仓库入库」约定（.gitignore 注释与 knowledge_audit 注释两处文档化）与执行机制互为引用：knowledge_audit 的白名单注释指向本巡检，任一侧可找到另一侧。

## 关键行为

- 单轮白名单检测：check-ignore 批量明细取放行路径 → ls-files 求交过滤已 tracked → 剩余集合构造指纹比对注册表（新指纹发 major 告警 / 同指纹复用留痕 / 指纹消失复位）→ 落盘 evidence（「项目名=」开头 + 文件清单段）→ 摄取循环解析项目名、唤起 Administrator 并 mark_escalated。

## 溯源

- 2026-10-30 evo-whitelist-tracked-patrol（spec/archive/2026-10-30-evo-whitelist-tracked-patrol） — 新建本页：主树白名单脱落巡检第三流（negation 放行未跟踪检测、tracked 求交门、保守放弃）、指纹独立分账去重与复位、信号四处登记接入唤起、knowledge_audit 约定互引；一次性处置恢复 potplayer-base .fenix/verify.yaml 入库。
