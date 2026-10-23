"""Run the planet-finding pipeline on one star and compare against the archive.

Usage:  python -m scripts.check_target "Kepler-10" [--min-period 0.5] [--max-period 20]
"""
import argparse
import time
import warnings

warnings.filterwarnings("ignore")  # lightkurve/astropy are chatty about harmless things

from kepler import fetch, process  # noqa: E402 (must come after silencing warnings)


def step(label, func, *args, **kwargs):
    start = time.time()
    result = func(*args, **kwargs)
    print(f"  {label:<28} {time.time() - start:6.1f} s")
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("name")
    parser.add_argument("--min-period", type=float, default=0.5)
    parser.add_argument("--max-period", type=float, default=20)
    parser.add_argument("--window-days", type=float, default=1.0)
    args = parser.parse_args()

    print(f"{args.name}")
    star = step("find star", fetch.find_star, args.name)
    print(f"    KIC {star.kic}; also known as {', '.join(star.aliases[:4])}")
    planets = step("known planets", fetch.known_planets, star)
    quarters = step("download light curves", fetch.download_light_curves, star)
    light_curve = step("clean", process.clean, quarters)
    flat = step("flatten", process.flatten, light_curve, args.window_days)
    flat = step("remove outliers", process.remove_outliers, flat)
    print(f"    {len(quarters)} quarters, {len(flat):,} measurements")
    _, signal = step("search for planet", process.search_for_planet, flat, args.min_period, args.max_period)

    _, signal = step("search again, masked", process.search_again_with_dips_protected,
                     light_curve, signal, args.window_days)

    match = process.closest_known_planet(planets, signal)
    print()
    if match is None:
        print(f"  Found: period {signal.period:.4f} d, depth {signal.depth * 1e6:.0f} ppm (no known planets to compare)")
        return
    radius = process.planet_radius(signal, match["star_radius_suns"])
    rows = [
        ("period (days)", signal.period, match["period_days"]),
        ("depth (ppm)", signal.depth * 1e6, match["depth_percent"] * 1e4),
        ("duration (hours)", signal.duration * 24, match["duration_hours"]),
        ("radius (Earths)", radius, match["radius_earths"]),
    ]
    print(f"  Closest known planet: {match['name']}")
    print(f"  {'':<18}{'ours':>10}{'archive':>10}{'diff':>9}")
    for label, ours, theirs in rows:
        print(f"  {label:<18}{ours:>10.4g}{theirs:>10.4g}{(ours - theirs) / theirs:>+9.1%}")


if __name__ == "__main__":
    main()
