from django.contrib import messages
from django.contrib.auth import login
from django.shortcuts import redirect, render
from django.utils.http import url_has_allowed_host_and_scheme

from .forms import RegistroForm
from .models import AutorizacionDatos, registrar_autorizacion


def registro(request):
    if request.user.is_authenticated:
        return redirect("dashboard")

    siguiente = request.POST.get("next") or request.GET.get("next") or ""
    if not url_has_allowed_host_and_scheme(siguiente, allowed_hosts={request.get_host()}):
        siguiente = ""

    form = RegistroForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        usuario = form.save()
        registrar_autorizacion(AutorizacionDatos.ORIGEN_REGISTRO, usuario=usuario)
        login(request, usuario, backend="django.contrib.auth.backends.ModelBackend")
        messages.success(request, "Tu cuenta fue creada. ¡Bienvenido a Tío Campo!")
        return redirect(siguiente or "dashboard")

    return render(request, "seguridad/registro.html", {"form": form, "next": siguiente})
