import requests

from apps.integrations.sap_b1.service_layer_probe import load_config


class SAPServiceLayer:
    def __init__(self, ruta_credenciales=None):
        service_layer_config = load_config()
        self.base_url = service_layer_config.base_url.rstrip("/")
        self.company_db = service_layer_config.company_db
        self.username = service_layer_config.username
        self.password = service_layer_config.password
        self.verify_ssl = service_layer_config.verify_ssl
        self.timeout = service_layer_config.timeout

        self.session = requests.Session()
        self.login_response = None

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
            timeout=self.timeout
        )

        response.raise_for_status()
        self.login_response = response.json()

        print("Conectado a SAP Service Layer:", self.company_db)
        return self.login_response

    def logout(self):
        try:
            url = f"{self.base_url}/Logout"
            response = self.session.post(url, verify=self.verify_ssl, timeout=self.timeout)
            return response.status_code in [200, 204]
        except Exception as e:
            print("Error al cerrar sesión Service Layer:", e)
            return False

    def get(self, endpoint):
        url = f"{self.base_url}/{endpoint.lstrip('/')}"
        response = self.session.get(url, verify=self.verify_ssl, timeout=self.timeout)
        response.raise_for_status()
        return response.json()

    def post(self, endpoint, payload):
        url = f"{self.base_url}/{endpoint.lstrip('/')}"
        response = self.session.post(
            url,
            json=payload,
            verify=self.verify_ssl,
            timeout=self.timeout,
        )
        response.raise_for_status()
        return response.json()

    def validar_socio_negocio(self, card_code):
        try:
            return self.get(f"BusinessPartners('{card_code}')")
        except Exception as e:
            print("Socio de negocio no encontrado:", e)
            return None

    def validar_item(self, item_code):
        try:
            return self.get(f"Items('{item_code}')")
        except Exception as e:
            print("Item no encontrado:", e)
            return None

    def validar_campo_terramar(self, endpoint, campo, valor):
        try:
            filtro = f"{endpoint}?$filter={campo} eq '{valor}'"
            data = self.get(filtro)
            return len(data.get("value", [])) > 0
        except Exception as e:
            print("Error validando campo en Service Layer:", e)
            return False
