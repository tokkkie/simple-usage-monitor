# Simple Usage Monitor

Windsurf / OpenRouter の使用量をモニタリングする Tkinter + Playwright アプリ。

## 必要要件

- Python 3.12+
- [uv](https://astral.sh/uv/)

## 起動

```bash
chmod +x run.sh

# 通常起動（バックグラウンド）
./run.sh

# デバッグモード（ターミナルにログ表示）
./run.sh --debug
```

`run.sh` が venv 作成、依存インストール（Playwright, PyYAML）、Chromium セットアップ、アプリ起動を自動で行います。

## 使い方

1. 各サービスの **Login** ボタンをクリック → ブラウザが開く
2. Google 等でログイン（自動検出される）
3. ログイン完了後、データ取得してブラウザが閉じる
4. 以降は30分間隔で自動更新（Settings で変更可）
5. **Refresh** ボタンで手動更新

セッション Cookie は `sessions/` に保存され、再起動後も再利用されます。

## 設定

`config.yaml`:

```yaml
headless: false
refresh_interval: 30      # 分
services:
  windsurf:
    enabled: true
    url: https://windsurf.com/subscription/usage
  openrouter:
    enabled: true
    url: https://openrouter.ai/activity
thresholds:
  windsurf_daily: 30       # 残量%がこの値以下でオレンジ表示
  windsurf_weekly: 20
```

## プロジェクト構成

```
├── main.py           # Tkinter GUI アプリ
├── config.yaml       # 設定ファイル
├── run.sh            # 起動スクリプト (Linux/WSL)
└── scrapers/
    ├── __init__.py
    ├── base.py       # BaseScraper（Playwright セッション管理）
    ├── windsurf.py   # Windsurf スクレイパー
    └── openrouter.py # OpenRouter スクレイパー
```

## トラブルシューティング

- **セッション切れ**: 対象サービスに Login ボタンが再表示されるのでクリック
- **ブラウザが閉じない**: GUI ウィンドウを閉じれば自動クリーンアップ
- **Google ログインブロック**: 試行回数が多すぎた場合、1〜2時間待つ
