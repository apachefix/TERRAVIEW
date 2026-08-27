from types import SimpleNamespace
from unittest.mock import patch

from django.test import SimpleTestCase

from apps.home import views
from apps.home.services.proforma_terramar import estado_permite_autorizar_sap


class SapProformaOcIdempotencyTestCase(SimpleTestCase):
    def test_crear_oc_no_reenvia_si_existe_doc_entry(self):
        proforma = SimpleNamespace(PRO_DOC_ENTRY=321, PRO_DOC_NUM=None)
        with patch.object(views.PROFORMA.objects, "get", return_value=proforma), patch.object(
            views, "sapConnect"
        ) as connect:
            success, message = views.CREAR_OC(1288)

        self.assertFalse(success)
        self.assertIn("ya tiene una OC SAP", message)
        connect.assert_not_called()

    def test_doc_num_existente_bloquea_autorizacion_aun_sin_doc_entry(self):
        proforma = SimpleNamespace(
            EP_NID_id=1,
            PRO_CESTADO="APROBADO",
            PRO_BBORRADOR=True,
            PRO_DOC_ENTRY=None,
            PRO_DOC_NUM="123456",
            PRO_FPERIODO_INICIO=object(),
            PRO_FPERIODO_FIN=object(),
        )
        self.assertFalse(estado_permite_autorizar_sap(proforma))

    def test_detalle_y_pdf_exponen_doc_num_como_referencia_principal(self):
        detail = open(
            "apps/templates/home/PROFORMA/proforma_terramar_detalle.html",
            encoding="utf-8",
        ).read()
        pdf = open(
            "apps/templates/home/PROFORMA/proforma_terramar_borrador_pdf.html",
            encoding="utf-8",
        ).read()

        self.assertIn("OC SAP N° {{ proforma.PRO_DOC_NUM }}", detail)
        self.assertIn("OC SAP N° {{ proforma.PRO_DOC_NUM }}", pdf)

