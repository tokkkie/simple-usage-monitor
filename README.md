# README.md

## Features

- **AGENTS.md**: AI development rules (common rules)
- **.githooks/**: Constraints physically enforced via Git Hooks
- **gitleaks + pattern matching**: Multi-layered protection against sensitive/environment-specific information leakage (local optional + CI required)

## Setup

On first use, enable Git Hooks by following the instructions in `.githooks/README.md`.

## Project Structure

```
.
├── AGENTS.md                          # AI development rules (common)
├── .githooks/                         # Git Hooks and sensitive info scanner (see .githooks/README.md)
├── .github/
│   ├── pull_request_template.md       # PR template
│   └── workflows/
│       ├── pr-body-validator.yml      # PR title/body validation
│       └── sensitive-info-guard.yml   # Sensitive info detection for PR body/comments (integrated with .githooks/)
├── README.md                          # This file(README, README_ja)
├── main.go                            # Application entry point
├── pkg/                               # Project-specific packages
│   ├── handler/                       # HTTP handlers
│   ├── service/                       # Business logic
│   └── model/                         # Data models
└── frontend/                          # Frontend (if needed)
    └── src/
```

※ Customize as needed for your project

## How to Use This Template

1. Create a new repository using the "Use this template" button on GitHub
2. Clone the repository
3. Follow the setup instructions above
4. Customize to match your project-specific structure
5. Add project-specific rules referencing AGENTS.md (if needed)

## Preventing Sensitive / Environment-Specific Information Leakage

All strings persisted in Git/GitHub (commit messages, code, PR body, comments, etc.) are blocked from containing sensitive information through multiple layers: local hooks (`.githooks/`) and GitHub Actions.

**Detection Layers:**

| Layer | Detection Target | Trigger |
|---|---|---|
| Pattern matching (`.githooks/sensitive-patterns.txt`) | Local absolute paths, RFC1918 IPs, project-specific identifiers, and other explicit patterns | commit / push / PR |
| gitleaks | Known secret formats (AWS/GCP/Stripe/Slack tokens, etc.), high-entropy strings | commit / push (local optional) / PR (CI required) |

**Default Pattern Match Detection Targets:**

- Local absolute paths (`/home/<user>/`, `/Users/<user>/`, `C:\Users\<user>\`)
- Private network IPs (RFC1918: `10.x`, `172.16-31.x`, `192.168.x`)
- Private repository identifiers (add project-specific entries as needed)
- Generic patterns for references to other GitHub repositories (warning only)

For instructions on adding pattern definitions, format, library API, local gitleaks installation, and Branch Protection integration, see `.githooks/README.md`.

## Development Rules

- Follow the constraints physically enforced by Git Hooks
- For any uncertainties, refer to the rules in AGENTS.md
- If environment/Git constraint violations occur, follow the error logs in `.githooks/` to fix them
