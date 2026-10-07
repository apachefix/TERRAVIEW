"""Local browser smoke check with synthetic responses; no application/DB writes."""
import json
from pathlib import Path
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.support.ui import WebDriverWait

ROOT = Path(__file__).resolve().parents[1]
template = (ROOT / 'apps/templates/home/HOME/monitor.html').read_text(encoding='utf-8')
body = template.split('{% block content %}')[1].split('{% endblock %}')[0]
body = body.replace('{{ mapa_empresa_id }}', '1').replace("{% url 'dashboard_grafico_estado' %}", '/dashboard_grafico/estado/')
body = body.replace("{% static 'assets/plano/plantilla_planta.png' %}", (ROOT / 'apps/static/assets/plano/plantilla_planta.png').as_uri())
truck = {'citacion_id': 90001, 'patente': 'TEST01', 'empresa_id': 1, 'empresa': 'TERRAMAR CHILE',
         'tipo': 'RECEPCION', 'etapa': 'Pesaje Entrada', 'estado': 'EN PROCESO',
         'secuencia': 'RECEPCION_TERRAMAR', 'secuencia_nombre': 'Recepción Terramar', 'zona': 'ROMANA',
         'segundos_etapa': 75, 'inicio_etapa': '2026-10-04T10:00:00-03:00', 'timer_activo': True,
         'eventos': [], 'trazabilidad_url': '/trazabilidad/buscar/?q=90001&_empresa_id=1'}
payload = {'empresa_id': 1, 'empresa': 'TERRAMAR CHILE', 'generado_en': '2026-10-04T10:01:15-03:00',
           'camiones': [dict(truck, citacion_id=90001+i, patente=f'TEST{i:02d}', tipo='DESPACHO' if i%2 else 'RECEPCION') for i in range(30)],
           'zonas': [{'codigo': 'ROMANA', 'nombre': 'Romana', 'x_pct': None, 'y_pct': None, 'habilitado': True},
                     {'codigo': 'DESCARGA', 'nombre': 'Descarga', 'x_pct': 35, 'y_pct': 30, 'width_pct': 25, 'height_pct': 10, 'habilitado': True}],
           'kpis': {'total':30,'recepciones':15,'despachos':15,'romana':30,'calidad':0,'carga_descarga':0,'salida':0}, 'cupos': [], 'sin_soporte':0}
css = (ROOT / 'apps/static/assets/css/mapa-operacional.css').as_uri()
js = (ROOT / 'apps/static/assets/js/mapa-operacional.js').as_uri()
bootstrap = (ROOT / 'apps/static/assets/css/style.css').as_uri()
harness = ROOT / 'tmp/mapa_browser_check.html'
if not harness.exists():
    harness.write_text('<!doctype html><html lang="es"><meta charset="utf-8"><link rel="stylesheet" href="'+bootstrap+'"><link rel="stylesheet" href="'+css+'"><style>body{padding:20px}.pcoded-main-container{margin:0}.pcoded-content{padding:0}</style>'+body+
                       '<script>window.payload='+json.dumps(payload)+';window.failure=false;window.calls=0;window.fetch=async()=>{window.calls++;if(window.failure)throw new Error("Offline");return {ok:true,status:200,json:async()=>window.payload}}</script><script src="'+js+'"></script></html>',encoding='utf-8')
options = webdriver.ChromeOptions()
options.binary_location = r'C:\Program Files\Google\Chrome\Application\chrome.exe'
options.add_argument('--headless=new')
options.add_argument('--window-size=1440,1100')
options.add_argument('--disable-gpu')
options.add_argument('--no-first-run')
options.add_argument('--no-default-browser-check')
options.set_capability('goog:loggingPrefs', {'browser': 'ALL'})
driver = webdriver.Chrome(service=Service(r'C:\Users\external01\.cache\selenium\chromedriver\win64\154.0.8037.92\chromedriver.exe'), options=options)
try:
    driver.get(harness.as_uri())
    wait = WebDriverWait(driver, 10)
    wait.until(lambda d: len(d.find_elements('css selector', '.mapa-camion')) == 30)
    assert driver.execute_script('return document.getElementById("mapa-imagen").naturalWidth') == 1786
    driver.find_element('css selector','.mapa-camion').click()
    assert not driver.find_element('id','mapa-detalle').get_attribute('hidden')
    driver.execute_script('window.payload.camiones[0].zona="DESCARGA";window.payload.camiones[0].etapa="Ciclo Descarga";document.getElementById("mapa-refrescar").click()')
    wait.until(lambda d: len(d.find_elements('css selector','#mapa-capa .mapa-camion')) == 1)
    assert len(driver.find_elements('css selector','.mapa-camion')) == 30
    assert len(driver.find_elements('css selector','[data-tipo="DESPACHO"]')) == 15
    driver.save_screenshot(str(ROOT / 'tmp/mapa_desktop.png'))
    driver.set_window_size(390,844)
    assert driver.execute_script('return document.documentElement.scrollWidth <= window.innerWidth')
    driver.save_screenshot(str(ROOT / 'tmp/mapa_mobile.png'))
    driver.execute_script('window.payload.camiones.splice(0,1);document.getElementById("mapa-refrescar").click()')
    wait.until(lambda d: len(d.find_elements('css selector','.mapa-camion')) == 29)
    assert driver.find_element('id','mapa-detalle').get_attribute('hidden')
    driver.execute_script('window.failure=true;document.getElementById("mapa-refrescar").click()')
    wait.until(lambda d: d.find_element('id','mapa-operacional').get_attribute('data-obsoleto') == 'true')
    errors = [log for log in driver.get_log('browser') if log['level']=='SEVERE']
    assert not errors, errors
    print('BROWSER OK: 30 markers, 15 blue/15 green, detail, transition, no duplicates, exit removal, stale state, mobile 390px, zero JS errors.')
finally:
    driver.quit()
