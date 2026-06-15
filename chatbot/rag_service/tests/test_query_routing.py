import unittest

from query_routing import is_company_focused_question


class TestQueryRouting(unittest.TestCase):
    def test_company_question(self):
        self.assertTrue(
            is_company_focused_question("Siapa direktur utama PT SMART?", has_attachments=False)
        )

    def test_course_question_not_company_only(self):
        self.assertFalse(
            is_company_focused_question("Jelaskan algoritma CNN pada slide 3", has_attachments=False)
        )


if __name__ == "__main__":
    unittest.main()
