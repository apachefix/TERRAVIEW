# -*- encoding: utf-8 -*-
"""
Copyright (c) 2019 - present AppSeed.us
"""

from django.db import models
from django.contrib.auth.models import User
from django import template
from django.utils import timezone
from datetime import date

from datetime import timedelta, datetime

from apps.home.general_postgres import *

register = template.Library()
# Create your models here.

###################################################################################################
################################## MODELO DE ETAPA 1 ##############################################
###################################################################################################
class SAP_OPOR_PROGRAMACION(models.Model):

    EP_NID = models.ForeignKey(
        'EMPRESA',
        verbose_name='Empresa',
        on_delete=models.PROTECT
    )

    # SAP
    SOP_DOCENTRY = models.CharField(max_length=50)

    # N PEDIDO
    SOP_DOCNUM = models.CharField(max_length=50)

    # ESTADO DOCUMENTO
    SOP_DOCSTATUS = models.CharField(max_length=10, blank=True, null=True)

    # CODIGO PROVEEDOR
    SOP_CARDCODE = models.CharField(max_length=50, blank=True, null=True)

    # NOMBRE PROVEEDOR
    SOP_CARDNAME = models.CharField(max_length=255, blank=True, null=True)

    # FECHAS SAP
    SOP_DOCDATE = models.DateTimeField(blank=True, null=True)
    SOP_TAXDATE = models.DateTimeField(blank=True, null=True)
    SOP_DOCDUEDATE = models.DateTimeField(blank=True, null=True)
    SOP_CREATEDATE = models.DateTimeField(blank=True, null=True)

    # CODIGO PRODUCTO
    SOP_ITEMCODE = models.CharField(max_length=50, blank=True, null=True)

    # DESCRIPCION PRODUCTO
    SOP_DSCRIPTIONS = models.CharField(max_length=255, blank=True, null=True)

    # CANTIDAD DISPONIBLE
    SOP_OPENQTY = models.DecimalField(
        max_digits=18,
        decimal_places=4,
        default=0
    )

    # BL / CONTENEDOR
    SOP_CONTENEDOR = models.CharField(
        max_length=100,
        blank=True,
        null=True
    )

    # PRODUCTOR
    SOP_PRODUCTOR = models.CharField(
        max_length=255,
        blank=True,
        null=True
    )

    SOP_BHABILITADO = models.BooleanField(default=True)

    SOP_FFECHAREGISTRO = models.DateTimeField(auto_now_add=True)
    SOP_FFECHAACTUALIZACION = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'SAP_OPOR_PROGRAMACION'

        constraints = [
            models.UniqueConstraint(
                fields=['EP_NID', 'SOP_DOCENTRY', 'SOP_ITEMCODE'],
                name='unique_sap_opor_empresa_docentry_item'
            )
        ]

    def __str__(self):
        return f'{self.SOP_DOCNUM} - {self.SOP_ITEMCODE}'
class EMPRESA(models.Model):
    EP_CRAZONSOCIAL = models.CharField(("Razón social"), max_length=128, null=False)
    EP_CRUT = models.CharField(("Rut"), max_length=128, null=False)
    EP_CEMAIL = models.CharField(("Email"), max_length=128, null=True, blank=True)
    EP_CTELEFONO = models.CharField(("Teléfono"), max_length=128, null=True, blank=True)
    EP_CDIRECCION = models.CharField(("Dirección"), max_length=256, null=True, blank=True)
    EP_CBASEDATOS = models.CharField(("Nombre base de datos"), max_length=128, null=False)
    EP_CUSUARIOSBD = models.CharField(("Usuario base de datos"), max_length=128, null=False)
    EP_CPASSWORDBD = models.CharField(("Contraseña base de datos"), max_length=128, null=True)
    EP_CPORT = models.CharField(("Puerto base de datos"), max_length=128, null=False)
    EP_CHOST = models.CharField(("Host base de datos"), max_length=128, null=True)
    EP_CSERVER = models.CharField(("Server SAP"), max_length=128, null=True)
    EP_CLISENCESERVER = models.CharField(("Server SAP"), max_length=128, null=True)
    EP_CDB_SERVER_TYPE = models.CharField(("Tipo de base de datos"), max_length=128, null=True)
    EP_CUSER_SAP = models.CharField(("Usuario SAP"), max_length=128, null=True)
    EP_CPASSWORD_SAP = models.CharField(("Contraseña SAP"), max_length=128, null=True)

    class Meta:
        db_table = "EMPRESA"
    
    def __str__(self):
        return self.EP_CRAZONSOCIAL
    def get_pk(self):
        return self.pk

class SYSLOGGER(models.Model):
    US_NID = models.ForeignKey(User, verbose_name='id usuario', on_delete=models.PROTECT)
    EP_NID = models.ForeignKey(EMPRESA, verbose_name='Id empresa', on_delete=models.PROTECT)
    LOG_FFECHAREGISTRO = models.DateTimeField(("Fecha Registro"),null=True,blank=True)
    LOG_CMODULO = models.CharField(("Modulo Origen"),max_length=128,null=True,blank=True)
    LOG_CDESCRIPCION = models.CharField(("Descripcion"),max_length=1024,null=True,blank=True)
    LOG_COPERACION =  models.CharField(("Operación"),max_length=24,null=True,blank=True)
    LOG_CADD1 = models.CharField(("Info Add 1"),max_length=128,null=True,blank=True)
    LOG_CADD2 = models.CharField(("Info Add 2"),max_length=128,null=True,blank=True)
    
    class Meta:
        db_table = 'SYSLOGGER'

    def __str__(self):
        return self.pk

class USERS_EXTENSION(models.Model):
    US_NID = models.OneToOneField(User, related_name='userv', on_delete=models.CASCADE)
    UX_IS_ADMINISTRADOR_SECUENCIA = models.BooleanField(("Es administrador de secuencias"), default=False)
    UX_IS_ADMINISTRADOR_ETAPA = models.BooleanField(("Es administrador de etapas"), default=False)
    UX_IS_PLANIFICADOR = models.BooleanField(("Es planificador"), default=False)
    UX_IS_RECEPCIONISTA = models.BooleanField(("Es recepcionista"), default=False)
    UX_IS_CLIENTE = models.BooleanField(("Es cliente"), default=False)
    UX_IS_PROVEEDOR = models.BooleanField(("Es proveedor"), default=False)
    UX_IS_CONDUCTOR = models.BooleanField(("Es conductor"), default=False)
    UX_IS_OPERADOR = models.BooleanField(("Es operador"), default=False)
    UX_IS_REPORTES = models.BooleanField(("Es reportes"), default=False)
    UX_IS_PROFORMA = models.BooleanField(("Es proforma"), default=False)
    UX_IS_TERRAMAR = models.BooleanField(("Es de Terramar Chile"), default=False)
    UX_IS_ACEITES = models.BooleanField(("Es de Aceites SBH"), default=False)
    UX_IS_ADMINISTRADOR_CONDUCTOR = models.BooleanField(("Es administrador de conductor"), default=False)
    class Meta:
        db_table = 'USERS_EXTENSION'

class USERS_EMPRESA(models.Model):
    US_NID = models.ForeignKey(
        User,
        related_name='empresas_asignadas',
        on_delete=models.CASCADE
    )
    EP_NID = models.ForeignKey(
    'EMPRESA',
        verbose_name='Id empresa',
        on_delete=models.PROTECT
    )

    class Meta:
        db_table = 'USERS_EMPRESA'
        constraints = [
            models.UniqueConstraint(
                fields=['US_NID', 'EP_NID'],
                name='unique_usuario_empresa'
            )
        ]

class REGION(models.Model):
    RG_CNOMBRE = models.CharField(("Nombre region"), max_length=128, null=False)
    RG_CCODIGO = models.CharField(("Codigo region"), max_length=128, null=False)

    class Meta:
        db_table = "REGION"

    def __str__(self):
        return self.RG_CNOMBRE
    def get_pk(self):
        return self.pk

class PROVINCIA(models.Model):
    RG_NID = models.ForeignKey(REGION, verbose_name='region_id', on_delete=models.PROTECT)
    PV_CNOMBRE = models.CharField(("Nombre provincia"), max_length=128, null=False)
    PV_CCODIGO = models.CharField(("Codigo provincia"), max_length=128, null=False)

    class Meta:
        db_table = 'PROVINCIA'

    def __str__(self):
        return self.PV_CNOMBRE
    def get_pk(self):
        return self.pk

class COMUNA(models.Model):
    PV_NID = models.ForeignKey(PROVINCIA, verbose_name="provincia_id", on_delete=models.PROTECT)
    COM_CNOMBRE = models.CharField(("Nombre comuna"), max_length=128, null=False)
    COM_CCODIGO = models.CharField(("Codigo comuna"), max_length=128, null=False)

    class Meta:
        db_table = "COMUNA"
    def __str__(self):
        return self.COM_CNOMBRE

class PARAMETRO(models.Model):
    PM_CGRUPO = models.CharField(("Grupo Parametro"),max_length=128,null=False)
    PM_CCODIGO = models.CharField(("Codigo Parametro"),max_length=128,null=False)
    PM_CDESCRIPCION = models.CharField(("Descripcion"),max_length=2048)
    PM_CVALOR1 = models.CharField(("Valor Texto 1"),max_length=2048)
    PM_CVALOR2 = models.CharField(("Valor Texto 2"),max_length=2048, blank=True,null=True)
    PM_CVALOR3 = models.CharField(("Valor Texto 3"),max_length=2048, blank=True,null=True)
    PM_NVALOR1 = models.DecimalField(("Valor Numerico 1"),max_digits=18,decimal_places=5,blank=True,null=True)
    PM_NVALOR2 = models.DecimalField(("Valor Numerico 2"),max_digits=18,decimal_places=5,blank=True,null=True)
    PM_NVALOR3 = models.DecimalField(("Valor Numerico 3"),max_digits=18,decimal_places=5,blank=True,null=True)

    class Meta:
        db_table = 'PARAMETRO'
        unique_together = (('PM_CGRUPO', 'PM_CCODIGO'),)

    def __str__(self):
        return self.PM_CCODIGO

class ZONA(models.Model):
    EP_NID = models.ForeignKey(EMPRESA, verbose_name='Id empresa', on_delete=models.PROTECT)
    ZON_CNOMBRE = models.CharField(("Nombre"), max_length=128, null=True, blank=True)
    ZON_CLATITUD1 = models.CharField(("Latitud 1"), max_length=128, null=True, blank=True)
    ZON_CLONGITUD1 = models.CharField(("Longitud 1"), max_length=128, null=True, blank=True)
    ZON_CLATITUD2 = models.CharField(("Latitud 2"), max_length=128, null=True, blank=True)
    ZON_CLONGITUD2 = models.CharField(("Longitud 2"), max_length=128, null=True, blank=True)
    ZON_CLATITUD3 = models.CharField(("Latitud 3"), max_length=128, null=True, blank=True)
    ZON_CLONGITUD3 = models.CharField(("Longitud 3"), max_length=128, null=True, blank=True)
    ZON_CLATITUD4 = models.CharField(("Latitud 4"), max_length=128, null=True, blank=True)
    ZON_CLONGITUD4 = models.CharField(("Longitud 4"), max_length=128, null=True, blank=True)
    ZON_CDESCRIPCION = models.TextField(("Descripcion"), null=True, blank=True)
    ZON_BHABILITADO = models.BooleanField(("Habilitado"), default=True)
    ZON_CCOLOR = models.CharField(("Color"), max_length=128, null=True, blank=True)
    ZON_NCANTIDADCUPOS = models.IntegerField(("Cantidad de cupos"), null=True)

    class Meta:
        db_table = "ZONA"

    def __str__(self):
        return self.ZON_CNOMBRE
    

class CALENDARIO(models.Model):
    US_NID = models.ForeignKey(User, verbose_name='Id usuario', on_delete=models.PROTECT, null=True)
    EP_NID = models.ForeignKey(EMPRESA, verbose_name='Id empresa', on_delete=models.PROTECT, null=True)
    CA_CNOMBRE = models.CharField(("Nombre calendario"), max_length=128, null=True, blank=True)
    CA_FHORA_APERTURA = models.TimeField(("Hora de apertura"), null=True, default='08:00')
    CA_FHORA_CIERRE = models.TimeField(("Hora de cierre"), null=True, default='15:00')
    CA_NDIA = models.IntegerField(("Dia"), null=False)
    CA_NMES = models.IntegerField(("Mes"), null=False)
    CA_NANO = models.IntegerField(("Año"), null=False)
    CA_NCANTIDADCUPOS = models.IntegerField(("Cantidad de cupos"), null=False)
    CA_BIS_FERIADO = models.BooleanField(("Es feriado"), default=False)
    CA_BHABILITADO = models.BooleanField(("Habilitado"), default=True)

    class Meta:
        db_table = 'CALENDARIO'

    @property
    def TOTAL_CUPOS_DISPONIBLES(self):
        planificaciones = PLANIFICACION.objects.filter(CAL_NID = self.pk)

        cupos_xplanificacion = 0
        for row in planificaciones:
            cupos_xplanificacion += row.PL_NCANTIDADCUPOS

        cupos_disponibles = self.CA_NCANTIDADCUPOS - cupos_xplanificacion
        if cupos_disponibles < 0:
            return 0
        return cupos_disponibles

class PLANIFICACION(models.Model):
    TIPO_CHOICES = [
        ('RECEPCION', 'Recepción'),
        ('DESPACHO', 'Despacho')
    ]
    US_NID = models.ForeignKey(User, verbose_name='Id usuario', on_delete=models.PROTECT, null=True, blank=True)
    EP_NID = models.ForeignKey(EMPRESA, verbose_name='Id empresa', on_delete=models.PROTECT, null=True)
    CAL_NID = models.ForeignKey(CALENDARIO, verbose_name='Id calendario', on_delete=models.PROTECT)
    US_ARCHIVADOR_ID = models.ForeignKey(User, verbose_name='Usuario archivador', related_name="Usuario_archivador_id", on_delete=models.PROTECT, null=True)
    PL_CTIPOCUPO = models.CharField(("Tipo de cupo"), choices=TIPO_CHOICES, max_length=128, null=False)
    PL_FFECHAREGISTRO = models.DateTimeField(("Fecha registro"), null=True, blank=True)
    PL_FFECHAINICIO = models.DateTimeField(("Fecha y hora de inicio"), null=True)
    PL_FFECHAFIN = models.DateTimeField(("Fecha y hora de termino"), null=True, blank=True)
    PL_FFECHAARCHIVADO = models.DateField(("Fecha de archivado"), null=True, blank=True)
    PL_NCANTIDADCUPOS = models.IntegerField(("Cantidad de cupos"), null=True, blank=True)
    PL_NSOBRECUPO = models.BooleanField(("Es sobre cupo"), default=False)
    PL_NCANTIDADSOBRECUPO = models.IntegerField(("Cantidad de sobrecupos"), default=0)
    PL_BARCHIVADO = models.BooleanField(("Archivado"), default=False)



    class Meta:
        db_table = 'PLANIFICACION'

    @property
    def TOTAL_CUPOS_DISPONIBLES(self):
        total_citaciones = self.TOTAL_CITACIONES
        diferencia = self.PL_NCANTIDADCUPOS - total_citaciones
        if diferencia < 0:
            return 0
        return self.PL_NCANTIDADCUPOS - total_citaciones

    @property
    def TOTAL_CITACIONES(self):
        return CITACION.objects.filter(PL_NID_id = self.pk, CI_BHABILITADO = True).count()

    @property
    def TOTAL_SOBRECUPO(self):
        total_citaciones = self.TOTAL_CITACIONES
        if self.PL_NCANTIDADCUPOS < total_citaciones:
            return total_citaciones - self.PL_NCANTIDADCUPOS
        
        planificaciones = PLANIFICACION.objects.filter(CAL_NID = self.CAL_NID)
        total_cupos_planificaciones = 0 
        for planificacion in planificaciones:
            total_cupos_planificaciones += planificacion.PL_NCANTIDADCUPOS
        if self.CAL_NID.CA_NCANTIDADCUPOS < total_cupos_planificaciones:
            return total_cupos_planificaciones - self.CAL_NID.CA_NCANTIDADCUPOS

        return 0

    @property
    def TOTAL_SOBRECUPOS_USADOS(self):
        return CITACION.objects.filter(
            PL_NID_id=self.pk,
            CI_BHABILITADO=True,
            CI_BSOBRECUPO=True
        ).count()

    @property
    def TOTAL_SOBRECUPOS_CONFIGURADOS(self):
        return (self.PL_NCANTIDADSOBRECUPO or 0) + self.TOTAL_SOBRECUPOS_USADOS

    @property
    def TOTAL_SOBRECUPOS_DISPONIBLES(self):
        return max(self.PL_NCANTIDADSOBRECUPO or 0, 0)

    @property
    def TIENE_SOBRECUPOS(self):
        return self.PL_NSOBRECUPO or self.TOTAL_SOBRECUPOS_CONFIGURADOS > 0

###################################################################################################
################################## MODELO DE ETAPA 2 ##############################################
###################################################################################################

class SOCIONEGOCIO(models.Model):
    EP_NID = models.ForeignKey(EMPRESA, verbose_name="Id empresa", on_delete=models.PROTECT)
    SN_CCODIGO_SAP = models.CharField(("Codigo SAP"), max_length=128, null=True)
    SN_CRAZONSOCIAL = models.CharField(("Razon social"), max_length=128, null=False)
    SN_CRUT = models.CharField(("Rut"), max_length=128, null=False)
    SN_CDIRECCION = models.CharField(("Direccion"), max_length=256, null=True, blank=True)
    SN_CCONTACTO = models.CharField(("Nombre contacto"), max_length=128, null=True, blank=True)
    SN_CTELEFONO = models.CharField(("Telefono"), max_length=128, null=True, blank=True)
    SN_CEMAIL = models.CharField(("Email"), max_length=128, null=True, blank=True)
    SN_BHABILITADO = models.BooleanField(("Habilitado"), default=True)
    SN_CTIPO = models.CharField(("Cliente/Proveedor"), max_length=128, null=False)
    SN_BGENERICO = models.BooleanField(("Es generico"), default=False)

    class Meta:
        db_table = 'SOCIONEGOCIO'

    def __str__(self):
        return self.SN_CRUT+' - ' + self.SN_CRAZONSOCIAL
    def get_nombre(self):
        return self.SN_CRAZONSOCIAL

    @property
    def LISTA_DOCUMENTOS(self):
        if self.SN_CTIPO == 'S':
            tipos_documentos = list(LISTADO_DOCUMENTO.objects.filter(LIS_CGRUPO = 'Proveedor', LIS_BOBLIGATORIO = True, LIS_BHABILITADO = True).values_list("LIS_CNOMBREDOCUMENTO", flat=True))
        elif self.SN_CTIPO == 'C':
            tipos_documentos = list(LISTADO_DOCUMENTO.objects.filter(LIS_CGRUPO = 'Cliente', LIS_BOBLIGATORIO = True, LIS_BHABILITADO = True).values_list("LIS_CNOMBREDOCUMENTO", flat=True))
        alerta = []
        lista_documentos_guardados = list(DOCUMENTO_SOCIONEGOCIO.objects.filter(SN_NID = self.pk, DSN_BHABILITADO = True).values_list("DSN_CTIPO", flat=True))
        if len(lista_documentos_guardados) > 0:
            alerta = [i for i in tipos_documentos if i not in lista_documentos_guardados]
        else:
            alerta = tipos_documentos
        return alerta
    
    @property
    def ESTADO_DOCUMENTOS(self):
        if self.SN_CTIPO == 'S':
            tipos_documentos = list(LISTADO_DOCUMENTO.objects.filter(LIS_CGRUPO = 'Proveedor', LIS_BOBLIGATORIO = True, LIS_BHABILITADO = True).values_list("LIS_CNOMBREDOCUMENTO", flat=True))
        elif self.SN_CTIPO == 'C':
            tipos_documentos = list(LISTADO_DOCUMENTO.objects.filter(LIS_CGRUPO = 'Cliente', LIS_BOBLIGATORIO = True, LIS_BHABILITADO = True).values_list("LIS_CNOMBREDOCUMENTO", flat=True))
        
        alerta = []
        documentos_en_lista = []
        lista_documentos_guardados = list(DOCUMENTO_SOCIONEGOCIO.objects.filter(SN_NID = self.pk, DSN_BHABILITADO = True).values_list("DSN_CTIPO", flat=True))
        documentos = DOCUMENTO_SOCIONEGOCIO.objects.filter(SN_NID = self.pk, DSN_BHABILITADO = True)

        if len(lista_documentos_guardados) > 1:
            documentos_en_lista = [i for i in tipos_documentos if i in lista_documentos_guardados]
            for i in documentos:
                if i.DSN_CTIPO in documentos_en_lista:
                    if i.DSN_FFECHAVENCIMIENTO and i.DIAS_VENCIMIENTO > 1:
                        alerta.append([i.DSN_CTIPO, i.DIAS_VENCIMIENTO])
            # Ordenar la lista por días de vencimiento (los más críticos primero)
            alerta.sort(key=lambda x: x[1])
        return alerta

class USUARIO_SOCIONEGOCIO(models.Model):
    EP_NID = models.ForeignKey(EMPRESA, verbose_name="Id empresa", on_delete=models.PROTECT)
    US_NID = models.ForeignKey(User, verbose_name='Id usuario',on_delete=models.PROTECT)
    SN_NID = models.ForeignKey(SOCIONEGOCIO, verbose_name='Id socionegocio', on_delete=models.PROTECT)
    USC_CTIPO = models.CharField(("Tipo S(Proveedor)/C(Cliente)"), max_length=128, null=False)

    class Meta:
        db_table = 'USUARIO_SOCIONEGOCIO'

class RUTA(models.Model):
    EP_NID = models.ForeignKey(EMPRESA, verbose_name='Id empresa', on_delete=models.PROTECT)
    RG_NID_INICIO = models.ForeignKey(REGION, verbose_name='Id region inicio', on_delete=models.PROTECT, related_name='ruta_inicio_region')
    PV_NID_INICIO = models.ForeignKey(PROVINCIA, verbose_name='Id provincia inicio', on_delete=models.PROTECT, related_name='ruta_inicio_provincia')
    COM_NID_INICIO = models.ForeignKey(COMUNA, verbose_name='Id comuna inicio', on_delete=models.PROTECT, related_name='ruta_inicio_comuna')
    RG_NID_TERMINO = models.ForeignKey(REGION, verbose_name='Id region termino', on_delete=models.PROTECT, related_name='ruta_termino_region')
    PV_NID_TERMINO = models.ForeignKey(PROVINCIA, verbose_name='Id provincia termino', on_delete=models.PROTECT, related_name='ruta_termino_provincia')
    COM_NID_TERMINO = models.ForeignKey(COMUNA, verbose_name='Id comuna termino', on_delete=models.PROTECT, related_name='ruta_termino_comuna')
    RUT_NTIEMPOMAXIMOENTREGA = models.DecimalField(("Tiempo maximo de entrega"), decimal_places=5, max_digits=18, null=False)
    RUT_NTIEMPOESTADIAPLANTA = models.DecimalField(("Tiempo estadia planta"), decimal_places=5, max_digits=18, null=False)
    RUT_CNOMBRE = models.CharField(("Nombre ruta"), max_length=256, null=False)
    RUT_CCODIGO = models.CharField(("Codigo ruta"), max_length=128, null=False)
    RUT_CCOMENTARIO = models.TextField(("Comentario"), null=True, blank=True)
    RUT_FFECHAREGISTRO = models.DateTimeField(("Fecha registro"), null=True, blank=True)
    RUT_BHABILITADO = models.BooleanField(("Habilitado"), default=True)

    class Meta:
        db_table = 'RUTA'
    
    def __str__(self):
        return self.RUT_CNOMBRE


class CAMION(models.Model):
    EP_NID = models.ForeignKey(EMPRESA, verbose_name="Id empresa", on_delete=models.PROTECT)
    SN_NID = models.ForeignKey(SOCIONEGOCIO, verbose_name="Id socio negocio", on_delete=models.PROTECT, null=True)
    US_NID = models.ForeignKey(User, verbose_name='Id usuario creador', on_delete=models.PROTECT, null=True, blank=True)
    CAM_CPATENTE = models.CharField(("Patente"), max_length=128, null=False)
    CAM_CMARCA = models.CharField(("Marca"), max_length=128, null=True,blank=True)
    CAM_CCOLOR = models.CharField(("Color"), max_length=128, null=True, blank=True)
    CAM_CMODELO  = models.CharField(("Modelo"), max_length=128, null=True, blank=True)
    CAM_CCARGA = models.CharField(("Carga"), max_length=128, null=True, blank=True)
    CAM_NMETROS3 = models.DecimalField(("Metros cubicos"), decimal_places=5, max_digits=18, null=True, blank=True)
    CAM_NANO = models.IntegerField(("Año"), null=True, blank=True)
    CAM_NKILOMETRAJE = models.DecimalField(("Kilometraje"), decimal_places=5, max_digits=18, null=True, blank=True)
    CAM_FFECHAREGISTRO = models.DateTimeField(("Fecha registro"), null=True, blank=True)
    CAM_BHABILITADO = models.BooleanField(("Habilitado"), default=True)

    class Meta:
        db_table = 'CAMION'

    @property
    def LISTA_DOCUMENTOS(self):
        tipos_documentos = list(LISTADO_DOCUMENTO.objects.filter(LIS_CGRUPO = 'Camion', LIS_BOBLIGATORIO = True, LIS_BHABILITADO = True).values_list("LIS_CNOMBREDOCUMENTO", flat=True))
        
        alerta = []
        lista_documentos_guardados = list(DOCUMENTO_CAMION.objects.filter(CA_NID = self.pk, DCA_BHABILITADO = True).values_list("DCA_CTIPO", flat=True))
        if len(lista_documentos_guardados) > 0:
            alerta = [i for i in tipos_documentos if i not in lista_documentos_guardados]
        else:
            alerta = tipos_documentos
        return alerta
    
    @property
    def ESTADO_DOCUMENTOS(self):
        tipos_documentos = list(LISTADO_DOCUMENTO.objects.filter(LIS_CGRUPO = 'Camion', LIS_BOBLIGATORIO = True, LIS_BHABILITADO = True).values_list("LIS_CNOMBREDOCUMENTO", flat=True))
        
        alerta = []
        documentos_en_lista = []
        lista_documentos_guardados = list(DOCUMENTO_CAMION.objects.filter(CA_NID = self.pk, DCA_BHABILITADO = True).values_list("DCA_CTIPO", flat=True))
        documentos = DOCUMENTO_CAMION.objects.filter(CA_NID = self.pk, DCA_BHABILITADO = True)

        if len(lista_documentos_guardados) > 1:
            documentos_en_lista = [i for i in tipos_documentos if i in lista_documentos_guardados]
            for i in documentos:
                if i.DCA_CTIPO in documentos_en_lista:
                    if i.DCA_FFECHAVENCIMIENTO and i.DIAS_VENCIMIENTO > 1:
                        alerta.append([i.DCA_CTIPO, i.DIAS_VENCIMIENTO])
        return alerta

    # @property
    # def DOCUMENTOS_REQUERIDOS(self):
    #     """Retorna la cantidad de documentos requeridos"""
    #     return LISTADO_DOCUMENTO.objects.filter(
    #         LIS_CGRUPO='Camion', 
    #         LIS_BOBLIGATORIO=True, 
    #         LIS_BHABILITADO=True
    #     ).count()

class CONDUCTOR(models.Model):
    EP_NID = models.ForeignKey(EMPRESA, verbose_name="Id empresa", on_delete=models.PROTECT)
    SN_NID = models.ForeignKey(SOCIONEGOCIO, verbose_name="Id socio negocio", on_delete=models.PROTECT, null=True)
    US_NID = models.ForeignKey(User, verbose_name='Id usuario creador', on_delete=models.PROTECT, null=True, blank=True)
    CON_CNOMBRE = models.CharField(("Nombre conductor"), max_length=128, null=False)
    CON_CAPELLIDO = models.CharField(("Apellido"), max_length=128, null=False)
    CON_CRUT = models.CharField(("Rut"), max_length=128, null=False)
    CON_CEMAIL = models.CharField(("Email"), max_length=128, null=True, blank=True)
    CON_CTELEFONO = models.CharField(("Telefono"), max_length=128, null=True, blank=True)
    CON_CDIRECCION = models.CharField(("Direccion"), max_length=256, null=True, blank=True)
    CON_FFECHAREGISTRO = models.DateTimeField(("Fecha registro"), null=True, blank=True)
    CON_BHABILITADO = models.BooleanField(("Habilitado"), default=True)
    CON_NPERIODO_EXTRA = models.IntegerField(("Periodo extra"), default = 10)

    class Meta:
        db_table = 'CONDUCTOR'
    
    @property
    def LISTA_DOCUMENTOS(self):
        tipos_documentos = list(LISTADO_DOCUMENTO.objects.filter(LIS_CGRUPO = 'Conductor', LIS_BOBLIGATORIO = True, LIS_BHABILITADO = True).values_list("LIS_CNOMBREDOCUMENTO", flat=True))
        alerta = []
        documentos = DOCUMENTO_CONDUCTOR.objects.filter(CON_NID = self.pk, DCON_BHABILITADO = True)

        # Verificar documentos faltantes
        documentos_existentes = list(documentos.values_list('DCON_CTIPO', flat=True))
        documentos_faltantes = [doc for doc in tipos_documentos if doc not in documentos_existentes]
        
        if documentos_faltantes:
            # Si faltan documentos, retornamos una lista con el primer documento faltante y -999 para indicar que falta
            return [[documentos_faltantes[0], -999]]
            
        # Si no faltan documentos, verificamos vencimientos
        for doc in documentos:
            if doc.DCON_CTIPO in tipos_documentos and doc.DCON_FFECHAVENCIMIENTO:
                dias = doc.DIAS_VENCIMIENTO
                if dias <= 30:  # Si está vencido o próximo a vencer (30 días o menos)
                    alerta.append([doc.DCON_CTIPO, dias])
        
        # Ordenar la lista por días de vencimiento (los más críticos primero)
        if alerta:
            alerta.sort(key=lambda x: x[1])
        return alerta
    
    @property
    def ESTADO_DOCUMENTOS(self):
        tipos_documentos = list(LISTADO_DOCUMENTO.objects.filter(LIS_CGRUPO = 'Conductor', LIS_BOBLIGATORIO = True, LIS_BHABILITADO = True).values_list("LIS_CNOMBREDOCUMENTO", flat=True))
        documentos = DOCUMENTO_CONDUCTOR.objects.filter(CON_NID = self.pk, DCON_BHABILITADO = True)
        
        # Verificar documentos faltantes
        documentos_existentes = list(documentos.values_list('DCON_CTIPO', flat=True))
        documentos_faltantes = [doc for doc in tipos_documentos if doc not in documentos_existentes]
        
        if documentos_faltantes:
            # Si faltan documentos, retornamos una lista con el primer documento faltante y -999 para indicar que falta
            return [[documentos_faltantes[0], -999]]
            
        # Si no faltan documentos, verificamos vencimientos
        alerta = []
        for doc in documentos:
            if doc.DCON_CTIPO in tipos_documentos and doc.DCON_FFECHAVENCIMIENTO:
                dias = doc.DIAS_VENCIMIENTO
                if dias <= 30:  # Si está vencido o próximo a vencer (30 días o menos)
                    alerta.append([doc.DCON_CTIPO, dias])
        
        # Ordenar la lista por días de vencimiento (los más críticos primero)
        if alerta:
            alerta.sort(key=lambda x: x[1])
        return alerta

class LISTADO_DOCUMENTO(models.Model):
    EP_NID = models.ForeignKey(EMPRESA, verbose_name='Id empresa', on_delete=models.PROTECT)
    US_NID = models.ForeignKey(User, verbose_name='Id usuario', on_delete=models.PROTECT, null=True, blank=True)
    LIS_CNOMBREDOCUMENTO = models.CharField(("Nombre documento"), max_length=128, null=False)
    LIS_CGRUPO = models.CharField(("Grupo"), max_length=128, null=False)
    LIS_CCODIGO = models.CharField(("Codigo"), max_length=128, null=False)
    LIS_CDESCRIPCION = models.CharField(("Descripcion"), max_length=128, null=True, blank=True)
    LIS_CFORMATO = models.CharField(("Formato"), max_length=128, null=False)
    LIS_FFECHAREGISTRO = models.DateTimeField(("Fecha registro"), null=True, blank=True)
    LIS_BOBLIGATORIO = models.BooleanField(("Obligatorio"), default=False)
    LIS_BHABILITADO = models.BooleanField(("Habilitado"), default=True)

    class Meta:
        db_table = 'LISTADO_DOCUMENTO'

class DOCUMENTO_SOCIONEGOCIO(models.Model):
    EP_NID = models.ForeignKey(EMPRESA, verbose_name='Id empresa', on_delete=models.PROTECT)
    SN_NID = models.ForeignKey(SOCIONEGOCIO, verbose_name='Id socionegocio', on_delete=models.PROTECT)
    US_NID = models.ForeignKey(User, verbose_name='Id usuario creador', on_delete=models.PROTECT)
    DSN_CTIPO = models.CharField(("Tipo documento"), max_length=128, null=False)
    DSN_CESTADO = models.CharField(("Estado"), max_length=128, null=False)
    DSN_CRUTADOC = models.CharField(("Ruta documento"), max_length=128, null=False)
    DSN_FFECHAREGISTRO = models.DateTimeField(("Fecha registro"), null=True, blank=True)
    DSN_FFECHAEMISION = models.DateField(("Fecha emisión"), null=True, blank=True)
    DSN_FFECHAVENCIMIENTO = models.DateField(("Fecha vencimiento"), null=True, blank=True)
    DSN_BHABILITADO = models.BooleanField(("Habilitado"), default=True)
    DSN_BOBLIGATORIO = models.BooleanField(("Obligatorio"), default=False)

    class Meta:
        db_table = 'DOCUMENTO_SOCIONEGOCIO'
    
    @property
    def DIAS_VENCIMIENTO(self):
        if self.DSN_FFECHAVENCIMIENTO:
            dias = 0
            today = date.today()
            fecha_vencimiento = self.DSN_FFECHAVENCIMIENTO
            dias_vencimiento_str = fecha_vencimiento - today
            dias_vencimiento = (str(dias_vencimiento_str).split(',')[0]).split(' ')[0]
            if dias_vencimiento == 0 or dias_vencimiento == '0:00:00':
                dias = 0
            else:
                dias = int(dias_vencimiento)
        else:
            dias = 9999
        return dias

class DOCUMENTO_CAMION(models.Model):
    EP_NID = models.ForeignKey(EMPRESA, verbose_name='Id empresa', on_delete=models.PROTECT)
    CA_NID = models.ForeignKey(CAMION, verbose_name='Id camion', on_delete=models.PROTECT)
    US_NID = models.ForeignKey(User, verbose_name='Id usuario creador', on_delete=models.PROTECT, null=True, blank=True)
    DCA_CTIPO = models.CharField(("Tipo documento"), max_length=128, null=False)
    DCA_CESTADO = models.CharField(("Estado"), max_length=128, null=False)
    DCA_CRUTADOC = models.CharField(("Ruta documento"), max_length=256, null=False)
    DCA_FFECHAREGISTRO = models.DateTimeField(("Fecha registro"), null=True, blank=True)
    DCA_FFECHAEMISION = models.DateField(("Fecha emisión"), null=False)
    DCA_FFECHAVENCIMIENTO = models.DateField(("Fecha vencimiento"), null=False)
    DCA_BHABILITADO = models.BooleanField(("Hablitado"), default=True)

    class Meta:
        db_table = 'DOCUMENTO_CAMION'

    @property
    def DIAS_VENCIMIENTO(self):
        if self.DCA_FFECHAVENCIMIENTO:
            dias = 0
            today = date.today()
            fecha_vencimiento = self.DCA_FFECHAVENCIMIENTO
            dias_vencimiento_str = fecha_vencimiento - today
            dias_vencimiento = (str(dias_vencimiento_str).split(',')[0]).split(' ')[0]
            if dias_vencimiento == 0 or dias_vencimiento == '0:00:00':
                dias = 0
            else:
                dias = int(dias_vencimiento)
        else:
            dias = 9999
        return dias

class DOCUMENTO_CONDUCTOR(models.Model):
    EP_NID = models.ForeignKey(EMPRESA, verbose_name='Id empresa', on_delete=models.PROTECT)
    CON_NID = models.ForeignKey(CONDUCTOR, verbose_name='Id conductor', on_delete=models.PROTECT)
    US_NID = models.ForeignKey(User, verbose_name='Id usuario creador', on_delete=models.PROTECT)
    DCON_CTIPO = models.CharField(("Tipo documento"), max_length=128, null=False)
    DCON_CESTADO = models.CharField(("Estado"), max_length=128, null=False)
    DCON_CRUTADOC = models.CharField(("Ruta documento"), max_length=256, null=False)
    DCON_FFECHAREGISTRO = models.DateTimeField(("Fecha registro"), null=True, blank=True)
    DCON_FFECHAEMISION = models.DateField(("Fecha emisión"), null=False)
    DCON_FFECHAVENCIMIENTO = models.DateField(("Fecha vencimiento"), null=False)
    DCON_BHABILITADO = models.BooleanField(("Hablitado"), default=True)

    class Meta:
        db_table = 'DOCUMENTO_CONDUCTOR'
    @property
    def DIAS_VENCIMIENTO(self):
        if self.DCON_FFECHAVENCIMIENTO:
            dias = 0
            today = date.today()
            fecha_vencimiento = self.DCON_FFECHAVENCIMIENTO
            dias_vencimiento_str = fecha_vencimiento - today
            dias_vencimiento = (str(dias_vencimiento_str).split(',')[0]).split(' ')[0]
            if dias_vencimiento == 0 or dias_vencimiento == '0:00:00':
                dias = 0
            else:
                dias = int(dias_vencimiento)
            return dias
        else:
            return 9999

class TARIFA_GLOBAL(models.Model):
    EP_NID = models.ForeignKey(EMPRESA, verbose_name='Id empresa', on_delete=models.PROTECT)
    RUT_NID = models.ForeignKey(RUTA, verbose_name="Id ruta", on_delete=models.PROTECT)
    US_NID = models.ForeignKey(User, verbose_name='Id usuario', null=True, blank=True, on_delete=models.PROTECT)
    MODIFICADO_POR = models.ForeignKey(User, verbose_name="Id usuario modificador", related_name="id_usuario_modifcador", null=True, on_delete=models.PROTECT)
    SN_NID = models.ForeignKey(SOCIONEGOCIO, verbose_name='Id socio negocio', on_delete=models.PROTECT)
    TAR_FFECHAREGISTRO = models.DateTimeField(("Fecha registro"), null=True, blank=True)
    TAR_FFECHAULTIMAMODIFICACION = models.DateTimeField(("Fecha ultima modificacion"), null=True, blank=True)
    TAR_NVALOR = models.DecimalField(("Valor tarifa"), decimal_places=5, max_digits=18, null=False)
    TAR_NVALORPREVIO = models.DecimalField(("Valor tarifa previo"), decimal_places=5, max_digits=18, null=True, blank=True)
    TAR_CNOMBRETARIFA = models.CharField(("Nombre tarifa"), max_length=128, null=False)
    TAR_CTIPOTARIFA  = models.CharField(("Tipo tarifa"), max_length=128, null=False)
    TAR_CDIVISA = models.CharField(("Moneda"), max_length=128, null=False)
    TAR_BHABILITADO = models.BooleanField(("Hablitado"), default=True)

    class Meta:
        db_table = 'TARIFA_GLOBAL'

class TARIFA_LOG(models.Model):
    TAR_NID = models.ForeignKey(TARIFA_GLOBAL, verbose_name='Id tarifa', on_delete=models.PROTECT)
    US_NID = models.ForeignKey(User, verbose_name='Id usuario', on_delete=models.PROTECT)
    TL_FFECHAREGISTRO = models.DateTimeField(("Fecha registro"), null=True, blank=True)
    TL_NVALOR = models.DecimalField(("Valor tarifa"), decimal_places=5, max_digits=18, null=False)

    class Meta:
        db_table = 'TARIFA_LOG'

###################################################################################################
################################## MODELO DE ETAPA 3 ##############################################
###################################################################################################

class CITACION(models.Model):
    US_NID = models.ForeignKey(User, verbose_name='Id usuario', on_delete=models.PROTECT, null=True, blank=True)
    EP_NID = models.ForeignKey(EMPRESA, verbose_name='Id empresa', on_delete=models.PROTECT)
    RUT_NID = models.ForeignKey(RUTA, verbose_name='Id ruta', on_delete=models.PROTECT, null=True, blank=True)
    TAR_NID = models.ForeignKey(TARIFA_GLOBAL, verbose_name='Id tarifa', on_delete=models.PROTECT, null=True, blank=True)
    PL_NID = models.ForeignKey(PLANIFICACION, verbose_name='Id planificacion', on_delete=models.PROTECT)
    SN_NID = models.ForeignKey(SOCIONEGOCIO, verbose_name='Id socio negocio', on_delete=models.PROTECT, null=True, blank=True, related_name='citaciones_as_negocio')
    CON_NID = models.ForeignKey(CONDUCTOR, verbose_name='id conductor', on_delete=models.PROTECT, null=True, blank=True)
    CA_NID = models.ForeignKey(CAMION, verbose_name='Id camion', on_delete=models.PROTECT, null=True, blank=True)
    SC_NID = models.ForeignKey("SECUENCIA", verbose_name='Id secuencia', on_delete=models.PROTECT)
    PRO_NID = models.ForeignKey(SOCIONEGOCIO, verbose_name='Id proveedor', on_delete=models.PROTECT, null=True, blank=True, related_name='citaciones_as_proveedor')
    CI_FFECHAREGISTRO = models.DateTimeField(("Fecha registro"), null=True, blank=True)
    CI_FFECHAINICIO = models.DateTimeField(("Fecha inicio"), null=True, blank=True)
    CI_FFECHATERMINO = models.DateTimeField(("Fecha termino"), null=True, blank=True)
    CI_FFECHACITACION = models.DateTimeField(("Fecha citacion"), null=False)
    CI_BAVISADO = models.BooleanField(("Avisado"), default=False)
    CI_BCONFIRMADO = models.BooleanField(("Confirmado"), default=False)
    CI_BARRIBADO = models.BooleanField(("Arribado"), default=False)
    CI_BHABILITADO = models.BooleanField(("Habilitado"), default=True)
    CI_BARCHIVADO = models.BooleanField(("Archivado"), default=False)
    CI_BSOBRECUPO = models.BooleanField(("Sobre cupo"), default=False)
    CI_NCUPO = models.IntegerField(("Numero cupo"), null=False)
    CI_CTIPO = models.CharField(("Tipo citacion"), max_length=128, null=True, blank=True)
    CI_CESTADO = models.CharField(("Estado"), max_length=128, null=False)
    CI_CTIPODOCUMENTO = models.CharField(("Tipo documento"), max_length=128, null=True, blank=True)
    CI_CNUMERODOCUMENTO = models.CharField(("Numero documento"), max_length=128, null=True, blank=True, db_index=True)
    CI_NVALORTARIFA = models.DecimalField(("Valor tarifa"), decimal_places=5, max_digits=18, null=True, blank=True)
    CI_NDIFERENCIATARIFA = models.DecimalField(("Diferencia tarifa"), decimal_places=5, max_digits=18, null=True, blank=True)
    CI_CCOMENTARIO = models.TextField(("Comentario"), null=True, blank=True)
    CI_NID_REF = models.IntegerField(("Id citacion original"), null=True, blank=True)
    CI_CTIPO_FLETE = models.CharField(("Tipo flete"), max_length=128, null=True, blank=True)
    CI_BCONFORME = models.BooleanField(("Entrega conforme"), default=False)
    
    class Meta:
        db_table = 'CITACION'

    @property
    def ETAPA_ACTUAL(self):
        secuencia = self.SC_NID
        ultimo_etapa_log = ETAPA_LOG.objects.filter(CI_NID = self.pk, SC_NID = secuencia, EL_FFECHAFIN = None).first()
        if ultimo_etapa_log:
            return ETAPA.objects.get(pk = ultimo_etapa_log.ET_NID.pk)
        else:
            ultimo_etapa_log = ETAPA_LOG.objects.filter(CI_NID = self.pk, SC_NID = secuencia).order_by("-EL_FFECHAFIN").first()
            if ultimo_etapa_log:
                return ETAPA.objects.get(pk = ultimo_etapa_log.ET_NID.pk)
            else:
                return DETALLE_SECUENCIA.objects.filter(SC_NID = secuencia, SE_BHABILITADO = True, SE_NPASO = 1).first().ET_NID
    
    @property
    def ETAPA_SIGUIENTE(self):
        secuencia = self.SC_NID
        etapa_actual = self.ETAPA_ACTUAL
        detalle_secuencia = DETALLE_SECUENCIA.objects.get(SC_NID = secuencia, ET_NID = etapa_actual, SE_BHABILITADO = True)
        id_detalle_secuencia = get_siguiente_etapa(secuencia.pk, detalle_secuencia.SE_NPASO)

        if id_detalle_secuencia:
            return DETALLE_SECUENCIA.objects.get(pk = id_detalle_secuencia[0])
        else:
            return None


    @property
    def ETAPA_SALIDA(self):
        secuencia = self.SC_NID
        id_etapa_salida, etapa_salida = getEtapaSalida(self.EP_NID.pk, self.SC_NID.pk)
        etapa = ETAPA.objects.get(pk = id_etapa_salida)
        return etapa
    
    @property
    def hora_ingreso_etapa(self):        
        try:
            dato_operacion = ETAPA_LOG.objects.filter(CI_NID=self.pk, ET_NID=self.ETAPA_ACTUAL.pk).first()
            if dato_operacion :
                return dato_operacion.EL_FFECHAINICIO
            elif self.CI_FFECHAINICIO:
                return self.CI_FFECHAINICIO
            else:
                return None
        except Exception as e:
            # Manejar la excepción o registrarla en el log
            print(f"Error en hora_ingreso_etapa: {str(e)}")
            return None

    @property
    def tiempo_total_secuencia(self):
        try:
            if self.CI_FFECHATERMINO and self.CI_FFECHAINICIO:
                tiempo_total = self.CI_FFECHATERMINO - self.CI_FFECHAINICIO
                # tiempo_total = str(temp_tiempo_total).split(".")[0]                
                return tiempo_total
            else:
                tiempo_total = timezone.now() - self.CI_FFECHAINICIO
                # tiempo_total = str(temp_tiempo_total).split(".")[0]        
                return tiempo_total
        except Exception as e:
            # Manejar la excepción o registrarla en el log
            print(f"Error en tiempo_total_secuencia: {str(e)}")
            return None

    @property
    def tiempo_en_etapa_actual(self):
        try:
            dato_operacion = ETAPA_LOG.objects.filter(CI_NID=self.pk, ET_NID=self.ETAPA_ACTUAL.pk).first()
            if dato_operacion:
                tiempo_etapa = timezone.now() - dato_operacion.EL_FFECHAINICIO
                return tiempo_etapa
            else:
                ultimo_registro = ETAPA_LOG.objects.filter(CI_NID=self.pk).order_by("-EL_FFECHAINICIO").first()
                if ultimo_registro:
                    tiempo_etapa = timezone.now() - ultimo_registro.EL_FFECHAINICIO
                    return tiempo_etapa
                elif self.CI_FFECHATERMINO and self.CI_FFECHAREGISTRO:
                    tiempo_etapa = self.CI_FFECHATERMINO - self.CI_FFECHAREGISTRO
                    return tiempo_etapa
                else:
                    return None
        except Exception as e:
            # Manejar la excepción o registrarla en el log
            print(f"Error en tiempo_en_etapa_actual: {str(e)}")
            return None

    def GET_STATUS_PROFORMA(self):
        citacion_proforma = CITACION_PROFORMA.objects.filter(CI_NID = self).first()
        if citacion_proforma:
            if citacion_proforma.PRO_NID.PRO_CESTADO == 'AUTORIZADO':
                return False
            return True
        return True


class CITACION_DETALLE_OPERACIONAL(models.Model):
    CI_NID = models.OneToOneField(CITACION, verbose_name='Id citacion', on_delete=models.CASCADE, related_name='detalle_operacional')
    EP_NID = models.ForeignKey(EMPRESA, verbose_name='Id empresa', on_delete=models.PROTECT)
    US_NID = models.ForeignKey(User, verbose_name='Usuario creacion', on_delete=models.PROTECT, null=True, blank=True)
    CDO_CORIGEN = models.CharField('Origen', max_length=64, null=True, blank=True)
    CDO_CINF_24HRS = models.CharField('Inf 24 hrs', max_length=16, null=True, blank=True)
    CDO_CCODIGO_SAP = models.CharField('Codigo SAP', max_length=128, null=True, blank=True)
    CDO_CINSUMO = models.CharField('Insumo producto', max_length=256, null=True, blank=True)
    CDO_CPEDIDO_SAP = models.CharField('Pedido SAP', max_length=128, null=True, blank=True)
    CDO_CSAP_OPOR_ID = models.CharField('SAP OPOR id', max_length=128, null=True, blank=True)
    CDO_CPROVEEDOR_CODIGO = models.CharField('Codigo proveedor', max_length=128, null=True, blank=True)
    CDO_CBL_CONTENEDOR = models.CharField('BL contenedor', max_length=128, null=True, blank=True)
    CDO_NCANTIDAD_DISPONIBLE = models.DecimalField('Cantidad disponible', max_digits=18, decimal_places=5, null=True, blank=True)
    CDO_CDOCENTRY = models.CharField('DocEntry', max_length=128, null=True, blank=True)
    CDO_CPRODUCTOR = models.CharField('Productor', max_length=256, null=True, blank=True)
    CDO_CALMACEN_DESTINO = models.CharField('Almacen destino', max_length=128, null=True, blank=True)
    CDO_CESTANQUE_DESTINO = models.CharField('Estanque destino', max_length=128, null=True, blank=True)
    CDO_COBSERVACION = models.TextField('Observacion', null=True, blank=True)
    CDO_FFECHACREACION = models.DateTimeField('Fecha creacion', auto_now_add=True)

    class Meta:
        db_table = 'CITACION_DETALLE_OPERACIONAL'
        indexes = [
            models.Index(fields=['EP_NID', 'CDO_CORIGEN'], name='CITACION_DE_EP_NID__cd1c92_idx'),
            models.Index(fields=['CDO_CCODIGO_SAP'], name='CITACION_DE_CDO_CCO_20d02e_idx'),
            models.Index(fields=['CDO_CPEDIDO_SAP'], name='CITACION_DE_CDO_CPE_bf9dd2_idx'),
            models.Index(fields=['CDO_CDOCENTRY'], name='CITACION_DE_CDO_CDO_14ae9a_idx'),
        ]


class CITACION_DESPACHO_DETALLE(models.Model):
    CI_NID = models.OneToOneField(CITACION, verbose_name='Id citacion', on_delete=models.CASCADE, related_name='detalle_despacho')
    EP_NID = models.ForeignKey(EMPRESA, verbose_name='Id empresa', on_delete=models.PROTECT)
    US_NID = models.ForeignKey(User, verbose_name='Usuario creacion', on_delete=models.PROTECT, null=True, blank=True)
    CDD_CDESTINO = models.CharField('Destino', max_length=256, null=True, blank=True)
    CDD_COC_CLIENTE = models.CharField('OC cliente', max_length=128, null=True, blank=True)
    CDD_NCANTIDAD_INTENTADA_DESPACHAR = models.DecimalField('Cantidad intentada a despachar', max_digits=18, decimal_places=5, null=True, blank=True)
    CDD_CCONDICION_ENTREGA = models.CharField('Condicion de entrega', max_length=128, null=True, blank=True)
    CDD_CSALIDA_DOCUMENTO = models.CharField('Salida de documento', max_length=128, null=True, blank=True)
    CDD_CEMPRESA_TRANSPORTE = models.CharField('Empresa transporte', max_length=256, null=True, blank=True)
    CDD_CCONDUCTOR = models.CharField('Conductor', max_length=256, null=True, blank=True)
    CDD_CTELEFONO_CONDUCTOR = models.CharField('Telefono conductor', max_length=64, null=True, blank=True)
    CDD_CPATENTE = models.CharField('Patente', max_length=32, null=True, blank=True)
    CDD_CORDEN_CARGA = models.CharField('Orden de carga', max_length=128, null=True, blank=True)
    CDD_CVENTANA_HORARIA_DESPACHO = models.CharField('Ventana horaria despacho', max_length=128, null=True, blank=True)
    CDD_NPESO_INFORMADO = models.DecimalField('Peso informado', max_digits=18, decimal_places=5, null=True, blank=True)
    CDD_CBODEGA = models.CharField('Bodega', max_length=128, null=True, blank=True)
    CDD_CSECUENCIA_OPERACIONAL_CODIGO = models.CharField('Codigo secuencia operacional', max_length=128, null=True, blank=True)
    CDD_CSECUENCIA_OPERACIONAL_NOMBRE = models.CharField('Nombre secuencia operacional', max_length=256, null=True, blank=True)
    CDD_CSAP_ABS_ID = models.CharField('SAP AbsID', max_length=128, null=True, blank=True)
    CDD_CSAP_NUMERO_ACUERDO = models.CharField('Numero acuerdo SAP', max_length=128, null=True, blank=True)
    CDD_CSAP_LINEA_ACUERDO = models.CharField('Linea acuerdo SAP', max_length=128, null=True, blank=True)
    CDD_CSAP_CLIENTE_CODIGO = models.CharField('Codigo cliente SAP', max_length=128, null=True, blank=True)
    CDD_CSAP_CLIENTE_NOMBRE = models.CharField('Nombre cliente SAP', max_length=256, null=True, blank=True)
    CDD_CSAP_OC_CLIENTE = models.CharField('OC cliente SAP', max_length=128, null=True, blank=True)
    CDD_CSAP_CODIGO_PRODUCTO = models.CharField('Codigo producto SAP', max_length=128, null=True, blank=True)
    CDD_CSAP_NOMBRE_PRODUCTO = models.CharField('Nombre producto SAP', max_length=256, null=True, blank=True)
    CDD_NSAP_CANTIDAD_PLANIFICADA = models.DecimalField('Cantidad planificada SAP', max_digits=18, decimal_places=5, null=True, blank=True)
    CDD_NSAP_CANTIDAD_CONSUMIDA = models.DecimalField('Cantidad consumida SAP', max_digits=18, decimal_places=5, null=True, blank=True)
    CDD_NSAP_SALDO_CONTRATO = models.DecimalField('Saldo contrato SAP', max_digits=18, decimal_places=5, null=True, blank=True)
    CDD_CSAP_UNIDAD_MEDIDA = models.CharField('Unidad medida SAP', max_length=64, null=True, blank=True)
    CDD_CSAP_DRAFT_DOCENTRY = models.CharField('DocEntry draft SAP despacho', max_length=128, null=True, blank=True)
    CDD_CSAP_DRAFT_DOCNUM = models.CharField('DocNum draft SAP despacho', max_length=128, null=True, blank=True)
    CDD_CJSON_DRAFT_REQUEST = models.TextField('JSON request draft SAP despacho', null=True, blank=True)
    CDD_CJSON_DRAFT_RESPONSE = models.TextField('JSON response draft SAP despacho', null=True, blank=True)
    CDD_FFECHA_DRAFT_SAP = models.DateTimeField('Fecha draft SAP despacho', null=True, blank=True)
    CDD_USUARIO_DRAFT_SAP = models.ForeignKey(User, verbose_name='Usuario draft SAP despacho', on_delete=models.PROTECT, null=True, blank=True, related_name='despacho_drafts_sap')
    CDD_CESTADO_DRAFT_SAP = models.CharField('Estado draft SAP despacho', max_length=64, null=True, blank=True)
    CDD_CSAP_UPDATE_ESTADO = models.CharField('Estado update SAP despacho', max_length=64, null=True, blank=True)
    CDD_CSAP_UPDATE_DOCENTRY = models.CharField('DocEntry update SAP despacho', max_length=128, null=True, blank=True)
    CDD_CJSON_UPDATE_REQUEST = models.TextField('JSON request update SAP despacho', null=True, blank=True)
    CDD_CJSON_UPDATE_RESPONSE = models.TextField('JSON response update SAP despacho', null=True, blank=True)
    CDD_FFECHA_UPDATE_SAP = models.DateTimeField('Fecha update SAP despacho', null=True, blank=True)
    CDD_USUARIO_UPDATE_SAP = models.ForeignKey(User, verbose_name='Usuario update SAP despacho', on_delete=models.PROTECT, null=True, blank=True, related_name='despacho_updates_sap')
    CDD_NSAP_PESO_SALIDA = models.DecimalField('Peso salida SAP despacho', max_digits=18, decimal_places=5, null=True, blank=True)
    CDD_FFECHACREACION = models.DateTimeField('Fecha creacion', auto_now_add=True)
    CDD_FFECHAACTUALIZACION = models.DateTimeField('Fecha actualizacion', auto_now=True)

    class Meta:
        db_table = 'CITACION_DESPACHO_DETALLE'
        indexes = [
            models.Index(fields=['EP_NID', 'CDD_COC_CLIENTE'], name='CIT_DESP_EP_OC_IDX'),
            models.Index(fields=['CDD_CPATENTE'], name='CIT_DESP_PATENTE_IDX'),
            models.Index(fields=['CDD_CSAP_NUMERO_ACUERDO'], name='CIT_DESP_SAP_ACUERDO_IDX'),
        ]

    
class ITEM(models.Model):
    EP_NID = models.ForeignKey(EMPRESA, verbose_name='Id emrpesa', on_delete=models.PROTECT)
    IT_CCODIGO = models.CharField(("Codigo"), max_length=128, null=False)
    IT_CNOMBRE = models.CharField(("Nombre"), max_length=128, null=False)

    class Meta:
        db_table = 'ITEM'

class CITACION_ITEM(models.Model):
    EP_NID = models.ForeignKey(EMPRESA, verbose_name='Id empresa', on_delete=models.PROTECT)
    IT_NID = models.ForeignKey(ITEM, verbose_name='Id item', on_delete=models.PROTECT)
    CI_NID = models.ForeignKey(CITACION, verbose_name='Id citacion', on_delete=models.PROTECT)

    class Meta:
        db_table = 'CITACION_ITEM'

class EXTRA(models.Model):
    TIPO_CHOICES = [
        ('RECEPCION', 'Recepción'),
        ('DESPACHO', 'Despacho')
    ]
    EP_NID = models.ForeignKey(EMPRESA, verbose_name='Id empresa', on_delete=models.PROTECT)
    US_NID = models.ForeignKey(User, verbose_name='Id usuario', on_delete=models.PROTECT, null=True, blank=True)
    EXT_CNOMBRE = models.CharField(("Extra"), max_length=128, null=False)
    EXT_CDESCRIPCION = models.TextField(("Descripcion"), null=True, blank=True)
    EXT_FFECHAREGISTRO = models.DateTimeField(("Fecha registro"), null=True, blank=True)
    EXT_BHABILITADO = models.BooleanField(("Habilitado"), default=True)
    EXT_BINGRESO = models.BooleanField(("Ingreso"), default=False)
    EXT_CTIPO_CITACION = models.CharField(("Tipo citacion"), choices=TIPO_CHOICES, max_length=128, null=True, blank=True)
    EXT_CARTICULOSAP = models.CharField(("Articulos SAP"), max_length=128, null=True, blank=True)
    EXT_CCUENTASAP = models.CharField(("Cuentas SAP"), max_length=128, null=True, blank=True)

    class Meta:
        db_table = 'EXTRA'

class CITACION_EXTRA(models.Model):
    EP_NID = models.ForeignKey(EMPRESA, verbose_name='Id empresa', on_delete=models.PROTECT)
    US_NID = models.ForeignKey(User, verbose_name='Id usuario', on_delete=models.PROTECT)
    EXT_NID = models.ForeignKey(EXTRA, verbose_name='Id extra', on_delete=models.PROTECT)
    CI_NID = models.ForeignKey(CITACION, verbose_name='Id citacion', on_delete=models.PROTECT)
    CIE_NVALOR = models.DecimalField(("Valor"), decimal_places=5, max_digits=18, null=False)
    CIE_FFECHAREGISTRO = models.DateTimeField(("Fecha registro"), null=True, blank=True)
    CIE_BINGRESO = models.BooleanField(("Ingreso"), default=False)
    CIE_CCOMENTARIO = models.CharField(("Comentario"), max_length=128, null=True, blank=True)

    class Meta:
        db_table = 'CITACION_EXTRA'

class SECUENCIA(models.Model):
    TIPO_CHOICES = [
        ('RECEPCION', 'Recepción'),
        ('DESPACHO', 'Despacho')
    ]
    US_NID = models.ForeignKey(User, verbose_name='Id usuario', on_delete=models.PROTECT,blank=True,null=True)
    EP_NID = models.ForeignKey(EMPRESA, verbose_name='Id empresa', on_delete=models.PROTECT)
    SE_CTIPO = models.CharField(("Tipo"), choices=TIPO_CHOICES, max_length=128, null=False)
    SE_CCODIGO = models.CharField(("Codigo"), max_length=128, null=False)
    SE_CNOMBRE = models.CharField(("Nombre"), max_length=128, null=False)
    SE_BHABILITADO = models.BooleanField(("Habilitado"), default=False)
    SE_FFECHAREGISTRO = models.DateTimeField(("Fecha registro"), null=True, blank=True)

    @property
    def tiempo_total_secuencia(self):
        detalles_secuencia = DETALLE_SECUENCIA.objects.filter(SC_NID=self.pk, SE_BHABILITADO=True).exclude(SE_NPASO = None)
        tiempo_maximo = 0
        for det in detalles_secuencia:
            tiempo_maximo += det.ET_NID.ET_TTIEMPOMAXIMO
        return tiempo_maximo
    class Meta:
        db_table = 'SECUENCIA'
    def __str__(self):
        return self.SE_CCODIGO + ' - ' + self.SE_CNOMBRE

class ETAPA(models.Model):
    TIPO_CHOICES = [
        ('OPERACION', 'Operación'),
        ('SALIDA', 'Salida'),
        ('SEGUIMIENTO', 'Seguimiento')
    ]
    US_NID = models.ForeignKey(User, verbose_name='Id usuario', on_delete=models.PROTECT,blank=True,null=True)
    EP_NID = models.ForeignKey(EMPRESA, verbose_name='Id empresa', on_delete=models.PROTECT)
    ZON_NID = models.ForeignKey("ZONA", verbose_name="Id zona", on_delete=models.PROTECT, null=True, blank=True)
    ET_CTIPO = models.CharField(("Tipo"), max_length=128,choices=TIPO_CHOICES, null=False)
    ET_CCODIGO = models.CharField(("Codigo estacion"), max_length=128, null=False)
    ET_CNOMBRE = models.CharField(("Nombre"), max_length=128, null=False)
    ET_CDESCRIPCION = models.TextField(("Descripcion"), null=True, blank=True)
    ET_FFECHAREGISTRO = models.DateTimeField(("Fecha registro"), null=True, blank=True)
    ET_NCANTIDADMAXIMA = models.IntegerField(("Cantidad maxima"), null=False)
    ET_TTIEMPOMAXIMO = models.TimeField(("Tiempo maximo"), null=True, blank=True)
    ET_TTIEMPOMINIMO = models.TimeField(("Tiempo minimo"), null=True, blank=True)
    ET_BHABILITADO = models.BooleanField(("Habilitado"), default=False)
    ET_BINTEGRARSAP = models.BooleanField(("Integrar SAP"), default=False)
    ET_BISCABECERA = models.BooleanField(("Es cabecera"), default=False)
    ET_BISLINEA = models.BooleanField(("Es linea"), default=False)
    ET_BISADICIONAL = models.BooleanField(("Es adicional"), default=False)
    ET_CNUMEROOBJETOSAP = models.CharField(("Numero objeto SAP"), max_length=128, null=True, blank=True)
    ET_CNOMBREOBJETOSAP = models.CharField(("Nombre objeto SAP"), max_length=128, null=True, blank=True)
    ET_CENDPOINT = models.CharField(("End point"), max_length=128, null=True, blank=True)
    ET_NID_REF = models.IntegerField(("Id etapa referencia"), null=True, blank=True)
    ET_NID_REF_ADICIONALES = models.IntegerField(("Id etapa referencia adicionales"), null=True, blank=True)

    class Meta:
        db_table = 'ETAPA'
    def __str__(self):
        return self.ET_CCODIGO + ' - ' + self.ET_CNOMBRE

class ETAPA_LOG(models.Model):
    CI_NID = models.ForeignKey(CITACION, verbose_name='Id citación', on_delete=models.PROTECT)
    EP_NID = models.ForeignKey(EMPRESA, verbose_name='Id empresa', on_delete=models.PROTECT)
    SC_NID = models.ForeignKey(SECUENCIA, verbose_name='Id secuencia', on_delete=models.PROTECT)
    ET_NID = models.ForeignKey(ETAPA, verbose_name='Id etapa', on_delete=models.PROTECT)
    US_INICIO_ID = models.ForeignKey(User, verbose_name='Usuario inicio etapa', on_delete=models.PROTECT, null=True, blank=True, related_name='etapas_log_inicio')
    US_FIN_ID = models.ForeignKey(User, verbose_name='Usuario fin etapa', on_delete=models.PROTECT, null=True, blank=True, related_name='etapas_log_fin')
    EL_FFECHAINICIO = models.DateTimeField(("Fecha de inicio"), null=True, blank=True)
    EL_FFECHAFIN = models.DateTimeField(("Fecha de fin"), null=True, blank=True)
    EL_CACCION = models.CharField(("Accion"), max_length=128, null=True, blank=True)
    EL_COBSERVACION = models.TextField(("Observacion"), null=True, blank=True)

    @property
    def TIEMPO_TRANSCURRIDO(self):
        try:
            if self.EL_FFECHAFIN:
                fecha_fin = timezone.localtime(self.EL_FFECHAFIN).replace(tzinfo=None)
                fecha_inicio = timezone.localtime(self.EL_FFECHAINICIO).replace(tzinfo=None)
                diferencia = fecha_fin - fecha_inicio
            else:
                fecha_inicio = timezone.localtime(self.EL_FFECHAINICIO).replace(tzinfo=None)
                diferencia = datetime.now() - fecha_inicio

            # Convertir total de días en horas y sumarlas a las horas actuales
            horas_totales = diferencia.days * 24 + diferencia.seconds // 3600
            minutos = (diferencia.seconds // 60) % 60
            segundos = diferencia.seconds % 60

            if horas_totales < 10:
                horas_totales = f"0{horas_totales}"
            if minutos < 10:
                minutos = f"0{minutos}"
            if segundos < 10:
                segundos = f"0{segundos}"

            return f"{horas_totales}:{minutos}:{segundos}"
        except Exception as e:
            print(e)
            return None
    class Meta:
        db_table = 'ETAPA_LOG'
    def __str__(self):
        return self.pk

class CAMPO(models.Model):
    TIPO_CHOICES = [
        ('TEXTO', 'Texto'),
        ('MULTILINEA', 'Multilínea'),
        ('NUMERO', 'Número'),
        ('DECIMAL', 'Decimal'),
        ('FECHA', 'Fecha'),
        ('FECHA/HORA', 'Fecha/Hora'),
        ('CHECK', 'Check'),
        ('LISTA', 'Lista'),
        ('ARCHIVO', 'Archivo'),
    ]

    US_NID = models.ForeignKey(User, verbose_name='Id usuario', on_delete=models.PROTECT, null=True, blank=True)
    EP_NID = models.ForeignKey(EMPRESA, verbose_name='Id empresa', on_delete=models.PROTECT)
    CA_CTIPO = models.CharField(("Tipo"), max_length=128, choices=TIPO_CHOICES, null=False)
    CA_CCODIGO = models.CharField(("Codigo"), max_length=128, null=True, blank=True)
    CA_CETIQUETA = models.CharField(("Etiqueta"), max_length=128, null=False)
    CA_CVALORDEFAULT = models.CharField(("Valor por defecto"), max_length=2048, null=True, blank=True)
    CA_CPLACEMARK = models.CharField(("Place Mark"), max_length=2048, null=True, blank=True)
    CA_CQUERY = models.TextField(("Query"), null=True, blank=True)
    CA_NLARGO = models.IntegerField(("Largo"), null=True, blank=True)
    CA_BOBLIGATORIO= models.BooleanField(("Obligatorio"), default=False)
    CA_BHABILITADO = models.BooleanField(("Habilitado"), default=False)
    CA_BVALIDARSAP = models.BooleanField(("Validar contra SAP"), default=False)
    CA_BASIGNARVALOR = models.BooleanField(("Asignar valor en bd"), default=False)

    class Meta:
        db_table = 'CAMPO'
        
    def __str__(self):
        return self.CA_CETIQUETA

class DETALLE_SECUENCIA(models.Model):
    US_NID = models.ForeignKey(User, verbose_name='Id usuario', on_delete=models.PROTECT)
    USERS_RESPONSABLE_ID = models.TextField(("Usuarios responsables"), null=True, blank=True)
    EP_NID = models.ForeignKey(EMPRESA, verbose_name='Id empresa', on_delete=models.PROTECT)
    SC_NID = models.ForeignKey(SECUENCIA, verbose_name='Id secuencia', on_delete=models.PROTECT)
    ET_NID = models.ForeignKey(ETAPA, verbose_name='Id etapa', on_delete=models.PROTECT)
    SE_NPASO = models.IntegerField(("Numero paso"), null=False)
    SE_BHABILITADO = models.BooleanField(("Habilitado"), default=False)
    SE_BOBLIGATORIO = models.BooleanField(("Obligatorio"), default=False)
    SE_FFECHAELIMICACION = models.DateTimeField(("Fecha de Eliminacion"), null=True)

    class Meta:
        db_table = 'DETALLE_SECUENCIA'

class DETALLE_ETAPA(models.Model):
    US_NID = models.ForeignKey(User, verbose_name='Id usuario', on_delete=models.PROTECT,blank=True,null=True)
    EP_NID = models.ForeignKey(EMPRESA, verbose_name='Id empresa', on_delete=models.PROTECT)
    ET_NID = models.ForeignKey(ETAPA, verbose_name='Id etapa', on_delete=models.PROTECT)
    CAMP_NID = models.ForeignKey(CAMPO, verbose_name='Id campo', on_delete=models.PROTECT)
    DET_NPASO = models.IntegerField(("Numero paso"), null=True,blank=True)
    DET_BOBLIGATORIO = models.BooleanField(("Obligatorio"), default=False)
    DET_CETIQUETAETAPA = models.CharField(("Etiqueta etapa"), max_length=128, null=True, blank=True)
    DET_BHABILITADO = models.BooleanField(("Habilitado"), default=False)

    class Meta:
        db_table = "DETALLE_ETAPA"

class CAMPO_OPCION(models.Model):
    US_NID = models.ForeignKey(User, verbose_name='Id usuario', on_delete=models.PROTECT,blank=True,null=True)
    EP_NID = models.ForeignKey(EMPRESA, verbose_name='Id empresa', on_delete=models.PROTECT)
    CAMP_NID = models.ForeignKey(CAMPO, verbose_name='Id campo', on_delete=models.PROTECT)
    CA_CTABLA = models.CharField(("Tabla"), max_length=128,null=True, blank=True)
    CA_CNOMBRECAMPO = models.CharField(("Nombre campo"), max_length=128, null=True, blank=True)
    CA_BHABILITADO = models.BooleanField(("Habilitado"), default=False)

    class Meta:
        db_table = 'CAMPO_OPCION'

class ETAPA_ACCION(models.Model):
    US_NID = models.ForeignKey(User, verbose_name='Id usuario', on_delete=models.PROTECT)
    EP_NID = models.ForeignKey(EMPRESA, verbose_name='Id empresa', on_delete=models.PROTECT)
    SC_NID = models.ForeignKey(SECUENCIA, verbose_name='Id secuencia', on_delete=models.PROTECT)
    ET_NID = models.ForeignKey(ETAPA, verbose_name='Id etapa', on_delete=models.PROTECT)
    CI_NID = models.ForeignKey(CITACION, verbose_name='Id citacion', on_delete=models.PROTECT)
    EA_CENDPOINT = models.CharField(("End point"), max_length=1024, null=False)
    EA_CPAYLOAD = models.TextField(("Payload"), null=False)
    EA_NPASO = models.IntegerField(("Numero paso"), null=False)
    EA_FFECHAREGISTRO = models.DateTimeField(("Fecha registro"), null=True, blank=True)

    class Meta:
        db_table = "ETAPA_ACCION"

class DATO_ACCION(models.Model):
    US_NID = models.ForeignKey(User, verbose_name='Id usuario', on_delete=models.PROTECT)
    EP_NID = models.ForeignKey(EMPRESA, verbose_name='Id empresa', on_delete=models.PROTECT)
    EA_NID = models.ForeignKey(ETAPA_ACCION, verbose_name='Id etapa accion', on_delete=models.PROTECT)
    CI_NID = models.ForeignKey(CITACION, verbose_name='Id citacion', on_delete=models.PROTECT)
    DA_CRESPONSE = models.CharField(("Response"), max_length=2048, null=False)
    DA_CCODIGORETORNO = models.CharField(("Codigo Retorno"), max_length=128, null=False)
    DA_CPAYLOAD = models.TextField(("Payload"), null=False)
    DA_FFECHAREGISTRO = models.DateTimeField(("Fecha registro"), null=True, blank=True)

    class Meta:
        db_table = "DATO_ACCION"

class DATO_OPERACION(models.Model):
    US_NID = models.ForeignKey(User, verbose_name='Id usuario', on_delete=models.PROTECT)
    EP_NID = models.ForeignKey(EMPRESA, verbose_name='Id empresa', on_delete=models.PROTECT)
    SC_NID = models.ForeignKey(SECUENCIA, verbose_name='Id secuencia', on_delete=models.PROTECT)
    ET_NID = models.ForeignKey(ETAPA, verbose_name='Id etapa', on_delete=models.PROTECT)
    CAMP_NID = models.ForeignKey(CAMPO, verbose_name='Id campo', on_delete=models.PROTECT)
    CI_NID = models.ForeignKey(CITACION, verbose_name='Id citacion', on_delete=models.PROTECT)
    DO_FFECHAREGISTRO = models.DateTimeField(("Fecha registro"), null=True, blank=True)
    DO_CVALOR = models.TextField(("Valor dato"), null=False)
    DO_NPESO = models.IntegerField(("Peso dato"), null=True, blank=True)

    class Meta:
        db_table = "DATO_OPERACION"


class CITACION_DOCUMENTO(models.Model):
    TIPO_GUIA = 'GUIA'
    TIPO_TICKET_ORIGEN = 'TICKET_ORIGEN'
    TIPO_SERNAPESCA = 'SERNAPESCA'
    TIPO_IMAGEN_SELLO_DESPACHO = 'IMAGEN_SELLO_DESPACHO'

    TIPOS_INICIALES = (
        (TIPO_GUIA, 'Guia'),
        (TIPO_TICKET_ORIGEN, 'Ticket origen'),
        (TIPO_SERNAPESCA, 'Sernapesca'),
        (TIPO_IMAGEN_SELLO_DESPACHO, 'Imagen sello despacho'),
    )

    CI_NID = models.ForeignKey(
        CITACION,
        verbose_name='Id citacion',
        on_delete=models.PROTECT,
        related_name='documentos_expediente'
    )
    EP_NID = models.ForeignKey(EMPRESA, verbose_name='Id empresa', on_delete=models.PROTECT)
    DO_NID = models.ForeignKey(
        DATO_OPERACION,
        verbose_name='Id dato operacion',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='documentos_expediente'
    )
    CD_CTIPO = models.CharField('Tipo documento', max_length=64, choices=TIPOS_INICIALES)
    CD_CRUTA_ARCHIVO = models.TextField('Ruta archivo')
    CD_CNOMBRE_ARCHIVO = models.CharField('Nombre archivo', max_length=255)
    CD_FFECHASUBIDA = models.DateTimeField('Fecha subida', auto_now_add=True)
    US_SUBE_NID = models.ForeignKey(
        User,
        verbose_name='Usuario subida',
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name='citacion_documentos_subidos'
    )
    CD_FFECHAMODIFICACION = models.DateTimeField('Fecha modificacion', null=True, blank=True)
    US_MODIFICA_NID = models.ForeignKey(
        User,
        verbose_name='Usuario modificacion',
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name='citacion_documentos_modificados'
    )
    CD_BACTIVO = models.BooleanField('Estado activo', default=True)

    class Meta:
        db_table = "CITACION_DOCUMENTO"
        indexes = [
            models.Index(fields=['EP_NID', 'CD_BACTIVO'], name='CIT_DOC_EP_ACT_idx'),
            models.Index(fields=['CI_NID', 'CD_CTIPO', 'CD_BACTIVO'], name='CIT_DOC_CI_TIPO_ACT_idx'),
            models.Index(fields=['CD_CTIPO'], name='CIT_DOC_TIPO_idx'),
            models.Index(fields=['CD_FFECHASUBIDA'], name='CIT_DOC_FECHA_idx'),
        ]


class ESTANQUE_RESERVA(models.Model):
    ESTADO_OCUPADO = 'OCUPADO'
    ESTADO_LIBERADO = 'LIBERADO'
    ESTADOS = (
        (ESTADO_OCUPADO, 'Ocupado'),
        (ESTADO_LIBERADO, 'Liberado'),
    )

    US_NID = models.ForeignKey(User, verbose_name='Usuario asignacion', on_delete=models.PROTECT)
    US_LIBERA_NID = models.ForeignKey(
        User,
        verbose_name='Usuario liberacion',
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name='estanques_liberados'
    )
    EP_NID = models.ForeignKey(EMPRESA, verbose_name='Empresa', on_delete=models.PROTECT)
    PL_NID = models.ForeignKey('PLANIFICACION', verbose_name='Planificacion', on_delete=models.PROTECT)
    CI_NID = models.ForeignKey(CITACION, verbose_name='Citacion', on_delete=models.PROTECT)
    ER_CALMACEN = models.CharField('Almacen', max_length=128)
    ER_CESTANQUE = models.CharField('Estanque', max_length=128)
    ER_CPATENTE = models.CharField('Patente', max_length=128, null=True, blank=True)
    ER_CESTADO = models.CharField('Estado reserva', max_length=32, choices=ESTADOS, default=ESTADO_OCUPADO)
    ER_FFECHA_ASIGNACION = models.DateTimeField('Fecha asignacion', default=timezone.now)
    ER_FFECHA_LIBERACION = models.DateTimeField('Fecha liberacion', null=True, blank=True)
    ER_COBSERVACION = models.TextField('Observacion', null=True, blank=True)

    class Meta:
        db_table = "ESTANQUE_RESERVA"
        constraints = [
            models.UniqueConstraint(
                fields=['EP_NID', 'ER_CALMACEN', 'ER_CESTANQUE'],
                condition=models.Q(ER_CESTADO='OCUPADO'),
                name='unique_estanque_ocupado_empresa_almacen'
            )
        ]

    def __str__(self):
        return f'{self.ER_CALMACEN} - {self.ER_CESTANQUE} ({self.ER_CESTADO})'


class OPERACION_PLANTA_LOG(models.Model):
    ESTADO_PENDIENTE = 'PENDIENTE'
    ESTADO_COMPLETADO = 'COMPLETADO'
    ESTADOS = (
        (ESTADO_PENDIENTE, 'Pendiente'),
        (ESTADO_COMPLETADO, 'Completado'),
    )

    US_NID = models.ForeignKey(User, verbose_name='Usuario', on_delete=models.PROTECT)
    EP_NID = models.ForeignKey(EMPRESA, verbose_name='Empresa', on_delete=models.PROTECT)
    PL_NID = models.ForeignKey('PLANIFICACION', verbose_name='Planificacion', on_delete=models.PROTECT)
    CI_NID = models.ForeignKey(CITACION, verbose_name='Citacion', on_delete=models.PROTECT)
    OPL_CPASO = models.CharField('Paso operacional', max_length=128)
    OPL_CPERFIL_RESPONSABLE = models.CharField('Perfil responsable', max_length=128)
    OPL_CESTADO = models.CharField('Estado', max_length=32, choices=ESTADOS, default=ESTADO_COMPLETADO)
    OPL_COBSERVACION = models.TextField('Observacion', null=True, blank=True)
    OPL_FFECHAREGISTRO = models.DateTimeField('Fecha registro', default=timezone.now)

    class Meta:
        db_table = "OPERACION_PLANTA_LOG"

    def __str__(self):
        return f'{self.CI_NID_id} - {self.OPL_CPASO} - {self.OPL_CESTADO}'


class RESULTADO_CALIDAD_OPERACION(models.Model):
    class Estado(models.TextChoices):
        PENDIENTE = 'PENDIENTE', 'Pendiente'
        APROBADO = 'APROBADO', 'Aprobado'
        RECHAZADO = 'RECHAZADO', 'Rechazado'
        APRUEBA_CLIENTE = 'APRUEBA_CLIENTE', 'Aprueba cliente'

    class Origen(models.TextChoices):
        OPERACION_PLANTA = 'OPERACION_PLANTA', 'Operacion Planta'
        EXCEL_CALIDAD = 'EXCEL_CALIDAD', 'Excel Calidad'
        CORREO_CLIENTE = 'CORREO_CLIENTE', 'Correo cliente'
        MANUAL_PRUEBA = 'MANUAL_PRUEBA', 'Manual / prueba'

    EP_NID = models.ForeignKey(EMPRESA, verbose_name='Empresa', on_delete=models.PROTECT)
    CI_NID = models.OneToOneField(
        CITACION,
        verbose_name='Citacion',
        on_delete=models.PROTECT,
        related_name='resultado_calidad_operacion',
    )
    PL_NID = models.ForeignKey(PLANIFICACION, verbose_name='Proceso Operacion Planta', on_delete=models.PROTECT)
    ET_NID = models.ForeignKey(ETAPA, verbose_name='Etapa operacional', on_delete=models.PROTECT, null=True, blank=True)
    CA_NID = models.ForeignKey(CAMION, verbose_name='Patente / camion', on_delete=models.PROTECT, null=True, blank=True)
    RCO_CNUMERO_GUIA = models.CharField('Numero de guia', max_length=128, null=True, blank=True, db_index=True)
    RCO_CESTADO = models.CharField('Estado actual', max_length=32, choices=Estado.choices, default=Estado.PENDIENTE)
    RCO_CORIGEN = models.CharField('Origen actualizacion', max_length=32, choices=Origen.choices, default=Origen.OPERACION_PLANTA)
    RCO_FINICIO = models.DateTimeField('Inicio analisis')
    RCO_FACTUALIZACION = models.DateTimeField('Ultimo cambio', default=timezone.now)
    RCO_FDETENCION_TEMPORIZADOR = models.DateTimeField('Detencion temporizador', null=True, blank=True)
    RCO_FSOLICITUD_CLIENTE = models.DateTimeField('Solicitud aprobacion cliente', null=True, blank=True)
    RCO_FRESOLUCION_FINAL = models.DateTimeField('Resolucion final', null=True, blank=True)
    RCO_FCIERRE = models.DateTimeField('Cierre definitivo', null=True, blank=True)
    RCO_COBSERVACION = models.TextField('Observacion', null=True, blank=True)
    US_NID = models.ForeignKey(User, verbose_name='Usuario responsable', on_delete=models.PROTECT, null=True, blank=True)
    RCO_CRESPONSABLE_SISTEMA = models.CharField('Sistema responsable', max_length=128, null=True, blank=True)
    RCO_BCIERRE_AUTOMATICO = models.BooleanField('Cierre automatico', default=False)
    RCO_BAUTORIZA_SALIDA = models.BooleanField('Autorizacion de salida', default=False)
    RCO_NDURACION_SEGUNDOS = models.BigIntegerField('Duracion acumulada analisis', default=0)

    class Meta:
        db_table = 'RESULTADO_CALIDAD_OPERACION'
        indexes = [
            models.Index(fields=['EP_NID', 'RCO_CNUMERO_GUIA'], name='RCO_EP_GUIA_IDX'),
            models.Index(fields=['EP_NID', 'RCO_CESTADO'], name='RCO_EP_ESTADO_IDX'),
        ]

    @property
    def temporizador_activo(self):
        return self.RCO_FDETENCION_TEMPORIZADOR is None and self.RCO_CESTADO == self.Estado.PENDIENTE

    def __str__(self):
        return f'{self.CI_NID_id} - {self.RCO_CESTADO}'


class RESULTADO_CALIDAD_HISTORIAL(models.Model):
    RCO_NID = models.ForeignKey(
        RESULTADO_CALIDAD_OPERACION,
        verbose_name='Resultado calidad',
        on_delete=models.CASCADE,
        related_name='historial',
    )
    EP_NID = models.ForeignKey(EMPRESA, verbose_name='Empresa', on_delete=models.PROTECT)
    CI_NID = models.ForeignKey(CITACION, verbose_name='Citacion', on_delete=models.PROTECT)
    RCH_CEVENTO = models.CharField('Evento', max_length=64)
    RCH_CESTADO_ANTERIOR = models.CharField('Estado anterior', max_length=32, null=True, blank=True)
    RCH_CESTADO_NUEVO = models.CharField('Estado nuevo', max_length=32)
    RCH_CORIGEN = models.CharField('Origen', max_length=32, choices=RESULTADO_CALIDAD_OPERACION.Origen.choices)
    RCH_CRESULTADO = models.CharField('Resultado', max_length=32, null=True, blank=True)
    RCH_COBSERVACION = models.TextField('Observacion', null=True, blank=True)
    US_NID = models.ForeignKey(User, verbose_name='Usuario responsable', on_delete=models.PROTECT, null=True, blank=True)
    RCH_CRESPONSABLE_SISTEMA = models.CharField('Sistema responsable', max_length=128, null=True, blank=True)
    RCH_FFECHAREGISTRO = models.DateTimeField('Fecha registro', default=timezone.now)

    class Meta:
        db_table = 'RESULTADO_CALIDAD_HISTORIAL'
        indexes = [
            models.Index(fields=['CI_NID', 'RCH_FFECHAREGISTRO'], name='RCH_CI_FECHA_IDX'),
        ]


#####################################################################
########################## PERFILAMIENTO ############################
#####################################################################

class PERFIL(models.Model):
    US_NID = models.ForeignKey(User, verbose_name='Id usuario', on_delete=models.PROTECT)
    PR_CCODIGO = models.CharField(("Codigo perfil"), max_length=128, null=False)
    PR_CNOMBRE = models.CharField(("Nombre perfil"), max_length=128, null=False)
    PR_CDESCRIPCION = models.TextField(("Descripcion"), null=True, blank=True)
    PR_BHABILITADO = models.BooleanField(("Habilitado"), default=True)

    class Meta:
        db_table = "PERFIL"

    def __str__ (self):
        return self.PR_CNOMBRE
    @property
    def CHECK_PERMISOS(self, id_vista):
        permiso = PERMISO.objects.filter(PR_NID = self.pk , VI_NID = id_vista).first()
        return True if permiso else False

class VISTA(models.Model):

    US_NID = models.ForeignKey(User, verbose_name='Id usuario', on_delete=models.PROTECT)    
    VI_CCODIGO = models.CharField(("Codigo vista"), max_length=128, null=False)
    VI_CNOMBRE = models.CharField(("Nombre vista"), max_length=128, null=False)
    VI_CDESCRIPCION = models.TextField(("Descripcion"), null=True, blank=True)
    VI_BHABILITADO = models.BooleanField(("Habilitado"), default=True)

    class Meta:
        db_table = "VISTA"

    def __str__ (self):
        return self.VI_CCODIGO

class PERMISO(models.Model):

    US_NID = models.ForeignKey(User, verbose_name='Id usuario', on_delete=models.PROTECT)
    PR_NID = models.ForeignKey(PERFIL, verbose_name='Id perfil', on_delete=models.PROTECT)
    VI_NID = models.ForeignKey(VISTA, verbose_name='Id vista', on_delete=models.PROTECT)
    PE_BHABILITADO = models.BooleanField(("Habilitado"), default=True)

    class Meta:
        db_table = "PERMISO"

class PERFIL_USUARIO(models.Model):
    US_NID = models.ForeignKey(User, verbose_name='Id usuario', on_delete=models.PROTECT)
    PR_NID = models.ForeignKey(PERFIL, verbose_name='Id perfil', on_delete=models.PROTECT)
    PE_BHABILITADO = models.BooleanField(("Habilitado"), default=True)

    class Meta:
        db_table = "PERFIL_USUARIO"

class PROFORMA(models.Model):
    EP_NID = models.ForeignKey(EMPRESA, verbose_name='Id empresa', on_delete=models.PROTECT)
    US_NID = models.ForeignKey(User, verbose_name='Id usuario', on_delete=models.PROTECT)
    SN_NID = models.ForeignKey(SOCIONEGOCIO, verbose_name='Id socionegocio', on_delete=models.PROTECT, null=True)
    PRO_CESTADO = models.CharField(("Estado proforma"), max_length=256, null=False)
    PRO_CCOMENTARIO = models.TextField(("Comentario"), null=True, blank=True)
    PRO_NSUBTOTAL = models.DecimalField(("Sub total"), decimal_places=5, max_digits=18, null=False)
    PRO_NIVA = models.DecimalField(("Iva"), decimal_places=5, max_digits=18, null=False)
    PRO_NTOTAL = models.DecimalField(("Total"), decimal_places=5, max_digits=18, null=False)
    PRO_NINGRESO = models.DecimalField(("Ingreso"), decimal_places=5, max_digits=18, null=False)
    PRO_NDESCUENTO = models.DecimalField(("Descuento"), decimal_places=5, max_digits=18, null=False)
    PRO_FFECHAREGISTRO = models.DateTimeField(("Fecha registro"), null=True, blank=True)
    PRO_FFECHAEMISION = models.DateTimeField(("Fecha emision"), null=True)
    PRO_CTIPO = models.CharField(("Tipo citacion"), max_length=128, null=True, blank=True)
    PRO_DOC_NUM = models.CharField(("DocNum"), max_length=128, null=True, blank=True)
    PRO_DOC_ENTRY = models.IntegerField(("DocEntry"), null=True, blank=True)
    PRO_FOLIO = models.IntegerField(("Folio"), null=True, blank=True)
    PRO_CNUMERO_DOCUMENTO = models.CharField(("Numero documento"), max_length=128, null=True, blank=True)
    PRO_BBORRADOR = models.BooleanField(("Borrador"), default=True)
    PRO_BSINEXTRAS = models.BooleanField(("Sin Extras"), default=False)
    PRO_BSOLOEXTRAS = models.BooleanField(("Solo extras"), default=False)

    class Meta:
        db_table = "PROFORMA"

class EXTRA_PROFORMA(models.Model):
    EP_NID = models.ForeignKey(EMPRESA, verbose_name='Id empresa', on_delete=models.PROTECT)
    CIE_NID = models.ForeignKey(CITACION_EXTRA, verbose_name='Id citacion extra', on_delete=models.PROTECT)
    PRO_NID = models.ForeignKey(PROFORMA, verbose_name='Id Proforma', on_delete=models.PROTECT)
    EPR_NVALOR = models.DecimalField(("Valor"), decimal_places=5, max_digits=18, null=False)
    EPR_BINGRESO = models.BooleanField(("Ingreso"), default=False)
    EPR_BHABILITADO = models.BooleanField(("Habilitado"), default=True)

    class Meta:
        db_table = "EXTRA_PROFORMA"

class CITACION_PROFORMA(models.Model):
    EP_NID = models.ForeignKey(EMPRESA, verbose_name='Id empresa', on_delete=models.PROTECT)
    CI_NID = models.ForeignKey(CITACION, verbose_name='id citacion', on_delete=models.PROTECT)
    PRO_NID = models.ForeignKey(PROFORMA, verbose_name='Id Proforma', on_delete=models.PROTECT)
    CIP_NSUBTOTAL = models.DecimalField(("Subtotal"), max_digits=18, decimal_places=5, null=False)

    class Meta:
        db_table = "CITACION_PROFORMA"
    
    def GET_ITEM_CODE(self):
        item_code, account_number = get_citacion_item_code(self.CI_NID.CI_CTIPO_FLETE, self.EP_NID_id)
        return item_code, account_number

    def GET_CITACION_EXTRA(self):
        citacion_extra = list(CITACION_EXTRA.objects.filter(CI_NID = self.CI_NID).values_list("id"))
        if not citacion_extra:
            return 0
        
        extra_proformas = EXTRA_PROFORMA.objects.filter(CIE_NID__in = citacion_extra, EPR_BHABILITADO = True)
        if not extra_proformas:
            return 0
        
        total = 0
        for extra in extra_proformas:
            if extra.EPR_BINGRESO:
                total += extra.EPR_NVALOR
            else:
                total -= extra.EPR_NVALOR
        return total
    
class DOCUMENTO_PROFORMA(models.Model):
    EP_NID = models.ForeignKey(EMPRESA, verbose_name='Id empresa', on_delete=models.PROTECT)
    US_NID = models.ForeignKey(User, verbose_name='Id usuario creador', on_delete=models.PROTECT)
    PRO_NID = models.ForeignKey(PROFORMA, verbose_name="id_proforma_documento", on_delete=models.PROTECT)
    DP_CNOMBREDOCUMENTO = models.CharField(("Nombre documento"), max_length=128, null=False)
    DP_CRUTADOC = models.CharField(("Ruta documento"), max_length=128, null=False)
    DP_FFECHAREGISTRO = models.DateTimeField(("Fecha registro"), null=True, blank=True)
    DP_BHABILITADO = models.BooleanField(("Habilitado"), default=True)

    class Meta:
        db_table = 'DOCUMENTO_PROFORMA'

class LINEA_PROFORMA(models.Model):
    PRO_NID = models.ForeignKey(PROFORMA, verbose_name="id_proforma_manual", on_delete=models.PROTECT)
    LP_CTIPO_ITEM = models.CharField(("Tipo Item"), max_length=128, null=False)
    LP_NCANTIDAD = models.IntegerField(("Cantidad"), null=False)
    LP_NPRECIO_UNITARIO = models.DecimalField(("Precio unitario"), max_digits=18, decimal_places=2, null=False)
    LP_CDESCRIPCION = models.CharField(("Descripcion"), max_length=256, null=False)
    LP_FFECHACREACION = models.DateTimeField(("Fecha creacion"), auto_now_add=True)
    US_NID = models.ForeignKey(User, verbose_name="usuario_creado_fila", on_delete=models.PROTECT)
    
    class Meta:
        db_table = "LINEA_PROFORMA"

    def GET_ITEM_CODE(self):
        item_code, account_number = get_linea_item_code(self.LP_CTIPO_ITEM, self.PRO_NID.EP_NID_id)
        return item_code, account_number
    
    
#####################################################################
######################### NOTIFICACIONES ############################
#####################################################################

class NOTIFICACION(models.Model):
    USER_SENDER_ID = models.ForeignKey(User, verbose_name='id usuario emisor', on_delete=models.PROTECT, related_name='user_sender')
    USER_RECEIVER_ID = models.ForeignKey(User, verbose_name='id usuario receptor', on_delete=models.PROTECT, related_name='user_receiver')
    EP_NID = models.ForeignKey(EMPRESA, verbose_name='Id empresa', on_delete=models.PROTECT)
    NOT_CCONTENIDO = models.TextField(("Contenido"), null=False)
    NOT_CURL = models.CharField(("url"), max_length=1024, null=True, blank=True)
    NOT_BHABILITADO = models.BooleanField(("Habilitado"), default=True)
    NOT_FFECHAREGISTRO = models.DateTimeField(("Fecha registro"), auto_now_add=True)
    NOT_FFECHALEIDO = models.DateTimeField(("Fecha leido"), null=True, blank=True)
    NOT_BREAD = models.BooleanField(("Leido"), default=False)

    class Meta:
        db_table = "NOTIFICACION"


def camion_no_planificado_upload_path(instance, filename):
    empresa_id = instance.EP_NID_id or 'sin_empresa'
    planificacion_id = instance.PL_NID_id or 'sin_planificacion'
    return f'camiones_no_planificados/{empresa_id}/{planificacion_id}/{filename}'


class CAMION_NO_PLANIFICADO(models.Model):
    ESTADO_PENDIENTE = 'PENDIENTE_REVISION'
    ESTADO_PLANIFICADO = 'PLANIFICADO'
    ESTADO_RECHAZADO = 'RECHAZADO'
    ESTADO_CORRECCION = 'CORRECCION_SOLICITADA'

    ESTADO_CHOICES = [
        (ESTADO_PENDIENTE, 'Pendiente de revision'),
        (ESTADO_PLANIFICADO, 'Planificado'),
        (ESTADO_RECHAZADO, 'Rechazado'),
        (ESTADO_CORRECCION, 'Correccion solicitada'),
    ]

    EP_NID = models.ForeignKey(EMPRESA, verbose_name='Id empresa', on_delete=models.PROTECT)
    PL_NID = models.ForeignKey(PLANIFICACION, verbose_name='Id planificacion', on_delete=models.PROTECT)
    US_GUARDIA_ID = models.ForeignKey(User, verbose_name='Usuario guardia', on_delete=models.PROTECT, related_name='camiones_no_planificados_solicitados')
    CLI_CCODIGO = models.CharField('Codigo cliente', max_length=128, null=True, blank=True)
    CLI_CNOMBRE = models.CharField('Cliente', max_length=256)
    CNP_CINSUMO = models.CharField('Insumo', max_length=256)
    CNP_CNUMEROGUIA = models.CharField('Numero guia', max_length=128)
    CNP_CPATENTE = models.CharField('Patente', max_length=32)
    CNP_CEMPRESATRANSPORTE = models.CharField('Empresa transporte', max_length=256)
    CNP_COBSERVACION = models.TextField('Observacion', null=True, blank=True)
    CNP_FARCHIVOGUIA = models.FileField('Archivo guia', upload_to=camion_no_planificado_upload_path)
    CNP_CESTADO = models.CharField('Estado', max_length=32, choices=ESTADO_CHOICES, default=ESTADO_PENDIENTE)
    US_PLANIFICADOR_ID = models.ForeignKey(User, verbose_name='Usuario planificador', on_delete=models.PROTECT, null=True, blank=True, related_name='camiones_no_planificados_resueltos')
    CNP_COBSERVACION_RECHAZO = models.TextField('Observacion rechazo', null=True, blank=True)
    CNP_FFECHACREACION = models.DateTimeField('Fecha creacion', auto_now_add=True)
    CNP_FFECHARESPUESTA = models.DateTimeField('Fecha respuesta', null=True, blank=True)

    class Meta:
        db_table = 'CAMION_NO_PLANIFICADO'
        indexes = [
            models.Index(fields=['EP_NID', 'PL_NID', 'CNP_CPATENTE', 'CNP_CESTADO']),
        ]

    def __str__(self):
        return f'{self.CNP_CPATENTE} - {self.CNP_CESTADO}'


def camion_patio_upload_path(instance, filename):
    camion = instance.CPA_NID
    empresa_id = camion.EP_NID_id or 'sin_empresa'
    patente = ''.join(ch for ch in (camion.CPA_CPATENTE or 'sin_patente').upper() if ch.isalnum())
    return f'camiones_patio/{empresa_id}/{patente}/{filename}'


TRANSPORTE_A_CARGO_CHOICES = [
    ('TERRAMAR', 'Terramar'),
    ('CLIENTE', 'Cliente'),
]


class CAMION_PATIO(models.Model):
    ESTADO_PENDIENTE_ASOCIACION = 'PENDIENTE_ASOCIACION'
    ESTADO_EN_REVISION_RECEPCION = 'EN_REVISION_RECEPCION'
    ESTADO_ASOCIADO_CITACION = 'ASOCIADO_CITACION'
    ESTADO_RECHAZADO = 'RECHAZADO'
    ESTADO_CANCELADO = 'CANCELADO'

    ESTADOS = (
        (ESTADO_PENDIENTE_ASOCIACION, 'Pendiente asociacion'),
        (ESTADO_EN_REVISION_RECEPCION, 'En revision recepcion'),
        (ESTADO_ASOCIADO_CITACION, 'Asociado a citacion'),
        (ESTADO_RECHAZADO, 'Rechazado'),
        (ESTADO_CANCELADO, 'Cancelado'),
    )

    EP_NID = models.ForeignKey(EMPRESA, verbose_name='Empresa', on_delete=models.PROTECT)
    CI_NID = models.ForeignKey(CITACION, verbose_name='Citacion asociada', on_delete=models.PROTECT, null=True, blank=True, related_name='camiones_patio')
    transporte_a_cargo = models.CharField('Transporte a cargo de', max_length=20, choices=TRANSPORTE_A_CARGO_CHOICES, default='TERRAMAR')
    CPA_CPATENTE = models.CharField('Patente camion', max_length=32)
    CPA_CPATENTE_RAMPLA = models.CharField('Patente rampla/acoplado', max_length=32, null=True, blank=True)
    CPA_CNOMBRE_CONDUCTOR = models.CharField('Nombre conductor', max_length=256)
    CPA_CRUT_CONDUCTOR = models.CharField('RUT conductor', max_length=32, null=True, blank=True)
    CPA_CTELEFONO_CONDUCTOR = models.CharField('Telefono conductor', max_length=64, null=True, blank=True)
    CPA_CTRANSPORTISTA_DECLARADO = models.CharField('Transportista declarado', max_length=256, null=True, blank=True)
    CPA_CPROVEEDOR_DECLARADO = models.CharField('Proveedor declarado', max_length=256, null=True, blank=True)
    CPA_CPRODUCTO_DECLARADO = models.CharField('Producto declarado', max_length=256, null=True, blank=True)
    CPA_CINSUMO_DECLARADO_GUIA = models.CharField('Insumo declarado en guia', max_length=256, null=True, blank=True)
    CPA_CCLIENTE_DECLARADO = models.CharField('Cliente declarado', max_length=256, null=True, blank=True)
    CPA_CNUMERO_GUIA = models.CharField('Numero guia/documento', max_length=128, null=True, blank=True)
    CPA_CBL = models.CharField('BL', max_length=128, null=True, blank=True)
    CPA_CCANTIDAD_EJES = models.CharField('Cantidad de ejes', max_length=64, null=True, blank=True)
    CPA_CLOTE_CONTENEDOR = models.CharField('Lote/contenedor', max_length=128, null=True, blank=True)
    CPA_COBSERVACION = models.TextField('Observacion', null=True, blank=True)
    CPA_CESTADO = models.CharField('Estado', max_length=32, choices=ESTADOS, default=ESTADO_PENDIENTE_ASOCIACION)
    US_GUARDIA_ID = models.ForeignKey(User, verbose_name='Usuario guardia', on_delete=models.PROTECT, related_name='camiones_patio_registrados')
    US_ASOCIA_ID = models.ForeignKey(User, verbose_name='Usuario asocia', on_delete=models.PROTECT, null=True, blank=True, related_name='camiones_patio_asociados')
    CPA_FFECHALLEGADA = models.DateTimeField('Fecha/hora llegada', default=timezone.now)
    CPA_FFECHACREACION = models.DateTimeField('Fecha creacion', auto_now_add=True)
    CPA_FFECHAACTUALIZACION = models.DateTimeField('Fecha actualizacion', auto_now=True)
    CPA_FFECHAASOCIACION = models.DateTimeField('Fecha asociacion', null=True, blank=True)

    class Meta:
        db_table = 'CAMION_PATIO'
        indexes = [
            models.Index(fields=['EP_NID', 'CPA_CESTADO'], name='CAM_PATIO_EP_EST_idx'),
            models.Index(fields=['EP_NID', 'CPA_CPATENTE'], name='CAM_PATIO_EP_PAT_idx'),
            models.Index(fields=['CI_NID'], name='CAM_PATIO_CIT_idx'),
        ]

    def __str__(self):
        return f'{self.CPA_CPATENTE} - {self.CPA_CESTADO}'


class CAMION_PATIO_ADJUNTO(models.Model):
    TIPO_GUIA = 'GUIA'
    TIPO_TICKET_ORIGEN = 'TICKET_ORIGEN'
    TIPO_SERNAPESCA = 'SERNAPESCA'
    TIPO_OTRO = 'OTRO'

    TIPOS = (
        (TIPO_GUIA, 'Guia'),
        (TIPO_TICKET_ORIGEN, 'Ticket origen'),
        (TIPO_SERNAPESCA, 'Sernapesca'),
        (TIPO_OTRO, 'Otro'),
    )

    CPA_NID = models.ForeignKey(CAMION_PATIO, verbose_name='Camion patio', on_delete=models.CASCADE, related_name='adjuntos')
    CPA_FARCHIVO = models.FileField('Archivo', upload_to=camion_patio_upload_path)
    CPA_CTIPO_DOCUMENTO = models.CharField('Tipo documento', max_length=64, choices=TIPOS, default=TIPO_OTRO)
    CPA_FFECHACARGA = models.DateTimeField('Fecha carga', auto_now_add=True)
    US_CARGA_ID = models.ForeignKey(User, verbose_name='Usuario carga', on_delete=models.PROTECT, related_name='camiones_patio_adjuntos')

    class Meta:
        db_table = 'CAMION_PATIO_ADJUNTO'
        indexes = [
            models.Index(fields=['CPA_NID', 'CPA_CTIPO_DOCUMENTO'], name='CAM_PAT_ADJ_TIPO_idx'),
        ]

    def __str__(self):
        return f'{self.CPA_NID_id} - {self.CPA_CTIPO_DOCUMENTO}'


class CAMION_PATIO_NO_PLANIFICADO(models.Model):
    ESTADO_PENDIENTE = 'PENDIENTE'
    ESTADO_APROBADO_PENDIENTE_PLANIFICACION = 'APROBADO_PENDIENTE_PLANIFICACION'
    ESTADO_APROBADO = 'APROBADO'
    ESTADO_RECHAZADO = 'RECHAZADO'

    ESTADOS = (
        (ESTADO_PENDIENTE, 'Pendiente de revision'),
        (ESTADO_APROBADO_PENDIENTE_PLANIFICACION, 'Aprobado pendiente de planificacion'),
        (ESTADO_APROBADO, 'Aprobado'),
        (ESTADO_RECHAZADO, 'Rechazado'),
    )

    CPA_NID = models.ForeignKey(
        CAMION_PATIO,
        verbose_name='Camion patio',
        on_delete=models.CASCADE,
        related_name='solicitudes_no_planificado'
    )
    EP_NID = models.ForeignKey(EMPRESA, verbose_name='Empresa', on_delete=models.PROTECT)
    CPNP_CESTADO = models.CharField('Estado', max_length=50, choices=ESTADOS, default=ESTADO_PENDIENTE)
    US_SOLICITA_ID = models.ForeignKey(
        User,
        verbose_name='Usuario solicitante',
        on_delete=models.PROTECT,
        related_name='camiones_patio_no_planificados_solicitados'
    )
    CPNP_FFECHASOLICITUD = models.DateTimeField('Fecha solicitud', auto_now_add=True)
    US_PLANIFICADOR_ID = models.ForeignKey(
        User,
        verbose_name='Usuario planificador',
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name='camiones_patio_no_planificados_resueltos'
    )
    CPNP_FFECHARESOLUCION = models.DateTimeField('Fecha resolucion', null=True, blank=True)
    CPNP_CMOTIVO_RECHAZO = models.TextField('Motivo rechazo', blank=True)
    CPNP_BTEAMS_ENVIADO = models.BooleanField('Teams enviado', default=False)
    CPNP_CTEAMS_ESTADO = models.CharField('Estado Teams', max_length=50, blank=True)
    CPNP_CTEAMS_DETALLE = models.TextField('Detalle Teams', blank=True)
    PL_NID = models.ForeignKey(
        PLANIFICACION,
        verbose_name='Planificacion creada',
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name='solicitudes_camion_patio_no_planificado'
    )
    CI_NID = models.ForeignKey(
        CITACION,
        verbose_name='Citacion creada',
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name='solicitudes_camion_patio_no_planificado'
    )

    class Meta:
        db_table = 'CAMION_PATIO_NO_PLANIFICADO'
        constraints = [
            models.UniqueConstraint(
                fields=['CPA_NID'],
                condition=models.Q(CPNP_CESTADO='PENDIENTE'),
                name='uniq_cam_pat_no_plan_pendiente'
            )
        ]
        indexes = [
            models.Index(fields=['EP_NID', 'CPNP_CESTADO'], name='CAM_PAT_NP_EP_EST_idx'),
        ]

    def __str__(self):
        return f'{self.CPA_NID_id} - {self.CPNP_CESTADO}'

#####################################################################
######################### CUPOS PROVEEDOR ###########################
#####################################################################

class CUPO_PROVEEDOR(models.Model):
    EP_NID = models.ForeignKey(EMPRESA, verbose_name='Id empresa', on_delete=models.PROTECT)
    PRO_NID = models.ForeignKey(SOCIONEGOCIO, verbose_name='Id socionegocio', on_delete=models.PROTECT)
    PLA_NID = models.ForeignKey(PLANIFICACION, verbose_name='Id planificacion', on_delete=models.PROTECT)
    CUP_NCUPOS = models.IntegerField(("Cupos"), null=False)
    CUP_BSOBRECUPO = models.BooleanField(("Sobre cupo"), default=False)
    CUP_FFECHAREGISTRO = models.DateTimeField(("Fecha registro"), auto_now_add=True)

    class Meta:
        db_table = "CUPO_PROVEEDOR"

    @property
    def CUPOS_DISPONIBLES(self):
        planificacion = self.PLA_NID
        citaciones = CITACION.objects.filter(CI_BHABILITADO = True, PL_NID = planificacion, CI_BARCHIVADO = False).count()
        return self.CUP_NCUPOS - citaciones
    
    @property
    def CUPOS_ASIGNADOS(self):
        planificacion = self.PLA_NID
        citaciones = CITACION.objects.filter(CI_BHABILITADO = True, PL_NID = planificacion, CI_BARCHIVADO = False).count()
        return citaciones

