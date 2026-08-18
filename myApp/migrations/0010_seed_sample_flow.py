"""Seed the downstream lifecycle for the Zenland sample quotation.

Builds Invoice (approved, part-paid) -> Job Order (complete) -> Delivery
(delivered) from the quotation seeded in 0009, so the demo shows the full
Quotation -> Delivery flow. Idempotent (keyed on customer_ref) and catalog-free
(lines carry text only, no Item/FG-lot dependencies).
"""
import datetime
from decimal import Decimal

from django.db import migrations
from django.utils import timezone

MARKER = 'ZENLAND-SAMPLE'
D = Decimal


def _aware(y, m, d, hh=9, mm=0):
    return timezone.make_aware(datetime.datetime(y, m, d, hh, mm))


def _next_number(NumberSeries, key, fallback):
    series = NumberSeries.objects.filter(key=key).first()
    if not series:
        return fallback
    n = series.next_number
    number = f'{series.prefix}{str(n).zfill(series.padding)}'
    series.next_number = n + 1
    series.save()
    return number


def seed_flow(apps, schema_editor):
    Quotation = apps.get_model('myApp', 'Quotation')
    Invoice = apps.get_model('myApp', 'Invoice')
    InvoiceLine = apps.get_model('myApp', 'InvoiceLine')
    Payment = apps.get_model('myApp', 'Payment')
    JobOrder = apps.get_model('myApp', 'JobOrder')
    JobOrderLine = apps.get_model('myApp', 'JobOrderLine')
    Delivery = apps.get_model('myApp', 'Delivery')
    DeliveryLine = apps.get_model('myApp', 'DeliveryLine')
    Warehouse = apps.get_model('myApp', 'Warehouse')
    User = apps.get_model('myApp', 'User')
    NumberSeries = apps.get_model('myApp', 'NumberSeries')

    quote = Quotation.objects.filter(customer_ref=MARKER).first()
    if not quote:
        return
    if Invoice.objects.filter(customer_ref=MARKER).exists():
        return

    admin = User.objects.filter(username='admin').first()
    warehouse = (Warehouse.objects.filter(code='LIPA').first()
                 or Warehouse.objects.first())
    quote_lines = list(quote.lines.all())

    # --- Invoice (approved) -------------------------------------------------
    invoice = Invoice.objects.create(
        number=_next_number(NumberSeries, 'invoice', 'INV-00001'),
        customer=quote.customer, quotation=quote, status='approved',
        payment_state='partial', invoice_date=datetime.date(2026, 8, 1),
        due_date=datetime.date(2026, 8, 8), payment_term=quote.payment_term,
        delivery_address=quote.delivery_address, customer_ref=MARKER,
        discount=D('0.00'), created_by=admin, approved_by=admin,
        approved_at=_aware(2026, 8, 1, 10), notes='Snapshotted from QT.')
    for ql in quote_lines:
        InvoiceLine.objects.create(
            invoice=invoice, item=ql.item, source_quotation_line=ql,
            description=ql.description, quantity=ql.quantity, uom=ql.uom,
            unit_price=ql.unit_price, discount=ql.discount,
            specs_json=dict(ql.specs_json or {}), sort=ql.sort)

    # 50% down payment -> invoice sits at "partial".
    Payment.objects.create(
        invoice=invoice, amount=D('40569.68'), method='bank',
        reference='50% down payment', status='verified',
        received_at=_aware(2026, 8, 1, 11), recorded_by=admin)

    # --- Job Order (complete) ----------------------------------------------
    product_lines = [l for l in invoice.lines.all()
                     if l.description != 'Delivery Charge']
    job = JobOrder.objects.create(
        number=_next_number(NumberSeries, 'job_order', 'JO-00001'),
        invoice=invoice, quotation=quote, customer=quote.customer,
        status='complete', priority='normal', warehouse=warehouse,
        required_date=datetime.date(2026, 8, 7), drawing_pending=False,
        material_short=False, credit_hold=False, created_by=admin,
        released_by=admin, released_at=_aware(2026, 8, 1, 12),
        notes='Produced and delivered (demo).')
    jo_lines = []
    for il in product_lines:
        jol = JobOrderLine.objects.create(
            job_order=job, item=il.item, source_invoice_line=il,
            description=il.description, quantity=il.quantity, uom=il.uom,
            qty_produced=il.quantity, qty_delivered=il.quantity,
            is_manufactured=True,
            requires_drawing='Flashing' in il.description,
            specs_json=dict(il.specs_json or {}), sort=il.sort)
        jo_lines.append(jol)

    # --- Delivery (delivered) ----------------------------------------------
    delivery = Delivery.objects.create(
        number=_next_number(NumberSeries, 'delivery', 'DR-00001'),
        customer=quote.customer, invoice=invoice, job_order=job,
        status='delivered', delivery_address=quote.delivery_address,
        truck='FEG Delivery Truck', driver='Company Driver',
        scheduled_for=_aware(2026, 8, 7, 8), dispatched_at=_aware(2026, 8, 7, 9),
        delivered_at=_aware(2026, 8, 7, 14), prepared_by=admin,
        released_by=admin, received_by='Zenland Site Representative',
        notes='Delivered in full (demo).')
    for jol in jo_lines:
        DeliveryLine.objects.create(
            delivery=delivery, job_order_line=jol, item=jol.item,
            description=jol.description, quantity=jol.quantity, uom=jol.uom)


def unseed(apps, schema_editor):
    Invoice = apps.get_model('myApp', 'Invoice')
    Delivery = apps.get_model('myApp', 'Delivery')
    JobOrder = apps.get_model('myApp', 'JobOrder')
    # Delete children first to respect PROTECT constraints.
    Delivery.objects.filter(invoice__customer_ref=MARKER).delete()
    JobOrder.objects.filter(invoice__customer_ref=MARKER).delete()
    Invoice.objects.filter(customer_ref=MARKER).delete()


class Migration(migrations.Migration):

    dependencies = [
        ('myApp', '0009_seed_sample_quotation'),
    ]

    operations = [
        migrations.RunPython(seed_flow, unseed),
    ]
