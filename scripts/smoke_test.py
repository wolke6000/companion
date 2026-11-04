"""Run the packaged Windows app, including two missing-file checks."""
import os
from pathlib import Path
import subprocess
import tempfile

stages = list(Path("builds").glob("*/stage"))
if len(stages) != 1:
    raise SystemExit(f"Expected one build stage, found {len(stages)}")
stage = stages[0].resolve()
python = stage / "python-3.11.8-embed-amd64" / "python.exe"
logs = Path("smoke-logs").resolve()
logs.mkdir(exist_ok=True)


def run_case(name, missing=None):
    env = os.environ.copy()
    for variable in ("PYTHONPATH", "PYTHONHOME"):
        env.pop(variable, None)
    original = stage / missing if missing else None
    backup = original.with_name(original.name + ".smoke-backup") if original else None
    with tempfile.TemporaryDirectory(prefix="companion-smoke-") as profile:
        env["APPDATA"] = profile
        env["LOCALAPPDATA"] = profile
        if original:
            original.rename(backup)
        try:
            try:
                result = subprocess.run(
                    [str(python), "-I", "gui.py", "--smoke-test"],
                    cwd=stage, env=env, stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT, timeout=45,
                )
            except subprocess.TimeoutExpired as exc:
                (logs / f"{name}.log").write_bytes((exc.stdout or b"") + b"\nTIMEOUT\n")
                raise RuntimeError(f"{name}: app did not exit within 45 seconds") from exc
            (logs / f"{name}.log").write_bytes(result.stdout)
            output = result.stdout.decode("utf-8", errors="replace")
            print(f"{name}: exit {result.returncode}\n{output}", flush=True)
            if missing:
                if result.returncode == 0 or missing not in output or "SMOKE_TEST_OK" in output:
                    raise RuntimeError(f"{name}: missing file was not detected")
            elif result.returncode != 0 or "SMOKE_TEST_OK" not in output:
                raise RuntimeError(f"{name}: packaged app failed startup")
        finally:
            if original:
                backup.rename(original)


run_case("startup")
run_case("missing-dll", "swinput.dll")
run_case("missing-theme", "sw_yellow.json")

