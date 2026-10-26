"""
FACTS Incidental Billing -- Synthetic Data Generator
=====================================================

Purpose
-------
Produces a realistic, *fake* dataset that mirrors what a K-6 Catholic
elementary school's monthly incidental-billing prep looks like -- and
deliberately seeds it with the kinds of messes a real office produces.

It writes four files:
  1. families.csv        -- the family/student roster
  2. charges_dirty.csv   -- the raw monthly charges, errors and all (your INPUT)
  3. charges_clean.csv   -- the same data done right (the ANSWER KEY)
  4. error_manifest.csv  -- exactly which rows are wrong and why (your TEST ORACLE)

Why a clean answer key + manifest?
----------------------------------
When you build the validation pipeline, you can prove it catches *exactly*
the errors that were planted -- no more, no fewer. That's the difference
between "I wrote a script" and "I can demonstrate it works."

Template engine
---------------
Everything is driven by CONFIG. Change `school_name` + `seed` and run again
to stamp out a second, different fake school. That's the diocese-replicable
build: school #2 is a config change, not a rewrite.

Dependencies: pandas (you have it). Standard library otherwise.
"""

import random
import copy
from datetime import date, timedelta
from pathlib import Path

import pandas as pd

# ---------------------------------------------------------------------------
# CONFIG -- change this block to generate a different school
# ---------------------------------------------------------------------------
CONFIG = {
    "school_name": "Example Catholic School",
    "num_families": 150,
    "billing_month": "2026-03",      # the month being billed (YYYY-MM)
    "seed": 42,                       # change this to get a different school
    "output_dir": "output",
    # how many of each deliberate mess to inject into the dirty file
    "errors": {
        "missing_amount": 4,          # blank amount -- can't bill it
        "bad_date_format": 6,         # mixed/invalid date strings
        "duplicate_family": 1,        # same family listed twice in roster
        "duplicate_charge": 2,        # same charge billed twice
        "miscoded_fee": 3,            # invalid code or code/description mismatch
        "withdrawn_student_charge": 2,# charge on a student who already left
        "orphan_charge": 2,           # charge for a family that isn't on the roster
        "bad_amount": 3,              # negative, zero, or wild fat-finger value
        "messy_text": 4,              # trailing spaces / inconsistent casing
    },
}

# Fee schedule: code -> (description, min_amount, max_amount)
FEE_SCHEDULE = {
    "LUNCH":     ("Hot Lunch",         40.00,  90.00),
    "AFTERCARE": ("Extended Day Care", 60.00, 220.00),
    "FIELDTRIP": ("Field Trip",        10.00,  45.00),
    "CLASSFEE":  ("Classroom Fee",     25.00,  75.00),
    "TECHFEE":   ("Technology Fee",    30.00, 100.00),
    "ATHLETIC":  ("Athletics Fee",     50.00, 150.00),
}
VALID_CODES = set(FEE_SCHEDULE)

# Probability a given active student incurs each charge type this month
CHARGE_PROBABILITY = {
    "LUNCH":     0.85,
    "AFTERCARE": 0.40,
    "FIELDTRIP": 0.25,
    "CLASSFEE":  0.15,
    "TECHFEE":   0.10,
    "ATHLETIC":  0.30,   # only applied to grades 5-8 (see build_charges)
}

FIRST_NAMES = [
    "Liam", "Olivia", "Noah", "Emma", "Mateo", "Sophia", "Lucas", "Isabella",
    "Elijah", "Ava", "James", "Mia", "Benjamin", "Amelia", "Henry", "Harper",
    "Sebastian", "Evelyn", "Jack", "Luna", "Owen", "Ella", "Daniel", "Gianna",
    "Michael", "Aria", "Joseph", "Nora", "Samuel", "Lily", "David", "Hazel",
    "Wyatt", "Aurora", "Carter", "Chloe", "Julian", "Penelope", "Levi", "Layla",
]
LAST_NAMES = [
    "Nguyen", "Garcia", "Martinez", "Rodriguez", "Hernandez", "Lopez", "Gonzalez",
    "Wilson", "Anderson", "Thomas", "Taylor", "Moore", "Jackson", "Martin", "Lee",
    "Perez", "Thompson", "White", "Harris", "Sanchez", "Clark", "Ramirez", "Lewis",
    "Robinson", "Walker", "Young", "Allen", "King", "Wright", "Scott", "Torres",
    "Hill", "Flores", "Green", "Adams", "Nelson", "Baker", "Rivera", "Campbell",
    "Mitchell", "Carter", "Roberts", "Murphy", "Kelly", "Cook", "Bailey", "Reed",
]
GRADES = ["K", "1", "2", "3", "4", "5", "6"]


def _money(lo, hi):
    """Random dollar amount in a range, rounded to the nearest quarter (realistic)."""
    raw = random.uniform(lo, hi)
    return round(raw * 4) / 4


def build_families(cfg):
    """Build the roster. A handful of families are 'Withdrawn' on purpose --
    they should NOT receive charges, which is one of the things validation checks."""
    families, students = [], []
    fam_seq = stu_seq = 1
    for _ in range(cfg["num_families"]):
        fam_id = f"FAM-{fam_seq:04d}"
        last = random.choice(LAST_NAMES)
        # ~4% of families have withdrawn mid-year
        status = "Withdrawn" if random.random() < 0.04 else "Active"
        n_kids = random.choices([1, 2, 3], weights=[55, 35, 10])[0]
        families.append({
            "family_id": fam_id,
            "family_last_name": last,
            "primary_contact": f"{random.choice(FIRST_NAMES)} {last}",
            "enrollment_status": status,
            "num_students": n_kids,
        })
        for _ in range(n_kids):
            students.append({
                "student_id": f"STU-{stu_seq:05d}",
                "family_id": fam_id,
                "first_name": random.choice(FIRST_NAMES),
                "last_name": last,
                "grade": random.choice(GRADES),
            })
            stu_seq += 1
        fam_seq += 1
    return pd.DataFrame(families), pd.DataFrame(students)


def build_charges(cfg, students_df, families_df):
    """Build one clean month of incidental charges for ACTIVE families only."""
    active = set(families_df.loc[families_df.enrollment_status == "Active", "family_id"])
    month = cfg["billing_month"]
    year, mon = int(month[:4]), int(month[5:7])
    rows = []
    seq = 1
    for s in students_df.itertuples(index=False):
        if s.family_id not in active:
            continue
        for code, prob in CHARGE_PROBABILITY.items():
            if code == "ATHLETIC" and s.grade in ("K", "1", "2", "3", "4"):
                continue  # athletics only for the older grades
            if random.random() > prob:
                continue
            desc, lo, hi = FEE_SCHEDULE[code]
            day = random.randint(1, 28)
            rows.append({
                "charge_id": f"CHG-{seq:06d}",
                "family_id": s.family_id,
                "student_id": s.student_id,
                "student_name": f"{s.first_name} {s.last_name}",
                "grade": s.grade,
                "charge_code": code,
                "charge_description": desc,
                "charge_date": date(year, mon, day).isoformat(),  # clean = ISO
                "amount": _money(lo, hi),
            })
            seq += 1
    return pd.DataFrame(rows)


def inject_errors(cfg, charges_clean, families_clean, students_df):
    """Return (charges_dirty, families_dirty, manifest). Every mess is logged."""
    charges = charges_clean.copy()
    # Amounts in the raw file arrive as strings -- that's how exports actually look.
    charges["amount"] = charges["amount"].map(lambda v: f"{v:.2f}")
    families = families_clean.copy()
    manifest = []
    used = set()  # charge row-indices already mutated, so errors don't collide

    def pick(n):
        avail = [i for i in charges.index if i not in used]
        chosen = random.sample(avail, min(n, len(avail)))
        used.update(chosen)
        return chosen

    def log(table, ref, issue, severity, desc, fix):
        manifest.append({
            "table": table, "ref_id": ref, "issue_type": issue,
            "severity": severity, "description": desc, "expected_fix": fix,
        })

    e = cfg["errors"]

    # 1. Missing amount -- nothing to bill
    for i in pick(e["missing_amount"]):
        charges.at[i, "amount"] = ""
        log("charges", charges.at[i, "charge_id"], "missing_amount", "medium",
            "Amount is blank.", "Flag for the office to supply the amount; do not bill.")

    # 2. Bad / mixed date formats (one is a genuinely invalid date)
    bad_dates = ["03/05/2026", "March 5, 2026", "3-5-26", "03/14/2026",
                 "Mar 22 2026", "2026-13-05"]  # last one is impossible
    for k, i in enumerate(pick(e["bad_date_format"])):
        val = bad_dates[k % len(bad_dates)]
        charges.at[i, "charge_date"] = val
        sev = "high" if val == "2026-13-05" else "low"
        log("charges", charges.at[i, "charge_id"], "bad_date_format", sev,
            f"Non-standard date string: '{val}'.",
            "Normalize to ISO; reject impossible dates.")

    # 3. Duplicate family in the roster
    for _ in range(e["duplicate_family"]):
        dup = families.sample(1, random_state=cfg["seed"]).iloc[0].to_dict()
        families = pd.concat([families, pd.DataFrame([dup])], ignore_index=True)
        log("families", dup["family_id"], "duplicate_family", "high",
            "Family appears more than once in the roster.",
            "De-duplicate on family_id.")

    # 4. Duplicate charge -- same line billed twice
    for i in pick(e["duplicate_charge"]):
        dup = charges.loc[i].to_dict()
        charges = pd.concat([charges, pd.DataFrame([dup])], ignore_index=True)
        log("charges", dup["charge_id"], "duplicate_charge", "high",
            "Identical charge_id appears twice -- family billed double.",
            "Drop exact duplicates on charge_id.")

    # 5. Miscoded fee -- invalid code OR code/description mismatch
    miscoded = pick(e["miscoded_fee"])
    for k, i in enumerate(miscoded):
        if k % 2 == 0:
            charges.at[i, "charge_code"] = "MISC99"  # not a real code
            log("charges", charges.at[i, "charge_id"], "miscoded_fee", "medium",
                "Charge code 'MISC99' is not in the fee schedule.",
                "Reject unknown codes; route to office for correct code.")
        else:
            charges.at[i, "charge_code"] = "LUNCH"
            charges.at[i, "charge_description"] = "Athletics Fee"  # mismatch
            log("charges", charges.at[i, "charge_id"], "miscoded_fee", "medium",
                "Code 'LUNCH' does not match description 'Athletics Fee'.",
                "Flag code/description mismatch for review.")

    # 6. Charge on a withdrawn student
    withdrawn_fams = families_clean.loc[
        families_clean.enrollment_status == "Withdrawn", "family_id"].tolist()
    for n in range(e["withdrawn_student_charge"]):
        if not withdrawn_fams:
            break
        fam = withdrawn_fams[n % len(withdrawn_fams)]
        kid = students_df.loc[students_df.family_id == fam]
        if kid.empty:
            continue
        kid = kid.iloc[0]
        cid = f"CHG-W{n:05d}"
        desc, lo, hi = FEE_SCHEDULE["AFTERCARE"]
        charges = pd.concat([charges, pd.DataFrame([{
            "charge_id": cid, "family_id": fam, "student_id": kid.student_id,
            "student_name": f"{kid.first_name} {kid.last_name}", "grade": kid.grade,
            "charge_code": "AFTERCARE", "charge_description": desc,
            "charge_date": f"{cfg['billing_month']}-10", "amount": f"{_money(lo, hi):.2f}",
        }])], ignore_index=True)
        log("charges", cid, "withdrawn_student_charge", "high",
            f"Charge for a student in withdrawn family {fam}.",
            "Suppress charges for non-active families.")

    # 7. Orphan charge -- references a family/student not on the roster
    for n in range(e["orphan_charge"]):
        cid = f"CHG-O{n:05d}"
        desc, lo, hi = FEE_SCHEDULE["FIELDTRIP"]
        charges = pd.concat([charges, pd.DataFrame([{
            "charge_id": cid, "family_id": f"FAM-9{n:03d}", "student_id": f"STU-9{n:04d}",
            "student_name": "Unknown Student", "grade": "5",
            "charge_code": "FIELDTRIP", "charge_description": desc,
            "charge_date": f"{cfg['billing_month']}-18", "amount": f"{_money(lo, hi):.2f}",
        }])], ignore_index=True)
        log("charges", cid, "orphan_charge", "high",
            "Charge references a family_id that isn't on the roster.",
            "Reject; cannot bill an unknown family.")

    # 8. Bad amounts -- negative, zero, fat-finger
    bad_vals = ["-25.00", "0.00", "4500.00"]
    for k, i in enumerate(pick(e["bad_amount"])):
        v = bad_vals[k % len(bad_vals)]
        charges.at[i, "amount"] = v
        log("charges", charges.at[i, "charge_id"], "bad_amount", "high",
            f"Implausible amount '{v}'.",
            "Flag negatives/zeros and outliers outside the fee range.")

    # 9. Messy text -- whitespace + casing in names (breaks naive joins/dedup)
    for i in pick(e["messy_text"]):
        name = charges.at[i, "student_name"]
        charges.at[i, "student_name"] = f"  {name.upper()} "
        log("charges", charges.at[i, "charge_id"], "messy_text", "low",
            "Student name has stray whitespace / inconsistent casing.",
            "Trim and standardize casing before matching.")

    # A little real-world formatting noise: a couple of amounts arrive with a $.
    for i in random.sample(list(charges.index), 2):
        if charges.at[i, "amount"] and not charges.at[i, "amount"].startswith("-"):
            charges.at[i, "amount"] = "$" + charges.at[i, "amount"]

    return charges, families, pd.DataFrame(manifest)


def generate(cfg):
    random.seed(cfg["seed"])
    out = Path(cfg["output_dir"])
    out.mkdir(parents=True, exist_ok=True)

    families_clean, students = build_families(cfg)
    charges_clean = build_charges(cfg, students, families_clean)
    charges_dirty, families_dirty, manifest = inject_errors(
        cfg, charges_clean, families_clean, students)

    # Roster handed to you = families with the duplicate baked in
    families_dirty.to_csv(out / "families.csv", index=False, lineterminator="\n")
    charges_dirty.to_csv(out / "charges_dirty.csv", index=False, lineterminator="\n")
    charges_clean.to_csv(out / "charges_clean.csv", index=False, lineterminator="\n")
    manifest.to_csv(out / "error_manifest.csv", index=False, lineterminator="\n")

    # Summary
    print(f"\n{cfg['school_name']}  --  billing {cfg['billing_month']}")
    print("-" * 56)
    print(f"Families (roster, incl. injected dup): {len(families_dirty)}")
    print(f"Students:                              {len(students)}")
    print(f"Clean charges (answer key):            {len(charges_clean)}")
    print(f"Dirty charges (your input):            {len(charges_dirty)}")
    print(f"Seeded errors logged in manifest:      {len(manifest)}")
    print("\nErrors by type:")
    for t, n in manifest.issue_type.value_counts().items():
        print(f"   {t:28s} {n}")
    print(f"\nWritten to: {out.resolve()}")
    return families_dirty, charges_dirty, charges_clean, manifest


if __name__ == "__main__":
    generate(CONFIG)

    # ---- Template engine: uncomment to stamp out a second school ----
    # school_b = dict(CONFIG)
    # school_b.update(school_name="Example Academy", seed=7,
    #                 num_families=90, output_dir="output_school_b")
    # generate(school_b)
