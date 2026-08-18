"""Business services: numbering, config, audit, the inventory ledger, document
snapshotting, material estimation and workflow gates.

All state changes that matter (stock, coil balances, status) go through here so
the rules live in one place and every posting is auditable.
"""
from decimal import Decimal

from django.db import transaction
from django.utils import timezone

from . import constants as C
from .models import (
    AppSetting, Coil, CoilConsumption, CreditCheckLog, DrawingAttachment,
    FinishedGoodsLot, InventoryTransaction, Invoice, InvoiceLine, InvoiceLineSpec,
    JobMaterialRequirement, JobOrder, JobOrderLine, JobOrderLineSpec,
    MaterialReservation, MaterialReservationLine, NumberSeries, ProductionRun,
    Quotation, QuotationLine, QuotationLineSpec, StatusHistory, StockBalance,
    AuditEvent,
)

ZERO = Decimal('0.00')


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
def get_setting(key, default=''):
    row = AppSetting.objects.filter(key=key).first()
    return row.value if row else default


def get_bool(key, default=False):
    val = get_setting(key, 'true' if default else 'false')
    return str(val).strip().lower() in ('1', 'true', 'yes', 'on')


def get_decimal(key, default='0'):
    try:
        return Decimal(get_setting(key, default) or default)
    except Exception:
        return Decimal(default)


# ---------------------------------------------------------------------------
# Numbering
# ---------------------------------------------------------------------------
@transaction.atomic
def next_number(key):
    series, _ = NumberSeries.objects.select_for_update().get_or_create(
        key=key, defaults={'prefix': key[:3].upper() + '-', 'padding': 5, 'next_number': 1}
    )
    n = series.next_number
    series.next_number = n + 1
    series.save(update_fields=['next_number'])
    return f'{series.prefix}{n:0{series.padding}d}'


# ---------------------------------------------------------------------------
# Audit
# ---------------------------------------------------------------------------
def log_status(entity, to_status, actor=None, from_status='', note=''):
    StatusHistory.objects.create(
        entity_type=entity.__class__.__name__,
        entity_id=entity.pk,
        from_status=from_status or '',
        to_status=to_status,
        actor=actor,
        note=note,
    )


def log_event(entity, action, actor=None, old=None, new=None, reason=''):
    AuditEvent.objects.create(
        entity_type=entity.__class__.__name__,
        entity_id=entity.pk,
        action=action,
        old_value=old,
        new_value=new,
        actor=actor,
        reason=reason,
    )


def set_status(entity, new_status, actor=None, note='', field='status'):
    old = getattr(entity, field)
    if old == new_status:
        return
    setattr(entity, field, new_status)
    entity.save(update_fields=[field, 'updated_at'] if hasattr(entity, 'updated_at') else [field])
    log_status(entity, new_status, actor=actor, from_status=old, note=note)


# ---------------------------------------------------------------------------
# Inventory ledger
# ---------------------------------------------------------------------------
def _balance(item, warehouse):
    bal, _ = StockBalance.objects.get_or_create(item=item, warehouse=warehouse)
    return bal


def post_transaction(txn_type, item, warehouse, quantity, *, onhand_delta=ZERO,
                     reserved_delta=ZERO, coil=None, weight=ZERO, job_order=None,
                     production_run=None, ref_type='', ref_id=None, reason='', user=None):
    """The single choke point for stock movement. Applies balance deltas and
    writes an immutable ledger row."""
    if onhand_delta or reserved_delta:
        bal = _balance(item, warehouse)
        bal.qty_on_hand = bal.qty_on_hand + onhand_delta
        bal.qty_reserved = bal.qty_reserved + reserved_delta
        bal.save(update_fields=['qty_on_hand', 'qty_reserved'])
    return InventoryTransaction.objects.create(
        txn_type=txn_type, item=item, warehouse=warehouse, coil=coil,
        quantity=quantity, weight=weight, job_order=job_order,
        production_run=production_run, ref_type=ref_type, ref_id=ref_id,
        reason=reason, created_by=user,
    )


def receive_stock(item, warehouse, qty, user=None, weight=ZERO, coil=None, reason=''):
    return post_transaction(
        C.InventoryTxnType.RECEIVE, item, warehouse, qty,
        onhand_delta=qty, weight=weight, coil=coil, reason=reason, user=user,
    )


def receive_coil(coil, user=None):
    """Bring a coil on hand (length added to its item's balance)."""
    coil.remaining_length_m = coil.remaining_length_m or coil.original_length_m
    coil.remaining_weight_kg = coil.remaining_weight_kg or coil.original_weight_kg
    coil.save(update_fields=['remaining_length_m', 'remaining_weight_kg'])
    return receive_stock(
        coil.item, coil.warehouse, coil.original_length_m, user=user,
        weight=coil.original_weight_kg, coil=coil, reason='Coil receipt',
    )


def reserve(item, warehouse, qty, job_order=None, coil=None, user=None):
    if coil:
        coil.status = C.CoilStatus.RESERVED
        coil.save(update_fields=['status'])
    return post_transaction(
        C.InventoryTxnType.RESERVE, item, warehouse, qty,
        reserved_delta=qty, coil=coil, job_order=job_order,
        ref_type='JobOrder', ref_id=job_order.pk if job_order else None, user=user,
    )


def unreserve(item, warehouse, qty, job_order=None, coil=None, user=None, reason=''):
    if coil and coil.status == C.CoilStatus.RESERVED:
        coil.status = C.CoilStatus.AVAILABLE
        coil.save(update_fields=['status'])
    return post_transaction(
        C.InventoryTxnType.UNRESERVE, item, warehouse, qty,
        reserved_delta=-qty, coil=coil, job_order=job_order, reason=reason, user=user,
    )


@transaction.atomic
def issue_to_production(res_line, qty, user=None):
    """Move material from stock (and the coil) onto the floor."""
    item = res_line.item
    wh = res_line.warehouse
    coil = res_line.coil
    post_transaction(
        C.InventoryTxnType.ISSUE_PRODUCTION, item, wh, qty,
        onhand_delta=-qty, reserved_delta=-qty, coil=coil,
        job_order=res_line.reservation.job_order, ref_type='MaterialReservationLine',
        ref_id=res_line.pk, user=user,
    )
    if coil:
        coil.remaining_length_m = coil.remaining_length_m - qty
        coil.status = C.CoilStatus.IN_USE
        coil.save(update_fields=['remaining_length_m', 'status'])
    res_line.qty_issued = res_line.qty_issued + qty
    res_line.status = (C.ReservationStatus.FULLY_ISSUED if res_line.qty_open <= 0
                       else C.ReservationStatus.PARTIALLY_ISSUED)
    res_line.save(update_fields=['qty_issued', 'status'])
    _rollup_reservation(res_line.reservation)
    return res_line


def _rollup_reservation(reservation):
    lines = list(reservation.lines.all())
    if lines and all(l.qty_open <= 0 for l in lines):
        reservation.status = C.ReservationStatus.FULLY_ISSUED
    elif any(l.qty_issued > 0 for l in lines):
        reservation.status = C.ReservationStatus.PARTIALLY_ISSUED
    reservation.save(update_fields=['status'])


@transaction.atomic
def record_coil_consumption(run, jo_line, coil, consumed_length, scrap_length=ZERO, user=None):
    """Traceability record of how much of an issued coil a run used."""
    before = coil.remaining_length_m
    weight = ZERO
    if coil.item.weight_factor_kg_per_lm:
        weight = consumed_length * coil.item.weight_factor_kg_per_lm
    CoilConsumption.objects.create(
        production_run=run, job_order_line=jo_line, coil=coil,
        length_before=before, length_after=coil.remaining_length_m,
        length_consumed=consumed_length, weight_consumed=weight, scrap_length=scrap_length,
    )
    post_transaction(
        C.InventoryTxnType.CONSUME, coil.item, coil.warehouse, consumed_length,
        coil=coil, production_run=run, job_order=run.job_order,
        ref_type='JobOrderLine', ref_id=jo_line.pk, user=user, reason='Production consume',
    )
    if scrap_length:
        post_transaction(
            C.InventoryTxnType.SCRAP, coil.item, coil.warehouse, scrap_length,
            coil=coil, production_run=run, job_order=run.job_order, user=user, reason='Scrap',
        )


@transaction.atomic
def receive_finished_goods(run, jo_line, warehouse, good_qty, user=None):
    """Post produced good units into Finished Goods (always, per policy)."""
    item = jo_line.item
    lot = FinishedGoodsLot.objects.create(
        lot_number=next_number('fg_lot'), item=item, job_order=run.job_order,
        job_order_line=jo_line, production_run=run, warehouse=warehouse,
        qty_produced=good_qty, qty_available=good_qty, uom=jo_line.uom,
    )
    if item:
        post_transaction(
            C.InventoryTxnType.FG_RECEIPT, item, warehouse, good_qty,
            onhand_delta=good_qty, production_run=run, job_order=run.job_order,
            ref_type='FinishedGoodsLot', ref_id=lot.pk, user=user, reason='FG receipt',
        )
    jo_line.qty_produced = jo_line.qty_produced + good_qty
    jo_line.save(update_fields=['qty_produced'])
    return lot


@transaction.atomic
def deliver_from_lot(delivery, lot, jo_line, qty, item, description, uom, user=None):
    """Ship FG and reduce stock + lot availability."""
    from .models import DeliveryLine
    DeliveryLine.objects.create(
        delivery=delivery, job_order_line=jo_line, fg_lot=lot, item=item,
        description=description, quantity=qty, uom=uom,
    )
    if lot:
        lot.qty_available = lot.qty_available - qty
        lot.qty_delivered = lot.qty_delivered + qty
        if lot.qty_available <= 0:
            lot.status = C.FGLotStatus.SHIPPED
        lot.save(update_fields=['qty_available', 'qty_delivered', 'status'])
    if item:
        post_transaction(
            C.InventoryTxnType.DELIVERY_ISSUE, item, delivery.job_order.warehouse if delivery.job_order and delivery.job_order.warehouse else lot.warehouse,
            qty, onhand_delta=-qty, ref_type='Delivery', ref_id=delivery.pk, user=user,
            reason='Delivery issue',
        )
    if jo_line:
        jo_line.qty_delivered = jo_line.qty_delivered + qty
        jo_line.save(update_fields=['qty_delivered'])


# ---------------------------------------------------------------------------
# Material estimation (configurable, formula-light for Phase 1)
# ---------------------------------------------------------------------------
def resolve_raw_item(jo_line):
    """Best-effort mapping of a finished line to the raw coil item it consumes.

    Matches the finished item's thickness (and the profile's default coil width)
    to a RAW_MATERIAL coil item. Falls back to the line item itself. This is the
    Phase-1 stand-in for full BOM resolution (Phase 2).
    """
    from .models import Item
    item = jo_line.item
    if item is None:
        return None
    if item.item_type == C.ItemType.RAW_MATERIAL:
        return item
    qs = Item.objects.filter(item_type=C.ItemType.RAW_MATERIAL, is_active=True)
    if item.thickness_mm is not None:
        qs = qs.filter(thickness_mm=item.thickness_mm)
    if item.profile and item.profile.default_coil_width_mm is not None:
        width_qs = qs.filter(coil_width_mm=item.profile.default_coil_width_mm)
        if width_qs.exists():
            qs = width_qs
    return qs.first() or item


def estimate_line_material(jo_line):
    """Estimate raw coil length for a manufactured roofing/bended line.

    Uses spec length x qty inflated by the profile (or default) waste percent.
    Waste and widths come from data, never hard-coded values.
    """
    specs = jo_line.specs_json or {}
    item = jo_line.item
    qty = jo_line.quantity or Decimal('0')
    length = _to_decimal(specs.get('length') or specs.get('length_m'))
    waste_pct = None
    if item and item.profile and item.profile.waste_pct is not None:
        waste_pct = item.profile.waste_pct
    if waste_pct is None:
        waste_pct = get_decimal('material.default_waste_pct', '5')
    if length and qty:
        base_lm = length * qty
    else:
        # accessory / girth based: fall back to qty as linear meters
        base_lm = qty
    required_lm = base_lm * (Decimal('1') + waste_pct / Decimal('100'))
    coil_item = resolve_raw_item(jo_line)
    weight = ZERO
    if coil_item and coil_item.weight_factor_kg_per_lm:
        weight = required_lm * coil_item.weight_factor_kg_per_lm
    return {'required_lm': required_lm.quantize(Decimal('0.001')),
            'weight': weight.quantize(Decimal('0.001')),
            'raw_item': coil_item}


def _to_decimal(v):
    if v in (None, ''):
        return None
    try:
        return Decimal(str(v))
    except Exception:
        return None


def build_job_requirements(job_order, user=None):
    """(Re)build estimated material requirements for a job order."""
    for line in job_order.lines.all():
        if not line.is_manufactured:
            continue
        est = estimate_line_material(line)
        raw_item = est['raw_item'] or line.item  # best-effort raw item link
        if raw_item is None:
            continue
        req, _ = JobMaterialRequirement.objects.get_or_create(
            job_order_line=line, item=raw_item,
            defaults={'uom': 'LM'},
        )
        req.estimated_qty = est['required_lm']
        req.estimated_weight = est['weight']
        req.uom = req.uom or 'LM'
        req.save()


# ---------------------------------------------------------------------------
# Quotation line sizes / drawings
# ---------------------------------------------------------------------------
def sync_quotation_line_derived(line):
    """Keep a quotation line's derived data in sync with its ``specs_json``:

    * mirror the free-form size rows into normalized ``QuotationLineSpec`` rows so
      they are reportable and survive snapshotting to invoice / job order, and
    * cache the attached drawing's name/id inside ``specs_json`` so the reference
      still prints on downstream documents even though the FK isn't copied.
    """
    line.specs.all().delete()
    for row in (line.specs_json or {}).get('specs', []):
        label = (row.get('label') or '').strip()
        value = (row.get('value') or '').strip()
        if label or value:
            QuotationLineSpec.objects.create(
                line=line, attribute_code=label or 'spec', value=value)

    sj = dict(line.specs_json or {})
    if line.standard_drawing_id:
        sj['drawing_id'] = line.standard_drawing_id
        sj['drawing_name'] = line.standard_drawing.name
    else:
        sj.pop('drawing_id', None)
        sj.pop('drawing_name', None)
    if sj != (line.specs_json or {}):
        line.specs_json = sj
        line.save(update_fields=['specs_json'])


# ---------------------------------------------------------------------------
# Snapshotting: quote -> invoice -> job order
# ---------------------------------------------------------------------------
@transaction.atomic
def create_invoice_from_quotation(quotation, user=None):
    """Copy an accepted quotation into a new invoice, snapshotting price+specs."""
    inv = Invoice.objects.create(
        number=next_number('invoice'), customer=quotation.customer, quotation=quotation,
        status=C.InvoiceStatus.DRAFT, invoice_date=timezone.localdate(),
        payment_term=quotation.payment_term, tax_code=quotation.tax_code,
        delivery_address=quotation.delivery_address, customer_ref=quotation.customer_ref,
        discount=quotation.discount, created_by=user,
    )
    for ql in quotation.lines.all():
        il = InvoiceLine.objects.create(
            invoice=inv, item=ql.item, source_quotation_line=ql,
            description=ql.description, quantity=ql.quantity, uom=ql.uom,
            unit_price=ql.unit_price, discount=ql.discount,
            specs_json=dict(ql.specs_json or {}), sort=ql.sort,
        )
        for s in ql.specs.all():
            InvoiceLineSpec.objects.create(
                line=il, attribute_code=s.attribute_code, value=s.value)
    log_status(inv, inv.status, actor=user, note='Created from quotation')
    log_event(inv, 'create_from_quotation', actor=user,
              new={'quotation': quotation.display_number})
    return inv


@transaction.atomic
def create_job_order_from_invoice(invoice, user=None, override_duplicate=False):
    """Create a Pending-Release job order from an approved invoice (controlled
    release -- never auto-started)."""
    existing = invoice.job_orders.exclude(status=C.JobOrderStatus.CANCELLED)
    if existing.exists() and not override_duplicate:
        raise ValueError('An active job order already exists for this invoice.')

    jo = JobOrder.objects.create(
        number=next_number('job_order'), invoice=invoice, quotation=invoice.quotation,
        customer=invoice.customer, status=C.JobOrderStatus.PENDING_RELEASE,
        created_by=user,
    )
    drawing_pending = False
    for il in invoice.lines.all():
        item = il.item
        is_mfg = bool(item.is_manufactured) if item else True
        needs_dwg = bool(item.requires_drawing) if item else False
        if needs_dwg:
            drawing_pending = True
        jl = JobOrderLine.objects.create(
            job_order=jo, item=item, source_invoice_line=il, description=il.description,
            quantity=il.quantity, uom=il.uom, is_manufactured=is_mfg,
            requires_drawing=needs_dwg, specs_json=dict(il.specs_json or {}), sort=il.sort,
        )
        for s in il.specs.all():
            JobOrderLineSpec.objects.create(
                line=jl, attribute_code=s.attribute_code, value=s.value)
        # Carry a custom sketch uploaded on the source quotation line to the shop.
        ql = il.source_quotation_line
        if ql and ql.custom_image:
            try:
                DrawingAttachment.objects.create(
                    job_order_line=jl, file=ql.custom_image.name,
                    status=C.DrawingStatus.SUBMITTED, notes='From quotation')
            except Exception:
                pass

    # credit gate
    credit_hold = not _credit_satisfied(invoice, user)
    jo.drawing_pending = drawing_pending
    jo.credit_hold = credit_hold
    jo.save(update_fields=['drawing_pending', 'credit_hold'])
    build_job_requirements(jo, user=user)
    log_status(jo, jo.status, actor=user, note='Created from invoice')
    log_event(jo, 'create_from_invoice', actor=user, new={'invoice': invoice.number})
    return jo


def _credit_satisfied(invoice, user=None):
    mode = get_setting('credit.gate_mode', 'deposit')
    if mode == 'none':
        satisfied, required = True, ZERO
    elif mode == 'full':
        required = invoice.total
        satisfied = invoice.total_paid >= required
    else:  # deposit
        pct = get_decimal('credit.deposit_pct', '50')
        required = invoice.total * pct / Decimal('100')
        satisfied = invoice.total_paid >= required
    CreditCheckLog.objects.create(
        invoice=invoice, mode=mode, required_amount=required,
        satisfied=satisfied, decided_by=user,
        note=f'paid={invoice.total_paid} required={required}',
    )
    return satisfied


@transaction.atomic
def revise_quotation(quotation, user=None):
    """Freeze the current quotation and clone it into a new revision."""
    from django.db.models import Q, Max
    root = quotation.parent or quotation
    chain = Quotation.objects.filter(Q(pk=root.pk) | Q(parent=root))
    latest_rev = chain.aggregate(m=Max('revision_no'))['m'] or 0
    quotation.is_current = False
    quotation.save(update_fields=['is_current'])
    set_status(quotation, C.QuotationStatus.REVISED, actor=user, note='Superseded by revision')

    new_q = Quotation.objects.create(
        number=root.number, revision_no=latest_rev + 1, parent=root, is_current=True,
        customer=quotation.customer, status=C.QuotationStatus.DRAFT,
        quote_date=timezone.localdate(), valid_until=quotation.valid_until,
        payment_term=quotation.payment_term, tax_code=quotation.tax_code,
        price_list=quotation.price_list, salesperson=quotation.salesperson,
        delivery_address=quotation.delivery_address, project_site=quotation.project_site,
        customer_ref=quotation.customer_ref, discount=quotation.discount,
        notes=quotation.notes, created_by=user,
    )
    for ql in quotation.lines.all():
        nl = QuotationLine.objects.create(
            quotation=new_q, item=ql.item, description=ql.description, quantity=ql.quantity,
            uom=ql.uom, unit_price=ql.unit_price, discount=ql.discount,
            specs_json=dict(ql.specs_json or {}), sort=ql.sort,
        )
        for s in ql.specs.all():
            QuotationLineSpec.objects.create(
                line=nl, attribute_code=s.attribute_code, value=s.value)
    log_event(new_q, 'revise', actor=user, new={'from': quotation.display_number})
    return new_q


# ---------------------------------------------------------------------------
# Job order release + rollup
# ---------------------------------------------------------------------------
@transaction.atomic
def release_job_order(job_order, user=None):
    """Reserve estimated material and move the JO onto the production floor,
    honouring the drawing and credit gates."""
    _refresh_gates(job_order)
    if job_order.drawing_pending:
        raise ValueError('Cannot release: a required drawing is not yet verified.')
    if job_order.credit_hold and not (user and user.has_perm_code('credit.override')):
        raise ValueError('Cannot release: credit / payment gate not satisfied.')

    reservation = MaterialReservation.objects.create(
        job_order=job_order, status=C.ReservationStatus.RESERVED, created_by=user)
    short = False
    wh = job_order.warehouse
    for line in job_order.lines.all():
        for req in line.requirements.all():
            item = req.item
            target_wh = wh or _first_warehouse_with_stock(item)
            if target_wh is None:
                short = True
                continue
            bal = StockBalance.objects.filter(item=item, warehouse=target_wh).first()
            available = bal.qty_available if bal else ZERO
            if available < req.estimated_qty:
                short = True
            reserve(item, target_wh, req.estimated_qty, job_order=job_order, user=user)
            MaterialReservationLine.objects.create(
                reservation=reservation, requirement=req, item=item, warehouse=target_wh,
                qty_reserved=req.estimated_qty, status=C.ReservationStatus.RESERVED,
            )
    job_order.material_short = short
    job_order.released_by = user
    job_order.released_at = timezone.now()
    job_order.save(update_fields=['material_short', 'released_by', 'released_at'])
    set_status(job_order, C.JobOrderStatus.RELEASED, actor=user, note='Released to production')
    return reservation


def _first_warehouse_with_stock(item):
    bal = item.stock_balances.order_by('-qty_on_hand').first()
    if bal:
        return bal.warehouse
    from .models import Warehouse
    return Warehouse.objects.first()


def _refresh_gates(job_order):
    """Recompute the drawing gate from current drawing verification state."""
    drawing_pending = False
    for line in job_order.lines.filter(requires_drawing=True):
        verified = line.drawings.filter(status=C.DrawingStatus.VERIFIED).exists()
        if not verified:
            drawing_pending = True
    if job_order.drawing_pending != drawing_pending:
        job_order.drawing_pending = drawing_pending
        job_order.save(update_fields=['drawing_pending'])


def rollup_job_order(job_order, user=None):
    lines = list(job_order.lines.all())
    if not lines:
        return
    if all(l.qty_produced >= l.quantity for l in lines):
        new = C.JobOrderStatus.COMPLETE
    elif any(l.qty_produced > 0 for l in lines):
        new = C.JobOrderStatus.PARTIALLY_COMPLETE
    else:
        new = job_order.status
    if new != job_order.status and job_order.status not in (
            C.JobOrderStatus.CANCELLED, C.JobOrderStatus.CLOSED):
        set_status(job_order, new, actor=user, note='Auto rollup from production')


@transaction.atomic
def cancel_job_order(job_order, user=None, reason=''):
    """Cancel a JO and release any outstanding reservations."""
    for reservation in job_order.reservations.all():
        for rl in reservation.lines.all():
            if rl.qty_open > 0:
                unreserve(rl.item, rl.warehouse, rl.qty_open, job_order=job_order,
                          coil=rl.coil, user=user, reason='JO cancelled')
                rl.status = C.ReservationStatus.CANCELLED
                rl.save(update_fields=['status'])
        reservation.status = C.ReservationStatus.CANCELLED
        reservation.save(update_fields=['status'])
    set_status(job_order, C.JobOrderStatus.CANCELLED, actor=user, note=reason)
    log_event(job_order, 'cancel', actor=user, reason=reason)
