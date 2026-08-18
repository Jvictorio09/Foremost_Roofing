from django.contrib import messages
from django.contrib.auth import get_user_model
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render

from ..forms import RoleForm, UserForm
from ..models import Permission, Role
from ..rbac import permission_required
from .common import is_hx

User = get_user_model()


def _hx_saved():
    """Close the modal and reload the underlying list."""
    resp = HttpResponse(status=204)
    resp['HX-Refresh'] = 'true'
    return resp


@permission_required('user.manage', 'role.manage')
def user_list(request):
    return render(request, 'admin/user_list.html', {
        'users': User.objects.prefetch_related('roles').all(),
        'roles': Role.objects.all(),
    })


@permission_required('user.manage')
def user_create(request):
    hx = is_hx(request)
    if request.method == 'POST':
        form = UserForm(request.POST)
        if form.is_valid():
            user = form.save(commit=False)
            user.set_password(request.POST.get('password') or 'password123')
            user.save()
            form.save_m2m()
            messages.success(request, f'User {user.username} created (default password if none set).')
            return _hx_saved() if hx else redirect('user_list')
    else:
        form = UserForm()
    template = 'admin/_user_form_modal.html' if hx else 'admin/user_form.html'
    return render(request, template, {'form': form, 'title': 'New User',
                                      'creating': True, 'form_action': request.path})


@permission_required('user.manage')
def user_edit(request, pk):
    user = get_object_or_404(User, pk=pk)
    hx = is_hx(request)
    if request.method == 'POST':
        form = UserForm(request.POST, instance=user)
        if form.is_valid():
            form.save()
            if request.POST.get('password'):
                user.set_password(request.POST['password'])
                user.save()
            messages.success(request, 'User updated.')
            return _hx_saved() if hx else redirect('user_list')
    else:
        form = UserForm(instance=user)
    template = 'admin/_user_form_modal.html' if hx else 'admin/user_form.html'
    return render(request, template, {'form': form, 'title': f'Edit {user.username}',
                                      'creating': False, 'form_action': request.path})


@permission_required('role.manage')
def role_list(request):
    roles = Role.objects.prefetch_related('permissions').all()
    return render(request, 'admin/role_list.html', {
        'roles': roles,
        'perm_total': Permission.objects.count(),
    })


@permission_required('role.manage')
def role_create(request):
    hx = is_hx(request)
    if request.method == 'POST':
        form = RoleForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, 'Role created.')
            return _hx_saved() if hx else redirect('role_list')
    else:
        form = RoleForm()
    template = 'admin/_role_form_modal.html' if hx else 'admin/role_form.html'
    return render(request, template, {'form': form, 'title': 'New Role',
                                      'form_action': request.path})


@permission_required('role.manage')
def role_edit(request, pk):
    role = get_object_or_404(Role, pk=pk)
    hx = is_hx(request)
    if request.method == 'POST':
        form = RoleForm(request.POST, instance=role)
        if form.is_valid():
            form.save()
            messages.success(request, 'Role updated.')
            return _hx_saved() if hx else redirect('role_list')
    else:
        form = RoleForm(instance=role)
    template = 'admin/_role_form_modal.html' if hx else 'admin/role_form.html'
    return render(request, template, {'form': form, 'title': f'Edit {role.name}',
                                      'role': role, 'form_action': request.path})
