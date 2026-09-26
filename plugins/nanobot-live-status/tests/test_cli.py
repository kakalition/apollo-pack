from __future__ import annotations

import pytest

from nanobot_live_status.__main__ import main


def test_phrases_command(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["phrases", "-n", "5"]) == 0
    lines = [line for line in capsys.readouterr().out.splitlines() if line.strip()]
    assert len(lines) == 5


def test_no_command_prints_help(capsys: pytest.CaptureFixture[str]) -> None:
    assert main([]) == 1
    assert "usage" in capsys.readouterr().out.lower()


def test_doctor_runs(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["doctor"]) == 0
    out = capsys.readouterr().out
    assert "nanobot-live-status" in out
    assert "nanobot.tools entry points" in out


def test_version_flag(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as excinfo:
        main(["--version"])
    assert excinfo.value.code == 0
    assert "nanobot-live-status" in capsys.readouterr().out
