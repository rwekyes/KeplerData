"""Getting the data: find a star, download what Kepler or TESS saw, and look up
what astronomers already know about its planets."""
import difflib
import re
import shutil
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

# Each telescope counts time in days from its own starting point: Kepler from
# noon on 1 Jan 2009 ("BKJD"), TESS from noon on 8 Dec 2014 ("BTJD"). The
# archive uses Julian days. These are the differences.
CLOCK_STARTS = {"Kepler": 2454833, "TESS": 2457000}

# Each telescope's star catalog: the Kepler Input Catalog and the TESS Input Catalog.
CATALOGS = {"Kepler": "KIC", "TESS": "TIC"}


class StarNotFound(Exception):
    """No NASA archive recognizes this name."""


class NotObserved(Exception):
    """A real star, but neither Kepler nor TESS recorded its brightness."""


class ArchiveUnavailable(Exception):
    """We couldn't reach NASA's archives (no internet, or the archive is down)."""


@dataclass
class Star:
    name: str            # its usual name, e.g. "Kepler-90"
    mission: str         # whose data we use: "Kepler" or "TESS"
    number: int          # its number in that telescope's star catalog
    aliases: list[str]   # every other name it goes by, e.g. "KOI-351"

    @property
    def catalog_name(self):
        """e.g. "KIC 11904151" or "TIC 150428135"."""
        return f"{CATALOGS[self.mission]} {self.number}"


def find_star(name, timeout=10):
    """Turn whatever name someone typed into a star, and pick the telescope whose data we use.

    Kepler watched one patch of sky for four years, so for its stars we use
    Kepler's data. TESS covers almost the whole sky, a month or more at a time,
    so every other star gets TESS's data, and so do TESS names (TIC and TOI numbers).
    """
    name = name.strip()
    if name.isdigit():
        name = f"KIC {name}"  # a bare number is most likely a KIC number

    # NASA's planet archive answers in a few seconds for stars it knows, but
    # stalls on names it doesn't, so we give up on it quickly and ask MAST
    # (which also knows stars without planets).
    aliases = _lookup_aliases(name, timeout)
    catalog_number = re.fullmatch(r"(KIC|TIC)\s*(\d+)", name, flags=re.IGNORECASE)
    if catalog_number:  # a catalog number is all we need
        aliases = list(dict.fromkeys([f"{catalog_number[1].upper()} {int(catalog_number[2])}", *aliases]))
    elif not (_catalog_number(aliases, "KIC") or _catalog_number(aliases, "TIC")):
        aliases = list(dict.fromkeys([*aliases, *_lookup_with_mast(name)]))

    usual_name = _usual_name(name, aliases)
    kic, tic = _catalog_number(aliases, "KIC"), _catalog_number(aliases, "TIC")
    wants_tess = re.match(r"(TIC|TOI)(?![a-z])", name, flags=re.IGNORECASE)
    if kic and not wants_tess:
        return Star(usual_name, "Kepler", kic, aliases)
    if tic:
        return Star(usual_name, "TESS", tic, aliases)
    raise NotObserved(f"{usual_name} is a real star, but it isn't in Kepler's or TESS's catalog.")


def _catalog_number(aliases, catalog):
    """The star's number in a catalog ("KIC" or "TIC"), or None."""
    numbers = [a.removeprefix(f"{catalog} ") for a in aliases if a.startswith(f"{catalog} ")]
    return int(numbers[0]) if numbers else None


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
    close = difflib.get_close_matches(word.lower(), ["kepler", "koi", "kic", "toi", "tic"], n=1, cutoff=0.6)
    if not close:
        return None
    guess = {"kepler": f"Kepler-{number}", "koi": f"KOI-{number}", "kic": f"KIC {number}",
             "toi": f"TOI-{number}", "tic": f"TIC {number}"}[close[0]]
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


@contextmanager
def _reaching(archive):
    """Turn any network failure into one friendly error."""
    try:
        yield
    except (requests.RequestException, RemoteServiceError, LightkurveError, OSError) as error:
        raise ArchiveUnavailable(f"Couldn't reach {archive}.") from error


# Where each telescope's downloads land inside RAW_DATA_DIR.
DOWNLOAD_FOLDERS = {"Kepler": "mastDownload/Kepler/kplr{:09d}_*", "TESS": "mastDownload/*/*{:016d}*"}


def download_light_curves(star):
    """Download every stretch of brightness measurements the telescope took of this star:
    Kepler's quarters (~3 months each) or TESS's sectors (~27 days each)."""
    with _reaching("NASA's MAST archive"):
        if star.mission == "Kepler":
            results = lk.search_lightcurve(star.catalog_name, mission="Kepler", exptime="long", author="Kepler")
        else:
            results = search_tess(star)
        if len(results) == 0:
            raise NotObserved(_why_not_observed(star))
        try:
            light_curves = results.download_all(download_dir=str(RAW_DATA_DIR))
        except LightkurveError:
            # A half-finished download (say, two people fetching the same star at
            # once) leaves a broken file behind. Delete this star's files and retry.
            for folder in RAW_DATA_DIR.glob(DOWNLOAD_FOLDERS[star.mission].format(star.number)):
                shutil.rmtree(folder, ignore_errors=True)
            light_curves = results.download_all(download_dir=str(RAW_DATA_DIR))
    if star.mission == "TESS":
        # Averaging TESS's measurements over 10 minutes (30 for full-frame images,
        # to match the slowest of them) keeps every dip but makes each later
        # step several times faster.
        minutes = 10 if results.author[0] == "SPOC" else 30
        light_curves = lk.LightCurveCollection(
            [lc.remove_nans().bin(time_bin_size=minutes * u.min) for lc in light_curves])
    return light_curves


def search_tess(star):
    """TESS's measurements of this star: every 2 minutes if it was picked for a close
    watch, otherwise every 3–30 minutes, taken from TESS's full-frame images."""
    results = lk.search_lightcurve(star.catalog_name, mission="TESS")
    if len(results) == 0:
        return results
    close_watch = results[(results.author == "SPOC") & (results.exptime.value == 120)]
    return close_watch if len(close_watch) else results[results.author == "TESS-SPOC"]


def _why_not_observed(star):
    if star.mission == "Kepler":
        return (f"{star.name} is in Kepler's catalog, but Kepler never recorded its brightness. "
                f"The catalog lists millions of stars; Kepler only measured about 200,000 of them.")
    if any(a.startswith("EPIC ") for a in star.aliases):
        return (f"{star.name} was observed by K2, Kepler's second mission, but not by TESS. "
                f"This app handles the original Kepler mission and TESS, but not K2.")
    return (f"{star.name} is in TESS's catalog, but NASA hasn't made measurements of its "
            f"brightness from TESS's images. TESS's catalog lists over a billion stars, and "
            f"NASA processes the brighter ones (and any it was asked to watch closely).")


def known_planets(star):
    """What NASA's Exoplanet Archive already knows about this star's planets."""
    names = ", ".join("'" + a.replace("'", "''") + "'" for a in star.aliases)
    if not names:
        return _empty_planet_table()
    with _reaching("NASA's Exoplanet Archive"):
        table = NasaExoplanetArchive.query_criteria(
            table="pscomppars",
            where=f"hostname in ({names})",
            select="pl_name, pl_orbper, pl_orbsmax, pl_tranmid, pl_trandur, pl_trandep, pl_rade, st_rad, tran_flag",
        )
    planets = table.to_pandas().rename(columns={
        "pl_name": "name",
        "pl_orbper": "period_days",
        "pl_orbsmax": "distance_au",
        "pl_tranmid": "transit_time",
        "pl_trandur": "duration_hours",
        "pl_trandep": "depth_percent",
        "pl_rade": "radius_earths",
        "st_rad": "star_radius_suns",
        "tran_flag": "transits",
    })
    planets["transit_time"] -= CLOCK_STARTS[star.mission]  # switch to the telescope's clock
    planets["name"] = [_rename_planet(name, star) for name in planets["name"]]
    planets["transits"] = planets["transits"] == 1  # some planets never pass in front of their star
    return planets.sort_values("period_days").reset_index(drop=True)


def _rename_planet(planet, star):
    """Label planets by the star's usual name: Kepler-90's planets are filed as "KOI-351 b"."""
    host, _, letter = planet.rpartition(" ")
    return f"{star.name} {letter}" if host in star.aliases else planet


def star_radius(planets, quarters):
    """The star's size in Suns: the planet archive's value if it has one, else the telescope's catalog's."""
    sizes = planets["star_radius_suns"].dropna()
    size = sizes.iloc[0] if len(sizes) else quarters[0].meta.get("RADIUS")
    return float(size) if size is not None and size == size else None  # NaN != NaN


def _empty_planet_table():
    return pd.DataFrame(columns=["name", "period_days", "distance_au", "transit_time", "duration_hours",
                                 "depth_percent", "radius_earths", "star_radius_suns", "transits"])
