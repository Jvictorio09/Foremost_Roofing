"""Backwards-compatible shim -- authorization now lives in rbac.py."""
from .rbac import has_any, has_perm, permission_required  # noqa: F401
