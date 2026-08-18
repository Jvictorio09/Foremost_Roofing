from django import forms
from django.contrib.auth.forms import AuthenticationForm
from django.forms import inlineformset_factory

from .models import (
    Coil, Color, Customer, Delivery, Invoice, InvoiceNote, Item, Machine,
    Payment, Profile, ProductionRun, Quotation, QuotationLine, Role,
    StandardDrawing, Supplier, User, Warehouse,
)


INPUT_CLASS = (
    'w-full rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm '
    'text-slate-900 placeholder-slate-400 focus:border-slate-900 focus:outline-none '
    'focus:ring-2 focus:ring-slate-900/10'
)


TEXTLIKE_WIDGETS = (
    forms.TextInput, forms.Textarea, forms.EmailInput, forms.NumberInput,
    forms.URLInput, forms.PasswordInput,
)


class StyledFormMixin:
    # Optional per-form map of {field_name: placeholder text}.
    placeholders = {}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for name, field in self.fields.items():
            widget = field.widget
            if isinstance(widget, forms.CheckboxInput):
                widget.attrs['class'] = 'h-4 w-4 rounded border-slate-300 accent-slate-900'
                continue
            # Multi-select checkbox / radio groups: style each option's input as a
            # real checkbox, never as a full-width text field.
            if isinstance(widget, (forms.CheckboxSelectMultiple, forms.RadioSelect)):
                widget.attrs['class'] = 'h-4 w-4 rounded border-slate-300 accent-slate-900'
                continue
            existing = widget.attrs.get('class', '')
            widget.attrs['class'] = (existing + ' ' + INPUT_CLASS).strip()

            placeholder = self.placeholders.get(name)
            # Single-select dropdowns become searchable (Tom Select, see base.html).
            if isinstance(widget, forms.Select) and not isinstance(
                    widget, (forms.SelectMultiple, forms.RadioSelect)):
                widget.attrs['class'] = (widget.attrs['class'] + ' js-search').strip()
                if placeholder:
                    widget.attrs['data-placeholder'] = placeholder
            elif placeholder and isinstance(widget, TEXTLIKE_WIDGETS):
                widget.attrs.setdefault('placeholder', placeholder)


class LoginForm(StyledFormMixin, AuthenticationForm):
    pass


CUSTOMER_PLACEHOLDERS = {
    'code': 'Auto-generated if left blank',
    'name': 'e.g. ABC Construction Corp.',
    'contact_person': 'e.g. Juan Dela Cruz',
    'phone': 'e.g. 0917 123 4567',
    'email': 'e.g. juan@abccorp.com',
    'address': 'Street, Barangay, City, Province',
    'tin': 'e.g. 009-300-990-000',
    'credit_limit': '0.00',
    'notes': 'Any special terms or reminders',
}


class CustomerForm(StyledFormMixin, forms.ModelForm):
    placeholders = CUSTOMER_PLACEHOLDERS

    class Meta:
        model = Customer
        fields = ['code', 'name', 'contact_person', 'phone', 'email', 'address',
                  'tin', 'credit_limit', 'payment_term', 'notes']
        widgets = {'address': forms.Textarea(attrs={'rows': 2}),
                   'notes': forms.Textarea(attrs={'rows': 2})}


class CustomerQuickForm(StyledFormMixin, forms.ModelForm):
    """Minimal customer form for inline creation from other screens."""
    placeholders = CUSTOMER_PLACEHOLDERS

    class Meta:
        model = Customer
        fields = ['name', 'contact_person', 'phone', 'email', 'tin', 'address']
        widgets = {'address': forms.Textarea(attrs={'rows': 2})}


class SalespersonQuickForm(StyledFormMixin, forms.Form):
    """Create a lightweight salesperson inline from the quotation form.

    It provisions a Sales-role user with an unusable password (an admin sets a
    real one later in Users & Roles), so the person is immediately selectable on
    quotations without leaving the page."""
    placeholders = {
        'full_name': 'e.g. Maria Santos',
        'email': 'e.g. maria@foremostroofing.com',
        'phone': 'e.g. 0917 123 4567',
    }
    full_name = forms.CharField(label='Full name', max_length=120)
    email = forms.EmailField(label='Email', required=False)
    phone = forms.CharField(label='Phone', max_length=32, required=False)


class SupplierForm(StyledFormMixin, forms.ModelForm):
    placeholders = {
        'code': 'Auto-generated if left blank',
        'name': 'e.g. Steel Supply Co.',
        'contact_person': 'e.g. Maria Santos',
        'phone': 'e.g. 0917 123 4567',
        'email': 'e.g. sales@steelsupply.com',
        'address': 'Street, Barangay, City, Province',
    }

    class Meta:
        model = Supplier
        fields = ['code', 'name', 'contact_person', 'phone', 'email', 'address']
        widgets = {'address': forms.Textarea(attrs={'rows': 2})}


class ItemForm(StyledFormMixin, forms.ModelForm):
    placeholders = {
        'code': 'e.g. BND-APRON-FLASHING',
        'name': 'e.g. Apron Flashing',
    }

    class Meta:
        model = Item
        fields = ['code', 'name', 'item_type', 'category', 'uom', 'profile', 'color',
                  'thickness_mm', 'coil_width_mm', 'finish', 'style',
                  'weight_factor_kg_per_lm', 'is_manufactured', 'requires_drawing',
                  'track_lot', 'standard_cost', 'reorder_point', 'reference_image',
                  'is_active']
        help_texts = {
            'code': 'Naming convention — bended / drawing items: BND-<ACCESSORY> '
                    '(e.g. BND-APRON-FLASHING). Roll-formed goods: FG-<PROFILE>-<THK> '
                    '(e.g. FG-BARCA_RIB-0.4). Keep it uppercase with dashes.',
            'name': 'Readable name shown on quotations, e.g. "Apron Flashing". '
                    'The specific girth / bend shape is set per line via the drawing.',
            'requires_drawing': 'Tick for bended accessories so a reference drawing '
                                 'and girth are required on each quotation line.',
        }


class StandardDrawingForm(StyledFormMixin, forms.ModelForm):
    placeholders = {
        'code': 'e.g. END-FLASH',
        'name': 'e.g. End Flashing',
        'default_girth': 'e.g. 24"',
        'notes': 'Optional description',
    }

    class Meta:
        model = StandardDrawing
        fields = ['code', 'name', 'category', 'image', 'default_girth', 'notes',
                  'is_active']


class ProfileForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = Profile
        fields = ['code', 'name', 'category', 'machine', 'nominal_width_mm',
                  'effective_width_mm', 'default_coil_width_mm', 'waste_pct',
                  'notes', 'is_active']
        widgets = {'notes': forms.Textarea(attrs={'rows': 2})}


class ColorForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = Color
        fields = ['code', 'name', 'hex_value']


class MachineForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = Machine
        fields = ['code', 'name', 'warehouse', 'is_active']


class CoilForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = Coil
        fields = ['coil_number', 'supplier_coil_no', 'item', 'color', 'thickness_mm',
                  'width_mm', 'finish', 'original_length_m', 'original_weight_kg',
                  'cost', 'supplier', 'received_at', 'warehouse', 'bin', 'lot', 'notes']
        widgets = {'received_at': forms.DateInput(attrs={'type': 'date'})}


class QuotationForm(StyledFormMixin, forms.ModelForm):
    placeholders = {
        'customer': 'Search or select a customer…',
        'payment_term': 'Select payment term',
        'tax_code': 'Select tax code',
        'price_list': 'Select price list',
        'salesperson': 'Select salesperson',
        'delivery_address': 'Where should the order be delivered?',
        'project_site': 'e.g. Lipa City warehouse project',
        'customer_ref': "Customer's PO or reference no.",
        'discount': '0.00',
        'notes': 'Internal notes or special instructions',
    }

    class Meta:
        model = Quotation
        fields = ['customer', 'quote_date', 'valid_until', 'payment_term', 'tax_code',
                  'price_list', 'salesperson', 'delivery_address', 'project_site',
                  'customer_ref', 'discount', 'notes']
        widgets = {
            'quote_date': forms.DateInput(attrs={'type': 'date'}),
            'valid_until': forms.DateInput(attrs={'type': 'date'}),
            'delivery_address': forms.Textarea(attrs={'rows': 2}),
            'notes': forms.Textarea(attrs={'rows': 2}),
        }


class QuotationLineForm(StyledFormMixin, forms.ModelForm):
    placeholders = {
        'item': 'Search item by name or code…',
        'description': 'Optional description / spec',
        'quantity': '0.00',
        'unit_price': '0.00',
        'discount': '0.00',
        'standard_drawing': 'Attach a reference drawing…',
    }

    class Meta:
        model = QuotationLine
        fields = ['item', 'description', 'quantity', 'uom', 'unit_price', 'discount',
                  'standard_drawing', 'custom_image', 'specs_json']
        widgets = {'specs_json': forms.HiddenInput(attrs={'x-ref': 'specsField'})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['quantity'].widget.attrs['x-ref'] = 'qtyField'
        self.fields['standard_drawing'].widget.attrs.update(
            {'x-ref': 'drawingField', '@change': 'onDrawing()'})
        self.fields['custom_image'].widget.attrs.update(
            {'x-ref': 'imageField', '@change': 'onImage($event)'})


QuotationLineFormSet = inlineformset_factory(
    Quotation, QuotationLine, form=QuotationLineForm,
    extra=1, can_delete=True,
)


class PaymentForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = Payment
        fields = ['amount', 'method', 'reference']


class InvoiceNoteForm(StyledFormMixin, forms.ModelForm):
    placeholders = {
        'body': 'e.g. Called Ms. Reyes 8/14, promised payment by Friday; '
                'emailed SOA, no response yet.',
    }

    class Meta:
        model = InvoiceNote
        fields = ['kind', 'body']
        widgets = {'body': forms.Textarea(attrs={'rows': 3, 'class': 'resize-none'})}


class ProductionRunForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = ProductionRun
        fields = ['job_order', 'machine', 'operator', 'notes']
        widgets = {'notes': forms.Textarea(attrs={'rows': 2})}


class DeliveryForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = Delivery
        fields = ['customer', 'invoice', 'job_order', 'delivery_address', 'truck',
                  'driver', 'scheduled_for', 'notes']
        widgets = {
            'scheduled_for': forms.DateTimeInput(attrs={'type': 'datetime-local'}),
            'delivery_address': forms.Textarea(attrs={'rows': 2}),
            'notes': forms.Textarea(attrs={'rows': 2}),
        }


class RoleForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = Role
        fields = ['name', 'description', 'permissions']
        widgets = {'permissions': forms.CheckboxSelectMultiple()}


class UserForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = User
        fields = ['username', 'first_name', 'last_name', 'email', 'phone',
                  'roles', 'is_active']
        widgets = {'roles': forms.CheckboxSelectMultiple()}
