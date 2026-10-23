"""Processing the data: turn raw brightness measurements into a planet detection."""
from dataclasses import dataclass

import numpy as np
from astropy.timeseries import BoxLeastSquares

CADENCE_DAYS = 29.4244 / (60 * 24)  # Kepler measured each star's brightness every 29.4 minutes
EARTH_RADII_PER_SUN = 109.1


@dataclass
class Signal:
    period: float        # days between dips
    transit_time: float  # when one dip happened (Kepler's clock, in days)
    duration: float      # how long each dip lasts, in days
    depth: float         # how much dimmer the star gets (0.001 = 0.1%)


def clean(quarters):
    """Join every quarter into one light curve, scaled so the star's normal brightness is 1.

    Lightkurve already drops measurements Kepler flagged as bad (e.g. during
    thruster firings); here we also drop gaps where there's no measurement.
    """
    return quarters.stitch().remove_nans()


def flatten(light_curve, window_days=1.0, transit_mask=None):
    """Remove slow brightness changes (starspots, instrument drift) so only short dips remain.

    The window should be much longer than a transit, or the transits get
    flattened away too. transit_mask marks known dips to protect them.
    """
    window = int(window_days / CADENCE_DAYS) | 1  # needs an odd number of points
    return light_curve.flatten(window_length=window, mask=transit_mask)


def remove_outliers(light_curve, sigma=4):
    """Drop single points that spike upward (cosmic rays, glitches).

    Only upward spikes: downward dips might be planets!
    """
    return light_curve.remove_outliers(sigma_upper=sigma, sigma_lower=np.inf)


def search_for_planet(light_curve, min_period=0.5, max_period=20):
    """Box Least Squares: try many possible orbits and find the one that lines up the most dips.

    Returns the search result (period vs. signal strength, for plotting) and
    the strongest signal found.
    """
    time = light_curve.time.value
    flux = _plain(light_curve.flux)
    flux_err = _plain(light_curve.flux_err)

    # Quick search on hourly averages, which is twice as fast...
    hourly = _hourly_averages(time, flux, flux_err)
    search = _box_least_squares(*hourly, _period_grid(time, min_period, max_period))
    rough_period = search.period[np.argmax(search.power)]

    # ...then a fine search near the best period using every measurement,
    # because averaging blurs the dip and makes it look shallower.
    nearby = np.linspace(rough_period * 0.999, rough_period * 1.001, 200)
    return search, _strongest_signal(_box_least_squares(time, flux, flux_err, nearby))


def _hourly_averages(time, flux, flux_err):
    """Average the measurements in each hour (Kepler took about two per hour)."""
    hour = np.floor((time - time.min()) * 24).astype(int)
    count = np.bincount(hour)
    has_data = count > 0
    count = count[has_data]
    return (
        np.bincount(hour, time)[has_data] / count,
        np.bincount(hour, flux)[has_data] / count,
        np.sqrt(np.bincount(hour, flux_err**2)[has_data]) / count,
    )


def _box_least_squares(time, flux, flux_err, periods):
    """Slide a box-shaped dip across the data at each period and score how well it fits."""
    durations = np.geomspace(1, 10, 8) / 24  # try dips lasting 1 to 10 hours
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

    Over 4 years, a slightly wrong period makes the predicted dips drift away
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


def _plain(values):
    """Plain numbers without units or masks, which BoxLeastSquares needs."""
    values = getattr(values, "value", values)
    return np.asarray(getattr(values, "unmasked", values), dtype=float)


def fold(light_curve, signal):
    """Stack every orbit on top of each other, so all the dips line up at time zero."""
    return light_curve.fold(period=signal.period, epoch_time=signal.transit_time)


def transit_mask(light_curve, signal):
    """Mark which measurements fall during this planet's dips (with some margin)."""
    return light_curve.create_transit_mask(
        period=signal.period, transit_time=signal.transit_time, duration=2 * signal.duration
    )


def planet_radius(signal, star_radius_suns):
    """A planet blocks (its size / star's size)² of the light, so size = star size × √depth."""
    return star_radius_suns * EARTH_RADII_PER_SUN * np.sqrt(signal.depth)
