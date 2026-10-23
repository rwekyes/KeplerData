# Temporary test app: confirms the cloud host has the right Python and
# libraries, and can reach the Kepler archive. Replaced by the real app in M2.
import sys
import time

import astropy
import lightkurve as lk
import streamlit as st

st.title("Kepler Data Explorer")
st.write("Deployment test. The real app is coming soon.")

st.subheader("Environment")
st.write(f"Python {sys.version.split()[0]}")
st.write(f"lightkurve {lk.__version__} · astropy {astropy.__version__} · streamlit {st.__version__}")

st.subheader("Archive connection")
if st.button("Search MAST for Kepler-10"):
    with st.spinner("Asking MAST for Kepler-10's light curves..."):
        start = time.time()
        results = lk.search_lightcurve("KIC 11904151", mission="Kepler", exptime="long")
    st.success(f"Found {len(results)} light curves in {time.time() - start:.1f} s")
