from pathlib import Path

from astrolol.plugins.viewer.settings import default_library_dir


def test_static_prefix_is_extracted() -> None:
    assert default_library_dir("~/astrolol_pictures/%D") == Path("~/astrolol_pictures").expanduser()


def test_no_template_tokens_returns_the_whole_path() -> None:
    assert default_library_dir("/data/pics") == Path("/data/pics")


def test_empty_static_prefix_falls_back_instead_of_scanning_everything() -> None:
    """A template starting with a token (e.g. "%D/…") must never resolve to the working
    directory or the filesystem root."""
    assert default_library_dir("%D/nightly") == Path("~/astrolol_pictures").expanduser()
