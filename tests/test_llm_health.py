"""tests/test_llm_health.py — LLM Provider 健康检测单测（add-provider-health-check 1.2）。

monkeypatch urllib.request.urlopen 替身覆盖四类失败分类与请求构造契约，
不发起真实网络请求。
"""
import io
import json
import sys
import urllib.error
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.dashboard import llm_health  # noqa: E402


class _FakeResponse:
    """urlopen 返回替身（context manager + read）。"""

    def __init__(self, body: bytes):
        self._body = body

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def read(self) -> bytes:
        return self._body


def _install_urlopen(monkeypatch, fn):
    """把 urlopen 替换为 fn(req, timeout=...) 形态的替身并捕获调用参数。"""
    captured = {}

    def fake_urlopen(req, timeout=None):
        captured["req"] = req
        captured["timeout"] = timeout
        return fn(req, timeout=timeout)

    monkeypatch.setattr(llm_health.urllib.request, "urlopen", fake_urlopen)
    return captured


def _ok_body(text: str = "hi") -> bytes:
    return json.dumps(
        {"content": [{"type": "text", "text": text}], "usage": {"output_tokens": 1}}
    ).encode("utf-8")


def test_200_normal_reply(monkeypatch):
    """200 正常回复：ok=True、latency_ms 正整数、model 回显、无错误字段。"""
    captured = _install_urlopen(
        monkeypatch, lambda req, timeout=None: _FakeResponse(_ok_body("hello there"))
    )
    result = llm_health.run_llm_health_check("https://gw.example.com", "sk-test", "mdl-1")
    assert result["ok"] is True
    assert isinstance(result["latency_ms"], int) and result["latency_ms"] > 0
    assert result["model"] == "mdl-1"
    assert result["error_kind"] is None and result["error"] is None and result["status"] is None
    # 请求构造契约：URL / 超时 / 最小消息体
    req = captured["req"]
    assert req.full_url == "https://gw.example.com/v1/messages"
    assert captured["timeout"] == llm_health.HEALTH_CHECK_TIMEOUT_SECONDS
    assert req.get_header("X-api-key") == "sk-test"
    assert req.get_header("Anthropic-version") == "2023-06-01"
    assert req.get_header("Authorization") == "Bearer sk-test"
    body = json.loads(req.data.decode("utf-8"))
    assert body["max_tokens"] == llm_health._PROBE_MAX_TOKENS == 64
    assert body["messages"] == [{"role": "user", "content": "hello"}]
    assert body["model"] == "mdl-1"


def test_http_error_status_and_snippet(monkeypatch):
    """非 200：error_kind=http_error、status 透传、错误体片段随 error 返回。"""
    err_body = b'{"error": {"message": "invalid x-api-key"}}'

    def raise_http_error(req, timeout=None):
        raise urllib.error.HTTPError(
            req.full_url, 401, "Unauthorized", hdrs={}, fp=io.BytesIO(err_body)
        )

    _install_urlopen(monkeypatch, raise_http_error)
    result = llm_health.run_llm_health_check("https://gw.example.com", "sk-bad", "mdl-1")
    assert result["ok"] is False
    assert result["error_kind"] == "http_error"
    assert result["status"] == 401
    assert "invalid x-api-key" in result["error"]
    assert result["model"] is None


def test_http_error_snippet_truncated(monkeypatch):
    """非 200 且错误体超长：片段截断 ≤200 字符。"""
    long_body = b"x" * 500

    def raise_http_error(req, timeout=None):
        raise urllib.error.HTTPError(req.full_url, 500, "Boom", hdrs={}, fp=io.BytesIO(long_body))

    _install_urlopen(monkeypatch, raise_http_error)
    result = llm_health.run_llm_health_check("https://gw.example.com", "sk", "m")
    assert result["error_kind"] == "http_error"
    assert len(result["error"]) <= 200
    assert result["status"] == 500


@pytest.mark.parametrize(
    "exc",
    [
        TimeoutError("timed out"),  # 读响应阶段的裸 socket 超时
        urllib.error.URLError(TimeoutError("timed out")),  # urlopen 阶段包成 URLError
    ],
)
def test_timeout_classified(monkeypatch, exc):
    """超时（裸 TimeoutError / URLError(reason=TimeoutError)）→ error_kind=timeout。"""

    def raise_timeout(req, timeout=None):
        raise exc

    _install_urlopen(monkeypatch, raise_timeout)
    result = llm_health.run_llm_health_check("https://gw.example.com", "sk", "m")
    assert result["ok"] is False
    assert result["error_kind"] == "timeout"
    assert result["error"]
    assert result["status"] is None


@pytest.mark.parametrize(
    "exc",
    [
        urllib.error.URLError(ConnectionRefusedError(111)),  # 连接被拒
        urllib.error.URLError(OSError("name resolution failed")),  # DNS 失败
        OSError("remote disconnect"),  # 远端断开
        ValueError("unknown url type: not-a-url"),  # baseurl 非法
    ],
)
def test_connection_error_classified(monkeypatch, exc):
    """连接类失败（含 baseurl 非法）→ error_kind=connection_error。"""

    def raise_conn(req, timeout=None):
        raise exc

    _install_urlopen(monkeypatch, raise_conn)
    result = llm_health.run_llm_health_check("not-a-url", "sk", "m")
    assert result["ok"] is False
    assert result["error_kind"] == "connection_error"
    assert result["error"]


def test_200_without_text_content(monkeypatch):
    """200 但无文本 content（空数组 / 纯非 text 块）→ error_kind=empty_reply。"""
    for body in (
        json.dumps({"content": []}).encode("utf-8"),
        json.dumps({"content": [{"type": "tool_use", "id": "t1"}]}).encode("utf-8"),
    ):
        _install_urlopen(
            monkeypatch, lambda req, timeout=None, b=body: _FakeResponse(b)
        )
        result = llm_health.run_llm_health_check("https://gw.example.com", "sk", "m")
        assert result["ok"] is False
        assert result["error_kind"] == "empty_reply"
        assert result["error"]
        assert result["status"] is None


def test_200_non_json_body(monkeypatch):
    """200 但响应非合法 JSON → error_kind=empty_reply（spec 同款归类）。"""
    _install_urlopen(
        monkeypatch, lambda req, timeout=None: _FakeResponse(b"<html>gateway error</html>")
    )
    result = llm_health.run_llm_health_check("https://gw.example.com", "sk", "m")
    assert result["error_kind"] == "empty_reply"


def test_baseurl_trailing_slash_stripped(monkeypatch):
    """baseurl 去尾部斜杠：不改写 URL 语义（https://x.com//v1/messages 防呆）。"""
    captured = _install_urlopen(
        monkeypatch, lambda req, timeout=None: _FakeResponse(_ok_body())
    )
    llm_health.run_llm_health_check("https://gw.example.com///", "sk", "m")
    assert captured["req"].full_url == "https://gw.example.com/v1/messages"


def test_empty_apikey_no_bearer_header(monkeypatch):
    """apikey 为空：不带 Authorization 头（与 probe 先例条件构造一致）。"""
    captured = _install_urlopen(
        monkeypatch, lambda req, timeout=None: _FakeResponse(_ok_body())
    )
    llm_health.run_llm_health_check("https://gw.example.com", "", "m")
    assert captured["req"].get_header("Authorization") is None
    assert captured["req"].get_header("X-api-key") == ""
