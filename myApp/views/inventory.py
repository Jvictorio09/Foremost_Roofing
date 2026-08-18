from decimal import Decimal

from django.contrib import messages
from django.db.models import Q
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from .. import constants as C
from .. import services
from ..forms import CoilForm
from ..models import (
    Coil, CoilConsumption, InventoryTransaction, MaterialReservationLine, StockBalance,
)
from ..rbac import permission_required
from .common import is_hx, paginate, render_detail


@permission_required('inventory.view')
def coil_list(request):
    q = request.GET.get('q', '').strip()
    status = request.GET.get('status', '').strip()
    qs = Coil.objects.select_related('item', 'color', 'warehouse', 'supplier')
    if q:
        qs = qs.filter(Q(coil_number__icontains=q) | Q(item__name__icontains=q))
    if status:
        qs = qs.filter(status=status)
    return render(request, 'inventory/coil_list.html', {
        'page_obj': paginate(request, qs),
        'q': q, 'status': status,
        'statuses': C.CoilStatus.choices,
        'status_tone': C.STATUS_TONE,
    })


@permission_required('inventory.view')
def coil_detail(request, pk):
    coil = get_object_or_404(Coil.objects.select_related('item', 'supplier', 'warehouse'), pk=pk)
    consumptions = coil.consumptions.select_related(
        'production_run', 'job_order_line__job_order').all()
    context = {
        'coil': coil,
        'consumptions': consumptions,
        'transactions': coil.transactions.select_related('job_order')[:30],
        'status_tone': C.STATUS_TONE,
    }
    return render_detail(
        request,
        page_template='inventory/coil_detail.html',
        body_template='inventory/_coil_detail_body.html',
        context=context,
        title=f'Coil {coil.coil_number}',
        full_url_name='coil_detail', pk=coil.pk)


@permission_required('inventory.receive')
def coil_create(request):
    hx = is_hx(request)
    if request.method == 'POST':
        form = CoilForm(request.POST)
        if form.is_valid():
            coil = form.save(commit=False)
            coil.remaining_length_m = coil.original_length_m
            coil.remaining_weight_kg = coil.original_weight_kg
            coil.save()
            services.receive_coil(coil, user=request.user)
            messages.success(request, f'Coil {coil.coil_number} received into {coil.warehouse}.')
            if hx:
                # Close the modal and reload the list underneath it.
                resp = HttpResponse(status=204)
                resp['HX-Refresh'] = 'true'
                return resp
            return redirect('coil_detail', pk=coil.pk)
    else:
        form = CoilForm()
    template = 'masters/_form_modal.html' if hx else 'inventory/coil_form.html'
    return render(request, template, {
        'form': form, 'title': 'Receive Coil', 'form_action': request.path})


@permission_required('inventory.view')
def inventory_ledger(request):
    txn_type = request.GET.get('type', '').strip()
    qs = InventoryTransaction.objects.select_related('item', 'warehouse', 'coil', 'created_by')
    if txn_type:
        qs = qs.filter(txn_type=txn_type)
    return render(request, 'inventory/ledger.html', {
        'page_obj': paginate(request, qs, 40),
        'txn_type': txn_type,
        'types': C.InventoryTxnType.choices,
    })


@permission_required('inventory.view')
def stock_balances(request):
    qs = StockBalance.objects.select_related('item', 'warehouse').filter(
        Q(qty_on_hand__gt=0) | Q(qty_reserved__gt=0))
    return render(request, 'inventory/stock_balances.html', {
        'page_obj': paginate(request, qs, 40)})


@require_POST
@permission_required('inventory.issue')
def issue_material(request, line_pk):
    rl = get_object_or_404(MaterialReservationLine.objects.select_related(
        'reservation__job_order', 'item', 'warehouse'), pk=line_pk)
    try:
        qty = Decimal(request.POST.get('qty') or rl.qty_open)
    except Exception:
        qty = rl.qty_open
    if qty <= 0 or qty > rl.qty_open:
        messages.error(request, 'Invalid issue quantity.')
        return redirect('job_order_detail', pk=rl.reservation.job_order_id)
    services.issue_to_production(rl, qty, user=request.user)
    messages.success(request, f'Issued {qty} {rl.item.uom} to production.')
    return redirect('job_order_detail', pk=rl.reservation.job_order_id)
