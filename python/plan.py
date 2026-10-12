"""Payment reminder rules engine (part 1).

Run from inside python/:

    python plan.py --invoices ../data/invoices.json --sent ../data/sent.json --today 2026-10-12 --out ../actions.json
"""

import argparse
import json
import math
import re
import sys
from collections import Counter
from datetime import date

from messages import build_message

# Steps from mildest to strongest, with the days overdue at which each is reached.
STEPS = ("friendly", "firm", "final")
DAYS_REACHED = {"friendly": 3, "firm": 10, "final": 24}
NEEDS_APPROVAL = {"friendly": False, "firm": True, "final": True}

_DATE_FORM = re.compile(r"\d{4}-\d{2}-\d{2}", re.ASCII)


class InputError(Exception):
    """The input files or the date argument cannot be used."""


def parse_date(value):
    """A real date in the exact form YYYY-MM-DD, or None."""
    if not isinstance(value, str) or not _DATE_FORM.fullmatch(value):
        return None
    try:
        return date(int(value[:4]), int(value[5:7]), int(value[8:]))
    except ValueError:  # e.g. 2026-02-30 or year 0000
        return None


def _valid_amount(amount):
    if isinstance(amount, bool) or not isinstance(amount, (int, float)):
        return False
    try:
        return math.isfinite(amount) and amount > 0
    except OverflowError:  # an int too large for float
        return amount > 0


def _skip_reason(invoice, duplicate_ids, today):
    """The first bad-data reason for this invoice, or None if the data is usable."""
    if invoice["id"] in duplicate_ids:
        return "duplicate_id"
    if not _valid_amount(invoice.get("amount")):
        return "invalid_amount"
    due = invoice.get("due_date")
    if due is None or due == "":
        return "missing_due_date"
    if parse_date(due) is None:
        return "invalid_due_date"
    paid = invoice.get("paid_date")
    if paid is not None:
        paid_on = parse_date(paid)
        if paid_on is None or paid_on > today:
            return "invalid_paid_date"
    return None


def _highest_sent_rank(sent, known_ids):
    """For each invoice id, the rank of the strongest step already sent."""
    ranks = {}
    for entry in sent:
        if not isinstance(entry, dict):
            continue
        invoice_id, step = entry.get("invoice_id"), entry.get("step")
        if invoice_id not in known_ids or step not in DAYS_REACHED:
            continue
        ranks[invoice_id] = max(ranks.get(invoice_id, -1), STEPS.index(step))
    return ranks


def evaluate(invoices, sent, today):
    """Apply the rules once. Returns (plan, quiet).

    plan is the required output (today, actions, skipped). quiet lists the invoices
    that are fine and need nothing today, each with the reason, for the page only.
    """
    today_date = parse_date(today)
    if today_date is None:
        raise InputError(f"today must be a real date as YYYY-MM-DD, got {today!r}")

    # An entry that is not an object with a text id cannot be named in the output.
    entries = [i for i in invoices if isinstance(i, dict) and isinstance(i.get("id"), str)]
    counts = Counter(i["id"] for i in entries)
    duplicate_ids = {invoice_id for invoice_id, n in counts.items() if n > 1}
    sent_ranks = _highest_sent_rank(sent, set(counts))

    actions, quiet = [], []
    skipped = [{"invoice_id": i, "reason": "duplicate_id"} for i in duplicate_ids]

    for invoice in entries:
        invoice_id = invoice["id"]
        if invoice_id in duplicate_ids:
            continue
        reason = _skip_reason(invoice, duplicate_ids, today_date)
        if reason:
            skipped.append({"invoice_id": invoice_id, "reason": reason})
            continue
        if invoice.get("paid_date") is not None:
            quiet.append({"invoice_id": invoice_id, "reason": "paid"})  # whatever was sent before
            continue

        days_overdue = (today_date - parse_date(invoice["due_date"])).days
        reached = [s for s in STEPS if days_overdue >= DAYS_REACHED[s]]
        if not reached:
            quiet.append({"invoice_id": invoice_id, "reason": "not_yet", "days_overdue": days_overdue})
            continue
        step = reached[-1]  # the highest step reached, one action at most
        if sent_ranks.get(invoice_id, -1) >= STEPS.index(step):
            quiet.append({"invoice_id": invoice_id, "reason": "already_sent",
                          "days_overdue": days_overdue, "step": STEPS[sent_ranks[invoice_id]]})
            continue

        actions.append(
            {
                "invoice_id": invoice_id,
                "step": step,
                "needs_approval": NEEDS_APPROVAL[step],
                "days_overdue": days_overdue,
                "message": build_message(
                    step,
                    invoice.get("customer", ""),
                    invoice_id,
                    invoice["due_date"],
                    invoice["amount"],
                    invoice.get("currency", ""),
                    days_overdue,
                ),
            }
        )

    for rows in (actions, skipped, quiet):
        rows.sort(key=lambda r: r["invoice_id"])
    return {"today": today, "actions": actions, "skipped": skipped}, quiet


def build_plan(invoices, sent, today):
    """Return the plan for `today` as a dict with the keys today, actions and skipped.

    invoices: the list from invoices.json
    sent: the list from sent.json
    today: a date string, YYYY-MM-DD
    """
    return evaluate(invoices, sent, today)[0]


def read_json_list(path, label):
    """Read a JSON file that must hold a list, or raise InputError with a clear message."""
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except OSError as e:
        raise InputError(f"cannot read {label} file {path}: {e.strerror or e}") from e
    except ValueError as e:  # bad JSON or bad UTF-8
        raise InputError(f"{label} file {path} is not valid JSON: {e}") from e
    if not isinstance(data, list):
        raise InputError(f"{label} file {path} must contain a JSON list")
    return data


def plan_from_files(invoices_path, sent_path, today):
    """Read both files and build the plan. Returns (plan, invoices, quiet)."""
    if parse_date(today) is None:
        raise InputError(f"--today must be a real date as YYYY-MM-DD, got {today!r}")
    invoices = read_json_list(invoices_path, "invoices")
    sent = read_json_list(sent_path, "sent")
    plan, quiet = evaluate(invoices, sent, today)
    return plan, invoices, quiet


def main():
    parser = argparse.ArgumentParser(description="Plan today's payment reminders.")
    parser.add_argument("--invoices", required=True, help="path to invoices.json")
    parser.add_argument("--sent", required=True, help="path to sent.json")
    parser.add_argument("--today", required=True, help="date as YYYY-MM-DD")
    parser.add_argument("--out", required=True, help="path to write the plan JSON")
    args = parser.parse_args()

    try:
        plan, _, _ = plan_from_files(args.invoices, args.sent, args.today)
        with open(args.out, "w", encoding="utf-8") as f:
            json.dump(plan, f, indent=2, ensure_ascii=False)
            f.write("\n")
    except InputError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    except OSError as e:
        print(f"error: cannot write {args.out}: {e.strerror or e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
