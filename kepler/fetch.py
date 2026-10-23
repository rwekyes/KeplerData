"""Getting the data: find a star, download what Kepler saw, and look up what
astronomers already know about its planets."""
import re
from dataclasses import dataclass
from pathlib import Path

import lightkurve as lk
import pandas as pd
import requests
from astroquery.ipac.nexsci.nasa_exoplanet_archive import NasaExoplanetArchive

RAW_DATA_DIR = Path(__file__).resolve().parent.parent / "data" / "raw"
ALIAS_URL = "https://exoplanetarchive.ipac.caltech.edu/cgi-bin/Lookup/nph-aliaslookup.py"

# Kepler counts time in days since 1 Jan 2009 ("BKJD"); the archive uses Julian
# days. This is the difference between the two.
BKJD_OFFSET = 2454833


class StarNotFound(Exception):
    """We couldn't match a name to a star that Kepler observed."""


@dataclass
class Star:
    name: str            # the name we were given, e.g. "Kepler-90"
    kic: int             # its number in the Kepler Input Catalog
    aliases: list[str]   # every other name it goes by, e.g. "KOI-351"


def find_star(name, timeout=10):
    """Look up every name a star goes by, and pick out its Kepler catalog number."""
    aliases = _lookup_aliases(name, timeout)
    kic_names = [a for a in aliases if a.startswith("KIC ")]
    if kic_names:
        return Star(name, int(kic_names[0].removeprefix("KIC ")), aliases)

    # The archive only knows stars with planets (or planet candidates), so
    # accept a bare KIC number even when the archive has never heard of it.
    match = re.fullmatch(r"\s*KIC\s*(\d+)\s*", name, flags=re.IGNORECASE)
    if match:
        return Star(name, int(match.group(1)), aliases)
    raise StarNotFound(f"Couldn't find a Kepler star called {name!r}.")


def _lookup_aliases(name, timeout):
    """Ask the NASA Exoplanet Archive for all known names of a star or system."""
    try:
        response = requests.get(ALIAS_URL, params={"objname": name}, timeout=timeout)
        lookup = response.json()
    except (requests.RequestException, ValueError):
        return []  # unknown names make the archive stall, so we give up quickly
    if lookup.get("manifest", {}).get("lookup_status") != "OK":
        return []

    # Gather the system's names plus the names of every star in it; for a
    # two-star system like Kepler-16 the KIC number lives on one of the stars.
    system = lookup["system"]
    aliases = [lookup["manifest"]["resolved_name"]]
    aliases += system.get("system_info", {}).get("alias_set", {}).get("aliases", [])
    for star in system["objects"]["stellar_set"]["stars"].values():
        aliases += star["alias_set"]["aliases"]
    return list(dict.fromkeys(aliases))  # drop duplicates, keep order


def download_light_curves(star):
    """Download every quarter (~3 months each) of brightness measurements Kepler took of this star."""
    results = lk.search_lightcurve(f"KIC {star.kic}", mission="Kepler", exptime="long", author="Kepler")
    if len(results) == 0:
        raise StarNotFound(f"Kepler has no light curves for {star.name}.")
    return results.download_all(download_dir=str(RAW_DATA_DIR))


def known_planets(star):
    """What NASA's Exoplanet Archive already knows about this star's planets."""
    names = ", ".join("'" + a.replace("'", "''") + "'" for a in star.aliases)
    if not names:
        return _empty_planet_table()
    table = NasaExoplanetArchive.query_criteria(
        table="pscomppars",
        where=f"hostname in ({names})",
        select="pl_name, pl_orbper, pl_tranmid, pl_trandur, pl_trandep, pl_rade, st_rad, tran_flag",
    )
    planets = table.to_pandas().rename(columns={
        "pl_name": "name",
        "pl_orbper": "period_days",
        "pl_tranmid": "transit_time",
        "pl_trandur": "duration_hours",
        "pl_trandep": "depth_percent",
        "pl_rade": "radius_earths",
        "st_rad": "star_radius_suns",
        "tran_flag": "transits",
    })
    planets["transit_time"] -= BKJD_OFFSET     # switch to Kepler's clock
    planets["transits"] = planets["transits"] == 1  # some planets never pass in front of their star
    return planets.sort_values("period_days").reset_index(drop=True)


def _empty_planet_table():
    return pd.DataFrame(columns=["name", "period_days", "transit_time", "duration_hours",
                                 "depth_percent", "radius_earths", "star_radius_suns", "transits"])
