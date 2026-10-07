"""财报核对助手 / Earnings Checker — web app entry (Streamlit Community Cloud runs this file).

  streamlit run app.py
"""
import streamlit as st

st.set_page_config(page_title="财报核对助手 · Earnings Checker", layout="wide")

from web.web_app import main  # noqa: E402

main()
