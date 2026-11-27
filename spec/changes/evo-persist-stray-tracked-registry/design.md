# 设计：tracked 流注册表落盘

## 决策重开（D5）
stray_wip.py:22-33 模块 docstring 与 :511-518 类 docstring 现行表述「tracked 流维持内存态（重启重置宽限的损失仅时效）；不引入新的持久化状态文件」。实证反驳：2026-11-21..22 窗 4 次重启后 69/71/69/69 秒必重告（4/4），每次兑现为完整处置 run（实测 120-232 秒、约 0.8 美元），两窗 14 run 11.8 美元。本 SPEC 重开 D5：仅对 tracked 流补持久化，untracked 流既有落盘（evo-persist-stray-escalation-clock 落地）不动。

## 方案
1. 同构复用 untracked 注册表实现：新增 TRACKED_REGISTRY_RELPATH='.fenix/stray_tracked_registry.json'，路径常量/字段白名单/加载（_load_tracked_registry）/原子写（_persist_tracked_registry，tmp+replace）照搬现有 untracked 三件套（:123/:1925/:1968/:2121）形态，载入/回写挂点接入现有盘点 sweep 流程。
2. 静默窗：注册表条目增 last_alert_at 与 last_alert_fingerprint（diff 归一化哈希）；告警发射判定先查窗与指纹——24 小时内且字节级零演进→仅累计度数（度数记账留在告警 description 侧，不重发 alert）；演进→重发并刷新两字段。
3. 与在途 spec 边界：evo-add-stray-wip-claim-reconcile（认领侧 auto-resolve）proposal 明文「处置侧 sweep 行为零改动」——本 SPEC 改的正是 sweep 告警发射侧，两者正交，文件交集仅 stray_wip.py，先后合入仅需 rebase。

## 测试与验证面
tests/test_stray_tracked_registry_persistence.py：落盘/重启恢复/原子性/静默窗抑制/演进重告/损坏回退六场景；装配方式参照现有 test_maintree_stray_wip_sweep.py 与 test_stray_whitelist_untracked.py。