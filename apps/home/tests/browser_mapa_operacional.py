"""Chrome checks of the actual map assets/template with synthetic data, no DB.

Run: venv/Scripts/python.exe -m apps.home.tests.browser_mapa_operacional
Serves both dashboard URLs on loopback only. Selenium is a local test tool,
not a runtime dependency. Screenshots go to tmp/mapa_zonas_*.png.
"""
import json
import os
import threading
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.support.ui import WebDriverWait

from apps.home.services.mapa_operacional_config import zonas_configuradas

ROOT = Path(__file__).resolve().parents[3]


def html(empresa, empty=False, static_origin=None):
    template = (ROOT / 'apps/templates/home/HOME/monitor.html').read_text(encoding='utf-8')
    body = template.split('{% block content %}')[1].split('{% endblock %}')[0]
    body = body.replace('{{ mapa_empresa_id }}', str(empresa)).replace("{% url 'dashboard_grafico_estado' %}", '/dashboard_grafico/estado/')
    body = body.replace("{% static 'assets/plano/plantilla_planta.png' %}", '/apps/static/assets/plano/plantilla_planta.png')
    truck = {'empresa_id': empresa, 'empresa': 'TERRAMAR CHILE' if empresa == 1 else 'ACEITES SBH',
             'tipo': 'RECEPCION', 'etapa': 'Ciclo Descarga', 'estado': 'EN PROCESO',
             'secuencia': 'RECEPCION_TERRAMAR' if empresa == 1 else 'RECEPCION_ESTANQUE_SBH',
             'secuencia_nombre': 'Secuencia de prueba', 'segundos_etapa': 75,
             'inicio_etapa': '2026-10-04T10:00:00-03:00', 'timer_activo': True,
             'eventos': [], 'trazabilidad_url': '/trazabilidad/buscar/'}
    payload = {'empresa_id': empresa, 'empresa': truck['empresa'], 'generado_en': '2026-10-04T10:01:15-03:00',
               'camiones': [dict(truck, citacion_id=90001+i, patente=f'ABCD{i:02d}',
                                 tipo='DESPACHO' if i % 2 else 'RECEPCION',
                                 zona='ZONA_CARGA_DESCARGA' if i < 12 else 'ZONA_ESPERA' if i < 24 else 'ROMANA') for i in range(30)],
               'zonas': list(zonas_configuradas().values()),
               'kpis': dict(total=30, recepciones=15, despachos=15, romana=6, calidad=0, carga_descarga=12, salida=0),
               'cupos': [], 'sin_soporte': 0}
    if empty:
        payload['camiones'] = []
        payload['kpis'] = {key: 0 for key in payload['kpis']}
    markup = ('<!doctype html><html lang="es"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
            '<link rel="stylesheet" href="/apps/static/assets/css/style.css">'
            '<link rel="stylesheet" href="/apps/static/assets/css/mapa-operacional.css">'
            '<style>body{padding:20px}.pcoded-main-container{margin:0}.pcoded-content{padding:0}</style>' + body +
            '<script>window.payload=' + json.dumps(payload) + ';window.failure=false;window.fetch=async()=>{'
            'if(window.failure)throw new Error("Offline");return {ok:true,status:200,json:async()=>window.payload}}</script>'
            '<script src="/apps/static/assets/js/mapa-operacional.js"></script></html>')
    if static_origin:
        markup = markup.replace('/apps/static/', static_origin.rstrip('/') + '/static/')
    return markup.encode('utf-8')


class Handler(SimpleHTTPRequestHandler):
    def do_GET(self):
        url = urlparse(self.path)
        if url.path == '/dashboard_grafico/':
            content = html(int(parse_qs(url.query)['_empresa_id'][0]))
            self.send_response(200)
            self.send_header('Content-Type', 'text/html; charset=utf-8')
            self.end_headers()
            self.wfile.write(content)
        elif url.path == '/favicon.ico':
            self.send_response(204)
            self.end_headers()
        else:
            super().do_GET()

    def log_message(self, *args):
        pass


GEOMETRY = """
const image = document.getElementById('mapa-imagen').getBoundingClientRect();
const physical = [...document.querySelectorAll('#mapa-capa .mapa-zona')].filter(z => !z.hidden);
for (const z of physical) {
  const config = window.payload.zonas.find(c => c.codigo === z.dataset.zona), r = z.getBoundingClientRect();
  for (const [actual, expected] of [[r.x-image.x,image.width*config.x_pct/100],
       [r.y-image.y,image.height*config.y_pct/100], [r.width,image.width*config.width_pct/100],
       [r.height,image.height*config.height_pct/100]]) {
    if (Math.abs(actual-expected) > 1) return 'Misaligned: '+z.dataset.zona;
  }
  const markers = [...z.querySelectorAll('.mapa-camion')];
  for (let i=0; i<markers.length; i++) {
    const a=markers[i].getBoundingClientRect(), plate=markers[i].querySelector('strong');
    if (plate.scrollWidth > plate.clientWidth) return 'Clipped plate: '+plate.textContent;
    if (parseFloat(getComputedStyle(plate).fontSize) < 12) return 'Small plate';
    for (let j=i+1; j<markers.length; j++) {
      const b=markers[j].getBoundingClientRect();
      // Different scroll containers may clip offscreen content; compare within a lane/list.
      if (markers[i].closest('.mapa-slots, .mapa-espera') !== markers[j].closest('.mapa-slots, .mapa-espera')) continue;
      if (Math.min(a.right,b.right)-Math.max(a.left,b.left)>0.5 &&
          Math.min(a.bottom,b.bottom)-Math.max(a.top,b.top)>0.5) return 'Overlapping markers';
    }
  }
}
return 'OK';
"""


def main():
    server = ThreadingHTTPServer(('127.0.0.1', 0), partial(Handler, directory=str(ROOT)))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    options = webdriver.ChromeOptions()
    options.binary_location = os.environ.get('MAPA_CHROME', r'C:\Program Files\Google\Chrome\Application\chrome.exe')
    options.add_argument('--headless=new')
    options.add_argument('--window-size=1440,1100')
    options.add_argument('--disable-gpu')
    options.add_argument('--no-first-run')
    options.set_capability('goog:loggingPrefs', {'browser': 'ALL'})
    driver_path = os.environ.get('MAPA_CHROMEDRIVER')
    if not driver_path:
        candidates = sorted((Path.home() / '.cache/selenium/chromedriver/win64').glob('*/chromedriver.exe'))
        driver_path = str(candidates[-1]) if candidates else None
    driver = webdriver.Chrome(service=Service(driver_path), options=options)
    wait = WebDriverWait(driver, 10)
    try:
        for empresa in (1, 2):
            driver.get(f'http://127.0.0.1:{server.server_port}/dashboard_grafico/?_empresa_id={empresa}')
            wait.until(lambda d: len(d.find_elements('css selector', '.mapa-camion')) == 30)
            wait.until(lambda d: d.execute_script('return document.getElementById("mapa-imagen").naturalWidth') == 1786)
            assert len(driver.find_elements('css selector', '#mapa-zonas .mapa-camion')) == 6
            assert len(driver.find_elements('css selector', '.mapa-slots')) == 2
            assert driver.execute_script(GEOMETRY) == 'OK', driver.execute_script(GEOMETRY)
            for tipo, rgb in [('RECEPCION', 'rgb(20, 108, 67)'), ('DESPACHO', 'rgb(7, 90, 170)')]:
                assert driver.execute_script('return [...document.querySelectorAll(`.mapa-camion[data-tipo="${arguments[0]}"]`)].every(m=>getComputedStyle(m).backgroundColor===arguments[1])', tipo, rgb)
            driver.execute_script("document.querySelector('[data-zona=ZONA_CARGA_DESCARGA]').scrollIntoView({block:'center',inline:'center'})")
            driver.save_screenshot(str(ROOT / f'tmp/mapa_zonas_empresa{empresa}_desktop.png'))
            driver.execute_script("document.querySelector('.mapa-camion').click()")
            assert not driver.find_element('id', 'mapa-detalle').get_attribute('hidden')
            driver.execute_script('window.original=[...window.payload.camiones];window.payload.camiones[0].zona="ZONA_ESPERA";document.getElementById("mapa-refrescar").click()')
            wait.until(lambda d: len(d.find_elements('css selector', '[data-zona=ZONA_ESPERA] .mapa-camion')) == 13)
            assert len(driver.find_elements('css selector', '.mapa-camion')) == 30
            assert driver.execute_script(GEOMETRY) == 'OK', driver.execute_script(GEOMETRY)
            driver.execute_cdp_cmd('Emulation.setDeviceMetricsOverride', {'width': 390, 'height': 844, 'deviceScaleFactor': 1, 'mobile': True})
            assert driver.execute_script('return innerWidth') == 390
            assert driver.execute_script('return document.documentElement.scrollWidth <= innerWidth')
            assert driver.execute_script(GEOMETRY) == 'OK', driver.execute_script(GEOMETRY)
            driver.execute_script("document.querySelector('[data-zona=ZONA_CARGA_DESCARGA]').scrollIntoView({block:'center',inline:'center'})")
            driver.save_screenshot(str(ROOT / f'tmp/mapa_zonas_empresa{empresa}_mobile.png'))
            assert driver.execute_script("const v=document.getElementById('mapa-visor').getBoundingClientRect(), z=document.querySelector('[data-zona=ZONA_CARGA_DESCARGA]').getBoundingClientRect(); return z.left>=v.left && z.right<=v.right"), 'Operation zone clipped in mobile viewport'
            driver.execute_script("document.querySelector('[data-zona=ZONA_ESPERA]').scrollIntoView({block:'center',inline:'center'})")
            driver.save_screenshot(str(ROOT / f'tmp/mapa_zonas_empresa{empresa}_espera.png'))
            driver.execute_script('document.getElementById("mapa-ampliar").click()')
            assert driver.execute_script(GEOMETRY) == 'OK', driver.execute_script(GEOMETRY)
            driver.execute_script('window.payload.camiones=[];document.getElementById("mapa-refrescar").click()')
            wait.until(lambda d: not d.find_elements('css selector', '.mapa-camion'))
            assert driver.find_element('id', 'mapa-imagen').is_displayed()
            assert len(driver.find_elements('css selector', '.mapa-slot')) == 8
            assert driver.find_element('id', 'mapa-detalle').get_attribute('hidden')
            assert all(z.is_displayed() for z in driver.find_elements('css selector', '#mapa-capa [data-zona^=ZONA_]'))
            driver.execute_script('window.payload.camiones=window.original;document.getElementById("mapa-refrescar").click()')
            wait.until(lambda d: len(d.find_elements('css selector', '.mapa-camion')) == 30)
            driver.execute_script('window.failure=true;document.getElementById("mapa-refrescar").click()')
            wait.until(lambda d: d.find_element('id', 'mapa-operacional').get_attribute('data-obsoleto') == 'true')
            assert driver.find_element('id', 'mapa-imagen').is_displayed()
            errors = [entry for entry in driver.get_log('browser') if entry['level'] == 'SEVERE']
            assert not errors, errors
            driver.execute_cdp_cmd('Emulation.clearDeviceMetricsOverride', {})
            print(f'Empresa {empresa}: 30 trucks, slots/overflow, colors, plate visibility, movement, empty map, generic panel, stale state, desktop/mobile 390px, percent alignment: OK')
    finally:
        driver.quit()
        server.shutdown()


if __name__ == '__main__':
    main()
