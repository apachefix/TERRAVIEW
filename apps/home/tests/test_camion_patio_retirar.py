from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from django.test import RequestFactory, TestCase

from apps.home import views


class CamionPatioRetirarViewTests(TestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.url = '/camiones-patio/17/retirar/'
        self.admin = SimpleNamespace(is_superuser=True, has_perm=lambda perm: False)
        self.normal = SimpleNamespace(is_superuser=False, has_perm=lambda perm: False)

    def test_get_no_elimina(self):
        request = self.factory.get(self.url)
        request.user = self.admin
        with patch.object(views, 'Verificar_empresa') as empresa, patch.object(
            views.CAMION_PATIO.objects, 'select_for_update'
        ) as manager:
            response = views.CAMION_PATIO_RETIRAR(request, 17)
        self.assertEqual(response.status_code, 405)
        empresa.assert_not_called()
        manager.assert_not_called()

    def test_usuario_normal_no_puede_retirar(self):
        request = self.factory.post(self.url)
        request.user = self.normal
        with patch.object(views, 'Verificar_empresa') as empresa:
            response = views.CAMION_PATIO_RETIRAR(request, 17)
        self.assertEqual(response.status_code, 403)
        empresa.assert_not_called()

    def test_admin_retiro_conserva_camion_maestro_y_audita(self):
        request = self.factory.post(self.url)
        request.user = self.admin
        empresa = MagicMock(id=1)
        camion = MagicMock(
            id=17,
            EP_NID_id=1,
            EP_NID=empresa,
            CI_NID_id=38629,
            CPA_CPATENTE='JWRS50',
            CPA_FFECHALLEGADA='2026-08-04 10:00',
        )
        manager = MagicMock()
        manager.select_related.return_value.select_for_update.return_value.get.return_value = camion
        with patch.object(views, 'Verificar_empresa', return_value=1), patch.object(
            views.CAMION_PATIO, 'objects', manager
        ), patch.object(views, 'registrar_log_camion_no_planificado') as audit:
            response = views.CAMION_PATIO_RETIRAR(request, 17)

        self.assertEqual(response.status_code, 200)
        self.assertTrue(__import__('json').loads(response.content)['success'])
        camion.delete.assert_called_once_with()
        audit.assert_called_once()
        self.assertIn('CAMION_PATIO #17', audit.call_args.args[3])
        self.assertEqual(audit.call_args.args[4], 38629)
        self.assertEqual(audit.call_args.args[5], 17)

    def test_citacion_nullable_bloquea_solo_camion_patio(self):
        request = self.factory.post(self.url)
        request.user = self.admin
        empresa = MagicMock(id=1)
        camion = MagicMock(
            id=17,
            EP_NID_id=1,
            EP_NID=empresa,
            CI_NID_id=None,
            CPA_CPATENTE='JWRS50',
            CPA_FFECHALLEGADA='2026-08-04 10:00',
        )
        manager = MagicMock()
        manager.select_related.return_value.select_for_update.return_value.get.return_value = camion
        with patch.object(views, 'Verificar_empresa', return_value=1), patch.object(
            views.CAMION_PATIO, 'objects', manager
        ), patch.object(views, 'registrar_log_camion_no_planificado'):
            response = views.CAMION_PATIO_RETIRAR(request, 17)

        self.assertEqual(response.status_code, 200)
        manager.select_related.assert_called_once_with('EP_NID', 'CI_NID')
        manager.select_related.return_value.select_for_update.assert_called_once_with(of=('self',))
        camion.delete.assert_called_once_with()
    def test_empresa_distinta_no_se_elimina(self):
        request = self.factory.post(self.url)
        request.user = self.admin
        manager = MagicMock()
        manager.select_related.return_value.select_for_update.return_value.get.side_effect = views.CAMION_PATIO.DoesNotExist
        with patch.object(views, 'Verificar_empresa', return_value=1), patch.object(
            views.CAMION_PATIO, 'objects', manager
        ):
            response = views.CAMION_PATIO_RETIRAR(request, 17)
        self.assertEqual(response.status_code, 404)