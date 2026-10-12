"""Reminder message text (part 3).

Fixed templates, so everything works offline. The text only
uses figures that come from the invoice (amount, due date, days overdue). It has no
fees, no interest, no deadlines and no mention of earlier reminders.
"""

from decimal import ROUND_HALF_UP, Decimal, localcontext


def format_amount(amount, currency):
    """`EUR 1250.00`: the currency, then the amount with 2 decimals."""
    with localcontext() as ctx:
        ctx.prec = 60
        value = Decimal(repr(amount)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return f"{currency} {value:f}"


_FRIENDLY = (
    "Dear {customer},\n\n"
    "Invoice {invoice_id} for {amount} was due on {due_date} and is now "
    "{days_overdue} days overdue. It may simply have slipped through, so we would be "
    "grateful if you could arrange payment.\n\n"
    "If you have already paid, please disregard this message, and thank you.\n\n"
    "Kind regards"
)

_FIRM = (
    "Dear {customer},\n\n"
    "Invoice {invoice_id} for {amount} was due on {due_date} and is now "
    "{days_overdue} days overdue. We have not received payment. Please pay this "
    "invoice without further delay.\n\n"
    "If there is a problem with the invoice, please contact us so that we can "
    "resolve it.\n\n"
    "Regards"
)

_FINAL = (
    "Dear {customer},\n\n"
    "This is our final notice about invoice {invoice_id} for {amount}. It was due on "
    "{due_date} and is now {days_overdue} days overdue, and we have not received "
    "payment. We ask you to pay this invoice now.\n\n"
    "If you believe this notice is a mistake, please contact us straight away.\n\n"
    "Regards"
)

TEMPLATES = {"friendly": _FRIENDLY, "firm": _FIRM, "final": _FINAL}


def build_message(step, customer, invoice_id, due_date, amount, currency, days_overdue):
    return TEMPLATES[step].format(
        customer=customer,
        invoice_id=invoice_id,
        amount=format_amount(amount, currency),
        due_date=due_date,
        days_overdue=days_overdue,
    )
