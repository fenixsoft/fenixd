## Context

receiver 真机调试产物落主树 .debug/（10-11 单日 3 会话、9 文件 51.25MB），未入 ignore 面已两度触发 maintree_untracked_stray_stale（info）告警，stray_untracked_registry.json 中 ff7ba470… 条目 escalated_at=2026-10-11T07:04:57Z、24 小时点（10-12 14:34:51 本地）将发 major 并自动唤起 admin run。机制关键事实：散件判定只认「无 ignore 规则命中」（stray_wip.py:676 porcelain -uall 不列 ignored、:692-693 仅无规则命中路径计入），gitignore 豁免即全链免疫且指纹消失自动复位。.gitignore 现有 30 行，末条为先例 151ff6e（build-win-configure.log）。receiver 真机运行时产物目录 receive_data/ 在 Windows 目标机、不在仓库，仓库内无第二标的。

## Goals / Non-Goals

**Goals:**
- .debug/ 整目录纳入 ignore 面，info 告警与升级处置双双不可达
- 注册表指纹随下一轮盘点自动复位，零手工清理
- 现场零扰动：不动任何现有调试文件

**Non-Goals:**
- 不清理/归档/移动 .debug/ 现有文件（那是处置链的事）
- 不建通用「运行时产物 ignore playbook」（tracked 散件根治已由框架 evo-recurring-stray-remediation 覆盖）
- 不改散件管线代码与阈值

## Decisions

### D1 目录级 .debug/ 条目而非逐文件 glob
会话子目录（1/2/3）与文件名（dump-*、receiver-<pid>）都是动态形态，目录级一条覆盖全部未来会话，且注释可写明成因。

### D2 前置免疫而非等处置链
散件管线的升级路径会归档仍在使用的调试现场；一行 ignore 让告警与升级根本不产生，优于事后裁决。若 major 已先触发，用既有 admin 裁决 ignore_untracked_stray 收口，不重复建设。

### D3 注释对齐既有先例风格
.gitignore 末条 151ff6e（build-win-configure.log）带中文注释说明「复发型产物」，新条目同风格，保留「为什么在这里」的上下文。