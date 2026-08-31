"""City registry for temperature-market event discovery."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from weather_copy_bot.config import Settings

CITY_CONFIG: dict[str, dict[str, str]] = {
    "nyc": {"slug": "new-york", "station": "KNYC"},
    "chicago": {"slug": "chicago", "station": "KORD"},
    "miami": {"slug": "miami", "station": "KMIA"},
    "los_angeles": {"slug": "los-angeles", "station": "KLAX"},
    "denver": {"slug": "denver", "station": "KDEN"},
}


def city_slugs(settings: Settings) -> list[str]:
    slugs: list[str] = []
    for city in settings.weather_cities:
        config = CITY_CONFIG.get(str(city).lower())
        if config is not None:
            slugs.append(config["slug"])
    return slugs
