"""Kepler Planet Finder: follow real NASA Kepler data from download to discovery.

Run with:  streamlit run app.py
"""
import inspect
import warnings
from dataclasses import astuple
from datetime import datetime, timedelta

import numpy as np
import streamlit as st

warnings.filterwarnings("ignore")  # lightkurve/astropy are chatty about harmless things

from kepler import fetch, plots, process, targets  # noqa: E402 (must come after silencing warnings)

WINDOW_CHOICES = [0.1, 0.25, 0.5, 1.0, 2.0, 3.0]  # days
PERIOD_CHOICES = [0.3, 0.5, 1.0, 2.0, 5.0, 10.0, 20.0, 50.0, 100.0, 200.0, 400.0]  # days
OUR_SIGNAL = "Our strongest signal"
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


@st.cache_data(show_spinner=False, max_entries=200)
def next_planet(_light_curve, kic, window_days, min_period, max_period, found):
    """One more round of "hide what we found, search again", cached so a second visit is instant."""
    return process.search_without(_light_curve, [process.Signal(*s) for s in found],
                                  window_days, min_period, max_period)


# ── Switching stars ──────────────────────────────────────────────────────────
def pick_featured():
    st.session_state.star_name = ""


def search_typed_star():
    target = targets.find(st.session_state.star_name)
    st.session_state.featured = target.name if target else None


def search_for(name):
    st.session_state.star_name = name
    search_typed_star()


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


def plot(figure, toolbar=True):
    st.plotly_chart(figure, theme=None, config={"displaylogo": False, "displayModeBar": toolbar})


def days(value):
    return f"{value:g} day" + ("" if value == 1 else "s")


def echo_description(echo):
    """("Kepler-18 c", 2) → "half of Kepler-18 c's orbit"."""
    planet, ratio = echo
    words = {2: "half", 3: "a third", 1 / 2: "twice", 1 / 3: "three times"}[ratio]
    return f"{words} {'of ' if ratio > 1 else ''}{planet['name']}'s orbit"


def calendar_date(kepler_days):
    """Kepler's clock counts days from noon on 1 Jan 2009."""
    return (datetime(2009, 1, 1, 12) + timedelta(days=float(kepler_days))).strftime("%b %d, %Y")


# ── Sidebar ──────────────────────────────────────────────────────────────────
st.session_state.setdefault("featured", targets.FEATURED[0].name)
st.session_state.setdefault("star_name", "")
name = st.session_state.star_name.strip() or st.session_state.featured
target = targets.find(name)
story = target.story if target else targets.PLANET
with st.sidebar:
    st.header("Pick a star")
    st.radio(
        "Featured stars", [t.name for t in targets.FEATURED], captions=[t.tagline for t in targets.FEATURED],
        key="featured", on_change=pick_featured,
    )
    st.text_input("…or search any Kepler star", key="star_name", on_change=search_typed_star,
                  placeholder="e.g. Kepler-11, KOI-72",
                  help="A Kepler or KOI name, or a number from the Kepler Input Catalog (KIC).")

    # Each star gets its own sliders (note the keys), starting from the settings that suit it.
    st.header("Settings")
    window_days = st.select_slider(
        "Flatten window (days)", WINDOW_CHOICES, key=f"window_days {name}", format_func=lambda d: f"{d:g}",
        value=target.window_days if target else targets.STANDARD_WINDOW,
        help="How much data around each moment we use to estimate the star's normal "
             "brightness. Too short, and flattening erases the dips along with the trends.",
    )
    min_period, max_period = st.select_slider(
        "Orbits to search (days)", PERIOD_CHOICES, key=f"periods {name}", format_func=lambda d: f"{d:g}",
        value=target.periods if target else targets.STANDARD_PERIODS,
        help="The shortest and longest orbits to try. A wider range can find more, but takes longer.",
    )
    planets_to_find = st.slider(
        "Planets to find", 1, 8, key=f"planets {name}",
        value=target.planets_to_find if target else targets.STANDARD_PLANETS_TO_FIND,
        help="How many times step ⑦ hides the dips it found and searches again.",
    ) if story == targets.PLANET else 1

st.title("Finding a planet in Kepler data")
st.markdown(
    "From 2009 to 2013, NASA's Kepler space telescope stared at one patch of sky "
    "and measured the brightness of about 150,000 stars every half hour. When a "
    "planet passes in front of its star, the star dims very slightly. Below, we "
    "follow one star's measurements from download to discovery."
)

if not name:
    st.info("Pick a featured star or type a star's name in the sidebar to begin.")
    st.stop()
if min_period >= max_period:
    st.error("Pick a range of orbits to search: the two ends of the slider are on the same value.")
    st.stop()

with st.spinner(f"Looking up {name} and downloading its Kepler data (the first time can take a minute)…"):
    try:
        loaded = load_star(target.lookup or target.name if target else name)
    except fetch.ArchiveUnavailable as problem:
        loaded = problem
if isinstance(loaded, Exception):
    explain_and_stop(loaded, name)
star, planets, quarters = loaded
known = planets[planets["transits"]]

display_name = target.name if target else star.name
st.subheader(display_name)
if target:
    st.markdown(target.blurb)

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

# ── ③ Boyajian's Star stops here: what are these dips? ───────────────────────
if story == targets.DIPS:
    st.header("③ What are these dips?", divider="gray")
    found = process.find_dips(light_curve)
    st.markdown(
        "Most of the time this star's brightness barely changes. But a few times in "
        "four years it dimmed far more than any planet could make it, for days at a "
        "time, and no two dips look alike:"
    )
    plot(plots.dips(light_curve, found))
    st.dataframe(
        {
            "Dip": list("ABCDEFGHIJ"[:len(found)]),
            "Deepest on": [calendar_date(d["deepest_time"]) for d in found],
            "Dimmer by": [f"{d['depth']:.0%}" for d in found],
            "Lasted": [f"about {days(round(d['end'] - d['start'], 1))}" for d in found],
        },
        hide_index=True,
    )
    st.markdown(
        "**Why not a planet?** A planet's dips repeat on a schedule, keep the same "
        "depth and shape, and last hours. These don't repeat, range from a few percent "
        "to a fifth of the star's light, and last days. Even a planet as big as Jupiter "
        "dims a Sun-like star by only about 1%.\n\n"
        "**So what is it?** The leading explanation is uneven clouds of dust passing in "
        "front of the star. In 2018, new dips seen from the ground were deeper in blue "
        "light than in red, which is what dust does; a solid object would block every "
        "color equally.\n\n"
        "We stop here: flattening would erase dips this long, and a search for "
        "repeating dips has nothing to find."
    )
    show_code(process.find_dips)
    st.stop()

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

# ── ⑤–⑥ Kepler-16: the stars eclipse each other ─────────────────────────────
if story == targets.ECLIPSES:
    st.header("⑤ Fold: stack every orbit", divider="gray")
    second = process.find_second_eclipse(flat, first_guess)
    gap = (second.transit_time - first_guess.transit_time) % first_guess.period
    protect = process.transit_mask(light_curve, first_guess) | process.transit_mask(light_curve, second)
    flat = process.remove_outliers(process.flatten(light_curve, window_days, protect))
    second = process.find_second_eclipse(flat, first_guess)  # re-measure, now undamaged by flattening
    st.markdown(
        f"We fold on the {first_guess.period:.1f}-day signal and stack every "
        f"orbit. Then we hide those dips and search the same orbit again, and find a "
        f"second, shallower dip {days(round(gap, 1))} after the first. Two dips per "
        f"orbit: the two stars are taking turns blocking each other. (As with a "
        f"planet, we flatten again with both dips protected before stacking.)"
    )
    columns = st.columns(2)
    for column, signal, title in [
        (columns[0], first_guess, "**Deep eclipse:** the small star passes in front of the big one"),
        (columns[1], second, "**Shallow eclipse:** the small star hides behind the big one"),
    ]:
        with column:
            st.markdown(f"{title}, {signal.depth:.1%} dimmer.")
            plot(plots.eclipse(process.fold(flat, signal), signal))
    caption = "Gray: single measurements. Blue: averages of nearby measurements."
    if abs(gap - first_guess.period / 2) > 0.5:
        caption += (f" The shallow eclipse isn't halfway round the orbit "
                    f"({days(round(first_guess.period / 2, 1))}) because the orbit is slightly oval.")
    st.caption(caption)
    show_code(process.find_second_eclipse, process.fold)

    st.header("⑥ What we found", divider="gray")
    star_size = fetch.star_radius(planets, quarters)
    size_suns = star_size * np.sqrt(first_guess.depth) if star_size else None
    columns = st.columns(3)
    columns[0].metric("Orbit", days(round(first_guess.period, 1)))
    columns[1].metric("Dip depth", f"{first_guess.depth:.1%}")
    columns[2].metric("Size", f"{size_suns:.2f}× the Sun" if size_suns else "unknown")
    if size_suns:
        st.markdown(
            f"If this were a planet, it would be {size_suns:.2f}× the size of the Sun, "
            f"or {size_suns * process.EARTH_RADII_PER_SUN:.0f}× Earth. Jupiter, the "
            f"biggest planet in our Solar System, is a tenth of the Sun's size. Something "
            f"this big is a **star**: this is two stars orbiting each other."
        )
    if len(known):
        planet = known.iloc[0]
        st.markdown(
            f"**And the planet?** {planet['name']} circles both stars every "
            f"{days(round(planet['period_days']))}. Its dips are in the data, but because "
            f"both stars are moving, each crossing comes at a different time and lasts a "
            f"different length. Folding on one orbit can't line them up, so astronomers "
            f"had to model both stars' motion to find it."
        )
    show_code(process.planet_radius)
    st.stop()

# ── ⑤ Fold ───────────────────────────────────────────────────────────────────
st.header("⑤ Fold: stack every orbit", divider="gray")
flat, signal = process.search_again_with_dips_protected(light_curve, first_guess, window_days)
our_signal = signal
match = process.matching_known_planet(planets, signal)
others = [p for p in known["name"] if match is None or p != match["name"]]
fold_on = OUR_SIGNAL
if others:
    which = f"matches {match['name']}" if match is not None else "doesn't match any planet NASA lists"
    st.markdown(
        f"Our strongest signal {which}. You can also fold on an orbit NASA has "
        f"already published, and measure that planet's dip in our data:"
    )
    fold_on = st.selectbox("Fold on", [OUR_SIGNAL, *others], key=f"fold_on_{star.kic}")

if fold_on == OUR_SIGNAL:
    st.markdown(
        f"First, a fix: flattening can't tell a dip from a slow trend, so it shaved a "
        f"little off each dip. Now that we know when the dips happen, we flatten again "
        f"with them protected and re-measure. Then we **fold**: cut the data into one "
        f"piece per orbit and stack them so every dip lines up at time zero. A dip "
        f"hidden in the scatter appears."
    )
    code = (process.search_again_with_dips_protected, process.transit_mask, process.fold)
else:
    match = known[known["name"] == fold_on].iloc[0]
    flat, signal = process.measure_known_planet(light_curve, match, window_days)
    st.markdown(
        f"We take NASA's orbit for {fold_on} ({days(round(signal.period, 3))}), flatten "
        f"with its dips protected, and **fold**: cut the data into one piece per orbit "
        f"and stack them so every dip lines up at time zero. Then we measure how deep "
        f"the stacked dip is."
    )
    code = (process.measure_known_planet, process.transit_mask, process.fold)
folded = process.fold(flat, signal)
plot(plots.folded(folded, signal))
st.caption(
    f"Gray: single measurements. Blue: averages of nearby measurements. Orange: "
    f"a box-shaped dip {signal.depth * 1e6:,.0f} ppm deep and "
    f"{signal.duration * 24:.1f} hours long."
)
show_code(*code)

# ── ⑥ Results ────────────────────────────────────────────────────────────────
st.header("⑥ What we found", divider="gray")
star_size = fetch.star_radius(planets, quarters)
radius = process.planet_radius(signal, star_size) if star_size and signal.depth > 0 else None

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

if match is not None:
    comparison = f"NASA's Exoplanet Archive lists **{match['name']}** with a {match['period_days']:.3f}-day orbit"
    if radius and match["radius_earths"] > 0:
        error = abs(radius - match["radius_earths"]) / match["radius_earths"]
        comparison += f" and a size of {match['radius_earths']:.2f}× Earth. Our size is within {error:.0%} of NASA's"
        if error > 0.25:
            comparison += (
                ". One common reason for a big difference: neighboring planets tug on "
                "each other, so some dips arrive early or late, and stacking them "
                "blurs the dip and makes it look shallower"
            )
    st.markdown(comparison + ".")
    if fold_on == OUR_SIGNAL:  # on NASA's orbit, only the size is our own measurement
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
    echo = process.echoed_known_planet(planets, signal)
    if echo:
        planet, ratio = echo
        st.markdown(
            f"Our strongest signal's orbit is **{echo_description(echo)}**: it's an echo. "
            f"The search lined that planet's real dips up at the wrong orbit"
            + (", and stacking the empty stretches between them makes its dip look shallower"
               if ratio > 1 else "")
            + f". Try folding on {planet['name']} in step ⑤. NASA's list:"
        )
    else:
        st.markdown(
            f"Our strongest signal doesn't match {which} NASA's Exoplanet Archive lists "
            f"for this star. It could be noise, an echo of a real planet, or something "
            f"happening on the star itself. NASA's list:"
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

# ── ⑦ Look for more planets ──────────────────────────────────────────────────
st.header("⑦ Look for more planets", divider="gray")
st.markdown(
    f"A search only finds the strongest signal. To look for more planets, we hide the "
    f"dips of every planet found so far, search again, and repeat. Each round tries every "
    f"orbit from {days(min_period)} to {days(max_period)}, so this takes a while. Set how "
    f"many rounds with **Planets to find** in the sidebar."
)
settings = (star.kic, window_days, min_period, max_period, planets_to_find)
if st.button(f"Search for up to {planets_to_find} planets", type="primary"):
    st.session_state[f"ran {settings}"] = True
if st.session_state.get(f"ran {settings}"):
    found = [our_signal]
    with st.status("Searching…", expanded=True) as status:
        st.write(f"Round 1: {days(round(our_signal.period, 3))} (from step ⑤)")
        for number in range(2, planets_to_find + 1):
            status.update(label=f"Round {number} of {planets_to_find}: hiding what we've found and searching again…")
            found.append(next_planet(light_curve, star.kic, window_days, min_period, max_period,
                                     tuple(astuple(s) for s in found)))
            st.write(f"Round {number}: {days(round(found[-1].period, 3))}")
        status.update(label=f"Searched {planets_to_find} times", state="complete", expanded=False)

    matched, matches = [], []
    for s in found:
        planet = process.matching_known_planet(planets, s)
        echo = process.echoed_known_planet(planets, s) if planet is None else None
        matched += [planet["name"]] if planet is not None else []
        matches.append(planet["name"] if planet is not None else f"echo: {echo_description(echo)}" if echo else "—")
    st.dataframe(
        {
            "Round": range(1, len(found) + 1),
            "Orbit (days)": [s.period for s in found],
            "Dip depth (ppm)": [s.depth * 1e6 for s in found],
            "Size (× Earth)": [process.planet_radius(s, star_size) if star_size and s.depth > 0 else None
                               for s in found],
            "Matches NASA's": matches,
        },
        hide_index=True,
        column_config={
            "Orbit (days)": st.column_config.NumberColumn(format="%.3f"),
            "Dip depth (ppm)": st.column_config.NumberColumn(format="%.0f"),
            "Size (× Earth)": st.column_config.NumberColumn(format="%.2f"),
        },
    )
    missed = known[~known["name"].isin(matched)]
    if len(known) and missed.empty:
        st.success(f"Found all {len(known)} of the planets NASA lists for this star.")
    elif len(known):
        st.markdown(
            f"We found **{len(set(matched))} of the {len(known)}** planets NASA lists. Missed: "
            + ", ".join(f"{p['name']} ({p['period_days']:.2f}-day orbit, {p['radius_earths']:.2f}× Earth"
                        + ("" if min_period <= p["period_days"] <= max_period else ", outside your search range")
                        + ")" for _, p in missed.iterrows()) + "."
        )
        for planet_name in missed["name"]:
            if target and planet_name in target.missed_notes:
                st.info(target.missed_notes[planet_name])
    if "—" in matches:
        st.caption("Rounds that match nothing may be noise, or leftovers of a big planet's dips "
                   "that weren't completely hidden.")
show_code(process.search_without, process.echoed_known_planet)

# ── ⑧ Every known planet, and how the system compares with ours ─────────────
if len(known) >= 2:
    st.header("⑧ Every planet NASA lists here", divider="gray")
    st.markdown(
        "Folding on each of NASA's published orbits shows every planet's dip, measured "
        "in our data, including any our search missed:"
    )
    rows = list(known.iterrows())
    for pair in (rows[i:i + 2] for i in range(0, len(rows), 2)):
        for column, (_, planet) in zip(st.columns(2), pair):
            with column:
                flat_known, measured = process.measure_known_planet(light_curve, planet, window_days)
                size = process.planet_radius(measured, star_size) if star_size and measured.depth > 0 else None
                st.markdown(
                    f"**{planet['name']}**: {planet['period_days']:.2f}-day orbit. "
                    + (f"We measure {size:.2f}× Earth" if size else "Too faint to measure")
                    + f" (NASA: {planet['radius_earths']:.2f}×)."
                )
                plot(plots.folded(process.fold(flat_known, measured), measured, compact=True), toolbar=False)
    show_code(process.measure_known_planet)

    st.markdown("**Compared with our Solar System**")
    plot(plots.compared_with_solar_system(known, display_name))
    farthest = known["distance_au"].max()
    beyond = [planet for planet, _, distance in plots.SOLAR_SYSTEM if distance > farthest]
    st.caption(
        "Each dot is sized to scale with the others (the smallest are enlarged a little so "
        "they stay visible), at its distance from its star."
        + (f" The whole {display_name} system would fit inside {beyond[0]}'s orbit." if beyond else "")
    )
