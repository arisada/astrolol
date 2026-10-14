from typing import Literal

from pydantic import BaseModel

# The port astrolol binds when started with `python -m astrolol.main`.
DEFAULT_PORT = 8000


class MdnsSettings(BaseModel):
    """What to advertise. The host name is always this machine's own (`<hostname>.local`).
    The port and scheme cannot be inferred: a reverse proxy (nginx for TLS, typically)
    usually sits between the network and the port astrolol actually binds, so they are
    settings rather than something astrolol can observe at runtime.
    """

    # None = the port astrolol itself listens on (DEFAULT_PORT). Set it when a reverse
    # proxy exposes astrolol on another one (443/80 behind nginx).
    advertised_port: int | None = None

    # TLS termination (if any) happens at the reverse proxy, not in astrolol itself —
    # this only tells clients which scheme to use when building the URL.
    scheme: Literal["http", "https"] = "http"

    # Distinguishes multiple astrolol instances on one network. Falls back to the
    # machine's hostname when unset.
    instance_name: str | None = None
