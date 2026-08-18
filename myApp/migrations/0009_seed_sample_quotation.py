"""Seed the Zenland Dev't Corp sales quotation (from the printed FEG quote).

Reproduces the real quotation faithfully (line items, per-line discounts and a
delivery charge) so production has a realistic example. Idempotent: keyed on
``customer_ref`` so re-running migrate won't duplicate it. Lines carry only
text/price (``item`` left null) so it doesn't depend on the product catalog.
"""
import datetime
from decimal import Decimal

from django.contrib.auth.hashers import make_password
from django.db import migrations

MARKER = 'ZENLAND-SAMPLE'
D = Decimal


def seed_quote(apps, schema_editor):
    Quotation = apps.get_model('myApp', 'Quotation')
    QuotationLine = apps.get_model('myApp', 'QuotationLine')
    Customer = apps.get_model('myApp', 'Customer')
    User = apps.get_model('myApp', 'User')
    Role = apps.get_model('myApp', 'Role')
    PaymentTerm = apps.get_model('myApp', 'PaymentTerm')
    NumberSeries = apps.get_model('myApp', 'NumberSeries')

    if Quotation.objects.filter(customer_ref=MARKER).exists():
        return

    customer, _ = Customer.objects.get_or_create(
        name="Zenland Dev't Corp.",
        defaults={'address': 'Munting Pulo, Lipa City', 'code': 'CUST-ZENLAND'})

    # Sales rep named on the quote (label only; no usable login).
    janet, created = User.objects.get_or_create(
        username='janet',
        defaults={'first_name': 'Janet', 'last_name': 'Cuevas',
                  'email': 'janet@foremosteg.com', 'is_active': True,
                  'password': make_password(None)})
    sales_role = Role.objects.filter(name='Sales').first()
    if sales_role:
        janet.roles.add(sales_role)

    admin = User.objects.filter(username='admin').first()
    term = PaymentTerm.objects.filter(code='50DP').first()

    # Allocate a proper quotation number and advance the series if present.
    series = NumberSeries.objects.filter(key='quotation').first()
    if series:
        n = series.next_number
        number = f'{series.prefix}{str(n).zfill(series.padding)}'
        series.next_number = n + 1
        series.save()
    else:
        number = 'QT-00001'

    quote = Quotation.objects.create(
        number=number, customer=customer, status='accepted',
        quote_date=datetime.date(2026, 7, 31),
        valid_until=datetime.date(2026, 8, 7),
        payment_term=term, salesperson=janet, created_by=admin,
        delivery_address='Munting Pulo, Lipa City',
        project_site='Munting Pulo, Lipa City',
        customer_ref=MARKER, discount=D('0.00'),
        notes=('Color: Gray. Strictly no cancellation once conformed. '
               '50% down payment, full payment upon delivery/pick up. '
               'Lead time 5-7 working days upon clearing of payments. '
               'Quotation valid for 7 days.'))

    lines = [
        dict(description='Barcelona Rib 0.5mm x 1220 XLS (S-RIBS) - Gray',
             quantity=D('172.20'), uom='LM', unit_price=D('450.00'),
             discount=D('20147.40'), sort=0,
             specs_json={'specs': [{'label': 'Color', 'value': 'Gray'},
                                   {'label': 'Thickness', 'value': '0.5mm'}],
                         'lengths': [{'pcs': 82, 'len': 2.10}]}),
        dict(description='Ridge Roll 0.5mm x 24" x 8\' (STD) - Gray',
             quantity=D('5'), uom='PC', unit_price=D('585.00'),
             discount=D('0.00'), sort=1,
             specs_json={'specs': [{'label': 'Color', 'value': 'Gray'},
                                   {'label': 'Size', 'value': '24" x 8\''}]}),
        dict(description='Wall Flashing 0.5mm x 24" x 8\' (with details) - Gray',
             quantity=D('40'), uom='PC', unit_price=D('585.00'),
             discount=D('5528.25'), sort=2,
             specs_json={'specs': [{'label': 'Color', 'value': 'Gray'},
                                   {'label': 'Size', 'value': '24" x 8\''}]}),
        dict(description='Delivery Charge', quantity=D('1'), uom='',
             unit_price=D('3000.00'), discount=D('0.00'), sort=3, specs_json={}),
    ]
    for data in lines:
        QuotationLine.objects.create(quotation=quote, **data)


def unseed(apps, schema_editor):
    Quotation = apps.get_model('myApp', 'Quotation')
    Quotation.objects.filter(customer_ref=MARKER).delete()


class Migration(migrations.Migration):

    dependencies = [
        ('myApp', '0008_seed_accounts'),
    ]

    operations = [
        migrations.RunPython(seed_quote, unseed),
    ]
