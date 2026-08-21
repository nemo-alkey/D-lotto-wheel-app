#!/usr/bin/env python3
"""
monitor_service.py — Service wrapper for live_draw_monitor.py.

Runs the monitor as a supervised background daemon: restarts it on crash
with exponential backoff, caps restarts, and tees all output to
data/logs/monitor_service.log.

Installation as a real service
------------------------------
Windows (NSSM — https://nssm.cc/download):
    nssm install LottoDrawMonitor "D:\\lotto-wheel-app\\venv\\Scripts\\python.exe" \
        "D:\\lotto-wheel-app\\monitor_service.py"
    nssm set LottoDrawMonitor AppDirectory "D:\\lotto-wheel-app"
    nssm start LottoDrawMonitor

  Or with Task Scheduler (no extra tools):
    python monitor_service.py --print-task-scheduler

Linux (systemd):
    python monitor_service.py --print-systemd-unit > /etc/systemd/system/lotto-monitor.service
    systemctl daemon-reload && systemctl enable --now lotto-monitor

Direct use:
    python monitor_service.py            # supervise in the foreground
    python monitor_service.py --dry-run  # supervise the monitor in dry-run mode
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
MONITOR_SCRIPT = HERE / "live_draw_monitor.py"
LOG_FILE = HERE / "data" / "logs" / "monitor_service.log"

MAX_RESTARTS_PER_HOUR = 5
BACKOFF_START = 5  # seconds; doubles per consecutive crash
BACKOFF_MAX = 300


def log(msg: str) -> None:
    """Append a timestamped line to the service log and stdout."""
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line, flush=True)
    try:
        LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except OSError:
        pass


def supervise(extra_args: list[str] | None = None) -> None:
    """Run the monitor, restarting it on crash with exponential backoff."""
    cmd = [sys.executable, str(MONITOR_SCRIPT)] + (extra_args or [])
    log(f"Supervisor starting: {' '.join(cmd)}")

    restarts: list[float] = []
    backoff = BACKOFF_START

    while True:
        started = time.time()
        try:
            proc = subprocess.run(cmd, cwd=str(HERE), check=False)
            exit_code = proc.returncode
        except KeyboardInterrupt:
            log("Supervisor stopped by user.")
            return
        except Exception as e:
            log(f"Failed to launch monitor: {e}")
            exit_code = -1

        ran_for = time.time() - started
        log(f"Monitor exited with code {exit_code} after {ran_for:.0f}s.")

        # A clean exit (code 0) means the monitor finished deliberately
        # (e.g. --once): stop supervising.
        if exit_code == 0:
            log("Clean exit — supervisor stopping.")
            return

        # Restart cap: max MAX_RESTARTS_PER_HOUR crashes per rolling hour
        now = time.time()
        restarts = [t for t in restarts if now - t < 3600]
        if len(restarts) >= MAX_RESTARTS_PER_HOUR:
            log(
                f"Too many crashes ({len(restarts)}/hour) — giving up. "
                f"Check {LOG_FILE} and live_monitor.log."
            )
            return
        restarts.append(now)

        log(f"Restarting in {backoff}s...")
        time.sleep(backoff)
        backoff = min(backoff * 2, BACKOFF_MAX)


SYSTEMD_UNIT = """\
[Unit]
Description=NZ Lotto live draw monitor
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
WorkingDirectory={workdir}
ExecStart={python} {script}
Restart=on-failure
RestartSec=30

[Install]
WantedBy=multi-user.target
"""

TASK_SCHEDULER_XML = """\
<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.2" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <Triggers>
    <BootTrigger><Enabled>true</Enabled></BootTrigger>
  </Triggers>
  <Settings>
    <RestartOnFailure><Interval>PT1M</Interval><Count>5</Count></RestartOnFailure>
    <ExecutionTimeLimit>PT0S</ExecutionTimeLimit>
  </Settings>
  <Actions>
    <Exec>
      <Command>{python}</Command>
      <Arguments>{script}</Arguments>
      <WorkingDirectory>{workdir}</WorkingDirectory>
    </Exec>
  </Actions>
</Task>

Import with:  schtasks /Create /TN "LottoDrawMonitor" /XML lotto-monitor-task.xml
"""


def main() -> None:
    parser = argparse.ArgumentParser(description="Service supervisor for live_draw_monitor.py.")
    parser.add_argument(
        "--dry-run", action="store_true", help="Pass --dry-run through to the monitor."
    )
    parser.add_argument(
        "--print-systemd-unit",
        action="store_true",
        help="Print a systemd unit file and exit.",
    )
    parser.add_argument(
        "--print-task-scheduler",
        action="store_true",
        help="Print a Windows Task Scheduler XML and exit.",
    )
    args = parser.parse_args()

    if args.print_systemd_unit:
        print(
            SYSTEMD_UNIT.format(
                workdir=HERE,
                python=sys.executable,
                script=Path(__file__).resolve(),
            )
        )
        return
    if args.print_task_scheduler:
        print(
            TASK_SCHEDULER_XML.format(
                workdir=HERE,
                python=sys.executable,
                script=Path(__file__).resolve(),
            )
        )
        return

    supervise(extra_args=["--dry-run"] if args.dry_run else [])


if __name__ == "__main__":
    main()
