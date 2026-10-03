# add-maintree-interactive-session-attribution

## 背景

2026-10-03（UTC）potplayer-base 项目 maintree_stray_wip_stale 信号一天 7 连发，框架逐条派 7 个 admin run 代查归属，duration 合计 3079 秒（≈51 分钟 admin 车道），其中 09:35:08Z 一例确认为归因盲区误报（实为主树内活交互会话已交付、待人工提交的成果）。归因器 identify_wip_occupant（core/worktree_manager/mergeback.py:856）只按在飞车道前缀（impl-/code-fix-，:847）与分支 diff 求交，主树直改形态结构性零命中；core/worktree_manager/types.py:27 BLIND_SPOT_NOTE 自认此盲区。同窗口放大器：被 git 跟踪的生成型构建日志（build-win-configure.log，提交 5935771 内容即绝对路径改写）每次主树构建都变脏，指纹一变即重置宽限再升级。

## 目标

1. 盘点归因数据源补「主树活交互会话」只读探测：主树散件能归因到活交互会话时，告警 evidence 标注归属，且此类散件默认不再升级为 major 告警/不派 admin 代查，降低无主误判与每日代查税。
2. 归因输出对既有消费者（stray_wip 盘点告警、code_fix defer 告警）透明生效。
3. 探测全程只读，不违反 mergeback.py:952「MUST NOT 为覆盖盲区引入主树写探测」约束。

## 非目标

- 不改 tracked-only 盘点口径（untracked 散件盲区另案处理）。
- 不处置消费项目仓库内的一次性清理（如 potplayer-base 的 build-win-configure.log 出库，属项目侧人工决策，5935771 提交信息已预留建议）。
- 不引入 LLM 推导路径（identify_wip_occupant 现有设计约束：纯机械归因）。

## 验收

- 构造主树内活交互会话直改场景：归因结果给出会话线索（非「无主」），盘点侧降级为 info 留痕而不派 major 告警。
- 无活会话/探测源缺失时行为与现状一致（fail-open 回「无主」走既有宽限升级），不新增误报。
- 新增测试覆盖归因分支；tests/test_maintree_stray_wip_sweep.py 既有用例不回退。