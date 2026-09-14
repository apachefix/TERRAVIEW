# Carga operacional DESPACHO SBH

Implementación acotada a EP=2, modal de Asistente Carga y Descarga.

## Alcance entregado

Antes, el modal consumía el detalle singular y preparaba una línea con un lote.
Ahora, la configuración tiene esta jerarquía normalizada:

```
CITACION_DESPACHO_CARGA (total operacional, zona, versión, usuario)
  CITACION_DESPACHO_ACUERDO_OPERACIONAL (AbsID, cantidad operacional)
    CITACION_DESPACHO_ACUERDO_ESTANQUE (Warehouse, un producto/línea, cantidad)
      CITACION_DESPACHO_ACUERDO_LOTE (batch, vencimiento, stock snapshot, cantidad)
    CITACION_DESPACHO_DRAFT_SAP (uno por acuerdo; estado PREPARADO)
```

La migración 0121 crea exclusivamente estas cinco tablas y sus restricciones.
No migra ni modifica datos históricos ni las filas CDAS de planificación.
La identidad del acuerdo es AbsID dentro de la citación; una fila CDAS no
equivale a un Draft. Varias líneas del mismo AbsID se agrupan en un acuerdo.

## Cantidades y compatibilidad

El total operacional es editable y se precarga desde el total singular anterior.
Las cantidades por acuerdo se ingresan explícitamente. No se suman automáticamente
las intenciones CDAS. Para 38700, el total inicial sigue siendo 100 y las cantidades
operacionales de los acuerdos 4092/429 y 3584/381 comienzan pendientes de distribución.

Se exige cantidad positiva con hasta cinco decimales y las igualdades lote→bloque,
bloque→acuerdo y acuerdo→total. Las unidades de las líneas deben coincidir; no hay
conversión inventada entre kg y toneladas. No se impone un bloqueo nuevo por saldo
comercial del contrato, que conserva la política de planificación existente.

El mismo producto puede provenir de distintos estanques. Se bloquea repetir la
misma combinación Warehouse/producto dentro del mismo acuerdo. El stock compartido
entre acuerdos se valida agregando todo el consumo por Warehouse/item/batch.

Sin asignaciones hijas se usa la representación legacy del detalle singular y se
precargan los datos operacionales antiguos disponibles. Los históricos que ya tienen
DocEntry singular conservan su circuito anterior. Abrir el modal no migra históricos.

## Lecturas SAP y FEFO

La configuración central resuelve CompanyDB para EP=2. En la verificación de QA fue
`SBO_TST_SBH_USD`. No se toma empresa, cliente ni schema desde el JSON del navegador.

`sap_despacho_carga.py` consulta OOAT/OAT1 por AbsID exacto, sin TOP 50 ni búsqueda
por número visible. Los productos se limitan a líneas abiertas del acuerdo activo.
El stock se obtiene de OBTQ y se enlaza con OBTN por ItemCode + SysNumber, y OWHS
por WhsCode. Se limita a stock positivo, lotes liberados y almacenes activos.

La fuente de vencimiento es **OBTN.ExpDate**, de tipo SAP DATE, formateada como
YYYY-MM-DD; no tiene hora ni timezone. Se compara con el día local Django. InDate
no se utiliza como vencimiento.

Referencia oficial:
https://help.sap.com/doc/089315d8d0f8475a9fc84fb919b501a3/10.0/en-US/SDKHelp/OBTN.html

FEFO ordena las fechas ascendentes y rechaza consumir un lote posterior sin agotar
los anteriores utilizables. Lotes vencidos no son utilizables. Empates de fecha
permiten elegir cualquiera. Sin fecha, la selección es manual; cuando hay mezcla,
los lotes sin fecha se habilitan después de agotar los fechados. El botón Distribuir
FEFO solo autocompleta lotes fechados. El backend vuelve a consultar stock/fechas y
revalida FEFO al guardar, ignorando snapshots manipulados del navegador.

La lectura QA de 980057 devolvió dos registros de stock sin vencimiento; 800040
también pudo consultarse. No se crearon registros de prueba para la citación 38700.

## Guardar y preparación SAP

Guardar usa el endpoint existente `/pla-citacion-estanque/<id>/` con el campo JSON
`carga_operacional`. Las consultas del modal usan el mismo GET con `catalogo_acuerdo`.
Se mantienen los permisos y condiciones de etapa existentes.

Guardar valida toda la estructura antes de persistirla dentro de una transacción.
Un bloqueo de la citación serializa escrituras y la versión rechaza formularios
obsoletos. Se conserva la identidad estable del acuerdo y del registro de Draft.
No se permite editar una carga con envíos iniciados, inciertos, fallidos o creados.

Se prepara un payload independiente por AbsID. Cada estanque/producto produce una
DocumentLine, con N BatchNumbers cuya suma coincide con Quantity. AgreementNo es
el AbsID interno entero (4092, no 429).

| Salida | DocObjectCode | ReserveInvoice |
|---|---|---|
| GD | 15 | campo ausente |
| FE | 13 | tNO |
| FE_RESERVA | 13 | tYES |

**No se ha conectado el envío real múltiple.** Guardar no invoca Service Layer.
Enviar siguiente etapa permanece deshabilitado y el backend responde 409 para la
carga nueva. El creador singular tampoco permite enviar solo el primer acuerdo.
Los payloads PREPARADO no se presentan como Drafts creados en SAP.

## Fase de envío pendiente

El modelo reserva estados PREPARADO, ENVIANDO, CREADO, ERROR e INCIERTO, una clave
estable por citación/acuerdo, DocEntry/DocNum, respuesta, error e intentos. Esto es
persistencia preparada, no una garantía de idempotencia distribuida ya implementada.

Antes de habilitar la creación real deben completarse el procesador/reintento por
acuerdo, la conciliación de respuestas inciertas y la distribución del peso final
entre Drafts. Si A se crea y B falla, el DocEntry de A debe conservarse y omitirse
en el reintento. Un timeout requiere conciliar SAP antes de reenviar; una clave local
no hace idempotente por sí misma al POST de Service Layer. No se propone borrar
documentos SAP ya creados como rollback.

El stock validado es un snapshot; no se reserva inventario SAP al preparar. Debe
reconsultarse antes de enviar. La fórmula de reparto del peso final no se inventó.
Operación Planta y Pesaje conservan su lógica anterior hasta validar esa adaptación.

## Verificación

Las pruebas Python de carga usan SQLite en memoria y mocks SAP, sin registros
persistentes QA. Cubren configuración, cantidades, FEFO, stock compartido, payloads,
rollback, versión, legacy, endpoints y aislamiento por empresa. La migración real se
aplicó al PostgreSQL local después de verificar que 0121 era la única pendiente.

Los tests JavaScript se ejecutan con:

```
node --test apps/home/tests/js/test_despacho_carga.js
```

Se comprueba también sintaxis JavaScript, compilación de templates Django,
`manage.py check` y `git diff --check`. La revisión visual queda a cargo del usuario;
no se usa navegador integrado.
