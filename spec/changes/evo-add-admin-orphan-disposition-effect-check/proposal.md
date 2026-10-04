# add-admin-orphan-disposition-effect-check

## Why

admin run 在「动作已执行、终态未落账」窗口死亡时，台账出现两类永久滞留：mid-run 产物内容落成的终态记录（如 827b4f2fe0c8，result=partially-resolved、handled=False）与唤起前占位记录（如 613d42266fdb，pending）。前者让 AdminMonitor 的孤儿处置扫描（_recover_orphaned_dispositions）因「组内已有非 pending 记录即 final」而永久跳过，后者随之永不被升级——2026-10-03 的 429 冻结处置现场（admin-global-1791056118，4 个 spec 解冻重派全部生效）滞留超过 21 小时无人收敛，台账与真实状态失真，占位记录里「AdminMonitor 会自动升级人工」的承诺对该形态系统性落空。

## What Changes

1. （主）孤儿处置收敛的生效核查补记：_recover_orphaned_dispositions 对 final 组不再无条件跳过——组内终结记录 handled=False（或仍有滞留 pending）时，对「动作是否已实际生效」做只读核查（STATE frozen/status、fenixd.log Transition 留痕等真实状态证据），核查通过则补记 resolved（append 新记录、注明补记与依据）并对关联信号 mark_signal_handled 收口；核查不通过维持滞留并走既有升级（fail-closed，守 evo-fix-global-signal-choice-execution 2.2 语义）。
2. （辅）choice 粒度小步落账：AdminMonitor 结构化 choice 通道内单个动作执行成功后即落逐动作 DISPOSITION 事件并提前收口信号，缩短「执行成功→落账」窗口；执行失败不得预写 resolved。

## Impact

- Affected specs: 无（新增能力 admin-orphan-disposition-effect-check）
- Affected code:
  - core/admin_monitor.py（孤儿收敛分支 + _worker 小步落账）
  - core/admin_store.py（补记用 append 形态处置事件写入支持）
  - tests/test_admin_orphan_disposition_effect_check.py（新增测试）

不改变回写门 fail-closed 语义（失败不得误记 resolved）；不改变人工 dashboard 通道的原子收口；不就地改写既有 pending/终态记录（补记一律 append）。