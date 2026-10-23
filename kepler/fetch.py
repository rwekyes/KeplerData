"""Getting the data: find a star, download what Kepler saw, and look up what
astronomers already know about its planets."""
import difflib
import re
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

import astropy.units as u
import lightkurve as lk
import pandas as pd
import requests
from astroquery.exceptions import RemoteServiceError, ResolverError
from astroquery.ipac.nexsci.nasa_exoplanet_archive import NasaExoplanetArchive
from astroquery.mast import Catalogs, Mast
from lightkurve.utils import LightkurveError

RAW_DATA_DIR = Path(__file__).resolve().parent.parent / "data" / "raw"
ALIAS_URL = "https://exoplanetarchive.ipac.caltech.edu/cgi-bin/Lookup/nph-aliaslookup.py"

# Kepler counts time in days since 1 Jan 2009 ("BKJD"); the archive uses Julian
# days. This is the difference between the two.
BKJD_OFFSET = 2454833


class StarNotFound(Exception):
    """No NASA archive recognizes this name."""


class NotObservedByKepler(Exception):
    """A real star, but Kepler never recorded its brightness."""


class ArchiveUnavailable(Exception):
    """We couldn't reach NASA's archives (no internet, or the archive is down)."""


@dataclass
class Star:
    name: str            # its usual name, e.g. "Kepler-90"
    kic: int             # its number in the Kepler Input Catalog
    aliases: list[str]   # every other name it goes by, e.g. "KOI-351"


def find_star(name, timeout=10):
    """Turn whatever name someone typed into a star in the Kepler Input Catalog (KIC)."""
    name = name.strip()
    if name.isdigit():
        name = f"KIC {name}"  # a bare number is most likely a KIC number

    # NASA's planet archive answers in a few seconds for stars it knows, but
    # stalls on names it doesn't, so we give up on it quickly and ask MAST
    # (which also knows stars without planets).
    aliases = _lookup_aliases(name, timeout)
    kic = re.fullmatch(r"KIC\s*(\d+)", name, flags=re.IGNORECASE)
    if kic:
        return Star(_usual_name(name, aliases), int(kic.group(1)), aliases)
    if not aliases:
        aliases = _lookup_with_mast(name)

    kic_names = [a for a in aliases if a.startswith("KIC ")]
    if kic_names:
        return Star(_usual_name(name, aliases), int(kic_names[0].removeprefix("KIC ")), aliases)
    raise NotObservedByKepler(_why_not_kepler(_usual_name(name, aliases), aliases))


def _usual_name(name, aliases):
    """The archive's spelling of the name we were given ("kepler 90" → "Kepler-90"),
    or else the archive's main name for the star."""
    def simplify(text):
        return re.sub(r"[\s-]", "", text).lower()
    same = [a for a in aliases if simplify(a) == simplify(name)]
    return same[0] if same else (aliases[0] if aliases else name)


def suggest_name(name):
    """Guess what a mistyped name meant, e.g. 'Keplr 10' → 'Kepler-10'."""
    match = re.fullmatch(r"\s*([a-z]+)[\s-]*(\d+(?:\.\d+)?)\s*", name, flags=re.IGNORECASE)
    if not match:
        return None
    word, number = match.groups()
    close = difflib.get_close_matches(word.lower(), ["kepler", "koi", "kic"], n=1, cutoff=0.6)
    if not close:
        return None
    guess = {"kepler": f"Kepler-{number}", "koi": f"KOI-{number}", "kic": f"KIC {number}"}[close[0]]
    return None if guess.lower() == name.strip().lower() else guess


def _lookup_aliases(name, timeout):
    """Ask the NASA Exoplanet Archive for all known names of a star or system."""
    try:
        response = requests.get(ALIAS_URL, params={"objname": name}, timeout=timeout)
        lookup = response.json()
    except (requests.RequestException, ValueError):
        return []  # a slow answer usually means an unknown name; MAST will tell us for sure
    if lookup.get("manifest", {}).get("lookup_status") != "OK":
        return []

    # Gather the system's names plus the names of every star in it; for a
    # two-star system like Kepler-16 the KIC number lives on one of the stars.
    system = lookup["system"]
    aliases = [lookup["manifest"]["system_name"], lookup["manifest"]["resolved_name"]]
    aliases += system.get("system_info", {}).get("alias_set", {}).get("aliases", [])
    for star in system["objects"]["stellar_set"]["stars"].values():
        aliases += star["alias_set"]["aliases"]
    return list(dict.fromkeys(aliases))  # drop duplicates, keep order


def _lookup_with_mast(name):
    """Ask MAST where in the sky this name points, then which catalog star sits there."""
    with _reaching("NASA's MAST archive"):
        try:
            position = Mast.resolve_object(name)
        except ResolverError:
            raise StarNotFound(f"Couldn't find a star called {name!r}.") from None
        nearby = Catalogs.query_region(position, radius=5 * u.arcsec, catalog="TIC")
    if len(nearby) == 0:
        raise StarNotFound(f"Couldn't find a star called {name!r}.")
    star = nearby[nearby["dstArcSec"].argmin()]
    aliases = [name, f"TIC {star['ID']}"]
    if star["KIC"]:
        aliases.append(f"KIC {star['KIC']}")
    return aliases


def _why_not_kepler(name, aliases):
    if any(a.startswith("EPIC ") for a in aliases):
        return (f"{name} was observed by K2, Kepler's second mission, which pointed at "
                f"different parts of the sky. This app only handles the original Kepler mission.")
    return (f"{name} is a real star, but it isn't in Kepler's catalog: Kepler only watched "
            f"one patch of sky, in the constellations Cygnus and Lyra. NASA's TESS "
            f"telescope, which scans almost the whole sky, may have observed it instead.")


@contextmanager
def _reaching(archive):
    """Turn any network failure into one friendly error."""
    try:
        yield
    except (requests.RequestException, RemoteServiceError, LightkurveError, OSError) as error:
        raise ArchiveUnavailable(f"Couldn't reach {archive}.") from error


def download_light_curves(star):
    """Download every quarter (~3 months each) of brightness measurements Kepler took of this star."""
    with _reaching("NASA's MAST archive"):
        results = lk.search_lightcurve(f"KIC {star.kic}", mission="Kepler", exptime="long", author="Kepler")
        if len(results) == 0:
            raise NotObservedByKepler(
                f"{star.name} is in Kepler's catalog, but Kepler never recorded its brightness. "
                f"The catalog lists millions of stars; Kepler only measured about 200,000 of them."
            )
        return results.download_all(download_dir=str(RAW_DATA_DIR))


def known_planets(star):
    """What NASA's Exoplanet Archive already knows about this star's planets."""
    names = ", ".join("'" + a.replace("'", "''") + "'" for a in star.aliases)
    if not names:
        return _empty_planet_table()
    with _reaching("NASA's Exoplanet Archive"):
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
    planets["name"] = [_rename_planet(name, star) for name in planets["name"]]
    planets["transits"] = planets["transits"] == 1  # some planets never pass in front of their star
    return planets.sort_values("period_days").reset_index(drop=True)


def _rename_planet(planet, star):
    """Label planets by the star's usual name: Kepler-90's planets are filed as "KOI-351 b"."""
    host, _, letter = planet.rpartition(" ")
    return f"{star.name} {letter}" if host in star.aliases else planet


def star_radius(planets, quarters):
    """The star's size in Suns: the planet archive's value if it has one, else Kepler's catalog's."""
    sizes = planets["star_radius_suns"].dropna()
    size = sizes.iloc[0] if len(sizes) else quarters[0].meta.get("RADIUS")
    return float(size) if size is not None and size == size else None  # NaN != NaN


def _empty_planet_table():
    return pd.DataFrame(columns=["name", "period_days", "transit_time", "duration_hours",
                                 "depth_percent", "radius_earths", "star_radius_suns", "transits"])
