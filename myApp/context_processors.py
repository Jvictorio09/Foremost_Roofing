"""Sidebar + permission context. Navigation is filtered by permission codes, so
the Super Admin (who holds every permission) sees and can operate every module,
while each department sees only what its role grants."""
from .rbac import has_any


# (label, url_name, icon, [permission codes that reveal the link])
NAV = [
    ('Dashboard', 'dashboard', 'home', None),
    ('Quotations', 'quotation_list', 'file', ['quotation.view', 'quotation.create']),
    ('Invoices', 'invoice_list', 'wallet', ['invoice.view', 'invoice.create']),
    ('Job Orders', 'job_order_list', 'clipboard', ['job_order.view']),
    ('Production', 'production_list', 'hammer', ['production.view']),
    ('Inventory', 'coil_list', 'box', ['inventory.view']),
    ('Deliveries', 'delivery_list', 'truck', ['delivery.view']),
    ('Customers', 'customer_list', 'users', ['quotation.view', 'masterdata.manage', 'invoice.view']),
    ('Master Data', 'master_hub', 'shield', ['masterdata.manage', 'product.manage', 'pricelist.manage']),
    ('Reports', 'report_hub', 'chart', ['report.sales', 'report.production',
                                        'report.inventory', 'report.management']),
    ('AI Analyst', 'ai_analyst', 'spark', ['ai.chat']),
    ('Users & Roles', 'user_list', 'lock', ['user.manage', 'role.manage']),
]


def sidebar_context(request):
    user = getattr(request, 'user', None)
    if not user or not user.is_authenticated:
        return {'sidebar_links': []}
    links = []
    for label, url_name, icon, perms in NAV:
        if perms is None or has_any(user, *perms):
            links.append({'label': label, 'url_name': url_name, 'icon': icon})
    return {'sidebar_links': links, 'role_label': user.role_label()}
