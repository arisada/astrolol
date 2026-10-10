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
