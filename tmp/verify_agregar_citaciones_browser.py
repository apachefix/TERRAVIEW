import mimetypes
import json
import os
import pathlib
import sys
import threading
import time
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
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.common.by import By
from selenium.webdriver.common.actions.wheel_input import ScrollOrigin
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

from apps.home import views
from apps.home.models import PLANIFICACION


pages = {}
with transaction.atomic():
    with connection.cursor() as cursor:
        cursor.execute('SET TRANSACTION READ ONLY')
    user = PLANIFICACION.objects.get(pk=1300).US_NID
    for key, path in [('detail', '/pla_listone/1300'), ('form', '/pla_addone/')]:
        request = RequestFactory().get(path, {
            '_empresa_id': '2', 'tipo': 'RECEPCION', 'flujo': 'INGRESO_MERCADERIA',
            'planificacion_existente_id': '1300', 'modal': 'recepcion',
        })
        request.user = user
        with patch.object(views, 'Verificar_empresa', return_value=2), \
             patch.object(views, 'usuario_es_planificador', return_value=True), \
             patch.object(views, 'obtener_clientes_aceite', return_value=[]), \
             patch.object(views, 'asegurar_flujos_recepcion_etapa_0', return_value=[]), \
             patch.object(views, 'asegurar_flujos_despacho_etapa_0'):
            response = (views.PLANIFICACION_LISTONE(request, 1300)
                        if key == 'detail' else views.PLANIFICACION_ADDONE(request))
        if response.status_code != 200:
            raise RuntimeError((key, response.status_code))
        pages[key] = response.content

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
        elif path.startswith('/pla_addone/'):
            data, content_type = pages['form'], 'text/html; charset=utf-8'
        elif path.startswith('/pla_listone/1300'):
            data, content_type = pages['detail'], 'text/html; charset=utf-8'
        elif path.startswith('/api/sap/productos/'):
            data, content_type = json.dumps({'ok': True, 'productos': []}).encode(), 'application/json'
        elif path.startswith('/api/sap/clientes/'):
            data, content_type = json.dumps({'ok': True, 'clientes': []}).encode(), 'application/json'
        elif path.startswith('/api/sap/pedidos-por-producto/'):
            data, content_type = json.dumps({'ok': True, 'pedidos': []}).encode(), 'application/json'
        elif path.startswith('/check_notifications/'):
            data, content_type = json.dumps({'notificaciones': []}).encode(), 'application/json'
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
driver = webdriver.Chrome(
    service=Service(r'C:\Users\external01\.cache\selenium\chromedriver\win64\154.0.8037.92\chromedriver.exe'),
    options=options,
)
try:
    driver.set_window_size(1440, 900)
    driver.get(f'http://127.0.0.1:{server.server_port}/pla_listone/1300?_empresa_id=2')
    wait = WebDriverWait(driver, 30)
    button = wait.until(EC.element_to_be_clickable((By.XPATH, '//button[normalize-space()="Agregar citaciones"]')))
    headers = driver.execute_script("return Array.from(document.querySelectorAll('#basic-btn1 thead th'), x => x.textContent.trim())")
    options_visible = driver.execute_script("return Array.from(document.querySelectorAll('button'), x => x.textContent.trim()).includes('Opciones')")
    print('button_visible', button.is_displayed(), 'options_visible', options_visible, 'first_headers', headers[:5])
    wait.until(lambda d: d.execute_script("return typeof $ !== 'undefined' && $.fn.DataTable.isDataTable('#basic-btn1')"))
    export = driver.execute_script("return $('#basic-btn1').DataTable().buttons.exportData()")
    print('export_headers', export['header'][:5], 'export_first_row', export['body'][0][:5])
    assert not driver.find_elements(By.TAG_NAME, 'iframe')
    button.click()
    modal = wait.until(EC.visibility_of_element_located((By.ID, 'ModalCrearCitacion')))
    fields = ['tipo', 'secuencia_id', 'pedido', 'proveedor', 'tipo_origen_recepcion',
              'recepcion_sbh_almacen_destino', 'recepcion_sbh_estanque_destino',
              'observacion', 'cantidad_repetir']
    assert all(modal.find_element(By.ID, field) for field in fields)
    assert all(driver.execute_script("return !!$('#' + arguments[0]).data('select2')", field)
               for field in ['cliente', 'insumo', 'pedido', 'proveedor', 'secuencia_id'])
    options_tanks = driver.execute_script("$('#recepcion_sbh_almacen_destino').val('SBH').trigger('change'); return $('#recepcion_sbh_estanque_destino option').map((_,x) => x.value).get()")
    print('etapa0_modal_visible', modal.is_displayed(),
          'title', driver.find_element(By.ID, 'ModalCrearCitacionLabel').text,
          'date', driver.find_element(By.ID, 'fecha_llegada').get_attribute('value'),
          'tank_options', options_tanks,
          'quantity', driver.find_element(By.ID, 'cantidad_repetir').get_attribute('value'))
    assert len(options_tanks) > 1
    handlers_before = driver.execute_script("return ($._data($('#recepcion_sbh_almacen_destino')[0], 'events').change || []).length")
    driver.execute_script("$('#ModalCrearCitacion').modal('hide')")
    wait.until(EC.invisibility_of_element(modal))
    button.click()
    wait.until(EC.visibility_of_element_located((By.ID, 'ModalCrearCitacion')))
    handlers_after = driver.execute_script("return ($._data($('#recepcion_sbh_almacen_destino')[0], 'events').change || []).length")
    assert handlers_before == handlers_after, (handlers_before, handlers_after)
    severe_logs = [item['message'] for item in driver.get_log('browser') if item['level'] == 'SEVERE']
    print('handlers_before_after', handlers_before, handlers_after,
          'browser_severe_logs', severe_logs)
    assert not severe_logs, severe_logs
    for width, height in [(1920, 1080), (1366, 768)]:
        driver.set_window_size(width, height)
        chrome_height = driver.execute_script('return outerHeight - innerHeight')
        driver.set_window_size(width, height + chrome_height)
        time.sleep(.4)
        body = driver.find_element(By.CSS_SELECTOR, '#ModalCrearCitacion .modal-body')
        driver.execute_script('arguments[0].scrollTop = 0', body)
        before = driver.execute_script("""const m = document.getElementById('ModalCrearCitacion');
          const b = m.querySelector('.modal-body'); const f = m.querySelector('.modal-footer');
          const h = m.querySelector('.modal-header'); const c = m.querySelector('.modal-content');
          return {bodyClient:b.clientHeight, bodyScroll:b.scrollHeight, bodyTop:b.scrollTop,
            bodyOverflow:getComputedStyle(b).overflowY, contentHeight:c.getBoundingClientRect().height,
            headerTop:h.getBoundingClientRect().top, footerBottom:f.getBoundingClientRect().bottom,
            viewport:innerHeight, backdropOverflow:getComputedStyle(document.body).overflowY};""")
        ActionChains(driver).scroll_from_origin(ScrollOrigin.from_element(body), 0, 480).perform()
        time.sleep(.4)
        after = driver.execute_script("return document.querySelector('#ModalCrearCitacion .modal-body').scrollTop")
        print('scroll_probe', width, height, before, 'wheel_after', after)
        assert before['bodyScroll'] > before['bodyClient'] and after > 0
        assert before['footerBottom'] <= before['viewport'] and before['headerTop'] >= 0
        driver.execute_script('arguments[0].scrollTop = 0', body)
        driver.execute_script("const b=document.querySelector('#ModalCrearCitacion .modal-body'); b.setAttribute('tabindex','0'); b.focus();")
        body.send_keys('\ue00f')
        time.sleep(.2)
        keyboard_after = driver.execute_script("return document.querySelector('#ModalCrearCitacion .modal-body').scrollTop")
        assert keyboard_after > 0, keyboard_after
        print('page_down_after', keyboard_after)
        body.send_keys('\ue00e')
        time.sleep(.2)
        assert driver.execute_script('return arguments[0].scrollTop', body) < keyboard_after
        driver.execute_script('arguments[0].scrollTop = 0', body)
        driver.execute_script("$('#cliente').select2('open')")
        select2_before = driver.execute_script("return {selection: document.querySelector('#cliente + .select2').getBoundingClientRect().bottom, dropdown: document.querySelector('.select2-dropdown').getBoundingClientRect().top}")
        ActionChains(driver).scroll_from_origin(ScrollOrigin.from_element(body), 0, 240).perform()
        time.sleep(.3)
        select2_after = driver.execute_script("return {selection: document.querySelector('#cliente + .select2').getBoundingClientRect().bottom, dropdown: document.querySelector('.select2-dropdown')?.getBoundingClientRect().top, open: $('#cliente').data('select2').isOpen(), scroll: document.querySelector('#ModalCrearCitacion .modal-body').scrollTop}")
        print('select2_scroll_probe', select2_before, select2_after)
        assert not select2_after['open'] and select2_after['scroll'] > 0
        driver.execute_script("$('#cliente').select2('close')")
        if width == 1366:
            driver.execute_script('arguments[0].scrollTop = 350', body)
            driver.execute_script("$('#proveedor').select2('open')")
            supplier_dropdown = driver.execute_script("""const m=document.querySelector('#ModalCrearCitacion');
              const s=document.querySelector('#proveedor + .select2').getBoundingClientRect();
              const d=document.querySelector('.select2-dropdown').getBoundingClientRect();
              return {selectionTop:s.top,selectionBottom:s.bottom,dropdownTop:d.top,dropdownBottom:d.bottom,
                headerBottom:m.querySelector('.modal-header').getBoundingClientRect().bottom,
                footerTop:m.querySelector('.modal-footer').getBoundingClientRect().top};""")
            print('supplier_dropdown', supplier_dropdown)
            assert supplier_dropdown['selectionTop'] < supplier_dropdown['footerTop']
            driver.save_screenshot('tmp/agregar_citaciones_select2_1366.png')
            driver.execute_script("$('#proveedor').select2('close')")
        driver.execute_script('arguments[0].scrollTop = arguments[0].scrollHeight', body)
        lower_fields = driver.execute_script("""const ids=['tipo_origen_recepcion','recepcion_sbh_almacen_destino','recepcion_sbh_estanque_destino','observacion','cantidad_repetir'];
          return Object.fromEntries(ids.map(id => {const r=document.querySelector('#ModalCrearCitacion #'+id).getBoundingClientRect(); return [id,{top:r.top,bottom:r.bottom}]}));""")
        print('lower_fields', width, lower_fields)
        assert all(v['bottom'] <= before['viewport'] and v['top'] >= 0 for v in lower_fields.values())
        driver.save_screenshot(f'tmp/agregar_citaciones_scroll_{width}.png')
        max_scroll = driver.execute_script('return arguments[0].scrollTop', body)
        ActionChains(driver).scroll_from_origin(ScrollOrigin.from_element(body), 0, -450).perform()
        time.sleep(.3)
        assert driver.execute_script('return arguments[0].scrollTop', body) < max_scroll
        if width == 1366:
            driver.execute_script('arguments[0].scrollTop = 0', body)
            scrollbar = driver.execute_script("const b=document.querySelector('#ModalCrearCitacion .modal-body'); const r=b.getBoundingClientRect();return {x:r.right-6,y:r.top+35,width:b.offsetWidth-b.clientWidth}")
            assert scrollbar['width'] > 0, scrollbar
            driver.execute_cdp_cmd('Input.dispatchMouseEvent', {
                'type': 'mousePressed', 'x': scrollbar['x'], 'y': scrollbar['y'],
                'button': 'left', 'buttons': 1, 'clickCount': 1,
            })
            driver.execute_cdp_cmd('Input.dispatchMouseEvent', {
                'type': 'mouseMoved', 'x': scrollbar['x'], 'y': scrollbar['y'] + 160,
                'button': 'left', 'buttons': 1,
            })
            driver.execute_cdp_cmd('Input.dispatchMouseEvent', {
                'type': 'mouseReleased', 'x': scrollbar['x'], 'y': scrollbar['y'] + 160,
                'button': 'left', 'buttons': 0, 'clickCount': 1,
            })
            scrollbar_after = driver.execute_script('return arguments[0].scrollTop', body)
            print('scrollbar_drag', scrollbar, scrollbar_after)
            assert scrollbar_after > 0
    driver.execute_cdp_cmd('Emulation.setDeviceMetricsOverride', {
        'width': 390, 'height': 844, 'deviceScaleFactor': 1, 'mobile': True,
    })
    driver.execute_cdp_cmd('Emulation.setTouchEmulationEnabled', {'enabled': True, 'maxTouchPoints': 1})
    time.sleep(.3)
    driver.execute_script("document.querySelector('#ModalCrearCitacion .modal-body').scrollTop=0")
    touch_rect = driver.execute_script("const r=document.querySelector('#ModalCrearCitacion .modal-body').getBoundingClientRect(); return {x:r.left+r.width/2,y:r.top+r.height/2}")
    print('touch_origin', touch_rect, driver.execute_script("return {target:document.elementFromPoint(arguments[0],arguments[1])?.outerHTML.slice(0,180),width:innerWidth,height:innerHeight}", touch_rect['x'], touch_rect['y']))
    driver.save_screenshot('tmp/agregar_citaciones_scroll_mobile_before.png')
    touch_x = touch_rect['x']
    driver.execute_cdp_cmd('Input.dispatchTouchEvent', {
        'type': 'touchStart', 'touchPoints': [{'x': touch_x, 'y': 650, 'id': 1}],
    })
    for touch_y in range(625, 225, -25):
        driver.execute_cdp_cmd('Input.dispatchTouchEvent', {
            'type': 'touchMove', 'touchPoints': [{'x': touch_x, 'y': touch_y, 'id': 1}],
        })
    driver.execute_cdp_cmd('Input.dispatchTouchEvent', {'type': 'touchEnd', 'touchPoints': []})
    time.sleep(.5)
    touch_scroll = driver.execute_script("const m=document.querySelector('#ModalCrearCitacion'); const b=m.querySelector('.modal-body'); return {scroll:b.scrollTop,bodyClient:b.clientHeight,bodyScroll:b.scrollHeight,footerBottom:m.querySelector('.modal-footer').getBoundingClientRect().bottom,viewport:innerHeight}")
    print('touch_probe', touch_scroll)
    assert touch_scroll['scroll'] > 0 and touch_scroll['footerBottom'] <= touch_scroll['viewport']
    driver.save_screenshot('tmp/agregar_citaciones_scroll_mobile.png')
    driver.execute_cdp_cmd('Emulation.setTouchEmulationEnabled', {'enabled': False})
    driver.execute_cdp_cmd('Emulation.clearDeviceMetricsOverride', {})
    form_probe = driver.execute_script("""
      const put = (id, value) => { document.getElementById(id).value = value; };
      const option = (id, value, title) => { const el = document.getElementById(id); el.add(new Option(title, value)); put(id, value); };
      option('cliente', 'C001', 'Cliente de prueba');
      put('inf_24hrs', 'Si');
      put('tipo_carga', document.querySelector('#tipo_carga option:not([value=""])').value);
      if (!document.querySelector('#secuencia_id option:not([value=""])')) option('secuencia_id', '1', 'Secuencia de prueba');
      put('secuencia_id', document.querySelector('#secuencia_id option:not([value=""])').value);
      option('insumo', 'P001', 'Producto de prueba');
      option('pedido', '98765', 'Pedido de prueba');
      option('proveedor', 'manual:Proveedor de prueba', 'Proveedor de prueba');
      put('codigo', 'P001');
      put('sap_opor_id', '12345');
      put('cantidad_disponible', '100');
      put('tipo_origen_recepcion', 'NACIONAL');
      put('recepcion_sbh_estanque_destino', 'TK01');
      put('cantidad_repetir', '2');
      return {valid: document.getElementById('form_crear_citacion').checkValidity(),
              invalid: Array.from(document.querySelectorAll('#form_crear_citacion :invalid'), x => x.id),
              secuencias: document.querySelectorAll('#secuencia_id option').length};
    """)
    print('form_probe', form_probe)
    assert form_probe['valid'], form_probe
    print('validation_probe', driver.execute_script("return {valid: validarFormularioCitacion(), blocked: TIPO_PLANIFICACION_BLOQUEADO, plan: PLANIFICACION_EXISTENTE_ID, summary: $('#ModalResumenCitacionesEtapa0').length}"))
    driver.execute_script('agregarCitacionTemporal()')
    print('after_add', driver.execute_script("return {draft: citacionesTemporales.length, formVisible: $('#ModalCrearCitacion').hasClass('show'), summaryVisible: $('#ModalResumenCitacionesEtapa0').hasClass('show'), alert: document.querySelector('.swal2-container')?.innerText}"))
    wait.until(EC.visibility_of_element_located((By.ID, 'ModalResumenCitacionesEtapa0')))
    draft_count = driver.execute_script('return citacionesTemporales.length')
    assert draft_count == 2, draft_count
    print('draft_count', draft_count, 'existing_plan', driver.execute_script('return PLANIFICACION_EXISTENTE_ID'))
    driver.save_screenshot('tmp/agregar_citaciones_browser.png')
    driver.set_window_size(1366, 920)
    driver.get(f'http://127.0.0.1:{server.server_port}/pla_addone/?_empresa_id=2&tipo=RECEPCION&flujo=INGRESO_MERCADERIA&planificacion_existente_id=1300')
    wait.until(lambda d: d.execute_script("return typeof abrirModalRecepcion === 'function'"))
    driver.execute_script('abrirModalRecepcion()')
    wait.until(EC.visibility_of_element_located((By.ID, 'ModalCrearCitacion')))
    original_scroll = driver.execute_script("const b=document.querySelector('#ModalCrearCitacion .modal-body');return {client:b.clientHeight,scroll:b.scrollHeight,footer:document.querySelector('#ModalCrearCitacion .modal-footer').getBoundingClientRect().bottom,viewport:innerHeight}")
    print('shared_form_scroll', original_scroll)
    assert original_scroll['scroll'] > original_scroll['client'] and original_scroll['footer'] <= original_scroll['viewport']
finally:
    driver.quit()
    server.shutdown()
    server.server_close()
