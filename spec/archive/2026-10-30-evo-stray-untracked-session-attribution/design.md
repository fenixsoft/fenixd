# design：stray-untracked-session-attribution

## 落点

- core/worktree_manager/stray_wip.py：MainTreeStrayWipSweeper._untracked_signal（657-755）与 _sweep_locked 调用点（:424）。

## 改动要点

1. _untracked_signal 签名增参 running_run_ids=()；_sweep_locked :424 改为 self._untracked_signal(untracked, running_run_ids)。
2. 在 not below_threshold 分支内（:710 宽限判定前）插入归因探测：
   - 调 wm.identify_wip_occupant(entries, running_run_ids)（与 tracked 流 :461 同一入口）。归因器输出三态（mergeback.py:823-912：在飞实现车道 holder / 主树会话归因 / 零命中），三态均须约定处置：
   - 命中会话归因且 self._config 的 admin.maintree_session_attribution_action != keep（缺省 info）：
     - self._untracked_registry.pop(fp, None)（时钟复位，与 tracked 流 :478 同型）；
     - self._log("info", f"主树 untracked 散件归因到主树活交互会话，复位宽限计时（不升级不处置）: <files>; <describe>")；
     - 返回 status session-attributed（携带归因证据），本轮不再进入宽限告警与升级判定。
   - 命中在飞实现车道 holder（非会话归因，info.holder 且非 is_session_attribution；机制可达：车道分支 git add 了与主树 untracked 同名的路径后，三点 diff 分支侧改动集与 overlap 求交命中）：同样 pop 计时、不告警、返回 status holder-attributed——对齐 tracked 流 holder 分支（:464-472「归属期间不算滞留」）语义，MUST NOT 视同零命中走宽限升级（否则对仍在飞 run 名下的文件发射 major）。
   - 零命中：维持现状流程不变（宽限→升级）。
   - 插入点在 _reset_untracked_registry_absent（:700）之后：pop 单独执行即可（absent 复位语义是清除「消失」指纹，pop 不属消失态），下轮指纹重建档 first_seen 重起即「复位时钟」；持久化注册表收尾落盘镜像自然不含被 pop 条目，无需额外落盘处理。
3. 升级分支（:726-739）发射 escalated 信号时，evidence 追加归因探测结果注记，措辞按探测结果分档（对齐 tracked 流 _write_alert 归因证据段「归因证据: <describe>」（:1357）形态）：零命中写「归因探测已执行，零命中（判据：近窗提交路径交/活跃 transcript 路径提及）」；命中但被 admin.maintree_session_attribution_action=keep 回退（tracked 流 :495-500 同型分支）写「归因探测已执行，命中但配置 keep 回退（视同零命中）」——MUST NOT 在 keep 回退场景误述为「零命中」，误导 admin 判读。
4. _untracked_signal docstring（:670-671）status 枚举说明同步补入 session-attributed / holder-attributed（现有枚举「below-threshold / timed / alerted」已缺 escalated，一并补全）。
5. 低于阈值早退分支（:702-709）保持不调归因：只建档计时，无探测成本。
4. 低于阈值早退分支（:702-709）保持不调归因：只建档计时，无探测成本。

## 边界与取舍

- 豁免=复位而非永久：与 tracked 流语义对齐，会话离场后 re-建档自然重新起算，不需要额外状态。
- 不建认领清单：外部交互会话不受 daemon hook 约束，登记不会自然发生；transcript 候选已是被动观测面，无需人工登记。
- 归因探测成本：仅越阈集合付出一次 identify_wip_occupant（内部 git log + transcript 读尾），与 tracked 流每轮同源调用同量级。
- 与 memory stale-stray-snapshot-race 的关系：机制化后 admin 收到的升级信号已带「零命中」注记，操作层重查 git status 的保险丝保留不撤。
- keep 配置回退守卫与 tracked 流同键（admin.maintree_session_attribution_action），运维心智单一。