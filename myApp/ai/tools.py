"""Read-only data tools for the AI Analyst.

Every tool is a plain function that queries the live ERP at call time and returns
a JSON-serializable dict. This is what makes the assistant "learn dynamically":
new invoices, production runs, coils, etc. are picked up on the next question --
nothing is baked into the prompt or a static snapshot.

Hard rules:
  * SELECT / aggregate only. No writes, ever.
  * Never return secrets, password hashes, or credentials.
  * Cap row counts so payloads stay small and cheap.
"""
from __future__ import annotations

from decimal import Decimal

from django.db.models import Count, Sum
from django.utils import timezone

from .. import constants as C
from ..models import (
    Coil, Customer, FinishedGoodsLot, Invoice, JobOrder, Payment,
    ProductionActual, ProductionRunOutput, Quotation, StockBalance,
)
from ..views.reports import (
    COLOR_REPORT_ORDER, GAUGE_ORDER, MONTHS_SHORT, PROFILE_REPORT_ORDER,
    _linear_forecast, _overall_summary, _production_matrices,
)
from . import inventory_forecast as _inv_forecast

ZERO = Decimal('0')
LOW_STOCK_M = 50


def _f(value) -> float:
    """Decimal/None -> rounded float for JSON."""
    try:
        return round(float(value or 0), 2)
    except (TypeError, ValueError):
        return 0.0


def _year(year) -> int:
    try:
        return int(year)
    except (TypeError, ValueError):
        return timezone.localdate().year


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------
def sales_year_snapshot(user=None, year=None) -> dict:
    """Monthly booked sales (approved invoices), collections (verified payments),
    quotation pipeline, a linear forecast to year-end, AR aging and top customers."""
    yr = _year(year)
    invoiced = [ZERO] * 12
    inv_count = [0] * 12
    collected = [ZERO] * 12
    pipeline = [ZERO] * 12
    q_count = [0] * 12
    accepted = 0
    decided = 0
    by_customer = {}

    invoices = (Invoice.objects.select_related('customer')
                .prefetch_related('lines', 'payments'))
    approved = C.InvoiceStatus.APPROVED
    today = timezone.localdate()
    ar_outstanding = ZERO
    ar_overdue = ZERO
    aging = {'current': ZERO, 'b1_30': ZERO, 'b31_60': ZERO, 'b60p': ZERO}

    for inv in invoices:
        if inv.status == approved and inv.invoice_date and inv.invoice_date.year == yr:
            m = inv.invoice_date.month - 1
            tot = inv.total
            invoiced[m] += tot
            inv_count[m] += 1
            c = by_customer.setdefault(inv.customer.name, ZERO)
            by_customer[inv.customer.name] = c + tot
        for pay in inv.payments.all():
            if (pay.status == C.PaymentStatus.VERIFIED and pay.received_at
                    and pay.received_at.year == yr):
                collected[pay.received_at.month - 1] += pay.amount
        # AR snapshot (current, across all approved invoices).
        if inv.status == approved:
            bal = inv.balance
            if bal > 0:
                ar_outstanding += bal
                due = inv.due_date or inv.invoice_date
                overdue = (today - due).days if due else 0
                if overdue > 0:
                    ar_overdue += bal
                    bucket = ('b1_30' if overdue <= 30 else
                              'b31_60' if overdue <= 60 else 'b60p')
                    aging[bucket] += bal
                else:
                    aging['current'] += bal

    for q in Quotation.objects.filter(is_current=True):
        if not q.quote_date or q.quote_date.year != yr:
            continue
        if q.status == C.QuotationStatus.DRAFT:
            continue
        m = q.quote_date.month - 1
        q_count[m] += 1
        pipeline[m] += q.total
        if q.status == C.QuotationStatus.ACCEPTED:
            accepted += 1
            decided += 1
        elif q.status in {C.QuotationStatus.REJECTED, C.QuotationStatus.EXPIRED,
                          C.QuotationStatus.CANCELLED}:
            decided += 1

    actual, forecast, projected = _linear_forecast([float(v) for v in invoiced])
    ytd = _f(sum(invoiced, ZERO))
    top = sorted(by_customer.items(), key=lambda kv: kv[1], reverse=True)[:10]

    return {
        'year': yr,
        'currency': 'PHP',
        'months': MONTHS_SHORT,
        'invoiced_by_month': [_f(v) for v in invoiced],
        'invoice_count_by_month': inv_count,
        'collected_by_month': [_f(v) for v in collected],
        'pipeline_by_month': [_f(v) for v in pipeline],
        'quote_count_by_month': q_count,
        'forecast_by_month': [None if v is None else round(v, 2) for v in forecast],
        'ytd_invoiced': ytd,
        'ytd_collected': _f(sum(collected, ZERO)),
        'projected_year_invoiced': round(projected, 2),
        'win_rate_pct': round(accepted / decided * 100, 1) if decided else None,
        'ar_outstanding': _f(ar_outstanding),
        'ar_overdue': _f(ar_overdue),
        'ar_aging': {k: _f(v) for k, v in aging.items()},
        'top_customers': [{'customer': n, 'invoiced': _f(v)} for n, v in top],
        'chart': {
            'title': f'{yr} Invoiced Sales (PHP) — actual vs forecast',
            'labels': MONTHS_SHORT,
            'actual': [_f(v) for v in invoiced],
            'forecast': [None if v is None else round(v, 2) for v in forecast],
        },
    }


def production_year_snapshot(user=None, year=None) -> dict:
    """Production output in linear metres by profile / gauge / colour for a year,
    a headline LM trend + forecast, and the bended/days efficiency summary."""
    yr = _year(year)
    profile_m, gauge_m, color_m = _production_matrices(yr)
    total_months = [float(v) for v in gauge_m['total_row']['months']]
    actual, forecast, projected = _linear_forecast(total_months)

    def _rows(matrix, order):
        out = []
        for row in matrix['rows']:
            if row['total']:
                out.append({'label': row['label'], 'total_lm': _f(row['total'])})
        out.sort(key=lambda r: r['total_lm'], reverse=True)
        return out

    overall = _overall_summary(yr)
    overall_out = None
    if overall:
        overall_out = {
            r['label']: (None if r['total'] is None else _f(r['total']))
            for r in overall['rows']
        }

    return {
        'year': yr,
        'unit': 'linear metres (LM)',
        'months': MONTHS_SHORT,
        'lm_by_month': [_f(v) for v in total_months],
        'forecast_by_month': [None if v is None else round(v, 2) for v in forecast],
        'ytd_lm': _f(sum(total_months)),
        'projected_year_lm': round(projected, 2),
        'by_profile': _rows(profile_m, PROFILE_REPORT_ORDER),
        'by_gauge': _rows(gauge_m, GAUGE_ORDER),
        'by_color': _rows(color_m, COLOR_REPORT_ORDER),
        'efficiency_summary': overall_out,
        'chart': {
            'title': f'{yr} Production (LM) — actual vs forecast',
            'labels': MONTHS_SHORT,
            'actual': [_f(v) for v in total_months],
            'forecast': [None if v is None else round(v, 2) for v in forecast],
        },
    }


def inventory_snapshot(user=None) -> dict:
    """Coil stock: counts by status, remaining linear metres available, low /
    short coils, and finished-goods lots on hand."""
    coils = Coil.objects.select_related('item', 'warehouse')
    avail = coils.filter(status=C.CoilStatus.AVAILABLE)
    remaining = avail.aggregate(s=Sum('remaining_length_m'))['s'] or ZERO
    low = avail.filter(remaining_length_m__lte=LOW_STOCK_M).order_by('remaining_length_m')

    status_counts = {row['status']: row['n'] for row in
                     coils.values('status').annotate(n=Count('id'))}

    return {
        'total_coils': coils.count(),
        'available_coils': avail.count(),
        'remaining_lm_available': _f(remaining),
        'status_counts': status_counts,
        'low_stock_threshold_m': LOW_STOCK_M,
        'low_stock_coils': [
            {'coil': c.coil_number, 'item': str(c.item),
             'remaining_lm': _f(c.remaining_length_m),
             'warehouse': str(c.warehouse) if c.warehouse_id else None}
            for c in low[:20]
        ],
        'fg_lots_available': FinishedGoodsLot.objects.filter(
            status=C.FGLotStatus.AVAILABLE, qty_available__gt=0).count(),
    }


def customer_ar(user=None, customer_name=None) -> dict:
    """Outstanding receivables for one customer (fuzzy name match): open invoices
    with balances and overdue days."""
    if not customer_name:
        return {'error': 'customer_name is required.'}
    cust = (Customer.objects.filter(name__icontains=customer_name).first())
    if not cust:
        return {'error': f'No customer matching "{customer_name}".'}

    today = timezone.localdate()
    rows = []
    outstanding = ZERO
    invoices = (Invoice.objects.filter(customer=cust, status=C.InvoiceStatus.APPROVED)
                .prefetch_related('lines', 'payments'))
    for inv in invoices:
        bal = inv.balance
        if bal <= 0:
            continue
        outstanding += bal
        due = inv.due_date or inv.invoice_date
        overdue = (today - due).days if due else 0
        rows.append({
            'invoice': str(inv), 'total': _f(inv.total), 'paid': _f(inv.total_paid),
            'balance': _f(bal), 'overdue_days': max(overdue, 0),
        })
    rows.sort(key=lambda r: r['balance'], reverse=True)
    return {
        'customer': cust.name,
        'credit_limit': _f(getattr(cust, 'credit_limit', 0)),
        'outstanding': _f(outstanding),
        'open_invoices': rows[:30],
    }


def open_pipeline(user=None) -> dict:
    """Current sales funnel (quotations by status, with value) and open job orders
    by status -- the forward-looking demand view."""
    funnel = []
    for s in C.QuotationStatus:
        qs = Quotation.objects.filter(is_current=True, status=s.value)
        n = qs.count()
        if not n:
            continue
        value = sum((q.total for q in qs), ZERO)
        funnel.append({'status': s.label, 'count': n, 'value': _f(value)})

    jo_status = {}
    for row in (JobOrder.objects.exclude(status__in=[
            C.JobOrderStatus.CLOSED, C.JobOrderStatus.CANCELLED])
            .values('status').annotate(n=Count('id'))):
        label = dict(C.JobOrderStatus.choices).get(row['status'], row['status'])
        jo_status[label] = row['n']

    today = timezone.localdate()
    late = JobOrder.objects.filter(required_date__lt=today).exclude(status__in=[
        C.JobOrderStatus.COMPLETE, C.JobOrderStatus.CLOSED,
        C.JobOrderStatus.CANCELLED]).count()

    return {
        'quotation_funnel': funnel,
        'open_job_orders_by_status': jo_status,
        'late_job_orders': late,
    }


def schema_overview(user=None) -> dict:
    """What data exists and for which years -- lets the assistant discover new
    datasets (e.g. a freshly imported year) instead of assuming a fixed range."""
    inv_years = sorted({d.year for d in Invoice.objects.filter(
        status=C.InvoiceStatus.APPROVED).values_list('invoice_date', flat=True) if d},
        reverse=True)
    quote_years = sorted({d.year for d in Quotation.objects.values_list(
        'quote_date', flat=True) if d}, reverse=True)
    actual_years = sorted(set(ProductionActual.objects.values_list('year', flat=True)),
                          reverse=True)
    run_years = sorted({(o.run.ended_at or o.run.started_at or o.run.created_at).year
                        for o in ProductionRunOutput.objects.select_related('run')
                        if (o.run.ended_at or o.run.started_at or o.run.created_at)},
                       reverse=True)
    return {
        'today': timezone.localdate().isoformat(),
        'counts': {
            'customers': Customer.objects.count(),
            'quotations': Quotation.objects.count(),
            'invoices_approved': Invoice.objects.filter(
                status=C.InvoiceStatus.APPROVED).count(),
            'job_orders': JobOrder.objects.count(),
            'coils': Coil.objects.count(),
            'production_actual_rows': ProductionActual.objects.count(),
            'payments_verified': Payment.objects.filter(
                status=C.PaymentStatus.VERIFIED).count(),
        },
        'years_with_sales': inv_years,
        'years_with_quotes': quote_years,
        'years_with_production_actuals': actual_years,
        'years_with_live_production': run_years,
    }


# ---------------------------------------------------------------------------
# Registry + OpenAI tool schemas
# ---------------------------------------------------------------------------
def inventory_shortage_forecast(user=None) -> dict:
    """Open production demand (LM) vs available coil supply (LM) -- a directional
    shortage signal for upcoming manufacturing."""
    return _inv_forecast.forecast(user=user)


REGISTRY = {
    'sales_year_snapshot': sales_year_snapshot,
    'production_year_snapshot': production_year_snapshot,
    'inventory_snapshot': inventory_snapshot,
    'inventory_shortage_forecast': inventory_shortage_forecast,
    'customer_ar': customer_ar,
    'open_pipeline': open_pipeline,
    'schema_overview': schema_overview,
}

_YEAR_PROP = {
    'type': 'object',
    'properties': {
        'year': {'type': 'integer',
                 'description': 'Calendar year. Defaults to the current year.'},
    },
}

TOOL_SPECS = [
    {'type': 'function', 'function': {
        'name': 'schema_overview',
        'description': ('List what data exists and which years have sales, quotes '
                        'and production. Call this first if unsure what years or '
                        'datasets are available.'),
        'parameters': {'type': 'object', 'properties': {}},
    }},
    {'type': 'function', 'function': {
        'name': 'sales_year_snapshot',
        'description': ('Monthly invoiced sales, collections, quotation pipeline, a '
                        'linear forecast to year end, AR aging, and top customers '
                        'for a year.'),
        'parameters': _YEAR_PROP,
    }},
    {'type': 'function', 'function': {
        'name': 'production_year_snapshot',
        'description': ('Production output in linear metres by profile, gauge and '
                        'colour, with a monthly trend + forecast and efficiency '
                        'summary for a year.'),
        'parameters': _YEAR_PROP,
    }},
    {'type': 'function', 'function': {
        'name': 'inventory_snapshot',
        'description': ('Current coil stock by status, remaining linear metres '
                        'available, low/short coils, and finished-goods on hand.'),
        'parameters': {'type': 'object', 'properties': {}},
    }},
    {'type': 'function', 'function': {
        'name': 'inventory_shortage_forecast',
        'description': ('Directional coil shortage outlook: open production demand '
                        'in LM vs available coil supply in LM, with coverage ratio.'),
        'parameters': {'type': 'object', 'properties': {}},
    }},
    {'type': 'function', 'function': {
        'name': 'customer_ar',
        'description': 'Outstanding receivables and open invoices for one customer.',
        'parameters': {
            'type': 'object',
            'properties': {
                'customer_name': {'type': 'string',
                                  'description': 'Full or partial customer name.'},
            },
            'required': ['customer_name'],
        },
    }},
    {'type': 'function', 'function': {
        'name': 'open_pipeline',
        'description': ('Current quotation funnel (by status, with value) and open '
                        'job orders by status, plus late job orders.'),
        'parameters': {'type': 'object', 'properties': {}},
    }},
]


def run_tool(name: str, arguments: dict, user=None) -> dict:
    """Dispatch a tool call by name. Unknown tools return an error dict rather
    than raising, so the model can recover gracefully."""
    fn = REGISTRY.get(name)
    if fn is None:
        return {'error': f'Unknown tool: {name}'}
    try:
        return fn(user=user, **(arguments or {}))
    except TypeError as e:
        return {'error': f'Bad arguments for {name}: {e}'}
    except Exception as e:  # noqa: BLE001 - surface tool errors to the model
        return {'error': f'{name} failed: {e}'}
