import unittest

from services.quiz_service import detect_quiz_intent, extract_question_count


class TestQuizIntent(unittest.TestCase):
    def test_detect_quiz_intent_id(self):
        self.assertTrue(detect_quiz_intent("buat 5 soal kuis dari materi ini"))

    def test_extract_question_count(self):
        self.assertEqual(extract_question_count("buat 10 soal"), 10)


if __name__ == "__main__":
    unittest.main()
