from unittest import TestCase

from evals.memory_retrieval.cuda_host import _parse_nvidia_profile


class CUDAHostTests(TestCase):
    def test_parses_the_pinned_nvidia_smi_row(self):
        self.assertEqual(
            _parse_nvidia_profile("NVIDIA GeForce RTX 2070 SUPER, 550.142, 8192\n"),
            ("NVIDIA GeForce RTX 2070 SUPER", "550.142", 8192),
        )

    def test_rejects_more_than_one_gpu(self):
        with self.assertRaisesRegex(RuntimeError, "exactly one"):
            _parse_nvidia_profile("gpu zero, 550.142, 8192\ngpu one, 550.142, 8192")
