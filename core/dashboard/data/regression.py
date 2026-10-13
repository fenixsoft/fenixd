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

from core.regression import (
    is_regression_running,
    read_progress,
    read_result,
)


def read_regression_result(project_root) -> dict:
    """读取 ``.fenix/regression/last-run.json`` 快照（结构化 dict）。

    直接透传 core.regression.read_result 的结果（含 never_run/parse_error
    降级），并附加 ``running`` 字段（marker 新鲜度判定，见 task 5.6）。
    读侧 MUST NOT 因快照问题抛异常——路由层据此 200 返回而非 500。
    运行中（running=True）附加 ``progress``（read_progress：终端真实标记 /
    耗时估算 / 未知三级口径），供分面渲染执行进度条。
    """
    try:
        result = read_result(project_root)
    except Exception as e:
        # 读侧 MUST NOT 抛（code-review item d8c0bf7369c7）：core.regression.
        # read_result 只捕 JSONDecodeError/OSError，无效 UTF-8 会让
        # read_text 抛 UnicodeDecodeError（ValueError 族）——不守卫会传播成
        # GET /api/regression/result 的 500。原地降级 parse_error，公共
        # 尾部仍能附 running。
        result = {"status": "parse_error", "reason": f"快照读取失败: {e}"}
    if not isinstance(result, dict):
        result = {"status": "parse_error", "reason": "快照非对象"}
    # 浅拷贝收拢所有权（code-review item 8771e71bc94e）：core.regression.
    # read_result 现实现每次返回 json.loads 新鲜 dict，但本函数要原地附加
    # running/progress——不耦合其内部所有权语义，未来底层引入缓存/共享
    # 对象时 Dashboard 侧字段也不会泄漏给其他调用方。
    result = dict(result)
    # never_run/parse_error 同样透出运行中态（触发后、快照未写盘窗口内）
    try:
        result["running"] = bool(is_regression_running(project_root))
    except Exception:
        result["running"] = False
    # 运行中透出执行进度；失败不抛（进度条缺失不应影响快照展示）但也不
    # 静默——降级为带 detail 的可区分形态（对齐上方 parse_error 降级带
    # reason 的口径，code-review item ac8e6b12666e），前端
    # RunningProgressView 对缺失 percent/elapsed 本就按「进度未知」渲染。
    if result["running"]:
        try:
            result["progress"] = read_progress(project_root)
        except Exception as e:
            result["progress"] = {"detail": f"进度读取失败: {e}"}
    return result