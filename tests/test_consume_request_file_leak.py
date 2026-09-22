"""`FenixDaemon._consume_request_file` 文件信号消费契约测试。

code-review item「admin_invoke_request 空壳文件泄漏」：消费端以
`tempfile.mkstemp` 建私有临时副本后 `os.replace` 占位；当信号文件本身不存在
（`FileNotFoundError`，即绝大多数轮次——信号是稀疏事件）时，必须清理刚建立的
临时文件，否则主循环每轮泄漏一个零字节 `.consumed.*` 文件。

观测到的线上后果：`.fenix/` 下堆积 11 万+ 个零字节
`.admin_invoke_request.json.consumed.*`，以 ~1 个/秒持续增长。
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fenixd import FenixDaemon


CONSUMED_GLOB = ".admin_invoke_request.json.consumed.*"


def _leftovers(fenix_dir: Path) -> list:
    return sorted(fenix_dir.glob(CONSUMED_GLOB))


def test_missing_request_file_leaves_no_leftover(tmp_path):
    """信号文件不存在时，不得遗留任何 .consumed.* 临时文件。

    这是主循环每轮都会走的路径（信号是稀疏事件，绝大多数轮次无请求文件），
    因此该路径的泄漏是「每轮一个文件」级别。
    """
    req_path = tmp_path / "admin_invoke_request.json"  # 故意不创建

    result = FenixDaemon._consume_request_file(req_path)

    assert result is None
    assert _leftovers(tmp_path) == [], (
        f"信号文件缺失时泄漏了临时文件：{[p.name for p in _leftovers(tmp_path)]}"
    )


def test_missing_request_file_repeated_calls_do_not_accumulate(tmp_path):
    """连续多轮消费（模拟主循环空转）不得累积残留文件。"""
    req_path = tmp_path / "admin_invoke_request.json"

    for _ in range(50):
        assert FenixDaemon._consume_request_file(req_path) is None

    assert _leftovers(tmp_path) == [], (
        f"50 轮空转后累积了 {len(_leftovers(tmp_path))} 个残留文件"
    )


def test_valid_request_file_consumed_and_cleaned(tmp_path):
    """正常消费：返回 payload，且信号文件与临时副本都已清理。"""
    req_path = tmp_path / "admin_invoke_request.json"
    req_path.write_text('{"spec": "foo", "source": "manual"}', encoding="utf-8")

    result = FenixDaemon._consume_request_file(req_path)

    assert result == {"spec": "foo", "source": "manual"}
    assert not req_path.exists()
    assert _leftovers(tmp_path) == []


def test_malformed_request_file_cleaned(tmp_path):
    """内容非法 JSON：返回 None，且信号文件与临时副本都已清理。"""
    req_path = tmp_path / "admin_invoke_request.json"
    req_path.write_text("{not valid json", encoding="utf-8")

    result = FenixDaemon._consume_request_file(req_path)

    assert result is None
    assert not req_path.exists()
    assert _leftovers(tmp_path) == []


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
