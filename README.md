# Simple Usage Monitor

Tkinter GUI + Playwright scraper for monitoring Windsurf and OpenRouter usage.

![Screenshot](docs/screenshot.png)

## Requirements

- Python 3.12+
- [uv](https://astral.sh/uv/)

## Quick Start

```bash
chmod +x run.sh

# Normal (background)
./run.sh

# Debug (foreground, verbose logs)
./run.sh --debug
```

`run.sh` automatically creates a venv, installs dependencies (Playwright, PyYAML), and launches the app.
Only one instance runs at a time; launching again terminates the previous process.

## Usage

1. **Click a service panel** (WindSurf / OpenRouter) to open the login browser
2. Log in via Google or other auth. MFA is supported (up to 5 minutes to complete)
3. After login is detected, the browser closes automatically
4. Data is fetched headlessly in the background
5. Auto-refresh runs at the configured interval (default: 30 min)
6. Click **RELOAD** for a manual refresh
7. Click the **"Usage Monitor" title** to open Settings

Session cookies are stored in `sessions/` and reused across restarts.
Window and settings dialog sizes are saved automatically on close.

## Config

`config.yaml` is auto-generated on first launch (`.gitignored`).

```yaml
headless: false
refresh_interval: 30      # minutes
window_size: 500x520      # main window size (saved on exit)
settings_size: 504x359    # settings dialog size (saved on close)
services:
  windsurf:
    enabled: true
    url: https://windsurf.com/subscription/usage
  openrouter:
    enabled: true
    url: https://openrouter.ai/activity
thresholds:
  windsurf_daily: 30       # % remaining → orange highlight
  windsurf_weekly: 20
```

## Project Structure

```
├── main.py           # Tkinter GUI app
├── config.yaml       # Configuration (auto-generated, gitignored)
├── run.sh            # Launch script (Linux)
└── scrapers/
    ├── __init__.py
    ├── base.py       # BaseScraper (Playwright session management)
    ├── windsurf.py   # Windsurf scraper
    └── openrouter.py # OpenRouter scraper
```

## Troubleshooting

- **Not logged in**: Click the service panel to open the login browser
- **Session expired**: Click the panel again to re-login
- **MFA timeout**: You have up to 5 minutes to complete login including MFA
- **Browser won't close**: Close the GUI window; the browser will be cleaned up
- **Google login blocked**: Wait 1-2 hours if too many attempts triggered a security lockout
