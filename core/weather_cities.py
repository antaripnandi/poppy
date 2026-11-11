"""Offline city suggestions using Poppy's compact GeoNames extract."""

import gzip
import re
import unicodedata
from functools import lru_cache

from poppy.core.storage import resource_path
from poppy.core.weather_manager import WeatherLocation


def city_key(text):
    return "".join(char for char in unicodedata.normalize("NFKD", text.casefold()) if char.isalnum())


@lru_cache(maxsize=1)
def _city_data():
    with gzip.open(resource_path("assets/weather-cities.tsv.gz"), "rt", encoding="utf-8") as file:
        return file.read()


def _one_edit_pattern(key):
    char_pattern = r"[^\t\n]"
    edits = [key + char_pattern]
    for index, char in enumerate(key):
        left, right = key[:index], key[index + 1:]
        edits.extend((left + right, left + char_pattern + right, left + char_pattern + char + right))
        if right:
            edits.append(left + right[0] + char + right[1:])
    return "(?:" + "|".join(edits) + ")"


def local_city_search(query, limit=8):
    parts = query.split(",")
    key = city_key(parts[0])
    if len(key) < 2 or len(key) > 80:
        return {}
    qualifiers = {city_key(part) for part in parts[1:] if city_key(part)}
    try:
        data = _city_data()
    except OSError:
        return {}

    patterns = [key]
    if len(key) >= 3:
        patterns.append(key + r"[^\t\n]+")
    if 4 <= len(key) <= 32 and not key.isdecimal():
        edit = _one_edit_pattern(key)
        patterns.append(edit)
        if len(key) >= 5:
            patterns.append(edit + r"[^\t\n]+")

    matches = {}
    for pattern in patterns:
        row = re.compile(rf"^(?:(?:{pattern})\t[^\t\n]*|[^\t\n]*\t(?:{pattern}))\t([^\n]+)$", re.MULTILINE)
        for match in row.finditer(data):
            name, latitude, longitude, region, country, code = match[1].split("\t")
            if qualifiers:
                places = tuple(map(city_key, (region, country, code)))
                if not all(any(place.startswith(part) for place in places) for part in qualifiers):
                    continue
            location = WeatherLocation(name, float(latitude), float(longitude), region, country)
            matches.setdefault(location.label, location)
            if len(matches) >= limit:
                return matches
    return matches
