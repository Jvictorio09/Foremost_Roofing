from django.contrib import messages
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from .. import constants as C
from .. import services
from ..models import DrawingAttachment, JobOrder, JobOrderLine
from ..rbac import has_perm, permission_required
from .common import paginate, render_detail


@permission_required('job_order.view')
def job_order_list(request):
    q = request.GET.get('q', '').strip()
    status = request.GET.get('status', '').strip()
    qs = JobOrder.objects.select_related('customer', 'invoice')
    if q:
        qs = qs.filter(Q(number__icontains=q) | Q(customer__name__icontains=q))
    if status:
        qs = qs.filter(status=status)
    return render(request, 'manufacturing/job_order_list.html', {
        'page_obj': paginate(request, qs),
        'q': q, 'status': status,
        'statuses': C.JobOrderStatus.choices,
        'status_tone': C.STATUS_TONE,
    })


@permission_required('job_order.view')
def job_order_detail(request, pk):
    jo = get_object_or_404(JobOrder.objects.select_related('customer', 'invoice'), pk=pk)
    services._refresh_gates(jo)
    lines = jo.lines.prefetch_related('drawings', 'requirements').all()
    context = {
        'jo': jo,
        'lines': lines,
        'reservations': jo.reservations.prefetch_related('lines').all(),
        'runs': jo.production_runs.all(),
        'history': _history('JobOrder', jo.pk),
        'status_tone': C.STATUS_TONE,
        'S': C.JobOrderStatus,
    }
    return render_detail(
        request,
        page_template='manufacturing/job_order_detail.html',
        body_template='manufacturing/_job_order_detail_body.html',
        context=context,
        title=f'Job Order {jo.number}',
        full_url_name='job_order_detail', pk=jo.pk)


@require_POST
@permission_required('job_order.release')
def job_order_release(request, pk):
    jo = get_object_or_404(JobOrder, pk=pk)
    try:
        services.release_job_order(jo, user=request.user)
        if jo.material_short:
            messages.warning(request, f'{jo.number} released, but material is short — flagged for purchasing.')
        else:
            messages.success(request, f'{jo.number} released. Material reserved.')
    except ValueError as e:
        messages.error(request, str(e))
    return redirect('job_order_detail', pk=pk)


@require_POST
@permission_required('job_order.hold')
def job_order_hold(request, pk):
    jo = get_object_or_404(JobOrder, pk=pk)
    services.set_status(jo, C.JobOrderStatus.ON_HOLD, actor=request.user,
                        note=request.POST.get('reason', ''))
    messages.success(request, f'{jo.number} placed on hold.')
    return redirect('job_order_detail', pk=pk)


@require_POST
@permission_required('job_order.cancel')
def job_order_cancel(request, pk):
    jo = get_object_or_404(JobOrder, pk=pk)
    services.cancel_job_order(jo, user=request.user, reason=request.POST.get('reason', ''))
    messages.success(request, f'{jo.number} cancelled and reservations released.')
    return redirect('job_order_detail', pk=pk)


@require_POST
@permission_required('drawing.upload')
def drawing_upload(request, line_pk):
    line = get_object_or_404(JobOrderLine, pk=line_pk)
    if 'file' not in request.FILES:
        messages.error(request, 'Please choose a drawing file.')
        return redirect('job_order_detail', pk=line.job_order_id)
    last = line.drawings.order_by('-revision_no').first()
    rev = (last.revision_no + 1) if last else 1
    DrawingAttachment.objects.create(
        job_order_line=line, file=request.FILES['file'], revision_no=rev,
        status=C.DrawingStatus.SUBMITTED, notes=request.POST.get('notes', ''),
        uploaded_by=request.user,
    )
    services._refresh_gates(line.job_order)
    messages.success(request, f'Drawing revision {rev} uploaded. Awaiting verification.')
    return redirect('job_order_detail', pk=line.job_order_id)


@require_POST
@permission_required('drawing.verify')
def drawing_verify(request, pk):
    drawing = get_object_or_404(DrawingAttachment, pk=pk)
    action = request.POST.get('action', 'verify')
    drawing.status = (C.DrawingStatus.VERIFIED if action == 'verify'
                      else C.DrawingStatus.REJECTED)
    drawing.verified_by = request.user
    drawing.verified_at = timezone.now()
    drawing.save(update_fields=['status', 'verified_by', 'verified_at'])
    services._refresh_gates(drawing.job_order_line.job_order)
    messages.success(request, f'Drawing {drawing.get_status_display().lower()}.')
    return redirect('job_order_detail', pk=drawing.job_order_line.job_order_id)


def _history(entity_type, entity_id):
    from ..models import StatusHistory
    return StatusHistory.objects.filter(
        entity_type=entity_type, entity_id=entity_id).select_related('actor')[:15]
