# ADR-321：arbiter 禁立项红线，框架缺口 todo.md 单一出口

date: 2026-11-03
status: accepted

## Context

arbiter 车道原设自动立项通道：消费调查报告 proposals 数组物化 drafted SPEC，配「单轮上限/周配额/查重」三限节流治理提案质量。框架缺口（裁决注册表、升级竞态等机制面缺陷）的修复成文需要设计与产品面裁量，调查报告的取证粒度天然不足以成文，立项产出必然是占位草案闯 spec-review 评审硬门——2026-11-03 连续两例被两轮否决冻结，证明提案质量治理三层补丁（晋升守卫/查重扩展/前提实测）治标不治本：出口不关，占位草案持续再生。用户定调车道边界：arbiter 只修 SPEC 问题，不修框架缺口。

## Decision

arbiter 处置动作面以 SPEC 问题为界，禁立项为权限红线：不创建、不注册任何 SPEC（无 `spec/changes` 目录物化、无 STATE 条目写入），立项写点/目录物化/节流三限整体退役且不留 config 开关——红线是车道边界，不是可调行为。框架缺口发现的出口唯一：调查报告 `gaps` 数组逐条按「可直接起草 SPEC」粒度上报（topic/evidence/impact/candidates），框架消费端记入 `.fenix/todo.md` 自省队列（复用 todo_format 结构契约与 fs_utils 锁单源，来源标记 arbiter+触发签名+run_id），由自进化车道既有 todo 消费机制统一评估立项；台账 kind 演进 `gap-noted`（append-only 存量保留），切换窗旧 prompt run 的 proposals 字段按未知字段容错（WARNING 台账后丢弃，不落池不抛异常）。既有白名单处置动作面（解冻/重验/载荷落地/陈锁清扫/分拣提交）不受红线扰动。后续扩 arbiter 动作面不得含立项，为框架缺口另立直接立项出口须显式 supersede 本裁定。

## Consequences

框架缺口从发现到立项隔一层 todo 异步队列（自进化车道按自身节律消费），非即时闭环；报告 schema 与消费端同 commit 切换、无双字段过渡态（arbiter run 无记忆、由 daemon 派发，重启即生效），切换窗在飞旧 run 的缺口发现仅存台账留痕可人工捞；todo 侧轻量同主题去重宁轻勿重，误跳靠台账人工补记、重复靠自省合并兜底；立项质量治理面（晋升守卫、提案查重、节流配额）随出口关闭整体消失，不再维护。
