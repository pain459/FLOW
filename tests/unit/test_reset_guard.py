"""Exercise the destructive scope guard with a fake Docker executable."""

import os
import subprocess
from pathlib import Path

import pytest


@pytest.mark.parametrize(
    "ack,project,allowed",
    [
        (None, "chaosloop", False),
        ("chaosloop", "other", False),
        ("chaosloop", "chaosloop", True),
    ],
)
def test_reset_requires_acknowledgement_and_exact_project(tmp_path, ack, project, allowed):
    fake = tmp_path / "docker"
    calls = tmp_path / "calls"
    fake.write_text("""#!/usr/bin/env python3
import json,os,sys
args=sys.argv[1:]
if args[0]=='compose':
    position=1
    while position < len(args) and args[position] in ('-f','--file','--profile'):
        position+=2
    operation=args[position:]
else:
    operation=[]
if operation==['config','--format','json']:
    print(json.dumps({'name':os.environ['FAKE_PROJECT']}))
elif sys.argv[1]=='run':
    print(json.load(sys.stdin)['name'])
else:
    with open(os.environ['FAKE_CALLS'],'a') as f: f.write(' '.join(sys.argv[1:])+'\\n')
""")
    fake.chmod(0o755)
    env = {
        **os.environ,
        "PATH": str(tmp_path) + os.pathsep + os.environ["PATH"],
        "FAKE_PROJECT": project,
        "FAKE_CALLS": str(calls),
        "FAKE_SCRIPT": str(fake),
    }
    env.pop("CONFIRM_RESET", None)
    if ack:
        env["CONFIRM_RESET"] = ack
    script = Path(__file__).resolve().parents[2] / "scripts/reset-lab.sh"
    # /tmp is deliberately noexec in the container; invoke the fake through Python.
    result = subprocess.run(
        ["sh", "-c", 'docker() { python "$FAKE_SCRIPT" "$@"; }; . "$0"', str(script)],
        env=env,
        capture_output=True,
        text=True,
    )
    assert (result.returncode == 0) == allowed
    if allowed:
        command = calls.read_text()
        assert "down --volumes --remove-orphans" in command
        assert "-f compose.yaml -f compose.phase4.yaml" in command
        assert "prune" not in command
    else:
        assert not calls.exists()
