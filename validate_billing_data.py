"""
FACTS Incidental Billing -- Validation Pipeline
================================================

Takes the raw monthly charges file an office would hand you and turns it into:
  1. facts_ready_import.csv -- clean, billable rows, normalized and ready to map
                               onto the school's real FACTS import template
  2. exception_report.csv   -- the audit trail: every row we touched, what was
                               wrong, what we did about it, and its severity

It then SCORES itself against error_manifest.csv (if present): did it catch
exactly the planted errors? That self-check is the proof the tool works.

Two dispositions
----------------
  * billed (auto-corrected)  -- we fixed it safely and it can be billed:
        date formats normalized, names trimmed, currency symbols stripped,
        duplicate lines removed.
  * held (needs office)      -- we will NOT bill it until a human resolves it:
        missing/implausible amounts, unknown or mismatched codes, charges for
        families not on the roster, charges for withdrawn families.

That split is the whole pitch: the safe stuff flows through untouched, and the
risky stuff is stopped *before* a family gets a wrong bill -- with a logged
reason for the annual audit.

Usage
-----
Set INPUT_DIR to wherever your CSVs live (e.g. your Current Files folder), then:
    python validate_billing_data.py

Dependencies: pandas. Standard library otherwise.
"""

from datetime import datetime
from pathlib import Path

import pandas as pd

# ---------------------------------------------------------------------------
# CONFIG
# ---------------------------------------------------------------------------
CONFIG = {
    # Point these at your files. On Windows you can use a raw string, e.g.:
    #   r"C:\Users\you\Documents\billing"
    "input_dir": "output",
    "output_dir": "output",
    "amount_tolerance": 0.01,   # float wiggle room for range checks
}

# Canonical fee schedule -- the source of truth for valid codes, descriptions,
# and plausible amount ranges. Keep this in sync with the generator's schedule.
FEE_SCHEDULE = {
    "LUNCH":     ("Hot Lunch",         40.00,  90.00),
    "AFTERCARE": ("Extended Day Care", 60.00, 220.00),
    "FIELDTRIP": ("Field Trip",        10.00,  45.00),
    "CLASSFEE":  ("Classroom Fee",     25.00,  75.00),
    "TECHFEE":   ("Technology Fee",    30.00, 100.00),
    "ATHLETIC":  ("Athletics Fee",     50.00, 150.00),
}
VALID_CODES = set(FEE_SCHEDULE)

# Date formats we'll accept and normalize to ISO. Anything else is unparseable.
DATE_FORMATS = ["%Y-%m-%d", "%m/%d/%Y", "%m-%d-%Y", "%m-%d-%y",
                "%B %d, %Y", "%b %d %Y", "%b %d, %Y"]

SEVERITY = {
    "missing_amount": "medium", "bad_date_format": "low", "duplicate_family": "high",
    "duplicate_charge": "high", "miscoded_fee": "medium", "withdrawn_student_charge": "high",
    "orphan_charge": "high", "bad_amount": "high", "messy_text": "low",
    "currency_format": "low",
}


def parse_amount(raw):
    """Return (value, note). value is float or None; note flags how it was handled."""
    s = str(raw).strip()
    if s == "" or s.lower() == "nan":
        return None, "missing"
    note = "ok"
    if s.startswith("$"):
        s = s[1:].strip()
        note = "currency_symbol_stripped"
    try:
        return float(s), note
    except ValueError:
        return None, "unparseable"


def parse_date(raw):
    """Return (iso_string, was_reformatted) or (None, _) if impossible."""
    s = str(raw).strip()
    for fmt in DATE_FORMATS:
        try:
            dt = datetime.strptime(s, fmt)
            iso = dt.date().isoformat()
            return iso, (iso != s)
        except ValueError:
            continue
    return None, True


def run(cfg):
    inp, out = Path(cfg["input_dir"]), Path(cfg["output_dir"])
    out.mkdir(parents=True, exist_ok=True)
    tol = cfg["amount_tolerance"]

    families = pd.read_csv(inp / "families.csv", dtype=str, keep_default_na=False)
    charges = pd.read_csv(inp / "charges_dirty.csv", dtype=str, keep_default_na=False)

    audit = []  # every finding -> the exception report / audit trail
    def flag(ref, table, issue, disposition, detail, action):
        audit.append({
            "ref_id": ref, "table": table, "issue_type": issue,
            "severity": SEVERITY.get(issue, "medium"), "disposition": disposition,
            "detail": detail, "action": action,
        })

    # --- Roster: de-duplicate and index for lookups -------------------------
    dup_fams = families[families.duplicated("family_id", keep="first")]
    for fid in dup_fams.family_id.unique():
        flag(fid, "families", "duplicate_family", "billed (auto-corrected)",
             "Family listed more than once in roster.", "Removed duplicate roster row.")
    families = families.drop_duplicates("family_id", keep="first")
    roster = families.set_index("family_id")["enrollment_status"].to_dict()

    # --- Charges: drop duplicate lines first --------------------------------
    dup_charges = charges[charges.duplicated("charge_id", keep="first")]
    for cid in dup_charges.charge_id.unique():
        flag(cid, "charges", "duplicate_charge", "billed (auto-corrected)",
             "Identical charge_id billed more than once.", "Dropped extra copy; kept one.")
    charges = charges.drop_duplicates("charge_id", keep="first")

    # --- Row-by-row validation ---------------------------------------------
    billable = []
    held_ids = set()

    for r in charges.itertuples(index=False):
        cid, fam, code = r.charge_id, r.family_id, r.charge_code
        held = False

        # Roster membership (must come before enrollment check)
        if fam not in roster:
            flag(cid, "charges", "orphan_charge", "held (needs office)",
                 f"family_id {fam} is not on the roster.", "Excluded from billing.")
            held = True
        elif roster[fam] != "Active":
            flag(cid, "charges", "withdrawn_student_charge", "held (needs office)",
                 f"family_id {fam} is {roster[fam]}.", "Excluded; do not bill inactive family.")
            held = True

        # Charge code: known? description consistent?
        if code not in VALID_CODES:
            flag(cid, "charges", "miscoded_fee", "held (needs office)",
                 f"Code '{code}' is not in the fee schedule.", "Excluded; office to assign valid code.")
            held = True
        else:
            canon_desc, lo, hi = FEE_SCHEDULE[code]
            if str(r.charge_description).strip().lower() != canon_desc.lower():
                flag(cid, "charges", "miscoded_fee", "held (needs office)",
                     f"Code '{code}' but description '{r.charge_description}'.",
                     "Excluded; code/description mismatch.")
                held = True

        # Amount
        amt, anote = parse_amount(r.amount)
        if anote == "missing":
            flag(cid, "charges", "missing_amount", "held (needs office)",
                 "Amount is blank.", "Excluded; office to supply amount.")
            held = True
        elif anote == "unparseable":
            flag(cid, "charges", "bad_amount", "held (needs office)",
                 f"Amount '{r.amount}' is not a number.", "Excluded.")
            held = True
        else:
            if anote == "currency_symbol_stripped":
                flag(cid, "charges", "currency_format", "billed (auto-corrected)",
                     f"Amount arrived as '{r.amount}'.", "Stripped '$' and parsed.")
            if amt <= 0:
                flag(cid, "charges", "bad_amount", "held (needs office)",
                     f"Non-positive amount {amt:.2f}.", "Excluded; cannot bill <= $0.")
                held = True
            elif code in VALID_CODES:
                _, lo, hi = FEE_SCHEDULE[code]
                if amt < lo - tol or amt > hi + tol:
                    flag(cid, "charges", "bad_amount", "held (needs office)",
                         f"{amt:.2f} is outside the {code} range ${lo:.0f}-${hi:.0f}.",
                         "Excluded as likely entry error.")
                    held = True

        # Date
        iso, reformatted = parse_date(r.charge_date)
        if iso is None:
            flag(cid, "charges", "bad_date_format", "held (needs office)",
                 f"Date '{r.charge_date}' is invalid.", "Excluded; office to correct date.")
            held = True
        elif reformatted:
            flag(cid, "charges", "bad_date_format", "billed (auto-corrected)",
                 f"Date arrived as '{r.charge_date}'.", f"Normalized to {iso}.")

        # Name hygiene
        name = str(r.student_name)
        clean_name = " ".join(name.split()).title()
        if clean_name != name:
            flag(cid, "charges", "messy_text", "billed (auto-corrected)",
                 f"Name arrived as '{name}'.", f"Standardized to '{clean_name}'.")

        if held:
            held_ids.add(cid)
            continue

        # Survived all checks -> billable, normalized
        canon_desc = FEE_SCHEDULE[code][0]
        billable.append({
            "family_id": fam, "student_id": r.student_id, "student_name": clean_name,
            "grade": r.grade, "charge_code": code, "charge_description": canon_desc,
            "charge_date": iso, "amount": round(amt, 2),
        })

    billable_df = pd.DataFrame(billable)
    audit_df = pd.DataFrame(audit)

    # --- Write outputs ------------------------------------------------------
    # NOTE: column names here are a sensible normalized intermediate. Once you
    # have the school's real FACTS incidental-billing import template, map these
    # columns onto it -- that's the only school-specific change needed.
    billable_df.to_csv(out / "facts_ready_import.csv", index=False, lineterminator="\n")
    audit_df.to_csv(out / "exception_report.csv", index=False, lineterminator="\n")

    # --- Reconciliation summary --------------------------------------------
    total_in = len(charges) + len(dup_charges)
    held_total = (billable_df.shape[0], audit_df.query("disposition.str.startswith('held')",
                  engine="python").shape[0]) if not audit_df.empty else (0, 0)
    billed_dollars = billable_df["amount"].sum() if not billable_df.empty else 0.0
    print(f"\nRECONCILIATION  --  input: {inp.resolve()}")
    print("-" * 60)
    print(f"Charge rows received:            {total_in}")
    print(f"  duplicate lines removed:       {len(dup_charges)}")
    print(f"  billable (clean + fixed):      {len(billable_df)}")
    print(f"  held for office review:        {len(held_ids)}")
    print(f"Billable total:                  ${billed_dollars:,.2f}")
    if not audit_df.empty:
        print("\nFindings by disposition:")
        for d, n in audit_df.disposition.value_counts().items():
            print(f"   {d:28s} {n}")
        print("\nFindings by severity:")
        for s, n in audit_df.severity.value_counts().items():
            print(f"   {s:28s} {n}")

    # --- Self-scoring against the manifest ---------------------------------
    man_path = inp / "error_manifest.csv"
    if man_path.exists():
        manifest = pd.read_csv(man_path, dtype=str, keep_default_na=False)
        detected = {}
        for a in audit:
            detected.setdefault(a["ref_id"], set()).add(a["issue_type"])

        caught, missed = 0, []
        for m in manifest.itertuples(index=False):
            if m.issue_type in detected.get(m.ref_id, set()):
                caught += 1
            else:
                missed.append((m.ref_id, m.issue_type))

        manifest_refs = set(manifest.ref_id)
        held_refs = {a["ref_id"] for a in audit if a["disposition"].startswith("held")}
        # A TRUE false positive = a row we HELD (blocked from billing) that was
        # not actually planted as an error. Benign auto-corrections logged for
        # the audit trail (e.g. stripping a '$') are not accusations, so they
        # don't count against the tool.
        false_pos = sorted(held_refs - manifest_refs)
        benign_extra = sorted(r for r in detected
                              if r not in manifest_refs and r not in held_refs)

        print("\nSCORECARD  --  vs error_manifest.csv")
        print("-" * 60)
        print(f"Planted errors:        {len(manifest)}")
        print(f"Caught:                {caught}")
        print(f"Missed:                {len(missed)}")
        for ref, issue in missed:
            print(f"   MISS  {ref}  {issue}")
        print(f"False positives:       {len(false_pos)}  (wrongly blocked from billing)")
        for r in false_pos:
            print(f"   FP    {r}  {detected[r]}")
        if benign_extra:
            print(f"Benign cleanups logged: {len(benign_extra)}  (cosmetic, still billed)")
        verdict = "PASS" if not missed and not false_pos else "REVIEW"
        print(f"\nResult: {verdict}")

    print(f"\nWrote facts_ready_import.csv and exception_report.csv to {out.resolve()}")
    return billable_df, audit_df


if __name__ == "__main__":
    run(CONFIG)
