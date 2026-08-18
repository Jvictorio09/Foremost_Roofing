"""Seed RBAC, master data and a demo transaction set for the Foremost EG ERP.

Master values (profiles, colors, thicknesses, widths, prices, waste factors) are
taken from the company's published price list and product primer and loaded as
DATA -- they can all be edited in-app afterwards.
"""
from datetime import date
from decimal import Decimal

from django.core.management.base import BaseCommand
from django.db import transaction

from myApp import constants as C
from myApp.models import (
    AppSetting, AttributeDefinition, AttributeOption, CategoryAttribute, Coil,
    Color, Customer, Item, ItemCategory, Machine, NumberSeries, PaymentTerm,
    Permission, PriceList, PriceListVersion, PriceMatrixRow, Profile, ProfileAlias,
    Role, Supplier, TaxCode, UnitOfMeasure, User, Warehouse,
)
from myApp.services import receive_coil

D = Decimal


class Command(BaseCommand):
    help = 'Seed permissions, roles, master data and demo records.'

    @transaction.atomic
    def handle(self, *args, **options):
        self._permissions()
        roles = self._roles()
        self._settings()
        self._number_series()
        uoms = self._uoms()
        terms, taxes = self._terms_taxes()
        warehouses, machines = self._warehouses_machines()
        colors = self._colors()
        categories = self._categories()
        self._attributes(categories)
        self._profiles(categories, machines)
        items = self._items(categories, uoms, colors)
        self._pricing(items, uoms)
        supplier = self._supplier()
        self._coils(items, colors, warehouses, supplier)
        self._users(roles)
        self._demo_customer_quote(uoms)
        self.stdout.write(self.style.SUCCESS('\nSeed complete.'))
        self.stdout.write('Logins (password: password123): admin (Super Admin), '
                          'sales, billing, inventory, production, logistics, manager')

    # ------------------------------------------------------------------
    def _permissions(self):
        for code, label, group in C.PERMISSION_CATALOG:
            Permission.objects.update_or_create(
                code=code, defaults={'label': label, 'group': group})
        self.stdout.write(f'  permissions: {Permission.objects.count()}')

    def _roles(self):
        roles = {}
        for name, codes in C.DEFAULT_ROLES.items():
            role, _ = Role.objects.get_or_create(
                name=name, defaults={'is_system': name == 'Super Admin'})
            perms = Permission.objects.filter(code__in=codes)
            role.permissions.set(perms)
            roles[name] = role
        self.stdout.write(f'  roles: {Role.objects.count()}')
        return roles

    def _settings(self):
        for key, (value, desc) in C.APP_SETTING_DEFAULTS.items():
            AppSetting.objects.get_or_create(
                key=key, defaults={'value': value, 'description': desc})

    def _number_series(self):
        series = {
            'quotation': ('QT-', 5), 'invoice': ('INV-', 5), 'job_order': ('JO-', 5),
            'production_run': ('PR-', 5), 'delivery': ('DR-', 5), 'fg_lot': ('FG-', 5),
            'coil': ('COIL-', 5),
        }
        for key, (prefix, pad) in series.items():
            NumberSeries.objects.get_or_create(
                key=key, defaults={'prefix': prefix, 'padding': pad, 'next_number': 1})

    def _uoms(self):
        data = [('LM', 'Linear Meter', True), ('PC', 'Piece', False),
                ('KG', 'Kilogram', False), ('ROLL', 'Roll', False),
                ('SHEET', 'Sheet', False), ('SET', 'Set', False),
                ('SQM', 'Square Meter', False)]
        uoms = {}
        for code, name, is_len in data:
            u, _ = UnitOfMeasure.objects.get_or_create(
                code=code, defaults={'name': name, 'is_length': is_len})
            uoms[code] = u
        return uoms

    def _terms_taxes(self):
        terms = {}
        for code, name, days, dep in [('COD', 'Cash on Delivery', 0, D('100')),
                                      ('50DP', '50% Down, balance on delivery', 0, D('50')),
                                      ('NET30', 'Net 30', 30, D('0'))]:
            t, _ = PaymentTerm.objects.get_or_create(
                code=code, defaults={'name': name, 'days': days, 'deposit_pct': dep})
            terms[code] = t
        vat, _ = TaxCode.objects.get_or_create(
            code='VAT12', defaults={'name': 'VAT 12%', 'rate_pct': D('12')})
        return terms, {'VAT12': vat}

    def _warehouses_machines(self):
        whs = {}
        for code, name, plant in [('LIPA', 'Lipa Plant (Bulacnin)', True),
                                  ('CAVITE', 'Cavite Plant', True),
                                  ('MAIN', 'Main Warehouse', False)]:
            w, _ = Warehouse.objects.get_or_create(
                code=code, defaults={'name': name, 'is_plant': plant})
            whs[code] = w
        machines = {}
        for code, name, wh in [('RF-01', 'Roll Former 1', 'LIPA'),
                               ('RF-02', 'Roll Former 2', 'LIPA'),
                               ('BND-01', 'Bending Brake 1', 'LIPA')]:
            m, _ = Machine.objects.get_or_create(
                code=code, defaults={'name': name, 'warehouse': whs[wh]})
            machines[code] = m
        return whs, machines

    def _colors(self):
        names = ['Red', 'Green', 'Brown', 'Mandarin Red', 'Blue', 'White', 'Gray',
                 'Beige', 'Terracotta', 'Off White', 'Brick Orange', 'Dark Wood',
                 'Light Wood', 'Ocean Blue', 'Palm Green']
        colors = {}
        for n in names:
            code = n.upper().replace(' ', '_')[:32]
            c, _ = Color.objects.get_or_create(code=code, defaults={'name': n})
            colors[n] = c
        return colors

    def _categories(self):
        data = [
            ('ROOF', 'Roof Panel', C.ItemType.FINISHED_GOOD, False, True),
            ('DECK', 'Steel Deck', C.ItemType.FINISHED_GOOD, False, True),
            ('SPANDREL', 'Spandrel / Cladding', C.ItemType.FINISHED_GOOD, False, True),
            ('PLAIN', 'Plainsheet', C.ItemType.FINISHED_GOOD, False, True),
            ('BENDED', 'Bended Accessory', C.ItemType.FINISHED_GOOD, True, True),
            ('INSULATION', 'Insulation', C.ItemType.STOCK_RESALE, False, False),
            ('HARDWARE', 'Hardware', C.ItemType.STOCK_RESALE, False, False),
            ('SKYLIGHT', 'Skylight', C.ItemType.FINISHED_GOOD, False, True),
            ('COIL', 'Metal Coil (Raw)', C.ItemType.RAW_MATERIAL, False, False),
        ]
        cats = {}
        for code, name, itype, dwg, mfg in data:
            c, _ = ItemCategory.objects.get_or_create(
                code=code, defaults={'name': name, 'default_item_type': itype,
                                     'requires_drawing': dwg, 'is_manufactured': mfg})
            cats[code] = c
        return cats

    def _attributes(self, cats):
        defs = [
            ('color', 'Color', C.AttributeDataType.ENUM, '', False, True, ['ROOF', 'BENDED', 'SPANDREL']),
            ('thickness', 'Thickness (mm)', C.AttributeDataType.DECIMAL, 'mm', True, True, ['ROOF', 'DECK', 'SPANDREL', 'BENDED']),
            ('feed_width', 'Feed / Coil Width (mm)', C.AttributeDataType.DECIMAL, 'mm', False, True, ['ROOF']),
            ('finished_width', 'Finished Width (mm)', C.AttributeDataType.DECIMAL, 'mm', False, False, ['ROOF']),
            ('length', 'Length (m)', C.AttributeDataType.DECIMAL, 'm', True, True, ['ROOF', 'DECK', 'SPANDREL', 'BENDED']),
            ('profile', 'Profile', C.AttributeDataType.TEXT, '', False, True, ['ROOF']),
            ('accessory_type', 'Accessory Type', C.AttributeDataType.TEXT, '', True, True, ['BENDED']),
            ('girth', 'Width / Girth (in)', C.AttributeDataType.DECIMAL, 'in', True, True, ['BENDED']),
            ('style', 'Style', C.AttributeDataType.ENUM, '', False, True, ['BENDED']),
            ('bend_design', 'Bend Design', C.AttributeDataType.TEXT, '', False, False, ['BENDED']),
            ('drawing_required', 'Drawing Required', C.AttributeDataType.BOOLEAN, '', False, False, ['BENDED']),
            ('hardware_type', 'Hardware Type', C.AttributeDataType.TEXT, '', True, True, ['HARDWARE']),
            ('size', 'Size', C.AttributeDataType.TEXT, '', False, True, ['HARDWARE']),
            ('brand', 'Brand', C.AttributeDataType.TEXT, '', False, False, ['HARDWARE']),
        ]
        options = {
            'style': ['STD', 'Spanish'],
            'color': ['Red', 'Green', 'Brown', 'Blue', 'White', 'Beige', 'Terracotta'],
        }
        order = 0
        for code, name, dtype, uom, req, affects_price, cat_codes in defs:
            order += 1
            a, _ = AttributeDefinition.objects.get_or_create(
                code=code, defaults={
                    'name': name, 'data_type': dtype, 'required_default': req,
                    'affects_price': affects_price,
                    'affects_material': code in ('thickness', 'length', 'feed_width', 'girth'),
                    'display_order': order})
            for i, val in enumerate(options.get(code, [])):
                AttributeOption.objects.get_or_create(
                    attribute=a, value=val, defaults={'label': val, 'sort': i})
            for cc in cat_codes:
                if cc in cats:
                    CategoryAttribute.objects.get_or_create(
                        category=cats[cc], attribute=a,
                        defaults={'required': req, 'display_order': order})

    def _profiles(self, cats, machines):
        # (code, name, category, nominal, effective, coil_width, waste, alias)
        data = [
            ('MONACO', 'Monaco Tile', 'ROOF', 1082, 1000, 1220, 5, 'Monaco Tile'),
            ('MILAZZO', 'Milazzo Tile', 'ROOF', 1060, 990, 1220, 5, None),
            ('VENICE', 'Venice Duplo / Twin Rib', 'ROOF', 1198, 1040, 1220, 6, '5-Rib'),
            ('FLORENCE', 'Florence Corrugated', 'ROOF', 1065, 980, 1220, 6, 'Corrugated'),
            ('BARCA_RIB', 'Barcelona Rib', 'ROOF', 1115, 1065, 1220, 6, '8-Rib'),
            ('BARCA_CURVE', 'Barcelona Curve', 'ROOF', 1115, 1040, 1220, 8, None),
            ('SPANDREL6', 'Spandrel 6"', 'SPANDREL', None, 140, 1220, 5, 'Spandrel'),
            ('DECK16', 'Monte Carlo Deck 16"', 'DECK', 274, 257, 1220, 5, 'Deck 16'),
            ('DECK24', 'Monte Carlo Deck 24"', 'DECK', 477, 460, 1220, 5, 'Deck 24'),
        ]
        for code, name, cat, nom, eff, cw, waste, alias in data:
            p, _ = Profile.objects.get_or_create(
                code=code, defaults={
                    'name': name, 'category': cats[cat],
                    'machine': machines.get('RF-01'),
                    'nominal_width_mm': nom, 'effective_width_mm': eff,
                    'default_coil_width_mm': cw, 'waste_pct': waste})
            if alias:
                ProfileAlias.objects.get_or_create(
                    profile=p, alias=alias, defaults={'context': 'production_report'})

    def _items(self, cats, uoms, colors):
        items = {}
        # Raw coils (per thickness x width); weight factor kg/LM from primer proxy
        wf = {D('0.4'): D('3.5'), D('0.5'): D('4.5'), D('0.6'): D('5.5')}
        for thk in [D('0.4'), D('0.5'), D('0.6')]:
            for width in [D('915'), D('1220')]:
                code = f'COIL-PPGI-{thk}-{int(width)}'
                it, _ = Item.objects.get_or_create(
                    code=code, defaults={
                        'name': f'Prepainted Coil {thk}mm x {int(width)}mm',
                        'item_type': C.ItemType.RAW_MATERIAL, 'category': cats['COIL'],
                        'uom': uoms['LM'], 'thickness_mm': thk, 'coil_width_mm': width,
                        'finish': 'Prepainted', 'track_lot': True,
                        'weight_factor_kg_per_lm': wf[thk], 'standard_cost': D('120')})
                items[code] = it
        # Finished roofing items for two profiles x thickness
        for prof_code in ['BARCA_RIB', 'FLORENCE', 'MONACO']:
            prof = Profile.objects.get(code=prof_code)
            for thk in [D('0.4'), D('0.5'), D('0.6')]:
                code = f'FG-{prof_code}-{thk}'
                it, _ = Item.objects.get_or_create(
                    code=code, defaults={
                        'name': f'{prof.name} {thk}mm', 'item_type': C.ItemType.FINISHED_GOOD,
                        'category': prof.category, 'uom': uoms['LM'], 'profile': prof,
                        'thickness_mm': thk, 'is_manufactured': True,
                        'weight_factor_kg_per_lm': wf[thk]})
                items[code] = it
        # Bended accessories (require drawing)
        for name in ['Spanish Gutter', 'Box Gutter', 'Valley Gutter', 'Ridge Roll',
                     'Capping Flashing', 'L Flashing', 'Apron Flashing']:
            code = 'BND-' + name.upper().replace(' ', '-')
            it, _ = Item.objects.get_or_create(
                code=code, defaults={
                    'name': name, 'item_type': C.ItemType.FINISHED_GOOD,
                    'category': cats['BENDED'], 'uom': uoms['LM'],
                    'is_manufactured': True, 'requires_drawing': True})
            items[code] = it
        # Hardware / insulation (stock/resale, no manufacturing)
        Item.objects.get_or_create(
            code='HW-TEXSCREW', defaults={
                'name': 'Tex Screw', 'item_type': C.ItemType.STOCK_RESALE,
                'category': cats['HARDWARE'], 'uom': uoms['PC'], 'standard_cost': D('2.5')})
        Item.objects.get_or_create(
            code='INS-PE5-SGL', defaults={
                'name': 'PE Foam 5mm Single (50m roll)', 'item_type': C.ItemType.STOCK_RESALE,
                'category': cats['INSULATION'], 'uom': uoms['ROLL'], 'standard_cost': D('3375')})
        return items

    def _pricing(self, items, uoms):
        pl, _ = PriceList.objects.get_or_create(
            code='PUBLISHED', defaults={'name': 'FEG Published Price', 'is_default': True})
        ver, _ = PriceListVersion.objects.get_or_create(
            price_list=pl, effective_from=date(2026, 1, 1),
            defaults={'note': 'From FEG Published Price PDF'})
        # profile x thickness -> price/LM (published list)
        matrix = {
            'BARCA_RIB': {D('0.4'): 350, D('0.5'): 450, D('0.6'): 550},
            'FLORENCE': {D('0.4'): 350, D('0.5'): 450, D('0.6'): 550},
            'MONACO': {D('0.4'): 400, D('0.5'): 520, D('0.6'): 645},
        }
        for prof_code, tiers in matrix.items():
            for thk, price in tiers.items():
                item = items.get(f'FG-{prof_code}-{thk}')
                PriceMatrixRow.objects.get_or_create(
                    version=ver, item=item,
                    keys={'profile': prof_code, 'thickness': str(thk)},
                    defaults={'unit_price': D(price), 'uom': uoms['LM']})
        # bended gauge x girth x style (sample cells from FEG Bended Pricelist)
        bended = [(D('0.4'), 6, 'STD', 117), (D('0.4'), 24, 'STD', 457),
                  (D('0.5'), 24, 'STD', 585), (D('0.5'), 24, 'Spanish', 610),
                  (D('0.6'), 24, 'STD', 705)]
        for gauge, girth, style, price in bended:
            PriceMatrixRow.objects.get_or_create(
                version=ver, keys={'gauge': str(gauge), 'girth': girth, 'style': style},
                defaults={'unit_price': D(price), 'uom': uoms['LM']})

    def _supplier(self):
        s, _ = Supplier.objects.get_or_create(
            code='ABC', defaults={'name': 'ABC Steel', 'contact_person': 'Supply Desk'})
        return s

    def _coils(self, items, colors, warehouses, supplier):
        coil_item = items.get('COIL-PPGI-0.5-1220')
        specs = [
            ('COIL-00881', 'Green', D('0.5'), D('1220'), D('900')),
            ('COIL-00882', 'Green', D('0.5'), D('1220'), D('1200')),
            ('COIL-00883', 'Red', D('0.5'), D('1220'), D('1000')),
        ]
        for num, color, thk, width, length in specs:
            if Coil.objects.filter(coil_number=num).exists():
                continue
            weight = length * (coil_item.weight_factor_kg_per_lm or D('4.5'))
            coil = Coil.objects.create(
                coil_number=num, supplier_coil_no=f'S-{num}', item=coil_item,
                color=colors.get(color), thickness_mm=thk, width_mm=width,
                finish='Prepainted', original_length_m=length, original_weight_kg=weight,
                remaining_length_m=length, remaining_weight_kg=weight,
                cost=length * D('120'), supplier=supplier, warehouse=warehouses['LIPA'],
                status=C.CoilStatus.AVAILABLE)
            receive_coil(coil)

    def _users(self, roles):
        specs = [
            ('sales', 'Sofia Sales', ['Sales']),
            ('billing', 'Bella Billing', ['Billing']),
            ('inventory', 'Ivan Inventory', ['Inventory Clerk', 'Warehouse Supervisor']),
            ('production', 'Pedro Production', ['Production Supervisor', 'Production Operator']),
            ('logistics', 'Lito Logistics', ['Logistics']),
            ('manager', 'Manny Manager', ['Management Viewer', 'Sales Approver']),
        ]
        for username, full, role_names in specs:
            user, created = User.objects.get_or_create(
                username=username, defaults={'email': f'{username}@foremosteg.test'})
            first, last = full.split(' ', 1)
            user.first_name, user.last_name = first, last
            if created or not user.has_usable_password():
                user.set_password('password123')
            user.save()
            user.roles.set([roles[r] for r in role_names if r in roles])

        admin, created = User.objects.get_or_create(
            username='admin', defaults={'email': 'admin@foremosteg.test',
                                        'is_staff': True, 'is_superuser': True})
        if created or not admin.has_usable_password():
            admin.set_password('password123')
        admin.is_superuser = True
        admin.is_staff = True
        admin.save()
        if 'Super Admin' in roles:
            admin.roles.set([roles['Super Admin']])

    def _demo_customer_quote(self, uoms):
        Customer.objects.get_or_create(
            name='Acme Construction',
            defaults={'contact_person': 'Joe Reyes', 'phone': '0917-1234567',
                      'address': 'Quezon City', 'code': 'CUST-0001'})
        Customer.objects.get_or_create(
            name='Bayside Realty',
            defaults={'contact_person': 'Maya Cruz', 'address': 'Cebu City',
                      'code': 'CUST-0002'})
