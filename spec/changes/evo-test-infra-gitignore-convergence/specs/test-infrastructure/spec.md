# test-infrastructure

## ADDED Requirements

### Requirement: 测试基建处于版本控制且不被清理器剥离

.gitignore 不得整目录忽略承载测试基建的目录本体；.test/ 下的回归脚本（*.test.ts）、共享辅助模块、SPEC commissioned 的 e2e 脚本与测试页必须可合法 tracked。stash_guard purge（merge 后移出随分支带回的 ignored 运行时草稿）对这些路径的 victims 集构造性为空。

#### Scenario: fresh worktree 回归面完整

- **WHEN** 全新检出 worktree 后执行 .fenix/verify.yaml regression（glob .test/*.test.ts 逐个 esbuild 打包 + node 执行）
- **THEN** 检出结果包含全部入库回归脚本，无「主树磁盘可见、fresh worktree 缺席」的静默缺口；顶层 .test/*.test.ts 全量可解析打包

#### Scenario: 合回带入测试基建不被剥离

- **WHEN** 任一实现分支将 .test/ 下新增 tracked 测试基建合回主树
- **THEN** 不产生「merge 后移出随分支带回的 ignored 运行时草稿」自动剥离提交，文件保持 tracked

### Requirement: .test 相关忽略规则逐条可归因

.gitignore 中与 .test 相关的规则只允许两类：运行时产物（回归截图 .test/verify-shots/、png 产物）与一次性调试/冒烟脚本形态（zz-*、repro-*、*-smoke* 等按盘点落规则）；测试脚本、共享模块、测试配置不得被任何忽略规则命中；.test/ 下每个存量文件必须归入「入库 / 留档区 / 忽略 / 删除」之一并有记录。

#### Scenario: 忽略规则可归因

- **WHEN** 对 .gitignore 全部 .test 相关规则以 git check-ignore -v 抽样核验
- **THEN** 每条命中路径均属运行时产物或已归类一次性调试脚本，tracked 测试基建路径零命中

#### Scenario: tracked-但被忽略 清零

- **WHEN** 执行 git ls-files -ci --exclude-standard 并过滤 .test 前缀
- **THEN** 结果为空（现存 4 个存量 tracked 测试从「违规态」转正）