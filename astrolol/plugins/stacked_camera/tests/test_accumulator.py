"""Tests for the raw-sum accumulator."""
from __future__ import annotations

import numpy as np
import pytest

from astrolol.plugins.stacked_camera.accumulator import (
    Accumulator,
    StackError,
    StackOverflow,
    SumAccumulator,
)


def _sub(value: int, shape: tuple[int, int] = (4, 6), dtype: type = np.uint16) -> np.ndarray:
    return np.full(shape, value, dtype=dtype)


def test_is_an_accumulator() -> None:
    assert isinstance(SumAccumulator(), Accumulator)


def test_sums_exactly_and_counts_exposure() -> None:
    acc = SumAccumulator()
    for value in (100, 200, 300):
        acc.add(_sub(value), 2.0)
    assert acc.count == 3
    assert acc.exposure == pytest.approx(6.0)
    result = acc.result()
    assert result.dtype == np.int32
    assert (result == 600).all()


def test_nothing_is_subtracted() -> None:
    """The sum of N subs sitting on a bias of 500 is N * 500 + signal: no offset removed."""
    acc = SumAccumulator()
    rng = np.random.default_rng(1)
    subs = [rng.integers(480, 520, size=(8, 8)).astype(np.uint16) for _ in range(50)]
    for sub in subs:
        acc.add(sub, 1.0)
    assert (acc.result() == np.sum([s.astype(np.int64) for s in subs], axis=0)).all()


def test_mixed_sub_lengths_add_up() -> None:
    acc = SumAccumulator()
    acc.add(_sub(1), 1.0)
    acc.add(_sub(1), 2.0)
    acc.add(_sub(1), 2.0)
    assert acc.exposure == pytest.approx(5.0)


def test_sum_beyond_uint16_does_not_wrap() -> None:
    acc = SumAccumulator()
    for _ in range(300):
        acc.add(_sub(65535), 1.0)  # a saturated pixel for five minutes
    assert int(acc.result()[0, 0]) == 65535 * 300


def test_accepts_narrower_and_signed_integers() -> None:
    acc = SumAccumulator()
    acc.add(_sub(10, dtype=np.uint8), 1.0)
    acc.add(_sub(-5, dtype=np.int16), 1.0)
    assert (acc.result() == 5).all()


def test_does_not_modify_the_sub() -> None:
    sub = _sub(7)
    SumAccumulator().add(sub, 1.0)
    assert (sub == 7).all()


def test_adds_in_place() -> None:
    acc = SumAccumulator()
    acc.add(_sub(1), 1.0)
    plane = acc.result()
    acc.add(_sub(1), 1.0)
    assert acc.result() is plane


def test_rejects_a_different_shape() -> None:
    acc = SumAccumulator()
    acc.add(_sub(1, (4, 6)), 1.0)
    with pytest.raises(StackError, match="does not match"):
        acc.add(_sub(1, (4, 7)), 1.0)
    assert acc.count == 1  # the failed add left the stack as it was


@pytest.mark.parametrize("dtype", [np.float32, np.float64, np.uint32, np.int32, np.int64])
def test_takes_wider_pixels_that_hold_whole_16_bit_counts(dtype: type) -> None:
    acc = SumAccumulator()
    acc.add(np.full((2, 2), 40000, dtype=dtype), 1.0)
    acc.add(np.full((2, 2), 25000, dtype=dtype), 1.0)
    assert acc.result().dtype == np.int32
    assert (acc.result() == 65000).all()
    assert acc.capacity == (2**31 - 1) // 65535


def test_rejects_float_pixels_with_fractions() -> None:
    with pytest.raises(StackError, match="whole counts"):
        SumAccumulator().add(np.full((2, 2), 10.5, dtype=np.float32), 1.0)


def test_rejects_nan_pixels() -> None:
    pixels = np.ones((2, 2), dtype=np.float32)
    pixels[0, 0] = np.nan
    with pytest.raises(StackError, match="whole counts"):
        SumAccumulator().add(pixels, 1.0)


@pytest.mark.parametrize("value", [70000, -40000])
def test_rejects_wide_pixels_beyond_16_bits(value: int) -> None:
    with pytest.raises(StackError, match="beyond 16 bits"):
        SumAccumulator().add(np.full((2, 2), value, dtype=np.int32), 1.0)


def test_rejects_other_pixel_types() -> None:
    with pytest.raises(StackError, match="cannot stack"):
        SumAccumulator().add(np.ones((2, 2), dtype=bool), 1.0)


def test_rejects_a_3d_frame() -> None:
    with pytest.raises(StackError, match="2-D"):
        SumAccumulator().add(np.ones((2, 2, 3), dtype=np.uint16), 1.0)


@pytest.mark.parametrize("exposure", [0.0, -1.0])
def test_rejects_a_non_positive_exposure(exposure: float) -> None:
    with pytest.raises(StackError, match="longer than"):
        SumAccumulator().add(_sub(1), exposure)


def test_result_of_an_empty_stack_is_an_error() -> None:
    with pytest.raises(StackError, match="nothing"):
        SumAccumulator().result()


def test_capacity_follows_the_dtype() -> None:
    acc = SumAccumulator()
    assert acc.capacity is None
    acc.add(_sub(1), 1.0)
    assert acc.capacity == (2**31 - 1) // 65535  # 32 768: far above any real stack
    narrow = SumAccumulator()
    narrow.add(_sub(1, dtype=np.uint8), 1.0)
    assert narrow.capacity == (2**31 - 1) // 255


def test_overflow_is_refused_before_it_can_happen() -> None:
    acc = SumAccumulator()
    acc.add(_sub(65535), 1.0)
    capacity = acc.capacity
    assert capacity is not None
    acc._count = capacity - 1  # the stack is one short of full (the cheap way to get there)
    acc.add(_sub(65535), 1.0)
    with pytest.raises(StackOverflow):
        acc.add(_sub(65535), 1.0)
    assert acc.count == capacity


def test_a_wider_sub_after_narrow_ones_tightens_the_guard() -> None:
    acc = SumAccumulator()
    acc.add(_sub(1, dtype=np.uint8), 1.0)
    acc._count = 10_000_000  # fine for 8-bit subs, too many for 16-bit ones
    with pytest.raises(StackOverflow):
        acc.add(_sub(1), 1.0)


def test_full_scale_is_every_sub_at_its_maximum() -> None:
    acc = SumAccumulator()
    assert acc.full_scale == 0
    for _ in range(20):
        acc.add(_sub(5), 1.0)
    assert acc.full_scale == 20 * 65535


def test_full_scale_follows_the_dtype_of_each_sub() -> None:
    acc = SumAccumulator()
    acc.add(_sub(5, dtype=np.uint8), 1.0)
    acc.add(_sub(5), 1.0)
    acc.add(np.full((4, 6), 5, dtype=np.int32), 1.0)  # whole counts in a wider type: 16-bit scale
    assert acc.full_scale == 255 + 65535 + 65535


def test_a_refused_sub_adds_nothing_to_the_full_scale() -> None:
    acc = SumAccumulator()
    acc.add(_sub(5), 1.0)
    with pytest.raises(StackError):
        acc.add(_sub(5, (9, 9)), 1.0)
    assert acc.full_scale == 65535
