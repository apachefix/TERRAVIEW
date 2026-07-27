from django.http import QueryDict
from django.test import SimpleTestCase

from apps.home.phone_utils import normalize_international_phone, split_legacy_phone


class InternationalPhoneTests(SimpleTestCase):
    def test_chile_local_and_pasted_prefix(self):
        self.assertEqual(normalize_international_phone("+56", "9 2398-9118")["full_number"], "+56923989118")
        value = normalize_international_phone("+56", "+56 9 2398 9118")
        self.assertEqual(value["local_number"], "923989118")
        self.assertEqual(value["full_number"], "+56923989118")

    def test_argentina_brazil_and_landline(self):
        self.assertEqual(normalize_international_phone("+54", "91123456789")["full_number"], "+5491123456789")
        self.assertEqual(normalize_international_phone("+55", "(11) 99999-9999")["full_number"], "+5511999999999")
        self.assertEqual(normalize_international_phone("+56", "2 2345 6789")["local_number"], "223456789")

    def test_invalid_phone_and_e164_limit(self):
        with self.assertRaises(ValueError):
            normalize_international_phone("+56", "abc")
        with self.assertRaises(ValueError):
            normalize_international_phone("+999", "1234567")
        with self.assertRaises(ValueError):
            normalize_international_phone("+56", "123456789012345")

    def test_urlencoded_country_code_keeps_plus(self):
        post = QueryDict('telefono_codigo_pais=%2B56&telefono_conductor=923989118')
        value = normalize_international_phone(post['telefono_codigo_pais'], post['telefono_conductor'])
        self.assertEqual(value['country_code'], '+56')
        self.assertEqual(value['local_number'], '923989118')

    def test_legacy_values_are_presentation_only(self):
        self.assertEqual(split_legacy_phone(None, "+5491123456789")["country_code"], "+54")
        self.assertEqual(split_legacy_phone(None, "+56923989118")["local_number"], "923989118")
        self.assertEqual(split_legacy_phone(None, "923989118")["country_code"], "+56")
