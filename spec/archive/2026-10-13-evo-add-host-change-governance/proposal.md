## 背景

2026-10-05 potplayer-base 项目 pack2-official-encoder 实现者为救模拟器相机验证场景，对宿主内核模块 v4l2loopback 打补丁并以 dirty 版（e27cd86-dirty）cp 覆盖 updates/dkms 正版，全程零备份；管理员诊断出疑似 fallthrough 缺陷、写好的 pristine 重建+重载修复计划随 run 被 600 轮击杀而未执行，dirty 模块至今仍加载。核查另发现影子副本遗留在 /lib/modules/…/extra/ 与 /tmp/v4l2loopback-src，dkms status 的 built/installed 不一致 WARNING 与 modinfo -dirty 后缀可作巡检锚点。

## 问题

1. 实现者提示词对宿主系统级变更（内核模块/dkms/系统包/设备节点）无「先备份、须登记、失败留回滚指引」约束。
2. run 失败终态时已登记的宿主变更无自动下游——修复义务随 run 击杀丢失，只能靠人工巡检偶发发现。

## 方案

- implementer/administrator 提示词立规：宿主系统级变更 MUST 先备份原版本（路径+版本+加载参数）并**在变更发生时即时写入宿主变更登记文件**（收尾在 run 结果汇总，两处一致）；收工时变更仍在位 MUST 附回滚指引，能用户态解决的优先用户态。
- 框架在 run 终态为失败（含击杀类无 run-result 终止）且存在宿主变更登记时，由 runner 终态记录点读取登记文件，自动向 admin 告警通道派发「回滚义务」告警；回滚执行交维护者/admin 人工裁决。

## 非目标

- 不做框架自动回滚执行器（自动 rmmod/depmod/modprobe 在共享宿主上属越权高危：run 前基线不可靠判定、EBUSY 误伤并发 run、回滚自身失败无兜底）。
- dirty v4l2loopback 的立即修复（用 /var/lib/dkms 下在位的 pristine 0.12.7 构建产物恢复 updates/dkms，清理 extra/ 影子副本与 /tmp 源码树，depmod+重载并还原实验加载参数）属运维动作，由维护者执行，不入本 spec。