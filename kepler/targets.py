"""The featured stars: why each one matters, and which story its page tells."""
from dataclasses import dataclass, field

# What a star's page walks through:
PLANET = "planet"      # the full search: download, clean, flatten, search, fold, results
ECLIPSES = "eclipses"  # two stars eclipsing each other, instead of a planet
DIPS = "dips"          # stop after cleaning and look at dips no planet explains

STANDARD_WINDOW = 1.0            # days
STANDARD_PERIODS = (0.5, 20.0)   # days
STANDARD_PLANETS_TO_FIND = 3


@dataclass(frozen=True)
class Target:
    name: str                  # what we call it on screen
    tagline: str               # a few words for the sidebar
    blurb: str                 # why it matters
    lookup: str = ""           # the name NASA's archives find fastest, if not `name`
    story: str = PLANET
    window_days: float = STANDARD_WINDOW
    periods: tuple = STANDARD_PERIODS
    planets_to_find: int = STANDARD_PLANETS_TO_FIND
    missed_notes: dict = field(default_factory=dict)  # planet → why a simple search misses it


FEATURED = [
    Target(
        "Kepler-10", "Kepler's first rocky planet",
        "Kepler's first confirmed rocky planet, announced in January 2011. It's about "
        "1.5× Earth's size and so close to its star that a year there lasts 20 hours.",
    ),
    Target(
        "Kepler-16", "A planet with two suns",
        "The first confirmed planet orbiting two stars, announced in 2011 and nicknamed "
        "\"Tatooine.\" The two stars also eclipse each other every 41 days, and those "
        "eclipses are far deeper than any planet's dip.",
        story=ECLIPSES, periods=(20.0, 50.0),
    ),
    Target(
        "Kepler-22", "First planet in a habitable zone",
        "Kepler's first planet in its star's habitable zone, where liquid water could "
        "exist, announced in December 2011. Its year lasts 290 days, so in four years "
        "Kepler saw it cross its star only four times, and with so few dips, a couple "
        "of glitches in the data are enough to fool our search. Step ⑤ lets you fold "
        "on NASA's orbit instead.",
        periods=(200.0, 400.0),
    ),
    Target(
        "Kepler-90", "8 planets, as many as our Solar System",
        "Eight known planets, as many as our Solar System. The eighth, Kepler-90 i, was "
        "found in 2017 by a neural network that Google researchers trained on Kepler "
        "data. One search finds the biggest planet; step ⑦ hunts for the rest.",
        periods=(0.5, 400.0), planets_to_find=8,
        missed_notes={"Kepler-90 i": (
            "Kepler-90 i dims its star by less than 0.01%, too little for a simple search "
            "to pick out of the noise. It went unnoticed until 2017, when Christopher "
            "Shallue (Google) and Andrew Vanderburg (University of Texas) trained a neural "
            "network to tell faint planet signals from noise, and used it to take a second "
            "look at stars already known to have planets. This is where a simple search "
            "stops working, and why that machine-learning result mattered."
        )},
    ),
    Target(
        "Boyajian's Star", "Dips no planet can explain",
        "Spotted in Kepler data by volunteers in the Planet Hunters project and "
        "published in 2016. Its brightness dropped by up to a fifth, at irregular "
        "times and in irregular shapes. No planet does that.",
        lookup="KIC 8462852", story=DIPS,
    ),
]


def find(name):
    """The featured target with this name (any capitalization), or None."""
    name = (name or "").strip().lower()
    for target in FEATURED:
        if name in (target.name.lower(), target.lookup.lower()):
            return target
    return None
