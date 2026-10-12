import re
import unittest

from messages import build_message, format_amount
from plan import build_plan

FORBIDDEN_WORDS = ["fee", "interest", "penalty", "reminder", "earlier", "previous", "again",
                   "second", "first", "legal", "court", "lawyer", "collection", "within", "by "]


def message(step, **kw):
    args = dict(customer="Alder Fabrication Ltd", invoice_id="INV-1001", due_date="2026-09-30",
                amount=1250.0, currency="EUR", days_overdue=12)
    args.update(kw)
    return build_message(step, **args)


class AmountFormatTest(unittest.TestCase):
    def test_two_decimals(self):
        for amount, expected in [(1250.0, "EUR 1250.00"), (215.5, "EUR 215.50"), (100, "EUR 100.00"),
                                 (845.25, "EUR 845.25"), (0.1, "EUR 0.10"), (2.675, "EUR 2.68"),
                                 (1e16, "EUR 10000000000000000.00")]:
            with self.subTest(amount=amount):
                self.assertEqual(format_amount(amount, "EUR"), expected)

    def test_currency_is_used(self):
        self.assertEqual(format_amount(845.25, "USD"), "USD 845.25")


class MessageContentTest(unittest.TestCase):
    def test_required_facts_in_every_step(self):
        for step in ("friendly", "firm", "final"):
            with self.subTest(step=step):
                text = message(step)
                for fact in ("Alder Fabrication Ltd", "INV-1001", "2026-09-30", "EUR 1250.00", "12 days"):
                    self.assertIn(fact, text)

    def test_no_other_figure(self):
        """Remove the allowed facts; no digit may be left."""
        for step in ("friendly", "firm", "final"):
            with self.subTest(step=step):
                text = message(step)
                for fact in ("INV-1001", "2026-09-30", "EUR 1250.00", "12"):
                    text = text.replace(fact, "")
                self.assertIsNone(re.search(r"\d", text), text)

    def test_no_invented_claims(self):
        for step in ("friendly", "firm", "final"):
            with self.subTest(step=step):
                lowered = message(step).lower()
                for word in FORBIDDEN_WORDS:
                    self.assertNotIn(word, lowered)
                self.assertNotIn("%", lowered)

    def test_tones_differ(self):
        texts = {message(s) for s in ("friendly", "firm", "final")}
        self.assertEqual(len(texts), 3)
        self.assertIn("final notice", message("final").lower())
        self.assertNotIn("final", message("friendly").lower())
        self.assertNotIn("final", message("firm").lower())

    def test_plan_messages_use_invoice_data(self):
        invoices = [{"id": "INV-7", "customer": "Kestrel Outdoor", "amount": 845.25, "currency": "USD",
                     "due_date": "2026-10-02", "paid_date": None}]
        action = build_plan(invoices, [], "2026-10-12")["actions"][0]
        for fact in ("Kestrel Outdoor", "INV-7", "2026-10-02", "USD 845.25", "10 days"):
            self.assertIn(fact, action["message"])


if __name__ == "__main__":
    unittest.main()
