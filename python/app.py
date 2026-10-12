"""The owner's page (part 2). Standard library only, no install needed.

Run from inside python/:

    python app.py

Environment variables:
    PORT      port to listen on, default 8000
    DATA_DIR  folder with invoices.json and sent.json, default ../data
    TODAY     date as YYYY-MM-DD, default the real date
"""

import os
import sys
import threading
from datetime import date
from html import escape
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs

from messages import format_amount
from plan import InputError, parse_date, plan_from_files

SKIP_REASONS = {
    "duplicate_id": ("Duplicate invoice number",
                     "Two or more invoices share this number, so we cannot tell which one is right. "
                     "Give each invoice its own number."),
    "invalid_amount": ("Amount is wrong",
                       "The amount is missing, not a number, or not above zero."),
    "missing_due_date": ("No due date",
                         "There is no due date, so we cannot tell if this invoice is overdue."),
    "invalid_due_date": ("Due date is not a real date",
                         "The due date is not a real date in the form YYYY-MM-DD."),
    "invalid_paid_date": ("Paid date is wrong",
                          "The paid date is not a real date in the form YYYY-MM-DD, or it is in the future."),
}

DECISIONS = {"approve": "approved", "reject": "rejected"}
STEP_LABELS = {"friendly": "Friendly reminder", "firm": "Firm reminder", "final": "Final notice"}

CSS = """
:root {
  --bg:#f4f6fb; --surface:#fff; --surface-2:#f8f9fc; --ink:#14192b; --muted:#59627a; --line:#e1e5ef;
  --brand:#3b4cca; --brand-ink:#fff;
  --friendly:#1d6fd8; --friendly-bg:#e8f1fd;
  --firm:#b45309; --firm-bg:#fef3e2;
  --final:#c2253a; --final-bg:#fde9ec;
  --ok:#17803d; --ok-bg:#e4f6ea; --bad:#c2253a; --bad-bg:#fde9ec; --warn:#b45309; --warn-bg:#fef3e2;
  --shadow:0 1px 2px rgba(20,25,43,.06), 0 4px 14px rgba(20,25,43,.05); --focus:#f59e0b;
}
@media (prefers-color-scheme: dark) { :root {
  --bg:#0f1220; --surface:#181c2e; --surface-2:#1e2338; --ink:#eef0f8; --muted:#a2aac4; --line:#2b3150;
  --brand:#8b98ff; --brand-ink:#0f1220;
  --friendly:#7db3ff; --friendly-bg:#16294a; --firm:#fbbf6a; --firm-bg:#3a2a12; --final:#ff8a9a; --final-bg:#40161f;
  --ok:#56d98a; --ok-bg:#12341f; --bad:#ff8a9a; --bad-bg:#40161f; --warn:#fbbf6a; --warn-bg:#3a2a12;
  --shadow:0 1px 2px rgba(0,0,0,.4), 0 4px 14px rgba(0,0,0,.25); --focus:#fbbf24;
} }
* { box-sizing:border-box; }
html { -webkit-text-size-adjust:100%; }
body { margin:0; background:var(--bg); color:var(--ink);
  font:16px/1.5 system-ui,-apple-system,"Segoe UI",Roboto,"Helvetica Neue",Arial,sans-serif; }
.skip { position:absolute; left:-999px; top:.5rem; background:var(--brand); color:var(--brand-ink);
  padding:.5rem 1rem; border-radius:.5rem; z-index:10; }
.skip:focus { left:.5rem; }
:focus-visible { outline:3px solid var(--focus); outline-offset:2px; border-radius:.35rem; }

header.top { background:var(--surface); border-bottom:1px solid var(--line); }
.wrap { max-width:60rem; margin:0 auto; padding:0 1rem; }
.top .wrap { display:flex; flex-wrap:wrap; align-items:center; justify-content:space-between; gap:.5rem 1rem; padding-block:1.1rem; }
.brand { display:flex; align-items:center; gap:.65rem; }
.logo { width:2.25rem; height:2.25rem; border-radius:.6rem; background:var(--brand); color:var(--brand-ink);
  display:grid; place-items:center; }
h1 { font-size:1.25rem; line-height:1.2; margin:0; letter-spacing:-.01em; }
.today { color:var(--muted); font-size:.9rem; margin:0; }
.datepill { display:inline-flex; gap:.4rem; align-items:center; background:var(--surface-2); border:1px solid var(--line);
  border-radius:2rem; padding:.3rem .8rem; font-size:.9rem; color:var(--muted); }
main.wrap { padding-block:2rem 3.5rem; }

.tiles { list-style:none; margin:0 0 .75rem; padding:0; display:grid; gap:1rem; grid-template-columns:repeat(2,1fr); }
@media (min-width:720px) { .tiles { grid-template-columns:repeat(4,1fr); } }
.tile { display:block; text-decoration:none; color:inherit; background:var(--surface); border:1px solid var(--line);
  border-radius:.9rem; padding:1.1rem 1.25rem; box-shadow:var(--shadow); border-top:4px solid var(--line); }
.tile:hover { border-color:var(--brand); }
.tile .n { display:block; font-size:1.9rem; font-weight:700; line-height:1.1; letter-spacing:-.02em; }
.tile .l { display:block; color:var(--muted); font-size:.85rem; margin-top:.15rem; }
.tile.t-approval { border-top-color:var(--firm); } .tile.t-auto { border-top-color:var(--friendly); }
.tile.t-skipped { border-top-color:var(--bad); } .tile.t-quiet { border-top-color:var(--ok); }

section { margin-top:2rem; }
.sh { display:flex; align-items:baseline; gap:.6rem; margin:0 0 .25rem; }
h2 { font-size:1.1rem; margin:0; letter-spacing:-.01em; }
.count { background:var(--surface-2); border:1px solid var(--line); border-radius:2rem; font-size:.8rem;
  padding:0 .55rem; color:var(--muted); }
.hint { color:var(--muted); margin:0 0 .75rem; font-size:.92rem; }

ul.cards { list-style:none; margin:0; padding:0; display:grid; gap:.85rem; }
.card { background:var(--surface); border:1px solid var(--line); border-radius:.9rem; box-shadow:var(--shadow);
  padding:1rem 1rem 1rem 1.15rem; border-left:6px solid var(--line); scroll-margin-top:1rem; }
.card.friendly { border-left-color:var(--friendly); } .card.firm { border-left-color:var(--firm); }
.card.final { border-left-color:var(--final); } .card.skipped { border-left-color:var(--bad); }
.row { display:flex; flex-wrap:wrap; justify-content:space-between; align-items:flex-start; gap:.25rem 1rem; }
.who { min-width:0; }
.who h3 { margin:0; font-size:1.05rem; line-height:1.3; overflow-wrap:anywhere; }
.who .inv { color:var(--muted); font-size:.9rem; overflow-wrap:anywhere; }
.amount { font-size:1.35rem; font-weight:700; letter-spacing:-.01em; white-space:nowrap; }
.chips { display:flex; flex-wrap:wrap; gap:.4rem; margin:.65rem 0 .25rem; padding:0; list-style:none; }
.chip { display:inline-flex; align-items:center; gap:.3rem; border-radius:2rem; padding:.15rem .65rem; font-size:.82rem;
  font-weight:600; background:var(--surface-2); border:1px solid var(--line); color:var(--muted); }
.chip.friendly { background:var(--friendly-bg); color:var(--friendly); border-color:transparent; }
.chip.firm { background:var(--firm-bg); color:var(--firm); border-color:transparent; }
.chip.final { background:var(--final-bg); color:var(--final); border-color:transparent; }
.chip.ok { background:var(--ok-bg); color:var(--ok); border-color:transparent; }
.chip.bad { background:var(--bad-bg); color:var(--bad); border-color:transparent; }
.chip.warn { background:var(--warn-bg); color:var(--warn); border-color:transparent; }

details { margin:.5rem 0 0; border:1px solid var(--line); border-radius:.6rem; background:var(--surface-2); }
summary { cursor:pointer; padding:.6rem .85rem; font-weight:600; font-size:.92rem; list-style:none; display:flex; align-items:center; gap:.5rem; }
summary::-webkit-details-marker { display:none; }
summary::before { content:""; width:.5rem; height:.5rem; border-right:2px solid currentColor; border-bottom:2px solid currentColor;
  transform:rotate(-45deg); transition:transform .15s; }
details[open] summary::before { transform:rotate(45deg); }
pre { white-space:pre-wrap; overflow-wrap:anywhere; font:inherit; margin:0; padding:.25rem .85rem 1rem; color:var(--ink); }

.decide { display:flex; flex-wrap:wrap; align-items:center; gap:.6rem .75rem; margin-top:.85rem; padding-top:.85rem;
  border-top:1px dashed var(--line); }
.decide .status { flex:1 1 12rem; margin:0; font-weight:600; font-size:.95rem; }
.decide .btns { display:flex; gap:.5rem; flex:1 1 14rem; }
.decide form { flex:1; display:flex; }
button { font:inherit; font-weight:600; flex:1; min-height:2.75rem; padding:.45rem 1rem; border-radius:.6rem; cursor:pointer;
  border:2px solid var(--ok); background:transparent; color:var(--ok); }
button.reject { border-color:var(--bad); color:var(--bad); }
button:hover { background:var(--ok-bg); } button.reject:hover { background:var(--bad-bg); }
button[aria-pressed="true"] { background:var(--ok); color:var(--surface); }
button.reject[aria-pressed="true"] { background:var(--bad); color:var(--surface); }
.auto { margin:.85rem 0 0; padding-top:.85rem; border-top:1px dashed var(--line); color:var(--muted); font-size:.92rem; }

.fix { margin:.5rem 0 0; color:var(--muted); font-size:.95rem; }
ul.quiet { list-style:none; margin:0; padding:0; background:var(--surface); border:1px solid var(--line); border-radius:.9rem;
  box-shadow:var(--shadow); overflow:hidden; }
ul.quiet li { display:flex; flex-wrap:wrap; justify-content:space-between; gap:.25rem 1rem; padding:.8rem 1rem; }
ul.quiet li + li { border-top:1px solid var(--line); }
ul.quiet .why { color:var(--muted); font-size:.9rem; flex-basis:100%; }

.notice { display:flex; gap:.85rem; align-items:flex-start; background:var(--surface); border:1px solid var(--line);
  border-radius:.9rem; box-shadow:var(--shadow); padding:1.1rem 1.15rem; margin-top:1rem; }
.notice .ic { flex:none; width:2.5rem; height:2.5rem; border-radius:50%; display:grid; place-items:center;
  background:var(--ok-bg); color:var(--ok); }
.notice p { margin:.25rem 0 0; color:var(--muted); }
.notice strong { font-size:1.05rem; }
.notice.error { border-color:var(--warn); } .notice.error .ic { background:var(--warn-bg); color:var(--warn); }
a { color:var(--brand); }
@media (max-width:480px) { .amount { order:-1; width:100%; } .wrap { padding-inline:.85rem; } main.wrap { padding-block:1.25rem 2.5rem; } .tiles { gap:.75rem; } .tile { padding:.9rem 1rem; } .tile .n { font-size:1.6rem; } }
@media (prefers-reduced-motion: reduce) { * { transition:none !important; } }
"""

ICONS = (
    '<svg width="0" height="0" style="position:absolute" aria-hidden="true"><defs>'
    '<symbol id="i-mail" viewBox="0 0 24 24"><path fill="none" stroke="currentColor" stroke-width="2" '
    'stroke-linecap="round" stroke-linejoin="round" d="M3 6h18v12H3zM3 7l9 7 9-7"/></symbol>'
    '<symbol id="i-check" viewBox="0 0 24 24"><path fill="none" stroke="currentColor" stroke-width="2.5" '
    'stroke-linecap="round" stroke-linejoin="round" d="M5 12.5l4.5 4.5L19 7.5"/></symbol>'
    '<symbol id="i-warn" viewBox="0 0 24 24"><path fill="none" stroke="currentColor" stroke-width="2" '
    'stroke-linecap="round" stroke-linejoin="round" d="M12 4l9 16H3zM12 10v4M12 17.5v.01"/></symbol>'
    "</defs></svg>"
)


def icon(name, size=20):
    return f'<svg width="{size}" height="{size}" aria-hidden="true"><use href="#i-{name}"/></svg>'


class DecisionStore:
    """The owner's decisions, kept while the app runs. Keyed by invoice and step."""

    def __init__(self):
        self._lock = threading.Lock()
        self._decisions = {}

    def get(self, invoice_id, step):
        with self._lock:
            return self._decisions.get((invoice_id, step))

    def set(self, invoice_id, step, decision):
        with self._lock:
            self._decisions[(invoice_id, step)] = decision


def anchor_for(invoice_id):
    return "inv-" + "".join(c if c.isalnum() else "-" for c in invoice_id)


def money(invoice):
    return format_amount(invoice["amount"], invoice.get("currency", ""))


def plural(n, word):
    return f"{n} {word}" + ("" if n == 1 else "s")


def nice_date(iso):
    d = parse_date(iso)
    return f"{d:%A} {d.day} {d:%B %Y}" if d else iso


def render_action(action, invoice, decision):
    invoice_id, step = action["invoice_id"], action["step"]
    safe_id = escape(invoice_id, quote=True)
    label = STEP_LABELS[step]
    head = (
        '<div class="row"><div class="who">'
        f'<h3>{escape(invoice.get("customer") or "(no name)")}</h3>'
        f'<div class="inv">Invoice {escape(invoice_id)}</div></div>'
        f'<div class="amount">{escape(money(invoice))}</div></div>'
        '<ul class="chips">'
        f'<li class="chip {step}">{label}</li>'
        f'<li class="chip">{plural(action["days_overdue"], "day")} overdue</li>'
        f'<li class="chip">Due {escape(invoice["due_date"])}</li></ul>'
    )
    message = (
        f'<details><summary>Read the message to {escape(invoice.get("customer") or "the customer")}</summary>'
        f"<pre>{escape(action['message'])}</pre></details>"
    )
    if not action["needs_approval"]:
        control = f'<p class="auto">{icon("mail", 16)} Goes out today. This step needs no approval.</p>'
    else:
        status = {
            "approved": '<p class="status" role="status" style="color:var(--ok)">You approved this reminder.</p>',
            "rejected": '<p class="status" role="status" style="color:var(--bad)">You rejected this reminder.</p>',
        }.get(decision, '<p class="status" style="color:var(--warn)">Waiting for your decision.</p>')
        buttons = ""
        for value, text, css in (("approve", "Approve", ""), ("reject", "Reject", "reject")):
            pressed = "true" if decision == DECISIONS[value] else "false"
            mark = ("&#10003; " if value == "approve" else "&#10005; ") if pressed == "true" else ""
            buttons += (
                '<form method="post" action="/decision">'
                f'<input type="hidden" name="invoice_id" value="{safe_id}">'
                f'<input type="hidden" name="decision" value="{value}">'
                f'<button type="submit" class="{css}" aria-pressed="{pressed}" '
                f'aria-label="{text} {label.lower()} for invoice {safe_id}">{mark}{text}'
                "</button></form>"
            )
        control = f'<div class="decide">{status}<div class="btns">{buttons}</div></div>'
    return f'<li class="card {step}" id="{anchor_for(invoice_id)}">{head}{message}{control}</li>'


def render_skipped(item, invoices):
    title, explanation = SKIP_REASONS[item["reason"]]
    rows = [i for i in invoices if isinstance(i, dict) and i.get("id") == item["invoice_id"]]
    names = sorted({str(i["customer"]) for i in rows if i.get("customer")})
    who = f'<div class="inv">{escape(", ".join(names))}</div>' if names else ""
    count = f'<li class="chip">{len(rows)} invoices use this number</li>' if item["reason"] == "duplicate_id" else ""
    return (
        '<li class="card skipped"><div class="row"><div class="who">'
        f'<h3>Invoice {escape(item["invoice_id"])}</h3>{who}</div></div>'
        f'<ul class="chips"><li class="chip bad">{icon("warn", 14)} {escape(title)}</li>{count}</ul>'
        f'<p class="fix">{escape(explanation)} No reminder is planned for it.</p></li>'
    )


def quiet_text(item):
    reason, days = item["reason"], item.get("days_overdue")
    if reason == "paid":
        return "ok", "Paid", "Already paid, so no reminder is needed."
    if reason == "already_sent":
        sent = STEP_LABELS[item["step"]].lower()
        return "warn", "Already sent", f"The {sent} has already gone out, and nothing stronger is due yet."
    if days < 0:
        return "", "Not due yet", f"Due in {plural(-days, 'day')}."
    if days == 0:
        return "", "Due today", "Due today. Reminders start 3 days after the due date."
    return "", "Not late enough", f"{plural(days, 'day')} overdue. The first reminder starts at 3 days."


def render_quiet(item, invoice):
    kind, title, why = quiet_text(item)
    return (
        '<li><div class="who">'
        f'<strong>{escape(invoice.get("customer") or "(no name)")}</strong> '
        f'<span class="inv">&middot; Invoice {escape(item["invoice_id"])} &middot; {escape(money(invoice))}</span></div>'
        f'<span class="chip {kind}">{escape(title)}</span><span class="why">{escape(why)}</span></li>'
    )


def render_page(today, plan=None, invoices=(), store=None, error=None, quiet=()):
    d = parse_date(today)
    pill = f'<span class="datepill">{escape(nice_date(today))}</span>' if d else ""
    header = (
        '<header class="top"><div class="wrap"><div class="brand">'
        f'<span class="logo">{icon("mail", 20)}</span>'
        '<div><h1>Payment reminders</h1><p class="today">What needs doing today</p></div></div>'
        f"{pill}</div></header>"
    )
    if error:
        body = (
            '<div class="notice error" role="alert">'
            f'<span class="ic">{icon("warn")}</span><div><strong>We could not read your invoice data.</strong>'
            f"<p>{escape(error)}</p>"
            "<p>Nothing has been planned. Check the data files, then reload this page.</p></div></div>"
        )
        return layout(header, body)

    by_id = {}
    for inv in invoices:
        if isinstance(inv, dict) and isinstance(inv.get("id"), str):
            by_id.setdefault(inv["id"], inv)
    actions, skipped = plan["actions"], plan["skipped"]
    approval = [a for a in actions if a["needs_approval"]]
    automatic = [a for a in actions if not a["needs_approval"]]

    def tile(css, href, n, text):
        return f'<li><a class="tile {css}" href="#{href}"><span class="n">{n}</span><span class="l">{text}</span></a></li>'

    parts = ['<ul class="tiles">'
             + tile("t-approval", "approval", len(approval), "Need your approval")
             + tile("t-auto", "auto", len(automatic), "Going out today")
             + tile("t-skipped", "skipped", len(skipped), "Could not be checked")
             + tile("t-quiet", "quiet", len(quiet), "No action needed")
             + "</ul>"]

    if not actions and not skipped:
        parts.append(
            '<div class="notice"><span class="ic">' + icon("check") + '</span><div><strong>Nothing to do today.</strong>'
            "<p>No invoice needs a reminder, and every invoice could be checked.</p></div></div>")

    def section(sid, title, items, hint, empty):
        head = (f'<div class="sh"><h2 id="{sid}-h">{title}</h2>'
                f'<span class="count">{len(items)}</span></div>')
        if items:
            cards = "".join(items)
            return (f'<section id="{sid}" aria-labelledby="{sid}-h">{head}<p class="hint">{hint}</p>'
                    f'<ul class="cards">{cards}</ul></section>')
        return f'<section id="{sid}" aria-labelledby="{sid}-h">{head}<p class="hint">{empty}</p></section>'

    parts.append(section(
        "approval", "Needs your approval",
        [render_action(a, by_id[a["invoice_id"]], store.get(a["invoice_id"], a["step"])) for a in approval],
        "Firm and final reminders only go out after you approve them. Nothing is sent from this page; it only records your decision.",
        "Nothing needs your approval today."))
    parts.append(section(
        "auto", "Going out today",
        [render_action(a, by_id[a["invoice_id"]], None) for a in automatic],
        "Friendly reminders. These need no approval.", "No friendly reminders today."))
    parts.append(section(
        "skipped", "Could not be checked",
        [render_skipped(s, invoices) for s in skipped],
        "These invoices have wrong data, so we cannot tell what to do. Fix the data to include them.",
        "Every invoice could be checked."))

    quiet_items = "".join(render_quiet(q, by_id[q["invoice_id"]]) for q in quiet)
    quiet_body = (f'<ul class="quiet" aria-labelledby="quiet-h">{quiet_items}</ul>' if quiet
                  else '<p class="hint">None.</p>')
    parts.append(
        '<section id="quiet" aria-labelledby="quiet-h"><div class="sh"><h2 id="quiet-h">No action needed</h2>'
        f'<span class="count">{len(quiet)}</span></div>'
        f'<p class="hint">These invoices are fine for today.</p>{quiet_body}</section>')
    return layout(header, "".join(parts))


def layout(header, body):
    return (
        '<!doctype html><html lang="en"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        '<meta name="color-scheme" content="light dark">'
        f"<title>Payment reminders</title><style>{CSS}</style></head><body>{ICONS}"
        f'<a class="skip" href="#main">Skip to the plan</a>{header}'
        f'<main id="main" class="wrap">{body}</main></body></html>'
    )


def make_handler(data_dir, today, store):
    def load():
        """Read the data fresh on every request. Returns (plan, invoices, quiet, error)."""
        try:
            plan, invoices, quiet = plan_from_files(
                os.path.join(data_dir, "invoices.json"), os.path.join(data_dir, "sent.json"), today)
            return plan, invoices, quiet, None
        except InputError as e:
            return None, [], [], str(e)

    class Handler(BaseHTTPRequestHandler):
        def _send(self, status, body, content_type="text/html; charset=utf-8"):
            data = body.encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            if self.path.split("?")[0] != "/":
                self.send_error(404)
                return
            plan, invoices, quiet, error = load()
            self._send(200, render_page(today, plan, invoices, store, error, quiet))

        def do_POST(self):
            if self.path != "/decision":
                self.send_error(404)
                return
            try:
                length = min(int(self.headers.get("Content-Length", "0")), 10_000)
            except ValueError:
                length = 0
            form = parse_qs(self.rfile.read(length).decode("utf-8", "replace"))
            invoice_id = form.get("invoice_id", [""])[0]
            decision = form.get("decision", [""])[0]
            plan = load()[0]
            # Only a reminder that is on today's plan and needs approval can be decided.
            action = next((a for a in (plan["actions"] if plan else [])
                           if a["invoice_id"] == invoice_id and a["needs_approval"]), None)
            if action is None or decision not in DECISIONS:
                self._send(400, layout("", '<h1>Cannot record that</h1><p>That reminder is not waiting for '
                                           'a decision. <a href="/">Back to the plan</a></p>'))
                return
            store.set(invoice_id, action["step"], DECISIONS[decision])
            self.send_response(303)
            self.send_header("Location", "/#" + anchor_for(invoice_id))
            self.send_header("Content-Length", "0")
            self.end_headers()

        def log_message(self, format, *args):
            sys.stderr.write("%s - %s\n" % (self.address_string(), format % args))

    return Handler


def main():
    try:
        port = int(os.environ.get("PORT", "8000"))
    except ValueError:
        sys.exit("error: PORT must be a number")
    data_dir = os.environ.get("DATA_DIR", "../data")
    today = os.environ.get("TODAY") or date.today().isoformat()
    server = ThreadingHTTPServer(("", port), make_handler(data_dir, today, DecisionStore()))
    print(f"Serving on http://localhost:{port}/")
    server.serve_forever()


if __name__ == "__main__":
    main()
