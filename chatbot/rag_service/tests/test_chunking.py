import unittest

from domain.chunking import chunk_text_with_overlap


class TestChunking(unittest.TestCase):
    def test_chunking_produces_multiple_chunks(self):
        text = "word " * 500
        chunks = chunk_text_with_overlap(text, chunk_size=100, overlap=20, max_chunks=10)
        self.assertGreaterEqual(len(chunks), 2)
        self.assertTrue(all(c.strip() for c in chunks))


if __name__ == "__main__":
    unittest.main()
