"""Seed RBAC roles/permissions and the standard staff logins.

Runs during ``migrate`` (including Railway's pre-deploy step), so a fresh
production database gets working accounts without a manual shell command.
Idempotent: existing users keep their current password; only accounts without a
usable password are (re)set to ``password123``.
"""
from django.contrib.auth.hashers import make_password
from django.db import migrations


TEAM = [
    ('sales', 'Sofia', 'Sales', ['Sales']),
    ('billing', 'Bella', 'Billing', ['Billing']),
    ('inventory', 'Ivan', 'Inventory', ['Inventory Clerk', 'Warehouse Supervisor']),
    ('production', 'Pedro', 'Production',
     ['Production Supervisor', 'Production Operator']),
    ('logistics', 'Lito', 'Logistics', ['Logistics']),
    ('manager', 'Manny', 'Manager', ['Management Viewer', 'Sales Approver']),
]


def seed_accounts(apps, schema_editor):
    from myApp import constants as C

    Permission = apps.get_model('myApp', 'Permission')
    Role = apps.get_model('myApp', 'Role')
    User = apps.get_model('myApp', 'User')

    # Permissions + roles from the catalog so RBAC works out of the box.
    for code, label, group in C.PERMISSION_CATALOG:
        Permission.objects.update_or_create(
            code=code, defaults={'label': label, 'group': group})

    roles = {}
    for name, codes in C.DEFAULT_ROLES.items():
        role, _ = Role.objects.get_or_create(
            name=name, defaults={'is_system': name == 'Super Admin'})
        role.permissions.set(Permission.objects.filter(code__in=codes))
        roles[name] = role

    pw = make_password('password123')

    # Super admin.
    admin, _ = User.objects.get_or_create(
        username='admin',
        defaults={'email': 'admin@foremosteg.com', 'first_name': 'Admin',
                  'last_name': 'User', 'is_staff': True, 'is_superuser': True,
                  'is_active': True, 'password': pw})
    changed = False
    if not admin.is_superuser:
        admin.is_superuser = True; changed = True
    if not admin.is_staff:
        admin.is_staff = True; changed = True
    if not admin.password or not admin.password.startswith(('pbkdf2', 'argon2', 'bcrypt')):
        admin.password = pw; changed = True
    if changed:
        admin.save()
    if 'Super Admin' in roles:
        admin.roles.set([roles['Super Admin']])

    # Team logins.
    for username, first, last, role_names in TEAM:
        user, created = User.objects.get_or_create(
            username=username,
            defaults={'email': f'{username}@foremosteg.com', 'first_name': first,
                      'last_name': last, 'is_active': True, 'password': pw})
        if not created and not user.password.startswith(('pbkdf2', 'argon2', 'bcrypt')):
            user.password = pw
            user.save()
        user.roles.set([roles[r] for r in role_names if r in roles])


def unseed(apps, schema_editor):
    # Keep accounts on reverse; nothing to undo safely.
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('myApp', '0007_aiconversation_aimessage_and_more'),
    ]

    operations = [
        migrations.RunPython(seed_accounts, unseed),
    ]
