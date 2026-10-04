# Mapa operacional de planta

Auditoría realizada el 4 de octubre de 2026, entregada en el chat antes de editar código. La consulta de la BD configurada se hizo dentro de transacciones PostgreSQL `READ ONLY`. No se ejecutaron migraciones sobre ella ni se modificaron datos operacionales.

## Estado y límite físico

La función está integrada en `/dashboard_grafico/?_empresa_id=1` y `?_empresa_id=2`, con el mismo template, servicio y endpoint. El estado, colores, zonas lógicas y relojes se actualizan por polling. **Espera y carga/descarga ahora usan las coordenadas iniciales proporcionadas por el usuario**, detalladas debajo. Romana, Muestreo/Calidad independiente, Vapor y Portería siguen en el panel lateral. Las equivalencias físicas entre códigos de BD y TK siguen sin confirmar.

La imagen base y los dos rectángulos manuales permanecen visibles con cero camiones. `ESTANQUES_CONFIRMADOS` está deliberadamente vacío: no se activa posicionamiento automático por TK. Las referencias TK extraídas del PDF se conservan para una iteración posterior, sin dibujar nuevas etiquetas ni vincular camiones automáticamente.

## Iteración 2: coordenadas manuales y distribución

Configuración única: `apps/home/services/mapa_operacional_config.py`, entradas de `ZONAS.update(...)`. Los porcentajes corresponden a **la imagen completa**, con origen en la esquina superior izquierda. No dependen de resolución, zoom ni tamaño de pantalla.

| Zona | x_pct | y_pct | width_pct | height_pct |
|---|---:|---:|---:|---:|
| ZONA_ESPERA | 44 | 66 | 22 | 16 |
| ZONA_CARGA_DESCARGA | 45 | 37 | 21 | 18 |

Estos son los porcentajes finales usados en esta iteración, idénticos a los indicados por el usuario. Son posiciones iniciales, no una calibración física definitiva. El PDF/PNG disponible no contiene los rótulos «Zona de Espera», D/R ni el círculo rojo; se utiliza la referencia porcentual comunicada por el usuario. Chrome confirmó que los rectángulos conservan esas proporciones al redimensionar y ampliar. No se desplazaron para intentar reconstruir una referencia gráfica ausente.

Para corregir una zona: editar `x_pct` (distancia desde izquierda), `y_pct` (desde arriba), `width_pct` (ancho) y `height_pct` (alto); reiniciar el proceso web si no tiene recarga automática y recargar el navegador. No editar template/JS ni datos de la base. Los dos rectángulos son compartidos por las empresas 1 y 2. Las cantidades de columnas y slots también están centralizadas (`columnas`, `slots_por_tipo`).

Mapeo físico adicional en `ZONAS_FISICAS`, aplicado **después** del resolver existente y de `_zona_y_reloj`. `zona_operacional` conserva su valor para KPIs; `zona` selecciona el rectángulo. No se agregan consultas, timestamps, estados de workflow ni reglas basadas en textos visibles.

| Secuencias auditadas | Evidencia operacional existente | Ubicación |
|---|---|---|
| Recepción Terramar; recepción SBH estanque/trasvasije/patio; despacho SBH estanque/trasvasije/patio | `Ciclo Descarga` sin `OP_CICLO_DESCARGA.inicio_descarga` | ZONA_ESPERA |
| Recepción SBH con calidad | `Analisis y calidad` o `Resultado Calidad`, sin vapor activo | ZONA_ESPERA |
| Las mismas secuencias con `Ciclo Descarga` | `inicio_descarga` registrado, ciclo todavía activo | ZONA_CARGA_DESCARGA |
| Despacho Terramar | Paso activo `Ciclo Carga` | ZONA_CARGA_DESCARGA |
| Cualquier secuencia soportada | Romana, muestra, vapor, documentación, salida o categoría desconocida | Panel genérico existente |

Fuentes: inventarios CSV de esta auditoría, claves `OPL_CPASO` y resolver actual. «Inicio Carga» no se agrega como alias global: el despacho SBH auditado persiste `Ciclo Descarga`; Terramar persiste `Ciclo Carga`. Este último no expone un inicio independiente de carga en el modelo de lectura existente, por lo que se conserva la evidencia del paso activo. El vapor activo mantiene precedencia sobre la espera de calidad. El inventario CSV conserva las categorías operacionales originales; no se reescribe como si fueran ubicaciones físicas.

Distribución: cuatro slots D arriba y cuatro R abajo, ordenados por citación. Son posiciones visuales, no calles, andenes ni reservas. **Azul = despacho; verde = recepción**, tanto en plano como en panel. Más de cuatro por tipo se muestran en filas «Adicional» dentro del mismo rectángulo, con contador y desplazamiento independiente. Espera usa una cuadrícula de cuatro columnas con desplazamiento. Los botones de patentes conservan detalle y timer; no se duplican al cambiar de zona.

La vista conserva un ancho mínimo legible del plano y desplaza únicamente su visor en pantallas pequeñas. Los accesos «Ver zona de espera» y «Ver carga / descarga» centran la zona elegida; la primera carga enfoca carga/descarga. El zoom usa el tamaño del lienzo sin cambiar los porcentajes. Las patentes largas pueden envolver líneas para no invadir otra posición. No se ocultó la imagen base en estados vacíos, errores ni zonas sin coordenadas.

Validación de esta iteración:

- **42 pruebas Django correctas**: las 37 previas conservadas (aserciones de zona física adaptadas, manteniendo las operacionales) y 5 nuevas. Cubren las nueve secuencias, espera, calidad, carga, colores, KPIs, timestamps, imagen vacía y categorías sin posición. Ambas empresas mantienen **8 SELECT para 1 y 30 camiones**, incluyendo conjuntos con las zonas nuevas.
- `venv/Scripts/python.exe -m apps.home.tests.browser_mapa_operacional`: Chrome headless, URLs locales `/dashboard_grafico/?_empresa_id=1` y `2`, template y assets reales con respuestas sintéticas, sin acceso a BD. Comprueba 30 marcadores, colores CSS, slots, exceso de capacidad, patentes, ausencia de superposición, transiciones, retirada, cero camiones, panel genérico, errores de actualización y alineación porcentual en escritorio y móvil real emulado de 390 px. Sin errores JavaScript.
- Capturas: `tmp/mapa_zonas_empresa1_desktop.png`, `tmp/mapa_zonas_empresa2_desktop.png`, `tmp/mapa_zonas_empresa1_mobile.png`, `tmp/mapa_zonas_empresa2_mobile.png` y `tmp/mapa_zonas_empresa{1,2}_espera.png`.

La validación visual usa datos ficticios aislados; no acredita ubicación física de vehículos reales. No se modifica endpoint, polling, temporizadores, seguridad, KPIs ni base operacional. Sin migraciones nuevas, commit o push.

## Auditoría posterior: plano ausente en IIS

**Causa encontrada:** los assets nuevos estaban en `apps/static`, pero no en el directorio publicado `STATIC_ROOT = C:\Dev\TERRAVIEW\staticfiles`. La validación anterior servía los archivos fuente mediante un servidor aislado y no verificaba la publicación de `/static/` en IIS.

El template siempre incluye `<img id="mapa-imagen">`, sin condición Django sobre camiones. Usa `assets/plano/plantilla_planta.png`; `{% static %}` resuelve `/static/assets/plano/plantilla_planta.png`. El archivo fuente existe y pesa 456.702 bytes. El JS no crea, elimina ni oculta imagen/lienzo/visor según `camiones.length`: únicamente actualiza marcadores, contadores y paneles. Las coordenadas de las dos zonas se conservaron exactamente.

Corrección aplicada: publicación **solo** del PNG, CSS y JS del mapa en sus rutas equivalentes dentro de `staticfiles`; `mapa-operacional.css` añade `width: 100%` y `min-height: 400px` al visor. Se solicitó la recarga del proceso FastCGI mediante la marca temporal de los módulos WSGI/URLs existentes, sin cambios de contenido en esos módulos. No se cambia endpoint ni workflow.

Evidencia del servidor real, 4 de octubre de 2026:

| URL bajo https://terraview.terramar-group.com | HTTP | Content-Type | Bytes | Coincide con fuente |
|---|---:|---|---:|---|
| /static/assets/plano/plantilla_planta.png | 200 | image/png | 456702 | Sí, SHA-256 |
| /static/assets/css/mapa-operacional.css | 200 | text/css | 4161 | Sí, SHA-256 |
| /static/assets/js/mapa-operacional.js | 200 | text/javascript | 12167 | Sí, SHA-256 |

El binding HTTP `localhost` respondía 200 con HTML de «404 Error» y no es equivalente al binding HTTPS del sitio real. Se descartó ese 200 como prueba de carga. La evidencia final usa el hostname público y verifica MIME, contenido y decodificación en Chrome.

`venv/Scripts/python.exe -m apps.home.tests.browser_render_mapa` valida los templates de ambas empresas con respuesta vacía aislada; **PNG/CSS/JS se descargan del IIS real por HTTPS**. No inicia sesión ni modifica datos operacionales. La página autenticada del sitio real requiere la sesión del usuario; el documento del test es una fixture del template, no una sesión productiva.

Resultado Chrome: 0 marcadores, PNG 200 `image/png`, dimensiones naturales 1786×2526; imagen y padres con `display` visible, `visibility: visible`, `opacity: 1`, ancho/alto positivos; visor de 850 px (833 px útiles descontando bordes y scrollbar), dos zonas base visibles. La imagen permanece visible con lista de zonas vacía, fallo de endpoint y viewport móvil 390×844. Sin errores JavaScript.

Capturas con cero camiones: `tmp/mapa_render_vacio_empresa1.png` y `tmp/mapa_render_vacio_empresa2.png`. Auditoría DOM y respuestas de red de Chrome: `tmp/mapa_render_auditoria.json`.

Para futuras publicaciones, ejecutar el paso habitual `venv/Scripts/python.exe manage.py collectstatic --noinput --skip-checks` y recargar los workers después de incorporar assets nuevos, ya que WhiteNoise construye su catálogo al iniciar. `staticfiles` es salida de despliegue y está excluido de Git. En esta corrección se copiaron únicamente los tres assets del mapa para no publicar otros cambios pendientes. Una recarga forzada del navegador permite descartar las respuestas anteriores.

## Autorización actual: visualización para cualquier usuario autenticado

Regla confirmada por el usuario: cualquier usuario autenticado puede ver las empresas **1 y 2** desde el mapa, independientemente de perfil, pertenencia a empresa o secuencias operacionales asignadas. Esta excepción se aplica exclusivamente a las dos vistas del mapa.

Auditoría antes del ajuste:

| Punto | Validación anterior | Efecto |
|---|---|---|
| `views._empresa_mapa_operacional` | `usuario_es_operacion_planta(request.user)` debía ser verdadero | Usuarios con otros perfiles recibían `None` |
| Mismo helper | `usuario_tiene_empresa(request, empresa_id)` comprobaba `USERS_EMPRESA` | La empresa no asignada se rechazaba incluso para visualizar |
| `DASHBOARD_GRAFICO` | Helper devolvía `None` | HTML 403: «No tiene acceso al mapa de la empresa seleccionada.» |
| `DASHBOARD_GRAFICO_ESTADO` | Mismo helper | JSON 403: «Sin acceso a la empresa seleccionada.» |
| Endpoint JSON | `obtener_secuencias_asignadas_usuario` limitaba el servicio | Asignaciones operacionales podían ocultar procesos de la empresa visualizada |

Corrección en `apps/home/views.py`: el helper valida exclusivamente que la empresa seleccionada sea 1 o 2; ambas vistas lo reutilizan. Se eliminó el filtro de secuencias por usuario de este endpoint. El servicio mantiene intactos su aislamiento por empresa, secuencias soportadas, condiciones de actividad, zonas, KPIs, timestamps y 8 consultas. La selección no altera la empresa activa de sesión ni añade asignaciones.

`apps/home/urls.py` conserva `login_required` en **ambas** rutas. Sin login: redirección al login. Autenticado y empresa 1/2: 200 HTML/JSON. Otros métodos: 405, `Allow: GET`. Empresa inválida o fuera de 1/2: 400 con mensaje de selección inválida. Los helpers compartidos `usuario_es_operacion_planta`, `usuario_tiene_empresa`, `Verificar_empresa`, `usuario_puede_paso_operacion` y `obtener_secuencias_asignadas_usuario` no se modifican: los demás módulos continúan aplicando sus reglas actuales.

Validación: **46 pruebas correctas** con SQLite en memoria. Se cubren las cuatro combinaciones de empresa asignada/visualizada, los 13 perfiles indicados (incluido un perfil ajeno a operación), usuarios sin perfil/asignación, HTML/JSON y login, aislamiento de citaciones de ambas empresas, sesión sin cambios, métodos de escritura rechazados y consultas exclusivamente SELECT. Tras abrir el mapa de una empresa no asignada, el mismo usuario sigue sin pertenecer a ella, sin permiso de Operación Planta, con rechazo del guardado de pasos y de la administración de empresas. Se conservan las regresiones de flujo y las pruebas anteriores de colores, timers, zonas y coste constante.

No se modifica ningún permiso en BD, endpoint operacional, SAP, Proforma, Control Camión, Planificación ni Administración. Sin migraciones, commit o push.

## A–C. Implementación auditada y modelos

| Responsabilidad | Archivo / símbolo |
|---|---|
| URL existente | `apps/home/urls.py`, `dashboard_grafico` |
| Vista | `apps/home/views.py`, `DASHBOARD_GRAFICO` |
| Template | `apps/templates/home/HOME/monitor.html` |
| JavaScript anterior | `apps/static/assets/js/flat.js` |
| CSS anterior | `apps/static/assets/css/flat.css` |
| SQL anterior | `apps/home/general_postgres.py`, `get_list_zonas`, `get_citaciones_zonas` |
| Empresa/perfiles | `views.py`: `Verificar_empresa`, `usuario_tiene_empresa`, `usuario_es_operacion_planta`, `obtener_secuencias_asignadas_usuario`; `apps/home/context_processors.py` |
| Workflow | `views.py`: `obtener_pasos_operacion_citacion`, `resolver_estado_operacional_visible`, `obtener_paso_activo_operacion` |
| Fuente de modelos | `apps/home/models.py` |

El monitor tenía un canvas Konva de 1200×520, plano `assets/images/planoPlanta.png`, controles de edición de zonas y tabla de cupos; no otros gráficos. Cargaba jQuery, DataTables/exportadores, Bootstrap Slider, Feather y Konva de CDN. Refrescaba cupos/zonas cada 10 segundos, con llamadas por zona a `/get_camiones_zona` y lectura de `/obtener_zonas`, `/obtener_cupos_disponibles`, `/obtener_posiciones_zonas`. También invocaba endpoints de escritura: `/guardar_zona`, `/eliminar_zona`, `/actualizar_coordenadas_zona`, `/guardar_posicion_zona`, `/cambiar_imagen_plano`.

Se sustituyó la capa editable en este template por una capa HTML de lectura. Los archivos/endpoints antiguos no se alteraron. La tabla de capacidades se conserva, ahora con ocupación derivada del mismo conjunto del mapa y asociación técnica `ETAPA.ZON_NID`. Esas zonas históricas no se usan como coordenadas del PDF nuevo. No se añadieron dependencias de frontend.

Modelos inspeccionados: `CITACION`, `PLANIFICACION`, `SECUENCIA`, `DETALLE_SECUENCIA`, `ETAPA`, `ETAPA_LOG`, `OPERACION_PLANTA_LOG`, `SYSLOGGER`, `DATO_OPERACION`, `CAMPO`, `ZONA`, `ESTANQUE_RESERVA`, `RESULTADO_CALIDAD_OPERACION`, `CITACION_DETALLE_OPERACIONAL`, `CITACION_DESPACHO_DETALLE`, `CITACION_RECEPCION_TERRAMAR_DETALLE`, `CAMION`, `CONDUCTOR`, `CAMION_PATIO`, `USERS_EMPRESA` y perfiles. No se necesita modelo nuevo ni migración.

## D–F. Fuente de verdad, timestamps y actividad

`CITACION` guarda empresa, secuencia, tipo, estado, archivo e inicio/término. **No tiene FK de etapa actual**. Su propiedad `ETAPA_ACTUAL` toma el primer log técnico abierto; en su defecto el último finalizado y, si no hay logs, el detalle de paso 1. `ETAPA_SIGUIENTE` usa el número de paso del detalle. La propiedad original consulta por vehículo, por eso el mapa precarga detalles y logs y usa un adaptador de lectura que expone la misma etapa sin consultar.

Operación Planta no siempre coincide con esa etapa técnica: resuelve su paso visible usando la configuración de flujo, el conjunto de `OPL_CPASO` completados, la etapa técnica y el resultado de calidad. Terramar y despacho priorizan el primer paso pendiente; ciertas recepciones pueden priorizar su etapa técnica; calidad rechazada tiene precedencia según el resolver existente. El mapa llama a **ese mismo resolver**, añadiéndole únicamente un argumento opcional para suministrar calidad precargada. Las llamadas existentes conservan su comportamiento.

Una cita del mapa requiere: empresa, secuencia y planificación coherentes; citación habilitada y no archivada; planificación no archivada; sin fecha de término; tipo estructurado RECEPCION/DESPACHO; estado distinto de TERMINADO, RECHAZADO, ANULADO, CANCELADO, COMPLETADO/COMPLETADA y SALIDA_CONFIRMADA; evidencia de `SYSLOGGER.AUTORIZA_INGRESO_PLANTA` de la misma empresa; `Habilitar Operacion Planta` completado para la citación/planificación; sin `Confirmar Salida` completado. Se excluye también rechazo de calidad con cierre definitivo y flujos totalmente completados. No se consulta `CAMION_PATIO` para determinar actividad.

`OPERACION_PLANTA_LOG` no tiene SC_NID: su aislamiento disponible es citación + empresa + planificación. `ETAPA_LOG` y `DATO_OPERACION` sí se limitan a la secuencia actual. Etapas maestras compartidas entre empresas solo se leen a través del detalle válido de la secuencia de la citación; no permiten recuperar datos/logs de otra empresa.

Timestamps: inicio/fin de ciclo en `OP_CICLO_DESCARGA`, vapor en `OP_TOMA_MUESTRA_TIEMPO_VAPOR` o su acción original, análisis en `RCO_FINICIO`/`RCO_FDETENCION_TEMPORIZADOR`, documentación de despacho Terramar en `DESP_TERR_DOC_TEMPORIZADOR`. En ausencia de un inicio específico se utiliza el log técnico abierto si representa el mismo paso o la finalización del paso anterior/habilitación. No se usa un evento arbitrario más reciente ni la fecha de planificación para inventar un inicio. Sin evidencia: timestamp y duración nulos. El navegador incrementa solo los timers activos y los resincroniza con cada respuesta.

## G–H. Inventario y clasificación

[Inventario técnico CSV](mapa_operacional_inventario.csv): 486 detalles, separados por empresa, secuencia y paso, incluidos deshabilitados y eliminados. [Pasos operacionales y perfiles CSV](mapa_operacional_pasos.csv). [Snapshot JSON](mapa_operacional_inventario.json): 67 secuencias, detalles y configuraciones operacionales existentes. Los IDs corresponden a la BD auditada, no se usan como constantes universales de la aplicación.

Los detalles técnicos almacenan usuarios responsables en `USERS_RESPONSABLE_ID`, no una FK de perfil. Los perfiles operacionales están en los pares `(OPL_CPASO, perfiles)` de `FLUJOS_OPERACION_PLANTA` y `FLUJOS_DESPACHO_OPERACION_PLANTA`, incluidos íntegramente en el JSON. El CSV técnico incluye los perfiles actuales de los usuarios vinculados a cada detalle; estos no sustituyen al perfil responsable del paso operacional. No existe correspondencia uno a uno garantizada entre detalle técnico y paso operacional. Por ejemplo, despacho SBH persiste su carga como `Ciclo Descarga`, mientras Despacho Terramar usa `Ciclo Carga`. No se ha inventado una FK para unirlos.

| Empresa / secuencia | Pasos y clasificación |
|---|---|
| 1 / 74 RECEPCION_TERRAMAR | Pesaje Entrada→ROMANA; Ciclo Descarga→ESPERA/DESCARGA; Pesaje Salida→ROMANA; Documentación→DOCUMENTACION; Autorizar/Confirmar Salida→SALIDA |
| 1 / 76 DESPACHO_TERRAMAR | Pesaje Entrada→ROMANA; Ciclo Carga→CARGA; Pesaje Salida→ROMANA; Documentación→DOCUMENTACION; Autorizar/Confirmar Salida→SALIDA |
| 2 / 56 RECEPCION_ESTANQUE_SBH | Pesajes→ROMANA; Toma de muestra→MUESTREO/VAPOR; Analisis y calidad y Resultado Calidad→ESPERA_CALIDAD; Ciclo Descarga→ESPERA/DESCARGA; salida→SALIDA |
| 2 / 58 RECEPCION_TRASVASIJE | Configuración independiente; mismas categorías genéricas que recepción SBH con calidad |
| 2 / 59 RECEPCION_PATIO_LF_CON_CALIDAD | Configuración independiente; mismas categorías genéricas que recepción SBH con calidad |
| 2 / 60 RECEPCION_PATIO_LF_SIN_CALIDAD | Pesajes, espera/descarga y salida; no hereda calidad |
| 2 / 61 EST_SBH_CLIENTE | Pesajes→ROMANA; Ciclo Descarga→ESPERA/CARGA; Cierre Proceso de Carga→DOCUMENTACION; salida→SALIDA |
| 2 / 63 TRASVASIJE_CLIENTE | Configuración independiente; categorías de despacho SBH sin alias físicos heredados |
| 2 / 64 BODEGA_PATIO_CLIENTE | Configuración independiente; categorías de despacho SBH sin alias físicos heredados |

Se respeta la desactivación temporal de Borrador SAP/Emisión de documentos que ya aplica el workflow. El mapa no ejecuta esas acciones. Clave de configuración: `(empresa, SE_CCODIGO, CI_CTIPO)`. Overrides opcionales: `(empresa, SE_CCODIGO, ET_CCODIGO, OPL_CPASO)`. No hay reglas globales por `ET_CNOMBRE` ni estado de workflow nuevo.

## I–J. Estanques y base estática

Destino: `DATO_OPERACION` con campo `ETA3_ESTANQUE`, luego `CDO_CESTANQUE_DESTINO`, luego reserva ocupada; origen: `ACD_ESTANQUE_ORIGEN` o `CDO_CESTANQUE_ORIGEN`. Reserva incluye `ER_CALMACEN`/`ER_CESTANQUE`; detalle incluye `CDO_CALMACEN_DESTINO`. En despacho se usa `ACD_ZONA_CARGA` como contexto adicional y siempre se exige una equivalencia explícita por secuencia.

La BD auditada tiene TK01…TK17 y PROSE_G2, PROSE_T3/T4/T5. El código también ofrece PATIO_LF, TKMX01… y PROSEG10. El plano tiene TK-01…TK-12. Los candidatos TK01→TK-01, etc., necesitan confirmación física; TK13+, TKMX y PROSESA no tienen posición demostrada. No hay normalización que elimine prefijos y termine asociándolos accidentalmente.

PDF original: `apps/static/assets/plano/plantilla_planta.pdf`, una página de 1190,52×1683,72 puntos. PNG web: 1786×2526, aproximadamente 470 KB. El conversor trabaja sobre una copia en memoria, retira trazos vectoriales de vehículos contenidos en rectángulos revisados y subtrazos independientes de las cabinas, y conserva las coordenadas de página e infraestructura que cruza esos recortes. La imagen no se genera en peticiones web. Los rótulos TK se extraen a JSON porcentual. El PDF permanece intacto.

Regeneración offline: `venv/Scripts/python.exe manage.py generar_plano_operacional`. Revisar visualmente el PNG si cambia el PDF; el conversor verifica el SHA-256 del PDF auditado y rechaza estructuras de operaciones desconocidas. Los rectángulos de limpieza corresponden exclusivamente al PDF auditado.

## K–N. Arquitectura, seguridad y coste

Servicio `obtener_estado_mapa_operacional(empresa_id)` con consultas en bloque: citas/relaciones/Exists; detalles con etapas; logs técnicos; logs operacionales; datos; reservas; capacidades; nombre de empresa. Son **8 SELECT con un conjunto no vacío**, independientemente del número de camiones. Sin citas soportadas, hace 3. No Redis, caché global ni queries por KPI. Los pasos/logs/eventos de una cita se procesan en memoria.

Endpoint `GET /dashboard_grafico/estado/?_empresa_id=N`: cualquier usuario autenticado puede consultar N=1 o N=2, con `Cache-Control: no-store, private`. No exige perfil operacional, pertenencia `USERS_EMPRESA` ni secuencias asignadas. Otros métodos: 405. Empresa inválida/fuera del alcance: 400. No cambia la empresa de sesión durante el polling. La página HTML aplica exactamente la misma selección y ambas rutas mantienen `login_required`. Esta regla de visualización no se extiende a otros módulos.

Frontend: polling cada 15 s, timeout de 12 s, sin solicitudes solapadas, pausa al ocultar pestaña. Identidad por citacion_id: crea/mueve/retira el mismo botón; timers desde segundos del servidor, no desde el reloj del cliente. Fallos conservan la última lectura señalada como desactualizada; pérdida de acceso limpia los vehículos. DOM creado con textContent. Se mantienen nombres, color y selección al refrescar. Zonas con varios camiones usan lista con scroll y contador; las posiciones confirmadas se expresan en porcentajes ligados a la imagen. KPIs, detalle y cupos derivan del mismo JSON. El enlace apunta a la búsqueda de trazabilidad existente con `q` y empresa.

| Medición | Camiones | Consultas | Tiempo |
|---|---:|---:|---:|
| SQL inicial anterior, empresa 1 / PostgreSQL | 0 | 2 | 80,55 ms |
| SQL inicial anterior, empresa 2 / PostgreSQL | 0 | 2 | 4,56 ms |
| Servicio nuevo, empresa 1 / PostgreSQL READ ONLY | 0 | 3 | 71,79 ms |
| Servicio nuevo, empresa 2 / PostgreSQL READ ONLY | 0 | 3 | 11,65 ms |
| Servicio nuevo / SQLite aislado | 1 | 8 | Comprobado en test |
| Servicio nuevo / SQLite aislado | 30 | 8 | 11,60 ms |

Las medidas anteriores no suman todos los AJAX por zona del monitor anterior y no son un benchmark equivalente de carga real. Las cifras de SQLite no predicen latencia de PostgreSQL. La BD auditada contenía 33.244 TERMINADO/103 RECHAZADO en empresa 1 y 4.414 TERMINADO/8 RECHAZADO en empresa 2: no se crearon ni reabrieron citas allí para probar.

## O–S. Riesgos, archivos y alcance

Modificados: `apps/home/views.py`, `apps/home/urls.py`, `apps/templates/home/HOME/monitor.html`.

Creados: `apps/home/services/mapa_operacional.py`, `mapa_operacional_config.py`; `apps/static/assets/js/mapa-operacional.js`; `apps/static/assets/css/mapa-operacional.css`; `apps/home/management/commands/generar_plano_operacional.py`; PNG y `estanques_plano.json`; `apps/home/tests/test_mapa_operacional.py`, `run_mapa_operacional.py`; este informe y los inventarios CSV/JSON. La prueba visual y capturas están en `tmp/mapa_browser_check.py`, `tmp/mapa_desktop.png`, `tmp/mapa_mobile.png` (datos ficticios).

Fuera inicialmente: secuencias antiguas (incluidas 42 y 54 PROSESA); copias SBH 65–73 en empresa 1; bodega externa 57/62/66/71/75/77; transferencias 78/79; PROSESA 80/81; New Jersey 82–85; Servicio 86/87. Se contabilizan procesos activos fuera del alcance sin ubicarlos artificialmente en esta planta. Las salidas temporales a bodega externa justifican excluir esos flujos completos hasta validar sus períodos dentro/fuera.

Riesgos pendientes: calibración física; confirmación de alias; prueba en una operación real con usuario autorizado. Los logs operacionales carecen de SC_NID y dependen de que el workflow mantenga coherencia de citación/planificación. El servicio no modifica ni repara inconsistencias. No se invocan GET operacionales que inicializan calidad/timers ni callbacks SAP.

## Validación y prueba manual

`venv/Scripts/python.exe -m apps.home.tests.run_mapa_operacional` usa SQLite en memoria, con tablas creadas allí antes de importar formularios legacy. No usa ni migra la BD de `.env`. Resultado inicial: **37 tests correctos**, 20 nuevos y 17 regresiones existentes; **42 tras la iteración 2**; **46 tras el ajuste de autorización del mapa**. Cubre empresa, permisos, colores, archivos/estados cerrados, patio, salida, etapa técnica, transiciones, vapor, origen/destino, aislamiento, equivalencia con resolver, SELECT-only y coste constante. La comprobación SQL del polling falla ante cualquier sentencia que no sea SELECT.

Primera validación Chrome: 30 marcadores, 15 verdes/15 azules, detalle, traslado a zona porcentual, ausencia de duplicados, retiro al salir, estado desactualizado y responsive; sin errores JavaScript. Las capturas antiguas `tmp/mapa_desktop.png` y `tmp/mapa_mobile.png` usaban coordenadas de prueba. Las nuevas `tmp/mapa_zonas_*` usan las coordenadas centralizadas indicadas por el usuario, con vehículos ficticios. No se simularon avances en la BD real.

Procedimiento manual, con un proceso de prueba autorizado y existente:

1. Entrar con cualquier usuario autenticado y abrir empresa 1; repetir con empresa 2, incluso si no están asignadas al usuario. Página y JSON deben aceptar ambas y mantener separados sus datasets. Sin login, ambas rutas deben redirigir al login. Empresa fuera de 1/2: selección inválida.
2. Comprobar que una planificación sin ingreso y un registro solo en Patio no aparecen. Ingresar mediante el workflow habitual fuera del mapa.
3. Registrar en Operación Planta los pasos pertinentes: romana, muestra/calidad/vapor para SBH, carga/descarga, romana salida, documentación, salida. Esperar como máximo un polling tras cada transición.
4. En cada paso comprobar misma patente/citación, zona lógica, reloj persistente tras recarga, verde para recepción/azul para despacho y ausencia de duplicados. No debe aparecer ningún botón de avance/SAP en el mapa.
5. Seleccionar camión y comprobar detalles y trazabilidad. Finalizar mediante el workflow habitual: debe retirarse en el siguiente polling.
6. Probar varios camiones en la misma zona, pantalla estrecha, zoom, pestaña oculta y desconexión. Al volver, resincronizar; no mostrar una lectura antigua como vigente.
7. Con el responsable de planta, confirmar coordenadas/alias y completar únicamente `ZONAS`/`ESTANQUES_CONFIRMADOS` (o overrides de la secuencia correspondiente). Repetir transiciones y comprobar alineación al redimensionar antes de considerar validado el posicionamiento físico.

No commit, push, reset, clean ni descarte de cambios ajenos.

## Iteración visual: diseño aprobado (2026-10-04)

Referencia de composición: `apps/static/assets/plano/Panel operativo de planta Terraview.png`.
No se incorpora esa referencia al HTML ni se usa como fondo. La única imagen
base continúa siendo `/static/assets/plano/plantilla_planta.png` (1786 × 2526).

Se reorganiza exclusivamente la presentación: cabecera, siete tarjetas KPI
con iconos, herramientas, plano principal y panel lateral con leyenda, resumen
de zonas, lista de todos los camiones y detalle seleccionado. Los cupos siguen
disponibles en un desplegable inferior. Los contadores, la lista y el detalle
usan el JSON existente; no se añadieron endpoints ni consultas.

El ajuste inicial y Restablecer vista muestran toda la imagen, sin deformarla,
sin recortarla y sin desplazamiento interno del visor. El 100% indicado significa
ajuste al visor, no tamaño nativo. El zoom y los accesos a las zonas se activan
por acción del usuario. Pantalla completa utiliza la API del navegador.
En vista general los camiones se representan mediante iconos seleccionables;
al ampliar se muestran las patentes y timers dentro de las zonas. La lista
lateral conserva siempre patente, tipo, zona/etapa y tiempo. El detalle aparece
primero en el panel para poder consultarlo sin perder el plano en escritorio.

Coordenadas sin cambios, sobre la imagen completa:

| Zona | x | y | ancho | alto |
|---|---:|---:|---:|---:|
| ZONA_ESPERA | 44% | 66% | 22% | 16% |
| ZONA_CARGA_DESCARGA | 45% | 37% | 21% | 18% |

Romana, espera salida y portería se identifican como sin posición; los estanques
mantienen su asociación pendiente. No se agregaron coordenadas ni equivalencias.
El resumen de calidad usa su KPI existente aunque los camiones estén agrupados
físicamente en ZONA_ESPERA.

Diferencias deliberadas respecto de la referencia:

- Se conserva la proporción vertical real del plano, por lo que aparecen márgenes
  laterales al ajustarlo a un escritorio horizontal. No se reproduce el recorte
  horizontal ni las posiciones ilustrativas de la referencia.
- Se conserva la navegación y cabecera global vigente de TERRAVIEW; no se
  modifica el estilo de otros módulos.
- Las patentes, números y nombres son datos del endpoint, nunca los ejemplos
  dibujados en la referencia. El estado indica la última actualización del mapa,
  sin afirmar disponibilidad de todo el sistema.
- En pantallas pequeñas el panel pasa debajo; en escritorio puede desplazarse
  cuando su contenido supera el alto disponible.

Archivos de esta iteración: `apps/templates/home/HOME/monitor.html`,
`apps/static/assets/css/mapa-operacional.css`,
`apps/static/assets/js/mapa-operacional.js`,
`apps/home/tests/browser_mapa_ux.py` y este documento.
Se sincronizan únicamente el CSS/JS correspondientes en `staticfiles/assets/`,
porque IIS sirve esa carpeta, y el template versiona sus URLs para evitar caché
de la presentación anterior.

Validación:

- 46 pruebas Django existentes aprobadas con SQLite en memoria; 8 consultas
  para 1 y 30 camiones, incluyendo ambas empresas. Sin acceso a la BD operacional.
- `browser_mapa_operacional`: dos escenarios Chrome existentes aprobados,
  conservando movimientos de zona, slots, colores, vacío y estado desactualizado.
- `browser_mapa_ux`: seis escenarios, empresas 1/2 × 1920×1080, 1366×768 y
  390×844. Renderiza el template Django completo y sus estilos de navegación
  contra una BD de prueba en memoria. El JSON contiene vehículos sintéticos;
  se aíslan los scripts de otros módulos para no ejecutar acciones externas.
  Comprueba 0/30 camiones, fit sin scroll, leyenda/panel, colores, selección por
  lista y mapa, timers, limpieza de sesión y fallos de red. En escritorio grande
  verifica además polling real de 15 segundos y la API de pantalla completa.
- `browser_render_mapa`: dos escenarios con 0 camiones y recursos reales de
  IIS; PNG HTTP 200, dimensiones correctas, zonas base visibles, lista vacía de
  zonas, fallo del endpoint y móvil.
- CSS, JS y PNG devueltos por IIS: HTTP 200 y bytes iguales a sus fuentes locales.

Capturas con datos ficticios: `tmp/mapa_ux_empresa{1,2}_{1920,1366,390}.png`,
sus variantes `_vacio.png` y `tmp/mapa_ux_empresa{1,2}_detalle.png`.
Resultado estructurado: `tmp/mapa_ux_validacion.json`.

No se cambia lógica operacional, autorización, filtrado multiempresa, reglas
de secuencias, cálculo de timers, polling, ni número de consultas. No se generan
migraciones ni se modifican datos operacionales. No commit ni push.
