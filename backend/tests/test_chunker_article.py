"""W7 D8：chunker「第X条」article 回退模式的正则单测。

锁定 RE_CLAUSE_ARTICLE / RE_CHAPTER_CN 行为，防止回归影响 GB/JGJ 小数切块。
（chunk_pdf 全流程依赖真实 PDF，由 ingest 集成验证；此处只测纯正则。）
"""

import unittest

from app.rag.chunker import RE_CHAPTER_CN, RE_CLAUSE_ARTICLE


class TestClauseArticleRegex(unittest.TestCase):
    """RE_CLAUSE_ARTICLE：识别「第X条」，X 为中文或阿拉伯数字。"""

    def test_matches_chinese_numeral(self):
        for s, expect in [
            ("第一条 托儿所、幼儿园的服务半径", "一"),
            ("第十二条 应符合下列规定", "十二"),
            ("第二十三条", "二十三"),
            ("第二百零五条 其他", "二百零五"),
        ]:
            m = RE_CLAUSE_ARTICLE.match(s)
            self.assertIsNotNone(m, f"应匹配: {s}")
            self.assertEqual(m.group(1), expect)

    def test_matches_arabic_and_spaced(self):
        self.assertEqual(RE_CLAUSE_ARTICLE.match("第5条 ...").group(1), "5")
        self.assertEqual(RE_CLAUSE_ARTICLE.match("第 8 条 ...").group(1), "8")

    def test_no_space_after_条(self):
        # OCR 常吃掉空格，"第二条托儿所" 也要能切
        m = RE_CLAUSE_ARTICLE.match("第二条托儿所应独立设置")
        self.assertIsNotNone(m)
        self.assertEqual(m.group(1), "二")

    def test_does_not_match_条例_title(self):
        # 标题里的「...保护条例」「第X条例」不能误判为条款
        self.assertIsNone(RE_CLAUSE_ARTICLE.match("历史文化名城名镇名村保护条例"))
        self.assertIsNone(RE_CLAUSE_ARTICLE.match("第一条例外情形"))  # 条例 紧跟

    def test_does_not_match_chapter(self):
        # 第X章 是章不是条
        self.assertIsNone(RE_CLAUSE_ARTICLE.match("第一章 总则"))

    def test_does_not_match_plain_text(self):
        self.assertIsNone(RE_CLAUSE_ARTICLE.match("本标准适用于城市规划"))
        self.assertIsNone(RE_CLAUSE_ARTICLE.match("5.0.3 配套设施"))  # 小数条款不归 article


class TestChapterCnRegex(unittest.TestCase):
    """RE_CHAPTER_CN：识别「第X章」。"""

    def test_matches_chapter(self):
        self.assertEqual(RE_CHAPTER_CN.match("第一章 总则").group(1), "一")
        self.assertEqual(RE_CHAPTER_CN.match("第三章").group(1), "三")

    def test_does_not_match_clause(self):
        self.assertIsNone(RE_CHAPTER_CN.match("第一条 服务半径"))


if __name__ == "__main__":
    unittest.main()
