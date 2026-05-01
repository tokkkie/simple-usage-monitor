# Simple Usage Monitor

Tkinter GUI + Playwright scraper for monitoring Windsurf and OpenRouter usage.

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

## Usage

1. Click **Login** on each service panel to open its browser
2. Log in via Google (or other auth). Login is auto-detected
3. After login, data is fetched and the browser closes
4. Auto-refresh runs every 30 minutes (configurable in Settings)
5. Click **Refresh** for manual update

Session cookies are stored in `sessions/` and reused across restarts.

## Config

`config.yaml`:

```yaml
headless: false
refresh_interval: 30      # minutes
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
├── config.yaml       # Configuration
├── run.sh            # Launch script (Linux/WSL)
└── scrapers/
    ├── __init__.py
    ├── base.py       # BaseScraper (Playwright session management)
    ├── windsurf.py   # Windsurf scraper
    └── openrouter.py # OpenRouter scraper
```

## Troubleshooting

- **Session expired**: Click the Login button that reappears on the affected service
- **Browser won't close**: Close the GUI window; the browser will be cleaned up
- **Google login blocked**: Wait 1-2 hours if too many attempts triggered a security lockout
