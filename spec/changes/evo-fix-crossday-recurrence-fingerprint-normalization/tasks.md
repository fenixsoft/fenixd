## Deliverables

```yaml
- path: core/admin_monitor.py
  kind: modify
- path: tests/test_crossday_recurrence_fingerprint.py
  kind: new
```

## 1. 指纹归一化补缺陷

- [ ] 1.1 core/admin_monitor.py：_normalize_error_message/_error_fingerprint（现约 :561-585）为「数字.数字+单位字母」形态增加归一规则（如 23.4s/5.3s 整体归一为占位符），使仅延迟数值不同的同形错误行指纹一致；非数值部分的差异仍须产出不同指纹
- [ ] 1.2 core/admin_monitor.py：对 api_timeout 类失败终态可选实现结构化签名路径（api_timeout 布尔 + stderr_tail 骨架）替代整行指纹；若实现，须与既有指纹空间命名空间隔离、不串扰 daemon_errors 第一维度判定

## 2. 跨日记忆跨重启可用

- [ ] 2.1 core/admin_monitor.py：_detect_crossday_recurrence（现约 :3081-3129）的指纹→上次失败时刻记忆持久化到 .fenix/ 下状态文件（原子写+锁，形态仿既有状态文件），daemon 启动时加载；文件缺失/损坏时降级为日志回退路径、不影响主扫描；持久化沿用既有内存淘汰语义（DAEMON_ERROR_FP_MEMORY_LIMIT 超限淘汰最早一半，admin_monitor.py:3121-3124）——淘汰后快照落盘，文件体量有界
- [ ] 2.2 core/admin_monitor.py：无持久化记忆时的回退对账从 256KB 尾读（_read_tail_error_entries，现约 :3257）改为定向检索：以本轮扫描得到的同签名最新时刻为锚，按「该时刻 − 24h ± 容差」构造窄时间窗（先按日期文件/行前缀缩小范围后 grep），检索能力覆盖至少 24h 回溯（非全窗扫描），并在 debug 日志留检索成本与命中痕迹

## 3. 测试

- [ ] 3.1 tests/test_crossday_recurrence_fingerprint.py：以 10-02/10-03 两夜真实死亡 ERROR 行形态构造样本（仅延迟数值不同），断言归一化后指纹相等且 _detect_crossday_recurrence 判定跨日同刻连发触发升级告警；构造非数值部分不同的样本，断言指纹不同不误聚
- [ ] 3.2 tests/test_crossday_recurrence_fingerprint.py：断言 daemon 重启场景（新实例从状态文件加载记忆）同刻连发仍可检出；断言状态文件缺失/损坏时降级到日志回退检索且主扫描不抛错