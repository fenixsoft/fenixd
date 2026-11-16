## Why

出题产物扩场景 kind 集与契约段位无同步校验，缺口要到实现合并消费期才被静态门拦下：2026-11-11 web-browser-client 13:46:58.999Z 打回（场景执行数 0），1 个 admin run（857.21s/128 轮）代起草 serve/ready，验证推迟约 13 分钟；该族缺口 4 天三度（11-08 模板态、11-09 regression 段、11-11 serve 段）。交叉规则本体已存在（serve_missing_for_scenario_kinds，scenario_static_check.py:662）却只挂在消费期两点（pipeline.py:3370/:3568），写盘/验收路径对契约零感知，周期预检只查模板态。

## What

出题产物写盘与验收点按 kind 集调用既有交叉规则前置校验，命中即出单条 verify_contract_missing 信号（实现期 info 一次性）并携带定向补段情报；不阻断落盘、不触发 replan，消费期门保留为最后防线。

## Goals

kind 集扩容与契约段位的同步缺口在出题轮内暴露（实现期即可安排补段），不再等消费期打回消耗 admin run 与验证时延。