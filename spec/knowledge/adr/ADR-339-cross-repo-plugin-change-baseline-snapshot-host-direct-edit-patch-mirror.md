# ADR-339：跨仓插件变更交付形态=基线快照+宿主直改+补丁镜像

date: 2026-11-09
status: accepted

## Context

fenixd 侧对 dsh-plugins 宿主仓插件的变更（dashboard-bridge 等）存在交付通道矛盾：fenixd daemon 无按 SPEC 跨仓派发机制（dispatch `project_root` 是项目级参数），实现 Agent 对仓库外路径受声明面约束；宿主主树常驻未提交改动（已部署的既有工作区状态）。直接改动后 fenixd 仓内没有可评审交付物，改动与宿主未提交态混淆不可对账，用户日后在宿主 `git checkout/restore` 还会静默丢弃改动。

## Decision

跨仓插件变更的交付形态固定三段：①实施前把拟触达文件当前内容（含宿主未提交态）只读复制为基线快照，记录宿主 HEAD 与 `status --porcelain`；②实现 Agent 在宿主主树直改并走宿主部署链生效（宿主仓内不做任何 git 提交/回退操作）；③fenixd 仓侧交付物 = 基线快照 → 宿主改后状态的 unified diff 补丁镜像 + BASELINE.md（HEAD、快照清单、宿主未提交态与恢复备忘），随 SPEC 目录提交，可评审、守卫可对账。补丁以基线对比生成，宿主既有未提交改动不得回退、不得混入补丁。

## Consequences

改动即刻部署生效，且 fenixd 侧有可评审、可对账、可恢复的交付物；宿主未提交态与本变更的叠加风险由 BASELINE.md 显式化。代价：交付物是镜像而非活代码，fenixd 守卫不直接跑宿主测试（验证走宿主 vitest / build / 实拍链），补丁镜像与宿主现状存在漂移窗口（宿主后续改动不自动回流镜像）。后续触碰 dsh-plugins 宿主的 SPEC 沿用同形态，另立通道须显式新裁定。
