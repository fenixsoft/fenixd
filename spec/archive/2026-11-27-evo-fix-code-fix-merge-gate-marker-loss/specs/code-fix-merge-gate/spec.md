# code-fix 合并门纯标记提交放行与弃件留证

## ADDED Requirements

### Requirement: 纯标记提交放行

合并门对 fixed=0 且 commits>0 的批次 SHALL 在拒合回前核查批内全部提交的变更形态。纯标记批判据：全部提交的新增行均为含 `[fenix-ignore:<item_id>]` 标记本体的注释行（注释语法按写侧契约 agents/code-fix.md「忽略标记」节取所在文件语言形态：Python/YAML `#`、TS/JS `//`、HTML/Markdown `<!-- -->` 等，可含尾随说明文字），且删除行仅为标记注释行或为空；满足时 SHALL 合回该批提交并按批完成收尾，批内 pending（非 ignored）条目比照现拒合回分支口径入 chain_skipped（保留下链重试语义，不因批放行而核销或置终态）。新增行含任一非标记行、或删除行含任一非标记行的混合批 SHALL NOT 放行。

#### Scenario: 纯标记批放行合回

- **WHEN** 某 fix 批报告 fixed=0、commits=1、ignored>=1，且该提交 diff 仅含 fenix-ignore 标记注释行（对照 11-14 弃件 00162a0 实例形态）
- **THEN** 合并门合回该提交，批按完成收尾，链 rollup 注记「产物已合并（纯标记）」

#### Scenario: 混合批不误放

- **WHEN** fixed=0、commits=1，但提交含非标记改动（源码/配置实质变更，对照 10-19 弃件形态）
- **THEN** 不合回，弃件留痕列出该 commit 完整 SHA 与非标记文件清单

### Requirement: 全批 ignored 收尾路径同治

fixed=0 且全批 ignored 的「批按完成收尾」分支 SHALL 在收尾前执行同一纯标记核查与合回，SHALL NOT 以 success 终态静默丢弃纯标记提交。

#### Scenario: 全 ignored 批的标记提交不再静默丢弃

- **WHEN** 批内条目全部判 ignored 且批内存在纯标记提交
- **THEN** 先合回标记提交再按完成收尾，rollup 注记产物已合并

### Requirement: 拒合回弃件强制留证

合并门发生拒合回时 SHALL 落一条 admin 告警记录，内容 MUST 含全部被弃提交的完整 SHA、对应批条目 id、非标记文件清单；留痕 MUST 先于 worktree 清理动作。

#### Scenario: 弃件可捞回

- **WHEN** 拒合回发生
- **THEN** 告警记录含被弃 commit 完整 SHA 清单，人工可按 id 直接 cherry-pick 捞回（对照 10-19 弃件 id 未落盘永久不可考反例）

### Requirement: 产物去向进批级终态

链收尾 rollup 与台账注记 SHALL 区分「产物已合并/产物已弃（附 commit id）」；run 层终态发出时点与语义保持现状不变。

#### Scenario: 三层认知一致

- **WHEN** 某批被拒合回
- **THEN** 链 rollup 与台账注记明确「产物已弃（commit <sha>）」，不再出现「收尾自述已落 + 终态 success」与产物实际被弃并存的矛盾记录