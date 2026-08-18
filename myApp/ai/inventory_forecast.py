"""Coarse inventory shortage outlook: open production demand vs coil supply.

Phase-1 heuristic (no full BOM yet): compares outstanding linear-metre demand on
released / in-progress job orders against available coil remaining length. Used
as a read-only tool by the AI Analyst.
"""
from __future__ import annotations

from decimal import Decimal

from django.db.models import Sum

from .. import constants as C
from ..models import Coil, JobOrderLine

ZERO = Decimal('0')


def forecast(user=None, provider_name=None) -> dict:
    open_statuses = [C.JobOrderStatus.RELEASED, C.JobOrderStatus.IN_PROGRESS,
                     C.JobOrderStatus.PARTIALLY_COMPLETE]
    lines = JobOrderLine.objects.filter(
        job_order__status__in=open_statuses, is_manufactured=True
    ).select_related('job_order')

    demand_lm = ZERO
    open_lines = 0
    for line in lines:
        remaining = line.qty_remaining_to_produce
        if remaining and remaining > 0:
            demand_lm += remaining
            open_lines += 1

    supply_lm = (Coil.objects.filter(status=C.CoilStatus.AVAILABLE)
                 .aggregate(s=Sum('remaining_length_m'))['s'] or ZERO)

    net = supply_lm - demand_lm
    coverage = (float(supply_lm) / float(demand_lm)) if demand_lm else None
    return {
        'open_demand_lm': round(float(demand_lm), 2),
        'available_supply_lm': round(float(supply_lm), 2),
        'net_lm': round(float(net), 2),
        'coverage_ratio': round(coverage, 2) if coverage is not None else None,
        'open_manufactured_lines': open_lines,
        'shortfall': net < 0,
        'note': ('Coarse heuristic without full BOM: totals ignore per-item coil '
                 'matching, so treat as a directional signal, not a hard plan.'),
    }
