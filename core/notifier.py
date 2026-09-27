"""
core/notifier.py — Desktop Notifications (P5.2)
Zero-dependency desktop notifications on Windows using PowerShell's native Forms API.
Safe fallback on non-Windows platforms. Never raises exceptions.
"""

import sys
import subprocess


def notify(title: str, body: str):
    """
    Best-effort desktop notification using PowerShell BalloonTip.
    Never blocks or raises exceptions.
    """
    if sys.platform != "win32":
        return
    try:
        # Escape single quotes and backticks for PowerShell string interpolation
        t = str(title).replace("`", "``").replace("'", "`'")
        b = str(body).replace("`", "``").replace("'", "`'")
        script = (
            "Add-Type -AssemblyName System.Windows.Forms;"
            "$n = New-Object System.Windows.Forms.NotifyIcon;"
            "$n.Icon = [System.Drawing.SystemIcons]::Information;"
            f"$n.BalloonTipTitle = '{t}';"
            f"$n.BalloonTipText = '{b}';"
            "$n.Visible = $true;"
            "$n.ShowBalloonTip(5000)"
        )
        subprocess.Popen(
            ["powershell", "-NoProfile", "-Command", script],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL
        )
    except Exception:
        pass  # Notifications are always best-effort
