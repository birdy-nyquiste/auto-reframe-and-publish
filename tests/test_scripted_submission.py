from __future__ import annotations

import subprocess
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / "skills/process-weixin-submissions/scripts/process_weixin_submissions.py"


class ScriptedSubmissionTest(unittest.TestCase):
    def test_skill_cli_exposes_the_planned_operations(self) -> None:
        completed = subprocess.run(
            [sys.executable, str(CLI), "--help"],
            cwd=ROOT,
            check=False,
            capture_output=True,
            text=True,
        )

        self.assertEqual(completed.returncode, 0, completed.stderr)
        for operation in ("initialize", "run", "status", "retry", "publish"):
            self.assertIn(operation, completed.stdout)


if __name__ == "__main__":
    unittest.main()
