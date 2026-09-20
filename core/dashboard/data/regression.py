"""regression.py — Dashboard 回归读取器（add-test-regression-tab）。

纯读侧封装：把 ``core.regression.read_result`` 转导为 Dashboard 端点友好形态。
写路径（触发信号）由 routes 层直接写 ``.fenix/regression_request.json``
（对齐 code-review 的「dashboard 原子写 → daemon 主循环消费」范式），
本模块不承载写逻辑。

结果快照降级（读侧契约）：快照缺失 → ``{status: "never_run"}``；损坏 →
``{status: "parse_error", reason}``（MUST NOT 因快照问题抛 500）。
「运行中」标记同步透出（task 5.6 判据：分面以服务端 ``running`` 字段判定
运行态，MUST NOT 依赖前端本地计时——回归可跑 1800s，跨刷新后本地态
丢失会让分面回落到「上次结果」）。never_run/parse_error 降级结果合并
running 字段：分面轮询期间运行中态始终可见。
"""

from core.regression import read_result, is_regression_running  # noqa: F401


def read_regression_result(project_root) -> dict:
    """读取 ``.fenix/regression/last-run.json`` 快照（结构化 dict）。

    直接透传 core.regression.read_result 的结果（含 never_run/parse_error
    降级），并附加 ``running`` 字段（marker 新鲜度判定，见 task 5.6）。
    读侧 MUST NOT 因快照问题抛异常——路由层据此 200 返回而非 500。
    """
    result = read_result(project_root)
    if not isinstance(result, dict):
        result = {"status": "parse_error", "reason": "快照非对象"}
    # never_run/parse_error 同样透出运行中态（触发后、快照未写盘窗口内）
    try:
        result["running"] = bool(is_regression_running(project_root))
    except Exception:
        result["running"] = False
    return result