let usuarioActual = null;
let perfilActual = null;
let consolaSeleccionada = 'todas';

function toggleAuth(isRegister) {
    document.getElementById('login-form').style.display = isRegister ? 'none' : 'block';
    document.getElementById('register-form').style.display = isRegister ? 'block' : 'none';
    document.getElementById('auth-error').innerText = '';
}

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

async function cargarPantallaPrincipal() {
    reiniciarEstadoUI();   // arranca siempre limpio: nada de la cuenta anterior
    document.getElementById('auth-screen').style.display = 'none';
    document.getElementById('app-screen').style.display = 'flex';

    await cargarPerfilUsuario();
    await cargarConsolas();
    await filtrarCatalogo();
    iniciarInsignias();
}

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

function abrirPerfil() {
    document.getElementById('profile-modal').style.display = 'flex';
}

function cerrarPerfil() {
    document.getElementById('profile-modal').style.display = 'none';
}

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

function seleccionarConsola(id, elemento) {
    consolaSeleccionada = id;
    volverABiblioteca();
    
    const items = document.querySelectorAll('#console-list li');
    items.forEach(item => item.classList.remove('active'));
    if (elemento) elemento.classList.add('active');

    filtrarCatalogo();
}

async function filtrarCatalogo() {
    try {
        const textoBusqueda = document.getElementById('search-input').value;
        const juegos = await window.pywebview.api.obtener_juegos_filtrados(textoBusqueda, consolaSeleccionada);
        renderizarJuegos(juegos);
    } catch (e) {
        console.error("Error al filtrar catálogo:", e);
    }
}

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
                    await window.pywebview.api.lanzar_juego(res.opciones[indice].id);
                }
            }
        } else {
            alert("No se pudo iniciar el juego: " + (res ? res.error : "Error desconocido"));
        }
    } catch (e) {
        console.error("Error al lanzar juego:", e);
    }
}

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

function abrirModalCodigo(email) {
    document.getElementById('code-email').textContent = email;
    document.getElementById('code-input').value = '';
    document.getElementById('code-msg').textContent = '';
    document.getElementById('code-modal').style.display = 'flex';
    document.getElementById('code-input').focus();
}

function omitirCodigo() {
    document.getElementById('code-modal').style.display = 'none';
}

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

async function reenviarCodigo() {
    const msg = document.getElementById('code-msg');
    try {
        const res = await window.pywebview.api.reenviar_codigo_recordar();
        msg.textContent = res && res.exito ? 'Te enviamos un código nuevo.' : (res ? res.error : 'No se pudo reenviar.');
    } catch (e) {
        msg.textContent = 'Error: ' + e;
    }
}

async function cerrarSesion() {
    if (!confirm('¿Cerrar sesión? Dejará de recordarse tu cuenta en este equipo.')) return;
    try { await window.pywebview.api.cerrar_sesion(); } catch (e) { /* se sigue igual */ }

    usuarioActual = null;
    perfilActual = null;
    consolaSeleccionada = 'todas';
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

function abrirEnlace(url) {
    window.pywebview.api.abrir_enlace(url);
}

// ============================================================================
// CONFIGURACIÓN (estilo "Parámetros" de Steam)
// ============================================================================

function abrirConfiguracion(seccion) {
    document.getElementById('settings-modal').style.display = 'flex';
    seleccionarSeccionConfig(seccion || 'paths');
}

function cerrarConfiguracion() {
    document.getElementById('settings-modal').style.display = 'none';
}

function seleccionarSeccionConfig(nombre) {
    document.querySelectorAll('.settings-section').forEach(s => s.style.display = 'none');
    document.getElementById('settings-' + nombre).style.display = 'block';
    document.querySelectorAll('.settings-nav li').forEach(li => {
        li.classList.toggle('active', li.dataset.section === nombre);
    });

    if (nombre === 'paths') cargarRutasConfig();
    else if (nombre === 'ra') cargarEstadoRA();
    else if (nombre === 'privacy') cargarPrivacidad();
    else if (nombre === 'info') cargarInfoLauncher();
}

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

async function borrarCredencialesRA() {
    await window.pywebview.api.borrar_credenciales_ra();
    await cargarEstadoRA();
}

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

function alBuscar() {
    volverABiblioteca();
    filtrarCatalogo();
}

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

function volverABiblioteca() {
    const detalle = document.getElementById('game-detail');
    if (detalle.style.display === 'none') return;
    detalle.style.display = 'none';
    const biblioteca = document.querySelector('.game-grid-container');
    biblioteca.style.display = '';
    biblioteca.scrollTop = scrollBiblioteca;
    juegoDetalleActual = null;
}

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
    document.getElementById('opinion-text').value = (j.opinion && j.opinion.texto) || '';
    document.getElementById('opinion-msg').textContent = '';
    pintarEstrellas();
}

function jugarDesdeDetalle() {
    if (juegoDetalleActual) lanzarJuego(juegoDetalleActual.id);
}

function elegirPuntuacion(valor) {
    opinionPuntuacion = (opinionPuntuacion === valor) ? 0 : valor;
    pintarEstrellas();
}

function pintarEstrellas() {
    document.querySelectorAll('#opinion-stars span').forEach(s => {
        s.classList.toggle('on', Number(s.dataset.v) <= opinionPuntuacion);
    });
}

async function guardarOpinion() {
    if (!juegoDetalleActual) return;
    const msg = document.getElementById('opinion-msg');
    try {
        const res = await window.pywebview.api.guardar_opinion(
            juegoDetalleActual.id,
            opinionPuntuacion,
            document.getElementById('opinion-text').value
        );
        msg.textContent = res && res.exito ? '✔ Opinión guardada' : (res ? res.error : 'Error al guardar.');
    } catch (e) {
        msg.textContent = 'Error: ' + e;
    }
}

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
        'Aquí verás qué amigos lo tienen en su lista de deseados. Función en desarrollo.');
}

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
        sub.textContent = a.veces ? `${a.veces} ${a.veces === 1 ? 'vez' : 'veces'} · ${formatearFecha(a.ultima_vez)}` : '';
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

function mostrarVista(nombre) {
    vistaActual = nombre;
    document.querySelectorAll('.view').forEach(v => {
        v.style.display = (v.id === 'view-' + nombre) ? '' : 'none';
    });
    document.querySelectorAll('.nav-btn').forEach(b => {
        b.classList.toggle('active', b.dataset.view === nombre);
    });

    if (nombre === 'social') abrirSocial();
    else detenerSocial();
}

// ============================================================================
// SOCIAL
// ============================================================================

const SECCIONES_PRONTO = {
    chat:           { icono: '💬', titulo: 'Chat',          texto: 'Mensajes directos con tus amigos.' },
    publicaciones:  { icono: '📰', titulo: 'Publicaciones', texto: 'Mirá lo que publican tus amigos y compartí tus propias capturas y opiniones.' },
    foros:          { icono: '🗨️', titulo: 'Foros',         texto: 'Foros por juego y por consola para preguntar, recomendar y debatir.' },
    llamadas:       { icono: '📞', titulo: 'Llamadas',      texto: 'Llamadas de voz con tus amigos.' },
};

let socialSeccion = 'amigos';
let socialTimer = null;
let busquedaTimer = null;

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

function detenerSocial() {
    if (socialTimer) clearInterval(socialTimer);
    socialTimer = null;
}

function seleccionarSeccionSocial(nombre) {
    socialSeccion = nombre;
    perfilAjenoId = null;
    document.getElementById('social-perfil').style.display = 'none';
    document.querySelectorAll('.social-nav li').forEach(li => {
        li.classList.toggle('active', li.dataset.social === nombre);
    });

    const esAmigos = nombre === 'amigos';
    document.getElementById('social-amigos').style.display = esAmigos ? 'block' : 'none';
    document.getElementById('social-pronto').style.display = esAmigos ? 'none' : 'block';

    if (esAmigos) {
        cargarSocial();
    } else {
        const info = SECCIONES_PRONTO[nombre];
        document.getElementById('pronto-icono').textContent = info.icono;
        document.getElementById('pronto-titulo').textContent = info.titulo;
        document.getElementById('pronto-texto').textContent = info.texto;
    }
}

function avatarDe(u) {
    return (u.avatar_url && u.avatar_url.trim() !== '')
        ? u.avatar_url
        : `https://ui-avatars.com/api/?name=${encodeURIComponent(u.username || '?')}&background=45A29E&color=fff`;
}

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

function mensajeVacio(texto) {
    const p = document.createElement('p');
    p.className = 'empty-state';
    p.textContent = texto;
    return p;
}

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
        const jugando = u.jugando ? `🎮 Jugando a ${u.jugando.titulo}` + (u.jugando.consola ? ` · ${u.jugando.consola}` : '') : '';
        cont.appendChild(filaUsuario(u, jugando, !!u.jugando, [
            boton('Quitar', 'btn-secondary-sm', () => quitarAmistad(u.friendship_id, u.username)),
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

function buscarUsuariosConRetraso() {
    clearTimeout(busquedaTimer);
    busquedaTimer = setTimeout(buscarUsuarios, 350);
}

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

async function refrescarSocialYBusqueda() {
    await cargarSocial();
    await buscarUsuarios();
    if (perfilAjenoId) await cargarPerfilAjeno();
}

async function agregarAmigo(userId) {
    const res = await window.pywebview.api.enviar_solicitud_amistad(userId);
    if (!res || !res.exito) alert(res ? res.error : 'No se pudo enviar la solicitud.');
    await refrescarSocialYBusqueda();
}

async function responderSolicitud(friendshipId, aceptar) {
    const res = await window.pywebview.api.responder_solicitud_amistad(friendshipId, aceptar);
    if (!res || !res.exito) alert(res ? res.error : 'No se pudo responder la solicitud.');
    await refrescarSocialYBusqueda();
}

async function quitarAmistad(friendshipId, nombre) {
    if (nombre && !confirm(`¿Quitar a ${nombre} de tus amigos?`)) return;
    const res = await window.pywebview.api.eliminar_amistad(friendshipId);
    if (!res || !res.exito) alert(res ? res.error : 'No se pudo completar la acción.');
    await refrescarSocialYBusqueda();
}

// ============================================================================
// PRIVACIDAD
// ============================================================================

async function cargarPrivacidad() {
    try {
        const p = await window.pywebview.api.obtener_privacidad();
        document.getElementById('privacy-share').checked = !!p.actividad;
        document.getElementById('privacy-history').checked = !!p.historial;
    } catch (e) {
        console.error(e);
    }
}

async function guardarCompartirActividad() {
    const activo = document.getElementById('privacy-share').checked;
    await window.pywebview.api.guardar_compartir_actividad(activo);
}

// ============================================================================
// PERFIL DE OTRO USUARIO
// ============================================================================

let perfilAjenoId = null;

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
    document.getElementById('pa-avatar').removeAttribute('src');
    await cargarPerfilAjeno();
}

function cerrarPerfilAjeno() {
    perfilAjenoId = null;
    document.getElementById('social-perfil').style.display = 'none';
    document.getElementById('social-amigos').style.display = 'block';
    cargarSocial();
}

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
    if (res.jugando) {
        estado.textContent = `🎮 Jugando a ${res.jugando.titulo}` + (res.jugando.consola ? ` · ${res.jugando.consola}` : '');
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
        acciones.appendChild(boton('Quitar de amigos', 'btn-secondary-sm', () => quitarAmistad(res.friendship_id, p.username)));
    }
}

// ============================================================================
// INSIGNIAS (solicitudes de amistad pendientes)
// ============================================================================

let insigniaTimer = null;

function pintarInsignias(n) {
    ['nav-social-badge', 'social-amigos-badge'].forEach(id => {
        const el = document.getElementById(id);
        if (!el) return;
        el.textContent = n;
        el.style.display = n > 0 ? '' : 'none';
    });
}

async function actualizarInsignias() {
    try {
        const r = await window.pywebview.api.obtener_resumen_social();
        if (r && r.exito) pintarInsignias(r.solicitudes);
    } catch (e) { /* sin conexión: se deja como estaba */ }
}

function iniciarInsignias() {
    detenerInsignias();
    actualizarInsignias();
    insigniaTimer = setInterval(actualizarInsignias, 60000);
}

function detenerInsignias() {
    if (insigniaTimer) clearInterval(insigniaTimer);
    insigniaTimer = null;
    pintarInsignias(0);
}

// ============================================================================
// CAMBIO DE CUENTA: estado limpio
// ============================================================================

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
    pintarInsignias(0);

    // Campos de texto
    ['login-email', 'login-pass', 'reg-username', 'reg-email', 'reg-pass', 'search-input', 'friend-search',
     'opinion-text', 'profile-bio', 'ra-user', 'ra-key', 'code-input'].forEach(id => {
        const el = document.getElementById(id);
        if (el) el.value = '';
    });
    ['login-remember', 'privacy-share', 'privacy-history'].forEach(id => {
        const el = document.getElementById(id);
        if (el) el.checked = false;
    });

    // Textos y listas que dependen de la cuenta
    ['friend-search-results', 'friend-lists', 'game-grid', 'friends-played', 'friends-wishlist',
     'achievements-content', 'paths-content', 'pa-acciones', 'pa-juegos', 'pa-comun'].forEach(id => {
        const el = document.getElementById(id);
        if (el) el.innerHTML = '';
    });
    ['header-username', 'profile-username', 'opinion-msg', 'ra-status', 'pa-nombre', 'pa-estado', 'pa-bio',
     'code-msg', 'scan-status', 'scan-status-config', 'auth-error', 'detail-title', 'detail-console'].forEach(id => {
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
    document.getElementById('game-detail').style.display = 'none';
    document.querySelector('.game-grid-container').style.display = '';
    document.getElementById('social-perfil').style.display = 'none';
    document.getElementById('social-pronto').style.display = 'none';
    document.getElementById('social-amigos').style.display = 'block';
    document.querySelectorAll('.social-nav li').forEach(li => li.classList.toggle('active', li.dataset.social === 'amigos'));
    document.querySelectorAll('.settings-section').forEach(s => s.style.display = (s.id === 'settings-paths') ? 'block' : 'none');
    document.querySelectorAll('.settings-nav li').forEach(li => li.classList.toggle('active', li.dataset.section === 'paths'));
    mostrarVista('biblioteca');
}

// ============================================================================
// HISTORIAL DE JUEGOS
// ============================================================================

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

function filaJuego(titulo, subtitulo) {
    const fila = document.createElement('div');
    fila.className = 'game-row';
    const t = document.createElement('strong');
    t.textContent = titulo;
    const s = document.createElement('small');
    s.textContent = subtitulo;
    fila.append(t, s);
    return fila;
}

function pintarJuegosPerfil(res) {
    const jugados = document.getElementById('pa-juegos');
    const comun = document.getElementById('pa-comun');
    jugados.innerHTML = '';
    comun.innerHTML = '';

    if (res.relacion !== 'amigos') {
        jugados.appendChild(mensajeVacio('Solo los amigos pueden ver los juegos que jugó.'));
        comun.appendChild(mensajeVacio('Agregalo a tus amigos para ver qué juegos tienen en común.'));
        return;
    }

    const recientes = res.recientes || [];
    if (recientes.length === 0) {
        jugados.appendChild(mensajeVacio('Todavía no hay juegos registrados (o no comparte su historial).'));
    }
    recientes.forEach(j => {
        const veces = `${j.veces} ${j.veces === 1 ? 'vez' : 'veces'}`;
        jugados.appendChild(filaJuego(j.titulo, [j.consola, veces, formatearFecha(j.ultima_vez)].filter(Boolean).join(' · ')));
    });

    const enComun = res.en_comun || [];
    if (enComun.length === 0) {
        comun.appendChild(mensajeVacio('Todavía no tienen juegos en común.'));
    } else {
        const resumen = document.createElement('p');
        resumen.className = 'settings-help';
        resumen.textContent = `${enComun.length} ${enComun.length === 1 ? 'juego' : 'juegos'} en común`;
        comun.appendChild(resumen);
        enComun.forEach(j => comun.appendChild(filaJuego(j.titulo, j.consola)));
    }
}

function irAPerfilAmigo(userId) {
    mostrarVista('social');
    seleccionarSeccionSocial('amigos');
    abrirPerfilAjeno(userId);
}

async function guardarCompartirHistorial() {
    const casilla = document.getElementById('privacy-history');
    if (!casilla.checked && !confirm('Se borrará de la nube el historial de juegos que ya publicaste. ¿Continuar?')) {
        casilla.checked = true;
        return;
    }
    await window.pywebview.api.guardar_compartir_historial(casilla.checked);
}
