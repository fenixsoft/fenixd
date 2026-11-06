# 蒸馏批 42 分钟=折叠积压税 + run 产物无内容观测缺口

日期：2026-11-06
类型：开放缺口（观测面 + 耗时治理）

## 现象

redesign-dashboard-v2-ui-mobile 归档触发的蒸馏批（2026-11-05 20:37–21:19 +08）耗时 42m48s；dashboard 运行明细里该 run 只有 2 行 heartbeat + 1 行摘要，看不到任何蒸馏内容，观感「什么都没输出」。

## 取证（daemon 日志 + git log 互证）

42 分钟的去向（单 worker 串行）：

| 段 | 耗时 |
| --- | --- |
| 折叠 settings-help-document-scroll-unify | 8m14s |
| 折叠 settings-menu-renamed-config-1105 | 5m29s |
| 折叠 systemd-hosted-daemon-path-missing-local-bin | 7m16s |
| 折叠 zn-inbox-entry-1（计数夹具，129B） | 4m57s |
| 折叠 zn-inbox-entry-2（计数夹具） | 5m08s |
| 折叠 zn-inbox-entry-3（计数夹具） | 2m03s |
| **当轮蒸馏 redesign-dashboard-v2-ui-mobile** | **~9m40s** |

- 折叠积压占 33m08s ≈ 78%；纯单 spec 蒸馏约 10 分钟。42 分钟不是该 spec 的蒸馏成本，是 `_inbox/` 积压折叠税（add-knowledge-inbox-pipeline 前置折叠段语义）。
- 蒸馏有真实产出：主提交 25737d58d 新增 ADR `breakpoint-single-source-container-level-branch.md` + `dashboard-frontend/v2-commercial-ui.md` 规则更新（+23/-4）+ index/_domain/log 同步；另有 6 个 fold 提交（f929329aa…9ae0ffa41）。

## 根因

1. **无输出观感 = 观测面缺口**：add-distill-run-artifacts 的合成事件流按设计只记 started/heartbeat/round/result；result 行仅含 commit hash + folded 计数，不含改动文件清单或内容摘要。dashboard 读侧（runs.py 事件窗）无从呈现「蒸馏了什么」。蒸馏内容与 run 观测面断裂。
2. **耗时 = 折叠税**：积压条目逐条完整子 run（spawn+读归档+改页+校验+提交，2–8 分钟/条），与当轮蒸馏串行；zn 计数夹具（空折叠、原样搬 done）也烧完整子 run，3 条夹具 ≈ 12 分钟。

## 伴生噪音（同窗取证）

- 每个折叠提交均伴随 WARNING「改动含 run 前基线已有路径…请人工核查: spec/knowledge/_inbox/zn-inbox-ent…」——zn 夹具长期 untracked 常驻工作区，每个折叠提交都触发一次误报性告警。
- run 自写的 `spec/knowledge/log.md` 折叠叙事有重复行（systemd-hosted、zn-entry-1 各两条），与 git 一提交一条的事实不符；权威记录以 git 为准。

## 建议方向（供立项裁量）

1. 蒸馏 result 行追加改动文件清单（pathspec diff 摘要），dashboard 运行明细即可展示蒸馏内容——低成本高收益。
2. zn 计数夹具（README 声明的空夹具）在折叠前置段派发侧短路：直接搬 done + 记日志，不 spawn 子 run。
3. 折叠积压大时批次耗时线性膨胀（11-06 已又积 5 条）；可考虑积压折叠与当轮蒸馏解耦或并行度治理。
4. 「run 前基线已有路径」WARNING 对 `_inbox/` 已知夹具降噪。
