# Degree Plan
# ---
# jupyter:
#   jupytext:
#     text_representation:
#       extension: .py
#       format_name: percent
#       format_version: '1.3'
#       jupytext_version: 1.18.1
#   kernelspec:
#     display_name: Python 3 (ipykernel) (Local)
#     language: python
#     name: conda-base-py
# ---

# %%
import os
import requests
import streamlit as st
import pandas as pd
from fpdf import FPDF
import re
import json
import uuid
import ast
from google.cloud import bigquery
from google.cloud.dialogflowcx_v3.services.sessions import SessionsClient
from google.cloud.dialogflowcx_v3.types import session as cx_session


# ---------- Page config & global styles ----------



st.set_page_config(
    page_title="OBCC Degree Planner",
    layout="wide",
)

st.markdown(
    """
    <style>

    

    .stApp {
        background-color: #ffffff;
        color: #111111;
        font-family: "Segoe UI", system-ui, -apple-system, BlinkMacSystemFont, sans-serif;
    }
    /* Top green bar */
    .utd-header {
        background-color: #00563F;  /* UTD green */
        color: #ffffff;
        padding: 0.45rem 1.5rem;
        font-size: 0.9rem;
        letter-spacing: 0.06em;
        text-transform: uppercase;
        font-weight: 600;
    }
    /* Orange program bar */
    .utd-subheader {
        background-color: #F36F21;  /* UTD orange */
        color: #ffffff;
        padding: 0.6rem 1.5rem;
        font-size: 1.1rem;
        font-weight: 600;
    }
    .page-intro {
        /* margin-top: 1.3rem;
        margin-bottom: 0.4rem; */
    }

    .main-page-title{
    margin-bottom: 0.2rem;
    color: #111111;
}

.section-subheader {
    color: #111111 !important;
    margin-top: 0;
    margin-bottom: 0;
}

.custom-info-box {
    background-color: #f5f5f5;
    color: #111111;
    border-left: 4px solid #F36F21;
    padding: 0.75rem 1rem;
    border-radius: 0.25rem;
    margin-bottom: 1rem;
}

div[data-testid="stTextInput"] label {
    color: #111111 !important;
}

.custom-caption {
    color: #111111;
    font-size: 14px;
    margin-top: 0.25rem;
    margin-bottom: -1rem;
}

/* Sidebar slider min/max labels only */
section[data-testid="stSidebar"] div[data-testid="stSlider"] div[data-testid="stTickBar"] > div {
    color: #FAFAFA !important;
}

.st-emotion-cache-ch5dnh {
    color: initial !important;
}

.section-divider {
    border-top: 1px solid #d9d9d9;
    margin: 1.5rem 0;
}

/* Chintan - CSS Changes end */

    .info-banner {
        background-color: #f7f7f7;
        border-left: 4px solid #F36F21;
        padding: 0.75rem 1rem;
        margin-bottom: 1.2rem;
        font-size: 0.95rem;
    }
    /* Make primary buttons orange */
    .stButton>button {
        background-color: #F36F21;
        color: #ffffff;
        border-radius: 4px;
        border: none;
        padding: 0.4rem 1.1rem;
        font-weight: 600;
    }
    .stButton>button:hover {
        background-color: #d85f1b;
    }
    /* Make download PDF button green */
    .stDownloadButton>button {
        background-color: #00563F;  /* UTD green */
        color: #ffffff;
        border-radius: 4px;
        border: none;
        padding: 0.4rem 1.1rem;
        font-weight: 600;
    }
    .stDownloadButton>button:hover {
        background-color: #004130;
    }

    /* Custom metric look */
    .summary-metric-label {
        color: #111111;          /* dark label so it is visible */
        font-size: 0.95rem;
        font-weight: 600;
        margin-bottom: 0.15rem;
    }
    .summary-metric-value {
        color: #F36F21;          /* orange value */
        font-size: 2.2rem;
        font-weight: 700;
    }
    </style>
    """,
    unsafe_allow_html=True,
)

# UTD / OBCC top bars
st.markdown(
    """
    <div class="utd-header">University of Texas at Dallas</div>
    <div class="utd-subheader">
        Organizational Behavior, Coaching and Consulting &nbsp;&middot;&nbsp; Degree Planner
    </div>
    """,
    unsafe_allow_html=True,
)

# Intro + instructions
st.markdown(
    """
    <div class="page-intro">
      <h2 class="main-page-title">OBCC Degree Planner</h2>
    </div>
    <div class="info-banner">
      <strong>How it works:</strong>
      Use the options on the left to choose your program, start term, pace, and certificates.
      When you click <em>Generate plan</em>, we'll build a recommended term-by-term schedule
      that follows OBCC course offerings and prerequisites. The plan is now generated
      via the OBCC Vertex AI Conversational Agent, which calls the planner tool behind the scenes.
    </div>
    """,
    unsafe_allow_html=True,
)

# ------------------ constants ------------------ #

# Planner API URL - configurable via environment variable
PLANNER_API_URL = os.environ.get(
    "PLANNER_API_URL",
    "http://localhost:8000/plan"
)

PROGRAM_CODES = {
    "MS LOD": "MSLOD",
    "EMBA HOL": "HOL-EMBA",
}

START_TERMS = [
    "SP26", "SU26", "FA26",
    "SP27", "SU27", "FA27",
    "SP28", "SU28", "FA28",
    "SP29", "SU29", "FA29",
]

CERT_LABEL_TO_CODE = {
    "Organizational Consulting": "OC",
    "Transformational Leadership": "TL",
    "Strategic Human Resources": "SHR",
    "Coaching": "COACH",
}

# NOTE: use <= (ASCII) so fpdf doesn't complain later
PACE_LABEL_TO_HALF_TIME = {
    "Full-time": False,
    "Half-time (<= 8 credits / long term)": True,
}

# ---------- Vertex AI Conversational Agent (Dialogflow CX) config ----------

DF_PROJECT_ID = "obcc-degree-planner-489404"
DF_LOCATION_ID = "us"
DF_AGENT_ID = "1d7f500e-0fbf-4fec-afe0-5f24836dd677"  # your agent ID
DF_AGENT_PATH = (
    f"projects/{DF_PROJECT_ID}/locations/{DF_LOCATION_ID}/agents/{DF_AGENT_ID}"
)


def _extract_json_from_text(text: str) -> dict:
    text = text.strip()

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    m = re.search(r"\{.*\}", text, re.DOTALL)
    if m:
        candidate = m.group(0).strip()
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            try:
                obj = ast.literal_eval(candidate)
                if isinstance(obj, dict):
                    return obj
            except Exception:
                pass

    try:
        obj = ast.literal_eval(text)
        if isinstance(obj, dict):
            return obj
    except Exception:
        pass

    rows: list[dict] = []

    for match in re.finditer(r'\{[^{}]*"course_number"[^{}]*\}', text):
        obj_str = match.group(0)
        parsed = None

        try:
            parsed = json.loads(obj_str)
        except json.JSONDecodeError:
            try:
                parsed = ast.literal_eval(obj_str)
            except Exception:
                parsed = None

        if isinstance(parsed, dict):
            rows.append(parsed)

    if rows:
        return {"rows": rows}

    snippet = text[:600] + ("..." if len(text) > 600 else "")
    raise ValueError(
        "Could not parse JSON from agent response. "
        "Here is the beginning of the response:\n"
        + snippet
    )


def call_planner_via_agent(payload: dict) -> list[dict]:
    if "df_session_id" not in st.session_state:
        st.session_state["df_session_id"] = str(uuid.uuid4())
    session_id = st.session_state["df_session_id"]

    session_path = f"{DF_AGENT_PATH}/sessions/{session_id}"
    api_endpoint = f"{DF_LOCATION_ID}-dialogflow.googleapis.com:443"
    client_options = {"api_endpoint": api_endpoint}
    client = SessionsClient(client_options=client_options)

    prompt = (
        "You are the OBCC Degree Planning agent. "
        "Use your configured Run Planner tool to generate a degree plan using "
        "the following JSON input:\n"
        f"{json.dumps(payload)}\n\n"
        "Return ONLY the raw tool output as JSON with a top-level key 'rows'. "
        "Use valid JSON with double quotes and NO trailing commas. "
        "Do not add any extra text, markdown, or explanation."
    )

    agent_rows: list[dict] = []

    try:
        text_input = cx_session.TextInput(text=prompt)
        query_input = cx_session.QueryInput(text=text_input, language_code="en")

        request = cx_session.DetectIntentRequest(
            session=session_path,
            query_input=query_input,
        )

        response = client.detect_intent(request=request)

        parts = []
        for msg in response.query_result.response_messages:
            if msg.text and msg.text.text:
                parts.extend(msg.text.text)
        agent_text = " ".join(parts).strip()

        if agent_text.startswith("```"):
            agent_text = re.sub(r"^```[a-zA-Z]*\n", "", agent_text)
            if agent_text.endswith("```"):
                agent_text = agent_text[:-3].strip()

        if agent_text:
            try:
                data = _extract_json_from_text(agent_text)
                if "rows" in data and isinstance(data["rows"], list):
                    agent_rows = data["rows"]
            except Exception:
                agent_rows = []

    except Exception:
        agent_rows = []

    try:
        resp = requests.post(PLANNER_API_URL, json=payload, timeout=60)
        resp.raise_for_status()
        data = resp.json()
        # Multiple plans response — return the whole dict so the caller can handle it
        if "plans" in data:
            return data
        # Single plan response — return the rows list
        planner_rows = data.get("rows", []) or []
        if planner_rows:
            return planner_rows
    except Exception as planner_err:
        if agent_rows:
            return agent_rows
        raise RuntimeError(
            f"Planner API failed after calling the agent: {planner_err}"
        )

    if agent_rows:
        return agent_rows

    raise ValueError("Both the OBCC agent and planner API returned no rows.")


# ------------------ BigQuery config for chatbot ------------------ #

PROJECT_ID = "obcc-degree-planner-489404"
DATASET = "degree_planner_config_data"
bq_client = bigquery.Client(project=PROJECT_ID)


@st.cache_data(show_spinner=False)
def load_catalog():
    courses_query = f"""
        SELECT
          CourseID,
          CourseNumber,
          CourseTitle,
          DefaultCreditHours,
          ProgramCode
        FROM `{PROJECT_ID}.{DATASET}.v_course_program`
    """
    offerings_query = f"""
        SELECT
          CourseID,
          TermCode,
          PartOfTermCode
        FROM `{PROJECT_ID}.{DATASET}.v_course_offering`
    """

    df_courses = bq_client.query(courses_query).to_dataframe()
    df_offerings = bq_client.query(offerings_query).to_dataframe()
    return df_courses, df_offerings


def _normalize_course_number(raw: str) -> str:
    raw = raw.strip().upper()
    m = re.match(r"^([A-Z]{2,4})\s*([0-9]{4})$", raw)
    if not m:
        return raw
    return f"{m.group(1)} {m.group(2)}"


def answer_course_question(
    question: str,
    df_courses: pd.DataFrame,
    df_offerings: pd.DataFrame,
) -> str:
    match = re.search(r"\b[A-Za-z]{2,4}\s*\d{4}\b", question)
    if not match:
        return (
            "Right now I can answer questions like:\n\n"
            "- *What is OB 6374?*\n"
            "- *How many credits is OB 6374?*\n"
            "- *When is OB 6374 offered?*\n\n"
            "Please include a course number such as `OB 6374` in your question."
        )

    raw_code = match.group(0)
    code = _normalize_course_number(raw_code)

    row = df_courses[df_courses["CourseNumber"].str.upper() == code].head(1)
    if row.empty:
        return f"I couldn't find a course with number **{code}** in the catalog."

    row = row.iloc[0]
    title = str(row["CourseTitle"])
    credits = int(row["DefaultCreditHours"])
    course_id = int(row["CourseID"])

    offs = df_offerings[df_offerings["CourseID"] == course_id]
    if offs.empty:
        base = f"**{code}** – *{title}* is a {credits}-credit course."
        return base + " I don't see any offerings configured yet in the planner data."

    def _fmt_term(term_code) -> str:
        term_code = str(term_code or "").strip()
        if len(term_code) < 4:
            return term_code or "Unknown term"

        season_code = term_code[:2]
        year_code = term_code[2:]

        if not year_code.isdigit():
            return term_code

        season_map = {"SP": "Spring", "SU": "Summer", "FA": "Fall"}
        season = season_map.get(season_code, season_code)
        year = 2000 + int(year_code)
        return f"{season} {year}"

    part_labels = {
        "1st8wk": "1st 8 weeks",
        "2nd8wk": "2nd 8 weeks",
        "Full16wk": "Full term",
    }

    pieces = []
    for term_code in sorted(offs["TermCode"].unique()):
        sub = offs[offs["TermCode"] == term_code]
        sessions = sorted(set(str(p) for p in sub["PartOfTermCode"]))
        nice_sessions = ", ".join(part_labels.get(s, s) for s in sessions)
        pieces.append(f"- {_fmt_term(term_code)} ({nice_sessions})")

    offerings_text = "\n".join(pieces)

    return (
        f"**{code}** – *{title}* is a **{credits}-credit** course.\n\n"
        f"It is currently offered in:\n{offerings_text}"
    )


# ------------------ sidebar ------------------ #
# The sidebar contains all the inputs the user needs to configure their plan.
# Each input maps to a parameter sent to the /plan API endpoint.

st.sidebar.header("Plan settings")

# Program selection — determines which degree (MS LOD or EMBA HOL)
# and affects available certificates, default term count, and target credits
program_label = st.sidebar.selectbox("Program", list(PROGRAM_CODES.keys()))
# Start term — defaults to the next full term based on current month.
# Jan-May -> Fall of current year, Jun-Dec -> Spring of next year.
# Summer is intentionally excluded as a default since it is not a full term.
from datetime import datetime
_now = datetime.now()
_year = _now.year % 100  # e.g. 2026 -> 26
if _now.month <= 5:
    _default_start = f"FA{_year:02d}"
else:
    _default_start = f"SP{_year + 1:02d}"
_default_start_idx = START_TERMS.index(_default_start) if _default_start in START_TERMS else 0

start_term_code = st.sidebar.selectbox("Start term", START_TERMS, index=_default_start_idx)

# Certificate selection — filtered by program.
# EMBA HOL only supports Transformational Leadership (pre-selected).
# MS LOD supports all 4 certificates.
if PROGRAM_CODES[program_label] == "HOL-EMBA":
    available_certs = ["Transformational Leadership"]
    default_certs = ["Transformational Leadership"]
else:
    available_certs = list(CERT_LABEL_TO_CODE.keys())
    default_certs = []

selected_cert_labels = st.sidebar.multiselect(
    "Certificates",
    available_certs,
    default=default_certs,
    help="Choose one or more OBCC certificates.",
)

# Show info message when SHR is selected
if "Strategic Human Resources" in selected_cert_labels:
    st.sidebar.info(
        "ℹ️ Plans with the SHR certificate typically require 7 terms due to "
        "Fall-only course scheduling constraints."
    )

# Pace — full-time allows up to the dynamic max courses per term.
# Half-time caps at 1 course per term regardless of season.
# Financial Aid Eligible enforces minimum credits per term.
pace_label = st.sidebar.selectbox(
    "Pace",
    ["Full-time", "Half-time (<= 8 credits / long term)", "Financial Aid Eligible"],
    index=0,
    help="Financial Aid Eligible pacing ensures every term meets minimum credit requirements: Fall/Spring ≥ 5 SCH, Summer ≥ 3 SCH",
)

# Term slider — controls how many terms the plan is spread across.
# Default is 6 for MS LOD, 7 for EMBA HOL and SHR (which need more terms).
# Higher values produce lighter-load plans spread across more semesters.
selected_cert_codes = [CERT_LABEL_TO_CODE[l] for l in selected_cert_labels]
_default_terms = 7 if PROGRAM_CODES[program_label] == "HOL-EMBA" or "SHR" in selected_cert_codes else 6

max_terms = st.sidebar.slider(
    "Maximum number of terms",
    min_value=6,
    max_value=25,
    value=_default_terms,
)

# Plan versions — generates multiple slightly different plans.
# Variations differ in which electives fill the remaining slots
# and which terms optional courses land in.
num_plans = st.sidebar.slider(
    "Number of plan versions",
    min_value=1,
    max_value=3,
    value=1,
    help="Generate multiple variations of the degree plan.",
)

# Summer toggle — when off, Summer terms are completely skipped.
# Courses that are Summer-only will still be included but moved to
# the nearest available Fall or Spring term.
include_summer = st.sidebar.toggle(
    "Include Summer terms",
    value=True,
    help="When off, Summer terms are skipped and courses spread across Spring and Fall only.",
)

# Breaks section — allows students to mark semesters they won't be enrolled
st.sidebar.markdown("---")
enable_breaks = st.sidebar.toggle(
    "Add semester breaks",
    value=False,
    help="Enable if the student needs to skip one or more semesters.",
)

break_terms = []
if enable_breaks:
    # Only show SP and FA terms as break options (Summer is already optional)
    break_term_options = [t for t in START_TERMS if not t.startswith("SU")]
    break1 = st.sidebar.selectbox(
        "Break semester 1",
        ["None"] + break_term_options,
        index=0,
    )
    if break1 != "None":
        break_terms.append(break1)

    break2 = st.sidebar.selectbox(
        "Break semester 2",
        ["None"] + [t for t in break_term_options if t != break1],
        index=0,
    )
    if break2 != "None":
        break_terms.append(break2)

# Set flags to control generation vs navigation
generate = st.sidebar.button("Generate plan", type="primary")
if generate:
    st.session_state["generate_clicked"] = True
    st.session_state["plans_loaded"] = False

# ------------------ main layout ------------------ #
# This section handles plan generation and display.
# Plans are stored in st.session_state so navigation between
# versions works without regenerating the plan.

st.markdown(
    '<h3 class="section-subheader">Generated degree plan</h3>',
    unsafe_allow_html=True,
)

df = None
cert_codes: list[str] = []

if not generate and "all_plans" not in st.session_state:
    st.markdown(
    """
    <div class="custom-info-box">
        Configure your plan options in the sidebar and click <strong>Generate plan</strong>.
    </div>
    """,
    unsafe_allow_html=True,
)
# Only run generation if Generate button was clicked and plans haven't been loaded yet
elif st.session_state.get("generate_clicked", False) and not st.session_state.get("plans_loaded", False):
    # Map UI labels -> API codes
    program_code = PROGRAM_CODES[program_label]
    cert_codes = [CERT_LABEL_TO_CODE[label] for label in selected_cert_labels]

    # Determine pacing parameters
    if pace_label == "Financial Aid Eligible":
        half_time = False
        financial_aid_pacing = True
    else:
        half_time = PACE_LABEL_TO_HALF_TIME.get(pace_label, False)
        financial_aid_pacing = False

    # Build the payload
    payload = {
        "program_code": program_code,
        "start_term_code": start_term_code,
        "half_time": half_time,
        "financial_aid_pacing": financial_aid_pacing,
        "certs": cert_codes,
        "max_terms": max_terms,
        "num_plans": num_plans,
        "include_summer": include_summer,  # whether to schedule courses in Summer terms
        "break_terms": break_terms,            # semesters the student will skip
    }

    try:
        with st.spinner("Generating degree plan..."):
            rows = call_planner_via_agent(payload)

        if not rows:
            st.warning(
                "The OBCC planning agent returned no rows. "
                "Check your agent tool configuration or planner logic."
            )
        else:
            # Handle multiple plans response
            if isinstance(rows, dict) and "plans" in rows:
                all_plans = rows["plans"]
            else:
                # Single plan or already-extracted rows
                all_plans = [{"variation": 1, "rows": rows if isinstance(rows, list) else rows.get("rows", [])}]

            # Mark generation complete and plans loaded
            st.session_state["generate_clicked"] = False
            st.session_state["plans_loaded"] = True

            # Store plans in session state
            st.session_state["all_plans"] = all_plans
            st.session_state["plan_index"] = 0
            st.session_state["plan_meta"] = {
                "program_label": program_label,
                "start_term_code": start_term_code,
                "pace_label": pace_label,
                "cert_codes": cert_codes,
                "max_terms": max_terms,
                "include_summer": include_summer,
                "break_terms": break_terms,
            }

    except Exception as e:
        st.error(
            "Error calling OBCC Vertex AI conversational agent for planning:\n"
            f"{e}"
        )

# Display plans from session state
if "all_plans" in st.session_state and st.session_state["all_plans"]:
    all_plans = st.session_state["all_plans"]
    plan_index = st.session_state.get("plan_index", 0)
    meta = st.session_state.get("plan_meta", {})

    current_plan = all_plans[plan_index]
    current_rows = current_plan.get("rows", [])
    total_plans = len(all_plans)
    
    # Check if all plans are identical — only relevant when multiple versions requested
    all_rows = [json.dumps(p.get("rows", []), sort_keys=True) for p in all_plans]
    plans_are_identical = len(set(all_rows)) == 1

    # Navigation header — only show if multiple plans AND they differ
    if total_plans > 1 and not plans_are_identical:
        nav_col1, nav_col2, nav_col3 = st.columns([1, 2, 1])
        with nav_col1:
            if st.button("← Previous", disabled=(plan_index == 0)):
                st.session_state["plan_index"] = plan_index - 1
                st.rerun()
        with nav_col2:
            st.markdown(
                f"<div style='text-align:center; padding-top:0.4rem; font-weight:600;'>Plan {plan_index + 1} of {total_plans}</div>",
                unsafe_allow_html=True,
            )
        with nav_col3:
            if st.button("Next →", disabled=(plan_index == total_plans - 1)):
                st.session_state["plan_index"] = plan_index + 1
                st.rerun()

    elif total_plans > 1 and plans_are_identical:
        st.markdown(
            """
            <div class="custom-info-box">
                Only one unique plan could be generated for this program and certificate combination — all required courses have fixed scheduling with no room for variation.
            </div>
            """,
            unsafe_allow_html=True,
        )

    st.markdown(
        f"Plan generated for **{meta.get('program_label', '')}**, "
        f"starting **{meta.get('start_term_code', '')}**, "
        f"Pace: **{meta.get('pace_label', '').split()[0]}**, "
        f"Certificates: **{', '.join(meta.get('cert_codes', [])) if meta.get('cert_codes') else 'None'}**."
    )

    # Add break term rows to the display dataframe
    # Break terms show as a single row with "SEMESTER BREAK" in the course title
    _meta_breaks = meta.get("break_terms", [])
    _break_rows = []
    for bt in _meta_breaks:
        _break_rows.append({
            "term": bt,
            "course_number": "—",
            "course_title": "⏸ Semester Break",
            "credits": 0,
            "session": "—",
            "tuition": 0,
        })

    if _break_rows:
        _break_df = pd.DataFrame(_break_rows)
        _all_rows = current_rows + _break_rows
        # Re-sort by term order using the START_TERMS list as reference
        _term_order = {t: i for i, t in enumerate(START_TERMS)}
        _all_rows.sort(key=lambda r: _term_order.get(r["term"], 999))
        df = pd.DataFrame(_all_rows)
    else:
        df = pd.DataFrame(current_rows)

    st.dataframe(df, use_container_width=True)

    total_hours = df["credits"].sum() if "credits" in df.columns else None
    total_tuition = df["tuition"].sum() if "tuition" in df.columns else None
    # Count only actual course terms (exclude break rows)
    total_terms = len(set(r["term"] for r in current_rows)) if current_rows else None

    col1, col2, col3 = st.columns(3)

    with col1:
        if total_hours is not None:
            st.markdown(
                f"""
                <div class="summary-metric-label">Total credits</div>
                <div class="summary-metric-value">{int(total_hours)}</div>
                """,
                unsafe_allow_html=True,
            )

    with col2:
        if total_terms is not None:
            st.markdown(
                f"""
                <div class="summary-metric-label">Total semesters</div>
                <div class="summary-metric-value">{total_terms}</div>
                """,
                unsafe_allow_html=True,
            )

    with col3:
        if total_tuition is not None:
            st.markdown(
                f"""
                <div class="summary-metric-label">Total tuition (estimate)</div>
                <div class="summary-metric-value">${int(total_tuition):,}</div>
                """,
                unsafe_allow_html=True,
            )

st.markdown(
    """
    <div class="custom-caption">
        Tuition estimates are approximate and subject to change.
    </div>
    """,
    unsafe_allow_html=True,
)

# ------------- PDF download ------------- #
# Generates a formatted PDF of the currently displayed plan.
# The PDF includes the plan header, a term-by-term course table,
# and a totals row with total credits and tuition estimate.


def _format_term_label(term_code: str) -> str:
    """Convert 'SP26' → 'Spring 2026', 'FA27' → 'Fall 2027' etc."""
    if not term_code or len(term_code) < 4:
        return term_code
    season_code = term_code[:2]
    year_code = term_code[2:]
    season_map = {"SP": "Spring", "SU": "Summer", "FA": "Fall"}
    season = season_map.get(season_code, season_code)
    year = 2000 + int(year_code)
    return f"{season} {year}"


def make_pdf(plan_df: pd.DataFrame, header_text: str) -> bytes:
    df_local = plan_df.copy()

    term_col = None
    for cand in ["term", "Term", "term_code", "TermCode"]:
        if cand in df_local.columns:
            term_col = cand
            break

    if term_col is None:
        raise ValueError(
            f"Could not find a term column in plan_df. "
            f"Available columns: {list(df_local.columns)}"
        )

    if term_col != "term":
        df_local = df_local.rename(columns={term_col: "term"})

    pdf = FPDF(orientation="P", unit="mm", format="Letter")
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.add_page()

    pdf.set_font("Helvetica", "B", 18)
    from fpdf.enums import XPos, YPos
    pdf.cell(0, 10, "OBCC Degree Plan", new_x=XPos.LMARGIN, new_y=YPos.NEXT)

    pdf.set_font("Helvetica", "", 11)
    pdf.multi_cell(0, 5, header_text)
    pdf.ln(3)

    col_course = 25
    col_title = 80
    col_credits = 15
    col_session = 35
    col_tuition = 30

    def draw_table_header():
        pdf.set_font("Helvetica", "B", 10)
        pdf.set_fill_color(230, 230, 230)
        pdf.cell(col_course, 7, "Course", border=1, align="L", fill=True)
        pdf.cell(col_title, 7, "Course Title", border=1, align="L", fill=True)
        pdf.cell(col_credits, 7, "Hours", border=1, align="C", fill=True)
        pdf.cell(col_session, 7, "Session", border=1, align="L", fill=True)
        pdf.cell(col_tuition, 7, "Tuition", border=1, align="R", fill=True)
        pdf.ln()

    total_credits = 0
    total_tuition_val = 0

    ordered_terms = list(dict.fromkeys(df_local["term"].tolist()))

    for term_code in ordered_terms:
        group = df_local[df_local["term"] == term_code]

        term_label = _format_term_label(term_code)
        pdf.set_font("Helvetica", "B", 12)
        pdf.set_fill_color(255, 230, 150)
        pdf.cell(0, 8, term_label, ln=1, fill=True)

        draw_table_header()

        pdf.set_font("Helvetica", "", 10)
        line_height = 5

        for _, row in group.iterrows():
            course = str(row["course_number"])
            title = str(row["course_title"])
            credits = int(row["credits"])
            session = str(row["session"])
            tuition = int(row["tuition"])

            total_credits += credits
            total_tuition_val += tuition

            x0, y0 = pdf.get_x(), pdf.get_y()

            title_lines = pdf.multi_cell(col_title, line_height, title, dry_run=True, output="LINES")
            row_height = line_height * len(title_lines)

            pdf.set_xy(x0, y0)
            pdf.cell(col_course, row_height, course, border=1, align="L")

            pdf.set_xy(x0 + col_course, y0)
            pdf.multi_cell(col_title, line_height, title, border=1, align="L")

            pdf.set_xy(x0 + col_course + col_title, y0)

            pdf.cell(col_credits, row_height, str(credits), border=1, align="C")
            pdf.cell(col_session, row_height, session, border=1, align="L")
            pdf.cell(col_tuition, row_height, f"${tuition:,.0f}", border=1, align="R")

            pdf.set_xy(x0, y0 + row_height)

        pdf.ln(3)

    pdf.set_font("Helvetica", "B", 11)
    pdf.set_fill_color(255, 230, 150)
    pdf.cell(col_course + col_title, 8, "TOTALS", border=1, align="R", fill=True)
    pdf.cell(col_credits, 8, str(total_credits), border=1, align="C", fill=True)
    pdf.cell(col_session, 8, "", border=1, fill=True)
    pdf.cell(col_tuition, 8, f"${total_tuition_val:,.0f}", border=1, align="R", fill=True)
    pdf.ln()

    raw = pdf.output()
    if isinstance(raw, (bytes, bytearray)):
        return bytes(raw)
    return raw.encode("latin1")


if df is not None:
    meta = st.session_state.get("plan_meta", {})
    plan_index = st.session_state.get("plan_index", 0)
    pace_label_pdf = meta.get("pace_label", "")
    cert_codes_pdf = meta.get("cert_codes", [])
    max_terms_pdf = meta.get("max_terms", 6)
    program_label_pdf = meta.get("program_label", "")
    start_term_code_pdf = meta.get("start_term_code", "")
    total_plans = len(st.session_state.get("all_plans", []))

    pace_for_pdf = (
        pace_label_pdf
        .replace("≤", "<=")
        .replace("–", "-")
    )

    plan_label = f" (Version {plan_index + 1} of {total_plans})" if total_plans > 1 else ""
    breaks_pdf = meta.get("break_terms", [])
    breaks_label = f"\nBreaks: {', '.join(breaks_pdf)}" if breaks_pdf else ""

    header_txt = (
        f"Program: {program_label_pdf}{plan_label}\n"
        f"Start term: {start_term_code_pdf}\n"
        f"Pace: {pace_for_pdf}\n"
        f"Certificates: {', '.join(cert_codes_pdf) if cert_codes_pdf else 'None'}\n"
        f"Max terms: {max_terms_pdf}"
        f"{breaks_label}"
    )

    # Filter out break rows before generating PDF (break rows have 0 credits)
    df_pdf = df[df["course_number"] != "—"].copy() if df is not None else df
    pdf_bytes = make_pdf(df_pdf, header_txt)

    st.download_button(
        f"Download degree plan as PDF",
        data=pdf_bytes,
        file_name=f"obcc_degree_plan_v{plan_index + 1}.pdf",
        mime="application/pdf",
    )

# ------------- OBCC Course Assistant (simple Q&A at bottom) ------------- #
# Simple course lookup tool. The user types a course number (e.g. "OB 6374")
# and the assistant returns the course name, credits, and when it is offered.
# Uses cached BigQuery data to avoid repeated API calls.

st.markdown('<div class="section-divider"></div>', unsafe_allow_html=True)

st.markdown(
    '<h3 class="section-subheader">Ask the OBCC Course Assistant</h3>',
    unsafe_allow_html=True,
)

st.write(
    "Ask about a specific course number and I'll tell you the name, "
    "credits, and when it's offered. For example: "
    "`What is OB 6374?` or `When is OB 6334 offered?`"
)

question = st.text_input("Type your question about a course...")

if question:
    df_courses, df_offerings = load_catalog()
    answer = answer_course_question(question, df_courses, df_offerings)
    st.markdown("#### Answer")
    st.markdown(answer)

# %%