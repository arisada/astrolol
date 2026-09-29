"""Errors raised by Guider implementations."""


class GuiderError(Exception):
    """Base class for guider errors."""


class GuiderNotConnected(GuiderError):
    """The guider (or the application behind it) is not connected."""


class SettleFailed(GuiderError):
    """Guiding started or dithered but did not settle (error or timeout)."""


class GuiderBusy(GuiderError):
    """Another guide/dither/settle is in progress."""
