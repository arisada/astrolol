class AstrolollError(Exception):
    """Base class for all astrolol domain errors."""


class AdapterNotFoundError(AstrolollError):
    """No adapter registered for the requested adapter_key."""


class DeviceAlreadyConnectedError(AstrolollError):
    """A device with this device_id is already connected."""


class DeviceConnectionError(AstrolollError):
    """The adapter raised an error during connect()."""


class DeviceNotFoundError(AstrolollError):
    """No connected device with the requested device_id."""


class DeviceKindError(AstrolollError):
    """The connected device is not of the expected kind."""
