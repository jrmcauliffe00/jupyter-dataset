# Git Commit Hook

This repository includes a `pre-commit` hook script at `.githooks/pre-commit`.

The hook scans staged files for:
- common environment/secret file names (for example `.env`, `*.pem`, `*.key`)
- obvious secret-like strings in staged content (for example hardcoded passwords or API keys)

To enable repository hooks:

```bash
git config core.hooksPath .githooks
chmod +x .githooks/pre-commit
```
