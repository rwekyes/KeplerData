# Kepler Data Project — Plan

Goal: an interactive web app that shows the Kepler data workflow step by step:
pull real light curves, clean them, find planets, and plot the results. You
present it live in class (10–20 min) for an audience of non-programmers, and
afterward the teacher and students can open it themselves and try any Kepler
star, or any star TESS has measured.

## Design principles

- **Show the process, not just the answer.** The app walks through numbered
  steps. Each step has a one-paragraph plain-English explanation, the plot, and
  a "Show the code" panel with the exact function that produced it. That way the
  code on screen is always the real code.
- **Built for poking at.** Sliders for the settings that matter (flattening
  window, period range, number of planets to search for) let people see what
  happens when they change them. For example, a flattening window that's too
  short erases the transits.
- **Live first, cached fallback.** Downloads come straight from MAST. A small
  set of featured targets also ships pre-processed in the repo, so the app still
  works if MAST or the network is having a bad day.
- **Readable on a projector and on a phone.** Large text, high-contrast plots,
  and nothing that depends on a huge screen. A light theme for the projector and
  a dark one for everyone else, switchable from the app's ⋮ menu.
- **Forgiving of bad input.** Typos and stars neither Kepler nor TESS measured
  get a friendly message and suggestions, not a stack trace.

## Stack

| Library | Role |
|---|---|
| **Streamlit** | The app: pure Python, top-to-bottom scripts that stay readable when shown on screen |
| **Plotly** | Interactive plots (zoom into a transit, hover for values) |
| **lightkurve** | Search/download Kepler and TESS light curves from MAST; stitching, flattening, folding |
| **astropy** | Units, time handling, `BoxLeastSquares` period search |
| **astroquery** | Known planet parameters from the NASA Exoplanet Archive |
| **numpy / pandas** | Array math and tables |

Why Streamlit over Dash, Panel, or Gradio: it has the least boilerplate, the
code reads like a script (good for a non-CIS audience), it has built-in caching
for slow downloads, and it offers free hosting on Streamlit Community Cloud.

**Python version: 3.14 everywhere** (checked 2026-10-22). The whole stack installs
and runs on 3.14 locally; versions are pinned in `requirements.txt`. Community
Cloud's docs say you pick the version in Advanced settings at deploy time (the
documented default is 3.12). Recent forum posts report apps landing on 3.14
regardless of that setting. Our stack already works on 3.14, so we pick 3.14
explicitly and do an early test deploy (M0) to catch platform surprises long
before class.

### Findings from the smoke test

- **Pipeline works:** downloading 3 quarters of Kepler-10, flattening, and
  running a period search recovered Kepler-10 b at 0.8376 d (published:
  0.8375 d). The period search took 0.2 s, and the download plus processing took 5 s.
- **MAST searches are slow:** a name search took 16–67 s. Searching by KIC
  number is about 3× faster (Kepler-90: 48 s by name vs. 16 s by KIC). So:
  resolve names to a KIC ID first, cache every search, precache the featured
  targets, and show a progress message on screen during live searches.
- **Stars go by different names in different catalogs:** the Exoplanet Archive files Kepler-90 under the host name
  **KOI-351**, so a query for `hostname='Kepler-90'` returns nothing.
  `NasaExoplanetArchive.query_aliases()` (~4 s) returns every alias, including
  the KIC ID and the archive host name. Use it for both lookups.
- **Non-transiting planets:** the archive lists Kepler-10 d (151 d), which
  doesn't transit and so won't appear in the light curve. Filter on `tran_flag`
  when folding on known periods.
- **Test deploy (M0):** Community Cloud runs Python 3.14 and searches MAST in 15.7 s.

### Findings from M1

- **Kepler-10 b recovered:** period 0.8375 d (exact match), radius 1.44 R⊕ vs.
  1.47 R⊕ in the archive (−2%). The box depth reads about 20% below the
  archive's, because a box-shaped fit averages over the dip's curved bottom
  while the archive reports the deepest point. Radius is what we compare.
- **Alias lookup:** unknown names make the archive's alias service stall for
  about 120 s, so `find_star` calls it directly with a 10 s timeout. The
  service also returns two-star systems (Kepler-16) under system-level
  aliases, so we gather aliases from every star in the system to find the KIC
  ID. Bare KIC numbers work even for stars the planet archive doesn't know.
- **Period search speed:** a naive grid over 0.5–20 d took about 60 s. Three
  fixes brought it to about 9 s locally:
  1. a period grid that thins out at long periods, where dips last longer
  2. searching hourly averages, then refining on the full data
  3. numpy binning, because lightkurve's `bin()` took 6.6 s on its own
- **We call astropy `BoxLeastSquares` directly** instead of
  `lc.to_periodogram("bls")`. Lightkurve's wrapper runs a size check based on
  its default grid even when you pass your own, so it raises spurious errors
  on wide searches.
- **Display names:** the archive uses the KOI-351 names for most Kepler-90
  planets ("KOI-351 b"). Relabel them to Kepler-90 names in the UI.
- **Still to watch:** about 9 s per search is OK behind a spinner with caching,
  but cloud CPUs may be slower. Time it on Community Cloud in M2, and consider
  narrower default ranges per target.

### Findings from M2

- **Load time (local):** about 20 s for a cold first visit (name lookup, archive,
  download, 9 s search), then about 1 s for each rerun from the cache.
  **On Community Cloud (2026-10-22, after a fresh reboot):** about 5 s to look up
  and load a new star (Kepler-17). Period search time on the cloud is not
  confirmed yet.
- **Plotly draws WebGL (`Scattergl`) traces above regular SVG traces**, whatever
  order you add them in. A plot that mixes thousands of points with a few
  highlight marks must make all of them WebGL, or the highlights end up hidden.
- **Date axes for free:** Kepler's clock (days since noon on 1 Jan 2009) converts
  to milliseconds since 1970, which Plotly date axes accept as plain numbers.
  The audience sees "Jul 2011", not "BKJD 920".
- **The period search curve has about 104k points.** We plot only the highest
  point in each stretch of about 26 points, so no peak gets lost and the page
  stays light on phones.
- **Kepler-10 is missing every fourth quarter.** It fell on one of Kepler's dead
  camera chips. The gaps in the plots are real, not a bug.
- **Name lookup can time out:** one test run reported Kepler-10 as "not found"
  because the archive's alias service took longer than the 10 s timeout.
  Usually it takes about 3.5 s. A timeout and an unknown name look the same
  today. Fix in M3 (a message saying "the archive is slow, try again") and M6
  (store each featured target's KIC so it never needs a lookup).
- **Box depth vs. real dip:** the fold plot shows it directly. The flat box sits
  above the curved bottom of the averages. That's a nice talking point in class.

### Findings from M3

- **How the two name services answer (measured):**

  | Input | Planet archive alias lookup | MAST name resolver |
  |---|---|---|
  | Known names (`kepler10`, `Kepler 10`, `KOI-72`, `KIC 11904151`) | about 3.5–4 s | about 1 s |
  | Typos, gibberish, bare numbers, nicknames (`Boyajian's Star`) | never answers (more than 60 s) | about 11 s to say "not found"; knows `Boyajian's Star` (but not `Tabby's Star`) |
  | TESS-only stars (`TOI-700`, `51 Peg`) | about 3.5 s, with a TIC number but no KIC | — |

  So `find_star` tries the archive (10 s timeout) and then MAST, and finds the
  KIC number in MAST's TESS catalog (its `KIC` column, about 3.6 s). Worst
  case, a typo takes about 21 s to report. This fixes the M2 "Kepler-10 not
  found" flake: a slow archive now falls through to MAST instead of failing.
- **Three friendly errors:** *not found* (with a "Did you mean Kepler-10?"
  button for near-misses of Kepler/KOI/KIC names), *not a Kepler star* (TESS
  stars and K2 stars get their own explanation, as does a catalog star Kepler
  never recorded), and *can't reach NASA* (with a Try again button). Tested
  offline by pointing `HTTPS_PROXY` at a dead port. "Not found" answers are
  cached, so a typo doesn't trigger another 21 s lookup on every slider move.
- **Watch out: lightkurve's `search_lightcurve` returns an empty result, not an
  error, when MAST can't resolve a name.** We always search by `KIC <number>`,
  so this doesn't bite us, but it would make a name search look like "no data".
- **Kepler's FITS headers carry the star's size** (`RADIUS`, from the Kepler
  catalog), so planet sizes work even for stars the planet archive doesn't
  list. The archive's value is preferred when it has one.
- **Matching known planets now needs orbits within 1% of each other.** Before,
  any star's strongest signal would be "matched" to the nearest known planet,
  however far off.
- **Slider effects (Kepler-10):** at a 0.1-day flatten window, Kepler-10 b
  disappears completely (the strongest signal becomes noise at 13.4 d). At
  0.25 d it's found, but the first pass shaves its depth from 142 to 90 ppm
  (the protected second pass restores 152 ppm). Good live demo.
- **Search time vs. orbit range:** 0.5–20 d about 9 s, 0.5–100 d about 14 s,
  0.5–400 d about 24 s (local).
- **Kepler-22 at 0.5–400 d finds 336 d, not the real 290 d.** It's a
  three-transit planet, so the search can fool itself: if a wrong period puts
  most of its predicted dips in data gaps, the one real dip it does catch can
  still fit well. The app correctly says "doesn't match". Fix in M4 with
  Kepler-22's own settings (narrower range, and maybe requiring 2+ dips
  actually seen).
- **Screenshot gotcha:** headless Chrome's full-page capture
  (`captureBeyondViewport`) draws Streamlit's sidebar shifted left. Use a
  normal viewport screenshot when checking the sidebar.

### Findings from M4

- **Kepler-90 at short orbits (0.5–20 d) finds 18.42 d, not b, c, or i.** The
  deep, half-day-long dips of g and h line up at a wrong orbit and outscore the
  small inner planets. Limiting the longest dip searched to what each orbit
  allows (1.5× a Sun-like star's) did *not* fix it, and didn't help anywhere
  else, so it was dropped. This is M5's job: find h, hide its dips, search
  again. For now Kepler-90 starts at 100–400 d, which finds h (11.6× Earth vs.
  NASA's 11.25×).
- **Kepler-22 is fooled by two glitches.** All four of b's real dips are in
  the data (each about 400 ppm, at days 134, 424, 713, and 1003; the fifth
  falls in a gap). Two deeper fake dips (about 1,200 ppm) near day 573
  (mid-quarter) and day 1581 (the very end of the data) line up at 336 d and
  281 d, so even a 200–300 d range finds the wrong orbit. lightkurve's stricter
  quality masks (`hard`, `hardest`) don't remove them. The flattened dip looks
  deeper than the raw sag, so flattening may be making it worse. We kept it as
  a lesson (few dips means one glitch can fool you) rather than chasing it.
- **"Fold on NASA's orbit" (step ⑤)** measures a known planet's dip at its
  published orbit, with the dips protected during flattening. Sizes vs. NASA:
  Kepler-22 b 2.16 vs. 2.10; Kepler-90 b 1.18 vs. 1.31, c 1.53 vs. 1.19,
  i 1.05 vs. 1.32, d 3.08 vs. 2.87, e 2.72 vs. 2.66, f 2.84 vs. 2.88,
  h 11.67 vs. 11.25. **Kepler-90 g is the outlier (5.3 vs. 7.7):** its dips
  are known to arrive hours early or late (planets tugging on each other), so
  stacking blurs them. Any comparison off by more than 25% gets that note.
- **Kepler-16:** the search finds the 41.08 d binary orbit (11.5% deep). Hiding
  those eclipses and searching the same orbit again finds the shallow eclipse
  20.0 d later. The flattening put "shoulders" around it (up to +0.3%), so we
  flatten again with both eclipses protected and re-measure: 1.3% as a box
  average, about 1.5% at the bottom. Treated as a planet, the deep eclipse
  gives 0.22× the Sun's size: clearly a star.
- **Boyajian's Star stops after cleaning, not flattening.** A 1-day flatten
  would erase dips that last 2–10 days. `find_dips` finds four from the data:
  Mar 5, 2011 (14%), Mar 1, 2013 (21%), Mar 21, 2013 (3%), Apr 18, 2013 (8%).
- **Streamlit sliders: `value=` decides one handle or two.** Leaving it out and
  setting the value through session state gives a single-handle slider, which
  crashes the period range on the first drag. Each star now gets its own slider
  keys (`periods <star>`), created with that star's defaults. Streamlit
  discards a slider's state once it's off screen, so switching stars always
  starts from that star's defaults.
- **The archive files Kepler-90 as "KOI-351"** (system name), so `find_star`
  keeps the archive's spelling of the name you typed, and `known_planets`
  relabels "KOI-351 b" as "Kepler-90 b".
- **Blurbs in `kepler/targets.py` are from memory, like the table below.**
  Verify them before quoting them in the report.

### Findings from M5

- **Search, hide, repeat works.** Kepler-90, 8 rounds over 0.5–400 d, finds
  **7 of 8**: h, g, d, c, b, e, f. Round 3 is a leftover (339.4 d, likely the
  edges of h's or g's dips). The only planet missed is **Kepler-90 i**
  (65 ppm), the one the 2017 neural network found, so the talk's point falls
  out of the data. Kepler-18 (0.5–20 d) finds d, c, and b, all exact.
- **Echoes are now recognized.** Kepler-18 at 0.3–5 d finds 3.8208 d, exactly
  half of c's 7.6416 d orbit; searching again finds 4.953 d, a third of d's
  14.859 d. The dip looks shallower because each stacked dip is diluted by an
  empty orbit. `echoed_known_planet` checks for 2×, 3×, ½, and ⅓ (within 1%).
- **Search changes (all in `search_for_planet`):**
  - Orbits of 20 d or more are searched on 3-hour averages with dips up to
    15 h. Kepler-90 h's dip lasts 14.4 h, and the old 10 h maximum left
    leftovers behind.
  - The protected stretch around each dip widened from 2× to 3× the dip length.
  - The 8-round Kepler-90 search took 157 s with only these dip changes and
    124 s with the 3-hour averages too.
  - Side effects: Kepler-10 b now measures 1.53× Earth (+4%, was −2%) with a
    1.5 h box; Kepler-16's deep eclipse reads 10.3% (was 11.5%). Kepler-22 is
    still fooled (336 d).
- **Time:** Kepler-90's whole page plus the 8 rounds took about 4 minutes on
  a fresh server locally. Each round is cached separately, so a second visit
  is instant. **Run Kepler-90's search once before class** (and check how
  long it takes on Community Cloud). Rounds start only with the button, so
  browsing other stars stays quick.
- **Download race (fixed):** two processes downloading the same star at once
  left a half-written file, and the app reported it as "Couldn't reach NASA".
  The broken file would have stayed in `data/raw/` and broken that star for
  good. Now a failed read deletes that star's files and downloads once more.
- **Step ⑧ for any star with 2+ known planets:** a fold for each NASA orbit,
  measured in our data, plus a to-scale picture next to the Solar System.
  The Kepler-90 g fold shows the V-shaped blur from its dips arriving early
  and late.
- **Local server gotcha:** `pkill` sends a polite stop, and Streamlit can take
  several seconds to exit. A new server started too soon fails with "Port
  8599 is not available", or worse, the old one keeps serving stale `kepler`
  modules (the same `AttributeError` as on the cloud). Use `pkill -9`, or
  wait before restarting.

### Findings from the TESS and dark-mode update

- **Which telescope:** `find_star` uses Kepler's data for any star with a KIC
  number (four unbroken years beat TESS's month-long sectors), and TESS's for
  everything else. A name starting with TIC or TOI always gets TESS's data, so
  `TIC 377780790` shows TESS's view of Kepler-10. K2-only stars now get TESS
  data when it exists.
- **Which TESS data:** SPOC's 2-minute light curves when the star was picked for a
  close watch, otherwise TESS-SPOC's light curves from full-frame images (every
  30, 10, or 3.3 minutes depending on the year). One MAST search returns both; we
  filter the table instead of searching twice (each search takes 5–20 s).
- **We average TESS's data before anything else:** 2-minute data into 10-minute
  stretches, and full-frame data into 30-minute stretches, so all its sectors
  match. TOI-700's 37 sectors are 590k measurements (68 MB just for the light
  curve) at 2 minutes and 119k after averaging; Kepler-10 has about 65k.
  lightkurve's `bin()` takes about 1.3 s for 11 sectors. That's slow but fine,
  since it's cached.
- **Each telescope has its own clock.** Kepler's BKJD starts at BJD 2454833
  (noon, 1 Jan 2009) and TESS's BTJD at BJD 2457000 (noon, 8 Dec 2014). The
  archive's transit times and the plot dates both convert using
  `lc.time.format` (`"bkjd"` or `"btjd"`). The flatten window now uses the
  measured time between points instead of Kepler's fixed 29.4 minutes.
- **π Mensae:** finds π Men c at 6.268 d, 2.04× Earth (NASA: 2.02×). Its other two
  planets don't transit (`tran_flag` = 0), the same lesson as Kepler-10 d. The
  archive files it under `HD 39091`, and `_rename_planet` relabels it.
  Download: 24 sectors in 69 s the first time; search: 9 s.
- **TOI-700 (5–50 d, 4 rounds):** finds c (16.05 d), then b (9.977 d), then
  **d (37.42 d, 0.99× Earth vs. NASA's 1.15×)**, the habitable-zone planet. Round
  4 is noise (41 d); it misses **e**, announced in 2023, the same "simple search
  stops here" story as Kepler-90 i. Folding on NASA's orbits measures all four
  within 10% (b 1.02 vs. 0.96, c 2.34 vs. 2.54, e 0.96 vs. 0.92, d 1.19 vs.
  1.15). Download: 37 sectors in 80 s the first time; each round: 11 s.
- **Memory:** loading TOI-700 peaks at about 600 MB while reading its 37 raw
  sectors (Kepler-90: 390 MB); after averaging, what's cached is small. The
  local server grew to 2.2 GB after hours of testing many stars. Watch this in
  the Phase 4 load test.
- **Short dips:** the search's shortest box is 1 hour. That's fine for both
  featured TESS stars, but small red dwarfs can have shorter dips (LHS 3844 b's
  lasts 31 min), and a 1-hour box would underestimate how deep they are.
- **Dark mode: plots must use `theme="streamlit"`.** Streamlit fills in the
  theme's text and background colors for `theme=None` plots too, but only when
  they're first drawn: after a live switch they stay white, even after a rerun.
  `theme="streamlit"` plots recolor instantly. That theme shrinks axis text, so
  `_style` sets tick and title sizes itself. Everything not tied to the data is
  a see-through gray (`rgba(128,128,128,…)`) that works on both backgrounds.
- **`st.context.theme` can't drive the plots:** it still said `light` after a
  switch to dark (as its docs warn).
- **Which theme opens first:** with `[theme.light]` and `[theme.dark]` in
  `config.toml`, the app follows the computer's light/dark setting, even with
  `base = "light"`. A choice in ⋮ → Light/Dark is saved in that browser
  (`stActiveTheme` in localStorage). **On the class laptop, pick Light once.**
- **Blurbs for π Mensae and TOI-700 are from memory too.** Verify before quoting.

## Where it runs

- **In class:** run locally on your laptop (`streamlit run app.py`) and open it
  in the browser. It doesn't depend on a cloud host being awake, and you control
  the environment you tested.
- **After class:** deployed to Streamlit Community Cloud from the GitHub repo.
  Share one link; nobody has to install anything.
- Community Cloud apps go to sleep when idle and take some time to wake up.
  Open the link before class so it's awake when you hand it out.

## The app

```
┌─ Sidebar ───────────────┐  ┌─ Main ──────────────────────────────────────┐
│ Featured targets        │  │ Kepler-90 — 8 planets, tied with our Solar  │
│  ○ Kepler-10            │  │ System for the most around one star         │
│  ○ Kepler-16            │  │                                             │
│  ○ Kepler-22            │  │ ① Download  ② Clean  ③ Flatten  ④ Search    │
│  ● Kepler-90            │  │ ⑤ Fold  ⑥ Results                           │
│  ○ Boyajian's Star      │  │                                             │
│                         │  │ [explanation]                               │
│ …or search any star:    │  │ [interactive plot]                          │
│ [ Kepler-11        ] 🔍 │  │ ▸ Show the code                             │
│                         │  │                                             │
│ Settings                │  │                       [ Next step → ]       │
│  Flatten window ──●──   │  │                                             │
│  Period range   ●────●  │  │                                             │
│  Planets to find  [3]   │  │                                             │
│                         │  │                                             │
│ ☐ Presentation mode     │  │                                             │
└─────────────────────────┘  └─────────────────────────────────────────────┘
```

- **Presentation mode** reveals one step at a time with a big "Next step"
  button, so you control the pacing. With it off, all the steps are on one page
  for people exploring on their own.
- **Featured targets** each come with a short blurb about why they matter.
  **Search** accepts Kepler-XX names, KIC, KOI, TOI, and TIC numbers, and star
  names MAST knows (π Men, Boyajian's Star).
- **Kepler-90** gets an extra multi-planet section (see below).

### Featured targets

| Target | Why it matters | What it shows off |
|---|---|---|
| **Kepler-10** | Kepler's first confirmed rocky planet (2011) | The basic process from start to finish, with one clear transit |
| **Kepler-16** | First planet confirmed orbiting two stars ("Tatooine") | Deep eclipses of the two stars passing in front of each other |
| **Kepler-22** | Kepler's first planet in a star's habitable zone (2011) | A long orbit (~290 d), so only a few transits in four years |
| **Kepler-90** | 8 planets; the 8th was found in 2017 by a neural network trained at Google | Finding several planets, and the limits of a simple search |
| **Boyajian's Star** (KIC 8462852) | Irregular, deep dips that no planet explains | Not every dip is a planet |
| **π Mensae** (TESS) | TESS's first planet (2018); π Men c is about 2× Earth | The basic process on TESS data; two planets that don't transit |
| **TOI-700** (TESS) | TESS's first Earth-size planet in a habitable zone (d, 2020); e followed in 2023 | Search, hide, repeat finds 3 of 4, missing the one found later |

These facts are from memory. Verify them against your sources for the report.

### Kepler-90 multi-planet section

1. **Search, mask, repeat:** find the strongest signal, hide those transits,
   and search again, up to the number in the "Planets to find" slider. A table
   shows which recovered signals match known planets.
2. **Fold on the published periods** to reveal all 8, including tiny
   Kepler-90 i. The takeaway: "here's where the simple search stops working,
   and why the machine-learning result mattered."
3. **Scale graphic:** the sizes and orbits of all 8 planets next to our Solar System.

### Per-target behavior

Not every star suits the full pipeline. Each featured target lists the steps it
runs. Kepler-16 shows its eclipses instead of a planet search, and Boyajian's
Star stops after cleaning (flattening would erase its days-long dips) and gets
a lettered "what are these dips?" plot.
Stars that come in through search get the standard pipeline.

## Code layout

```
KeplerData/
├── PLAN.md
├── requirements.txt         # pinned, for Community Cloud
├── app.py                   # Streamlit entry point: layout, sidebar, step flow
├── kepler/                  # at the root (not src/) so Streamlit imports it without path hacks
│   ├── targets.py           # featured targets: names, blurbs, steps to run
│   ├── fetch.py             # find the star, pick Kepler or TESS, MAST download, archive query
│   ├── process.py           # clean, stitch, flatten, period search, fold, multi-planet loop
│   └── plots.py             # Plotly figures with shared projector-friendly styling
├── scripts/
│   ├── check_target.py      # run the pipeline on one star, time each step, compare to archive
│   └── precache.py          # build the bundled fallback data for featured targets
├── data/
│   ├── raw/                 # lightkurve download cache (gitignored)
│   └── featured/            # compact stitched light curves + archive params (committed)
└── .streamlit/config.toml   # light and dark themes, font size
```

The "Show the code" panels use `inspect.getsource()` on the functions in
`process.py`, so those functions should be short and commented in plain English.

## Phase 0 — Setup

- [x] Install the stack into `.venv` on Python 3.14 and pin it in `requirements.txt`
- [x] `.gitignore`: `.venv/`, `data/raw/`, `__pycache__/`, `.idea/`
- [x] `streamlit hello` runs in the browser
- [x] Test deploy of a one-line app to Community Cloud on Python 3.14

## Phase 1 — Data layer (`fetch.py`)

1. **Resolve the name first** with `query_aliases()` to get the KIC ID and the
   archive host name (see the smoke-test findings).
2. `search_lightcurve("KIC <id>", mission="Kepler", exptime="long")`. Long
   cadence only, because short cadence is far larger and slower, especially on a
   shared cloud host.
3. `download_all()` → stitch → wrap in `st.cache_data` so repeat visits are instant.
4. Get known planet parameters from the Exoplanet Archive `pscomppars` table.
5. **Fallback order:** in-memory cache → `data/featured/` → live MAST. Show a
   small badge saying which source was used.
6. `precache.py` writes each featured target's stitched light curve and archive
   parameters to `data/featured/`. Check the size: it should be a few MB per
   target, small enough to commit.

## Phase 2 — Processing (`process.py`)

1. **Clean:** drop NaNs, apply quality flags, normalize.
2. **Flatten:** remove slow trends, masking known transits; the window size is
   adjustable in the sidebar.
3. **Clip outliers** on the upper side only.
4. **Period search** with Box Least Squares; the period range is adjustable.
   Cache the results, and keep the search fast enough to run interactively
   (tune the grid density, and maybe bin the data first).
5. **Fold and bin** on the detected or known period.
6. **Results:** derive planet radius from depth (`Rp ≈ R★ · sqrt(depth)`) and
   compare it to the archive in plain language ("we measured 1.5× Earth's size;
   NASA says 1.47×").
7. **Multi-planet loop:** mask the detected transits and search again.

## Phase 3 — Plots (`plots.py`)

- Raw light curve (colored by quarter), flattened light curve, period search
  result with the peak marked, folded transit (points, bins, box model), and a
  results card
- Kepler-90: multi-planet fold grid and scale/orbit graphic
- Kepler-16: eclipse zoom; Boyajian's Star: annotated dips
- Plotly `scattergl` for the full four-year light curves (~65k points) so zooming stays smooth
- One shared theme with large fonts and a colorblind-safe palette, tested on the real projector

## Phase 4 — Deploy

- [ ] Push to GitHub; deploy on Community Cloud; confirm live downloads work from the cloud host
- **After every push that changes `kepler/`, reboot the app** (Manage app → ⋮ →
  Reboot app). Community Cloud picks up the new `app.py` but keeps the old
  `kepler` modules loaded, so new functions show up as `AttributeError`. This
  happened after the M3 push.
- [ ] Load test: a few people searching different stars at once without hitting memory limits
- [ ] Share the link with the class

## Milestones

- [x] **M0** Environment installs; `streamlit hello` works locally; hello-world app deploys to Community Cloud
- [x] **M1** Kepler-10 end to end in plain functions: download, clean, find the planet, fold
- [x] **M2** Streamlit app with the step flow, explanations, "Show the code," and Plotly plots, for Kepler-10
- [x] **M3** Search box with friendly errors; sidebar settings wired up
- [x] **M4** All featured targets, including per-target behavior for Kepler-16 and Boyajian's Star
- [x] **M5** Kepler-90 multi-planet section
- [ ] **M6** Bundled fallback data plus a test run with Wi-Fi off for the featured targets
- [ ] **M7** Presentation mode; dress rehearsal on the projector, timed to fit 10–20 min
- [ ] **M8** Deployed to Community Cloud and tested by someone other than you

## Open questions

- **Talk structure:** with 10–20 min, a suggested run is Kepler-10 for the full
  walkthrough (~5 min), Kepler-90 as the main event (~5–8 min), then one quick
  live search suggested by the audience. Kepler-16, Kepler-22, and Boyajian's
  Star stay in the app for people to explore afterward. Adjust to taste.

## Docs to review before we start

**Core (read these first)**
- Lightkurve tutorials: https://lightkurve.github.io/lightkurve/tutorials/index.html
  (the search & download, flatten, and BLS planet-search tutorials map almost 1:1 onto Phases 1–2)
- Streamlit docs, especially "Get started" and the basic concepts: https://docs.streamlit.io/
- Streamlit caching: https://docs.streamlit.io/develop/concepts/architecture/caching
- Astropy Box Least Squares: https://docs.astropy.org/en/stable/timeseries/bls.html

**App and plotting**
- Streamlit + Plotly: https://docs.streamlit.io/develop/api-reference/charts/st.plotly_chart
- Plotly Python: https://plotly.com/python/
- Streamlit Community Cloud (deploying, Python versions, resource limits): https://docs.streamlit.io/deploy/streamlit-community-cloud
- Streamlit theming (`[theme.light]` / `[theme.dark]`): https://docs.streamlit.io/develop/concepts/configuration/theming

**Data sources**
- Lightkurve API reference: https://lightkurve.github.io/lightkurve/
- MAST Kepler mission page (data products, quality flags, archive manuals): https://archive.stsci.edu/missions-and-data/kepler
- MAST TESS mission page (sectors, SPOC and TESS-SPOC products): https://archive.stsci.edu/missions-and-data/tess
- NASA Exoplanet Archive: https://exoplanetarchive.ipac.caltech.edu/
- `pscomppars` column definitions: https://exoplanetarchive.ipac.caltech.edu/docs/API_PS_columns.html
- astroquery NASA Exoplanet Archive module: https://astroquery.readthedocs.io/en/latest/ipac/nexsci/nasa_exoplanet_archive.html

**Background for the talk**
- Shallue & Vanderburg (2018), the neural-network discovery of Kepler-90 i: https://arxiv.org/abs/1712.05044

**Reference (as needed)**
- Astropy units: https://docs.astropy.org/en/stable/units/
- NumPy: https://numpy.org/doc/stable/
- pandas: https://pandas.pydata.org/docs/
