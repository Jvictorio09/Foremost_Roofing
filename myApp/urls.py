from django.contrib.auth.views import LogoutView
from django.urls import path

from . import views

urlpatterns = [
    path('', views.root_redirect, name='root'),
    path('login/', views.LoginView.as_view(), name='login'),
    path('logout/', LogoutView.as_view(), name='logout'),
    path('dashboard/', views.dashboard, name='dashboard'),
    path('dashboard/panel/', views.dashboard_panel, name='dashboard_panel'),
    path('search/', views.global_search, name='global_search'),

    # Quotations
    path('quotations/', views.quotation_list, name='quotation_list'),
    path('quotations/new/', views.quotation_create, name='quotation_create'),
    path('quotations/<int:pk>/', views.quotation_detail, name='quotation_detail'),
    path('quotations/<int:pk>/print/', views.quotation_print, name='quotation_print'),
    path('quotations/<int:pk>/edit/', views.quotation_edit, name='quotation_edit'),
    path('quotations/<int:pk>/submit/', views.quotation_submit, name='quotation_submit'),
    path('quotations/<int:pk>/approve/', views.quotation_approve, name='quotation_approve'),
    path('quotations/<int:pk>/send/', views.quotation_send, name='quotation_send'),
    path('quotations/<int:pk>/accept/', views.quotation_accept, name='quotation_accept'),
    path('quotations/<int:pk>/revise/', views.quotation_revise, name='quotation_revise'),
    path('quotations/<int:pk>/cancel/', views.quotation_cancel, name='quotation_cancel'),
    path('quotations/<int:pk>/invoice/', views.invoice_create_from_quotation,
         name='invoice_create_from_quotation'),

    # Invoices
    path('invoices/', views.invoice_list, name='invoice_list'),
    path('invoices/<int:pk>/', views.invoice_detail, name='invoice_detail'),
    path('invoices/<int:pk>/print/', views.invoice_print, name='invoice_print'),
    path('invoices/<int:pk>/approve/', views.invoice_approve, name='invoice_approve'),
    path('invoices/<int:pk>/job-order/', views.invoice_create_job_order,
         name='invoice_create_job_order'),
    path('invoices/<int:pk>/payment/', views.invoice_record_payment, name='invoice_record_payment'),
    path('invoices/<int:pk>/note/', views.invoice_add_note, name='invoice_add_note'),
    path('invoice-notes/<int:pk>/edit/', views.invoice_note_edit, name='invoice_note_edit'),
    path('invoice-notes/<int:pk>/delete/', views.invoice_note_delete, name='invoice_note_delete'),

    # Job orders
    path('job-orders/', views.job_order_list, name='job_order_list'),
    path('job-orders/<int:pk>/', views.job_order_detail, name='job_order_detail'),
    path('job-orders/<int:pk>/print/', views.job_order_print, name='job_order_print'),
    path('job-orders/<int:pk>/release/', views.job_order_release, name='job_order_release'),
    path('job-orders/<int:pk>/hold/', views.job_order_hold, name='job_order_hold'),
    path('job-orders/<int:pk>/cancel/', views.job_order_cancel, name='job_order_cancel'),
    path('job-order-lines/<int:line_pk>/drawing/', views.drawing_upload, name='drawing_upload'),
    path('drawings/<int:pk>/verify/', views.drawing_verify, name='drawing_verify'),

    # Inventory
    path('inventory/coils/', views.coil_list, name='coil_list'),
    path('inventory/coils/new/', views.coil_create, name='coil_create'),
    path('inventory/coils/<int:pk>/', views.coil_detail, name='coil_detail'),
    path('inventory/ledger/', views.inventory_ledger, name='inventory_ledger'),
    path('inventory/balances/', views.stock_balances, name='stock_balances'),
    path('inventory/reservation-lines/<int:line_pk>/issue/', views.issue_material,
         name='issue_material'),

    # Production
    path('production/', views.production_list, name='production_list'),
    path('production/new/', views.production_run_create, name='production_run_create'),
    path('production/<int:pk>/', views.production_run_detail, name='production_run_detail'),
    path('production/<int:pk>/complete/', views.production_run_complete,
         name='production_run_complete'),

    # Deliveries
    path('deliveries/', views.delivery_list, name='delivery_list'),
    path('deliveries/new/', views.delivery_create, name='delivery_create'),
    path('deliveries/<int:pk>/', views.delivery_detail, name='delivery_detail'),
    path('deliveries/<int:pk>/print/', views.delivery_print, name='delivery_print'),
    path('deliveries/<int:pk>/add-line/', views.delivery_add_line, name='delivery_add_line'),
    path('deliveries/<int:pk>/dispatch/', views.delivery_dispatch, name='delivery_dispatch'),
    path('deliveries/<int:pk>/confirm/', views.delivery_confirm, name='delivery_confirm'),

    # Master data
    path('masters/', views.master_hub, name='master_hub'),
    path('masters/customers/', views.customer_list, name='customer_list'),
    path('masters/customers/new/', views.customer_create, name='customer_create'),
    path('masters/customers/quick-new/', views.customer_quick_create, name='customer_quick_create'),
    path('masters/customers/<int:pk>/edit/', views.customer_edit, name='customer_edit'),
    path('masters/suppliers/', views.supplier_list, name='supplier_list'),
    path('masters/suppliers/new/', views.supplier_create, name='supplier_create'),
    path('masters/suppliers/<int:pk>/edit/', views.supplier_edit, name='supplier_edit'),
    path('masters/items/', views.item_list, name='item_list'),
    path('masters/items/new/', views.item_create, name='item_create'),
    path('masters/items/<int:pk>/edit/', views.item_edit, name='item_edit'),
    path('masters/profiles/', views.profile_list, name='profile_list'),
    path('masters/profiles/new/', views.profile_create, name='profile_create'),
    path('masters/profiles/<int:pk>/edit/', views.profile_edit, name='profile_edit'),
    path('masters/colors/', views.color_list, name='color_list'),
    path('masters/colors/new/', views.color_create, name='color_create'),
    path('masters/colors/<int:pk>/edit/', views.color_edit, name='color_edit'),
    path('masters/drawings/', views.drawing_list, name='drawing_list'),
    path('masters/drawings/new/', views.drawing_create, name='drawing_create'),
    path('masters/drawings/quick-new/', views.drawing_quick_create, name='drawing_quick_create'),
    path('masters/drawings/<int:pk>/edit/', views.drawing_edit, name='drawing_edit'),
    path('masters/machines/', views.machine_list, name='machine_list'),
    path('masters/machines/new/', views.machine_create, name='machine_create'),
    path('masters/machines/<int:pk>/edit/', views.machine_edit, name='machine_edit'),
    path('masters/warehouses/', views.warehouse_list, name='warehouse_list'),
    path('masters/attributes/', views.attribute_list, name='attribute_list'),
    path('masters/settings/', views.settings_list, name='settings_list'),

    # Reports
    path('reports/', views.report_hub, name='report_hub'),
    path('reports/sales/', views.report_sales, name='report_sales'),
    path('reports/production/', views.report_production, name='report_production'),
    path('reports/inventory/', views.report_inventory, name='report_inventory'),
    path('reports/management/', views.report_management, name='report_management'),

    # AI Analyst
    path('ai/', views.ai_analyst, name='ai_analyst'),
    path('ai/conversations/new/', views.ai_conversation_create, name='ai_conversation_create'),
    path('ai/conversations/<int:pk>/', views.ai_conversation, name='ai_conversation'),
    path('ai/conversations/<int:pk>/messages/', views.ai_message_send, name='ai_message_send'),
    path('ai/conversations/<int:pk>/delete/', views.ai_conversation_delete,
         name='ai_conversation_delete'),

    # Users & roles
    path('admin/users/', views.user_list, name='user_list'),
    path('admin/users/new/', views.user_create, name='user_create'),
    path('admin/users/<int:pk>/edit/', views.user_edit, name='user_edit'),
    path('admin/roles/', views.role_list, name='role_list'),
    path('admin/roles/new/', views.role_create, name='role_create'),
    path('admin/roles/<int:pk>/edit/', views.role_edit, name='role_edit'),
]
