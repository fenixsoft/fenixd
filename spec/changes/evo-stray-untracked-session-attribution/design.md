# design：stray-untracked-session-attribution

## 落点

- core/worktree_manager/stray_wip.py：MainTreeStrayWipSweeper._untracked_signal（657-755）与 _sweep_locked 调用点（:424）。

## 改动要点

1. _untracked_signal 签名增参 running_run_ids=()；_sweep_locked :424 改为 self._untracked_signal(untracked, running_run_ids)。
2. 在 not below_threshold 分支内（:710 宽限判定前）插入归因探测：
   - 调 wm.identify_wip_occupant(entries, running_run_ids)（与 tracked 流 :463 同一入口）。
   - 命中会话归因且 self._config 的 admin.maintree_session_attribution_action != keep（缺省 info）：
     - self._untracked_registry.pop(fp, None)（时钟复位，与 tracked 流 :478 同型）；
     - self._log("info", f"主树 untracked 散件归因到主树活交互会话，复位宽限计时（不升级不处置）: <files>; <describe>")；
     - 返回 status session-attributed（携带归因证据），本轮不再进入宽限告警与升级判定。
   - 零命中：维持现状流程不变（宽限→升级）。
3. 升级分支（:726-739）发射 escalated 信号时，evidence 追加「归因探测已执行，零命中（判据：近窗提交路径交/活跃 transcript 路径提及）」注记，对齐 tracked 流 _write_alert 归因证据段（:1341）形态。
4. 低于阈值早退分支（:702-709）保持不调归因：只建档计时，无探测成本。

## 边界与取舍

- 豁免=复位而非永久：与 tracked 流语义对齐，会话离场后 re-建档自然重新起算，不需要额外状态。
- 不建认领清单：外部交互会话不受 daemon hook 约束，登记不会自然发生；transcript 候选已是被动观测面，无需人工登记。
- 归因探测成本：仅越阈集合付出一次 identify_wip_occupant（内部 git log + transcript 读尾），与 tracked 流每轮同源调用同量级。
- 与 memory stale-stray-snapshot-race 的关系：机制化后 admin 收到的升级信号已带「零命中」注记，操作层重查 git status 的保险丝保留不撤。
- keep 配置回退守卫与 tracked 流同键（admin.maintree_session_attribution_action），运维心智单一。