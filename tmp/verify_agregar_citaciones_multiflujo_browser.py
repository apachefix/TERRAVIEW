import mimetypes
import os
import pathlib
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import patch
from urllib.parse import urlsplit

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'core.settings')
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

import django
django.setup()

from django.db import connection, transaction
from django.test import RequestFactory
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

from apps.home import views
from apps.home.models import PLANIFICACION


pages = {}
with transaction.atomic():
    with connection.cursor() as cursor:
        cursor.execute('SET TRANSACTION READ ONLY')
    for pid, flujo in ((1300, 'INGRESO_MERCADERIA'), (1301, 'TRANSFERENCIA')):
        plan = PLANIFICACION.objects.get(pk=pid)
        request = RequestFactory().get(
            f'/pla_listone/{pid}',
            {'_empresa_id': '2', 'tipo': 'RECEPCION', 'flujo': flujo},
        )
        request.user = plan.US_NID
        with patch.object(views, 'Verificar_empresa', return_value=2), \
             patch.object(views, 'usuario_es_planificador', return_value=True), \
             patch.object(views, 'obtener_clientes_aceite', return_value=[]):
            response = views.PLANIFICACION_LISTONE(request, pid)
        assert response.status_code == 200, (pid, response.status_code)
        pages[f'/pla_listone/{pid}'] = response.content

static_root = pathlib.Path('apps/static').resolve()


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_GET(self):
        path = urlsplit(self.path).path
        if path.startswith('/static/'):
            target = (static_root / path[len('/static/'):]).resolve()
            if not target.is_relative_to(static_root) or not target.is_file():
                self.send_error(404)
                return
            data = target.read_bytes()
            content_type = mimetypes.guess_type(str(target))[0] or 'application/octet-stream'
        elif path in pages:
            data = pages[path]
            content_type = 'text/html; charset=utf-8'
        elif path.startswith('/api/sap/'):
            data = b'{"ok": true, "productos": [], "clientes": [], "resultados": []}'
            content_type = 'application/json'
        elif path.startswith('/check_notifications/'):
            data = b'{"notificaciones": []}'
            content_type = 'application/json'
        else:
            self.send_error(404)
            return
        self.send_response(200)
        self.send_header('Content-Type', content_type)
        self.send_header('Content-Length', str(len(data)))
        self.end_headers()
        self.wfile.write(data)


server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
threading.Thread(target=server.serve_forever, daemon=True).start()
options = webdriver.ChromeOptions()
for arg in ('--headless=new', '--no-sandbox', '--disable-dev-shm-usage', '--disable-gpu', '--disable-extensions'):
    options.add_argument(arg)
options.page_load_strategy = 'eager'
options.set_capability('goog:loggingPrefs', {'browser': 'ALL'})
driver = webdriver.Chrome(options=options)
try:
    driver.set_window_size(1366, 768)
    for pid, expected in ((1300, 'ModalCrearCitacion'), (1301, 'ModalCrearRecepcionTransferencia')):
        driver.get(f'http://127.0.0.1:{server.server_port}/pla_listone/{pid}?_empresa_id=2')
        wait = WebDriverWait(driver, 30)
        button = wait.until(EC.element_to_be_clickable((By.XPATH, '//button[normalize-space()="Agregar citaciones"]')))
        if pid == 1300:
            wait.until(lambda d: d.execute_script(
                "return typeof $ !== 'undefined' && $.fn.DataTable.isDataTable('#basic-btn1')"
            ))
            exported = driver.execute_script("return $('#basic-btn1').DataTable().buttons.exportData()")
            assert exported['header'][1:4] == ['NUMERO CITACIÓN', 'PRODUCTO', 'FECHA CITACION'], exported['header'][:5]
            print('datatable_export_headers', exported['header'][:5])
        assert not driver.find_elements(By.TAG_NAME, 'iframe')
        button.click()
        modal = wait.until(EC.visibility_of_element_located((By.ID, expected)))
        body = modal.find_element(By.CSS_SELECTOR, '.modal-body')
        footer = modal.find_element(By.CSS_SELECTOR, '.modal-footer')
        geometry = driver.execute_script('''const m=arguments[0], b=arguments[1], f=arguments[2];
            return {bodyHeight:b.clientHeight, scrollHeight:b.scrollHeight,
              overflow:getComputedStyle(b).overflowY,
              footerBottom:f.getBoundingClientRect().bottom, viewport:innerHeight,
              count:document.querySelectorAll('#'+m.id).length};''', modal, body, footer)
        assert geometry['count'] == 1, geometry
        assert geometry['footerBottom'] <= geometry['viewport'], geometry
        assert geometry['overflow'] == 'auto', geometry
        assert driver.find_element(By.ID, 'ModalResumenCitacionesEtapa0')
        if pid == 1301:
            for field in ('transferencia_fecha', 'transferencia_estanque_origen',
                          'transferencia_insumo', 'transferencia_cantidad_camion',
                          'transferencia_almacen_destino', 'transferencia_estanque_destino'):
                assert modal.find_element(By.ID, field)
            assert not driver.find_elements(By.ID, 'ModalCrearCitacion')
            assert modal.find_element(By.ID, 'transferencia_fecha').get_attribute('value') == '2026-10-05'
        driver.save_screenshot(f'tmp/agregar_citaciones_{pid}_multiflujo.png')
        print(pid, expected, geometry)
        driver.execute_script('arguments[0].scrollTop=arguments[0].scrollHeight', body)
        assert driver.execute_script('return arguments[0].scrollTop', body) > 0
        driver.execute_script('arguments[0].scrollTop=0', body)
        watched = ('recepcion_sbh_almacen_destino' if pid == 1300
                   else 'transferencia_almacen_destino')
        handlers_before = driver.execute_script('''const e=document.getElementById(arguments[0]);
            return (($._data(e, 'events') || {}).change || []).length;''', watched)
        driver.execute_script('$(arguments[0]).modal("hide")', modal)
        wait.until(EC.invisibility_of_element(modal))
        button.click()
        wait.until(EC.visibility_of_element_located((By.ID, expected)))
        handlers_after = driver.execute_script('''const e=document.getElementById(arguments[0]);
            return (($._data(e, 'events') || {}).change || []).length;''', watched)
        assert handlers_before == handlers_after, (handlers_before, handlers_after)
        severe = [item['message'] for item in driver.get_log('browser') if item['level'] == 'SEVERE']
        assert not severe, severe
        print(pid, 'reopened=True', 'handlers', handlers_before, handlers_after,
              'severe_errors=0')
finally:
    driver.quit()
    server.shutdown()
