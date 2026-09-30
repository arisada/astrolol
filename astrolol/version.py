"""Protocol version for the astrolol client/server contract.

Bump PROTOCOL_VERSION only for breaking changes: removing or renaming a field,
or changing what a field means. Additive changes (new event types, new optional
fields, new endpoints) never bump it. Clients must ignore unknown event types
and unknown fields on known events.
"""

PROTOCOL_VERSION = 1
