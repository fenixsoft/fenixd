# Proposal: worktree 创建重名换名重试

## 问题背景

就绪态并行出题（planner-plan）与实现派发同秒触发时，两车道各自按 int(time.time()) 生成同名分支与 worktree 路径（core/worktree_manager/lifecycle.py:173-184），后到者 worktree add -b 必败（fatal: a branch named … already exists）。失败分支无重名识别、直接放弃（:212-219），只能靠 runner 层 attempt 循环 sleep 5 秒后换新时间戳自愈——每次白烧 1/3 attempt 配额、约 5 秒延迟，并重复拉起一套 worktree 供给链（node_modules provision、dev-server、route-map 生成）。当前日志窗口已实测 5 组同签名事故（2026-09-22 一组、09-23 四组），并行出题默认开启（verify.parallel_planning=True）使触发面为常态路径；既有双派发锁（S2）按 spec:agent_type 分键，天然不覆盖跨 agent_type 命名冲突。

## 方案概述

在 lifecycle.create 的 worktree add -b 失败分支捕获 already exists 后就地换名重试：

1. stderr 含 already exists 时，取 timestamp = max(int(time.time()), 原值 + 1) 重建分支名与 worktree 路径（路径与分支同名双换——事故现场胜者已占用原路径），重发 git worktree add -b，有界重试 2-3 次。
2. 分支名末段保持纯数字时间戳，queries 层全部解析契约不变。
3. 重试全程持有原锁并落一条含新旧分支名的 WARNING；重试耗尽仍失败则沿用现状语义（discard 锁、返回 None），runner 层 attempt 兜底不变。

## 影响范围

- 修改 core/worktree_manager/lifecycle.py：create 失败分支换名重试
- 修改 tests/test_dual_dispatch_and_freeze.py：新增跨 agent_type 同秒 create 用例

## 非目标

- 不改分支命名公式、不掺 uuid/attempt 字符串——「末段纯数字」是 queries.py 多处 rsplit+isdigit 的显式解析契约，掺非数字后缀会静默打断恢复/推送/遗产认领链。
- 不做同名分支复用主修——胜者 create 成功即注册挂载，「无挂载同名分支」窗口极窄且有 TOCTOU，且复用会纠缠两车道 merge-back 语义（孤儿分支场景已部分被 legacy/resume 机制覆盖）。
