// Dimensiones fijas del plano (basadas en la imagen original 1600x694)
const PLANO_WIDTH_FIJO = 1200;
const PLANO_HEIGHT_FIJO = 520;

// Inicializar el stage de Konva con dimensiones fijas
const stage = new Konva.Stage({
    container: 'container',
    width: PLANO_WIDTH_FIJO,
    height: PLANO_HEIGHT_FIJO
});

// Crear una capa para el plano
const layer = new Konva.Layer();

// Variable para controlar si la imagen está cargada
let isImageLoaded = false;

// IMPORTANTE: Variable global para mantener referencia a la imagen del plano
let planoImageObj = null;
// Variable para controlar si ya se inicializó el plano
let planoInicializado = false;

// Colocar la función aquí, a nivel global
function calcularColor(cuposOcupados, cuposMaximos) {
    // Convertir a números y asegurar valores no negativos
    cuposOcupados = Math.max(0, Number(cuposOcupados));
    cuposMaximos = Math.max(1, Number(cuposMaximos));

    // Validar que cuposMaximos no sea 0
    if (cuposMaximos === 0) {
        console.warn('Cupos máximos no puede ser 0, usando 1 como valor por defecto');
        cuposMaximos = 1;
    }

    // Calcular el porcentaje y limitarlo a 100%
    const porcentaje = Math.min(100, (cuposOcupados / cuposMaximos) * 100);

    // Asignar colores basados en el porcentaje de ocupación
    if (porcentaje <= 40) {
        return {
            fill: '#bbed7f',    // Verde claro
            stroke: '#5a7a3d'   // Verde oscuro
        };
    } else if (porcentaje <= 80) {
        return {
            fill: '#facf55',    // Amarillo claro
            stroke: '#b38f24'   // Amarillo oscuro
        };
    } else {
        return {
            fill: '#f34226',    // Rojo claro
            stroke: '#a12213'   // Rojo oscuro
        };
    }
}

function cargarImagenPlano(rutaImagen = null) {
    // Intentar múltiples rutas en orden de prioridad
    const rutasPosibles = [
        '/static/assets/images/planoPlanta.png',
        '/static/assets/images/planoPlanta.PNG', // Mayúsculas
        'static/assets/images/planoPlanta.png',   // Sin barra inicial
        '/apps/static/assets/images/planoPlanta.png',
        '/media/planoPlanta.png'  // Ruta alternativa
    ];
    
    // Si se proporciona una ruta específica, usarla primero
    if (rutaImagen) {
        rutasPosibles.unshift(rutaImagen);
    }
    
    console.log('Iniciando carga de imagen del plano...');
    console.log('Rutas a intentar:', rutasPosibles);
    
    // Función para probar una ruta
    function probarRuta(index) {
        if (index >= rutasPosibles.length) {
            console.error('No se pudo cargar la imagen desde ninguna ruta');
            mostrarErrorImagen();
            return;
        }
        
        const rutaActual = rutasPosibles[index];
        console.log(`Intentando cargar imagen desde: ${rutaActual}`);
        
        // Crear nueva imagen con timestamp para evitar caché
        const timestamp = Date.now();
        const rutaConTimestamp = rutaActual.includes('?') 
            ? `${rutaActual}&cache_bust=${timestamp}` 
            : `${rutaActual}?cache_bust=${timestamp}`;
        
        const imageObj = new Image();
        imageObj.crossOrigin = 'anonymous';
        
        imageObj.onload = function() {
            console.log(`✅ Imagen cargada exitosamente desde: ${rutaActual}`);
            console.log(`Dimensiones originales: ${this.width}x${this.height}`);
            console.log(`Dimensiones fijas del plano: ${PLANO_WIDTH_FIJO}x${PLANO_HEIGHT_FIJO}`);
            
            isImageLoaded = true;
            
            // Buscar si ya existe una imagen en la capa
            const imagenExistente = layer.findOne('Image');
            
            if (imagenExistente) {
                console.log('Actualizando imagen existente');
                imagenExistente.image(imageObj);
                imagenExistente.width(PLANO_WIDTH_FIJO);
                imagenExistente.height(PLANO_HEIGHT_FIJO);
                imagenExistente.moveToBottom();
            } else {
                console.log('Creando nueva imagen Konva');
                planoImageObj = new Konva.Image({
                    x: 0,
                    y: 0,
                    image: imageObj,
                    width: PLANO_WIDTH_FIJO,
                    height: PLANO_HEIGHT_FIJO,
                    name: 'plano-imagen'
                });

                layer.add(planoImageObj);
                planoImageObj.moveToBottom();
                
                if (layer.getStage() === null) {
                    stage.add(layer);
                }

                if (!planoInicializado) {
                    if (!document.querySelector('.toolbar')) {
                        crearToolbar();
                    }
                    configurarZoomYPanFijo();
                    window.marker_list_zonas = window.marker_list_zonas || [];
                    
                    if (typeof zonas !== 'undefined' && zonas.length === 0) {
                        cargarZonasDesdeServidor();
                    }
                    planoInicializado = true;
                }
            }
            
            layer.batchDraw();
            console.log('✅ Proceso de carga de imagen completado exitosamente');
        };

        imageObj.onerror = function(e) {
            console.warn(`❌ Error al cargar imagen desde: ${rutaActual}`);
            console.log('Detalles del error:', e);
            
            // Intentar la siguiente ruta
            setTimeout(() => probarRuta(index + 1), 100);
        };

        // Iniciar carga
        imageObj.src = rutaConTimestamp;
    }
    
    // Comenzar con la primera ruta
    probarRuta(0);
}

// Función para mostrar error cuando no se puede cargar ninguna imagen
function mostrarErrorImagen() {
    console.error('No se pudo cargar la imagen del plano desde ninguna ubicación');
    
    // Mostrar un mensaje en el plano
    const textoError = new Konva.Text({
        x: PLANO_WIDTH_FIJO / 2,
        y: PLANO_HEIGHT_FIJO / 2,
        text: 'Error: No se pudo cargar la imagen del plano\nVerifique la configuración de archivos estáticos',
        fontSize: 16,
        fontFamily: 'Arial',
        fill: '#ff0000',
        align: 'center',
        offsetX: 200, // Centrar horizontalmente
        offsetY: 20   // Centrar verticalmente
    });
    
    layer.add(textoError);
    
    if (layer.getStage() === null) {
        stage.add(layer);
    }
    
    layer.batchDraw();
    
    // También mostrar alerta
    if (typeof Swal !== 'undefined') {
        Swal.fire({
            icon: 'error',
            title: 'Error al cargar imagen',
            text: 'No se pudo cargar la imagen del plano. Verifique la configuración de archivos estáticos en IIS.',
            confirmButtonText: 'Aceptar'
        });
    } else {
        alert('Error: No se pudo cargar la imagen del plano. Verifique la configuración de archivos estáticos.');
    }
}

window.addEventListener('resize', () => {
    // Las dimensiones del stage se mantienen fijas
    // Solo centramos el contenedor si es necesario
    centrarContenedorPlano();
});

function configurarZoomYPanFijo() {
    const scaleBy = 1.1;
    const minScale = 0.3; // Permitir más zoom out
    const maxScale = 5;   // Zoom in más controlado

    stage.on('wheel', (e) => {
        e.evt.preventDefault();
        const oldScale = stage.scaleX();

        // Calcular nueva escala
        let newScale = e.evt.deltaY > 0 ? oldScale / scaleBy : oldScale * scaleBy;

        // Aplicar límites
        newScale = Math.max(minScale, Math.min(maxScale, newScale));

        // Si la nueva escala es igual a la anterior, no hacer nada
        if (newScale === oldScale) {
            return;
        }

        const pointer = stage.getPointerPosition();
        const mousePointTo = {
            x: (pointer.x - stage.x()) / oldScale,
            y: (pointer.y - stage.y()) / oldScale,
        };

        const newPos = {
            x: pointer.x - mousePointTo.x * newScale,
            y: pointer.y - mousePointTo.y * newScale,
        };

        stage.scale({ x: newScale, y: newScale });
        stage.position(newPos);

        // Ajustar el tamaño de los puntos de camiones
        stage.find('.punto-camion').forEach(punto => {
            const nuevoRadio = Math.min(4, 4 / newScale);
            const nuevoStroke = Math.min(0.5, 0.5 / newScale);
            
            punto.radius(nuevoRadio);
            punto.strokeWidth(nuevoStroke);
        });

        stage.batchDraw();
    });

    // Habilitar arrastre del plano
    stage.draggable(true);
}

// NUEVA función para centrar el contenedor del plano
function centrarContenedorPlano() {
    const container = document.getElementById('container');
    const containerParent = container.parentElement;
    
    if (containerParent) {
        // Calcular si necesitamos centrar horizontalmente
        const parentWidth = containerParent.clientWidth;
        
        if (parentWidth > PLANO_WIDTH_FIJO) {
            // Centrar horizontalmente si el contenedor padre es más ancho
            const margenIzquierdo = (parentWidth - PLANO_WIDTH_FIJO) / 2;
            container.style.marginLeft = margenIzquierdo + 'px';
            container.style.marginRight = margenIzquierdo + 'px';
        } else {
            // Remover márgenes si no hay espacio
            container.style.marginLeft = '0px';
            container.style.marginRight = '0px';
        }
    }
}

// NUEVA función para convertir coordenadas del mundo real a coordenadas del plano fijo
function coordenadasRealesAPlano(lat, lng) {
    // Esta función convierte coordenadas de latitud/longitud a coordenadas del plano fijo
    // Ajusta estos valores según tu sistema de coordenadas específico
    
    const isLatLong = Math.abs(lat) > 0 && Math.abs(lat) < 90;
    
    if (isLatLong) {
        // Conversión para coordenadas geográficas
        const x = (Math.abs(lat + 36.95) * 10000) + 100;
        const y = (Math.abs(lng + 73.15) * 10000) + 100;
        
        // Escalar a las dimensiones fijas del plano
        const xPlano = (x / 10000) * PLANO_WIDTH_FIJO;
        const yPlano = (y / 10000) * PLANO_HEIGHT_FIJO;
        
        return { x: xPlano, y: yPlano };
    } else {
        // Las coordenadas ya están en formato de píxeles
        // Escalar proporcionalmente a las dimensiones fijas
        const factorEscalaX = PLANO_WIDTH_FIJO / 1600; // 1600 es el ancho original
        const factorEscalaY = PLANO_HEIGHT_FIJO / 694;  // 694 es el alto original
        
        return {
            x: lat * factorEscalaX,
            y: lng * factorEscalaY
        };
    }
}

// NUEVA función para convertir coordenadas del plano a coordenadas reales para guardar
function coordenadasPlanoAReales(x, y) {
    // Convertir de coordenadas del plano fijo a coordenadas reales para guardar en BD
    const factorEscalaX = 1600 / PLANO_WIDTH_FIJO; // Factor inverso
    const factorEscalaY = 694 / PLANO_HEIGHT_FIJO;  // Factor inverso
    
    return {
        x: x * factorEscalaX,
        y: y * factorEscalaY
    };
}


// Función para obtener la posición del puntero considerando la escala (VERSIÓN ACTUALIZADA)
function getPointerPosition() {
    const pos = stage.getPointerPosition();
    if (!pos) return null;
    
    const scale = stage.scaleX();
    return {
        x: (pos.x - stage.x()) / scale,
        y: (pos.y - stage.y()) / scale
    };
}

function crearNuevaZonaConDimensionesFijas(zonaData, planoScale = null, planoOffset = null) {
    const NOMBRE = 0;
    const CUPOS_OCUPADOS = 13;
    const CUPOS_MAXIMOS = 14;
    const ID_ZONA = 15;

    const colorZona = calcularColor(zonaData[CUPOS_OCUPADOS], zonaData[CUPOS_MAXIMOS]);
    const idZona = parseInt(zonaData[ID_ZONA]);

    // Procesar coordenadas usando el sistema fijo
    const points = [];
    
    for (let i = 1; i <= 8; i++) {
        const coord = zonaData[i];
        let coordNum = (typeof coord === 'number') 
            ? coord 
            : (typeof coord === 'string' && coord.trim() !== '') 
                ? parseFloat(coord) 
                : 0;

        if (coordNum !== 0) {
            if (i % 2 === 1) {
                // Coordenada X - convertir a coordenadas del plano fijo
                const coordPlano = coordenadasRealesAPlano(coordNum, 0);
                points.push(coordPlano.x);
            } else {
                // Coordenada Y - convertir a coordenadas del plano fijo
                const coordPlano = coordenadasRealesAPlano(0, coordNum);
                points.push(coordPlano.y);
            }
        } else {
            points.push(0);
        }
    }

    // Verificar puntos válidos
    let puntosDefined = 0;
    for (let i = 0; i < points.length; i += 2) {
        if (points[i] !== 0 || points[i+1] !== 0) {
            puntosDefined++;
        }
    }
    
    if (puntosDefined < 3) {
        console.log(`Zona ${zonaData[NOMBRE]} no tiene suficientes puntos válidos`);
        return null;
    }

    // Crear elementos de la zona
    const grupoZona = new Konva.Group({ 
        draggable: false, 
        name: `grupo-${zonaData[NOMBRE]}`, 
        listening: true,
        perfectDrawEnabled: false
    });
    
    const zona = new Konva.Line({
        points: points,
        closed: true,
        fill: colorZona.fill,
        stroke: colorZona.stroke,
        strokeWidth: 3,
        opacity: 0.5,
        name: zonaData[NOMBRE],
        id_zona: idZona,
        draggable: false,
        hitStrokeWidth: 20,
        listening: true,
        perfectDrawEnabled: false,
        shadowForStrokeEnabled: false
    });

    // Crear puntos de control reutilizando del pool
    const puntosControl = [];
    for (let i = 0; i < points.length; i += 2) {
        const control = obtenerPuntoControlDelPool();
        control.x(points[i]);
        control.y(points[i + 1]);
        control.name(`control-${i/2}`);
        puntosControl.push(control);
    }

    // Obtener tooltip del pool
    const tooltip = obtenerTooltipDelPool();
    
    // Actualizar contenido del tooltip
    const tooltipText = tooltip.findOne('Text');
    const cuposOcupados = zonaData[CUPOS_OCUPADOS] || 0;
    const cuposMaximos = zonaData[CUPOS_MAXIMOS] || 0;
    const cuposLibres = cuposMaximos - cuposOcupados;
    
    tooltipText.text(
        `${zonaData[NOMBRE]}\nCupos ocupados: ${cuposOcupados}\nCupos máximos: ${cuposMaximos}\nCupos libres: ${cuposLibres}`
    );

    // Configurar eventos de la zona
    configurarEventosZona(zona, tooltip, zonaData[NOMBRE]);

    // Añadir click event
    zona.on('click', function() {
        zonaClick(idZona);
    });

    // Ensamblar elementos
    grupoZona.add(zona);
    puntosControl.forEach(control => {
        grupoZona.add(control);
    });

    layer.add(grupoZona);
    layer.add(tooltip);

    // Crear objeto de retorno
    const zonaObj = {
        grupoZona,
        zona,
        tooltip,
        puntosControl,
        nombre: zonaData[NOMBRE],
        id: zonaData[ID_ZONA]
    };

    return zonaObj;
}

// Función para cargar zonas desde el servidor
function cargarZonasDesdeServidor(callback = null) {
    console.log('Cargando zonas desde el servidor...');
    cargarPosicionesGuardadas(callback);
}
// Variables para el modo de dibujo
let dibujandoZona = false;
let puntosTemporales = [];
let lineaTemporalZona = null;
let puntoTemporal = null;
let zonaSeleccionada = null;
let puntosControl = [];
let herramientaActiva = null;
let zonas = [];
let marcadores = [];
// Global variables for zone data
let zoneData = {};
let refreshInterval = null;
// Variable global para controlar el modal activo
let modalActivo = false;
// Variables globales para el sistema de edición por toolbar
let modoEdicionToolbar = false;
let zonaSeleccionadaEdicion = null;
let coordenadasOriginalesEdicion = null;
let toolbarOriginal = null;
// Variables globales para el sistema de mover zonas
let modoMoverZona = false;
let zonaSeleccionadaMover = null;
let coordenadasOriginalesMover = null;
let posicionInicialMover = null;
// Variables globales para el sistema de eliminar zonas
let modoEliminarZona = false;
let zonaSeleccionadaEliminar = null;
// Variables para cache de camiones (agregar si no existe)
let cacheCamionesZona = new Map();
let ultimaActualizacionCamiones = new Map();

// Variables globales para optimización

let poolPuntosControl = [];
let poolTooltips = [];

// Pool de objetos reutilizables
function obtenerPuntoControlDelPool() {
    if (poolPuntosControl.length > 0) {
        const punto = poolPuntosControl.pop();
        punto.visible(false);
        punto.draggable(false);
        return punto;
    }
    return new Konva.Circle({
        radius: 3,
        fill: '#ffffff',
        stroke: '#00ff00',
        strokeWidth: 2,
        draggable: false,
        visible: false,
        opacity: 1,
        listening: false,
        perfectDrawEnabled: false
    });
}

function obtenerTooltipDelPool() {
    if (poolTooltips.length > 0) {
        const tooltip = poolTooltips.pop();
        tooltip.visible(false);
        return tooltip;
    }
    
    const tooltip = new Konva.Label({ 
        x: 0, 
        y: 0, 
        opacity: 0.9, 
        visible: false,
        listening: false,
        perfectDrawEnabled: false
    });
    
    tooltip.add(new Konva.Tag({
        fill: '#fff',
        stroke: '#e0e0e0',
        strokeWidth: 1,
        cornerRadius: 4,
        shadowColor: 'black',
        shadowBlur: 10,
        shadowOffset: { x: 2, y: 2 },
        shadowOpacity: 0.2,
        pointerDirection: 'down',
        pointerWidth: 10,
        pointerHeight: 10
    }));

    tooltip.add(new Konva.Text({
        text: '',
        fontFamily: 'Arial',
        fontSize: 14,
        padding: 8,
        fill: '#333',
        align: 'center'
    }));
    
    return tooltip;
}

function devolverObjetosAlPool(zonaObj) {
    // Devolver puntos de control al pool
    zonaObj.puntosControl.forEach(punto => {
        punto.off(); // Limpiar eventos
        poolPuntosControl.push(punto);
    });
    
    // Devolver tooltip al pool
    if (zonaObj.tooltip) {
        zonaObj.tooltip.off(); // Limpiar eventos
        poolTooltips.push(zonaObj.tooltip);
    }
}

function handleKeyDown(e) {
    if (e.key === 'Escape') {
        console.log('Cancelando dibujo');
        cancelarDibujoZona();
    }
}

let isDragging = false;
let lastPointerPosition = null;

function handleMouseDown(e) {
    if (e.evt.shiftKey) {
        isDragging = true;
        lastPointerPosition = stage.getPointerPosition();
    }
}

function handleMouseMoveDrag(e) {
    if (!isDragging) return;

    const newPointerPosition = stage.getPointerPosition();
    if (!newPointerPosition || !lastPointerPosition) return;

    const dx = newPointerPosition.x - lastPointerPosition.x;
    const dy = newPointerPosition.y - lastPointerPosition.y;

    stage.x(stage.x() + dx);
    stage.y(stage.y() + dy);
    lastPointerPosition = newPointerPosition;
    stage.batchDraw();
}

function handleMouseUp() {
    isDragging = false;
}

// Función para limpiar todos los eventos de las zonas
function limpiarEventosZonas() {
    // Si hay una zona en edición desde toolbar, finalizarla
    if (modoEdicionToolbar && zonaSeleccionadaEdicion) {
        finalizarEdicionToolbar();
        return; // Salir temprano para evitar conflictos
    }
    
    // Si hay una zona en movimiento desde toolbar, finalizarla
    if (modoMoverZona && zonaSeleccionadaMover) {
        finalizarMovimientoToolbar();
        return; // Salir temprano para evitar conflictos
    }
    
    // Si hay una zona en eliminación desde toolbar, finalizarla
    if (modoEliminarZona && zonaSeleccionadaEliminar) {
        finalizarEliminacionToolbar();
        return; // Salir temprano para evitar conflictos
    }
    
    zonas.forEach(({ grupoZona, zona, tooltip, puntosControl }) => {
        // Limpiar todos los eventos existentes
        grupoZona.off('dragstart');
        grupoZona.off('dragmove');
        grupoZona.off('dragend');
        grupoZona.off('mousedown');
        grupoZona.off('mouseover');
        grupoZona.off('mouseout');
        
        zona.off('mousedown');
        
        // Limpiar eventos específicos de todos los modos
        zona.off('.seleccion');
        zona.off('.mover');
        zona.off('.eliminar');
        grupoZona.off('.mover');
        
        // Asegurar que no esté en modo arrastrable
        grupoZona.draggable(false);
        
        // Restaurar el evento de click solo si la zona tiene un ID válido
        if (zona.attrs.id_zona && !isNaN(zona.attrs.id_zona)) {
            zona.off('click');
            zona.on('click', function() {
                // Solo permitir click normal si no estamos en ningún modo especial
                if (!modoEdicionToolbar && !modoMoverZona && !modoEliminarZona) {
                    zonaClick(zona.attrs.id_zona);
                }
            });
        }
        
        // Restaurar estilos y propiedades
        zona.strokeWidth(3);
        zona.opacity(0.5);
        
        // Restaurar colores originales
        const idZona = zona.attrs.id_zona;
        if (idZona) {
            const zonaData = obtenerDatosZona(idZona);
            if (zonaData) {
                const color = calcularColor(zonaData.ocupados, zonaData.maximos);
                zona.stroke(color.stroke);
                zona.fill(color.fill);
            }
        }
        
        // Ocultar puntos de control
        puntosControl.forEach(control => {
            control.visible(false);
            control.draggable(false);
            control.off('dragmove.edicionToolbar');
        });

        // Restablecer eventos de tooltip con throttling
        configurarEventosZona(zona, tooltip, zona.name());
    });
    layer.batchDraw();
}

// Función para crear la barra de herramientas (modificada)
function crearToolbar() {
    // Eliminar la barra de herramientas existente si existe
    const existingToolbar = document.querySelector('.toolbar');
    if (existingToolbar) {
        existingToolbar.remove();
    }

    const toolbar = document.createElement('div');
    toolbar.className = 'toolbar';

    // Guardar referencia para restaurar después
    toolbarOriginal = toolbar;

    crearBotonesToolbarNormal(toolbar);

    // Añadir la barra de herramientas al contenedor
    const container = document.getElementById('container');
    container.appendChild(toolbar);

    // Inicializar los iconos de Feather
    feather.replace();
}

// Función para crear botones normales de la toolbar
function crearBotonesToolbarNormal(toolbar) {
    const botones = [
        { 
            icon: 'edit-2', 
            titulo: '', 
            accion: 'delimitar',
            descripcion: 'Dibuja el perímetro de una nueva zona'
        },
        {
            icon: 'plus-square',
            titulo: '',
            accion: 'agregarZona',
            descripcion: 'Agregar zona desde lista'
        },
        { 
            icon: 'move', 
            titulo: '', 
            accion: 'mover',
            descripcion: 'Mueve una zona existente'
        },
        {
            icon: 'tool',
            titulo: '',
            accion: 'editarPredefinidas',
            descripcion: 'Editar zonas predefinidas'
        },
        { 
            icon: 'trash-2', 
            titulo: '', 
            accion: 'eliminar',
            descripcion: 'Elimina la zona seleccionada'
        },
        // {
        //     icon: 'image',
        //     titulo: '',
        //     accion: 'cambiarImagen',
        //     descripcion: 'Cambiar imagen del plano'
        // }
    ];

    botones.forEach(boton => {
        const button = document.createElement('button');
        button.className = 'tool-button';
        button.innerHTML = `
            <i data-feather="${boton.icon}"></i>
            <span class="tool-tip">${boton.descripcion}</span>
        `;
        button.title = boton.titulo;
        
        button.addEventListener('click', () => {
            manejarClickBotonNormal(boton, button, toolbar);
        });

        toolbar.appendChild(button);
    });

    // Crear un separador visual antes del botón de total
    const separator = document.createElement('div');
    separator.style.width = '100%';
    separator.style.height = '1px';
    separator.style.backgroundColor = '#e0e0e0';
    separator.style.margin = '5px 0';

    // Crear el botón de total de camiones
    const totalCamionesBtn = document.createElement('div');
    totalCamionesBtn.className = 'tool-button total-camiones';
    totalCamionesBtn.innerHTML = `
        <i data-feather="truck"></i>
        <span class="total-count">0</span>
        <span class="tool-tip">Total de camiones en planta</span>
    `;
    totalCamionesBtn.style.cursor = 'default';
    totalCamionesBtn.style.pointerEvents = 'none';

    // Añadir el separador y el botón de total de camiones después de los otros botones
    toolbar.appendChild(separator);
    toolbar.appendChild(totalCamionesBtn);
}


// Función para manejar clicks en botones normales
function manejarClickBotonNormal(boton, button, toolbar) {
    // Manejar el nuevo botón de agregar zona
    if (boton.accion === 'agregarZona') {
        mostrarListaZonasDisponibles(button);
        return;
    }

    // Si es el botón de editar zonas predefinidas
    if (boton.accion === 'editarPredefinidas') {
        iniciarModoEdicionToolbar();
        return;
    }

    // Si es el botón de mover zona
    if (boton.accion === 'mover') {
        iniciarModoMoverToolbar();
        return;
    }

    // Si es el botón de eliminar zona
    if (boton.accion === 'eliminar') {
        iniciarModoEliminarToolbar();
        return;
    }

    // Si es el botón de cambiar imagen
    if (boton.accion === 'cambiarImagen') {
        mostrarModalCambiarImagen();
        return;
    }

    // Resto de la lógica existente para otros botones...
    // Si el botón ya está activo, desactivarlo
    if (button.classList.contains('active') && herramientaActiva === boton.accion) {
        button.classList.remove('active');
        herramientaActiva = null;
        stage.container().style.cursor = 'default';
        
        // Desactivar todas las funciones
        cancelarDibujoZona();
        limpiarEventosZonas();

        // Restablecer los eventos por defecto para cada zona
        zonas.forEach(({ zona, tooltip, nombre }) => {
            // Eliminar todos los eventos del modo eliminar
            zona.off('.eliminar');
            
            // Restablecer los eventos por defecto
            configurarEventosZona(zona, tooltip, nombre);
        });
        
        layer.batchDraw();
        return;
    }
    
    // Desactivar el botón anterior si existe
    const botonAnterior = toolbar.querySelector('.active');
    if (botonAnterior) {
        botonAnterior.classList.remove('active');
    }
    
    // Activar el nuevo botón
    button.classList.add('active');
    
    // Cambiar la herramienta activa
    herramientaActiva = boton.accion;
    
    // Cerrar cualquier modal abierto
    const existingModal = document.getElementById('modal-data-camiones');
    if (existingModal) {
        existingModal.remove();
    }
    
    // Ajustar el cursor y comportamiento según la herramienta
    switch(boton.accion) {
        case 'delimitar':
            stage.container().style.cursor = 'crosshair';
            cancelarDibujoZona();
            iniciarDibujoZona();
            limpiarEventosZonas();
            break;
    }
}

function mostrarModalCambiarImagen() {
    console.log('Mostrando modal para cambiar imagen del plano');
    
    // Crear el modal
    const modal = document.createElement('div');
    modal.id = 'modal-cambiar-imagen';
    modal.className = 'modal fade show';
    modal.style.cssText = `
        display: block;
        background-color: rgba(0, 0, 0, 0.5);
        z-index: 9999;
        overflow-y: auto;
        max-height: 100vh;
        padding: 20px 0;
    `;
    modal.innerHTML = `
        <div class="modal-dialog modal-dialog-centered" style="max-width: 600px; margin: auto;">
            <div class="modal-content" style="max-height: 90vh; display: flex; flex-direction: column;">
                <div class="modal-header" style="flex-shrink: 0;">
                    <h5 class="modal-title">
                        <i class="fas fa-image me-2"></i>
                        Cambiar Imagen del Plano
                    </h5>
                    <button type="button" class="close" data-dismiss="modal" aria-label="Close">
                        <span aria-hidden="true">&times;</span>
                    </button>
                </div>
                <div class="modal-body" style="overflow-y: auto; flex: 1; padding: 20px;">
                    <div class="form-group">
                        <label for="nuevaImagen" class="form-label">
                            <strong>Seleccionar nueva imagen del plano:</strong>
                        </label>
                        <input 
                            type="file" 
                            class="form-control-file" 
                            id="nuevaImagen" 
                            accept="image/*"
                            style="margin-bottom: 15px;"
                        >
                        <small class="form-text text-muted">
                            Formatos soportados: JPG, PNG, GIF. Tamaño máximo: 10MB
                        </small>
                    </div>
                    
                    <!-- Vista previa -->
                    <div id="vista-previa" style="display: none; margin-top: 15px;">
                        <label class="form-label"><strong>Vista previa:</strong></label>
                        <div style="border: 1px solid #ddd; padding: 10px; border-radius: 4px; max-height: 400px; overflow: auto;">
                            <img id="imagen-preview" style="max-width: 100%; height: auto; display: block; margin: 0 auto; max-height: 300px;">
                        </div>
                        <div id="info-imagen" style="margin-top: 10px; font-size: 12px; color: #666;"></div>
                    </div>
                    
                    <!-- Advertencia -->
                    <div class="alert alert-warning mt-3" role="alert">
                        <i class="fas fa-exclamation-triangle me-2"></i>
                        <strong>Advertencia:</strong> Cambiar la imagen del plano puede afectar las posiciones de las zonas existentes. Se recomienda hacer una copia de seguridad antes de proceder.
                    </div>
                </div>
                <div class="modal-footer" style="flex-shrink: 0;">
                    <button type="button" class="btn btn-secondary" id="btn-cancelar-imagen">
                        <i class="fas fa-times me-1"></i>
                        Cancelar
                    </button>
                    <button type="button" class="btn btn-primary" id="btn-cambiar-imagen" disabled>
                        <i class="fas fa-upload me-1"></i>
                        Cambiar Imagen
                    </button>
                </div>
            </div>
        </div>
    `;

    // Añadir el modal al body
    document.body.appendChild(modal);

    // Referencias a elementos del modal
    const inputImagen = modal.querySelector('#nuevaImagen');
    const vistaPrevia = modal.querySelector('#vista-previa');
    const imagenPreview = modal.querySelector('#imagen-preview');
    const infoImagen = modal.querySelector('#info-imagen');
    const btnCambiar = modal.querySelector('#btn-cambiar-imagen');
    const btnCancelar = modal.querySelector('#btn-cancelar-imagen');
    const btnCerrar = modal.querySelector('.close');

    // Función para cerrar el modal
    const cerrarModal = () => {
        modal.remove();
    };

    // Función para ocultar modal antes de mostrar Swal
    const ocultarModalTemporalmente = () => {
        modal.style.display = 'none';
    };

    // Función para mostrar modal después de cerrar Swal
    const mostrarModalNuevamente = () => {
        if (document.body.contains(modal)) {
            modal.style.display = 'block';
        }
    };

    // Event listeners
    btnCancelar.addEventListener('click', cerrarModal);
    btnCerrar.addEventListener('click', cerrarModal);
    modal.addEventListener('click', (e) => {
        if (e.target === modal) cerrarModal();
    });

    // Prevenir scroll del body cuando se hace scroll en el modal
    modal.addEventListener('scroll', (e) => {
        e.stopPropagation();
    });

    // Manejar selección de archivo
    inputImagen.addEventListener('change', (e) => {
        const archivo = e.target.files[0];
        
        if (!archivo) {
            vistaPrevia.style.display = 'none';
            btnCambiar.disabled = true;
            return;
        }

        // Validar tipo de archivo
        if (!archivo.type.startsWith('image/')) {
            ocultarModalTemporalmente();
            Swal.fire({
                icon: 'error',
                title: 'Tipo de archivo inválido',
                text: 'Por favor selecciona un archivo de imagen válido.',
                confirmButtonText: 'Aceptar',
                zIndex: 10000
            }).then(() => {
                mostrarModalNuevamente();
            });
            inputImagen.value = '';
            return;
        }

        // Validar tamaño (10MB máximo)
        const maxSize = 10 * 1024 * 1024; // 10MB
        if (archivo.size > maxSize) {
            ocultarModalTemporalmente();
            Swal.fire({
                icon: 'error',
                title: 'Archivo muy grande',
                text: 'El archivo no puede ser mayor a 10MB.',
                confirmButtonText: 'Aceptar',
                zIndex: 10000
            }).then(() => {
                mostrarModalNuevamente();
            });
            inputImagen.value = '';
            return;
        }

        // Mostrar vista previa
        const reader = new FileReader();
        reader.onload = (e) => {
            imagenPreview.src = e.target.result;
            vistaPrevia.style.display = 'block';
            btnCambiar.disabled = false;

            // Mostrar información del archivo
            const tamañoMB = (archivo.size / (1024 * 1024)).toFixed(2);
            infoImagen.innerHTML = `
                <strong>Nombre:</strong> ${archivo.name}<br>
                <strong>Tamaño:</strong> ${tamañoMB} MB<br>
                <strong>Tipo:</strong> ${archivo.type}
            `;

            // Obtener dimensiones de la imagen
            imagenPreview.onload = () => {
                const width = imagenPreview.naturalWidth;
                const height = imagenPreview.naturalHeight;
                infoImagen.innerHTML += `<br><strong>Dimensiones:</strong> ${width} x ${height} px`;
            };
        };
        reader.readAsDataURL(archivo);
    });

    // Manejar clic en cambiar imagen
    btnCambiar.addEventListener('click', () => {
        const archivo = inputImagen.files[0];
        if (!archivo) return;

        // Ocultar modal antes de mostrar confirmación
        ocultarModalTemporalmente();

        // Mostrar confirmación
        Swal.fire({
            title: '¿Estás seguro?',
            text: 'Esto cambiará la imagen del plano. Las zonas existentes mantendrán sus posiciones.',
            icon: 'question',
            showCancelButton: true,
            confirmButtonColor: '#007bff',
            cancelButtonColor: '#6c757d',
            confirmButtonText: 'Sí, cambiar imagen',
            cancelButtonText: 'Cancelar',
            zIndex: 10000
        }).then((result) => {
            if (result.isConfirmed) {
                cambiarImagenPlano(archivo);
                cerrarModal();
            } else {
                mostrarModalNuevamente();
            }
        });
    });

    // Manejar tecla ESC para cerrar
    const handleEscape = (e) => {
        if (e.key === 'Escape') {
            cerrarModal();
            document.removeEventListener('keydown', handleEscape);
        }
    };
    document.addEventListener('keydown', handleEscape);

    // Limpiar event listener al cerrar
    modal.addEventListener('remove', () => {
        document.removeEventListener('keydown', handleEscape);
    });

    // Inicializar iconos si usas Font Awesome
    if (typeof feather !== 'undefined') {
        feather.replace();
    }
}

// FUNCIÓN CORREGIDA para cambiar imagen del plano
function cambiarImagenPlano(archivo) {
    console.log('Cambiando imagen del plano...');
    
    // Mostrar indicador de carga con z-index alto
    Swal.fire({
        title: 'Cambiando imagen del plano...',
        text: 'Por favor espera mientras se procesa la nueva imagen',
        allowOutsideClick: false,
        allowEscapeKey: false,
        showConfirmButton: false,
        zIndex: 10000,
        willOpen: () => {
            Swal.showLoading();
        }
    });

    // Crear FormData para enviar el archivo
    const formData = new FormData();
    formData.append('imagen', archivo);
    formData.append('csrfmiddlewaretoken', getCsrfToken());

    // Enviar imagen al servidor
    $.ajax({
        url: '/cambiar_imagen_plano',
        method: 'POST',
        data: formData,
        processData: false,
        contentType: false,
        cache: false, // Importante: desactivar caché de la petición
        success: function(response) {
            console.log('Respuesta del servidor:', response);
            
            if (response.success) {
                console.log('Imagen cambiada exitosamente:', response.nueva_ruta);
                console.log('Timestamp recibido:', response.timestamp);
                console.log('Info de imagen:', response.info_imagen);
                
                // Delay más largo para asegurar que el archivo esté completamente guardado
                setTimeout(() => {
                    // Actualizar la imagen en el plano
                    actualizarImagenEnPlano(response.nueva_ruta);
                    
                    // Mostrar mensaje de éxito con información adicional
                    let textoExito = 'La imagen del plano ha sido actualizada correctamente.';
                    if (response.info_imagen && response.info_imagen.ancho) {
                        textoExito += `\n\nDimensiones: ${response.info_imagen.ancho}x${response.info_imagen.alto}px`;
                        textoExito += `\nTamaño: ${(response.info_imagen.tamaño_bytes / 1024 / 1024).toFixed(2)} MB`;
                    }
                    
                    Swal.fire({
                        icon: 'success',
                        title: '¡Imagen cambiada!',
                        text: textoExito,
                        confirmButtonText: 'Aceptar',
                        zIndex: 10000
                    });
                }, 1000); // Delay de 1 segundo
                
            } else {
                console.error('Error del servidor:', response.error);
                Swal.fire({
                    icon: 'error',
                    title: 'Error',
                    text: 'Error al cambiar la imagen: ' + (response.error || 'Error desconocido'),
                    confirmButtonText: 'Aceptar',
                    zIndex: 10000
                });
            }
        },
        error: function(xhr, status, error) {
            console.error('Error en la petición AJAX:');
            console.error('Status:', status);
            console.error('Error:', error);
            console.error('Response:', xhr.responseText);
            
            let mensajeError = 'Error al cambiar la imagen. ';
            
            // Proporcionar mensajes más específicos según el error
            if (xhr.status === 413) {
                mensajeError += 'El archivo es muy grande.';
            } else if (xhr.status === 415) {
                mensajeError += 'Tipo de archivo no soportado.';
            } else if (xhr.status === 500) {
                mensajeError += 'Error interno del servidor.';
            } else if (xhr.status === 0) {
                mensajeError += 'Error de conexión. Verifique su conexión a internet.';
            } else {
                mensajeError += 'Por favor, intente nuevamente.';
            }
            
            Swal.fire({
                icon: 'error',
                title: 'Error de conexión',
                text: mensajeError,
                confirmButtonText: 'Aceptar',
                zIndex: 10000
            });
        }
    });
}

function getCsrfToken() {
    // Método 1: Desde cookies
    let cookieValue = null;
    if (document.cookie && document.cookie !== '') {
        const cookies = document.cookie.split(';');
        for (let i = 0; i < cookies.length; i++) {
            const cookie = cookies[i].trim();
            if (cookie.substring(0, 10) === 'csrftoken=') {
                cookieValue = decodeURIComponent(cookie.substring(10));
                break;
            }
        }
    }
    
    // Método 2: Desde meta tag (si existe)
    if (!cookieValue) {
        const csrfMeta = document.querySelector('meta[name="csrf-token"]');
        if (csrfMeta) {
            cookieValue = csrfMeta.getAttribute('content');
        }
    }
    
    // Método 3: Desde input hidden (si existe)
    if (!cookieValue) {
        const csrfInput = document.querySelector('input[name="csrfmiddlewaretoken"]');
        if (csrfInput) {
            cookieValue = csrfInput.value;
        }
    }
    
    if (!cookieValue) {
        console.warn('No se pudo obtener el token CSRF');
    }
    
    return cookieValue;
}

function limpiarCacheImagen() {
    // Limpiar caché de Service Workers si están disponibles
    if ('serviceWorker' in navigator) {
        navigator.serviceWorker.getRegistrations().then(registrations => {
            registrations.forEach(registration => {
                registration.update();
            });
        });
    }
    
    // Limpiar caché de imágenes en memoria
    if ('caches' in window) {
        caches.keys().then(names => {
            names.forEach(name => {
                if (name.includes('static') || name.includes('assets') || name.includes('images')) {
                    caches.delete(name);
                    console.log('Cache eliminado:', name);
                }
            });
        });
    }
}

function actualizarImagenEnPlano(nuevaRuta) {
    console.log('=== INICIO ACTUALIZACIÓN IMAGEN ===');
    console.log('Nueva ruta:', nuevaRuta);
    console.log('Estado del layer:', layer);
    console.log('Elementos en layer:', layer.getChildren().length);
    
    // Limpiar caché del navegador para la imagen anterior
    const timestamp = Date.now();
    const rutaConTimestamp = nuevaRuta.includes('?') 
        ? `${nuevaRuta}&cache_bust=${timestamp}` 
        : `${nuevaRuta}?cache_bust=${timestamp}`;
    
    console.log('Ruta con cache bust:', rutaConTimestamp);
    
    // Buscar la imagen actual en la capa
    const imagenActual = layer.findOne('Image');
    console.log('Imagen encontrada:', imagenActual ? 'SÍ' : 'NO');
    
    if (imagenActual) {
        console.log('Imagen actual encontrada, procediendo a actualizar...');
        
        // Crear nueva imagen con cache busting
        const nuevaImagen = new Image();
        nuevaImagen.crossOrigin = 'anonymous';
        
        // Manejar la carga exitosa
        nuevaImagen.onload = function() {
            console.log('=== NUEVA IMAGEN CARGADA ===');
            console.log(`Dimensiones: ${this.width}x${this.height}`);
            
            try {
                // Actualizar la imagen de Konva
                imagenActual.image(nuevaImagen);
                
                // Mantener las dimensiones fijas
                imagenActual.width(PLANO_WIDTH_FIJO);
                imagenActual.height(PLANO_HEIGHT_FIJO);
                
                // Asegurar posición
                imagenActual.x(0);
                imagenActual.y(0);
                
                // Mover al fondo
                imagenActual.moveToBottom();
                
                console.log('Imagen actualizada, redibujando...');
                
                // Múltiples redraws para asegurar actualización
                imagenActual.getLayer().batchDraw();
                layer.batchDraw();
                stage.batchDraw();
                
                // Forzar repaint después de delay
                setTimeout(() => {
                    layer.batchDraw();
                    stage.batchDraw();
                    console.log('=== ACTUALIZACIÓN COMPLETADA ===');
                }, 200);
                
            } catch (error) {
                console.error('Error al actualizar imagen Konva:', error);
                // Fallback: recargar completamente
                console.log('Intentando recarga completa...');
                cargarImagenPlano(rutaConTimestamp);
            }
        };
        
        // Manejar errores de carga
        nuevaImagen.onerror = function() {
            console.error('Error al cargar nueva imagen desde:', rutaConTimestamp);
            
            // Intentar sin cache busting
            console.log('Reintentando sin cache busting...');
            const imagenFallback = new Image();
            imagenFallback.crossOrigin = 'anonymous';
            
            imagenFallback.onload = function() {
                console.log('Imagen fallback cargada');
                imagenActual.image(imagenFallback);
                imagenActual.width(PLANO_WIDTH_FIJO);
                imagenActual.height(PLANO_HEIGHT_FIJO);
                imagenActual.moveToBottom();
                layer.batchDraw();
            };
            
            imagenFallback.onerror = function() {
                console.error('Fallback también falló');
                Swal.fire({
                    icon: 'error',
                    title: 'Error al cargar imagen',
                    text: 'No se pudo cargar la nueva imagen. Intente nuevamente.',
                    confirmButtonText: 'Aceptar',
                    zIndex: 10000
                });
            };
            
            imagenFallback.src = nuevaRuta;
        };
        
        // Cargar la nueva imagen
        console.log('Iniciando carga de nueva imagen...');
        nuevaImagen.src = rutaConTimestamp;
        
    } else {
        console.log('No se encontró imagen existente, creando nueva...');
        // Forzar recarga completa si no hay imagen
        cargarImagenPlano(nuevaRuta);
    }
}

// Función para iniciar el modo de edición desde toolbar
function iniciarModoEdicionToolbar() {
    console.log('Iniciando modo edición desde toolbar');
    
    modoEdicionToolbar = true;
    herramientaActiva = 'editandoZona';
    
    // Cambiar la toolbar a modo edición
    crearToolbarEdicion();
    
    // Configurar las zonas para ser seleccionables
    configurarZonasParaSeleccion();
    
    // Cambiar cursor
    stage.container().style.cursor = 'pointer';
    
    // Mostrar mensaje informativo
    mostrarMensajeInformativo('Haz clic en una zona para editarla');
}

// REEMPLAZAR la función limpiarCacheCamiones existente para manejar variables no definidas:

// Función para limpiar cache periódicamente (versión corregida)
function limpiarCacheCamiones() {
    // Verificar que las variables existan antes de usarlas
    if (typeof cacheCamionesZona === 'undefined') {
        cacheCamionesZona = new Map();
    }
    if (typeof ultimaActualizacionCamiones === 'undefined') {
        ultimaActualizacionCamiones = new Map();
    }
    
    const ahora = Date.now();
    const tiempoExpiracion = 30000; // 30 segundos
    
    for (const [idZona, datos] of cacheCamionesZona.entries()) {
        if (ahora - datos.timestamp > tiempoExpiracion) {
            cacheCamionesZona.delete(idZona);
            ultimaActualizacionCamiones.delete(idZona);
        }
    }
}


// Función para iniciar el modo de eliminar desde toolbar
function iniciarModoEliminarToolbar() {
    console.log('Iniciando modo eliminar desde toolbar');
    
    modoEliminarZona = true;
    herramientaActiva = 'eliminandoZona';
    
    // Cambiar la toolbar a modo eliminar
    crearToolbarEliminar();
    
    // Configurar las zonas para ser seleccionables para eliminar
    configurarZonasParaEliminar();
    
    // Cambiar cursor
    stage.container().style.cursor = 'pointer';
    
    // Mostrar mensaje informativo
    mostrarMensajeInformativo('Haz clic en una zona para eliminarla');
}

// Función para crear la toolbar en modo eliminar
function crearToolbarEliminar() {
    const toolbar = document.querySelector('.toolbar');
    if (!toolbar) return;
    
    // Limpiar toolbar actual
    toolbar.innerHTML = '';
    
    const botonesEliminar = [
        {
            icon: 'trash-2',
            accion: 'eliminando',
            descripcion: 'Eliminando zona - Selecciona una zona para eliminar',
            clase: 'eliminando'
        },
        {
            icon: 'x-square',
            accion: 'confirmarEliminar',
            descripcion: 'Eliminar zona seleccionada',
            clase: 'confirmar-eliminar'
        },
        {
            icon: 'x-circle',
            accion: 'cancelar',
            descripcion: 'Cancelar eliminación',
            clase: 'cancelar'
        }
    ];

    botonesEliminar.forEach(boton => {
        const button = document.createElement('button');
        button.className = `tool-button ${boton.clase}`;
        button.innerHTML = `
            <i data-feather="${boton.icon}"></i>
            <span class="tool-tip">${boton.descripcion}</span>
        `;
        
        // Los botones están deshabilitados hasta que se seleccione una zona
        if (boton.accion === 'eliminando' || boton.accion === 'confirmarEliminar') {
            button.disabled = true;
            button.style.opacity = '0.5';
        }
        
        button.addEventListener('click', () => {
            manejarClickBotonEliminar(boton.accion);
        });

        toolbar.appendChild(button);
    });

    // Reinicializar iconos de Feather
    feather.replace();
}

// Función para manejar clicks en botones de eliminar
function manejarClickBotonEliminar(accion) {
    switch(accion) {
        case 'confirmarEliminar':
            confirmarEliminacionToolbar();
            break;
        case 'cancelar':
            cancelarEliminacionToolbar();
            break;
        // El botón 'eliminando' no hace nada, solo es informativo
    }
}

// Función para configurar zonas para eliminar
function configurarZonasParaEliminar() {
    // Limpiar eventos previos
    limpiarEventosZonas();
    
    zonas.forEach(({ zona, grupoZona }) => {
        // Configurar eventos de hover
        zona.on('mouseover.eliminar', () => {
            if (zonaSeleccionadaEliminar !== zona) {
                zona.opacity(0.8);
                zona.strokeWidth(4);
                zona.stroke('#f44336'); // Color rojo para eliminar
                layer.batchDraw();
            }
        });

        zona.on('mouseout.eliminar', () => {
            if (zonaSeleccionadaEliminar !== zona) {
                zona.opacity(0.5);
                zona.strokeWidth(3);
                // Restaurar color original
                const idZona = zona.attrs.id_zona;
                if (idZona) {
                    const zonaData = obtenerDatosZona(idZona);
                    if (zonaData) {
                        const color = calcularColor(zonaData.ocupados, zonaData.maximos);
                        zona.stroke(color.stroke);
                    }
                }
                layer.batchDraw();
            }
        });

        // Configurar evento de click para selección
        zona.on('click.eliminar', () => {
            seleccionarZonaParaEliminar(zona);
        });
    });
}

// Función para seleccionar una zona para eliminar
function seleccionarZonaParaEliminar(zona) {
    console.log('Zona seleccionada para eliminar:', zona.name());
    
    // Si ya hay una zona seleccionada, deseleccionarla primero
    if (zonaSeleccionadaEliminar) {
        deseleccionarZonaEliminar();
    }
    
    // Seleccionar la nueva zona
    zonaSeleccionadaEliminar = zona;
    
    // Cambiar apariencia de la zona seleccionada
    zona.opacity(1);
    zona.strokeWidth(5);
    zona.stroke('#d32f2f'); // Color rojo oscuro para indicar selección para eliminar
    zona.fill('rgba(244, 67, 54, 0.3)'); // Fondo rojo semi-transparente
    
    // Habilitar los botones en la toolbar
    const botonEliminando = document.querySelector('.tool-button.eliminando');
    const botonConfirmarEliminar = document.querySelector('.tool-button.confirmar-eliminar');
    
    if (botonEliminando) {
        botonEliminando.disabled = false;
        botonEliminando.style.opacity = '1';
    }
    
    if (botonConfirmarEliminar) {
        botonConfirmarEliminar.disabled = false;
        botonConfirmarEliminar.style.opacity = '1';
    }
    
    // Limpiar eventos de selección de otras zonas
    zonas.forEach(({ zona: otraZona }) => {
        if (otraZona !== zona) {
            otraZona.off('.eliminar');
            otraZona.opacity(0.3); // Hacer otras zonas más transparentes
        }
    });
    
    layer.batchDraw();
    
    // Actualizar mensaje
    mostrarMensajeInformativo(`Zona "${zona.name()}" seleccionada para eliminar. Confirma la eliminación con el botón rojo.`);
}

// Función para deseleccionar zona para eliminar
function deseleccionarZonaEliminar() {
    if (!zonaSeleccionadaEliminar) return;
    
    // Restaurar apariencia normal
    zonaSeleccionadaEliminar.opacity(0.5);
    zonaSeleccionadaEliminar.strokeWidth(3);
    
    // Restaurar color original
    const idZona = zonaSeleccionadaEliminar.attrs.id_zona;
    if (idZona) {
        const zonaData = obtenerDatosZona(idZona);
        if (zonaData) {
            const color = calcularColor(zonaData.ocupados, zonaData.maximos);
            zonaSeleccionadaEliminar.stroke(color.stroke);
            zonaSeleccionadaEliminar.fill(color.fill);
        }
    }
    
    zonaSeleccionadaEliminar = null;
}

// Función para confirmar eliminación desde toolbar
function confirmarEliminacionToolbar() {
    if (!zonaSeleccionadaEliminar) {
        Swal.fire({
            icon: 'warning',
            title: 'Ninguna zona seleccionada',
            text: 'Selecciona una zona para eliminar.',
            confirmButtonText: 'Aceptar'
        });
        return;
    }

    const idZona = zonaSeleccionadaEliminar.attrs.id_zona;
    const nombreZona = zonaSeleccionadaEliminar.name();
    
    if (!idZona) {
        console.error('ID de zona no encontrado');
        return;
    }

    // Mostrar confirmación con SweetAlert
    Swal.fire({
        title: '¿Estás seguro?',
        text: `¿Deseas eliminar la zona "${nombreZona}"? Esta acción se puede revertir.`,
        icon: 'warning',
        showCancelButton: true,
        confirmButtonColor: '#d33',
        cancelButtonColor: '#3085d6',
        confirmButtonText: 'Sí, eliminar',
        cancelButtonText: 'No, cancelar'
    }).then((result) => {
        if (result.isConfirmed) {
            // Usuario confirmó, proceder con la eliminación
            ejecutarEliminacionZona(idZona, nombreZona);
        } else {
            // Usuario canceló, resetear todo
            console.log('Eliminación cancelada por el usuario');
            finalizarEliminacionToolbar();
        }
    });
}

// Función para ejecutar la eliminación de la zona
function ejecutarEliminacionZona(idZona, nombreZona) {
    console.log('Eliminando zona:', nombreZona, 'ID:', idZona);
    
    // Obtener token CSRF
    function getCookie(name) {
        let cookieValue = null;
        if (document.cookie && document.cookie !== '') {
            const cookies = document.cookie.split(';');
            for (let i = 0; i < cookies.length; i++) {
                const cookie = cookies[i].trim();
                if (cookie.substring(0, name.length + 1) === (name + '=')) {
                    cookieValue = decodeURIComponent(cookie.substring(name.length + 1));
                    break;
                }
            }
        }
        return cookieValue;
    }
    
    const csrftoken = getCookie('csrftoken');
    
    // Llamada AJAX para eliminar la zona (nueva vista)
    $.ajax({
        url: '/eliminar_zona',
        method: 'POST',
        data: {
            id_zona: idZona,
            csrfmiddlewaretoken: csrftoken
        },
        success: function(response) {
            if (response.success) {
                console.log('Zona eliminada exitosamente');
                
                Swal.fire({
                    icon: 'success',
                    title: '¡Eliminada!',
                    text: `La zona "${nombreZona}" ha sido eliminada correctamente.`,
                    showConfirmButton: false,
                    timer: 2000,
                    timerProgressBar: true,
                    toast: true,
                    position: 'top-end'
                });
                
                // Resetear el plano completo
                resetearPlanoCompleto();
                
                // Finalizar eliminación
                finalizarEliminacionToolbar();
            } else {
                console.error('Error al eliminar zona:', response.error);
                Swal.fire({
                    icon: 'error',
                    title: 'Error',
                    text: 'Error al eliminar la zona: ' + response.error,
                    confirmButtonText: 'Aceptar'
                });
            }
        },
        error: function(error) {
            console.error('Error en la petición AJAX:', error);
            Swal.fire({
                icon: 'error',
                title: 'Error de conexión',
                text: 'Error al eliminar la zona. Por favor, intente nuevamente.',
                confirmButtonText: 'Aceptar'
            });
        }
    });
}

// Función para cancelar eliminación desde toolbar
function cancelarEliminacionToolbar() {
    console.log('Cancelando eliminación desde toolbar');
    finalizarEliminacionToolbar();
}

// Función para finalizar la eliminación desde toolbar
function finalizarEliminacionToolbar() {
    console.log('Finalizando eliminación desde toolbar');
    
    // No hacer nada si ya se está reseteando el plano
    if (zonas.length === 0) {
        console.log('El plano ya está siendo reseteado, saltando finalización');
        // Solo limpiar estado y restaurar toolbar
        modoEliminarZona = false;
        zonaSeleccionadaEliminar = null;
        herramientaActiva = null;
        stage.container().style.cursor = 'default';
        restaurarToolbarOriginal();
        ocultarMensajeInformativo();
        return;
    }
    
    // Deseleccionar zona si hay una seleccionada
    if (zonaSeleccionadaEliminar) {
        deseleccionarZonaEliminar();
    }
    
    // Restaurar todas las zonas a su estado normal
    zonas.forEach(({ zona }) => {
        zona.opacity(0.5);
        zona.strokeWidth(3);
        zona.off('.eliminar');
        
        // Restaurar color original
        const idZona = zona.attrs.id_zona;
        if (idZona) {
            const zonaData = obtenerDatosZona(idZona);
            if (zonaData) {
                const color = calcularColor(zonaData.ocupados, zonaData.maximos);
                zona.stroke(color.stroke);
                zona.fill(color.fill);
            }
        }
    });
    
    // Limpiar estado
    modoEliminarZona = false;
    zonaSeleccionadaEliminar = null;
    herramientaActiva = null;
    
    // Restaurar cursor
    stage.container().style.cursor = 'default';
    
    // Restaurar toolbar original
    restaurarToolbarOriginal();
    
    // Restaurar eventos normales de las zonas
    limpiarEventosZonas();
    
    // Ocultar mensaje informativo
    ocultarMensajeInformativo();
    
    layer.batchDraw();
}
// Función para iniciar el modo de mover desde toolbar
function iniciarModoMoverToolbar() {
    console.log('Iniciando modo mover desde toolbar');
    
    modoMoverZona = true;
    herramientaActiva = 'moviendoZona';
    
    // Cambiar la toolbar a modo mover
    crearToolbarMover();
    
    // Configurar las zonas para ser seleccionables para mover
    configurarZonasParaMover();
    
    // Cambiar cursor
    stage.container().style.cursor = 'pointer';
    
    // Mostrar mensaje informativo
    mostrarMensajeInformativo('Haz clic en una zona para moverla');
}

// Función para crear la toolbar en modo mover
function crearToolbarMover() {
    const toolbar = document.querySelector('.toolbar');
    if (!toolbar) return;
    
    // Limpiar toolbar actual
    toolbar.innerHTML = '';
    
    const botonesMover = [
        {
            icon: 'move',
            accion: 'moviendo',
            descripcion: 'Moviendo zona - Arrastra para cambiar posición',
            clase: 'moviendo'
        },
        {
            icon: 'save',
            accion: 'guardar',
            descripcion: 'Guardar nueva posición',
            clase: 'guardar'
        },
        {
            icon: 'x-circle',
            accion: 'cancelar',
            descripcion: 'Cancelar movimiento',
            clase: 'cancelar'
        }
    ];

    botonesMover.forEach(boton => {
        const button = document.createElement('button');
        button.className = `tool-button ${boton.clase}`;
        button.innerHTML = `
            <i data-feather="${boton.icon}"></i>
            <span class="tool-tip">${boton.descripcion}</span>
        `;
        
        // El primer botón (moviendo) está deshabilitado hasta que se seleccione una zona
        if (boton.accion === 'moviendo') {
            button.disabled = true;
            button.style.opacity = '0.5';
        }
        
        button.addEventListener('click', () => {
            manejarClickBotonMover(boton.accion);
        });

        toolbar.appendChild(button);
    });

    // Reinicializar iconos de Feather
    feather.replace();
}

// Función para manejar clicks en botones de mover
function manejarClickBotonMover(accion) {
    switch(accion) {
        case 'guardar':
            guardarMovimientoToolbar();
            break;
        case 'cancelar':
            cancelarMovimientoToolbar();
            break;
        // El botón 'moviendo' no hace nada, solo es informativo
    }
}

// Función para configurar zonas para mover
function configurarZonasParaMover() {
    // Limpiar eventos previos
    limpiarEventosZonas();
    
    zonas.forEach(({ zona, grupoZona, puntosControl }) => {
        // Configurar eventos de hover
        zona.on('mouseover.mover', () => {
            if (zonaSeleccionadaMover !== zona) {
                zona.opacity(0.8);
                zona.strokeWidth(4);
                layer.batchDraw();
            }
        });

        zona.on('mouseout.mover', () => {
            if (zonaSeleccionadaMover !== zona) {
                zona.opacity(0.5);
                zona.strokeWidth(3);
                layer.batchDraw();
            }
        });

        // Configurar evento de click para selección
        zona.on('click.mover', () => {
            seleccionarZonaParaMover(zona, grupoZona);
        });
    });
}

// Función para seleccionar una zona para mover
function seleccionarZonaParaMover(zona, grupoZona) {
    console.log('Zona seleccionada para mover:', zona.name());
    
    // Si ya hay una zona seleccionada, deseleccionarla primero
    if (zonaSeleccionadaMover) {
        deseleccionarZonaMover();
    }
    
    // Seleccionar la nueva zona
    zonaSeleccionadaMover = zona;
    coordenadasOriginalesMover = [...zona.points()];
    posicionInicialMover = { x: grupoZona.x(), y: grupoZona.y() };
    
    // Cambiar apariencia de la zona seleccionada
    zona.opacity(1);
    zona.strokeWidth(5);
    zona.stroke('#2196f3'); // Color azul para indicar selección para mover
    
    // Hacer el grupo arrastrable
    grupoZona.draggable(true);
    grupoZona.listening(true);
    
    // Configurar eventos de arrastre
    grupoZona.off('dragstart.mover');
    grupoZona.off('dragmove.mover');
    grupoZona.off('dragend.mover');
    
    grupoZona.on('dragstart.mover', () => {
        stage.container().style.cursor = 'grabbing';
    });
    
    grupoZona.on('dragmove.mover', () => {
        layer.batchDraw();
    });
    
    grupoZona.on('dragend.mover', () => {
        stage.container().style.cursor = 'grab';
        // Actualizar las coordenadas de la zona basándose en la nueva posición del grupo
        actualizarCoordenadasZonaMover(zona, grupoZona);
    });
    
    // Habilitar el botón de mover en la toolbar
    const botonMoviendo = document.querySelector('.tool-button.moviendo');
    if (botonMoviendo) {
        botonMoviendo.disabled = false;
        botonMoviendo.style.opacity = '1';
    }
    
    // Limpiar eventos de selección de otras zonas
    zonas.forEach(({ zona: otraZona }) => {
        if (otraZona !== zona) {
            otraZona.off('.mover');
            otraZona.opacity(0.3); // Hacer otras zonas más transparentes
        }
    });
    
    // Cambiar cursor a grab
    stage.container().style.cursor = 'grab';
    
    layer.batchDraw();
    
    // Actualizar mensaje
    mostrarMensajeInformativo('Zona seleccionada. Arrastra para mover o usa los botones de la barra de herramientas.');
}

// Función para actualizar coordenadas de zona después de mover
function actualizarCoordenadasZonaMover(zona, grupoZona) {
    const desplazamientoX = grupoZona.x() - posicionInicialMover.x;
    const desplazamientoY = grupoZona.y() - posicionInicialMover.y;
    
    // Aplicar el desplazamiento a las coordenadas de la zona
    const puntosOriginales = coordenadasOriginalesMover;
    const nuevosPoints = puntosOriginales.map((coord, index) => {
        if (index % 2 === 0) {
            // Coordenada X
            return coord + desplazamientoX;
        } else {
            // Coordenada Y
            return coord + desplazamientoY;
        }
    });
    
    // Actualizar los puntos de la zona
    zona.points(nuevosPoints);
    
    // Resetear la posición del grupo a 0,0 ya que las coordenadas ya están ajustadas
    grupoZona.position({ x: 0, y: 0 });
    
    layer.batchDraw();
}

// Función para deseleccionar zona para mover
function deseleccionarZonaMover() {
    if (!zonaSeleccionadaMover) return;
    
    const zonaObj = zonas.find(z => z.zona === zonaSeleccionadaMover);
    if (zonaObj) {
        // Restaurar apariencia normal
        zonaSeleccionadaMover.opacity(0.5);
        zonaSeleccionadaMover.strokeWidth(3);
        
        // Restaurar color original
        const idZona = zonaSeleccionadaMover.attrs.id_zona;
        if (idZona) {
            // Obtener color original basado en ocupación
            const zonaData = obtenerDatosZona(idZona);
            if (zonaData) {
                const color = calcularColor(zonaData.ocupados, zonaData.maximos);
                zonaSeleccionadaMover.stroke(color.stroke);
            }
        }
        
        // Deshabilitar arrastre
        zonaObj.grupoZona.draggable(false);
        zonaObj.grupoZona.off('.mover');
    }
    
    zonaSeleccionadaMover = null;
    coordenadasOriginalesMover = null;
    posicionInicialMover = null;
}

// Función para guardar movimiento desde toolbar
function guardarMovimientoToolbar() {
    if (!zonaSeleccionadaMover) {
        Swal.fire({
            icon: 'warning',
            title: 'Ninguna zona seleccionada',
            text: 'Selecciona una zona para guardar el movimiento.',
            confirmButtonText: 'Aceptar'
        });
        return;
    }

    const idZona = zonaSeleccionadaMover.attrs.id_zona;
    const nuevasCoordenadas = zonaSeleccionadaMover.points();
    
    if (!idZona) {
        console.error('ID de zona no encontrado');
        return;
    }

    console.log('Guardando zona movida:', zonaSeleccionadaMover.name(), 'ID:', idZona);
    
    // Obtener token CSRF
    function getCookie(name) {
        let cookieValue = null;
        if (document.cookie && document.cookie !== '') {
            const cookies = document.cookie.split(';');
            for (let i = 0; i < cookies.length; i++) {
                const cookie = cookies[i].trim();
                if (cookie.substring(0, name.length + 1) === (name + '=')) {
                    cookieValue = decodeURIComponent(cookie.substring(name.length + 1));
                    break;
                }
            }
        }
        return cookieValue;
    }
    
    const csrftoken = getCookie('csrftoken');
    
    // Llamada AJAX para guardar las coordenadas (reutilizamos la misma vista)
    $.ajax({
        url: '/actualizar_coordenadas_zona',
        method: 'POST',
        data: {
            id_zona: idZona,
            coordenadas: JSON.stringify(nuevasCoordenadas),
            csrfmiddlewaretoken: csrftoken
        },
        success: function(response) {
            if (response.success) {
                console.log('Posición guardada exitosamente');
                
                Swal.fire({
                    icon: 'success',
                    title: '¡Guardado!',
                    text: 'La zona ha sido movida correctamente.',
                    showConfirmButton: false,
                    timer: 2000,
                    timerProgressBar: true,
                    toast: true,
                    position: 'top-end'
                });
                
                // Resetear el plano completo
                resetearPlanoCompleto();
                
                // Finalizar movimiento
                finalizarMovimientoToolbar();
            } else {
                console.error('Error al guardar posición:', response.error);
                Swal.fire({
                    icon: 'error',
                    title: 'Error',
                    text: 'Error al guardar el movimiento: ' + response.error,
                    confirmButtonText: 'Aceptar'
                });
            }
        },
        error: function(error) {
            console.error('Error en la petición AJAX:', error);
            Swal.fire({
                icon: 'error',
                title: 'Error de conexión',
                text: 'Error al guardar el movimiento. Por favor, intente nuevamente.',
                confirmButtonText: 'Aceptar'
            });
        }
    });
}

// Función para cancelar movimiento desde toolbar
function cancelarMovimientoToolbar() {
    if (!zonaSeleccionadaMover) {
        finalizarMovimientoToolbar();
        return;
    }
    
    // Verificar si hay cambios en la posición
    const coordenadasActuales = zonaSeleccionadaMover.points();
    const hayCambios = !coordenadasOriginalesMover || 
        coordenadasOriginalesMover.length !== coordenadasActuales.length ||
        coordenadasOriginalesMover.some((coord, index) => Math.abs(coord - coordenadasActuales[index]) > 1);
    
    if (hayCambios) {
        // Mostrar confirmación si hay cambios
        Swal.fire({
            title: '¿Descartar movimiento?',
            text: 'Se perderán todos los cambios de posición realizados.',
            icon: 'warning',
            showCancelButton: true,
            confirmButtonColor: '#d33',
            cancelButtonColor: '#3085d6',
            confirmButtonText: 'Sí, descartar',
            cancelButtonText: 'Continuar moviendo'
        }).then((result) => {
            if (result.isConfirmed) {
                // Restaurar coordenadas y posición originales
                if (coordenadasOriginalesMover && posicionInicialMover) {
                    zonaSeleccionadaMover.points(coordenadasOriginalesMover);
                    
                    // Restaurar posición del grupo
                    const zonaObj = zonas.find(z => z.zona === zonaSeleccionadaMover);
                    if (zonaObj) {
                        zonaObj.grupoZona.position(posicionInicialMover);
                    }
                    
                    layer.batchDraw();
                }
                finalizarMovimientoToolbar();
            }
        });
    } else {
        finalizarMovimientoToolbar();
    }
}

// Función para finalizar el movimiento desde toolbar
function finalizarMovimientoToolbar() {
    console.log('Finalizando movimiento desde toolbar');
    
    // No hacer nada si ya se está reseteando el plano
    if (zonas.length === 0) {
        console.log('El plano ya está siendo reseteado, saltando finalización');
        // Solo limpiar estado y restaurar toolbar
        modoMoverZona = false;
        zonaSeleccionadaMover = null;
        coordenadasOriginalesMover = null;
        posicionInicialMover = null;
        herramientaActiva = null;
        stage.container().style.cursor = 'default';
        restaurarToolbarOriginal();
        ocultarMensajeInformativo();
        return;
    }
    
    // Deseleccionar zona si hay una seleccionada
    if (zonaSeleccionadaMover) {
        deseleccionarZonaMover();
    }
    
    // Restaurar todas las zonas a su estado normal
    zonas.forEach(({ zona, grupoZona }) => {
        zona.opacity(0.5);
        zona.strokeWidth(3);
        zona.off('.mover');
        grupoZona.draggable(false);
        grupoZona.off('.mover');
    });
    
    // Limpiar estado
    modoMoverZona = false;
    zonaSeleccionadaMover = null;
    coordenadasOriginalesMover = null;
    posicionInicialMover = null;
    herramientaActiva = null;
    
    // Restaurar cursor
    stage.container().style.cursor = 'default';
    
    // Restaurar toolbar original
    restaurarToolbarOriginal();
    
    // Restaurar eventos normales de las zonas
    limpiarEventosZonas();
    
    // Ocultar mensaje informativo
    ocultarMensajeInformativo();
    
    layer.batchDraw();
}

// Función para crear la toolbar en modo edición
function crearToolbarEdicion() {
    const toolbar = document.querySelector('.toolbar');
    if (!toolbar) return;
    
    // Limpiar toolbar actual
    toolbar.innerHTML = '';
    
    const botonesEdicion = [
        {
            icon: 'edit-3',
            accion: 'editando',
            descripcion: 'Editando zona - Arrastra los puntos para modificar',
            clase: 'editando'
        },
        {
            icon: 'save',
            accion: 'guardar',
            descripcion: 'Guardar cambios',
            clase: 'guardar'
        },
        {
            icon: 'x-circle',
            accion: 'cancelar',
            descripcion: 'Cancelar edición',
            clase: 'cancelar'
        }
    ];

    botonesEdicion.forEach(boton => {
        const button = document.createElement('button');
        button.className = `tool-button ${boton.clase}`;
        button.innerHTML = `
            <i data-feather="${boton.icon}"></i>
            <span class="tool-tip">${boton.descripcion}</span>
        `;
        
        // El primer botón (editando) está deshabilitado hasta que se seleccione una zona
        if (boton.accion === 'editando') {
            button.disabled = true;
            button.style.opacity = '0.5';
        }
        
        button.addEventListener('click', () => {
            manejarClickBotonEdicion(boton.accion);
        });

        toolbar.appendChild(button);
    });

    // Reinicializar iconos de Feather
    feather.replace();
}

// Función para manejar clicks en botones de edición
function manejarClickBotonEdicion(accion) {
    switch(accion) {
        case 'guardar':
            guardarEdicionToolbar();
            break;
        case 'cancelar':
            cancelarEdicionToolbar();
            break;
        // El botón 'editando' no hace nada, solo es informativo
    }
}

// Función para configurar zonas para selección
function configurarZonasParaSeleccion() {
    // Limpiar eventos previos
    limpiarEventosZonas();
    
    zonas.forEach(({ zona, grupoZona, puntosControl }) => {
        // Configurar eventos de hover
        zona.on('mouseover.seleccion', () => {
            if (zonaSeleccionadaEdicion !== zona) {
                zona.opacity(0.8);
                zona.strokeWidth(4);
                layer.batchDraw();
            }
        });

        zona.on('mouseout.seleccion', () => {
            if (zonaSeleccionadaEdicion !== zona) {
                zona.opacity(0.5);
                zona.strokeWidth(3);
                layer.batchDraw();
            }
        });

        // Configurar evento de click para selección
        zona.on('click.seleccion', () => {
            seleccionarZonaParaEdicion(zona, puntosControl);
        });
    });
}

// Función para seleccionar una zona para edición
function seleccionarZonaParaEdicion(zona, puntosControl) {
    console.log('Zona seleccionada para edición:', zona.name());
    
    // Si ya hay una zona seleccionada, deseleccionarla primero
    if (zonaSeleccionadaEdicion) {
        deseleccionarZona();
    }
    
    // Seleccionar la nueva zona
    zonaSeleccionadaEdicion = zona;
    coordenadasOriginalesEdicion = [...zona.points()];
    
    // Cambiar apariencia de la zona seleccionada
    zona.opacity(1);
    zona.strokeWidth(5);
    zona.stroke('#ff9800'); // Color naranja para indicar selección
    
    // Mostrar puntos de control
    puntosControl.forEach((control, index) => {
        control.visible(true);
        control.draggable(true);
        control.listening(true);
        
        // Limpiar eventos anteriores
        control.off('dragmove.edicionToolbar');
        
        // Configurar evento de arrastre
        control.on('dragmove.edicionToolbar', () => {
            const points = zona.points();
            const controlIndex = parseInt(control.name().split('-')[1]);
            points[controlIndex * 2] = control.x();
            points[controlIndex * 2 + 1] = control.y();
            zona.points(points);
            layer.batchDraw();
        });
    });
    
    // Habilitar el botón de edición en la toolbar
    const botonEditando = document.querySelector('.tool-button.editando');
    if (botonEditando) {
        botonEditando.disabled = false;
        botonEditando.style.opacity = '1';
    }
    
    // Limpiar eventos de selección de otras zonas
    zonas.forEach(({ zona: otraZona }) => {
        if (otraZona !== zona) {
            otraZona.off('.seleccion');
            otraZona.opacity(0.3); // Hacer otras zonas más transparentes
        }
    });
    
    layer.batchDraw();
    
    // Actualizar mensaje
    mostrarMensajeInformativo('Zona seleccionada. Arrastra los puntos para editar o usa los botones de la barra de herramientas.');
}

// Función para deseleccionar zona
function deseleccionarZona() {
    if (!zonaSeleccionadaEdicion) return;
    
    const zonaObj = zonas.find(z => z.zona === zonaSeleccionadaEdicion);
    if (zonaObj) {
        // Restaurar apariencia normal
        zonaSeleccionadaEdicion.opacity(0.5);
        zonaSeleccionadaEdicion.strokeWidth(3);
        
        // Restaurar color original
        const idZona = zonaSeleccionadaEdicion.attrs.id_zona;
        if (idZona) {
            // Obtener color original basado en ocupación
            const zonaData = obtenerDatosZona(idZona);
            if (zonaData) {
                const color = calcularColor(zonaData.ocupados, zonaData.maximos);
                zonaSeleccionadaEdicion.stroke(color.stroke);
            }
        }
        
        // Ocultar puntos de control
        zonaObj.puntosControl.forEach(control => {
            control.visible(false);
            control.draggable(false);
            control.off('dragmove.edicionToolbar');
        });
    }
    
    zonaSeleccionadaEdicion = null;
    coordenadasOriginalesEdicion = null;
}

// Función para guardar edición desde toolbar
function guardarEdicionToolbar() {
    if (!zonaSeleccionadaEdicion) {
        Swal.fire({
            icon: 'warning',
            title: 'Ninguna zona seleccionada',
            text: 'Selecciona una zona para guardar los cambios.',
            confirmButtonText: 'Aceptar'
        });
        return;
    }

    const idZona = zonaSeleccionadaEdicion.attrs.id_zona;
    const coordenadasPlano = zonaSeleccionadaEdicion.points();
    
    if (!idZona) {
        console.error('ID de zona no encontrado');
        return;
    }

    // Convertir coordenadas del plano a coordenadas reales para guardar
    const coordenadasReales = [];
    for (let i = 0; i < coordenadasPlano.length; i += 2) {
        const coordReal = coordenadasPlanoAReales(coordenadasPlano[i], coordenadasPlano[i + 1]);
        coordenadasReales.push(coordReal.x, coordReal.y);
    }

    console.log('Guardando zona editada:', zonaSeleccionadaEdicion.name(), 'ID:', idZona);
    
    // Obtener token CSRF
    function getCookie(name) {
        let cookieValue = null;
        if (document.cookie && document.cookie !== '') {
            const cookies = document.cookie.split(';');
            for (let i = 0; i < cookies.length; i++) {
                const cookie = cookies[i].trim();
                if (cookie.substring(0, name.length + 1) === (name + '=')) {
                    cookieValue = decodeURIComponent(cookie.substring(name.length + 1));
                    break;
                }
            }
        }
        return cookieValue;
    }
    
    const csrftoken = getCookie('csrftoken');
    
    // Llamada AJAX para guardar las coordenadas reales
    $.ajax({
        url: '/actualizar_coordenadas_zona',
        method: 'POST',
        data: {
            id_zona: idZona,
            coordenadas: JSON.stringify(coordenadasReales), // Enviar coordenadas reales
            csrfmiddlewaretoken: csrftoken
        },
        success: function(response) {
            if (response.success) {
                console.log('Coordenadas guardadas exitosamente');
                
                Swal.fire({
                    icon: 'success',
                    title: '¡Guardado!',
                    text: 'La zona ha sido actualizada correctamente.',
                    showConfirmButton: false,
                    timer: 2000,
                    timerProgressBar: true,
                    toast: true,
                    position: 'top-end'
                });
                
                // Resetear el plano completo
                resetearPlanoCompleto();
                
                // Finalizar edición
                finalizarEdicionToolbar();
            } else {
                console.error('Error al guardar coordenadas:', response.error);
                Swal.fire({
                    icon: 'error',
                    title: 'Error',
                    text: 'Error al guardar los cambios: ' + response.error,
                    confirmButtonText: 'Aceptar'
                });
            }
        },
        error: function(error) {
            console.error('Error en la petición AJAX:', error);
            Swal.fire({
                icon: 'error',
                title: 'Error de conexión',
                text: 'Error al guardar los cambios. Por favor, intente nuevamente.',
                confirmButtonText: 'Aceptar'
            });
        }
    });
}


// Función para cancelar edición desde toolbar
function cancelarEdicionToolbar() {
    if (!zonaSeleccionadaEdicion) {
        finalizarEdicionToolbar();
        return;
    }
    
    // Verificar si hay cambios
    const coordenadasActuales = zonaSeleccionadaEdicion.points();
    const hayCambios = !coordenadasOriginalesEdicion || 
        coordenadasOriginalesEdicion.length !== coordenadasActuales.length ||
        coordenadasOriginalesEdicion.some((coord, index) => Math.abs(coord - coordenadasActuales[index]) > 1);
    
    if (hayCambios) {
        // Mostrar confirmación si hay cambios
        Swal.fire({
            title: '¿Descartar cambios?',
            text: 'Se perderán todos los cambios realizados en esta zona.',
            icon: 'warning',
            showCancelButton: true,
            confirmButtonColor: '#d33',
            cancelButtonColor: '#3085d6',
            confirmButtonText: 'Sí, descartar',
            cancelButtonText: 'Continuar editando'
        }).then((result) => {
            if (result.isConfirmed) {
                // Restaurar coordenadas originales
                if (coordenadasOriginalesEdicion) {
                    zonaSeleccionadaEdicion.points(coordenadasOriginalesEdicion);
                    
                    // Actualizar posiciones de los puntos de control
                    const zonaObj = zonas.find(z => z.zona === zonaSeleccionadaEdicion);
                    if (zonaObj) {
                        zonaObj.puntosControl.forEach((control, index) => {
                            if (index * 2 < coordenadasOriginalesEdicion.length) {
                                control.x(coordenadasOriginalesEdicion[index * 2]);
                                control.y(coordenadasOriginalesEdicion[index * 2 + 1]);
                            }
                        });
                    }
                    layer.batchDraw();
                }
                finalizarEdicionToolbar();
            }
        });
    } else {
        finalizarEdicionToolbar();
    }
}

// Función para finalizar la edición desde toolbar
function finalizarEdicionToolbar() {
    console.log('Finalizando edición desde toolbar');
    
    // No hacer nada si ya se está reseteando el plano
    if (zonas.length === 0) {
        console.log('El plano ya está siendo reseteado, saltando finalización');
        // Solo limpiar estado y restaurar toolbar
        modoEdicionToolbar = false;
        zonaSeleccionadaEdicion = null;
        coordenadasOriginalesEdicion = null;
        herramientaActiva = null;
        stage.container().style.cursor = 'default';
        restaurarToolbarOriginal();
        ocultarMensajeInformativo();
        return;
    }
    
    // Deseleccionar zona si hay una seleccionada
    if (zonaSeleccionadaEdicion) {
        deseleccionarZona();
    }
    
    // Restaurar todas las zonas a su estado normal
    zonas.forEach(({ zona }) => {
        zona.opacity(0.5);
        zona.strokeWidth(3);
        zona.off('.seleccion');
    });
    
    // Limpiar estado
    modoEdicionToolbar = false;
    zonaSeleccionadaEdicion = null;
    coordenadasOriginalesEdicion = null;
    herramientaActiva = null;
    
    // Restaurar cursor
    stage.container().style.cursor = 'default';
    
    // Restaurar toolbar original
    restaurarToolbarOriginal();
    
    // Restaurar eventos normales de las zonas
    limpiarEventosZonas();
    
    // Ocultar mensaje informativo
    ocultarMensajeInformativo();
    
    layer.batchDraw();
}

// Función para restaurar la toolbar original
function restaurarToolbarOriginal() {
    const toolbar = document.querySelector('.toolbar');
    if (toolbar) {
        toolbar.remove();
    }
    
    // Recrear toolbar normal
    crearToolbar();
}

// Función para mostrar mensaje informativo
function mostrarMensajeInformativo(mensaje) {
    // Remover mensaje anterior si existe
    ocultarMensajeInformativo();
    
    const mensajeDiv = document.createElement('div');
    mensajeDiv.id = 'mensaje-informativo-edicion';
    mensajeDiv.style.cssText = `
        position: absolute;
        top: 10px;
        left: 50%;
        transform: translateX(-50%);
        background: rgba(33, 150, 243, 0.9);
        color: white;
        padding: 8px 16px;
        border-radius: 4px;
        font-size: 12px;
        font-weight: bold;
        z-index: 1000;
        pointer-events: none;
        box-shadow: 0 2px 8px rgba(0,0,0,0.2);
    `;
    mensajeDiv.textContent = mensaje;
    
    const container = document.getElementById('container');
    container.appendChild(mensajeDiv);
}

// Función para ocultar mensaje informativo
function ocultarMensajeInformativo() {
    const mensaje = document.getElementById('mensaje-informativo-edicion');
    if (mensaje) {
        mensaje.remove();
    }
}

// Función auxiliar para obtener datos de zona (debes implementar según tu lógica)
function obtenerDatosZona(idZona) {
    // Esta función debería retornar los datos actuales de ocupación de la zona
    // Por ahora retorna valores por defecto
    return {
        ocupados: 0,
        maximos: 10
    };
}

// Función para resetear el plano completo
function resetearPlanoCompleto() {
    console.log('Reseteando plano completo...');
    
    // Mostrar indicador de carga
    Swal.fire({
        title: 'Actualizando plano...',
        text: 'Recargando todas las zonas',
        allowOutsideClick: false,
        allowEscapeKey: false,
        showConfirmButton: false,
        willOpen: () => {
            Swal.showLoading();
        }
    });
    
    // 1. Limpiar todas las zonas actuales del mapa
    limpiarTodasLasZonas();
    
    // 2. Limpiar arrays y variables globales
    zonas = [];
    zonasAgregadas.clear();
    marcadores = [];
    
    // 3. Devolver objetos al pool para reutilización
    devolverTodosLosObjetosAlPool();
    
    // 4. Limpiar datos en caché
    if (typeof zoneData !== 'undefined') {
        zoneData = {};
    }
    
    // 5. Recargar las zonas desde el servidor con callback
    setTimeout(() => {
        cargarZonasDesdeServidor(() => {
            // 6. Recargar datos de cupos después de cargar las zonas
            cargarDatosZonas();
            
            // 7. Cerrar indicador de carga
            Swal.close();
            
            console.log('Plano reseteado completamente');
        });
    }, 100); // Pequeño delay para asegurar que se complete la limpieza
}

// Función para limpiar todas las zonas del mapa
function limpiarTodasLasZonas() {
    zonas.forEach(({ grupoZona, tooltip, puntosControl }) => {
        // Limpiar eventos
        grupoZona.off();
        tooltip.off();
        puntosControl.forEach(control => control.off());
        
        // Destruir elementos gráficos
        grupoZona.destroy();
        tooltip.destroy();
        puntosControl.forEach(control => control.destroy());
    });
    
    // Limpiar la capa de elementos residuales
    layer.find('Group').forEach(grupo => {
        if (grupo.name() && grupo.name().startsWith('grupo-')) {
            grupo.destroy();
        }
    });
    
    layer.find('Label').forEach(label => {
        label.destroy();
    });
    
    // Redibujar la capa
    layer.batchDraw();
}

// Función para devolver todos los objetos al pool
function devolverTodosLosObjetosAlPool() {
    zonas.forEach(zonaObj => {
        if (zonaObj.puntosControl) {
            zonaObj.puntosControl.forEach(punto => {
                punto.off(); // Limpiar eventos
                poolPuntosControl.push(punto);
            });
        }
        
        if (zonaObj.tooltip) {
            zonaObj.tooltip.off(); // Limpiar eventos
            poolTooltips.push(zonaObj.tooltip);
        }
    });
}

function zonaClick(id_zona) {
    // Si hay una herramienta activa o ya hay un modal abierto, no mostrar el modal
    if (herramientaActiva || modalActivo) {
        return;
    }

    // Asegurarse de que el ID sea un número
    id_zona = parseInt(id_zona);
    if (isNaN(id_zona)) {
        console.error('ID de zona inválido:', id_zona);
        return;
    }

    // Marcar que hay un modal activo
    modalActivo = true;

    // Destruir cualquier instancia existente de DataTable
    if ($.fn.DataTable.isDataTable('#tabla-camiones-datatable')) {
        $('#tabla-camiones-datatable').DataTable().destroy();
    }

    $.ajax({
        method: "GET",
        url: "/get_camiones_zona",
        data: {
            "id_zona": id_zona
        },
        success: function(response) {
            if (!response.success) {
                console.error('Error al obtener datos de la zona:', response.error);
                modalActivo = false; // Resetear el estado del modal
                return;
            }
            
            const nombre_zona = response.nombre_zona;
            const total_camiones = response.total_camiones;
            const cupos_total = response.cupos_total;
            const camiones_zona = response.camiones_zona;

            // Crear el modal
            const modal = document.createElement('div');
            modal.id = "modal-data-camiones";
            modal.className = 'modal fade show';
            modal.style.display = 'block';
            modal.style.backgroundColor = 'rgba(0, 0, 0, 0.5)';
            modal.tabIndex = "-1";
            modal.role = "dialog";
            modal.ariaHidden = "true";
            modal.style.overflow = "auto";
            modal.style.maxHeight = "100vh";
            
            modal.innerHTML = `
                <div class="modal-dialog modal-dialog-centered modal-lg" id="modal-dialog-container" style="margin: 30px auto; width: auto; max-width: 90%;">
                    <div class="modal-content">
                        <div class="modal-header">
                            <h5 class="modal-title">${nombre_zona} (${total_camiones}/${cupos_total} camiones)</h5>
                            <button type="button" class="close" data-dismiss="modal" aria-label="Close">
                                <span aria-hidden="true">&times;</span>
                            </button>
                        </div>
                        <div class="modal-body">
                            <div class="dt-responsive table-responsive">
                                <table id="tabla-camiones-datatable" class="table table-striped table-bordered nowrap" width="100%">
                                    <thead>
                                        <tr>
                                            <th style="width: 50px"></th>
                                            <th>PATENTE</th>
                                            <th>SECUENCIA</th>
                                            <th>ETAPA</th>
                                            <th>INICIO</th>
                                            <th>TIEMPO TRANSCURRIDO</th>
                                        </tr>
                                    </thead>
                                    <tbody id="tabla-camiones">
                                        <!-- Los datos de los camiones se insertarán aquí -->
                                    </tbody>
                                </table>
                            </div>
                        </div>
                        <div class="modal-footer">
                            <button type="button" class="btn btn-secondary" data-dismiss="modal">Cerrar</button>
                        </div>
                    </div>
                </div>
            `;

            // Añadir el modal al body
            document.body.appendChild(modal);

            // Llenar la tabla con los datos de los camiones
            const tablaCamiones = modal.querySelector('#tabla-camiones');
            if (camiones_zona && camiones_zona.length > 0) {
                camiones_zona.forEach(camion => {
                    const tiempoStr = camion.Tiempo_transcurrido;
                    const horas = parseInt(tiempoStr.split(' hrs ')[0]);
                    const tiempoClass = horas >= 2 ? 'text-danger font-weight-bold' : '';
                    const alertIcon = horas >= 2 ? '<i data-feather="alert-circle" class="text-danger" style="width: 16px; height: 16px; margin-right: 5px;"></i>' : '';
                    
                    const fila = document.createElement('tr');
                    fila.innerHTML = `
                        <td style="text-align: center;">
                            <a class="btn btn-sm btn-primary" href="/cit_listone/${camion.id}">
                                <i data-feather="external-link" style="width: 14px; height: 14px;"></i>
                            </a>
                        </td>
                        <td>${camion.Patente || ''}</td>
                        <td>${camion.Secuencia || ''}</td>
                        <td>${camion.Etapa || ''}</td>
                        <td>${camion.Tiempo_entrada || ''}</td>
                        <td class="${tiempoClass}" style="display: flex; align-items: center; justify-content: start;">
                            ${alertIcon}${camion.Tiempo_transcurrido || ''}
                        </td>
                    `;
                    tablaCamiones.appendChild(fila);
                });
                // Inicializar los iconos de Feather después de agregar las filas
                feather.replace();
            } else {
                const fila = document.createElement('tr');
                fila.innerHTML = `
                    <td colspan="5" class="text-center">No hay camiones en esta zona</td>
                `;
                tablaCamiones.appendChild(fila);
            }
            
            let dataTable;
            if ($.fn.DataTable) {
                try {
                dataTable = $('#tabla-camiones-datatable').DataTable({
                    responsive: true,
                        destroy: true,
                    language: {
                        lengthMenu: "Mostrar _MENU_",
                            search: "Buscar:",
                            info: "Mostrando _START_ a _END_ de _TOTAL_ registros",
                        infoEmpty: "Mostrando 0 a 0 de 0 registros",
                        infoFiltered: "(filtrado de _MAX_ registros totales)",
                        paginate: {
                            first: "Primero",
                            last: "Último",
                            next: "Siguiente",
                            previous: "Anterior"
                        },
                        zeroRecords: "No se encontraron registros"
                    },
                    pageLength: 10,
                    dom: 'Bfrtip',
                    buttons: [],
                    initComplete: function(settings, json) {
                        setTimeout(function() {
                            const tableWidth = $('#tabla-camiones-datatable').width();
                            if (tableWidth > 0) {
                                const modalDialogContainer = $('#modal-dialog-container');
                                const currentWidth = modalDialogContainer.width();
                                    const newWidth = Math.max(currentWidth, tableWidth + 50);
                                modalDialogContainer.css('width', newWidth + 'px');
                            }
                        }, 100);
                    }
                });
                } catch (error) {
                    console.error('Error al inicializar DataTable:', error);
                }
            } else {
                console.warn('DataTables no está disponible');
            }

            // Función para cerrar el modal
            const cerrarModal = () => {
                    if (dataTable) {
                    try {
                        dataTable.destroy();
                } catch (e) {
                    console.warn('Error al destruir DataTable:', e);
                }
                }
                modal.remove();
                modalActivo = false; // Resetear el estado del modal
            };

            // Configurar eventos de cierre
            modal.querySelector('.close').addEventListener('click', cerrarModal);
            modal.querySelector('.btn-secondary').addEventListener('click', cerrarModal);
            modal.addEventListener('click', (e) => {
                if (e.target === modal) {
                    cerrarModal();
                }
            });

            // Manejar cierre con la tecla ESC
            document.addEventListener('keydown', function(e) {
                if (e.key === 'Escape' && modalActivo) {
                    cerrarModal();
                }
            });
            
            // Prevenir que el scroll del modal afecte al scroll del body
            modal.addEventListener('wheel', (e) => {
                e.stopPropagation();
            });
        },
        error: function(error) {
            console.error('Error en la petición AJAX:', error);
            alert('Error al obtener datos de la zona. Por favor, intente nuevamente.');
            modalActivo = false; // Resetear el estado del modal en caso de error
        }
    });
}



function actualizarZonaExistente(zonaObj, zonaData) {
    const CUPOS_OCUPADOS = 13;
    const CUPOS_MAXIMOS = 14;
    
    const colorZona = calcularColor(zonaData[CUPOS_OCUPADOS], zonaData[CUPOS_MAXIMOS]);
    
    // Actualizar colores de la zona
    zonaObj.zona.fill(colorZona.fill);
    zonaObj.zona.stroke(colorZona.stroke);
    
    // Actualizar tooltip
    const tooltipText = zonaObj.tooltip.findOne('Text');
    if (tooltipText) {
        const cuposOcupados = zonaData[CUPOS_OCUPADOS] || 0;
        const cuposMaximos = zonaData[CUPOS_MAXIMOS] || 0;
        const cuposLibres = cuposMaximos - cuposOcupados;
        
        tooltipText.text(
            `${zonaData[0]}\nCupos ocupados: ${cuposOcupados}\nCupos máximos: ${cuposMaximos}\nCupos libres: ${cuposLibres}`
        );
    }
}

function crearNuevaZona(zonaData, planoScale, planoOffset) {
    const NOMBRE = 0;
    const CUPOS_OCUPADOS = 13;
    const CUPOS_MAXIMOS = 14;
    const ID_ZONA = 15;

    const colorZona = calcularColor(zonaData[CUPOS_OCUPADOS], zonaData[CUPOS_MAXIMOS]);
    const idZona = parseInt(zonaData[ID_ZONA]);

    // Procesar coordenadas
    const isLatLong = Math.abs(zonaData[1]) > 0 && Math.abs(zonaData[1]) < 90;
    const points = [];
    
    for (let i = 1; i <= 8; i++) {
        const coord = zonaData[i];
        let coordNum = (typeof coord === 'number') 
            ? coord 
            : (typeof coord === 'string' && coord.trim() !== '') 
                ? parseFloat(coord) 
                : 0;

        if (isLatLong) {
            if (i % 2 === 1) {
                coordNum = (Math.abs(coordNum + 36.95) * 10000) + 100;
            } else {
                coordNum = (Math.abs(coordNum + 73.15) * 10000) + 100;
            }
        }
        
        points.push(coordNum);
    }
    
    // Ajustar coordenadas
    for (let i = 0; i < points.length; i += 2) {
        if (points[i] !== 0 || points[i + 1] !== 0) {
            points[i] = (points[i] * planoScale.x) + planoOffset.x;
            points[i + 1] = (points[i + 1] * planoScale.y) + planoOffset.y;
        }
    }

    // Verificar puntos válidos
    let puntosDefined = 0;
    for (let i = 0; i < points.length; i += 2) {
        if (points[i] !== 0 || points[i+1] !== 0) {
            puntosDefined++;
        }
    }
    
    if (puntosDefined < 3) {
        console.log(`Zona ${zonaData[NOMBRE]} no tiene suficientes puntos válidos`);
        return null;
    }

    // Crear elementos de la zona
    const grupoZona = new Konva.Group({ 
        draggable: false, 
        name: `grupo-${zonaData[NOMBRE]}`, 
        listening: true,
        perfectDrawEnabled: false
    });
    
    const zona = new Konva.Line({
        points: points,
        closed: true,
        fill: colorZona.fill,
        stroke: colorZona.stroke,
        strokeWidth: 3,
        opacity: 0.5,
        name: zonaData[NOMBRE],
        id_zona: idZona,
        draggable: false,
        hitStrokeWidth: 20,
        listening: true,
        perfectDrawEnabled: false,
        shadowForStrokeEnabled: false
    });

    // Crear puntos de control reutilizando del pool
    const puntosControl = [];
    for (let i = 0; i < points.length; i += 2) {
        const control = obtenerPuntoControlDelPool();
        control.x(points[i]);
        control.y(points[i + 1]);
        control.name(`control-${i/2}`);
        puntosControl.push(control);
    }

    // Obtener tooltip del pool
    const tooltip = obtenerTooltipDelPool();
    
    // Actualizar contenido del tooltip
    const tooltipText = tooltip.findOne('Text');
    const cuposOcupados = zonaData[CUPOS_OCUPADOS] || 0;
    const cuposMaximos = zonaData[CUPOS_MAXIMOS] || 0;
    const cuposLibres = cuposMaximos - cuposOcupados;
    
    tooltipText.text(
        `${zonaData[NOMBRE]}\nCupos ocupados: ${cuposOcupados}\nCupos máximos: ${cuposMaximos}\nCupos libres: ${cuposLibres}`
    );

    // Configurar eventos de la zona
    configurarEventosZona(zona, tooltip, zonaData[NOMBRE]);

    // Añadir click event
    zona.on('click', function() {
        zonaClick(idZona);
    });

    // Ensamblar elementos
    grupoZona.add(zona);
    puntosControl.forEach(control => {
        grupoZona.add(control);
    });

    layer.add(grupoZona);
    layer.add(tooltip);

    return {
        grupoZona,
        zona,
        tooltip,
        puntosControl,
        nombre: zonaData[NOMBRE],
        id: zonaData[ID_ZONA]
    };
}



// Función para actualizar los cupos (replaced by our enhanced version)
function actualizarCupos() {
    cargarDatosZonas();
}

// Setup periodic refresh (10 seconds)
function configurarActualizacionPeriodica() {
    // Clear any existing interval
    if (refreshInterval) {
        clearInterval(refreshInterval);
    }
    
    // Set new interval (10 seconds = 10000ms)
    refreshInterval = setInterval(function() {
        cargarDatosZonas();
    }, 10000);
    
    // Also update once immediately
    cargarDatosZonas();
    
    console.log('Configurada actualización periódica cada 10 segundos');
}

// Función para obtener la posición del puntero considerando la escala
function getPointerPosition() {
    const pos = stage.getPointerPosition();
    if (!pos) return null;
    
    const scale = stage.scaleX();
    return {
        x: (pos.x - stage.x()) / scale,
        y: (pos.y - stage.y()) / scale
    };
}

// Función para mostrar las instrucciones de dibujo
function mostrarInstruccionesDibujo() {
    // Crear el contenedor de instrucciones
    const instrucciones = document.createElement('div');
    instrucciones.id = 'instruccionesDibujo';
    instrucciones.className = 'toolbar';
    instrucciones.style.top = '20px'; // Posicionar debajo de la barra de herramientas
    instrucciones.style.right = '20px';
    instrucciones.style.left = 'auto';
    instrucciones.innerHTML = `
        <div class="d-flex flex-column gap-2 p-2">
            <div class="d-flex align-items-center>
                <i data-feather="mouse-pointer" class="me-2"></i>
                <span>Haz clic para añadir puntos</span>
            </div>
            <div class="d-flex align-items-center>
                <i data-feather="refresh-cw" class="me-2"></i>
                <span>Mantén Shift + Arrastra para mover el plano</span>
            </div>
            <div class="d-flex align-items-center>
                <i data-feather="x-circle" class="me-2"></i>
                <span>Doble clic para finalizar</span>
            </div>
            <div class="d-flex align-items-center>
                <i data-feather="corner-down-left" class="me-2"></i>
                <span>ESC para cancelar</span>
            </div>
        </div>
    `;

    // Añadir las instrucciones al contenedor
    const container = document.getElementById('container');
    container.appendChild(instrucciones);

    // Inicializar los iconos de Feather
    feather.replace();
}

// Función para ocultar las instrucciones
function ocultarInstruccionesDibujo() {
    const instrucciones = document.getElementById('instruccionesDibujo');
    if (instrucciones) {
        instrucciones.remove();
    }
}

// Función para iniciar el dibujo de zona (corregida)
function iniciarDibujoZona() {
    console.log('Iniciando dibujo de zona');
    
    // Si ya estamos dibujando, no hacer nada
    if (dibujandoZona) {
        console.log('Ya se está dibujando una zona');
        return;
    }

    // Inicializar el estado
    dibujandoZona = true;
    puntosTemporales = [];
    stage.container().style.cursor = 'crosshair';

    // Mostrar instrucciones
    mostrarInstruccionesDibujo();

    // Crear la línea temporal
    lineaTemporalZona = new Konva.Line({
        points: [],
        stroke: '#00ff00',
        strokeWidth: 1,
        dash: [3, 2],
        closed: true,
        listening: false, // Deshabilita cualquier evento 
        perfectDrawEnabled: false, // Alineacion exacta de pixeles
        shadowForStrokeEnabled: false // Efecto de sombra
    });

    // Crear el punto temporal
    puntoTemporal = new Konva.Circle({
        radius: 1,
        fill: '#00ff00',
        stroke: 'white',
        strokeWidth: 1,
        listening: false,
        perfectDrawEnabled: false,
        shadowForStrokeEnabled: false
    });

    // Añadir los elementos a la capa
    layer.add(lineaTemporalZona);
    layer.add(puntoTemporal);

    // throttle para el movimiento del mouse
    const throttledMouseMove = throttle((e) => {
        if (puntosTemporales.length === 0) return;

        const pos = getPointerPosition();
        if (!pos) return;

        const puntosTmp = [...puntosTemporales, [pos.x, pos.y]];
        lineaTemporalZona.points(puntosTmp.flat());
        puntoTemporal.x(pos.x);
        puntoTemporal.y(pos.y);

        layer.batchDraw();
    }, 16); // 60fps

    // Función para manejar el clic
    function handleClick(e) {
        const pos = getPointerPosition();
        if (!pos) return;

        // Verificar si ya tenemos 4 puntos (sin mostrar alerta)
        if (puntosTemporales.length >= 4) {
            console.log('Se ha alcanzado el límite máximo de 4 puntos.');
            return;
        }

        console.log('Añadiendo punto en:', pos.x, pos.y);
        puntosTemporales.push([pos.x, pos.y]);
        lineaTemporalZona.points(puntosTemporales.flat());
        layer.batchDraw();
    }

    // Función para manejar el doble clic
    function handleDoubleClick() {
        if (!dibujandoZona) return;
        
        // Verificar que tengamos suficientes puntos (mínimo 3)
        if (puntosTemporales.length < 3) {
            alert('Se necesitan al menos 3 puntos para crear una zona');
            return;
        }

        console.log('Finalizando dibujo con puntos:', puntosTemporales);
        finalizarDibujoZona();
    }

    // Si llegamos a 4 puntos, finalizar
    if (puntosTemporales.length === 4) {
        setTimeout(() => {
            finalizarDibujoZona();
        }, 100);
    }

    // Limpiar eventos anteriores antes de añadir nuevos
    stage.off('click');
    stage.off('mousemove');
    stage.off('dblclick');
    document.removeEventListener('keydown', handleKeyDown);

    // Añadir event listeners
    stage.on('click', handleClick);
    stage.on('mousemove', throttledMouseMove);
    stage.on('dblclick', handleDoubleClick);
    document.addEventListener('keydown', handleKeyDown);
}

// Función auxiliar para throttle
function throttle(func, limit) {
    let inThrottle;
    return function(...args) {
        if (!inThrottle) {
            func.apply(this, args);
            inThrottle = true;
            setTimeout(() => inThrottle = false, limit);
        }
    };
}

// Función para finalizar el dibujo y crear la zona
function finalizarDibujoZona() {
    if (!dibujandoZona) {
        console.log('No hay dibujo activo para finalizar');
        return;
    }
    
    if (puntosTemporales.length < 3) {
        alert('Se necesitan al menos 3 puntos para crear una zona');
        return;
    }
    
    // Limitar a 4 puntos si hay más
    if (puntosTemporales.length > 4) {
        puntosTemporales = puntosTemporales.slice(0, 4);
        console.log('Se han limitado los puntos a 4:', puntosTemporales);
    }

    console.log('Finalizando dibujo con puntos:', puntosTemporales);
    
    // Extraer las coordenadas seleccionadas en un formato plano para enviar
    const coordenadasPlanas = puntosTemporales.flat();
    console.log('Coordenadas planas:', coordenadasPlanas);
    
    // Obtener el token CSRF de las cookies (método estándar en Django)
    function getCookie(name) {
        let cookieValue = null;
        if (document.cookie && document.cookie !== '') {
            const cookies = document.cookie.split(';');
            for (let i = 0; i < cookies.length; i++) {
                const cookie = cookies[i].trim();
                if (cookie.substring(0, name.length + 1) === (name + '=')) {
                    cookieValue = decodeURIComponent(cookie.substring(name.length + 1));
                    break;
                }
            }
        }
        return cookieValue;
    }
    const csrftoken = getCookie('csrftoken');
    
    // Crear el modal para solicitar información de la zona
    const modal = document.createElement('div');
    modal.className = 'modal fade show';
    modal.style.display = 'block';
    modal.style.backgroundColor = 'rgba(0, 0, 0, 0.5)';
    modal.innerHTML = `
        <div class="modal-dialog modal-dialog-centered">
            <div class="modal-content">
                <div class="modal-header">
                    <h5 class="modal-title">Información de la zona</h5>
                    <button type="button" class="close" data-dismiss="modal" aria-label="Close">
                        <span aria-hidden="true">&times;</span>
                    </button>
                </div>
                <div class="modal-body">
                    <form id="zonaForm">
                        <div class="form-group">
                            <label for="nombreZona">Nombre de la zona:</label>
                            <input type="text" class="form-control" id="nombreZona" name="nombreZona" required>
                        </div>
                        <div class="form-group">
                            <label for="cupoMaximo">Cupo máximo de la zona:</label>
                            <input type="number" class="form-control" id="cupoMaximo" name="cupoMaximo" min="1" required>
                        </div>
                        <div class="form-group" style="display:none;">
                            <label>Coordenadas seleccionadas:</label>
                            <textarea class="form-control" id="coordenadasZona" rows="4" readonly>${JSON.stringify(coordenadasPlanas)}</textarea>
                        </div>
                    </form>
                </div>
                <div class="modal-footer">
                    <button type="button" class="btn btn-secondary" id="btnCancelar">Cancelar</button>
                    <button type="button" class="btn btn-primary" id="btnGuardar">Guardar</button>
                </div>
            </div>
        </div>
    `;

    // Añadir el modal al body
    document.body.appendChild(modal);

    // Función simple para cerrar el modal y limpiar el estado
    const cerrarModal = () => {
        document.body.removeChild(modal);
        cancelarDibujoZona();
        
        // Desactivar el botón de la barra de herramientas
        const botonActivo = document.querySelector('.tool-button.active');
        if (botonActivo) {
            botonActivo.classList.remove('active');
        }
    };

    // Manejar clic en Cancelar y clic fuera del modal
    modal.querySelector('#btnCancelar').addEventListener('click', cerrarModal);
    modal.querySelector('.close').addEventListener('click', cerrarModal);
    modal.addEventListener('click', (e) => {
        if (e.target === modal) cerrarModal();
    });

    // Manejar el clic en el botón de guardar
    const btnGuardar = modal.querySelector('#btnGuardar');
    btnGuardar.addEventListener('click', () => {
        const nombreZona = document.getElementById('nombreZona').value.trim();
        const cupoMaximo = parseInt(document.getElementById('cupoMaximo').value);

        // Validar los campos
        if (!nombreZona) {
            alert('Por favor, ingrese un nombre de zona válido');
            return;
        }

        if (isNaN(cupoMaximo) || cupoMaximo <= 0) {
            alert('Por favor, ingrese un cupo máximo válido');
            return;
        }

        console.log('Creando zona con nombre:', nombreZona, 'cupo:', cupoMaximo);
        
        // Preparar datos para enviar por AJAX
        const datosZona = {
            nombre: nombreZona,
            cupoMaximo: cupoMaximo,
            coordenadas: coordenadasPlanas
        };
        
        // Realizar la llamada AJAX para guardar la zona en el servidor
        $.ajax({
            url: '/guardar_zona',  // Asegúrate de que la URL termine con una barra si Django lo requiere
            method: 'POST',
            contentType: 'application/json',
            data: JSON.stringify(datosZona),
            headers: {
                'X-CSRFToken': csrftoken  // Añadir el token CSRF como header
            },
            success: function(response) {
                console.log('Zona guardada correctamente:', response);
                
                // Crear la zona en el mapa
                crearZonaEnMapa(nombreZona, cupoMaximo, puntosTemporales);
                
                // Cerrar el modal y finalizar el dibujo
                cerrarModal();
                
                // Mostrar mensaje de éxito
                alert('Zona guardada correctamente');
                
                // Actualizar la lista de zonas
                cargarDatosZonas();
            },
            error: function(error) {
                console.error('Error al guardar la zona:', error);
                alert('Error al guardar la zona: ' + (error.responseText || 'Error de conexión'));
            }
        });
    });

    // Permitir enviar el formulario con Enter
    const form = modal.querySelector('#zonaForm');
    form.addEventListener('keypress', (e) => {
        if (e.key === 'Enter') {
            e.preventDefault();
            btnGuardar.click();
        }
    });

    // Dar foco al campo de nombre de zona
    setTimeout(() => {
        document.getElementById('nombreZona').focus();
    }, 100);
}

// Función auxiliar para crear la zona en el mapa
function crearZonaEnMapa(nombreZona, cupoMaximo, puntosTemporales) {
    // Color por defecto para la zona (verde)
    const colorZona = '#4caf50';
    
    // Crear la zona 
    const zona = new Konva.Line({
        points: puntosTemporales.flat(),
        closed: true,
        fill: colorZona,
        stroke: colorZona,
        strokeWidth: 1,
        opacity: 0.5,
        name: nombreZona,
        draggable: false,
        listening: true
    });

    // Crear un grupo para la zona y sus puntos de control
    const grupoZona = new Konva.Group({
        draggable: false,
        name: `grupo-${nombreZona}`,
        listening: true
    });

    // Añadir tooltip
    const tooltip = new Konva.Label({
        x: 0,
        y: 0,
        opacity: 0.9,
        visible: false
    });

    tooltip.add(
        new Konva.Tag({
            fill: '#fff',
            stroke: '#e0e0e0',
            strokeWidth: 1,
            cornerRadius: 4,
            shadowColor: 'black',
            shadowBlur: 10,
            shadowOffset: { x: 2, y: 2 },
            shadowOpacity: 0.2
        })
    );

    tooltip.add(
        new Konva.Text({
            text: `${nombreZona}\nCupo: 0/${cupoMaximo}`,
            fontFamily: 'Arial',
            fontSize: 14,
            padding: 8,
            fill: '#333',
            align: 'center'
        })
    );

    // Añadir puntos de control
    const puntosControl = puntosTemporales.map((punto, index) => {
        const control = new Konva.Circle({
            x: punto[0],
            y: punto[1],
            radius: 3,
            fill: '#00ff00',
            stroke: 'white',
            strokeWidth: 1,
            draggable: false,
            visible: false,
            name: `control-${index}`
        });

        control.on('dragmove', () => {
            const points = zona.points();
            const index = parseInt(control.name().split('-')[1]);
            points[index * 2] = control.x();
            points[index * 2 + 1] = control.y();
            zona.points(points);
            layer.batchDraw();
        });

        return control;
    });

    // Eventos de la zona
    zona.on('mouseover', () => {
        const pos = stage.getPointerPosition();
        if (pos) {
            // Ajustar la posición considerando el zoom y la posición del stage
            const scale = stage.scaleX();
            tooltip.position({
                x: (pos.x - stage.x()) / scale,
                y: (pos.y - stage.y()) / scale - (tooltip.height() / scale) - 10
            });
            // Ajustar la escala del tooltip para mantener su tamaño visual
            tooltip.scale({ x: 1/scale, y: 1/scale });
            tooltip.visible(true);
            document.body.style.cursor = 'pointer';
            layer.batchDraw();
        }
    });

    zona.on('mousemove', () => {
        const pos = stage.getPointerPosition();
        if (pos) {
            // Ajustar la posición considerando el zoom y la posición del stage
            const scale = stage.scaleX();
            tooltip.position({
                x: (pos.x - stage.x()) / scale,
                y: (pos.y - stage.y()) / scale - (tooltip.height() / scale) - 10
            });
            layer.draw();
        }
    });

    zona.on('mouseout', () => {
        tooltip.visible(false);
        document.body.style.cursor = 'default';
        layer.draw();
    });

    // Añadir elementos al grupo
    grupoZona.add(zona);
    puntosControl.forEach(control => {
        grupoZona.add(control);
    });

    // Añadir todo a la capa
    layer.add(grupoZona);
    layer.add(tooltip);

    // Almacenar la zona en el array de zonas
    const nuevaZona = {
        grupoZona: grupoZona,
        zona: zona,
        tooltip: tooltip,
        puntosControl: puntosControl,
        nombre: nombreZona,
        cupoMaximo: cupoMaximo
    };
    
    zonas.push(nuevaZona);

    console.log('Zona creada:', nuevaZona);
    console.log('Total de zonas:', zonas.length);
    
    // Actualizar marker_list_zonas también
    const nuevaZonaData = [
        nombreZona,  // Nombre
        puntosTemporales[0][0], puntosTemporales[0][1], // Punto 1
        puntosTemporales[1][0], puntosTemporales[1][1], // Punto 2
        puntosTemporales[2][0], puntosTemporales[2][1], // Punto 3
        puntosTemporales.length > 3 ? puntosTemporales[3][0] : "", puntosTemporales.length > 3 ? puntosTemporales[3][1] : "", // Punto 4
        "", "",  // Vacíos
        colorZona,  // Color fijo - posición 11
        nombreZona,  // Identificador - posición 12
        0,  // Cupos ocupados - posición 13
        cupoMaximo  // Cupos máximos - posición 14
    ];
    
    window.marker_list_zonas = window.marker_list_zonas || [];
    window.marker_list_zonas.push(nuevaZonaData);
    
    layer.draw();
}

// Función para cancelar el dibujo
function cancelarDibujoZona() {
    console.log('Cancelando dibujo');
    
    dibujandoZona = false;
    puntosTemporales = [];

    if (lineaTemporalZona) {
        lineaTemporalZona.destroy();
        lineaTemporalZona = null;
    }

    if (puntoTemporal) {
        puntoTemporal.destroy();
        puntoTemporal = null;
    }

    // Remover todos los eventos
    stage.off('click');
    stage.off('mousemove');
    stage.off('dblclick');
    document.removeEventListener('keydown', handleKeyDown);
    stage.off('mousedown', handleMouseDown);
    stage.off('mousemove', handleMouseMoveDrag);
    stage.off('mouseup', handleMouseUp);

    // Ocultar instrucciones
    ocultarInstruccionesDibujo();

    stage.container().style.cursor = 'default';
    layer.batchDraw();
}

// Función para manejar tecla ESC durante edición y movimiento
function handleKeyDownEdicion(e) {
    if (e.key === 'Escape') {
        if (modoEdicionToolbar) {
            cancelarEdicionToolbar();
        } else if (modoMoverZona) {
            cancelarMovimientoToolbar();
        } else if (modoEliminarZona) {
            cancelarEliminacionToolbar();
        }
    }
}

// Función para activar/desactivar el modo de mover zonas
function toggleModoMover(activar) {
    console.log('Modo mover:', activar ? 'activado' : 'desactivado');
    
    // Limpiar eventos anteriores
    limpiarEventosZonas();
    
    // Cambiar el cursor según el modo
    stage.container().style.cursor = activar ? 'move' : 'default';

    if (activar) {
        zonas.forEach(({ grupoZona, zona, puntosControl }) => {
            // Hacer el grupo arrastrable
            grupoZona.draggable(true);
            
            // Asegurar que el grupo reciba los eventos
            grupoZona.listening(true);
            
             // Usar un solo evento de dragmove para mejor rendimiento
            grupoZona.on('dragmove', () => {
                // Usar batchDraw en lugar de draw para mejor rendimiento
                layer.batchDraw();
            });

            // Actualizar puntos de control solo al finalizar el arrastre
            grupoZona.on('dragend', () => {
                const points = zona.points();
                puntosControl.forEach((control, index) => {
                    control.x(points[index * 2]);
                    control.y(points[index * 2 + 1]);
                });
                puntosControl.forEach(control => control.visible(false));
                layer.batchDraw();
            });
        });
    }
    layer.batchDraw();
    
}

// Función para mostrar el modal de confirmación
function mostrarModalConfirmacion(mensaje, callback) {
    // Crear el modal
    const modal = document.createElement('div');
    modal.className = 'modal fade show';
    modal.style.display = 'block';
    modal.style.backgroundColor = 'rgba(0, 0, 0, 0.5)';
    modal.innerHTML = `
        <div class="modal-dialog modal-dialog-centered">
            <div class="modal-content">
                <div class="modal-header">
                    <h5 class="modal-title">Confirmar acción</h5>
                    <button type="button" class="close" data-dismiss="modal" aria-label="Close">
                        <span aria-hidden="true">&times;</span>
                    </button>
                </div>
                <div class="modal-body">
                    <p>${mensaje}</p>
                </div>
                <div class="modal-footer">
                    <button type="button" class="btn btn-secondary" data-dismiss="modal">Cancelar</button>
                    <button type="button" class="btn btn-danger">Eliminar</button>
                </div>
            </div>
        </div>
    `;

    // Añadir el modal al body
    document.body.appendChild(modal);

    // Manejar el clic en el botón de eliminar
    const btnEliminar = modal.querySelector('.btn-danger');
    btnEliminar.addEventListener('click', () => {
        callback(true);
        document.body.removeChild(modal);
    });

    // Manejar el clic en el botón de cancelar
    const btnCancelar = modal.querySelector('.btn-secondary');
    btnCancelar.addEventListener('click', () => {
        callback(false);
        document.body.removeChild(modal);
    });

    // Manejar el clic en el botón de cerrar
    const btnCerrar = modal.querySelector('.close');
    btnCerrar.addEventListener('click', () => {
        callback(false);
        document.body.removeChild(modal);
    });

    // Manejar el clic fuera del modal
    modal.addEventListener('click', (e) => {
        if (e.target === modal) {
            callback(false);
            document.body.removeChild(modal);
        }
    });
}

// Nueva función para encontrar una posición cercana dentro del polígono (mantiene puntos dentro de la zona)
function encontrarPosicionCercana(x, y, points) {
    // Encontrar los límites del polígono
    let minX = Infinity, maxX = -Infinity, minY = Infinity, maxY = -Infinity;
    for (let i = 0; i < points.length; i += 2) {
        minX = Math.min(minX, points[i]);
        maxX = Math.max(maxX, points[i]);
        minY = Math.min(minY, points[i + 1]);
        maxY = Math.max(maxY, points[i + 1]);
    }

    // Intentar encontrar un punto válido en espiral
    const maxIntentos = 50;
    const incrementoAngulo = Math.PI / 8; // 22.5 grados
    let distancia = 5; // Distancia inicial
    const incrementoDistancia = 5;
    const maxDistancia = Math.min(maxX - minX, maxY - minY) * 0.2; // 20% del tamaño de la zona

    for (let intento = 0; intento < maxIntentos; intento++) {
        // Aumentar la distancia gradualmente en espiral
        distancia = Math.min(5 + (intento * incrementoDistancia), maxDistancia);
        
        // Probar varios ángulos en cada distancia
        for (let angulo = 0; angulo < Math.PI * 2; angulo += incrementoAngulo) {
            const nuevoX = x + distancia * Math.cos(angulo);
            const nuevoY = y + distancia * Math.sin(angulo);
            
            // Verificar si el punto es válido (dentro del polígono y lejos de los bordes)
            if (puntoEnPoligono(nuevoX, nuevoY, points)) {
                return { x: nuevoX, y: nuevoY };
            }
        }
    }

    // Si no se encuentra un punto válido, intentar encontrar cualquier punto válido en la zona
    const areaMuestreo = 100;
    for (let i = 0; i < areaMuestreo; i++) {
        const muestraX = minX + Math.random() * (maxX - minX);
        const muestraY = minY + Math.random() * (maxY - minY);
        
        if (puntoEnPoligono(muestraX, muestraY, points)) {
            return { x: muestraX, y: muestraY };
        }
    }

    // Como último recurso, encontrar el centroide del polígono
    let centroideX = 0, centroideY = 0;
    const numPuntos = points.length / 2;
    for (let i = 0; i < points.length; i += 2) {
        centroideX += points[i];
        centroideY += points[i + 1];
    }
    centroideX /= numPuntos;
    centroideY /= numPuntos;

    return { x: centroideX, y: centroideY };
}

// Function to load zone data from server and process it
function cargarDatosZonas() {
    $.ajax({
        url: '/obtener_cupos_disponibles',
        method: 'GET',
        success: function(data) {
            // Actualizar tabla de cupos y contador total primero
            actualizarTablaCupos(data);
            
            // Procesar actualizaciones visuales en lote
            const actualizaciones = [];
            
            data.forEach(function(item) {
                const zona = item[0];
                const citaciones = item[1];
                const cupos_zona = item[2];
                const cupos_libres = item[3];
                const color = calcularColor(citaciones, cupos_zona);
                
                const zonaObj = zonas.find(z => z.zona.name() === zona);
                if (zonaObj) {
                    actualizaciones.push(() => {
                        zonaObj.zona.fill(color.fill);
                        zonaObj.zona.stroke(color.stroke);
                        
                        const tooltipText = zonaObj.tooltip.findOne('Text');
                        if (tooltipText) {
                            tooltipText.text(
                                `${zona}\nCupos ocupados: ${citaciones}\n` +
                                `Cupos máximos: ${cupos_zona}\n` +
                                `Cupos libres: ${cupos_libres}`
                            );
                        }

                        actualizarPuntosCamiones(zonaObj, citaciones);
                    });
                    }
            });
            
            // Ejecutar todas las actualizaciones visuales de una vez
            actualizaciones.forEach(fn => fn());
            layer.batchDraw();
        },
        error: function(error) {
            console.error('Error al obtener los datos:', error);
        }
    });
}

// Modified zona events to show enhanced tooltip
function configurarEventosZona(zona, tooltip, nombre) {
    // Función throttle para el mousemove con un tiempo más apropiado
    const throttledMouseMove = throttle((pos) => {
        if (pos) {
            const scale = stage.scaleX();
            tooltip.position({
                x: (pos.x - stage.x()) / scale,
                y: (pos.y - stage.y()) / scale - 20 // Offset fijo para evitar parpadeo
            });
            layer.batchDraw();
        }
    }, 16);

    zona.on('mouseover', () => {
        // No mostrar tooltip si hay una herramienta activa
        if (!herramientaActiva) {
        const pos = stage.getPointerPosition();
        if (pos) {
            const scale = stage.scaleX();
            tooltip.scale({ x: 1/scale, y: 1/scale });
            tooltip.position({
                x: (pos.x - stage.x()) / scale,
                y: (pos.y - stage.y()) / scale - 20
            });
            tooltip.visible(true);
            document.body.style.cursor = 'pointer';
            layer.batchDraw();
            }
        }
    });

    zona.on('mousemove', () => {
        if (tooltip.visible() && !herramientaActiva) {
            throttledMouseMove(stage.getPointerPosition());
        }
    });

    zona.on('mouseout', () => {
        tooltip.visible(false);
        if (!herramientaActiva) {
        document.body.style.cursor = 'default';
        }
        layer.draw();
    });

    // Mantener el evento click separado y solo si no hay herramienta activa
    if (zona.attrs.id_zona && !isNaN(zona.attrs.id_zona)) {
        zona.on('click', function() {
            if (!herramientaActiva) {
            zonaClick(zona.attrs.id_zona);
            }
        });
    }
}



// Función mejorada para verificar si un punto está dentro del polígono
function puntoEnPoligono(x, y, points) {
    let dentro = false;
    const margen = 2; // Margen en píxeles desde el borde

    // Primero verificamos si el punto está dentro del polígono usando ray-casting
    for (let i = 0, j = points.length - 2; i < points.length; i += 2) {
        const xi = points[i], yi = points[i + 1];
        const xj = points[j], yj = points[j + 1];
        
        const intersecta = ((yi > y) !== (yj > y)) &&
            (x < (xj - xi) * (y - yi) / (yj - yi) + xi);
        if (intersecta) dentro = !dentro;
        
        j = i;
    }

    // Si el punto no está dentro del polígono, retornamos false
    if (!dentro) return false;

    // Ahora verificamos que el punto no esté demasiado cerca de ningún borde
    for (let i = 0, j = points.length - 2; i < points.length; i += 2) {
        const xi = points[i], yi = points[i + 1];
        const xj = points[j], yj = points[j + 1];

        // Calcular la distancia del punto al segmento de línea actual
        const distancia = distanciaPuntoALinea(x, y, xi, yi, xj, yj);
        
        // Si está demasiado cerca del borde, retornamos false
        if (distancia < margen) return false;
        
        j = i;
    }

    return true;
}

// Función auxiliar para calcular la distancia de un punto a una línea (mantiene puntos dentro de la zona)
function distanciaPuntoALinea(px, py, x1, y1, x2, y2) {
    const A = px - x1;
    const B = py - y1;
    const C = x2 - x1;
    const D = y2 - y1;

    const dot = A * C + B * D;
    const len_sq = C * C + D * D;
    let param = -1;

    if (len_sq !== 0) param = dot / len_sq;

    let xx, yy;

    if (param < 0) {
        xx = x1;
        yy = y1;
    } else if (param > 1) {
        xx = x2;
        yy = y2;
    } else {
        xx = x1 + param * C;
        yy = y1 + param * D;
    }

    const dx = px - xx;
    const dy = py - yy;

    return Math.sqrt(dx * dx + dy * dy);
}







// Variables globales para optimización de puntos de camiones







// Función simplificada para actualizar puntos de camiones
function actualizarPuntosCamiones(zonaObj, numCamiones) {
    const { zona, grupoZona } = zonaObj;
    const idZona = zona.attrs.id_zona;
    
    // Obtener puntos existentes
    const puntosExistentes = grupoZona.find('.punto-camion');
    const numPuntosExistentes = puntosExistentes.length;
    
    // Si el número es igual, solo actualizar colores
    if (numPuntosExistentes === numCamiones) {
        actualizarColoresPuntosSimple(idZona, puntosExistentes);
        return;
    }
    
    // Si hay más puntos de los necesarios, eliminar los sobrantes
    if (numPuntosExistentes > numCamiones) {
        for (let i = numCamiones; i < numPuntosExistentes; i++) {
            puntosExistentes[i].destroy();
        }
        layer.batchDraw();
        return;
    }
    
    // Si necesitamos más puntos, obtener datos y crearlos
    if (numPuntosExistentes < numCamiones) {
        obtenerDatosCamionesSimple(idZona, (camiones) => {
            const puntosNecesarios = numCamiones - numPuntosExistentes;
            const nuevasPosiciones = generarPosicionesSimples(zona.points(), puntosNecesarios);
            
            // Actualizar colores de puntos existentes
            actualizarColoresConDatos(puntosExistentes, camiones);
            
            // Crear nuevos puntos con colores correctos
            crearPuntosConColores(grupoZona, nuevasPosiciones, camiones, numPuntosExistentes);
            layer.batchDraw();
        });
    }
}

// Función simple para obtener datos de camiones
function obtenerDatosCamionesSimple(idZona, callback) {
    $.ajax({
        method: "GET",
        url: "/get_camiones_zona",
        data: { "id_zona": idZona },
        success: function(response) {
            if (response.success) {
                callback(response.camiones_zona || []);
            } else {
                console.error('Error al obtener datos de la zona:', response.error);
                callback([]);
            }
        },
        error: function(error) {
            console.error('Error al obtener datos de los camiones:', error);
            callback([]);
        }
    });
}

// Actualizar colores cuando solo tenemos los puntos existentes
function actualizarColoresPuntosSimple(idZona, puntosExistentes) {
    if (puntosExistentes.length === 0) return;
    
    obtenerDatosCamionesSimple(idZona, (camiones) => {
        actualizarColoresConDatos(puntosExistentes, camiones);
        layer.batchDraw();
    });
}

// Actualizar colores de puntos existentes con datos de camiones
function actualizarColoresConDatos(puntos, camiones) {
    puntos.forEach((punto, index) => {
        if (index < camiones.length) {
            const camion = camiones[index];
            const horas = parseInt(camion.Tiempo_transcurrido.split(' hrs ')[0]);
            punto.fill(horas >= 2 ? '#800080' : '#000000'); // Morado si >= 2 horas, negro si no
        }
    });
}

// Crear puntos simples con colores basados en tiempo
function crearPuntosConColores(grupoZona, posiciones, camiones, startIndex) {
    const scale = stage.scaleX();
    const radio = Math.min(2, 2 / scale);
    
    posiciones.forEach((pos, index) => {
        const camionIndex = startIndex + index;
        let color = '#000000'; // Negro por defecto
        
        // Si tenemos datos del camión, usar el color correcto
        if (camionIndex < camiones.length) {
            const camion = camiones[camionIndex];
            const horas = parseInt(camion.Tiempo_transcurrido.split(' hrs ')[0]);
            color = horas >= 2 ? '#800080' : '#000000'; // Morado si >= 2 horas
        }
        
        const punto = new Konva.Circle({
            x: pos.x,
            y: pos.y,
            radius: 4,
            fill: color,
            stroke: '#ffffff',
            strokeWidth: 0.5,
            name: 'punto-camion',
            opacity: 0.8,
            listening: false,
            perfectDrawEnabled: false
        });
        
        grupoZona.add(punto);
    });
}

// Función simple para generar posiciones aleatorias dentro de la zona
function generarPosicionesSimples(points, numPuntos) {
    if (numPuntos === 0) return [];
    
    // Calcular límites de la zona
    let minX = Infinity, maxX = -Infinity, minY = Infinity, maxY = -Infinity;
    for (let i = 0; i < points.length; i += 2) {
        minX = Math.min(minX, points[i]);
        maxX = Math.max(maxX, points[i]);
        minY = Math.min(minY, points[i + 1]);
        maxY = Math.max(maxY, points[i + 1]);
    }
    
    // Añadir margen
    const margenX = (maxX - minX) * 0.1;
    const margenY = (maxY - minY) * 0.1;
    minX += margenX;
    maxX -= margenX;
    minY += margenY;
    maxY -= margenY;
    
    const posiciones = [];
    let intentos = 0;
    const maxIntentos = numPuntos * 50; // Límite de intentos
    
    // Generar posiciones aleatorias válidas
    while (posiciones.length < numPuntos && intentos < maxIntentos) {
        const x = minX + Math.random() * (maxX - minX);
        const y = minY + Math.random() * (maxY - minY);
        
        // Verificación simple de punto en polígono
        if (puntoEnPoligonoSimple(x, y, points)) {
            posiciones.push({ x, y });
        }
        intentos++;
    }
    
    return posiciones;
}

// Verificación simple de punto en polígono (ray casting)
function puntoEnPoligonoSimple(x, y, points) {
    let dentro = false;
    
    for (let i = 0, j = points.length - 2; i < points.length; i += 2) {
        const xi = points[i], yi = points[i + 1];
        const xj = points[j], yj = points[j + 1];
        
        if (((yi > y) !== (yj > y)) && (x < (xj - xi) * (y - yi) / (yj - yi) + xi)) {
            dentro = !dentro;
        }
        j = i;
    }
    
    return dentro;
}

// Crear puntos simples sin pools ni cache
function crearPuntosSimples(grupoZona, posiciones) {
    const scale = stage.scaleX();
    const radio = Math.min(2, 2 / scale);
    
    posiciones.forEach(pos => {
        const punto = new Konva.Circle({
            x: pos.x,
            y: pos.y,
            radius: radio,
            fill: '#000000',
            stroke: '#ffffff',
            strokeWidth: 0.5,
            name: 'punto-camion',
            opacity: 0.8,
            listening: false,
            perfectDrawEnabled: false
        });
        
        grupoZona.add(punto);
    });
}

// Función para limpiar cache periódicamente
function limpiarCacheCamiones() {
    const ahora = Date.now();
    const tiempoExpiracion = 30000; // 30 segundos
    
    for (const [idZona, datos] of cacheCamionesZona.entries()) {
        if (ahora - datos.timestamp > tiempoExpiracion) {
            cacheCamionesZona.delete(idZona);
            ultimaActualizacionCamiones.delete(idZona);
        }
    }
}

// Limpiar cache cada 60 segundos
setInterval(limpiarCacheCamiones, 60000);

function actualizarTablaCupos(data) {
    const tbody = $('#cuposTable tbody');
    tbody.empty();
    let total_ocupados = 0;
    
    data.forEach(function(item) {
        const zona = item[0];
        const citaciones = item[1];
        const cupos_zona = item[2];
        const color = calcularColor(citaciones, cupos_zona);
        
        total_ocupados += citaciones;
        tbody.append(`
            <tr>
                <td><div class="zone-color" style="background-color: ${color.fill}; display: inline-block; vertical-align: middle;"></div> ${zona}</td>
                <td>${citaciones}</td>
                <td>${cupos_zona}</td>
            </tr>
        `);
    });
    
    tbody.append(`
        <tr>
            <td><div class="zone-color" style="background-color: gray; display: inline-block; vertical-align: middle;"></div> Total</td>
            <td>${total_ocupados}</td>
            <td></td>
        </tr>
    `);

    // Actualizar el contador en el botón de total de camiones
    const totalCountElement = document.querySelector('.total-camiones .total-count');
    if (totalCountElement) {
        totalCountElement.textContent = total_ocupados;
    }
}

// Variable global para llevar registro de zonas agregadas
let zonasAgregadas = new Set();

// Función para mostrar la lista de zonas disponibles
function mostrarListaZonasDisponibles(buttonElement) {
    // Eliminar lista existente si hay una
    const existingList = document.querySelector('.zonas-disponibles-lista');
    if (existingList) {
        existingList.remove();
        return;
    }

    // Crear el contenedor de la lista
    const listaContainer = document.createElement('div');
    listaContainer.className = 'zonas-disponibles-lista';
    listaContainer.style.cssText = `
        position: absolute;
        background: white;
        border: 1px solid #ccc;
        border-radius: 4px;
        box-shadow: 0 2px 10px rgba(0,0,0,0.1);
        z-index: 1000;
        max-height: 300px;
        overflow-y: auto;
        min-width: 200px;
    `;

    // Obtener la posición del botón
    const buttonRect = buttonElement.getBoundingClientRect();
    listaContainer.style.top = `${buttonRect.bottom + 5}px`;
    listaContainer.style.left = `${buttonRect.left}px`;

    // Función para cerrar la lista
    const cerrarLista = () => {
        if (listaContainer && listaContainer.parentNode) {
            listaContainer.remove();
        }
    };

    // Obtener lista de zonas disponibles desde el servidor
    $.ajax({
        url: '/obtener_zonas',
        method: 'GET',
        success: function(response) {
            if (response.success) {
                // Filtrar zonas que ya han sido agregadas
                const zonasDisponibles = response.zonas.filter(zonaData => {
                    const idZona = zonaData[15]; // ID_ZONA está en el índice 15
                    return !zonasAgregadas.has(idZona);
                });

                if (zonasDisponibles.length === 0) {
                    const noZonasItem = document.createElement('div');
                    noZonasItem.style.cssText = `
                        padding: 8px 16px;
                        color: #666;
                        font-style: italic;
                        text-align: center;
                    `;
                    noZonasItem.textContent = 'Todas las zonas ya han sido agregadas';
                    listaContainer.appendChild(noZonasItem);
                } else {
                    zonasDisponibles.forEach(zonaData => {
                        const zonaItem = document.createElement('div');
                        zonaItem.className = 'zona-disponible-item';
                        zonaItem.style.cssText = `
                            padding: 8px 16px;
                            cursor: pointer;
                            transition: background 0.2s;
                            border-bottom: 1px solid #eee;
                        `;
                        zonaItem.textContent = zonaData[0]; // Nombre de la zona
                        
                        zonaItem.addEventListener('mouseover', () => {
                            zonaItem.style.background = '#f0f0f0';
                        });
                        
                        zonaItem.addEventListener('mouseout', () => {
                            zonaItem.style.background = 'white';
                        });
                        
                        zonaItem.addEventListener('click', (e) => {
                            e.stopPropagation(); // Evitar que se propague el evento
                            cerrarLista(); // Cerrar la lista primero
                            
                            // Pequeño delay para asegurar que la lista se cierre antes de iniciar la colocación
                            setTimeout(() => {
                                iniciarColocacionZona(zonaData);
                            }, 50);
                        });
                        
                        listaContainer.appendChild(zonaItem);
                    });
                }
            } else {
                const errorItem = document.createElement('div');
                errorItem.style.cssText = `
                    padding: 8px 16px;
                    color: #666;
                    font-style: italic;
                `;
                errorItem.textContent = 'No hay zonas disponibles';
                listaContainer.appendChild(errorItem);
            }
        },
        error: function(error) {
            console.error('Error al obtener zonas disponibles:', error);
            const errorItem = document.createElement('div');
            errorItem.style.cssText = `
                padding: 8px 16px;
                color: #d32f2f;
                font-style: italic;
            `;
            errorItem.textContent = 'Error al cargar zonas';
            listaContainer.appendChild(errorItem);
        }
    });

    // Agregar la lista al documento
    document.body.appendChild(listaContainer);

    // Cerrar la lista al hacer click fuera - con delay para evitar cierre inmediato
    setTimeout(() => {
        document.addEventListener('click', function cerrarListaFuera(e) {
            if (!listaContainer.contains(e.target) && e.target !== buttonElement) {
                cerrarLista();
                document.removeEventListener('click', cerrarListaFuera);
            }
        });
    }, 100); // Delay de 100ms
}

// Función para iniciar la colocación de una zona
function iniciarColocacionZona(zonaData) {
    // Limpiar eventos previos por si acaso
    stage.off('mousemove.colocarZona');
    stage.off('click.colocarZona');

    // Obtener dimensiones del plano
    const planoImage = layer.findOne('Image');
    if (!planoImage) {
        console.error('No se encontró la imagen del plano');
        return;
    }

    // Procesar coordenadas de la zona
    const NOMBRE = 0;
    const CUPOS_OCUPADOS = 13;
    const CUPOS_MAXIMOS = 14;
    const ID_ZONA = 15;

    // Verificar si hay un tipo de forma específico
    const tipoForma = zonaData.tipo_forma || 'cuadrado'; // Por defecto cuadrado
    const points = convertirAFormaEstandar(zonaData, tipoForma);
    
    // Calcular centro basado en la nueva forma
    let minX = Math.min(...points.filter((_, i) => i % 2 === 0));
    let maxX = Math.max(...points.filter((_, i) => i % 2 === 0));
    let minY = Math.min(...points.filter((_, i) => i % 2 === 1));
    let maxY = Math.max(...points.filter((_, i) => i % 2 === 1));
    
    const centroOriginalX = (minX + maxX) / 2;
    const centroOriginalY = (minY + maxY) / 2;

    // Crear zona temporal que sigue al mouse
    const zonaTemporal = new Konva.Group({
        draggable: false,
        opacity: 0.7
    });

    const colorZona = calcularColor(zonaData[CUPOS_OCUPADOS], zonaData[CUPOS_MAXIMOS]);
    const forma = new Konva.Line({
        points: points,
        closed: true,
        fill: colorZona.fill,
        stroke: colorZona.stroke,
        strokeWidth: 2
    });

    zonaTemporal.add(forma);
    layer.add(zonaTemporal);

    // Variable para controlar si ya se colocó la zona
    let zonaColocada = false;

    // Función para actualizar la posición
    const updatePosition = () => {
        if (zonaColocada) return; // No actualizar si ya se colocó
        
        const pos = stage.getPointerPosition();
        if (pos) {
            const scale = stage.scaleX();
            const mouseX = (pos.x - stage.x()) / scale;
            const mouseY = (pos.y - stage.y()) / scale;
            
            // Calcular el offset para centrar la zona en el mouse
            const offsetX = mouseX - centroOriginalX;
            const offsetY = mouseY - centroOriginalY;
            
            zonaTemporal.position({
                x: offsetX,
                y: offsetY
            });
            layer.batchDraw();
        }
    };

    // Función para colocar la zona
    const colocarZona = (e) => {
        if (zonaColocada) return; // Evitar múltiples ejecuciones
        
        console.log('Colocando zona...');
        zonaColocada = true;
        
        // Remover eventos INMEDIATAMENTE
        stage.off('mousemove.colocarZona');
        stage.off('click.colocarZona');
        stage.off('mousedown.colocarZona');

        const pos = zonaTemporal.position();
        
        // Ajustar las coordenadas finales
        const finalPoints = points.map((p, i) => {
            return i % 2 === 0 ? p + pos.x : p + pos.y;
        });

        // Crear la zona definitiva
        crearZonaDefinitiva(zonaData, finalPoints, colorZona);

        // Eliminar la zona temporal
        zonaTemporal.destroy();
        
        // Desactivar el botón y restablecer el estado
        finalizarColocacionZona();
        
        // Redibujar
        layer.batchDraw();
        
        console.log('Zona colocada exitosamente');
    };

    // Seguir al mouse
    stage.on('mousemove.colocarZona', updatePosition);

    // Usar tanto click como mousedown para asegurar que se capture
    stage.on('click.colocarZona', colocarZona);
    stage.on('mousedown.colocarZona', colocarZona);

    // Posición inicial
    updatePosition();
    
    console.log('Iniciada colocación de zona:', zonaData[NOMBRE]);
}

// Nueva función para finalizar la colocación de zona
function finalizarColocacionZona() {
    // Desactivar el botón activo
    const botonActivo = document.querySelector('.toolbar .tool-button.active');
    if (botonActivo) {
        botonActivo.classList.remove('active');
    }
    
    // Restablecer variables globales
    herramientaActiva = null;
    
    // Restablecer el cursor
    stage.container().style.cursor = 'default';
    
    // Limpiar TODOS los eventos relacionados con colocación
    stage.off('mousemove.colocarZona');
    stage.off('click.colocarZona');
    stage.off('mousedown.colocarZona');
    
    console.log('Colocación de zona finalizada');
}

// Función para crear la zona definitiva
function crearZonaDefinitiva(zonaData, points, colorZona) {
    const NOMBRE = 0;
    const CUPOS_OCUPADOS = 13;
    const CUPOS_MAXIMOS = 14;
    const ID_ZONA = 15;

    const idZona = parseInt(zonaData[ID_ZONA]);

    // Registrar que esta zona ha sido agregada
    zonasAgregadas.add(idZona);

    // Crear elementos de la zona
    const grupoZona = new Konva.Group({ 
        draggable: false, 
        name: `grupo-${zonaData[NOMBRE]}`, 
        listening: true,
        perfectDrawEnabled: false
    });
    
    const zona = new Konva.Line({
        points: points,
        closed: true,
        fill: colorZona.fill,
        stroke: colorZona.stroke,
        strokeWidth: 3,
        opacity: 0.5,
        name: zonaData[NOMBRE],
        id_zona: idZona,
        draggable: false,
        hitStrokeWidth: 20,
        listening: true,
        perfectDrawEnabled: false,
        shadowForStrokeEnabled: false
    });

    // Crear puntos de control
    const puntosControl = [];
    for (let i = 0; i < points.length; i += 2) {
        const control = obtenerPuntoControlDelPool();
        control.x(points[i]);
        control.y(points[i + 1]);
        control.name(`control-${i/2}`);
        puntosControl.push(control);
    }

    // Obtener tooltip del pool
    const tooltip = obtenerTooltipDelPool();
    
    // Actualizar contenido del tooltip
    const tooltipText = tooltip.findOne('Text');
    const cuposOcupados = zonaData[CUPOS_OCUPADOS] || 0;
    const cuposMaximos = zonaData[CUPOS_MAXIMOS] || 0;
    const cuposLibres = cuposMaximos - cuposOcupados;
    
    tooltipText.text(
        `${zonaData[NOMBRE]}\nCupos ocupados: ${cuposOcupados}\nCupos máximos: ${cuposMaximos}\nCupos libres: ${cuposLibres}`
    );

    // Configurar eventos de la zona
    configurarEventosZona(zona, tooltip, zonaData[NOMBRE]);

    // Añadir click event
    zona.on('click', function() {
        zonaClick(idZona);
    });

    // Ensamblar elementos
    grupoZona.add(zona);
    puntosControl.forEach(control => {
        grupoZona.add(control);
    });

    layer.add(grupoZona);
    layer.add(tooltip);

    // Agregar a la lista de zonas
    zonas.push({
        grupoZona,
        zona,
        tooltip,
        puntosControl,
        nombre: zonaData[NOMBRE],
        id: zonaData[ID_ZONA]
    });

    console.log(`Zona ${zonaData[NOMBRE]} agregada al mapa`);
}

// Función para convertir cualquier forma en un cuadrado
function convertirAFormaEstandar(zonaData, tipoForma = 'cuadrado') {
    const CUPOS_MAXIMOS = 14;
    
    switch(tipoForma) {
        case 'cuadrado':
            const tamañoBase = 60;
            const tamañoCuadrado = tamañoBase + (zonaData[CUPOS_MAXIMOS] * 3);
            return [
                0, 0,
                tamañoCuadrado, 0,
                tamañoCuadrado, tamañoCuadrado,
                0, tamañoCuadrado
            ];
            
        case 'rectangulo':
            const ancho = 100 + (zonaData[CUPOS_MAXIMOS] * 2);
            const alto = 60 + (zonaData[CUPOS_MAXIMOS] * 1.5);
            return [
                0, 0,
                ancho, 0,
                ancho, alto,
                0, alto
            ];
            
        case 'circulo':
            // Aproximar un círculo con un octágono
            const radio = 40 + (zonaData[CUPOS_MAXIMOS] * 2);
            const puntos = [];
            for (let i = 0; i < 8; i++) {
                const angulo = (i * Math.PI * 2) / 8;
                puntos.push(
                    radio + Math.cos(angulo) * radio,
                    radio + Math.sin(angulo) * radio
                );
            }
            return puntos;
            
        default:
            return [0, 0, 80, 0, 80, 80, 0, 80]; // Cuadrado por defecto
    }
}

// Función para remover una zona del registro (cuando se elimina)
function removerZonaDelRegistro(idZona) {
    zonasAgregadas.delete(idZona);
    console.log(`Zona ${idZona} removida del registro, ahora está disponible nuevamente`);
}

// Función para guardar la posición de una zona
function guardarPosicionZona(idZona, points, accion = 'actualizar') {
    $.ajax({
        url: '/guardar_posicion_zona',
        method: 'POST',
        data: {
            id_zona: idZona,
            coordenadas: JSON.stringify(points),
            accion: accion, // 'agregar', 'mover', 'editar', 'eliminar'
            csrfmiddlewaretoken: $('[name=csrfmiddlewaretoken]').val()
        },
        success: function(response) {
            if (response.success) {
                console.log(`Posición de zona ${idZona} guardada exitosamente (${accion})`);
            } else {
                console.error('Error al guardar posición:', response.error);
            }
        },
        error: function(error) {
            console.error('Error al guardar posición de zona:', error);
        }
    });
}

function cargarPosicionesGuardadas(callback = null) {
    $.ajax({
        url: '/obtener_posiciones_zonas',
        method: 'GET',
        success: function(response) {
            if (response.success && response.posiciones) {
                console.log(`Cargando ${response.posiciones.length} zonas desde el servidor`);
                
                // Cargar zonas con sus posiciones guardadas
                response.posiciones.forEach(posicion => {
                    const zonaData = posicion.zona_data;
                    const points = JSON.parse(posicion.coordenadas);
                    const colorZona = calcularColor(zonaData[13], zonaData[14]);
                    const idZona = parseInt(zonaData[15]);
                    
                    // Registrar que esta zona está agregada
                    if (!isNaN(idZona)) {
                        zonasAgregadas.add(idZona);
                    }
                    
                    // Crear la zona en la posición guardada
                    const nuevaZona = crearZonaDefinitiva(zonaData, points, colorZona);
                    
                    if (nuevaZona) {
                        console.log(`Zona ${zonaData[0]} cargada exitosamente`);
                    }
                });
                
                layer.batchDraw();
                console.log(`${response.posiciones.length} zonas cargadas con posiciones guardadas`);
                
                // Ejecutar callback si se proporciona
                if (callback && typeof callback === 'function') {
                    callback();
                }
            } else {
                console.log('No hay zonas guardadas para cargar');
                
                // Ejecutar callback incluso si no hay zonas
                if (callback && typeof callback === 'function') {
                    callback();
                }
            }
        },
        error: function(error) {
            console.error('Error al cargar posiciones guardadas:', error);
            
            // Ejecutar callback incluso en caso de error
            if (callback && typeof callback === 'function') {
                callback();
            }
        }
    });
}

function actualizarColorZona(zona) {
    const idZona = zona.attrs.id_zona;
    if (!idZona) return;
    
    // Obtener datos actuales de la zona desde el servidor o cache local
    $.ajax({
        url: '/get_camiones_zona',
        method: 'GET',
        data: { id_zona: idZona },
        success: function(response) {
            if (response.success) {
                const ocupados = response.total_camiones || 0;
                const maximos = response.cupos_total || 0;
                const color = calcularColor(ocupados, maximos);
                
                // Solo actualizar si no está en edición
                if (zona !== zonaSeleccionadaEdicion) {
                    zona.fill(color.fill);
                    zona.stroke(color.stroke);
                    layer.batchDraw();
                }
            }
        },
        error: function(error) {
            console.error('Error al obtener datos de zona:', error);
        }
    });
}

function guardarEdicionToolbarConDimensionesFijas() {
    if (!zonaSeleccionadaEdicion) {
        Swal.fire({
            icon: 'warning',
            title: 'Ninguna zona seleccionada',
            text: 'Selecciona una zona para guardar los cambios.',
            confirmButtonText: 'Aceptar'
        });
        return;
    }

    const idZona = zonaSeleccionadaEdicion.attrs.id_zona;
    const coordenadasPlano = zonaSeleccionadaEdicion.points();
    
    if (!idZona) {
        console.error('ID de zona no encontrado');
        return;
    }

    // Convertir coordenadas del plano a coordenadas reales para guardar
    const coordenadasReales = [];
    for (let i = 0; i < coordenadasPlano.length; i += 2) {
        const coordReal = coordenadasPlanoAReales(coordenadasPlano[i], coordenadasPlano[i + 1]);
        coordenadasReales.push(coordReal.x, coordReal.y);
    }

    console.log('Guardando zona editada:', zonaSeleccionadaEdicion.name(), 'ID:', idZona);
    console.log('Coordenadas del plano:', coordenadasPlano);
    console.log('Coordenadas reales para BD:', coordenadasReales);
    
    // Obtener token CSRF
    function getCookie(name) {
        let cookieValue = null;
        if (document.cookie && document.cookie !== '') {
            const cookies = document.cookie.split(';');
            for (let i = 0; i < cookies.length; i++) {
                const cookie = cookies[i].trim();
                if (cookie.substring(0, name.length + 1) === (name + '=')) {
                    cookieValue = decodeURIComponent(cookie.substring(name.length + 1));
                    break;
                }
            }
        }
        return cookieValue;
    }
    
    const csrftoken = getCookie('csrftoken');
    
    // Llamada AJAX para guardar las coordenadas reales
    $.ajax({
        url: '/actualizar_coordenadas_zona',
        method: 'POST',
        data: {
            id_zona: idZona,
            coordenadas: JSON.stringify(coordenadasReales), // Enviar coordenadas reales
            csrfmiddlewaretoken: csrftoken
        },
        success: function(response) {
            if (response.success) {
                console.log('Coordenadas guardadas exitosamente');
                
                Swal.fire({
                    icon: 'success',
                    title: '¡Guardado!',
                    text: 'La zona ha sido actualizada correctamente.',
                    showConfirmButton: false,
                    timer: 2000,
                    timerProgressBar: true,
                    toast: true,
                    position: 'top-end'
                });
                
                // Resetear el plano completo
                resetearPlanoCompleto();
                
                // Finalizar edición
                finalizarEdicionToolbar();
            } else {
                console.error('Error al guardar coordenadas:', response.error);
                Swal.fire({
                    icon: 'error',
                    title: 'Error',
                    text: 'Error al guardar los cambios: ' + response.error,
                    confirmButtonText: 'Aceptar'
                });
            }
        },
        error: function(error) {
            console.error('Error en la petición AJAX:', error);
            Swal.fire({
                icon: 'error',
                title: 'Error de conexión',
                text: 'Error al guardar los cambios. Por favor, intente nuevamente.',
                confirmButtonText: 'Aceptar'
            });
        }
    });
}

// ACTUALIZAR guardarMovimientoToolbar para usar conversión de coordenadas:
function guardarMovimientoToolbarConDimensionesFijas() {
    if (!zonaSeleccionadaMover) {
        Swal.fire({
            icon: 'warning',
            title: 'Ninguna zona seleccionada',
            text: 'Selecciona una zona para guardar el movimiento.',
            confirmButtonText: 'Aceptar'
        });
        return;
    }

    const idZona = zonaSeleccionadaMover.attrs.id_zona;
    const coordenadasPlano = zonaSeleccionadaMover.points();
    
    if (!idZona) {
        console.error('ID de zona no encontrado');
        return;
    }

    // Convertir coordenadas del plano a coordenadas reales para guardar
    const coordenadasReales = [];
    for (let i = 0; i < coordenadasPlano.length; i += 2) {
        const coordReal = coordenadasPlanoAReales(coordenadasPlano[i], coordenadasPlano[i + 1]);
        coordenadasReales.push(coordReal.x, coordReal.y);
    }

    console.log('Guardando zona movida:', zonaSeleccionadaMover.name(), 'ID:', idZona);
    console.log('Coordenadas del plano:', coordenadasPlano);
    console.log('Coordenadas reales para BD:', coordenadasReales);
    
    // Obtener token CSRF
    function getCookie(name) {
        let cookieValue = null;
        if (document.cookie && document.cookie !== '') {
            const cookies = document.cookie.split(';');
            for (let i = 0; i < cookies.length; i++) {
                const cookie = cookies[i].trim();
                if (cookie.substring(0, name.length + 1) === (name + '=')) {
                    cookieValue = decodeURIComponent(cookie.substring(name.length + 1));
                    break;
                }
            }
        }
        return cookieValue;
    }
    
    const csrftoken = getCookie('csrftoken');
    
    // Llamada AJAX para guardar las coordenadas reales
    $.ajax({
        url: '/actualizar_coordenadas_zona',
        method: 'POST',
        data: {
            id_zona: idZona,
            coordenadas: JSON.stringify(coordenadasReales), // Enviar coordenadas reales
            csrfmiddlewaretoken: csrftoken
        },
        success: function(response) {
            if (response.success) {
                console.log('Posición guardada exitosamente');
                
                Swal.fire({
                    icon: 'success',
                    title: '¡Guardado!',
                    text: 'La zona ha sido movida correctamente.',
                    showConfirmButton: false,
                    timer: 2000,
                    timerProgressBar: true,
                    toast: true,
                    position: 'top-end'
                });
                
                // Resetear el plano completo
                resetearPlanoCompleto();
                
                // Finalizar movimiento
                finalizarMovimientoToolbar();
            } else {
                console.error('Error al guardar posición:', response.error);
                Swal.fire({
                    icon: 'error',
                    title: 'Error',
                    text: 'Error al guardar el movimiento: ' + response.error,
                    confirmButtonText: 'Aceptar'
                });
            }
        },
        error: function(error) {
            console.error('Error en la petición AJAX:', error);
            Swal.fire({
                icon: 'error',
                title: 'Error de conexión',
                text: 'Error al guardar el movimiento. Por favor, intente nuevamente.',
                confirmButtonText: 'Aceptar'
            });
        }
    });
}

// ACTUALIZAR finalizarDibujoZona para usar conversión de coordenadas (FUNCIÓN COMPLETA):
function finalizarDibujoZonaConDimensionesFijas() {
    if (!dibujandoZona) {
        console.log('No hay dibujo activo para finalizar');
        return;
    }
    
    if (puntosTemporales.length < 3) {
        alert('Se necesitan al menos 3 puntos para crear una zona');
        return;
    }
    
    // Limitar a 4 puntos si hay más
    if (puntosTemporales.length > 4) {
        puntosTemporales = puntosTemporales.slice(0, 4);
        console.log('Se han limitado los puntos a 4:', puntosTemporales);
    }

    console.log('Finalizando dibujo con puntos del plano:', puntosTemporales);
    
    // Convertir coordenadas del plano a coordenadas reales para enviar
    const coordenadasReales = [];
    puntosTemporales.forEach(punto => {
        const coordReal = coordenadasPlanoAReales(punto[0], punto[1]);
        coordenadasReales.push(coordReal.x, coordReal.y);
    });
    
    console.log('Coordenadas reales para enviar:', coordenadasReales);
    
    // Obtener el token CSRF de las cookies (método estándar en Django)
    function getCookie(name) {
        let cookieValue = null;
        if (document.cookie && document.cookie !== '') {
            const cookies = document.cookie.split(';');
            for (let i = 0; i < cookies.length; i++) {
                const cookie = cookies[i].trim();
                if (cookie.substring(0, name.length + 1) === (name + '=')) {
                    cookieValue = decodeURIComponent(cookie.substring(name.length + 1));
                    break;
                }
            }
        }
        return cookieValue;
    }
    const csrftoken = getCookie('csrftoken');
    
    // Crear el modal para solicitar información de la zona
    const modal = document.createElement('div');
    modal.className = 'modal fade show';
    modal.style.display = 'block';
    modal.style.backgroundColor = 'rgba(0, 0, 0, 0.5)';
    modal.innerHTML = `
        <div class="modal-dialog modal-dialog-centered">
            <div class="modal-content">
                <div class="modal-header">
                    <h5 class="modal-title">Información de la zona</h5>
                    <button type="button" class="close" data-dismiss="modal" aria-label="Close">
                        <span aria-hidden="true">&times;</span>
                    </button>
                </div>
                <div class="modal-body">
                    <form id="zonaForm">
                        <div class="form-group">
                            <label for="nombreZona">Nombre de la zona:</label>
                            <input type="text" class="form-control" id="nombreZona" name="nombreZona" required>
                        </div>
                        <div class="form-group">
                            <label for="cupoMaximo">Cupo máximo de la zona:</label>
                            <input type="number" class="form-control" id="cupoMaximo" name="cupoMaximo" min="1" required>
                        </div>
                        <div class="form-group" style="display:none;">
                            <label>Coordenadas seleccionadas:</label>
                            <textarea class="form-control" id="coordenadasZona" rows="4" readonly>${JSON.stringify(coordenadasReales)}</textarea>
                        </div>
                    </form>
                </div>
                <div class="modal-footer">
                    <button type="button" class="btn btn-secondary" id="btnCancelar">Cancelar</button>
                    <button type="button" class="btn btn-primary" id="btnGuardar">Guardar</button>
                </div>
            </div>
        </div>
    `;

    // Añadir el modal al body
    document.body.appendChild(modal);

    // Función simple para cerrar el modal y limpiar el estado
    const cerrarModal = () => {
        document.body.removeChild(modal);
        cancelarDibujoZona();
        
        // Desactivar el botón de la barra de herramientas
        const botonActivo = document.querySelector('.tool-button.active');
        if (botonActivo) {
            botonActivo.classList.remove('active');
        }
    };

    // Manejar clic en Cancelar y clic fuera del modal
    modal.querySelector('#btnCancelar').addEventListener('click', cerrarModal);
    modal.querySelector('.close').addEventListener('click', cerrarModal);
    modal.addEventListener('click', (e) => {
        if (e.target === modal) cerrarModal();
    });

    // Manejar el clic en el botón de guardar
    const btnGuardar = modal.querySelector('#btnGuardar');
    btnGuardar.addEventListener('click', () => {
        const nombreZona = document.getElementById('nombreZona').value.trim();
        const cupoMaximo = parseInt(document.getElementById('cupoMaximo').value);

        // Validar los campos
        if (!nombreZona) {
            alert('Por favor, ingrese un nombre de zona válido');
            return;
        }

        if (isNaN(cupoMaximo) || cupoMaximo <= 0) {
            alert('Por favor, ingrese un cupo máximo válido');
            return;
        }

        console.log('Creando zona con nombre:', nombreZona, 'cupo:', cupoMaximo);
        
        // Preparar datos para enviar por AJAX
        const datosZona = {
            nombre: nombreZona,
            cupoMaximo: cupoMaximo,
            coordenadas: coordenadasReales // Usar coordenadas reales convertidas
        };
        
        // Realizar la llamada AJAX para guardar la zona en el servidor
        $.ajax({
            url: '/guardar_zona',
            method: 'POST',
            contentType: 'application/json',
            data: JSON.stringify(datosZona),
            headers: {
                'X-CSRFToken': csrftoken
            },
            success: function(response) {
                console.log('Zona guardada correctamente:', response);
                
                // Crear la zona en el mapa usando las coordenadas del plano
                crearZonaEnMapaConDimensionesFijas(nombreZona, cupoMaximo, puntosTemporales);
                
                // Cerrar el modal y finalizar el dibujo
                cerrarModal();
                
                // Mostrar mensaje de éxito
                Swal.fire({
                    icon: 'success',
                    title: '¡Guardado!',
                    text: 'Zona guardada correctamente',
                    showConfirmButton: false,
                    timer: 2000,
                    timerProgressBar: true,
                    toast: true,
                    position: 'top-end'
                });
                
                // Actualizar la lista de zonas
                cargarDatosZonas();
            },
            error: function(error) {
                console.error('Error al guardar la zona:', error);
                Swal.fire({
                    icon: 'error',
                    title: 'Error',
                    text: 'Error al guardar la zona: ' + (error.responseText || 'Error de conexión'),
                    confirmButtonText: 'Aceptar'
                });
            }
        });
    });

    // Permitir enviar el formulario con Enter
    const form = modal.querySelector('#zonaForm');
    form.addEventListener('keypress', (e) => {
        if (e.key === 'Enter') {
            e.preventDefault();
            btnGuardar.click();
        }
    });

    // Dar foco al campo de nombre de zona
    setTimeout(() => {
        document.getElementById('nombreZona').focus();
    }, 100);
}

// NUEVA función auxiliar para crear zona en el mapa con dimensiones fijas
function crearZonaEnMapaConDimensionesFijas(nombreZona, cupoMaximo, puntosTemporales) {
    // Color por defecto para la zona (verde)
    const colorZona = '#4caf50';
    
    // Crear la zona usando las coordenadas del plano (ya están en el sistema correcto)
    const zona = new Konva.Line({
        points: puntosTemporales.flat(),
        closed: true,
        fill: colorZona,
        stroke: colorZona,
        strokeWidth: 3,
        opacity: 0.5,
        name: nombreZona,
        draggable: false,
        listening: true,
        perfectDrawEnabled: false,
        shadowForStrokeEnabled: false
    });

    // Crear un grupo para la zona y sus puntos de control
    const grupoZona = new Konva.Group({
        draggable: false,
        name: `grupo-${nombreZona}`,
        listening: true,
        perfectDrawEnabled: false
    });

    // Añadir tooltip
    const tooltip = new Konva.Label({
        x: 0,
        y: 0,
        opacity: 0.9,
        visible: false,
        listening: false,
        perfectDrawEnabled: false
    });

    tooltip.add(
        new Konva.Tag({
            fill: '#fff',
            stroke: '#e0e0e0',
            strokeWidth: 1,
            cornerRadius: 4,
            shadowColor: 'black',
            shadowBlur: 10,
            shadowOffset: { x: 2, y: 2 },
            shadowOpacity: 0.2
        })
    );

    tooltip.add(
        new Konva.Text({
            text: `${nombreZona}\nCupo: 0/${cupoMaximo}`,
            fontFamily: 'Arial',
            fontSize: 14,
            padding: 8,
            fill: '#333',
            align: 'center'
        })
    );

    // Añadir puntos de control
    const puntosControl = puntosTemporales.map((punto, index) => {
        const control = obtenerPuntoControlDelPool();
        control.x(punto[0]);
        control.y(punto[1]);
        control.radius(3);
        control.fill('#00ff00');
        control.stroke('white');
        control.strokeWidth(1);
        control.draggable(false);
        control.visible(false);
        control.name(`control-${index}`);
        control.listening(false);
        control.perfectDrawEnabled(false);

        control.on('dragmove', () => {
            const points = zona.points();
            const index = parseInt(control.name().split('-')[1]);
            points[index * 2] = control.x();
            points[index * 2 + 1] = control.y();
            zona.points(points);
            layer.batchDraw();
        });

        return control;
    });

    // Configurar eventos de la zona
    configurarEventosZona(zona, tooltip, nombreZona);

    // Añadir elementos al grupo
    grupoZona.add(zona);
    puntosControl.forEach(control => {
        grupoZona.add(control);
    });

    // Añadir todo a la capa
    layer.add(grupoZona);
    layer.add(tooltip);

    // Almacenar la zona en el array de zonas
    const nuevaZona = {
        grupoZona: grupoZona,
        zona: zona,
        tooltip: tooltip,
        puntosControl: puntosControl,
        nombre: nombreZona,
        cupoMaximo: cupoMaximo
    };
    
    zonas.push(nuevaZona);

    console.log('Zona creada en el mapa con dimensiones fijas:', nuevaZona);
    console.log('Total de zonas:', zonas.length);
    
    layer.draw();
}

// NUEVA función para mostrar indicador de zoom
function mostrarIndicadorZoom() {
    // Remover indicador existente
    const indicadorExistente = document.getElementById('zoom-indicator');
    if (indicadorExistente) {
        indicadorExistente.remove();
    }
    
    // Crear nuevo indicador
    const indicador = document.createElement('div');
    indicador.id = 'zoom-indicator';
    indicador.className = 'zoom-indicator';
    
    // Función para actualizar el indicador
    function actualizarIndicador() {
        const escala = stage.scaleX();
        const porcentaje = Math.round(escala * 100);
        indicador.textContent = `Zoom: ${porcentaje}%`;
    }
    
    // Actualizar inicialmente
    actualizarIndicador();
    
    // Agregar al contenedor
    const container = document.getElementById('container');
    container.appendChild(indicador);
    
    // Actualizar cuando cambie el zoom
    stage.on('scaleChange', actualizarIndicador);
    
    return indicador;
}

$(document).ready(function() {
    cargarImagenPlano();
    // Centrar el contenedor inicialmente
    centrarContenedorPlano();
    
    // ... resto del código de inicialización existente ...
    cargarZonasDesdeServidor();
    configurarActualizacionPeriodica();
    
    document.addEventListener('visibilitychange', function() {
        if (document.visibilityState === 'visible') {
            if (!refreshInterval) {
                configurarActualizacionPeriodica();
            }
            cargarDatosZonas();
        }
    });
    
    document.addEventListener('keydown', handleKeyDownEdicion);
});