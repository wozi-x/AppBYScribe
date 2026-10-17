# AppByeScribe

**Your breathing data, made readable.**

AppByeScribe is a local, open-source toolkit for extracting Yuwell ET525A PAP recordings from BYS files. It preserves the original bytes, builds a deduplicated history and produces offline reports with explicit confidence labels.

Initial support is limited to the observed ET525A format. This is independent research software, not a manufacturer product or a clinically validated diagnostic tool.

## Features

- Read-only card-folder imports with exact raw-byte archives and SHA-256 checks.
- Complete minute-record exports, raw waveform samples, settings candidates and unknown-field preservation.
- Session statistics and daily, weekly and monthly coverage summaries.
- Qualified AHI estimates with exact-session machine-screen comparisons.
- Repeated-import deduplication, conflict reporting and versioned offline HTML reports.
- No network requests or third-party runtime dependencies.

## Install

Python 3.10+ on macOS or Linux is required. The filesystem safeguards use POSIX features; Windows is not supported in this release.

```sh
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e .
appbyescribe --version
```

## Use

Copy the complete device folder from a stopped, stable card into `private/card-copies/`. Keep the internal filenames unchanged. Import a dated copy with:

```sh
appbyescribe "private/card-copies/YYYY-MM-DD/DEVICE_FOLDER" --library private/library
```

Open **`private/library/index.html`** to reach the latest report. Reuse this library for later imports. Reimporting an identical copy does not duplicate sessions. Each device serial needs its own library.

To compare against exact-session screen readings, copy `examples/observations_template.csv` to `private/observations.csv`, fill it in, then run:

```sh
appbyescribe --library private/library --observations private/observations.csv
```

The CLI also works as `python -m appbyescribe`. See [the daily workflow](docs/WORKFLOW.md) for observation fields, report locations, recovery and limitations.

## Interpretation and scope

AHI is estimated from candidate event-counter sums divided by elapsed session hours, only when timestamps, record counts and counter totals reconcile. Exact-session screen matches provide supporting evidence; estimates do not automatically become validated for every mode or firmware. Event subtype names, waveform physical units and several settings remain unresolved.

Calendar summaries split elapsed intervals at midnight. AHI period summaries instead group whole sessions by start date, preserving overnight counters. Missing dates remain unknown; these are not adherence calculations or reconstructed full-period therapy histories.

See [format documentation](docs/FORMAT.md) and [research sources](docs/RESEARCH.md).

## Repository layout

```text
src/appbyescribe/       Installable package and CLI
  decoder.py           Binary layout, provenance and stable-source checks
  analysis.py          Byte accounting, statistics and waveform CSV streaming
  ahi.py               Qualified estimates and screen comparisons
  report.py            Offline HTML/SVG reports
  workflow.py          Imports, history deduplication and report publication
tests/                 Synthetic fixtures and regression tests
docs/                  Workflow, format, research and architecture
examples/              Empty observation template
scripts/               Public-tree privacy audit
.github/workflows/     Tests and privacy checks
private/               Local personal data; ignored and not distributed
```

## Development

```sh
python -m pip install -e '.[dev]'
git config core.hooksPath .githooks
python -m pytest -q
ruff check .
ruff format --check .
python scripts/check_public_tree.py
```

The optional local pre-commit hook runs the same privacy audit automatically. It checks Git's index, including staged file contents. `.gitignore` prevents accidental ordinary additions; it is not encryption and does not protect a file that has already been committed. Keep real recordings, screenshots, serials, observation logs and reports under `private/`. Public fixtures must be synthetic.

Read [CONTRIBUTING.md](CONTRIBUTING.md) before submitting changes. Licensed under [MIT](LICENSE).
