## Why

receiver 真机调试产物（dump-*.png 帧存 + receiver-<pid>.log）落在主树 .debug/，9 文件 51,250,165 字节 untracked 滞留约 44 小时，已触发 2 次 maintree_untracked_stray_stale（info）告警；按宽限管线滞留满 24 小时将升级 maintree_untracked_stray_escalated（major）并自动唤起 admin run 归档仍在使用的调试现场（上次同类处置实测 8.9 分钟/$1.51）。该目录每次真机调试都新增（10-11 单日 3 个会话各产 10~25MB），而散件判定（stray_wip.py _untracked_stray_entries）只把「无 ignore 规则命中」的路径计为散件——加一行 .gitignore 即从 info 告警与升级处置面整体免疫，属一行成本的前置免疫，无需等处置链兜底。（时点更正：2026-10-12 评审实测 .debug/ 目录已消失、注册表条目已自动复位，升级前提解除——本 SPEC 价值收敛为面向目录复发的前置免疫，详见 Impact。）

## What Changes

- `.gitignore` 追加 `.debug/` 条目（中文注释说明用途与落点成因，对齐既有 tailwind.gen.css 条目的注释风格——同为复发型散件产物 + 成因注释；评审更正：原引 build-win-configure.log 系 potplayer-base 仓案例，非本仓 .gitignore 条目）
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
- **生效即时**：git 层即刻生效；时点更正（2026-10-12 评审实测）：.debug/ 目录已消失、stray_untracked_registry.json 已为空 {}——原指纹 ff7ba470… 条目已按「指纹消失自动复位」（stray_wip.py _reset_untracked_registry_absent）清除，无需等待复位
- **时点更正**：major 升级（maintree_untracked_stray_escalated）倒计时前提已消失（原倒计时 2026-10-12 14:34:51 本地基于已复位的注册表条目，条目不存在则升级不可达）；本 SPEC 价值收敛为复发型产物前置免疫——receiver 下次真机调试将重建 .debug/，届时免告警免处置；若个别场景仍见历史告警，以既有 admin 裁决 ignore_untracked_stray 收口