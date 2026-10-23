"""Interactive plots, styled to read well on a projector and on a phone."""
import numpy as np
import plotly.graph_objects as go

from kepler.process import plain_numbers

# A colorblind-safe pair for the data, and quiet grays for everything else.
BLUE = "#2a78d6"
ORANGE = "#eb6834"
INK = "#0b0b0b"
MUTED_INK = "#52514e"
GRID = "#e6e5e0"
FAINT_POINTS = "#c4c3bc"

# Kepler's clock starts at noon on 1 Jan 2009; Plotly's date axes count
# milliseconds since 1970.
KEPLER_START_MS = float(np.datetime64("2009-01-01T12:00", "ms").astype("int64"))
MS_PER_DAY = 86_400_000


def raw_quarters(quarters):
    """Each quarter as Kepler recorded it, in alternating colors so the seams show."""
    fig = go.Figure()
    for i, quarter in enumerate(quarters):
        fig.add_trace(go.Scattergl(
            x=_dates(quarter.time.value),
            y=plain_numbers(quarter.flux),
            name=f"Quarter {quarter.meta['QUARTER']}",
            mode="markers",
            marker=dict(size=2, color=(BLUE, ORANGE)[i % 2]),
            hovertemplate="%{x|%b %d, %Y}<br>%{y:,.0f} electrons/s<extra>%{fullData.name}</extra>",
        ))
    fig.update_layout(showlegend=False)
    fig.update_xaxes(type="date")
    return _style(fig, None, "Brightness (electrons/s)")


def light_curve(lc):
    """A whole light curve, in parts per million above or below normal brightness."""
    fig = go.Figure(go.Scattergl(
        x=_dates(lc.time.value),
        y=_ppm(lc.flux),
        mode="markers",
        marker=dict(size=2, color=BLUE),
        hovertemplate="%{x|%b %d, %Y}<br>%{y:+,.0f} ppm<extra></extra>",
    ))
    fig.update_xaxes(type="date")
    return _style(fig, None, "Brightness change (ppm)")


def period_search(search):
    """Signal strength for every orbit we tried, with the strongest one marked."""
    period, power = _keep_peaks(search.period, search.power)
    best = np.argmax(search.power)
    best_period, best_power = search.period[best], search.power[best]
    fig = go.Figure([
        go.Scattergl(
            x=period, y=power, mode="lines", line=dict(color=BLUE, width=2),
            hovertemplate="%{x:.3f} days<br>strength %{y:,.0f}<extra></extra>",
        ),
        go.Scatter(
            x=[best_period], y=[best_power], mode="markers",
            marker=dict(size=12, color=ORANGE, line=dict(color="white", width=2)),
            hovertemplate="%{x:.4f} days<br>strength %{y:,.0f}<extra>Strongest signal</extra>",
        ),
    ])
    fig.add_annotation(
        x=np.log10(best_period), y=best_power, text=f"<b>{best_period:.3f} days</b>",
        showarrow=False, xanchor="left", xshift=12, font=dict(color=INK),
    )
    fig.update_layout(showlegend=False)
    fig.update_xaxes(type="log", tickvals=[0.5, 1, 2, 5, 10, 20, 50, 100, 200, 500])
    return _style(fig, "Orbit tried (days)", "Signal strength")


def folded(folded_lc, signal):
    """All orbits stacked: single measurements, their averages, and the best-fit box."""
    hours = folded_lc.time.value * 24
    ppm = _ppm(folded_lc.flux)
    duration = signal.duration * 24
    window = max(3 * duration, 3)  # hours to show on each side of the dip
    near = np.abs(hours) < window
    hours, ppm = hours[near], ppm[near]
    bin_hours, bin_ppm = _averages(hours, ppm, width=duration / 8)

    # The box hangs from the star's average level outside the dip, a hair below
    # 0 because we removed upward spikes but kept the downward ones.
    half = duration / 2
    level = np.mean(ppm[np.abs(hours) > duration])
    bottom = level - signal.depth * 1e6
    # All WebGL, because Plotly always draws WebGL above regular traces and
    # the averages and box need to sit on top of the cloud of points.
    fig = go.Figure([
        go.Scattergl(
            x=hours, y=ppm, name="Single measurements", mode="markers",
            marker=dict(size=3, color=FAINT_POINTS), hoverinfo="skip",
        ),
        go.Scattergl(
            x=bin_hours, y=bin_ppm, name="Averages", mode="markers",
            marker=dict(size=9, color=BLUE, line=dict(color="white", width=2)),
            hovertemplate="%{x:+.1f} h<br>%{y:+.0f} ppm<extra>Average</extra>",
        ),
        go.Scattergl(
            x=[-window, -half, -half, half, half, window], y=[level, level, bottom, bottom, level, level],
            name="Best-fit dip", mode="lines", line=dict(color=ORANGE, width=3),
            hovertemplate="%{y:+.0f} ppm<extra>Best-fit dip</extra>",
        ),
    ])
    # Zoom on the bulk of the points so the dip isn't squashed by a few strays.
    low, high = np.percentile(ppm, [1, 99])
    fig.update_yaxes(range=[min(low, level + 1.5 * (bottom - level)), high])
    fig.update_xaxes(range=[-window, window])
    return _style(fig, "Hours from the middle of the dip", "Brightness change (ppm)")


def eclipse(folded_lc, signal):
    """One eclipse, zoomed in: every orbit stacked, in percent."""
    hours = folded_lc.time.value * 24
    percent = _percent(folded_lc.flux)
    window = 3 * signal.duration * 24  # hours to show on each side
    near = np.abs(hours) < window
    hours, percent = hours[near], percent[near]
    bin_hours, bin_percent = _averages(hours, percent, width=signal.duration * 24 / 8)
    fig = go.Figure([
        go.Scattergl(
            x=hours, y=percent, name="Single measurements", mode="markers",
            marker=dict(size=3, color=FAINT_POINTS), hoverinfo="skip",
        ),
        go.Scattergl(
            x=bin_hours, y=bin_percent, name="Averages", mode="markers",
            marker=dict(size=9, color=BLUE, line=dict(color="white", width=2)),
            hovertemplate="%{x:+.1f} h<br>%{y:+.2f}%<extra>Average</extra>",
        ),
    ])
    fig.update_layout(showlegend=False)  # two of these sit side by side; the caption explains the colors
    fig.update_xaxes(range=[-window, window])
    return _style(fig, "Hours from the middle of the eclipse", "Brightness change (%)")


def dips(lc, found):
    """The whole light curve in percent, with each big dip lettered."""
    fig = go.Figure(go.Scattergl(
        x=_dates(lc.time.value), y=_percent(lc.flux), mode="markers",
        marker=dict(size=2, color=BLUE),
        hovertemplate="%{x|%b %d, %Y}<br>%{y:+.1f}%<extra></extra>",
    ))
    for letter, dip in zip("ABCDEFGHIJ", found):
        fig.add_annotation(x=_dates(dip["deepest_time"]), y=-dip["depth"] * 100, text=f"<b>{letter}</b>",
                           showarrow=True, arrowcolor=MUTED_INK, ax=0, ay=28, font=dict(color=INK, size=20))
    fig.update_xaxes(type="date")
    fig.update_yaxes(range=[-100 * max(d["depth"] for d in found) - 6, 3] if found else None)
    return _style(fig, None, "Brightness change (%)")


def _style(fig, x_title, y_title):
    """Big text, light gridlines, and nothing that needs a wide screen."""
    fig.update_layout(
        height=430,
        font=dict(size=18, color=INK),
        paper_bgcolor="white",
        plot_bgcolor="white",
        margin=dict(l=10, r=10, t=10, b=10),  # axes grow it as their labels need
        legend=dict(orientation="h", x=0, y=1.02, yanchor="bottom"),
        hoverlabel=dict(font_size=16),
    )
    axes = dict(automargin=True, gridcolor=GRID, linecolor=GRID, zeroline=False, title_font_color=MUTED_INK,
                tickfont_color=MUTED_INK)
    fig.update_xaxes(title=x_title, **axes)
    fig.update_yaxes(title=y_title, **axes)
    return fig


def _dates(kepler_days):
    return KEPLER_START_MS + kepler_days * MS_PER_DAY


def _ppm(flux):
    return (plain_numbers(flux) - 1) * 1e6


def _percent(flux):
    return (plain_numbers(flux) - 1) * 100


def _averages(x, y, width):
    """Average y within bins of the given width along x."""
    bins = np.floor((x - x.min()) / width).astype(int)
    count = np.bincount(bins)
    has_data = count > 0
    count = count[has_data]
    return np.bincount(bins, x)[has_data] / count, np.bincount(bins, y)[has_data] / count


def _keep_peaks(x, y, points=4000):
    """Thin a long curve for drawing, keeping the highest point in each stretch so no peak disappears."""
    chunk = max(1, len(y) // points)
    end = len(y) // chunk * chunk
    best = y[:end].reshape(-1, chunk).argmax(axis=1) + np.arange(0, end, chunk)
    return x[best], y[best]
