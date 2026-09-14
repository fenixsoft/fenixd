# scheduling-showcase（验证夹具骨架）

这是 fenixd **自身验证链**使用的夹具项目骨架 —— 仓内事实源（丢历史入库）。

## 它是什么

一个最小的 Fenixd 被管项目：8 个特定状态的 SPEC（`c-sched-set` / `c-sched-clear` /
`c-sched-done` / `c-frozen-a..e`），供 29 个 api/web/cli 验证场景消费（scheduling
开关、冻结/解冻、归档、预算、approve-push、hosting 生命周期等）。没有它，
这些场景会 404 unknown project / 无行可点，整轮 env 假失败（2026-09-06 实证）。

## 骨架 vs 运行时

- **骨架（本目录，入库）**：`scheduling_showcase/` 包、`tests/`、`pyproject.toml`、
  `.gitignore` —— 稳定资产，没有任何验证场景会写它们。
- **运行时（仓库外）**：`/root/scheduling-showcase`。验证场景会往夹具写
  `spec/changes/*`、`.fenix/STATE.md`、`.fenix/config.yaml`、`approve_push_request.json`
  等；`fix-supervisor-hosting-chain` 的场景还会在夹具里起真实 daemon。
  运行时**不能**落在 fenixd 跟踪路径内，否则每轮验证都会弄脏 fenixd 主树工作区。
- `.fenix/STATE.md` 与 `.fenix/config.yaml` 的基线不在此目录 —— 它们是
  `bin/fixture_scheduling_showcase.py` 的 `BASELINE_STATE` / `BASELINE_CONFIG`
  常量，由 `--reset` 写入（避免两份真源漂移）。

## 供给方式

`.fenix/verify.yaml` 的 prepare 步骤每轮验证前调用：

```bash
python3 bin/fixture_scheduling_showcase.py --reset
```

`--reset` 幂等：缺失的骨架资产从本目录 `copy2` 补齐（不覆盖既有），
`.fenix/` 与 `spec/changes/<name>/` 目录确保存在，`STATE.md`/`config.yaml`
写回基线（场景每轮会真实改写它们），并把项目登记进 dashboard registry。

## 为什么不带 git 历史

它原先是个独立 git 仓库。若带着 `.git` 作为 fenixd 子目录提交，git 会把它记成
gitlink（`160000`），克隆后是空壳 —— 于是改为丢历史、正文入库。
夹具 daemon 需要 git（worktree 管理），由 `--reset` 在运行时 `git init` 新建。
