from decimal import Decimal

from django.core.paginator import Paginator
from django.shortcuts import render
from django.urls import reverse

from .. import constants as C
from .. import services


def money(value):
    if value is None:
        return '0.00'
    return f'{Decimal(value):,.2f}'


def company_info():
    """Company letterhead details for printed documents. Values come from
    AppSetting (editable in Master Data > System Settings) and fall back to the
    seeded defaults so printing works out of the box."""
    def _s(key):
        default = C.APP_SETTING_DEFAULTS.get(key, ('', ''))[0]
        return services.get_setting(key, default)

    return {
        'name': _s('company.name'),
        'tagline': _s('company.tagline'),
        'address': _s('company.address'),
        'tin': _s('company.tin'),
        'contact': _s('company.contact'),
        'email': _s('company.email'),
        'bank1': _s('company.bank1'),
        'bank2': _s('company.bank2'),
        'sales_rep': _s('company.sales_rep'),
        'quotation_terms': [
            line for line in _s('quotation.print_terms').splitlines() if line.strip()],
    }


def paginate(request, queryset, per_page=25):
    paginator = Paginator(queryset, per_page)
    return paginator.get_page(request.GET.get('page'))


def is_hx(request):
    """True when the request was made by htmx (used to render modal partials)."""
    return request.headers.get('HX-Request') == 'true'


def render_detail(request, *, page_template, body_template, context,
                  title, full_url_name, pk):
    """Render a detail view either as a full page or, for htmx requests, as a
    modal overlay wrapping the same body partial. This lets list rows and
    cross-links open records in a modal without leaving the current page."""
    if is_hx(request):
        modal_ctx = dict(context)
        modal_ctx.update({
            'modal_title': title,
            'body_template': body_template,
            'full_url': reverse(full_url_name, args=[pk]),
        })
        return render(request, 'partials/modal.html', modal_ctx)
    return render(request, page_template, context)
