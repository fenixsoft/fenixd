# 调试产物目录 ignore 豁免

<!-- knowledge: capability=receiver-debug-artifact-ignore rev=1
     sources=spec/archive/2026-10-30-evo-ignore-receiver-debug-artifacts -->

receiver 真机调试产物目录（`.debug/`：dump-*.png 帧存 + receiver-<pid>.log）的 git ignore 前置免疫——一行目录级条目使其从散件告警与升级处置面整体消失，且不影响调试会话继续写入。

## 规则

- **目录级 ignore 条目**：`.gitignore` 包含 `.debug/` 目录条目（目录级一条而非逐文件 glob——会话子目录与文件名都是动态形态，目录级覆盖全部未来会话；含中文注释说明为 receiver 真机调试帧存/日志落点与成因，对齐既有复发型产物条目的注释风格）；`git check-ignore` 命中该条目，`git status --porcelain -uall` 对其零输出。
- **散件巡检面整体免疫**：散件判定只把「无 ignore 规则命中」的路径计为散件——`.debug/` 下路径被 ignore 命中后不计散件，`maintree_untracked_stray_stale`（info）告警与第二档升级 `maintree_untracked_stray_escalated`（major，自动唤起 admin 归档仍在使用的调试现场）均不可达；目录复发后经盘点不产生注册表新条目。
- **已先触发的收口**：major 升级告警在 ignore 落地前已触发的场景，以既有 admin 裁决 `ignore_untracked_stray` 收口并在处置记录注明，不重复建设。
- **指纹消失自动复位**：目录消失后注册表条目按既有「指纹消失自动复位」模式清除，升级倒计时前提随之解除，无需手工清理。
- **现场零扰动**：不移动、不重命名、不删除 `.debug/` 下任何现有文件，不影响接收器后续调试会话继续写入该目录；不为验证而重建该目录。ignore 只改 git 可见性，磁盘占用与写入行为不变。

## 关键行为

同类「复发型运行时产物 + 目录级 ignore + 成因注释」是散件前置免疫的标准形态；新型产物目录的系统性预防见 [stray-first-sight-prevention](stray-first-sight-prevention.md)（首现即提示预防性 ignore 草案）。

## 溯源

- 2026-10-30 evo-ignore-receiver-debug-artifacts（spec/archive/2026-10-30-evo-ignore-receiver-debug-artifacts） — 新增本能力：.debug/ 目录级 ignore 豁免（check-ignore 命中、porcelain 零输出、info 告警与 major 升级处置面整体免疫、现场零扰动）（动因实测：调试产物 9 文件约 51MB untracked 滞留 44 小时触发 2 次 info 告警，按宽限管线将升级 major 并自动唤起 admin 归档仍在用的调试现场）
