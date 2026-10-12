# Payment reminder assistant (Python, standard library only)

**Run from `python/`:**
- Tests: `python -m unittest`
- Plan: `python plan.py --invoices ../data/invoices.json --sent ../data/sent.json --today 2026-10-12 --out ../actions.json`
- Page: `python app.py`, then open http://localhost:8000/ (env: `PORT`, `DATA_DIR`, `TODAY`)

**Structure:** `plan.py` is the rules engine (`build_plan` is a pure function, no web or I/O). `messages.py` has the email templates. `app.py` is the page and only calls the engine. `RESEARCH.md` has the research answers.

**Decisions**
- One engine, used by the command line and the page. The page has no copy of the rules. It also gets a "no action needed" list (paid, not late enough, already sent) from the same function, so the output file keeps the required shape.
- Dates must be exactly `YYYY-MM-DD` and a real date (so `2026-02-30` and `2026-9-3` are invalid). Booleans are not numbers. Amounts must be finite and above 0.
- Messages are fixed templates in `messages.py`, written by hand, with nothing to configure and no internet needed. They contain only the invoice's own figures: no fees, interest, deadlines or mention of earlier reminders. A test strips the allowed facts and checks that no digit is left.
- The page re-reads the data on each request and keeps approve and reject choices in memory, per invoice and step. Only firm and final reminders on today's plan can be decided. Unreadable data shows a clear message.
- Invoice entries without a text `id` cannot be named in the output, so they are ignored.
- Tests: rule boundaries, every skip reason and its order, sorting, the command line errors, and the page. I also compared the engine with a separate implementation of the rules on 20,000 random datasets, with no differences.

**With more time**
- Persist decisions and sent reminders to disk or a database, and actually send the emails.
- Let the owner edit the message wording per step, with the same no-extra-figures check applied to any change.
- Add currency-aware formatting, a date picker for "today", and browser tests for the page.
