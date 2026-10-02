// Pruebas de comportamiento JavaScript sin navegador ni dependencias externas.
const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

function harness(stockRows) {
    const nodes = new Map();
    const node = selector => {
        if (!nodes.has(selector)) nodes.set(selector, {
            markup: '', handlers: {}, properties: {},
            html(s) { this.markup = s; return this; },
            text(s) { this.message = s; return this; },
            prop(k, v) { this.properties[k] = v; return this; },
            addClass() { return this; }, removeClass() { return this; }, hide() { this.hidden = true; return this; },
            toggle(value) { this.hidden = !value; return this; },
            off() { this.handlers = {}; return this; },
            on(event, selector, handler) { this.handlers[event] = handler || selector; return this; }
        });
        return nodes.get(selector);
    };
    const $ = input => typeof input === 'string' ? node(input) : input;
    const product = {linea_acuerdo:'1', item_code:'P', item_name:'Producto', unidad_medida:'Ton'};
    $.getJSON = async () => ({success:true, productos:[product], stocks:{P:stockRows}});
    let submitted = null;
    $.ajax = async opts => {
        submitted = JSON.parse(opts.data.carga_operacional);
        return {success:true, datos_guardados:true, puede_avanzar:true,
            carga_operacional:{...submitted, guardado:true, puede_avanzar:true}, message:'Guardado'};
    };
    const context = vm.createContext({$, escapeHtml: s => String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/"/g,'&quot;'), renderRevisionDocuments: () => ''});
    vm.runInContext(fs.readFileSync('apps/templates/home/PLANIFICACION/despacho_carga_js.html','utf8') + '\nglobalThis.api = cargaSbh;', context);
    const block = {warehouse_code:'TK', item_code:'P', linea_acuerdo:'1', cantidad:'60', lotes:[]};
    const response = {citacion_id:1, carga_operacional:{version:0,hoy:'2026-01-01',zona_carga:'Línea 1',cantidad_total:'60', acuerdos:[
        {sap_abs_id:4092,numero_acuerdo:'429',cantidad:'60',cliente_nombre:'Cliente',estanques:[block]}]}};
    const click = key => {
        const el = {closest(selector) { return {attr: () => '0'}; }, is(selector) { return selector === key; }};
        node('#sbh_carga').handlers['click.sbh'].call(el);
    };
    const change = (key, value) => {
        const el = {
            closest(selector) { return {attr: () => '0'}; },
            is(selector) { return selector === key; },
            val() { return value; },
            attr() { return ''; },
        };
        node('#sbh_carga').handlers['change.sbh'].call(el);
    };
    return {api:context.api,response,node,click,change,submitted:() => submitted};
}

const row = (batch, stock, fecha) => ({warehouse_code:'TK',item_code:'P',batch_number:batch,stock,fecha_vencimiento:fecha});

test('catálogo muestra TK04 y TKMX01 y TK04 conserva sus lotes', async () => {
    const stocks = [
        {warehouse_code:'TK04',item_code:'P',batch_number:'LOTE-PT-980057-6-01',stock:70,fecha_vencimiento:null},
        {warehouse_code:'TK04',item_code:'P',batch_number:'LOTE-PT-980057-7-01',stock:270,fecha_vencimiento:null},
        {warehouse_code:'TKMX01',item_code:'P',batch_number:'LOTE-PT-980057-4-01',stock:80.25,fecha_vencimiento:null},
    ];
    const h = harness(stocks);
    await h.api.mount(h.response,true);
    assert.match(h.node('#sbh_carga').markup, /TK04/);
    assert.match(h.node('#sbh_carga').markup, /TKMX01/);
    h.change('[data-warehouse]', 'TK04');
    h.change('[data-product]', '1');
    const html = h.node('#sbh_carga').markup;
    assert.match(html, /LOTE-PT-980057-6-01/);
    assert.match(html, /LOTE-PT-980057-7-01/);
    assert.doesNotMatch(html, /LOTE-PT-980057-4-01/);
});

test('FEFO distribuye 20 + 40 y guarda múltiples lotes', async () => {
    const h = harness([row('C',100,'2099-03-01'),row('B',50,'2099-02-01'),row('A',20,'2099-01-01')]);
    await h.api.mount(h.response,true);
    h.click('[data-fefo]'); await h.api.save();
    assert.deepEqual(h.submitted().acuerdos[0].estanques[0].lotes,
        [{batch_number:'A',cantidad:'20'},{batch_number:'B',cantidad:'40'}]);
    assert.equal(h.node('#btn_enviar_estanque').properties.disabled,false);
});

test('no autoselecciona lotes sin fecha', async () => {
    const h = harness([row('A',20,null),row('B',100,null)]);
    await h.api.mount(h.response,true); h.click('[data-fefo]'); await h.api.save();
    assert.deepEqual(h.submitted().acuerdos[0].estanques[0].lotes,[]);
});

test('no permite eliminar último estanque y conserva jerarquía', async () => {
    const h = harness([row('A',100,null)]);
    await h.api.mount(h.response,true); h.click('[data-remove]'); await h.api.save();
    assert.equal(h.submitted().acuerdos[0].estanques.length,1);
    const html = h.node('#sbh_carga').markup;
    assert.ok(html.indexOf('Estanque / Warehouse') < html.indexOf('Producto SAP del acuerdo'));
    assert.ok(html.indexOf('Producto SAP del acuerdo') < html.indexOf('<th>Lote</th>'));
    assert.ok(!html.includes('acd_numero_bach'));
});

test('agrega y elimina segundo estanque', async () => {
    const h = harness([row('A',100,null)]);
    await h.api.mount(h.response,true); h.click('[data-add]'); await h.api.save();
    assert.equal(h.submitted().acuerdos[0].estanques.length,2);
    h.click('[data-remove]'); await h.api.save();
    assert.equal(h.submitted().acuerdos[0].estanques.length,1);
});

test('modal no editable no guarda', async () => {
    const h = harness([row('A',100,null)]);
    await h.api.mount(h.response,false); await h.api.save();
    assert.equal(h.submitted(),null);
    assert.equal(h.node('#btn_guardar_estanque').properties.disabled,true);
});

test('cambios posteriores al guardado vuelven a bloquear el avance', async () => {
    const h = harness([row('A',100,'2099-01-01')]);
    await h.api.mount(h.response,true);
    h.click('[data-fefo]'); await h.api.save();
    assert.equal(h.node('#btn_enviar_estanque').properties.disabled,false);
    h.click('[data-add]');
    assert.equal(h.node('#btn_enviar_estanque').properties.disabled,true);
    assert.equal(h.api.status().cambios_pendientes,true);
});
test('dos acuerdos 20 + 7.5 quedan habilitados después del POST exitoso', async () => {
    const h = harness([row('A',100,'2099-01-01')]);
    h.response.carga_operacional.cantidad_total = '27.5';
    h.response.carga_operacional.acuerdos = [
        {sap_abs_id:4138,numero_acuerdo:'433',cantidad:'20',cliente_nombre:'Cliente',
            estanques:[{warehouse_code:'TK',item_code:'P',linea_acuerdo:'1',cantidad:'20',lotes:[{batch_number:'A',cantidad:'20'}]}]},
        {sap_abs_id:4062,numero_acuerdo:'426',cantidad:'7.5',cliente_nombre:'Cliente',
            estanques:[{warehouse_code:'TK',item_code:'P',linea_acuerdo:'1',cantidad:'7.5',lotes:[{batch_number:'A',cantidad:'7.5'}]}]},
    ];
    await h.api.mount(h.response,true);
    await h.api.save();
    assert.equal(h.submitted().acuerdos.reduce((sum, a) => sum + Number(a.cantidad), 0), 27.5);
    const status = h.api.status();
    assert.equal(status.cantidad_total,'27.5');
    assert.equal(status.distribuido,'27.5');
    assert.equal(status.pendiente,'0');
    assert.equal(status.guardado,true);
    assert.equal(status.puede_avanzar,true);
    assert.equal(status.cambios_pendientes,false);
    assert.equal(status.acuerdos_validos,2);
    assert.equal(status.cargas_persistidas,1);
    assert.equal(status.disabled,false);
    assert.equal(h.node('#btn_enviar_estanque').properties.disabled,false);
});
test('doble click queda bloqueado durante el envío SAP', async () => {
    const h = harness([row('A',100,'2099-01-01')]);
    await h.api.mount(h.response,true);
    h.click('[data-fefo]'); await h.api.save();
    assert.equal(h.api.beginSend(),true);
    assert.equal(h.api.beginSend(),false);
    assert.equal(h.node('#btn_enviar_estanque').properties.disabled,true);
    assert.equal(h.node('#btn_enviar_estanque').message,'Enviando a SAP...');
    h.api.endSend();
    assert.equal(h.node('#btn_enviar_estanque').properties.disabled,false);
});
test('reintento SAP habilitado aunque la distribución quede bloqueada para edición', async () => {
    const h = harness([row('A',100,'2099-01-01')]);
    h.response.carga_operacional.guardado = true;
    h.response.carga_operacional.puede_avanzar = true;
    await h.api.mount(h.response,false);
    assert.equal(h.node('#btn_guardar_estanque').properties.disabled,true);
    assert.equal(h.node('#btn_enviar_estanque').properties.disabled,false);
});

test('preview solo se muestra con flag y carga guardada sin cambios pendientes', async () => {
    const h = harness([row('A',100,'2099-01-01')]);
    h.response.sap_despacho_preview_enabled = false;
    h.response.carga_operacional.guardado = true;
    h.response.carga_operacional.puede_avanzar = true;
    await h.api.mount(h.response,true);
    assert.equal(h.node('#btn_preview_borrador_sap_despacho_carga').hidden,true);
    h.response.sap_despacho_preview_enabled = true;
    await h.api.mount(h.response,true);
    assert.equal(h.node('#btn_preview_borrador_sap_despacho_carga').hidden,false);
    assert.equal(h.node('#btn_preview_borrador_sap_despacho_carga').properties.disabled,false);
    h.change('[data-total]', '61');
    assert.equal(h.node('#btn_preview_borrador_sap_despacho_carga').properties.disabled,true);
});
