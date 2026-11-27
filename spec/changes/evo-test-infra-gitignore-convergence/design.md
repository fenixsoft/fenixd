# 设计：test-infra-gitignore-convergence

## D1 采用 .gitignore 收敛（不改 stash_guard）

- 5 次复发全部集中于本项目的规约矛盾（CLAUDE.md:32 强制测试进 .test/ × .gitignore:11,40 整目录忽略）；框架侧豁免会波及所有项目且引用核查形态不可行。
- stash_guard 机制不动：对真运行时产物（verify-shots 截图）的剥离是设计预期（防 merge-back 撞车循环）。
- 交付落点为 fenix-desktop 仓库（.fenix/core 为指向 /root/fenixd/core 的符号链接，框架侧零改动）。

## D2 .gitignore 目标形态

- 删除第 11 行（# Logs 块内，错置）与第 40 行（# IDE 块内）两条 .test/ 整目录规则，规则集中到单一区段避免双声明漂移。
- 代之以窄规则（按存量盘点落定，种子形态）：
  - .test/verify-shots/（回归截图运行时产物，28 张 png）
  - .test/*.png（fetch-icon 等截图产物）
  - 一次性调试/冒烟脚本形态种子：zz-*、repro-*、*-repro.*、*-smoke*.mjs、*-probe*.mjs、verify-*.mjs（按实际文件名盘点校准，如 probe-extension.mjs、stock-account-sync-repro.mjs、aggregation-tabs-scroll-debug.mjs 的归属）
- 收敛后 git status --porcelain .test/ 复核：可见 untracked 只剩待入库测试基建，无成片散件。

## D3 版本控制恢复清单（Deliverables 口径）

- 重新入库 9 月 4 次剥离的 10 个文件（provenance 明确、3 个在途 SPEC 的验收面直接受益）：multi-user-sync.test.ts、notes-standalone-sync.test.ts、notes-sync-integration.test.ts、quick-links-sync.test.ts、quick-links-sync-adapter.test.ts、stock-standalone-sync.test.ts、stock-sync-adapter.test.ts、quick-links-e2e.mjs、stock-sync-e2e.ts、test-panel-input-autofocus.html。
- 磁盘其余 10 个 never-tracked 回归脚本（aggregation-email / aggregation-storage / finance-stats / floating-panel-layout / ipo-monitor / monitor-snapshots-merge / quick-links-model / quick-links-url / settings-transfer / stock-search 的 .test.ts）：逐个在 fresh worktree 跑通后入库；跑不通者移入 .test/attic/ 留档区（仍入库、退出回归面 glob），不删除。
- helpers.ts：053da8b 内联后已无引用者（死残留），随散件盘点删除；4 个存量 tracked 测试的内联副本保持现状（不对已稳定测试扩大改动面）。
- playwright-config.json（30 字节）与 test-harness*.html 等散件随盘点逐个表态（入库 / 忽略 / 删除）。

## D4 回归面扩容的过期风险处置

- 回归面按 .test/*.test.ts 顶层 glob 收集，任何入库 .test.ts 自动入面；never-tracked 脚本多产自 8-9 月，可能存在过期或环境依赖失败。
- 处置：fresh 检出全量跑一遍 regression.cmd 同款命令（esbuild 打包 + node 执行）；因脚本过期失败（非产品缺陷）或单文件耗时过长拖垮回归总预算（verify.yaml timeout_seconds=1800，实测判定）的移入 .test/attic/（glob 非递归，attic 内脚本不进面，verify.yaml:65 顶层 glob 已证实）并在提交说明记录处置清单；产品缺陷形态的失败不在本 SPEC 范围（走 code-review 台账）。
- .test/attic/ 默认入库留档（preserve 历史），不设忽略规则；若实现时判定留档价值为零可改窄规则忽略，须记录。

## 风险

- stray-WIP 清扫面：收敛必须与窄规则、散件表态同批落地，否则 .test/ 下约 45 个 untracked 散件暴露给主树散件清扫（目录约 75 条目 - 21 脚本 - helpers - verify-shots）。
- 交付物守卫联动：收敛后未来 SPEC 可直接把 .test 路径写入 Deliverables 声明（解除 gitignore 拒 new 双难）；本 SPEC 自身的新增交付物在同一分支先改 .gitignore 再入库即可满足守卫校验。
- 回归时长：21 脚本全量执行受 verify.yaml regression timeout_seconds=1800 约束；现有 4 脚本秒级完成，扩容后仍充裕，实现时以实测为准。