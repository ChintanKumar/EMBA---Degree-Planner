# Planner Core
import os
import random
from typing import List, Dict, Any, Set

from google.cloud import bigquery
import pandas as pd

PROJECT_ID = os.environ.get("GOOGLE_CLOUD_PROJECT", "obcc-degree-planner-489404")
DATASET = "obcc-degree-planner-489404.degree_planner_config_data"


def get_bq_client() -> bigquery.Client:
    """Create a BigQuery client. Called inside functions so imports don't crash in Cloud Run."""
    return bigquery.Client(project=PROJECT_ID)


PART_OF_TERM_LABELS = {
    "1st8wk": "1st 8 weeks",
    "2nd8wk": "2nd 8 weeks",
    "Full16wk": "Full Term",
}

TUITION_PER_CREDIT = 900

CERT_ALIAS_MAP = {
    "OC": "OC", "Organizational Consulting": "OC",
    "TL": "TL", "Transformational Leadership": "TL",
    "SHR": "SHR", "Strategic Human Resources": "SHR",
    "COACH": "COACH", "Coaching": "COACH",
}


def normalize_certs(certs: List[str]) -> set:
    """Normalize certificate names to canonical short codes."""
    return {CERT_ALIAS_MAP.get(c, c) for c in certs or []}


def get_program_courses(program_code: str, certs: List[str]) -> pd.DataFrame:
    """
    Fetches courses for a program/cert combo from BigQuery, sorted by priority:
      - CorePriority 0: certificate courses (scheduled first)
      - CorePriority 1: required core courses
      - CorePriority 2: supplemental electives (scheduled last)
    Applies data overrides for BigQuery view inconsistencies.
    """
    client = get_bq_client()
    norm_certs = normalize_certs(certs)
    want_oc = "OC" in norm_certs
    want_shr = "SHR" in norm_certs
    want_tl = "TL" in norm_certs
    want_coaching = "COACH" in norm_certs

    if program_code == "MSLOD":
        query = f"""
        DECLARE want_oc       BOOL DEFAULT @want_oc;
        DECLARE want_shr      BOOL DEFAULT @want_shr;
        DECLARE want_tl       BOOL DEFAULT @want_tl;
        DECLARE want_coaching BOOL DEFAULT @want_coaching;

        SELECT CourseID, CourseNumber, CourseTitle, DefaultCreditHours, ProgramCode,
               IsCoreRecommended, IsSupplementalElective, IsCore,
               IsOC, IsSHR, IsTL, IsCoaching, OCPreferredOrder, SHRPreferredOrder,
          CASE
            WHEN ((want_oc AND IsOC=1) OR (want_shr AND IsSHR=1) OR
                  (want_tl AND IsTL=1) OR (want_coaching AND IsCoaching=1)) THEN 0
            WHEN IsCoreRecommended=1 OR IsCore=1 THEN 1
            ELSE 2
          END AS CorePriority,
          CASE
            WHEN want_oc  AND IsOC=1  AND OCPreferredOrder  IS NOT NULL THEN OCPreferredOrder
            WHEN want_shr AND IsSHR=1 AND SHRPreferredOrder IS NOT NULL THEN SHRPreferredOrder
            ELSE 200
          END AS OrderRank
        FROM `{DATASET}.v_course_program`
        WHERE ProgramCode = @program_code
          AND (IsCoreRecommended=1 OR IsCore=1 OR IsSupplementalElective=1
               OR (want_oc AND IsOC=1) OR (want_shr AND IsSHR=1)
               OR (want_tl AND IsTL=1) OR (want_coaching AND IsCoaching=1));
        """
        job = client.query(query, job_config=bigquery.QueryJobConfig(query_parameters=[
            bigquery.ScalarQueryParameter("program_code", "STRING", program_code),
            bigquery.ScalarQueryParameter("want_oc", "BOOL", want_oc),
            bigquery.ScalarQueryParameter("want_shr", "BOOL", want_shr),
            bigquery.ScalarQueryParameter("want_tl", "BOOL", want_tl),
            bigquery.ScalarQueryParameter("want_coaching", "BOOL", want_coaching),
        ]))

    elif program_code == "HOL-EMBA":
        query = f"""
        SELECT CourseID, CourseNumber, CourseTitle, DefaultCreditHours, ProgramCode,
               IsCore, IsElective, IsCoreRecommended, IsSupplementalElective,
               IsOC, IsSHR, IsTL, IsCoaching, OCPreferredOrder, SHRPreferredOrder,
          CASE
            WHEN ((@want_oc AND IsOC=1) OR (@want_shr AND IsSHR=1) OR
                  (@want_tl AND IsTL=1) OR (@want_coaching AND IsCoaching=1)) THEN 0
            WHEN IsCore=1 THEN 1
            WHEN IsElective=1 THEN 2
            ELSE 3
          END AS CorePriority,
          CASE
            WHEN @want_oc  AND IsOC=1  AND OCPreferredOrder  IS NOT NULL THEN OCPreferredOrder
            WHEN @want_shr AND IsSHR=1 AND SHRPreferredOrder IS NOT NULL THEN SHRPreferredOrder
            ELSE 200
          END AS OrderRank
        FROM `{DATASET}.v_course_program`
        WHERE ProgramCode = @program_code
          AND (IsCore=1 OR IsElective=1
               OR (@want_oc AND IsOC=1) OR (@want_shr AND IsSHR=1)
               OR (@want_tl AND IsTL=1) OR (@want_coaching AND IsCoaching=1));
        """
        job = client.query(query, job_config=bigquery.QueryJobConfig(query_parameters=[
            bigquery.ScalarQueryParameter("program_code", "STRING", program_code),
            bigquery.ScalarQueryParameter("want_oc", "BOOL", want_oc),
            bigquery.ScalarQueryParameter("want_shr", "BOOL", want_shr),
            bigquery.ScalarQueryParameter("want_tl", "BOOL", want_tl),
            bigquery.ScalarQueryParameter("want_coaching", "BOOL", want_coaching),
        ]))
    else:
        raise ValueError(f"Unknown program_code {program_code}")

    df = job.to_dataframe()

    # Override: BigQuery incorrectly marks OB 6342/6344 as IsCoreRecommended=1
    df.loc[df["CourseNumber"].isin(["OB 6342", "OB 6344"]), "IsCoreRecommended"] = 0
    df.loc[df["CourseNumber"].isin(["OB 6342", "OB 6344"]), "CorePriority"] = 2

    df["OrderRank"] = df["OrderRank"].fillna(999)
    df = df.sort_values(["CorePriority", "OrderRank", "CourseNumber"], ascending=[True, True, True])
    return df


def get_prereqs(program_code: str) -> pd.DataFrame:
    """
    Fetches prerequisite relationships for the given program.
    MS LOD: IsSuggested=1 (enforced by planner).
    HOL-EMBA: IsSuggested=0 (all hard requirements).
    """
    client = get_bq_client()
    if program_code == "MSLOD":
        program_id, is_suggested_value = 2, 1
    elif program_code == "HOL-EMBA":
        program_id, is_suggested_value = 1, 0
    else:
        raise ValueError(f"Unknown program_code {program_code}")

    job = client.query(
        f"SELECT * FROM `{DATASET}.courseprerequisite` WHERE ProgramID=@program_id AND IsSuggested=@is_suggested",
        job_config=bigquery.QueryJobConfig(query_parameters=[
            bigquery.ScalarQueryParameter("program_id", "INT64", program_id),
            bigquery.ScalarQueryParameter("is_suggested", "INT64", is_suggested_value),
        ])
    )
    return job.to_dataframe()


def get_offerings(program_code: str) -> pd.DataFrame:
    """
    Fetches term/session offerings for each course.
    Applies overrides for rows missing from the BigQuery view.
    """
    client = get_bq_client()
    job = client.query(
        f"SELECT * FROM `{DATASET}.v_course_offering` WHERE ProgramCode=@program_code",
        job_config=bigquery.QueryJobConfig(query_parameters=[
            bigquery.ScalarQueryParameter("program_code", "STRING", program_code)
        ])
    )
    df = job.to_dataframe()

    # Override: MS LOD missing Fall offerings for OB 6301, OB 6357, OB 6393
    if program_code == "MSLOD":
        extra_rows = pd.DataFrame([
            {"CourseOfferingID": 112, "CourseID": 8,  "ProgramID": 2, "ProgramCode": "MSLOD", "TermCode": "FA", "TermSeason": "Fall", "PartOfTermCode": "2nd8wk", "SessionLabel": "2nd 8 weeks", "CreditHours": None, "PrimaryFacultyID": 24, "Format": "Online"},
            {"CourseOfferingID": 113, "CourseID": 21, "ProgramID": 2, "ProgramCode": "MSLOD", "TermCode": "FA", "TermSeason": "Fall", "PartOfTermCode": "1st8wk", "SessionLabel": "1st 8 weeks", "CreditHours": None, "PrimaryFacultyID": 20, "Format": "Online"},
            {"CourseOfferingID": 114, "CourseID": 22, "ProgramID": 2, "ProgramCode": "MSLOD", "TermCode": "FA", "PartOfTermCode": "2nd8wk", "SessionLabel": "2nd 8 weeks", "CreditHours": None, "PrimaryFacultyID": 21, "Format": "Online"},
        ])
        df = pd.concat([df, extra_rows], ignore_index=True)
    return df


def get_term_preferences(program_code: str) -> pd.DataFrame:
    """
    Fetches term preferences — e.g. a course that must start in Fall of year 1.
    Used to restrict scheduling in the first year of the plan.
    """
    client = get_bq_client()
    job = client.query(
        f"SELECT CourseID, TermCode FROM `{DATASET}.v_course_term_preference` WHERE ProgramCode=@program_code",
        job_config=bigquery.QueryJobConfig(query_parameters=[
            bigquery.ScalarQueryParameter("program_code", "STRING", program_code)
        ])
    )
    return job.to_dataframe()


def generate_term_sequence(start_term_code: str, max_terms: int) -> List[str]:
    """
    Generates an ordered list of term codes from start_term_code.
    Example: generate_term_sequence("SP26", 5) -> ["SP26","SU26","FA26","SP27","SU27"]
    """
    seasons = ["SP", "SU", "FA"]
    start_season = start_term_code[:2]
    year = int(start_term_code[2:])
    if start_season not in seasons:
        raise ValueError(f"Unknown season in start_term_code: {start_term_code}")
    idx = seasons.index(start_season)
    seq: List[str] = []
    for _ in range(max_terms):
        seq.append(f"{seasons[idx]}{year:02d}")
        idx += 1
        if idx == len(seasons):
            idx = 0
            year += 1
    return seq


def compact_plan_terms(
    plan_terms: List[Dict[str, Any]],
    max_courses_per_term: int,
    offerings: pd.DataFrame,
    prereqs: pd.DataFrame,
    deferred_ids: Set[int] = None,
) -> List[Dict[str, Any]]:
    """
    Moves courses earlier in the plan to fill gaps (like a defragmenter).
    Respects offering seasons, prerequisites, Summer caps, and max_courses_per_term.
    Runs repeatedly until no more moves are possible.
    Deferred courses (deferred_ids) are never pulled forward — this preserves
    the term-shift variation so compaction doesn't undo it.
    """
    if deferred_ids is None:
        deferred_ids = set()
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
            off = offerings[(offerings["CourseID"] == course_id) & (offerings["TermCode"] == season)]
            if off.empty:
                return False
            if season == "SU":
                course_credits = next((c["credits"] for c in target_term["courses"] if c["course_id"] == course_id), 3)
                if len(target_term["courses"]) >= 2 or target_term["total_credits"] + course_credits > 6:
                    return False
            needed = prereqs.loc[prereqs["CourseID"] == course_id, "PrerequisiteCourseID"].tolist()
            for pid in needed:
                if pid not in course_term or course_term[pid] >= target_idx:
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
                        # Never pull a deferred course forward — it was intentionally
                        # placed later and compaction must not undo that.
                        if cid in deferred_ids:
                            continue
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


def _build_deferred_set(
    courses: pd.DataFrame,
    offerings: pd.DataFrame,
    variation: int,
) -> Set[int]:
    """
    For variation > 0, picks a seeded random subset of courses to defer
    by one term, producing meaningfully different term layouts.

    Eligibility rules:
      - Course must be offered in 2+ non-Summer seasons (SP and/or FA).
        Summer-only courses cannot be deferred — they have no alternative
        season to land in, so deferring them has no effect on the plan.
      - All CorePriority levels are included so small programs with few
        flexible courses still get variation.

    Split strategy:
      - A single fixed shuffle (seed 99) is used for all variations.
      - Variation 1 defers the first half, variation 2 defers the second half.
      - The two halves are always disjoint, guaranteeing different plans
        for any pool size > 1. Pool size 1 is the only unavoidable tie.

    Size cap:
      - At most 3 courses deferred per variation to prevent HOL-EMBA
        (which has a larger pool) from pushing courses into extra terms.
    """
    if variation == 0:
        return set()

    def non_summer_seasons(cid: int) -> int:
        seasons = set(offerings.loc[offerings["CourseID"] == cid, "TermCode"].tolist())
        return len(seasons - {"SU"})

    # Only courses offered in 2+ non-Summer seasons can meaningfully shift terms.
    # For HOL-EMBA: restrict to CorePriority >= 2 (electives only) and cap at 2.
    #   Core courses (priority 1) in HOL-EMBA have tight prereq chains
    #   (e.g. OPRE->FIN) so deferring them cascades into extra terms.
    # For all other programs: include all priorities, cap at 3.
    has_hol_emba = courses["ProgramCode"].eq("HOL-EMBA").any()
    if has_hol_emba:
        # For HOL-EMBA, exclude courses in the OPRE->FIN prereq chain since
        # deferring them cascades into extra terms. All other multi-season
        # non-Summer courses are eligible regardless of CorePriority.
        EMBA_PREREQ_CHAIN = {"FIN 6301", "OPRE 6301"}
        eligible = [
            int(row["CourseID"])
            for _, row in courses.iterrows()
            if non_summer_seasons(int(row["CourseID"])) >= 2
            and row["CourseNumber"] not in EMBA_PREREQ_CHAIN
        ]
        cap = 2
    else:
        eligible = [
            int(row["CourseID"])
            for _, row in courses.iterrows()
            if non_summer_seasons(int(row["CourseID"])) >= 2
        ]
        cap = 3

    if not eligible:
        return set()

    import math
    rng = random.Random(99)
    rng.shuffle(eligible)

    n = max(1, min(cap, math.ceil(len(eligible) / 2)))

    if variation == 1:
        return set(eligible[:n])
    else:
        second_half = eligible[n:n*2]
        return set(second_half) if second_half else set(eligible[:n])


def run_planner(
    program_code: str,
    start_term_code: str,
    certs: List[str],
    max_terms: int = 20,
    target_credits: int = 36,
    half_time: bool = False,
    variation: int = 0,
    include_summer: bool = True,
    break_terms: List[str] = None,
) -> Dict[str, Any]:
    """
    Core planning engine. Two-phase approach:

    Phase 1 (main loop): Schedules at a controlled rate.
    Phase 2 (compaction): Pulls courses forward after each term.
    Phase 3 (post-processing): Fills remaining gaps.

    Variation via term-shifting:
      For variation > 0, a seeded-random subset of eligible multi-season
      non-cert courses are blocked from their FIRST eligible term and placed
      in their next eligible term instead.

      The block is enforced at the TERM level (not per get_ordered_courses call)
      so the course cannot sneak back in during the while-scheduled inner loop
      within the same term. Post-processing guarantees all credits are still met.
    """
    import math

    norm_certs = normalize_certs(certs)

    if program_code == "HOL-EMBA":
        baseline = 7
    elif "SHR" in norm_certs:
        baseline = 7
    else:
        baseline = 6

    break_terms_set = set(break_terms) if break_terms else set()

    courses = get_program_courses(program_code, certs)
    prereqs = get_prereqs(program_code)
    offerings = get_offerings(program_code)
    term_prefs_df = get_term_preferences(program_code)

    if program_code == "HOL-EMBA":
        try:
            fin_id = int(courses.loc[courses["CourseNumber"] == "FIN 6301", "CourseID"].iloc[0])
            opre_id = int(courses.loc[courses["CourseNumber"] == "OPRE 6301", "CourseID"].iloc[0])
            exists_mask = (prereqs["CourseID"] == fin_id) & (prereqs["PrerequisiteCourseID"] == opre_id)
            if not exists_mask.any():
                extra_row = {"CourseID": fin_id, "PrerequisiteCourseID": opre_id}
                if "ProgramID" in prereqs.columns: extra_row["ProgramID"] = 1
                if "IsSuggested" in prereqs.columns: extra_row["IsSuggested"] = 0
                prereqs = pd.concat([prereqs, pd.DataFrame([extra_row])], ignore_index=True)
        except IndexError:
            pass

    term_seq_full = generate_term_sequence(start_term_code, max_terms * 3)
    if not include_summer:
        term_seq_full = [t for t in term_seq_full if not t.startswith("SU")]
    term_seq_main = term_seq_full[:max_terms]
    term_seq_post = term_seq_full[:max_terms * 2]

    total_courses = len(courses)

    if half_time:
        dynamic_max = 1
    elif max_terms <= baseline:
        if program_code == "HOL-EMBA" or "SHR" in norm_certs:
            dynamic_max = 2
        else:
            dynamic_max = 3
    else:
        sp_fa_terms = sum(1 for t in term_seq_main if not t.startswith("SU"))
        su_terms = sum(1 for t in term_seq_main if t.startswith("SU")) if include_summer else 0
        su_capacity = su_terms * 2
        sp_fa_courses_needed = max(0, total_courses - su_capacity)
        dynamic_max = math.ceil(sp_fa_courses_needed / sp_fa_terms) if sp_fa_terms > 0 else 3
        dynamic_max = max(1, min(3, dynamic_max))

    def get_max_courses(term_code: str) -> int:
        if half_time:
            return 1
        if term_code[:2] == "SU":
            return 2
        return dynamic_max

    term_pref_map = (
        term_prefs_df
        .groupby("CourseID")["TermCode"]
        .apply(set)
        .to_dict()
    )

    # Build the deferred set for this variation.
    # deferred_ids: courses to skip on their first eligible term.
    # deferred_released: courses that have already been skipped once and
    #   are now free to schedule normally.
    # Both sets live at the run_planner scope so they persist correctly
    # across all terms and all inner-loop iterations.
    deferred_ids: Set[int] = _build_deferred_set(courses, offerings, variation)
    deferred_released: Set[int] = set()

    start_year = int(start_term_code[2:])
    taken: Set[int] = set()
    plan_terms: List[Dict[str, Any]] = []
    total_credits_so_far = 0
    part_order = {"1st8wk": 0, "2nd8wk": 1, "Full16wk": 2}

    # Main scheduling loop
    for full_term in term_seq_main:
        if total_credits_so_far >= target_credits:
            break

        season = full_term[:2]
        if not include_summer and season == "SU":
            continue
        if full_term in break_terms_set:
            continue

        year = int(full_term[2:])
        term_courses: List[Dict[str, Any]] = []
        term_credits = 0
        term_course_count = 0
        used_8wk_slots: Set[str] = set()
        has_full16wk = False

        # Courses that are deferred but not yet released are blocked for
        # this entire term. We release them here so they are available
        # from the NEXT term onward. This happens once per term, before
        # the inner scheduling loop, so get_ordered_courses cannot
        # accidentally schedule them within the same term they are deferred.
        newly_released: Set[int] = set()
        for cid in deferred_ids:
            if cid not in deferred_released and cid not in taken:
                # Check if this course is eligible this term (offered + prereqs met)
                offered = offerings[(offerings["CourseID"] == cid) & (offerings["TermCode"] == season)]
                if not offered.empty:
                    needed = prereqs.loc[prereqs["CourseID"] == cid, "PrerequisiteCourseID"].tolist()
                    if set(needed).issubset(taken):
                        # Course is eligible this term — defer it (block this term, release next)
                        newly_released.add(cid)
        # Add to released AFTER the loop so all deferred courses are blocked this term
        deferred_released.update(newly_released)

        def get_available(df, _season=season, _year=year):
            result = []
            for _, row in df.iterrows():
                cid = int(row["CourseID"])
                if cid in taken:
                    continue
                # Block deferred courses that were just released this term —
                # they become available next term
                if cid in newly_released:
                    continue
                prefs = term_pref_map.get(cid)
                if _year == start_year and prefs and _season not in prefs:
                    continue
                needed = prereqs.loc[prereqs["CourseID"] == cid, "PrerequisiteCourseID"].tolist()
                if not set(needed).issubset(taken):
                    continue
                if total_credits_so_far + int(row["DefaultCreditHours"]) > target_credits:
                    continue
                if offerings[(offerings["CourseID"] == cid) & (offerings["TermCode"] == _season)].empty:
                    continue
                result.append(row)
            return result

        def count_seasons(cid):
            return len(set(offerings.loc[offerings["CourseID"] == cid, "TermCode"].tolist()))

        def get_ordered_courses(_season=season):
            available = get_available(courses)
            multi_cert = sorted([r for r in available if count_seasons(int(r["CourseID"])) > 1  and r["CorePriority"] == 0], key=lambda r: (r["OrderRank"], r["CourseNumber"]))
            excl_cert  = sorted([r for r in available if count_seasons(int(r["CourseID"])) == 1 and r["CorePriority"] == 0], key=lambda r: (r["OrderRank"], r["CourseNumber"]))
            excl_core  = sorted([r for r in available if count_seasons(int(r["CourseID"])) == 1 and r["CorePriority"] == 1], key=lambda r: (r["OrderRank"], r["CourseNumber"]))
            multi_core = sorted([r for r in available if count_seasons(int(r["CourseID"])) > 1  and r["CorePriority"] == 1], key=lambda r: (r["OrderRank"], r["CourseNumber"]))
            excl_elec  = sorted([r for r in available if count_seasons(int(r["CourseID"])) == 1 and r["CorePriority"] == 2], key=lambda r: (r["OrderRank"], r["CourseNumber"]))
            multi_elec = sorted([r for r in available if count_seasons(int(r["CourseID"])) > 1  and r["CorePriority"] == 2], key=lambda r: (r["OrderRank"], r["CourseNumber"]))
            if variation > 0:
                rng = random.Random(variation + 1)
                rng.shuffle(excl_elec)
                rng.shuffle(multi_elec)
            return multi_cert + excl_cert + excl_core + multi_core + excl_elec + multi_elec

        scheduled_this_term = True
        while scheduled_this_term:
            scheduled_this_term = False

            for row in get_ordered_courses():
                if total_credits_so_far >= target_credits:
                    break

                season = full_term[:2]
                term_max = get_max_courses(full_term)

                if season == "SU":
                    credits = int(row["DefaultCreditHours"])
                    if term_course_count >= term_max:
                        break
                    if term_credits + credits > 6:
                        continue
                else:
                    if has_full16wk:
                        if term_course_count >= 2:
                            break
                    else:
                        if len(used_8wk_slots) >= term_max:
                            break

                cid = int(row["CourseID"])
                if cid in taken:
                    continue

                course_number = row["CourseNumber"]
                prefs = term_pref_map.get(cid)
                if year == start_year and prefs and season not in prefs:
                    continue

                needed = prereqs.loc[prereqs["CourseID"] == cid, "PrerequisiteCourseID"].tolist()
                if not set(needed).issubset(taken):
                    continue

                credits = int(row["DefaultCreditHours"])
                if total_credits_so_far + credits > target_credits:
                    continue

                offered = offerings[(offerings["CourseID"] == cid) & (offerings["TermCode"] == season)]
                if offered.empty:
                    continue

                chosen_slot = None
                slots = [str(s) for s in offered["PartOfTermCode"].dropna().unique()]

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

                if season in ("SP", "FA"):
                    if chosen_slot == "Full16wk":
                        has_full16wk = True
                    elif chosen_slot in ("1st8wk", "2nd8wk"):
                        used_8wk_slots.add(chosen_slot)

                term_courses.append({
                    "course_id": cid,
                    "course_number": course_number,
                    "title": row["CourseTitle"],
                    "credits": credits,
                    "part_of_term": chosen_slot,
                    "part_of_term_label": PART_OF_TERM_LABELS.get(chosen_slot, chosen_slot),
                })
                term_credits += credits
                total_credits_so_far += credits
                term_course_count += 1
                taken.add(cid)
                scheduled_this_term = True
                break

        if term_courses:
            term_courses.sort(key=lambda c: part_order.get(c["part_of_term"], 99))
            plan_terms.append({
                "term_code": full_term,
                "total_credits": term_credits,
                "courses": term_courses,
            })

        if total_credits_so_far >= target_credits:
            break

        if full_term[:2] == "SU":
            compact_max = 2
        elif program_code == "HOL-EMBA":
            compact_max = 3
        else:
            compact_max = dynamic_max
        plan_terms = compact_plan_terms(plan_terms, compact_max, offerings, prereqs, deferred_ids)


    # Post-processing: fill remaining credit gaps
    if total_credits_so_far < target_credits:

        for term in plan_terms:
            if total_credits_so_far >= target_credits:
                break
            season = term["term_code"][:2]
            max_slots = 2 if season == "SU" else 3
            if len(term["courses"]) >= max_slots:
                continue
            for _, row in courses.iterrows():
                if total_credits_so_far >= target_credits:
                    break
                cid = int(row["CourseID"])
                if cid in taken:
                    continue
                credits = int(row["DefaultCreditHours"])
                offered = offerings[(offerings["CourseID"] == cid) & (offerings["TermCode"] == season)]
                if offered.empty:
                    continue
                needed = prereqs.loc[prereqs["CourseID"] == cid, "PrerequisiteCourseID"].tolist()
                if not set(needed).issubset(taken):
                    continue
                if season == "SU" and (len(term["courses"]) >= 2 or term["total_credits"] + credits > 6):
                    continue
                slots = [str(s) for s in offered["PartOfTermCode"].dropna().unique()]
                used = {c["part_of_term"] for c in term["courses"]}
                chosen_slot = slots[0] if season == "SU" and slots else next((s for s in slots if s not in used), None)
                if chosen_slot is None:
                    continue
                term["courses"].append({
                    "course_id": cid,
                    "course_number": row["CourseNumber"],
                    "title": row["CourseTitle"],
                    "credits": credits,
                    "part_of_term": chosen_slot,
                    "part_of_term_label": PART_OF_TERM_LABELS.get(chosen_slot, chosen_slot),
                })
                term["total_credits"] += credits
                total_credits_so_far += credits
                taken.add(cid)

        if total_credits_so_far < target_credits:
            existing_terms = {t["term_code"] for t in plan_terms}
            for full_term in term_seq_post:
                if total_credits_so_far >= target_credits:
                    break
                if full_term in existing_terms:
                    continue
                season = full_term[:2]
                if not include_summer and season == "SU":
                    continue
                if full_term in break_terms_set:
                    continue
                new_courses, new_credits = [], 0
                for _, row in courses.iterrows():
                    if total_credits_so_far >= target_credits:
                        break
                    max_slots = 2 if season == "SU" else 3
                    if len(new_courses) >= max_slots:
                        break
                    cid = int(row["CourseID"])
                    if cid in taken:
                        continue
                    credits = int(row["DefaultCreditHours"])
                    offered = offerings[(offerings["CourseID"] == cid) & (offerings["TermCode"] == season)]
                    if offered.empty:
                        continue
                    needed = prereqs.loc[prereqs["CourseID"] == cid, "PrerequisiteCourseID"].tolist()
                    if not set(needed).issubset(taken):
                        continue
                    if season == "SU" and (len(new_courses) >= 2 or new_credits + credits > 6):
                        continue
                    slots = [str(s) for s in offered["PartOfTermCode"].dropna().unique()]
                    used = {c["part_of_term"] for c in new_courses}
                    chosen_slot = slots[0] if season == "SU" and slots else next((s for s in slots if s not in used), None)
                    if chosen_slot is None:
                        continue
                    new_courses.append({
                        "course_id": cid,
                        "course_number": row["CourseNumber"],
                        "title": row["CourseTitle"],
                        "credits": credits,
                        "part_of_term": chosen_slot,
                        "part_of_term_label": PART_OF_TERM_LABELS.get(chosen_slot, chosen_slot),
                    })
                    new_credits += credits
                    total_credits_so_far += credits
                    taken.add(cid)
                if new_courses:
                    plan_terms.append({"term_code": full_term, "total_credits": new_credits, "courses": new_courses})
                    plan_terms.sort(key=lambda t: term_seq_post.index(t["term_code"]))

    for break_term in break_terms_set:
        if break_term in term_seq_post:
            plan_terms.append({
                "term_code": break_term,
                "total_credits": 0,
                "courses": [],
                "is_break": True,
            })
    plan_terms.sort(key=lambda t: term_seq_post.index(t["term_code"]) if t["term_code"] in term_seq_post else 999)


    return {
        "program_code": program_code,
        "certificates": certs,
        "start_term_code": start_term_code,
        "half_time": half_time,
        "include_summer": include_summer,
        "break_terms": list(break_terms_set),
        "terms": plan_terms,
        "total_credits": total_credits_so_far,
    }


def enrich_plan_with_tuition(plan: Dict[str, Any], tuition_per_credit: int = TUITION_PER_CREDIT) -> Dict[str, Any]:
    """Adds tuition estimates to each course and computes term and plan totals."""
    total = 0
    for term in plan["terms"]:
        term_tuition = 0
        for c in term["courses"]:
            t = int(c["credits"]) * tuition_per_credit
            c["tuition"] = t
            term_tuition += t
        term["term_tuition"] = term_tuition
        total += term_tuition
    plan["tuition_per_credit"] = tuition_per_credit
    plan["total_tuition"] = total
    return plan


def plan_to_table_rows(plan: Dict[str, Any], tuition_per_credit: int = TUITION_PER_CREDIT) -> List[Dict[str, Any]]:
    """Flattens nested plan into a flat list of rows for the Streamlit table."""
    rows: List[Dict[str, Any]] = []
    for term in plan["terms"]:
        for c in term["courses"]:
            credits = int(c["credits"])
            rows.append({
                "term": term["term_code"],
                "course_number": c["course_number"],
                "course_title": c["title"],
                "credits": credits,
                "session": c.get("part_of_term_label", c["part_of_term"]),
                "tuition": credits * tuition_per_credit,
            })
    return rows


def summarize_plan(plan: Dict[str, Any], label: str = "") -> None:
    """Prints a human-readable plan summary to the terminal (for debugging)."""
    if label:
        print(f"\n===== {label} =====")
    print(f"Program: {plan['program_code']}, Certs: {plan['certificates']}, Total credits: {plan['total_credits']}")
    for term in plan["terms"]:
        courses = ", ".join(f"{c['course_number']} ({c.get('part_of_term_label', c['part_of_term'])})" for c in term["courses"])
        print(f"  - {term['term_code']}: {term['total_credits']} credits -> {courses}")

# %%