from pathlib import Path

from fdc.sec_storage import default_output_dir

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def test_default_output_dir_uses_central_sec_root():
    assert default_output_dir("msft") == PROJECT_ROOT / "sec" / "MSFT"
