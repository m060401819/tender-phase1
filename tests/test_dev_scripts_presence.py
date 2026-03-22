from pathlib import Path


def test_dev_scripts_presence() -> None:
    root = Path(__file__).resolve().parents[1]
    required_files = [
        root / "scripts" / "dev_up.sh",
        root / "scripts" / "dev_down.sh",
        root / "scripts" / "dev_up.bat",
        root / "scripts" / "dev_down.bat",
    ]

    missing = [str(path.relative_to(root)) for path in required_files if not path.exists()]
    assert not missing, f"Missing required dev script files: {', '.join(missing)}"
