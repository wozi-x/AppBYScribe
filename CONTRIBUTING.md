# Contributing

Use Python 3.10+ on macOS or Linux. Install `.[dev]`, then run pytest, Ruff checks and the public-tree audit described in the README.

Use synthetic fixtures only. Do not attach real card files, photos, device serials, observation logs or generated therapy reports to public issues or pull requests. Store local research material in `private/`, which is ignored. Inspect the staged diff and run `python scripts/check_public_tree.py` before committing.

For a new field mapping, document byte offsets, byte order, scaling, confidence and independent evidence. Preserve raw values and distinguish structural certainty from physiological interpretation. Add tests for malformed data, missing fields and boundary conditions where relevant. Do not silently reinterpret unsupported formats or force a calculation to match one screen value.

Keep all runtime processing local. Network calls and input-file/device-setting writes are outside the current workflow. Changes to AHI interpretation require explicit evidence and should preserve alternative hypotheses for review.

Contributions are provided under the project's MIT license.
