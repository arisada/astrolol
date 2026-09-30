"""Protocol version for the astrolol client/server contract.

Bump PROTOCOL_VERSION only for breaking changes: removing or renaming a field,
or changing what a field means. Additive changes (new event types, new optional
fields, new endpoints) never bump it. Clients must ignore unknown event types
and unknown fields on known events.
"""

from importlib.metadata import PackageNotFoundError, version as _pkg_version

PROTOCOL_VERSION = 1

try:
    SERVER_VERSION = _pkg_version("astrolol")
except PackageNotFoundError:
    SERVER_VERSION = "0.0.0-dev"
