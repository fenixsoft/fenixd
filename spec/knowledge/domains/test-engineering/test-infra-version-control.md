# 测试基建版本控制与忽略规则收敛

<!-- knowledge: capability=test-infra-version-control rev=1
     sources=spec/changes/evo-test-infra-gitignore-convergence -->

承载回归测试基建的 `.test/` 目录（交付载体在 fenix-desktop 仓）必须处于版本控制：忽略规则只收运行时产物与一次性调试脚本，不做整目录忽略——「规约要求 tracked × gitignore 判忽略 × merge-back 清理器必剥离」的三方冲突从忽略规则侧解除，框架清理器零改动。

## 规则

- **测试基建 tracked 且不被清理器剥离**：`.gitignore` 不得整目录忽略承载测试基建的目录本体；回归脚本（`*.test.ts`）、共享辅助模块、SPEC commissioned 的 e2e 脚本与测试页合法 tracked。merge-back 清理器（stash_guard purge）对这类路径的剥离 victims 构造性为空——fresh worktree 检出的回归面与主树磁盘一致，无「主树可见、fresh 缺席」的静默缺口。
- **忽略规则两类可归因**：与测试目录相关的忽略规则只允许两类——①运行时产物（回归截图目录、png 产物）；②一次性调试/冒烟脚本形态（`zz-*`、`repro-*`、`*-repro.*`、`*-smoke*`、`*-probe*`、`verify-*.mjs`、`*-debug.mjs` 等按存量盘点落窄规则）。测试脚本、共享模块、测试配置不得被任何忽略规则命中；收敛后不留成片未表态散件（不扩大主树散件清扫面）。
- **存量散件四类表态**：目录下每个存量文件归入「入库 / 留档区 / 忽略 / 删除」之一并有记录；过期（脚本自身失效，非产品缺陷）或单文件耗时超回归总预算的脚本移入 `.test/attic/` 留档区——仍入库保留历史、退出回归面（回归收集 glob 非递归，attic 内脚本不进面），不删除；产品缺陷形态的失败走审查台账，不在忽略规则面处置。
- **回归面完整与守卫双难解除**：回归收集按顶层 glob 逐脚本打包执行，任何入库脚本自动入面；「gitignore 拒 new / worktree 缺件打回 reference」的交付物守卫双难随收敛解除，后续 SPEC 可直接把测试路径写入交付物声明。
- **框架清理器不豁免**：本能力以忽略规则收敛实现，框架侧 stash_guard 对真运行时产物（如 verify 截图）的剥离是设计预期、保持不动；框架不为单个项目的忽略规则错配提供扩展名白名单或引用核查豁免。

## 代码锚点

- 框架侧消费守卫：`core/worktree_manager/stash_guard.py`（merge-back purge 面；对测试基建路径 victims 构造性为空）
- 交付载体：fenix-desktop 仓（忽略规则窄化区段、测试基建入库与 `.test/attic/` 留档区；跨仓交付，不设本仓路径锚点）

## 溯源

- 2026-11-27 evo-test-infra-gitignore-convergence（spec/changes/evo-test-infra-gitignore-convergence/） — 新建本能力：整目录忽略收敛为窄规则两类、9 月 4 次误剥离的 10 个测试文件重新入库、never-tracked 回归脚本逐个表态入库或 attic 留档（动因：stash_guard 对「tracked 且被忽略」一律剥出索引，同指纹 5 次剥离全部命中合法测试基建约 3300 行、剥真草稿 0 次；fresh worktree 回归面自 9 月静默塌缩——磁盘 21 个回归脚本仅 4 个 tracked，并迫使 3 份在途 SPEC 写绕行条款）
