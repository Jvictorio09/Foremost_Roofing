"""Print-ready document views. Each renders a standalone A4 page that mirrors
Foremost EG's official paper forms (Sales Quotation, Invoice, Delivery Receipt,
Job Order). The layouts live under templates/print/."""
from decimal import Decimal

from django.shortcuts import get_object_or_404, render

from ..models import Delivery, Invoice, JobOrder, Quotation, StandardDrawing
from ..rbac import permission_required
from .common import company_info

ZERO = Decimal('0')

# Roman-numbered sections on the sales quotation, mapped to item-category codes.
QUOTATION_SECTIONS = [
    ('I. Panel', {'ROOF', 'DECK', 'SPANDREL'}),
    ('II. Bended Accessories', {'BENDED'}),
    ('III. Hardware Accessories', {'HARDWARE', 'INSULATION'}),
]


def _auto(request):
    """Trigger the browser print dialog automatically unless ?auto=0."""
    return request.GET.get('auto', '1') != '0'


def _filler(count, minimum=8):
    """Blank rows so short documents keep the paper form's ruled look."""
    return range(max(0, minimum - count))


def _group_quotation_lines(lines):
    """Split quotation lines into the Panel / Bended / Hardware sections used on
    the printed form, keyed off each line item's category code."""
    buckets = [(title, codes, []) for title, codes in QUOTATION_SECTIONS]
    other = []
    for line in lines:
        code = getattr(getattr(line.item, 'category', None), 'code', None)
        for _title, codes, bucket in buckets:
            if code in codes:
                bucket.append(line)
                break
        else:
            other.append(line)
    sections = [
        {'title': title, 'lines': bucket,
         'subtotal': sum((l.line_total for l in bucket), ZERO)}
        for title, _codes, bucket in buckets if bucket
    ]
    if other:
        sections.append({'title': 'IV. Other Items', 'lines': other,
                         'subtotal': sum((l.line_total for l in other), ZERO)})
    return sections


def _line_drawings(lines):
    """Collect the reference drawings used across a set of lines for the diagram
    band on the printed quotation. Uploaded/library images are deduplicated by
    URL; lines with no image fall back to their generated bend profile (SVG)."""
    seen, drawings = set(), []
    for line in lines:
        url = line.drawing_image_url
        if url:
            if url in seen:
                continue
            seen.add(url)
            drawings.append({'url': url, 'caption': line.drawing_caption or line.description,
                             'girth': (line.standard_drawing.default_girth
                                       if line.standard_drawing_id else '')})
        elif line.has_generated_drawing:
            drawings.append({'svg': line.profile_svg, 'caption': line.description,
                             'girth': line.profile_girth_label})
    return drawings


_IMG_EXTS = ('.png', '.jpg', '.jpeg', '.gif', '.webp', '.svg')


def _job_order_drawings(lines):
    """Reference drawings for a job order's diagram band. Per line we resolve, in
    order: an uploaded image attachment, the generated bend profile (SVG) carried
    over via ``specs_json``, or the standard drawing referenced on the original
    quotation (its FK isn't copied onto the JO line, but ``sync_quotation_line_
    derived`` caches ``drawing_id`` inside ``specs_json`` so we can re-resolve it)."""
    # Bulk-load any standard drawings referenced by cached id to avoid N+1.
    ids = {(l.specs_json or {}).get('drawing_id') for l in lines}
    ids.discard(None)
    lib = {d.pk: d for d in StandardDrawing.objects.filter(pk__in=ids)}

    seen, drawings = set(), []
    for line in lines:
        image_url = None
        for att in line.drawings.all():
            url = att.file.url if att.file else ''
            if url.lower().endswith(_IMG_EXTS):
                image_url = url
                break
        girth = line.profile_girth_label
        if not image_url:
            sd = lib.get((line.specs_json or {}).get('drawing_id'))
            if sd and sd.image:
                image_url = sd.image.url
                girth = girth or sd.default_girth
        if image_url:
            if image_url in seen:
                continue
            seen.add(image_url)
            drawings.append({'url': image_url, 'caption': line.description, 'girth': girth})
        elif line.profile_svg:
            drawings.append({'svg': line.profile_svg, 'caption': line.description,
                             'girth': line.profile_girth_label})
    return drawings


@permission_required('quotation.view', 'quotation.create')
def quotation_print(request, pk):
    q = get_object_or_404(
        Quotation.objects.select_related('customer', 'salesperson', 'tax_code'), pk=pk)
    lines = list(q.lines.select_related('item__category', 'standard_drawing').all())
    return render(request, 'print/quotation.html', {
        'q': q, 'sections': _group_quotation_lines(lines),
        'filler': _filler(len(lines)),
        'drawings': _line_drawings(lines),
        'company': company_info(), 'auto_print': _auto(request),
    })


@permission_required('invoice.view', 'invoice.create')
def invoice_print(request, pk):
    inv = get_object_or_404(
        Invoice.objects.select_related('customer', 'payment_term', 'tax_code'), pk=pk)
    lines = list(inv.lines.all())
    return render(request, 'print/invoice.html', {
        'inv': inv, 'lines': lines, 'filler': _filler(len(lines)),
        'net': inv.subtotal - inv.discount,
        'company': company_info(), 'auto_print': _auto(request),
    })


@permission_required('delivery.view')
def delivery_print(request, pk):
    delivery = get_object_or_404(
        Delivery.objects.select_related('customer', 'job_order'), pk=pk)
    lines = list(delivery.lines.select_related('fg_lot', 'item').all())
    return render(request, 'print/delivery_receipt.html', {
        'delivery': delivery, 'lines': lines, 'filler': _filler(len(lines)),
        'company': company_info(), 'auto_print': _auto(request),
    })


@permission_required('job_order.view')
def job_order_print(request, pk):
    jo = get_object_or_404(
        JobOrder.objects.select_related('customer', 'invoice'), pk=pk)
    lines = list(jo.lines.prefetch_related('drawings').all())
    return render(request, 'print/job_order.html', {
        'jo': jo, 'lines': lines, 'filler': _filler(len(lines)),
        'drawings': _job_order_drawings(lines),
        'company': company_info(), 'auto_print': _auto(request),
    })
