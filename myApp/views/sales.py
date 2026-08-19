from datetime import timedelta

from django.contrib import messages
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from .. import constants as C
from .. import services
from ..forms import (
    InvoiceNoteForm, PaymentForm, QuotationForm, QuotationLineFormSet)
from ..models import (
    CustomerAcceptance, Invoice, InvoiceNote, Item, ItemCategory, JobOrder, Quotation)


def _note_edit_window():
    """Minutes a user may edit/delete their own invoice note (configurable)."""
    return int(services.get_decimal('invoice.note_edit_window_min', '15'))


def _can_edit_note(note, user):
    if not (user.is_superuser or note.author_id == user.id):
        return False
    return note.created_at >= timezone.now() - timedelta(minutes=_note_edit_window())
from ..rbac import has_perm, permission_required
from .common import money, paginate, render_detail


# ---------------------------------------------------------------------------
# Quotations
# ---------------------------------------------------------------------------
@permission_required('quotation.view', 'quotation.create')
def quotation_list(request):
    q = request.GET.get('q', '').strip()
    status = request.GET.get('status', '').strip()
    qs = Quotation.objects.select_related('customer', 'salesperson').filter(is_current=True)
    if q:
        qs = qs.filter(Q(number__icontains=q) | Q(customer__name__icontains=q))
    if status:
        qs = qs.filter(status=status)
    return render(request, 'sales/quotation_list.html', {
        'page_obj': paginate(request, qs),
        'q': q, 'status': status,
        'statuses': C.QuotationStatus.choices,
        'status_tone': C.STATUS_TONE,
    })


@permission_required('quotation.view', 'quotation.create')
def quotation_detail(request, pk):
    quotation = get_object_or_404(
        Quotation.objects.select_related('customer', 'salesperson', 'tax_code'), pk=pk)
    context = {
        'q': quotation,
        'lines': quotation.lines.all(),
        'invoices': quotation.invoices.all(),
        'history': _history('Quotation', quotation.pk),
        'status_tone': C.STATUS_TONE,
        'S': C.QuotationStatus,
    }
    return render_detail(
        request,
        page_template='sales/quotation_detail.html',
        body_template='sales/_quotation_detail_body.html',
        context=context,
        title=f'Quotation {quotation.display_number}',
        full_url_name='quotation_detail', pk=quotation.pk)


@permission_required('quotation.create')
def quotation_create(request):
    if request.method == 'POST':
        form = QuotationForm(request.POST)
        formset = QuotationLineFormSet(request.POST, request.FILES)
        if form.is_valid() and formset.is_valid():
            quotation = form.save(commit=False)
            quotation.number = services.next_number('quotation')
            quotation.created_by = request.user
            if not quotation.salesperson_id:
                quotation.salesperson = request.user
            if not quotation.valid_until:
                days = int(services.get_setting('quotation.default_validity_days', '30') or 30)
                quotation.valid_until = timezone.localdate() + timezone.timedelta(days=days)
            quotation.save()
            formset.instance = quotation
            lines = formset.save()
            for line in lines:
                services.sync_quotation_line_derived(line)
            services.log_status(quotation, quotation.status, actor=request.user,
                                note='Quotation created')
            messages.success(request, f'Quotation {quotation.number} created.')
            return redirect('quotation_detail', pk=quotation.pk)
        messages.error(request, 'This quotation was not saved. Please fix the highlighted errors.')
    else:
        form = QuotationForm()
        formset = QuotationLineFormSet()
    return render(request, 'sales/quotation_form.html', _quotation_form_context(
        form=form, formset=formset, title='New Quotation'))


@permission_required('quotation.edit')
def quotation_edit(request, pk):
    quotation = get_object_or_404(Quotation, pk=pk)
    if quotation.status not in (C.QuotationStatus.DRAFT, C.QuotationStatus.PENDING_APPROVAL):
        messages.error(request, 'Only draft / pending quotations can be edited. Create a revision instead.')
        return redirect('quotation_detail', pk=pk)
    if request.method == 'POST':
        form = QuotationForm(request.POST, instance=quotation)
        formset = QuotationLineFormSet(request.POST, request.FILES, instance=quotation)
        if form.is_valid() and formset.is_valid():
            form.save()
            lines = formset.save()
            for line in lines:
                services.sync_quotation_line_derived(line)
            services.log_event(quotation, 'edit', actor=request.user)
            messages.success(request, 'Quotation updated.')
            return redirect('quotation_detail', pk=pk)
        messages.error(request, 'Changes were not saved. Please fix the highlighted errors.')
    else:
        form = QuotationForm(instance=quotation)
        formset = QuotationLineFormSet(instance=quotation)
    return render(request, 'sales/quotation_form.html', _quotation_form_context(
        form=form, formset=formset, title=f'Edit {quotation.display_number}'))


def _quotation_form_context(**extra):
    extra.update({
        'standard_drawings': _drawing_map(),
        'item_prices': _item_price_map(),
        'item_categories': list(ItemCategory.objects.order_by('name').values(
            'id', 'code', 'name')),
        'item_catalog': _item_catalog(),
    })
    return extra


def _drawing_map():
    """{id: image_url} for the standard drawing picker preview on the line editor."""
    from ..models import StandardDrawing
    return {d.pk: d.image.url for d in StandardDrawing.objects.filter(
        is_active=True) if d.image}


def _item_catalog():
    """Item id -> category / label, used to filter the line-item picker."""
    catalog = {}
    qs = Item.objects.filter(is_active=True).select_related('category')
    for item in qs:
        catalog[str(item.pk)] = {
            'category': item.category_id,
            'code': item.category.code if item.category_id else '',
            'label': str(item),
        }
    return catalog


def _item_price_map():
    """{item_id: unit_price} from the default price list's latest version, for
    items that carry a direct (item-keyed) price row. Used to prefill the unit
    price on a quotation line as soon as an item is picked."""
    from ..models import PriceList
    pl = PriceList.objects.filter(is_default=True).first() or PriceList.objects.first()
    if not pl:
        return {}
    ver = pl.versions.first()  # PriceListVersion ordering is -effective_from
    if not ver:
        return {}
    prices = {}
    for row in ver.rows.filter(item__isnull=False).values('item_id', 'unit_price'):
        prices.setdefault(row['item_id'], float(row['unit_price']))
    return prices


@require_POST
@permission_required('quotation.submit')
def quotation_submit(request, pk):
    quotation = get_object_or_404(Quotation, pk=pk)
    services.set_status(quotation, C.QuotationStatus.PENDING_APPROVAL, actor=request.user)
    messages.success(request, 'Quotation submitted for approval.')
    return redirect('quotation_detail', pk=pk)


@require_POST
@permission_required('quotation.approve')
def quotation_approve(request, pk):
    quotation = get_object_or_404(Quotation, pk=pk)
    if (services.get_bool('approval.maker_checker', True)
            and quotation.created_by_id == request.user.id
            and not request.user.is_superuser):
        messages.error(request, 'Maker-checker: you cannot approve a quotation you created.')
        return redirect('quotation_detail', pk=pk)
    quotation.approved_by = request.user
    quotation.approved_at = timezone.now()
    quotation.save(update_fields=['approved_by', 'approved_at'])
    services.set_status(quotation, C.QuotationStatus.APPROVED, actor=request.user)
    messages.success(request, 'Quotation approved.')
    return redirect('quotation_detail', pk=pk)


@require_POST
@permission_required('quotation.send')
def quotation_send(request, pk):
    quotation = get_object_or_404(Quotation, pk=pk)
    quotation.sent_at = timezone.now()
    quotation.save(update_fields=['sent_at'])
    services.set_status(quotation, C.QuotationStatus.SENT, actor=request.user)
    messages.success(request, 'Quotation marked as sent to customer.')
    return redirect('quotation_detail', pk=pk)


@require_POST
@permission_required('quotation.accept')
def quotation_accept(request, pk):
    quotation = get_object_or_404(Quotation, pk=pk)
    CustomerAcceptance.objects.update_or_create(
        quotation=quotation,
        defaults={'accepted_by_name': request.POST.get('accepted_by', ''),
                  'reference': request.POST.get('reference', ''),
                  'note': request.POST.get('note', ''),
                  'recorded_by': request.user},
    )
    services.set_status(quotation, C.QuotationStatus.ACCEPTED, actor=request.user,
                        note='Customer acceptance recorded')
    messages.success(request, 'Customer acceptance recorded. You can now create an invoice.')
    return redirect('quotation_detail', pk=pk)


@require_POST
@permission_required('quotation.revise')
def quotation_revise(request, pk):
    quotation = get_object_or_404(Quotation, pk=pk)
    new_q = services.revise_quotation(quotation, user=request.user)
    messages.success(request, f'Created revision r{new_q.revision_no}. Previous revision preserved.')
    return redirect('quotation_detail', pk=new_q.pk)


@require_POST
@permission_required('quotation.cancel')
def quotation_cancel(request, pk):
    quotation = get_object_or_404(Quotation, pk=pk)
    services.set_status(quotation, C.QuotationStatus.CANCELLED, actor=request.user,
                        note=request.POST.get('reason', ''))
    messages.success(request, 'Quotation cancelled.')
    return redirect('quotation_detail', pk=pk)


# ---------------------------------------------------------------------------
# Invoices
# ---------------------------------------------------------------------------
@permission_required('invoice.view', 'invoice.create')
def invoice_list(request):
    q = request.GET.get('q', '').strip()
    status = request.GET.get('status', '').strip()
    qs = Invoice.objects.select_related('customer')
    if q:
        qs = qs.filter(Q(number__icontains=q) | Q(customer__name__icontains=q))
    if status:
        qs = qs.filter(status=status)
    page = paginate(request, qs)
    # Pin the latest follow-up onto each row so overdue accounts show last contact.
    latest = {}
    ids = [inv.pk for inv in page]
    for note in (InvoiceNote.objects.filter(invoice_id__in=ids)
                 .select_related('author').order_by('-created_at')):
        latest.setdefault(note.invoice_id, note)
    for inv in page:
        inv.last_note = latest.get(inv.pk)
    return render(request, 'sales/invoice_list.html', {
        'page_obj': page,
        'q': q, 'status': status,
        'statuses': C.InvoiceStatus.choices,
        'status_tone': C.STATUS_TONE,
    })


@permission_required('invoice.view', 'invoice.create')
def invoice_detail(request, pk):
    invoice = get_object_or_404(Invoice.objects.select_related('customer', 'quotation'), pk=pk)
    notes = list(invoice.followup_notes.select_related('author'))
    for note in notes:
        note.can_edit = _can_edit_note(note, request.user)
    context = {
        'inv': invoice,
        'lines': invoice.lines.all(),
        'payments': invoice.payments.all(),
        'job_orders': invoice.job_orders.all(),
        'credit_checks': invoice.credit_checks.all()[:5],
        'payment_form': PaymentForm(),
        'notes': notes,
        'note_form': InvoiceNoteForm(),
        'note_kinds': C.InvoiceNoteKind.choices,
        'history': _history('Invoice', invoice.pk),
        'status_tone': C.STATUS_TONE,
        'S': C.InvoiceStatus,
    }
    return render_detail(
        request,
        page_template='sales/invoice_detail.html',
        body_template='sales/_invoice_detail_body.html',
        context=context,
        title=f'Invoice {invoice.number}',
        full_url_name='invoice_detail', pk=invoice.pk)


@require_POST
@permission_required('invoice.create')
def invoice_create_from_quotation(request, pk):
    quotation = get_object_or_404(Quotation, pk=pk)
    if quotation.status != C.QuotationStatus.ACCEPTED and not has_perm(request.user, 'credit.override'):
        messages.error(request, 'Invoice can only be created from an accepted quotation.')
        return redirect('quotation_detail', pk=pk)
    invoice = services.create_invoice_from_quotation(quotation, user=request.user)
    messages.success(request, f'Invoice {invoice.number} created from quotation (prices snapshotted).')
    return redirect('invoice_detail', pk=invoice.pk)


@require_POST
@permission_required('invoice.approve')
def invoice_approve(request, pk):
    invoice = get_object_or_404(Invoice, pk=pk)
    if (services.get_bool('approval.maker_checker', True)
            and invoice.created_by_id == request.user.id and not request.user.is_superuser):
        messages.error(request, 'Maker-checker: you cannot approve an invoice you created.')
        return redirect('invoice_detail', pk=pk)
    invoice.approved_by = request.user
    invoice.approved_at = timezone.now()
    invoice.save(update_fields=['approved_by', 'approved_at'])
    services.set_status(invoice, C.InvoiceStatus.APPROVED, actor=request.user)
    # Controlled release: create a Pending-Release job order (not auto-started).
    try:
        jo = services.create_job_order_from_invoice(invoice, user=request.user)
        messages.success(request, f'Invoice approved. Job order {jo.number} created (pending release).')
    except ValueError as e:
        messages.warning(request, f'Invoice approved. {e}')
    return redirect('invoice_detail', pk=pk)


@require_POST
@permission_required('invoice.release_job_order')
def invoice_create_job_order(request, pk):
    invoice = get_object_or_404(Invoice, pk=pk)
    override = has_perm(request.user, 'invoice.duplicate_override') and request.POST.get('override')
    try:
        jo = services.create_job_order_from_invoice(invoice, user=request.user,
                                                    override_duplicate=bool(override))
        messages.success(request, f'Job order {jo.number} created.')
    except ValueError as e:
        messages.error(request, str(e))
    return redirect('invoice_detail', pk=pk)


@require_POST
@permission_required('payment.record', 'invoice.edit')
def invoice_add_note(request, pk):
    """Append a collections / follow-up note to an invoice (append-only log)."""
    invoice = get_object_or_404(Invoice, pk=pk)
    form = InvoiceNoteForm(request.POST)
    if form.is_valid():
        note = form.save(commit=False)
        note.invoice = invoice
        note.author = request.user
        note.save()
        services.log_event(invoice, 'note', actor=request.user,
                           new={'kind': note.kind})
        messages.success(request, 'Follow-up note added.')
    else:
        messages.error(request, 'Note cannot be empty.')
    return redirect('invoice_detail', pk=pk)


@require_POST
@permission_required('payment.record', 'invoice.edit')
def invoice_note_edit(request, pk):
    """Edit your own follow-up note within the allowed time window."""
    note = get_object_or_404(InvoiceNote, pk=pk)
    if not _can_edit_note(note, request.user):
        messages.error(request, 'You can no longer edit this note.')
        return redirect('invoice_detail', pk=note.invoice_id)
    form = InvoiceNoteForm(request.POST, instance=note)
    if form.is_valid():
        form.save()
        services.log_event(note.invoice, 'note_edit', actor=request.user,
                           new={'note_id': note.pk})
        messages.success(request, 'Note updated.')
    else:
        messages.error(request, 'Note cannot be empty.')
    return redirect('invoice_detail', pk=note.invoice_id)


@require_POST
@permission_required('payment.record', 'invoice.edit')
def invoice_note_delete(request, pk):
    """Delete your own follow-up note within the allowed time window."""
    note = get_object_or_404(InvoiceNote.objects.select_related('invoice'), pk=pk)
    invoice = note.invoice
    if not _can_edit_note(note, request.user):
        messages.error(request, 'You can no longer delete this note.')
        return redirect('invoice_detail', pk=invoice.pk)
    note.delete()
    services.log_event(invoice, 'note_delete', actor=request.user)
    messages.success(request, 'Note removed.')
    return redirect('invoice_detail', pk=invoice.pk)


@require_POST
@permission_required('payment.record')
def invoice_record_payment(request, pk):
    invoice = get_object_or_404(Invoice, pk=pk)
    form = PaymentForm(request.POST)
    if not form.is_valid():
        messages.error(request, 'Invalid payment.')
        return redirect('invoice_detail', pk=pk)
    payment = form.save(commit=False)
    payment.invoice = invoice
    payment.recorded_by = request.user
    payment.status = C.PaymentStatus.VERIFIED
    payment.save()
    # update payment_state
    paid = invoice.total_paid
    if paid <= 0:
        state = C.PaymentState.UNPAID
    elif paid >= invoice.total:
        state = C.PaymentState.PAID
    else:
        state = C.PaymentState.PARTIAL
    invoice.payment_state = state
    invoice.save(update_fields=['payment_state'])
    services.log_event(invoice, 'payment', actor=request.user,
                       new={'amount': str(payment.amount)})
    messages.success(request, f'Payment of {money(payment.amount)} recorded.')
    return redirect('invoice_detail', pk=pk)


def _history(entity_type, entity_id):
    from ..models import StatusHistory
    return StatusHistory.objects.filter(
        entity_type=entity_type, entity_id=entity_id).select_related('actor')[:15]
