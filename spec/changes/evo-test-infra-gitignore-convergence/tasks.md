## Deliverables

```yaml
- path: .gitignore
  kind: modify
- path: .test/multi-user-sync.test.ts
  kind: reference
- path: .test/notes-standalone-sync.test.ts
  kind: new
- path: .test/notes-sync-integration.test.ts
  kind: new
- path: .test/quick-links-sync.test.ts
  kind: new
- path: .test/quick-links-sync-adapter.test.ts
  kind: new
- path: .test/stock-standalone-sync.test.ts
  kind: new
- path: .test/stock-sync-adapter.test.ts
  kind: new
- path: .test/quick-links-e2e.mjs
  kind: new
- path: .test/stock-sync-e2e.ts
  kind: new
- path: .test/test-panel-input-autofocus.html
  kind: new
```

## 1. 忽略规则收敛

- [x] 1.1 .gitignore：删除第 11、40 行两条 .test/ 整目录忽略规则并集中为单区段声明，代之以运行时产物与调试形态窄规则（种子：.test/verify-shots/、.test/*.png、zz-*、repro-*、*-repro.*、*-smoke*.mjs、*-probe*.mjs、verify-*.mjs，按 .test/ 实际盘点校准）
- [x] 1.2 盘点 .test/ 全部存量文件并逐个表态（入库 / .test/attic/ 留档 / 窄规则忽略 / 删除）：含 helpers.ts 死残留删除（053da8b 内联后无引用者）、playwright-config.json、test-harness*.html、probe/verify 类散件归属，表态清单写入提交说明
- [x] 1.3 核验：git check-ignore -v 抽样确认 .test/*.test.ts 等测试基建路径零命中忽略规则；git ls-files -ci --exclude-standard 过滤 .test 前缀结果为空

## 2. 测试基建入库

- [x] 2.1 将 9 月 4 次剥离的 10 个文件重新入库（与 .gitignore 收敛同一分支，先改 ignore 再 git add 入库以满足守卫 gitignore 校验）：multi-user-sync.test.ts、notes-standalone-sync.test.ts、notes-sync-integration.test.ts、quick-links-sync.test.ts、quick-links-sync-adapter.test.ts、stock-standalone-sync.test.ts、stock-sync-adapter.test.ts、quick-links-e2e.mjs、stock-sync-e2e.ts、test-panel-input-autofocus.html
- [x] 2.2 其余 10 个 never-tracked 回归脚本（aggregation-email / aggregation-storage / finance-stats / floating-panel-layout / ipo-monitor / monitor-snapshots-merge / quick-links-model / quick-links-url / settings-transfer / stock-search 的 .test.ts）逐个在 fresh worktree 跑通后入库；跑不通者按 D4 移入 .test/attic/ 留档并在提交说明记录。落地顺序约束：这 10 个脚本在实跑定性前先随收敛提交移入 .test/attic/ 缓冲（attic 入库留档、在回归 glob 之外），跑通后同分支从 attic 转正入库——确保分支任一前缀合入主树时 .test/ 下都不存在未被表态且未被忽略规则覆盖的 untracked 散件（防止「收敛已合入、表态未落」窗口把散件暴露给主树 stray-WIP 清扫）
- [x] 2.3 fresh 检出（git worktree add 临时树或 /tmp clone 副本）全量执行 .fenix/verify.yaml regression.cmd 同款命令（esbuild 打包 + node 执行），顶层 .test/*.test.ts 全绿；产品缺陷形态的失败不在本 SPEC 范围，报 code-review 台账

## 3. 机制闭环验证

- [x] 3.1 在 /tmp 以 git clone 仓库副本模拟「分支新增 tracked .test 基建 → 合回」，确认不再产生「merge 后移出随分支带回的 ignored 运行时草稿」自动剥离提交（主树不受影响）
- [x] 3.2 以 git check-ignore 确认含绕行条款的在途 SPEC（quick-links-standalone-sync、stock-account-finance-sync）tasks.md 提及的 .test 路径全部脱离忽略射程，核验结果写入提交说明（不回改在途 SPEC 文档）
