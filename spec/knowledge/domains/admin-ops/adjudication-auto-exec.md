# 裁决告警推荐项分级自动执行

<!-- knowledge: capability=adjudication-auto-exec rev=1
     sources=spec/changes/add-adjudication-auto-exec -->

链终点 pending 升级告警的推荐项分级自动执行策略引擎（daemon 侧）：在「arbiter 有明确推荐 + 推荐为可逆自限动作 + 判据齐备」时，grace 否决窗到点自动执行推荐 choice，压缩「机器已有答案、等人点击」的决策就绪后空转段；链序不变，只改变链终点（人工出口）在可逆推荐场景下的等待语义。

## 规则

- 触发面为链终点产生的 pending 升级告警（ESCALATION）。策略引擎为 daemon 侧独立模块，60 秒轻量扫描环（文件读 + 内存判据），与 STATE 写权威同侧、不随 dashboard 独立重启失联。
- 自动执行判据四条 MUST 全部满足，任一不满足跳过本轮并记录日志，不得部分执行：
  1. 告警关联 arbiter 完整调查 ≥1 次且推荐明确——推荐 choice 由告警 `choices[]` 注册 id 对 `recommended_action` 文本做正向提及机械解析：否定语境（「不推荐/不选/勿选/不作为」等就近修饰）不计正向，否定词与提及之间允许隔同级选项列表（「不推荐 A/B」对 B 同样构成否定修饰）；唯一正向命中方视为明确，零命中或多义命中一律判不明确、跳过等人工（宁跳过勿误执行）。
  2. 推荐 choice 的 `risk_tier=reversible-experiment`（档位经注册表单源解析，缺档按 terminal 兜底永不自动执行）。
  3. 同 SPEC 无共存更高风险档 pending 告警（severity 更高，或选项集最高档更高——任一命中即冲突，让人工一并裁决）。
  4. 本 SPEC 连续自动执行计数低于上限（缺省 2）。
- grace 否决窗：缺省 30 分钟；到期时刻 = 推荐可用时刻 + grace_minutes，读时计算、状态不落盘。推荐可用时刻取告警 `arbiter_upgrade.upgraded_at`（arbiter 调查完成、推荐落账时刻；告警创建与推荐落账异步，锚 `created` 会使异步升级件否决窗归零），无 upgrade 痕回退告警 `created`。窗内人工处置（resolve 任一 choice 或标记已处理）先到先得；引擎执行前瞬时重读 handled 与判据二次确认。
- 执行复用既有 choice 执行单机器（`execute_choice_for_disposition`——人工 alert-resolve、admin 直接路径、链 closed 出口之外的第四同源处，禁止为自动执行复制分支逻辑）：DISPOSITION 处置留痕与人工点击同构，仅 `actor=auto-policy` 并附触发告警 id；执行成功闭环告警（handled_by=auto-policy），执行失败不闭环、保持 pending 等人工。
- 连续自动执行计数从处置留痕按 actor 派生（零新增状态文件）：从最新留痕向前数 actor=auto-policy 连续段；aging-watch 与 pending 在飞记录中性跳过（不误计不误重置），人工/链出口留痕（无 actor）中断计数。达上限转纯人工等待；cap 放宽或人工留痕落地后计数自然重置恢复。
- human-only 两档（`state-advance`/`terminal`）MUST NOT 自动执行；引擎扫描时对 pending 超老化阈值（缺省 2h warning / 6h critical）的此类告警写升级活动记录（actor=aging-watch，只做可见性提升、不改变处置语义），同告警同档去重、warning→critical 随老化递进；可逆档由 grace 窗语义负责、不写老化记录。
- 开关与降级：`auto_exec.enabled` 缺省 true，false 时引擎零动作零噪音（回退纯人工语义）；引擎构造/启动异常在 daemon 装配处捕获降级为 None，引擎缺位不阻塞其他车道。fail-open 纪律：单告警判定异常单条捕获隔离、同轮其余告警照常；存储读失败整轮放弃；任何异常不上抛。
- 阈值单源 `ConfigLoader.get_auto_exec_config`（cap=2、grace=30 分钟、老化 120/360 分钟），`auto_exec` 配置段热更新生效。
- 告警读面投影：ESCALATION 行读时附 `auto_exec` 投影（executed 徽标键=handled_by=auto-policy、recommended_choice/risk_tier、anchor_at/due_at 倒计时）；前端「自动执行」徽标独立于人工闭环「已收口」绿标并存，grace 倒计时仅可逆档且推荐明确的 pending 件渲染——自动执行可见不静默。

## 关键行为

- 扫描环 60 秒一轮；首轮先睡一个间隔（避让 daemon 启动风暴，grace 判定基于稳定读数）；重复 start 复用存活线程；stop 有界 join 不阻塞 daemon 关停。
- 单轮扫描返回实际自动执行次数（供测试断言/手动触发）。

## 代码锚点

- 主实现：`core/admin_auto_exec.py`（AdminAutoExecEngine 扫描环、判据与推荐解析、老化升级、auto_exec_projection 读侧投影）
- 装配点：`fenixd.py`（daemon 装配构造 + start，异常降级 None；shutdown 收口）
- 单源符号：`core/config.py:get_auto_exec_config`（cap/grace/aging 阈值与 enabled 开关）、`core/admin_choice_exec.py:execute_choice_for_disposition`（执行单机器）
- 消费方：`core/dashboard/data/admin_alerts.py`（ESCALATION 行读时合并 auto_exec 投影）
- 守卫测试：`tests/test_admin_auto_exec_policy.py`

## 溯源

- 2026-11-11 add-adjudication-auto-exec（spec/changes/add-adjudication-auto-exec/） — 新增本页：四判据（调查痕/唯一正向提及推荐/可逆档/无共存更高档+连续 cap）、grace 否决窗锚推荐可用时刻读时计算、执行复用单机器第四同源处（actor=auto-policy 同构留痕）、human-only 老化升级、auto_exec.enabled 开关与 fail-open 降级、告警读面 auto_exec 投影
