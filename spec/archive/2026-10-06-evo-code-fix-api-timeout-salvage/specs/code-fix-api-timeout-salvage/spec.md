# code-fix-api-timeout-salvage

## ADDED Requirements

### Requirement: API 超时终局签名结构化
code-fix 批 run 终局失败时，框架 SHALL 判别是否为单轮 API 请求超时签名（CLI Exit 1 且末次 result 事件 terminal_reason 为 api_error，或 result 文本含 "Request timed out"），并在失败记录与日志中携带结构化 api_timeout 标记；非该签名的失败 SHALL NOT 被误标。

#### Acceptance Scenario 1: 超时签名识别与透出
- WHEN 批 run 终局为 CLI Exit 1 且末次 result 事件 terminal_reason=="api_error"（或 result 文本命中 "Request timed out"）
- THEN 失败记录与日志携带 api_timeout=true 结构化字段，不再把签名压扁为异常字符串

#### Acceptance Scenario 2: 非超时失败不误标
- WHEN 批 run 因确定性失败或其他异常终局（末次 result 非 api_error 且无超时文本）
- THEN api_timeout 标记为 false，失败处理路径与现状一致

### Requirement: 超时失败现场 salvage
api_timeout 终局且 worktree 工作区存在未提交改动的 code-fix 批 run，框架 SHALL 在判失败时把 WIP salvage 提交到该批分支，并按既有 recovery legacy 机制登记保全现场，而不是立即物理清理。

#### Acceptance Scenario 3: 失败现场保全
- WHEN api_timeout 终局且工作区脏
- THEN WIP 以 salvage commit 落到批分支（复用 add-codefix-commit-first-contract 的 salvage 模式）
- AND worktree 按 legacy 机制登记保全（宽限期内豁免陈旧清扫），不再只留悬空快照

#### Acceptance Scenario 4: 工作区干净时不做 salvage
- WHEN api_timeout 终局但工作区无改动
- THEN 跳过 salvage，按现状清理

### Requirement: 同链下一批接续 salvaged 现场
api_timeout 失败批 salvage 后，框架 SHALL 以既有 reuse 认领机制（mark_legacy_reusable + create 内 _take_reusable_worktree）使同链下一批建树继承 salvaged 分支，让后续承担同批条目的重试批从 salvaged 工作起步；认领不可用时 SHALL fail-open 保持既有行为（全新建树），MUST NOT 以 consume_legacy（回收端，删除分支）实现接续。

#### Acceptance Scenario 5: 现场被下一批接续
- WHEN 同链下一批建树且存在置了 reuse 标记的 salvaged legacy
- THEN wm.create 经既有认领通路继承 salvaged 分支（仅分支模式在既有分支上重建载体），salvaged 提交对重试批可见
- AND 认领不可用（无 legacy/载体失效/换壳失败）时 fail-open 降级为现状行为（正常新建 worktree），不阻断链推进