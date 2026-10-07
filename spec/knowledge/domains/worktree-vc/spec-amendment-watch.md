# 主树 spec 目录在飞修订探测与预警

<!-- knowledge: capability=spec-amendment-watch rev=1
     sources=spec/archive/2026-10-08-evo-inflight-spec-amendment-watch -->

实现分支在飞期间对主树 spec/changes/<spec>/ 已提交修订的早期探测与预警：修订落地后一个扫描周期内浮出，merge-back 相撞转 repair 时上下文自带根因；告警是唯一反馈面，不改变任何 merge 决策。

## 规则

### 检测判定（两入口单源）

- 判定「spec/changes/<spec>/ 相对 merge-base 在主树出现新已提交修订」收口单一模块级函数 `core.worktree_manager.mergeback.detect_spec_amended_inflight`：`git merge-base HEAD <branch>` 求分叉点，`git log <merge-base>..HEAD -- spec/changes/<spec>/` 非空即命中，命中返回修订提交短哈希列表（时间正序）。merge-back 主链与 admin_monitor 周期扫描两入口共用同一判定（admin_monitor 侧延迟导入防装载环），MUST NOT 出现第二套同语义判定。
- 检测纯只读（不触碰工作区、不写任何状态）；实现分支不存在（已合回清理）、merge-base 失败、git 命令失败或超时一律返回空列表静默跳过——不报错、不产信号、主链照常。
- 分支名以 run/spec 记录的 branch 锚点为准，不自行猜测命名规则；周期扫描入口只对在飞实现 spec 检测（状态 implementing + 分支锚点在案 + run 文件写活动在宽限窗内或 worktree agent 进程存活），run 不在飞不检测不告警。

### 告警与指纹去重

- 命中发 `spec_amendment_inflight` 告警（severity=major）：内容含修订提交短哈希列表、受影响在飞分支与「merge-back 将相撞」预警；kind 注册进 admin_monitor 级别/处方表，并属入库信号类型——merge-back 侧直写 store 的记录同样由监视器摄取唤起 Administrator。
- 告警指纹 = spec + 修订提交集合（`spec_amendment_fingerprint`，对提交顺序不敏感）：同一提交集合不重复成条（不逐扫描周期轰炸）；主树又落新修订即提交集变化产生新指纹，允许再次成条作相撞风险升级提醒。两入口共用同一指纹函数。
- merge-back 侧对同 spec 同指纹的未消费（未 handled、未 escalated）在途信号跳过重复写入——merge-back 会被周期复查车道按固定节拍反复触发，不去重会逐轮轰炸；信号写入异常只记 warning，不影响 merge-back 判定。
- 周期入口的指纹备忘在信号未送达时回滚（节流/冻结/夹具抑制/在飞互斥/落库拒写任一守卫命中即丢弃本次唤起）：冷却过期后同一修订集合仍可再次成条，MUST NOT 出现「已记为已告警却未送达」的漏报。
- 处置处方指向「等实现收尾后在分支上补齐同一修订（merge main 或手工同步），或 merge-back 相撞后经 repair 车道把 main 合入分支；勿在主树侧继续叠加修订加剧分叉」；merge-back 直写记录的内联处方与 admin_monitor 处方表同文，文案变更须两处同步。

### merge-back 接入与根因透传

- 检测挂 merge-back 闸门序列头部（预演闸之前）：命中只发告警并把修订提交列表附着 `MergeConflictInfo.amended_inflight`（字段缺省空列表，既有构造点零破坏）；预演直通 repair 之外的路径（成功/真失败）同样携带该字段供观测，不改判定。
- 检测命中 MUST NOT 顺延或中止 merge-back、MUST NOT 计入 merge 熔断记账（_merge_fp/_merge_streak）；冲突结局确定性不变——相撞仍由预演检出并按既有 rehearsed 链路转 repair。
- 预演检出 spec 目录语义冲突直通 repair 时，amended_inflight 透传进 repair 派发上下文（conflict_summary.amended_inflight），prompt_builder 据此增补「主树在飞修订根因」段（含修订提交列表），repair 无须自行考古；无修订时根因段不注入，repair prompt 逐字节不变。

### 反馈面边界

- 告警是唯一反馈面：不做修订自动改道实现分支、不向在飞 run 推送任务清单变更通知、不对框架外提交者做强制拦截（git 直提无法拦截）。

## 溯源

- 2026-10-08 evo-inflight-spec-amendment-watch（spec/archive/2026-10-08-evo-inflight-spec-amendment-watch） — 新建本页：merge-back 主链与 admin_monitor 周期扫描双入口共用单源检测与指纹、spec_amendment_inflight major 告警（直写+摄取双通路、在途去重与未送达指纹回滚）、amended_inflight 情报附着与 rehearsed 直通 repair 根因透传、观察型边界（不改 merge 结局/不入熔断/告警唯一反馈面）
