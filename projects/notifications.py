"""
projects/notifications.py
════════════════════════════════════════════════════════════════
Crea las notificaciones que aparecen en la campana de la página.

Privacidad: el texto de una notificación NUNCA incluye la descripción
del reporte ni datos personales; solo el número de caso, el nivel y
el tipo de evento (las notificaciones pueden verse en pantallas
compartidas o bloqueadas).
"""
from django.contrib.auth.models import User
from django.db.models import Q

from .models import Notificacion

# Mismo criterio que views._is_admin: staff o el usuario administrador histórico
ADMIN_USERNAMES = ('recemilian79',)

ETIQUETA_NIVEL = {'critico': 'CRÍTICO', 'alto': 'ALTO', 'medio': 'Medio', 'bajo': 'Bajo'}


def usuarios_admin():
    return User.objects.filter(
        Q(is_staff=True) | Q(username__in=ADMIN_USERNAMES), is_active=True
    )


def notificar(usuario, titulo, mensaje='', tipo='sistema', reporte=None, nivel=''):
    if usuario is None:
        return None
    return Notificacion.objects.create(
        usuario=usuario, titulo=titulo[:200], mensaje=mensaje[:300],
        tipo=tipo, reporte=reporte, nivel=nivel,
    )


def notificar_admins(titulo, mensaje='', tipo='sistema', reporte=None, nivel='', excluir=None):
    destinatarios = usuarios_admin()
    if excluir is not None:
        destinatarios = destinatarios.exclude(pk=getattr(excluir, 'pk', excluir))
    Notificacion.objects.bulk_create([
        Notificacion(usuario=u, titulo=titulo[:200], mensaje=mensaje[:300],
                     tipo=tipo, reporte=reporte, nivel=nivel)
        for u in destinatarios
    ])


# ── Eventos concretos ────────────────────────────────────────────────

def notificar_reporte_nuevo(reporte):
    nivel = reporte.nivel_urgencia
    icono = '🚨 ' if nivel == 'critico' or reporte.llamar_911 else ''
    notificar_admins(
        titulo=f'{icono}Nuevo reporte #{reporte.pk} · {ETIQUETA_NIVEL.get(nivel, nivel)}',
        mensaje='Solicitó contacto urgente.' if reporte.llamar_911 else 'Pendiente de revisión.',
        tipo='reporte_nuevo', reporte=reporte, nivel=nivel,
        excluir=reporte.user,
    )


def notificar_cambio_estado(reporte, actor):
    if reporte.user_id and reporte.user_id != getattr(actor, 'pk', None):
        notificar(
            reporte.user,
            titulo=f'Tu reporte #{reporte.pk} cambió de estado',
            mensaje=f'Ahora está: {reporte.get_status_display()}.',
            tipo='estado', reporte=reporte, nivel=reporte.nivel_urgencia,
        )


def notificar_cambio_nivel(reporte, actor):
    notificar_admins(
        titulo=f'Reporte #{reporte.pk}: nivel actualizado a {ETIQUETA_NIVEL.get(reporte.nivel_urgencia)}',
        tipo='nivel', reporte=reporte, nivel=reporte.nivel_urgencia, excluir=actor,
    )


def notificar_mensaje(reporte, autor, es_del_admin):
    if es_del_admin:
        notificar(
            reporte.user,
            titulo=f'Nuevo mensaje del equipo en tu reporte #{reporte.pk}',
            mensaje='Abre el reporte para leerlo.',
            tipo='mensaje', reporte=reporte, nivel=reporte.nivel_urgencia,
        )
    else:
        notificar_admins(
            titulo=f'Nuevo mensaje en el reporte #{reporte.pk}',
            mensaje='La persona respondió.',
            tipo='mensaje', reporte=reporte, nivel=reporte.nivel_urgencia, excluir=autor,
        )
