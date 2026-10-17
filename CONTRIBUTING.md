# Contributing

From the repository root with the virtual environment active:

```sh
python -m pip install -e '.[dev]'
git config core.hooksPath .githooks
python -m pytest -q
ruff check .
ruff format --check .
python scripts/check_public_tree.py
```

The privacy audit reads **staged blobs**, not unstaged edits. Review `git diff --cached` and rerun the audit after staging. The optional pre-commit hook runs it automatically; CI runs it against tracked files.

- Use synthetic fixtures only. Keep real recordings, identifiers, photos, observations and reports under `private/`; never attach them to public issues or pull requests.
- For field mappings, record offsets, byte order, scale, confidence and independent evidence in `docs/FORMAT.md`. Preserve unknown bytes. Add meaningful boundary and malformed-input tests.
- AHI changes need evidence beyond one matching display. Retain failed checks and alternative hypotheses; never tune results to force a match.
- Keep processing local and source files read-only. Tests are grouped by decoder, analysis, integrity, workflow, report and publication safeguards.

Contributions use the MIT license. Build public source archives with `git archive`, never by zipping the working directory.
