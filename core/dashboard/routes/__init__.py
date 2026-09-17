"""core.dashboard.routes — Dashboard 路由子包（refactor-giant-classes D1/D3/D5/D6）。

各组方法按资源拆分为 mixin，DashboardHandler 继承它们（D5：MRO 中
资源组须排在 BaseHTTPRequestHandler 之前）。门面 re-export 全部公开名。
"""
