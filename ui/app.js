// app.js - Toda la interfaz salvo las llamadas: login, biblioteca, detalle de juego, Configuración,
// amigos, deseados, chat, publicaciones y menú de cada amigo.
// Habla con Python mediante window.pywebview.api.<método> (ver la clase API en gui_app.py).
// Regla de seguridad: lo que escribe un usuario se muestra con textContent, nunca con innerHTML.

let usuarioActual = null;
let perfilActual = null;
let consolaSeleccionada = 'todas';

// Alterna entre los formularios de entrar y registrarse.
function toggleAuth(isRegister) {
    document.getElementById('login-form').style.display = isRegister ? 'none' : 'block';
    document.getElementById('register-form').style.display = isRegister ? 'block' : 'none';
    document.getElementById('auth-error').innerText = '';
}

// Formulario de entrar. Si se pidió recordar la sesión, luego pide el código del correo.
async function login() {
    const email = document.getElementById('login-email').value;
    const pass = document.getElementById('login-pass').value;
    const err = document.getElementById('auth-error');

    if (!email || !pass) {
        err.innerText = "Completá todos los campos.";
        return;
    }

    try {
        const recordar = document.getElementById('login-remember').checked;
        const res = await window.pywebview.api.iniciar_sesion(email, pass, recordar);
        if (res && res.exito) {
            usuarioActual = res.usuario;
            await cargarPantallaPrincipal();
            if (res.requiere_codigo) {
                abrirModalCodigo(email);
            } else if (res.aviso) {
                alert(res.aviso);
            }
        } else {
            err.innerText = res ? res.error : "Error de autenticación.";
        }
    } catch (e) {
        err.innerText = "Error en login: " + e;
    }
}

// Formulario de registro.
async function registrar() {
    const username = document.getElementById('reg-username').value;
    const email = document.getElementById('reg-email').value;
    const pass = document.getElementById('reg-pass').value;
    const err = document.getElementById('auth-error');

    if (!username || !email || !pass) {
        err.innerText = "Completá todos los campos.";
        return;
    }

    try {
        const res = await window.pywebview.api.registrar_usuario(email, pass, username);
        if (res && res.exito) {
            usuarioActual = res.usuario;
            await cargarPantallaPrincipal();
        } else {
            err.innerText = res ? res.error : "Error al registrar.";
        }
    } catch (e) {
        err.innerText = "Error en registro: " + e;
    }
}

// Pasa del login a la app y carga los datos de la cuenta.
async function cargarPantallaPrincipal() {
    reiniciarEstadoUI();   // arranca siempre limpio: nada de la cuenta anterior
    document.getElementById('auth-screen').style.display = 'none';
    document.getElementById('app-screen').style.display = 'flex';

    await cargarPerfilUsuario();
    await cargarConsolas();
    await filtrarCatalogo();
    iniciarInsignias();
    llamadasIniciar();
    llavesIniciar();
}

// Pinta nombre y foto; si no hay perfil usa los datos del registro.
async function cargarPerfilUsuario() {
    try {
        const res = await window.pywebview.api.obtener_perfil();
        
        if (res && res.exito && res.perfil) {
            perfilActual = res.perfil;
        } else if (usuarioActual && usuarioActual.user_metadata) {
            perfilActual = {
                username: usuarioActual.user_metadata.username || usuarioActual.email.split('@')[0],
                bio: '',
                avatar_url: ''
            };
        }

        if (perfilActual) {
            const username = perfilActual.username || "Usuario";
            
            document.getElementById('header-username').innerText = username;
            document.getElementById('profile-username').innerText = username;
            document.getElementById('profile-bio').value = perfilActual.bio || '';

            const avatarUrl = (perfilActual.avatar_url && perfilActual.avatar_url.trim() !== "") 
                ? perfilActual.avatar_url 
                : `https://ui-avatars.com/api/?name=${encodeURIComponent(username)}&background=45A29E&color=fff`;

            document.getElementById('header-avatar').src = avatarUrl;
            document.getElementById('profile-avatar').src = avatarUrl;
        }
    } catch (e) {
        console.error("Error al cargar perfil:", e);
    }
}

// Abre tu perfil.
function abrirPerfil() {
    document.getElementById('profile-modal').style.display = 'flex';
    cargarMiActividad();
}

// Cierra tu perfil.
function cerrarPerfil() {
    document.getElementById('profile-modal').style.display = 'none';
}

// Guarda la biografía.
async function guardarPerfil() {
    const nuevaBio = document.getElementById('profile-bio').value;
    const res = await window.pywebview.api.actualizar_perfil(nuevaBio);
    if (res && res.exito) {
        alert("Perfil actualizado correctamente.");
        if (res.perfil) perfilActual = res.perfil;
        cerrarPerfil();
        await cargarPerfilUsuario();
    } else {
        alert("Error al actualizar biografía: " + (res ? res.error : "error desconocido"));
    }
}

// Pide un nombre nuevo y lo guarda.
async function cambiarNombreUsuario() {
    const nombreActual = perfilActual ? (perfilActual.username || "") : "";
    const nuevoUsername = prompt("Ingresá tu nuevo nombre de usuario:", nombreActual);

    if (nuevoUsername === null) return;
    if (nuevoUsername.trim() === "" || nuevoUsername === nombreActual) return;

    try {
        const res = await window.pywebview.api.cambiar_username(nuevoUsername.trim());
        if (res && res.exito) {
            alert("¡Nombre de usuario actualizado con éxito!");
            if (res.perfil) perfilActual = res.perfil;
            await cargarPerfilUsuario();
        } else {
            alert("No se pudo cambiar el nombre: " + (res ? res.error : "Error desconocido"));
        }
    } catch (e) {
        alert("Error al comunicarse con el servidor: " + e);
    }
}

// Abre el selector de archivos y actualiza la foto.
async function subirNuevaFoto() {
    try {
        const res = await window.pywebview.api.seleccionar_foto_avatar();
        if (res && res.exito) {
            if (res.perfil) {
                perfilActual = res.perfil;
            } else {
                if (!perfilActual) perfilActual = {};
                perfilActual.avatar_url = res.avatar_url;
            }
            
            document.getElementById('header-avatar').src = res.avatar_url;
            document.getElementById('profile-avatar').src = res.avatar_url;
            alert("Foto de perfil actualizada.");
        } else if (res && res.error && res.error !== "No se seleccionó ninguna imagen.") {
            alert("Error al subir foto: " + res.error);
        }
    } catch (e) {
        alert("Error al abrir selector de imagen: " + e);
    }
}

// Llena la lista de consolas de la barra lateral.
async function cargarConsolas() {
    try {
        const consolas = await window.pywebview.api.obtener_consolas();
        const list = document.getElementById('console-list');
        list.innerHTML = `<li class="${consolaSeleccionada === 'todas' ? 'active' : ''}" onclick="seleccionarConsola('todas', this)">Todas</li>`;

        if (consolas && consolas.length > 0) {
            consolas.forEach(c => {
                const consolaId = c.id || (Array.isArray(c) ? c[0] : null);
                const nombreConsola = c.nombre || (Array.isArray(c) ? c[1] : "Consola");
                
                const li = document.createElement('li');
                li.innerText = nombreConsola;
                if (consolaId === consolaSeleccionada) li.classList.add('active');
                li.onclick = () => seleccionarConsola(consolaId, li);
                list.appendChild(li);
            });
        }
    } catch (e) {
        console.error("Error al cargar consolas:", e);
    }
}

// Filtra la biblioteca por la consola elegida.
function seleccionarConsola(id, elemento) {
    consolaSeleccionada = id;
    volverABiblioteca();
    
    const items = document.querySelectorAll('#console-list li');
    items.forEach(item => item.classList.remove('active'));
    if (elemento) elemento.classList.add('active');

    filtrarCatalogo();
}

// Vuelve a pedir los juegos según la búsqueda y la consola.
async function filtrarCatalogo() {
    try {
        const textoBusqueda = document.getElementById('search-input').value;
        const juegos = await window.pywebview.api.obtener_juegos_filtrados(textoBusqueda, consolaSeleccionada);
        renderizarJuegos(juegos);
    } catch (e) {
        console.error("Error al filtrar catálogo:", e);
    }
}

// Abre un juego; si tiene varias versiones o discos, pide elegir primero.
async function lanzarJuego(gameId) {
    try {
        const res = await window.pywebview.api.lanzar_juego(gameId);
        
        if (res && res.exito) {
            return;
        } else if (res && res.requiere_seleccion) {
            let mensaje = "Se encontraron varias opciones para este juego. Elegí cuál abrir:\n\n";
            res.opciones.forEach((op, index) => {
                mensaje += `${index + 1}: ${op.descripcion}\n`;
            });

            const seleccion = prompt(mensaje, "1");
            if (seleccion !== null) {
                const indice = parseInt(seleccion.trim()) - 1;
                if (!isNaN(indice) && indice >= 0 && indice < res.opciones.length) {
                    const elegido = await window.pywebview.api.lanzar_juego(res.opciones[indice].id, true);
                    if (!elegido || !elegido.exito) {
                        alert("No se pudo iniciar el juego: " + (elegido ? elegido.error : "Error desconocido"));
                    }
                }
            }
        } else {
            alert("No se pudo iniciar el juego: " + (res ? res.error : "Error desconocido"));
        }
    } catch (e) {
        console.error("Error al lanzar juego:", e);
    }
}

// Crea la carátula con plan B: file://, luego base64, luego el emoji.
function crearPortada(juego, nombre) {
    const wrapper = document.createElement('div');
    wrapper.className = 'game-cover-wrapper';

    const fallback = document.createElement('div');
    fallback.className = 'game-cover-fallback';
    fallback.textContent = '🎮';

    if (!juego.portada_url) {
        wrapper.appendChild(fallback);
        return wrapper;
    }

    const img = document.createElement('img');
    img.alt = nombre;
    img.loading = 'lazy';

    let reintentado = false;
    img.onerror = async () => {
        // Plan B: pedirle la imagen en base64 a Python; si tampoco, queda el emoji
        if (!reintentado && juego.portada_path) {
            reintentado = true;
            try {
                const dataUri = await window.pywebview.api.obtener_portada_data_uri(juego.portada_path);
                if (dataUri) {
                    img.src = dataUri;
                    return;
                }
            } catch (e) { /* se muestra el emoji */ }
        }
        img.remove();
        wrapper.appendChild(fallback);
    };

    img.src = juego.portada_url;
    wrapper.appendChild(img);
    return wrapper;
}

// Dibuja la grilla de juegos.
function renderizarJuegos(juegos) {
    const grid = document.getElementById('game-grid');
    grid.innerHTML = '';

    if (!juegos || juegos.length === 0) {
        grid.innerHTML = '<p style="color: #a0a0a0;">No se encontraron juegos.</p>';
        return;
    }

    juegos.forEach(juego => {
        const nombreJuego = juego.nombre || juego.titulo || juego.title || juego.name || '';
        const consolaJuego = juego.nombre_consola || juego.consola || '';

        const card = document.createElement('div');
        card.className = 'game-card';
        card.appendChild(crearPortada(juego, nombreJuego));

        const info = document.createElement('div');
        info.className = 'game-info';
        const titulo = document.createElement('h3');
        titulo.textContent = nombreJuego;
        titulo.title = nombreJuego;
        const consola = document.createElement('p');
        consola.style.cssText = 'color: #45A29E; font-size: 0.82em;';
        consola.textContent = consolaJuego;
        info.append(titulo, consola);
        card.appendChild(info);

        card.onclick = () => abrirDetalle(juego);
        grid.appendChild(card);
    });
}

let escaneoEnCurso = false;

// Botón Escanear: inicia el proceso en segundo plano.
async function escanearRoms() {
    if (escaneoEnCurso) return;
    try {
        const res = await window.pywebview.api.escanear_roms();
        if (!res || !res.exito) {
            alert("No se pudo iniciar el escaneo.");
            return;
        }
        seguirEscaneo();
    } catch (e) {
        console.error("Error al escanear ROMs:", e);
        alert("Hubo un error al iniciar el escaneo.");
    }
}

// Consulta el progreso y refresca la biblioteca cuando hay novedades.
async function seguirEscaneo() {
    escaneoEnCurso = true;
    const btn = document.getElementById('btn-scan');
    // El progreso se muestra en la cabecera y también dentro de Configuración
    const label = { set textContent(t) {
        ['scan-status', 'scan-status-config'].forEach(id => {
            const el = document.getElementById(id);
            if (el) el.textContent = t;
        });
    } };
    btn.disabled = true;

    let ultimo = '';
    let estado = null;
    try {
        do {
            await new Promise(r => setTimeout(r, 1500));
            estado = await window.pywebview.api.obtener_estado_escaneo();
            if (!estado) break;

            if (estado.portadas_total > 0) {
                label.textContent = `Carátulas ${estado.portadas_hechas}/${estado.portadas_total}`;
            } else {
                label.textContent = `${estado.fase || 'Escaneando…'} ${estado.juegos || ''}`.trim();
            }

            // Refrescar el catálogo solo cuando hay novedades
            const firma = `${estado.juegos}|${estado.portadas_ok}`;
            if (firma !== ultimo) {
                ultimo = firma;
                await cargarConsolas();
                await filtrarCatalogo();
            }
        } while (estado && estado.activo);

        await cargarConsolas();
        await filtrarCatalogo();
        if (document.getElementById('settings-modal').style.display === 'flex') cargarRutasConfig();
        label.textContent = estado && estado.portadas_total > 0
            ? `Listo: ${estado.portadas_ok}/${estado.portadas_total} carátulas`
            : 'Escaneo finalizado';
    } catch (e) {
        console.error("Error siguiendo el escaneo:", e);
        label.textContent = '';
    } finally {
        btn.disabled = false;
        escaneoEnCurso = false;
        setTimeout(() => { label.textContent = ''; }, 5000);
    }
}

// ============================================================================
// SESIÓN RECORDADA ("Recuérdame")
// ============================================================================

// Al abrir la app, entra solo si había una sesión recordada.
async function intentarRestaurarSesion() {
    try {
        const res = await window.pywebview.api.restaurar_sesion();
        if (res && res.exito) {
            usuarioActual = res.usuario;
            await cargarPantallaPrincipal();
        }
    } catch (e) {
        console.error("Error al restaurar sesión:", e);
    }
}
window.addEventListener('pywebviewready', intentarRestaurarSesion);

// Pide el código enviado por correo.
function abrirModalCodigo(email) {
    document.getElementById('code-email').textContent = email;
    document.getElementById('code-input').value = '';
    document.getElementById('code-msg').textContent = '';
    document.getElementById('code-modal').style.display = 'flex';
    document.getElementById('code-input').focus();
}

// Cierra esa ventana sin recordar la sesión.
function omitirCodigo() {
    document.getElementById('code-modal').style.display = 'none';
}

// Verifica el código.
async function confirmarCodigo() {
    const codigo = document.getElementById('code-input').value.trim();
    const msg = document.getElementById('code-msg');
    if (!codigo) {
        msg.textContent = 'Ingresá el código que te llegó por correo.';
        return;
    }
    try {
        const res = await window.pywebview.api.confirmar_recordar(codigo);
        if (res && res.exito) {
            omitirCodigo();
            alert('¡Listo! La próxima vez entrarás automáticamente.');
        } else {
            msg.textContent = res ? res.error : 'No se pudo verificar el código.';
        }
    } catch (e) {
        msg.textContent = 'Error: ' + e;
    }
}

// Pide un código nuevo.
async function reenviarCodigo() {
    const msg = document.getElementById('code-msg');
    try {
        const res = await window.pywebview.api.reenviar_codigo_recordar();
        msg.textContent = res && res.exito ? 'Te enviamos un código nuevo.' : (res ? res.error : 'No se pudo reenviar.');
    } catch (e) {
        msg.textContent = 'Error: ' + e;
    }
}

// Corta las llamadas, sale de la cuenta y limpia la pantalla.
async function cerrarSesion() {
    if (!confirm('¿Cerrar sesión? Dejará de recordarse tu cuenta en este equipo.')) return;
    try { await llamadasDetener(); } catch (e) { /* se sigue igual */ }
    try { await window.pywebview.api.cerrar_sesion(); } catch (e) { /* se sigue igual */ }

    usuarioActual = null;
    perfilActual = null;
    consolaSeleccionada = 'todas';
    llavesCerrar();
    cerrarConfiguracion();
    volverABiblioteca();
    detenerInsignias();
    reiniciarEstadoUI();
    mostrarVista('biblioteca');
    document.getElementById('app-screen').style.display = 'none';
    document.getElementById('auth-screen').style.display = 'flex';
    document.getElementById('login-pass').value = '';
    document.getElementById('login-remember').checked = false;
}

// ============================================================================
// ENLACES
// ============================================================================

// Abre un enlace en el navegador; Python solo permite sitios de confianza.
function abrirEnlace(url) {
    window.pywebview.api.abrir_enlace(url);
}

// ============================================================================
// CONFIGURACIÓN (estilo "Parámetros" de Steam)
// ============================================================================

// Abre Configuración en la sección indicada.
function abrirConfiguracion(seccion) {
    document.getElementById('settings-modal').style.display = 'flex';
    seleccionarSeccionConfig(seccion || 'paths');
}

// Cierra Configuración.
function cerrarConfiguracion() {
    document.getElementById('settings-modal').style.display = 'none';
}

// Muestra una sección de Configuración y carga sus datos.
function seleccionarSeccionConfig(nombre) {
    document.querySelectorAll('.settings-section').forEach(s => s.style.display = 'none');
    document.getElementById('settings-' + nombre).style.display = 'block';
    document.querySelectorAll('.settings-nav li').forEach(li => {
        li.classList.toggle('active', li.dataset.section === nombre);
    });

    if (nombre === 'paths') cargarRutasConfig();
    else if (nombre === 'audio') cargarConfigAudio();
    else if (nombre === 'ra') cargarEstadoRA();
    else if (nombre === 'privacy') cargarPrivacidad();
    else if (nombre === 'info') cargarInfoLauncher();
}

// Fila de texto "etiqueta: ruta".
function filaRuta(etiqueta, valor) {
    const fila = document.createElement('div');
    fila.className = 'path-row';
    const label = document.createElement('span');
    label.textContent = etiqueta;
    const code = document.createElement('code');
    code.textContent = valor;
    fila.append(label, code);
    return fila;
}

// Sección Rutas: carpetas y una tarjeta por cada consola con juegos.
async function cargarRutasConfig() {
    const cont = document.getElementById('paths-content');
    cont.textContent = 'Cargando…';
    try {
        const cfg = await window.pywebview.api.obtener_config_rutas();
        cont.innerHTML = '';
        cont.append(
            filaRuta('Carpeta base de ROMs', cfg.roms_base),
            filaRuta('Carpeta de carátulas', cfg.boxarts)
        );

        const titulo = document.createElement('h3');
        titulo.className = 'settings-subtitle';
        titulo.textContent = 'Emuladores por consola';
        cont.appendChild(titulo);

        if (!cfg.consolas || cfg.consolas.length === 0) {
            const vacio = document.createElement('p');
            vacio.className = 'settings-help';
            vacio.textContent = 'Todavía no hay juegos escaneados. Poné tus ROMs en la carpeta de cada consola y tocá "Escanear ROMs": las consolas con juegos aparecerán acá.';
            cont.appendChild(vacio);
            return;
        }
        cfg.consolas.forEach(c => cont.appendChild(tarjetaEmulador(c)));
    } catch (e) {
        cont.textContent = 'Error al cargar la configuración: ' + e;
    }
}

// Tarjeta para elegir y guardar el emulador de una consola.
function tarjetaEmulador(c) {
    const card = document.createElement('div');
    card.className = 'emu-card';

    const cabecera = document.createElement('div');
    cabecera.className = 'emu-card-head';
    const nombre = document.createElement('strong');
    nombre.textContent = c.nombre;
    const cantidad = document.createElement('span');
    cantidad.textContent = `${c.total_juegos} juego${c.total_juegos === 1 ? '' : 's'}`;
    cabecera.append(nombre, cantidad);

    const roms = document.createElement('p');
    roms.className = 'emu-card-roms';
    roms.textContent = 'ROMs: ' + (c.ruta_roms || '(sin definir)');

    const fila = document.createElement('div');
    fila.className = 'emu-card-row';
    const input = document.createElement('input');
    input.type = 'text';
    input.className = 'settings-input';
    input.placeholder = 'Ruta del emulador (ej: /usr/bin/retroarch)';
    input.value = c.ruta_emulador || '';

    const btnExaminar = document.createElement('button');
    btnExaminar.className = 'btn-secondary-sm';
    btnExaminar.textContent = 'Examinar…';
    btnExaminar.onclick = async () => {
        const ruta = await window.pywebview.api.seleccionar_ejecutable_emulador();
        if (ruta) input.value = ruta;
    };

    const msg = document.createElement('span');
    msg.className = 'settings-msg';

    const btnGuardar = document.createElement('button');
    btnGuardar.className = 'btn-primary-sm';
    btnGuardar.textContent = 'Guardar';
    btnGuardar.onclick = async () => {
        const res = await window.pywebview.api.guardar_ruta_emulador(c.id, input.value);
        msg.textContent = res && res.exito ? '✔ Guardado' : (res ? res.error : 'Error');
        msg.style.color = res && res.exito ? '#66FCF1' : '#ff4d4d';
    };

    fila.append(input, btnExaminar, btnGuardar);
    card.append(cabecera, roms, fila, msg);
    return card;
}

// Sección RetroAchievements: muestra si hay una cuenta conectada.
async function cargarEstadoRA() {
    try {
        const est = await window.pywebview.api.obtener_estado_ra();
        document.getElementById('ra-user').value = est.usuario || '';
        const key = document.getElementById('ra-key');
        key.value = '';
        key.placeholder = est.configurado ? '•••••••• (guardada)' : 'Tu Web API Key';
        const status = document.getElementById('ra-status');
        status.textContent = est.configurado ? `Cuenta conectada: ${est.usuario}` : 'Sin cuenta conectada.';
        status.style.color = est.configurado ? '#66FCF1' : '#a0a0a0';
    } catch (e) {
        console.error(e);
    }
}

// Prueba y guarda las credenciales.
async function guardarCredencialesRA() {
    const status = document.getElementById('ra-status');
    status.style.color = '#a0a0a0';
    status.textContent = 'Comprobando…';
    const res = await window.pywebview.api.guardar_credenciales_ra(
        document.getElementById('ra-user').value,
        document.getElementById('ra-key').value
    );
    if (res && res.exito) {
        document.getElementById('ra-key').value = '';
        await cargarEstadoRA();
    } else {
        status.style.color = '#ff4d4d';
        status.textContent = res ? res.error : 'No se pudo guardar.';
    }
}

// Desconecta la cuenta.
async function borrarCredencialesRA() {
    await window.pywebview.api.borrar_credenciales_ra();
    await cargarEstadoRA();
}

// Sección Información.
async function cargarInfoLauncher() {
    try {
        const info = await window.pywebview.api.obtener_info_launcher();
        document.getElementById('info-version').textContent = info.version;
        document.getElementById('info-dev').textContent = info.desarrollador;
        document.getElementById('info-juegos').textContent = info.juegos;
        document.getElementById('info-emus').textContent = info.emuladores;
        const gh = document.getElementById('info-github');
        gh.textContent = info.github;
        gh.dataset.url = info.github;
    } catch (e) {
        console.error(e);
    }
}

// ============================================================================
// DETALLE DE JUEGO (estilo biblioteca de Steam)
// ============================================================================

let juegoDetalleActual = null;
let opinionPuntuacion = 0;
let scrollBiblioteca = 0;

// Al escribir en el buscador: vuelve a la biblioteca y filtra.
function alBuscar() {
    volverABiblioteca();
    filtrarCatalogo();
}

// Abre la pantalla de un juego y recuerda la posición de la biblioteca.
async function abrirDetalle(juego) {
    const biblioteca = document.querySelector('.game-grid-container');
    scrollBiblioteca = biblioteca.scrollTop;

    let res;
    try {
        res = await window.pywebview.api.obtener_detalle_juego(juego.id);
    } catch (e) {
        alert("No se pudo abrir el juego: " + e);
        return;
    }
    if (!res || !res.exito) {
        alert(res ? res.error : "No se pudo abrir el juego.");
        return;
    }

    juegoDetalleActual = res.juego;
    pintarDetalle(juegoDetalleActual);

    biblioteca.style.display = 'none';
    const detalle = document.getElementById('game-detail');
    detalle.style.display = 'block';
    detalle.scrollTop = 0;

    cargarLogros(juegoDetalleActual.id);
    cargarAmigos(juegoDetalleActual.id);
}

// Cierra el detalle y restaura la posición.
function volverABiblioteca() {
    const detalle = document.getElementById('game-detail');
    if (detalle.style.display === 'none') return;
    detalle.style.display = 'none';
    const biblioteca = document.querySelector('.game-grid-container');
    biblioteca.style.display = '';
    biblioteca.scrollTop = scrollBiblioteca;
    juegoDetalleActual = null;
}

// Llena la pantalla de detalle con los datos del juego.
function pintarDetalle(j) {
    document.getElementById('detail-title').textContent = j.titulo;
    document.getElementById('detail-console').textContent =
        j.consola + (j.total_variantes > 1 ? ` · ${j.total_variantes} versiones/discos` : '');

    const cover = document.getElementById('detail-cover');
    cover.innerHTML = '';
    cover.appendChild(crearPortada(j, j.titulo));

    document.getElementById('detail-hero-bg').style.backgroundImage =
        j.portada_url ? `url("${j.portada_url}")` : 'none';

    opinionPuntuacion = (j.opinion && j.opinion.puntuacion) || 0;
    document.getElementById('opinion-publica').checked = j.opinion ? !!j.opinion.publica : true;
    document.getElementById('opinion-text').value = (j.opinion && j.opinion.texto) || '';
    document.getElementById('opinion-msg').textContent = '';
    pintarEstrellas();
}

// Botón Jugar del detalle.
function jugarDesdeDetalle() {
    if (juegoDetalleActual) lanzarJuego(juegoDetalleActual.id);
}

// Elige estrellas; tocar la misma las quita.
function elegirPuntuacion(valor) {
    opinionPuntuacion = (opinionPuntuacion === valor) ? 0 : valor;
    pintarEstrellas();
}

// Rellena las estrellas según la puntuación.
function pintarEstrellas() {
    document.querySelectorAll('#opinion-stars span').forEach(s => {
        s.classList.toggle('on', Number(s.dataset.v) <= opinionPuntuacion);
    });
}

// Guarda la opinión del juego.
async function guardarOpinion() {
    if (!juegoDetalleActual) return;
    const msg = document.getElementById('opinion-msg');
    try {
        const res = await window.pywebview.api.guardar_opinion(
            juegoDetalleActual.id,
            opinionPuntuacion,
            document.getElementById('opinion-text').value,
            document.getElementById('opinion-publica').checked
        );
        if (res && res.exito) {
            msg.textContent = res.aviso
                ? `✔ Guardada en tu equipo. No se pudo publicar: ${res.aviso}`
                : '✔ Opinión guardada';
        } else {
            msg.textContent = (res && res.error) || 'Error al guardar.';
        }
    } catch (e) {
        msg.textContent = 'Error: ' + e;
    }
}

// Explica por qué no hay logros para mostrar.
function mensajeLogros(cont, res) {
    const p = document.createElement('p');
    p.className = 'settings-help';
    const motivo = res ? res.motivo : 'error';

    if (motivo === 'sin_credenciales') {
        p.textContent = 'Conectá tu cuenta de RetroAchievements para ver los logros de este juego.';
        const btn = document.createElement('button');
        btn.className = 'btn-primary-sm';
        btn.textContent = 'Conectar RetroAchievements';
        btn.onclick = () => abrirConfiguracion('ra');
        cont.append(p, btn);
        return;
    }
    if (motivo === 'consola_no_soportada') {
        p.textContent = 'RetroAchievements no tiene soporte para esta consola.';
    } else if (motivo === 'sin_logros') {
        p.textContent = 'No se encontraron logros de RetroAchievements para este juego. (Más adelante: logros personalizados.)';
    } else {
        p.textContent = (res && res.error) || 'No se pudieron cargar los logros.';
    }
    cont.appendChild(p);
}

// Trae y dibuja los logros con la barra de progreso.
async function cargarLogros(id) {
    const cont = document.getElementById('achievements-content');
    cont.textContent = 'Cargando logros…';

    let res;
    try {
        res = await window.pywebview.api.obtener_logros_juego(id);
    } catch (e) {
        res = { exito: false, motivo: 'error', error: String(e) };
    }
    if (!juegoDetalleActual || juegoDetalleActual.id !== id) return;  // el usuario ya cambió de pantalla

    cont.innerHTML = '';
    if (!res || !res.exito) {
        mensajeLogros(cont, res);
        return;
    }

    const pct = res.total ? Math.round((res.obtenidos / res.total) * 100) : 0;
    const resumen = document.createElement('div');
    resumen.className = 'ach-summary';
    const texto = document.createElement('span');
    texto.textContent = `${res.obtenidos}/${res.total} logros · ${res.puntos_obtenidos}/${res.puntos_total} pts (${pct}%)`;
    const enlace = document.createElement('button');
    enlace.className = 'btn-secondary-sm';
    enlace.textContent = 'Ver en RetroAchievements';
    enlace.onclick = () => abrirEnlace(res.url);
    resumen.append(texto, enlace);

    const barra = document.createElement('div');
    barra.className = 'ach-bar';
    const relleno = document.createElement('div');
    relleno.className = 'ach-bar-fill';
    relleno.style.width = pct + '%';
    barra.appendChild(relleno);

    const lista = document.createElement('div');
    lista.className = 'ach-list';
    res.logros.forEach(l => {
        const item = document.createElement('div');
        item.className = 'ach-item' + (l.obtenido ? '' : ' locked');

        if (l.badge_url) {
            const img = document.createElement('img');
            img.src = l.badge_url;
            img.alt = '';
            img.loading = 'lazy';
            img.onerror = () => { img.style.visibility = 'hidden'; };
            item.appendChild(img);
        }

        const info = document.createElement('div');
        info.className = 'ach-info';
        const t = document.createElement('strong');
        t.textContent = l.titulo;
        const d = document.createElement('small');
        d.textContent = l.descripcion;
        info.append(t, d);

        const meta = document.createElement('div');
        meta.className = 'ach-meta';
        meta.textContent = `${l.puntos} pts` + (l.obtenido ? ` · ${l.hardcore ? '🔥 ' : ''}${l.fecha}` : '');

        item.append(info, meta);
        lista.appendChild(item);
    });

    cont.append(resumen, barra, lista);
}

// Amigos: la parte de servidor todavía no existe (se desarrollará más adelante).
// La interfaz ya consulta la API y muestra las listas cuando lleguen datos.
async function cargarAmigos(id) {
    let res = null;
    try {
        res = await window.pywebview.api.obtener_amigos_juego(id);
    } catch (e) { /* se muestran los vacíos */ }
    if (!juegoDetalleActual || juegoDetalleActual.id !== id) return;

    pintarAmigos(document.getElementById('friends-played'), res && res.jugaron,
        'Ninguno de tus amigos jugó este juego todavía.');
    pintarAmigos(document.getElementById('friends-wishlist'), res && res.deseado,
        'Ninguno de tus amigos lo tiene en su lista de deseados.');
    pintarOpinionesAmigos(document.getElementById('friends-opiniones'), res && res.opiniones);
}

// Lista de amigos que jugaron o desean el juego.
function pintarAmigos(el, amigos, textoVacio) {
    el.innerHTML = '';
    if (!amigos || amigos.length === 0) {
        const p = document.createElement('p');
        p.className = 'empty-state';
        p.textContent = textoVacio;
        el.appendChild(p);
        return;
    }
    amigos.forEach(a => {
        const fila = document.createElement('div');
        fila.className = 'friend-item';

        const img = document.createElement('img');
        img.src = avatarDe(a);
        img.alt = '';
        img.onerror = () => { img.style.visibility = 'hidden'; };

        const info = document.createElement('div');
        info.className = 'friend-info';
        const nombre = document.createElement('span');
        nombre.textContent = a.username || String(a);
        const sub = document.createElement('small');
        sub.textContent = a.veces
            ? `${a.veces} ${a.veces === 1 ? 'vez' : 'veces'} · ${formatearFecha(a.ultima_vez)}`
            : (a.agregado_en ? `Lo quiere desde ${formatearFecha(a.agregado_en)}` : '');
        info.append(nombre, sub);

        fila.append(img, info);
        if (a.user_id) {
            fila.classList.add('clickable');
            fila.onclick = () => irAPerfilAmigo(a.user_id);
        }
        el.appendChild(fila);
    });
}

// ============================================================================
// NAVEGACIÓN PRINCIPAL (SOCIAL · BIBLIOTECA · NOTICIAS · CATÁLOGO)
// ============================================================================

let vistaActual = 'biblioteca';

// Cambia de pestaña principal y detiene lo que deja de verse.
function mostrarVista(nombre) {
    vistaActual = nombre;
    document.querySelectorAll('.view').forEach(v => {
        v.style.display = (v.id === 'view-' + nombre) ? '' : 'none';
    });
    document.querySelectorAll('.nav-btn').forEach(b => {
        b.classList.toggle('active', b.dataset.view === nombre);
    });

    if (nombre === 'social') {
        abrirSocial();
    } else {
        detenerSocial();
        detenerChat();
        cerrarPicker();
    }
}

// ============================================================================
// SOCIAL
// ============================================================================

let socialSeccion = 'amigos';
let socialTimer = null;
let busquedaTimer = null;

// Entra a Social y refresca cada 30 s qué juegan tus amigos.
function abrirSocial() {
    seleccionarSeccionSocial(socialSeccion);
    detenerSocial();
    // Se refresca solo para ver qué juegan tus amigos
    socialTimer = setInterval(() => {
        if (vistaActual === 'social' && socialSeccion === 'amigos') {
            if (perfilAjenoId) cargarPerfilAjeno(); else cargarSocial();
        }
    }, 30000);
}

// Detiene ese refresco.
function detenerSocial() {
    if (socialTimer) clearInterval(socialTimer);
    socialTimer = null;
}

// Muestra una sección de Social y carga sus datos.
function seleccionarSeccionSocial(nombre) {
    socialSeccion = nombre;
    if (nombre !== 'chat') detenerChat();
    if (nombre !== 'publicaciones') cerrarPicker();
    document.querySelector('.social-content').classList.toggle('chat-vista', nombre === 'chat');
    perfilAjenoId = null;
    document.getElementById('social-perfil').style.display = 'none';
    document.querySelectorAll('.social-nav li').forEach(li => {
        li.classList.toggle('active', li.dataset.social === (nombre === 'chat' ? 'amigos' : nombre));
    });

    const reales = { amigos: 'social-amigos', deseados: 'social-deseados', chat: 'social-chat', publicaciones: 'social-publicaciones' };
    Object.values(reales).forEach(id => document.getElementById(id).style.display = 'none');

    document.getElementById(reales[nombre]).style.display = 'block';
    if (nombre === 'amigos') cargarSocial();
    else if (nombre === 'deseados') abrirDeseados();
    else if (nombre === 'chat') abrirChat();
    else if (nombre === 'publicaciones') abrirPublicaciones();
}

// Foto del usuario, o una generada con su nombre si no tiene.
function avatarDe(u) {
    return (u.avatar_url && u.avatar_url.trim() !== '')
        ? u.avatar_url
        : `https://ui-avatars.com/api/?name=${encodeURIComponent(u.username || '?')}&background=45A29E&color=fff`;
}

// Crea un botón que se desactiva mientras se procesa, para evitar dobles clics.
function boton(texto, clase, accion) {
    const b = document.createElement('button');
    b.className = clase;
    b.textContent = texto;
    b.onclick = async () => {
        b.disabled = true;   // evita dobles clics mientras se procesa
        try { await accion(); } finally { b.disabled = false; }
    };
    return b;
}

// "📞 En llamada · 🎮 Jugando a X · PS1" (cualquiera de las dos partes puede faltar)
function textoActividad(enLlamada, jugando) {
    const juego = jugando ? `🎮 Jugando a ${jugando.titulo}` + (jugando.consola ? ` · ${jugando.consola}` : '') : '';
    return [enLlamada ? '📞 En llamada' : '', juego].filter(Boolean).join(' · ');
}

// Fila de un usuario: foto, nombre, estado y acciones.
function filaUsuario(u, subtitulo, jugando, acciones) {
    const fila = document.createElement('div');
    fila.className = 'user-row';

    const img = document.createElement('img');
    img.src = avatarDe(u);
    img.alt = '';
    img.onerror = () => { img.style.visibility = 'hidden'; };

    const info = document.createElement('div');
    info.className = 'user-row-info';
    const nombre = document.createElement('span');
    nombre.className = 'user-row-name';
    nombre.textContent = u.username || 'Usuario';
    const sub = document.createElement('span');
    sub.className = 'user-row-sub' + (jugando ? ' playing' : '');
    sub.textContent = subtitulo || '';
    info.append(nombre, sub);

    const cont = document.createElement('div');
    cont.className = 'user-row-actions';
    acciones.forEach(a => cont.appendChild(a));

    if (u.user_id) {
        img.onclick = info.onclick = () => abrirPerfilAjeno(u.user_id);
    }
    fila.append(img, info, cont);
    return fila;
}

// Título de una lista, con contador opcional.
function tituloBloque(texto, cantidad) {
    const h = document.createElement('h3');
    h.className = 'social-block-title';
    h.textContent = texto;
    if (cantidad !== undefined) {
        const c = document.createElement('span');
        c.className = 'count-badge';
        c.textContent = cantidad;
        h.appendChild(c);
    }
    return h;
}

// Texto para una lista vacía o que está cargando.
function mensajeVacio(texto) {
    const p = document.createElement('p');
    p.className = 'empty-state';
    p.textContent = texto;
    return p;
}

// Dibuja solicitudes, amigos y solicitudes enviadas.
async function cargarSocial() {
    const cont = document.getElementById('friend-lists');
    if (!cont.children.length) cont.appendChild(mensajeVacio('Cargando…'));
    let res;
    try {
        res = await window.pywebview.api.obtener_social();
    } catch (e) {
        res = { exito: false, error: String(e) };
    }

    if (!res || !res.exito) {
        cont.innerHTML = '';
        const err = document.createElement('p');
        err.className = 'error-msg';
        err.textContent = (res && res.error) || 'No se pudo cargar la sección social.';
        cont.appendChild(err);
        return;
    }
    pintarInsignias(res.recibidas.length);
    cont.innerHTML = '';

    // Solicitudes recibidas (solo si hay)
    if (res.recibidas.length > 0) {
        cont.appendChild(tituloBloque('Solicitudes de amistad', res.recibidas.length));
        res.recibidas.forEach(u => {
            cont.appendChild(filaUsuario(u, 'Quiere ser tu amigo', false, [
                boton('Aceptar', 'btn-primary-sm', () => responderSolicitud(u.friendship_id, true)),
                boton('Rechazar', 'btn-secondary-sm', () => responderSolicitud(u.friendship_id, false)),
            ]));
        });
    }

    // Amigos
    cont.appendChild(tituloBloque('Amigos', res.amigos.length));
    if (res.amigos.length === 0) {
        cont.appendChild(mensajeVacio('Todavía no tenés amigos agregados. Buscá a alguien por su nombre de usuario en el cuadro de arriba.'));
    }
    res.amigos.forEach(u => {
        cont.appendChild(filaUsuario(u, textoActividad(u.en_llamada, u.jugando), !!u.jugando || u.en_llamada, [
            botonIcono('💬', 'Enviar mensaje', () => irAlChat(u.user_id)),
            botonIcono('📞', 'Llamada de voz', () => llamarAmigo(u.user_id, u.username)),
            botonIcono('🎥', 'Videollamada', () => llamarAmigo(u.user_id, u.username, true)),
            menuAmigo(u),
        ]));
    });

    // Enviadas (solo si hay)
    if (res.enviadas.length > 0) {
        cont.appendChild(tituloBloque('Solicitudes enviadas', res.enviadas.length));
        res.enviadas.forEach(u => {
            cont.appendChild(filaUsuario(u, 'Esperando respuesta', false, [
                boton('Cancelar', 'btn-secondary-sm', () => quitarAmistad(u.friendship_id, null)),
            ]));
        });
    }
}

// Espera a que dejes de escribir antes de buscar.
function buscarUsuariosConRetraso() {
    clearTimeout(busquedaTimer);
    busquedaTimer = setTimeout(buscarUsuarios, 350);
}

// Busca usuarios por nombre y muestra la acción posible con cada uno.
async function buscarUsuarios() {
    const texto = document.getElementById('friend-search').value.trim();
    const cont = document.getElementById('friend-search-results');
    if (texto.length < 2) {
        cont.innerHTML = '';
        if (texto.length === 1) cont.appendChild(mensajeVacio('Escribí al menos 2 letras para buscar.'));
        return;
    }

    let res;
    try {
        res = await window.pywebview.api.buscar_usuarios(texto);
    } catch (e) {
        res = { exito: false, error: String(e) };
    }
    // Si mientras tanto cambió el texto, esta respuesta ya no sirve
    if (document.getElementById('friend-search').value.trim() !== texto) return;

    cont.innerHTML = '';
    if (!res || !res.exito) {
        const err = document.createElement('p');
        err.className = 'error-msg';
        err.textContent = (res && res.error) || 'No se pudo buscar.';
        cont.appendChild(err);
        return;
    }

    cont.appendChild(tituloBloque('Resultados'));
    if (res.usuarios.length === 0) {
        cont.appendChild(mensajeVacio('No se encontró ningún usuario con ese nombre.'));
        return;
    }
    res.usuarios.forEach(u => {
        let accion;
        if (u.relacion === 'amigos') {
            accion = boton('✔ Amigos', 'btn-secondary-sm', () => {});
            accion.disabled = true;
        } else if (u.relacion === 'enviada') {
            accion = boton('Solicitud enviada', 'btn-secondary-sm', () => {});
            accion.disabled = true;
        } else if (u.relacion === 'recibida') {
            accion = boton('Aceptar solicitud', 'btn-primary-sm', () => responderSolicitud(u.friendship_id, true));
        } else {
            accion = boton('Agregar', 'btn-primary-sm', () => agregarAmigo(u.user_id));
        }
        cont.appendChild(filaUsuario(u, '', false, [accion]));
    });
}

// Vuelve a dibujar todo lo que depende de una amistad.
async function refrescarSocialYBusqueda() {
    await cargarSocial();
    await buscarUsuarios();
    if (perfilAjenoId) await cargarPerfilAjeno();
}

// Envía una solicitud de amistad.
async function agregarAmigo(userId) {
    const res = await window.pywebview.api.enviar_solicitud_amistad(userId);
    if (!res || !res.exito) alert(res ? res.error : 'No se pudo enviar la solicitud.');
    await refrescarSocialYBusqueda();
}

// Acepta o rechaza una solicitud.
async function responderSolicitud(friendshipId, aceptar) {
    const res = await window.pywebview.api.responder_solicitud_amistad(friendshipId, aceptar);
    if (!res || !res.exito) alert(res ? res.error : 'No se pudo responder la solicitud.');
    await refrescarSocialYBusqueda();
}

// Quita a un amigo, o cancela una solicitud si no se indica nombre.
async function quitarAmistad(friendshipId, nombre) {
    if (nombre && !confirm(`¿Quitar a ${nombre} de tus amigos?`)) return;
    const res = await window.pywebview.api.eliminar_amistad(friendshipId);
    if (!res || !res.exito) alert(res ? res.error : 'No se pudo completar la acción.');
    await refrescarSocialYBusqueda();
}

// ============================================================================
// BLOQUEAR Y DENUNCIAR
// ============================================================================

// Bloquea a un usuario y quita de la pantalla todo lo que dependía de esa relación.
async function bloquearUsuario(userId, nombre) {
    if (!confirm(`¿Bloquear a ${nombre}? Dejarán de ser amigos, y no podrán escribirse, llamarse ni ver sus publicaciones. Podés deshacerlo en Configuración → Privacidad.`)) return false;
    let res;
    try {
        res = await window.pywebview.api.bloquear_usuario(userId);
    } catch (e) {
        res = { exito: false, error: String(e) };
    }
    if (!res || !res.exito) {
        alert((res && res.error) || 'No se pudo bloquear al usuario.');
        return false;
    }
    if (chatAmigo && chatAmigo.user_id === userId) {
        chatAmigo = null;
        document.getElementById('chat-activo').style.display = 'none';
        document.getElementById('chat-vacio').style.display = '';
    }
    if (perfilAjenoId === userId) cerrarPerfilAjeno();
    avisoPost(`Bloqueaste a ${nombre}.`);
    if (socialSeccion === 'chat') cargarConversaciones();
    else if (socialSeccion === 'publicaciones') cargarPublicaciones(true);
    else await refrescarSocialYBusqueda();
    return true;
}

let denunciaActual = null;   // { userId, nombre }

// Abre el formulario de denuncia, siempre vacío.
function abrirDenuncia(userId, nombre) {
    denunciaActual = { userId, nombre };
    document.getElementById('denuncia-titulo').textContent = `Denunciar a ${nombre}`;
    document.getElementById('denuncia-motivo').value = '';
    document.getElementById('denuncia-detalle').value = '';
    document.getElementById('denuncia-bloquear').checked = false;
    document.getElementById('denuncia-msg').textContent = '';
    document.getElementById('denuncia-enviar').disabled = false;
    document.getElementById('denuncia-modal').style.display = 'flex';
    document.getElementById('denuncia-motivo').focus();
}

// Cierra el formulario sin enviar.
function cerrarDenuncia() {
    denunciaActual = null;
    document.getElementById('denuncia-modal').style.display = 'none';
}

// Envía la denuncia y, si se pidió, bloquea también a esa persona.
async function confirmarDenuncia() {
    if (!denunciaActual) return;
    const { userId, nombre } = denunciaActual;
    const msg = document.getElementById('denuncia-msg');
    const motivo = document.getElementById('denuncia-motivo').value;
    if (!motivo) { msg.textContent = 'Elegí un motivo.'; return; }
    const btn = document.getElementById('denuncia-enviar');
    btn.disabled = true;
    msg.textContent = 'Enviando…';
    let res;
    try {
        res = await window.pywebview.api.denunciar_usuario(userId, motivo, document.getElementById('denuncia-detalle').value);
    } catch (e) {
        res = { exito: false, error: String(e) };
    }
    btn.disabled = false;
    if (!res || !res.exito) {
        msg.textContent = (res && res.error) || 'No se pudo enviar la denuncia.';
        return;
    }
    const tambienBloquear = document.getElementById('denuncia-bloquear').checked;
    cerrarDenuncia();
    avisoPost(res.ya_existia ? 'Ya tenías una denuncia pendiente contra este usuario.' : 'Denuncia enviada. Gracias por avisar.');
    if (tambienBloquear) bloquearUsuario(userId, nombre);
}

// Lista de usuarios bloqueados en Configuración → Privacidad.
async function cargarBloqueados() {
    const cont = document.getElementById('bloqueados-lista');
    let res;
    try {
        res = await window.pywebview.api.obtener_bloqueados();
    } catch (e) {
        res = { exito: false, error: String(e) };
    }
    cont.innerHTML = '';
    if (!res || !res.exito) {
        cont.appendChild(mensajeVacio((res && res.error) || 'No se pudo cargar la lista.'));
        return;
    }
    if (res.bloqueados.length === 0) {
        cont.appendChild(mensajeVacio('No bloqueaste a nadie.'));
        return;
    }
    res.bloqueados.forEach(u => {
        // Sin user_id: la fila no abre el perfil, porque un usuario bloqueado no se puede ver
        cont.appendChild(filaUsuario({ username: u.username, avatar_url: u.avatar_url }, '', false, [
            boton('Desbloquear', 'btn-secondary-sm', () => desbloquearUsuario(u.user_id)),
        ]));
    });
}

// Quita un bloqueo y actualiza la lista.
async function desbloquearUsuario(userId) {
    const res = await window.pywebview.api.desbloquear_usuario(userId);
    if (!res || !res.exito) alert((res && res.error) || 'No se pudo desbloquear.');
    await cargarBloqueados();
}

// ============================================================================
// PRIVACIDAD
// ============================================================================

// Sección Privacidad: marca las casillas guardadas.
async function cargarPrivacidad() {
    try {
        const p = await window.pywebview.api.obtener_privacidad();
        document.getElementById('privacy-share').checked = !!p.actividad;
        document.getElementById('privacy-history').checked = !!p.historial;
        document.getElementById('privacy-deseados').checked = !!p.deseados;
        cargarBloqueados();
    } catch (e) {
        console.error(e);
    }
}

// Guarda el ajuste de actividad.
async function guardarCompartirActividad() {
    const activo = document.getElementById('privacy-share').checked;
    await window.pywebview.api.guardar_compartir_actividad(activo);
}

// ============================================================================
// PERFIL DE OTRO USUARIO
// ============================================================================

let perfilAjenoId = null;

// Muestra el perfil de otro usuario, limpiando el anterior.
async function abrirPerfilAjeno(userId) {
    perfilAjenoId = userId;
    document.getElementById('social-amigos').style.display = 'none';
    document.getElementById('social-perfil').style.display = 'block';
    document.getElementById('pa-nombre').textContent = 'Cargando…';
    document.getElementById('pa-estado').textContent = '';
    document.getElementById('pa-estado').className = 'pa-estado';
    document.getElementById('pa-bio').textContent = '';
    document.getElementById('pa-acciones').innerHTML = '';
    document.getElementById('pa-juegos').innerHTML = '';
    document.getElementById('pa-comun').innerHTML = '';
    document.getElementById('pa-deseados').innerHTML = '';
    document.getElementById('pa-avatar').removeAttribute('src');
    await cargarPerfilAjeno();
}

// Vuelve a la lista de amigos.
function cerrarPerfilAjeno() {
    perfilAjenoId = null;
    document.getElementById('social-perfil').style.display = 'none';
    document.getElementById('social-amigos').style.display = 'block';
    cargarSocial();
}

// Pinta el perfil; ignora la respuesta si mientras tanto se cerró.
async function cargarPerfilAjeno() {
    const id = perfilAjenoId;
    let res;
    try {
        res = await window.pywebview.api.obtener_perfil_social(id);
    } catch (e) {
        res = { exito: false, error: String(e) };
    }
    if (perfilAjenoId !== id) return;   // ya se cerró o se abrió otro perfil

    const acciones = document.getElementById('pa-acciones');
    acciones.innerHTML = '';

    if (!res || !res.exito) {
        document.getElementById('pa-nombre').textContent = 'No se pudo cargar el perfil';
        document.getElementById('pa-estado').textContent = (res && res.error) || '';
        return;
    }

    const p = res.perfil;
    const avatar = document.getElementById('pa-avatar');
    avatar.onerror = () => {
        avatar.onerror = null;
        avatar.src = `https://ui-avatars.com/api/?name=${encodeURIComponent(p.username || '?')}&background=45A29E&color=fff`;
    };
    avatar.src = avatarDe(p);
    document.getElementById('pa-nombre').textContent = p.username || 'Usuario';

    const estado = document.getElementById('pa-estado');
    if (res.jugando || res.en_llamada) {
        estado.textContent = textoActividad(res.en_llamada, res.jugando);
        estado.className = 'pa-estado playing';
    } else {
        estado.textContent = res.relacion === 'amigos' ? 'No está jugando ahora' : '';
        estado.className = 'pa-estado';
    }

    const bio = document.getElementById('pa-bio');
    if (p.bio && p.bio.trim() !== '') {
        bio.textContent = p.bio;
        bio.className = 'pa-bio';
    } else {
        bio.textContent = 'Este usuario todavía no escribió una biografía.';
        bio.className = 'empty-state';
    }

    pintarJuegosPerfil(res);

    if (res.relacion === 'ninguna') {
        acciones.appendChild(boton('Agregar a amigos', 'btn-primary-sm', () => agregarAmigo(p.user_id)));
    } else if (res.relacion === 'enviada') {
        acciones.appendChild(boton('Cancelar solicitud', 'btn-secondary-sm', () => quitarAmistad(res.friendship_id, null)));
    } else if (res.relacion === 'recibida') {
        acciones.append(
            boton('Aceptar solicitud', 'btn-primary-sm', () => responderSolicitud(res.friendship_id, true)),
            boton('Rechazar', 'btn-secondary-sm', () => responderSolicitud(res.friendship_id, false))
        );
    } else if (res.relacion === 'amigos') {
        acciones.appendChild(boton('💬 Enviar mensaje', 'btn-primary-sm', () => irAlChat(p.user_id)));
        acciones.appendChild(boton('Quitar de amigos', 'btn-secondary-sm', () => quitarAmistad(res.friendship_id, p.username)));
    }
    if (res.relacion !== 'yo') {
        acciones.appendChild(boton('Bloquear', 'btn-secondary-sm', () => bloquearUsuario(p.user_id, p.username)));
        acciones.appendChild(boton('Denunciar', 'btn-secondary-sm', () => abrirDenuncia(p.user_id, p.username)));
    }
}

// ============================================================================
// LLAVES DEL CIFRADO: la frase de recuperación (la lógica está en nucleo/cifrado.py)
// ============================================================================

// Muestra un solo paso de la ventana: 'frase', 'confirmar', 'contrasena' o 'recuperar'.
function llavesPaso(paso) {
    ['frase', 'confirmar', 'contrasena', 'recuperar'].forEach(p => {
        document.getElementById(`llaves-paso-${p}`).style.display = p === paso ? 'block' : 'none';
        const msg = document.getElementById(`llaves-${p}-msg`);
        if (msg) msg.textContent = '';
    });
    document.getElementById('llaves-confirmar-texto').value = '';
    document.getElementById('llaves-modal').style.display = 'flex';
    if (paso !== 'frase') document.getElementById(`llaves-${paso}-texto`).focus();
}

// Cierra la ventana y borra de la pantalla las palabras y lo escrito.
function llavesCerrar() {
    document.getElementById('llaves-modal').style.display = 'none';
    document.getElementById('llaves-palabras').replaceChildren();
    document.getElementById('llaves-confirmar-texto').value = '';
    document.getElementById('llaves-recuperar-texto').value = '';
    document.getElementById('llaves-contrasena-texto').value = '';
    window.pywebview.api.llaves_cerrar().catch(() => {});
}

// Comprueba la contraseña y muestra la frase, sin pedir confirmarla porque ya está activa.
async function llavesVerFrase() {
    const msg = document.getElementById('llaves-contrasena-msg');
    msg.textContent = 'Comprobando…';
    const res = await window.pywebview.api.llaves_ver_frase(document.getElementById('llaves-contrasena-texto').value);
    if (!res || !res.exito) {
        msg.textContent = (res && res.error) || 'No se pudo comprobar la contraseña.';
        return;
    }
    document.getElementById('llaves-contrasena-texto').value = '';
    llavesPintarFrase(res.palabras, true);
}

// Guarda la frase en pantalla en el archivo que se elija.
async function llavesGuardarArchivo() {
    const msg = document.getElementById('llaves-frase-msg');
    const res = await window.pywebview.api.llaves_guardar_archivo();
    if (res && res.exito) {
        msg.textContent = 'Archivo guardado. Guardalo en un lugar seguro: quien lo tenga puede leer tus chats.';
    } else if (!res || res.error !== 'cancelado') {
        msg.textContent = (res && res.error) || 'No se pudo guardar el archivo.';
    }
}

// Pinta las palabras; 'yaActiva' es para "Ver mi frase", donde no hay nada que confirmar.
function llavesPintarFrase(palabras, yaActiva) {
    document.getElementById('llaves-palabras').replaceChildren(...palabras.map(palabra => {
        const li = document.createElement('li');
        li.textContent = palabra;
        return li;
    }));
    document.getElementById('llaves-anote').style.display = yaActiva ? 'none' : '';
    document.getElementById('llaves-frase-cerrar').textContent = yaActiva ? 'Cerrar' : 'Ahora no';
    llavesPaso('frase');
}

// Al entrar, abre la ventana si falta algo. Si el servidor no responde no se muestra nada.
async function llavesIniciar() {
    let res;
    try {
        res = await window.pywebview.api.llaves_estado();
    } catch (e) {
        res = { exito: false, error: String(e) };
    }
    if (!res || !res.exito) {
        console.warn('Llaves:', res && res.error);
    } else if (res.estado === 'crear') {
        await llavesMostrarFrase(false);
    } else if (res.estado === 'recuperar') {
        document.getElementById('llaves-recuperar-ayuda').textContent = res.cambio
            ? 'Tu frase se cambió desde otro equipo. Escribí la frase nueva para seguir leyendo tus chats aquí.'
            : 'Esta cuenta ya tiene una frase de recuperación. Escribí las 12 palabras para usar tus chats en este equipo.';
        llavesPaso('recuperar');
    }
}

// Pide una frase nueva y la muestra.
async function llavesMostrarFrase(reemplazar) {
    const res = await window.pywebview.api.llaves_generar(reemplazar);
    if (!res || !res.exito) {
        console.warn('Llaves:', res && res.error);
        return false;
    }
    llavesPintarFrase(res.palabras, false);
    return true;
}

// Comprueba que la frase quedó anotada y la activa.
async function llavesConfirmar() {
    const msg = document.getElementById('llaves-confirmar-msg');
    msg.textContent = 'Guardando…';
    const res = await window.pywebview.api.llaves_confirmar(document.getElementById('llaves-confirmar-texto').value);
    if (res && res.exito) {
        llavesCerrar();
        avisoPost('Tu frase de recuperación quedó activada.');
    } else {
        msg.textContent = (res && res.error) || 'No se pudo activar la frase.';
    }
}

// Trae las llaves a este equipo con una frase existente.
async function llavesRecuperar() {
    const msg = document.getElementById('llaves-recuperar-msg');
    msg.textContent = 'Comprobando…';
    const res = await window.pywebview.api.llaves_recuperar(document.getElementById('llaves-recuperar-texto').value);
    if (res && res.exito) {
        llavesCerrar();
        avisoPost('Tus chats ya se pueden usar en este equipo.');
    } else {
        msg.textContent = (res && res.error) || 'No se pudo comprobar la frase.';
    }
}

// Sin la frase vieja solo queda crear otra, y los mensajes cifrados anteriores se pierden.
async function llavesPerdi() {
    if (!confirm('¿Crear una frase nueva? Los mensajes cifrados anteriores quedarán ilegibles para siempre, en todos tus equipos. Hacelo solo si perdiste tu frase.')) return;
    if (!await llavesMostrarFrase(true)) {
        document.getElementById('llaves-recuperar-msg').textContent = 'No se pudo crear la frase.';
    }
}

// ============================================================================
// INSIGNIAS (solicitudes de amistad pendientes)
// ============================================================================

let insigniaTimer = null;

const insignias = { solicitudes: 0, mensajes: 0 };

// Actualiza los contadores rojos de solicitudes y mensajes.
function pintarInsignias(solicitudes, mensajes) {
    if (solicitudes !== undefined) insignias.solicitudes = solicitudes;
    if (mensajes !== undefined) insignias.mensajes = mensajes;
    const total = insignias.solicitudes + insignias.mensajes;
    [['nav-social-badge', total], ['social-amigos-badge', insignias.solicitudes + insignias.mensajes],
     ['social-chat-badge', insignias.mensajes]].forEach(([id, n]) => {
        const el = document.getElementById(id);
        if (!el) return;
        el.textContent = n;
        el.style.display = n > 0 ? '' : 'none';
    });
}

// Pide esos contadores al servidor.
async function actualizarInsignias() {
    try {
        const r = await window.pywebview.api.obtener_resumen_social();
        if (r && r.exito) pintarInsignias(r.solicitudes, r.mensajes);
    } catch (e) { /* sin conexión: se deja como estaba */ }
}

// Consulta los contadores cada 20 s.
function iniciarInsignias() {
    detenerInsignias();
    actualizarInsignias();
    insigniaTimer = setInterval(actualizarInsignias, 20000);
}

// Detiene esa consulta y los pone en cero.
function detenerInsignias() {
    if (insigniaTimer) clearInterval(insigniaTimer);
    insigniaTimer = null;
    pintarInsignias(0, 0);
}

// ============================================================================
// CAMBIO DE CUENTA: estado limpio
// ============================================================================

// Deja la interfaz limpia: nada de una cuenta debe verse en la siguiente.
function reiniciarEstadoUI() {
    // Estado en memoria
    perfilActual = null;
    consolaSeleccionada = 'todas';
    juegoDetalleActual = null;
    opinionPuntuacion = 0;
    scrollBiblioteca = 0;
    perfilAjenoId = null;
    socialSeccion = 'amigos';
    clearTimeout(busquedaTimer);
    pintarInsignias(0, 0);

    // Campos de texto
    ['login-email', 'login-pass', 'reg-username', 'reg-email', 'reg-pass', 'search-input', 'friend-search',
     'opinion-text', 'profile-bio', 'ra-user', 'ra-key', 'code-input', 'wish-titulo', 'wish-consola', 'chat-texto'].forEach(id => {
        const el = document.getElementById(id);
        if (el) el.value = '';
    });
    ['login-remember', 'privacy-share', 'privacy-history', 'privacy-deseados'].forEach(id => {
        const el = document.getElementById(id);
        if (el) el.checked = false;
    });

    // Textos y listas que dependen de la cuenta
    ['friend-search-results', 'friend-lists', 'game-grid', 'friends-played', 'friends-wishlist',
     'achievements-content', 'paths-content', 'pa-acciones', 'pa-juegos', 'pa-comun', 'pa-deseados',
     'wish-list', 'wish-sugerencias', 'friends-opiniones', 'mi-recientes', 'mi-deseados', 'bloqueados-lista'].forEach(id => {
        const el = document.getElementById(id);
        if (el) el.innerHTML = '';
    });
    ['header-username', 'profile-username', 'opinion-msg', 'ra-status', 'pa-nombre', 'pa-estado', 'pa-bio',
     'code-msg', 'scan-status', 'scan-status-config', 'auth-error', 'detail-title', 'detail-console', 'wish-msg'].forEach(id => {
        const el = document.getElementById(id);
        if (el) el.textContent = '';
    });
    ['header-avatar', 'profile-avatar', 'pa-avatar'].forEach(id => {
        const el = document.getElementById(id);
        if (el) el.removeAttribute('src');
    });
    document.getElementById('console-list').innerHTML =
        '<li class="active" onclick="seleccionarConsola(\'todas\', this)">Todas</li>';

    // Pantallas y ventanas
    cerrarConfiguracion();
    cerrarPerfil();
    document.getElementById('code-modal').style.display = 'none';
    cerrarDenuncia();
    document.getElementById('game-detail').style.display = 'none';
    document.querySelector('.game-grid-container').style.display = '';
    document.getElementById('social-perfil').style.display = 'none';
    document.getElementById('social-deseados').style.display = 'none';
    document.getElementById('social-amigos').style.display = 'block';
    document.querySelectorAll('.social-nav li').forEach(li => li.classList.toggle('active', li.dataset.social === 'amigos'));
    document.querySelectorAll('.settings-section').forEach(s => s.style.display = (s.id === 'settings-paths') ? 'block' : 'none');
    document.querySelectorAll('.settings-nav li').forEach(li => li.classList.toggle('active', li.dataset.section === 'paths'));
    document.getElementById('social-chat').style.display = 'none';
    reiniciarChat();
    reiniciarPublicaciones();
    mostrarVista('biblioteca');
}

// ============================================================================
// HISTORIAL DE JUEGOS
// ============================================================================

// Fecha relativa: hoy, ayer, hace N días.
function formatearFecha(iso) {
    if (!iso) return '';
    const d = new Date(iso);
    if (isNaN(d.getTime())) return '';
    const dias = Math.floor((Date.now() - d.getTime()) / 86400000);
    if (dias <= 0) return 'hoy';
    if (dias === 1) return 'ayer';
    if (dias < 30) return `hace ${dias} días`;
    return d.toLocaleDateString('es-AR', { day: 'numeric', month: 'short', year: 'numeric' });
}

// Fila de un juego con mini carátula.
function filaJuego(titulo, subtitulo, identificativo) {
    const fila = document.createElement('div');
    fila.className = 'game-row';
    if (identificativo) fila.appendChild(crearMiniPortada(identificativo, titulo));

    const info = document.createElement('div');
    info.className = 'game-row-info';
    const t = document.createElement('strong');
    t.textContent = titulo;
    const sub = document.createElement('small');
    sub.textContent = subtitulo;
    info.append(t, sub);
    fila.appendChild(info);
    return fila;
}

// Juegos recientes, en común y deseados de un amigo.
function pintarJuegosPerfil(res) {
    const jugados = document.getElementById('pa-juegos');
    const comun = document.getElementById('pa-comun');
    const deseados = document.getElementById('pa-deseados');
    jugados.innerHTML = '';
    comun.innerHTML = '';
    deseados.innerHTML = '';

    if (res.relacion !== 'amigos') {
        jugados.appendChild(mensajeVacio('Solo los amigos pueden ver los juegos que jugó.'));
        comun.appendChild(mensajeVacio('Agregalo a tus amigos para ver qué juegos tienen en común.'));
        deseados.appendChild(mensajeVacio('Solo los amigos pueden ver su lista de deseados.'));
        return;
    }

    const recientes = res.recientes || [];
    if (recientes.length === 0) {
        jugados.appendChild(mensajeVacio('Todavía no hay juegos registrados (o no comparte su historial).'));
    }
    recientes.forEach(j => {
        const veces = `${j.veces} ${j.veces === 1 ? 'vez' : 'veces'}`;
        jugados.appendChild(filaJuego(j.titulo, [j.consola, veces, formatearFecha(j.ultima_vez)].filter(Boolean).join(' · '), j.identificativo));
    });

    const enComun = res.en_comun || [];
    if (enComun.length === 0) {
        comun.appendChild(mensajeVacio('Todavía no tienen juegos en común.'));
    } else {
        const resumen = document.createElement('p');
        resumen.className = 'settings-help';
        resumen.textContent = `${enComun.length} ${enComun.length === 1 ? 'juego' : 'juegos'} en común`;
        comun.appendChild(resumen);
        enComun.forEach(j => comun.appendChild(filaJuego(j.titulo, j.consola, j.identificativo)));
    }

    const lista = res.deseados || [];
    if (lista.length === 0) {
        deseados.appendChild(mensajeVacio('No tiene juegos en su lista de deseados (o no la comparte).'));
    }
    lista.forEach(d => deseados.appendChild(filaJuego(d.titulo, d.consola, d.identificativo)));
}

// Va a Social y abre el perfil de un amigo.
function irAPerfilAmigo(userId) {
    mostrarVista('social');
    seleccionarSeccionSocial('amigos');
    abrirPerfilAjeno(userId);
}

// Avisa antes de borrar el historial publicado.
async function guardarCompartirHistorial() {
    const casilla = document.getElementById('privacy-history');
    if (!casilla.checked && !confirm('Se borrará de la nube el historial de juegos que ya publicaste. ¿Continuar?')) {
        casilla.checked = true;
        return;
    }
    await window.pywebview.api.guardar_compartir_historial(casilla.checked);
}

// ============================================================================
// LISTA DE DESEADOS (Social → Deseados)
// ============================================================================

let consolasDeseadosCargadas = false;
let sugerenciasTimer = null;

// Entra a la sección Deseados.
async function abrirDeseados() {
    await prepararConsolasDeseados();
    await cargarDeseados();
}

// Llena el selector de consolas, una sola vez.
async function prepararConsolasDeseados() {
    if (consolasDeseadosCargadas) return;
    const sel = document.getElementById('wish-consola');
    let consolas = [];
    try {
        consolas = await window.pywebview.api.obtener_consolas_catalogo();
    } catch (e) { /* queda solo el texto de ayuda */ }

    sel.innerHTML = '';
    const vacio = document.createElement('option');
    vacio.value = '';
    vacio.textContent = '— Elegí la consola —';
    sel.appendChild(vacio);
    (consolas || []).forEach(c => {
        const op = document.createElement('option');
        op.value = c.identificativo;
        op.textContent = c.nombre;
        sel.appendChild(op);
    });
    consolasDeseadosCargadas = true;
}

// Mensaje de éxito o error en Deseados.
function mensajeDeseados(texto, esError) {
    const msg = document.getElementById('wish-msg');
    msg.textContent = texto;
    msg.style.color = esError ? '#ff4d4d' : '#66FCF1';
}

// Espera a que dejes de escribir antes de sugerir.
function buscarTitulosConRetraso() {
    clearTimeout(sugerenciasTimer);
    sugerenciasTimer = setTimeout(buscarTitulos, 300);
}

// Sugiere títulos; ignora la respuesta si lo escrito ya cambió.
async function buscarTitulos() {
    const ident = document.getElementById('wish-consola').value;
    const texto = document.getElementById('wish-titulo').value.trim();
    const cont = document.getElementById('wish-sugerencias');
    cont.innerHTML = '';
    if (!ident || texto.length < 2) return;

    cont.appendChild(mensajeVacio('Buscando…'));
    let lista = [];
    try {
        lista = await window.pywebview.api.buscar_titulos(ident, texto);
    } catch (e) { /* sin sugerencias */ }

    // Si mientras tanto cambió lo escrito, esta respuesta ya no sirve
    if (document.getElementById('wish-titulo').value.trim() !== texto ||
        document.getElementById('wish-consola').value !== ident) return;

    cont.innerHTML = '';
    if (!lista || lista.length === 0) {
        cont.appendChild(mensajeVacio('Sin sugerencias. Podés agregarlo igual con el botón.'));
        return;
    }
    lista.forEach(t => {
        const item = document.createElement('div');
        item.className = 'wish-sug';
        const nombre = document.createElement('span');
        nombre.textContent = t;
        item.append(crearMiniPortada(ident, t, true), nombre);
        item.onclick = () => agregarDeseado(t);
        cont.appendChild(item);
    });
}

// Agrega lo que está escrito en el campo.
function agregarDeseadoEscrito() {
    agregarDeseado(document.getElementById('wish-titulo').value);
}

// Agrega un juego a la lista; Python comprueba que exista.
async function agregarDeseado(titulo) {
    const ident = document.getElementById('wish-consola').value;
    titulo = (titulo || '').trim();
    if (!ident) { mensajeDeseados('Elegí primero la consola.', true); return; }
    if (!titulo) { mensajeDeseados('Escribí el nombre del juego.', true); return; }

    let res;
    try {
        res = await window.pywebview.api.agregar_deseado(ident, titulo);
    } catch (e) {
        res = { exito: false, error: String(e) };
    }
    if (res && res.exito) {
        document.getElementById('wish-titulo').value = '';
        document.getElementById('wish-sugerencias').innerHTML = '';
        mensajeDeseados(`✔ "${titulo}" agregado a tu lista.`, false);
        await cargarDeseados();
    } else {
        mensajeDeseados((res && res.error) || 'No se pudo agregar.', true);
    }
}

// Quita un juego de la lista.
async function quitarDeseado(clave) {
    const res = await window.pywebview.api.quitar_deseado(clave);
    if (!res || !res.exito) mensajeDeseados((res && res.error) || 'No se pudo quitar.', true);
    await cargarDeseados();
}

// Dibuja tu lista de deseados.
async function cargarDeseados() {
    const cont = document.getElementById('wish-list');
    if (!cont.children.length) cont.appendChild(mensajeVacio('Cargando…'));

    let res;
    try {
        res = await window.pywebview.api.obtener_mis_deseados();
    } catch (e) {
        res = { exito: false, error: String(e) };
    }
    cont.innerHTML = '';
    if (!res || !res.exito) {
        const err = document.createElement('p');
        err.className = 'error-msg';
        err.textContent = (res && res.error) || 'No se pudo cargar tu lista.';
        cont.appendChild(err);
        return;
    }

    cont.appendChild(tituloBloque('Tu lista', res.deseados.length));
    if (res.deseados.length === 0) {
        cont.appendChild(mensajeVacio('Todavía no agregaste ningún juego. Elegí una consola y buscá un título arriba.'));
        return;
    }
    res.deseados.forEach(d => {
        const fila = document.createElement('div');
        fila.className = 'wish-row';
        const info = document.createElement('div');
        info.className = 'wish-row-info';
        const t = document.createElement('strong');
        t.textContent = d.titulo;
        const s = document.createElement('small');
        s.textContent = [d.consola, 'agregado ' + formatearFecha(d.agregado_en)].filter(Boolean).join(' · ');
        info.append(t, s);
        fila.append(crearMiniPortada(d.identificativo, d.titulo), info, boton('Quitar', 'btn-secondary-sm', () => quitarDeseado(d.clave)));
        cont.appendChild(fila);
    });
}

// Si no se puede guardar, devuelve la casilla a su estado anterior.
async function guardarCompartirDeseados() {
    const casilla = document.getElementById('privacy-deseados');
    const res = await window.pywebview.api.guardar_compartir_deseados(casilla.checked);
    if (!res || !res.exito) {
        alert((res && res.error) || 'No se pudo actualizar la visibilidad de tu lista.');
        casilla.checked = !casilla.checked;   // vuelve a como estaba
    }
}

// ============================================================================
// OPINIONES DE AMIGOS (en el detalle de un juego)
// ============================================================================

// Opiniones de tus amigos sobre un juego.
function pintarOpinionesAmigos(el, opiniones) {
    el.innerHTML = '';
    if (!opiniones || opiniones.length === 0) {
        el.appendChild(mensajeVacio('Ninguno de tus amigos dejó una opinión de este juego todavía.'));
        return;
    }
    opiniones.forEach(o => {
        const item = document.createElement('div');
        item.className = 'opinion-item';

        const cab = document.createElement('div');
        cab.className = 'opinion-head';
        const img = document.createElement('img');
        img.src = avatarDe(o);
        img.alt = '';
        img.onerror = () => { img.style.visibility = 'hidden'; };
        const nombre = document.createElement('strong');
        nombre.textContent = o.username || 'Usuario';
        nombre.className = 'clickable';
        nombre.onclick = () => irAPerfilAmigo(o.user_id);
        const estrellas = document.createElement('span');
        estrellas.className = 'opinion-stars-static';
        estrellas.textContent = o.puntuacion > 0 ? '★'.repeat(o.puntuacion) + '☆'.repeat(5 - o.puntuacion) : '';
        const fecha = document.createElement('small');
        fecha.textContent = formatearFecha(o.actualizado_en);
        cab.append(img, nombre, estrellas, fecha);
        item.appendChild(cab);

        if (o.texto && o.texto.trim() !== '') {
            const t = document.createElement('p');
            t.className = 'opinion-text';
            t.textContent = o.texto;
            item.appendChild(t);
        }
        el.appendChild(item);
    });
}

// ============================================================================
// CARÁTULAS PEQUEÑAS (juegos que no están en tu biblioteca)
// ============================================================================

const cachePortadas = new Map();   // "psx|Silent Hill" -> promesa con {url, path} o null
const colaPortadas = [];
let portadasActivas = 0;

// Pide carátulas de a 3 como máximo para no saturar la conexión.
function procesarColaPortadas() {
    while (portadasActivas < 3 && colaPortadas.length > 0) {
        const tarea = colaPortadas.shift();
        portadasActivas++;
        window.pywebview.api.obtener_portada_juego(tarea.ident, tarea.titulo)
            .then(r => tarea.resolver(r && r.url ? r : null))
            .catch(() => tarea.resolver(null))
            .finally(() => { portadasActivas--; procesarColaPortadas(); });
    }
}

// Pide una carátula una sola vez; si falla, reintenta pasado un minuto.
function solicitarPortada(ident, titulo) {
    const clave = ident + '|' + titulo;
    if (cachePortadas.has(clave)) return cachePortadas.get(clave);
    const promesa = new Promise(resolver => {
        colaPortadas.push({ ident, titulo, resolver });
        procesarColaPortadas();
    });
    cachePortadas.set(clave, promesa);
    // Si no hubo carátula (por ejemplo sin conexión) se vuelve a intentar más tarde
    promesa.then(r => { if (!r) setTimeout(() => cachePortadas.delete(clave), 60000); });
    return promesa;
}

// Carátula pequeña: muestra un emoji hasta que llega la imagen.
function crearMiniPortada(identificativo, titulo, chica) {
    const caja = document.createElement('div');
    caja.className = 'mini-cover' + (chica ? ' mini-cover-sm' : '');
    caja.textContent = '🎮';
    if (!identificativo) return caja;

    solicitarPortada(identificativo, titulo).then(info => {
        if (!info) return;
        const img = document.createElement('img');
        img.alt = '';
        let reintentado = false;
        img.onerror = async () => {
            if (!reintentado && info.path) {
                reintentado = true;
                try {
                    const dataUri = await window.pywebview.api.obtener_portada_data_uri(info.path);
                    if (dataUri) { img.src = dataUri; return; }
                } catch (e) { /* queda el emoji */ }
            }
            img.remove();
            caja.textContent = '🎮';
        };
        img.src = info.url;
        caja.textContent = '';
        caja.appendChild(img);
    });
    return caja;
}

// ============================================================================
// MI PERFIL: juegos jugados y deseados
// ============================================================================

// Juegos recientes y deseados de tu perfil.
async function cargarMiActividad() {
    const recientes = document.getElementById('mi-recientes');
    const deseados = document.getElementById('mi-deseados');
    if (!recientes.children.length) recientes.appendChild(mensajeVacio('Cargando…'));
    if (!deseados.children.length) deseados.appendChild(mensajeVacio('Cargando…'));

    let res;
    try {
        res = await window.pywebview.api.obtener_mi_actividad();
    } catch (e) {
        res = { exito: false, error: String(e) };
    }
    recientes.innerHTML = '';
    deseados.innerHTML = '';
    if (!res || !res.exito) {
        recientes.appendChild(mensajeVacio((res && res.error) || 'No se pudo cargar.'));
        return;
    }

    if (res.recientes.length === 0) {
        recientes.appendChild(mensajeVacio('Todavía no jugaste nada desde el launcher.'));
    }
    res.recientes.forEach(j => {
        const veces = `${j.veces} ${j.veces === 1 ? 'vez' : 'veces'}`;
        recientes.appendChild(filaJuego(j.titulo, [j.consola, veces, formatearFecha(j.ultima_vez)].filter(Boolean).join(' · '), j.identificativo));
    });

    if (res.deseados.length === 0) {
        deseados.appendChild(mensajeVacio('Tu lista está vacía. Podés agregar juegos en Social → Deseados.'));
    }
    res.deseados.forEach(d => deseados.appendChild(filaJuego(d.titulo, d.consola, d.identificativo)));
}

// ============================================================================
// CHAT
// ============================================================================

let chatAmigo = null;               // conversación abierta
let chatConversaciones = [];
let chatMensajes = [];              // mensajes de la conversación abierta, en orden
let chatIds = new Set();
let chatPendientes = new Set();     // mis mensajes que el otro todavía no vio
let chatUltimoId = 0;
let chatHayMas = false;
let chatTimer = null;
let chatListaTimer = null;
let chatOcupado = false;

// Entra al chat y consulta novedades cada 4 s, y la lista cada 10 s.
function abrirChat() {
    detenerChat();
    cargarConversaciones();
    if (chatAmigo) abrirConversacion(chatAmigo.user_id);   // se refresca lo que quedó abierto
    chatTimer = setInterval(sincronizarChat, 4000);
    chatListaTimer = setInterval(cargarConversaciones, 10000);
}

// Detiene esas consultas.
function detenerChat() {
    if (chatTimer) clearInterval(chatTimer);
    if (chatListaTimer) clearInterval(chatListaTimer);
    chatTimer = null;
    chatListaTimer = null;
}

// Olvida todo el chat al cambiar de cuenta.
function reiniciarChat() {
    detenerChat();
    cerrarPicker();
    chatAmigo = null;
    chatConversaciones = [];
    chatMensajes = [];
    chatIds = new Set();
    chatPendientes = new Set();
    chatUltimoId = 0;
    chatHayMas = false;
    chatOcupado = false;
    chatLlamadas = [];
    imagenesChat.clear();
    imagenesChatPendientes.clear();
    imagenesChatFallidas.clear();
    categoriaEmojiElegida = false;
    ['imagen-modal', 'sticker-modal', 'visor-modal', 'picker'].forEach(id => document.getElementById(id).style.display = 'none');
    document.getElementById('chat-activo').style.display = 'none';
    document.getElementById('chat-vacio').style.display = '';
    document.getElementById('chat-error').textContent = '';
    document.querySelector('.social-content').classList.remove('chat-vista');
}

// Separador de día: Hoy, Ayer o la fecha.
function etiquetaDia(iso) {
    const d = new Date(iso);
    if (isNaN(d.getTime())) return '';
    const hoy = new Date();
    const dias = Math.round((new Date(hoy.getFullYear(), hoy.getMonth(), hoy.getDate()) -
                             new Date(d.getFullYear(), d.getMonth(), d.getDate())) / 86400000);
    if (dias === 0) return 'Hoy';
    if (dias === 1) return 'Ayer';
    return d.toLocaleDateString('es-AR', { day: 'numeric', month: 'long', year: 'numeric' });
}

// Hora de un mensaje.
function horaDe(iso) {
    const d = new Date(iso);
    return isNaN(d.getTime()) ? '' : d.toLocaleTimeString('es-AR', { hour: '2-digit', minute: '2-digit' });
}

// Dibuja la lista de chats y actualiza los contadores.
async function cargarConversaciones() {
    const cont = document.getElementById('chat-list');
    let res;
    try {
        res = await window.pywebview.api.obtener_conversaciones();
    } catch (e) {
        res = { exito: false, error: String(e) };
    }
    if (!res || !res.exito) {
        if (!cont.children.length) {
            cont.appendChild(mensajeVacio((res && res.error) || 'No se pudieron cargar las conversaciones.'));
        }
        return;
    }

    chatConversaciones = res.conversaciones || [];
    pintarInsignias(undefined, chatConversaciones.reduce((n, c) => n + c.no_leidos, 0));

    cont.innerHTML = '';
    if (chatConversaciones.length === 0) {
        cont.appendChild(mensajeVacio('Todavía no tenés amigos con quienes chatear. Agregalos en la sección Amigos.'));
        return;
    }
    chatConversaciones.forEach(c => {
        const item = document.createElement('div');
        item.className = 'chat-item' + (chatAmigo && chatAmigo.user_id === c.user_id ? ' active' : '');
        item.onclick = () => abrirConversacion(c.user_id);

        const img = document.createElement('img');
        img.src = avatarDe(c);
        img.alt = '';
        img.onerror = () => { img.style.visibility = 'hidden'; };

        const info = document.createElement('div');
        info.className = 'chat-item-info';
        const nombre = document.createElement('strong');
        nombre.textContent = c.username + (c.en_llamada ? ' 📞' : '') + (c.jugando ? ' 🎮' : '');
        const previo = document.createElement('small');
        previo.textContent = c.ultimo ? (c.ultimo.mio ? 'Tú: ' : '') + c.ultimo.texto : 'Sin mensajes todavía';
        info.append(nombre, previo);

        const meta = document.createElement('div');
        meta.className = 'chat-item-meta';
        if (c.ultimo) {
            const hora = document.createElement('small');
            hora.textContent = etiquetaDia(c.ultimo.creado_en) === 'Hoy' ? horaDe(c.ultimo.creado_en) : etiquetaDia(c.ultimo.creado_en);
            meta.appendChild(hora);
        }
        if (c.no_leidos > 0) {
            const b = document.createElement('span');
            b.className = 'count-badge';
            b.textContent = c.no_leidos;
            meta.appendChild(b);
        }
        item.append(img, info, meta);
        cont.appendChild(item);
    });
}

// Agrega un mensaje sin repetirlo; devuelve false si ya estaba.
function registrarMensaje(m) {
    if (chatIds.has(m.id)) return false;
    chatIds.add(m.id);
    chatMensajes.push(m);
    chatMensajes.sort((a, b) => a.id - b.id);
    if (m.id > chatUltimoId) chatUltimoId = m.id;
    if (m.mio && !m.leido) chatPendientes.add(m.id);
    return true;
}

// Crea la burbuja según el tipo: texto, imagen, sticker, GIF o publicación.
function crearBurbuja(m) {
    const fila = document.createElement('div');
    fila.className = 'msg ' + (m.mio ? 'msg-mio' : 'msg-otro');

    const burbuja = document.createElement('div');
    burbuja.className = 'msg-burbuja';
    if (m.tipo === 'imagen' || m.tipo === 'sticker' || m.tipo === 'gif') {
        burbuja.className = 'msg-burbuja msg-media' + (m.tipo === 'sticker' ? ' msg-sticker' : '');
        const img = document.createElement('img');
        img.alt = '';
        img.className = m.tipo === 'sticker' ? 'chat-sticker' : (m.tipo === 'gif' ? 'chat-gif' : 'chat-imagen');
        img.onload = () => {
            if (chatPegadoAbajo) {   // al cargar la imagen el hilo crece: se sigue pegado al final
                const c = document.getElementById('chat-mensajes');
                c.scrollTop = c.scrollHeight;
            }
        };
        if (m.tipo !== 'sticker') img.onclick = () => abrirVisor(img.src);
        if (m.tipo === 'gif') {
            if (urlGifPermitida(m.contenido)) {
                img.src = m.contenido;
                img.onerror = () => { img.classList.add('rota'); img.alt = '⚠️ No se pudo cargar el GIF'; };
            } else {
                img.classList.add('rota');
                img.alt = '⚠️ GIF no válido';
            }
        } else {
            cargarImagenEn(img, m.contenido);
        }
        burbuja.appendChild(img);
    } else if (m.tipo === 'publicacion') {
        burbuja.className = 'msg-burbuja msg-publicacion';
        burbuja.appendChild(crearTarjetaCompartida(m.contenido));
    } else {
        burbuja.textContent = m.tipo === 'texto' ? m.contenido : '📎 Contenido que esta versión todavía no puede mostrar';
        if (m.tipo === 'texto' && esSoloEmojis(m.contenido)) burbuja.classList.add('msg-emoji');
    }

    const meta = document.createElement('div');
    meta.className = 'msg-meta';
    const hora = document.createElement('span');
    hora.textContent = horaDe(m.creado_en);
    meta.appendChild(hora);
    if (m.mio) {
        const estado = document.createElement('span');
        estado.className = 'msg-estado' + (m.leido ? ' visto' : '');
        estado.textContent = m.leido ? '✓✓ Visto' : '✓';
        meta.appendChild(estado);
    }
    fila.append(burbuja, meta);
    return fila;
}

// modo: 'fondo' baja al último mensaje; 'normal' respeta dónde estabas leyendo;
// 'anteriores' mantiene la posición al agregar mensajes viejos arriba
function renderizarChat(modo, alturaAntes) {
    const cont = document.getElementById('chat-mensajes');
    const distanciaAlFondo = cont.scrollHeight - cont.scrollTop - cont.clientHeight;
    cont.innerHTML = '';

    if (chatHayMas) {
        cont.appendChild(boton('Cargar mensajes anteriores', 'btn-secondary-sm chat-mas', cargarAnteriores));
    }
    if (chatItemsOrdenados().length === 0) {
        cont.appendChild(mensajeVacio('Todavía no hay mensajes. ¡Escribí el primero!'));
    }
    let dia = '';
    chatItemsOrdenados().forEach(m => {
        const etiqueta = etiquetaDia(m.creado_en);
        if (etiqueta !== dia) {
            const sep = document.createElement('div');
            sep.className = 'msg-dia';
            sep.textContent = etiqueta;
            cont.appendChild(sep);
            dia = etiqueta;
        }
        cont.appendChild(m.tipo === 'registro_llamada' ? crearRegistroLlamada(m) : crearBurbuja(m));
    });

    chatPegadoAbajo = (modo === 'fondo' || distanciaAlFondo < 80);
    if (modo === 'fondo' || distanciaAlFondo < 80) cont.scrollTop = cont.scrollHeight;
    else if (modo === 'anteriores') cont.scrollTop = cont.scrollHeight - alturaAntes;
}

// Abre un chat; ignora la respuesta si mientras tanto cambiaste de chat.
async function abrirConversacion(amigoId) {
    const conv = chatConversaciones.find(c => c.user_id === amigoId) || chatAmigo;
    if (!conv || conv.user_id !== amigoId) return;
    chatAmigo = conv;

    document.getElementById('chat-vacio').style.display = 'none';
    document.getElementById('chat-activo').style.display = 'flex';
    document.getElementById('chat-error').textContent = '';
    document.getElementById('picker').style.display = 'none';
    document.getElementById('chat-nombre').textContent = conv.username;
    document.getElementById('chat-estado').textContent = textoActividad(conv.en_llamada, conv.jugando);
    const avatar = document.getElementById('chat-avatar');
    avatar.src = avatarDe(conv);
    document.querySelectorAll('.chat-item').forEach(i => i.classList.remove('active'));

    let res;
    try {
        res = await window.pywebview.api.obtener_mensajes(amigoId, null);
    } catch (e) {
        res = { exito: false, error: String(e) };
    }
    if (!chatAmigo || chatAmigo.user_id !== amigoId) return;   // cambió de conversación mientras cargaba
    if (!res || !res.exito) {
        document.getElementById('chat-error').textContent = (res && res.error) || 'No se pudieron cargar los mensajes.';
        return;
    }

    chatMensajes = [];
    chatIds = new Set();
    chatPendientes = new Set();
    chatUltimoId = 0;
    res.mensajes.forEach(registrarMensaje);
    chatHayMas = !!res.hay_mas;
    chatLlamadas = [];
    renderizarChat('fondo');
    document.getElementById('chat-texto').focus();
    chatRefrescarLlamadas();   // registro de llamadas con este amigo
    cargarConversaciones();   // refresca "sin leer"
}

// Trae mensajes más viejos manteniendo la posición.
async function cargarAnteriores() {
    if (!chatAmigo || chatMensajes.length === 0) return;
    const id = chatAmigo.user_id;
    const primero = chatMensajes[0].id;
    const cont = document.getElementById('chat-mensajes');
    const alturaAntes = cont.scrollHeight;
    let res;
    try {
        res = await window.pywebview.api.obtener_mensajes(id, primero);
    } catch (e) {
        return;
    }
    if (!chatAmigo || chatAmigo.user_id !== id || !res || !res.exito) return;
    res.mensajes.forEach(registrarMensaje);
    chatHayMas = !!res.hay_mas;
    renderizarChat('anteriores', alturaAntes);
}

// Consulta periódica de mensajes nuevos y vistos.
async function sincronizarChat() {
    if (chatOcupado || !chatAmigo) return;
    chatOcupado = true;
    const id = chatAmigo.user_id;
    try {
        const res = await window.pywebview.api.sincronizar_chat(id, chatUltimoId, Array.from(chatPendientes));
        if (!chatAmigo || chatAmigo.user_id !== id || !res || !res.exito) return;

        let cambio = false, llegaron = false;
        (res.nuevos || []).forEach(m => {
            if (registrarMensaje(m)) { cambio = true; if (!m.mio) llegaron = true; }
        });
        (res.vistos || []).forEach(vid => {
            chatPendientes.delete(vid);
            const m = chatMensajes.find(x => x.id === vid);
            if (m && !m.leido) { m.leido = true; cambio = true; }
        });
        if (cambio) renderizarChat('normal');
        if (llegaron) cargarConversaciones();
    } catch (e) {
        /* sin conexión: se reintenta en la próxima vuelta */
    } finally {
        chatOcupado = false;
    }
}

// Envía el texto escrito.
async function enviarMensaje() {
    if (!chatAmigo) return;
    const caja = document.getElementById('chat-texto');
    const texto = caja.value.trim();
    if (!texto) return;
    const id = chatAmigo.user_id;
    const btn = document.getElementById('chat-enviar');
    const error = document.getElementById('chat-error');
    btn.disabled = true;
    error.textContent = '';

    let res;
    try {
        res = await window.pywebview.api.enviar_mensaje(id, texto);
    } catch (e) {
        res = { exito: false, error: String(e) };
    }
    btn.disabled = false;

    if (res && res.exito) {
        caja.value = '';
        autoAjustarChat(caja);
        if (chatAmigo && chatAmigo.user_id === id) {
            registrarMensaje(res.mensaje);
            renderizarChat('fondo');
        }
        cargarConversaciones();
    } else {
        error.textContent = (res && res.error) || 'No se pudo enviar el mensaje.';
        if (res && res.falta_mi_llave) llavesIniciar();
    }
    caja.focus();
}

// Enter envía; Mayús + Enter hace un salto de línea.
function teclaChat(ev) {
    if (ev.key === 'Enter' && !ev.shiftKey) {
        ev.preventDefault();
        enviarMensaje();
    }
}

// La caja crece con el texto, hasta un máximo.
function autoAjustarChat(caja) {
    caja.style.height = 'auto';
    caja.style.height = Math.min(caja.scrollHeight, 100) + 'px';
}

// Abre el perfil de la persona del chat.
function verPerfilDelChat() {
    if (chatAmigo) irAPerfilAmigo(chatAmigo.user_id);
}

// Va directamente al chat con un amigo.
async function irAlChat(userId) {
    mostrarVista('social');
    seleccionarSeccionSocial('chat');
    await cargarConversaciones();
    abrirConversacion(userId);
}

// ============================================================================
// CHAT: IMÁGENES Y STICKERS
// ============================================================================

const imagenesChat = new Map();             // ruta -> data URI ya descargado
const imagenesChatPendientes = new Map();   // ruta -> promesa en curso
const imagenesChatFallidas = new Map();     // ruta -> cuándo falló (no se insiste durante un minuto)
const colaImagenesChat = [];
let imagenesChatActivas = 0;
let chatPegadoAbajo = true;
let vistaStickerToken = 0;

// Recuerda si estás al final para seguir pegado a los mensajes nuevos.
function alScrollChat() {
    const c = document.getElementById('chat-mensajes');
    chatPegadoAbajo = (c.scrollHeight - c.scrollTop - c.clientHeight) < 80;
}

// Descarga imágenes de a 3 como máximo.
function procesarColaImagenesChat() {
    while (imagenesChatActivas < 3 && colaImagenesChat.length > 0) {
        const tarea = colaImagenesChat.shift();
        imagenesChatActivas++;
        window.pywebview.api.obtener_imagen_chat(tarea.ruta)
            .then(r => tarea.resolver(r || null))
            .catch(() => tarea.resolver(null))
            .finally(() => { imagenesChatActivas--; procesarColaImagenesChat(); });
    }
}

// Devuelve la imagen desde memoria o la descarga; si falla, espera un minuto.
function obtenerImagenChat(ruta) {
    if (imagenesChat.has(ruta)) return Promise.resolve(imagenesChat.get(ruta));
    if (imagenesChatPendientes.has(ruta)) return imagenesChatPendientes.get(ruta);
    if (Date.now() - (imagenesChatFallidas.get(ruta) || 0) < 60000) return Promise.resolve(null);
    const promesa = new Promise(resolver => {
        colaImagenesChat.push({ ruta, resolver });
        procesarColaImagenesChat();
    });
    imagenesChatPendientes.set(ruta, promesa);
    promesa.then(uri => {
        imagenesChatPendientes.delete(ruta);
        if (uri) imagenesChat.set(ruta, uri);
        else imagenesChatFallidas.set(ruta, Date.now());
    });
    return promesa;
}

// Coloca una imagen del chat en un <img>.
function cargarImagenEn(img, ruta) {
    if (imagenesChat.has(ruta)) {          // ya la tenemos: sin parpadeo al redibujar el hilo
        img.src = imagenesChat.get(ruta);
        return;
    }
    obtenerImagenChat(ruta).then(uri => {
        if (uri) {
            img.src = uri;
        } else {
            img.classList.add('rota');
            img.alt = '⚠️ No se pudo cargar la imagen';
        }
    });
}

// Muestra un error, salvo que el usuario haya cancelado.
function mostrarErrorChat(res) {
    if (res && res.error && res.error !== 'cancelado') {
        document.getElementById('chat-error').textContent = res.error;
    }
}

// Muestra una imagen en grande.
function abrirVisor(src) {
    if (!src) return;
    document.getElementById('visor-img').src = src;
    document.getElementById('visor-modal').style.display = 'flex';
}

// Cierra el visor.
function cerrarVisor() {
    document.getElementById('visor-modal').style.display = 'none';
}

// --- Enviar una imagen ---

// Abre el selector y muestra la vista previa antes de enviar.
async function elegirImagenChat() {
    if (!chatAmigo) return;
    document.getElementById('chat-error').textContent = '';
    let res;
    try {
        res = await window.pywebview.api.seleccionar_imagen();
    } catch (e) {
        res = { exito: false, error: String(e) };
    }
    if (!res || !res.exito) { mostrarErrorChat(res); return; }

    document.getElementById('imagen-vista').src = res.vista;
    document.getElementById('imagen-nombre').textContent = res.nombre;
    document.getElementById('imagen-msg').textContent = '';
    document.getElementById('imagen-enviar').disabled = false;
    document.getElementById('imagen-modal').style.display = 'flex';
}

// Cancela el envío de la imagen.
function cerrarImagenModal() {
    document.getElementById('imagen-modal').style.display = 'none';
    window.pywebview.api.descartar_imagen();
}

// Envía la imagen elegida.
async function confirmarEnvioImagen() {
    if (!chatAmigo) return;
    const id = chatAmigo.user_id;
    const btn = document.getElementById('imagen-enviar');
    const msg = document.getElementById('imagen-msg');
    btn.disabled = true;
    msg.textContent = 'Enviando…';

    let res;
    try {
        res = await window.pywebview.api.enviar_imagen(id);
    } catch (e) {
        res = { exito: false, error: String(e) };
    }
    btn.disabled = false;
    if (!res || !res.exito) {
        msg.textContent = (res && res.error) || 'No se pudo enviar la imagen.';
        return;
    }
    document.getElementById('imagen-modal').style.display = 'none';
    if (chatAmigo && chatAmigo.user_id === id) {
        registrarMensaje(res.mensaje);
        renderizarChat('fondo');
    }
    cargarConversaciones();
}

// --- Stickers ---

// Usa la imagen elegida para crear un sticker.
function convertirImagenEnSticker() {
    document.getElementById('imagen-modal').style.display = 'none';   // la imagen elegida se conserva
    abrirEditorSticker();
}

// Elige una imagen y abre el editor de stickers.
async function crearStickerNuevo() {
    let res;
    try {
        res = await window.pywebview.api.seleccionar_imagen();
    } catch (e) {
        res = { exito: false, error: String(e) };
    }
    if (!res || !res.exito) { mostrarErrorChat(res); return; }
    abrirEditorSticker();
}

// Abre el editor de stickers.
function abrirEditorSticker() {
    document.getElementById('sticker-msg').textContent = '';
    document.getElementById('sticker-vista').removeAttribute('src');
    document.getElementById('sticker-modal').style.display = 'flex';
    actualizarVistaSticker();
}

// Cierra el editor y olvida la imagen.
function cerrarStickerModal() {
    document.getElementById('sticker-modal').style.display = 'none';
    window.pywebview.api.descartar_imagen();
}

// Forma, ajuste y contorno elegidos.
function opcionesSticker() {
    return [document.getElementById('sticker-forma').value,
            document.getElementById('sticker-ajuste').value,
            document.getElementById('sticker-contorno').checked];
}

// Actualiza la vista previa; el token descarta respuestas viejas.
async function actualizarVistaSticker() {
    const token = ++vistaStickerToken;
    const msg = document.getElementById('sticker-msg');
    let res;
    try {
        res = await window.pywebview.api.previsualizar_sticker(...opcionesSticker());
    } catch (e) {
        res = { exito: false, error: String(e) };
    }
    if (token !== vistaStickerToken) return;   // cambió una opción mientras se generaba
    if (res && res.exito) {
        msg.textContent = '';
        document.getElementById('sticker-vista').src = res.vista;
    } else {
        msg.textContent = (res && res.error) || 'No se pudo generar la vista previa.';
    }
}

// Crea el sticker y, si se pidió, lo envía.
async function guardarSticker(enviar) {
    const msg = document.getElementById('sticker-msg');
    const botones = [document.getElementById('sticker-guardar'), document.getElementById('sticker-guardar-enviar')];
    botones.forEach(b => b.disabled = true);
    msg.textContent = 'Guardando…';

    let res;
    try {
        res = await window.pywebview.api.crear_sticker(...opcionesSticker());
    } catch (e) {
        res = { exito: false, error: String(e) };
    }
    botones.forEach(b => b.disabled = false);
    if (!res || !res.exito) {
        msg.textContent = (res && res.error) || 'No se pudo guardar el sticker.';
        return;
    }

    cerrarStickerModal();
    if (document.getElementById('picker').style.display !== 'none') cargarStickers();
    if (enviar && chatAmigo) enviarStickerChat(res.sticker.ruta);
}

// Dibuja tu colección de stickers.
async function cargarStickers() {
    const grilla = document.getElementById('sticker-grid');
    if (!grilla.children.length) grilla.appendChild(mensajeVacio('Cargando…'));

    let res;
    try {
        res = await window.pywebview.api.obtener_stickers();
    } catch (e) {
        res = { exito: false, error: String(e) };
    }
    grilla.innerHTML = '';
    if (!res || !res.exito) {
        grilla.appendChild(mensajeVacio((res && res.error) || 'No se pudieron cargar tus stickers.'));
        return;
    }
    res.stickers = res.stickers || [];
    if (res.stickers.length === 0) {
        grilla.appendChild(mensajeVacio('Todavía no tenés stickers. Tocá "＋ Crear sticker" para hacer el primero con una de tus imágenes.'));
        return;
    }
    res.stickers.forEach(s => {
        const item = document.createElement('div');
        item.className = 'sticker-item';
        item.title = 'Enviar';
        item.onclick = () => enviarStickerChat(s.ruta);

        const img = document.createElement('img');
        img.alt = '';
        cargarImagenEn(img, s.ruta);

        const x = document.createElement('button');
        x.className = 'sticker-borrar';
        x.textContent = '✕';
        x.title = 'Quitar de mi colección';
        x.onclick = ev => { ev.stopPropagation(); quitarStickerPropio(s.id); };

        item.append(img, x);
        grilla.appendChild(item);
    });
}

// Quita un sticker de tu colección.
async function quitarStickerPropio(id) {
    if (!confirm('¿Quitar este sticker de tu colección? Los que ya enviaste se siguen viendo.')) return;
    await window.pywebview.api.eliminar_sticker(id);
    cargarStickers();
}

// Envía un sticker por el chat.
async function enviarStickerChat(ruta) {
    if (!chatAmigo) return;
    const id = chatAmigo.user_id;
    document.getElementById('picker').style.display = 'none';

    let res;
    try {
        res = await window.pywebview.api.enviar_sticker(id, ruta);
    } catch (e) {
        res = { exito: false, error: String(e) };
    }
    if (!res || !res.exito) {
        document.getElementById('chat-error').textContent = (res && res.error) || 'No se pudo enviar el sticker.';
        return;
    }
    if (chatAmigo && chatAmigo.user_id === id) {
        registrarMensaje(res.mensaje);
        renderizarChat('fondo');
    }
    cargarConversaciones();
}

// ============================================================================
// CHAT: PANEL DE EMOJIS, STICKERS Y GIFS
// ============================================================================

const EMOJIS = {
    'Caritas': ['😀','😃','😄','😁','😆','😅','🤣','😂','🙂','🙃','😉','😊','😇','🥰','😍','🤩','😘','😗','😚','😋','😛','😜','🤪','😝','🤑','🤗','🤭','🤫','🤔','🤐','🤨','😐','😑','😶','😏','😒','🙄','😬','🤥','😌','😔','😪','🤤','😴','😷','🤒','🤕','🤢','🤮','🤧','🥵','🥶','🥴','😵','🤯','🤠','🥳','😎','🤓','🧐','😕','😟','🙁','😮','😯','😲','😳','🥺','😦','😧','😨','😰','😥','😢','😭','😱','😖','😣','😞','😓','😩','😫','🥱','😤','😡','😠','🤬','😈','👿','💀','☠️','💩','🤡','👹','👺','👻','👽','👾','🤖'],
    'Gestos': ['👋','🤚','🖐️','✋','🖖','👌','🤌','🤏','✌️','🤞','🤟','🤘','🤙','👈','👉','👆','👇','☝️','👍','👎','✊','👊','🤛','🤜','👏','🙌','👐','🤲','🤝','🙏','💪','🫶','❤️','🧡','💛','💚','💙','💜','🖤','🤍','🤎','💔','💕','💞','💓','💗','💖','💘','💝'],
    'Juegos': ['🎮','🕹️','👾','🏆','🥇','🥈','🥉','🎲','🎯','🧩','♟️','🃏','🎰','🎳','⚔️','🛡️','🗡️','🏹','💣','🔫','🪄','👑','💎','🍄','⭐','🌟','✨','⚡','🔥','💥','🚀','🛸','🕶️','📼','💾','📺','🎧','🎵','🎶','🎤','🎸','🥁','🎹'],
    'Animales': ['🐶','🐱','🐭','🐹','🐰','🦊','🐻','🐼','🐨','🐯','🦁','🐮','🐷','🐸','🐵','🙈','🙉','🙊','🐔','🐧','🐦','🐤','🦆','🦅','🦉','🦇','🐺','🐗','🐴','🦄','🐝','🐛','🦋','🐌','🐞','🐢','🐍','🦎','🐙','🦑','🦀','🐠','🐬','🐳','🦈','🐘','🦒','🦘','🐕','🐈'],
    'Comida': ['🍎','🍌','🍇','🍓','🍉','🍑','🍒','🍍','🥝','🍅','🥑','🌽','🥕','🍔','🍟','🍕','🌭','🥪','🌮','🌯','🍝','🍜','🍣','🍤','🍩','🍪','🎂','🍰','🍫','🍬','🍭','🍿','☕','🍵','🍺','🍻','🥂','🍷','🥤','🧉','🍾'],
    'Objetos': ['⚽','🏀','🏈','⚾','🎾','🏐','🏓','🥊','🎬','🎨','🎭','🎪','🎉','🎊','🎁','🎈','📷','📱','💻','⌨️','🖥️','🔋','💡','📚','✏️','📌','🔒','🔑','⏰','💰','🚗','✈️','🌍','🌈','☀️','🌙','☁️','❄️','🌊'],
    'Símbolos': ['✅','❌','⭕','❗','❓','‼️','💯','🔴','🟠','🟡','🟢','🔵','🟣','⚫','⚪','➕','➖','➡️','⬅️','⬆️','⬇️','🔄','▶️','⏸️','⏹️','⏩','⏪','🔔','🔇','💤','💢','💬','💭','🆗','🆒','🆕','🔝','⚠️','🚫','♻️'],
};
const ICONOS_EMOJI = { 'Recientes': '🕘', 'Caritas': '😀', 'Gestos': '👍', 'Juegos': '🎮', 'Animales': '🐶', 'Comida': '🍔', 'Objetos': '🎁', 'Símbolos': '✅' };

let pestanaPicker = 'emojis';
let categoriaEmoji = 'Caritas';
let emojisRecientes = [];
let categoriaEmojiElegida = false;   // mientras no elijas una, se abre en "Recientes" si tenés

// Detecta mensajes de solo emojis para mostrarlos más grandes.
function esSoloEmojis(texto) {
    const t = (texto || '').trim();
    if (!t || [...t].length > 10) return false;
    return /^[\p{Extended_Pictographic}\p{Emoji_Modifier}\uFE0F\u200D\s]+$/u.test(t) && /\p{Extended_Pictographic}/u.test(t);
}

// El mismo panel (emojis · stickers · GIFs) sirve para el chat, para redactar una publicación
// y para comentar: se mueve al lugar donde se abre y recuerda a quién entrega lo que elegís.
//   destino = { id, caja: <input/textarea donde van los emojis>, gif: función(url) | null, stickers: bool }
let pickerDestino = null;

// Muestra solo las pestañas que admite el destino actual.
function ajustarPestanasPicker() {
    const d = pickerDestino || {};
    const visibles = { emojis: true, stickers: !!d.stickers, gifs: !!d.gif };
    document.querySelectorAll('.picker-tab').forEach(b => {
        b.style.display = visibles[b.dataset.tab] ? '' : 'none';
    });
    if (!visibles[pestanaPicker]) pestanaPicker = 'emojis';
}

// Abre el panel en ese lugar; el mismo botón también lo cierra.
function abrirPickerEn(contenedor, destino, antesDe) {
    const panel = document.getElementById('picker');
    if (panel.style.display !== 'none' && pickerDestino && pickerDestino.id === destino.id) {
        cerrarPicker();   // el mismo botón lo abre y lo cierra
        return;
    }
    contenedor.insertBefore(panel, antesDe || null);
    pickerDestino = destino;
    ajustarPestanasPicker();
    panel.style.display = 'block';
    return elegirPestanaPicker(pestanaPicker);
}

// Devuelve el panel a su lugar dentro del chat.
function moverPickerAChat() {
    const panel = document.getElementById('picker');
    const activo = document.getElementById('chat-activo');
    if (panel.parentElement !== activo) activo.insertBefore(panel, activo.querySelector('.chat-composer'));
}

// Cierra el panel.
function cerrarPicker() {
    document.getElementById('picker').style.display = 'none';
    pickerDestino = null;
    moverPickerAChat();
}

// Botón de emojis del chat.
function alternarPicker() {
    const activo = document.getElementById('chat-activo');
    const destino = { id: 'chat', caja: document.getElementById('chat-texto'), gif: enviarGifChat, stickers: true };
    return abrirPickerEn(activo, destino, activo.querySelector('.chat-composer'));
}

// Cambia entre emojis, stickers y GIFs.
function elegirPestanaPicker(nombre) {
    pestanaPicker = nombre;
    ['emojis', 'stickers', 'gifs'].forEach(n => {
        document.getElementById('picker-' + n).style.display = (n === nombre) ? 'block' : 'none';
    });
    document.querySelectorAll('.picker-tab').forEach(b => b.classList.toggle('active', b.dataset.tab === nombre));
    if (nombre === 'emojis') return abrirEmojis();
    if (nombre === 'stickers') return cargarStickers();
    return abrirGifs();
}

// --- Emojis ---

// Carga los recientes y dibuja los emojis.
async function abrirEmojis() {
    try {
        emojisRecientes = (await window.pywebview.api.obtener_emojis_recientes()) || [];
    } catch (e) {
        emojisRecientes = [];
    }
    if (emojisRecientes.length && !categoriaEmojiElegida) categoriaEmoji = 'Recientes';
    pintarCategoriasEmoji();
    pintarEmojis();
}

// Dibuja las categorías.
function pintarCategoriasEmoji() {
    const cont = document.getElementById('emoji-cats');
    cont.innerHTML = '';
    const cats = (emojisRecientes.length ? ['Recientes'] : []).concat(Object.keys(EMOJIS));
    if (!cats.includes(categoriaEmoji)) categoriaEmoji = cats[0];
    cats.forEach(c => {
        const b = document.createElement('button');
        b.className = 'emoji-cat' + (c === categoriaEmoji ? ' active' : '');
        b.textContent = ICONOS_EMOJI[c] || c;
        b.title = c;
        b.onclick = () => { categoriaEmoji = c; categoriaEmojiElegida = true; pintarCategoriasEmoji(); pintarEmojis(); };
        cont.appendChild(b);
    });
}

// Dibuja los emojis de la categoría elegida.
function pintarEmojis() {
    const grilla = document.getElementById('emoji-grid');
    grilla.innerHTML = '';
    const lista = categoriaEmoji === 'Recientes' ? emojisRecientes : (EMOJIS[categoriaEmoji] || []);
    lista.forEach(e => {
        const b = document.createElement('button');
        b.className = 'emoji-item';
        b.textContent = e;
        b.onclick = () => insertarEmoji(e);
        grilla.appendChild(b);
    });
}

// Inserta el emoji donde está el cursor, respetando el límite de la caja.
function insertarEmoji(e) {
    const caja = pickerDestino && pickerDestino.caja;
    if (!caja) return;
    const limite = caja.maxLength > 0 ? caja.maxLength : 1000;
    if (caja.value.length + e.length > limite) return;
    const ini = typeof caja.selectionStart === 'number' ? caja.selectionStart : caja.value.length;
    const fin = typeof caja.selectionEnd === 'number' ? caja.selectionEnd : ini;
    caja.value = caja.value.slice(0, ini) + e + caja.value.slice(fin);
    caja.selectionStart = caja.selectionEnd = ini + e.length;
    caja.dispatchEvent(new Event('input'));   // que cada caja ajuste su altura / contador
    caja.focus();
    emojisRecientes = [e].concat(emojisRecientes.filter(x => x !== e)).slice(0, 24);
    window.pywebview.api.registrar_emoji_reciente(e);
}

// --- GIFs (KLIPY) ---

let gifPagina = 1;
let gifToken = 0;
let gifTimer = null;

// Solo https y servidores de KLIPY. Python hace la misma comprobación.
function urlGifPermitida(url) {
    if (typeof url !== 'string' || url.length > 1000 || /[\s<>"'`\\]/.test(url)) return false;
    try {
        const u = new URL(url);
        const h = u.hostname.toLowerCase();
        return u.protocol === 'https:' &&
            (h === 'klipy.com' || h.endsWith('.klipy.com') || h === 'klipy.co' || h.endsWith('.klipy.co'));
    } catch (e) {
        return false;
    }
}

// Abre la pestaña de GIFs.
function abrirGifs() {
    if (!document.getElementById('gif-grid').children.length) cargarGifs(true);
    document.getElementById('gif-busqueda').focus();
}

// Espera a que dejes de escribir antes de buscar.
function gifBuscarConRetraso() {
    clearTimeout(gifTimer);
    gifTimer = setTimeout(() => cargarGifs(true), 450);
}

// Trae la siguiente página de GIFs.
function gifMas() {
    gifPagina++;
    cargarGifs(false);
}

// Busca GIFs; el token descarta respuestas de una búsqueda anterior.
async function cargarGifs(reiniciar) {
    const token = ++gifToken;
    const grilla = document.getElementById('gif-grid');
    const estado = document.getElementById('gif-estado');
    const mas = document.getElementById('gif-mas');
    const consulta = document.getElementById('gif-busqueda').value.trim();
    if (reiniciar) {
        gifPagina = 1;
        grilla.innerHTML = '';
    }
    mas.style.display = 'none';
    estado.textContent = 'Buscando…';

    let res;
    try {
        res = await window.pywebview.api.buscar_gifs(consulta, gifPagina);
    } catch (e) {
        res = { exito: false, error: String(e) };
    }
    if (token !== gifToken) return;   // se escribió otra cosa mientras buscaba

    if (!res || !res.exito) {
        estado.textContent = (res && res.error) || 'No se pudo buscar GIFs.';
        return;
    }
    const validos = res.gifs.filter(g => urlGifPermitida(g.url));
    estado.textContent = (validos.length === 0 && reiniciar)
        ? (consulta ? 'No se encontraron GIFs para esa búsqueda.' : 'No hay GIFs para mostrar.') : '';

    validos.forEach(g => {
        const item = document.createElement('div');
        item.className = 'gif-item';
        item.title = g.titulo;
        const img = document.createElement('img');
        img.alt = g.titulo;
        img.loading = 'lazy';
        img.src = urlGifPermitida(g.miniatura) ? g.miniatura : g.url;
        // al pasar el mouse se anima
        item.onmouseenter = () => { if (urlGifPermitida(g.vista)) img.src = g.vista; };
        item.onmouseleave = () => { img.src = urlGifPermitida(g.miniatura) ? g.miniatura : g.url; };
        item.onclick = () => { if (pickerDestino && pickerDestino.gif) pickerDestino.gif(g.url); };
        item.appendChild(img);
        grilla.appendChild(item);
    });
    mas.style.display = res.hay_mas ? '' : 'none';
}

// Envía un GIF por el chat.
async function enviarGifChat(url) {
    if (!chatAmigo) return;
    const id = chatAmigo.user_id;
    document.getElementById('picker').style.display = 'none';

    let res;
    try {
        res = await window.pywebview.api.enviar_gif(id, url);
    } catch (e) {
        res = { exito: false, error: String(e) };
    }
    if (!res || !res.exito) {
        document.getElementById('chat-error').textContent = (res && res.error) || 'No se pudo enviar el GIF.';
        return;
    }
    if (chatAmigo && chatAmigo.user_id === id) {
        registrarMensaje(res.mensaje);
        renderizarChat('fondo');
    }
    cargarConversaciones();
}


// ============================================================================
// PUBLICACIONES (públicas: las ve cualquier usuario)
// ============================================================================

let postsFiltro = 'todas';        // 'todas' | 'mias' | 'una' (una sola, al abrirla desde el chat)
let postsUnaId = null;
let postsUnaPendiente = null;     // publicación a mostrar al entrar a la sección
let postsUltimoId = null;         // id de la última cargada (para "Ver más")
let postsToken = 0;
let postsCargando = false;
let postsPublicando = false;
let postAdjunto = null;           // { tipo: 'imagen' | 'gif', vista, url? }
const postsCache = new Map();     // id -> publicación (la usan también las tarjetas del chat)

const ICONOS_POST = {
    like: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M15 5.88 14 10h5.83a2 2 0 0 1 1.92 2.56l-2.33 8A2 2 0 0 1 17.5 22H4a2 2 0 0 1-2-2v-8a2 2 0 0 1 2-2h2.76a2 2 0 0 0 1.79-1.11L12 2a3.13 3.13 0 0 1 3 3.88Z"/><path class="detalle" d="M7 10v12"/></svg>',
    dislike: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M9 18.12 10 14H4.17a2 2 0 0 1-1.92-2.56l2.33-8A2 2 0 0 1 6.5 2H20a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2h-2.76a2 2 0 0 0-1.79 1.11L12 22a3.13 3.13 0 0 1-3-3.88Z"/><path class="detalle" d="M17 14V2"/></svg>',
    comentar: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M7.9 20A9 9 0 1 0 4 16.1L2 22Z"/></svg>',
    compartir: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="m22 2-7 20-4-9-9-4Z"/><path class="detalle" d="M22 2 11 13"/></svg>',
};

// Atajo para crear un elemento con clase y texto (siempre como texto, nunca como HTML).
function nodo(etiqueta, clase, texto) {
    const n = document.createElement(etiqueta);
    if (clase) n.className = clase;
    if (texto !== undefined) n.textContent = texto;
    return n;
}

// Abrevia contadores: 1,2K o 3M.
function abreviarNumero(n) {
    n = Math.max(0, n || 0);
    if (n < 1000) return String(n);
    if (n >= 999500 && n < 1000000) return '1M';
    if (n < 1000000) return (n / 1000).toFixed(n < 10000 ? 1 : 0).replace('.', ',').replace(/,0$/, '') + 'K';
    return (n / 1000000).toFixed(1).replace('.', ',').replace(/,0$/, '') + 'M';
}

// Fecha y hora de una publicación.
function fechaPublicacion(iso) {
    const d = new Date(iso);
    if (isNaN(d.getTime())) return '';
    return d.toLocaleDateString('es-AR', { day: 'numeric', month: 'short', year: 'numeric' }) + ' · ' + horaDe(iso);
}

// Aviso flotante breve.
function avisoPost(texto, esError) {
    document.querySelectorAll('.post-toast').forEach(t => t.remove());
    const t = nodo('div', 'post-toast' + (esError ? ' error' : ''), texto);
    document.body.appendChild(t);
    setTimeout(() => t.remove(), 3500);
}

// Solo muestra imágenes https y GIFs de KLIPY.
function mediaPostPermitida(p) {
    if (!p.media_url) return false;
    if (p.tipo_media === 'gif') return urlGifPermitida(p.media_url);
    return /^https:\/\//i.test(p.media_url);
}

// --- Entrar / salir de la sección ---

// Entra al feed, o a una publicación concreta si viene del chat.
function abrirPublicaciones() {
    if (postsUnaPendiente) {
        postsFiltro = 'una';
        postsUnaId = postsUnaPendiente;
        postsUnaPendiente = null;
    } else if (postsFiltro === 'una') {
        postsFiltro = 'todas';
    }
    const avatar = document.getElementById('post-composer-avatar');
    avatar.src = avatarDe(perfilActual || {});
    avatar.onerror = () => { avatar.style.visibility = 'hidden'; };
    pintarCabeceraPosts();
    cargarPublicaciones(true);
}

// Olvida las publicaciones al cambiar de cuenta.
function reiniciarPublicaciones() {
    postsToken++;
    postsFiltro = 'todas';
    postsUnaId = null;
    postsUnaPendiente = null;
    postsUltimoId = null;
    postsCargando = false;
    postsPublicando = false;
    postAdjunto = null;
    postsCache.clear();
    cerrarPicker();
    document.getElementById('post-lista').innerHTML = '';
    document.getElementById('post-texto').value = '';
    document.getElementById('post-error').textContent = '';
    document.getElementById('post-mas').style.display = 'none';
    document.getElementById('post-publicar').disabled = false;
    document.getElementById('post-publicar').textContent = 'Publicar';
    document.getElementById('social-publicaciones').style.display = 'none';
    document.getElementById('compartir-modal').style.display = 'none';
    pintarAdjuntoPost();
    autoAjustarPost(document.getElementById('post-texto'));
    try { window.pywebview.api.descartar_imagen_publicacion(); } catch (e) { /* aún sin puente */ }
    pintarCabeceraPosts();
}

// Muestra las pestañas, o el botón volver si se ve una sola publicación.
function pintarCabeceraPosts() {
    const unica = postsFiltro === 'una';
    document.getElementById('posts-tabs').style.display = unica ? 'none' : '';
    document.getElementById('posts-volver').style.display = unica ? '' : 'none';
    document.getElementById('post-composer').style.display = unica ? 'none' : '';
    document.querySelectorAll('.posts-tab').forEach(b => b.classList.toggle('active', b.dataset.filtro === postsFiltro));
}

// Cambia entre Todas y Mías.
function cambiarFiltroPosts(filtro) {
    if (filtro === postsFiltro && filtro !== 'todas') return;
    postsFiltro = filtro;
    postsUnaId = null;
    pintarCabeceraPosts();
    cargarPublicaciones(true);
}

// Desde una publicación compartida en el chat
function irAPublicacion(id) {
    postsUnaPendiente = id;
    mostrarVista('social');
    seleccionarSeccionSocial('publicaciones');
}

// --- Cargar el feed ---

// Carga el feed; el token descarta respuestas de otra pestaña o cuenta.
async function cargarPublicaciones(reiniciar) {
    const token = ++postsToken;
    const lista = document.getElementById('post-lista');
    const mas = document.getElementById('post-mas');
    if (reiniciar) {
        postsUltimoId = null;
        lista.innerHTML = '';
        lista.appendChild(mensajeVacio('Cargando…'));
    }
    mas.style.display = 'none';
    postsCargando = true;

    let res;
    try {
        if (postsFiltro === 'una') {
            const r = await window.pywebview.api.obtener_publicacion(postsUnaId);
            res = r && r.exito ? { exito: true, publicaciones: [r.publicacion], hay_mas: false } : r;
        } else {
            const autor = postsFiltro === 'mias' && usuarioActual ? usuarioActual.id : null;
            res = await window.pywebview.api.obtener_publicaciones(reiniciar ? null : postsUltimoId, autor);
        }
    } catch (e) {
        res = { exito: false, error: String(e) };
    }
    if (token !== postsToken) return;   // cambió de pestaña o de cuenta mientras cargaba
    postsCargando = false;

    if (reiniciar) lista.innerHTML = '';
    else lista.querySelectorAll('.empty-state').forEach(n => n.remove());

    if (!res || !res.exito) {
        lista.appendChild(mensajeVacio((res && res.error) || 'No se pudieron cargar las publicaciones.'));
        return;
    }
    res.publicaciones.forEach(p => lista.appendChild(crearTarjetaPost(p)));
    if (res.publicaciones.length) postsUltimoId = res.publicaciones[res.publicaciones.length - 1].id;
    if (!lista.children.length) {
        lista.appendChild(mensajeVacio(postsFiltro === 'mias'
            ? 'Todavía no publicaste nada. ¡Escribí tu primera publicación!'
            : 'Todavía no hay publicaciones. ¡Sé el primero en publicar!'));
    }
    mas.style.display = res.hay_mas ? '' : 'none';
}

// Botón Ver más.
async function cargarMasPublicaciones() {
    if (postsCargando) return;
    const mas = document.getElementById('post-mas');
    mas.disabled = true;
    await cargarPublicaciones(false);
    mas.disabled = false;
}

// --- Redactar ---

// La caja crece con el texto y actualiza el contador.
function autoAjustarPost(caja) {
    caja.style.height = 'auto';
    caja.style.height = Math.min(caja.scrollHeight, 220) + 'px';
    const largo = caja.value.length;
    const c = document.getElementById('post-contador');
    c.textContent = `${largo} / 2000`;
    c.classList.toggle('casi', largo > 1800);
}

// Vista previa de la imagen o GIF adjunto.
function pintarAdjuntoPost() {
    const cont = document.getElementById('post-adjunto');
    if (!postAdjunto) {
        cont.style.display = 'none';
        document.getElementById('post-adjunto-img').removeAttribute('src');
        return;
    }
    document.getElementById('post-adjunto-img').src = postAdjunto.vista;
    cont.style.display = '';
}

// Adjunta una imagen a la publicación.
async function elegirImagenPost() {
    document.getElementById('post-error').textContent = '';
    let res;
    try {
        res = await window.pywebview.api.seleccionar_imagen_publicacion();
    } catch (e) {
        res = { exito: false, error: String(e) };
    }
    if (!res || !res.exito) {
        if (res && res.error && res.error !== 'cancelado') document.getElementById('post-error').textContent = res.error;
        return;
    }
    postAdjunto = { tipo: 'imagen', vista: res.vista };   // una publicación lleva una imagen o un GIF
    pintarAdjuntoPost();
}

// Adjunta un GIF; reemplaza la imagen si había una.
function adjuntarGifPost(url) {
    if (!urlGifPermitida(url)) return;
    window.pywebview.api.descartar_imagen_publicacion();
    postAdjunto = { tipo: 'gif', vista: url, url };
    pintarAdjuntoPost();
    cerrarPicker();
}

// Quita lo adjunto.
function quitarAdjuntoPost() {
    window.pywebview.api.descartar_imagen_publicacion();
    postAdjunto = null;
    pintarAdjuntoPost();
}

// Panel de emojis y GIFs al escribir una publicación.
function alternarPickerPost() {
    const caja = document.getElementById('post-texto');
    abrirPickerEn(document.getElementById('post-picker-slot'), { id: 'post', caja, gif: adjuntarGifPost, stickers: false });
}

// Crea la publicación y la agrega arriba del feed.
async function publicar() {
    if (postsPublicando) return;
    const caja = document.getElementById('post-texto');
    const error = document.getElementById('post-error');
    const btn = document.getElementById('post-publicar');
    const texto = caja.value.trim();
    if (!texto && !postAdjunto) {
        error.textContent = 'Escribí algo o agregá una imagen o un GIF.';
        return;
    }
    postsPublicando = true;
    btn.disabled = true;
    btn.textContent = 'Publicando…';
    error.textContent = '';

    const token = postsToken;
    let res;
    try {
        res = await window.pywebview.api.crear_publicacion(texto, postAdjunto && postAdjunto.tipo === 'gif' ? postAdjunto.url : null);
    } catch (e) {
        res = { exito: false, error: String(e) };
    }
    postsPublicando = false;
    btn.disabled = false;
    btn.textContent = 'Publicar';
    if (token !== postsToken) return;   // se cambió de cuenta mientras publicaba

    if (!res || !res.exito) {
        error.textContent = (res && res.error) || 'No se pudo publicar.';
        return;
    }
    caja.value = '';
    autoAjustarPost(caja);
    postAdjunto = null;
    pintarAdjuntoPost();
    cerrarPicker();

    const lista = document.getElementById('post-lista');
    lista.querySelectorAll('.empty-state').forEach(n => n.remove());
    lista.insertBefore(crearTarjetaPost(res.publicacion), lista.firstChild);
    avisoPost('Publicación creada');
}

// --- Tarjeta de una publicación ---

// Dibuja una publicación: autor, contenido y acciones.
function crearTarjetaPost(p) {
    postsCache.set(p.id, p);
    const tarjeta = nodo('article', 'post');
    tarjeta.dataset.id = p.id;

    // Cabecera: autor y fecha de publicación
    const cab = nodo('div', 'post-cab');
    const avatar = nodo('img', 'post-avatar');
    avatar.src = avatarDe(p);
    avatar.alt = '';
    avatar.onerror = () => { avatar.style.visibility = 'hidden'; };
    const info = nodo('div', 'post-cab-info');
    const autor = nodo('span', 'post-autor', p.username);
    const fecha = nodo('span', 'post-fecha', fechaPublicacion(p.creado_en));
    info.append(autor, fecha);
    const irAlPerfil = () => (p.mia ? abrirPerfil() : irAPerfilAmigo(p.autor_id));
    avatar.onclick = autor.onclick = irAlPerfil;
    cab.append(avatar, info);
    if (p.mia) {
        const borrar = nodo('button', 'post-borrar', '🗑️');
        borrar.title = 'Eliminar publicación';
        borrar.onclick = () => eliminarPost(p, tarjeta);
        cab.appendChild(borrar);
    }
    tarjeta.appendChild(cab);

    // Contenido: texto (con emojis) e imagen o GIF
    if (p.texto) {
        const t = nodo('div', 'post-texto' + (esSoloEmojis(p.texto) ? ' post-emoji' : ''), p.texto);
        tarjeta.appendChild(t);
    }
    if (mediaPostPermitida(p)) {
        const m = nodo('img', 'post-media' + (p.tipo_media === 'gif' ? ' post-gif' : ''));
        m.alt = '';
        m.loading = 'lazy';
        m.src = p.media_url;
        m.onclick = () => abrirVisor(m.src);
        m.onerror = () => { m.classList.add('rota'); m.alt = '⚠️ No se pudo cargar el contenido'; };
        tarjeta.appendChild(m);
    }

    // Acciones: cada una con su contador
    const barra = nodo('div', 'post-acciones');
    const acciones = [
        ['like', 'Me gusta', () => reaccionarPost(p, 'like', tarjeta)],
        ['dislike', 'No me gusta', () => reaccionarPost(p, 'dislike', tarjeta)],
        ['comentar', 'Comentarios', () => alternarComentarios(p, tarjeta)],
        ['compartir', 'Compartir con amigos', () => alternarCompartido(p, tarjeta)],
    ];
    acciones.forEach(([tipo, titulo, accion]) => {
        const b = nodo('button', `post-accion accion-${tipo}`);
        b.dataset.accion = tipo;
        b.title = titulo;
        b.innerHTML = ICONOS_POST[tipo];
        b.appendChild(nodo('span', 'post-cuenta', '0'));
        b.onclick = accion;
        barra.appendChild(b);
    });
    tarjeta.appendChild(barra);
    pintarAcciones(tarjeta, p);
    return tarjeta;
}

// Actualiza contadores y botones activos.
function pintarAcciones(tarjeta, p) {
    const estado = {
        like: [p.mi_like, p.likes],
        dislike: [p.mi_dislike, p.dislikes],
        comentar: [false, p.comentarios],
        compartir: [p.mi_compartido, p.compartidos],
    };
    Object.entries(estado).forEach(([tipo, [activo, cuenta]]) => {
        const b = tarjeta.querySelector(`.post-accion[data-accion="${tipo}"]`);
        if (!b) return;
        b.classList.toggle('activa', !!activo);
        b.setAttribute('aria-pressed', activo ? 'true' : 'false');
        b.querySelector('.post-cuenta').textContent = abreviarNumero(cuenta);
    });
}

// Cuando el servidor responde, se toman sus números (son los reales de toda la gente)
function aplicarPublicacion(p, nueva, tarjeta) {
    ['likes', 'dislikes', 'compartidos', 'comentarios', 'mi_like', 'mi_dislike', 'mi_compartido'].forEach(k => { p[k] = nueva[k]; });
    pintarAcciones(tarjeta, p);
}

// Quita de la pantalla una publicación que ya no existe.
function quitarTarjetaPost(p, tarjeta) {
    postsCache.delete(p.id);
    if (pickerDestino && pickerDestino.id === 'comentario-' + p.id) cerrarPicker();
    tarjeta.remove();
    const lista = document.getElementById('post-lista');
    if (!lista.children.length) lista.appendChild(mensajeVacio('No hay publicaciones para mostrar.'));
}

// Pide confirmación y borra la publicación.
async function eliminarPost(p, tarjeta) {
    if (!confirm('¿Eliminar esta publicación? Se borran también sus comentarios y reacciones.')) return;
    let res;
    try {
        res = await window.pywebview.api.eliminar_publicacion(p.id);
    } catch (e) {
        res = { exito: false, error: String(e) };
    }
    if (res && res.exito) quitarTarjetaPost(p, tarjeta);
    else avisoPost((res && res.error) || 'No se pudo eliminar la publicación.', true);
}

// --- Me gusta / No me gusta: interruptor con contador ---
// Un clic da la reacción (el ícono se rellena y el contador sube); otro clic la quita
// (se vacía y baja). Like y dislike se excluyen, como en YouTube.

// Actualiza al instante y deshace el cambio si el servidor falla.
async function reaccionarPost(p, tipo, tarjeta) {
    if (p._ocupado) return;
    p._ocupado = true;
    const antes = { mi_like: p.mi_like, mi_dislike: p.mi_dislike, likes: p.likes, dislikes: p.dislikes };
    const [miCampo, cuenta] = tipo === 'like' ? ['mi_like', 'likes'] : ['mi_dislike', 'dislikes'];
    const [opCampo, opCuenta] = tipo === 'like' ? ['mi_dislike', 'dislikes'] : ['mi_like', 'likes'];
    if (p[miCampo]) {
        p[miCampo] = false;
        p[cuenta] = Math.max(0, p[cuenta] - 1);
    } else {
        p[miCampo] = true;
        p[cuenta]++;
        if (p[opCampo]) { p[opCampo] = false; p[opCuenta] = Math.max(0, p[opCuenta] - 1); }
    }
    pintarAcciones(tarjeta, p);   // se ve al instante; el servidor confirma enseguida

    let res;
    try {
        res = await window.pywebview.api.alternar_reaccion(p.id, tipo);
    } catch (e) {
        res = { exito: false, error: String(e) };
    }
    if (res && res.exito) {
        aplicarPublicacion(p, res.publicacion, tarjeta);
    } else if (res && res.no_existe) {
        avisoPost(res.error, true);
        quitarTarjetaPost(p, tarjeta);
    } else {
        Object.assign(p, antes);
        pintarAcciones(tarjeta, p);
        avisoPost((res && res.error) || 'No se pudo registrar tu reacción.', true);
    }
    p._ocupado = false;
}

// --- Compartir con amigos ---

let compartirActual = null;   // { p, tarjeta }

// Abre el selector de amigos, o quita tu compartido si ya estaba.
async function alternarCompartido(p, tarjeta) {
    if (!p.mi_compartido) {
        abrirCompartir(p, tarjeta);
        return;
    }
    // Ya lo compartiste: un segundo clic quita tu "compartido" (los mensajes ya enviados quedan en el chat)
    if (p._ocupado) return;
    p._ocupado = true;
    const antes = { mi_compartido: p.mi_compartido, compartidos: p.compartidos };
    p.mi_compartido = false;
    p.compartidos = Math.max(0, p.compartidos - 1);
    pintarAcciones(tarjeta, p);

    let res;
    try {
        res = await window.pywebview.api.quitar_compartido(p.id);
    } catch (e) {
        res = { exito: false, error: String(e) };
    }
    if (res && res.exito) {
        aplicarPublicacion(p, res.publicacion, tarjeta);
    } else {
        Object.assign(p, antes);
        pintarAcciones(tarjeta, p);
        avisoPost((res && res.error) || 'No se pudo quitar el compartido.', true);
    }
    p._ocupado = false;
}

// Muestra tus amigos para elegir con quién compartir.
async function abrirCompartir(p, tarjeta) {
    compartirActual = { p, tarjeta };
    const lista = document.getElementById('compartir-lista');
    document.getElementById('compartir-msg').textContent = '';
    document.getElementById('compartir-enviar').disabled = true;
    lista.innerHTML = '';
    lista.appendChild(mensajeVacio('Cargando tus amigos…'));
    document.getElementById('compartir-modal').style.display = 'flex';

    let res;
    try {
        res = await window.pywebview.api.obtener_social();
    } catch (e) {
        res = { exito: false, error: String(e) };
    }
    if (!compartirActual || compartirActual.p !== p) return;   // se cerró mientras cargaba
    lista.innerHTML = '';
    if (!res || !res.exito) {
        lista.appendChild(mensajeVacio((res && res.error) || 'No se pudieron cargar tus amigos.'));
        return;
    }
    if (!res.amigos.length) {
        lista.appendChild(mensajeVacio('Todavía no tenés amigos agregados. Buscalos en la sección Amigos.'));
        return;
    }
    res.amigos.forEach(a => {
        const fila = nodo('label', 'compartir-fila');
        const img = nodo('img');
        img.src = avatarDe(a);
        img.alt = '';
        img.onerror = () => { img.style.visibility = 'hidden'; };
        const chk = document.createElement('input');
        chk.type = 'checkbox';
        chk.value = a.user_id;
        chk.onchange = () => {
            document.getElementById('compartir-enviar').disabled = !lista.querySelector('input:checked');
        };
        fila.append(img, nodo('span', '', a.username), chk);
        lista.appendChild(fila);
    });
}

// Cierra esa ventana.
function cerrarCompartir() {
    compartirActual = null;
    document.getElementById('compartir-modal').style.display = 'none';
}

// Envía la publicación a los amigos elegidos.
async function confirmarCompartir() {
    if (!compartirActual) return;
    const { p, tarjeta } = compartirActual;
    const ids = [...document.querySelectorAll('#compartir-lista input:checked')].map(i => i.value);
    if (!ids.length) return;
    const btn = document.getElementById('compartir-enviar');
    const msg = document.getElementById('compartir-msg');
    btn.disabled = true;
    msg.textContent = 'Enviando…';

    let res;
    try {
        res = await window.pywebview.api.compartir_publicacion(p.id, ids);
    } catch (e) {
        res = { exito: false, error: String(e) };
    }
    if (!res || !res.exito) {
        msg.textContent = (res && res.error) || 'No se pudo compartir la publicación.';
        btn.disabled = false;
        if (res && res.no_existe) { cerrarCompartir(); quitarTarjetaPost(p, tarjeta); }
        return;
    }
    cerrarCompartir();
    aplicarPublicacion(p, res.publicacion, tarjeta);
    let texto = res.enviados === 1 ? 'Enviada a 1 amigo' : `Enviada a ${res.enviados} amigos`;
    if (res.fallidos) texto += ` (${res.fallidos} no se pudo enviar)`;
    avisoPost(texto);
    cargarConversaciones();   // el chat de esos amigos ya tiene el mensaje
}

// --- Comentarios ---

// Abre o cierra los comentarios de una publicación.
async function alternarComentarios(p, tarjeta) {
    let cont = tarjeta.querySelector('.post-comentarios');
    if (cont) {
        if (pickerDestino && pickerDestino.id === 'comentario-' + p.id) cerrarPicker();
        cont.remove();
        return;
    }
    cont = nodo('div', 'post-comentarios');
    const lista = nodo('div', 'post-comentarios-lista');
    lista.appendChild(mensajeVacio('Cargando comentarios…'));
    const slot = nodo('div');

    const fila = nodo('div', 'post-comentar-fila');
    const input = nodo('input', 'post-comentar-input');
    input.type = 'text';
    input.maxLength = 500;
    input.placeholder = 'Escribí un comentario…';
    input.autocomplete = 'off';
    const btnEmoji = nodo('button', 'chat-icono', '😀');
    btnEmoji.title = 'Emojis';
    btnEmoji.onclick = () => abrirPickerEn(slot, { id: 'comentario-' + p.id, caja: input, gif: null, stickers: false });
    const enviar = nodo('button', 'btn-primary-sm', 'Comentar');
    const mandar = async () => {
        const texto = input.value.trim();
        if (!texto || enviar.disabled) return;
        enviar.disabled = true;
        let res;
        try {
            res = await window.pywebview.api.comentar_publicacion(p.id, texto);
        } catch (e) {
            res = { exito: false, error: String(e) };
        }
        enviar.disabled = false;
        if (res && res.exito) {
            input.value = '';
            lista.querySelectorAll('.empty-state').forEach(n => n.remove());
            lista.appendChild(filaComentario(res.comentario, p, tarjeta, lista));
            aplicarPublicacion(p, res.publicacion, tarjeta);
        } else if (res && res.no_existe) {
            avisoPost(res.error, true);
            quitarTarjetaPost(p, tarjeta);
        } else {
            avisoPost((res && res.error) || 'No se pudo comentar.', true);
        }
        input.focus();
    };
    enviar.onclick = mandar;
    input.onkeydown = ev => { if (ev.key === 'Enter') { ev.preventDefault(); mandar(); } };
    fila.append(input, btnEmoji, enviar);

    cont.append(lista, slot, fila);
    tarjeta.appendChild(cont);
    input.focus();

    let res;
    try {
        res = await window.pywebview.api.obtener_comentarios(p.id);
    } catch (e) {
        res = { exito: false, error: String(e) };
    }
    lista.innerHTML = '';
    if (!res || !res.exito) {
        lista.appendChild(mensajeVacio((res && res.error) || 'No se pudieron cargar los comentarios.'));
        return;
    }
    if (!res.comentarios.length) lista.appendChild(mensajeVacio('Todavía no hay comentarios. ¡Escribí el primero!'));
    res.comentarios.forEach(c => lista.appendChild(filaComentario(c, p, tarjeta, lista)));
}

// Dibuja un comentario, con botón de borrar si corresponde.
function filaComentario(c, p, tarjeta, lista) {
    const fila = nodo('div', 'comentario');
    const img = nodo('img');
    img.src = avatarDe(c);
    img.alt = '';
    img.onerror = () => { img.style.visibility = 'hidden'; };
    const irAlPerfil = () => (c.mio ? abrirPerfil() : irAPerfilAmigo(c.autor_id));
    img.onclick = irAlPerfil;

    const cuerpo = nodo('div', 'comentario-cuerpo');
    const cab = nodo('div', 'comentario-cab');
    const nombre = nodo('strong', '', c.username);
    nombre.onclick = irAlPerfil;
    cab.append(nombre, nodo('small', '', fechaPublicacion(c.creado_en)));
    if (c.mio || p.mia) {   // tus comentarios, y los que te hicieron en tus publicaciones
        const borrar = nodo('button', 'comentario-borrar', '🗑️');
        borrar.title = 'Eliminar comentario';
        borrar.onclick = async () => {
            borrar.disabled = true;
            let res;
            try {
                res = await window.pywebview.api.eliminar_comentario(c.id, p.id);
            } catch (e) {
                res = { exito: false, error: String(e) };
            }
            if (res && res.exito) {
                fila.remove();
                aplicarPublicacion(p, res.publicacion, tarjeta);
                if (!lista.children.length) lista.appendChild(mensajeVacio('Todavía no hay comentarios. ¡Escribí el primero!'));
            } else {
                borrar.disabled = false;
                avisoPost((res && res.error) || 'No se pudo eliminar el comentario.', true);
            }
        };
        cab.appendChild(borrar);
    }
    const texto = nodo('div', 'comentario-texto', c.texto);
    cuerpo.append(cab, texto);
    fila.append(img, cuerpo);
    return fila;
}

// --- Publicación compartida dentro del chat ---

// Tarjeta de una publicación compartida dentro del chat.
function crearTarjetaCompartida(contenido) {
    const id = parseInt(contenido, 10);
    const caja = nodo('div', 'chat-post');
    caja.appendChild(nodo('div', 'chat-post-titulo', '📰 PUBLICACIÓN'));
    const cuerpo = nodo('div', 'chat-post-cuerpo', 'Cargando…');
    caja.appendChild(cuerpo);
    if (!id) {
        cuerpo.textContent = 'Publicación no válida.';
        return caja;
    }

    const pintar = p => {
        cuerpo.innerHTML = '';
        if (!p) {
            cuerpo.textContent = 'Esta publicación ya no está disponible.';
            return;
        }
        caja.onclick = () => irAPublicacion(id);
        cuerpo.appendChild(nodo('div', 'chat-post-autor', p.username));
        if (p.texto) cuerpo.appendChild(nodo('div', 'chat-post-texto', p.texto.length > 140 ? p.texto.slice(0, 140) + '…' : p.texto));
        if (p.media_url) cuerpo.appendChild(nodo('div', 'chat-post-media', p.tipo_media === 'gif' ? '🎞️ GIF' : '🖼️ Imagen'));
    };

    if (postsCache.has(id)) {
        pintar(postsCache.get(id));
    } else {
        window.pywebview.api.obtener_publicacion(id).then(res => {
            if (res && res.exito) {
                postsCache.set(id, res.publicacion);
                pintar(res.publicacion);
            } else if (res && res.no_existe) {
                postsCache.set(id, null);
                pintar(null);
            } else {
                cuerpo.textContent = 'No se pudo cargar la publicación.';
            }
        }).catch(() => { cuerpo.textContent = 'No se pudo cargar la publicación.'; });
    }
    return caja;
}

// ============================================================================
// AMIGOS: botones de acción por amigo y menú desplegable (▾)
//   💬 Mensaje · 📞 Llamada de voz · ▾ (Quitar, Bloquear, Denunciar)
// ============================================================================

// Botón redondo de amigo; se desactiva mientras se procesa.
function botonIcono(icono, titulo, accion) {
    const b = document.createElement('button');
    b.className = 'amigo-icono';
    b.textContent = icono;
    b.title = titulo;
    b.setAttribute('aria-label', titulo);
    b.onclick = async ev => {
        ev.stopPropagation();
        b.disabled = true;   // evita dobles clics mientras se procesa
        try { await accion(); } finally { b.disabled = false; }
    };
    return b;
}

let amigoMenuAbierto = null;   // { menu, boton }

// Cierra el menú ▾ abierto.
function cerrarMenuAmigo() {
    if (!amigoMenuAbierto) return;
    amigoMenuAbierto.menu.remove();
    amigoMenuAbierto.boton.classList.remove('abierto');
    amigoMenuAbierto = null;
}

// Opción del menú ▾.
function itemMenuAmigo(texto, clase, accion) {
    const it = document.createElement('button');
    it.className = 'amigo-menu-item' + (clase ? ' ' + clase : '');
    it.textContent = texto;
    it.onclick = ev => {
        ev.stopPropagation();
        cerrarMenuAmigo();
        accion();
    };
    return it;
}

// Flechita ▾ que despliega las opciones del amigo
function menuAmigo(u) {
    const flecha = document.createElement('button');
    flecha.className = 'amigo-icono amigo-flecha';
    flecha.textContent = '▾';
    flecha.title = 'Más opciones';
    flecha.setAttribute('aria-label', 'Más opciones');
    flecha.onclick = ev => {
        ev.stopPropagation();
        if (amigoMenuAbierto && amigoMenuAbierto.boton === flecha) { cerrarMenuAmigo(); return; }
        cerrarMenuAmigo();

        const menu = document.createElement('div');
        menu.className = 'amigo-menu';
        menu.append(
            itemMenuAmigo('Quitar de amigos', '', () => quitarAmistad(u.friendship_id, u.username)),
            itemMenuAmigo('Bloquear', '', () => bloquearUsuario(u.user_id, u.username)),
            itemMenuAmigo('Denunciar', 'peligro', () => abrirDenuncia(u.user_id, u.username)),
        );
        document.body.appendChild(menu);

        // Posición fija junto a la flecha (así no lo recorta ningún contenedor con scroll)
        const r = flecha.getBoundingClientRect();
        const ancho = menu.offsetWidth, alto = menu.offsetHeight;
        const izquierda = Math.max(8, Math.min(r.right - ancho, window.innerWidth - ancho - 8));
        const abajo = r.bottom + 6 + alto <= window.innerHeight;
        menu.style.left = izquierda + 'px';
        menu.style.top = (abajo ? r.bottom + 6 : r.top - 6 - alto) + 'px';

        flecha.classList.add('abierto');
        amigoMenuAbierto = { menu, boton: flecha };
    };
    return flecha;
}

// Cualquier clic fuera, Escape o desplazarse cierra el menú
document.addEventListener('click', cerrarMenuAmigo);
document.addEventListener('keydown', ev => { if (ev.key === 'Escape') cerrarMenuAmigo(); });
window.addEventListener('blur', cerrarMenuAmigo);
document.addEventListener('scroll', cerrarMenuAmigo, true);
