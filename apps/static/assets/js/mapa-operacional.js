(() => {
  'use strict';
  const root = document.getElementById('mapa-operacional');
  if (!root) return;
  const el = id => document.getElementById(`mapa-${id}`);
  const markers = new Map(), zones = new Map(), rows = new Map();
  let trucks = new Map(), selected = null, received = 0, inFlight = false;
  let poll = null, lastUpdate = null, zoom = 1, frozenAt = 0;
  const node = (tag, text, cls) => {
    const n = document.createElement(tag);
    if (text !== undefined) n.textContent = text;
    if (cls) n.className = cls;
    return n;
  };
  const duration = truck => {
    if (truck.segundos_etapa === null) return 'Sin inicio registrado';
    const clock = root.dataset.obsoleto === 'true' ? frozenAt : performance.now();
    const extra = truck.timer_activo ? Math.floor((clock - received) / 1000) : 0;
    const s = Math.max(0, truck.segundos_etapa + extra);
    return [Math.floor(s / 3600), Math.floor(s / 60) % 60, s % 60].map(n => String(n).padStart(2, '0')).join(':');
  };
  const timestamp = value => value ? new Date(value).toLocaleString('es-CL', {timeZone: 'America/Santiago'}) : 'Sin registro';
  function timers() {
    for (const [id, marker] of markers) marker.querySelector('.mapa-timer').textContent = duration(trucks.get(id));
    for (const [id, row] of rows) row.querySelector('.mapa-timer').textContent = duration(trucks.get(id));
    const timer = document.getElementById('mapa-detalle-timer');
    if (timer && trucks.has(selected)) timer.textContent = duration(trucks.get(selected));
  }
  function detail(id, reveal = false) {
    selected = id;
    const t = trucks.get(id);
    for (const [key, marker] of markers) marker.setAttribute('aria-pressed', String(key === id));
    for (const [key, row] of rows) row.setAttribute('aria-pressed', String(key === id));
    el('seleccion').hidden = !!t;
    if (!t) { selected = null; el('detalle').hidden = true; return; }
    el('detalle').hidden = false;
    el('detalle-titulo').textContent = `${t.patente} · Citación ${t.citacion_id}`;
    const list = el('detalle-datos'); list.replaceChildren();
    const fields = [
      ['Empresa', t.empresa], ['Tipo', t.tipo], ['Secuencia', `${t.secuencia_nombre} (${t.secuencia})`],
      ['Etapa actual', t.etapa], ['Zona', zones.get(t.zona)?.config.nombre || t.zona],
      ['Estado', t.estado], ['Tiempo en etapa', duration(t)], ['Inicio', timestamp(t.inicio_etapa)],
      ['Producto', t.producto], ['Transportista', t.transportista], ['Conductor', t.conductor],
      ['Estanque origen', t.estanque_origen], ['Estanque destino', t.estanque_destino], ['Documento', t.documento]
    ];
    for (const [label, value] of fields) {
      const dd = node('dd', value || 'Sin registro');
      if (label === 'Tiempo en etapa') dd.id = 'mapa-detalle-timer';
      list.append(node('dt', label), dd);
    }
    el('eventos').replaceChildren(...t.eventos.map(e => node('li', `${timestamp(e.fecha)} · ${e.paso} · ${e.estado}`)));
    el('trazabilidad').href = t.trazabilidad_url;
    if (reveal) {
      el('detalle-titulo').focus({preventScroll: true});
      root.querySelector('.mapa-lateral').scrollTo(0, 0);
      if (innerWidth <= 850) el('detalle').scrollIntoView({block: 'center', behavior: 'smooth'});
    }
  }
  function distribute(zone, occupants) {
    if (!zone.lanes) {
      for (const t of occupants) {
        const marker = markers.get(t.citacion_id);
        if (marker.parentNode !== zone.items) zone.items.append(marker);
      }
      return;
    }
    for (const [type, lane] of zone.lanes) {
      const group = occupants.filter(t => t.tipo === type);
      const capacity = zone.config.slots_por_tipo;
      lane.heading.textContent = `${type === 'DESPACHO' ? 'Despacho' : 'Recepción'} · ${group.length}`;
      lane.heading.dataset.resumen = `${type[0]} · ${group.length}`;
      lane.note.textContent = group.length > capacity ? `+${group.length - capacity} en filas adicionales ↓` : `${capacity} posiciones visuales`;
      const count = Math.max(capacity, group.length);
      while (lane.items.children.length < count) {
        const index = lane.items.children.length;
        const slot = node('div', undefined, 'mapa-slot');
        slot.append(node('small', index < capacity ? `${type[0]}${index + 1}` : 'Adicional'), node('span', 'Libre', 'mapa-slot-libre'));
        lane.items.append(slot);
      }
      group.forEach((t, index) => {
        const slot = lane.items.children[index], marker = markers.get(t.citacion_id);
        if (marker.parentNode !== slot) slot.append(marker);
      });
      // All markers have their final destination before releasing empty slots.
      while (lane.items.children.length > count) lane.items.lastElementChild.remove();
      for (const slot of lane.items.children) slot.children[1].hidden = !!slot.querySelector('.mapa-camion');
    }
  }
  function focusZone(code) {
    const section = zones.get(code)?.section;
    if (!section) return;
    zoom = Math.max(zoom, 1400 / fitWidth());
    layoutMap();
    const viewport = el('visor');
    viewport.scrollTo({left: section.offsetLeft + section.offsetWidth / 2 - viewport.clientWidth / 2,
      top: section.offsetTop + section.offsetHeight / 2 - viewport.clientHeight / 2});
  }
  function truckList(data) {
    for (const [id, row] of rows) {
      if (!trucks.has(id)) { row.remove(); rows.delete(id); }
    }
    for (const t of data.camiones) {
      let row = rows.get(t.citacion_id);
      if (!row) {
        row = node('button', undefined, 'mapa-fila-camion');
        row.type = 'button'; row.dataset.id = t.citacion_id;
        row.append(node('strong'), node('span', '', 'mapa-timer'), node('small'));
        rows.set(t.citacion_id, row); el('lista').append(row);
      }
      row.dataset.tipo = t.tipo;
      row.children[0].textContent = t.patente;
      row.children[2].textContent = `${t.tipo === 'DESPACHO' ? 'Despacho' : 'Recepción'} · ${zones.get(t.zona)?.config.nombre || t.zona} · ${t.etapa}`;
      row.setAttribute('aria-label', `${t.patente}, ${t.tipo}, ${t.etapa}`);
      row.setAttribute('aria-pressed', String(t.citacion_id === selected));
    }
    el('total-lista').textContent = `(${data.camiones.length})`;
  }
  function zoneSummary(data) {
    // Presentation labels only: quantities reuse the existing KPI dataset.
    const summaries = [
      ['Romana', data.kpis.romana, '(sin posición)'],
      ['Espera calidad', data.kpis.calidad, '(en zona de espera)', 'ZONA_ESPERA'],
      ['Carga / descarga', data.kpis.carga_descarga, '(posición inicial)', 'ZONA_CARGA_DESCARGA'],
      ['Espera salida', data.kpis.salida, '(sin posición)'],
      ['Portería', null, '(sin posición)'],
      ['Estanques TK-01 a TK-12', null, '(asociación pendiente)'],
    ];
    el('resumen-zonas').replaceChildren(...summaries.map(([name, count, status, code]) => {
      const row = node('div', undefined, 'mapa-resumen-fila');
      const label = node(code ? 'button' : 'span', `${name}${count === null ? '' : ' · ' + count}`);
      if (code) { label.type = 'button'; label.addEventListener('click', () => focusZone(code)); }
      row.append(label, node('small', status)); return row;
    }));
  }
  function kpiIcon(key) {
    const paths = {
      total: 'M3 6h11v11H3z M14 10h4l3 4v3h-7 M5 17a2 2 0 1 0 4 0 M15 17a2 2 0 1 0 4 0',
      romana: 'M12 3v17 M6 20h12 M3 6h18 M6 6l-3 8h6z M18 6l-3 8h6z',
      calidad: 'M9 3h6 M10 3v6L4 19q-1 2 2 2h12q3 0 2-2L14 9V3 M8 14h8',
      carga_descarga: 'M4 6h16v14H4z M4 11h16 M9 6V3h6v3 M9 15h6',
      salida: 'M13 3H4v18h9 M10 12h11 M17 8l4 4-4 4',
    };
    const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
    svg.setAttribute('viewBox', '0 0 24 24'); svg.setAttribute('aria-hidden', 'true');
    svg.classList.add('mapa-kpi-icon');
    const path = document.createElementNS(svg.namespaceURI, 'path');
    path.setAttribute('d', paths[key] || paths.total);
    path.setAttribute('fill', 'none'); path.setAttribute('stroke', 'currentColor');
    path.setAttribute('stroke-width', '1.8'); path.setAttribute('stroke-linejoin', 'round');
    svg.append(path); return svg;
  }
  function render(data) {
    if (data.empresa_id !== Number(root.dataset.empresa)) throw new Error('Empresa inesperada');
    root.dataset.obsoleto = 'false'; received = performance.now();
    trucks = new Map(data.camiones.map(t => [t.citacion_id, t]));
    for (const z of data.zonas.filter(z => z.habilitado)) {
      if (zones.has(z.codigo)) continue;
      const section = node('section', undefined, 'mapa-zona');
      const heading = node('h3', z.nombre), items = node('div', undefined, 'mapa-vehiculos');
      section.append(heading, items);
      const physical = Number.isFinite(z.x_pct) && Number.isFinite(z.y_pct);
      const zone = {config: z, section, heading, items, physical};
      section.dataset.zona = z.codigo;
      if (physical) {
        Object.assign(section.style, {left: `${z.x_pct}%`, top: `${z.y_pct}%`, width: `${z.width_pct}%`, height: `${z.height_pct}%`});
        el('capa').append(section);
        if (z.distribucion === 'por_tipo') {
          section.classList.add('mapa-con-slots');
          zone.lanes = new Map();
          items.classList.add('mapa-carriles');
          for (const type of ['DESPACHO', 'RECEPCION']) {
            const lane = node('div', undefined, 'mapa-carril');
            const title = node('h4'), note = node('small', '', 'mapa-adicionales');
            const slots = node('div', undefined, 'mapa-slots');
            slots.style.setProperty('--columnas', z.slots_por_tipo);
            lane.append(title, note, slots); items.append(lane);
            zone.lanes.set(type, {heading: title, note, items: slots});
          }
        } else if (z.distribucion === 'espera') {
          items.classList.add('mapa-espera');
          items.style.setProperty('--columnas', z.columnas);
        }
      } else el('zonas').append(section);
      zones.set(z.codigo, zone);
      if (physical && z.distribucion) {
        const shortcut = node('button', `Ver ${z.nombre.toLowerCase()}`, 'btn btn-sm btn-light');
        shortcut.type = 'button';
        shortcut.addEventListener('click', () => focusZone(z.codigo));
        el('atajos').append(shortcut);
      }
    }
    for (const [id, marker] of markers) {
      if (!trucks.has(id)) { marker.remove(); markers.delete(id); }
    }
    for (const t of data.camiones) {
      let marker = markers.get(t.citacion_id);
      if (!marker) {
        marker = node('button', undefined, 'mapa-camion'); marker.type = 'button'; marker.dataset.id = t.citacion_id;
        marker.append(node('strong'), node('span'), node('span', '', 'mapa-timer'), node('small'));
        const icon = kpiIcon('total'); icon.classList.add('mapa-icono-camion'); marker.append(icon);
        markers.set(t.citacion_id, marker);
      }
      marker.dataset.tipo = t.tipo;
      marker.children[0].textContent = t.patente;
      marker.children[1].textContent = t.etapa;
      marker.children[3].textContent = `#${t.citacion_id} · ${t.estado}`;
      marker.setAttribute('aria-label', `${t.patente}, ${t.tipo}, ${t.etapa}, citación ${t.citacion_id}`);
      marker.title = `${t.patente} · ${t.etapa} · #${t.citacion_id}`;
    }
    // Detach movers first so a shrinking lane cannot remove another zone's truck.
    for (const t of data.camiones) {
      const marker = markers.get(t.citacion_id);
      if (marker.closest('.mapa-zona')?.dataset.zona !== t.zona) marker.remove();
    }
    for (const z of zones.values()) {
      const occupants = data.camiones.filter(t => t.zona === z.config.codigo).sort((a, b) => a.citacion_id - b.citacion_id);
      distribute(z, occupants);
      const count = occupants.length;
      z.heading.textContent = `${z.config.nombre} · ${count}`;
      z.section.hidden = count === 0 && !(z.physical && z.config.distribucion);
    }
    const labels = {total: 'Dentro de planta', recepciones: 'Recepciones', despachos: 'Despachos', romana: 'En romana', calidad: 'Espera calidad', carga_descarga: 'Carga / descarga', salida: 'Espera salida'};
    el('kpis').replaceChildren(...Object.entries(labels).map(([key, label]) => {
      const card = node('div', undefined, 'mapa-kpi'), text = node('div');
      card.dataset.kpi = key;
      text.append(node('strong', data.kpis[key]), node('span', label));
      card.append(kpiIcon(key), text); return card;
    }));
    el('cupos').replaceChildren(...data.cupos.map(z => {
      const row = node('tr'); row.append(node('td', z.nombre), node('td', z.ocupados), node('td', z.maximos ?? 'Sin definir')); return row;
    }));
    el('empresa').textContent = data.empresa || (data.camiones[0]?.empresa ?? `Empresa ${data.empresa_id}`);
    el('vacio').hidden = data.camiones.length > 0;
    el('sin-soporte').hidden = data.sin_soporte === 0;
    el('sin-soporte').textContent = `${data.sin_soporte} procesos abiertos fuera del alcance físico configurado.`;
    lastUpdate = data.generado_en;
    el('estado').textContent = `Actualizado: ${timestamp(lastUpdate)} · Consulta cada 15 segundos`;
    el('conexion').textContent = '● Estado actualizado';
    truckList(data);
    zoneSummary(data);
    if (selected !== null) detail(selected);
    layoutMap();
    timers();
  }
  async function refresh() {
    if (inFlight || document.hidden) return;
    inFlight = true; el('refrescar').disabled = true;
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 12000);
    try {
      const response = await fetch(root.dataset.endpoint, {method: 'GET', cache: 'no-store', credentials: 'same-origin', signal: controller.signal, headers: {'Accept': 'application/json'}});
      if (response.redirected || response.status === 401 || response.status === 403) {
        for (const m of markers.values()) m.remove();
        markers.clear(); trucks.clear(); selected = null;
        rows.clear(); el('lista').replaceChildren(); el('resumen-zonas').replaceChildren();
        el('total-lista').textContent = '(0)'; el('seleccion').hidden = false;
        el('kpis').replaceChildren(); el('cupos').replaceChildren(); el('detalle').hidden = true;
        for (const z of zones.values()) z.section.hidden = true;
        throw new Error('Sesión o permiso no disponible. Vuelve a ingresar con una empresa autorizada.');
      }
      if (!response.ok) throw new Error('No fue posible actualizar el estado.');
      render(await response.json());
    } catch (error) {
      if (root.dataset.obsoleto !== 'true') frozenAt = performance.now();
      root.dataset.obsoleto = 'true';
      el('conexion').textContent = '● Sin actualizar';
      el('estado').textContent = `Datos sin actualizar. ${error.message} ${lastUpdate ? `Última lectura: ${timestamp(lastUpdate)}` : ''}`;
    } finally {
      clearTimeout(timeout); inFlight = false; el('refrescar').disabled = false;
      clearTimeout(poll); poll = setTimeout(refresh, 15000);
    }
  }
  root.addEventListener('click', event => {
    const marker = event.target.closest('.mapa-camion, .mapa-fila-camion');
    if (marker) detail(Number(marker.dataset.id), true);
  });
  el('cerrar').addEventListener('click', () => detail(null));
  el('refrescar').addEventListener('click', refresh);
  function fitWidth() {
    const img = el('imagen'), v = el('visor');
    const ratio = (img.naturalWidth || 1786) / (img.naturalHeight || 2526);
    return Math.max(1, Math.min(v.clientWidth - 2, (v.clientHeight - 2) * ratio));
  }
  function layoutMap() {
    const viewport = el('visor');
    const fullscreen = document.fullscreenElement === root;
    const top = viewport.getBoundingClientRect().top + (fullscreen ? root.scrollTop : window.scrollY);
    const height = innerWidth <= 850 ? 540 : Math.min(950, Math.max(400, innerHeight - top - 34));
    viewport.style.height = `${height}px`;
    root.style.setProperty('--mapa-view-height', `${height}px`);
    const width = fitWidth() * zoom;
    el('lienzo').style.maxWidth = 'none';
    el('lienzo').style.width = `${width}px`;
    el('lienzo').dataset.compacto = String(width < 1100);
    el('lienzo').dataset.mini = String(width < 800);
    el('lienzo').dataset.diminuto = String(width < 400);
    el('zoom').textContent = `${Math.round(zoom * 100)}%`;
    el('reducir').disabled = zoom <= 1;
    el('ampliar').disabled = zoom >= 6;
    if (zoom === 1) el('visor').scrollTo(0, 0);
  }
  function scale(delta) {
    const v = el('visor'), canvas = el('lienzo');
    const left = () => canvas.getBoundingClientRect().left - v.getBoundingClientRect().left + v.scrollLeft - v.clientLeft;
    const x = (v.scrollLeft + v.clientWidth / 2 - left()) / canvas.offsetWidth;
    const y = (v.scrollTop + v.clientHeight / 2) / canvas.offsetHeight;
    zoom = Math.min(6, Math.max(1, zoom + delta));
    layoutMap();
    if (zoom > 1) v.scrollTo(left() + x * canvas.offsetWidth - v.clientWidth / 2,
      y * canvas.offsetHeight - v.clientHeight / 2);
  }
  el('ampliar').addEventListener('click', () => scale(.25));
  el('reducir').addEventListener('click', () => scale(-.25));
  el('ajustar').addEventListener('click', () => { zoom = 1; layoutMap(); });
  el('completa').addEventListener('click', async () => {
    try {
      if (document.fullscreenElement === root) await document.exitFullscreen();
      else await root.requestFullscreen();
    } catch (_) { el('estado').textContent = 'El navegador no permite pantalla completa en esta ventana.'; }
  });
  document.addEventListener('fullscreenchange', () => {
    const active = document.fullscreenElement === root;
    el('completa').setAttribute('aria-pressed', String(active));
    el('completa').querySelector('span').textContent = active ? 'Salir de pantalla completa' : 'Pantalla completa';
    layoutMap();
  });
  new ResizeObserver(layoutMap).observe(el('visor'));
  window.addEventListener('resize', layoutMap);
  el('imagen').addEventListener('load', layoutMap);
  for (const symbol of root.querySelectorAll('.mapa-simbolo')) symbol.replaceChildren(kpiIcon('total'));
  layoutMap();
  el('imagen').addEventListener('error', () => { el('estado').textContent = 'No se pudo cargar el plano. Los vehículos siguen disponibles por zona.'; });
  document.addEventListener('visibilitychange', () => { clearTimeout(poll); if (!document.hidden) refresh(); });
  window.addEventListener('pagehide', () => clearTimeout(poll));
  setInterval(timers, 1000);
  refresh();
})();
