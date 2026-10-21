"""The adjudicate page: an adjudicator sets the final labels of a study's judged images."""

import streamlit as st

from components import adjudication
from state import client, current_study

study = current_study()
api = client()
st.title(study.name)
st.caption("Set the final label where annotators disagree, marked Unsure, or where you want to check them.")
adjudication.final_labels(api, study, api.agreement(study.id))
