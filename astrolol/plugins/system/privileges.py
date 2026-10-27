"""Which host-management actions astrolol may perform, as polkit sees it.

The System page's privileged commands (nmcli, hostnamectl, timedatectl, systemctl reboot and
poweroff) run as astrolol's own user: the daemons behind them (NetworkManager, systemd) ask
polkit, and deploy/50-astrolol.rules says yes for the astrolol user. `pkcheck` asks the same
question without doing anything, so the page can say what works before anyone clicks.
"""
from __future__ import annotations

import asyncio
import os
import pwd
from pathlib import Path

# One action per capability is enough to know whether the rule is in place.
# Keep in sync with deploy/50-astrolol.rules.
ACTIONS = {
    "network": "org.freedesktop.NetworkManager.settings.modify.system",
    "reboot": "org.freedesktop.login1.reboot",
    "shutdown": "org.freedesktop.login1.power-off",
    "hostname": "org.freedesktop.hostname1.set-static-hostname",
    "timezone": "org.freedesktop.timedate1.set-timezone",
}

# The rule in a git checkout (a packaged install already has it in /usr/share/polkit-1/rules.d).
RULES_FILE = Path(__file__).resolve().parents[3] / "deploy" / "50-astrolol.rules"
INSTALLED_RULES = Path("/etc/polkit-1/rules.d/50-astrolol.rules")


async def _authorized(action_id: str) -> bool:
    """pkcheck: 0 = allowed; 1 = refused, 2 = would ask for a password; 127 = no polkit."""
    try:
        proc = await asyncio.create_subprocess_exec(
            "pkcheck", "--action-id", action_id, "--process", str(os.getpid()),
            stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL,
        )
    except FileNotFoundError:
        return False
    return await proc.wait() == 0


async def check() -> dict[str, bool]:
    """Each capability of ACTIONS: whether polkit lets astrolol do it without a password."""
    results = await asyncio.gather(*(_authorized(a) for a in ACTIONS.values()))
    return dict(zip(ACTIONS, results, strict=True))


def setup_commands() -> list[str]:
    """What to run as root to install the rule, for an install from a git checkout."""
    if not RULES_FILE.is_file():
        return []
    user = pwd.getpwuid(os.getuid()).pw_name
    if user == "astrolol":
        return [f"sudo install -m 644 {RULES_FILE} {INSTALLED_RULES}"]
    # The rule names the astrolol user: install it for the one this process runs as.
    return [f"sed 's/\"astrolol\"/\"{user}\"/' {RULES_FILE} | sudo tee {INSTALLED_RULES} >/dev/null"]
