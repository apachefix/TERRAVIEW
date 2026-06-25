import requests

from apps.integrations.sap_b1.service_layer_probe import load_config


class SAPServiceLayer:
    def __init__(self, base_url=None, company_db=None, username=None, password=None):
        config = load_config()
        self.base_url = (base_url or config.base_url).rstrip("/")
        self.company_db = company_db or config.company_db
        self.username = username or config.username
        self.password = password or config.password
        self.verify_ssl = config.verify_ssl
        self.timeout = config.timeout
        self.session = requests.Session()

    def login(self):
        url = f"{self.base_url}/Login"

        payload = {
            "CompanyDB": self.company_db,
            "UserName": self.username,
            "Password": self.password
        }

        response = self.session.post(
            url,
            json=payload,
            verify=self.verify_ssl,
            timeout=self.timeout,
        )
        response.raise_for_status()

        return response.json()

    def get_business_partner(self, card_code):
        url = f"{self.base_url}/BusinessPartners('{card_code}')"

        response = self.session.get(
            url,
            verify=self.verify_ssl,
            timeout=self.timeout,
        )
        response.raise_for_status()

        return response.json()
