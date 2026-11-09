"""Desktop notifications through tools the OS already ships with.

No Python dependencies: ``notify-send`` on Linux, ``osascript`` on macOS and a
PowerShell toast on Windows. Every failure is swallowed, because a missing
notification must never stop a focus session.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from typing import Callable, Mapping, Optional

Notifier = Callable[[str, str], None]

# AppUserModelID of Windows PowerShell; toasts from an unregistered ID are dropped.
_PS_APP_ID = r"{1AC14E77-02E7-4E5D-B744-2EB1AE5198B7}\WindowsPowerShell\v1.0\powershell.exe"

# Title and message come in through environment variables, so no quoting or
# escaping of user text (the --label) is needed inside the script.
_PS_SCRIPT = (
    "$ErrorActionPreference='Stop';"
    "[Windows.UI.Notifications.ToastNotificationManager,Windows.UI.Notifications,"
    "ContentType=WindowsRuntime]>$null;"
    "$t=[Windows.UI.Notifications.ToastNotificationManager]::GetTemplateContent("
    "[Windows.UI.Notifications.ToastTemplateType]::ToastText02);"
    "$x=$t.GetElementsByTagName('text');"
    "$x.Item(0).AppendChild($t.CreateTextNode($env:FOCUSBELL_NOTIFY_TITLE))>$null;"
    "$x.Item(1).AppendChild($t.CreateTextNode($env:FOCUSBELL_NOTIFY_MESSAGE))>$null;"
    "[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier("
    f"'{_PS_APP_ID}').Show([Windows.UI.Notifications.ToastNotification]::new($t))"
)

_OSASCRIPT = [
    "-e", "on run argv",
    "-e", "display notification (item 2 of argv) with title (item 1 of argv)",
    "-e", "end run",
]


def notifier_command(
    title: str,
    message: str,
    platform: Optional[str] = None,
    which: Callable[[str], Optional[str]] = shutil.which,
) -> Optional[tuple[list[str], dict[str, str]]]:
    """Return ``(argv, extra_env)`` that shows a notification, or None if unsupported.

    ``extra_env`` holds variables to add to the child's environment.
    """
    platform = sys.platform if platform is None else platform
    if platform.startswith("win"):
        exe = which("powershell") or which("pwsh")
        if not exe:
            return None
        argv = [exe, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
                "-Command", _PS_SCRIPT]
        return argv, {"FOCUSBELL_NOTIFY_TITLE": title, "FOCUSBELL_NOTIFY_MESSAGE": message}
    if platform == "darwin":
        exe = which("osascript")
        if not exe:
            return None
        return [exe, *_OSASCRIPT, title, message], {}
    exe = which("notify-send")
    if not exe:
        return None
    return [exe, "--app-name=focusbell", "--", title, message], {}


def system_notifier(
    platform: Optional[str] = None,
    which: Callable[[str], Optional[str]] = shutil.which,
    popen: Callable[..., object] = subprocess.Popen,
    environ: Optional[Mapping[str, str]] = None,
) -> Optional[Notifier]:
    """A notifier for this OS, or None when no notification tool is available.

    The helper process is started and not waited for, so a slow PowerShell
    start-up never delays the countdown.
    """
    platform = sys.platform if platform is None else platform
    if notifier_command("", "", platform, which) is None:
        return None
    base_env = dict(os.environ if environ is None else environ)

    def notify(title: str, message: str) -> None:
        try:
            found = notifier_command(title, message, platform, which)
            if found is None:
                return
            argv, extra = found
            kwargs: dict = {
                "stdin": subprocess.DEVNULL,
                "stdout": subprocess.DEVNULL,
                "stderr": subprocess.DEVNULL,
                "env": {**base_env, **extra},
            }
            if platform.startswith("win"):
                kwargs["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0)
            popen(argv, **kwargs)
        except Exception:  # noqa: BLE001 - notifications are best effort
            pass

    return notify

