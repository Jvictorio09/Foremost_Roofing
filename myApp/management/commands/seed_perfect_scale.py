"""Seed the real 'PERFECT SCALE' sales quotation from the company's paper form.

Reproduces the quotation exactly, including:
  * the panel line with a per-piece length schedule (12x8m + 6x5m = 126 TLM) and
    the volume discount,
  * bended accessories (End Flashing / Box Gutter / Wall Flashing) each linked to
    its reference drawing, and
  * hardware (double-sided insulation) plus the delivery charge.

Grand total matches the paper form: 87,493.70 (no VAT line).

Run ``python manage.py seed_erp`` first for base masters/users. Idempotent:
re-running skips unless ``--reset`` is passed.
"""
from datetime import date
from decimal import Decimal

from django.core.management.base import BaseCommand
from django.db import transaction

from myApp import constants as C
from myApp import services
from myApp.models import (
    Color, Customer, Item, ItemCategory, Quotation, QuotationLine, StandardDrawing,
    UnitOfMeasure, User,
)

D = Decimal
MARKER = 'PERFECT-SCALE'


class Command(BaseCommand):
    help = "Seed the 'Perfect Scale' sales quotation from the paper form."

    def add_arguments(self, parser):
        parser.add_argument('--reset', action='store_true',
                            help='Delete the existing Perfect Scale quotation first.')

    @transaction.atomic
    def handle(self, *args, **options):
        if options['reset']:
            n = Quotation.objects.filter(customer_ref=MARKER).count()
            Quotation.objects.filter(customer_ref=MARKER).delete()
            if n:
                self.stdout.write(f'  reset {n} existing Perfect Scale quotation(s)')
        if Quotation.objects.filter(customer_ref=MARKER).exists():
            self.stdout.write(self.style.WARNING(
                'Perfect Scale quotation already exists. Use --reset to rebuild.'))
            return

        admin = User.objects.filter(is_superuser=True).first()
        uoms = {c: UnitOfMeasure.objects.get_or_create(
            code=c, defaults={'name': c})[0] for c in ('LM', 'PC', 'ROLL')}
        cats = self._categories()
        gray = Color.objects.get_or_create(code='GRAY', defaults={'name': 'Gray'})[0]
        items = self._items(cats, uoms, gray)
        drawings = self._drawings(cats['BENDED'])
        customer = Customer.objects.get_or_create(
            name='PERFECT SCALE',
            defaults={'contact_person': 'Ms. Maria Anna Dimen', 'code': 'CUST-PSCALE'})[0]

        quotation = Quotation.objects.create(
            number=services.next_number('quotation'), customer=customer,
            status=C.QuotationStatus.DRAFT, quote_date=date(2026, 8, 5),
            valid_until=date(2026, 8, 12), salesperson=None, tax_code=None,
            discount=D('0'), customer_ref=MARKER,
            notes='Supply of Roofing & Ceiling Materials', created_by=admin)

        lines = [
            # I. Panel -- Barcelona Rib with length schedule + volume discount
            {'item': items['panel'], 'desc': 'BARCELONA RIB .5MM X 1220 X LS',
             'qty': D('126'), 'uom': 'TLM', 'price': D('450.00'), 'disc': D('15309.00'),
             'specs': {
                 'specs': [
                     {'label': 'Thickness', 'value': '.5mm'},
                     {'label': 'Feed Width', 'value': '1220'},
                     {'label': 'Profile', 'value': 'Barcelona Rib (8-Rib)'},
                     {'label': 'Color', 'value': 'Gray'},
                 ],
                 'lengths': [{'pcs': 12, 'len': 8.0}, {'pcs': 6, 'len': 5.0}],
             }},
            # II. Bended accessories
            {'item': items['endflash'], 'desc': 'END FLASHING .5MM X 24" X 8\'',
             'qty': D('20'), 'uom': 'PC', 'price': D('456.30'),
             'drawing': drawings['END-FLASH'],
             'specs': {'specs': [{'label': 'Size', 'value': '.5mm x 24" x 8\''},
                                 {'label': 'Style', 'value': 'STD'},
                                 {'label': 'Color', 'value': 'Gray'}]}},
            {'item': items['boxgutter'], 'desc': 'BOX GUTTER .5MM X 36" X 8\'',
             'qty': D('10'), 'uom': 'PC', 'price': D('772.20'),
             'drawing': drawings['BOX-GUTTER'],
             'specs': {'specs': [{'label': 'Size', 'value': '.5mm x 36" x 8\''},
                                 {'label': 'Style', 'value': 'STD'},
                                 {'label': 'Color', 'value': 'Gray'}]}},
            {'item': items['wallflash'], 'desc': 'WALL FLASHING .5MM X 12" X 8\'',
             'qty': D('5'), 'uom': 'PC', 'price': D('232.44'),
             'drawing': drawings['WALL-FLASH'],
             'specs': {'specs': [{'label': 'Size', 'value': '.5mm x 12" x 8\''},
                                 {'label': 'Style', 'value': 'STD'},
                                 {'label': 'Color', 'value': 'Gray'}]}},
            # III. Hardware accessories
            {'item': items['insulation'], 'desc': '10MM DOUBLE SIDED INSULATION',
             'qty': D('5'), 'uom': 'ROLL', 'price': D('4018.50'),
             'specs': {'specs': [{'label': 'Type', 'value': '10mm double sided'}]}},
            # Delivery charge (no item -> prints under "Other Items")
            {'item': None, 'desc': 'DELIVERY CHARGE', 'qty': D('1'), 'uom': '',
             'price': D('8000.00')},
        ]
        for i, l in enumerate(lines):
            line = QuotationLine.objects.create(
                quotation=quotation, item=l['item'], description=l['desc'],
                quantity=l['qty'], uom=l['uom'], unit_price=l['price'],
                discount=l.get('disc', D('0')), standard_drawing=l.get('drawing'),
                specs_json=l.get('specs', {}), sort=i)
            services.sync_quotation_line_derived(line)

        services.log_status(quotation, quotation.status, actor=admin,
                            note='Seeded from paper sales quotation')

        self.stdout.write(self.style.SUCCESS('\nPerfect Scale quotation seeded:'))
        self.stdout.write(f'  {quotation.number}  {customer.name}')
        self.stdout.write(f'  lines: {quotation.lines.count()}   '
                          f'grand total: {quotation.total:,.2f} (expected 87,493.70)')

    # ------------------------------------------------------------------
    def _categories(self):
        data = [
            ('ROOF', 'Roof Panel', C.ItemType.FINISHED_GOOD, False, True),
            ('BENDED', 'Bended Accessory', C.ItemType.FINISHED_GOOD, True, True),
            ('INSULATION', 'Insulation', C.ItemType.STOCK_RESALE, False, False),
        ]
        cats = {}
        for code, name, itype, dwg, mfg in data:
            cats[code] = ItemCategory.objects.get_or_create(
                code=code, defaults={'name': name, 'default_item_type': itype,
                                     'requires_drawing': dwg, 'is_manufactured': mfg})[0]
        return cats

    def _items(self, cats, uoms, gray):
        panel = Item.objects.get_or_create(
            code='FG-BARCA_RIB-0.5', defaults={
                'name': 'Barcelona Rib 0.5mm', 'item_type': C.ItemType.FINISHED_GOOD,
                'category': cats['ROOF'], 'uom': uoms['LM'], 'color': gray,
                'thickness_mm': D('0.5'), 'is_manufactured': True})[0]
        endflash = Item.objects.get_or_create(
            code='BND-END-FLASHING', defaults={
                'name': 'End Flashing', 'item_type': C.ItemType.FINISHED_GOOD,
                'category': cats['BENDED'], 'uom': uoms['PC'], 'is_manufactured': True,
                'requires_drawing': True})[0]
        boxgutter = Item.objects.get_or_create(
            code='BND-BOX-GUTTER', defaults={
                'name': 'Box Gutter', 'item_type': C.ItemType.FINISHED_GOOD,
                'category': cats['BENDED'], 'uom': uoms['PC'], 'is_manufactured': True,
                'requires_drawing': True})[0]
        wallflash = Item.objects.get_or_create(
            code='BND-WALL-FLASHING', defaults={
                'name': 'Wall Flashing', 'item_type': C.ItemType.FINISHED_GOOD,
                'category': cats['BENDED'], 'uom': uoms['PC'], 'is_manufactured': True,
                'requires_drawing': True})[0]
        insulation = Item.objects.get_or_create(
            code='INS-DS10', defaults={
                'name': '10mm Double Sided Insulation',
                'item_type': C.ItemType.STOCK_RESALE, 'category': cats['INSULATION'],
                'uom': uoms['ROLL'], 'standard_cost': D('4018.50')})[0]
        return {'panel': panel, 'endflash': endflash, 'boxgutter': boxgutter,
                'wallflash': wallflash, 'insulation': insulation}

    def _drawings(self, bended):
        data = [
            ('END-FLASH', 'End Flashing', '24"', 'end_flashing.png'),
            ('BOX-GUTTER', 'Box Gutter', '36"', 'box_gutter.png'),
            ('WALL-FLASH', 'Wall Flashing', '12"', 'wall_flashing.png'),
        ]
        drawings = {}
        for code, name, girth, fname in data:
            drawings[code] = StandardDrawing.objects.get_or_create(
                code=code, defaults={
                    'name': name, 'category': bended, 'default_girth': girth,
                    'image': f'drawings/standard/{fname}'})[0]
        return drawings
