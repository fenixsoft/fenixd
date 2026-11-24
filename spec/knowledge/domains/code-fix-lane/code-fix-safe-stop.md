# code-fix 链安全停车

<!-- knowledge: capability=code-fix-safe-stop rev=1
     sources=spec/knowledge/_inbox/done/code-fix-lane-safe-stop-procedure.md -->

code-fix 链需人工强制停止时的开关失效面判别、顺序敏感停车程序与根因类批量失败下的台账处置纪律。

## 规则

### 开关失效面（停车前 MUST 知）

- `admin.code_review_fix.enabled=false`（30s 热更新）拦不住 live 链：手动触发的链在 fix-progress.json 持久化 `manual_authorized=true`，checkpoint 凭「链 live 且旗标为真」越过 enabled 总开关继续投递（整链授权语义见 [code-fix-manual-trigger](code-fix-manual-trigger.md)）。
- 批内定向重试循环派 run 不经 checkpoint、无任何开关闸：只杀回归 pytest 会让 worker 以 parse_error 进入定向重试，阈值 2 次才熔断，首轮必空转一轮全量重试。

### 安全停车程序（顺序敏感）

1. `systemctl stop <fenixd 单元>`（实例名形如 `fenixd-fenixd-f7f989.service`）：连带杀掉 cgroup 内在飞 `claude -p` 与回归子进程，此时无任何派发面。
2. daemon 停机窗口内改 `.fenix/config.yaml`：`code_review_fix.enabled: false`。
3. 同窗口改 `.fenix/code-review/fix-progress.json` 落终态：`running=false`、`phase=blocked`、`reason=disabled`、`manual_authorized=false`、`worktree`/`run_id`/`batch_total` 置 null（与 checkpoint disabled 分支终态同构）；恢复看护只认 `phase=failed` 拥堵特征，`blocked` 不触发恢复重派。
4. `systemctl start` 重启；核对 daemon 无 `claude -p` 子进程、progress 保持终态。

重开：config `enabled: true`（热更新 30s 生效）后手动重触发链。

### 台账空转处置纪律

- 根因修复落地不等于台账清空：台账 stale 条目会持续喂车道空转烧 token。
- 根因类批量失败（单一 error message 占绝大多数）的处置顺序是先停车、修根因、再批量处置台账，不逐条派批。

## 代码锚点

- 主实现：`core/code_fix.py`（checkpoint 守卫链、`manual_authorized` 随链持久化与终态清除、disabled 分支终态形态）
- 消费方：`core/dashboard/data/code_review.py`（fix-progress 快照读侧呈现）

## 溯源

- 2026-11-24 code-fix-lane-safe-stop-procedure（spec/knowledge/_inbox/done/code-fix-lane-safe-stop-procedure.md） — 折叠 2026-11-22 basetemp 共享根被删致 907 失败台账空转的停车结论：enabled 与定向重试两条开关失效面、顺序敏感四步停车程序与 fix-progress 终态字段形态、根因类批量失败的台账处置纪律
