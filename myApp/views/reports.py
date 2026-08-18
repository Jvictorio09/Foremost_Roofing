from decimal import Decimal

from django.db.models import Count, Sum
from django.shortcuts import render
from django.utils import timezone

from .. import constants as C
from ..models import (
    Coil, Color, FinishedGoodsLot, Invoice, JobOrder, ProductionActual,
    ProductionRunOutput, Profile, ProfileAlias, Quotation, StockBalance,
)
from ..rbac import has_any, permission_required
from .common import money

ZERO = Decimal('0')

MONTHS = ['JANUARY', 'FEBRUARY', 'MARCH', 'APRIL', 'MAY', 'JUNE', 'JULY',
          'AUGUST', 'SEPTEMBER', 'OCTOBER', 'NOVEMBER', 'DECEMBER']
MONTHS_SHORT = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep',
                'Oct', 'Nov', 'Dec']

# Canonical report taxonomy, matching the company's official spreadsheet. Rows
# always appear in this order so the report keeps its familiar shape; live data
# and imported actuals map onto these labels (case-insensitively).
PROFILE_REPORT_ORDER = ['5-Rib', '8-Rib', 'Corrugated', 'Monaco Tile',
                        'Milazzo Tile', 'Cladding', 'Spandrel', 'Deck 16',
                        'Deck 24', 'North Steel', 'NS Wood Grain-Spandrel']
GAUGE_ORDER = ['0.35mm', '0.40mm', '0.50mm', '0.60mm', '0.75mm (galv)',
               '0.80mm (galv)', '1.00mm (galv)', '.35mm (spandrel)',
               '.4mm (spandrel)']
COLOR_REPORT_ORDER = ['RED', 'GREEN', 'BROWN', 'MANDARIN RED', 'BLUE', 'WHITE',
                      'GRAY', 'BEIGE', 'TERRACOTTA', 'OFF WHITE', 'BRICK ORANGE',
                      'DARK WOOD', 'LIGHT WOOD', 'OCEAN BLUE', 'PALM GREEN']
COLOR_HEX = {
    'RED': '#c0392b', 'GREEN': '#2e7d32', 'BROWN': '#8d6e63', 'MANDARIN RED': '#e64a19',
    'BLUE': '#1e63c9', 'WHITE': '#f5f5f5', 'GRAY': '#9e9e9e', 'BEIGE': '#d8c9a3',
    'TERRACOTTA': '#c1502e', 'OFF WHITE': '#eceff1', 'BRICK ORANGE': '#d35400',
    'DARK WOOD': '#5d4037', 'LIGHT WOOD': '#b78a5f', 'OCEAN BLUE': '#1565c0',
    'PALM GREEN': '#558b2f',
}


@permission_required('report.sales', 'report.production', 'report.inventory', 'report.management')
def report_hub(request):
    user = request.user
    today = timezone.localdate()
    reports = []

    if has_any(user, 'report.sales'):
        quotes = Quotation.objects.filter(is_current=True)
        total = quotes.exclude(status=C.QuotationStatus.DRAFT).count()
        accepted = quotes.filter(status=C.QuotationStatus.ACCEPTED).count()
        conv = f'{(accepted / total * 100):.0f}%' if total else '-'
        reports.append({
            'label': 'Sales', 'url': 'report_sales', 'icon': 'file',
            'desc': 'Quotations, conversion, sales by customer',
            'stats': [
                {'label': 'Current Quotes', 'value': quotes.count()},
                {'label': 'Accepted', 'value': accepted, 'tone': 'green'},
                {'label': 'Conversion', 'value': conv, 'tone': 'blue'},
                {'label': 'Invoiced', 'value': Invoice.objects.count(), 'tone': 'blue'},
            ],
        })

    if has_any(user, 'report.production'):
        jos = JobOrder.objects.all()
        out = ProductionRunOutput.objects.aggregate(
            good=Sum('good_qty'), scrap=Sum('scrap_qty'))
        good, scrap = out['good'] or ZERO, out['scrap'] or ZERO
        scrap_pct = f'{(scrap/(good+scrap)*100):.1f}%' if (good + scrap) else '-'
        late = jos.filter(required_date__lt=today).exclude(status__in=[
            C.JobOrderStatus.COMPLETE, C.JobOrderStatus.CLOSED,
            C.JobOrderStatus.CANCELLED]).count()
        reports.append({
            'label': 'Production', 'url': 'report_production', 'icon': 'hammer',
            'desc': 'Output by profile / gauge / colour, job orders, scrap',
            'stats': [
                {'label': 'In Progress', 'value': jos.filter(
                    status=C.JobOrderStatus.IN_PROGRESS).count(), 'tone': 'blue'},
                {'label': 'Good Output (LM)', 'value': money(good), 'tone': 'green'},
                {'label': 'Scrap %', 'value': scrap_pct, 'tone': 'red'},
                {'label': 'Late JOs', 'value': late, 'tone': 'red'},
            ],
        })

    if has_any(user, 'report.inventory'):
        coils = Coil.objects.all()
        avail = coils.filter(status=C.CoilStatus.AVAILABLE)
        remaining = avail.aggregate(s=Sum('remaining_length_m'))['s'] or ZERO
        low = coils.filter(status=C.CoilStatus.AVAILABLE,
                           remaining_length_m__lte=50).count()
        reports.append({
            'label': 'Inventory', 'url': 'report_inventory', 'icon': 'box',
            'desc': 'Coils, remaining length, reserved, low stock',
            'stats': [
                {'label': 'Total Coils', 'value': coils.count()},
                {'label': 'Available', 'value': avail.count(), 'tone': 'green'},
                {'label': 'Remaining LM', 'value': money(remaining)},
                {'label': 'Low / Short', 'value': low, 'tone': 'yellow'},
            ],
        })

    if has_any(user, 'report.management'):
        inv = Invoice.objects.filter(status=C.InvoiceStatus.APPROVED)
        sales_total = sum((i.total for i in inv), ZERO)
        inv_value = sum(
            (b.qty_on_hand * (b.item.standard_cost or ZERO)
             for b in StockBalance.objects.select_related('item')), ZERO)
        reports.append({
            'label': 'Management', 'url': 'report_management', 'icon': 'chart',
            'desc': 'Sales vs production, inventory value',
            'stats': [
                {'label': 'Approved Sales', 'value': money(sales_total), 'tone': 'green'},
                {'label': 'Open JOs', 'value': JobOrder.objects.exclude(status__in=[
                    C.JobOrderStatus.CLOSED, C.JobOrderStatus.CANCELLED]).count(),
                 'tone': 'blue'},
                {'label': 'Inventory Value', 'value': money(inv_value)},
                {'label': 'FG On Hand', 'value': FinishedGoodsLot.objects.filter(
                    qty_available__gt=0).count(), 'tone': 'blue'},
            ],
        })

    return render(request, 'reports/hub.html', {'reports': reports})


def _person_name(user):
    if not user:
        return 'Unassigned'
    return user.get_full_name() or user.username


@permission_required('report.sales')
def report_sales(request):
    import json
    today = timezone.localdate()
    try:
        year = int(request.GET.get('year') or today.year)
    except (TypeError, ValueError):
        year = today.year

    quotes = (Quotation.objects.filter(is_current=True)
              .select_related('customer', 'salesperson'))
    invoices = (Invoice.objects.select_related('customer', 'tax_code')
                .prefetch_related('lines', 'lines__item', 'payments'))

    yrs = {q.quote_date.year for q in quotes if q.quote_date}
    yrs |= {i.invoice_date.year for i in invoices if i.invoice_date}
    years = sorted(yrs | {year, today.year, 2026}, reverse=True)

    # --- Monthly series -----------------------------------------------------
    invoiced = [ZERO] * 12       # approved invoice value = booked sales
    inv_count = [0] * 12
    pipeline = [ZERO] * 12       # quotation value = incoming demand
    q_count = [0] * 12
    accepted_cnt = [0] * 12
    collected = [ZERO] * 12      # verified payments received

    by_customer = {}             # name -> {value, count}
    by_person = {}               # name -> counters
    by_product = {}              # name -> {qty, value}
    funnel = {s.value: {'label': s.label, 'count': 0, 'value': ZERO}
              for s in C.QuotationStatus}
    dead_q = {C.QuotationStatus.CANCELLED, C.QuotationStatus.REJECTED,
              C.QuotationStatus.EXPIRED, C.QuotationStatus.DRAFT}

    # Quotations -------------------------------------------------------------
    for q in quotes:
        if not q.quote_date or q.quote_date.year != year:
            continue
        val = q.total
        f = funnel.get(q.status)
        if f:
            f['count'] += 1
            f['value'] += val
        person = _person_name(q.salesperson)
        p = by_person.setdefault(person, {
            'q_count': 0, 'q_val': ZERO, 'accepted': 0, 'lost': 0, 'inv_val': ZERO})
        p['q_count'] += 1
        p['q_val'] += val
        if q.status == C.QuotationStatus.ACCEPTED:
            p['accepted'] += 1
            accepted_cnt[q.quote_date.month - 1] += 1
        elif q.status in {C.QuotationStatus.REJECTED, C.QuotationStatus.EXPIRED,
                          C.QuotationStatus.CANCELLED}:
            p['lost'] += 1
        if q.status != C.QuotationStatus.DRAFT:
            m = q.quote_date.month - 1
            q_count[m] += 1
            pipeline[m] += val

    # Invoices (approved = booked) + product mix ----------------------------
    approved = C.InvoiceStatus.APPROVED
    for inv in invoices:
        if inv.status == approved and inv.invoice_date and inv.invoice_date.year == year:
            m = inv.invoice_date.month - 1
            tot = inv.total
            invoiced[m] += tot
            inv_count[m] += 1
            c = by_customer.setdefault(inv.customer.name, {'value': ZERO, 'count': 0})
            c['value'] += tot
            c['count'] += 1
            for line in inv.lines.all():
                name = (line.item.name if line.item else None) or line.description or 'Misc'
                pr = by_product.setdefault(name, {'qty': ZERO, 'value': ZERO})
                pr['qty'] += line.quantity or ZERO
                pr['value'] += line.line_total
        # Collections: verified payments received in the selected year.
        for pay in inv.payments.all():
            if pay.status == C.PaymentStatus.VERIFIED and pay.received_at and \
                    pay.received_at.year == year:
                collected[pay.received_at.month - 1] += pay.amount

    # --- Accounts receivable (current snapshot, all approved invoices) ------
    ar_outstanding = ZERO
    ar_overdue = ZERO
    aging = {'current': ZERO, 'b1_30': ZERO, 'b31_60': ZERO, 'b60p': ZERO}
    outstanding_rows = []
    for inv in invoices:
        if inv.status != approved:
            continue
        bal = inv.balance
        if bal <= 0:
            continue
        ar_outstanding += bal
        due = inv.due_date or inv.invoice_date
        overdue_days = (today - due).days if due else 0
        if overdue_days > 0:
            ar_overdue += bal
            if overdue_days <= 30:
                aging['b1_30'] += bal
            elif overdue_days <= 60:
                aging['b31_60'] += bal
            else:
                aging['b60p'] += bal
        else:
            aging['current'] += bal
        outstanding_rows.append({
            'customer': inv.customer.name, 'number': str(inv),
            'total': inv.total, 'paid': inv.total_paid, 'balance': bal,
            'due': due, 'overdue_days': max(overdue_days, 0),
        })
    outstanding_rows.sort(key=lambda r: r['balance'], reverse=True)

    # --- Headline numbers ---------------------------------------------------
    actual, forecast, projected = _linear_forecast([float(v) for v in invoiced])
    ytd = sum(invoiced, ZERO)
    ytd_collected = sum(collected, ZERO)
    total_inv = sum(inv_count)
    avg_inv = (ytd / total_inv) if total_inv else ZERO
    won = sum(accepted_cnt)
    decided = won + sum(v['lost'] for v in by_person.values())
    win_rate = f'{(won / decided * 100):.0f}%' if decided else '-'
    quotes_year = sum(q_count)

    cards = [
        {'label': f'{year} Invoiced', 'value': money(ytd), 'tone': 'green'},
        {'label': f'{year} Collected', 'value': money(ytd_collected), 'tone': 'green'},
        {'label': 'Outstanding AR', 'value': money(ar_outstanding), 'tone': 'red'},
        {'label': 'Overdue AR', 'value': money(ar_overdue), 'tone': 'red'},
        {'label': 'Pipeline (Quotes)', 'value': money(sum(pipeline, ZERO)), 'tone': 'yellow'},
        {'label': 'Projected Year', 'value': money(Decimal(str(round(projected, 2)))), 'tone': 'blue'},
        {'label': 'Win Rate', 'value': win_rate, 'tone': 'blue'},
        {'label': 'Avg Invoice', 'value': money(avg_inv)},
    ]

    charts = {
        'labels': MONTHS_SHORT,
        'invoiced': {'actual': actual, 'forecast': forecast},
        'collected': [float(v) for v in collected],
        'pipeline': [float(v) for v in pipeline],
    }

    # --- Monthly performance matrix ----------------------------------------
    monthly_rows = []
    for i, mo in enumerate(MONTHS_SHORT):
        conv = f'{(accepted_cnt[i] / q_count[i] * 100):.0f}%' if q_count[i] else '-'
        monthly_rows.append({
            'month': mo, 'q_count': q_count[i], 'q_val': pipeline[i],
            'inv_count': inv_count[i], 'inv_val': invoiced[i],
            'collected': collected[i], 'conv': conv,
        })
    conv_tot = f'{(won / quotes_year * 100):.0f}%' if quotes_year else '-'
    monthly_total = {
        'q_count': quotes_year, 'q_val': sum(pipeline, ZERO),
        'inv_count': total_inv, 'inv_val': ytd,
        'collected': ytd_collected, 'conv': conv_tot,
    }

    # --- Breakdown tables (ranked) -----------------------------------------
    cust_rows = sorted(by_customer.items(), key=lambda kv: kv[1]['value'], reverse=True)[:12]
    cust_table = [{
        'name': n, 'count': d['count'], 'value': d['value'],
        'pct': (float(d['value']) / float(ytd) * 100) if ytd else 0,
    } for n, d in cust_rows]

    person_rows = sorted(by_person.items(), key=lambda kv: kv[1]['q_val'], reverse=True)
    person_table = [{
        'name': n, 'q_count': d['q_count'], 'q_val': d['q_val'],
        'accepted': d['accepted'],
        'win': (f"{(d['accepted'] / (d['accepted'] + d['lost']) * 100):.0f}%"
                if (d['accepted'] + d['lost']) else '-'),
    } for n, d in person_rows]

    prod_rows = sorted(by_product.items(), key=lambda kv: kv[1]['value'], reverse=True)[:12]
    product_table = [{'name': n, 'qty': d['qty'], 'value': d['value']}
                     for n, d in prod_rows]

    funnel_order = [C.QuotationStatus.DRAFT, C.QuotationStatus.PENDING_APPROVAL,
                    C.QuotationStatus.APPROVED, C.QuotationStatus.SENT,
                    C.QuotationStatus.ACCEPTED, C.QuotationStatus.REJECTED,
                    C.QuotationStatus.EXPIRED, C.QuotationStatus.CANCELLED]
    funnel_max = max((funnel[s]['count'] for s in funnel), default=0) or 1
    funnel_rows = [{
        'label': funnel[s]['label'], 'count': funnel[s]['count'],
        'value': funnel[s]['value'], 'status': s,
        'pct': funnel[s]['count'] / funnel_max * 100,
    } for s in funnel_order]

    return render(request, 'reports/sales.html', {
        'title': 'Sales Report', 'cards': cards,
        'year': year, 'years': years,
        'charts_json': json.dumps(charts),
        'monthly_rows': monthly_rows, 'monthly_total': monthly_total,
        'funnel_rows': funnel_rows,
        'ar': {
            'outstanding': ar_outstanding, 'overdue': ar_overdue,
            'count': len(outstanding_rows), 'aging': aging,
        },
        'outstanding_rows': outstanding_rows[:12],
        'cust_table': cust_table,
        'person_table': person_table,
        'product_table': product_table,
    })


def _gauge_label(item):
    """Human gauge label like the production report ('0.40mm', '0.50mm')."""
    t = item.thickness_mm
    if t is None:
        return 'Unspecified'
    label = f'{t:.2f}mm'
    finish = (item.finish or '').lower()
    cat = (getattr(item.category, 'code', '') or '').upper()
    if 'galv' in finish or 'gi' in finish:
        label += ' (galv)'
    elif 'SPANDREL' in cat or 'spandrel' in (item.style or '').lower():
        label += ' (spandrel)'
    return label


def _blank_year(labels):
    return {lbl: [ZERO] * 12 for lbl in labels}


def _build_matrix(title, cell_map, order, *, weight_map=None):
    """Turn ``{label: [12 monthly values]}`` into a render-ready matrix that
    mirrors the spreadsheet: a Total column (+ optional Tons/weight), a row per
    label, and a grand-total row across the bottom."""
    rows, col_totals, grand_total, tons_total = [], [ZERO] * 12, ZERO, ZERO
    for label in order:
        months = cell_map.get(label, [ZERO] * 12)
        total = sum(months, ZERO)
        tons = (weight_map or {}).get(label, ZERO)
        rows.append({'label': label, 'total': total, 'tons': tons, 'months': months})
        for i, v in enumerate(months):
            col_totals[i] += v
        grand_total += total
        tons_total += tons
    return {
        'title': title,
        'show_tons': weight_map is not None,
        'months': MONTHS,
        'rows': rows,
        'total_row': {'total': grand_total, 'tons': tons_total, 'months': col_totals},
    }


def _canon(order):
    """Case-insensitive lookup {label.lower(): canonical label}."""
    return {lbl.lower(): lbl for lbl in order}


def _production_matrices(year):
    """Build the three matrices of the official production report (Profile,
    Gauge + tons, Colour), merging live production output with imported
    historical actuals, all in linear metres per month."""
    profiles = _blank_year(PROFILE_REPORT_ORDER)
    gauges = _blank_year(GAUGE_ORDER)
    colors = _blank_year(COLOR_REPORT_ORDER)
    gauge_weight = {}
    prof_lookup = _canon(PROFILE_REPORT_ORDER)
    color_lookup = _canon(COLOR_REPORT_ORDER)

    # 1) Live production output for the year.
    alias = {a.profile_id: a.alias for a in
             ProfileAlias.objects.filter(context='production_report')}
    outputs = (ProductionRunOutput.objects
               .filter(good_qty__gt=0)
               .select_related('run', 'job_order_line__item__profile',
                               'job_order_line__item__color',
                               'job_order_line__item__category'))
    for o in outputs:
        run = o.run
        when = run.ended_at or run.started_at or run.created_at
        if not when or when.year != year:
            continue
        m = when.month - 1
        item = o.job_order_line.item
        lm = o.good_qty or ZERO

        if item and item.profile_id:
            raw = alias.get(item.profile_id, item.profile.name)
        else:
            raw = 'Other / Accessories'
        pkey = prof_lookup.get(raw.lower(), raw)
        profiles.setdefault(pkey, [ZERO] * 12)[m] += lm

        gkey = _gauge_label(item) if item else 'Unspecified'
        gauges.setdefault(gkey, [ZERO] * 12)[m] += lm
        factor = (item.weight_factor_kg_per_lm if item else None) or ZERO
        gauge_weight[gkey] = gauge_weight.get(gkey, ZERO) + lm * factor

        raw_c = item.color.name if (item and item.color_id) else 'Uncoloured'
        ckey = color_lookup.get(raw_c.lower(), raw_c)
        colors.setdefault(ckey, [ZERO] * 12)[m] += lm

    # 2) Imported historical actuals for the year.
    for pa in ProductionActual.objects.filter(year=year):
        m = pa.month - 1
        if not 0 <= m < 12:
            continue
        if pa.dimension == ProductionActual.Dimension.PROFILE:
            key = prof_lookup.get(pa.category.lower(), pa.category)
            profiles.setdefault(key, [ZERO] * 12)[m] += pa.lm
        elif pa.dimension == ProductionActual.Dimension.GAUGE:
            gauges.setdefault(pa.category, [ZERO] * 12)[m] += pa.lm
            gauge_weight[pa.category] = gauge_weight.get(pa.category, ZERO) + pa.weight_kg
        elif pa.dimension == ProductionActual.Dimension.COLOR:
            key = color_lookup.get(pa.category.lower(), pa.category)
            colors.setdefault(key, [ZERO] * 12)[m] += pa.lm

    prof_order = PROFILE_REPORT_ORDER + [k for k in profiles if k not in PROFILE_REPORT_ORDER]
    gauge_order = GAUGE_ORDER + [k for k in gauges if k not in GAUGE_ORDER]
    col_order = COLOR_REPORT_ORDER + [k for k in colors if k not in COLOR_REPORT_ORDER]

    color_matrix = _build_matrix('Color (in LM)', colors, col_order)
    # Swatches: prefer the Colour master's hex, fall back to the report palette.
    master_hex = {c.name.upper(): c.hex_value for c in Color.objects.all() if c.hex_value}
    for row in color_matrix['rows']:
        row['swatch'] = master_hex.get(row['label'].upper()) or COLOR_HEX.get(row['label'].upper())

    return [
        _build_matrix('PROFILE (in LM)', profiles, prof_order),
        _build_matrix('GAUGE (in LM)', gauges, gauge_order, weight_map=gauge_weight),
        color_matrix,
    ]


def _overall_summary(year):
    """The bottom 'overall' block: No. of Bended, No. of Days and the derived
    Average Daily (bended / days), per month with a Total column."""
    bended = [ZERO] * 12
    days = [ZERO] * 12
    for pa in ProductionActual.objects.filter(
            year=year, dimension=ProductionActual.Dimension.SUMMARY):
        m = pa.month - 1
        if not 0 <= m < 12:
            continue
        if pa.category.lower().startswith('no. of bended') or pa.category.lower() == 'bended':
            bended[m] += pa.lm
        elif 'day' in pa.category.lower():
            days[m] += pa.lm
    if not any(bended) and not any(days):
        return None
    avg = [(bended[i] / days[i]) if days[i] else None for i in range(12)]
    tot_bended = sum(bended, ZERO)
    tot_days = sum(days, ZERO)
    tot_avg = (tot_bended / tot_days) if tot_days else None
    return {
        'months': MONTHS,
        'rows': [
            {'label': 'No. of Bended', 'total': tot_bended, 'values': bended, 'int': True},
            {'label': 'No. of Days', 'total': tot_days, 'values': days, 'int': True},
            {'label': 'Average Daily', 'total': tot_avg, 'values': avg, 'int': False},
        ],
    }


def _linear_forecast(values):
    """Least-squares trend over the leading months that have data, projected to
    year end. Returns (actual_series, forecast_series, projected_year_total)
    where each series is 12-long with ``None`` outside its own region."""
    vals = [float(v or 0) for v in values]
    points = [(i, v) for i, v in enumerate(vals) if v > 0]
    if len(points) < 2:
        return vals, [None] * 12, sum(vals)
    n = len(points)
    sx = sum(x for x, _ in points)
    sy = sum(y for _, y in points)
    sxx = sum(x * x for x, _ in points)
    sxy = sum(x * y for x, y in points)
    denom = (n * sxx - sx * sx) or 1
    slope = (n * sxy - sx * sy) / denom
    intercept = (sy - slope * sx) / n
    last = max(i for i, _ in points)

    actual = [vals[i] if i <= last else None for i in range(12)]
    forecast = [None] * 12
    forecast[last] = vals[last]  # anchor the dashed line to the last actual
    projected_total = sum(v for v in vals[:last + 1])
    for i in range(last + 1, 12):
        pred = max(0.0, intercept + slope * i)
        forecast[i] = round(pred, 2)
        projected_total += pred
    return actual, forecast, projected_total


@permission_required('report.production')
def report_production(request):
    import json
    today = timezone.localdate()
    jos = JobOrder.objects.all()

    # Year selector: requested year plus any years that have runs or actuals.
    try:
        year = int(request.GET.get('year') or today.year)
    except (TypeError, ValueError):
        year = today.year
    run_years = {
        (r.ended_at or r.started_at or r.created_at).year
        for r in ProductionRunOutput.objects.select_related('run')
        if (r.run.ended_at or r.run.started_at or r.run.created_at)}
    actual_years = set(ProductionActual.objects.values_list('year', flat=True))
    years = sorted(run_years | actual_years | {year, today.year, 2026}, reverse=True)

    matrices = _production_matrices(year)
    profile_m, gauge_m, color_m = matrices

    # --- Charts: headline trend + forecast, and profile breakdown ----------
    total_months = [float(v) for v in gauge_m['total_row']['months']]
    actual, forecast, projected = _linear_forecast(total_months)
    top_profiles = sorted(profile_m['rows'], key=lambda r: r['total'], reverse=True)[:5]
    palette = ['#2563eb', '#059669', '#d97706', '#dc2626', '#7c3aed']
    charts = {
        'labels': MONTHS_SHORT,
        'trend': {'actual': actual, 'forecast': forecast},
        'profiles': [
            {'label': r['label'], 'data': [float(v) for v in r['months']],
             'color': palette[i % len(palette)]}
            for i, r in enumerate(top_profiles) if r['total']
        ],
    }

    out = ProductionRunOutput.objects.aggregate(good=Sum('good_qty'), scrap=Sum('scrap_qty'))
    live_good = out['good'] or ZERO
    scrap = out['scrap'] or ZERO
    scrap_pct = f'{(scrap/(live_good+scrap)*100):.1f}%' if (live_good + scrap) else '-'
    ytd = sum(total_months)
    cards = [
        {'label': f'{year} Output (LM)', 'value': money(Decimal(str(ytd))), 'tone': 'green'},
        {'label': 'Projected Year (LM)', 'value': money(Decimal(str(round(projected, 2)))),
         'tone': 'blue'},
        {'label': 'In Progress', 'value': jos.filter(
            status=C.JobOrderStatus.IN_PROGRESS).count(), 'tone': 'blue'},
        {'label': 'Scrap %', 'value': scrap_pct, 'tone': 'red'},
    ]
    return render(request, 'reports/production.html', {
        'title': 'Production Report', 'cards': cards,
        'year': year, 'years': years,
        'matrices': matrices,
        'overall': _overall_summary(year),
        'charts_json': json.dumps(charts),
    })


@permission_required('report.inventory')
def report_inventory(request):
    coils = Coil.objects.all()
    low = coils.filter(status=C.CoilStatus.AVAILABLE, remaining_length_m__lte=50)
    reserved = StockBalance.objects.filter(qty_reserved__gt=0).select_related('item', 'warehouse')
    cards = [
        {'label': 'Total Coils', 'value': coils.count()},
        {'label': 'Available', 'value': coils.filter(status=C.CoilStatus.AVAILABLE).count(), 'tone': 'green'},
        {'label': 'Remaining LM (avail.)', 'value': money(
            coils.filter(status=C.CoilStatus.AVAILABLE).aggregate(s=Sum('remaining_length_m'))['s'] or 0)},
        {'label': 'Low / Short', 'value': low.count(), 'tone': 'yellow'},
    ]
    return render(request, 'reports/table.html', {
        'title': 'Inventory Report', 'cards': cards,
        'tables': [
            {'title': 'Low / Short Coils',
             'head': ['Coil', 'Item', 'Remaining LM', 'Warehouse'],
             'rows': [[c.coil_number, str(c.item), c.remaining_length_m, str(c.warehouse)]
                      for c in low[:20]]},
            {'title': 'Reserved Stock',
             'head': ['Item', 'Warehouse', 'Reserved'],
             'rows': [[str(b.item), str(b.warehouse), b.qty_reserved] for b in reserved[:20]]},
        ],
    })


@permission_required('report.management')
def report_management(request):
    inv = Invoice.objects.filter(status=C.InvoiceStatus.APPROVED)
    sales_total = sum((i.total for i in inv), ZERO)
    inv_value = sum(
        (b.qty_on_hand * (b.item.standard_cost or ZERO)
         for b in StockBalance.objects.select_related('item')), ZERO)
    cards = [
        {'label': 'Approved Sales', 'value': money(sales_total), 'tone': 'green'},
        {'label': 'Open Job Orders', 'value': JobOrder.objects.exclude(status__in=[
            C.JobOrderStatus.CLOSED, C.JobOrderStatus.CANCELLED]).count(), 'tone': 'blue'},
        {'label': 'Inventory Value', 'value': money(inv_value)},
        {'label': 'FG Lots On Hand', 'value': FinishedGoodsLot.objects.filter(
            qty_available__gt=0).count(), 'tone': 'blue'},
    ]
    return render(request, 'reports/table.html', {
        'title': 'Management Overview', 'cards': cards, 'tables': []})
