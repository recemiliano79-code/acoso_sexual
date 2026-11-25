"""
projects/risk.py
════════════════════════════════════════════════════════════════
Clasificación automática del grado de riesgo de un reporte.

• Funciona con reglas (palabras clave) → es instantáneo, determinista
  y NO envía el texto del reporte a ningún servicio externo.
• Nunca BAJA el nivel que eligió la persona: lo que ella marca es el
  mínimo. El sistema solo puede subirlo si detecta señales graves.
• Devuelve también los motivos, para que quien revise el caso vea
  por qué quedó en ese nivel.
• El equipo siempre puede corregir el nivel a mano desde el detalle.
"""
import re
import unicodedata

NIVELES = ['bajo', 'medio', 'alto', 'critico']
RANGO = {n: i for i, n in enumerate(NIVELES)}
ETIQUETA = {'bajo': 'Bajo', 'medio': 'Medio', 'alto': 'Alto', 'critico': 'Crítico'}

# Puntaje mínimo que corresponde a cada nivel
PISO_PUNTAJE = {'bajo': 0, 'medio': 20, 'alto': 45, 'critico': 75}


def _normalizar(texto: str) -> str:
    texto = unicodedata.normalize('NFD', texto or '')
    texto = ''.join(c for c in texto if unicodedata.category(c) != 'Mn')
    return re.sub(r'\s+', ' ', texto.lower()).strip()


# (etiqueta para mostrar, expresión regular sobre texto SIN acentos)
GRUPOS_CRITICOS = [
    ('Violencia sexual / violación',
     r'\bviol(o|aron|ar|acion|ada|ado)\b|abuso sexual|abusaron|agresion sexual|sumision quimica|me drogaron|me drogo'),
    ('Amenaza de muerte / riesgo de feminicidio',
     r'me (va|van) a matar|matarme|amenaza(s)? de muerte|amenazo de muerte|feminicid|quiere matarme|me quiere matar'),
    ('Arma involucrada',
     r'\barmas?\b|pistola|cuchillo|navaja|machete|disparo|disparos|balazo'),
    ('Privación de la libertad',
     r'secuestr|privacion de la libertad|me encerr|encerrada|no me deja salir|me retiene|retenida'),
    ('Asfixia / estrangulamiento',
     r'estrangul|asfixi|ahorc'),
    ('Riesgo de autolesión o suicidio',
     r'me quiero morir|quitarme la vida|suicid|hacerme dano'),
    ('Lesiones graves',
     r'sangr|lesion|herida|inconsciente|desmay|hospitalizad|me llevaron al hospital|fui al hospital'),
]

GRUPOS_ALTOS = [
    ('Amenazas', r'amenaz'),
    ('Violencia física',
     r'\bgolpe|golpea|golpeo|\bpego\b|\bpega\b|patada|empuj|jaloneo|jalone|cachetada|bofetada|moreton'),
    ('Contacto sexual sin consentimiento',
     r'me toco|me tocaron|me toca\b|tocamiento|manose|me agarro|a la fuerza|me obligo|me forzo|sin mi consentimiento|sin consentimiento|\babus'),
    ('Persecución / acecho',
     r'me sigue|me siguio|me persigue|me persiguio|me espia|acech|stalke|me vigila|aparece donde estoy'),
    ('Extorsión / difusión de contenido íntimo',
     r'extors|chantaj|sextors|fotos intimas|videos intimos|contenido intimo|desnud|difundi|filtr(o|aron)|porno venganza|revenge'),
    ('Involucra a menores de edad',
     r'menor de edad|menores|mi hij[oa]\b|\bnin[oa]s?\b|adolescente'),
]

GRUPOS_MEDIOS = [
    ('Acoso / hostigamiento', r'acoso|acosa|hostig'),
    ('Agresión verbal', r'insult|humill|grita|gritos|denigr|ofend|burla'),
    ('Mensajes o comentarios no deseados',
     r'piropo|insinuacion|comentarios|mensajes|llamadas|silbid|miradas|incomod|molest'),
    ('Discriminación / represalias',
     r'discrimin|represalia|me despid|me corrieron|exclu'),
]

# Agravantes (suman puntaje, no definen el nivel por sí solos)
AGRAVANTES = [
    ('Violencia reiterada',
     r'todos los dias|cada dia|cada semana|constantemente|desde hace (meses|anos|semanas)|reiterad|otra vez|de nuevo|siempre'),
    ('Contexto de pareja o convivencia',
     r'mi pareja|mi esposo|mi novio|mi ex\b|expareja|ex pareja|vivo con|vivimos juntos|mi marido'),
]

_COMPILADOS = {
    'critico': [(e, re.compile(p)) for e, p in GRUPOS_CRITICOS],
    'alto': [(e, re.compile(p)) for e, p in GRUPOS_ALTOS],
    'medio': [(e, re.compile(p)) for e, p in GRUPOS_MEDIOS],
    'agravantes': [(e, re.compile(p)) for e, p in AGRAVANTES],
}


def _nivel_por_puntaje(puntaje: int) -> str:
    if puntaje >= PISO_PUNTAJE['critico']:
        return 'critico'
    if puntaje >= PISO_PUNTAJE['alto']:
        return 'alto'
    if puntaje >= PISO_PUNTAJE['medio']:
        return 'medio'
    return 'bajo'


def _max_nivel(a: str, b: str) -> str:
    return a if RANGO[a] >= RANGO[b] else b


def calcular_riesgo(descripcion='', tipo_nombre='', nivel_usuario='medio', llamar_911=False):
    """
    Devuelve (nivel, puntaje 0-100, lista_de_motivos).

    nivel_usuario: lo que la persona marcó en el formulario; es el piso.

    Se analiza la descripción y el tipo de acoso. El "lugar" NO se analiza a
    propósito: un hospital o una escuela como lugar no indica gravedad.
    Las señales de nivel medio solo se buscan en la descripción: casi todos los
    tipos del glosario contienen la palabra "acoso" y subirían todo a "medio".
    """
    if nivel_usuario not in RANGO:
        nivel_usuario = 'medio'

    texto_desc = _normalizar(descripcion)
    texto      = _normalizar(f'{descripcion} {tipo_nombre}')
    motivos, puntaje = [], 0

    # ── Señales críticas ───────────────────────────────────────
    hits = [e for e, rx in _COMPILADOS['critico'] if rx.search(texto)]
    if hits:
        puntaje += 80 + 5 * (len(hits) - 1)
        motivos += hits

    # ── Señales altas ──────────────────────────────────────────
    hits = [e for e, rx in _COMPILADOS['alto'] if rx.search(texto)]
    if hits:
        puntaje += 45 + 15 * (len(hits) - 1)
        motivos += hits

    # ── Señales medias ─────────────────────────────────────────
    hits = [e for e, rx in _COMPILADOS['medio'] if rx.search(texto_desc)]
    if hits:
        puntaje += 20 + 4 * (len(hits) - 1)
        motivos += hits[:2]

    # ── Agravantes (solo cuentan si ya hay alguna señal) ───────
    if puntaje:
        for etiqueta, rx in _COMPILADOS['agravantes']:
            if rx.search(texto):
                puntaje += 10
                motivos.append(etiqueta)

    nivel = _nivel_por_puntaje(puntaje)

    # ── Contacto urgente solicitado ────────────────────────────
    if llamar_911:
        motivos.append('Solicitó contacto urgente')
        nivel = _max_nivel(nivel, 'alto')
        if puntaje >= PISO_PUNTAJE['alto']:
            nivel = 'critico'

    # ── Lo que marcó la persona es el mínimo ───────────────────
    if RANGO[nivel_usuario] > RANGO[nivel]:
        nivel = nivel_usuario
        motivos.append(f'Nivel elegido por la persona: {ETIQUETA[nivel_usuario]}')
    elif nivel_usuario in ('alto', 'critico'):
        motivos.append(f'Nivel elegido por la persona: {ETIQUETA[nivel_usuario]}')

    puntaje = min(100, max(puntaje, PISO_PUNTAJE[nivel]))
    return nivel, puntaje, motivos


def resumen_motivos(motivos, limite=300):
    """Texto corto para guardar en la base (CharField)."""
    texto = ' · '.join(dict.fromkeys(motivos))  # sin duplicados, conserva orden
    return texto if len(texto) <= limite else texto[:limite - 1] + '…'
