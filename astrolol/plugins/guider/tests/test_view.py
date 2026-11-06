import numpy as np

from astrolol.plugins.guider.view import render_jpeg


def test_jpeg_of_a_star_field_is_valid_and_not_flat() -> None:
    from io import BytesIO

    from PIL import Image

    rng = np.random.default_rng(0)
    img = rng.normal(100, 3, (300, 400))
    img[100:104, 200:204] += 3000
    out = Image.open(BytesIO(render_jpeg(img.astype(np.uint16))))
    assert out.size == (400, 300) and out.mode == "L"
    px = np.asarray(out)
    assert px[100:104, 200:204].mean() > 200 > np.median(px)  # the star stands out of the sky


def test_large_frames_are_reduced() -> None:
    from io import BytesIO

    from PIL import Image

    out = Image.open(BytesIO(render_jpeg(np.zeros((1024, 1280), dtype=np.uint8) + 5, max_width=640)))
    assert out.width <= 640 and out.height == round(1024 * out.width / 1280)


def test_flat_image_does_not_crash() -> None:
    assert render_jpeg(np.full((50, 60), 7, dtype=np.uint16))[:2] == b"\xff\xd8"


def test_stars_stand_out_of_the_quantisation_noise_of_an_8_bit_stream() -> None:
    """Background of 0-2 ADU and stars of 10-30: the sky must not become black and white speckle."""
    from io import BytesIO

    from PIL import Image

    rng = np.random.default_rng(1)
    img = rng.choice([0, 1, 1, 1, 2], size=(97, 97)).astype(np.uint8)
    img[40:43, 50:53] = 30
    img[10:12, 20:22] = 12
    px = np.asarray(Image.open(BytesIO(render_jpeg(img)))).astype(float)
    sky = np.ones(img.shape, bool)
    sky[40:43, 50:53] = sky[10:12, 20:22] = False
    assert px[40:43, 50:53].mean() > 200  # the bright star is near white
    assert px[10:12, 20:22].mean() > px[sky].mean() + 60  # the faint one clearly above the sky
    assert px[sky].mean() < 40 and np.percentile(px[sky], 99) < 100  # the sky stays dark, with no white specks


def _frame(pixels: np.ndarray):  # noqa: ANN202
    from astrolol.devices.base.streaming import Frame

    return Frame(pixels=pixels, seq=1, timestamp=0.0, exposure=1.0, gain=None, binning=2)


def test_the_image_is_shown_after_its_dark() -> None:
    """With a dark that matches, the hot pixels are gone from the image, and the page says so."""
    from astrolol.imaging.darks import DarkLibrary, make_dark
    from astrolol.plugins.guider.view import GuideView

    hot = np.full((60, 80), 56, dtype=np.uint8)
    hot[10, 10] = 120
    library = DarkLibrary()
    library.add(make_dark([_frame(hot.copy()) for _ in range(5)]))
    view = GuideView(library)
    view.update(_frame(hot.copy()), [], "preview")
    info = view.info()
    assert info.dark_applied and info.stats is not None
    assert info.stats.brightest < 5   # the hot pixel is healed, and the sky is what is left after its dark


def test_without_a_matching_dark_the_image_is_as_it_came() -> None:
    from astrolol.imaging.darks import DarkLibrary
    from astrolol.plugins.guider.view import GuideView

    pixels = np.full((60, 80), 56, dtype=np.uint8)
    pixels[10, 10] = 120
    view = GuideView(DarkLibrary())
    view.update(_frame(pixels), [], "preview")
    info = view.info()
    assert not info.dark_applied and info.stats is not None and info.stats.brightest == 120
    assert GuideView().info().dark_applied is False   # no frame yet
