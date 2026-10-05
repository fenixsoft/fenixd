## 设计

### 判定点

core/code_fix.py 的 checkpoint()（:2813）已有守卫块（:2935-3010）处理 switch_cooldown（冷却中 return {"triggered": False, "reason": "switch_cooldown"}）。在紧邻位置增加静默窗分支：

- 新增 _night_quiet_window() 辅助：读配置 night_quiet_window（点号键走与 :2646 相同的 config 访问路径），解析 "HH:MM-HH:MM"，用本地时间（time.localtime）判断当前是否在区间内；解析失败按无窗处理并 WARNING 一次（防配置错误静默吞掉）。
- 窗内：与冷却路径同样 return {"triggered": False, "reason": "night_quiet_window"}；首次进入武装时写武装告警（形态对齐 :2301），窗末首个放行触发写解除告警（对齐 :2341），evidence 含窗区间与下一可投递时刻。
- 与冷却共存：两者同时命中取更晚可投递时刻，各自独立武装/解除，互不复位。

### 配置

沿 _switch_cooldown_seconds（:2646）的既有模式：点号键 + 代码内缺省常量（缺省 "04:15-04:45"），不在模板强配（与冷却 300 秒缺省同策略）。

### 为什么不改三路触发点

_resubmit（:3369）、event_bus full-scan 兜底（core/event_bus.py:274）、持有者回调（:3643）最终都调 checkpoint()，入口单点判定即全覆盖；分散判定反而引入不一致。

### 风险

- 时钟/时区错配：测试用注入时钟覆盖四点边界（04:14:59 放行、04:15:00 拦截、04:44:59 拦截、04:45:00 放行）。
- 窗口消失后退化为每晚固定约 30 分钟不投递：武装/解除告警使其显性可见，配置一键关闭，属可接受代价。