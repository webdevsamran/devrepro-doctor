# Exit Codes (stable contract)

Onboarding scripts and CI gates may rely on these codes. Meanings never
change; new codes are only appended.

| Code | Meaning |
| --- | --- |
| `0` | READY — scan succeeded, no blocking problems |
| `1` | READY_WITH_WARNINGS — warnings/unknowns found |
| `2` | BLOCKED — one or more BLOCKED/ERROR findings |
| `3` | INTERNAL_ERROR — DevRepro itself failed |
| `4` | USAGE_ERROR — invalid arguments or unreadable policy |

`devrepro preflight` and `devrepro check --policy` are the intended CI
entry points:

```yaml
# GitHub Actions example
- run: python -m devrepro preflight --policy .devrepro.toml
```
