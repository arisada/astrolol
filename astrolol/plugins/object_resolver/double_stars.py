"""Showpiece double stars, by Hipparcos number.

OpenNGC lists hardly any, and the Hipparcos catalogue does not say which stars are double. These
are the well-known ones; each is marked as a "Double Star" and given the names people use.
"""
from __future__ import annotations

DOUBLE_STARS: dict[str, int] = {
    "Albireo": 95947, "Mizar": 65378, "Almach": 9640, "Rigel": 24436, "Castor": 36850,
    "Polaris": 11767, "Antares": 80763, "Algieba": 50583, "Cor Caroli": 63125,
    "Acrux": 60718, "Izar": 72105, "Mintaka": 25930,
    "Mesarthim": 8832, "Porrima": 61941, "Rasalgethi": 84345, "Alrescha": 9487,
    "Gamma Delphini": 102532, "70 Ophiuchi": 88601, "Epsilon Lyrae": 91919,
    "Double Double": 91919, "Iota Cancri": 43103, "Gamma Leporis": 27072,
    "Eta Cassiopeiae": 3821, "Delta Cephei": 110991, "Beta Monocerotis": 30867,
    "Alya": 92946, "Xi Bootis": 72659, "40 Eridani": 19849, "Sigma Orionis": 26549,
    "61 Cygni": 104214,
}
