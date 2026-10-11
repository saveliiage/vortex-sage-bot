"""Cookie fallback rule for yt-dlp runs.

A stale cookie jar must never break a download that works anonymously — that is exactly
how YouTube downloads died (403 on videoplayback while the same URL pulled fine with no
cookies). These tests pin the retry rule in core.ytdlp.
"""

from core import ytdlp

STALE_JAR = ["--cookies", "/app/cookies/youtube.txt"]


def _patch(monkeypatch, jar=STALE_JAR):
    monkeypatch.setattr(ytdlp, "YT_COOKIES_JAR_ARGS", jar)


def test_anonymous_success_never_touches_the_jar(monkeypatch):
    _patch(monkeypatch)
    calls = []

    def fake_exec(cmd, want_path, timeout, cwd):
        calls.append(cmd)
        return {"success": True, "output": "ok"}

    monkeypatch.setattr(ytdlp, "_exec", fake_exec)
    res = ytdlp.run(["--dump-json", "u"])
    assert res["success"]
    assert len(calls) == 1
    assert "--cookies" not in calls[0]


def test_cookie_error_retries_with_the_jar(monkeypatch):
    _patch(monkeypatch)
    calls = []

    def fake_exec(cmd, want_path, timeout, cwd):
        calls.append(cmd)
        if "--cookies" in cmd:
            return {"success": True, "output": "ok"}
        return {"success": False, "error": "ERROR: unable to download video data: HTTP Error 403: Forbidden"}

    monkeypatch.setattr(ytdlp, "_exec", fake_exec)
    res = ytdlp.run(["--dump-json", "u"])
    assert res["success"]
    assert len(calls) == 2
    assert "--cookies" not in calls[0]
    assert "--cookies" in calls[1]


def test_unrelated_failure_is_not_retried(monkeypatch):
    _patch(monkeypatch)
    calls = []

    def fake_exec(cmd, want_path, timeout, cwd):
        calls.append(cmd)
        return {"success": False, "error": "ERROR: Video unavailable"}

    monkeypatch.setattr(ytdlp, "_exec", fake_exec)
    res = ytdlp.run(["--dump-json", "u"])
    assert not res["success"]
    assert len(calls) == 1


def test_no_jar_means_single_anonymous_attempt(monkeypatch):
    _patch(monkeypatch, jar=[])
    calls = []

    def fake_exec(cmd, want_path, timeout, cwd):
        calls.append(cmd)
        return {"success": False, "error": "ERROR: unable to download video data: HTTP Error 403: Forbidden"}

    monkeypatch.setattr(ytdlp, "_exec", fake_exec)
    res = ytdlp.run(["--dump-json", "u"])
    assert not res["success"]
    assert len(calls) == 1


def test_cmd_shape_keeps_remote_components():
    cmd = ytdlp.build_cmd(["--dump-json", "u"], [])
    assert cmd[0] == ytdlp.YT_DLP_BIN
    assert "--no-playlist" in cmd and "--no-warnings" in cmd
    assert "--cookies" not in cmd
