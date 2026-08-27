from types import SimpleNamespace
from unittest.mock import Mock, patch

from django.test import SimpleTestCase

from apps.home import views
from apps.home.sap_di_proforma import SapDiApiError


class CrearOcSapGuardTestCase(SimpleTestCase):
    def test_revalida_company_db_antes_de_get_business_object(self):
        proforma = SimpleNamespace(
            EP_NID_id=views.ID_TERRAMAR,
            PRO_BSOLOEXTRAS=True,
            PRO_DOC_ENTRY=None,
            PRO_DOC_NUM=None,
            PRO_CTIPO="RECEPCION",
        )
        company = Mock()

        with patch.object(views.PROFORMA.objects, "get", return_value=proforma), patch.object(
            views.CITACION_PROFORMA.objects, "filter", return_value=[]
        ), patch.object(
            views.LINEA_PROFORMA.objects, "filter", return_value=[]
        ), patch.object(
            views.EXTRA_PROFORMA.objects, "filter", return_value=[]
        ), patch.object(
            views, "es_proforma_mensual_terramar", return_value=False
        ), patch.object(
            views.EXTRA_PROFORMA.objects, "filter", return_value=[]
        ), patch.object(
            views, "es_proforma_mensual_terramar", return_value=False
        ), patch.object(
            views, "sapConnect", return_value=company
        ) as connect, patch.object(
            views, "get_sap_proforma_series", return_value=79
        ) as series, patch.object(
            views,
            "validate_sap_di_company",
            side_effect=SapDiApiError("CompanyDB conectada no coincide"),
        ) as validate, patch.object(
            views, "disconnect_sap_company"
        ) as disconnect:
            result, message = views.CREAR_OC(123)

        self.assertFalse(result)
        self.assertIn("no coincide", message)
        series.assert_called_once_with(views.ID_TERRAMAR)
        connect.assert_called_once_with(views.ID_TERRAMAR)
        validate.assert_called_once_with(company, views.ID_TERRAMAR)
        company.GetBusinessObject.assert_not_called()
        disconnect.assert_called_once_with(company)
