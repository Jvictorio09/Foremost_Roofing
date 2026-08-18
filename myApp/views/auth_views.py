from django.contrib.auth.decorators import login_required
from django.contrib.auth.views import LoginView as DjangoLoginView
from django.db.models import Q
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils import timezone

from .. import constants as C
from ..forms import LoginForm
from ..models import (
    Coil, Customer, Delivery, FinishedGoodsLot, Invoice, JobOrder, Quotation,
    StockBalance,
)
from ..rbac import has_any
from .common import money


class LoginView(DjangoLoginView):
    template_name = 'auth/login.html'
    authentication_form = LoginForm
    redirect_authenticated_user = True


def landing(request):
    """Public marketing landing page. Authenticated staff are sent straight to
    their dashboard so they don't have to click through the brochure site."""
    if request.user.is_authenticated:
        return redirect('dashboard')
    return render(request, 'foremost_glory_single_file.html')


_PRIORITY_RANK = {'urgent': 0, 'high': 1, 'normal': 2, 'low': 3}


def _production_queue(today):
    """Actionable, at-a-glance work list for the production team: every active job
    order with its priority, due date, release-gate blockers and build progress."""
    from datetime import timedelta
    active = (JobOrder.objects.select_related('customer')
              .prefetch_related('lines')
              .filter(status__in=[
                  C.JobOrderStatus.PENDING_RELEASE, C.JobOrderStatus.RELEASED,
                  C.JobOrderStatus.IN_PROGRESS, C.JobOrderStatus.PARTIALLY_COMPLETE,
                  C.JobOrderStatus.ON_HOLD]))
    soon = today + timedelta(days=3)
    rows = []
    for jo in active:
        lines = list(jo.lines.all())
        total = sum((l.quantity for l in lines), 0)
        made = sum((l.qty_produced for l in lines), 0)
        pct = int(made / total * 100) if total else 0
        gates = []
        if jo.drawing_pending:
            gates.append('Drawing')
        if jo.credit_hold:
            gates.append('Credit')
        if jo.material_short:
            gates.append('Material')
        late = bool(jo.required_date and jo.required_date < today
                    and jo.status != C.JobOrderStatus.COMPLETE)
        due_soon = bool(jo.required_date and today <= jo.required_date <= soon)
        rows.append({
            'pk': jo.pk, 'number': jo.number or f'JO-{jo.pk}',
            'customer': jo.customer.name, 'status': jo.status,
            'status_label': jo.get_status_display(),
            'priority': jo.priority, 'priority_label': jo.get_priority_display(),
            'required_date': jo.required_date, 'late': late, 'due_soon': due_soon,
            'gates': gates, 'blocked': bool(gates),
            'lines': len(lines), 'pct': pct,
            'made': made, 'total': total,
        })
    rows.sort(key=lambda r: (
        not r['late'], not r['blocked'],
        _PRIORITY_RANK.get(r['priority'], 9),
        r['required_date'] or today.replace(year=today.year + 5)))
    return rows


@login_required
def dashboard(request):
    user = request.user
    today = timezone.localdate()
    sections = []
    highlights = []
    production_queue = []

    if has_any(user, 'quotation.view', 'quotation.create', 'report.sales'):
        quotes = Quotation.objects.filter(is_current=True)
        accepted = quotes.filter(status=C.QuotationStatus.ACCEPTED).count()
        total = quotes.exclude(status=C.QuotationStatus.DRAFT).count()
        conv = f'{(accepted / total * 100):.0f}%' if total else '-'
        open_q = quotes.exclude(
            status__in=[C.QuotationStatus.ACCEPTED, C.QuotationStatus.REJECTED,
                        C.QuotationStatus.CANCELLED, C.QuotationStatus.EXPIRED]).count()
        pending_q = quotes.filter(status=C.QuotationStatus.PENDING_APPROVAL).count()
        sections.append({
            'title': 'Sales', 'icon': 'file', 'cards': [
                {'label': 'Open Quotations', 'value': open_q, 'key': 'quotes_open'},
                {'label': 'Pending Approval', 'value': pending_q, 'tone': 'yellow',
                 'key': 'quotes_pending'},
                {'label': 'Accepted', 'value': accepted, 'tone': 'green', 'key': 'quotes_accepted'},
                {'label': 'Conversion', 'value': conv, 'tone': 'blue', 'key': 'quotes_accepted'},
            ],
        })
        if pending_q:
            highlights.append({'label': 'Quotations to approve', 'value': pending_q,
                               'tone': 'yellow', 'key': 'quotes_pending'})

    if has_any(user, 'invoice.view', 'payment.record'):
        inv = Invoice.objects.all()
        outstanding = sum((i.balance for i in inv.filter(
            status=C.InvoiceStatus.APPROVED)), 0)
        unpaid = inv.filter(payment_state=C.PaymentState.UNPAID).count()
        sections.append({
            'title': 'Billing', 'icon': 'wallet', 'cards': [
                {'label': 'For Approval', 'value': inv.filter(
                    status=C.InvoiceStatus.PENDING_APPROVAL).count(), 'tone': 'yellow',
                 'key': 'inv_approval'},
                {'label': 'Approved', 'value': inv.filter(
                    status=C.InvoiceStatus.APPROVED).count(), 'tone': 'blue', 'key': 'inv_approved'},
                {'label': 'Unpaid', 'value': unpaid, 'tone': 'red', 'key': 'inv_unpaid'},
                {'label': 'Outstanding', 'value': money(outstanding), 'tone': 'red',
                 'key': 'inv_outstanding'},
            ],
        })
        if outstanding:
            highlights.append({'label': 'Outstanding balance', 'value': money(outstanding),
                               'tone': 'red', 'key': 'inv_outstanding'})

    if has_any(user, 'job_order.view', 'production.view', 'report.production'):
        jos = JobOrder.objects.all()
        production_queue = _production_queue(today)
        late = sum(1 for r in production_queue if r['late'])
        blocked = sum(1 for r in production_queue if r['blocked'])
        due_soon = sum(1 for r in production_queue if r['due_soon'] and not r['late'])
        sections.append({
            'title': 'Production', 'icon': 'hammer', 'cards': [
                {'label': 'Pending Release', 'value': jos.filter(
                    status=C.JobOrderStatus.PENDING_RELEASE).count(), 'tone': 'yellow',
                 'key': 'jo_pending'},
                {'label': 'Released', 'value': jos.filter(
                    status=C.JobOrderStatus.RELEASED).count(), 'tone': 'blue', 'key': 'jo_released'},
                {'label': 'In Progress', 'value': jos.filter(
                    status=C.JobOrderStatus.IN_PROGRESS).count(), 'tone': 'blue',
                 'key': 'jo_inprogress'},
                {'label': 'Blocked', 'value': blocked, 'tone': 'red', 'key': 'jo_blocked'},
                {'label': 'Awaiting Drawing', 'value': jos.filter(
                    drawing_pending=True).exclude(status__in=[
                        C.JobOrderStatus.COMPLETE, C.JobOrderStatus.CLOSED,
                        C.JobOrderStatus.CANCELLED]).count(), 'tone': 'yellow',
                 'key': 'jo_drawing'},
                {'label': 'Due \u2264 3 days', 'value': due_soon, 'tone': 'yellow',
                 'key': 'jo_duesoon'},
                {'label': 'Late', 'value': late, 'tone': 'red', 'key': 'jo_late'},
            ],
        })
        if late:
            highlights.append({'label': 'Late job orders', 'value': late, 'tone': 'red',
                               'key': 'jo_late'})
        if blocked:
            highlights.append({'label': 'Blocked job orders', 'value': blocked,
                               'tone': 'red', 'key': 'jo_blocked'})

    if has_any(user, 'inventory.view', 'report.inventory'):
        coils = Coil.objects.all()
        low = coils.filter(status=C.CoilStatus.AVAILABLE,
                           remaining_length_m__lte=50).count()
        sections.append({
            'title': 'Inventory', 'icon': 'box', 'cards': [
                {'label': 'Coils Available', 'value': coils.filter(
                    status=C.CoilStatus.AVAILABLE).count(), 'tone': 'green',
                 'key': 'coils_available'},
                {'label': 'Coils In Use', 'value': coils.filter(
                    status=C.CoilStatus.IN_USE).count(), 'tone': 'blue', 'key': 'coils_inuse'},
                {'label': 'Low / Short Coils', 'value': low, 'tone': 'yellow', 'key': 'coils_low'},
                {'label': 'Reserved (rows)', 'value': StockBalance.objects.filter(
                    qty_reserved__gt=0).count(), 'tone': 'blue', 'key': 'stock_reserved'},
            ],
        })

    if has_any(user, 'delivery.view'):
        deliveries = Delivery.objects.all()
        sections.append({
            'title': 'Logistics', 'icon': 'truck', 'cards': [
                {'label': 'FG Ready', 'value': FinishedGoodsLot.objects.filter(
                    status=C.FGLotStatus.AVAILABLE, qty_available__gt=0).count(),
                 'tone': 'green', 'key': 'fg_ready'},
                {'label': 'Scheduled', 'value': deliveries.filter(
                    status=C.DeliveryStatus.SCHEDULED).count(), 'tone': 'blue',
                 'key': 'del_scheduled'},
                {'label': 'Dispatched', 'value': deliveries.filter(
                    status=C.DeliveryStatus.DISPATCHED).count(), 'tone': 'blue',
                 'key': 'del_dispatched'},
                {'label': 'Delivered', 'value': deliveries.filter(
                    status=C.DeliveryStatus.DELIVERED).count(), 'tone': 'green',
                 'key': 'del_delivered'},
            ],
        })

    overview, dash_charts = _dashboard_overview(user)

    return render(request, 'dashboards/hub.html', {
        'sections': sections,
        'highlights': highlights,
        'status_tone': C.STATUS_TONE,
        'production_queue': production_queue,
        'overview': overview,
        'dash_charts': dash_charts,
        'recent_quotes': Quotation.objects.filter(is_current=True)[:6]
        if has_any(user, 'quotation.view') else [],
        'recent_jos': JobOrder.objects.all()[:6] if has_any(user, 'job_order.view') else [],
        'recent_deliveries': Delivery.objects.select_related('customer')[:6]
        if has_any(user, 'delivery.view') else [],
    })


def _dashboard_overview(user):
    """Build the visual overview band (headline stats + chart series). Reuses the
    same live-data helpers as the AI Analyst so the numbers match the reports.
    Returns (overview_dict, charts_dict) -- both None/empty when the user lacks
    the sales/reporting permissions that the band summarises."""
    if not has_any(user, 'report.sales', 'report.management',
                   'quotation.view', 'invoice.view'):
        return None, None

    from ..ai import tools  # local import avoids app-load ordering issues

    sales = tools.sales_year_snapshot()
    prod = None
    if has_any(user, 'report.production', 'production.view', 'job_order.view'):
        prod = tools.production_year_snapshot()

    aging = sales['ar_aging']
    overview = {
        'year': sales['year'],
        'stats': [
            {'label': f"{sales['year']} Invoiced", 'value': sales['ytd_invoiced'],
             'money': True, 'tone': 'blue', 'spark': 'invoiced',
             'sub': f"Projected {sales['projected_year_invoiced']:,.0f}"},
            {'label': f"{sales['year']} Collected", 'value': sales['ytd_collected'],
             'money': True, 'tone': 'green', 'spark': 'collected',
             'sub': 'Verified payments received'},
            {'label': 'Outstanding AR', 'value': sales['ar_outstanding'],
             'money': True, 'tone': 'rose', 'spark': None,
             'sub': f"{sales['ar_overdue']:,.0f} overdue"},
            {'label': 'Win Rate', 'value': sales['win_rate_pct'],
             'money': False, 'suffix': '%', 'tone': 'indigo', 'spark': None,
             'sub': f"{len(sales['top_customers'])} active customers"},
        ],
        'top_customers': sales['top_customers'][:5],
        'has_production': prod is not None,
    }
    charts = {
        'labels': sales['months'],
        'invoiced': sales['invoiced_by_month'],
        'invoiced_forecast': sales['forecast_by_month'],
        'collected': sales['collected_by_month'],
        'ar_aging': [aging['current'], aging['b1_30'], aging['b31_60'], aging['b60p']],
        'ar_aging_labels': ['Current', '1-30d', '31-60d', '60d+'],
        'production_labels': prod['months'] if prod else None,
        'production_lm': prod['lm_by_month'] if prod else None,
        'production_forecast': prod['forecast_by_month'] if prod else None,
    }
    return overview, charts


# ---------------------------------------------------------------------------
# Dashboard drill-down side panel (htmx)
# ---------------------------------------------------------------------------
def _rows_quotations(qs):
    return [{'href': reverse('quotation_detail', args=[o.pk]), 'title': o.display_number,
             'subtitle': o.customer.name, 'status': o.status,
             'status_label': o.get_status_display(), 'meta': money(o.total)} for o in qs]


def _rows_invoices(qs, use_balance=False):
    return [{'href': reverse('invoice_detail', args=[o.pk]), 'title': o.number or f'INV-{o.pk}',
             'subtitle': o.customer.name, 'status': o.status,
             'status_label': o.get_status_display(),
             'meta': money(o.balance if use_balance else o.total)} for o in qs]


def _rows_job_orders(qs):
    return [{'href': reverse('job_order_detail', args=[o.pk]), 'title': o.number or f'JO-{o.pk}',
             'subtitle': o.customer.name, 'status': o.status,
             'status_label': o.get_status_display(),
             'meta': o.required_date.strftime('%b %d') if o.required_date else ''} for o in qs]


def _rows_coils(qs):
    return [{'href': reverse('coil_detail', args=[o.pk]), 'title': o.coil_number,
             'subtitle': o.item.name if o.item else '', 'status': o.status,
             'status_label': o.get_status_display(),
             'meta': f'{o.remaining_length_m} LM'} for o in qs]


def _rows_deliveries(qs):
    return [{'href': reverse('delivery_detail', args=[o.pk]), 'title': o.number or f'DR-{o.pk}',
             'subtitle': o.customer.name, 'status': o.status,
             'status_label': o.get_status_display(),
             'meta': o.scheduled_for.strftime('%b %d') if o.scheduled_for else ''} for o in qs]


@login_required
def dashboard_panel(request):
    """Return a right-side drawer listing the records behind a dashboard metric."""
    key = request.GET.get('key', '')
    user = request.user
    today = timezone.localdate()
    title, subtitle, rows, empty = key.replace('_', ' ').title(), '', [], 'Nothing here right now.'

    quotes = Quotation.objects.filter(is_current=True).select_related('customer')
    inv = Invoice.objects.select_related('customer')
    jos = JobOrder.objects.select_related('customer')
    coils = Coil.objects.select_related('item')
    deliveries = Delivery.objects.select_related('customer')

    if key == 'quotes_open' and has_any(user, 'quotation.view', 'quotation.create'):
        title, subtitle = 'Open Quotations', 'In progress, not yet closed'
        rows = _rows_quotations(quotes.exclude(status__in=[
            C.QuotationStatus.ACCEPTED, C.QuotationStatus.REJECTED,
            C.QuotationStatus.CANCELLED, C.QuotationStatus.EXPIRED])[:50])
    elif key == 'quotes_pending' and has_any(user, 'quotation.view', 'quotation.approve'):
        title, subtitle = 'Pending Approval', 'Quotations waiting for a checker'
        rows = _rows_quotations(quotes.filter(status=C.QuotationStatus.PENDING_APPROVAL)[:50])
    elif key == 'quotes_accepted' and has_any(user, 'quotation.view'):
        title, subtitle = 'Accepted Quotations', 'Ready to invoice'
        rows = _rows_quotations(quotes.filter(status=C.QuotationStatus.ACCEPTED)[:50])
    elif key == 'inv_approval' and has_any(user, 'invoice.view'):
        title, subtitle = 'Invoices for Approval', ''
        rows = _rows_invoices(inv.filter(status=C.InvoiceStatus.PENDING_APPROVAL)[:50])
    elif key == 'inv_approved' and has_any(user, 'invoice.view'):
        title, subtitle = 'Approved Invoices', ''
        rows = _rows_invoices(inv.filter(status=C.InvoiceStatus.APPROVED)[:50])
    elif key == 'inv_unpaid' and has_any(user, 'invoice.view', 'payment.record'):
        title, subtitle = 'Unpaid Invoices', ''
        rows = _rows_invoices(inv.filter(payment_state=C.PaymentState.UNPAID)[:50], use_balance=True)
    elif key == 'inv_outstanding' and has_any(user, 'invoice.view', 'payment.record'):
        title, subtitle = 'Outstanding Balances', 'Approved invoices with a balance'
        rows = _rows_invoices(
            [i for i in inv.filter(status=C.InvoiceStatus.APPROVED) if i.balance > 0][:50],
            use_balance=True)
    elif key == 'jo_pending' and has_any(user, 'job_order.view'):
        title, subtitle = 'Job Orders Pending Release', ''
        rows = _rows_job_orders(jos.filter(status=C.JobOrderStatus.PENDING_RELEASE)[:50])
    elif key == 'jo_released' and has_any(user, 'job_order.view'):
        title, subtitle = 'Released Job Orders', ''
        rows = _rows_job_orders(jos.filter(status=C.JobOrderStatus.RELEASED)[:50])
    elif key == 'jo_inprogress' and has_any(user, 'job_order.view'):
        title, subtitle = 'Job Orders In Progress', ''
        rows = _rows_job_orders(jos.filter(status=C.JobOrderStatus.IN_PROGRESS)[:50])
    elif key == 'jo_late' and has_any(user, 'job_order.view'):
        title, subtitle = 'Late Job Orders', 'Past required date, not yet complete'
        rows = _rows_job_orders(jos.filter(required_date__lt=today).exclude(status__in=[
            C.JobOrderStatus.COMPLETE, C.JobOrderStatus.CLOSED, C.JobOrderStatus.CANCELLED])[:50])
    elif key == 'jo_blocked' and has_any(user, 'job_order.view', 'production.view'):
        title, subtitle = 'Blocked Job Orders', 'Held by a drawing, credit or material gate'
        active = jos.exclude(status__in=[
            C.JobOrderStatus.COMPLETE, C.JobOrderStatus.CLOSED, C.JobOrderStatus.CANCELLED])
        rows = _rows_job_orders(active.filter(
            Q(drawing_pending=True) | Q(credit_hold=True) | Q(material_short=True))[:50])
    elif key == 'jo_drawing' and has_any(user, 'job_order.view', 'production.view'):
        title, subtitle = 'Awaiting Drawing', 'A required drawing is not yet verified'
        rows = _rows_job_orders(jos.filter(drawing_pending=True).exclude(status__in=[
            C.JobOrderStatus.COMPLETE, C.JobOrderStatus.CLOSED, C.JobOrderStatus.CANCELLED])[:50])
    elif key == 'jo_duesoon' and has_any(user, 'job_order.view', 'production.view'):
        from datetime import timedelta
        title, subtitle = 'Due Within 3 Days', 'Active job orders approaching their required date'
        rows = _rows_job_orders(jos.filter(
            required_date__gte=today, required_date__lte=today + timedelta(days=3)).exclude(
            status__in=[C.JobOrderStatus.COMPLETE, C.JobOrderStatus.CLOSED,
                        C.JobOrderStatus.CANCELLED])[:50])
    elif key == 'coils_available' and has_any(user, 'inventory.view'):
        title, subtitle = 'Coils Available', ''
        rows = _rows_coils(coils.filter(status=C.CoilStatus.AVAILABLE)[:50])
    elif key == 'coils_inuse' and has_any(user, 'inventory.view'):
        title, subtitle = 'Coils In Use', ''
        rows = _rows_coils(coils.filter(status=C.CoilStatus.IN_USE)[:50])
    elif key == 'coils_low' and has_any(user, 'inventory.view'):
        title, subtitle = 'Low / Short Coils', 'Available with \u2264 50 LM remaining'
        rows = _rows_coils(coils.filter(status=C.CoilStatus.AVAILABLE,
                                        remaining_length_m__lte=50)[:50])
    elif key == 'stock_reserved' and has_any(user, 'inventory.view'):
        title, subtitle = 'Reserved Stock', ''
        rows = [{'href': None, 'title': b.item.code if b.item else '-',
                 'subtitle': b.warehouse.name if b.warehouse else '',
                 'status': '', 'status_label': '', 'meta': f'{b.qty_reserved}'}
                for b in StockBalance.objects.select_related(
                    'item', 'warehouse').filter(qty_reserved__gt=0)[:50]]
    elif key == 'fg_ready' and has_any(user, 'delivery.view', 'inventory.view'):
        title, subtitle = 'Finished Goods Ready', 'Available to deliver'
        rows = [{'href': None, 'title': lot.lot_number,
                 'subtitle': str(lot.item) if lot.item else '',
                 'status': lot.status, 'status_label': lot.get_status_display(),
                 'meta': f'{lot.qty_available}'}
                for lot in FinishedGoodsLot.objects.select_related('item').filter(
                    status=C.FGLotStatus.AVAILABLE, qty_available__gt=0)[:50]]
    elif key == 'del_scheduled' and has_any(user, 'delivery.view'):
        title, subtitle = 'Scheduled Deliveries', ''
        rows = _rows_deliveries(deliveries.filter(status=C.DeliveryStatus.SCHEDULED)[:50])
    elif key == 'del_dispatched' and has_any(user, 'delivery.view'):
        title, subtitle = 'Dispatched Deliveries', ''
        rows = _rows_deliveries(deliveries.filter(status=C.DeliveryStatus.DISPATCHED)[:50])
    elif key == 'del_delivered' and has_any(user, 'delivery.view'):
        title, subtitle = 'Delivered', ''
        rows = _rows_deliveries(deliveries.filter(status=C.DeliveryStatus.DELIVERED)[:50])
    else:
        subtitle = 'No details available for this metric.'

    return render(request, 'dashboards/_panel.html', {
        'panel_title': title, 'panel_subtitle': subtitle,
        'rows': rows, 'empty': empty, 'status_tone': C.STATUS_TONE,
    })


# ---------------------------------------------------------------------------
# Global search typeahead (htmx dropdown)
# ---------------------------------------------------------------------------
@login_required
def global_search(request):
    """Live search dropdown for the top bar. Returns matching records grouped by
    type, respecting the user's permissions. Each result opens its detail modal."""
    q = (request.GET.get('q') or '').strip()
    user = request.user
    groups = []

    if len(q) >= 2:
        limit = 6

        if has_any(user, 'quotation.view', 'quotation.create'):
            rows = [
                {'title': o.display_number, 'subtitle': o.customer.name,
                 'href': reverse('quotation_detail', args=[o.pk]),
                 'status': o.status, 'status_label': o.get_status_display()}
                for o in Quotation.objects.filter(is_current=True).select_related(
                    'customer').filter(
                    Q(number__icontains=q) | Q(customer__name__icontains=q))[:limit]]
            if rows:
                groups.append({'label': 'Quotations', 'rows': rows})

        if has_any(user, 'invoice.view'):
            rows = [
                {'title': o.number or f'INV-{o.pk}', 'subtitle': o.customer.name,
                 'href': reverse('invoice_detail', args=[o.pk]),
                 'status': o.status, 'status_label': o.get_status_display()}
                for o in Invoice.objects.select_related('customer').filter(
                    Q(number__icontains=q) | Q(customer__name__icontains=q))[:limit]]
            if rows:
                groups.append({'label': 'Invoices', 'rows': rows})

        if has_any(user, 'job_order.view'):
            rows = [
                {'title': o.number or f'JO-{o.pk}', 'subtitle': o.customer.name,
                 'href': reverse('job_order_detail', args=[o.pk]),
                 'status': o.status, 'status_label': o.get_status_display()}
                for o in JobOrder.objects.select_related('customer').filter(
                    Q(number__icontains=q) | Q(customer__name__icontains=q))[:limit]]
            if rows:
                groups.append({'label': 'Job Orders', 'rows': rows})

        if has_any(user, 'delivery.view'):
            rows = [
                {'title': o.number or f'DR-{o.pk}', 'subtitle': o.customer.name,
                 'href': reverse('delivery_detail', args=[o.pk]),
                 'status': o.status, 'status_label': o.get_status_display()}
                for o in Delivery.objects.select_related('customer').filter(
                    Q(number__icontains=q) | Q(customer__name__icontains=q))[:limit]]
            if rows:
                groups.append({'label': 'Deliveries', 'rows': rows})

        if has_any(user, 'inventory.view'):
            rows = [
                {'title': o.coil_number, 'subtitle': o.item.name if o.item else '',
                 'href': reverse('coil_detail', args=[o.pk]),
                 'status': o.status, 'status_label': o.get_status_display()}
                for o in Coil.objects.select_related('item').filter(
                    Q(coil_number__icontains=q)
                    | Q(supplier_coil_no__icontains=q))[:limit]]
            if rows:
                groups.append({'label': 'Coils', 'rows': rows})

        if has_any(user, 'masterdata.view', 'masterdata.manage',
                   'quotation.view', 'quotation.create'):
            rows = [
                {'title': o.name, 'subtitle': o.code or o.phone or o.email,
                 'href': reverse('customer_edit', args=[o.pk]),
                 'status': '', 'status_label': ''}
                for o in Customer.objects.filter(
                    Q(name__icontains=q) | Q(code__icontains=q)
                    | Q(phone__icontains=q))[:limit]]
            if rows:
                groups.append({'label': 'Customers', 'rows': rows})

    return render(request, 'partials/search_results.html', {
        'groups': groups, 'q': q, 'status_tone': C.STATUS_TONE,
    })
