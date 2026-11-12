"""Adding short sub-exposures into one virtual long exposure.

``SumAccumulator`` is the plain sum, kept as exact int32 with nothing subtracted: no offset,
no pedestal, no estimate. Bias, fixed pattern and amplifier glow add up in a light and in a
dark taken the same way, so they cancel in the usual calibration whatever the camera's
offset is. Anything that estimates a constant from the data could change between a dark and a
light and silently invalidate the darks; the raw sum cannot.

Rejection (frame-level, or pixel clipping with a running mean) would be another
``Accumulator`` with the same interface.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

import numpy as np


class StackError(Exception):
    """A sub-exposure cannot be added to the stack."""


class StackOverflow(StackError):
    """One more sub could overflow the accumulator."""


@runtime_checkable
class Accumulator(Protocol):
    """Collects sub-exposures; ``result()`` is the image of their combined exposure."""

    @property
    def count(self) -> int: ...

    @property
    def exposure(self) -> float:
        """Seconds of light in the stack: the sum of the lengths of the subs added."""
        ...

    def add(self, pixels: np.ndarray, exposure: float) -> None: ...

    def result(self) -> np.ndarray: ...


_INT32_MAX = int(np.iinfo(np.int32).max)
_ADU_MIN, _ADU_MAX = -32768, 65535  # what 16-bit cameras produce, signed or unsigned


class SumAccumulator:
    """Exact int32 sum of sub-exposures holding whole ADU counts.

    A camera's frames come as 16-bit integers, or sometimes as wider integers or floats that
    still hold whole 16-bit counts (a FITS file written by a driver that stores 32 bits). Those
    are taken too, once checked; anything else (fractions, values beyond 16 bits) is refused
    rather than summed inexactly.
    """

    def __init__(self) -> None:
        self._plane: np.ndarray | None = None
        self._count = 0
        self._exposure = 0.0
        self._peak = 0  # the largest value a sub of the dtype in use can hold
        self._full_scale = 0  # the sum if every sub held its largest value

    @property
    def count(self) -> int:
        return self._count

    @property
    def exposure(self) -> float:
        return self._exposure

    @property
    def full_scale(self) -> int:
        """The value a pixel reaches when it was at full scale in every sub."""
        return self._full_scale

    @property
    def shape(self) -> tuple[int, int] | None:
        if self._plane is None:
            return None
        return (int(self._plane.shape[0]), int(self._plane.shape[1]))

    @property
    def capacity(self) -> int | None:
        """How many subs of the dtype in use fit before the int32 sum could overflow."""
        return None if self._peak == 0 else _INT32_MAX // self._peak

    def add(self, pixels: np.ndarray, exposure: float) -> None:
        if pixels.ndim != 2:
            raise StackError(f"expected a 2-D image, got shape {pixels.shape}")
        if exposure <= 0:
            raise StackError(f"a sub-exposure lasts longer than {exposure} s")

        if self._plane is None:
            self._plane = np.zeros(pixels.shape, dtype=np.int32)
        elif pixels.shape != self._plane.shape:
            raise StackError(
                f"sub of shape {pixels.shape} does not match the stack {self._plane.shape}"
            )

        pixels, largest = self._as_adu(pixels)
        # The sum is exact as long as the biggest possible sub value times the count fits.
        peak = max(self._peak, largest)
        if (self._count + 1) * peak > _INT32_MAX:
            raise StackOverflow(
                f"{self._count} subs are the most an int32 sum holds"
            )
        self._peak = peak

        np.add(self._plane, pixels, out=self._plane, casting="safe")  # in place: no temporary frame
        self._count += 1
        self._exposure += exposure
        self._full_scale += largest

    def _as_adu(self, pixels: np.ndarray) -> tuple[np.ndarray, int]:
        """*pixels* as integers a 16-bit-wide sum can take, and the largest value they may hold."""
        kind = pixels.dtype.kind
        if kind in "ui" and pixels.dtype.itemsize <= 2:
            return pixels, int(np.iinfo(pixels.dtype).max)
        if kind not in "uif":
            raise StackError(f"cannot stack {pixels.dtype} pixels")
        if kind == "f":
            whole = np.rint(pixels)
            if self._count == 0 and not np.array_equal(whole, pixels):  # NaN fails this too
                raise StackError("the pixels are not whole counts: cannot sum them exactly")
            pixels = whole
        low, high = pixels.min(), pixels.max()
        if low < _ADU_MIN or high > _ADU_MAX:
            raise StackError(f"pixel values {low}..{high} are beyond 16 bits")
        return pixels.astype(np.int32, copy=False), _ADU_MAX

    def result(self) -> np.ndarray:
        """The sum. It is the accumulator's own plane: take it once the stack is complete."""
        if self._plane is None:
            raise StackError("nothing was added to the stack")
        return self._plane
