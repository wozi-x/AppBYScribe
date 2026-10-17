import importlib.util
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
