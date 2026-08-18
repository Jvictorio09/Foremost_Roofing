from decimal import Decimal

from django.contrib import messages
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from .. import constants as C
from .. import services
from ..forms import ProductionRunForm
from ..models import (
    Coil, JobOrder, JobOrderLine, ProductionRun, ProductionRunOutput, Warehouse,
)
from ..rbac import permission_required
from .common import paginate, render_detail

ZERO = Decimal('0')


@permission_required('production.view')
def production_list(request):
    status = request.GET.get('status', '').strip()
    qs = ProductionRun.objects.select_related('job_order__customer', 'machine', 'operator')
    if status:
        qs = qs.filter(status=status)
    releasable = JobOrder.objects.filter(status__in=[
        C.JobOrderStatus.RELEASED, C.JobOrderStatus.IN_PROGRESS,
        C.JobOrderStatus.PARTIALLY_COMPLETE])
    return render(request, 'production/run_list.html', {
        'page_obj': paginate(request, qs),
        'releasable': releasable,
        'status': status,
        'statuses': C.ProductionRunStatus.choices,
        'status_tone': C.STATUS_TONE,
    })


@permission_required('production.start')
def production_run_create(request):
    initial = {}
    jo_id = request.GET.get('job_order')
    if jo_id:
        initial['job_order'] = jo_id
    if request.method == 'POST':
        form = ProductionRunForm(request.POST)
        if form.is_valid():
            run = form.save(commit=False)
            run.number = services.next_number('production_run')
            run.status = C.ProductionRunStatus.STARTED
            run.started_at = timezone.now()
            if not run.operator_id:
                run.operator = request.user
            run.save()
            jo = run.job_order
            if jo.status == C.JobOrderStatus.RELEASED:
                services.set_status(jo, C.JobOrderStatus.IN_PROGRESS, actor=request.user)
            services.log_status(run, run.status, actor=request.user, note='Run started')
            messages.success(request, f'Production run {run.number} started.')
            return redirect('production_run_detail', pk=run.pk)
    else:
        form = ProductionRunForm(initial=initial)
    return render(request, 'production/run_form.html', {'form': form, 'title': 'New Production Run'})


@permission_required('production.view')
def production_run_detail(request, pk):
    run = get_object_or_404(ProductionRun.objects.select_related(
        'job_order__customer', 'machine', 'operator'), pk=pk)
    jo_lines = run.job_order.lines.all()
    coils = Coil.objects.filter(status__in=[
        C.CoilStatus.AVAILABLE, C.CoilStatus.RESERVED, C.CoilStatus.IN_USE])
    context = {
        'run': run,
        'jo_lines': jo_lines,
        'coils': coils,
        'outputs': run.outputs.select_related('job_order_line').all(),
        'consumptions': run.coil_consumptions.select_related('coil', 'job_order_line').all(),
        'warehouses': Warehouse.objects.all(),
        'status_tone': C.STATUS_TONE,
        'R': C.ProductionRunStatus,
    }
    return render_detail(
        request,
        page_template='production/run_detail.html',
        body_template='production/_run_detail_body.html',
        context=context,
        title=f'Production Run {run.number}',
        full_url_name='production_run_detail', pk=run.pk)


@require_POST
@permission_required('production.complete')
@transaction.atomic
def production_run_complete(request, pk):
    run = get_object_or_404(ProductionRun, pk=pk)
    jo = run.job_order
    fg_wh = jo.warehouse or Warehouse.objects.first()
    wh_id = request.POST.get('fg_warehouse')
    if wh_id:
        fg_wh = Warehouse.objects.filter(pk=wh_id).first() or fg_wh

    posted = 0
    for line in jo.lines.all():
        prefix = f'line_{line.pk}_'
        good = _dec(request.POST.get(prefix + 'good'))
        reject = _dec(request.POST.get(prefix + 'reject'))
        scrap = _dec(request.POST.get(prefix + 'scrap'))
        coil_id = request.POST.get(prefix + 'coil')
        consumed = _dec(request.POST.get(prefix + 'consumed'))

        if good <= 0 and reject <= 0 and consumed <= 0:
            continue

        ProductionRunOutput.objects.create(
            run=run, job_order_line=line, good_qty=good, reject_qty=reject,
            scrap_qty=scrap, uom=line.uom)

        coil = Coil.objects.filter(pk=coil_id).first() if coil_id else None
        if coil and consumed > 0:
            coil.remaining_length_m = coil.remaining_length_m - consumed
            if coil.remaining_length_m <= services.get_decimal('coil.remnant_threshold_m', '3'):
                coil.status = C.CoilStatus.REMNANT if coil.remaining_length_m > 0 else C.CoilStatus.CONSUMED
            coil.save(update_fields=['remaining_length_m', 'status'])
            services.record_coil_consumption(run, line, coil, consumed, scrap_length=scrap,
                                              user=request.user)

        if good > 0 and services.get_bool('fg.always_post', True):
            services.receive_finished_goods(run, line, fg_wh, good, user=request.user)
        elif good > 0:
            line.qty_produced = line.qty_produced + good
            line.save(update_fields=['qty_produced'])
        posted += 1

    run.status = C.ProductionRunStatus.COMPLETED
    run.ended_at = timezone.now()
    run.save(update_fields=['status', 'ended_at'])
    services.log_status(run, run.status, actor=request.user, note='Run completed')
    services.rollup_job_order(jo, user=request.user)
    messages.success(request, f'Run {run.number} completed. {posted} line(s) posted to finished goods.')
    return redirect('production_run_detail', pk=pk)


def _dec(v):
    try:
        return Decimal(v) if v not in (None, '') else ZERO
    except Exception:
        return ZERO
