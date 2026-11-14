"""FlockRotatingFileHandler.doRollover 回归测试（item 04b47753a443）。

收敛提交 4958898f4 把 doRollover 里的 fcntl.flock 换成
flock_exclusive/flock_release 但漏了导入：首次轮转（日志涨到 maxBytes，
或多进程下另一进程已轮转使 _path_is_stale 恒真）即 NameError，emit 捕获
后仅向 stderr 打 handleError 提示、记录丢弃，finally 里 flock_release
再次 NameError 使 os.close 永不执行、每次尝试泄漏一个 fd；此后该进程
100% 日志写入持续失败直至重启。

本测试以小 maxBytes 在 tmp_path 真实触发 doRollover（emit → shouldRollover
→ doRollover 全链路），断言备份文件生成且进程可持续再轮转——NameError
形态下 doRollover 不产生任何备份文件，断言即失败。

不依赖真实日志路径：handler 直接指向 tmp_path。
"""

import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.logger import FlockRotatingFileHandler  # noqa: E402


def _write_record(handler, message):
    rec = logging.LogRecord(
        name="fenixd",
        level=logging.INFO,
        pathname="",
        lineno=0,
        msg=message,
        args=(),
        exc_info=None,
    )
    handler.handle(rec)


def test_do_rollover_creates_backup_and_keeps_rolling(tmp_path):
    """写入超 maxBytes 触发 doRollover：备份生成，且后续写入可再轮转。"""
    log_file = tmp_path / "fenixd.log"
    handler = FlockRotatingFileHandler(
        str(log_file),
        maxBytes=512,  # 故意取小值：几条记录即越过阈值
        backupCount=5,
        encoding="utf-8",
    )
    try:
        # 第一批：12 条 × 101 字节 ≈ 1.2KB > 512B，至少触发一次轮转。
        # 修复前此处 emit 内 NameError 被吞（仅 stderr 提示），无备份生成。
        for n in range(12):
            _write_record(handler, "x" * 100 + f"-{n}")

        first_backup = tmp_path / "fenixd.log.1"
        assert first_backup.exists(), (
            "writing past maxBytes must produce fenixd.log.1 "
            "(absent means doRollover failed silently)"
        )
        assert first_backup.read_text(encoding="utf-8").strip()

        # 第二批：继续写入再次越限，验证首转之后轮转链路仍可用
        # （修复前首转 NameError 后本进程日志写入持续静默失败）。
        before = len(list(tmp_path.glob("fenixd.log.[0-9]*")))
        for n in range(12):
            _write_record(handler, "y" * 100 + f"-{n}")
        after = len(list(tmp_path.glob("fenixd.log.[0-9]*")))
        assert after > before, (
            "second batch must roll over again (doRollover usable repeatedly)"
        )
        # 基底文件仍是活跃日志，轮转没有把它弄丢
        assert log_file.exists()
    finally:
        handler.close()
