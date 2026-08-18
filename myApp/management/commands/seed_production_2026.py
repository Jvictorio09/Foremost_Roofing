"""Import the company's 2026 production actuals (Jan-May) from the official
PRODUCTION REPORT spreadsheet so the on-screen report matches it exactly and the
trend / forecast charts have real history. Idempotent: re-running replaces the
2026 import rows.

Values are linear metres (LM) per month. The gauge table also carries a weight
(the spreadsheet's "Tons" column) for 0.40 / 0.50 / 0.60 mm.
"""
from decimal import Decimal as D

from django.core.management.base import BaseCommand
from django.db import transaction

from myApp.models import ProductionActual as PA

YEAR = 2026
SOURCE = 'import:2026'
# Months present in the sheet: January..May (1..5).

# --- PROFILE (in LM) -------------------------------------------------------
PROFILE = {
    '5-Rib': [18165.61, 19969.58, 24816.83, 21346.54, 19940.22],
    '8-Rib': [16576.36, 19513.83, 27434.96, 22382.35, 20841.74],
    'Corrugated': [3442.72, 1617.58, 2710.99, 1640.39, 2455.31],
    'Monaco Tile': [1006.72, 2399.13, 794.89, 559.91, 740.88],
    'Milazzo Tile': [306.56, 0, 272.86, 0, 394.70],
    'Cladding': [2129.77, 2285.40, 2059.74, 3239.87, 2336.55],
    'Spandrel': [12977.05, 14630.38, 23250.21, 10109.68, 12062.55],
    'Deck 16': [1211.80, 50.80, 3066.05, 1175.20, 2221.75],
    'Deck 24': [863.25, 876.54, 427.85, 1452.73, 2273.37],
    'North Steel': [486.30, 142.54, 1159.01, 287.43, 825.89],
    'NS Wood Grain-Spandrel': [0, 0, 0, 0, 0],
}

# --- GAUGE (in LM) + weight for the Tons column ----------------------------
# (lm months, total weight for the year)
GAUGE = {
    '0.35mm': ([0, 0, 0, 0, 0], 0),
    '0.40mm': ([18172.04, 16109.80, 19534.16, 15530.18, 16603.08], 300822.41),
    '0.50mm': ([28556.76, 30763.04, 39989.62, 36996.84, 33455.87], 763929.585),
    '0.60mm': ([6341.12, 6532.10, 12173.62, 8358.72, 4847.30], 210390.73),
    '0.75mm (galv)': ([136.98, 0, 13.90, 0, 741.01], 0),
    '0.80mm (galv)': ([1162.78, 778.85, 1325.66, 1493.55, 2712.89], 0),
    '1.00mm (galv)': ([899.68, 255.99, 7365.44, 821.06, 1114.73], 0),
    '.35mm (spandrel)': ([0, 0, 0, 0, 0], 0),
    '.4mm (spandrel)': ([13565.64, 18348.25, 33265.93, 10633.76, 13108.22], 0),
}

# --- Color (in LM) ---------------------------------------------------------
COLOR = {
    'RED': [10062.58, 10023.96, 11525.28, 12747.30, 9240.81],
    'GREEN': [5578.63, 8784.29, 10351.33, 9239.83, 9279.03],
    'BROWN': [11937.70, 7961.32, 10810.86, 9119.41, 6850.23],
    'MANDARIN RED': [3231.03, 3015.19, 1987.14, 2380.02, 3553.32],
    'BLUE': [6269.38, 7245.35, 12478.10, 8931.25, 6404.74],
    'WHITE': [2770.41, 3044.27, 3340.60, 3446.07, 3488.01],
    'GRAY': [9972.93, 7800.29, 12013.19, 7954.14, 10217.94],
    'BEIGE': [1061.84, 2467.11, 5275.81, 4211.82, 2427.30],
    'TERRACOTTA': [1017.95, 1473.46, 2254.86, 1768.04, 1572.07],
    'OFF WHITE': [246.49, 95.34, 396.25, 549.52, 311.02],
    'BRICK ORANGE': [252.54, 193.48, 18.30, 76.64, 122.32],
    'DARK WOOD': [100.99, 262.60, 400.71, 159.84, 526.94],
    'LIGHT WOOD': [464.31, 745.03, 781.97, 301.86, 912.52],
    'OCEAN BLUE': [0, 0, 0, 0, 0],
    'PALM GREEN': [103.13, 293.24, 63.00, 0, 0],
}

# --- Overall operational summary (counts, not LM) --------------------------
SUMMARY = {
    'No. of Bended': [5491, 5993, 6908, 5862, 5006],
    'No. of Days': [23, 23, 25, 23, 24],
}


class Command(BaseCommand):
    help = 'Import 2026 production actuals (Jan-May) from the official spreadsheet.'

    @transaction.atomic
    def handle(self, *args, **options):
        PA.objects.filter(year=YEAR, source=SOURCE).delete()

        n = 0
        n += self._load(PA.Dimension.PROFILE, PROFILE)
        n += self._load(PA.Dimension.GAUGE, GAUGE, has_weight=True)
        n += self._load(PA.Dimension.COLOR, COLOR)
        n += self._load(PA.Dimension.SUMMARY, SUMMARY)

        prof_total = sum(sum(v) for v in PROFILE.values())
        gauge_total = sum(sum(v[0]) for v in GAUGE.values())
        color_total = sum(sum(v) for v in COLOR.values())
        self.stdout.write(self.style.SUCCESS(
            f'\nImported {n} monthly rows for {YEAR} (Jan-May).'))
        self.stdout.write(f'  Profile total : {prof_total:,.2f} LM')
        self.stdout.write(f'  Gauge total   : {gauge_total:,.2f} LM')
        self.stdout.write(f'  Colour total  : {color_total:,.2f} LM')

    def _load(self, dimension, data, has_weight=False):
        rows = []
        for category, payload in data.items():
            months = payload[0] if has_weight else payload
            weight_total = payload[1] if has_weight else 0
            active = [(i, v) for i, v in enumerate(months, start=1) if v]
            # Spread the annual weight across months proportional to LM.
            lm_sum = sum(v for _, v in active) or 1
            for month, lm in active:
                w = (D(str(weight_total)) * (D(str(lm)) / D(str(lm_sum)))
                     if has_weight and weight_total else D('0'))
                rows.append(PA(year=YEAR, month=month, dimension=dimension,
                               category=category, lm=D(str(lm)),
                               weight_kg=w, source=SOURCE))
        PA.objects.bulk_create(rows)
        return len(rows)
