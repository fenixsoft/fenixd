# code-fix 车道安全停车程序（manual_authorized 越权旁路陷阱）

- 日期：2026-11-22
- 类型：排查结论 / 操作程序
- 关联：`tests/conftest.py` basetemp 两层生命线（fenix-ignore 0d455012bcbe）；`_inbox/code-fix-stale-regression-mapping-disposition.md`

## 现象

2026-11-22 00:19 全量回归 907/11055 用例 setup 报同一 `FileNotFoundError: .fenix/pytest-basetemp`（共享根被外部删除、TempPathFactory 缓存不重建，单根因）。根因已于 14:19（f0ca50fad）由 conftest 生命线修复，但 code-fix 车道仍按台账 778 条逐一派批修复（12+ 批、16+ run），持续空转数小时。

## 关键机制（停车 MUST 知）

1. `admin.code_review_fix.enabled=false`（`.fenix/config.yaml`，30s 热更新）**拦不住 live 链**：手动触发的链在 `fix-progress.json` 持久化 `manual_authorized=true`，checkpoint 凭「链 live 且旗标为真」越过 enabled 总开关（core/code_fix.py checkpoint 守卫链）。
2. 批内定向重试循环派 run **不经 checkpoint**，无任何开关闸——只杀回归 pytest 会让 worker 以 parse_error 进入定向重试（阈值 2 次才熔断，首轮必空转一轮全量重试）。

## 安全停车程序（顺序敏感）

1. `systemctl stop fenixd-fenixd-f7f989.service`（连带杀掉 cgroup 内在飞 `claude -p` 与回归子进程；此时无任何派发面）。
2. daemon 停机窗口内改 `.fenix/config.yaml`：`code_review_fix.enabled: false`。
3. 同窗口改 `.fenix/code-review/fix-progress.json` 落终态：`running=false, phase=blocked, reason=disabled, manual_authorized=false, worktree/run_id/batch_total=null`（与 checkpoint disabled 分支终态同构；resume-watch 看护只认 `phase=failed` 拥堵特征，blocked 不触发）。
4. `systemctl start` 重启；核对：daemon 无 `claude -p` 子进程、progress 保持终态。

重开：config `enabled: true`（热更新 30s 生效）后手动重触发链。

## 遗留教训

根因修复落地 ≠ 台账清空：stale 条目会持续喂车道空转烧 token。根因类批量失败（单 error message 占 907/907）应先停车、修根因、再批量处置台账，而不是逐条派批。
