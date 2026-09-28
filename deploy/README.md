# Vortex — systemd units (cookie refresh pipeline)

Optional. The bot itself runs under Docker Compose; these units only exist for the
cookie refresh path, which needs a real Chromium on the host.

They talk to Chromium over CDP on `127.0.0.1:9222` and then run `refresh_cookies.py`.
**Paths in the unit files are placeholders** — edit them for the target host before
installing, and install with `sudo` (the files live in `/etc/systemd/system/`).

## Install

```bash
sudo cp deploy/*.service deploy/*.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now vortex-chromium.service
sudo systemctl enable --now vortex-cookies-refresh.timer
```

Verify before trusting it:

```bash
systemctl status vortex-chromium.service --no-pager    # must be "active (running)", not "activating (start-pre)"
curl -s http://127.0.0.1:9222/json/version             # must print Chrome version JSON
systemctl list-timers vortex-cookies-refresh.timer --no-pager
```

If `vortex-chromium.service` sits in `activating (start-pre)`, the `ExecStartPre` Xvfb
process is blocking the main `ExecStart`. Start Xvfb from its own unit (or drop the
`ExecStartPre` line if a display already exists) and the CDP port will come up.

## What each unit does

- `vortex-chromium.service` — Xvfb + stealth Chromium with `--remote-debugging-port=9222`,
  `--user-data-dir` under the service user's home.
- `vortex-cookies-refresh.service` — one-shot: runs `refresh_cookies.py` (extracts YouTube
  cookies from the browsing profile over CDP, writes Netscape `cookies/youtube.txt`, copies
  it into the `vortex-cookies` Docker volume), then restarts the bot container.
- `vortex-cookies-refresh.timer` — fires that service every 12 hours.

## Editing the placeholders

The units ship with paths from the original host. Replace:

- `/home/agent/...` in `ExecStart` / `--user-data-dir` — where the Chromium build and the
  checkout live on the new host.
- `User=agent` — the account that owns that home.
- the `ExecStart` interpreter in `vortex-cookies-refresh.service` — any Python that has
  the `websockets` package (the project venv works).

`TIKTOK_APIFY_FALLBACK` and the TikTok cookie trap are unrelated to these units; see
`docs/TROUBLESHOOTING.md` § 9.
