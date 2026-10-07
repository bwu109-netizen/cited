"""有据 / Cited — web app entry (Streamlit Community Cloud runs this file).

  streamlit run app.py
"""
import streamlit as st

st.set_page_config(page_title="有据 · Cited", layout="wide")

from web.web_app import main  # noqa: E402

main()
