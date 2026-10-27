"""Processing the data: turn raw brightness measurements into a planet detection."""
from dataclasses import dataclass

import numpy as np
from astropy.timeseries import BoxLeastSquares

EARTH_RADII_PER_SUN = 109.1


@dataclass
class Signal:
    period: float        # days between dips
    transit_time: float  # when one dip happened (the telescope's clock, in days)
    duration: float      # how long each dip lasts, in days
    depth: float         # how much dimmer the star gets (0.001 = 0.1%)


def clean(segments):
    """Join every quarter (Kepler) or sector (TESS) into one light curve, scaled so
    the star's normal brightness is 1.

    Lightkurve already drops measurements the telescope flagged as bad (e.g.
    during thruster firings); here we also drop gaps where there's no measurement.
    """
    return segments.stitch().remove_nans()


def flatten(light_curve, window_days=1.0, transit_mask=None):
    """Remove slow brightness changes (starspots, instrument drift) so only short dips remain.

    The window should be much longer than a transit, or the transits get
    flattened away too. transit_mask marks known dips to protect them.
    """
    cadence = np.median(np.diff(light_curve.time.value))  # days between measurements
    window = int(window_days / cadence) | 1  # needs an odd number of points
    return light_curve.flatten(window_length=window, mask=transit_mask)


def remove_outliers(light_curve, sigma=4):
    """Drop single points that spike upward (cosmic rays, glitches).

    Only upward spikes: downward dips might be planets!
    """
    return light_curve.remove_outliers(sigma_upper=sigma, sigma_lower=np.inf)


LONG_ORBIT = 20  # days; longer orbits have longer dips, so we can search them more coarsely


@dataclass
class Periodogram:
    period: np.ndarray  # every orbit we tried, in days
    power: np.ndarray   # how well a box-shaped dip fits at each one


def search_for_planet(light_curve, min_period=0.5, max_period=20):
    """Box Least Squares: try many possible orbits and find the one that lines up the most dips.

    Returns the search result (period vs. signal strength, for plotting) and
    the strongest signal found.
    """
    time = light_curve.time.value
    flux = plain_numbers(light_curve.flux)
    flux_err = plain_numbers(light_curve.flux_err)
    periods = _period_grid(time, min_period, max_period)

    # Quick search on averages, which is much faster: hourly averages for
    # short orbits, 3-hour averages for long orbits (whose dips last longer)...
    short, long = periods[periods < LONG_ORBIT], periods[periods >= LONG_ORBIT]
    parts = []
    if len(short):
        parts.append(_box_least_squares(*_averages(time, flux, flux_err, hours=1), short, max_dip_hours=10))
    if len(long):
        parts.append(_box_least_squares(*_averages(time, flux, flux_err, hours=3), long, max_dip_hours=15))
    search = Periodogram(np.concatenate([p.period for p in parts]), np.concatenate([p.power for p in parts]))
    rough_period = search.period[np.argmax(search.power)]

    # ...then a fine search near the best period using every measurement,
    # because averaging blurs the dip and makes it look shallower.
    nearby = np.linspace(rough_period * 0.999, rough_period * 1.001, 200)
    return search, _strongest_signal(_box_least_squares(time, flux, flux_err, nearby, max_dip_hours=15))


def _averages(time, flux, flux_err, hours):
    """Average the measurements in each stretch of this many hours."""
    stretch = np.floor((time - time.min()) * 24 / hours).astype(int)
    count = np.bincount(stretch)
    has_data = count > 0
    count = count[has_data]
    return (
        np.bincount(stretch, time)[has_data] / count,
        np.bincount(stretch, flux)[has_data] / count,
        np.sqrt(np.bincount(stretch, flux_err**2)[has_data]) / count,
    )


def _box_least_squares(time, flux, flux_err, periods, max_dip_hours):
    """Slide a box-shaped dip across the data at each period and score how well it fits."""
    durations = np.geomspace(1, max_dip_hours, 8) / 24  # try dips lasting 1 hour up to the maximum
    durations = durations[durations < periods.min() / 2]
    return BoxLeastSquares(time, flux, flux_err).power(periods, durations)


def _strongest_signal(search):
    best = np.argmax(search.power)
    return Signal(
        period=float(search.period[best]),
        transit_time=float(search.transit_time[best]),
        duration=float(search.duration[best]),
        depth=float(search.depth[best]),
    )


def _period_grid(time, min_period, max_period, oversample=2):
    """Periods to try, spaced closely enough that we can't miss a dip.

    Over years of data, a slightly wrong period makes the predicted dips drift away
    from the real ones. Planets on longer orbits have longer dips, which
    tolerate more drift, so the grid can thin out at long periods.
    """
    baseline = time.max() - time.min()
    periods = [min_period]
    while periods[-1] < max_period:
        step = _expected_dip_length(periods[-1]) / (oversample * baseline)
        periods.append(periods[-1] * (1 + step))
    return np.array(periods)


def _expected_dip_length(period):
    """Roughly how long (days) a planet with this period takes to cross a Sun-like star."""
    return 13 / 24 * (period / 365.25) ** (1 / 3)


def plain_numbers(values):
    """Plain numbers without units or masks, which BoxLeastSquares needs."""
    values = getattr(values, "value", values)
    return np.asarray(getattr(values, "unmasked", values), dtype=float)


def fold(light_curve, signal):
    """Stack every orbit on top of each other, so all the dips line up at time zero."""
    return light_curve.fold(period=signal.period, epoch_time=signal.transit_time)


def transit_mask(light_curve, signal):
    """Mark which measurements fall during this planet's dips (with some margin)."""
    return light_curve.create_transit_mask(
        period=signal.period, transit_time=signal.transit_time, duration=3 * signal.duration
    )


def search_again_with_dips_protected(light_curve, signal, window_days=1.0):
    """Flatten again with the dips we found protected, then re-measure them.

    The first flatten can't tell a dip from a slow trend, so it shaves a little
    off each dip and the planet looks smaller than it is.
    """
    mask = transit_mask(light_curve, signal)
    flat = remove_outliers(flatten(light_curve, window_days, transit_mask=mask))
    _, signal = search_for_planet(flat, signal.period * 0.999, signal.period * 1.001)
    return flat, signal


def measure_known_planet(light_curve, planet, window_days=1.0):
    """Use an orbit astronomers already published, and measure how deep its dips are in our data."""
    duration = planet["duration_hours"] / 24
    if not duration > 0:  # the archive leaves some durations blank
        duration = _expected_dip_length(planet["period_days"])
    signal = Signal(planet["period_days"], planet["transit_time"], duration, depth=0.0)
    flat = remove_outliers(flatten(light_curve, window_days, transit_mask(light_curve, signal)))

    # Compare the middle of each dip with the time around the dips.
    flux = plain_numbers(flat.flux)
    middle = flat.create_transit_mask(period=signal.period, transit_time=signal.transit_time,
                                      duration=duration / 2)
    signal.depth = float(flux[~transit_mask(flat, signal)].mean() - flux[middle].mean())
    return flat, signal


def search_without(light_curve, found, window_days=1.0, min_period=0.5, max_period=20):
    """Hide the dips of every planet found so far, then search what's left for the next one."""
    hide = np.zeros(len(light_curve), dtype=bool)
    for signal in found:
        hide |= transit_mask(light_curve, signal)
    flat = remove_outliers(flatten(light_curve, window_days, transit_mask=hide))
    for signal in found:
        flat = flat[~transit_mask(flat, signal)]
    _, signal = search_for_planet(flat, min_period, max_period)
    return signal


def find_second_eclipse(light_curve, signal):
    """Hide the deep eclipses and search the same orbit again: what's left is the shallow one."""
    hidden = light_curve[~transit_mask(light_curve, signal)]
    _, second = search_for_planet(hidden, signal.period * 0.999, signal.period * 1.001)
    return second


def find_dips(light_curve, threshold=0.01, gap_days=5):
    """Find stretches where the star dims by more than 1%, and how deep each one gets."""
    time = light_curve.time.value
    flux = plain_numbers(light_curve.flux)
    dim = np.flatnonzero(flux < 1 - threshold)
    dips = []
    # Measurements within a few days of each other belong to the same dip.
    for group in np.split(dim, np.flatnonzero(np.diff(time[dim]) > gap_days) + 1):
        if len(group):
            deepest = group[np.argmin(flux[group])]
            dips.append({"start": time[group[0]], "end": time[group[-1]],
                         "deepest_time": time[deepest], "depth": 1 - flux[deepest]})
    return dips


def planet_radius(signal, star_radius_suns):
    """A planet blocks (its size / star's size)² of the light, so size = star size × √depth."""
    return star_radius_suns * EARTH_RADII_PER_SUN * np.sqrt(signal.depth)


def matching_known_planet(planets, signal, tolerance=0.01):
    """The known planet whose orbit matches what we found to within 1% (None if none does)."""
    transiting = planets[planets["transits"]].dropna(subset=["period_days"])
    mismatch = (transiting["period_days"] - signal.period).abs() / transiting["period_days"]
    if transiting.empty or mismatch.min() > tolerance:
        return None
    return transiting.loc[mismatch.idxmin()]


def echoed_known_planet(planets, signal, tolerance=0.01):
    """A known planet whose orbit is 2× or 3× ours, or ½ or ⅓ of it: our signal is its echo.

    Returns the planet and how many of our orbits fit in one of its (None if there's no echo).
    """
    transiting = planets[planets["transits"]].dropna(subset=["period_days"])
    for ratio in (2, 3, 1 / 2, 1 / 3):
        mismatch = (transiting["period_days"] / signal.period - ratio).abs() / ratio
        if len(transiting) and mismatch.min() <= tolerance:
            return transiting.loc[mismatch.idxmin()], ratio
    return None
