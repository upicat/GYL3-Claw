"""launchd LaunchAgent management for claw daemon."""
from __future__ import annotations

import os
import plistlib
import subprocess
import sys
from pathlib import Path

LABEL = "com.gyl3.claw"
BASE_DIR = Path(__file__).resolve().parent.parent
PLIST_DIR = Path.home() / "Library" / "LaunchAgents"
PLIST_PATH = PLIST_DIR / f"{LABEL}.plist"
LOG_DIR = BASE_DIR / "logs"
PID_FILE = BASE_DIR / "data" / "claw.pid"


def _uid() -> int:
    return os.getuid()


def _find_claw_bin() -> str:
    """Locate the claw executable inside the current venv."""
    # When installed via pip/setuptools, the entry-point script sits next to python
    venv_bin = Path(sys.executable).parent / "claw"
    if venv_bin.exists():
        return str(venv_bin)
    # Fallback: use sys.executable -m app.cli
    return str(venv_bin)


def generate_plist(port: int | None = None, webhook: bool = False) -> dict:
    """Build the launchd plist dict."""
    claw_bin = _find_claw_bin()

    args = [claw_bin, "_run"]
    if port is not None:
        args += ["--port", str(port)]
    if webhook:
        args.append("--webhook")

    LOG_DIR.mkdir(parents=True, exist_ok=True)

    env = {}
    # Forward critical environment variables
    for key in ("PATH", "HOME", "LANG", "FEISHU_APP_ID", "FEISHU_APP_SECRET",
                "OPENAI_API_KEY", "OPENAI_BASE_URL", "AI_BASE_URL", "AI_API_KEY",
                "AI_MODEL"):
        val = os.environ.get(key)
        if val:
            env[key] = val

    plist: dict = {
        "Label": LABEL,
        "ProgramArguments": args,
        "KeepAlive": True,
        "ThrottleInterval": 5,
        "RunAtLoad": True,
        "WorkingDirectory": str(BASE_DIR),
        "StandardOutPath": str(LOG_DIR / "claw_stdout.log"),
        "StandardErrorPath": str(LOG_DIR / "claw_stderr.log"),
    }
    if env:
        plist["EnvironmentVariables"] = env

    return plist


def install_and_start(port: int | None = None, webhook: bool = False) -> None:
    """Write plist and load the LaunchAgent."""
    PLIST_DIR.mkdir(parents=True, exist_ok=True)
    plist = generate_plist(port, webhook)

    with open(PLIST_PATH, "wb") as f:
        plistlib.dump(plist, f)

    uid = _uid()
    # Try modern launchctl bootstrap, fallback to legacy load
    ret = subprocess.run(
        ["launchctl", "bootstrap", f"gui/{uid}", str(PLIST_PATH)],
        capture_output=True,
    )
    if ret.returncode != 0:
        subprocess.run(
            ["launchctl", "load", str(PLIST_PATH)],
            capture_output=True,
        )


def stop_and_uninstall() -> None:
    """Unload the LaunchAgent, remove plist and PID file."""
    uid = _uid()
    # Try modern bootout, fallback to legacy unload
    ret = subprocess.run(
        ["launchctl", "bootout", f"gui/{uid}/{LABEL}"],
        capture_output=True,
    )
    if ret.returncode != 0 and PLIST_PATH.exists():
        subprocess.run(
            ["launchctl", "unload", str(PLIST_PATH)],
            capture_output=True,
        )

    PLIST_PATH.unlink(missing_ok=True)
    PID_FILE.unlink(missing_ok=True)


def is_running() -> bool:
    """Check if the LaunchAgent is loaded and running."""
    uid = _uid()
    ret = subprocess.run(
        ["launchctl", "print", f"gui/{uid}/{LABEL}"],
        capture_output=True,
    )
    return ret.returncode == 0


