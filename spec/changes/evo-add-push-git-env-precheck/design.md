# 设计：推送步骤无远程环境预检短路

## 现状代码

- core/pm_engine/engine.py:3505 approve_push 主推送 _git_push_ref("main")，:3687 归档收口同款裸推；:3392 _git_push_ref 裸 git push origin <ref>，无 remote/分支存在性检查；:3867-3890 分支尽力推路径已有 remote 感知逻辑可参考。
- core/event_bus.py:481-556 _recover_done_push_retry 四重门（退避期、重试计数、终态标记、executor 挂载）——缺 approve_mode 门与 git 环境门。
- core/pm_engine/engine.py:3698-3767 _handle_push_failure 与 :3745-3748 退避配置守卫：缺键与非法同门槛触发 WARNING。
- core/config.py:2314 get_approve_mode 为现行审批语义读取点；gates.require_push_approval 全库无读取点（死键，仅文档层面清理）。

## 设计要点

1. 预检单点：在 _git_push_ref 内做 git remote 与目标分支存在性检查（git remote / git rev-parse --verify），返回结构化结果（ok / no-remote / no-ref），调用方按结果分流——所有调用方（approve_push、归档收口、续推）自动继承。
2. N/A 留痕：no-remote/no-ref 时推送结果记 push=N/A 并附原因（无远程/无目标分支），走既有留痕通道，不触达 _handle_push_failure。
3. 续推门序：_recover_done_push_retry 在既有四重门后追加两道——get_approve_mode==manual 直接跳过；预检判为 no-remote 时写 N/A 留痕并永久跳过该 spec（等价终态，不占退避计数）。
4. 分支解析：新读推送目标分支（配置键优先，缺省 git symbolic-ref HEAD 探测当前分支），3505/3687 两处统一走该解析。
5. 配置分级：退避配置守卫区分「键不存在」（debug/静默，用默认）与「键存在但非法」（WARNING 回退），消除全量未配置项目的告警噪音。

## 风险与回退

- 预检引入额外 git 子进程调用：仅在推送路径触发，频次低，可接受。
- N/A 永久跳过与「将来配置 remote」的兼容：N/A 留痕在配置变化后可由人工清除或随 spec 归档自然消失。
