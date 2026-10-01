"""Tests for the fitness package.

Run from the repository root:

    python -m unittest tests.py
"""

import unittest


class TestPackageImports(unittest.TestCase):
    """A placeholder so the test command works from the first commit."""

    def test_package_can_be_imported(self):
        import fitness

        self.assertTrue(hasattr(fitness, "__file__"))


if __name__ == "__main__":
    unittest.main()
