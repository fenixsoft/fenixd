# 设计：推送步骤无远程环境预检短路

## 现状代码

- core/pm_engine/engine.py:3560 approve_push 主推送 _git_push_ref("main")，:3742 归档收口同款裸推；:3425 _git_push_ref 裸 git push origin <ref>，无 remote/分支存在性检查；:3910-3958 分支尽力推路径已有 remote 感知逻辑可参考；:3956 best-effort 同样解包 (bool, str) 二元组（第三调用方）。
- core/event_bus.py:529-570 _recover_done_push_retry 四重门（退避期、重试计数、终态标记、executor 挂载）——缺 approve_mode 门与 git 环境门；reporting.py:153 _is_push_backoffed 对零记账条目返回 False（零记账 done spec 每轮扫描被投递，dsh-plugins 四条目集体必败即此形态）。
- core/pm_engine/engine.py:3754-3845 _handle_push_failure 与 :3829-3839 退避配置守卫：None（缺键）已 DEBUG 静默（v0.1.4 实测 item 7 先例）、非 None 非法 WARNING；元素级非法（int 转换失败）静默回退——分级已存在，本 SPEC 仅测试锁定。
- core/config.py:2363 get_approve_mode 为现行审批语义读取点，**缺省回退 manual**（键缺失/非法均 manual）；done 时点判定 engine.py:2149 仅 approve_mode==auto 自动推；gates.require_push_approval 全库无读取点（死键，仅文档层面清理）。

## 设计要点

1. 预检单点：在 _git_push_ref 内做 git remote 与目标分支存在性检查（git remote / git rev-parse --verify）。**返回契约保持既有 (bool, str) 二元组不变**：no-remote/no-ref 时返回 (False, "[push_na:no-remote|no-ref] <原因>") 结构化标记，调用方按 error 标记前缀分流——二元契约下的既有测试打桩（MagicMock(return_value=(True, ""))）与各调用方解包零改动；调用方覆盖三处：approve_push（主推）、归档收口、_push_branch_best_effort（遇 N/A 标记按既有 best-effort 口径降级为 info 级跳过，不写 spec STATE 失败留痕）。
2. N/A 留痕：no-remote/no-ref 时推送结果记 push=N/A 并附原因（无远程/无目标分支）。**留痕落点为 entry 新增专用持久字段**（如 push_na + push_na_reason，字段化先例对齐 PUSH_BACKOFF_NEXT_RETRY_AT_FIELD 的 D3 双活约定），不走 error 字段（目标 1 明令不写 error，既有留痕通道主体即 error 字段——两者矛盾以此专用字段消解）；不触达 _handle_push_failure、不写退避记账。持久化目的：续推门读该字段即终局跳过，daemon 重启后零重投递（行为规格 6 幂等语义）。
3. 续推门序：_recover_done_push_retry 追加两道门（置于既有四重门之前短路，行为等价且省无效投递）——(a) approve_mode 门：get_approve_mode 生效 manual（含缺省回退）**且 spec 无推送记账**（push_attempts/退避字段双源皆缺）→ 跳过（零记账 done spec 未经人工批准，续推投递即绕过审批）；**有记账的 manual spec 不拦**——manual 项目唯一推送触发源是人工批准，有记账=已批准推送的退避重试，无差别拦之将回归 push-retry-recovery 动因场景（人工批准后推送失败滞留 done 需反复人工救回）；(b) N/A 终局门：entry 已含 N/A 持久标记 → 终局跳过（等价终态，不占退避计数，跨重启存活）。
4. 分支解析：新读推送目标分支（配置键优先，缺省 git symbolic-ref HEAD 探测当前分支），3505/3687 两处统一走该解析。
5. 配置分级：退避配置守卫区分「键不存在」（debug/静默，用默认）与「键存在但非法」（WARNING 回退），消除全量未配置项目的告警噪音。

## 风险与回退

- 预检引入额外 git 子进程调用：仅在推送路径触发，频次低，可接受。
- N/A 永久跳过与「将来配置 remote」的兼容：N/A 持久字段在配置变化后可由人工清除或随 spec 归档自然消失。
- 环境注入测试适配：_git_push_ref 内预检会使无 remote 的临时测试仓直接走 N/A 短路、不再执行 git push 子进程——既有环境注入用例（tests/test_spec_approve_push.py）的临时仓须补挂本地 bare remote（git remote add origin <tmp bare>）让预检放行，argv/env 断言方可持续有效。
