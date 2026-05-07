#Main
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
# main.py
# -------
# FastAPI backend for the OBCC Degree Planner.
# Exposes a single POST /plan endpoint that accepts plan configuration
# and returns one or more degree plan variations.
# Called by the Streamlit frontend (degree_plan_app.py) via HTTP.

from typing import List, Optional

from fastapi import FastAPI
from pydantic import BaseModel

import planner_core as pc

app = FastAPI()


class DegreePlannerRequest(BaseModel):
    """
    Defines the expected JSON body for the /plan endpoint.
    All fields have sensible defaults so only program_code and
    start_term_code are truly required.
    """
    program_code: str                    # "MSLOD" or "HOL-EMBA"
    start_term_code: str                 # e.g. "SP26" — first term of the plan
    certs: Optional[List[str]] = None    # certificate codes e.g. ["OC", "TL"]
    half_time: bool = False              # if True, max 1 course per term
    max_terms: int = 20                  # target number of terms to spread courses across
    target_credits: Optional[int] = None # override total credits (defaults by program)
    return_rows: bool = True             # if True, return flat row list for the UI table
    num_plans: int = 1                   # number of plan variations to generate (max 3)
    include_summer: bool = True
    break_terms: list = []             # term codes where student takes a break e.g. ["FA26"]          # if False, Summer terms are skipped entirely


@app.get("/")
def health_check():
    """Simple health check endpoint — returns ok if the server is running."""
    return {"status": "ok"}


@app.post("/plan")
def generate_plan(body: DegreePlannerRequest):
    """
    Main planning endpoint. Builds one or more degree plan variations.

    Flow:
    1. Determine target credits based on program (36 for MSLOD, 53 for HOL-EMBA)
    2. Loop through each requested variation, calling run_planner with a different seed
    3. Enrich each plan with tuition estimates
    4. Return either a single plan (num_plans=1) or a dict with all plans
    """

    # Determine target credits — use override if provided, otherwise use program defaults
    if body.target_credits is None:
        if body.program_code == "MSLOD":
            target = 36
        elif body.program_code == "HOL-EMBA":
            target = 53
        else:
            target = 36
    else:
        target = body.target_credits

    certs = body.certs or []
    num_plans = max(1, min(body.num_plans, 3))  # safety cap at 3 variations

    # Generate each plan variation
    # variation=0 is the default/baseline plan
    # variation=1,2 use different random seeds for elective ordering
    all_plans = []
    for i in range(num_plans):
        plan = pc.run_planner(
            program_code=body.program_code,
            start_term_code=body.start_term_code,
            certs=certs,
            half_time=body.half_time,
            max_terms=body.max_terms,
            target_credits=target,
            variation=i,
            include_summer=body.include_summer,
            break_terms=body.break_terms,
        )

        # Add tuition estimates to each course and compute totals
        plan = pc.enrich_plan_with_tuition(plan)

        if body.return_rows:
            # Flatten the nested plan structure into a list of rows
            # suitable for display in the Streamlit dataframe table
            rows = pc.plan_to_table_rows(plan)
            all_plans.append({
                "variation": i + 1,
                "program_code": plan["program_code"],
                "certificates": plan["certificates"],
                "start_term_code": plan["start_term_code"],
                "half_time": plan["half_time"],
                "include_summer": plan["include_summer"],
                "break_terms": plan.get("break_terms", []),
                "total_credits": plan["total_credits"],
                "total_tuition": plan["total_tuition"],
                "tuition_per_credit": plan["tuition_per_credit"],
                "rows": rows,
            })
        else:
            # Return the full nested plan structure (used for debugging/testing)
            plan["variation"] = i + 1
            all_plans.append(plan)

    # For single plan requests, return the plan directly (backwards compatible)
    # For multiple plans, wrap in a {"plans": [...]} dict
    if num_plans == 1:
        return all_plans[0]

    return {"plans": all_plans}
