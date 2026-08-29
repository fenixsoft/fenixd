## ADDED Requirements

### Requirement: 主入口切换

dashboard 运行时访问 `/`(及 /index.html)serve v2/index.html;访问 /legacy.html serve 老版界面(功能完整,引原 app.js/style.css)。

#### Scenario: 新入口
- **WHEN** 访问 /
- **THEN** v2 界面渲染(AMIS 壳、概览页可用)

#### Scenario: 老版回退入口
- **WHEN** 访问 /legacy.html
- **THEN** 老版界面完整渲染,功能与切换前一致

### Requirement: 用户授权前置

执行切换前必须确认:v2-acceptance-suite 全绿、用户人工浏览通过、用户明确批准切换;三者缺一则停止执行并在 SPEC error 记录等待原因。

#### Scenario: 未授权不切换
- **WHEN** 用户尚未批准切换
- **THEN** 不修改 server.py,SPEC 保持未实施状态并说明原因

### Requirement: 切换后回归

切换提交后对 `/` 复跑核心冒烟(playwright),全部通过。

#### Scenario: 切换后复跑
- **WHEN** 切换完成并重启 dashboard
- **THEN** base-url 冒烟对 / 全绿
