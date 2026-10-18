"""IAU proper names of the brightest stars, by Hipparcos number.

The Hipparcos catalogue only has numbers; this adds the names people actually type.
"""
from __future__ import annotations

STAR_NAMES: dict[str, int] = {
    "Sirius": 32349, "Canopus": 30438, "Rigil Kentaurus": 71683, "Arcturus": 69673,
    "Vega": 91262, "Capella": 24608, "Rigel": 24436, "Procyon": 37279,
    "Achernar": 7588, "Betelgeuse": 27989, "Hadar": 68702, "Altair": 97649,
    "Acrux": 60718, "Aldebaran": 21421, "Antares": 80763, "Spica": 65474,
    "Pollux": 37826, "Fomalhaut": 113368, "Deneb": 102098, "Mimosa": 62434,
    "Regulus": 49669, "Adhara": 33579, "Castor": 36850, "Gacrux": 61084,
    "Shaula": 85927, "Bellatrix": 25336, "Elnath": 25428, "Miaplacidus": 45238,
    "Alnilam": 26311, "Alnair": 109268, "Alnitak": 26727, "Alioth": 62956,
    "Dubhe": 54061, "Mirfak": 15863, "Wezen": 34444, "Sargas": 86228,
    "Kaus Australis": 90185, "Avior": 41037, "Alkaid": 67301, "Menkalinan": 28360,
    "Atria": 82273, "Alhena": 31681, "Peacock": 100751, "Mirzam": 30324,
    "Alphard": 46390, "Polaris": 11767, "Hamal": 9884, "Algieba": 50583,
    "Diphda": 3419, "Mizar": 65378, "Alcor": 65477, "Nunki": 92855,
    "Menkent": 68933, "Mirach": 5447, "Alpheratz": 677, "Rasalhague": 86032,
    "Kochab": 72607, "Saiph": 27366, "Denebola": 57632, "Algol": 14576,
    "Suhail": 44816, "Alphecca": 76267, "Mintaka": 25930, "Sadr": 100453,
    "Eltanin": 87833, "Schedar": 3179, "Naos": 39429, "Almach": 9640,
    "Caph": 746, "Izar": 72105, "Merak": 53910, "Enif": 107315,
    "Scheat": 113881, "Markab": 113963, "Albireo": 95947, "Thuban": 68756,
    "Vindemiatrix": 63608, "Algenib": 1067, "Mira": 10826, "Navi": 4427,
    "Ruchbah": 6686, "Menkar": 14135, "Zubeneschamali": 74785,
    "Zubenelgenubi": 72622, "Unukalhai": 77070, "Cor Caroli": 63125,
    "Alderamin": 105199, "Sheliak": 92420, "Sulafat": 93194, "Rastaban": 85670,
    "Gienah": 102488, "Dschubba": 78401, "Acrab": 78820, "Sabik": 84012,
    "Tarazed": 97278, "Alcyone": 17702, "Atlas": 17847, "Electra": 17499,
    "Maia": 17573, "Merope": 17608, "Taygeta": 17531, "Pleione": 17851,
}

# Extra spellings / popular names for the same stars.
STAR_ALIASES: dict[str, int] = {
    "Alpha Centauri": 71683, "Toliman": 71683, "Rigil Kent": 71683,
    "Dog Star": 32349, "North Star": 11767, "Pole Star": 11767,
    "Cor Leonis": 49669,
}
