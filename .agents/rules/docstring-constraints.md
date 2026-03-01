---
trigger: always_on
glob: "**/*.{py,js,ts}"
description: Mandatory docstring coverage for functional code
---

## Docstring requirements

1. Any new or modified functional code must include docstrings/comments in the language-appropriate format.
2. Coverage is mandatory for:
   - modules/files,
   - classes,
   - functions/methods.
3. Existing docstrings in touched code must be updated when outdated or inaccurate.
4. Exclusions: `*.md`, `*.html`, `*.json`, and generated/vendor build artifacts.

## Format by language

- **Python**: Use triple-quoted docstrings (`"""docstring"""`).
- **JavaScript / TypeScript**: Use JSDoc-style block comments (`/** ... */`) above module/class/function/method declarations.
