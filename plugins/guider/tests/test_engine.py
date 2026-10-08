import numpy as np
import pytest

from astrolol.devices.base.streaming import Frame
from plugins.guider.darks import DarkLibrary, make_dark
from plugins.guider.stars import detect_stars, measure, select_guide_stars
from plugins.guider.tracker import StarTracker

W, H = 200, 160


def field(
    stars: list[tuple[float, float, float]],
    *,
    seed: int = 1,
    noise: float = 3.0,
    bias: float = 100.0,
    hot: list[tuple[int, int, float]] = (),
    sigma: float = 1.8,
    shape: tuple[int, int] = (H, W),
    origin: tuple[int, int] = (0, 0),
) -> Frame:
    """Gaussian stars (x, y, amplitude) on a noisy background, plus hot pixels."""
    rng = np.random.default_rng(seed)
    img = bias + rng.normal(0, noise, shape)
    ys, xs = np.mgrid[0 : shape[0], 0 : shape[1]]
    for x, y, amp in stars:
        img += amp * np.exp(-((xs - (x - origin[0])) ** 2 + (ys - (y - origin[1])) ** 2) / (2 * sigma**2))
    for x, y, amp in hot:
        img[y, x] += amp
    return Frame(
        pixels=np.clip(img, 0, 65535).astype(np.uint16),
        seq=1, timestamp=0.0, exposure=1.0, gain=50, binning=1, origin=origin,
    )


def dark_frames(hot: list[tuple[int, int, float]], n: int = 5, **kw: object) -> list[Frame]:
    return [field([], seed=100 + i, hot=hot, **kw) for i in range(n)]  # type: ignore[arg-type]


# --- measure ---

def test_measure_is_subpixel_accurate() -> None:
    f = field([(60.37, 50.81, 800)])
    star = measure(f.pixels.astype(np.float32), 60, 51)
    assert star is not None
    assert star.x == pytest.approx(60.37, abs=0.08)
    assert star.y == pytest.approx(50.81, abs=0.08)
    assert star.fwhm == pytest.approx(2.355 * 1.8, rel=0.25)


def test_measure_finds_nothing_in_noise() -> None:
    f = field([])
    star = measure(f.pixels.astype(np.float32), 100, 80)
    assert star is None or star.snr < 4


# --- detection and selection ---

def test_detect_orders_by_flux_and_ignores_edges() -> None:
    f = field([(50, 40, 300), (120, 90, 900), (4, 80, 900)])
    stars = detect_stars(f)
    assert [round(s.x) for s in stars] == [120, 50]  # (4, 80) is inside the 12 px edge


def test_hot_pixel_is_not_a_star() -> None:
    f = field([(100, 80, 600)], hot=[(30, 30, 3000), (150, 120, 3000)])
    stars = detect_stars(f)
    assert [round(s.x) for s in stars] == [100]


def test_dark_removes_hot_pixels_and_dark_current() -> None:
    hot = [(30, 30, 500), (150, 120, 500)]
    lib = DarkLibrary()
    lib.add(make_dark(dark_frames(hot)))
    f = field([(100, 80, 400)], hot=hot, bias=100.0)
    img = lib.prepare(f)
    assert img[30, 30] < 30 and img[120, 150] < 30
    assert abs(float(np.median(img))) < 5  # bias gone as well


def test_dark_flags_hot_pixels() -> None:
    dark = make_dark(dark_frames([(30, 30, 200), (70, 20, 200)]))
    assert dark.hot[30, 30] and dark.hot[20, 70]
    assert dark.hot.sum() == 2


def test_select_skips_saturated_crowded_and_faint() -> None:
    f = field(
        [(40, 40, 500), (50, 40, 500),            # a close pair
         (100, 100, 700), (150, 60, 400), (60, 120, 20),  # good, good, too faint
         (110, 30, 900)],
    )
    stars = detect_stars(f)
    chosen = select_guide_stars(stars, count=3)
    positions = {(round(s.x), round(s.y)) for s in chosen}
    assert positions == {(100, 100), (150, 60), (110, 30)}
    assert chosen[0].snr >= chosen[1].snr >= chosen[2].snr


def test_saturated_star_is_rejected() -> None:
    f = field([(100, 80, 70000), (50, 50, 400)])
    stars = detect_stars(f, saturation=65000)
    chosen = select_guide_stars(stars)
    assert [round(s.x) for s in chosen] == [50]


# --- tracker ---

def test_tracker_reports_median_offset_of_found_stars() -> None:
    base = [(60.0, 50.0, 600.0), (140.0, 100.0, 500.0), (100.0, 130.0, 450.0)]
    stars = select_guide_stars(detect_stars(field(base)))
    tracker = StarTracker(stars)
    moved = [(x + 1.3, y - 0.6, a) for x, y, a in base]
    result = tracker.update(field(moved, seed=2))
    assert result.found == 3
    assert result.dx == pytest.approx(1.3, abs=0.1)
    assert result.dy == pytest.approx(-0.6, abs=0.1)


def test_tracker_survives_losing_a_star() -> None:
    base = [(60.0, 50.0, 600.0), (140.0, 100.0, 500.0), (100.0, 130.0, 450.0)]
    tracker = StarTracker(select_guide_stars(detect_stars(field(base))))
    result = tracker.update(field([(x + 0.5, y, a) for x, y, a in base[:2]], seed=3))
    assert result.found == 2
    assert result.dx == pytest.approx(0.5, abs=0.1)
    assert sum(r.star is None for r in result.readings) == 1


def test_tracker_reports_nothing_when_every_star_is_gone() -> None:
    base = [(60.0, 50.0, 600.0)]
    tracker = StarTracker(select_guide_stars(detect_stars(field(base))))
    result = tracker.update(field([], seed=4))
    assert result.found == 0 and result.dx is None and result.dy is None


def test_hot_pixel_next_to_the_star_is_healed_by_the_dark() -> None:
    hot = [(66, 50, 2500)]  # in the star's window, would drag the centroid
    star_at = [(60.0, 50.0, 600.0)]
    lib = DarkLibrary()
    lib.add(make_dark(dark_frames(hot)))
    stars = select_guide_stars(detect_stars(field(star_at, hot=hot), lib))
    with_dark = StarTracker(stars, lib).update(field(star_at, hot=hot, seed=5))
    without = StarTracker(stars).update(field(star_at, hot=hot, seed=5))
    assert abs(with_dark.dx) < 0.1
    assert abs(without.dx) > abs(with_dark.dx) + 0.2


def test_tracker_handles_a_cropped_frame_with_origin() -> None:
    sensor = [(300.4, 220.7, 600.0)]
    crop = field(sensor, shape=(80, 100), origin=(260, 190))
    stars = detect_stars(crop, edge=5)
    assert stars[0].x == pytest.approx(300.4, abs=0.1)  # sensor coordinates, not frame ones
    tracker = StarTracker(stars)
    nxt = field([(301.4, 220.7, 600.0)], shape=(80, 100), origin=(260, 190), seed=6)
    assert tracker.update(nxt).dx == pytest.approx(1.0, abs=0.1)


def test_dark_library_persists_and_serves_a_cropped_frame(tmp_path) -> None:
    hot = [(30, 30, 500)]
    DarkLibrary(tmp_path).add(make_dark(dark_frames(hot)))
    lib = DarkLibrary(tmp_path)
    assert len(lib) == 1
    crop = field([], shape=(40, 50), origin=(10, 10), hot=[(20, 20, 500)])  # sensor (30, 30)
    assert lib.lookup(crop) is not None
    assert lib.prepare(crop)[20, 20] < 30
    other_gain = Frame(pixels=crop.pixels, seq=1, timestamp=0, exposure=1.0, gain=99, origin=(10, 10))
    assert lib.lookup(other_gain) is None


def test_dark_needs_matching_frames() -> None:
    a = field([], seed=1)
    b = Frame(pixels=a.pixels, seq=2, timestamp=0, exposure=2.0, gain=50)
    with pytest.raises(ValueError):
        make_dark([a, b])
