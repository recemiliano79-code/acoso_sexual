from django import forms
from .models import Tip, TipoAcoso, Institucion, Reporte

class BaseStyleForm(forms.ModelForm):
    """
    Clase base que aplica los estilos oscuros a todos los inputs.
    """
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field_name, field in self.fields.items():
            # Estilo CSS para modo oscuro (Glassmorphism)
            field.widget.attrs.update({
                'class': 'form-control',
                'style': 'background: rgba(255,255,255,0.05); border: 1px solid rgba(255,255,255,0.1); color: white; padding: 12px; border-radius: 10px; width: 100%;'
            })
            
            # Placeholder con el nombre del campo si lo deseas
            field.widget.attrs['placeholder'] = field.label

            # Quitar la opción "------" vacía por un texto más amable en los Select
            if isinstance(field.widget, forms.Select):
                field.empty_label = "Seleccione una opción..."

class TipoAcosoForm(BaseStyleForm):
    class Meta:
        model = TipoAcoso
        fields = ['nombre', 'descripcion']
        labels = {
            'nombre': 'Nombre del tipo de acoso',
            'descripcion': 'Descripción breve',
        }

class InstitucionForm(BaseStyleForm):
    class Meta:
        model = Institucion
        fields = ['nombre', 'direccion', 'telefono', 'email', 'sitio_web', 'notas']
        widgets = {
            'notas': forms.Textarea(attrs={'rows': 3}),
        }

class TipForm(BaseStyleForm):
    class Meta:
        model = Tip
        fields = ['titulo', 'contenido', 'publicado']
        widgets = {
            'contenido': forms.Textarea(attrs={'rows': 4}),
        }

class ReporteForm(BaseStyleForm):
    class Meta:
        model = Reporte
        fields = [
            'nombre_reportante',
            'correo_reportante',
            'telefono_reportante',
            'tipo_acoso',
            'institucion',
            'descripcion',
            'fecha_suceso',
            'lugar'
        ]
        labels = {
            'tipo_acoso': 'Tipo de acoso',
            'institucion': 'Institución (Opcional)',
            'descripcion': 'Descripción de los hechos',
            'lugar': 'Lugar del suceso'
        }
        widgets = {
            'fecha_suceso': forms.DateInput(attrs={'type': 'date'}), # Muestra el calendario
            'descripcion': forms.Textarea(attrs={'rows': 5}),
        }