from decimal import Decimal

from django.contrib import messages
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from .. import constants as C
from .. import services
from ..forms import DeliveryForm
from ..models import Delivery, DeliveryProof, FinishedGoodsLot, JobOrderLine
from ..rbac import permission_required
from .common import paginate, render_detail

ZERO = Decimal('0')


@permission_required('delivery.view')
def delivery_list(request):
    status = request.GET.get('status', '').strip()
    qs = Delivery.objects.select_related('customer', 'invoice', 'job_order')
    if status:
        qs = qs.filter(status=status)
    return render(request, 'logistics/delivery_list.html', {
        'page_obj': paginate(request, qs),
        'status': status,
        'statuses': C.DeliveryStatus.choices,
        'status_tone': C.STATUS_TONE,
    })


@permission_required('delivery.schedule')
def delivery_create(request):
    if request.method == 'POST':
        form = DeliveryForm(request.POST)
        if form.is_valid():
            delivery = form.save(commit=False)
            delivery.number = services.next_number('delivery')
            delivery.status = C.DeliveryStatus.SCHEDULED
            delivery.prepared_by = request.user
            if not delivery.delivery_address and delivery.customer:
                delivery.delivery_address = delivery.customer.address
            delivery.save()
            services.log_status(delivery, delivery.status, actor=request.user)
            messages.success(request, f'Delivery {delivery.number} scheduled. Add items to ship.')
            return redirect('delivery_detail', pk=delivery.pk)
    else:
        form = DeliveryForm()
    return render(request, 'logistics/delivery_form.html', {'form': form, 'title': 'Schedule Delivery'})


@permission_required('delivery.view')
def delivery_detail(request, pk):
    delivery = get_object_or_404(Delivery.objects.select_related(
        'customer', 'invoice', 'job_order'), pk=pk)
    # Available FG lots for this customer / job order
    lots = FinishedGoodsLot.objects.filter(
        status=C.FGLotStatus.AVAILABLE, qty_available__gt=0)
    if delivery.job_order_id:
        lots = lots.filter(job_order=delivery.job_order)
    elif delivery.invoice_id:
        lots = lots.filter(job_order__invoice=delivery.invoice)
    else:
        lots = lots.filter(job_order__customer=delivery.customer)
    context = {
        'delivery': delivery,
        'lines': delivery.lines.select_related('fg_lot', 'item').all(),
        'lots': lots.select_related('item', 'job_order_line'),
        'proofs': delivery.proofs.all(),
        'status_tone': C.STATUS_TONE,
        'S': C.DeliveryStatus,
    }
    return render_detail(
        request,
        page_template='logistics/delivery_detail.html',
        body_template='logistics/_delivery_detail_body.html',
        context=context,
        title=f'Delivery {delivery.number}',
        full_url_name='delivery_detail', pk=delivery.pk)


@require_POST
@permission_required('delivery.partial', 'delivery.schedule')
def delivery_add_line(request, pk):
    delivery = get_object_or_404(Delivery, pk=pk)
    lot = get_object_or_404(FinishedGoodsLot, pk=request.POST.get('fg_lot'))
    try:
        qty = Decimal(request.POST.get('qty') or '0')
    except Exception:
        qty = ZERO
    if qty <= 0 or qty > lot.qty_available:
        messages.error(request, 'Invalid quantity (exceeds available in lot).')
        return redirect('delivery_detail', pk=pk)
    services.deliver_from_lot(
        delivery, lot, lot.job_order_line, qty, lot.item,
        description=str(lot.item), uom=lot.uom, user=request.user)
    messages.success(request, f'Added {qty} from lot {lot.lot_number}.')
    return redirect('delivery_detail', pk=pk)


@require_POST
@permission_required('delivery.dispatch')
def delivery_dispatch(request, pk):
    delivery = get_object_or_404(Delivery, pk=pk)
    if not delivery.lines.exists():
        messages.error(request, 'Add at least one item before dispatch.')
        return redirect('delivery_detail', pk=pk)
    delivery.dispatched_at = timezone.now()
    delivery.released_by = request.user
    delivery.save(update_fields=['dispatched_at', 'released_by'])
    services.set_status(delivery, C.DeliveryStatus.DISPATCHED, actor=request.user)
    messages.success(request, f'{delivery.number} dispatched.')
    return redirect('delivery_detail', pk=pk)


@require_POST
@permission_required('delivery.confirm')
def delivery_confirm(request, pk):
    delivery = get_object_or_404(Delivery, pk=pk)
    delivery.delivered_at = timezone.now()
    delivery.received_by = request.POST.get('received_by', '')
    delivery.save(update_fields=['delivered_at', 'received_by'])
    DeliveryProof.objects.create(
        delivery=delivery, image=request.FILES.get('image'),
        received_by_name=delivery.received_by, note=request.POST.get('note', ''))
    services.set_status(delivery, C.DeliveryStatus.DELIVERED, actor=request.user)
    # Close job order logistics if fully delivered
    jo = delivery.job_order
    if jo and all(l.qty_remaining_to_deliver <= 0 for l in jo.lines.all()):
        if jo.status == C.JobOrderStatus.COMPLETE:
            services.set_status(jo, C.JobOrderStatus.CLOSED, actor=request.user,
                                note='All quantities delivered')
    messages.success(request, f'{delivery.number} delivered and proof captured.')
    return redirect('delivery_detail', pk=pk)
