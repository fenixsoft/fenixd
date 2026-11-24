"""code-review item a991a4bb0891：读/写两侧 spec 名正则字面同步表征测试。

锁定两侧正则对样例名集的命中/拒绝矩阵，任一侧漂移时本测试先红：
- 读侧 core.dashboard.data.spec_docs._SPEC_NAME_RE——防路径穿越白名单，
  刻意宽于写侧创建口径（数字开头 / 连续或尾随连字符也可命中）
- 写侧权威口径 core.spec_naming.KEBAB_RE——创建校验单源（spec_gen 消费，
  复制约定见 spec_docs 模块头注释）

矩阵语义：
- 双侧均接受 = 写侧可产生、读侧可解析的合法 kebab-case 名
- 读侧独有命中 = 刻意宽松取舍的漂移哨兵（写侧产生不了的形态；两侧任一
  突然翻转即红，提示核对模块头注释的字面同步约定是否仍成立）
- 双侧均拒绝 = 穿越/非法形态
不覆盖空白字符形态（读侧 ``$`` 锚允许尾随换行的 re 语义属另一独立面，
与本条目的字面同步哨兵无关）。
"""

import unittest

from core.spec_naming import KEBAB_RE
from core.dashboard.data.spec_docs import _SPEC_NAME_RE

# 双侧均接受：合法 kebab-case（含数字段与数字结尾）
_BOTH_ACCEPT = ("add-auth", "refactor-db2", "a", "abc-123", "evo-foo-2")

# 读侧独有命中（写侧创建口径拒绝）：数字开头 / 连续连字符 / 尾随连字符
_READ_ONLY_ACCEPT = ("1abc", "a--b", "abc-")

# 双侧均拒绝：大写 / 空白 / 下划线 / 首连字符 / 穿越片段 / 空串
_BOTH_REJECT = ("ABC", "a_b", "a b", "-abc", "..", ".", "../evil", "a/b", "")


class TestSpecNameRegexMatrix(unittest.TestCase):
    """读侧 _SPEC_NAME_RE 与写侧 KEBAB_RE 的命中/拒绝矩阵表征锁定。"""

    def test_both_accept_valid_kebab_names(self):
        for name in _BOTH_ACCEPT:
            with self.subTest(name=name):
                self.assertIsNotNone(_SPEC_NAME_RE.match(name))
                self.assertIsNotNone(KEBAB_RE.fullmatch(name))

    def test_read_side_deliberate_widening_samples(self):
        """读侧刻意宽于写侧的形态：读侧命中、写侧拒绝（既有取舍哨兵）。"""
        for name in _READ_ONLY_ACCEPT:
            with self.subTest(name=name):
                self.assertIsNotNone(_SPEC_NAME_RE.match(name))
                self.assertIsNone(KEBAB_RE.fullmatch(name))

    def test_both_reject_unsafe_or_invalid_names(self):
        for name in _BOTH_REJECT:
            with self.subTest(name=name):
                self.assertIsNone(_SPEC_NAME_RE.match(name))
                self.assertIsNone(KEBAB_RE.fullmatch(name))


if __name__ == "__main__":
    unittest.main()
