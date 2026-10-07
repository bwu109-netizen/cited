"""财报核验 / Earnings Verifier — web app entry (Streamlit Community Cloud runs this file).

  streamlit run app.py
"""
import streamlit as st

st.set_page_config(page_title="财报核验 · Earnings Verifier", layout="wide")

from web.web_app import main  # noqa: E402

main()
