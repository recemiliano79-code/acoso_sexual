# ══════════════════════════════════════════════════════════════════
#  projects/views.py  — VERSIÓN COMPLETA v2
# ══════════════════════════════════════════════════════════════════

from django.urls import reverse, reverse_lazy
from django.views.generic import (
    ListView, CreateView, UpdateView, DeleteView, TemplateView, DetailView
)
from django.views import View
from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
from django.contrib.auth.models import User
from django.shortcuts import get_object_or_404, redirect, render
from django.contrib import messages
from django.utils import timezone
from django.utils.timesince import timesince
from django.http import JsonResponse
from django.db.models import Case, When, Value, IntegerField, Count, Max, Q
import json
from datetime import datetime, time, timedelta
from .models import Tip, TipoAcoso, Institucion, Reporte, Sugerencia, MensajeAdmin, Notificacion
from .forms import TipForm, TipoAcosoForm, InstitucionForm, ReporteForm
from .risk import calcular_riesgo, resumen_motivos, PISO_PUNTAJE, ETIQUETA
from .notifications import (
    notificar_reporte_nuevo, notificar_cambio_estado, notificar_cambio_nivel, notificar_mensaje,
)


# ── Helpers ───────────────────────────────────────────────────────
def _is_admin(user):
    return user.is_staff or user.username == 'recemilian79'


# ── Orden por grado de riesgo ─────────────────────────────────────
_ORDEN_URGENCIA = Case(
    When(nivel_urgencia='critico', then=Value(0)),
    When(nivel_urgencia='alto',    then=Value(1)),
    When(nivel_urgencia='medio',   then=Value(2)),
    default=Value(3), output_field=IntegerField(),
)
_CERRADO_AL_FINAL = Case(
    When(status='cerrado', then=Value(1)),
    default=Value(0), output_field=IntegerField(),
)


def ordenar_por_riesgo(qs):
    """
    Casos abiertos primero → de mayor a menor riesgo → los que pidieron
    contacto urgente → sin revisar antes que revisados → más recientes.
    """
    return qs.annotate(_cerrado=_CERRADO_AL_FINAL, _urg=_ORDEN_URGENCIA).order_by(
        '_cerrado', '_urg', '-llamar_911', 'revisado', '-creado_en'
    )


# ── Cambio de estado (un solo lugar para que todo quede coherente) ──
def aplicar_estado(reporte, nuevo, actor, notificar=True):
    """Devuelve True si hubo cambio. Al salir de 'nuevo' el reporte cuenta como revisado."""
    if reporte.status == nuevo:
        return False
    reporte.status = nuevo
    if nuevo != 'nuevo' and not reporte.revisado:
        reporte.revisado     = True
        reporte.revisado_por = actor
        reporte.revisado_en  = timezone.now()
    reporte.save()
    if notificar:
        notificar_cambio_estado(reporte, actor)
    return True


class SidebarMixin:
    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['is_admin']           = _is_admin(self.request.user)
        ctx['mis_reportes_count'] = Reporte.objects.filter(user=self.request.user).count()
        ctx['pendientes_global']  = Sugerencia.objects.filter(estado='pendiente').count()
        ctx['mensajes_no_leidos'] = MensajeAdmin.objects.filter(
            reporte__user=self.request.user, leido=False, es_del_admin=True
        ).count()
        return ctx


class AdminRequiredMixin(UserPassesTestMixin):
    def test_func(self):
        return _is_admin(self.request.user)


# ══════════════════════════════════════════════════════════════════
#  DASHBOARD — bifurca admin vs usuario
# ══════════════════════════════════════════════════════════════════

def _contexto_admin(base_ctx):
    """Todo lo que muestra el panel del administrador, calculado con datos reales."""
    reportes = Reporte.objects.all()
    total = reportes.count()
    por_nivel = {
        n: reportes.filter(nivel_urgencia=n).count()
        for n in ('critico', 'alto', 'medio', 'bajo')
    }

    # Ultimos 7 dias (se agrupa en Python para no depender de las zonas horarias de MySQL)
    hoy = timezone.localdate()
    dias = [hoy - timedelta(days=i) for i in range(6, -1, -1)]
    conteo = {d: 0 for d in dias}
    desde = timezone.make_aware(datetime.combine(dias[0], time.min))
    for creado in reportes.filter(creado_en__gte=desde).values_list('creado_en', flat=True):
        d = timezone.localtime(creado).date()
        if d in conteo:
            conteo[d] += 1
    maximo = max(conteo.values()) or 1
    iniciales = ['L', 'M', 'X', 'J', 'V', 'S', 'D']
    semana = [
        {'dia': iniciales[d.weekday()], 'n': conteo[d],
         'alto': max(6, round(conteo[d] * 100 / maximo)) if conteo[d] else 4}
        for d in dias
    ]

    return {
        **base_ctx,
        'total_reportes':          total,
        'reportes_criticos':       por_nivel['critico'],
        'reportes_alto':           por_nivel['alto'],
        'reportes_medio':          por_nivel['medio'],
        'reportes_bajo':           por_nivel['bajo'],
        'reportes_sin_revisar':    reportes.filter(revisado=False).count(),
        'total_usuarios':          User.objects.count(),
        'sugerencias_pendientes':  Sugerencia.objects.filter(estado='pendiente').count(),
        'reportes':                ordenar_por_riesgo(reportes.select_related('user'))[:20],
        'actividad':               reportes.order_by('-creado_en')[:8],
        'usuarios_recientes':      User.objects.order_by('-date_joined')[:6],
        'sugerencias_recientes':   Sugerencia.objects.filter(estado='pendiente').select_related('usuario')[:5],
        'tips_recientes':          Tip.objects.all()[:4],
        'instituciones_recientes': Institucion.objects.all()[:4],
        'tipos_recientes':         TipoAcoso.objects.all()[:4],
        'semana':                  semana,
    }


class DashboardView(LoginRequiredMixin, View):
    def get(self, request):
        is_admin = _is_admin(request.user)

        base_ctx = {
            'is_admin':           is_admin,
            'mis_reportes_count': Reporte.objects.filter(user=request.user).count(),
            'pendientes_global':  Sugerencia.objects.filter(estado='pendiente').count(),
            'mensajes_no_leidos': MensajeAdmin.objects.filter(
                reporte__user=request.user, leido=False, es_del_admin=True
            ).count(),
        }

        if is_admin:
            return render(request, 'projects/dashboard_admin.html', _contexto_admin(base_ctx))
        else:
            mis_reportes = Reporte.objects.filter(user=request.user).order_by('-creado_en')
            # Marcar mensajes como leídos
            MensajeAdmin.objects.filter(
                reporte__user=request.user, leido=False, es_del_admin=True
            ).update(leido=True)
            ctx = {
                **base_ctx,
                'mis_reportes':   mis_reportes[:5],
                'tips_destacados':Tip.objects.all()[:3],
                'instituciones':  Institucion.objects.all()[:4],
            }
            return render(request, 'projects/dashboard_user.html', ctx)


# ══════════════════════════════════════════════════════════════════
#  REPORTES
# ══════════════════════════════════════════════════════════════════

class ReporteCreateView(SidebarMixin, LoginRequiredMixin, CreateView):
    model         = Reporte
    form_class    = ReporteForm
    template_name = 'projects/reporte_form.html'
    success_url   = reverse_lazy('projects:reporte-list')

    def get_initial(self):
        """Pre-llena los datos de contacto con lo que ya conocemos de la persona."""
        initial = super().get_initial()
        u = self.request.user
        previos = Reporte.objects.filter(user=u).order_by('-creado_en')

        def ultimo(campo):
            return (previos.exclude(**{campo + '__isnull': True}).exclude(**{campo: ''})
                    .values_list(campo, flat=True).first() or '')

        initial['nombre_reportante']   = u.get_full_name() or ultimo('nombre_reportante')
        initial['correo_reportante']   = u.email or ultimo('correo_reportante')
        initial['telefono_reportante'] = ultimo('telefono_reportante')
        return initial

    def form_valid(self, form):
        inst = form.instance
        inst.user   = self.request.user
        inst.status = 'nuevo'

        # Grado de riesgo: lo que marcó la persona es el mínimo; el sistema puede subirlo
        nivel, puntaje, motivos = calcular_riesgo(
            descripcion  = inst.descripcion,
            tipo_nombre  = inst.tipo_acoso.nombre if inst.tipo_acoso else '',
            nivel_usuario= inst.nivel_urgencia,
            llamar_911   = inst.llamar_911,
        )
        inst.nivel_urgencia = nivel
        inst.puntaje_riesgo = puntaje
        inst.motivos_riesgo = resumen_motivos(motivos)

        resp = super().form_valid(form)
        notificar_reporte_nuevo(self.object)      # → campana de los administradores
        if nivel == 'critico':
            messages.error(self.request, '🚨 Reporte CRÍTICO enviado. El equipo lo atenderá con prioridad máxima.')
        elif nivel == 'alto':
            messages.warning(self.request, '⚠️ Reporte urgente enviado. Nos pondremos en contacto pronto.')
        else:
            messages.success(self.request, '✅ Reporte enviado correctamente.')
        return resp


class ReporteListView(SidebarMixin, LoginRequiredMixin, ListView):
    model               = Reporte
    template_name       = 'projects/reporte_list.html'
    context_object_name = 'reportes'

    def get_queryset(self):
        if _is_admin(self.request.user):
            qs = Reporte.objects.select_related('user')
            nivel  = self.request.GET.get('nivel', '')
            estado = self.request.GET.get('revisado', '')
            if nivel:  qs = qs.filter(nivel_urgencia=nivel)
            if estado == '0': qs = qs.filter(revisado=False)
            if estado == '1': qs = qs.filter(revisado=True)
            return ordenar_por_riesgo(qs)
        return Reporte.objects.filter(user=self.request.user).order_by('-creado_en')

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        base = self.object_list
        ctx['activos']   = base.exclude(status='cerrado').count()
        ctx['cerrados']  = base.filter(status='cerrado').count()
        ctx['nivel_max'] = next((ETIQUETA[n] for n in ('critico', 'alto', 'medio', 'bajo')
                                 if base.filter(nivel_urgencia=n).exists()), '')
        if _is_admin(self.request.user):
            ctx['criticos']  = Reporte.objects.filter(nivel_urgencia='critico').count()
            ctx['altos']     = Reporte.objects.filter(nivel_urgencia='alto').count()
            ctx['sin_revisar']= Reporte.objects.filter(revisado=False).count()
            ctx['nivel_actual']   = self.request.GET.get('nivel', '')
            ctx['revisado_actual']= self.request.GET.get('revisado', '')
        return ctx


class ReporteDetailView(SidebarMixin, LoginRequiredMixin, View):
    """Detalle del reporte + mensajes admin ↔ usuario."""
    def get(self, request, pk):
        reporte = get_object_or_404(Reporte, pk=pk)
        if not _is_admin(request.user) and reporte.user != request.user:
            messages.error(request, 'Sin permisos.')
            return redirect('projects:reporte-list')
        # Marcar leídos
        MensajeAdmin.objects.filter(reporte=reporte, leido=False, es_del_admin=True).update(leido=True)
        Notificacion.objects.filter(usuario=request.user, reporte=reporte, leida=False).update(leida=True)

        is_admin = _is_admin(request.user)
        ctx = {
            'reporte':            reporte,
            'mensajes':           reporte.mensajes.all(),
            'is_admin':           is_admin,
            'mis_reportes_count': Reporte.objects.filter(user=request.user).count(),
            'pendientes_global':  Sugerencia.objects.filter(estado='pendiente').count(),
            'mensajes_no_leidos': MensajeAdmin.objects.filter(
                reporte__user=request.user, leido=False, es_del_admin=True
            ).count(),
        }
        return render(request, 'projects/reporte_detail.html', ctx)

    def post(self, request, pk):
        reporte  = get_object_or_404(Reporte, pk=pk)
        es_admin = _is_admin(request.user)
        if not es_admin and reporte.user != request.user:
            return redirect('projects:reporte-list')

        # ── 1) El equipo cambia el estado ─────────────────────────
        if es_admin and 'cambiar_status' in request.POST:
            nuevo = request.POST.get('nuevo_status', '')
            if nuevo not in dict(Reporte.STATUS_CHOICES):
                messages.error(request, 'Estado no válido.')
            elif aplicar_estado(reporte, nuevo, request.user):
                messages.success(request, f'Estado actualizado: {reporte.get_status_display()}.')
            else:
                messages.info(request, 'El reporte ya tenía ese estado.')
            return redirect('projects:reporte-detail', pk=pk)

        # ── 2) El equipo corrige el nivel de riesgo ───────────────
        if es_admin and 'cambiar_nivel' in request.POST:
            nuevo = request.POST.get('nuevo_nivel', '')
            if nuevo not in dict(Reporte.URGENCIA_CHOICES):
                messages.error(request, 'Nivel no válido.')
            elif nuevo != reporte.nivel_urgencia:
                reporte.nivel_urgencia = nuevo
                reporte.puntaje_riesgo = PISO_PUNTAJE[nuevo]
                reporte.motivos_riesgo = resumen_motivos(
                    [m for m in reporte.motivos_riesgo.split(' · ') if m and not m.startswith('Ajustado')]
                    + [f'Ajustado por el equipo a {ETIQUETA[nuevo]}']
                )
                reporte.save()
                notificar_cambio_nivel(reporte, request.user)
                messages.success(request, f'Nivel de riesgo: {ETIQUETA[nuevo]}.')
            return redirect('projects:reporte-detail', pk=pk)

        # ── 3) Mensaje y/o "marcar como revisado" ─────────────────
        texto = request.POST.get('texto', '').strip()
        if texto:
            MensajeAdmin.objects.create(
                reporte=reporte, autor=request.user, texto=texto, es_del_admin=es_admin,
            )
            notificar_mensaje(reporte, request.user, es_admin)
            # Primera respuesta del equipo → el caso pasa solo a "En revisión"
            if es_admin and reporte.status == 'nuevo':
                aplicar_estado(reporte, 'revision', request.user, notificar=False)
            messages.success(request, 'Mensaje enviado.')

        if es_admin and request.POST.get('marcar_revisado') and not reporte.revisado:
            reporte.revisado     = True
            reporte.revisado_por = request.user
            reporte.revisado_en  = timezone.now()
            if reporte.status == 'nuevo':
                reporte.status = 'revision'
            reporte.save()
            notificar_cambio_estado(reporte, request.user)
            messages.success(request, 'Reporte marcado como revisado.')
        return redirect('projects:reporte-detail', pk=pk)


# ══════════════════════════════════════════════════════════════════
#  GLOSARIO
# ══════════════════════════════════════════════════════════════════

class TipoListView(SidebarMixin, LoginRequiredMixin, ListView):
    model         = TipoAcoso
    template_name = 'projects/tipo_list.html'

class TipoCreateView(SidebarMixin, AdminRequiredMixin, LoginRequiredMixin, CreateView):
    model         = TipoAcoso
    form_class    = TipoAcosoForm
    template_name = 'projects/form_generic.html'
    success_url   = reverse_lazy('projects:tipo-list')
    extra_context = {'title': 'Nuevo Tipo de Acoso'}

class TipoUpdateView(SidebarMixin, AdminRequiredMixin, LoginRequiredMixin, UpdateView):
    model         = TipoAcoso
    form_class    = TipoAcosoForm
    template_name = 'projects/form_generic.html'
    success_url   = reverse_lazy('projects:tipo-list')
    extra_context = {'title': 'Editar Tipo de Acoso'}

class TipoDeleteView(SidebarMixin, AdminRequiredMixin, LoginRequiredMixin, DeleteView):
    model         = TipoAcoso
    template_name = 'projects/confirm_delete.html'
    success_url   = reverse_lazy('projects:tipo-list')


# ══════════════════════════════════════════════════════════════════
#  INSTITUCIONES
# ══════════════════════════════════════════════════════════════════

class InstitucionListView(SidebarMixin, LoginRequiredMixin, ListView):
    model         = Institucion
    template_name = 'projects/institucion_list.html'

class InstitucionCreateView(SidebarMixin, AdminRequiredMixin, LoginRequiredMixin, CreateView):
    model         = Institucion
    form_class    = InstitucionForm
    template_name = 'projects/form_generic.html'
    success_url   = reverse_lazy('projects:institucion-list')
    extra_context = {'title': 'Nueva Institución Aliada'}

class InstitucionUpdateView(SidebarMixin, AdminRequiredMixin, LoginRequiredMixin, UpdateView):
    model         = Institucion
    form_class    = InstitucionForm
    template_name = 'projects/form_generic.html'
    success_url   = reverse_lazy('projects:institucion-list')
    extra_context = {'title': 'Editar Institución'}

class InstitucionDeleteView(SidebarMixin, AdminRequiredMixin, LoginRequiredMixin, DeleteView):
    model         = Institucion
    template_name = 'projects/confirm_delete.html'
    success_url   = reverse_lazy('projects:institucion-list')


# ══════════════════════════════════════════════════════════════════
#  TIPS
# ══════════════════════════════════════════════════════════════════

class TipListView(SidebarMixin, LoginRequiredMixin, ListView):
    model         = Tip
    template_name = 'projects/tip_list.html'

class TipCreateView(SidebarMixin, AdminRequiredMixin, LoginRequiredMixin, CreateView):
    model         = Tip
    form_class    = TipForm
    template_name = 'projects/form_generic.html'
    success_url   = reverse_lazy('projects:tip-list')
    extra_context = {'title': 'Nuevo Consejo de Seguridad'}

class TipUpdateView(SidebarMixin, AdminRequiredMixin, LoginRequiredMixin, UpdateView):
    model         = Tip
    form_class    = TipForm
    template_name = 'projects/form_generic.html'
    success_url   = reverse_lazy('projects:tip-list')
    extra_context = {'title': 'Editar Consejo'}

class TipDeleteView(SidebarMixin, AdminRequiredMixin, LoginRequiredMixin, DeleteView):
    model         = Tip
    template_name = 'projects/confirm_delete.html'
    success_url   = reverse_lazy('projects:tip-list')


# ══════════════════════════════════════════════════════════════════
#  SUGERENCIAS
# ══════════════════════════════════════════════════════════════════

class SugerenciaCreateView(SidebarMixin, LoginRequiredMixin, CreateView):
    model         = Sugerencia
    fields        = ['tipo', 'titulo', 'contenido']
    template_name = 'projects/sugerencia_form.html'
    success_url   = reverse_lazy('projects:sugerencia-enviada')

    def form_valid(self, form):
        form.instance.usuario = self.request.user
        messages.success(self.request, '¡Sugerencia enviada!')
        return super().form_valid(form)

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['tipo_inicial'] = self.request.GET.get('tipo', '')
        return ctx


class SugerenciaEnviadaView(SidebarMixin, LoginRequiredMixin, TemplateView):
    template_name = 'projects/sugerencia_enviada.html'


class SugerenciasAdminView(SidebarMixin, AdminRequiredMixin, LoginRequiredMixin, ListView):
    model               = Sugerencia
    template_name       = 'projects/sugerencias_admin.html'
    context_object_name = 'sugerencias'

    def get_queryset(self):
        qs     = Sugerencia.objects.select_related('usuario', 'revisado_por').all()
        estado = self.request.GET.get('estado', '')
        tipo   = self.request.GET.get('tipo', '')
        if estado: qs = qs.filter(estado=estado)
        if tipo:   qs = qs.filter(tipo=tipo)
        return qs

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['pendientes']    = Sugerencia.objects.filter(estado='pendiente').count()
        ctx['aprobadas']     = Sugerencia.objects.filter(estado='aprobada').count()
        ctx['rechazadas']    = Sugerencia.objects.filter(estado='rechazada').count()
        ctx['estado_actual'] = self.request.GET.get('estado', '')
        ctx['tipo_actual']   = self.request.GET.get('tipo', '')
        return ctx


class SugerenciaRevisarView(LoginRequiredMixin, View):
    def post(self, request, pk):
        if not _is_admin(request.user):
            return redirect('projects:sugerencias-admin')
        sug    = get_object_or_404(Sugerencia, pk=pk)
        accion = request.POST.get('accion')
        if accion == 'aprobar':
            sug.estado = 'aprobada'
            messages.success(request, f'Sugerencia aprobada.')
        elif accion == 'rechazar':
            sug.estado = 'rechazada'
            messages.warning(request, f'Sugerencia rechazada.')
        sug.nota_admin   = request.POST.get('nota_admin', '')
        sug.revisado_en  = timezone.now()
        sug.revisado_por = request.user
        sug.save()
        return redirect('projects:sugerencias-admin')


# ══════════════════════════════════════════════════════════════════
#  NOTIFICACIONES EN TIEMPO CASI REAL  (la página consulta cada ~12 s)
# ══════════════════════════════════════════════════════════════════

def _rev(user, reporte_id=None):
    """
    Huella de lo que el usuario ve. Si cambia, la página sabe que
    algún reporte o mensaje se actualizó.
    """
    if reporte_id:
        rep = Reporte.objects.filter(pk=reporte_id).first()
        if rep and (_is_admin(user) or rep.user_id == user.pk):
            t = rep.actualizado_en.timestamp()
            m = rep.mensajes.aggregate(m=Max('id'))['m'] or 0
            return f'r{rep.pk}|{t}|{m}'
    if _is_admin(user):
        reps, msgs = Reporte.objects.all(), MensajeAdmin.objects.all()
    else:
        reps, msgs = Reporte.objects.filter(user=user), MensajeAdmin.objects.filter(reporte__user=user)
    a = reps.aggregate(n=Count('id'), t=Max('actualizado_en'))
    m = msgs.aggregate(m=Max('id'))['m'] or 0
    return f"{a['n']}|{a['t'].timestamp() if a['t'] else 0}|{m}"


def _serializar_notificacion(n):
    return {
        'id':     n.pk,
        'tipo':   n.tipo,
        'titulo': n.titulo,
        'mensaje': n.mensaje,
        'nivel':  n.nivel,
        'leida':  n.leida,
        'url':    reverse('projects:reporte-detail', kwargs={'pk': n.reporte_id}) if n.reporte_id else '',
        'hace':   timesince(n.creado_en).split(',')[0],
    }


class NotificacionesAPIView(View):
    """GET → notificaciones no leídas + huella de cambios. Responde 401 en JSON si no hay sesión."""
    def get(self, request):
        if not request.user.is_authenticated:
            return JsonResponse({'auth': False}, status=401)
        qs = Notificacion.objects.filter(usuario=request.user)
        reporte_id = request.GET.get('reporte')
        resp = JsonResponse({
            'unread': qs.filter(leida=False).count(),
            'items':  [_serializar_notificacion(n) for n in qs.select_related('reporte')[:15]],
            'max_id': qs.values_list('id', flat=True).first() or 0,
            'rev':    _rev(request.user, int(reporte_id) if reporte_id and reporte_id.isdigit() else None),
        })
        resp['Cache-Control'] = 'no-store'
        return resp


class NotificacionesLeerAPIView(View):
    """POST {"all": true} o {"ids": [1,2]} → marca como leídas solo las del usuario."""
    def post(self, request):
        if not request.user.is_authenticated:
            return JsonResponse({'auth': False}, status=401)
        try:
            data = json.loads(request.body or '{}')
        except ValueError:
            data = {}
        qs = Notificacion.objects.filter(usuario=request.user, leida=False)
        if not data.get('all'):
            ids = [i for i in data.get('ids', []) if isinstance(i, int)]
            qs = qs.filter(pk__in=ids)
        return JsonResponse({'marcadas': qs.update(leida=True)})
