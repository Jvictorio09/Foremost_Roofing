"""Foremost EG Manufacturing ERP -- data model.

Organised in the same layers as the blueprint:
  1. RBAC (User, Role, Permission)
  2. Master data (Customer, Supplier, Warehouse, UoM, Color, Machine, ...)
  3. Catalog (ItemCategory, Profile, Item, ProductConstraint, PriceList)
  4. Dynamic attributes (AttributeDefinition, AttributeOption, CategoryAttribute)
  5. Sales (Quotation, Invoice, Payment)
  6. Manufacturing (JobOrder, MaterialReservation, ProductionRun, QC)
  7. Inventory (StockBalance, Coil, InventoryTransaction, FinishedGoodsLot)
  8. Logistics (Delivery)
  9. Audit (AuditEvent, StatusHistory)

Design rules honoured here:
  * No product/profile/price/waste values are hard-coded -- they are rows.
  * Commercial documents snapshot description, specs and price so historical
    documents never change when masters change (specs_json + snapshot columns).
  * Inventory changes only through the InventoryTransaction ledger; balances are
    derived counters, postings are never hard-deleted (use reversals).
"""
from decimal import Decimal

from django.conf import settings
from django.contrib.auth.models import AbstractUser
from django.db import models
from django.utils import timezone

from . import constants as C
from .profile_render import (
    build_profile_svg, girth_label, has_profile, profile_girth)

ZERO = Decimal('0.00')


class TimeStamped(models.Model):
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


# ===========================================================================
# 1. RBAC
# ===========================================================================
class Permission(models.Model):
    """A single, granular capability such as ``quotation.approve``."""
    code = models.CharField(max_length=64, unique=True)
    label = models.CharField(max_length=160)
    group = models.CharField(max_length=64, blank=True)

    class Meta:
        ordering = ['group', 'code']

    def __str__(self):
        return self.code


class Role(TimeStamped):
    """A named bundle of permissions. Fully editable at runtime."""
    name = models.CharField(max_length=80, unique=True)
    description = models.CharField(max_length=255, blank=True)
    is_system = models.BooleanField(default=False)  # e.g. Super Admin -- protected
    permissions = models.ManyToManyField(Permission, related_name='roles', blank=True)

    class Meta:
        ordering = ['name']

    def __str__(self):
        return self.name


class User(AbstractUser):
    phone = models.CharField(max_length=32, blank=True)
    roles = models.ManyToManyField(Role, related_name='users', blank=True)

    def permission_codes(self):
        if self.is_superuser:
            return {c for c, _, _ in C.PERMISSION_CATALOG}
        return set(
            Permission.objects.filter(roles__users=self)
            .values_list('code', flat=True)
        )

    def has_perm_code(self, code):
        return self.is_superuser or code in self.permission_codes()

    def role_label(self):
        names = list(self.roles.values_list('name', flat=True))
        if self.is_superuser and 'Super Admin' not in names:
            names.insert(0, 'Super Admin')
        return ', '.join(names) if names else 'No role'

    def __str__(self):
        return self.get_full_name() or self.username


# ===========================================================================
# 2. Master data
# ===========================================================================
class UnitOfMeasure(models.Model):
    code = models.CharField(max_length=16, unique=True)
    name = models.CharField(max_length=64)
    is_length = models.BooleanField(default=False)

    class Meta:
        ordering = ['code']

    def __str__(self):
        return self.code


class PaymentTerm(models.Model):
    code = models.CharField(max_length=32, unique=True)
    name = models.CharField(max_length=120)
    days = models.PositiveIntegerField(default=0)
    deposit_pct = models.DecimalField(max_digits=5, decimal_places=2, default=ZERO)

    class Meta:
        ordering = ['days']

    def __str__(self):
        return self.name


class TaxCode(models.Model):
    code = models.CharField(max_length=32, unique=True)
    name = models.CharField(max_length=120)
    rate_pct = models.DecimalField(max_digits=5, decimal_places=2, default=ZERO)
    is_inclusive = models.BooleanField(default=False)

    class Meta:
        ordering = ['code']

    def __str__(self):
        return f'{self.name} ({self.rate_pct}%)'


class Customer(TimeStamped):
    code = models.CharField(max_length=32, blank=True)
    name = models.CharField(max_length=200)
    contact_person = models.CharField(max_length=200, blank=True)
    phone = models.CharField(max_length=32, blank=True)
    email = models.EmailField(blank=True)
    address = models.TextField(blank=True)
    tin = models.CharField(max_length=32, blank=True)
    credit_limit = models.DecimalField(max_digits=14, decimal_places=2, default=ZERO)
    payment_term = models.ForeignKey(
        PaymentTerm, on_delete=models.SET_NULL, null=True, blank=True, related_name='customers'
    )
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ['name']

    def __str__(self):
        return self.name


class Supplier(TimeStamped):
    code = models.CharField(max_length=32, blank=True)
    name = models.CharField(max_length=200)
    contact_person = models.CharField(max_length=200, blank=True)
    phone = models.CharField(max_length=32, blank=True)
    email = models.EmailField(blank=True)
    address = models.TextField(blank=True)

    class Meta:
        ordering = ['name']

    def __str__(self):
        return self.name


class Warehouse(models.Model):
    code = models.CharField(max_length=32, unique=True)
    name = models.CharField(max_length=120)
    is_plant = models.BooleanField(default=False)
    address = models.CharField(max_length=255, blank=True)

    class Meta:
        ordering = ['name']

    def __str__(self):
        return self.name


class BinLocation(models.Model):
    warehouse = models.ForeignKey(Warehouse, on_delete=models.CASCADE, related_name='bins')
    code = models.CharField(max_length=32)
    description = models.CharField(max_length=120, blank=True)

    class Meta:
        ordering = ['warehouse', 'code']
        unique_together = [('warehouse', 'code')]

    def __str__(self):
        return f'{self.warehouse.code}/{self.code}'


class Color(models.Model):
    code = models.CharField(max_length=32, unique=True)
    name = models.CharField(max_length=80)
    hex_value = models.CharField(max_length=7, blank=True)

    class Meta:
        ordering = ['name']

    def __str__(self):
        return self.name


class Machine(models.Model):
    code = models.CharField(max_length=32, unique=True)
    name = models.CharField(max_length=120)
    warehouse = models.ForeignKey(
        Warehouse, on_delete=models.SET_NULL, null=True, blank=True, related_name='machines'
    )
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ['name']

    def __str__(self):
        return self.name


class NumberSeries(models.Model):
    """Configurable document numbering (prefix + zero-padded counter)."""
    key = models.CharField(max_length=32, unique=True)  # e.g. 'quotation'
    prefix = models.CharField(max_length=16)
    padding = models.PositiveIntegerField(default=5)
    next_number = models.PositiveIntegerField(default=1)

    def __str__(self):
        return f'{self.key} -> {self.prefix}'


class AppSetting(models.Model):
    """Runtime configuration -- credit rules, waste %, thresholds, company info."""
    key = models.CharField(max_length=64, unique=True)
    value = models.CharField(max_length=255, blank=True)
    description = models.CharField(max_length=255, blank=True)

    class Meta:
        ordering = ['key']

    def __str__(self):
        return f'{self.key}={self.value}'


# ===========================================================================
# 3. Catalog
# ===========================================================================
class ItemCategory(models.Model):
    code = models.CharField(max_length=32, unique=True)
    name = models.CharField(max_length=120)
    parent = models.ForeignKey(
        'self', on_delete=models.SET_NULL, null=True, blank=True, related_name='children'
    )
    default_item_type = models.CharField(
        max_length=20, choices=C.ItemType.choices, default=C.ItemType.FINISHED_GOOD
    )
    requires_drawing = models.BooleanField(default=False)
    is_manufactured = models.BooleanField(default=True)

    class Meta:
        ordering = ['name']
        verbose_name_plural = 'item categories'

    def __str__(self):
        return self.name


class Profile(models.Model):
    """Roofing / accessory profile master (Barcelona Rib, Monaco Tile, ...)."""
    code = models.CharField(max_length=32, unique=True)
    name = models.CharField(max_length=120)
    category = models.ForeignKey(
        ItemCategory, on_delete=models.PROTECT, related_name='profiles'
    )
    machine = models.ForeignKey(
        Machine, on_delete=models.SET_NULL, null=True, blank=True, related_name='profiles'
    )
    nominal_width_mm = models.DecimalField(max_digits=8, decimal_places=2, null=True, blank=True)
    effective_width_mm = models.DecimalField(max_digits=8, decimal_places=2, null=True, blank=True)
    default_coil_width_mm = models.DecimalField(max_digits=8, decimal_places=2, null=True, blank=True)
    waste_pct = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    notes = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ['name']

    def __str__(self):
        return self.name


class ProfileAlias(models.Model):
    """Maps commercial names to plant / report names (Barcelona Rib <-> 8-Rib)."""
    profile = models.ForeignKey(Profile, on_delete=models.CASCADE, related_name='aliases')
    alias = models.CharField(max_length=120)
    context = models.CharField(max_length=64, blank=True)  # 'production_report', plant, ...

    class Meta:
        ordering = ['alias']

    def __str__(self):
        return f'{self.alias} -> {self.profile.name}'


class Item(TimeStamped):
    """Any stock / sellable / buyable thing: coils, panels, accessories, hardware."""
    code = models.CharField(max_length=48, unique=True)
    name = models.CharField(max_length=200)
    item_type = models.CharField(max_length=20, choices=C.ItemType.choices)
    category = models.ForeignKey(
        ItemCategory, on_delete=models.PROTECT, related_name='items'
    )
    uom = models.ForeignKey(UnitOfMeasure, on_delete=models.PROTECT, related_name='items')
    profile = models.ForeignKey(
        Profile, on_delete=models.SET_NULL, null=True, blank=True, related_name='items'
    )
    color = models.ForeignKey(
        Color, on_delete=models.SET_NULL, null=True, blank=True, related_name='items'
    )
    # Common spec defaults (nullable -- not all items have all specs)
    thickness_mm = models.DecimalField(max_digits=6, decimal_places=3, null=True, blank=True)
    coil_width_mm = models.DecimalField(max_digits=8, decimal_places=2, null=True, blank=True)
    finish = models.CharField(max_length=40, blank=True)      # Prepainted / GI / Stainless
    style = models.CharField(max_length=40, blank=True)       # STD / Spanish / Curve
    weight_factor_kg_per_lm = models.DecimalField(
        max_digits=8, decimal_places=4, null=True, blank=True
    )
    is_manufactured = models.BooleanField(default=False)
    requires_drawing = models.BooleanField(default=False)
    track_lot = models.BooleanField(default=False)   # coils / lot-tracked raw
    standard_cost = models.DecimalField(max_digits=12, decimal_places=2, default=ZERO)
    reorder_point = models.DecimalField(max_digits=12, decimal_places=2, default=ZERO)
    # Optional per-item reference drawing (overrides the shared library drawing).
    reference_image = models.ImageField(upload_to='items/', null=True, blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ['name']

    def __str__(self):
        return f'{self.code} - {self.name}'


class StandardDrawing(TimeStamped):
    """Reusable reference drawing (End Flashing, Box Gutter, Wall Flashing, ...).
    Shown in the sales-quotation diagram band and reusable across many lines and
    items. A specific Item may override this with its own ``reference_image``."""
    code = models.CharField(max_length=32, unique=True)
    name = models.CharField(max_length=120)
    category = models.ForeignKey(
        ItemCategory, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='standard_drawings'
    )
    image = models.ImageField(upload_to='drawings/standard/')
    default_girth = models.CharField(max_length=64, blank=True)
    notes = models.CharField(max_length=255, blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ['name']

    def __str__(self):
        return self.name

    @property
    def total_on_hand(self):
        return self.stock_balances.aggregate(s=models.Sum('qty_on_hand'))['s'] or ZERO

    @property
    def total_reserved(self):
        return self.stock_balances.aggregate(s=models.Sum('qty_reserved'))['s'] or ZERO

    @property
    def total_available(self):
        return self.total_on_hand - self.total_reserved


class ProductConstraint(models.Model):
    """Restriction rules -- e.g. profile X only allows thickness in {0.4,0.5,0.6}."""
    class RuleType(models.TextChoices):
        ALLOWED_VALUES = 'allowed_values', 'Allowed values'
        MIN = 'min', 'Minimum'
        MAX = 'max', 'Maximum'
        FIXED = 'fixed', 'Fixed value'

    category = models.ForeignKey(
        ItemCategory, on_delete=models.CASCADE, null=True, blank=True, related_name='constraints'
    )
    profile = models.ForeignKey(
        Profile, on_delete=models.CASCADE, null=True, blank=True, related_name='constraints'
    )
    attribute_code = models.CharField(max_length=64)
    rule_type = models.CharField(max_length=20, choices=RuleType.choices)
    value = models.JSONField(default=dict)  # {"values":[...]} or {"value":...}

    def __str__(self):
        return f'{self.attribute_code} {self.rule_type}'


class PriceList(models.Model):
    code = models.CharField(max_length=32, unique=True)
    name = models.CharField(max_length=120)
    customer = models.ForeignKey(
        Customer, on_delete=models.CASCADE, null=True, blank=True, related_name='price_lists'
    )
    is_default = models.BooleanField(default=False)

    class Meta:
        ordering = ['name']

    def __str__(self):
        return self.name


class PriceListVersion(models.Model):
    price_list = models.ForeignKey(PriceList, on_delete=models.CASCADE, related_name='versions')
    effective_from = models.DateField()
    effective_to = models.DateField(null=True, blank=True)
    note = models.CharField(max_length=255, blank=True)

    class Meta:
        ordering = ['-effective_from']

    def __str__(self):
        return f'{self.price_list.code} @ {self.effective_from}'


class PriceMatrixRow(models.Model):
    """Specification-based price cell. ``keys`` holds the dimension values
    (profile / thickness / width / style / gauge / girth ...) as data, so new
    pricing dimensions never require code changes."""
    version = models.ForeignKey(PriceListVersion, on_delete=models.CASCADE, related_name='rows')
    item = models.ForeignKey(
        Item, on_delete=models.CASCADE, null=True, blank=True, related_name='price_rows'
    )
    keys = models.JSONField(default=dict)
    unit_price = models.DecimalField(max_digits=12, decimal_places=2)
    uom = models.ForeignKey(UnitOfMeasure, on_delete=models.PROTECT, related_name='+')

    def __str__(self):
        return f'{self.keys} = {self.unit_price}'


# ===========================================================================
# 4. Dynamic product attributes
# ===========================================================================
class AttributeDefinition(models.Model):
    code = models.CharField(max_length=64, unique=True)
    name = models.CharField(max_length=120)
    data_type = models.CharField(max_length=16, choices=C.AttributeDataType.choices)
    uom = models.ForeignKey(
        UnitOfMeasure, on_delete=models.SET_NULL, null=True, blank=True, related_name='+'
    )
    required_default = models.BooleanField(default=False)
    min_value = models.DecimalField(max_digits=14, decimal_places=4, null=True, blank=True)
    max_value = models.DecimalField(max_digits=14, decimal_places=4, null=True, blank=True)
    default_value = models.CharField(max_length=120, blank=True)
    validation_regex = models.CharField(max_length=255, blank=True)
    affects_material = models.BooleanField(default=False)
    affects_price = models.BooleanField(default=False)
    show_on_job_order = models.BooleanField(default=True)
    show_on_quote = models.BooleanField(default=True)
    display_order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ['display_order', 'name']

    def __str__(self):
        return self.name


class AttributeOption(models.Model):
    attribute = models.ForeignKey(
        AttributeDefinition, on_delete=models.CASCADE, related_name='options'
    )
    value = models.CharField(max_length=120)
    label = models.CharField(max_length=120, blank=True)
    sort = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ['sort', 'value']

    def __str__(self):
        return self.label or self.value


class CategoryAttribute(models.Model):
    """Binds an attribute to a category (which fields appear for which product)."""
    category = models.ForeignKey(
        ItemCategory, on_delete=models.CASCADE, related_name='category_attributes'
    )
    attribute = models.ForeignKey(
        AttributeDefinition, on_delete=models.CASCADE, related_name='category_bindings'
    )
    required = models.BooleanField(default=False)
    display_order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ['display_order']
        unique_together = [('category', 'attribute')]

    def __str__(self):
        return f'{self.category.code}:{self.attribute.code}'


# ===========================================================================
# 5. Sales
# ===========================================================================
class Quotation(TimeStamped):
    number = models.CharField(max_length=24, blank=True)
    revision_no = models.PositiveIntegerField(default=0)
    parent = models.ForeignKey(
        'self', on_delete=models.SET_NULL, null=True, blank=True, related_name='revisions'
    )
    is_current = models.BooleanField(default=True)
    customer = models.ForeignKey(Customer, on_delete=models.PROTECT, related_name='quotations')
    status = models.CharField(
        max_length=24, choices=C.QuotationStatus.choices, default=C.QuotationStatus.DRAFT
    )
    quote_date = models.DateField(default=timezone.localdate)
    valid_until = models.DateField(null=True, blank=True)
    payment_term = models.ForeignKey(
        PaymentTerm, on_delete=models.SET_NULL, null=True, blank=True, related_name='+'
    )
    tax_code = models.ForeignKey(
        TaxCode, on_delete=models.SET_NULL, null=True, blank=True, related_name='+'
    )
    price_list = models.ForeignKey(
        PriceList, on_delete=models.SET_NULL, null=True, blank=True, related_name='+'
    )
    salesperson = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='quotations'
    )
    delivery_address = models.TextField(blank=True)
    project_site = models.CharField(max_length=200, blank=True)
    customer_ref = models.CharField(max_length=120, blank=True)
    discount = models.DecimalField(max_digits=12, decimal_places=2, default=ZERO)
    notes = models.TextField(blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name='+'
    )
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='+'
    )
    approved_at = models.DateTimeField(null=True, blank=True)
    sent_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return self.display_number

    @property
    def display_number(self):
        base = self.number or f'QT-draft-{self.pk}'
        return f'{base} r{self.revision_no}' if self.revision_no else base

    @property
    def subtotal(self):
        return sum((l.line_total for l in self.lines.all()), ZERO)

    @property
    def tax_amount(self):
        rate = self.tax_code.rate_pct if self.tax_code else ZERO
        return (self.subtotal - self.discount) * rate / Decimal('100')

    @property
    def total(self):
        return self.subtotal - self.discount + self.tax_amount


class QuotationLine(models.Model):
    quotation = models.ForeignKey(Quotation, on_delete=models.CASCADE, related_name='lines')
    item = models.ForeignKey(
        Item, on_delete=models.SET_NULL, null=True, blank=True, related_name='+'
    )
    description = models.CharField(max_length=255)
    quantity = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('1.00'))
    uom = models.CharField(max_length=16, blank=True)
    unit_price = models.DecimalField(max_digits=12, decimal_places=2, default=ZERO)
    discount = models.DecimalField(max_digits=12, decimal_places=2, default=ZERO)
    specs_json = models.JSONField(default=dict, blank=True)
    # Reference drawing for this line: a shared library drawing and/or a one-off
    # image uploaded for a non-standard shape (custom_image wins when both set).
    standard_drawing = models.ForeignKey(
        StandardDrawing, on_delete=models.SET_NULL, null=True, blank=True, related_name='+'
    )
    custom_image = models.ImageField(upload_to='quote_lines/', null=True, blank=True)
    sort = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ['sort', 'id']

    @property
    def line_total(self):
        return self.quantity * self.unit_price - self.discount

    # --- Size / spec helpers (stored inside specs_json) --------------------
    @property
    def spec_rows(self):
        """Free-form size/spec rows: [{'label': 'Girth', 'value': '24\"'}, ...]."""
        return [r for r in (self.specs_json or {}).get('specs', [])
                if r.get('label') or r.get('value')]

    @property
    def length_rows(self):
        """Panel cutting list: [{'pcs': 12, 'len': 8.0}, ...]."""
        return [r for r in (self.specs_json or {}).get('lengths', [])
                if r.get('pcs') or r.get('len')]

    @property
    def length_total(self):
        total = Decimal('0')
        for r in self.length_rows:
            try:
                total += Decimal(str(r.get('pcs') or 0)) * Decimal(str(r.get('len') or 0))
            except (TypeError, ValueError):
                pass
        return total

    @property
    def drawing_image_url(self):
        """Resolved reference image: custom upload > line drawing > item image."""
        if self.custom_image:
            return self.custom_image.url
        if self.standard_drawing and self.standard_drawing.image:
            return self.standard_drawing.image.url
        if self.item and self.item.reference_image:
            return self.item.reference_image.url
        return ''

    @property
    def drawing_caption(self):
        if self.standard_drawing:
            return self.standard_drawing.name
        return self.specs_json.get('drawing_name', '') if self.specs_json else ''

    # --- Generated bend profile (cross-section drawing) --------------------
    @property
    def profile_data(self):
        # ``specs_json['profile']`` may legitimately be a roll-former profile
        # *code* (a string) rather than a bend-profile spec; only treat dicts as
        # a drawable bend profile.
        data = (self.specs_json or {}).get('profile')
        return data if isinstance(data, dict) else {}

    @property
    def has_generated_drawing(self):
        """True when no image is attached but a bend profile can be drawn."""
        return not self.drawing_image_url and has_profile(self.profile_data)

    @property
    def profile_svg(self):
        return build_profile_svg(self.profile_data) if self.profile_data else ''

    @property
    def profile_girth(self):
        return profile_girth(self.profile_data) if self.profile_data else 0

    @property
    def profile_girth_label(self):
        return girth_label(self.profile_data) if self.profile_data else ''


class QuotationLineSpec(models.Model):
    """Normalized spec value for reporting (mirrors specs_json)."""
    line = models.ForeignKey(QuotationLine, on_delete=models.CASCADE, related_name='specs')
    attribute_code = models.CharField(max_length=64)
    value = models.CharField(max_length=255, blank=True)


class CustomerAcceptance(models.Model):
    quotation = models.OneToOneField(
        Quotation, on_delete=models.CASCADE, related_name='acceptance'
    )
    accepted_at = models.DateTimeField(default=timezone.now)
    accepted_by_name = models.CharField(max_length=160, blank=True)
    reference = models.CharField(max_length=120, blank=True)
    note = models.TextField(blank=True)
    recorded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name='+'
    )


class Invoice(TimeStamped):
    number = models.CharField(max_length=24, blank=True)
    customer = models.ForeignKey(Customer, on_delete=models.PROTECT, related_name='invoices')
    quotation = models.ForeignKey(
        Quotation, on_delete=models.SET_NULL, null=True, blank=True, related_name='invoices'
    )
    status = models.CharField(
        max_length=24, choices=C.InvoiceStatus.choices, default=C.InvoiceStatus.DRAFT
    )
    payment_state = models.CharField(
        max_length=16, choices=C.PaymentState.choices, default=C.PaymentState.UNPAID
    )
    invoice_date = models.DateField(default=timezone.localdate)
    due_date = models.DateField(null=True, blank=True)
    payment_term = models.ForeignKey(
        PaymentTerm, on_delete=models.SET_NULL, null=True, blank=True, related_name='+'
    )
    tax_code = models.ForeignKey(
        TaxCode, on_delete=models.SET_NULL, null=True, blank=True, related_name='+'
    )
    delivery_address = models.TextField(blank=True)
    customer_ref = models.CharField(max_length=120, blank=True)
    discount = models.DecimalField(max_digits=12, decimal_places=2, default=ZERO)
    notes = models.TextField(blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name='+'
    )
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='+'
    )
    approved_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return self.number or f'INV-draft-{self.pk}'

    @property
    def subtotal(self):
        return sum((l.line_total for l in self.lines.all()), ZERO)

    @property
    def tax_amount(self):
        rate = self.tax_code.rate_pct if self.tax_code else ZERO
        return (self.subtotal - self.discount) * rate / Decimal('100')

    @property
    def total(self):
        return self.subtotal - self.discount + self.tax_amount

    @property
    def total_paid(self):
        return self.payments.filter(status=C.PaymentStatus.VERIFIED).aggregate(
            s=models.Sum('amount'))['s'] or ZERO

    @property
    def balance(self):
        return self.total - self.total_paid


class InvoiceLine(models.Model):
    invoice = models.ForeignKey(Invoice, on_delete=models.CASCADE, related_name='lines')
    item = models.ForeignKey(
        Item, on_delete=models.SET_NULL, null=True, blank=True, related_name='+'
    )
    source_quotation_line = models.ForeignKey(
        QuotationLine, on_delete=models.SET_NULL, null=True, blank=True, related_name='+'
    )
    description = models.CharField(max_length=255)
    quantity = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('1.00'))
    uom = models.CharField(max_length=16, blank=True)
    unit_price = models.DecimalField(max_digits=12, decimal_places=2, default=ZERO)
    discount = models.DecimalField(max_digits=12, decimal_places=2, default=ZERO)
    specs_json = models.JSONField(default=dict, blank=True)
    sort = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ['sort', 'id']

    @property
    def line_total(self):
        return self.quantity * self.unit_price - self.discount

    @property
    def spec_rows(self):
        return [r for r in (self.specs_json or {}).get('specs', [])
                if r.get('label') or r.get('value')]

    @property
    def length_rows(self):
        return [r for r in (self.specs_json or {}).get('lengths', [])
                if r.get('pcs') or r.get('len')]

    @property
    def length_total(self):
        total = Decimal('0')
        for r in self.length_rows:
            try:
                total += Decimal(str(r.get('pcs') or 0)) * Decimal(str(r.get('len') or 0))
            except (TypeError, ValueError):
                pass
        return total


class InvoiceLineSpec(models.Model):
    line = models.ForeignKey(InvoiceLine, on_delete=models.CASCADE, related_name='specs')
    attribute_code = models.CharField(max_length=64)
    value = models.CharField(max_length=255, blank=True)


class Payment(models.Model):
    invoice = models.ForeignKey(Invoice, on_delete=models.CASCADE, related_name='payments')
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    method = models.CharField(
        max_length=20, choices=C.PaymentMethod.choices, default=C.PaymentMethod.CASH
    )
    reference = models.CharField(max_length=120, blank=True)
    status = models.CharField(
        max_length=20, choices=C.PaymentStatus.choices, default=C.PaymentStatus.VERIFIED
    )
    received_at = models.DateTimeField(default=timezone.now)
    recorded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name='+'
    )

    class Meta:
        ordering = ['-received_at']


class InvoiceNote(models.Model):
    """A collections / follow-up log entry on an invoice (e.g. "called the
    customer, promised to pay Friday, still awaiting response")."""
    invoice = models.ForeignKey(
        Invoice, on_delete=models.CASCADE, related_name='followup_notes'
    )
    kind = models.CharField(
        max_length=16, choices=C.InvoiceNoteKind.choices,
        default=C.InvoiceNoteKind.FOLLOW_UP
    )
    body = models.TextField()
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name='+'
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']


class CreditCheckLog(models.Model):
    invoice = models.ForeignKey(Invoice, on_delete=models.CASCADE, related_name='credit_checks')
    mode = models.CharField(max_length=16)
    required_amount = models.DecimalField(max_digits=12, decimal_places=2, default=ZERO)
    satisfied = models.BooleanField(default=False)
    overridden = models.BooleanField(default=False)
    note = models.CharField(max_length=255, blank=True)
    decided_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name='+'
    )
    created_at = models.DateTimeField(auto_now_add=True)


# ===========================================================================
# 6. Manufacturing
# ===========================================================================
class JobOrder(TimeStamped):
    class Priority(models.TextChoices):
        LOW = 'low', 'Low'
        NORMAL = 'normal', 'Normal'
        HIGH = 'high', 'High'
        URGENT = 'urgent', 'Urgent'

    number = models.CharField(max_length=24, blank=True)
    invoice = models.ForeignKey(
        Invoice, on_delete=models.PROTECT, null=True, blank=True, related_name='job_orders'
    )
    quotation = models.ForeignKey(
        Quotation, on_delete=models.SET_NULL, null=True, blank=True, related_name='job_orders'
    )
    customer = models.ForeignKey(Customer, on_delete=models.PROTECT, related_name='job_orders')
    status = models.CharField(
        max_length=24, choices=C.JobOrderStatus.choices, default=C.JobOrderStatus.PENDING_RELEASE
    )
    priority = models.CharField(max_length=10, choices=Priority.choices, default=Priority.NORMAL)
    warehouse = models.ForeignKey(
        Warehouse, on_delete=models.SET_NULL, null=True, blank=True, related_name='job_orders'
    )
    required_date = models.DateField(null=True, blank=True)
    # Release gate flags (computed, but persisted so boards can filter cheaply)
    drawing_pending = models.BooleanField(default=False)
    material_short = models.BooleanField(default=False)
    credit_hold = models.BooleanField(default=False)
    notes = models.TextField(blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name='+'
    )
    released_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='+'
    )
    released_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return self.number or f'JO-draft-{self.pk}'

    @property
    def can_release(self):
        return not (self.drawing_pending or self.credit_hold)


class JobOrderLine(models.Model):
    job_order = models.ForeignKey(JobOrder, on_delete=models.CASCADE, related_name='lines')
    item = models.ForeignKey(
        Item, on_delete=models.SET_NULL, null=True, blank=True, related_name='+'
    )
    source_invoice_line = models.ForeignKey(
        InvoiceLine, on_delete=models.SET_NULL, null=True, blank=True, related_name='+'
    )
    description = models.CharField(max_length=255)
    quantity = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('1.00'))
    uom = models.CharField(max_length=16, blank=True)
    qty_produced = models.DecimalField(max_digits=12, decimal_places=2, default=ZERO)
    qty_delivered = models.DecimalField(max_digits=12, decimal_places=2, default=ZERO)
    is_manufactured = models.BooleanField(default=True)
    requires_drawing = models.BooleanField(default=False)
    specs_json = models.JSONField(default=dict, blank=True)
    sort = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ['sort', 'id']

    @property
    def qty_remaining_to_produce(self):
        return self.quantity - self.qty_produced

    @property
    def qty_remaining_to_deliver(self):
        return self.qty_produced - self.qty_delivered

    # --- Size / spec helpers (mirrors QuotationLine, read from specs_json) ---
    @property
    def spec_rows(self):
        return [r for r in (self.specs_json or {}).get('specs', [])
                if r.get('label') or r.get('value')]

    @property
    def length_rows(self):
        return [r for r in (self.specs_json or {}).get('lengths', [])
                if r.get('pcs') or r.get('len')]

    @property
    def length_total(self):
        total = Decimal('0')
        for r in self.length_rows:
            try:
                total += Decimal(str(r.get('pcs') or 0)) * Decimal(str(r.get('len') or 0))
            except (TypeError, ValueError):
                pass
        return total

    @property
    def spec_rows_no_color(self):
        """Spec rows minus the colour row (colour prints in its own column)."""
        return [r for r in self.spec_rows
                if (r.get('label') or '').strip().lower() != 'color']

    @property
    def color_label(self):
        specs = self.specs_json or {}
        if specs.get('color'):
            return specs['color']
        for r in self.spec_rows:
            if (r.get('label') or '').strip().lower() == 'color':
                return r.get('value') or ''
        return ''

    @property
    def profile_data(self):
        # See QuotationLine.profile_data: guard against a profile *code* string.
        data = (self.specs_json or {}).get('profile')
        return data if isinstance(data, dict) else {}

    @property
    def profile_svg(self):
        return build_profile_svg(self.profile_data) if self.profile_data else ''

    @property
    def profile_girth(self):
        return profile_girth(self.profile_data) if self.profile_data else 0

    @property
    def profile_girth_label(self):
        return girth_label(self.profile_data) if self.profile_data else ''


class JobOrderLineSpec(models.Model):
    line = models.ForeignKey(JobOrderLine, on_delete=models.CASCADE, related_name='specs')
    attribute_code = models.CharField(max_length=64)
    value = models.CharField(max_length=255, blank=True)


class DrawingAttachment(models.Model):
    job_order_line = models.ForeignKey(
        JobOrderLine, on_delete=models.CASCADE, related_name='drawings'
    )
    file = models.FileField(upload_to='drawings/')
    revision_no = models.PositiveIntegerField(default=1)
    status = models.CharField(
        max_length=16, choices=C.DrawingStatus.choices, default=C.DrawingStatus.SUBMITTED
    )
    notes = models.CharField(max_length=255, blank=True)
    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name='+'
    )
    uploaded_at = models.DateTimeField(auto_now_add=True)
    verified_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='+'
    )
    verified_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-revision_no']


class JobMaterialRequirement(models.Model):
    """Estimated (and later actual) raw material needed for a JO line."""
    job_order_line = models.ForeignKey(
        JobOrderLine, on_delete=models.CASCADE, related_name='requirements'
    )
    item = models.ForeignKey(Item, on_delete=models.PROTECT, related_name='+')
    estimated_qty = models.DecimalField(max_digits=12, decimal_places=3, default=ZERO)
    estimated_weight = models.DecimalField(max_digits=12, decimal_places=3, default=ZERO)
    actual_qty = models.DecimalField(max_digits=12, decimal_places=3, default=ZERO)
    uom = models.CharField(max_length=16, blank=True)
    note = models.CharField(max_length=255, blank=True)


class MaterialReservation(TimeStamped):
    job_order = models.ForeignKey(
        JobOrder, on_delete=models.CASCADE, related_name='reservations'
    )
    status = models.CharField(
        max_length=20, choices=C.ReservationStatus.choices, default=C.ReservationStatus.PENDING
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name='+'
    )

    def __str__(self):
        return f'RES for {self.job_order}'


class MaterialReservationLine(models.Model):
    reservation = models.ForeignKey(
        MaterialReservation, on_delete=models.CASCADE, related_name='lines'
    )
    requirement = models.ForeignKey(
        JobMaterialRequirement, on_delete=models.SET_NULL, null=True, blank=True, related_name='+'
    )
    item = models.ForeignKey(Item, on_delete=models.PROTECT, related_name='+')
    coil = models.ForeignKey(
        'Coil', on_delete=models.SET_NULL, null=True, blank=True, related_name='reservation_lines'
    )
    warehouse = models.ForeignKey(Warehouse, on_delete=models.PROTECT, related_name='+')
    qty_reserved = models.DecimalField(max_digits=12, decimal_places=3, default=ZERO)
    qty_issued = models.DecimalField(max_digits=12, decimal_places=3, default=ZERO)
    status = models.CharField(
        max_length=20, choices=C.ReservationStatus.choices, default=C.ReservationStatus.RESERVED
    )

    @property
    def qty_open(self):
        return self.qty_reserved - self.qty_issued


class ProductionRun(TimeStamped):
    number = models.CharField(max_length=24, blank=True)
    job_order = models.ForeignKey(
        JobOrder, on_delete=models.PROTECT, related_name='production_runs'
    )
    machine = models.ForeignKey(
        Machine, on_delete=models.SET_NULL, null=True, blank=True, related_name='runs'
    )
    operator = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='+'
    )
    status = models.CharField(
        max_length=16, choices=C.ProductionRunStatus.choices, default=C.ProductionRunStatus.PLANNED
    )
    started_at = models.DateTimeField(null=True, blank=True)
    ended_at = models.DateTimeField(null=True, blank=True)
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return self.number or f'PR-draft-{self.pk}'


class ProductionRunOutput(models.Model):
    run = models.ForeignKey(ProductionRun, on_delete=models.CASCADE, related_name='outputs')
    job_order_line = models.ForeignKey(
        JobOrderLine, on_delete=models.PROTECT, related_name='run_outputs'
    )
    good_qty = models.DecimalField(max_digits=12, decimal_places=2, default=ZERO)
    reject_qty = models.DecimalField(max_digits=12, decimal_places=2, default=ZERO)
    scrap_qty = models.DecimalField(max_digits=12, decimal_places=3, default=ZERO)
    uom = models.CharField(max_length=16, blank=True)


class QCInspection(models.Model):
    run_output = models.ForeignKey(
        ProductionRunOutput, on_delete=models.CASCADE, related_name='inspections'
    )
    result = models.CharField(
        max_length=10, choices=C.QCResult.choices, default=C.QCResult.PENDING
    )
    qty_pass = models.DecimalField(max_digits=12, decimal_places=2, default=ZERO)
    qty_reject = models.DecimalField(max_digits=12, decimal_places=2, default=ZERO)
    notes = models.CharField(max_length=255, blank=True)
    inspected_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name='+'
    )
    created_at = models.DateTimeField(auto_now_add=True)


# ===========================================================================
# 7. Inventory
# ===========================================================================
class StockBalance(models.Model):
    """Derived counters per item+warehouse. Updated only via the ledger service."""
    item = models.ForeignKey(Item, on_delete=models.CASCADE, related_name='stock_balances')
    warehouse = models.ForeignKey(Warehouse, on_delete=models.CASCADE, related_name='stock_balances')
    qty_on_hand = models.DecimalField(max_digits=14, decimal_places=3, default=ZERO)
    qty_reserved = models.DecimalField(max_digits=14, decimal_places=3, default=ZERO)

    class Meta:
        unique_together = [('item', 'warehouse')]
        ordering = ['item_id', 'warehouse_id']

    @property
    def qty_available(self):
        return self.qty_on_hand - self.qty_reserved

    def __str__(self):
        return f'{self.item.code} @ {self.warehouse.code}'


class Coil(TimeStamped):
    """Lot-tracked raw coil instance -- the spine of traceability."""
    coil_number = models.CharField(max_length=32, unique=True)
    supplier_coil_no = models.CharField(max_length=64, blank=True)
    item = models.ForeignKey(Item, on_delete=models.PROTECT, related_name='coils')
    color = models.ForeignKey(
        Color, on_delete=models.SET_NULL, null=True, blank=True, related_name='+'
    )
    thickness_mm = models.DecimalField(max_digits=6, decimal_places=3, null=True, blank=True)
    width_mm = models.DecimalField(max_digits=8, decimal_places=2, null=True, blank=True)
    finish = models.CharField(max_length=40, blank=True)
    original_length_m = models.DecimalField(max_digits=12, decimal_places=3, default=ZERO)
    original_weight_kg = models.DecimalField(max_digits=12, decimal_places=3, default=ZERO)
    remaining_length_m = models.DecimalField(max_digits=12, decimal_places=3, default=ZERO)
    remaining_weight_kg = models.DecimalField(max_digits=12, decimal_places=3, default=ZERO)
    cost = models.DecimalField(max_digits=14, decimal_places=2, default=ZERO)
    supplier = models.ForeignKey(
        Supplier, on_delete=models.SET_NULL, null=True, blank=True, related_name='coils'
    )
    received_at = models.DateField(default=timezone.localdate)
    warehouse = models.ForeignKey(Warehouse, on_delete=models.PROTECT, related_name='coils')
    bin = models.ForeignKey(
        BinLocation, on_delete=models.SET_NULL, null=True, blank=True, related_name='coils'
    )
    lot = models.CharField(max_length=64, blank=True)
    status = models.CharField(
        max_length=16, choices=C.CoilStatus.choices, default=C.CoilStatus.AVAILABLE
    )
    parent_coil = models.ForeignKey(
        'self', on_delete=models.SET_NULL, null=True, blank=True, related_name='remnants'
    )
    notes = models.CharField(max_length=255, blank=True)

    class Meta:
        ordering = ['coil_number']

    def __str__(self):
        return self.coil_number


class InventoryTransaction(models.Model):
    """Immutable stock ledger. Postings are never edited/deleted -- reversed."""
    txn_type = models.CharField(max_length=24, choices=C.InventoryTxnType.choices)
    item = models.ForeignKey(Item, on_delete=models.PROTECT, related_name='transactions')
    warehouse = models.ForeignKey(Warehouse, on_delete=models.PROTECT, related_name='transactions')
    coil = models.ForeignKey(
        Coil, on_delete=models.SET_NULL, null=True, blank=True, related_name='transactions'
    )
    quantity = models.DecimalField(max_digits=14, decimal_places=3)  # signed
    uom = models.CharField(max_length=16, blank=True)
    weight = models.DecimalField(max_digits=14, decimal_places=3, default=ZERO)
    # loose references (avoid a hard FK web; keep queryable pointers)
    job_order = models.ForeignKey(
        JobOrder, on_delete=models.SET_NULL, null=True, blank=True, related_name='transactions'
    )
    production_run = models.ForeignKey(
        ProductionRun, on_delete=models.SET_NULL, null=True, blank=True, related_name='transactions'
    )
    ref_type = models.CharField(max_length=32, blank=True)
    ref_id = models.PositiveIntegerField(null=True, blank=True)
    reversed_by = models.ForeignKey(
        'self', on_delete=models.SET_NULL, null=True, blank=True, related_name='reverses'
    )
    reason = models.CharField(max_length=255, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name='+'
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at', '-id']

    def __str__(self):
        return f'{self.get_txn_type_display()} {self.item.code} {self.quantity}'


class CoilConsumption(models.Model):
    production_run = models.ForeignKey(
        ProductionRun, on_delete=models.CASCADE, related_name='coil_consumptions'
    )
    job_order_line = models.ForeignKey(
        JobOrderLine, on_delete=models.PROTECT, related_name='coil_consumptions'
    )
    coil = models.ForeignKey(Coil, on_delete=models.PROTECT, related_name='consumptions')
    length_before = models.DecimalField(max_digits=12, decimal_places=3, default=ZERO)
    length_after = models.DecimalField(max_digits=12, decimal_places=3, default=ZERO)
    length_consumed = models.DecimalField(max_digits=12, decimal_places=3, default=ZERO)
    weight_consumed = models.DecimalField(max_digits=12, decimal_places=3, default=ZERO)
    scrap_length = models.DecimalField(max_digits=12, decimal_places=3, default=ZERO)
    remnant_coil = models.ForeignKey(
        Coil, on_delete=models.SET_NULL, null=True, blank=True, related_name='+'
    )
    created_at = models.DateTimeField(auto_now_add=True)


class StockTransfer(TimeStamped):
    number = models.CharField(max_length=24, blank=True)
    item = models.ForeignKey(Item, on_delete=models.PROTECT, related_name='+')
    coil = models.ForeignKey(
        Coil, on_delete=models.SET_NULL, null=True, blank=True, related_name='+'
    )
    from_warehouse = models.ForeignKey(Warehouse, on_delete=models.PROTECT, related_name='+')
    to_warehouse = models.ForeignKey(Warehouse, on_delete=models.PROTECT, related_name='+')
    quantity = models.DecimalField(max_digits=14, decimal_places=3)
    note = models.CharField(max_length=255, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name='+'
    )


class FinishedGoodsLot(TimeStamped):
    lot_number = models.CharField(max_length=32, unique=True)
    item = models.ForeignKey(Item, on_delete=models.PROTECT, related_name='fg_lots')
    job_order = models.ForeignKey(
        JobOrder, on_delete=models.SET_NULL, null=True, blank=True, related_name='fg_lots'
    )
    job_order_line = models.ForeignKey(
        JobOrderLine, on_delete=models.SET_NULL, null=True, blank=True, related_name='fg_lots'
    )
    production_run = models.ForeignKey(
        ProductionRun, on_delete=models.SET_NULL, null=True, blank=True, related_name='fg_lots'
    )
    warehouse = models.ForeignKey(Warehouse, on_delete=models.PROTECT, related_name='fg_lots')
    qty_produced = models.DecimalField(max_digits=12, decimal_places=2, default=ZERO)
    qty_available = models.DecimalField(max_digits=12, decimal_places=2, default=ZERO)
    qty_delivered = models.DecimalField(max_digits=12, decimal_places=2, default=ZERO)
    uom = models.CharField(max_length=16, blank=True)
    status = models.CharField(
        max_length=16, choices=C.FGLotStatus.choices, default=C.FGLotStatus.AVAILABLE
    )

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return self.lot_number


# ===========================================================================
# 8. Logistics
# ===========================================================================
class Delivery(TimeStamped):
    number = models.CharField(max_length=24, blank=True)
    customer = models.ForeignKey(Customer, on_delete=models.PROTECT, related_name='deliveries')
    invoice = models.ForeignKey(
        Invoice, on_delete=models.SET_NULL, null=True, blank=True, related_name='deliveries'
    )
    job_order = models.ForeignKey(
        JobOrder, on_delete=models.SET_NULL, null=True, blank=True, related_name='deliveries'
    )
    status = models.CharField(
        max_length=16, choices=C.DeliveryStatus.choices, default=C.DeliveryStatus.DRAFT
    )
    delivery_address = models.TextField(blank=True)
    truck = models.CharField(max_length=120, blank=True)
    driver = models.CharField(max_length=120, blank=True)
    scheduled_for = models.DateTimeField(null=True, blank=True)
    dispatched_at = models.DateTimeField(null=True, blank=True)
    delivered_at = models.DateTimeField(null=True, blank=True)
    prepared_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name='+'
    )
    released_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='+'
    )
    received_by = models.CharField(max_length=160, blank=True)
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return self.number or f'DR-draft-{self.pk}'


class DeliveryLine(models.Model):
    delivery = models.ForeignKey(Delivery, on_delete=models.CASCADE, related_name='lines')
    job_order_line = models.ForeignKey(
        JobOrderLine, on_delete=models.SET_NULL, null=True, blank=True, related_name='delivery_lines'
    )
    fg_lot = models.ForeignKey(
        FinishedGoodsLot, on_delete=models.SET_NULL, null=True, blank=True, related_name='delivery_lines'
    )
    item = models.ForeignKey(Item, on_delete=models.SET_NULL, null=True, blank=True, related_name='+')
    description = models.CharField(max_length=255)
    quantity = models.DecimalField(max_digits=12, decimal_places=2, default=ZERO)
    uom = models.CharField(max_length=16, blank=True)


class DeliveryProof(models.Model):
    delivery = models.ForeignKey(Delivery, on_delete=models.CASCADE, related_name='proofs')
    image = models.ImageField(upload_to='delivery_proofs/', null=True, blank=True)
    received_by_name = models.CharField(max_length=160, blank=True)
    signed_at = models.DateTimeField(default=timezone.now)
    note = models.CharField(max_length=255, blank=True)


# ===========================================================================
# 9. Audit
# ===========================================================================
class AuditEvent(models.Model):
    entity_type = models.CharField(max_length=64)
    entity_id = models.PositiveIntegerField()
    action = models.CharField(max_length=64)
    old_value = models.JSONField(null=True, blank=True)
    new_value = models.JSONField(null=True, blank=True)
    reason = models.CharField(max_length=255, blank=True)
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name='+'
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [models.Index(fields=['entity_type', 'entity_id'])]

    def __str__(self):
        return f'{self.entity_type}#{self.entity_id} {self.action}'


class StatusHistory(models.Model):
    entity_type = models.CharField(max_length=64)
    entity_id = models.PositiveIntegerField()
    from_status = models.CharField(max_length=32, blank=True)
    to_status = models.CharField(max_length=32)
    note = models.CharField(max_length=255, blank=True)
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name='+'
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [models.Index(fields=['entity_type', 'entity_id'])]

    def __str__(self):
        return f'{self.entity_type}#{self.entity_id} -> {self.to_status}'


# ===========================================================================
# 10. Reporting -- imported / historical actuals
# ===========================================================================
class ProductionActual(models.Model):
    """A single month's production figure for one report category. Lets the
    official production report show historical actuals (imported from the
    company's spreadsheets) alongside live production, so trends and forecasts
    have real history to work from."""
    class Dimension(models.TextChoices):
        PROFILE = 'profile', 'Profile'
        GAUGE = 'gauge', 'Gauge'
        COLOR = 'color', 'Colour'
        SUMMARY = 'summary', 'Summary'  # e.g. No. of Bended, No. of Days

    year = models.PositiveSmallIntegerField()
    month = models.PositiveSmallIntegerField()  # 1-12
    dimension = models.CharField(max_length=10, choices=Dimension.choices)
    category = models.CharField(max_length=80)  # e.g. '8-Rib', '0.50mm', 'RED'
    lm = models.DecimalField(max_digits=14, decimal_places=2, default=ZERO)
    weight_kg = models.DecimalField(max_digits=16, decimal_places=3, default=ZERO)
    source = models.CharField(max_length=64, blank=True)  # e.g. 'import:2026'

    class Meta:
        ordering = ['year', 'dimension', 'category', 'month']
        unique_together = [('year', 'month', 'dimension', 'category')]
        indexes = [models.Index(fields=['year', 'dimension'])]

    def __str__(self):
        return f'{self.year}-{self.month:02d} {self.dimension}:{self.category} {self.lm} LM'


# ===========================================================================
# 11. AI Analyst -- read-only conversational assistant
# ===========================================================================
class AIConversation(TimeStamped):
    """One chat thread between a user and the AI Analyst. Threads are private to
    their owner; grounding always happens against live data at answer time."""
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='ai_conversations'
    )
    title = models.CharField(max_length=160, default='New conversation')

    class Meta:
        ordering = ['-updated_at']
        indexes = [models.Index(fields=['user', '-updated_at'])]

    def __str__(self):
        return f'{self.title} ({self.user})'


class AIMessage(models.Model):
    """A single turn in an AIConversation. ``meta`` carries non-content extras
    such as the tools the assistant called and any chart payload for the UI."""
    class Role(models.TextChoices):
        USER = 'user', 'User'
        ASSISTANT = 'assistant', 'Assistant'
        SYSTEM = 'system', 'System'

    conversation = models.ForeignKey(
        AIConversation, on_delete=models.CASCADE, related_name='messages'
    )
    role = models.CharField(max_length=10, choices=Role.choices)
    content = models.TextField(blank=True)
    meta = models.JSONField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['created_at']
        indexes = [models.Index(fields=['conversation', 'created_at'])]

    def __str__(self):
        return f'{self.role}: {self.content[:40]}'
