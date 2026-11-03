// ============================================================================
// AMIGOS: botones de acción por amigo y menú desplegable (▾)
//   💬 Mensaje · 📞 Llamada de voz · ▾ (Quitar, Bloquear, Denunciar)
// Bloquear y Denunciar todavía no tienen función: muestran un aviso.
// ============================================================================

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

function cerrarMenuAmigo() {
    if (!amigoMenuAbierto) return;
    amigoMenuAbierto.menu.remove();
    amigoMenuAbierto.boton.classList.remove('abierto');
    amigoMenuAbierto = null;
}

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
            itemMenuAmigo('Bloquear', '', () => llAviso('Bloquear usuarios estará disponible pronto.')),
            itemMenuAmigo('Denunciar', 'peligro', () => llAviso('Las denuncias estarán disponibles pronto.')),
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
