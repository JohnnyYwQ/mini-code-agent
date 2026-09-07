"""Discover tests in the separate source tree for tests."""

import sys
from pathlib import Path

from django.test.runner import DiscoverRunner


class TestRunner(DiscoverRunner):
    def build_suite(self, test_labels=None, **kwargs):
        test_root = Path(__file__).resolve().parents[4] / "src" / "test" / "python"
        if str(test_root) not in sys.path:
            sys.path.insert(0, str(test_root))
        return super().build_suite(test_labels or ["tests"], **kwargs)
