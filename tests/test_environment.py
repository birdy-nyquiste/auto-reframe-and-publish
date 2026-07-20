from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "skills/process-weixin-submissions/scripts"
sys.path.insert(0, str(SCRIPTS))

from weixin_submission.environment import load_env_file  # noqa: E402


class EnvironmentFileTest(unittest.TestCase):
    def test_quotes_are_removed_without_shell_or_variable_expansion(self) -> None:
        name = "WEIXIN_BLOG_ENV_TEST"
        previous = os.environ.pop(name, None)
        try:
            with tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / ".env"
                path.write_text(
                    f'{name}="literal-$HOME-$(touch should-not-run)"\n',
                    encoding="utf-8",
                )

                load_env_file(path)

            self.assertEqual(
                os.environ[name], "literal-$HOME-$(touch should-not-run)"
            )
        finally:
            if previous is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = previous


if __name__ == "__main__":
    unittest.main()
