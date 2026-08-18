"""Master data screens. A small generic CRUD helper keeps every master
(customer, supplier, item, profile, color, coil...) on two shared templates."""
import json

from django.contrib import messages
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render

from ..forms import (
    ColorForm, CustomerForm, CustomerQuickForm, ItemForm, MachineForm, ProfileForm,
    StandardDrawingForm, SupplierForm,
)
from ..models import (
    AppSetting, AttributeDefinition, CategoryAttribute, Color, Customer, Item,
    ItemCategory, Machine, Profile, StandardDrawing, Supplier, Warehouse,
)
from ..rbac import permission_required
from .common import is_hx, paginate


@permission_required('masterdata.manage', 'product.manage', 'pricelist.manage')
def master_hub(request):
    groups = [
        {'title': 'Commercial', 'items': [
            ('Customers', 'customer_list', Customer.objects.count()),
            ('Suppliers', 'supplier_list', Supplier.objects.count()),
        ]},
        {'title': 'Catalog', 'items': [
            ('Items', 'item_list', Item.objects.count()),
            ('Profiles', 'profile_list', Profile.objects.count()),
            ('Colors', 'color_list', Color.objects.count()),
            ('Standard Drawings', 'drawing_list', StandardDrawing.objects.count()),
            ('Product Attributes', 'attribute_list', AttributeDefinition.objects.count()),
        ]},
        {'title': 'Operations', 'items': [
            ('Machines', 'machine_list', Machine.objects.count()),
            ('Warehouses', 'warehouse_list', Warehouse.objects.count()),
            ('System Settings', 'settings_list', AppSetting.objects.count()),
        ]},
    ]
    return render(request, 'masters/hub.html', {'groups': groups})


def _crud_form(request, form_class, instance, title, redirect_url, success_msg):
    hx = is_hx(request)
    if request.method == 'POST':
        form = form_class(request.POST, request.FILES, instance=instance)
        if form.is_valid():
            form.save()
            messages.success(request, success_msg)
            if hx:
                # Close the modal and reload the list underneath it.
                resp = HttpResponse(status=204)
                resp['HX-Refresh'] = 'true'
                return resp
            return redirect(redirect_url)
        # Invalid: re-render so errors show (in modal or full page).
    else:
        form = form_class(instance=instance)
    template = 'masters/_form_modal.html' if hx else 'masters/form.html'
    return render(request, template, {
        'form': form, 'title': title, 'form_action': request.path})


# --- Customers -------------------------------------------------------------
@permission_required('quotation.view', 'masterdata.manage', 'invoice.view')
def customer_list(request):
    return render(request, 'masters/simple_list.html', {
        'title': 'Customers', 'rows': Customer.objects.all(),
        'create_url': 'customer_create', 'edit_url': 'customer_edit',
        'fields': [('name', 'Name'), ('contact_person', 'Contact'),
                   ('phone', 'Phone'), ('email', 'Email')]})


@permission_required('masterdata.manage')
def customer_create(request):
    return _crud_form(request, CustomerForm, None, 'New Customer',
                      'customer_list', 'Customer created.')


@permission_required('masterdata.manage')
def customer_edit(request, pk):
    return _crud_form(request, CustomerForm, get_object_or_404(Customer, pk=pk),
                      'Edit Customer', 'customer_list', 'Customer updated.')


@permission_required('masterdata.manage')
def customer_quick_create(request):
    """Inline customer creation used from other forms (e.g. New Quotation).
    On success it fires an htmx ``customerCreated`` event so the opener can add
    the new customer to its dropdown without losing the page state."""
    if request.method == 'POST':
        form = CustomerQuickForm(request.POST)
        if form.is_valid():
            customer = form.save()
            resp = HttpResponse(status=204)
            resp['HX-Trigger'] = json.dumps({
                'customerCreated': {'id': customer.pk, 'name': customer.name}})
            return resp
    else:
        form = CustomerQuickForm()
    return render(request, 'masters/_form_modal.html', {
        'form': form, 'title': 'New Customer',
        'form_action': request.path})


# --- Suppliers -------------------------------------------------------------
@permission_required('masterdata.manage', 'inventory.view')
def supplier_list(request):
    return render(request, 'masters/simple_list.html', {
        'title': 'Suppliers', 'rows': Supplier.objects.all(),
        'create_url': 'supplier_create', 'edit_url': 'supplier_edit',
        'fields': [('name', 'Name'), ('contact_person', 'Contact'), ('phone', 'Phone')]})


@permission_required('masterdata.manage')
def supplier_create(request):
    return _crud_form(request, SupplierForm, None, 'New Supplier',
                      'supplier_list', 'Supplier created.')


@permission_required('masterdata.manage')
def supplier_edit(request, pk):
    return _crud_form(request, SupplierForm, get_object_or_404(Supplier, pk=pk),
                      'Edit Supplier', 'supplier_list', 'Supplier updated.')


# --- Items -----------------------------------------------------------------
@permission_required('product.manage', 'inventory.view')
def item_list(request):
    return render(request, 'masters/simple_list.html', {
        'title': 'Items', 'rows': Item.objects.select_related('category', 'uom'),
        'create_url': 'item_create', 'edit_url': 'item_edit',
        'fields': [('code', 'Code'), ('name', 'Name'),
                   ('get_item_type_display', 'Type'), ('category', 'Category')]})


@permission_required('product.manage')
def item_create(request):
    return _crud_form(request, ItemForm, None, 'New Item', 'item_list', 'Item created.')


@permission_required('product.manage')
def item_edit(request, pk):
    return _crud_form(request, ItemForm, get_object_or_404(Item, pk=pk),
                      'Edit Item', 'item_list', 'Item updated.')


# --- Profiles --------------------------------------------------------------
@permission_required('product.manage')
def profile_list(request):
    return render(request, 'masters/simple_list.html', {
        'title': 'Profiles', 'rows': Profile.objects.select_related('category'),
        'create_url': 'profile_create', 'edit_url': 'profile_edit',
        'fields': [('code', 'Code'), ('name', 'Name'), ('category', 'Category'),
                   ('effective_width_mm', 'Eff. width')]})


@permission_required('product.manage')
def profile_create(request):
    return _crud_form(request, ProfileForm, None, 'New Profile', 'profile_list', 'Profile created.')


@permission_required('product.manage')
def profile_edit(request, pk):
    return _crud_form(request, ProfileForm, get_object_or_404(Profile, pk=pk),
                      'Edit Profile', 'profile_list', 'Profile updated.')


# --- Colors ----------------------------------------------------------------
@permission_required('product.manage')
def color_list(request):
    return render(request, 'masters/simple_list.html', {
        'title': 'Colors', 'rows': Color.objects.all(),
        'create_url': 'color_create', 'edit_url': 'color_edit',
        'fields': [('code', 'Code'), ('name', 'Name'), ('hex_value', 'Hex')]})


@permission_required('product.manage')
def color_create(request):
    return _crud_form(request, ColorForm, None, 'New Color', 'color_list', 'Color created.')


@permission_required('product.manage')
def color_edit(request, pk):
    return _crud_form(request, ColorForm, get_object_or_404(Color, pk=pk),
                      'Edit Color', 'color_list', 'Color updated.')


# --- Standard drawings -----------------------------------------------------
@permission_required('product.manage', 'quotation.view', 'quotation.create')
def drawing_list(request):
    return render(request, 'masters/drawing_list.html', {
        'title': 'Standard Drawings', 'rows': StandardDrawing.objects.select_related('category')})


@permission_required('product.manage')
def drawing_create(request):
    return _crud_form(request, StandardDrawingForm, None, 'New Standard Drawing',
                      'drawing_list', 'Drawing created.')


@permission_required('product.manage')
def drawing_edit(request, pk):
    return _crud_form(request, StandardDrawingForm, get_object_or_404(StandardDrawing, pk=pk),
                      'Edit Standard Drawing', 'drawing_list', 'Drawing updated.')


@permission_required('product.manage', 'quotation.create')
def drawing_quick_create(request):
    """Inline standard-drawing creation from the quotation line editor. On success
    fires an htmx ``drawingCreated`` event so the opener can add the new drawing to
    every line's picker (and preview map) without leaving the page."""
    if request.method == 'POST':
        form = StandardDrawingForm(request.POST, request.FILES)
        if form.is_valid():
            drawing = form.save()
            resp = HttpResponse(status=204)
            resp['HX-Trigger'] = json.dumps({'drawingCreated': {
                'id': drawing.pk, 'name': drawing.name,
                'url': drawing.image.url if drawing.image else ''}})
            return resp
    else:
        form = StandardDrawingForm()
    return render(request, 'masters/_form_modal.html', {
        'form': form, 'title': 'New Standard Drawing', 'form_action': request.path})


# --- Machines --------------------------------------------------------------
@permission_required('masterdata.manage')
def machine_list(request):
    return render(request, 'masters/simple_list.html', {
        'title': 'Machines', 'rows': Machine.objects.select_related('warehouse'),
        'create_url': 'machine_create', 'edit_url': 'machine_edit',
        'fields': [('code', 'Code'), ('name', 'Name'), ('warehouse', 'Warehouse')]})


@permission_required('masterdata.manage')
def machine_create(request):
    return _crud_form(request, MachineForm, None, 'New Machine', 'machine_list', 'Machine created.')


@permission_required('masterdata.manage')
def machine_edit(request, pk):
    return _crud_form(request, MachineForm, get_object_or_404(Machine, pk=pk),
                      'Edit Machine', 'machine_list', 'Machine updated.')


# --- Warehouses (read-only list for Phase 1) -------------------------------
@permission_required('masterdata.manage', 'inventory.view')
def warehouse_list(request):
    return render(request, 'masters/simple_list.html', {
        'title': 'Warehouses', 'rows': Warehouse.objects.all(),
        'fields': [('code', 'Code'), ('name', 'Name'), ('address', 'Address')]})


# --- Attributes (shows the dynamic attribute architecture) -----------------
@permission_required('product.manage', 'masterdata.manage')
def attribute_list(request):
    attributes = AttributeDefinition.objects.prefetch_related('options', 'category_bindings__category')
    return render(request, 'masters/attributes.html', {
        'attributes': attributes,
        'bindings': CategoryAttribute.objects.select_related('category', 'attribute'),
        'categories': ItemCategory.objects.all(),
    })


# --- System settings -------------------------------------------------------
@permission_required('config.manage')
def settings_list(request):
    if request.method == 'POST':
        for setting in AppSetting.objects.all():
            key = f'setting_{setting.pk}'
            if key in request.POST:
                setting.value = request.POST[key]
                setting.save(update_fields=['value'])
        messages.success(request, 'Settings saved.')
        return redirect('settings_list')
    return render(request, 'masters/settings.html', {
        'settings': AppSetting.objects.all()})
