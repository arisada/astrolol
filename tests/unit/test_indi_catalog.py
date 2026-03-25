"""
Tests for the INDI driver catalog parser.
"""
import textwrap
from pathlib import Path

import pytest

from astrolol.devices.indi.catalog import (
    DriverEntry,
    GROUP_TO_KIND,
    load_catalog,
    _parse_file,
    drivers_by_kind,
)


SAMPLE_XML = textwrap.dedent("""\
    <?xml version="1.0" encoding="UTF-8"?>
    <driversList>
      <devGroup group="CCDs">
        <device label="ZWO CCD" manufacturer="ZWO">
          <driver name="ZWO CCD">indi_asi_ccd</driver>
          <version>2.1</version>
        </device>
        <device label="QHY CCD" manufacturer="QHYCCD">
          <driver name="QHY CCD">indi_qhy_ccd</driver>
          <version>1.3</version>
        </device>
      </devGroup>
      <devGroup group="Telescopes">
        <device label="EQMod Mount" manufacturer="Synta">
          <driver name="EQMod Mount">indi_eqmod_telescope</driver>
          <version>1.0</version>
        </device>
      </devGroup>
      <devGroup group="Focusers">
        <device label="Moonlite" manufacturer="Moonlite">
          <driver name="Moonlite">indi_moonlite_focus</driver>
          <version>1.0</version>
        </device>
      </devGroup>
      <devGroup group="UnknownGroup">
        <device label="Mystery Device" manufacturer="X">
          <driver name="Mystery">indi_mystery</driver>
          <version>0.1</version>
        </device>
      </devGroup>
    </driversList>
""")

XML_NO_DRIVER_TEXT = textwrap.dedent("""\
    <?xml version="1.0" encoding="UTF-8"?>
    <driversList>
      <devGroup group="CCDs">
        <device label="Broken" manufacturer="Acme">
          <driver name="Broken"></driver>
        </device>
      </devGroup>
    </driversList>
""")

XML_MISSING_DRIVER_EL = textwrap.dedent("""\
    <?xml version="1.0" encoding="UTF-8"?>
    <driversList>
      <devGroup group="CCDs">
        <device label="NoDrvEl" manufacturer="Acme">
        </device>
      </devGroup>
    </driversList>
""")


@pytest.fixture
def sample_catalog_dir(tmp_path: Path) -> Path:
    (tmp_path / "main.xml").write_text(SAMPLE_XML)
    return tmp_path


def test_parse_file_returns_correct_count(tmp_path: Path) -> None:
    f = tmp_path / "test.xml"
    f.write_text(SAMPLE_XML)
    entries = _parse_file(f)
    assert len(entries) == 5  # 2 CCDs + 1 Telescope + 1 Focuser + 1 Unknown


def test_camera_kind(tmp_path: Path) -> None:
    f = tmp_path / "test.xml"
    f.write_text(SAMPLE_XML)
    entries = _parse_file(f)
    cameras = [e for e in entries if e.kind == "camera"]
    assert len(cameras) == 2
    assert {e.executable for e in cameras} == {"indi_asi_ccd", "indi_qhy_ccd"}


def test_mount_kind(tmp_path: Path) -> None:
    f = tmp_path / "test.xml"
    f.write_text(SAMPLE_XML)
    entries = _parse_file(f)
    mounts = [e for e in entries if e.kind == "mount"]
    assert len(mounts) == 1
    assert mounts[0].executable == "indi_eqmod_telescope"


def test_focuser_kind(tmp_path: Path) -> None:
    f = tmp_path / "test.xml"
    f.write_text(SAMPLE_XML)
    entries = _parse_file(f)
    focusers = [e for e in entries if e.kind == "focuser"]
    assert len(focusers) == 1
    assert focusers[0].executable == "indi_moonlite_focus"


def test_unknown_group_falls_back_to_aux(tmp_path: Path) -> None:
    f = tmp_path / "test.xml"
    f.write_text(SAMPLE_XML)
    entries = _parse_file(f)
    aux = [e for e in entries if e.group == "UnknownGroup"]
    assert len(aux) == 1
    assert aux[0].kind == "aux"


def test_driver_entry_fields(tmp_path: Path) -> None:
    f = tmp_path / "test.xml"
    f.write_text(SAMPLE_XML)
    entries = _parse_file(f)
    zwo = next(e for e in entries if e.executable == "indi_asi_ccd")
    assert zwo.label == "ZWO CCD"
    assert zwo.device_name == "ZWO CCD"
    assert zwo.manufacturer == "ZWO"
    assert zwo.group == "CCDs"


def test_skips_device_with_empty_driver_text(tmp_path: Path) -> None:
    f = tmp_path / "test.xml"
    f.write_text(XML_NO_DRIVER_TEXT)
    entries = _parse_file(f)
    assert entries == []


def test_skips_device_with_missing_driver_element(tmp_path: Path) -> None:
    f = tmp_path / "test.xml"
    f.write_text(XML_MISSING_DRIVER_EL)
    entries = _parse_file(f)
    assert entries == []


def test_load_catalog_nonexistent_dir() -> None:
    entries = load_catalog(Path("/nonexistent/indi/path"))
    assert entries == []


def test_load_catalog_multiple_files(tmp_path: Path) -> None:
    (tmp_path / "a.xml").write_text(SAMPLE_XML)
    (tmp_path / "b.xml").write_text(SAMPLE_XML)
    entries = load_catalog(tmp_path)
    assert len(entries) == 10  # 5 from each file


def test_load_catalog_ignores_non_xml(tmp_path: Path) -> None:
    (tmp_path / "main.xml").write_text(SAMPLE_XML)
    (tmp_path / "readme.txt").write_text("not xml")
    entries = load_catalog(tmp_path)
    assert len(entries) == 5


def test_load_catalog_invalid_xml_skipped(tmp_path: Path) -> None:
    (tmp_path / "good.xml").write_text(SAMPLE_XML)
    (tmp_path / "bad.xml").write_text("this is not xml <<<")
    entries = load_catalog(tmp_path)
    assert len(entries) == 5  # bad file skipped, good file processed


def test_drivers_by_kind(sample_catalog_dir: Path) -> None:
    cameras = drivers_by_kind("camera", sample_catalog_dir)
    assert all(d.kind == "camera" for d in cameras)
    assert len(cameras) == 2


def test_group_to_kind_mapping() -> None:
    assert GROUP_TO_KIND["CCDs"] == "camera"
    assert GROUP_TO_KIND["DSLRs"] == "camera"
    assert GROUP_TO_KIND["Telescopes"] == "mount"
    assert GROUP_TO_KIND["Focusers"] == "focuser"
    assert GROUP_TO_KIND["Filter Wheels"] == "filter_wheel"
