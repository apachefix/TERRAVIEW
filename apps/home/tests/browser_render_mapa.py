"""Empty dashboard render audit using real IIS assets; no operational DB access.

Run: venv/Scripts/python.exe -m apps.home.tests.browser_render_mapa
The dashboard document and empty endpoint response are isolated fixtures. PNG,
CSS and JS load over HTTPS from IIS, using the deployed /static/ URLs.
"""
import json
import os
import threading
from functools import partial
from http.server import ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.support.ui import WebDriverWait

from .browser_mapa_operacional import Handler, ROOT, html

ORIGIN = os.environ.get('MAPA_STATIC_ORIGIN', 'https://terraview.terramar-group.com').rstrip('/')


class RenderHandler(Handler):
    def do_GET(self):
        url = urlparse(self.path)
        if url.path != '/dashboard_grafico/':
            return super().do_GET()
        empresa = int(parse_qs(url.query)['_empresa_id'][0])
        content = html(empresa, empty=True, static_origin=ORIGIN)
        self.send_response(200)
        self.send_header('Content-Type', 'text/html; charset=utf-8')
        self.end_headers()
        self.wfile.write(content)


AUDIT_DOM = """
const img=document.getElementById('mapa-imagen'), visor=document.getElementById('mapa-visor');
const chain=[];
for(let n=img;n;n=n.parentElement) {
  const css=getComputedStyle(n),r=n.getBoundingClientRect();
  chain.push({tag:n.tagName,id:n.id,display:css.display,visibility:css.visibility,
    opacity:css.opacity,width:r.width,height:r.height,overflow:css.overflow});
}
return {url:img.currentSrc,naturalWidth:img.naturalWidth,naturalHeight:img.naturalHeight,
  imageCount:document.querySelectorAll('#mapa-imagen').length,
  markers:document.querySelectorAll('.mapa-camion').length,
  baseZones:[...document.querySelectorAll('#mapa-capa [data-zona^=ZONA_]')].map(z=>({code:z.dataset.zona,hidden:z.hidden})),
  chain,visorHeight:visor.clientHeight};
"""


def main():
    server = ThreadingHTTPServer(('127.0.0.1', 0), partial(RenderHandler, directory=str(ROOT)))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    options = webdriver.ChromeOptions()
    options.binary_location = os.environ.get('MAPA_CHROME', r'C:\Program Files\Google\Chrome\Application\chrome.exe')
    options.add_argument('--headless=new')
    options.add_argument('--window-size=1440,1100')
    options.add_argument('--disable-gpu')
    options.set_capability('goog:loggingPrefs', {'browser': 'ALL', 'performance': 'ALL'})
    candidates = sorted((Path.home() / '.cache/selenium/chromedriver/win64').glob('*/chromedriver.exe'))
    driver = webdriver.Chrome(service=Service(os.environ.get('MAPA_CHROMEDRIVER', str(candidates[-1]))), options=options)
    wait = WebDriverWait(driver, 20)
    reports = []
    try:
        driver.execute_cdp_cmd('Network.enable', {})
        driver.execute_cdp_cmd('Network.setCacheDisabled', {'cacheDisabled': True})
        for empresa in (1, 2):
            driver.get(f'http://127.0.0.1:{server.server_port}/dashboard_grafico/?_empresa_id={empresa}')
            wait.until(lambda d: d.execute_script('return document.getElementById("mapa-imagen").naturalWidth') == 1786)
            wait.until(lambda d: len(d.find_elements('css selector', '#mapa-capa [data-zona^=ZONA_]')) == 2)
            report = driver.execute_script(AUDIT_DOM)
            report['empresa_id'] = empresa
            report['fixture'] = 'Dashboard template with zero trucks; static assets from real IIS'
            image_responses = []
            for entry in driver.get_log('performance'):
                message = json.loads(entry['message'])['message']
                if message['method'] == 'Network.responseReceived':
                    response = message['params']['response']
                    if response['url'] == report['url']:
                        image_responses.append({'url': response['url'], 'status': response['status'], 'mimeType': response['mimeType']})
            assert image_responses and image_responses[-1]['status'] == 200, image_responses
            assert image_responses[-1]['mimeType'] == 'image/png', image_responses
            report['http'] = image_responses[-1]
            assert report['imageCount'] == 1 and report['markers'] == 0
            assert report['naturalHeight'] == 2526 and report['visorHeight'] >= 400
            assert all(n['display'] != 'none' and n['visibility'] == 'visible' and float(n['opacity']) > 0
                       and n['width'] > 0 and n['height'] > 0 for n in report['chain'])
            assert all(not z['hidden'] for z in report['baseZones'])
            driver.find_element('id', 'mapa-visor').screenshot(str(ROOT / f'tmp/mapa_render_vacio_empresa{empresa}.png'))
            driver.execute_script('window.payload.zonas=[];document.getElementById("mapa-refrescar").click()')
            assert driver.find_element('id', 'mapa-imagen').is_displayed()
            driver.execute_script('window.failure=true;document.getElementById("mapa-refrescar").click()')
            wait.until(lambda d: d.find_element('id', 'mapa-operacional').get_attribute('data-obsoleto') == 'true')
            assert driver.find_element('id', 'mapa-imagen').is_displayed()
            driver.execute_cdp_cmd('Emulation.setDeviceMetricsOverride', {'width': 390, 'height': 844, 'deviceScaleFactor': 1, 'mobile': True})
            mobile = driver.execute_script(AUDIT_DOM)
            assert mobile['visorHeight'] >= 400 and mobile['naturalWidth'] == 1786
            assert driver.execute_script('return document.documentElement.scrollWidth <= innerWidth')
            report['mobile'] = mobile
            driver.execute_cdp_cmd('Emulation.clearDeviceMetricsOverride', {})
            errors = [entry for entry in driver.get_log('browser') if entry['level'] == 'SEVERE']
            assert not errors, errors
            reports.append(report)
            print(f"Empresa {empresa}: zero trucks; PNG HTTP 200 image/png; natural size 1786x2526; visible parents; viewport {report['visorHeight']}px; base zones; empty zones; failed endpoint; mobile: OK")
        (ROOT / 'tmp/mapa_render_auditoria.json').write_text(json.dumps(reports, indent=2, ensure_ascii=False), encoding='utf-8')
    finally:
        driver.quit()
        server.shutdown()


if __name__ == '__main__':
    main()
