"""
Recalcula el grado de riesgo de los reportes que ya existen.

Los reportes creados antes del arreglo quedaron todos en "medio" porque el
formulario ignoraba el nivel. Este comando los clasifica con el texto real.

Uso:
    python manage.py recalcular_riesgo --dry-run     # solo muestra qué cambiaría
    python manage.py recalcular_riesgo               # aplica los cambios
    python manage.py recalcular_riesgo --incluir-revisados

Por seguridad NO baja el nivel de ningún reporte: solo lo sube.
"""
from django.core.management.base import BaseCommand

from projects.models import Reporte
from projects.risk import calcular_riesgo, resumen_motivos, RANGO


class Command(BaseCommand):
    help = 'Clasifica por riesgo los reportes existentes (solo sube niveles, nunca los baja).'

    def add_arguments(self, parser):
        parser.add_argument('--dry-run', action='store_true', help='No guarda nada, solo muestra.')
        parser.add_argument('--incluir-revisados', action='store_true',
                            help='También recalcula los reportes que el equipo ya revisó.')

    def handle(self, *args, **opts):
        qs = Reporte.objects.select_related('tipo_acoso')
        if not opts['incluir_revisados']:
            qs = qs.filter(revisado=False)

        cambios = 0
        for r in qs:
            nivel, puntaje, motivos = calcular_riesgo(
                descripcion=r.descripcion,
                tipo_nombre=r.tipo_acoso.nombre if r.tipo_acoso else '',
                nivel_usuario='bajo',            # el nivel guardado era el valor por defecto, no una elección real
                llamar_911=r.llamar_911,
            )
            if RANGO[nivel] < RANGO[r.nivel_urgencia]:
                nivel = r.nivel_urgencia         # nunca bajar
            if (nivel, puntaje) == (r.nivel_urgencia, r.puntaje_riesgo):
                continue
            cambios += 1
            self.stdout.write(f'#{r.pk}: {r.nivel_urgencia} → {nivel} ({puntaje}/100) {", ".join(motivos)[:80]}')
            if not opts['dry_run']:
                r.nivel_urgencia = nivel
                r.puntaje_riesgo = puntaje
                r.motivos_riesgo = resumen_motivos(motivos)
                r.save(update_fields=['nivel_urgencia', 'puntaje_riesgo', 'motivos_riesgo', 'actualizado_en'])

        etiqueta = 'se cambiarían' if opts['dry_run'] else 'se actualizaron'
        self.stdout.write(self.style.SUCCESS(f'{cambios} reportes {etiqueta}.'))
