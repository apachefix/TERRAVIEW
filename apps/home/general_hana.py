import json
import requests
from pathlib import Path
from django.conf import settings


class SAPServiceLayer:
    def __init__(self, ruta_credenciales=None):
        if ruta_credenciales is None:
            ruta_credenciales = Path(settings.BASE_DIR) / "loginSL.json"

        self.ruta_credenciales = ruta_credenciales
        self.login_info = self._cargar_credenciales()

        self.base_url = self.login_info["ServiceLayerURL"].rstrip("/")
        self.company_db = self.login_info["CompanyDB"]
        self.username = self.login_info["UserName"]
        self.password = self.login_info["Password"]

        self.session = requests.Session()
        self.login_response = None

    def _cargar_credenciales(self):
        with open(self.ruta_credenciales, "r", encoding="utf-8") as archivo:
            return json.load(archivo)

    def login(self):
        url = f"{self.base_url}/b1s/v1/Login"

        payload = {
            "CompanyDB": self.company_db,
            "UserName": self.username,
            "Password": self.password
        }

        response = self.session.post(
            url,
            json=payload,
            verify=False,
            timeout=30
        )

        response.raise_for_status()
        self.login_response = response.json()

        print("Conectado a SAP Service Layer:", self.company_db)
        return self.login_response

    def logout(self):
        try:
            url = f"{self.base_url}/b1s/v1/Logout"
            response = self.session.post(url, verify=False, timeout=30)
            return response.status_code in [200, 204]
        except Exception as e:
            print("Error al cerrar sesión Service Layer:", e)
            return False

    def get(self, endpoint):
        url = f"{self.base_url}/b1s/v1/{endpoint.lstrip('/')}"
        response = self.session.get(url, verify=False, timeout=30)
        response.raise_for_status()
        return response.json()

    def post(self, endpoint, payload):
        url = f"{self.base_url}/b1s/v1/{endpoint.lstrip('/')}"
        response = self.session.post(url, json=payload, verify=False, timeout=30)
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