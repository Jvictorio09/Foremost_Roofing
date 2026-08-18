"""Enumerations, status maps, and the permission catalog for the Foremost EG ERP.

Status labels and permission codes live here (not scattered through the code) so
they can be reasoned about in one place. Business *values* that change often
(profiles, colors, prices, waste factors, credit rules) are stored as data /
AppSetting rows, never here.
"""
from django.db import models


# ---------------------------------------------------------------------------
# Item / product classification
# ---------------------------------------------------------------------------
class ItemType(models.TextChoices):
    RAW_MATERIAL = 'raw_material', 'Raw Material'
    WIP = 'wip', 'Work in Process'
    FINISHED_GOOD = 'finished_good', 'Finished Good'
    STOCK_RESALE = 'stock_resale', 'Stock / Resale'
    CONSUMABLE = 'consumable', 'Consumable'
    SERVICE = 'service', 'Service'


class AttributeDataType(models.TextChoices):
    TEXT = 'text', 'Text'
    NUMBER = 'number', 'Whole Number'
    DECIMAL = 'decimal', 'Decimal'
    BOOLEAN = 'boolean', 'Yes / No'
    DATE = 'date', 'Date'
    ENUM = 'enum', 'Select (options)'
    UOM_QTY = 'uom_qty', 'Quantity + UoM'
    FILE = 'file', 'File / Attachment'


# ---------------------------------------------------------------------------
# Document status lifecycles
# ---------------------------------------------------------------------------
class QuotationStatus(models.TextChoices):
    DRAFT = 'draft', 'Draft'
    PENDING_APPROVAL = 'pending_approval', 'Pending Approval'
    APPROVED = 'approved', 'Approved'
    SENT = 'sent', 'Sent to Customer'
    ACCEPTED = 'accepted', 'Accepted'
    REJECTED = 'rejected', 'Rejected'
    EXPIRED = 'expired', 'Expired'
    REVISED = 'revised', 'Revised'
    CANCELLED = 'cancelled', 'Cancelled'


class InvoiceStatus(models.TextChoices):
    DRAFT = 'draft', 'Draft'
    PENDING_APPROVAL = 'pending_approval', 'Pending Approval'
    APPROVED = 'approved', 'Approved'
    CANCELLED = 'cancelled', 'Cancelled'
    VOID = 'void', 'Void'


class PaymentState(models.TextChoices):
    UNPAID = 'unpaid', 'Unpaid'
    PARTIAL = 'partial', 'Partially Paid'
    PAID = 'paid', 'Paid'


class JobOrderStatus(models.TextChoices):
    DRAFT = 'draft', 'Draft'
    PENDING_RELEASE = 'pending_release', 'Pending Release'
    RELEASED = 'released', 'Released'
    IN_PROGRESS = 'in_progress', 'In Progress'
    PARTIALLY_COMPLETE = 'partially_complete', 'Partially Complete'
    COMPLETE = 'complete', 'Complete'
    CLOSED = 'closed', 'Closed'
    ON_HOLD = 'on_hold', 'On Hold'
    CANCELLED = 'cancelled', 'Cancelled'


class ReservationStatus(models.TextChoices):
    PENDING = 'pending', 'Pending'
    RESERVED = 'reserved', 'Reserved'
    PARTIALLY_ISSUED = 'partially_issued', 'Partially Issued'
    FULLY_ISSUED = 'fully_issued', 'Fully Issued'
    RELEASED = 'released', 'Released'
    CANCELLED = 'cancelled', 'Cancelled'


class ProductionRunStatus(models.TextChoices):
    PLANNED = 'planned', 'Planned'
    STARTED = 'started', 'Started'
    COMPLETED = 'completed', 'Completed'
    ABORTED = 'aborted', 'Aborted'


class QCResult(models.TextChoices):
    PENDING = 'pending', 'Pending'
    PASS = 'pass', 'Passed'
    HOLD = 'hold', 'On Hold'
    REJECT = 'reject', 'Rejected'


class CoilStatus(models.TextChoices):
    AVAILABLE = 'available', 'Available'
    RESERVED = 'reserved', 'Reserved'
    IN_USE = 'in_use', 'In Use'
    CONSUMED = 'consumed', 'Consumed'
    QUARANTINE = 'quarantine', 'Quarantine'
    REMNANT = 'remnant', 'Remnant'


class FGLotStatus(models.TextChoices):
    AVAILABLE = 'available', 'Available'
    RESERVED = 'reserved', 'Reserved for Delivery'
    SHIPPED = 'shipped', 'Shipped'
    QUARANTINE = 'quarantine', 'Quarantine'


class DeliveryStatus(models.TextChoices):
    DRAFT = 'draft', 'Draft'
    SCHEDULED = 'scheduled', 'Scheduled'
    PICKING = 'picking', 'Picking'
    DISPATCHED = 'dispatched', 'Dispatched'
    DELIVERED = 'delivered', 'Delivered'
    FAILED = 'failed', 'Failed'
    RETURNED = 'returned', 'Returned'


class DrawingStatus(models.TextChoices):
    PENDING = 'pending', 'Pending'
    SUBMITTED = 'submitted', 'Submitted'
    VERIFIED = 'verified', 'Verified'
    REJECTED = 'rejected', 'Rejected'


class InventoryTxnType(models.TextChoices):
    RECEIVE = 'receive', 'Receive'
    TRANSFER = 'transfer', 'Transfer'
    ADJUST = 'adjust', 'Adjustment'
    RESERVE = 'reserve', 'Reserve'
    UNRESERVE = 'unreserve', 'Unreserve'
    ISSUE_PRODUCTION = 'issue_production', 'Issue to Production'
    RETURN_PRODUCTION = 'return_production', 'Return from Production'
    CONSUME = 'consume', 'Consume'
    SCRAP = 'scrap', 'Scrap'
    FG_RECEIPT = 'fg_receipt', 'Finished Goods Receipt'
    DELIVERY_ISSUE = 'delivery_issue', 'Delivery Issue'
    REVERSE = 'reverse', 'Reversal / Void'


class PaymentMethod(models.TextChoices):
    CASH = 'cash', 'Cash'
    BANK_TRANSFER = 'bank', 'Bank Transfer'
    CHECK = 'check', 'Check'
    CARD = 'card', 'Card'
    OTHER = 'other', 'Other'


class PaymentStatus(models.TextChoices):
    PENDING = 'pending', 'Pending'
    VERIFIED = 'verified', 'Verified'
    REJECTED = 'rejected', 'Rejected'


class InvoiceNoteKind(models.TextChoices):
    """Collections / follow-up log entry types for an invoice."""
    NOTE = 'note', 'Note'
    FOLLOW_UP = 'follow_up', 'Follow-up'
    PROMISE = 'promise', 'Promise to Pay'
    DISPUTE = 'dispute', 'Dispute'
    RESOLVED = 'resolved', 'Resolved'


# ---------------------------------------------------------------------------
# UI tone mapping for status badges (keyed by raw status value)
# ---------------------------------------------------------------------------
STATUS_TONE = {
    # Quotation
    'draft': 'gray', 'pending_approval': 'yellow', 'approved': 'blue',
    'sent': 'blue', 'accepted': 'green', 'rejected': 'red',
    'expired': 'gray', 'revised': 'gray', 'cancelled': 'red',
    # Invoice / payment
    'void': 'red', 'unpaid': 'red', 'partial': 'yellow', 'paid': 'green',
    # Job order / production
    'pending_release': 'yellow', 'released': 'blue', 'in_progress': 'blue',
    'partially_complete': 'yellow', 'complete': 'green', 'closed': 'green',
    'on_hold': 'red',
    # Reservation
    'reserved': 'blue', 'partially_issued': 'yellow', 'fully_issued': 'green',
    'pending': 'yellow',
    # Production run
    'planned': 'gray', 'started': 'blue', 'completed': 'green', 'aborted': 'red',
    # Coil
    'available': 'green', 'in_use': 'blue', 'consumed': 'gray',
    'quarantine': 'red', 'remnant': 'yellow',
    # Delivery
    'scheduled': 'blue', 'picking': 'yellow', 'dispatched': 'blue',
    'delivered': 'green', 'failed': 'red', 'returned': 'red',
    # QC / drawing
    'pass': 'green', 'hold': 'yellow', 'reject': 'red',
    'submitted': 'blue', 'verified': 'green',
    # Invoice follow-up notes
    'note': 'gray', 'follow_up': 'yellow', 'promise': 'blue',
    'dispute': 'red', 'resolved': 'green',
}


# ---------------------------------------------------------------------------
# Permission catalog
# ---------------------------------------------------------------------------
# (code, human label, group). Seeded into the Permission table. Roles are
# bundles of these codes; nothing in code checks a hard-coded role name for
# authorization -- always a permission code via rbac.has_perm().
PERMISSION_CATALOG = [
    # Sales / quotation
    ('quotation.view', 'View quotations', 'Sales'),
    ('quotation.create', 'Create quotations', 'Sales'),
    ('quotation.edit', 'Edit quotations', 'Sales'),
    ('quotation.submit', 'Submit quotation for approval', 'Sales'),
    ('quotation.approve', 'Approve quotations', 'Sales'),
    ('quotation.send', 'Send quotation to customer', 'Sales'),
    ('quotation.revise', 'Revise quotations', 'Sales'),
    ('quotation.accept', 'Record customer acceptance', 'Sales'),
    ('quotation.cancel', 'Cancel quotations', 'Sales'),
    # Invoice / billing
    ('invoice.view', 'View invoices', 'Billing'),
    ('invoice.create', 'Create invoices', 'Billing'),
    ('invoice.edit', 'Edit invoices', 'Billing'),
    ('invoice.approve', 'Approve invoices', 'Billing'),
    ('invoice.cancel', 'Cancel / void invoices', 'Billing'),
    ('invoice.release_job_order', 'Release job order from invoice', 'Billing'),
    ('invoice.duplicate_override', 'Override duplicate job order rule', 'Billing'),
    ('payment.view', 'View payments', 'Billing'),
    ('payment.record', 'Record payments', 'Billing'),
    ('credit.override', 'Override credit / payment gate', 'Billing'),
    # Job order
    ('job_order.view', 'View job orders', 'Production'),
    ('job_order.create', 'Create job orders', 'Production'),
    ('job_order.edit', 'Edit job orders', 'Production'),
    ('job_order.release', 'Release job orders to floor', 'Production'),
    ('job_order.hold', 'Place job orders on hold', 'Production'),
    ('job_order.cancel', 'Cancel job orders', 'Production'),
    # Drawings
    ('drawing.upload', 'Upload drawings', 'Production'),
    ('drawing.verify', 'Verify / approve drawings', 'Production'),
    # Inventory
    ('inventory.view', 'View inventory', 'Inventory'),
    ('inventory.receive', 'Receive stock / coils', 'Inventory'),
    ('inventory.reserve', 'Reserve material', 'Inventory'),
    ('inventory.issue', 'Issue material to production', 'Inventory'),
    ('inventory.return', 'Return material from production', 'Inventory'),
    ('inventory.adjust', 'Adjust stock', 'Inventory'),
    ('inventory.transfer', 'Transfer stock between warehouses', 'Inventory'),
    ('inventory.override', 'Override availability / substitution', 'Inventory'),
    # Production
    ('production.view', 'View production', 'Production'),
    ('production.start', 'Start production runs', 'Production'),
    ('production.complete', 'Complete production runs', 'Production'),
    ('production.record_scrap', 'Record scrap / waste', 'Production'),
    # QC
    ('qc.inspect', 'Perform QC inspection', 'Quality'),
    ('qc.release', 'Release QC pass', 'Quality'),
    ('qc.reject', 'Reject in QC', 'Quality'),
    # Delivery
    ('delivery.view', 'View deliveries', 'Logistics'),
    ('delivery.schedule', 'Schedule deliveries', 'Logistics'),
    ('delivery.dispatch', 'Dispatch deliveries', 'Logistics'),
    ('delivery.confirm', 'Confirm delivery / POD', 'Logistics'),
    ('delivery.partial', 'Create partial deliveries', 'Logistics'),
    # Master data
    ('product.manage', 'Manage products / items', 'Master Data'),
    ('bom.manage', 'Manage BOM / formulas', 'Master Data'),
    ('pricelist.manage', 'Manage price lists', 'Master Data'),
    ('masterdata.manage', 'Manage master data', 'Master Data'),
    # Reports
    ('report.sales', 'View sales reports', 'Reports'),
    ('report.production', 'View production reports', 'Reports'),
    ('report.inventory', 'View inventory reports', 'Reports'),
    ('report.management', 'View management reports', 'Reports'),
    ('ai.chat', 'Use AI Analyst', 'Reports'),
    # Administration
    ('user.manage', 'Manage users', 'Administration'),
    ('role.manage', 'Manage roles & permissions', 'Administration'),
    ('config.manage', 'Manage system configuration', 'Administration'),
]

# Convenience groupings used when seeding default roles.
_SALES = [c for c, _, g in PERMISSION_CATALOG if g == 'Sales' or c in ('customer.view',)]
_BILLING = [c for c, _, g in PERMISSION_CATALOG if g == 'Billing']
_INVENTORY = [c for c, _, g in PERMISSION_CATALOG if g == 'Inventory']
_PRODUCTION = [c for c, _, g in PERMISSION_CATALOG if g == 'Production']
_QUALITY = [c for c, _, g in PERMISSION_CATALOG if g == 'Quality']
_LOGISTICS = [c for c, _, g in PERMISSION_CATALOG if g == 'Logistics']
_MASTER = [c for c, _, g in PERMISSION_CATALOG if g == 'Master Data']
_REPORTS = [c for c, _, g in PERMISSION_CATALOG if g == 'Reports']
_ADMIN = [c for c, _, g in PERMISSION_CATALOG if g == 'Administration']

# Default seed roles -> permission codes. Editable at runtime via role.manage;
# this is only the starting point, not an authorization source of truth.
DEFAULT_ROLES = {
    'Super Admin': [c for c, _, _ in PERMISSION_CATALOG],
    'Sales': _SALES + ['quotation.view', 'report.sales'],
    'Sales Approver': _SALES + ['report.sales'],
    'Billing': _BILLING + ['quotation.view', 'report.sales'],
    'Credit / AR': ['invoice.view', 'payment.view', 'payment.record',
                    'credit.override', 'report.sales'],
    'Inventory Clerk': _INVENTORY + ['job_order.view', 'report.inventory'],
    'Warehouse Supervisor': _INVENTORY + ['job_order.view', 'inventory.override',
                                          'report.inventory'],
    'Production Operator': ['job_order.view', 'production.view', 'production.start',
                            'production.complete', 'production.record_scrap',
                            'drawing.upload'],
    'Production Supervisor': _PRODUCTION + ['job_order.view', 'job_order.release',
                                            'job_order.hold', 'drawing.verify',
                                            'report.production'],
    'QC': _QUALITY + ['production.view', 'job_order.view'],
    'Logistics': _LOGISTICS + ['job_order.view', 'inventory.view'],
    'Management Viewer': _REPORTS + ['quotation.view', 'invoice.view',
                                     'job_order.view', 'inventory.view',
                                     'delivery.view', 'ai.chat'],
    'Master Data Admin': _MASTER + ['config.manage'],
}


# ---------------------------------------------------------------------------
# Default system configuration (AppSetting). These answer the open Section-T
# business questions with safe, changeable defaults instead of hard-coding.
# ---------------------------------------------------------------------------
APP_SETTING_DEFAULTS = {
    # Credit gate: 'none' | 'deposit' | 'full' -- may production start before pay?
    'credit.gate_mode': ('deposit', 'Credit gate before job order release'),
    'credit.deposit_pct': ('50', 'Required deposit percentage when gate = deposit'),
    # Finished goods: always post MTO output to FG before delivery.
    'fg.always_post': ('true', 'Post made-to-order output to Finished Goods'),
    # Maker-checker: a maker cannot approve their own document.
    'approval.maker_checker': ('true', 'Enforce maker-checker on approvals'),
    # Default trim/setup waste percent used by material estimates when a
    # profile does not define its own.
    'material.default_waste_pct': ('5', 'Default trim/setup waste percent'),
    # Remnant: coils cut below this remaining length (m) become a REMNANT lot.
    'coil.remnant_threshold_m': ('3', 'Remnant threshold in linear meters'),
    # Overproduction tolerance percent allowed without supervisor override.
    'production.overproduction_tolerance_pct': ('2', 'Overproduction tolerance percent'),
    # Quotation validity default (days).
    'quotation.default_validity_days': ('30', 'Default quotation validity in days'),
    # How long (minutes) a user may edit/delete their own invoice follow-up note.
    'invoice.note_edit_window_min': ('15', 'Minutes to edit/delete own invoice note'),
    # Company details for printed documents.
    'company.name': ('FOREMOST EG METAL CORP.', 'Company legal name'),
    'company.tagline': ('Ever Glory', 'Brand / tagline shown with the logo'),
    'company.address': ('Leviste Highway, Brgy. Bulacnin, Lipa City, Batangas',
                        'Company address'),
    'company.tin': ('009-300-990-000', 'VAT Registration TIN'),
    'company.contact': ("0933-860-8182 / 0956-251-7865", 'Contact numbers'),
    'company.email': ('jangeles.online.feg@gmail.com', 'Company email address'),
    'company.bank1': ('BDO Lima Park Branch \u2014 010748001029',
                      'Primary bank account for payments'),
    'company.bank2': ('Metro Bank Lima Park Branch \u2014 892-7-89200170-3',
                      'Secondary bank account for payments'),
    'company.sales_rep': ('Janet T. Cuevas', 'Default sales representative on quotations'),
    # Quotation printed terms (one per line).
    'quotation.print_terms': (
        'STRICTLY NO CANCELLATION OF ORDERS ONCE QUOTATION IS CONFORMED\n'
        '50% DOWN PAYMENT, FULL PAYMENT UPON DELIVERY / PICK UP\n'
        'LEAD TIME 3-5 WORKING DAYS UPON CLEARING OF PAYMENTS\n'
        'QUOTATION VALID FOR 7 DAYS',
        'Terms printed on the sales quotation'),
    'tax.default_rate_pct': ('12', 'Default VAT rate percent'),
}
