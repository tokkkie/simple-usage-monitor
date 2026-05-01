# README_ja

## 特徴

- **AGENTS.md**: AI開発ルール（共通ルール）
- **.githooks/**: Git Hookで物理的に強制される制約
- **gitleaks + パターンマッチ**: 機密情報・環境固有情報の多層ガード（ローカル optional + CI 必須）

## セットアップ

初回のみ `.githooks/README.md` の手順に従って Git Hook を有効化してください。

## プロジェクト構成

```
.
├── AGENTS.md                          # AI開発ルール（共通）
├── .githooks/                         # Git Hook と機密情報スキャナ（詳細は .githooks/README.md）
├── .github/
│   ├── pull_request_template.md       # PRテンプレート
│   └── workflows/
│       ├── pr-body-validator.yml      # PRタイトル・本文バリデーション
│       └── sensitive-info-guard.yml   # PR本文・コメントの機密情報検知（.githooks/ と連携）
├── README.md                          # このファイル(README, README_ja)
├── main.go                            # アプリケーションエントリポイント
├── pkg/                               # プロジェクト固有のパッケージ
│   ├── handler/                       # HTTPハンドラ
│   ├── service/                       # ビジネスロジック
│   └── model/                         # データモデル
└── frontend/                          # フロントエンド（必要な場合）
    └── src/
```

※ プロジェクトに合わせてカスタマイズしてください

## テンプレートの使い方

1. GitHubの「Use this template」ボタンで新規リポジトリを作成
2. リポジトリをクローン
3. 上記セットアップ手順を実行
4. プロジェクト固有の構成に合わせてカスタマイズ
5. AGENTS.mdを参考に、プロジェクト固有のルールを追加（必要な場合）

## 機密情報・環境固有情報の混入防止

Git/GitHub に永続化される全ての文字列（commit message, コード, PR本文, コメント等）への混入を、ローカル hook (`.githooks/`) と GitHub Actions の多層で block します。

**検出層:**

| 層　　　　　　　　　　　　　　　　　　　　　　　　　| 検出対象　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　| 発火　　　　　　　　　　　　　　　　　　　　　　　　|
| -----------------------------------------------------| -----------------------------------------------------------------------------| -----------------------------------------------------|
| パターンマッチ (`.githooks/sensitive-patterns.txt`) | ローカル絶対パス、RFC1918 IP、プロジェクト固有識別子等の明示パターン　　　　| commit / push / PR　　　　　　　　　　　　　　　　　|
| gitleaks　　　　　　　　　　　　　　　　　　　　　　| 既知シークレット形式（AWS/GCP/Stripe/Slack token 等）、高エントロピー文字列 | commit / push（ローカルは optional）/ PR（CI 必須） |

**既定のパターンマッチ検出対象:**

- ローカル絶対パス（`/home/<user>/`, `/Users/<user>/`, `C:\Users\<user>\`）
- プライベートネットワーク IP（RFC1918: `10.x`, `172.16-31.x`, `192.168.x`）
- プライベートリポジトリ識別子（プロジェクト固有で追記）
- GitHub 他リポジトリ参照の汎用パターン（警告のみ）

パターン定義の追記・書式・ライブラリ API・ローカル gitleaks のインストール・Branch Protection への組み込み手順は `.githooks/README.md` を参照してください。

## 開発ルール

- Git Hookで物理的に強制される制約に従う
- 不明点はAGENTS.mdのルールに従い確認する
- 環境/Git制約違反時は `.githooks/` のエラーログに従い修正する
