"""Kepler Planet Finder: follow real NASA Kepler data from download to discovery.

Run with:  streamlit run app.py
"""
import inspect
import warnings

import streamlit as st

warnings.filterwarnings("ignore")  # lightkurve/astropy are chatty about harmless things

from kepler import fetch, plots, process  # noqa: E402 (must come after silencing warnings)

DEFAULT_STAR = "Kepler-10"
BLURBS = {"Kepler-10": "Kepler's first confirmed rocky planet, announced in 2011."}  # more in M4
WINDOW_CHOICES = [0.1, 0.25, 0.5, 1.0, 2.0, 3.0]  # days
PERIOD_CHOICES = [0.3, 0.5, 1.0, 2.0, 5.0, 10.0, 20.0, 50.0, 100.0, 200.0, 400.0]  # days
NAME_HELP = (
    "Names that work: **Kepler** numbers (Kepler-22), **KOI** numbers (KOI-72), "
    "**KIC** numbers (KIC 11904151, or just 11904151), and well-known star names "
    "(Boyajian's Star)."
)

st.set_page_config(page_title="Kepler Planet Finder", page_icon="🔭", layout="wide")


@st.cache_data(show_spinner=False, max_entries=10)
def load_star(name):
    """Find and download a star once; later visits are instant.

    "No such star" answers are cached too, so a typo doesn't trigger another
    slow lookup every time someone moves a slider.
    """
    try:
        star = fetch.find_star(name)
        return star, fetch.known_planets(star), fetch.download_light_curves(star)
    except (fetch.StarNotFound, fetch.NotObservedByKepler) as problem:
        return problem


@st.cache_data(show_spinner=False, max_entries=20)
def search(_flat, kic, window_days, min_period, max_period):
    """The slow step, cached by star and settings (the leading _ skips hashing the light curve)."""
    return process.search_for_planet(_flat, min_period, max_period)


def search_for(name):
    st.session_state.star_name = name


def explain_and_stop(problem, name):
    """Show a friendly message instead of a stack trace, then stop the page here."""
    if isinstance(problem, fetch.StarNotFound):
        st.error(f"Couldn't find a star called **{name}**.")
        guess = fetch.suggest_name(name)
        if guess:
            st.button(f"Did you mean {guess}?", on_click=search_for, args=(guess,))
        st.markdown(NAME_HELP)
    elif isinstance(problem, fetch.NotObservedByKepler):
        st.warning(str(problem))
        st.markdown(NAME_HELP)
    else:
        st.error(
            f"{problem} Check the internet connection, or try again in a minute: "
            f"NASA's archives are sometimes slow or down for maintenance."
        )
        st.button("Try again")
    st.stop()


def show_code(*functions):
    with st.expander("Show the code"):
        for function in functions:
            st.code(inspect.getsource(function))


def plot(figure):
    st.plotly_chart(figure, theme=None, config={"displaylogo": False})


def days(value):
    return f"{value:g} day" + ("" if value == 1 else "s")


# ── Sidebar ──────────────────────────────────────────────────────────────────
st.session_state.setdefault("star_name", DEFAULT_STAR)
with st.sidebar:
    st.header("Pick a star")
    st.text_input("Search any Kepler star", key="star_name",
                  help="A Kepler or KOI name, or a number from the Kepler Input Catalog (KIC).")
    st.caption("For example: Kepler-10, Kepler-22, KOI-72, or KIC 11904151.")

    st.header("Settings")
    window_days = st.select_slider(
        "Flatten window (days)", WINDOW_CHOICES, value=1.0, format_func=lambda d: f"{d:g}",
        help="How much data around each moment we use to estimate the star's normal "
             "brightness. Too short, and flattening erases the dips along with the trends.",
    )
    min_period, max_period = st.select_slider(
        "Orbits to search (days)", PERIOD_CHOICES, value=(0.5, 20.0), format_func=lambda d: f"{d:g}",
        help="The shortest and longest orbits to try. A wider range can find more, but takes longer.",
    )

st.title("Finding a planet in Kepler data")
st.markdown(
    "From 2009 to 2013, NASA's Kepler space telescope stared at one patch of sky "
    "and measured the brightness of about 150,000 stars every half hour. When a "
    "planet passes in front of its star, the star dims very slightly. Below, we "
    "follow one star's measurements from download to discovery."
)

name = st.session_state.star_name.strip()
if not name:
    st.info("Type a star's name in the sidebar to begin.")
    st.stop()
if min_period >= max_period:
    st.error("Pick a range of orbits to search: the two ends of the slider are on the same value.")
    st.stop()

with st.spinner(f"Looking up {name} and downloading its Kepler data (the first time can take a minute)…"):
    try:
        loaded = load_star(name)
    except fetch.ArchiveUnavailable as problem:
        loaded = problem
if isinstance(loaded, Exception):
    explain_and_stop(loaded, name)
star, planets, quarters = loaded

st.subheader(star.name)
if star.name in BLURBS:
    st.markdown(BLURBS[star.name])

# ── ① Download ───────────────────────────────────────────────────────────────
st.header("① Download what Kepler saw", divider="gray")
st.markdown(
    f"Kepler measured this star's brightness every 29.4 minutes. Every three months "
    f"the spacecraft rolled to keep its solar panels facing the Sun, so NASA's "
    f"archive splits the data into **quarters**. We look up the star's catalog "
    f"number (KIC {star.kic}) and download all {len(quarters)} quarters."
)
plot(plots.raw_quarters(quarters))
st.caption(
    "Alternating colors mark the quarters. Each roll put the star on a different "
    "part of Kepler's camera, so each quarter reads at a different level."
)
show_code(fetch.find_star, fetch.download_light_curves)

# ── ② Clean ──────────────────────────────────────────────────────────────────
st.header("② Clean and join", divider="gray")
light_curve = process.clean(quarters)
st.markdown(
    "To join the quarters, we divide each one by its own average, so *normal "
    "brightness* means the same thing everywhere. We also drop moments with no "
    "measurement. From here on, brightness is shown in **parts per million (ppm)** "
    "above or below normal: 100 ppm is 0.01%."
)
plot(plots.light_curve(light_curve))
st.caption(
    "The slow ups and downs come from the star itself (spots rotating into view) "
    "and from the telescope drifting slightly. A planet's dip lasts only hours."
)
show_code(process.clean)

# ── ③ Flatten ────────────────────────────────────────────────────────────────
st.header("③ Flatten", divider="gray")
flat = process.remove_outliers(process.flatten(light_curve, window_days))
st.markdown(
    f"A planet's dip lasts a few hours, so we remove anything slower. At each "
    f"moment we estimate the star's normal brightness from the surrounding "
    f"{days(window_days)} of data and divide by it. Then we drop single upward "
    f"spikes (cosmic rays hitting the camera), but keep downward ones: those "
    f"might be planets."
)
plot(plots.light_curve(flat))
st.caption(
    "Flat, but still no planet in sight. A planet's dip is usually smaller than "
    "the scatter between measurements, so finding one takes a search. Try a "
    "shorter flatten window in the sidebar: once it's not much longer than a dip, "
    "flattening starts erasing the dips too."
)
show_code(process.flatten, process.remove_outliers)

# ── ④ Search ─────────────────────────────────────────────────────────────────
st.header("④ Search for repeating dips", divider="gray")
with st.spinner(f"Trying every orbit from {days(min_period)} to {days(max_period)}…"):
    periodogram, first_guess = search(flat, star.kic, window_days, min_period, max_period)
st.markdown(
    f"One dip is too small to see, but a planet repeats its dip on every orbit. "
    f"**Box Least Squares** tries {len(periodogram.period):,} possible orbits "
    f"between {days(min_period)} and {days(max_period)}. For each one, it lines the "
    f"data up at that orbit and checks how well a box-shaped dip fits. The taller "
    f"the peak, the better the dips line up."
)
plot(plots.period_search(periodogram))
st.caption(
    f"The tallest peak is an orbit of {days(round(first_guess.period, 3))}. Smaller "
    f"peaks at 2×, 3×, … that orbit are usually echoes of the same signal."
)
show_code(process.search_for_planet)

# ── ⑤ Fold ───────────────────────────────────────────────────────────────────
st.header("⑤ Fold: stack every orbit", divider="gray")
flat, signal = process.search_again_with_dips_protected(light_curve, first_guess, window_days)
folded = process.fold(flat, signal)
orbits = (flat.time.value.max() - flat.time.value.min()) / signal.period
st.markdown(
    f"First, a fix: flattening can't tell a dip from a slow trend, so it shaved a "
    f"little off each dip. Now that we know when the dips happen, we flatten again "
    f"with them protected and re-measure. Then we **fold**: cut the data into "
    f"{orbits:,.0f} pieces, one per orbit, and stack them so every dip lines up at "
    f"time zero. A dip hidden in the scatter appears."
)
plot(plots.folded(folded, signal))
st.caption(
    f"Gray: single measurements. Blue: averages of nearby measurements. Orange: "
    f"the box-shaped dip that fits best, {signal.depth * 1e6:,.0f} ppm deep and "
    f"{signal.duration * 24:.1f} hours long."
)
show_code(process.search_again_with_dips_protected, process.transit_mask, process.fold)

# ── ⑥ Results ────────────────────────────────────────────────────────────────
st.header("⑥ What we found", divider="gray")
match = process.matching_known_planet(planets, signal)
star_size = fetch.star_radius(planets, quarters)
radius = process.planet_radius(signal, star_size) if star_size else None

columns = st.columns(3)
columns[0].metric("Orbit", f"{signal.period * 24:.1f} hours" if signal.period < 2 else days(round(signal.period, 1)))
columns[1].metric("Dip depth", f"{signal.depth * 1e6:,.0f} ppm")
columns[2].metric("Size", f"{radius:.2f}× Earth" if radius else "unknown")
if radius:
    st.markdown(
        f"A planet blocks a share of its star's light equal to (planet size ÷ star "
        f"size)². This star is {star_size:.2f}× the size of the Sun, so the planet "
        f"would be about **{radius:.2f}× the size of Earth**."
    )

known = planets[planets["transits"]]
if match is not None:
    comparison = f"NASA's Exoplanet Archive lists **{match['name']}** with a {match['period_days']:.3f}-day orbit"
    if radius and match["radius_earths"] > 0:
        error = abs(radius - match["radius_earths"]) / match["radius_earths"]
        comparison += f" and a size of {match['radius_earths']:.2f}× Earth. Our size is within {error:.0%} of NASA's"
    st.markdown(comparison + ".")
    st.dataframe(
        {
            "": ["Orbit (days)", "Dip length (hours)", "Size (× Earth)"],
            "We measured": [signal.period, signal.duration * 24, radius],
            "NASA's archive": [match["period_days"], match["duration_hours"], match["radius_earths"]],
        },
        hide_index=True,
        column_config={
            "We measured": st.column_config.NumberColumn(format="%.3f"),
            "NASA's archive": st.column_config.NumberColumn(format="%.3f"),
        },
    )
elif len(known):
    which = "the planet" if len(known) == 1 else f"any of the {len(known)} planets"
    st.markdown(
        f"Our strongest signal doesn't match {which} NASA's Exoplanet Archive lists "
        f"for this star. It could be noise, an echo of a "
        f"real planet, or something happening on the star itself. NASA's list:"
    )
    in_range = known["period_days"].between(min_period, max_period)
    st.dataframe(
        {
            "Planet": known["name"],
            "Orbit (days)": known["period_days"],
            "Size (× Earth)": known["radius_earths"],
            "In your search range?": in_range.map({True: "yes", False: "no"}),
        },
        hide_index=True,
        column_config={
            "Orbit (days)": st.column_config.NumberColumn(format="%.3f"),
            "Size (× Earth)": st.column_config.NumberColumn(format="%.2f"),
        },
    )
    if not in_range.all():
        st.info("Some of these orbits are outside the range you searched. Widen "
                "**Orbits to search** in the sidebar to include them.")
else:
    st.markdown(
        "NASA's Exoplanet Archive doesn't list any planets crossing in front of this "
        "star, so there's nothing to compare against. The strongest peak can still be "
        "noise or something happening on the star itself: astronomers run many more "
        "checks before calling a signal a planet."
    )
show_code(process.planet_radius, process.matching_known_planet, fetch.known_planets)
