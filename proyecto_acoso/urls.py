from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static
from projects.pwa_views import service_worker, manifest, offline   # ← AGREGAR ESTA

urlpatterns = [
    path('service-worker.js', service_worker, name='service-worker'),
    path('manifest.json',     manifest,       name='manifest'),
    path('offline/',          offline,         name='offline'),
    path('admin/', admin.site.urls),
    path('accounts/', include('accounts.urls')),

    # ── Tu app de cuentas PRIMERO ──────────────────────────────
    # Así login/ y register/ apuntan a tu vista combinada,
    # no a la de Django por defecto.
    path('accounts/', include('accounts.urls')),

    # ── URLs de Django Auth para logout y reset de contraseña ──
    # logout/ viene de aquí. El login/ de Django queda opacado
    # por el de arriba (se resuelve el primero que coincide).
    path('accounts/', include('django.contrib.auth.urls')),

    # ── Sentinel AI ────────────────────────────────────────────
    path('ai/', include('projects.ai_urls')),

    # ── Proyecto principal ──────────────────────────────────────
    path('', include('projects.urls')),
]