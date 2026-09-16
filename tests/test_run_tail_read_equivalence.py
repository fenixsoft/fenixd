"""尾读路径与全量读取等价性用例（fix-dashboard-read-path-performance 任务 1.3）。

覆盖三种输入：小文件（≤ 窗口，走全读）/ 大文件（> 窗口，走尾部 seek）/
超长末行（> 窗口，回退全读）。断言尾读结果与独立参考实现（逐行全读）逐条
等价，且 classify_run 判定一致（正确性约束：不得从行中间截断导致已完成 run
被误判 running）。
"""
import json
import sys
import time
from collections import deque
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.dashboard.data import classify_run
from core.dashboard.data.runs import _read_run_lines, _READ_RUN_TAIL_WINDOW


def _ref_full_read(path: Path, max_lines: int = 3) -> list:
    """独立参考实现：逐行全读（与修复前语义一致）。"""
    tail = deque(maxlen=max_lines)
    try:
        with path.open("rb") as f:
            for raw in f:
                line = raw.decode("utf-8", errors="replace").strip()
                if not line:
                    continue
                try:
                    tail.append(json.loads(line))
                except json.JSONDecodeError:
                    tail.append({"type": "stderr", "line": line})
    except OSError:
        pass
    return list(tail)


class TestTailReadEquivalence:
    def _check(self, path: Path, max_lines: int = 3):
        got = _read_run_lines(path, max_lines)
        want = _ref_full_read(path, max_lines)
        assert got == want, f"尾读与全量读取结果不一致: got={got}  want={want}"
        assert classify_run(got) == classify_run(want)

    def test_small_file_equivalence(self, tmp_path):
        """小文件（≤ 64KB）：直接走全读分支，结果与参考实现一致。"""
        p = tmp_path / "small.jsonl"
        lines = [
            json.dumps({"type": "assistant", "content": f"line {i}"})
            for i in range(8)
        ]
        lines.append(json.dumps({"type": "result", "result": "done"}))
        p.write_text("\n".join(lines) + "\n", encoding="utf-8")
        assert p.stat().st_size <= _READ_RUN_TAIL_WINDOW
        self._check(p)
        assert classify_run(_read_run_lines(p)) == "done"

    def test_large_file_tail_reads_window_bytes(self, tmp_path, monkeypatch):
        """12MB 文件：末 3 行在窗口内，读取字节量 ≤ 窗口，结果与全量读取一致。"""
        import pathlib

        p = tmp_path / "large.jsonl"
        n_bulk = 400
        bulk_line = {"type": "assistant", "content": "b" * (30 * 1024)}  # ~30KB/行
        bulk = [json.dumps(bulk_line) for _ in range(n_bulk)]
        tail3 = [
            json.dumps({"type": "assistant", "content": f"tail-{i}"})
            for i in range(3)
        ]
        p.write_text("\n".join(bulk + tail3) + "\n", encoding="utf-8")
        assert p.stat().st_size > _READ_RUN_TAIL_WINDOW

        # 跟踪 f.read() 字节量（仅 seek 分支调用；全读分支用迭代不走 .read()）
        real_open = pathlib.Path.open
        reads = {"bytes": 0}

        def counting_open(self, *a, **kw):
            f = real_open(self, *a, **kw)
            orig_read = f.read

            def counting_read(*ra, **rk):
                data = orig_read(*ra, **rk)
                reads["bytes"] += len(data)
                return data

            f.read = counting_read
            return f

        monkeypatch.setattr(pathlib.Path, "open", counting_open)
        got = _read_run_lines(p, 3)
        reads_after = reads["bytes"]
        monkeypatch.undo()

        assert reads_after <= _READ_RUN_TAIL_WINDOW, (
            f"读取 {reads_after}B 超过窗口 {_READ_RUN_TAIL_WINDOW}B"
        )
        assert got == _ref_full_read(p, 3)
        assert classify_run(got) == "running"

    def test_super_long_last_line_falls_back(self, tmp_path):
        """末行超窗 → 回退全量读取；classify_run 与全量读取一致（不得误判 running）。"""
        p = tmp_path / "huge-last.jsonl"
        bulk = [
            json.dumps({"type": "assistant", "content": f"b{i}"})
            for i in range(5)
        ]
        huge = json.dumps({"type": "result", "result": "ok", "payload": "x" * (200 * 1024)})
        p.write_text("\n".join(bulk + [huge]) + "\n", encoding="utf-8")
        assert p.stat().st_size > _READ_RUN_TAIL_WINDOW
        got = _read_run_lines(p, 3)
        assert got == _ref_full_read(p, 3)
        assert classify_run(got) == "done", "超长末行不得因字节截断被误判 running"

    def test_partial_last_line_no_newline(self, tmp_path):
        """末行无换行（中断写入）：与全量读取等价。"""
        p = tmp_path / "partial.jsonl"
        content = (
            json.dumps({"type": "assistant", "content": "ok"}) + "\n"
            + '{"type": "assist'  # 断尾，无 \n
        )
        p.write_text(content, encoding="utf-8")
        self._check(p)

    def test_empty_file(self, tmp_path):
        """空文件：返回空列表，不抛异常。"""
        p = tmp_path / "empty.jsonl"
        p.write_text("", encoding="utf-8")
        assert _read_run_lines(p) == []
        assert _ref_full_read(p) == []

    def test_all_jsonparse_fail_lines(self, tmp_path):
        """所有行均非法 JSON → 按 stderr 降级，与全量读取等价。"""
        p = tmp_path / "bad.jsonl"
        p.write_text("not-json\nalso-not-json\n{broken\n", encoding="utf-8")
        self._check(p)

    def test_run_meta_memo_skips_reread(self, tmp_path, monkeypatch):
        """4.2：run 元数据 memo——文件未变第二次 get_runs 不重扫头 200 行。"""
        from core.dashboard.data import get_runs
        import core.dashboard.data.runs as runs_mod

        runs_dir = tmp_path / ".fenix" / "runs"
        runs_dir.mkdir(parents=True)
        run_file = runs_dir / "impl-myspec-1788000000.jsonl"
        run_file.write_text(
            json.dumps({"type": "provider_marker", "timestamp": "2026-09-01T00:00:00.000000Z",
                         "model": "m", "provider": "p"})
            + "\n"
            + json.dumps({"type": "result", "result": "ok"})
            + "\n",
            encoding="utf-8",
        )
        first = get_runs(tmp_path, "myspec", include_archive=True)
        assert len(first) == 1
        assert first[0]["status"] == "done"

        orig_ts = runs_mod._first_run_event_ts
        calls = {"n": 0}

        def counting_ts(p):
            calls["n"] += 1
            return orig_ts(p)

        monkeypatch.setattr(runs_mod, "_first_run_event_ts", counting_ts)
        second = get_runs(tmp_path, "myspec", include_archive=True)
        assert second == first
        assert calls["n"] == 0, "文件未变时第二次 get_runs 应命中 memo，不重扫"

    def test_run_meta_memo_invalidated_on_append(self, tmp_path):
        """4.2：追加终态行 → mtime/size 变化 → memo 失效 → 新状态生效。"""
        from core.dashboard.data import get_runs

        runs_dir = tmp_path / ".fenix" / "runs"
        runs_dir.mkdir(parents=True)
        run_file = runs_dir / "impl-myspec-1788000000.jsonl"
        run_file.write_text(
            json.dumps({"type": "assistant", "content": "working..."}) + "\n",
            encoding="utf-8",
        )
        first = get_runs(tmp_path, "myspec", include_archive=True)
        assert first[0]["status"] == "running"

        with run_file.open("a", encoding="utf-8") as f:
            f.write(json.dumps({"type": "result", "result": "ok"}) + "\n")
        second = get_runs(tmp_path, "myspec", include_archive=True)
        assert second[0]["status"] == "done"

    def test_run_meta_memo_stale_consistent(self, tmp_path, monkeypatch):
        """4.2：stale 判定按当前时刻重算，缓存不缓存 stale 本身。"""
        from core.dashboard.data import get_runs, _RUN_STALE_SECONDS
        import core.dashboard.data.runs as runs_mod

        runs_dir = tmp_path / ".fenix" / "runs"
        runs_dir.mkdir(parents=True)
        run_file = runs_dir / "impl-myspec-1788000000.jsonl"
        run_file.write_text(
            json.dumps({"type": "assistant", "content": "wip"}) + "\n",
            encoding="utf-8",
        )
        first = get_runs(tmp_path, "myspec", include_archive=True)
        assert first[0]["status"] == "running"

        # 直接修改 mtime 制造超时（绕过运行时间）
        import os

        stale_ts = int(time.time() - _RUN_STALE_SECONDS - 10)
        os.utime(run_file, (stale_ts, stale_ts))
        # mtime 变化 → key 变化 → memo miss → stale=True
        result2 = get_runs(tmp_path, "myspec", include_archive=True)
        assert result2[0]["status"] == "stale"
