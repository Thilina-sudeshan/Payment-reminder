"""Run from inside python/:  python -m unittest"""

import json
import os
import subprocess
import sys
import tempfile
import unittest
from datetime import date, timedelta

from plan import build_plan

PYTHON_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TODAY = "2026-10-12"


def invoice(id="INV-1", days_overdue=0, **overrides):
    due = date.fromisoformat(TODAY) - timedelta(days=days_overdue)
    data = {
        "id": id,
        "customer": "Example Ltd",
        "email": "accounts@example.test",
        "amount": 100.0,
        "currency": "EUR",
        "due_date": due.isoformat(),
        "paid_date": None,
    }
    data.update(overrides)
    return data


def sent(id="INV-1", step="friendly"):
    return {"invoice_id": id, "step": step, "sent_on": "2026-10-01"}


def plan_for(invoices, sent_list=(), today=TODAY):
    return build_plan(list(invoices), list(sent_list), today)


def steps_of(plan):
    return [(a["invoice_id"], a["step"]) for a in plan["actions"]]


class ShapeTest(unittest.TestCase):
    def test_empty_input_gives_empty_plan(self):
        self.assertEqual(plan_for([]), {"today": TODAY, "actions": [], "skipped": []})

    def test_action_has_exactly_the_required_keys(self):
        action = plan_for([invoice(days_overdue=12)])["actions"][0]
        self.assertEqual(
            set(action),
            {"invoice_id", "step", "needs_approval", "days_overdue", "message"},
        )


class StepThresholdTest(unittest.TestCase):
    def test_thresholds(self):
        cases = [
            (-5, None), (0, None), (2, None),
            (3, "friendly"), (9, "friendly"),
            (10, "firm"), (23, "firm"),
            (24, "final"), (400, "final"),
        ]
        for days, expected in cases:
            with self.subTest(days=days):
                got = steps_of(plan_for([invoice(days_overdue=days)]))
                self.assertEqual(got, [("INV-1", expected)] if expected else [])

    def test_needs_approval(self):
        for days, approval in [(3, False), (10, True), (24, True)]:
            with self.subTest(days=days):
                action = plan_for([invoice(days_overdue=days)])["actions"][0]
                self.assertIs(action["needs_approval"], approval)

    def test_days_overdue_is_calendar_days(self):
        action = plan_for([invoice(days_overdue=12)])["actions"][0]
        self.assertEqual(action["days_overdue"], 12)

    def test_calendar_days_across_month_and_leap_day(self):
        inv = invoice(due_date="2028-02-27")  # 2028 is a leap year
        action = plan_for([inv], today="2028-03-02")["actions"][0]
        self.assertEqual(action["days_overdue"], 4)


class OneActionTest(unittest.TestCase):
    def test_only_highest_step_is_planned(self):
        plan = plan_for([invoice(days_overdue=12)])
        self.assertEqual(steps_of(plan), [("INV-1", "firm")])

    def test_same_step_already_sent(self):
        self.assertEqual(plan_for([invoice(days_overdue=5)], [sent(step="friendly")])["actions"], [])

    def test_higher_step_already_sent(self):
        self.assertEqual(plan_for([invoice(days_overdue=5)], [sent(step="final")])["actions"], [])

    def test_lower_step_sent_still_plans_higher(self):
        plan = plan_for([invoice(days_overdue=12)], [sent(step="friendly")])
        self.assertEqual(steps_of(plan), [("INV-1", "firm")])

    def test_firm_sent_at_final_stage_plans_final(self):
        plan = plan_for([invoice(days_overdue=30)], [sent(step="firm")])
        self.assertEqual(steps_of(plan), [("INV-1", "final")])

    def test_sent_order_in_file_does_not_matter(self):
        sent_list = [sent(step="final"), sent(step="friendly")]
        self.assertEqual(plan_for([invoice(days_overdue=30)], sent_list)["actions"], [])

    def test_sent_for_unknown_invoice_is_ignored(self):
        plan = plan_for([invoice(days_overdue=5)], [sent(id="INV-404", step="final")])
        self.assertEqual(steps_of(plan), [("INV-1", "friendly")])

    def test_sent_with_unknown_step_is_ignored(self):
        plan = plan_for([invoice(days_overdue=5)], [sent(step="urgent"), sent(step=None)])
        self.assertEqual(steps_of(plan), [("INV-1", "friendly")])

    def test_malformed_sent_entries_are_ignored(self):
        plan = plan_for([invoice(days_overdue=5)], ["x", None, 3, {}, {"step": "final"}])
        self.assertEqual(steps_of(plan), [("INV-1", "friendly")])

    def test_sent_on_is_not_used(self):
        for sent_on in (None, "garbage", "2099-01-01"):
            entry = {"invoice_id": "INV-1", "step": "friendly", "sent_on": sent_on}
            self.assertEqual(plan_for([invoice(days_overdue=5)], [entry])["actions"], [])


class PaidTest(unittest.TestCase):
    def test_paid_plans_nothing(self):
        inv = invoice(days_overdue=30, paid_date="2026-10-05")
        self.assertEqual(plan_for([inv], [sent(step="friendly")]), {"today": TODAY, "actions": [], "skipped": []})

    def test_paid_today_is_paid(self):
        self.assertEqual(plan_for([invoice(days_overdue=30, paid_date=TODAY)])["actions"], [])

    def test_missing_paid_date_is_unpaid(self):
        inv = invoice(days_overdue=5)
        del inv["paid_date"]
        self.assertEqual(steps_of(plan_for([inv])), [("INV-1", "friendly")])

    def test_paid_before_due_date_is_paid(self):
        inv = invoice(days_overdue=30, paid_date="2026-01-01")
        self.assertEqual(plan_for([inv])["actions"], [])


class BadDataTest(unittest.TestCase):
    def reasons(self, *invoices):
        return {s["invoice_id"]: s["reason"] for s in plan_for(invoices)["skipped"]}

    def test_invalid_amount(self):
        for bad in (None, "100", "abc", True, False, 0, -5, 0.0, [], {}, float("nan"), float("inf")):
            with self.subTest(amount=bad):
                self.assertEqual(self.reasons(invoice(amount=bad, days_overdue=30)), {"INV-1": "invalid_amount"})

    def test_missing_amount_key(self):
        inv = invoice(days_overdue=30)
        del inv["amount"]
        self.assertEqual(self.reasons(inv), {"INV-1": "invalid_amount"})

    def test_valid_amounts(self):
        for good in (1, 0.01, 99999999999999999999):
            with self.subTest(amount=good):
                self.assertEqual(steps_of(plan_for([invoice(amount=good, days_overdue=5)])), [("INV-1", "friendly")])

    def test_missing_due_date(self):
        for value in (None, ""):
            with self.subTest(due=value):
                self.assertEqual(self.reasons(invoice(due_date=value)), {"INV-1": "missing_due_date"})
        inv = invoice()
        del inv["due_date"]
        self.assertEqual(self.reasons(inv), {"INV-1": "missing_due_date"})

    def test_invalid_due_date(self):
        bad_dates = ["2026-02-30", "30/09/2026", "2026-13-01", "2026-9-30", "20260930",
                     " 2026-09-30", "2026-09-30 ", "2026-09-30\n", "2026-09-30T00:00:00",
                     "abc", "0000-01-01", "٢٠٢٦-٠٩-٣٠", 20260930, True, [], "2025-02-29"]
        for bad in bad_dates:
            with self.subTest(due=bad):
                self.assertEqual(self.reasons(invoice(due_date=bad)), {"INV-1": "invalid_due_date"})

    def test_leap_day_is_valid(self):
        self.assertEqual(self.reasons(invoice(due_date="2024-02-29")), {})

    def test_invalid_paid_date(self):
        for bad in ("", "2026-02-30", "05/10/2026", "yes", 0, False, "2026-10-13", "2999-01-01"):
            with self.subTest(paid=bad):
                self.assertEqual(self.reasons(invoice(paid_date=bad)), {"INV-1": "invalid_paid_date"})

    def test_paid_on_today_is_valid(self):
        self.assertEqual(self.reasons(invoice(paid_date=TODAY)), {})

    def test_duplicate_id_listed_once_and_all_skipped(self):
        invoices = [invoice("INV-2", 30), invoice("INV-2", 12), invoice("INV-2", 5), invoice("INV-3", 5)]
        plan = plan_for(invoices)
        self.assertEqual(plan["skipped"], [{"invoice_id": "INV-2", "reason": "duplicate_id"}])
        self.assertEqual(steps_of(plan), [("INV-3", "friendly")])

    def test_duplicate_wins_over_other_reasons(self):
        invoices = [invoice("INV-2", amount=-1), invoice("INV-2", due_date="nope")]
        self.assertEqual(plan_for(invoices)["skipped"], [{"invoice_id": "INV-2", "reason": "duplicate_id"}])

    def test_duplicate_even_when_both_paid(self):
        invoices = [invoice("INV-2", paid_date="2026-10-01"), invoice("INV-2", paid_date="2026-10-02")]
        self.assertEqual(plan_for(invoices)["skipped"], [{"invoice_id": "INV-2", "reason": "duplicate_id"}])

    def test_ids_are_case_sensitive(self):
        self.assertEqual(plan_for([invoice("inv-1", 5), invoice("INV-1", 5)])["skipped"], [])

    def test_first_reason_wins(self):
        self.assertEqual(self.reasons(invoice(amount=0, due_date=None, paid_date="bad")), {"INV-1": "invalid_amount"})
        self.assertEqual(self.reasons(invoice(due_date=None, paid_date="bad")), {"INV-1": "missing_due_date"})
        self.assertEqual(self.reasons(invoice(due_date="bad", paid_date="bad")), {"INV-1": "invalid_due_date"})

    def test_bad_data_wins_over_paid_and_not_yet(self):
        # A future due date is not bad data: not yet overdue, nothing planned, not skipped.
        plan = plan_for([invoice(due_date="2026-12-01")])
        self.assertEqual(plan, {"today": TODAY, "actions": [], "skipped": []})
        # Paid with a future paid_date is bad data even though "paid" would plan nothing.
        self.assertEqual(self.reasons(invoice(days_overdue=30, paid_date="2026-11-01")), {"INV-1": "invalid_paid_date"})

    def test_skipped_invoice_gets_no_action_even_if_overdue(self):
        plan = plan_for([invoice(days_overdue=40, amount="x")])
        self.assertEqual(plan["actions"], [])
        self.assertEqual(len(plan["skipped"]), 1)

    def test_entries_without_a_text_id_are_ignored(self):
        plan = plan_for(["junk", None, {"amount": 5}, {"id": 5}, invoice(days_overdue=5)])
        self.assertEqual(steps_of(plan), [("INV-1", "friendly")])
        self.assertEqual(plan["skipped"], [])


class SortingTest(unittest.TestCase):
    def test_actions_and_skipped_sorted_by_plain_text(self):
        invoices = [
            invoice("INV-99", 5), invoice("INV-100", 5), invoice("INV-1000", 5), invoice("inv-5", 5),
            invoice("INV-9", amount=0), invoice("INV-10", amount=0), invoice("INV-B", amount=0),
        ]
        plan = plan_for(invoices)
        self.assertEqual([a["invoice_id"] for a in plan["actions"]], ["INV-100", "INV-1000", "INV-99", "inv-5"])
        self.assertEqual([s["invoice_id"] for s in plan["skipped"]], ["INV-10", "INV-9", "INV-B"])

    def test_duplicates_sorted_among_other_skips(self):
        invoices = [invoice("B", amount=0), invoice("C"), invoice("C"), invoice("A", amount=0)]
        self.assertEqual([s["invoice_id"] for s in plan_for(invoices)["skipped"]], ["A", "B", "C"])

    def test_input_order_does_not_change_output(self):
        invoices = [invoice("INV-3", 12), invoice("INV-1", 30), invoice("INV-2", 5)]
        self.assertEqual(plan_for(invoices), plan_for(list(reversed(invoices))))


class SampleDataTest(unittest.TestCase):
    """The sample files in data/, worked out by hand from the rules."""

    def test_sample_data(self):
        data = os.path.join(os.path.dirname(PYTHON_DIR), "data")
        with open(os.path.join(data, "invoices.json"), encoding="utf-8") as f:
            invoices = json.load(f)
        with open(os.path.join(data, "sent.json"), encoding="utf-8") as f:
            sent_list = json.load(f)
        plan = build_plan(invoices, sent_list, "2026-10-12")
        self.assertEqual(
            [(a["invoice_id"], a["step"], a["needs_approval"], a["days_overdue"]) for a in plan["actions"]],
            [
                ("INV-1001", "firm", True, 12),
                ("INV-1002", "friendly", False, 3),
                ("INV-1004", "final", True, 32),
                ("INV-1009", "firm", True, 12),
                ("INV-1011", "firm", True, 10),
            ],
        )
        self.assertEqual(
            [(s["invoice_id"], s["reason"]) for s in plan["skipped"]],
            [
                ("INV-1007", "invalid_due_date"),
                ("INV-1008", "missing_due_date"),
                ("INV-1010", "duplicate_id"),
            ],
        )


class CommandLineTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.invoices = self.write("invoices.json", [invoice(days_overdue=12)])
        self.sent = self.write("sent.json", [])
        self.out = os.path.join(self.tmp.name, "actions.json")

    def write(self, name, data, raw=None):
        path = os.path.join(self.tmp.name, name)
        with open(path, "w", encoding="utf-8") as f:
            f.write(raw if raw is not None else json.dumps(data))
        return path

    def run_cli(self, today=TODAY, invoices=None, sent_path=None):
        cmd = [sys.executable, "plan.py", "--invoices", invoices or self.invoices,
               "--sent", sent_path or self.sent, "--today", today, "--out", self.out]
        return subprocess.run(cmd, cwd=PYTHON_DIR, capture_output=True, text=True)

    def test_writes_plan_and_exits_zero(self):
        result = self.run_cli()
        self.assertEqual(result.returncode, 0, result.stderr)
        with open(self.out, encoding="utf-8") as f:
            plan = json.load(f)
        self.assertEqual(list(plan), ["today", "actions", "skipped"])
        self.assertEqual(plan["actions"][0]["step"], "firm")

    def test_invalid_today(self):
        for bad in ("2026-02-30", "12/10/2026", "", "today"):
            with self.subTest(today=bad):
                result = self.run_cli(today=bad)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("--today", result.stderr)
                self.assertNotIn("Traceback", result.stderr)

    def test_missing_file(self):
        result = self.run_cli(invoices=os.path.join(self.tmp.name, "nope.json"))
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("cannot read", result.stderr)
        self.assertNotIn("Traceback", result.stderr)

    def test_broken_json(self):
        broken = self.write("broken.json", None, raw="{not json")
        result = self.run_cli(sent_path=broken)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("not valid JSON", result.stderr)
        self.assertNotIn("Traceback", result.stderr)

    def test_json_that_is_not_a_list(self):
        wrong = self.write("object.json", {"a": 1})
        result = self.run_cli(invoices=wrong)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("must contain a JSON list", result.stderr)

    def test_unwritable_output(self):
        self.out = os.path.join(self.tmp.name, "no-such-dir", "actions.json")
        result = self.run_cli()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("cannot write", result.stderr)


if __name__ == "__main__":
    unittest.main()
