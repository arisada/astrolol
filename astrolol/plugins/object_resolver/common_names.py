"""Names people type that no downloaded catalogue carries, and the showpieces it lacks.

OpenNGC only knows the common names of NGC/IC objects, and not even all of those; Sharpless,
Barnard and Melotte objects, and compound names ("Perseus Double Cluster"), have none.
"""
from __future__ import annotations

# alias -> the catalogue name of the object it designates
COMMON_NAMES: dict[str, str] = {
    "Double Cluster": "NGC 869",
    "Perseus Double Cluster": "NGC 869",
    "Double Cluster in Perseus": "NGC 869",
    "h and chi Persei": "NGC 869",
    "chi Persei Cluster": "NGC 884",
    "Cave Nebula": "Sh2-155",
    "Heart Nebula": "IC 1805",
    "Soul Nebula": "IC 1848",
    "Fish Head Nebula": "IC 1848",
    "Elephant Trunk Nebula": "IC 1396",
    "Horsehead Nebula": "IC 434",
    "Barnard 33": "IC 434",
    "B 33": "IC 434",
    "Wizard Nebula": "NGC 7380",
    "Hercules Cluster": "NGC 6205",
    "Beehive Cluster": "NGC 2632",
    "Praesepe": "NGC 2632",
    "Jellyfish Nebula": "IC 443",
    "Cone Nebula": "NGC 2264",
    "Tulip Nebula": "Sh2-101",
    "Leo Triplet": "NGC 3623",
    "Markarian's Chain": "NGC 4374",
    "Barnard's Loop": "Sh2-276",
    "Pacman Nebula": "NGC 281",
    "Seagull Nebula": "IC 2177",
    "Thor's Helmet": "NGC 2359",
    "Cygnus Wall": "NGC 7000",
    "Gamma Cygni": "HIP 100453",
}

# name -> (type, RA deg, Dec deg, V magnitude, size arcmin, aliases): well-known objects that have
# no NGC or IC number, so OpenNGC does not list them
EXTRA_OBJECTS: dict[str, tuple[str, float, float, float, float, tuple[str, ...]]] = {
    "M 45": (
        "Open Cluster", 56.75, 24.1167, 1.6, 110.0,
        ("M45", "Pleiades", "Seven Sisters", "Melotte 22", "Mel 22"),
    ),
}
