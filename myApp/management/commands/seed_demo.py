"""Seed demo *transactions* on top of the master data from ``seed_erp``.

Creates quotations, invoices and job orders at every stage of the workflow so
each board has realistic in-flight data — including a quotation that is still
awaiting approval and an invoice that is not yet approved.

Run ``python manage.py seed_erp`` first (masters + users), then this command.
Idempotent: re-running skips if demo data already exists (use --reset to rebuild).
"""
from decimal import Decimal

from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from myApp import constants as C
from myApp import services
from myApp.models import (
    Customer, CustomerAcceptance, Item, Quotation, QuotationLine, User,
)

D = Decimal
MARKER = 'DEMO'


class Command(BaseCommand):
    help = 'Seed demo quotations / invoices / job orders across all stages.'

    def add_arguments(self, parser):
        parser.add_argument('--reset', action='store_true',
                            help='Delete existing demo documents first.')

    @transaction.atomic
    def handle(self, *args, **options):
        if options['reset']:
            self._reset()
        if Quotation.objects.filter(customer_ref=MARKER).exists():
            self.stdout.write(self.style.WARNING(
                'Demo data already present. Use --reset to rebuild.'))
            return

        admin = User.objects.filter(is_superuser=True).first()
        sales = User.objects.filter(username='sales').first() or admin
        acme = self._customer('Acme Construction')
        bayside = self._customer('Bayside Realty')

        # Common line templates (item code, description, qty, uom, price, specs)
        rib = self._line('FG-BARCA_RIB-0.5', 20, D('450'),
                         {'length': '6', 'thickness': '0.5', 'profile': 'BARCA_RIB'})
        florence = self._line('FG-FLORENCE-0.4', 15, D('350'),
                              {'length': '5', 'thickness': '0.4', 'profile': 'FLORENCE'})
        monaco = self._line('FG-MONACO-0.6', 30, D('645'),
                            {'length': '6', 'thickness': '0.6', 'profile': 'MONACO'})
        screws = self._line('HW-TEXSCREW', 500, D('2.5'), {})

        made = []

        # 1) Draft quotation (not yet submitted)
        made.append(self._quote(acme, sales, C.QuotationStatus.DRAFT, [florence], admin))
        # 2) Pending approval quotation  <-- "already but not yet approved"
        made.append(self._quote(bayside, sales, C.QuotationStatus.PENDING_APPROVAL,
                                [rib, screws], admin))
        # 3) Approved (awaiting send)
        made.append(self._quote(acme, sales, C.QuotationStatus.APPROVED, [monaco], admin))
        # 4) Sent to customer (awaiting acceptance)
        made.append(self._quote(bayside, sales, C.QuotationStatus.SENT, [florence, screws], admin))

        # 5) Accepted -> Invoice left in DRAFT (invoice not yet approved)
        q_acc1 = self._quote(acme, sales, C.QuotationStatus.ACCEPTED, [rib], admin)
        inv1 = services.create_invoice_from_quotation(q_acc1, user=admin)

        # 6) Accepted -> Invoice approved -> Job Order pending release
        q_acc2 = self._quote(bayside, sales, C.QuotationStatus.ACCEPTED, [monaco], admin)
        inv2 = services.create_invoice_from_quotation(q_acc2, user=admin)
        services.set_status(inv2, C.InvoiceStatus.APPROVED, actor=admin)
        inv2.approved_by = admin
        inv2.approved_at = timezone.now()
        inv2.save(update_fields=['approved_by', 'approved_at'])
        services.create_job_order_from_invoice(inv2, user=admin)

        # 7) Accepted -> Invoice approved w/ deposit -> Job Order released (reserved)
        q_acc3 = self._quote(acme, sales, C.QuotationStatus.ACCEPTED, [rib, florence], admin)
        inv3 = services.create_invoice_from_quotation(q_acc3, user=admin)
        from myApp.models import Payment
        Payment.objects.create(invoice=inv3, amount=inv3.total, method=C.PaymentMethod.BANK_TRANSFER,
                               status=C.PaymentStatus.VERIFIED, recorded_by=admin)
        inv3.payment_state = C.PaymentState.PAID
        services.set_status(inv3, C.InvoiceStatus.APPROVED, actor=admin)
        inv3.approved_by = admin
        inv3.approved_at = timezone.now()
        inv3.save(update_fields=['approved_by', 'approved_at', 'payment_state'])
        jo3 = services.create_job_order_from_invoice(inv3, user=admin)
        try:
            services.release_job_order(jo3, user=admin)
        except ValueError as e:
            self.stdout.write(self.style.WARNING(f'  JO release skipped: {e}'))

        self.stdout.write(self.style.SUCCESS('\nDemo data created:'))
        self.stdout.write(f'  Quotations: {Quotation.objects.filter(customer_ref=MARKER).count()} '
                          '(draft, pending approval, approved, sent, 3x accepted)')
        self.stdout.write('  Invoices: 3 (1 draft/unapproved, 2 approved)')
        self.stdout.write('  Job Orders: 2 (1 pending release, 1 released & reserved)')

    # ------------------------------------------------------------------
    def _reset(self):
        from myApp.models import JobOrder, Invoice, ProductionRun
        qs = Quotation.objects.filter(customer_ref=MARKER)
        invoices = Invoice.objects.filter(quotation__in=qs)
        jos = JobOrder.objects.filter(invoice__in=invoices)
        if ProductionRun.objects.filter(job_order__in=jos).exists():
            self.stdout.write(self.style.WARNING(
                'Demo job orders have production runs; skipping reset of those.'))
            return
        jos.delete()
        invoices.delete()
        qs.delete()
        self.stdout.write('  demo documents reset')

    def _customer(self, name):
        c, _ = Customer.objects.get_or_create(name=name)
        return c

    def _line(self, item_code, qty, price, specs):
        item = Item.objects.filter(code=item_code).first()
        desc = str(item) if item else item_code
        return {'item': item, 'description': desc, 'quantity': D(qty),
                'uom': item.uom.code if item else 'PC', 'unit_price': price,
                'specs': specs}

    def _quote(self, customer, sales, status, lines, admin):
        q = Quotation.objects.create(
            number=services.next_number('quotation'), customer=customer,
            status=C.QuotationStatus.DRAFT, quote_date=timezone.localdate(),
            valid_until=timezone.localdate() + timezone.timedelta(days=30),
            salesperson=sales, customer_ref=MARKER, created_by=admin,
            tax_code=None,
        )
        for i, l in enumerate(lines):
            QuotationLine.objects.create(
                quotation=q, item=l['item'], description=l['description'],
                quantity=l['quantity'], uom=l['uom'], unit_price=l['unit_price'],
                specs_json=l['specs'], sort=i)
        if status != C.QuotationStatus.DRAFT:
            if status in (C.QuotationStatus.APPROVED, C.QuotationStatus.SENT,
                          C.QuotationStatus.ACCEPTED):
                q.approved_by = admin
                q.approved_at = timezone.now()
            if status in (C.QuotationStatus.SENT, C.QuotationStatus.ACCEPTED):
                q.sent_at = timezone.now()
            q.save()
            services.set_status(q, status, actor=admin, note='Demo seed')
            if status == C.QuotationStatus.ACCEPTED:
                CustomerAcceptance.objects.create(
                    quotation=q, accepted_by_name='Demo Client',
                    reference='PO-DEMO', recorded_by=admin)
        return q
