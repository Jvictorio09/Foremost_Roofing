"""Permission-based access control.

Authorization always resolves to a permission *code* (e.g. ``quotation.approve``),
never a hard-coded role name. Super Admin / Django superuser bypasses all checks,
which is how the Super Admin can operate any department's screens.
"""
from functools import wraps

from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied


def has_perm(user, code):
    if not user or not user.is_authenticated:
        return False
    return user.has_perm_code(code)


def has_any(user, *codes):
    return any(has_perm(user, c) for c in codes)


def permission_required(*codes):
    """View decorator -- user must hold at least one of the given permission codes."""
    def decorator(view):
        @wraps(view)
        @login_required
        def _wrapped(request, *args, **kwargs):
            if has_any(request.user, *codes):
                return view(request, *args, **kwargs)
            raise PermissionDenied('You do not have permission for this action.')
        return _wrapped
    return decorator
