import importlib.util
import subprocess
from pathlib import Path

SPEC = importlib.util.spec_from_file_location(
    "public_guard", Path(__file__).parents[1] / "scripts/check_public_tree.py"
)
guard = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(guard)


def test_private_directory_and_binary_files_rejected():
    assert guard.violations("private/notes.md", b"anything")
    assert guard.violations("session.bys", b"anything")


def test_only_blank_observation_template_allowed():
    assert not guard.violations("examples/observations_template.csv", b"column1,column2\n")
    assert guard.violations("examples/observations_template.csv", b"column1,column2\nvalue,value\n")


def test_fixture_serial_allowed_but_other_identifiers_rejected():
    assert not guard.violations("tests/example.py", b"ET525A-TEST00001")
    assert guard.violations("notes.md", b"ET525A-" + b"SECRET001")


def test_absolute_home_and_embedded_raw_data_rejected():
    assert guard.violations("notes.md", b"/" + b"Users" + b"/someone/file")
    assert guard.violations("example.json", b'{"raw_hex":"' + b"00" * 100 + b'"}')


def test_generated_report_files_rejected_even_outside_private():
    for path in [
        "nested/reports/notes.txt",
        "outputs/notes.txt",
        "report.html",
        "chart.svg",
        "LATEST.json",
        "history_provenance.json",
    ]:
        assert guard.violations(path, b"synthetic")


def test_gitignore_covers_nested_reports_and_allows_public_template(tmp_path):
    root = Path(__file__).parents[1]
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    (tmp_path / ".gitignore").write_bytes((root / ".gitignore").read_bytes())
    paths = [
        "report.html",
        "nested/reports/notes.txt",
        "nested/output/analysis.json",
        "outputs/notes.txt",
        "private/observations.csv",
        "chart.svg",
    ]
    result = subprocess.run(
        ["git", "check-ignore", "--stdin"],
        cwd=tmp_path,
        input="\n".join(paths),
        text=True,
        capture_output=True,
        check=True,
    )
    assert result.stdout.splitlines() == paths
    assert (
        subprocess.run(
            ["git", "check-ignore", "-q", "examples/observations_template.csv"], cwd=tmp_path
        ).returncode
        == 1
    )
