from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from .models import Notificacion, Reporte, TipoAcoso
from .risk import calcular_riesgo


class RiesgoTests(TestCase):
    def test_nunca_baja_lo_que_eligio_la_persona(self):
        nivel, _, _ = calcular_riesgo('hola', nivel_usuario='alto')
        self.assertEqual(nivel, 'alto')

    def test_detecta_amenaza_con_arma_como_critico(self):
        nivel, puntaje, motivos = calcular_riesgo('Mi pareja me amenazó con un cuchillo', nivel_usuario='bajo')
        self.assertEqual(nivel, 'critico')
        self.assertGreaterEqual(puntaje, 75)
        self.assertTrue(motivos)

    def test_texto_neutro_es_bajo(self):
        self.assertEqual(calcular_riesgo('Quiero informarme', nivel_usuario='bajo')[0], 'bajo')

    def test_no_confunde_alarma_con_arma(self):
        self.assertEqual(calcular_riesgo('Sonó la alarma del armario', nivel_usuario='bajo')[0], 'bajo')

    def test_tipo_acoso_no_sube_un_reporte_informativo(self):
        self.assertEqual(calcular_riesgo('Quiero informarme', 'Acoso laboral', 'bajo')[0], 'bajo')

    def test_hospital_como_lugar_no_es_gravedad(self):
        nivel, _, _ = calcular_riesgo('Trabajo en un hospital y me incomodan', nivel_usuario='bajo')
        self.assertNotEqual(nivel, 'critico')

    def test_contacto_urgente_sube_a_alto(self):
        self.assertEqual(calcular_riesgo('Me siento mal', nivel_usuario='bajo', llamar_911=True)[0], 'alto')


class FlujoReportesTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_user('equipo', password='x', is_staff=True)
        self.user = User.objects.create_user('ana', password='x')
        self.otro = User.objects.create_user('beto', password='x')
        self.tipo = TipoAcoso.objects.create(nombre='Acoso')

    def _crear(self, descripcion, nivel='medio', **extra):
        self.client.force_login(self.user)
        data = {'descripcion': descripcion, 'nivel_urgencia': nivel, 'tipo_acoso': self.tipo.pk, **extra}
        return self.client.post(reverse('projects:reporte-create'), data)

    # ── 1) Riesgo ─────────────────────────────────────────────
    def test_el_nivel_del_formulario_ya_se_guarda(self):
        self._crear('Me insultan en el trabajo', nivel='alto')
        self.assertEqual(Reporte.objects.get().nivel_urgencia, 'alto')

    def test_el_sistema_sube_el_nivel_si_detecta_gravedad(self):
        self._crear('Me golpeó y me amenazó con un arma', nivel='bajo')
        r = Reporte.objects.get()
        self.assertEqual(r.nivel_urgencia, 'critico')
        self.assertTrue(r.motivos_riesgo)

    def test_lista_admin_ordenada_por_riesgo(self):
        for nivel, desc in [('bajo', 'consulta'), ('critico', 'urgente'), ('medio', 'molestias'), ('alto', 'amenaza')]:
            Reporte.objects.create(user=self.user, descripcion=desc, nivel_urgencia=nivel)
        self.client.force_login(self.admin)
        r = self.client.get(reverse('projects:reporte-list'))
        niveles = [x.nivel_urgencia for x in r.context['reportes']]
        self.assertEqual(niveles, ['critico', 'alto', 'medio', 'bajo'])

    def test_cerrados_van_al_final(self):
        Reporte.objects.create(user=self.user, descripcion='a', nivel_urgencia='critico', status='cerrado')
        Reporte.objects.create(user=self.user, descripcion='b', nivel_urgencia='bajo')
        self.client.force_login(self.admin)
        r = self.client.get(reverse('projects:reporte-list'))
        self.assertEqual([x.status for x in r.context['reportes']], ['nuevo', 'cerrado'])

    # ── 2) Estado ─────────────────────────────────────────────
    def test_admin_cambia_estado_y_avisa_a_la_persona(self):
        rep = Reporte.objects.create(user=self.user, descripcion='x')
        self.client.force_login(self.admin)
        self.client.post(reverse('projects:reporte-detail', args=[rep.pk]),
                         {'cambiar_status': '1', 'nuevo_status': 'proceso'})
        rep.refresh_from_db()
        self.assertEqual(rep.status, 'proceso')
        self.assertTrue(rep.revisado)
        self.assertTrue(Notificacion.objects.filter(usuario=self.user, tipo='estado', reporte=rep).exists())

    def test_estado_invalido_se_rechaza(self):
        rep = Reporte.objects.create(user=self.user, descripcion='x')
        self.client.force_login(self.admin)
        self.client.post(reverse('projects:reporte-detail', args=[rep.pk]),
                         {'cambiar_status': '1', 'nuevo_status': 'hackeado'})
        rep.refresh_from_db()
        self.assertEqual(rep.status, 'nuevo')

    def test_usuario_normal_no_puede_cambiar_estado(self):
        rep = Reporte.objects.create(user=self.user, descripcion='x')
        self.client.force_login(self.user)
        self.client.post(reverse('projects:reporte-detail', args=[rep.pk]),
                         {'cambiar_status': '1', 'nuevo_status': 'cerrado'})
        rep.refresh_from_db()
        self.assertEqual(rep.status, 'nuevo')

    def test_primera_respuesta_del_equipo_pasa_a_revision(self):
        rep = Reporte.objects.create(user=self.user, descripcion='x')
        self.client.force_login(self.admin)
        self.client.post(reverse('projects:reporte-detail', args=[rep.pk]), {'texto': 'Hola, te acompañamos'})
        rep.refresh_from_db()
        self.assertEqual(rep.status, 'revision')

    def test_marcar_revisado_funciona_sin_texto(self):
        rep = Reporte.objects.create(user=self.user, descripcion='x')
        self.client.force_login(self.admin)
        self.client.post(reverse('projects:reporte-detail', args=[rep.pk]), {'marcar_revisado': 'on'})
        rep.refresh_from_db()
        self.assertTrue(rep.revisado)

    def test_admin_corrige_nivel(self):
        rep = Reporte.objects.create(user=self.user, descripcion='x', nivel_urgencia='medio')
        self.client.force_login(self.admin)
        self.client.post(reverse('projects:reporte-detail', args=[rep.pk]),
                         {'cambiar_nivel': '1', 'nuevo_nivel': 'critico'})
        rep.refresh_from_db()
        self.assertEqual(rep.nivel_urgencia, 'critico')

    # ── 3) Notificaciones ─────────────────────────────────────
    def test_reporte_nuevo_notifica_a_admins_sin_exponer_el_texto(self):
        self._crear('Texto muy sensible que nadie debe ver en una notificación', nivel='alto')
        n = Notificacion.objects.get(usuario=self.admin)
        self.assertEqual(n.tipo, 'reporte_nuevo')
        self.assertNotIn('sensible', n.titulo + n.mensaje)
        self.assertFalse(Notificacion.objects.filter(usuario=self.user).exists())

    def test_respuesta_de_la_persona_notifica_al_equipo(self):
        rep = Reporte.objects.create(user=self.user, descripcion='x')
        self.client.force_login(self.user)
        self.client.post(reverse('projects:reporte-detail', args=[rep.pk]), {'texto': 'Gracias'})
        self.assertTrue(Notificacion.objects.filter(usuario=self.admin, tipo='mensaje').exists())

    def test_api_devuelve_solo_mis_notificaciones(self):
        rep = Reporte.objects.create(user=self.user, descripcion='x')
        Notificacion.objects.create(usuario=self.user, titulo='mía', reporte=rep)
        Notificacion.objects.create(usuario=self.otro, titulo='ajena')
        self.client.force_login(self.user)
        d = self.client.get(reverse('projects:api-notificaciones')).json()
        self.assertEqual(d['unread'], 1)
        self.assertEqual([i['titulo'] for i in d['items']], ['mía'])
        self.assertIn('rev', d)

    def test_api_sin_sesion_responde_401_json(self):
        r = self.client.get(reverse('projects:api-notificaciones'))
        self.assertEqual(r.status_code, 401)

    def test_la_huella_cambia_cuando_cambia_el_estado(self):
        rep = Reporte.objects.create(user=self.user, descripcion='x')
        self.client.force_login(self.user)
        antes = self.client.get(reverse('projects:api-notificaciones')).json()['rev']
        rep.status = 'proceso'; rep.save()
        despues = self.client.get(reverse('projects:api-notificaciones')).json()['rev']
        self.assertNotEqual(antes, despues)

    def test_marcar_leidas_no_toca_las_de_otros(self):
        a = Notificacion.objects.create(usuario=self.user, titulo='a')
        b = Notificacion.objects.create(usuario=self.otro, titulo='b')
        self.client.force_login(self.user)
        self.client.post(reverse('projects:api-notificaciones-leer'), data='{"all": true}',
                         content_type='application/json')
        a.refresh_from_db(); b.refresh_from_db()
        self.assertTrue(a.leida)
        self.assertFalse(b.leida)

    def test_abrir_el_reporte_marca_sus_notificaciones_como_leidas(self):
        rep = Reporte.objects.create(user=self.user, descripcion='x')
        n = Notificacion.objects.create(usuario=self.user, titulo='t', reporte=rep)
        self.client.force_login(self.user)
        self.client.get(reverse('projects:reporte-detail', args=[rep.pk]))
        n.refresh_from_db()
        self.assertTrue(n.leida)

    def test_un_usuario_no_ve_la_huella_de_un_reporte_ajeno(self):
        rep = Reporte.objects.create(user=self.otro, descripcion='x')
        self.client.force_login(self.user)
        d = self.client.get(reverse('projects:api-notificaciones') + f'?reporte={rep.pk}').json()
        self.assertFalse(d['rev'].startswith('r'))
