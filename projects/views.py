# ══════════════════════════════════════════════════════════════════
#  projects/views.py  — VERSIÓN COMPLETA v2
# ══════════════════════════════════════════════════════════════════

from django.urls import reverse_lazy
from django.views.generic import (
    ListView, CreateView, UpdateView, DeleteView, TemplateView, DetailView
)
from django.views import View
from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
from django.contrib.auth.models import User
from django.shortcuts import get_object_or_404, redirect, render
from django.contrib import messages
from django.utils import timezone
from django.http import JsonResponse
from .models import Tip, TipoAcoso, Institucion, Reporte, Sugerencia, MensajeAdmin
from .forms import TipForm, TipoAcosoForm, InstitucionForm, ReporteForm


# ── Helpers ───────────────────────────────────────────────────────
def _is_admin(user):
    return user.is_staff or user.username == 'recemilian79'


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
            ctx = {
                **base_ctx,
                'total_reportes':    Reporte.objects.count(),
                'reportes_urgentes': Reporte.objects.filter(nivel_urgencia='critico').count(),
                'reportes_nuevos':   Reporte.objects.filter(revisado=False).count(),
                'total_usuarios':    User.objects.count(),
                'sugerencias_pend':  Sugerencia.objects.filter(estado='pendiente').count(),
                'reportes_recientes':Reporte.objects.select_related('user').order_by('-creado_en')[:8],
                'usuarios_recientes':User.objects.order_by('-date_joined')[:6],
                'reportes_urgentes_list': Reporte.objects.filter(
                    nivel_urgencia='critico', revisado=False
                ).select_related('user').order_by('-creado_en')[:5],
                'all_reportes':      Reporte.objects.select_related('user').order_by('-creado_en')[:20],
            }
            return render(request, 'projects/dashboard_admin.html', ctx)
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

    def form_valid(self, form):
        form.instance.user = self.request.user
        if not form.instance.status:
            form.instance.status = 'nuevo'
        resp = super().form_valid(form)
        nivel = form.instance.nivel_urgencia
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
            qs = Reporte.objects.select_related('user').order_by('-creado_en')
            nivel  = self.request.GET.get('nivel', '')
            estado = self.request.GET.get('revisado', '')
            if nivel:  qs = qs.filter(nivel_urgencia=nivel)
            if estado == '0': qs = qs.filter(revisado=False)
            if estado == '1': qs = qs.filter(revisado=True)
            return qs
        return Reporte.objects.filter(user=self.request.user).order_by('-creado_en')

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
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
        reporte = get_object_or_404(Reporte, pk=pk)
        if not _is_admin(request.user) and reporte.user != request.user:
            return redirect('projects:reporte-list')
        texto = request.POST.get('texto', '').strip()
        if texto:
            MensajeAdmin.objects.create(
                reporte=reporte,
                autor=request.user,
                texto=texto,
                es_del_admin=_is_admin(request.user),
            )
            # Si admin marca revisado
            if _is_admin(request.user) and request.POST.get('marcar_revisado'):
                reporte.revisado    = True
                reporte.revisado_por= request.user
                reporte.revisado_en = timezone.now()
                reporte.save()
                messages.success(request, 'Reporte marcado como revisado.')
            else:
                messages.success(request, 'Mensaje enviado.')
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