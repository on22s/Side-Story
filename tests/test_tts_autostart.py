from __future__ import annotations

import os
import subprocess
import unittest
from unittest import mock

import cli


class TtsAutostartTests(unittest.TestCase):
    def test_canonical_endpoints_invoke_background_recovery(self) -> None:
        config = {
            "tts": {
                "mode": "external",
                "urls": [
                    "http://127.0.0.1:18000/tts",
                    "http://127.0.0.1:18001/tts",
                ],
            }
        }
        completed = subprocess.CompletedProcess([], 0, "", "")
        with mock.patch.dict(os.environ, {"ALEXANDRIA_XC_TTS_AUTO_START": "1"}, clear=False):
            with mock.patch("cli.subprocess.run", return_value=completed) as run:
                cli.ensure_xc_tts_services(config)

        command, kwargs = run.call_args
        self.assertEqual(command[0], [str(cli.ROOT_DIR / "start_xc_tts_tunnel.sh")])
        self.assertEqual(kwargs["env"]["ALEXANDRIA_XC_TTS_BACKGROUND"], "1")
        self.assertEqual(kwargs["env"]["ALEXANDRIA_XC_TTS_AUTO_START"], "1")
        self.assertNotIn("ALEXANDRIA_XC_TTS_GPU1_LOCAL_PORT", kwargs["env"])

    def test_single_endpoint_disables_gpu1_forwarding(self) -> None:
        config = {
            "tts": {
                "mode": "external",
                "urls": ["http://localhost:18000/tts"],
            }
        }
        completed = subprocess.CompletedProcess([], 0, "", "")
        with mock.patch.dict(os.environ, {"ALEXANDRIA_XC_TTS_AUTO_START": "1"}, clear=False):
            with mock.patch("cli.subprocess.run", return_value=completed) as run:
                cli.ensure_xc_tts_services(config)

        self.assertEqual(
            run.call_args.kwargs["env"]["ALEXANDRIA_XC_TTS_GPU1_LOCAL_PORT"],
            "",
        )

    def test_noncanonical_external_endpoint_is_not_touched(self) -> None:
        config = {
            "tts": {
                "mode": "external",
                "urls": ["https://tts.example/tts"],
            }
        }
        with mock.patch("cli.subprocess.run") as run:
            cli.ensure_xc_tts_services(config)
        run.assert_not_called()

    def test_autostart_can_be_disabled(self) -> None:
        config = {
            "tts": {
                "mode": "external",
                "urls": ["http://127.0.0.1:18000/tts"],
            }
        }
        with mock.patch.dict(os.environ, {"ALEXANDRIA_XC_TTS_AUTO_START": "0"}, clear=False):
            with mock.patch("cli.subprocess.run") as run:
                cli.ensure_xc_tts_services(config)
        run.assert_not_called()


if __name__ == "__main__":
    unittest.main()
