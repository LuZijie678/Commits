import importlib.util
import unittest
from pathlib import Path
from unittest.mock import patch


SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "recover_batch_diffs_remote.py"


def load_module():
    spec = importlib.util.spec_from_file_location("recover_batch_diffs_remote", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class RecoverBatchDiffsRemoteTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.module = load_module()

    def test_parse_args_defaults_diff_max_chars_to_zero(self) -> None:
        with patch.object(
            self.module.sys,
            "argv",
            [
                "recover_batch_diffs_remote.py",
                "--input-csv",
                "input.csv",
                "--output-csv",
                "output.csv",
                "--output-jsonl",
                "output.jsonl",
                "--summary",
                "summary.json",
            ],
        ):
            args = self.module.parse_args()

        self.assertEqual(args.diff_max_chars, 0)


if __name__ == "__main__":
    unittest.main()
