"""Production seed for the Foremost EG ERP.

Loads real master data taken from the company documents in ``docs_for_seed`` --
the FEG Published Price list (roofing profiles x thickness), the FEG Bended
Pricelist (gauge x width x style, stainless, PE foam) and the product spec sheet
(nominal / effective widths) -- and creates a SINGLE administrator account.

Unlike ``seed_erp`` this command adds NO demo customers, quotations, coils or
extra user accounts: it is meant to stand up a clean production instance that the
admin then populates (users, customers, stock) from the app.

Everything is idempotent (get_or_create), so it is safe to re-run after editing
the tables below. Prices, widths and waste factors are DATA and remain editable
in-app afterwards.

Usage:
    python manage.py seed_production
    python manage.py seed_production --username owner --email you@company.com
    python manage.py seed_production --password 'S3cret!' --reset-password

The admin username / email / password may also come from the environment
(ADMIN_USERNAME, ADMIN_EMAIL, ADMIN_PASSWORD) -- handy on Railway. If no password
is supplied a strong one is generated and printed once.
"""
import os
import secrets
import string
from datetime import date
from decimal import Decimal

from django.core.management.base import BaseCommand
from django.db import transaction

from myApp import constants as C
from myApp.models import (
    AppSetting, AttributeDefinition, AttributeOption, CategoryAttribute, Color,
    Item, ItemCategory, Machine, NumberSeries, PaymentTerm, Permission,
    PriceList, PriceListVersion, PriceMatrixRow, Profile, ProfileAlias, Role,
    TaxCode, UnitOfMeasure, User, Warehouse,
)

D = Decimal
STEEL_DENSITY = D('7850')  # kg/m3, for kg-per-LM weight factors

# ---------------------------------------------------------------------------
# Catalog data taken from docs_for_seed
# ---------------------------------------------------------------------------
# Roofing / deck / spandrel / plainsheet products.
#   (code, name, category, nominal_mm, effective_mm, coil_width_mm, waste_pct,
#    report_alias, manufactured, {thickness_mm: price_per_LM})
# Prices: FEG Published Price (1).pdf. Widths: product spec sheet on the same PDF.
PRODUCTS = [
    ('MONACO', 'Monaco Tile', 'ROOF', 1082, 1000, 1220, 5, 'Monaco Tile', True,
     {D('0.4'): 400, D('0.5'): 520, D('0.6'): 645}),
    ('MILAZZO', 'Milazzo Tile', 'ROOF', 1060, 990, 1220, 5, 'Milazzo Tile', True,
     {D('0.4'): 400, D('0.5'): 520, D('0.6'): 645}),
    ('VENICE', 'Venice Duplo Rib', 'ROOF', 1198, 1040, 1220, 6, '5-Rib', True,
     {D('0.4'): 350, D('0.5'): 450, D('0.6'): 550}),
    ('FLORENCE', 'Florence Corrugated', 'ROOF', 1065, 980, 1220, 6, 'Corrugated', True,
     {D('0.4'): 350, D('0.5'): 450, D('0.6'): 550}),
    ('BARCA_RIB', 'Barcelona Rib', 'ROOF', 1115, 1065, 1220, 6, '8-Rib', True,
     {D('0.4'): 350, D('0.5'): 450, D('0.6'): 550}),
    ('BARCA_CURVE', 'Barcelona Curve', 'ROOF', 1115, 1040, 1220, 8, None, True,
     {D('0.4'): 415, D('0.5'): 515, D('0.6'): 615}),
    ('SPANDREL6', 'Spandrel 6"', 'SPANDREL', 140, 140, 1220, 5, 'Spandrel', True,
     {D('0.4'): 70, D('0.5'): 88, D('0.6'): 105}),
    ('SPANDREL4', 'Spandrel 4"', 'SPANDREL', 100, 100, 1220, 5, None, True,
     {D('0.4'): 57}),
    ('PLAIN1220', 'Plainsheet 1220', 'PLAIN', 1220, 1220, 1220, 2, None, False,
     {D('0.4'): 854, D('0.5'): 1098, D('0.6'): 1342}),
    ('PLAIN915', 'Plainsheet 915', 'PLAIN', 915, 915, 915, 2, None, False,
     {D('0.4'): 659, D('0.5'): 830, D('0.6'): 1015}),
    # Monte Carlo steel deck (gauges 0.8 / 1.0). NOTE: 24"/16" prices follow the
    # published sheet's row order -- verify against the printed list if unsure.
    ('DECK48', 'Monte Carlo Deck 48"', 'DECK', 984, 972, 1220, 5, None, True,
     {D('0.8'): 600, D('1.0'): 775}),
    ('DECK24', 'Monte Carlo Deck 24"', 'DECK', 477, 460, 1220, 5, 'Deck 24', True,
     {D('0.8'): 200, D('1.0'): 258}),
    ('DECK16', 'Monte Carlo Deck 16"', 'DECK', 274, 257, 1220, 5, 'Deck 16', True,
     {D('0.8'): 300, D('1.0'): 387}),
]

# Bended accessories: price per LM by gauge x width(inches) x style.
# From FEG Bended Pricelist (2).jpg. width_in -> metres for reference.
BENDED_WIDTH_M = {6: D('0.152'), 9: D('0.229'), 12: D('0.305'), 16: D('0.406'),
                  18: D('0.457'), 24: D('0.610'), 36: D('0.915'), 48: D('1.220')}
# gauge -> {width_in: (STD, Spanish)}
BENDED_PRICES = {
    D('0.4'): {6: (117, 124), 9: (180, 190), 12: (234, 246), 16: (307, 325),
               18: (377, 395), 24: (457, 481), 36: (698, 734), 48: (914, 960)},
    D('0.5'): {6: (150, 162), 9: (275, 290), 12: (298, 313), 16: (397, 418),
               18: (525, 545), 24: (585, 610), 36: (990, 1010), 48: (1170, 1220)},
    D('0.6'): {6: (177, 187), 9: (326, 340), 12: (353, 365), 16: (470, 487),
               18: (625, 645), 24: (705, 730), 36: (1195, 1215), 48: (1410, 1460)},
}

# Standard bended accessory items (drawing-driven). Priced by the matrix above at
# quote time based on the chosen gauge / girth / style.
BENDED_ACCESSORIES = [
    'Spanish Gutter', 'Box Gutter', 'Canal Gutter', 'Valley Gutter',
    'Ridge Roll (Plain)', 'Ridge Roll (Vented)', 'Hip Roll',
    'End Flashing', 'Side / Wall Flashing', 'Apron Flashing', 'Counter Flashing',
    'Step Flashing', 'L-Flashing', 'U-Flashing', 'J-Flashing',
    'Barge / Rake Flashing', 'Fascia Cover', 'Drip Edge', 'Capping / Ridge Cap',
    'Downspout', 'Splash Board / Gutter Guard',
]

# Stainless 304, 8' (2.44 m) sheet, 48" wide -- price per sheet.
# gauge -> (plain_sheet_price, bended_price)
STAINLESS_PRICES = {
    D('0.4'): (2350, 2400), D('0.5'): (2850, 2900), D('0.6'): (3350, 3400),
}

# PE foam insulation, 50 m roll -- price per roll.
# (code, description, price)
PE_FOAM = [
    ('INS-PE5-SGL', 'PE Foam 5mm Single-Sided (50m roll)', 3375),
    ('INS-PE10-SGL', 'PE Foam 10mm Single-Sided (50m roll)', 5800),
    ('INS-PE5-DBL', 'PE Foam 5mm Double-Sided (50m roll)', 4625),
    ('INS-PE10-DBL', 'PE Foam 10mm Double-Sided (50m roll)', 7050),
]

COLOR_HEX = {
    'Red': '#c0392b', 'Green': '#2e7d32', 'Brown': '#8d6e63',
    'Mandarin Red': '#e64a19', 'Blue': '#1e63c9', 'White': '#f5f5f5',
    'Gray': '#9e9e9e', 'Beige': '#d8c9a3', 'Terracotta': '#c1502e',
    'Off White': '#eceff1', 'Brick Orange': '#d35400', 'Dark Wood': '#5d4037',
    'Light Wood': '#b78a5f', 'Ocean Blue': '#1565c0', 'Palm Green': '#558b2f',
}


def weight_factor(width_mm, thickness_mm):
    """Approximate kg per linear metre of coil/panel from geometry + steel density."""
    return (D(str(width_mm)) / 1000 * D(str(thickness_mm)) / 1000
            * STEEL_DENSITY).quantize(D('0.0001'))


class Command(BaseCommand):
    help = 'Seed real master data from docs_for_seed and create one admin account.'

    def add_arguments(self, parser):
        parser.add_argument('--username',
                            default=os.environ.get('ADMIN_USERNAME', 'admin'))
        parser.add_argument('--email',
                            default=os.environ.get('ADMIN_EMAIL', 'admin@foremosteg.com'))
        parser.add_argument('--password',
                            default=os.environ.get('ADMIN_PASSWORD'))
        parser.add_argument('--reset-password', action='store_true',
                            help='Reset the password if the admin already exists.')
        parser.add_argument('--with-team', action='store_true',
                            help='Also create the standard team logins '
                                 '(sales, billing, inventory, production, logistics, '
                                 'manager) with password "password123".')

    @transaction.atomic
    def handle(self, *args, **options):
        self._permissions()
        roles = self._roles()
        self._settings()
        self._number_series()
        uoms = self._uoms()
        self._terms_taxes()
        self._warehouses_machines()
        self._colors()
        cats = self._categories()
        self._attributes(cats)
        self._catalog(cats, uoms)
        self._admin(roles, options)
        if options['with_team']:
            self._team(roles)
        self.stdout.write(self.style.SUCCESS('\nProduction seed complete.'))

    # ------------------------------------------------------------------ RBAC
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
            role.permissions.set(Permission.objects.filter(code__in=codes))
            roles[name] = role
        self.stdout.write(f'  roles: {Role.objects.count()}')
        return roles

    # -------------------------------------------------------------- config
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
        for code, name, days, dep in [('COD', 'Cash on Delivery', 0, D('100')),
                                      ('50DP', '50% Down, balance on delivery', 0, D('50')),
                                      ('NET30', 'Net 30', 30, D('0'))]:
            PaymentTerm.objects.get_or_create(
                code=code, defaults={'name': name, 'days': days, 'deposit_pct': dep})
        TaxCode.objects.get_or_create(
            code='VAT12', defaults={'name': 'VAT 12%', 'rate_pct': D('12')})

    def _warehouses_machines(self):
        whs = {}
        for code, name, plant in [('LIPA', 'Lipa Plant (Bulacnin)', True),
                                  ('CAVITE', 'Cavite Plant', True),
                                  ('MAIN', 'Main Warehouse', False)]:
            w, _ = Warehouse.objects.get_or_create(
                code=code, defaults={'name': name, 'is_plant': plant})
            whs[code] = w
        for code, name, wh in [('RF-01', 'Roll Former 1', 'LIPA'),
                               ('RF-02', 'Roll Former 2', 'LIPA'),
                               ('BND-01', 'Bending Brake 1', 'LIPA')]:
            Machine.objects.get_or_create(
                code=code, defaults={'name': name, 'warehouse': whs[wh]})

    def _colors(self):
        for name, hexv in COLOR_HEX.items():
            code = name.upper().replace(' ', '_')[:32]
            Color.objects.get_or_create(
                code=code, defaults={'name': name, 'hex_value': hexv})

    def _categories(self):
        data = [
            ('ROOF', 'Roof Panel', C.ItemType.FINISHED_GOOD, False, True),
            ('DECK', 'Steel Deck', C.ItemType.FINISHED_GOOD, False, True),
            ('SPANDREL', 'Spandrel / Cladding', C.ItemType.FINISHED_GOOD, False, True),
            ('PLAIN', 'Plainsheet', C.ItemType.FINISHED_GOOD, False, False),
            ('BENDED', 'Bended Accessory', C.ItemType.FINISHED_GOOD, True, True),
            ('STAINLESS', 'Stainless', C.ItemType.FINISHED_GOOD, False, True),
            ('INSULATION', 'Insulation', C.ItemType.STOCK_RESALE, False, False),
            ('HARDWARE', 'Hardware', C.ItemType.STOCK_RESALE, False, False),
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
            'color': list(COLOR_HEX.keys()),
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

    # ------------------------------------------------------------- catalog
    def _catalog(self, cats, uoms):
        pl, _ = PriceList.objects.get_or_create(
            code='PUBLISHED', defaults={'name': 'FEG Published Price', 'is_default': True})
        ver, _ = PriceListVersion.objects.get_or_create(
            price_list=pl, effective_from=date(2026, 1, 1),
            defaults={'note': 'From FEG Published Price + Bended Pricelist (docs_for_seed)'})
        lm = uoms['LM']

        n_items = n_prices = 0

        # 1) Roll-formed / flat products: profile + FG item + price per thickness.
        for (code, name, cat, nom, eff, cw, waste, alias, mfg, tiers) in PRODUCTS:
            prof, _ = Profile.objects.get_or_create(
                code=code, defaults={
                    'name': name, 'category': cats[cat],
                    'machine': Machine.objects.filter(code='RF-01').first(),
                    'nominal_width_mm': nom, 'effective_width_mm': eff,
                    'default_coil_width_mm': cw, 'waste_pct': waste})
            if alias:
                ProfileAlias.objects.get_or_create(
                    profile=prof, alias=alias, defaults={'context': 'production_report'})
            for thk, price in tiers.items():
                item, created = Item.objects.get_or_create(
                    code=f'FG-{code}-{thk}', defaults={
                        'name': f'{name} {thk}mm', 'item_type': C.ItemType.FINISHED_GOOD,
                        'category': cats[cat], 'uom': lm, 'profile': prof,
                        'thickness_mm': thk, 'is_manufactured': mfg,
                        'weight_factor_kg_per_lm': weight_factor(cw, thk)})
                n_items += 1 if created else 0
                _, made = PriceMatrixRow.objects.get_or_create(
                    version=ver, item=item,
                    keys={'profile': code, 'thickness': str(thk)},
                    defaults={'unit_price': D(price), 'uom': lm})
                n_prices += 1 if made else 0

        # 2) Bended accessories: drawing-driven items + gauge x girth x style prices.
        for name in BENDED_ACCESSORIES:
            code = 'BND-' + name.upper().replace(' ', '-').replace('/', '').replace('(', '').replace(')', '')
            code = code.replace('--', '-')[:48]
            item, created = Item.objects.get_or_create(
                code=code, defaults={
                    'name': name, 'item_type': C.ItemType.FINISHED_GOOD,
                    'category': cats['BENDED'], 'uom': lm,
                    'is_manufactured': True, 'requires_drawing': True})
            n_items += 1 if created else 0
        for gauge, widths in BENDED_PRICES.items():
            for girth_in, (std, spanish) in widths.items():
                for style, price in (('STD', std), ('Spanish', spanish)):
                    _, made = PriceMatrixRow.objects.get_or_create(
                        version=ver,
                        keys={'gauge': str(gauge), 'girth': girth_in, 'style': style},
                        defaults={'unit_price': D(price), 'uom': lm})
                    n_prices += 1 if made else 0

        # 3) Stainless 304 sheet (8' x 48"), plain + bended, price per sheet.
        sheet = uoms['SHEET']
        for gauge, (plain, bended) in STAINLESS_PRICES.items():
            item, created = Item.objects.get_or_create(
                code=f'SS304-{gauge}', defaults={
                    'name': f'Stainless 304 {gauge}mm (8\' x 48")',
                    'item_type': C.ItemType.FINISHED_GOOD, 'category': cats['STAINLESS'],
                    'uom': sheet, 'thickness_mm': gauge, 'finish': 'Stainless 304'})
            n_items += 1 if created else 0
            for form, price in (('plain', plain), ('bended', bended)):
                _, made = PriceMatrixRow.objects.get_or_create(
                    version=ver, item=item,
                    keys={'material': 'stainless_304', 'gauge': str(gauge), 'form': form},
                    defaults={'unit_price': D(price), 'uom': sheet})
                n_prices += 1 if made else 0

        # 4) PE foam insulation (resale), price per roll.
        roll = uoms['ROLL']
        for code, desc, price in PE_FOAM:
            item, created = Item.objects.get_or_create(
                code=code, defaults={
                    'name': desc, 'item_type': C.ItemType.STOCK_RESALE,
                    'category': cats['INSULATION'], 'uom': roll,
                    'standard_cost': D(price)})
            n_items += 1 if created else 0
            _, made = PriceMatrixRow.objects.get_or_create(
                version=ver, item=item, keys={'insulation': code},
                defaults={'unit_price': D(price), 'uom': roll})
            n_prices += 1 if made else 0

        # 5) Raw prepainted coils (per thickness x coil width) for production.
        for thk in [D('0.4'), D('0.5'), D('0.6'), D('0.8'), D('1.0')]:
            for width in [D('1220'), D('915')]:
                Item.objects.get_or_create(
                    code=f'COIL-PPGI-{thk}-{int(width)}', defaults={
                        'name': f'Prepainted Coil {thk}mm x {int(width)}mm',
                        'item_type': C.ItemType.RAW_MATERIAL, 'category': cats['COIL'],
                        'uom': lm, 'thickness_mm': thk, 'coil_width_mm': width,
                        'finish': 'Prepainted', 'track_lot': True,
                        'weight_factor_kg_per_lm': weight_factor(width, thk)})

        self.stdout.write(f'  items: {Item.objects.count()} (new {n_items})')
        self.stdout.write(f'  price rows: {PriceMatrixRow.objects.count()} (new {n_prices})')

    # --------------------------------------------------------------- admin
    def _admin(self, roles, options):
        username = options['username']
        email = options['email']
        password = options['password']
        generated = False
        if not password:
            alphabet = string.ascii_letters + string.digits
            password = ''.join(secrets.choice(alphabet) for _ in range(16))
            generated = True

        admin, created = User.objects.get_or_create(
            username=username,
            defaults={'email': email, 'is_staff': True, 'is_superuser': True})
        admin.email = email or admin.email
        admin.is_staff = True
        admin.is_superuser = True

        set_pw = created or options['reset_password'] or not admin.has_usable_password()
        if set_pw:
            admin.set_password(password)
        admin.save()
        if 'Super Admin' in roles:
            admin.roles.set([roles['Super Admin']])

        self.stdout.write(self.style.SUCCESS(f'\n  admin account: {username}'))
        if set_pw:
            if generated:
                self.stdout.write(self.style.WARNING(
                    f'  generated password (save it now): {password}'))
            else:
                self.stdout.write('  password set from --password / ADMIN_PASSWORD')
        else:
            self.stdout.write('  existing admin left unchanged '
                              '(use --reset-password to change it)')

    # ---------------------------------------------------------------- team
    def _team(self, roles):
        """Create the standard non-admin team logins (idempotent). New accounts
        get password123; existing ones keep their current password."""
        specs = [
            ('sales', 'Sofia Sales', ['Sales']),
            ('billing', 'Bella Billing', ['Billing']),
            ('inventory', 'Ivan Inventory', ['Inventory Clerk', 'Warehouse Supervisor']),
            ('production', 'Pedro Production',
             ['Production Supervisor', 'Production Operator']),
            ('logistics', 'Lito Logistics', ['Logistics']),
            ('manager', 'Manny Manager', ['Management Viewer', 'Sales Approver']),
        ]
        created_names = []
        for username, full, role_names in specs:
            user, created = User.objects.get_or_create(
                username=username, defaults={'email': f'{username}@foremosteg.com'})
            first, last = full.split(' ', 1)
            user.first_name, user.last_name = first, last
            if created or not user.has_usable_password():
                user.set_password('password123')
                created_names.append(username)
            user.save()
            user.roles.set([roles[r] for r in role_names if r in roles])
        self.stdout.write(self.style.SUCCESS(
            f'  team logins ensured: {", ".join(u for u, _, _ in specs)}'))
        if created_names:
            self.stdout.write('  password "password123" set for: '
                              + ', '.join(created_names))
