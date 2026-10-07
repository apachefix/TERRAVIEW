"""Chrome UX regression using the real rendered Django layout and local assets.
Only an in-memory test database is used; operational data is never accessed.
Run: venv/Scripts/python.exe -m apps.home.tests.browser_mapa_ux
"""
import json
import os
import re
import threading
from functools import partial
from http.server import ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.support.ui import WebDriverWait

from .browser_mapa_operacional import Handler, ROOT, html, GEOMETRY


def documents():
    os.environ['DJANGO_SETTINGS_MODULE'] = 'core.settings'
    from django.conf import settings
    settings.DATABASES = {'default': {'ENGINE': 'django.db.backends.sqlite3', 'NAME': ':memory:'}}
    settings.MIGRATION_MODULES = {'home': None}
    settings.CACHES = {'default': {'BACKEND': 'django.core.cache.backends.locmem.LocMemCache'}}
    settings.ALLOWED_HOSTS = ['testserver', 'localhost']
    import django
    django.setup()
    from django.core.management import call_command
    call_command('migrate', run_syncdb=True, skip_checks=True, verbosity=0)
    from django.test import Client
    from .test_mapa_operacional import MapaOperacionalTests
    MapaOperacionalTests.setUpTestData()
    client = Client()
    client.force_login(MapaOperacionalTests.user)
    result = {}
    for company in (1, 2):
        response = client.get('/dashboard_grafico/', {'_empresa_id': company})
        assert response.status_code == 200
        markup = response.content.decode('utf-8-sig')
        # Preserve the real layout and styles; isolate unrelated module scripts.
        markup = re.sub(r'<script\b[^>]*>.*?</script>', '', markup, flags=re.S | re.I)
        markup = re.sub(r'<link\b[^>]*href=["\']https?://[^>]*>', '', markup)
        fixture = html(company).decode('utf-8')
        payload = fixture.split('window.payload=', 1)[1].split(';window.failure=', 1)[0]
        bootstrap = (
            '<script>window.payload=' + payload + ';window.failure=false;window.denied=false;'
            'window.fetchCount=0;window.fetch=async()=>{window.fetchCount++;await new Promise(r=>setTimeout(r,250));'
            'if(window.failure)throw new Error("Offline");'
            'return {ok:!window.denied,status:window.denied?403:200,json:async()=>window.payload}};</script>'
            '<script src="/static/assets/js/mapa-operacional.js"></script>'
        )
        result[company] = markup.replace('</body>', bootstrap + '</body>').encode('utf-8')
    return result


FIT = """
const v=document.getElementById('mapa-visor'),i=document.getElementById('mapa-imagen'),
r=i.getBoundingClientRect(), b=v.getBoundingClientRect();
return {fits:r.width<=v.clientWidth+1 && r.height<=v.clientHeight+1
  && r.left>=b.left && r.right<=b.right+1 && r.top>=b.top && r.bottom<=b.bottom+1,
  noScroll:v.scrollWidth<=v.clientWidth+1 && v.scrollHeight<=v.clientHeight+1,
  naturalWidth:i.naturalWidth,src:i.currentSrc,zoom:document.getElementById('mapa-zoom').textContent};
"""


def main():
    pages = documents()

    class UXHandler(Handler):
        def do_GET(self):
            url = urlparse(self.path)
            if url.path == '/dashboard_grafico/':
                content = pages[int(parse_qs(url.query)['_empresa_id'][0])]
                self.send_response(200)
                self.send_header('Content-Type', 'text/html; charset=utf-8')
                self.end_headers()
                self.wfile.write(content)
            elif url.path.startswith('/static/'):
                self.path = self.path.replace('/static/', '/apps/static/', 1)
                super().do_GET()
            else:
                super().do_GET()

    server = ThreadingHTTPServer(('127.0.0.1', 0), partial(UXHandler, directory=str(ROOT)))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    options = webdriver.ChromeOptions()
    options.binary_location = os.environ.get('MAPA_CHROME', r'C:\Program Files\Google\Chrome\Application\chrome.exe')
    options.add_argument('--headless=new')
    options.add_argument('--disable-gpu')
    options.set_capability('goog:loggingPrefs', {'browser': 'ALL', 'performance': 'ALL'})
    paths = sorted((Path.home() / '.cache/selenium/chromedriver/win64').glob('*/chromedriver.exe'))
    driver = webdriver.Chrome(service=Service(str(paths[-1])), options=options)
    wait = WebDriverWait(driver, 20)
    reports = []
    try:
        for company in (1, 2):
            for width, height in ((1920, 1080), (1366, 768), (390, 844)):
                driver.execute_cdp_cmd('Emulation.setDeviceMetricsOverride', {
                    'width': width, 'height': height, 'deviceScaleFactor': 1, 'mobile': width < 500})
                driver.get(f'http://127.0.0.1:{server.server_port}/dashboard_grafico/?_empresa_id={company}')
                wait.until(lambda d: len(d.find_elements('css selector', '.mapa-fila-camion')) == 30)
                wait.until(lambda d: d.execute_script(FIT)['naturalWidth'] == 1786)
                wait.until(lambda d: d.execute_script(FIT)['fits'])
                fit = driver.execute_script(FIT)
                assert fit['noScroll'] and fit['zoom'] == '100%', fit
                assert driver.execute_script('return document.documentElement.scrollWidth<=innerWidth')
                assert len(driver.find_elements('css selector', '.mapa-kpi')) == 7
                assert len(driver.find_elements('css selector', '.mapa-resumen-fila')) == 6
                assert driver.execute_script(GEOMETRY) == 'OK', driver.execute_script(GEOMETRY)
                assert driver.execute_script("""
const a=document.querySelector('.mapa-lateral').getBoundingClientRect(),
b=document.getElementById('mapa-visor').getBoundingClientRect();
return innerWidth<850 ? a.top>=b.bottom : a.left>=b.right;
""")
                for kind, color in (('RECEPCION', 'rgb(20, 108, 67)'), ('DESPACHO', 'rgb(7, 90, 170)')):
                    assert driver.execute_script("""
return [...document.querySelectorAll('.mapa-camion')].filter(m=>m.dataset.tipo===arguments[0])
.every(m=>getComputedStyle(m).backgroundColor===arguments[1]);
""", kind, color)
                prefix = f'tmp/mapa_ux_empresa{company}_{width}'
                driver.save_screenshot(str(ROOT / (prefix + '.png')))
                # Both selectors point to the same existing detail and persistent timer.
                driver.find_element('css selector', '.mapa-fila-camion').click()
                wait.until(lambda d: d.find_element('id', 'mapa-detalle').is_displayed())
                assert 'ABCD00' in driver.find_element('id', 'mapa-detalle-titulo').text
                initial = driver.find_element('id', 'mapa-detalle-timer').text
                wait.until(lambda d: d.find_element('id', 'mapa-detalle-timer').text != initial)
                assert driver.execute_script("""
return document.getElementById('mapa-detalle-timer').textContent===
document.querySelector('.mapa-fila-camion .mapa-timer').textContent;
""")
                if width == 1920:
                    count = driver.execute_script('return window.fetchCount')
                    wait.until(lambda d: d.execute_script('return window.fetchCount') > count)
                    assert 'ABCD00' in driver.find_element('id', 'mapa-detalle-titulo').text
                    driver.save_screenshot(str(ROOT / f'tmp/mapa_ux_empresa{company}_detalle.png'))
                driver.find_element('id', 'mapa-cerrar').click()
                driver.execute_script("document.querySelector('#mapa-atajos button:last-child').click()")
                assert driver.execute_script(GEOMETRY) == 'OK'
                driver.find_element('css selector', '#mapa-capa .mapa-camion').click()
                assert driver.find_element('id', 'mapa-detalle').is_displayed()
                driver.execute_script("document.getElementById('mapa-ajustar').click()")
                assert driver.execute_script(FIT)['fits']
                # Fullscreen uses the real browser API, initiated by a click.
                if width == 1920:
                    driver.execute_script('window.scrollTo(0,0)')
                    driver.find_element('id', 'mapa-completa').click()
                    wait.until(lambda d: d.execute_script('return !!document.fullscreenElement'))
                    wait.until(lambda d: d.execute_script(FIT)['fits'])
                    driver.find_element('id', 'mapa-completa').click()
                    wait.until(lambda d: not d.execute_script('return !!document.fullscreenElement'))
                driver.execute_script("""
window.saved=window.payload.camiones;
window.payload.camiones=[];window.payload.kpis=Object.fromEntries(Object.keys(window.payload.kpis).map(k=>[k,0]));
document.getElementById('mapa-refrescar').click();
""")
                wait.until(lambda d: not d.find_elements('css selector', '.mapa-camion'))
                assert not driver.find_elements('css selector', '.mapa-fila-camion')
                assert driver.find_element('id', 'mapa-vacio').is_displayed()
                assert driver.find_element('id', 'mapa-detalle').get_attribute('hidden')
                assert driver.execute_script(FIT)['fits']
                assert all(z.is_displayed() for z in driver.find_elements('css selector', '#mapa-capa [data-zona^=ZONA_]'))
                driver.execute_script('window.scrollTo(0,0)')
                driver.save_screenshot(str(ROOT / (prefix + '_vacio.png')))
                driver.execute_script('window.payload.camiones=window.saved;document.getElementById("mapa-refrescar").click()')
                wait.until(lambda d: len(d.find_elements('css selector', '.mapa-fila-camion')) == 30)
                driver.execute_script('window.failure=true;document.getElementById("mapa-refrescar").click()')
                wait.until(lambda d: d.find_element('id', 'mapa-operacional').get_attribute('data-obsoleto') == 'true')
                frozen = driver.find_element('css selector', '.mapa-fila-camion .mapa-timer').get_attribute('textContent')
                # Use a browser timer to validate frozen elapsed time, without changing production clocks.
                driver.execute_async_script('const done=arguments[0];setTimeout(done,1100)')
                assert frozen == driver.find_element('css selector', '.mapa-fila-camion .mapa-timer').get_attribute('textContent')
                driver.execute_script('window.failure=false;window.denied=true;document.getElementById("mapa-refrescar").click()')
                wait.until(lambda d: not d.find_elements('css selector', '.mapa-fila-camion'))
                assert not driver.find_elements('css selector', '.mapa-camion')
                assert driver.find_element('id', 'mapa-imagen').is_displayed()
                errors = [x for x in driver.get_log('browser') if x['level'] == 'SEVERE']
                assert not errors, errors
                reports.append({'company': company, 'viewport': [width, height], 'fit': fit,
                                'trucks': 30, 'empty': True, 'selection': True, 'timers': True,
                                'sidebar': True, 'stale': True, 'access_cleanup': True,
                                'polling_and_fullscreen': width == 1920})
                print(f'Empresa {company}, {width}x{height}: 30/0 trucks, fit, sidebar, colors, selection, timers, stale/access: OK')
        (ROOT / 'tmp/mapa_ux_validacion.json').write_text(json.dumps(reports, indent=2), encoding='utf-8')
    finally:
        driver.quit()
        server.shutdown()


if __name__ == '__main__':
    main()
