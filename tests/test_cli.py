"""명령줄 인터페이스 테스트."""

from __future__ import annotations

from pathlib import Path

import pytest

from conftest import make_video, needs_ffmpeg
from webrec.cli import build_parser, main


@pytest.fixture
def config_file(tmp_path: Path) -> Path:
    path = tmp_path / "webrec.yaml"
    path.write_text(
        "jobs:\n"
        "  - name: 주간회의\n"
        "    url: https://zoom.us/j/1234567890\n"
        "    cron: '0 9 * * mon'\n"
        "    duration: 1h\n"
        "    backend: browser\n"
        "  - name: 비활성\n"
        "    url: https://example.com/live\n"
        "    start: '2030-01-01 10:00'\n"
        "    duration: 10m\n"
        "    enabled: false\n",
        encoding="utf-8",
    )
    return path


def test_parser_requires_subcommand():
    with pytest.raises(SystemExit):
        build_parser().parse_args([])


def test_once_requires_url():
    with pytest.raises(SystemExit):
        build_parser().parse_args(["once", "--at", "2030-01-01 10:00"])


def test_once_parses_time_and_duration():
    args = build_parser().parse_args(
        ["once", "--url", "https://youtu.be/x", "--at", "2030-01-01 21:00", "--duration", "1h30m"]
    )
    assert args.url == "https://youtu.be/x"
    assert args.at == "2030-01-01 21:00"
    assert args.duration == "1h30m"
    assert args.sample == 10  # 기본 샘플링 10초


def test_list_shows_next_run(config_file, capsys):
    assert main(["list", "-c", str(config_file)]) == 0
    output = capsys.readouterr().out
    assert "주간회의" in output
    assert "zoom.us" in output
    assert "비활성화된 작업" in output


def test_list_without_config_reports_error(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    assert main(["list"]) == 2
    assert "설정 파일" in capsys.readouterr().err


def test_doctor_reports_tools(capsys, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    code = main(["doctor"])
    output = capsys.readouterr().out
    assert "ffmpeg" in output
    assert "메일 설정" in output
    assert code in (0, 1)


@needs_ffmpeg
def test_verify_command_on_good_file(tmp_path, capsys):
    path = make_video(tmp_path / "ok.mp4", seconds=4)
    assert main(["verify", str(path)]) == 0
    assert "정상" in capsys.readouterr().out


@needs_ffmpeg
def test_verify_command_on_black_file(tmp_path, capsys):
    path = make_video(tmp_path / "black.mp4", seconds=4, black=True)
    assert main(["verify", str(path)]) == 1
    assert "비정상" in capsys.readouterr().out


@needs_ffmpeg
def test_check_command_samples_live_url(media_server, tmp_path, monkeypatch, capsys):
    """check 는 짧은 샘플을 떠 보고 녹화 가능 여부를 알려준다."""
    monkeypatch.chdir(tmp_path)
    code = main([
        "check", "--url", f"{media_server}/live.mp4",
        "--backend", "stream", "--sample", "3", "--no-mail",
    ])
    output = capsys.readouterr().out
    assert code == 0
    assert "사전 샘플링 점검" in output
    assert "정상" in output


@needs_ffmpeg
def test_check_command_fails_on_black_source(media_server, tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    code = main([
        "check", "--url", f"{media_server}/black.mp4",
        "--backend", "stream", "--sample", "3", "--no-mail",
    ])
    assert code == 1
    assert "검은 화면" in capsys.readouterr().out


@needs_ffmpeg
def test_once_command_records_immediately(media_server, tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    code = main([
        "once", "--url", f"{media_server}/live.mp4", "--duration", "4s",
        "--backend", "stream", "--no-preflight", "--no-mail",
        "--out", str(tmp_path / "rec"), "--name", "cli테스트",
    ])
    assert code == 0, capsys.readouterr().out
    files = list((tmp_path / "rec").glob("*.mkv"))
    assert len(files) == 1
    assert files[0].stat().st_size > 10_000
