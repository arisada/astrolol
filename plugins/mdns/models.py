from typing import Literal

from pydantic import BaseModel


class MdnsSettings(BaseModel):
    """What to advertise. astrolol cannot infer this itself: a reverse proxy (nginx for
    TLS, typically) usually sits between the network and the port astrolol actually binds,
    so the advertised host/port/scheme are independent of anything astrolol can observe
    at runtime.
    """

    # None = auto-detect this machine's local network addresses at startup.
    # Set explicitly when there's more than one interface, or the deployment fronts
    # astrolol with a reverse proxy on a different host than astrolol itself.
    advertised_host: str | None = None

    # No safe default: the port a client should connect to is whatever's exposed to the
    # network (443/80 behind nginx, or astrolol's own bound port with no proxy).
    advertised_port: int | None = None

    # TLS termination (if any) happens at the reverse proxy, not in astrolol itself —
    # this only tells clients which scheme to use when building the URL.
    scheme: Literal["http", "https"] = "http"

    # Distinguishes multiple astrolol instances on one network. Falls back to the
    # machine's hostname when unset.
    instance_name: str | None = None
