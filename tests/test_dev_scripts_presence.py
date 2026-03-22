from pathlib import Path


def test_dev_scripts_presence() -> None:
    root = Path(__file__).resolve().parents[1]
    required_files = [
        root / "scripts" / "dev_up.sh",
        root / "scripts" / "dev_down.sh",
        root / "scripts" / "dev_up.bat",
        root / "scripts" / "dev_down.bat",
        root / "scripts" / "app_entrypoint.sh",
        root / "scripts" / "migrate_entrypoint.sh",
        root / "scripts" / "seed_demo_entrypoint.sh",
        root / "scripts" / "check_env.py",
        root / "scripts" / "wait_for_db.py",
    ]

    missing = [str(path.relative_to(root)) for path in required_files if not path.exists()]
    assert not missing, f"Missing required dev script files: {', '.join(missing)}"
