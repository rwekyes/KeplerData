"""Kepler Planet Finder: follow real NASA Kepler data from download to discovery.

Run with:  streamlit run app.py
"""
import inspect
import warnings

import streamlit as st

warnings.filterwarnings("ignore")  # lightkurve/astropy are chatty about harmless things

from kepler import fetch, plots, process  # noqa: E402 (must come after silencing warnings)

TARGET = "Kepler-10"
BLURB = "Kepler's first confirmed rocky planet, announced in 2011."

# Fixed for now; these become sidebar sliders in M3.
WINDOW_DAYS = 1.0
MIN_PERIOD, MAX_PERIOD = 0.5, 20

st.set_page_config(page_title="Kepler Planet Finder", page_icon="🔭", layout="wide")


@st.cache_data(show_spinner=False)
def load_star(name):
    """Download once per star; later visits are instant."""
    star = fetch.find_star(name)
    return star, fetch.known_planets(star), fetch.download_light_curves(star)


@st.cache_data(show_spinner=False)
def search(_flat, name, window_days, min_period, max_period):
    """The slow step, cached by star and settings (the leading _ skips hashing the light curve)."""
    return process.search_for_planet(_flat, min_period, max_period)


def show_code(*functions):
    with st.expander("Show the code"):
        for function in functions:
            st.code(inspect.getsource(function))


def plot(figure):
    st.plotly_chart(figure, theme=None, config={"displaylogo": False})


st.title("Finding a planet in Kepler data")
st.markdown(
    f"### {TARGET}\n{BLURB}\n\n"
    "From 2009 to 2013, NASA's Kepler space telescope stared at one patch of sky "
    "and measured the brightness of about 150,000 stars every half hour. When a "
    "planet passes in front of its star, the star dims very slightly. Below, we "
    "follow one star's measurements from download to discovery."
)

# ── ① Download ───────────────────────────────────────────────────────────────
st.header("① Download what Kepler saw", divider="gray")
with st.spinner(f"Downloading four years of {TARGET} measurements from NASA's archive…"):
    try:
        star, planets, quarters = load_star(TARGET)
    except fetch.StarNotFound as error:
        st.error(str(error))
        st.stop()
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
flat = process.remove_outliers(process.flatten(light_curve, WINDOW_DAYS))
st.markdown(
    f"A planet's dip lasts a few hours, so we remove anything slower. At each "
    f"moment we estimate the star's normal brightness from the surrounding "
    f"{WINDOW_DAYS:g} day of data and divide by it. Then we drop single upward "
    f"spikes (cosmic rays hitting the camera), but keep downward ones: those "
    f"might be planets."
)
plot(plots.light_curve(flat))
st.caption(
    "Flat, but still no planet in sight. A planet's dip is usually smaller than "
    "the scatter between measurements, so finding one takes a search."
)
show_code(process.flatten, process.remove_outliers)

# ── ④ Search ─────────────────────────────────────────────────────────────────
st.header("④ Search for repeating dips", divider="gray")
with st.spinner("Trying about 100,000 possible orbits…"):
    periodogram, first_guess = search(flat, TARGET, WINDOW_DAYS, MIN_PERIOD, MAX_PERIOD)
st.markdown(
    f"One dip is too small to see, but a planet repeats its dip on every orbit. "
    f"**Box Least Squares** tries {len(periodogram.period):,} possible orbits "
    f"between {MIN_PERIOD:g} and {MAX_PERIOD:g} days. For each one, it lines the "
    f"data up at that orbit and checks how well a box-shaped dip fits. The taller "
    f"the peak, the better the dips line up."
)
plot(plots.period_search(periodogram))
st.caption(
    f"The tallest peak is an orbit of {first_guess.period:.3f} days "
    f"({first_guess.period * 24:.1f} hours). Smaller peaks at 2×, 3×, … that orbit "
    f"are echoes of the same signal."
)
show_code(process.search_for_planet)

# ── ⑤ Fold ───────────────────────────────────────────────────────────────────
st.header("⑤ Fold: stack every orbit", divider="gray")
flat, signal = process.search_again_with_dips_protected(light_curve, first_guess, WINDOW_DAYS)
folded = process.fold(flat, signal)
orbits = (flat.time.value.max() - flat.time.value.min()) / signal.period
st.markdown(
    f"First, a fix: flattening can't tell a dip from a slow trend, so it shaved a "
    f"little off each dip. Now that we know when the dips happen, we flatten again "
    f"with them protected and re-measure. Then we **fold**: cut the data into "
    f"{orbits:,.0f} pieces, one per orbit, and stack them so every dip lines up at "
    f"time zero. The dip that was hidden in the scatter appears."
)
plot(plots.folded(folded, signal))
st.caption(
    f"Gray: single measurements. Blue: averages of nearby measurements. Orange: "
    f"the box-shaped dip that fits best, {signal.depth * 1e6:.0f} ppm deep and "
    f"{signal.duration * 24:.1f} hours long."
)
show_code(process.search_again_with_dips_protected, process.transit_mask, process.fold)

# ── ⑥ Results ────────────────────────────────────────────────────────────────
st.header("⑥ What we found", divider="gray")
match = process.closest_known_planet(planets, signal)
star_radius = match["star_radius_suns"] if match is not None else None

columns = st.columns(3)
columns[0].metric("Orbit", f"{signal.period * 24:.1f} hours")
columns[1].metric("Dip depth", f"{signal.depth * 1e6:.0f} ppm")
if star_radius is not None:
    radius = process.planet_radius(signal, star_radius)
    columns[2].metric("Size", f"{radius:.2f}× Earth")
    st.markdown(
        f"A planet blocks a share of its star's light equal to (planet size ÷ star "
        f"size)². This star is {star_radius:.2f}× the size of the Sun, so the planet "
        f"is about **{radius:.2f}× the size of Earth**."
    )
    st.markdown(
        f"NASA's Exoplanet Archive lists **{match['name']}** with a "
        f"{match['period_days']:.3f}-day orbit and a size of {match['radius_earths']:.2f}× "
        f"Earth. Our size is within "
        f"{abs(radius - match['radius_earths']) / match['radius_earths']:.0%} of NASA's."
    )
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
else:
    st.markdown("NASA's Exoplanet Archive doesn't list a planet here, so we have nothing to compare against.")
show_code(process.planet_radius, process.closest_known_planet, fetch.known_planets)
