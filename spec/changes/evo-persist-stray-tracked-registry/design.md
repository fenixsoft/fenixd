# 设计：tracked 流注册表落盘与同指纹静默窗

## 决策重开（D5）
stray_wip.py:22-33 模块 docstring 与 :517-521 类 docstring 现行表述「tracked 流维持内存态（重启重置宽限的损失仅时效）；不引入新的持久化状态文件」。实证反驳：2026-11-21..22 窗 4 次重启后 69/71/69/69 秒内必重登记 first_seen（4/4），宽限耗尽后兑现为完整处置 run（实测 120-232 秒、约 0.8 美元），两窗 14 run 11.8 美元。同型实测口径见归档先例 spec/archive/2026-10-30-evo-persist-stray-escalation-clock/design.md：first_seen 落在重启后约 70 秒，告警在 30 分钟宽限后发出；AdminStore 现存同指纹告警记录亦均为 first_seen 之后约 30.2 分钟（如 .fenix/admin_alerts.json 中指纹 b2409791a7c421ad 的两条记录）。本 SPEC 重开 D5：仅对 tracked 流补持久化，untracked 流既有落盘（evo-persist-stray-escalation-clock 落地）不动。

## 方案
1. 同构复用 untracked 注册表实现：新增 TRACKED_REGISTRY_RELPATH='.fenix/stray_tracked_registry.json'，路径常量/字段白名单/加载（_load_tracked_registry）/原子写（_persist_tracked_registry，tmp+replace、payload 无变更跳过）照搬现有 untracked 形态（UNTRACKED_REGISTRY_RELPATH:128、_UNTRACKED_PERSISTED_FIELDS:136、_load_untracked_registry:2039、_persist_untracked_registry:2192）。文件两分区：
   - `tracked`：计时注册表，键=改动指纹 fp，条目字段白名单同 untracked 计时条目（first_seen/first_seen_iso/files/escalated_at；不写 escalated_signal_at，该档属 untracked 升级语义）；
   - `alert_history`：静默窗台账，键=同一 fp，值={"last_alert_at": epoch 秒, "suppressed_count": int}。
   载入挂点：`sweep()` 进入 `_sweep_locked` 之前，以 `_tracked_registry_loaded` 守卫每进程一次（对齐 :685 的 untracked 载入）；回写挂点：`sweep()` 的内层 finally（`_sweep_locked` 之后、主树锁释放之前），含本轮放弃路径——与 :687-691 的 untracked 落盘同位置。载入遇 OSError/字节层损坏时置 tracked 版「本轮禁写」哨兵（对齐 `_untracked_persist_suppressed`，code-review item d055f002ec41），本进程跳过回写，防空表 payload 覆写盘上完好注册表；JSON 层真损坏仍覆写自愈。
2. 静默窗（取代 tracked 流现行 escalated_at 一次性门槛）：
   - fp 定义已含路径排序集 + `git diff HEAD` 内容哈希 + 二进制内容补全（_fingerprint:1203-1223），同 fp ⟺ diff 字节级零演进，无需另存 last_alert_fingerprint（设计初稿的该字段与注册表键重复，删除）。
   - 宽限判定不变（elapsed_min >= grace 才进入告警候选）。候选轮查 `alert_history[fp]`：
     - 无记录 → 发告警，记 last_alert_at=now、suppressed_count=0；
     - 有记录且 now-last_alert_at < 24h → 抑制：MUST NOT 写 AdminStore、MUST NOT 唤起 admin run；suppressed_count += 1；按既有 60 分钟日志窗落一条聚合 info（形态对齐 `_session_attr_dedup_log`）；sweep 返回 status 维持 `orphan-timed`、返回键集不变（既有返回值契约零改动）。
     - 有记录且 ≥24h → 正常重告，evidence 增「静默窗抑制轮数=N」（N=suppressed_count，与既有 `_prior_stray_rounds` 复发轮数分列、语义不混），随后刷新 last_alert_at=now、suppressed_count=0。
   - `escalated_at` 仍随 tracked 条目录入/持久化（审计与既有断言兼容），但 tracked 流告警门槛以 `alert_history` 为准：当前 `elapsed_min >= grace and not entry.get("escalated_at")` 判据须改写，否则持久化的 escalated_at 会把「满 24h 可再告」永久禁掉（静默窗的 24 小时边界将不可达）。
   - 指纹演进＝新 fp＝alert_history 无记录＝按宽限正常告警；旧 fp 台账保留至淘汰。
   - `alert_history` 独立于 `_registry` 条目生命周期：`_registry.pop`（在飞车道命中 :1035、会话归因 :1048）与 `_reset_registry_absent`（:1125）只清计时条目，不动静默窗台账——归因瞬时 pop 后同指纹重登记仍在 24h 窗内。淘汰：某 fp 当轮不在场且 last_alert_at 已超 24h → 删除台账条目；散件提交/还原后计时条目照旧清除。
3. 零触碰口径与落盘位置：新文件在 `.fenix/*` 忽略区内（.gitignore:26），不入库、不被 untracked 散件盘点计入（已 ignore 路径豁免）、不出现在 `git status --porcelain`，故零触碰对账（tracked 行逐字节一致）仍成立；模块 docstring「落盘仅两处」注记须同步改为三处（AdminStore、untracked 注册表、tracked 注册表）。
4. 与在途 spec 边界：evo-add-stray-wip-claim-reconcile（认领侧 auto-resolve）proposal 明文「处置侧 sweep 行为零改动」——本 SPEC 改的正是 sweep 告警发射侧（升级节奏由「一次性」改为「24h 滚动窗」），两者对 AdminStore 记录的消费互不依赖，文件交集仅 stray_wip.py，先后合入仅需 rebase。

## 权衡
- 24h 滚动窗把复发上界收敛为「每指纹每 24 小时至多一条告警」，而非无限期一次性——这是 proposal 目标 2 的明示口径。若产品改为「永不重告」，只需把窗比较改成「有 last_alert_at 即抑制」，台账与持久化结构不变。
- 不选「把静默窗字段塞进计时条目」：该条目在归因命中/会话归因分支会被 pop（:1035/:1048）、在指纹不在场时被复位（:1125），条目级字段会随复发路径一起丢失，24h 窗恰在最需要它的场景失效。

## 测试与验证面
tests/test_stray_tracked_registry_persistence.py：落盘/重启恢复/原子写与字段白名单/24h 内同指纹抑制与 suppressed_count 累计/满 24h 重告带抑制轮数/指纹演进重告/归因分支 pop 计时条目后台账仍在/载入 OSError 禁写/损坏回退内存态不阻塞盘点/台账淘汰；装配方式参照现有 tests/test_maintree_stray_wip_sweep.py 与 tests/test_stray_whitelist_untracked.py。回归锚：既有 test_maintree_stray_wip_sweep.py（同指纹一次性、registry 复位、sweep 返回值契约逐位不变）全绿。
