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
        const res = await window.pywebview.api.iniciar_sesion(email, pass);
        if (res && res.exito) {
            usuarioActual = res.usuario;
            await cargarPantallaPrincipal();
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
    document.getElementById('auth-screen').style.display = 'none';
    document.getElementById('app-screen').style.display = 'flex';

    await cargarPerfilUsuario();
    await cargarConsolas();
    await filtrarCatalogo();
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

        card.onclick = () => lanzarJuego(juego.id);
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
    const label = document.getElementById('scan-status');
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
