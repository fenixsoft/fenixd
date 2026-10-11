## Why

receiver 真机调试产物（dump-*.png 帧存 + receiver-<pid>.log）落在主树 .debug/，9 文件 51,250,165 字节 untracked 滞留约 44 小时，已触发 2 次 maintree_untracked_stray_stale（info）告警；按宽限管线滞留满 24 小时将升级 maintree_untracked_stray_escalated（major）并自动唤起 admin run 归档仍在使用的调试现场（上次同类处置实测 8.9 分钟/$1.51）。该目录每次真机调试都新增（10-11 单日 3 个会话各产 10~25MB），而散件判定（stray_wip.py _untracked_stray_entries）只把「无 ignore 规则命中」的路径计为散件——加一行 .gitignore 即从 info 告警与升级处置面整体免疫，属一行成本的前置免疫，无需等处置链兜底。

## What Changes

- `.gitignore` 追加 `.debug/` 条目（中文注释说明用途与落点成因，对齐既有 build-win-configure.log 条目的注释风格）
- 落地时以 git status --porcelain -uall 全表对照盘点：如存在第二个同类运行时产物目录一并追加（当前实测仓库内无第二标的，receiver 运行时产物目录 receive_data/ 在 Windows 目标机、不在仓库）
- 不移动、不删除 .debug/ 下任何现有文件

## Capabilities

### New Capabilities
- `receiver-debug-artifact-ignore`: 主树调试产物目录纳入 git ignore 面——check-ignore 命中、porcelain 零输出、散件巡检与升级处置面整体豁免

### Modified Capabilities

（无——spec/changes/ 与 spec/archive/ 均无 ignore/散件治理类既有能力）

## Impact

- **改动**：.gitignore 追加 1 行（含注释）；不动 .debug/ 下任何现有文件
- **零副作用**：ignore 只改 git 可见性，不影响接收器下次调试继续写该目录；磁盘占用不变
- **生效即时**：git 层即刻生效；散件指纹随下一轮盘点（daemon 300 秒周期）按「指纹消失自动复位」清除注册表条目
- **时点注意**：major 升级（maintree_untracked_stray_escalated）倒计时至 2026-10-12 14:34:51 本地——若实现先于该时点落地则升级自然解除；若已先触发，以既有 admin 裁决 ignore_untracked_stray 收口