import json
import os
import tempfile
import threading
import unittest
import urllib.error
import urllib.parse
import urllib.request
from http.server import ThreadingHTTPServer

from app import DecisionStore, make_handler

INVOICES = [
    {"id": "INV-1", "customer": "Alder <b>Ltd</b>", "amount": 1250.0, "currency": "EUR",
     "due_date": "2026-09-30", "paid_date": None},                    # 12 days: firm
    {"id": "INV-2", "customer": "Birchway", "amount": 480.0, "currency": "EUR",
     "due_date": "2026-10-09", "paid_date": None},                    # 3 days: friendly
    {"id": "INV-3", "customer": "Granite", "amount": 1.0, "currency": "EUR",
     "due_date": "2026-02-30", "paid_date": None},                    # bad date
]


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


class PageTest(unittest.TestCase):
    def serve(self, invoices=INVOICES, sent=(), today="2026-10-12", raw_invoices=None):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        with open(os.path.join(tmp.name, "invoices.json"), "w", encoding="utf-8") as f:
            f.write(raw_invoices if raw_invoices is not None else json.dumps(invoices))
        with open(os.path.join(tmp.name, "sent.json"), "w", encoding="utf-8") as f:
            json.dump(list(sent), f)
        server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(tmp.name, today, DecisionStore()))
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        self.base = f"http://127.0.0.1:{server.server_address[1]}"

    def get(self, path="/"):
        with urllib.request.urlopen(self.base + path) as r:
            return r.status, r.read().decode("utf-8")

    def post(self, invoice_id, decision, path="/decision"):
        data = urllib.parse.urlencode({"invoice_id": invoice_id, "decision": decision}).encode()
        opener = urllib.request.build_opener(NoRedirect)
        try:
            with opener.open(urllib.request.Request(self.base + path, data=data)) as r:
                return r.status
        except urllib.error.HTTPError as e:
            return e.code

    def test_shows_plan_and_skipped_in_plain_words(self):
        self.serve()
        status, html = self.get()
        self.assertEqual(status, 200)
        self.assertIn("EUR 1250.00", html)
        self.assertIn("12 days overdue", html)
        self.assertIn("Firm reminder", html)
        self.assertIn("Dear Alder &lt;b&gt;Ltd&lt;/b&gt;", html)  # customer text is escaped
        self.assertNotIn("<b>Ltd</b>", html)
        self.assertIn("not a real date", html)
        self.assertNotIn("invalid_due_date", html)

    def test_viewport_meta_for_phones(self):
        self.serve()
        self.assertIn('name="viewport"', self.get()[1])

    def test_approve_and_reject_are_recorded_and_changeable(self):
        self.serve()
        self.assertIn("Waiting for your decision", self.get()[1])
        self.assertEqual(self.post("INV-1", "approve"), 303)
        self.assertIn("You approved this reminder", self.get()[1])
        self.assertEqual(self.post("INV-1", "reject"), 303)
        self.assertIn("You rejected this reminder", self.get()[1])

    def test_cannot_decide_friendly_unknown_or_bad_decision(self):
        self.serve()
        self.assertEqual(self.post("INV-2", "approve"), 400)  # friendly: no approval needed
        self.assertEqual(self.post("INV-3", "approve"), 400)  # skipped
        self.assertEqual(self.post("INV-404", "approve"), 400)
        self.assertEqual(self.post("INV-1", "maybe"), 400)

    def test_nothing_to_do(self):
        self.serve(invoices=[INVOICES[1] | {"due_date": "2026-12-01"}])
        self.assertIn("Nothing to do today", self.get()[1])

    def test_unreadable_data(self):
        self.serve(raw_invoices="{broken")
        status, html = self.get()
        self.assertEqual(status, 200)
        self.assertIn("could not read your invoice data", html)

    def test_invalid_today(self):
        self.serve(today="not-a-date")
        self.assertIn("could not read your invoice data", self.get()[1])

    def test_unknown_path_is_404(self):
        self.serve()
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            self.get("/nope")
        self.assertEqual(ctx.exception.code, 404)


if __name__ == "__main__":
    unittest.main()
