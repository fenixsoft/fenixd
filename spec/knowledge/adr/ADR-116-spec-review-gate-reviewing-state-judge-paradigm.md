# ADR-116：方案级评审门——显式 reviewing 状态与判官范式

date: 2026-09-19
status: accepted

## Context

drafted→ready 晋升链全是机械校验（声明软化、两道 lint），没有环节判「方案本身是否成立」；方向性错误要等一整轮实现+验证预算烧完才暴露，且无法归因到方案。自进化批量产出的 evo-* SPEC 更是零人工方案背书直接进入实现。硬约束：agent 以 bypassPermissions 启动，进程层面无法硬限制其写范围；主树常存人工在途修改。

## Decision

- drafted 与 ready 之间插入方案级评审，承载为**显式状态** `reviewing`（drafted→reviewing→ready/blocked），不以字段承载子状态——「状态字面量不变、靠字段区分真实语义」是本框架可观测性事故高发形态；显式状态换来事件映射、recovery、dashboard、hook 全部既有机制零成本适配。
- 分流为「默认全量 + 白名单跳过」：正向风险特征实测无区分力（`mode==full` 单条即命中 62.7%，任何并集与全量无实质差别），判据判错时「多评一次」优于「漏审」。`evo-` 前缀永不命中跳过白名单——批量产出的质量保障不能被同一批量的特征自我取消。
- 评审 agent 走判官范式：主树直跑、不建 worktree——评审对象（SPEC、归档、run 转录）全在主树，worktree 会凭空引入本框架多次出事故的 merge-back 依赖链。
- 越界写入用**检测式**边界校验（派发前快照 / 收工比对，脏文件附内容哈希），不做强制隔离、不自动回滚：无法硬限制就诚实检测；自动还原会把越界改动与人工在途修改一并回滚，误伤人工的代价更高。
- 评审失败 fail-closed（失败即放行等于让评审器崩掉成为绕过捷径），重试耗尽转 blocked；`spec-review-rejected:`（方案被否决）与 `spec-review-incomplete:`（评审器没跑成）同前缀族不同值——两者都停下等人，但人要做的事完全不同。
- 结论三值 `approved` / `repaired` / `rejected` 供机械对账（approved 无改动、repaired 必有修补清单）；配置面最小化，只留 `auto`/`never` 整体开关，启发式阈值一律硬编码。

## Consequences

- 方向性风险被挡在实现之前，把关成本从一轮实现+验证降为一次单轮只读评审；评审 run 计入既有并发闸门。
- 新状态触及面广（转移表、事件、recovery、色板、文档），是一次性成本；新增推进路径必须核对状态全集消费点。
- 评审是 LLM 判断可误判：rejected 一律交人工，evidence 必须引用具体文件位置，禁止无依据断言。
