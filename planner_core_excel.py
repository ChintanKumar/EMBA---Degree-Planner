import os
from typing import List, Dict, Any

import pandas as pd

# -------------------------
# Data loading
# -------------------------

EXCEL_FILE = os.path.join(os.path.dirname(__file__), "Data - New", "DATA_modified AI6399 2.xlsx")
data_sheets = None

def load_data():
    global data_sheets
    if data_sheets is None:
        data_sheets = pd.read_excel(EXCEL_FILE, sheet_name=None)


# -------------------------
# Display labels & tuition
# -------------------------

PART_OF_TERM_LABELS = {
    "1st8wk": "1st 8 weeks",
    "2nd8wk": "2nd 8 weeks",
    "Full16wk": "Full Term",  # change text if you want "Full 11 weeks"
}

TUITION_PER_CREDIT = 900


# -------------------------
# Certificate code helper
# -------------------------

# Map multiple UI labels / text values → canonical short codes
CERT_ALIAS_MAP = {
    # Organizational Consulting
    "OC": "OC",
    "Organizational Consulting": "OC",

    # Transformational Leadership
    "TL": "TL",
    "Transformational Leadership": "TL",

    # Strategic Human Resources
    "SHR": "SHR",
    "Strategic Human Resources": "SHR",

    # Coaching
    "COACH": "COACH",
    "Coaching": "COACH",
}


def normalize_certs(certs: List[str]) -> set:
    """
    Normalize certificate names coming from the UI / API payload.

    Accepts both short codes ("OC", "TL", "SHR", "COACH") and
    full labels ("Organizational Consulting", etc.) and returns
    a set of canonical codes.
    """
    return {CERT_ALIAS_MAP.get(c, c) for c in certs or []}


# -------------------------
# 1. Data access helpers
# -------------------------

def get_program_courses(program_code: str, certs: List[str]) -> pd.DataFrame:
    """
    certs only matter for:
      - MSLOD (OC / SHR / TL / Coaching)
      - HOL-EMBA when student wants to add cert-style courses on top of EMBA.

    MSLOD:
      - Cores: IsCoreRecommended = 1 OR IsCore = 1
      - MSLOD electives: IsSupplementalElective = 1
      - Plus cert-flagged courses (IsOC / IsSHR / IsTL / IsCoaching)
      - CorePriority:
          0 = chosen cert courses
          1 = cores
          2 = other electives

    HOL-EMBA:
      - Always include:
          * IsCore = 1  (EMBA cores)
          * IsElective = 1 (EMBA electives)
      - If certs requested, push those cert-flagged courses earlier:
          * CorePriority:
              0 = chosen cert courses
              1 = cores
              2 = other electives
              3 = everything else (rare)
    """
    load_data()

    # Create v_course_program equivalent
    course_program = data_sheets['CourseProgram'].merge(data_sheets['Program'], on='ProgramID')
    v_course_program = course_program.merge(data_sheets['Course'], on='CourseID')

    # Normalize column names
    v_course_program = v_course_program.rename(columns={'IsCoachingCourse': 'IsCoaching'})

    df = v_course_program[v_course_program['ProgramCode'] == program_code].copy()

    # 🔴 Normalize certificate names first
    norm_certs = normalize_certs(certs)
    want_oc = "OC" in norm_certs
    want_shr = "SHR" in norm_certs
    want_tl = "TL" in norm_certs
    want_coaching = "COACH" in norm_certs

    if program_code == "MSLOD":
        # Filter
        mask = (
            (df['IsCoreRecommended'] == 1) |
            (df['IsCore'] == 1) |
            (df['IsSupplementalElective'] == 1) |
            (want_oc & (df['IsOC'] == 1)) |
            (want_shr & (df['IsSHR'] == 1)) |
            (want_tl & (df['IsTL'] == 1)) |
            (want_coaching & (df['IsCoaching'] == 1))
        )
        df = df[mask]

        # CorePriority
        df['CorePriority'] = 2  # default
        cert_mask = (
            (want_oc & (df['IsOC'] == 1)) |
            (want_shr & (df['IsSHR'] == 1)) |
            (want_tl & (df['IsTL'] == 1)) |
            (want_coaching & (df['IsCoaching'] == 1))
        )
        df.loc[cert_mask, 'CorePriority'] = 0
        core_mask = (df['IsCoreRecommended'] == 1) | (df['IsCore'] == 1)
        df.loc[~cert_mask & core_mask, 'CorePriority'] = 1

        # OrderRank
        df['OrderRank'] = 200
        df.loc[want_oc & (df['IsOC'] == 1) & df['OCPreferredOrder'].notna(), 'OrderRank'] = df['OCPreferredOrder']
        df.loc[want_shr & (df['IsSHR'] == 1) & df['SHRPreferredOrder'].notna(), 'OrderRank'] = df['SHRPreferredOrder']

    elif program_code == "HOL-EMBA":
        # Filter
        mask = (
            (df['IsCore'] == 1) |
            (df['IsElective'] == 1) |
            (want_oc & (df['IsOC'] == 1)) |
            (want_shr & (df['IsSHR'] == 1)) |
            (want_tl & (df['IsTL'] == 1)) |
            (want_coaching & (df['IsCoaching'] == 1))
        )
        df = df[mask]

        # CorePriority
        df['CorePriority'] = 3  # default
        cert_mask = (
            (want_oc & (df['IsOC'] == 1)) |
            (want_shr & (df['IsSHR'] == 1)) |
            (want_tl & (df['IsTL'] == 1)) |
            (want_coaching & (df['IsCoaching'] == 1))
        )
        df.loc[cert_mask, 'CorePriority'] = 0
        df.loc[~cert_mask & (df['IsCore'] == 1), 'CorePriority'] = 1
        df.loc[~cert_mask & (df['IsElective'] == 1), 'CorePriority'] = 2

        # OrderRank
        df['OrderRank'] = 200
        df.loc[want_oc & (df['IsOC'] == 1) & df['OCPreferredOrder'].notna(), 'OrderRank'] = df['OCPreferredOrder']
        df.loc[want_shr & (df['IsSHR'] == 1) & df['SHRPreferredOrder'].notna(), 'OrderRank'] = df['SHRPreferredOrder']

    else:
        raise ValueError(f"Unknown program_code {program_code}")

    df["OrderRank"] = df["OrderRank"].fillna(999)

    df = df.sort_values(
        ["CorePriority", "OrderRank", "CourseNumber"],
        ascending=[True, True, True],
    )

    # Select columns as in the query
    columns = [
        'CourseID', 'CourseNumber', 'CourseTitle', 'DefaultCreditHours', 'ProgramCode',
        'IsCoreRecommended', 'IsSupplementalElective', 'IsCore', 'IsOC', 'IsSHR', 'IsTL', 'IsCoaching',
        'OCPreferredOrder', 'SHRPreferredOrder', 'CorePriority', 'OrderRank'
    ]
    if program_code == "HOL-EMBA":
        columns.extend(['IsElective'])
    df = df[columns]

    return df


def get_prereqs(program_code: str) -> pd.DataFrame:
    load_data()

    df = data_sheets['CoursePrerequisite']

    if program_code == "MSLOD":
        program_id = 2
        is_suggested_value = 1
    elif program_code == "HOL-EMBA":
        program_id = 1
        is_suggested_value = 0
    else:
        raise ValueError(f"Unknown program_code {program_code}")

    df = df[(df['ProgramID'] == program_id) & (df['IsSuggested'] == is_suggested_value)]
    return df


def get_offerings(program_code: str) -> pd.DataFrame:
    load_data()

    # Create v_course_offering equivalent
    df = data_sheets['Courseoffering '].merge(data_sheets['Program'], on='ProgramID')
    df = df.merge(data_sheets['Term'], on='TermID')

    df = df[df['ProgramCode'] == program_code]
    return df


def get_term_preferences(program_code: str) -> pd.DataFrame:
    load_data()

    # Create v_course_term_preference equivalent
    df = data_sheets['CourseTermPreference'].merge(data_sheets['CourseProgram'], on='CourseProgramID')
    df = df.merge(data_sheets['Program'], on='ProgramID')
    df = df.merge(data_sheets['Term'], on='TermID')

    df = df[df['ProgramCode'] == program_code]
    df = df[['CourseID', 'TermCode']]
    return df


# -------------------------
# 2. Term sequence helper
# -------------------------

def generate_term_sequence(start_term_code: str, max_terms: int) -> List[str]:
    seasons = ["SP", "SU", "FA"]

    start_season = start_term_code[:2]
    year = int(start_term_code[2:])

    if start_season not in seasons:
        raise ValueError(f"Unknown season in start_term_code: {start_term_code}")

    idx = seasons.index(start_season)

    seq: List[str] = []
    for _ in range(max_terms):
        season = seasons[idx]
        seq.append(f"{season}{year:02d}")

        idx += 1
        if idx == len(seasons):
            idx = 0
            year += 1

    return seq


# -------------------------
# 3. Compaction helper
# -------------------------

def compact_plan_terms(
    plan_terms: List[Dict[str, Any]],
    max_courses_per_term: int,
    offerings: pd.DataFrame,
    prereqs: pd.DataFrame,
) -> List[Dict[str, Any]]:
    if not plan_terms:
        return plan_terms

    changed = True

    while changed:
        changed = False

        course_term: Dict[int, int] = {}
        for ti, term in enumerate(plan_terms):
            for c in term["courses"]:
                course_term[c["course_id"]] = ti

        def can_place(course_id: int, target_idx: int) -> bool:
            target_term = plan_terms[target_idx]
            season = target_term["term_code"][:2]

            off = offerings[
                (offerings["CourseID"] == course_id) &
                (offerings["TermCode"] == season)
            ]
            if off.empty:
                return False

            needed = prereqs.loc[
                prereqs["CourseID"] == course_id,
                "PrerequisiteCourseID"
            ].tolist()

            for pid in needed:
                if pid not in course_term:
                    return False
                if course_term[pid] >= target_idx:
                    return False

            return True

        for i in range(len(plan_terms)):
            if not plan_terms[i]["courses"]:
                continue

            while len(plan_terms[i]["courses"]) < max_courses_per_term:
                moved_any = False

                for j in range(i + 1, len(plan_terms)):
                    if not plan_terms[j]["courses"]:
                        continue

                    for c in list(plan_terms[j]["courses"]):
                        cid = c["course_id"]

                        if not can_place(cid, i):
                            continue

                        plan_terms[j]["courses"].remove(c)
                        plan_terms[j]["total_credits"] -= c["credits"]

                        plan_terms[i]["courses"].append(c)
                        plan_terms[i]["total_credits"] += c["credits"]

                        changed = True
                        moved_any = True
                        course_term[cid] = i
                        break

                    if moved_any:
                        break

                if not moved_any:
                    break

        while plan_terms and not plan_terms[-1]["courses"]:
            plan_terms.pop()
            changed = True

    return plan_terms


# -------------------------
# 4. Main planner
# -------------------------

def run_planner(
    program_code: str,
    start_term_code: str,
    certs: List[str],
    max_terms: int = 20,
    target_credits: int = 36,
    half_time: bool = False,
) -> Dict[str, Any]:
    max_courses_per_term = 1 if half_time else 2

    courses = get_program_courses(program_code, certs)
    prereqs = get_prereqs(program_code)
    offerings = get_offerings(program_code)
    term_prefs_df = get_term_preferences(program_code)

    # Manual prereq override: FIN 6301 requires OPRE 6301 for HOL-EMBA
    if program_code == "HOL-EMBA":
        try:
            fin_id = int(
                courses.loc[courses["CourseNumber"] == "FIN 6301", "CourseID"].iloc[0]
            )
            opre_id = int(
                courses.loc[courses["CourseNumber"] == "OPRE 6301", "CourseID"].iloc[0]
            )

            exists_mask = (
                (prereqs["CourseID"] == fin_id) &
                (prereqs["PrerequisiteCourseID"] == opre_id)
            )

            if not exists_mask.any():
                extra_row = {
                    "CourseID": fin_id,
                    "PrerequisiteCourseID": opre_id,
                }
                if "ProgramID" in prereqs.columns:
                    extra_row["ProgramID"] = 1
                if "IsSuggested" in prereqs.columns:
                    extra_row["IsSuggested"] = 0

                prereqs = pd.concat(
                    [prereqs, pd.DataFrame([extra_row])],
                    ignore_index=True,
                )
        except IndexError:
            pass

    term_seq = generate_term_sequence(start_term_code, max_terms)

    term_pref_map = (
        term_prefs_df
        .groupby("CourseID")["TermCode"]
        .apply(set)
        .to_dict()
    )

    start_year = int(start_term_code[2:])

    taken = set()
    plan_terms: List[Dict[str, Any]] = []
    total_credits_so_far = 0

    part_order = {"1st8wk": 0, "2nd8wk": 1, "Full16wk": 2}

    for full_term in term_seq:
        if total_credits_so_far >= target_credits:
            break

        season = full_term[:2]
        year = int(full_term[2:])

        term_courses: List[Dict[str, Any]] = []
        term_credits = 0
        term_course_count = 0

        used_8wk_slots = set()

        for _, row in courses.iterrows():
            if total_credits_so_far >= target_credits:
                break
            if term_course_count >= max_courses_per_term:
                break

            cid = int(row["CourseID"])
            if cid in taken:
                continue

            course_number = row["CourseNumber"]

            prefs = term_pref_map.get(cid)
            if year == start_year and prefs and season not in prefs:
                continue

            needed = prereqs.loc[
                prereqs["CourseID"] == cid,
                "PrerequisiteCourseID"
            ].tolist()
            if not set(needed).issubset(taken):
                continue

            credits = int(row["DefaultCreditHours"])
            if total_credits_so_far + credits > target_credits:
                continue

            offered = offerings[
                (offerings["CourseID"] == cid) &
                (offerings["TermCode"] == season)
            ]
            if offered.empty:
                continue

            chosen_slot = None
            slots = [str(s) for s in offered["PartOfTermCode"].dropna().unique()]

            # Special rule: for HOL-EMBA, force FIN 6301 & OPRE 6301 to Full16wk
            if program_code == "HOL-EMBA" and course_number in ("FIN 6301", "OPRE 6301"):
                if "Full16wk" in slots:
                    chosen_slot = "Full16wk"
                else:
                    continue
            else:
                if season in ("SP", "FA"):
                    has_real_8wk = any(s in ("1st8wk", "2nd8wk") for s in slots)

                    if has_real_8wk:
                        for slot in slots:
                            if slot in ("1st8wk", "2nd8wk") and slot not in used_8wk_slots:
                                chosen_slot = slot
                                break
                    else:
                        if "1st8wk" not in used_8wk_slots:
                            chosen_slot = "1st8wk"
                        elif "2nd8wk" not in used_8wk_slots:
                            chosen_slot = "2nd8wk"
                else:
                    for slot in slots:
                        chosen_slot = slot
                        break

            if chosen_slot is None:
                continue

            if season in ("SP", "FA") and chosen_slot in ("1st8wk", "2nd8wk"):
                used_8wk_slots.add(chosen_slot)

            label = PART_OF_TERM_LABELS.get(chosen_slot, chosen_slot)

            term_courses.append({
                "course_id": cid,
                "course_number": course_number,
                "title": row["CourseTitle"],
                "credits": credits,
                "part_of_term": chosen_slot,
                "part_of_term_label": label,
            })
            term_credits += credits
            total_credits_so_far += credits
            term_course_count += 1
            taken.add(cid)

        if term_courses:
            term_courses.sort(key=lambda c: part_order.get(c["part_of_term"], 99))

            plan_terms.append({
                "term_code": full_term,
                "total_credits": term_credits,
                "courses": term_courses,
            })

        if total_credits_so_far >= target_credits:
            break

        plan_terms = compact_plan_terms(
            plan_terms=plan_terms,
            max_courses_per_term=max_courses_per_term,
            offerings=offerings,
            prereqs=prereqs,
        )

    return {
        "program_code": program_code,
        "certificates": certs,
        "start_term_code": start_term_code,
        "half_time": half_time,
        "terms": plan_terms,
        "total_credits": total_credits_so_far,
    }


# -------------------------
# 5. Tuition helpers
# -------------------------

def enrich_plan_with_tuition(
    plan: Dict[str, Any],
    tuition_per_credit: int = TUITION_PER_CREDIT,
) -> Dict[str, Any]:
    total = 0

    for term in plan["terms"]:
        term_tuition = 0
        for c in term["courses"]:
            credits = int(c["credits"])
            t = credits * tuition_per_credit
            c["tuition"] = t
            term_tuition += t
        term["term_tuition"] = term_tuition
        total += term_tuition

    plan["tuition_per_credit"] = tuition_per_credit
    plan["total_tuition"] = total
    return plan


def plan_to_table_rows(
    plan: Dict[str, Any],
    tuition_per_credit: int = TUITION_PER_CREDIT,
) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []

    for term in plan["terms"]:
        term_code = term["term_code"]

        for c in term["courses"]:
            credits = int(c["credits"])
            session_label = c.get("part_of_term_label", c["part_of_term"])
            tuition = credits * tuition_per_credit

            rows.append({
                "term": term_code,
                "course_number": c["course_number"],
                "course_title": c["title"],
                "credits": credits,
                "session": session_label,
                "tuition": tuition,
            })

    return rows


# -------------------------
# 6. Simple text summary
# -------------------------

def summarize_plan(plan: Dict[str, Any], label: str = "") -> None:
    if label:
        print(f"\n===== {label} =====")
    print(
        f"Program: {plan['program_code']}, Certs: {plan['certificates']}, "
        f"Half-time: {plan.get('half_time', False)}, "
        f"Total credits: {plan['total_credits']}"
    )
    print("Terms:")
    for term in plan["terms"]:
        term_code = term["term_code"]
        t_cred = term["total_credits"]
        courses = ", ".join(
            f"{c['course_number']} ({c.get('part_of_term_label', c['part_of_term'])})"
            for c in term["courses"]
        )
        print(f"  - {term_code}: {t_cred} credits -> {courses}")

# %%
