import requests


class SAPServiceLayer:
    def __init__(self, base_url, company_db, username, password):
        self.base_url = base_url.rstrip("/")
        self.company_db = company_db
        self.username = username
        self.password = password
        self.session = requests.Session()

    def login(self):
        url = f"{self.base_url}/b1s/v1/Login"

        payload = {
            "CompanyDB": self.company_db,
            "UserName": self.username,
            "Password": self.password
        }

        response = self.session.post(url, json=payload, verify=False)
        response.raise_for_status()

        return response.json()

    def get_business_partner(self, card_code):
        url = f"{self.base_url}/b1s/v1/BusinessPartners('{card_code}')"

        response = self.session.get(url, verify=False)
        response.raise_for_status()

        return response.json()