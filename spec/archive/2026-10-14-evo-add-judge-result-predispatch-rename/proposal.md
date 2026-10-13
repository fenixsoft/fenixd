## 背景

2026-10-05 potplayer-base 项目 pack2-official-encoder 第 8 次裁决派发时，上一轮遗留的 .fenix/verify-progress/<spec>/.fenix-run-result.json 未清理，planner-judge 产物硬门（校验结果文件 mtime 必须晚于本轮启动-grace）将一个 exit 0、12 轮/$1.375 的正常裁决轮整轮作废，30 秒退避后重跑补位（$0.80/255s），作废轮成本脱离验证台账（tokens.json 无条目）。硬门工作正常（拦下陈旧文件、防旧结果污染裁决），缺口在上游：轮与轮之间不留痕上轮裁决产物，硬门以「作废整轮」的高价兜底。

## 问题

1. 裁决 run 派发前无预清理/改名逻辑：上轮结果文件残留即必触发硬门作废。
2. 硬门命中「陈旧残留」后的整体重跑路径也不清理陈旧文件，最坏可烧光 3 次原地重试预算（每次都是整轮 $1 级重跑）。

## 方案

run_planner（裁决派发单一收口点）在 mode="judge" 派发前，将已存在的 .fenix-run-result.json 原子改名为 prev-judge-result.json 留档（仿 core/pm_engine/family.py prev-impl-result.json 先例）；捆绑：硬门命中陈旧残留进入原地重试前同步改名陈旧文件，使再败归因退化为「结果文件缺失」并防烧光重试预算。

## 非目标

- 不走 is_resumed_worktree 豁免路线（会让陈旧文件被读侧当成本轮裁决，属历史 fail-open 事故模式）。
- 不触碰 report.json/tokens.json/scenarios 等跨轮累积产物；不改硬门 fail-closed 校验语义。
- 作废轮 usage 不入验证侧车台账（tokens.json）属另一观测缺口，不在本 spec 处理。