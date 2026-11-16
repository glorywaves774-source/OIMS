"""Currency conversion with the organization's own exchange rates (app/models/rates.py).

Rules, chosen so reports stay explainable:
* Positions (budget, spent so far, committed, available) are converted at the latest rate on or before the
  date of the report ("as of" date, normally today).
* Spending within a period is converted at the rate of the day each payment was made, so last year's figures
  do not change when rates move.
* A missing rate is never guessed: the amount is left out of the combined total and the page says which
  currency needs a rate.
"""
from datetime import date
from decimal import ROUND_HALF_UP, Decimal

from flask import g
from sqlalchemy import select

from app.extensions import db
from app.models import ExchangeRate

CENT = Decimal("0.01")


class Rates:
    """All of an organization's rates, loaded once per page; lookups are then in memory."""

    def __init__(self, organization_id=None):
        org_id = organization_id or g.tenant.id
        self.by_pair = {}
        for r in db.session.execute(select(ExchangeRate).where(ExchangeRate.organization_id == org_id)
                                    .order_by(ExchangeRate.effective_on)).scalars():
            self.by_pair.setdefault((r.currency, r.base_currency), []).append((r.effective_on, Decimal(r.rate), r))

    def _direct(self, cur, base, on):
        found = None
        for day, rate, row in self.by_pair.get((cur, base), []):
            if day <= on:
                found = (rate, row)
            else:
                break
        return found

    def rate(self, cur, to, on=None):
        """How many `to` for one `cur` on that day, or None. Uses the pair either way round, or via a third
        currency both have rates against (e.g. USD -> GHS -> EUR)."""
        on = on or date.today()
        r = self.rate_direct_or_inverse(cur, to, on)
        if r is not None:
            return r
        bases = {b for (c, b) in self.by_pair if c == cur} | {c for (c, b) in self.by_pair if b == cur}
        for mid in sorted(bases):
            a = self.rate_direct_or_inverse(cur, mid, on)
            b = self.rate_direct_or_inverse(mid, to, on)
            if a and b:
                return a * b
        return None

    def rate_direct_or_inverse(self, cur, to, on):
        if cur == to:
            return Decimal(1)
        d = self._direct(cur, to, on)
        if d:
            return d[0]
        d = self._direct(to, cur, on)
        return (Decimal(1) / d[0]) if d else None

    def convert(self, amount, cur, to, on=None):
        r = self.rate(cur, to, on)
        if r is None:
            return None
        return (Decimal(amount or 0) * r).quantize(CENT, rounding=ROUND_HALF_UP)

    def latest(self, cur, base, on=None):
        """The rate row in force for a stored pair (for showing 'rate of <date>')."""
        d = self._direct(cur, base, on or date.today())
        return d[1] if d else None


def combine(totals, to, rates, on=None, keys=None):
    """Add per-currency totals ({currency: {key: amount}}) into one currency.

    Returns (combined {key: amount}, missing currencies)."""
    keys = keys or sorted({k for t in totals.values() for k in t})
    out = {k: Decimal(0) for k in keys}
    missing = []
    for cur, t in totals.items():
        r = rates.rate(cur, to, on)
        if r is None:
            missing.append(cur)
            continue
        for k in keys:
            out[k] += (Decimal(t.get(k) or 0) * r).quantize(CENT, rounding=ROUND_HALF_UP)
    return out, sorted(missing)
