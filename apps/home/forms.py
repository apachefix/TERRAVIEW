    # -*- encoding: utf-8 -*-
"""
Copyright (c) 2019 - present AppSeed.us
"""
from django import forms
from django.contrib.auth.models import *
from django.contrib.auth.forms import UserCreationForm
from django.core.exceptions import ValidationError
from django.contrib.auth import password_validation
from django.utils.translation import gettext_lazy as _

from apps.home.general_postgres import *
from apps.home.models import *

#########################################
###        FORMULARIO EMPRESA         ###
#########################################
class formEMPRESA(forms.ModelForm):
    class Meta:
        #Asignacion de la tabla EMPRESA para crear el formulario
        model = EMPRESA
        #Seleccion de campos a solicitar en el formulario
        fields = ['EP_CRAZONSOCIAL', 'EP_CRUT', 'EP_CEMAIL', 'EP_CTELEFONO', 'EP_CDIRECCION', 'EP_CUSUARIOSBD', 'EP_CPASSWORDBD', 'EP_CPORT', 'EP_CHOST', 'EP_CSERVER', 'EP_CLISENCESERVER', 'EP_CDB_SERVER_TYPE', 'EP_CUSER_SAP', 'EP_CPASSWORD_SAP']
        labels = '__all__'

        widgets = {
            'EP_CRAZONSOCIAL': forms.TextInput(attrs={'class': 'form-control', 'id': 'razon_social'}),
            'EP_CRUT': forms.TextInput(attrs={'class': 'form-control', 'id': 'rut'}),
            'EP_CEMAIL': forms.TextInput(attrs={'class': 'form-control', 'id': 'email'}),
            'EP_CTELEFONO': forms.TextInput(attrs={'class': 'form-control', 'id': 'telefono'}),
            'EP_CDIRECCION': forms.TextInput(attrs={'class': 'form-control', 'id': 'direccion'}),
            'EP_CUSUARIOSBD': forms.TextInput(attrs={'class': 'form-control', 'id': 'usuario_sbd'}),
            'EP_CPASSWORDBD': forms.TextInput(attrs={'class': 'form-control', 'id': 'password_sbd'}),
            'EP_CPORT': forms.TextInput(attrs={'class': 'form-control', 'id': 'port'}),
            'EP_CHOST': forms.TextInput(attrs={'class': 'form-control', 'id': 'host'}),
            'EP_CSERVER': forms.TextInput(attrs={'class': 'form-control', 'id': 'server'}),
            'EP_CLISENCESERVER': forms.TextInput(attrs={'class': 'form-control', 'id': 'liscence_server'}),
            'EP_CDB_SERVER_TYPE': forms.TextInput(attrs={'class': 'form-control', 'id': 'db_server_type'}),
            'EP_CUSER_SAP': forms.TextInput(attrs={'class': 'form-control', 'id': 'user_sap'}),
            'EP_CPASSWORD_SAP': forms.TextInput(attrs={'class': 'form-control', 'id': 'password_sap'}),
        }
#########################################
###      FORMULARIO CONDUCTOR         ###
#########################################
class formCONDUCTOR(forms.ModelForm):
    class Meta:
        #Asignacion de la tabla CONDUCTOR para crear el formulario
        model = CONDUCTOR
        #Seleccion de campos a solicitar en el formulario
        fields = ['EP_NID', 'SN_NID', 'US_NID', 'CON_CNOMBRE', 'CON_CAPELLIDO', 'CON_CRUT', 'CON_CEMAIL', 'CON_CTELEFONO', 'CON_FFECHAREGISTRO', 'CON_BHABILITADO', 'CON_CDIRECCION', 'CON_NPERIODO_EXTRA']
        labels = '__all__'

        #Widgets para el formulario
        widgets = {
            'EP_NID': forms.HiddenInput(attrs={'class': 'form-control', 'id': 'id_empresa'}),
            'SN_NID': forms.Select(choices=listarOpcionesTabla('CAST("id" AS text)', ''' "SN_CRUT" || ' - ' || "SN_CRAZONSOCIAL" ''', 'SOCIONEGOCIO', '', '', '''"SN_CTIPO" = 'S' '''),attrs={'class': 'form-control js-example-placeholder-multiple', 'id': 'id_socionegocio'}),
            'CON_CNOMBRE': forms.TextInput(attrs={'class': 'form-control', 'id': 'nombre'}),
            'CON_CAPELLIDO': forms.TextInput(attrs={'class': 'form-control', 'id': 'apellido'}),
            'CON_CRUT': forms.TextInput(attrs={'class': 'form-control', 'id': 'rut'}),
            'CON_CEMAIL': forms.TextInput(attrs={'class': 'form-control', 'id': 'email'}),
            'CON_CTELEFONO': forms.TextInput(attrs={'class': 'form-control', 'id': 'telefono'}),
            'CON_BHABILITADO': forms.CheckboxInput(attrs={'class':'form-check-input', 'type':'checkbox','id':"switch-s-2"}),
            'CON_CDIRECCION': forms.TextInput(attrs={'class': 'form-control', 'id': 'id_direccion'}),
            'CON_NPERIODO_EXTRA': forms.NumberInput(attrs={'class': 'form-control', 'id': 'id_periodo_extra'}),
        }

class formDOCUMENTO_CONDUCTOR(forms.ModelForm):
    class Meta:
        #Asignacion de la tabla DOCUMENTO_CONDUCTOR para crear el formulario
        model = DOCUMENTO_CONDUCTOR
        #Seleccion de campos a solicitar en el formulario
        fields = ['EP_NID', 'US_NID','CON_NID', 'DCON_CTIPO', 'DCON_CRUTADOC', 'DCON_FFECHAREGISTRO', 'DCON_FFECHAEMISION', 'DCON_FFECHAVENCIMIENTO', 'DCON_BHABILITADO']

        widgets = {
            'EP_NID': forms.HiddenInput(attrs={'class': 'form-control', 'id': 'id_empresa'}),
            'CON_NID': forms.Select(attrs={'class': 'form-control js-example-placeholder-multiple', 'id': 'id_conductor'}),
            'DCON_CTIPO': forms.TextInput(attrs={'class':'form-control','type':'text','name':'validation-required','id':'dconductor_id'}),
            'DCON_FFECHAEMISION': forms.DateInput(attrs={'class': 'form-control', 'id': 'fecha_emision','type':'date'}),
            'DCON_FFECHAVENCIMIENTO': forms.DateInput(attrs={'class': 'form-control', 'id': 'fecha_vencimiento','type':'date'}),
            'DCON_BHABILITADO': forms.CheckboxInput(attrs={'class':'form-check-input', 'type':'checkbox','id':"switch-s-1"}),
        }

#########################################
###       FORMULARIO CAMION           ###
#########################################
class formCAMION(forms.ModelForm):
    class Meta:
        #Asignacion de la tabla CONDUCTOR para crear el formulario
        model = CAMION
        #Seleccion de campos a solicitar en el formulario
        fields = ['EP_NID', 'SN_NID', 'US_NID', 'CAM_CPATENTE', 'CAM_CMARCA', 'CAM_CCOLOR', 'CAM_CMODELO', 'CAM_CCARGA', 'CAM_NMETROS3', 'CAM_NANO', 'CAM_NKILOMETRAJE', 'CAM_FFECHAREGISTRO', 'CAM_BHABILITADO']
        lables = '__all__'
        
        #Widgets para el formulario
        widgets = {
            'EP_NID': forms.HiddenInput(attrs={'class': 'form-control ', 'id': 'id_empresa'}),
            'SN_NID': forms.Select(attrs={'class': 'form-control js-example-placeholder-multiple', 'id': 'id_socionegocio'}),
            'CAM_CPATENTE': forms.TextInput(attrs={'class': 'form-control', 'id': 'patente'}),
            'CAM_CMARCA': forms.TextInput(attrs={'class': 'form-control', 'id': 'marca'}),
            'CAM_CCOLOR': forms.TextInput(attrs={'class': 'form-control', 'id': 'color'}),
            'CAM_CMODELO': forms.TextInput(attrs={'class': 'form-control', 'id': 'modelo'}),
            'CAM_CCARGA': forms.TextInput(attrs={'class': 'form-control', 'id': 'carga'}),
            'CAM_NMETROS3': forms.TextInput(attrs={'class': 'form-control', 'id': 'metros3'}),
            'CAM_NANO': forms.NumberInput(attrs={'class': 'form-control', 'id': 'ano'}),
            'CAM_NKILOMETRAJE': forms.TextInput(attrs={'class': 'form-control', 'id': 'kilometraje'}),
            'CAM_BHABILITADO': forms.CheckboxInput(attrs={'class':'form-check-input', 'type':'checkbox','id':"switch-s-1"}),
        }

#########################################
###      FORMULARIO DOCUMENTO         ###
#########################################
class formDOCUMENTO(forms.ModelForm):
    class Meta:
        #Asignacion de la tabla LISTADO_DOCUMENTO para crear el formulario
        model = LISTADO_DOCUMENTO
        #Seleccion de campos a solicitar en el formulario
        fields = ['EP_NID', 'US_NID', 'LIS_CNOMBREDOCUMENTO', 'LIS_CGRUPO', 'LIS_CCODIGO', 'LIS_CDESCRIPCION', 'LIS_CFORMATO','LIS_FFECHAREGISTRO', 'LIS_BOBLIGATORIO', 'LIS_BHABILITADO']
        labels = '__all__'
        #Widgets para el formulario
        widgets = {
            'EP_NID': forms.HiddenInput(attrs={'class': 'form-control', 'id': 'id_empresa'}),
            'LIS_CNOMBREDOCUMENTO': forms.TextInput(attrs={'class': 'form-control', 'id': 'nombre_documento'}),
            'LIS_CGRUPO': forms.Select(choices=listarOpcionesTabla('"PM_CDESCRIPCION"', '"PM_CVALOR1"', 'PARAMETRO', '', '', '''"PM_CGRUPO" = 'TIPO_ENTIDADES' '''),attrs={'class': 'form-control js-example-placeholder-multiple', 'id': 'grupo_documento'}),
            'LIS_CCODIGO': forms.TextInput(attrs={'class': 'form-control', 'id': 'codigo_documento'}),
            'LIS_CDESCRIPCION': forms.TextInput(attrs={'class': 'form-control', 'id': 'descripcion_documento'}),
            'LIS_CFORMATO': forms.Select(choices=listarOpcionesTabla('"PM_CDESCRIPCION"', '"PM_CVALOR1"', 'PARAMETRO', '', '', '''"PM_CGRUPO" = 'FORMATO_DOCUMENTOS' '''),attrs={'class': 'form-control js-example-placeholder-multiple', 'id': 'formato_documento'}),
            'LIS_BOBLIGATORIO': forms.CheckboxInput(attrs={'class':'form-check-input', 'type':'checkbox','id':"switch-s-1"}),
            'LIS_BHABILITADO': forms.CheckboxInput(attrs={'class':'form-check-input', 'type':'checkbox','id':"switch-s-2"}),
        }
#########################################
###              CAMPOS               ###
#########################################
class formCAMPO(forms.ModelForm):
    class Meta:
        #Asignacion de la tabla LISTADO_DOCUMENTO para crear el formulario
        model = CAMPO
        #Seleccion de campos a solicitar en el formulario
        fields = [
            'EP_NID',
            'US_NID',
            'CA_CTIPO',
            'CA_CETIQUETA',
            'CA_CVALORDEFAULT',
            'CA_CPLACEMARK',
            'CA_CQUERY',
            'CA_NLARGO',
            'CA_BOBLIGATORIO',
            'CA_BHABILITADO',
            'CA_BVALIDARSAP',
            'CA_CCODIGO',
            'CA_BASIGNARVALOR'
            ]
        labels = '__all__'
        #Widgets para el formulario
        widgets = {
            'EP_NID': forms.HiddenInput(attrs={'class': 'form-control', 'id': 'id_empresa'}),
            'US_NID': forms.Select(attrs={'class': 'form-control js-example-placeholder-multiple'}),
            'CA_CTIPO': forms.Select(attrs={'class': 'form-control js-example-placeholder-multiple', 'id': 'nombre_documento'}),
            'CA_CETIQUETA': forms.TextInput(attrs={'class': 'form-control'}),
            'CA_CVALORDEFAULT': forms.TextInput(attrs={'class': 'form-control'}),
            'CA_CPLACEMARK': forms.TextInput(attrs={'class': 'form-control'}),
            'CA_CQUERY': forms.TextInput(attrs={'class': 'form-control'}),
            'CA_NLARGO': forms.NumberInput(attrs={'class': 'form-control'}),
            'CA_BOBLIGATORIO': forms.CheckboxInput(attrs={'class':'form-check-input', 'type':'checkbox','id':"switch-s-1"}),
            'CA_BHABILITADO': forms.CheckboxInput(attrs={'class':'form-check-input', 'type':'checkbox','id':"switch-s-2"}),
            'CA_BVALIDARSAP': forms.CheckboxInput(attrs={'class':'form-check-input', 'type':'checkbox','id':"switch-s-3"}),
            'CA_CCODIGO': forms.TextInput(attrs={'class': 'form-control'}),
            'CA_BASIGNARVALOR': forms.CheckboxInput(attrs={'class':'form-check-input', 'type':'checkbox','id':"switch-s-4"}),
        }

#########################################
###              ETAPA               ###
#########################################
class formETAPA(forms.ModelForm):
    class Meta:
        # Asignación de la tabla ETAPA para crear el formulario
        model = ETAPA
        # Selección de campos a solicitar en el formulario
        fields = ['EP_NID',
                  'US_NID',
                  'ET_CTIPO',
                  'ET_CCODIGO',
                  'ET_CNOMBRE',
                  'ET_CDESCRIPCION',
                  'ET_FFECHAREGISTRO',
                  'ET_NCANTIDADMAXIMA',
                  'ET_TTIEMPOMAXIMO',
                  'ET_TTIEMPOMINIMO',
                  'ET_BHABILITADO',
                  'ET_BINTEGRARSAP',
                  'ET_CNUMEROOBJETOSAP',
                  'ET_CENDPOINT',
                  'ET_BISCABECERA',
                  'ET_BISLINEA',
                  'ET_NID_REF',
                  'ET_CNOMBREOBJETOSAP',
                  'ZON_NID',
                  'ET_BISADICIONAL',
                  ]
        labels = '__all__'
        # Widgets para el formulario
        widgets = {
            'EP_NID': forms.HiddenInput(attrs={'class': 'form-control', 'id': 'id_empresa'}),
            'US_NID': forms.Select(attrs={'class': 'form-control js-example-placeholder-multiple', 'id': 'id_usuario'}),
            'ET_CTIPO':forms.Select(attrs={'class': 'form-control js-example-placeholder-multiple', 'id': 'tipo_etapa'}),
            'ET_CCODIGO': forms.TextInput(attrs={'class': 'form-control', 'id': 'codigo_etapa'}),
            'ET_CNOMBRE': forms.TextInput(attrs={'class': 'form-control', 'id': 'nombre_etapa'}),
            'ET_CDESCRIPCION': forms.TextInput(attrs={'class': 'form-control', 'id': 'descripcion_etapa'}),
            'ET_FFECHAREGISTRO': forms.DateTimeInput(attrs={'class': 'form-control', 'type': 'datetime-local', 'id': 'fecha_registro_etapa'}),
            'ET_NCANTIDADMAXIMA': forms.NumberInput(attrs={'class': 'form-control', 'id': 'cantidad_maxima'}),
            'ET_TTIEMPOMAXIMO': forms.TimeInput(attrs={'class': 'form-control', 'type': 'time', 'id': 'tiempo_maximo'}),
            'ET_TTIEMPOMINIMO': forms.TimeInput(attrs={'class': 'form-control', 'type': 'time', 'id': 'tiempo_minimo'}),
            'ET_BHABILITADO': forms.CheckboxInput(attrs={'class':'form-check-input', 'type':'checkbox', 'id':"switch-s-2"}),
            'ET_BINTEGRARSAP': forms.CheckboxInput(attrs={'class':'form-check-input', 'type':'checkbox', 'id':"switch-s-3"}),
            'ET_CNUMEROOBJETOSAP': forms.TextInput(attrs={'class': 'form-control', 'id': 'numero_objeto_sap'}),
            'ET_CENDPOINT': forms.Select(choices=listarOpcionesTabla('"PM_CDESCRIPCION"', '"PM_CVALOR1"', 'PARAMETRO', '', '', '''"PM_CGRUPO" = 'ENDPOINTS' '''),attrs={'class': 'form-control', 'id': 'endpoint'}),
            'ET_BISCABECERA': forms.CheckboxInput(attrs={'class':'form-check-input', 'type':'checkbox', 'id':"switch-s-4"}),
            'ET_BISLINEA': forms.CheckboxInput(attrs={'class':'form-check-input', 'type':'checkbox', 'id':"switch-s-5"}),
            'ET_NID_REF': forms.Select(attrs={'class': 'form-control js-example-placeholder-multiple', 'id': 'id_etapa_ref'}),
            'ET_CNOMBREOBJETOSAP': forms.TextInput(attrs={'class': 'form-control', 'id': 'nombre_objeto_sap'}),
            'ZON_NID': forms.Select(attrs={'class': 'form-control', 'id': 'id_zona'}),
            'ET_BISADICIONAL': forms.CheckboxInput(attrs={'class':'form-check-input', 'type':'checkbox', 'id':"switch-s-6"}),
        }
#########################################
###              SECUENCIA           ###
#########################################
class formSECUENCIA(forms.ModelForm):
    class Meta:
        # Asignación de la tabla SECUENCIA para crear el formulario
        model = SECUENCIA
        # Selección de campos a solicitar en el formulario
        fields = [
            'EP_NID',
            'SE_CTIPO',
            'SE_CCODIGO',
            'SE_CNOMBRE',
            'SE_BHABILITADO',
            'SE_FFECHAREGISTRO'
        ]
        labels = '__all__'
        # Widgets para el formulario
        widgets = {
            'EP_NID': forms.HiddenInput(attrs={'class': 'form-control', 'id': 'id_empresa'}),
            'SE_CTIPO': forms.Select(attrs={'class': 'form-control js-example-placeholder-multiple', 'id': 'tipo_secuencia'}),
            'SE_CCODIGO': forms.TextInput(attrs={'class': 'form-control', 'id': 'codigo_secuencia'}),
            'SE_CNOMBRE': forms.TextInput(attrs={'class': 'form-control', 'id': 'nombre_secuencia'}),
            'SE_BHABILITADO': forms.CheckboxInput(attrs={'class':'form-check-input', 'type':'checkbox', 'id':"switch-s-2"}),
            'SE_FFECHAREGISTRO': forms.DateTimeInput(attrs={'class': 'form-control', 'type': 'datetime-local', 'id': 'fecha_registro_secuencia'}),
        }
#########################################
###           Usuarios empresa           ###
#########################################
class formUSERS_EMPRESA(forms.ModelForm):
    class Meta:
        # Asignación de la tabla SECUENCIA para crear el formulario
        model = USERS_EMPRESA
        # Selección de campos a solicitar en el formulario
        fields = [
            'EP_NID',
            'US_NID'
        ]
        labels = '__all__'
        # Widgets para el formulario
        widgets = {
            'EP_NID': forms.Select(attrs={'class': 'form-control js-example-placeholder-multiple', 'id': 'id_empresa'}),
            'US_NID': forms.Select(attrs={'class': 'form-control js-example-placeholder-multiple', 'id': 'id_usuario'}),
        }

#########################################
###          DETALLE SECUENCIA        ###
#########################################
class formDETALLESECUENCIA(forms.ModelForm):
    class Meta:
        # Asignación de la tabla SECUENCIA para crear el formulario
        model = DETALLE_SECUENCIA
        # Selección de campos a solicitar en el formulario
        fields = [
            'EP_NID',
            'SC_NID',
            'ET_NID',
            'SE_NPASO',
            'SE_BHABILITADO',
            'SE_BOBLIGATORIO',
            'USERS_RESPONSABLE_ID'
        ]
        labels = '__all__'
        # Widgets para el formulario
        widgets = {
            'EP_NID': forms.HiddenInput(attrs={'class': 'form-control', 'id': 'id_empresa'}),
            'SC_NID': forms.Select(attrs={'class': 'form-control js-example-placeholder-multiple', 'id': 'id_secuencia'}),
            'ET_NID': forms.Select(attrs={'class': 'form-control js-example-placeholder-multiple', 'id': 'id_etapa'}),
            'SE_NPASO': forms.TextInput(attrs={'class': 'form-control', 'id': 'paso'}),
            'SE_BHABILITADO': forms.CheckboxInput(attrs={'class':'form-check-input', 'type':'checkbox', 'id':"switch-s-2"}),
            'SE_BOBLIGATORIO': forms.CheckboxInput(attrs={'class':'form-check-input', 'type':'checkbox', 'id':"switch-s-3"}),
            'USERS_RESPONSABLE_ID': forms.SelectMultiple(choices=get_actuve_users(),attrs={'class': 'js-example-responsive col-sm-12', 'id': 'id_usuario_responsable', 'placeholder': 'Seleccione usuarios responsables'}),
         }
#########################################
###              DETALLE ETAPA        ###
#########################################
class formDETALLE_ETAPA(forms.ModelForm):
    class Meta:
        # Asignación de la tabla DETALLE_ETAPA para crear el formulario
        model = DETALLE_ETAPA
        # Selección de campos a solicitar en el formulario
        fields = [
                  'EP_NID',
                  'ET_NID',
                  'CAMP_NID',
                  'DET_NPASO',
                  'DET_CETIQUETAETAPA',
                  'DET_BOBLIGATORIO',
                  'DET_BHABILITADO'
                  ]
        labels = '__all__'
        # Widgets para el formulario
        widgets = {
            'EP_NID': forms.HiddenInput(attrs={'class': 'form-control', 'id': 'id_empresa'}),
            'ET_NID': forms.Select(attrs={'class': 'form-control js-example-placeholder-multiple', 'id': 'id_etapa'}),
            'CAMP_NID': forms.Select(attrs={'class': 'form-control js-example-placeholder-multiple', 'id': 'id_campo'}),
            'DET_NPASO': forms.NumberInput(attrs={'class': 'form-control', 'id': 'numero_paso'}),
            'DET_BOBLIGATORIO': forms.CheckboxInput(attrs={'class':'form-check-input', 'type':'checkbox', 'id':"switch-s-1"}),
            'DET_CETIQUETAETAPA': forms.TextInput(attrs={'class': 'form-control', 'id': 'etiqueta_etapa'}),
            'DET_BHABILITADO': forms.CheckboxInput(attrs={'class':'form-check-input', 'type':'checkbox', 'id':"switch-s-2"}),
        }
#########################################
###     CAMPOS-OPCIONES               ###
#########################################
class formCAMPO_OPCIONES(forms.ModelForm):
    class Meta:
        #Asignacion de la tabla LISTADO_DOCUMENTO para crear el formulario
        model = CAMPO_OPCION
        fields = ['US_NID',
                  'EP_NID',
                  'CAMP_NID',
                  'CA_CTABLA',
                  'CA_CNOMBRECAMPO',
                  'CA_BHABILITADO',
                  ]
        labels = '__all__'
        #Widgets para el formulario
        widgets = {
            'EP_NID': forms.Select(attrs={'class': 'form-control', 'id': 'id_empresa'}),
            'US_NID': forms.HiddenInput(attrs={'class': 'form-control js-example-placeholder-multiple'}),
            'CAMP_NID': forms.Select(attrs={'class': 'form-control js-example-placeholder-multiple'}),
            'CA_CTABLA': forms.TextInput(attrs={'class': 'form-control', 'id': 'valor'}),
            'CA_CNOMBRECAMPO': forms.TextInput(attrs={'class': 'form-control', 'id': 'etiqueta'}),
            'CA_BHABILITADO': forms.CheckboxInput(attrs={'class':'form-check-input', 'type':'checkbox','id':"switch-s-2"}),
        }

#########################################
###      FORMULARIO TARIFA            ###
#########################################


class formTARIFA_GLOBAL(forms.ModelForm):
    class Meta:
        #Asignacion de la tabla TARIFA_GLOBAL para crear el formulario
        model = TARIFA_GLOBAL
        #Seleccion de campos a solicitar en el formulario
        fields = ['EP_NID', 'RUT_NID', 'SN_NID', 'TAR_NVALOR', 'TAR_NVALORPREVIO', 'TAR_CNOMBRETARIFA', 'TAR_CTIPOTARIFA', 'TAR_CDIVISA', 'TAR_FFECHAREGISTRO', 'TAR_FFECHAULTIMAMODIFICACION', 'TAR_BHABILITADO']
        labels = '__all__'
        #Widgets para el formulario
        widgets = {
            'EP_NID': forms.HiddenInput(attrs={'class': 'form-control' ,'id': 'id_empresa'}),
            'RUT_NID': forms.Select(attrs={'class': 'form-control js-example-placeholder-multiple', 'placeholder':'Seleccione una ruta' ,'id': 'id_ruta'}),
            'SN_NID': forms.Select(attrs={'class': 'form-control js-example-placeholder-multiple', 'placeholder':'Seleccione un socio de negocio' ,'id': 'id_socio_negocio'}),
            'TAR_NVALOR': forms.NumberInput(attrs={'class': 'form-control', 'placeholder':'Valor de la tarifa' ,  'id': 'valor_tarifa'}),
            'TAR_NVALORPREVIO': forms.NumberInput(attrs={'class': 'form-control', 'placeholder':'Valor de la tarifa anterior' ,  'id': 'valor_previo_tarifa'}),
            'TAR_CNOMBRETARIFA': forms.TextInput(attrs={'class': 'form-control', 'id': 'nombre_tarifa'}),
            'TAR_CTIPOTARIFA': forms.Select(choices=listarOpcionesTabla('"PM_CDESCRIPCION"', '"PM_CVALOR1"', 'PARAMETRO', '', '', '''"PM_CGRUPO" = 'TIPO_TARIFA' '''), attrs={'class': 'form-control',  'id': 'tipo_tarifa'}),
            'TAR_CDIVISA': forms.Select(choices=listarOpcionesTabla('"PM_CDESCRIPCION"', '"PM_CVALOR1"', 'PARAMETRO', '', '', '''"PM_CGRUPO" = 'DIVISA' '''), attrs={'class': 'form-control',  'id': 'divisa'}),
            'TAR_FFECHAREGISTRO': forms.DateInput(attrs={'class': 'form-control', 'type': 'date',  'id': 'fecha_registro'}),
            'TAR_FFECHAULTIMAMODIFICACION': forms.DateInput(attrs={'class': 'form-control', 'type': 'date',  'id': 'fecha_ultima_modificacion'}),
            'TAR_BHABILITADO': forms.CheckboxInput(attrs={'class':'form-check-input', 'type':'checkbox','id':"switch-s-1"}),
        }

#########################################
###      FORMULARIO RUTA              ###
#########################################

class formRUTA(forms.ModelForm):
    class Meta:
        #Asignacion de la tabla RUTA para crear el formulario
        model = RUTA
        #Seleccion de campos a solicitar en el formulario
        fields = [
            'EP_NID', 
            'RG_NID_INICIO', 
            'PV_NID_INICIO', 
            'COM_NID_INICIO', 
            'RG_NID_TERMINO', 
            'PV_NID_TERMINO', 
            'COM_NID_TERMINO', 
            'RUT_NTIEMPOMAXIMOENTREGA', 
            'RUT_NTIEMPOESTADIAPLANTA', 
            'RUT_CNOMBRE', 
            'RUT_CCODIGO', 
            'RUT_CCOMENTARIO', 
            'RUT_FFECHAREGISTRO',
            'RUT_BHABILITADO']
        labels = '__all__'
        #Widgets para el formulario
        widgets = {
            'EP_NID': forms.HiddenInput(attrs={'class': 'form-control', 'placeholder':'Seleccione una empresa' ,'id': 'id_empresa'}),
            'RG_NID_INICIO': forms.Select(attrs={'class': 'form-control', 'placeholder':'Seleccione una región' ,'id': 'id_region_inicio'}),
            'PV_NID_INICIO': forms.Select(attrs={'class': 'form-control', 'placeholder':'Seleccione una provincia' ,'id': 'id_provincia_inicio'}),
            'COM_NID_INICIO': forms.Select(attrs={'class': 'form-control', 'placeholder':'Seleccione una comuna' ,'id': 'id_comuna_inicio'}),
            'RG_NID_TERMINO': forms.Select(attrs={'class': 'form-control', 'placeholder':'Seleccione una región' ,'id': 'id_region_termino'}),
            'PV_NID_TERMINO': forms.Select(attrs={'class': 'form-control', 'placeholder':'Seleccione una provincia' ,'id': 'id_provincia_termino'}),
            'COM_NID_TERMINO': forms.Select(attrs={'class': 'form-control', 'placeholder':'Seleccione una comuna' ,'id': 'id_comuna_termino'}),
            'RUT_NTIEMPOMAXIMOENTREGA': forms.NumberInput(attrs={'class': 'form-control', 'placeholder':'Cantidad de horas' ,'id': 'tiempo_maximo_entrega'}),
            'RUT_NTIEMPOESTADIAPLANTA': forms.NumberInput(attrs={'class': 'form-control', 'placeholder':'Cantidad de horas' ,'id': 'tiempo_estadia_planta'}),
            'RUT_CNOMBRE': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Nombre de la ruta',  'id': 'nombre_ruta'}),
            'RUT_CCODIGO': forms.TextInput(attrs={'class': 'form-control', 'placeholder':'Código de la ruta' ,'id': 'codigo_ruta'}),
            'RUT_CCOMENTARIO': forms.Textarea(attrs={'class': 'form-control', 'placeholder':'Comentario de la ruta' ,'id': 'comentario_ruta'}),
            'RUT_FFECHAREGISTRO': forms.DateInput(attrs={'class': 'form-control', 'type': 'date',  'id': 'fecha_registro'}),
            'RUT_BHABILITADO': forms.CheckboxInput(attrs={'class':'form-check-input', 'type':'checkbox','id':"switch-s-1"}),
        }

########################################
###     FORMULARIO PLANIFICACION     ###
########################################
class formPLANIFICACION(forms.ModelForm):
    class Meta:
        model = PLANIFICACION
        #Asignacion de la tabla PLANIFICACION para crear el formulario
        fields = ['US_NID', 'EP_NID', 'CAL_NID', 'PL_CTIPOCUPO', 'PL_FFECHAINICIO', 'PL_FFECHAFIN', 'PL_NCANTIDADCUPOS', 'PL_NSOBRECUPO', 'PL_FFECHAREGISTRO']
        labels = '__all__'
        #Widgets para el formulario
        widgets = {
            'EP_NID': forms.Select(attrs={'class': 'form-control js-example-placeholder-multiple', 'placeholder': 'Seleccione una empresa','id': 'id_empresa'}),
            'CAL_NID': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Seleccione una empresa','id': 'id_calendario'}),
            'PL_CTIPOCUPO': forms.Select(attrs={'class': 'form-control js-example-placeholder-multiple','placeholder': 'Seleccione un tipo de planificación', 'id': 'id_tipo_cupo'}),
            'PL_FFECHAINICIO': forms.DateTimeInput(attrs={'class': 'form-control', 'id': 'fecha_inicio_id', 'type': 'datetime-local'}),
            'PL_FFECHAFIN': forms.DateTimeInput(attrs={'class': 'form-control', 'id': 'fecha_termino_id', 'type': 'datetime-local'}),
            'PL_NCANTIDADCUPOS': forms.NumberInput(attrs={'class': 'form-control', 'placeholder': 'Ingrese cantidad de cupos', 'id': 'cantidad_cupos_id'})
        }

########################################
###         FORMULARIO EXTRA         ###
########################################
class formEXTRA(forms.ModelForm):
    class Meta:
        model = EXTRA
        #Asignacion de la tabla EXTRA para crear el formulario
        fields = ['EP_NID', 'EXT_CNOMBRE', 'EXT_BHABILITADO', 'EXT_BINGRESO', 'EXT_FFECHAREGISTRO', 'US_NID', 'EXT_CDESCRIPCION', 'EXT_CTIPO_CITACION']
        labels = '__all__'
        #Widgets para el formulario
        widgets = {
            'EP_NID': forms.HiddenInput(attrs={'class': 'form-control', 'placeholder':'Seleccione una empresa' ,'id': 'id_empresa'}),
            'EXT_CNOMBRE': forms.TextInput(attrs={'class': 'form-control', 'id': 'nombre_extra_id'}),
            'EXT_BHABILITADO': forms.CheckboxInput(attrs={'class':'form-check-input', 'type':'checkbox','id':"switch-s-1"}),
            'EXT_BINGRESO': forms.CheckboxInput(attrs={'class':'form-check-input', 'type':'checkbox','id':"switch-s-2"}),
            'EXT_CDESCRIPCION': forms.TextInput(attrs={'class': 'form-control'}),
            'EXT_CTIPO_CITACION': forms.Select(attrs={'class': 'form-control js-example-placeholder-multiple','placeholder': 'Seleccione un tipo de citación', 'id': 'id_tipo_citacion'}),
        }

########################################
###    FORMULARIO CITACION EXTRA     ###
########################################
class formCITACION_EXTRA(forms.ModelForm):
    class Meta:
        #Asignacion de la tabla CITACION_EXTRA para crear el formulario
        model = CITACION_EXTRA
        #Seleccion de campos a solicitar en el formulario
        fields = ['EP_NID', 'US_NID', 'EXT_NID', 'CI_NID', 'CIE_NVALOR', 'CIE_FFECHAREGISTRO', 'CIE_BINGRESO', 'CIE_CCOMENTARIO']
        labels = '__all__'
        #Widgets para el formulario
        widgets = {
            'EP_NID': forms.HiddenInput(attrs={'class': 'form-control', 'placeholder':'Seleccione una empresa' ,'id': 'id_empresa'}),
            'CI_NID': forms.Select(attrs={'class': 'form-control js-example-placeholder-multiple', 'placeholder':'Seleccione una citación' ,'id': 'id_citacion'}),
            'EXT_NID': forms.Select(attrs={'class': 'form-control js-example-placeholder-multiple', 'placeholder':'Seleccione un extra' ,'id': 'id_extra'}),
            'CIE_NVALOR': forms.NumberInput(attrs={'class': 'form-control', 'placeholder':'Valor del extra' ,  'id': 'valor_extra', 'type': 'number'}),
            'CIE_BINGRESO': forms.CheckboxInput(attrs={'class':'form-check-input', 'type':'checkbox','id':"switch-s-1"}),
            'CIE_CCOMENTARIO': forms.Textarea(attrs={'class': 'form-control', 'placeholder':'Comentario del extra' ,'id': 'comentario_extra'}),
        }

########################################
###        FORMULARIO USUARIO        ###
########################################

class SignUpForm(UserCreationForm):
    username = forms.CharField(
        widget=forms.TextInput(
            attrs={
                "placeholder": "Nombre de usuario",
                "class": "form-control"
            }
        ))
    first_name = forms.CharField(
        widget=forms.TextInput(
            attrs={
                "placeholder": "Nombre",
                "class": "form-control"
            }
        ))
    last_name = forms.CharField(
        widget=forms.TextInput(
            attrs={
                "placeholder": "Apellido",
                "class": "form-control"
            }
        ))
    email = forms.EmailField(
        widget=forms.EmailInput(
            attrs={
                "placeholder": "Email",
                "class": "form-control"
            }
        ))
    password1 = forms.CharField(
        widget=forms.PasswordInput(
            attrs={
                "placeholder": "Contraseña",
                "class": "form-control"
            }
        ))
    password2 = forms.CharField(
        widget=forms.PasswordInput(
            attrs={
                "placeholder": "Confirmar contraseña",
                "class": "form-control"
            }
        ))
    perfil = forms.ModelChoiceField(
        queryset=PERFIL.objects.all(),
        widget=forms.Select(
            attrs={
                "class": "form-control",
                "placeholder": "Seleccione un perfil"
            }
        ))
    empresa = forms.ModelChoiceField(
        queryset=EMPRESA.objects.all(),
        widget=forms.Select(
            attrs={
                "class": "form-control",
                "placeholder": "Seleccione una empresa"
            }
        ))
    class Meta:
        model = User
        fields = ('username', 'first_name', 'last_name', 'email', 'password1', 'password2', 'perfil', 'empresa')

    def save(self, commit=True):
        user = super().save(commit=False)
        perfil = self.cleaned_data['perfil']
        empresa = self.cleaned_data['empresa']
        nombre_perfil = perfil.PR_CNOMBRE
        if commit:
            user.save()
            users_empresa = USERS_EMPRESA.objects.create(
                US_NID=user,
                EP_NID=empresa
            )
            users_extension = USERS_EXTENSION.objects.create(
                US_NID=user
            )
            perfil_usuario = PERFIL_USUARIO.objects.create(
                US_NID = user,
                PR_NID = perfil
            )
            if nombre_perfil == 'Administrador de Secuencia':
                users_extension.UX_IS_ADMINISTRADOR_SECUENCIA = True
            elif nombre_perfil == 'Administrador de Etapa':
                users_extension.UX_IS_ADMINISTRADOR_ETAPA = True
            elif nombre_perfil == 'Planificador':
                users_extension.UX_IS_PLANIFICADOR = True
            elif nombre_perfil == 'Recepcionista':
                users_extension.UX_IS_RECEPCIONISTA = True
            elif nombre_perfil == 'Cliente':
                users_extension.UX_IS_CLIENTE = True
            elif nombre_perfil == 'Proveedor':
                users_extension.UX_IS_PROVEEDOR = True
            elif nombre_perfil == 'Operador':
                users_extension.UX_IS_OPERADOR = True
            elif nombre_perfil == 'Reportes':
                users_extension.UX_IS_REPORTES = True
            elif nombre_perfil == 'Proforma':
                users_extension.UX_IS_PROFORMA = True
            users_extension.save()
            users_empresa.save()
        return user

class UserSimpleUpdateForm(forms.ModelForm):
    username = forms.CharField(
        widget=forms.TextInput(
            attrs={
                "placeholder": "Nombre de usuario",
                "class": "form-control"
            }
        ))
    password1 = forms.CharField(
        required=False,  # Hacemos la contraseña opcional
        widget=forms.PasswordInput(
            attrs={
                "placeholder": "Nueva contraseña (dejar en blanco para mantener la actual)",
                "class": "form-control"
            }
        ))
    password2 = forms.CharField(
        required=False,  # Hacemos la confirmación opcional
        widget=forms.PasswordInput(
            attrs={
                "placeholder": "Confirmar nueva contraseña",
                "class": "form-control"
            }
        ))

    class Meta:
        model = User
        fields = ('username',)  # Solo incluimos username en los campos del modelo

    def clean(self):
        cleaned_data = super().clean()
        password1 = cleaned_data.get('password1')
        password2 = cleaned_data.get('password2')

        if password1 or password2:  # Solo validamos si se ingresó alguna contraseña
            if password1 != password2:
                raise forms.ValidationError("Las contraseñas no coinciden")
        return cleaned_data

    def save(self, commit=True):
        user = super().save(commit=False)
        # Si se proporcionó una nueva contraseña, la actualizamos
        if self.cleaned_data.get('password1'):
            user.set_password(self.cleaned_data['password1'])
        if commit:
            user.save()
        return user

class SetPasswordForm(forms.Form):
    """
    A form that lets a user set their password without entering the old
    password
    """

    error_messages = {
        "password_mismatch": _("The two password fields didn’t match."),
    }
    new_password1 = forms.CharField(
        label=_("New password"),
        widget=forms.PasswordInput(attrs={"autocomplete": "new-password"}),
        strip=False,
        help_text=password_validation.password_validators_help_text_html(),
    )
    new_password2 = forms.CharField(
        label=_("New password confirmation"),
        strip=False,
        widget=forms.PasswordInput(attrs={"autocomplete": "new-password"}),
    )

    def __init__(self, user, *args, **kwargs):
        self.user = user
        super().__init__(*args, **kwargs)

    def clean_new_password2(self):
        password1 = self.cleaned_data.get("new_password1")
        password2 = self.cleaned_data.get("new_password2")
        if password1 and password2 and password1 != password2:
            raise ValidationError(
                self.error_messages["password_mismatch"],
                code="password_mismatch",
            )
        password_validation.validate_password(password2, self.user)
        return password2

    def save(self, commit=True):
        password = self.cleaned_data["new_password1"]
        self.user.set_password(password)
        if commit:
            self.user.save()
        return self.user

class PasswordChangeForm(SetPasswordForm):
    """
    A form that lets a user change their password by entering their old
    password.
    """

    error_messages = {
        **SetPasswordForm.error_messages,
        "password_incorrect": _(
            "Your old password was entered incorrectly. Please enter it again."
        ),
    }
    old_password = forms.CharField(
        label=_("Old password"),
        strip=False,
        widget=forms.PasswordInput(
            attrs={"autocomplete": "current-password", "autofocus": True}
        ),
    )

    field_order = ["old_password", "new_password1", "new_password2"]

    def clean_old_password(self):
        """
        Validate that the old_password field is correct.
        """
        old_password = self.cleaned_data["old_password"]
        if not self.user.check_password(old_password):
            raise ValidationError(
                self.error_messages["password_incorrect"],
                code="password_incorrect",
            )
        return old_password

########################################
###    FORMULARIO CUPO PROVEEDOR     ###
########################################

class formCUPO_PROVEEDOR(forms.ModelForm):
    class Meta:
        model = CUPO_PROVEEDOR
        fields = ['EP_NID', 'PRO_NID', 'PLA_NID', 'CUP_NCUPOS', 'CUP_BSOBRECUPO']
        labels = '__all__'
        widgets = {
            'EP_NID': forms.HiddenInput(attrs={'class': 'form-control', 'placeholder':'Seleccione una empresa' ,'id': 'id_empresa'}),
            'PLA_NID': forms.Select(attrs={'class': 'form-control js-example-placeholder-multiple', 'placeholder':'Seleccione una planificacion' ,'id': 'id_planificacion'}),
            'PRO_NID': forms.Select(attrs={'class': 'form-control js-example-placeholder-multiple', 'placeholder':'Seleccione un proveedor' ,'id': 'id_proveedor'}),
            'CUP_NCUPOS': forms.NumberInput(attrs={'class': 'form-control', 'placeholder':'Ingrese cantidad de cupos' ,'id': 'cantidad_cupos'}),
        }

########################################
###         FORMULARIO ZONA          ###
########################################

class formZONA(forms.ModelForm):
    class Meta:
        model = ZONA
        fields = ['EP_NID', 'ZON_CNOMBRE', 'ZON_CLATITUD1', 'ZON_CLONGITUD1', 'ZON_CLATITUD2', 'ZON_CLONGITUD2', 'ZON_CLATITUD3', 'ZON_CLONGITUD3', 'ZON_CLATITUD4', 'ZON_CLONGITUD4', 'ZON_CDESCRIPCION', 'ZON_BHABILITADO', 'ZON_CCOLOR','ZON_NCANTIDADCUPOS']
        labels = '__all__'
        widgets = {
            'EP_NID': forms.HiddenInput(attrs={'class': 'form-control', 'placeholder':'Seleccione una empresa' ,'id': 'id_empresa'}),
            'ZON_CNOMBRE': forms.TextInput(attrs={'class': 'form-control', 'placeholder':'Ingrese nombre de la zona' ,'id': 'nombre_zona'}),
            'ZON_CLATITUD1': forms.NumberInput(attrs={'class': 'form-control', 'placeholder':'Ingrese latitud 1' ,'id': 'latitud1'}),
            'ZON_CLONGITUD1': forms.NumberInput(attrs={'class': 'form-control', 'placeholder':'Ingrese longitud 1' ,'id': 'longitud1'}),
            'ZON_CLATITUD2': forms.NumberInput(attrs={'class': 'form-control', 'placeholder':'Ingrese latitud 2' ,'id': 'latitud2'}),
            'ZON_CLONGITUD2': forms.NumberInput(attrs={'class': 'form-control', 'placeholder':'Ingrese longitud 2' ,'id': 'longitud2'}),
            'ZON_CLATITUD3': forms.NumberInput(attrs={'class': 'form-control', 'placeholder':'Ingrese latitud 3' ,'id': 'latitud3'}),
            'ZON_CLONGITUD3': forms.NumberInput(attrs={'class': 'form-control', 'placeholder':'Ingrese longitud 3' ,'id': 'longitud3'}),
            'ZON_CLATITUD4': forms.NumberInput(attrs={'class': 'form-control', 'placeholder':'Ingrese latitud 4' ,'id': 'latitud4'}),
            'ZON_CLONGITUD4': forms.NumberInput(attrs={'class': 'form-control', 'placeholder':'Ingrese longitud 4' ,'id': 'longitud4'}),
            'ZON_CDESCRIPCION': forms.Textarea(attrs={'class': 'form-control', 'placeholder':'Ingrese descripcion de la zona' ,'id': 'descripcion_zona'}),
            'ZON_BHABILITADO': forms.CheckboxInput(attrs={'class':'form-check-input', 'type':'checkbox','id':"switch-s-1"}),
            'ZON_CCOLOR': forms.TextInput(attrs={'class': 'form-control', 'type':'color', 'placeholder':'Ingrese color de la zona' ,'id': 'color_zona'}),
            'ZON_NCANTIDADCUPOS': forms.NumberInput(attrs={'class':'form-control', 'placeholder':'Ingrese cantidad de cupos', 'id':'cantidad_cupos'}),
        }

