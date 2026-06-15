import unittest

from retrieval.content_filter import is_substantive_learning_content


class TestContentFilter(unittest.TestCase):
    def test_learning_chunk_accepted(self):
        text = (
            "Convolutional neural networks apply filters across spatial dimensions to detect "
            "edges, textures, and hierarchical features. The algorithm uses backpropagation to "
            "update kernel weights. Students study pooling layers, stride, padding, and "
            "activation functions such as ReLU. Example: given an input tensor, compute the "
            "feature map dimensions after a 3x3 convolution with stride 1. "
        ) * 3
        self.assertTrue(is_substantive_learning_content(text))

    def test_empty_chunk_rejected(self):
        self.assertFalse(is_substantive_learning_content(""))


if __name__ == "__main__":
    unittest.main()
