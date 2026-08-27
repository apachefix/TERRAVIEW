from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from apps.home.models import CITACION_PROFORMA, EXTRA_PROFORMA, PROFORMA, SYSLOGGER
from apps.home.services.proforma_mensual import (
    obtener_o_crear_borrador_extras, recalcular_totales,
)


class Command(BaseCommand):
    help = 'Separa de forma controlada EPR 2612/CIE 3971 de la Proforma 1286.'

    def add_arguments(self, parser):
        parser.add_argument('--user-id', type=int, required=True)
        parser.add_argument('--apply', action='store_true')

    @transaction.atomic
    def handle(self, *args, **options):
        User = get_user_model()
        try:
            actor = User.objects.get(pk=options['user_id'], is_active=True)
        except User.DoesNotExist as exc:
            raise CommandError('El usuario de auditoría no existe o está inactivo.') from exc
        try:
            flete = PROFORMA.objects.select_for_update().get(
                pk=1286, EP_NID_id=1
            )
        except PROFORMA.DoesNotExist as exc:
            raise CommandError('No existe la Proforma Terramar 1286.') from exc
        if (
            flete.PRO_CTIPO != 'RECEPCION'
            or flete.PRO_CESTADO != 'CREADO'
            or not flete.PRO_BBORRADOR
            or flete.PRO_DOC_ENTRY is not None
            or str(flete.PRO_DOC_NUM or '').strip()
        ):
            raise CommandError('La Proforma 1286 ya no cumple las precondiciones autorizadas.')
        asociaciones = list(
            CITACION_PROFORMA.objects.select_for_update()
            .filter(PRO_NID=flete).order_by('pk')
        )
        citacion_ids = sorted(item.CI_NID_id for item in asociaciones)
        subtotal_fletes = sum(
            (Decimal(item.CIP_NSUBTOTAL or 0) for item in asociaciones), Decimal('0')
        )
        if citacion_ids != [38640, 38641, 38659, 38666]:
            raise CommandError(f'Las citaciones de 1286 cambiaron: {citacion_ids}.')
        if subtotal_fletes != Decimal('426119'):
            raise CommandError(f'El subtotal de Fletes cambió: {subtotal_fletes}.')
        snapshot = EXTRA_PROFORMA.objects.select_for_update().select_related(
            'CIE_NID'
        ).filter(pk=2612, CIE_NID_id=3971).first()
        if not snapshot:
            raise CommandError('No existe EPR 2612 / CIE 3971.')
        if snapshot.PRO_NID_id != flete.pk:
            if snapshot.PRO_NID.PRO_CTIPO != 'RECEPCION EXTRAS':
                raise CommandError(
                    f'EPR 2612 está asociada inesperadamente a Proforma {snapshot.PRO_NID_id}.'
                )
            extras_existente = snapshot.PRO_NID
            restantes = list(
                EXTRA_PROFORMA.objects.select_for_update()
                .filter(PRO_NID=flete).order_by('pk')
            )
            estructura_restante = [
                (item.pk, item.CIE_NID_id, str(item.EPR_NVALOR), item.EPR_BHABILITADO)
                for item in restantes
            ]
            esperada_restante = [
                (2578, 3937, '90000.00000', False),
                (2611, 3970, '100000.00000', False),
            ]
            if not restantes:
                self.stdout.write(self.style.SUCCESS(
                    f'YA REPARADA: todos los snapshots están en Proforma Extras #{extras_existente.pk}.'
                ))
                return
            if estructura_restante != esperada_restante:
                raise CommandError(
                    f'La reparación parcial tiene snapshots inesperados: {estructura_restante}.'
                )
            self.stdout.write(
                f'REPARACIÓN PARCIAL: falta mover {estructura_restante} a Extras #{extras_existente.pk}.'
            )
            if not options['apply']:
                transaction.set_rollback(True)
                self.stdout.write(self.style.WARNING(
                    'DRY-RUN: use --apply para completar la separación estructural.'
                ))
                return
            SYSLOGGER.objects.create(
                US_NID=actor, EP_NID_id=1, LOG_FFECHAREGISTRO=timezone.now(),
                LOG_CMODULO='PROFORMA', LOG_COPERACION='REP_1286_COMPLETA',
                LOG_CADD1='Proforma: 1286', LOG_CADD2=f'Extras: {extras_existente.pk}',
                LOG_CDESCRIPCION=(
                    'Completa separación estructural autorizada moviendo snapshots '
                    f'deshabilitados sin reactivarlos: {estructura_restante}.'
                ),
            )
            EXTRA_PROFORMA.objects.filter(
                pk__in=[item.pk for item in restantes]
            ).update(PRO_NID=extras_existente)
            recalcular_totales(flete)
            recalcular_totales(extras_existente)
            if EXTRA_PROFORMA.objects.filter(PRO_NID=flete).exists():
                raise CommandError('Persisten snapshots de Extras en la Proforma 1286.')
            self.stdout.write(self.style.SUCCESS(
                f'REPARACIÓN COMPLETADA: snapshots {[item.pk for item in restantes]} '
                f'movidos deshabilitados a Extras #{extras_existente.pk}.'
            ))
            return
        if Decimal(snapshot.EPR_NVALOR or 0) != Decimal('250000'):
            raise CommandError(f'El valor de EPR 2612 cambió: {snapshot.EPR_NVALOR}.')
        snapshots_mover = list(
            EXTRA_PROFORMA.objects.select_for_update()
            .filter(PRO_NID=flete).order_by('pk')
        )
        estructura = [
            (item.pk, item.CIE_NID_id, str(item.EPR_NVALOR), item.EPR_BHABILITADO)
            for item in snapshots_mover
        ]
        esperada_estructura = [
            (2578, 3937, '90000.00000', False),
            (2611, 3970, '100000.00000', False),
            (2612, 3971, '250000.00000', True),
        ]
        if estructura != esperada_estructura:
            raise CommandError(f'Los snapshots de Extras cambiaron: {estructura}.')
        antes = {
            'subtotal': str(flete.PRO_NSUBTOTAL), 'iva': str(flete.PRO_NIVA),
            'total': str(flete.PRO_NTOTAL), 'epr': snapshot.pk,
            'cie': snapshot.CIE_NID_id,
            'snapshots_movidos': [item.pk for item in snapshots_mover], 'valor_extra': str(snapshot.EPR_NVALOR),
            'citaciones': citacion_ids, 'snapshots_extras': estructura,
        }
        self.stdout.write(f'ANTES: {antes}')
        if not options['apply']:
            transaction.set_rollback(True)
            self.stdout.write(self.style.WARNING(
                'DRY-RUN: use --apply para ejecutar la reparación autorizada.'
            ))
            return
        SYSLOGGER.objects.create(
            US_NID=actor, EP_NID_id=1, LOG_FFECHAREGISTRO=timezone.now(),
            LOG_CMODULO='PROFORMA', LOG_COPERACION='REP_1286_ANTES',
            LOG_CADD1='Proforma: 1286', LOG_CADD2='EPR: 2612; CIE: 3971',
            LOG_CDESCRIPCION=f'Reparación autorizada 1286, estado anterior: {antes}',
        )
        extras, creada = obtener_o_crear_borrador_extras(
            user=actor,
            empresa_id=1,
            transporte_id=flete.SN_NID_id,
            tipo='RECEPCION',
            inicio=flete.PRO_FPERIODO_INICIO,
            fin=flete.PRO_FPERIODO_FIN,
            comentario='Separación autorizada desde Proforma Flete #1286',
        )
        snapshot.PRO_NID = extras
        snapshot.save(update_fields=['PRO_NID'])
        recalcular_totales(flete)
        recalcular_totales(extras)
        flete.refresh_from_db(); extras.refresh_from_db(); snapshot.refresh_from_db()
        despues = {
            'flete': flete.pk,
            'subtotal_flete': str(flete.PRO_NSUBTOTAL),
            'iva_flete': str(flete.PRO_NIVA),
            'total_flete': str(flete.PRO_NTOTAL),
            'extras': extras.pk,
            'extras_creada': creada,
            'subtotal_extras': str(extras.PRO_NSUBTOTAL),
            'iva_extras': str(extras.PRO_NIVA),
            'total_extras': str(extras.PRO_NTOTAL),
            'epr': snapshot.pk,
            'cie': snapshot.CIE_NID_id,
            'snapshots_movidos': [item.pk for item in snapshots_mover],
        }
        esperados = (
            Decimal('426119'), Decimal('80962.61'), Decimal('507081.61'),
            Decimal('250000'), Decimal('47500'), Decimal('297500'),
        )
        actuales = (
            flete.PRO_NSUBTOTAL, flete.PRO_NIVA, flete.PRO_NTOTAL,
            extras.PRO_NSUBTOTAL, extras.PRO_NIVA, extras.PRO_NTOTAL,
        )
        if actuales != esperados:
            raise CommandError(f'Los totales posteriores no coinciden: {actuales}.')
        SYSLOGGER.objects.create(
            US_NID=actor, EP_NID_id=1, LOG_FFECHAREGISTRO=timezone.now(),
            LOG_CMODULO='PROFORMA', LOG_COPERACION='REP_1286_DESPUES',
            LOG_CADD1='Proforma: 1286', LOG_CADD2=f'Extras: {extras.pk}',
            LOG_CDESCRIPCION=f'Reparación autorizada 1286 completada: {despues}',
        )
        self.stdout.write(self.style.SUCCESS(f'REPARACIÓN APLICADA: {despues}'))