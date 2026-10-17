# AppByeScribe

Read Yuwell ET525A therapy recordings locally. Preserve original BYS files, accumulate a deduplicated history, and generate offline reports with qualified AHI estimates.

**Scope:** the observed ET525A format on Python 3.10+, macOS or Linux. BYS is vendor-specific and varies by model. This independent research tool is not clinically validated; Windows is not supported.

## Quick start

Run from the repository root:

```sh
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e .
appbyescribe "private/card-copies/YYYY-MM-DD/DEVICE_FOLDER" --library private/library
```

Use a complete, stable copy of the device folder. Open **`private/library/index.html`** for the latest report. Reuse the library for later imports; identical sessions are not counted twice. Use one library per device.

To rebuild without a new card copy:

```sh
appbyescribe --library private/library
```

For screen comparisons, copy `examples/observations_template.csv` to `private/observations.csv`, enter exact-session readings, then add `--observations private/observations.csv`. Saved observations are reused.

## What the report means

- **AHI:** candidate event counters / elapsed hours, withheld when integrity checks fail. A screen match supports that session; it does not validate all event labels, modes or firmware.
- **Periods:** AHI groups whole sessions by start date; calendar coverage splits time at midnight. Missing dates are unknown, not zero use.
- **Signals:** pressure, leak and breathing metrics have probable meanings. Waveform units and some fields remain unresolved; zero oxygen/pulse slots mean unavailable.
- **Completeness:** all imported bytes are archived, including unknown and malformed data. This does not prove the card recorded every machine operation or that elapsed time equals sleep time.

Full CSV/JSON exports remain available behind the concise report. No runtime network requests or third-party runtime dependencies are used.

## Files and documentation

| Location | Purpose |
|---|---|
| `src/appbyescribe/` | Decoder, analysis, AHI, report and import workflow |
| `tests/` | Synthetic fixtures and regression tests |
| `docs/WORKFLOW.md` | Daily use, outputs and recovery |
| `docs/FORMAT.md` | Byte layouts, confidence and limits |
| `docs/ARCHITECTURE.md` | Processing stages and data ownership |
| `docs/RESEARCH.md` | Research sources and evidence policy |
| `examples/` | Blank observation template |
| `scripts/`, `.githooks/`, `.github/` | Privacy audit and development checks |
| `private/` | Ignored card copies, observations, photos and generated libraries |

**Keep personal data in `private/`.** Generated libraries also contain their own `.gitignore`. Ignore rules do not protect already tracked files. Never publish a ZIP of the working directory; use `git archive HEAD` for a source-only archive.

For checks and contribution rules, see [CONTRIBUTING.md](CONTRIBUTING.md). [Security and privacy](SECURITY.md) · [MIT license](LICENSE).
