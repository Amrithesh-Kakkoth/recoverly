"""deploy/backup.sh against a fake `docker`, so it needs neither Docker nor Postgres."""
import gzip
import os
import pathlib
import stat
import subprocess
import time

import pytest

SCRIPT = pathlib.Path(__file__).resolve().parents[2] / "deploy/backup.sh"
GOOD = "SELECT 1;\n-- PostgreSQL database dump complete\n"


def run(tmp_path, dump: str, exit_code: int = 0, **env):
    fake = tmp_path / "bin"
    fake.mkdir(exist_ok=True)
    (tmp_path / "dump.sql").write_text(dump)
    docker = fake / "docker"
    docker.write_text(f'#!/bin/sh\ncat "{tmp_path}/dump.sql"\nexit {exit_code}\n')
    docker.chmod(docker.stat().st_mode | stat.S_IEXEC)
    backups = tmp_path / "backups"
    result = subprocess.run(["bash", str(SCRIPT)], capture_output=True, text=True, env={
        **os.environ, "PATH": f"{fake}:{os.environ['PATH']}", "BACKUP_REPO": str(tmp_path),
        "BACKUP_DIR": str(backups), **env})
    return result, backups


def old_dump(backups: pathlib.Path) -> pathlib.Path:
    backups.mkdir(exist_ok=True)
    old = backups / "recoverly-old.sql.gz"
    old.write_bytes(gzip.compress(GOOD.encode()))
    ten_days_ago = time.time() - 10 * 86400
    os.utime(old, (ten_days_ago, ten_days_ago))
    return old


def test_good_dump_is_saved_private_and_old_ones_are_pruned(tmp_path):
    old = old_dump(tmp_path / "backups")
    result, backups = run(tmp_path, GOOD)
    assert result.returncode == 0, result.stderr
    files = list(backups.glob("recoverly-*.sql.gz"))
    assert len(files) == 1 and files[0] != old
    assert gzip.decompress(files[0].read_bytes()).decode() == GOOD
    assert stat.S_IMODE(files[0].stat().st_mode) == 0o600


@pytest.mark.parametrize("dump,exit_code", [("SELECT 1;\n", 0), (GOOD, 1)])
def test_failed_dump_leaves_no_file_and_keeps_old_backups(tmp_path, dump, exit_code):
    old = old_dump(tmp_path / "backups")
    result, backups = run(tmp_path, dump, exit_code)
    assert result.returncode != 0
    assert [p.name for p in backups.iterdir()] == [old.name]
