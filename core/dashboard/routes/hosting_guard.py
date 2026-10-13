"""hosting_guard.py — dashboard 触发类端点共用的「消费方守卫」（hosting_state 判据）。

item fcadb893a1c8：``_guard_hosting_state`` 原定义于 code_review_routes（run /
fix-run 两端点共用，item 13d53dcd5440 去重），regression_routes 的 run / fix
两端点又各内联一份同构守卫——守卫规则变化（新增 hosting 态、改兜底判据、
改错误码/文案）需多点同修。提升到本共享模块供 code_review 与 regression
两族端点共用，调用方只留 label 文案。本模块仅依赖 stdlib（hosting_state 在
函数内延迟导入，便于测试 monkeypatch ``core.fenix_session.hosting_state``），
MUST NOT 反向依赖任何 routes 模块或 base.py，避免导入环。
"""

from __future__ import annotations

import logging

logger = logging.getLogger("fenixd.dashboard.routes.hosting_guard")


def _guard_hosting_state(proot, signal_label):
    """消费方守卫（hosting_state 判据，先例 request_spec_approve_push），
    code_review 的 run / fix-run 与 regression 的 run / fix 四端点共用
    （item 13d53dcd5440 首提去重；item fcadb893a1c8 提升到共享模块——regression
    侧此前又各复制一份同构守卫，仅「回归信号/回归修复信号」一词之差，守卫
    规则变化需多点同修，易漂移；去重手法对齐 code_review_routes 的
    _write_signal_exclusive 先例）。

    - 判定异常按未运行兜底，宁拒勿假放行；降级可观测（item 0d1ba0c6efc0）；
      兜底文案与真实 stopped 区分（item 90888da0836d）：异常时 daemon 可能
      实际在运行，真实原因多为权限/IO 等内部错误——复用「daemon 未运行」
      会把用户排障引向「启动 daemon」白费功夫，故返回可检索的区分文案，
      原始异常经日志留痕；
    - unmanaged（daemon 未受 supervisor 托管）→ 409 明确拒绝——信号无人消费
      会永久滞留并在 daemon 下次启动时被消费成一次用户并未请求的触发；
    - 非 managed（stopped）→ 400「daemon 未运行」。

    ``signal_label`` 仅用于 409 文案（「审查信号」/「修复信号」/「回归信号」/
    「回归修复信号」）。返回：放行 → None；拒绝 → (http_status, message) 元组，
    409/400 的错误码与文案由调用方映射，本函数不发响应。
    """
    from core.fenix_session import hosting_state as _hosting_state

    try:
        state = _hosting_state(str(proot))
    except Exception as exc:
        # 判定异常按未运行兜底，宁拒勿假放行；降级可观测（item 0d1ba0c6efc0）。
        # 文案不复用「daemon 未运行」（item 90888da0836d）：异常兜底时 daemon
        # 可能实际在跑，需给可检索的区分文案指引看服务端日志。
        logger.warning(
            "hosting_state 判定异常，按 stopped 兜底（宁拒勿假放行）: %r", exc
        )
        return 400, "daemon 运行状态判定失败（hosting_state 异常），请查看服务端日志后重试"
    if state == "unmanaged":
        return (
            409,
            f"本项目 daemon 未受 supervisor 托管，{signal_label}不会被消费。"
            f"经项目页「安装托管」或 /fenix-setup 恢复 supervisor 托管后重试",
        )
    if state != "managed":
        return 400, "daemon 未运行，请先启动 daemon"
    return None
