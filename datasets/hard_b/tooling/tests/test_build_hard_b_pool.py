import importlib.util
import unittest
from pathlib import Path


SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "build_hard_b_pool.py"


def load_module():
    spec = importlib.util.spec_from_file_location("build_hard_b_pool", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class BuildHardBPoolTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.module = load_module()

    def test_cap_need_diff_rows_zero_means_no_cap(self) -> None:
        rows = [{"repo": "a", "sha": "1"}, {"repo": "b", "sha": "2"}, {"repo": "c", "sha": "3"}]
        self.assertEqual(self.module.cap_need_diff_rows(rows, 0), rows)

    def test_cap_need_diff_rows_positive_value_truncates(self) -> None:
        rows = [{"repo": "a", "sha": "1"}, {"repo": "b", "sha": "2"}, {"repo": "c", "sha": "3"}]
        self.assertEqual(self.module.cap_need_diff_rows(rows, 2), rows[:2])


if __name__ == "__main__":
    unittest.main()
