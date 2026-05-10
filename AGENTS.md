# AI Agent SSOT Hub

本プロジェクトのAIエージェントは、以下の`.ai-rules/`配下の規約を「不変の前提」として動作せよ。

## 1. Core Rules (SSOT)
- [00_identity.md](./.ai-rules/00_identity.md) : 事実至上主義・感情排除・最小コンテキスト。
- [10_tech_stack.md](./.ai-rules/10_tech_stack.md) : 実行環境・ディレクトリ構造。
- [20_coding.md](./.ai-rules/20_coding.md) : コード規約・秘匿情報禁止・最小差分。
- [30_git.md](./.ai-rules/30_git.md) : コミット規約・PRバリデーション。

## 2. Tool-Specific Integration
各ツールは以下の設定を通じて上記規約を読み込むこと。
- **Continue**: `.continuerc.json`
- **Windsurf**: `.windsurfrules`

## 3. Deployment Constraints
- `.githooks/` によるローカルガード。
- `.github/workflows/` によるCI/CDゲート。
