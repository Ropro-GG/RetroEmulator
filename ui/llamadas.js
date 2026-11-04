// ============================================================================
// LLAMADAS: voz, video y compartir pantalla, 1 a 1 o en grupo (hasta 6 personas, cada una conectada con todas)
//
//  - Python (gui_app.py) crea/responde/cierra la llamada en Supabase.
//  - Este archivo escucha Realtime (timbre) y arma la conexión WebRTC entre equipos.
//  - Las señales de conexión viajan por un canal "broadcast" privado por llamada. Las que definen
//    la conexión van además selladas en Python, para que ni el servidor pueda alterarlas
//    (llamada:<id>) y no se guardan en ninguna tabla.
// Requiere: supabase-js (CDN, en index.html) y los métodos de gui_app.py.
// ============================================================================

const LL_ICE = { iceServers: [{ urls: 'stun:stun.l.google.com:19302' }] };  // solo STUN: gratis, pero algunas redes no pueden conectarse
const LL_MAX_PERSONAS = 6;       // en una llamada grupal cada uno se conecta con todos: más de 6 se vuelve pesado
const LL_VIDEO = { width: { ideal: 1280 }, height: { ideal: 720 }, frameRate: { ideal: 30 } };
const LL_TIMBRE_MS = 45000;      // cuánto suena antes de darla por no atendida
const LL_VIGENCIA_MS = 60000;    // invitaciones más viejas que esto se ignoran (mismo valor en invitar_a_llamada)
const LL_CONEXION_MS = 30000;    // cuánto se espera a que conecte después de atender

let llSb = null;                 // cliente Realtime de Supabase
let llYo = null;                 // mi id de usuario
let llCanalGlobal = null;        // escucha invitaciones y cambios de estado
let llTimerToken = null;
let llActual = null;             // llamada en la que estoy
let llEntrante = null;           // invitación que está sonando
let llTimbreTimer = null;
let llTimbreCtx = null;
let llDuracionTimer = null;
let llIniciando = false;         // evita dos llamadas por un doble clic mientras se pide el micrófono

// ---------------------------------------------------------------------------
// Arranque y cierre (se llaman desde app.js al entrar / salir de la cuenta)
// ---------------------------------------------------------------------------

// Al entrar a la cuenta: limpia llamadas colgadas y empieza a escuchar el timbre.
async function llamadasIniciar() {
    await llamadasDetener();
    llCrearUI();
    if (!window.supabase || !window.supabase.createClient) {
        console.warn('[LLAMADAS] supabase-js no cargó (¿sin internet?). Las llamadas quedan desactivadas.');
        return;
    }
    let cfg;
    try { cfg = await window.pywebview.api.obtener_config_llamadas(); } catch (e) { cfg = null; }
    if (!cfg || !cfg.exito) {
        console.warn('[LLAMADAS] No se pudo preparar:', cfg && cfg.error);
        return;
    }
    llYo = cfg.user_id;
    try { await window.pywebview.api.limpiar_llamadas_colgadas(); } catch (e) { /* no impide llamar */ }
    llSb = window.supabase.createClient(cfg.url, cfg.anon_key, {
        auth: { persistSession: false, autoRefreshToken: false, detectSessionInUrl: false },
    });
    llSb.realtime.setAuth(cfg.token);

    llCanalGlobal = llSb.channel('llamadas-usuario-' + llYo)
        .on('postgres_changes',
            { event: 'INSERT', schema: 'public', table: 'llamada_participantes', filter: `usuario_id=eq.${llYo}` },
            p => llAlInvitacion(p.new))
        .on('postgres_changes', { event: 'UPDATE', schema: 'public', table: 'llamadas' },
            p => llAlCambioLlamada(p.new))
        .on('postgres_changes', { event: 'UPDATE', schema: 'public', table: 'llamada_participantes' },
            p => llAlCambioParticipante(p.new))
        .subscribe(estado => {
            if (estado === 'CHANNEL_ERROR' || estado === 'TIMED_OUT') {
                console.warn('[LLAMADAS] Realtime no conectó:', estado);
            }
        });

    // El token de sesión vence: se renueva antes para que Realtime siga funcionando
    llTimerToken = setInterval(llRenovarToken, 40 * 60 * 1000);
}

// Al salir de la cuenta: cuelga y deja de escuchar.
async function llamadasDetener() {
    if (llTimerToken) clearInterval(llTimerToken);
    llTimerToken = null;
    if (llEntrante) { llDetenerTimbre(); llOcultar('llamada-timbre'); llEntrante = null; }
    if (llActual) await llColgar(null);
    if (llSb && llCanalGlobal) { try { llSb.removeChannel(llCanalGlobal); } catch (e) { /* nada */ } }
    llCanalGlobal = null;
    llSb = null;
    llYo = null;
}

// Entrega a Realtime un token vigente para que no se desconecte.
async function llRenovarToken() {
    try {
        const cfg = await window.pywebview.api.obtener_config_llamadas();
        if (cfg && cfg.exito && llSb) llSb.realtime.setAuth(cfg.token);
    } catch (e) { /* se reintenta en el próximo ciclo */ }
}

// ---------------------------------------------------------------------------
// Interfaz (se crea por código para no tocar mucho index.html)
// ---------------------------------------------------------------------------

// Crea una sola vez el timbre, la barra de llamada y las ventanas de video.
function llCrearUI() {
    if (document.getElementById('llamada-timbre')) return;
    const cont = document.createElement('div');
    cont.innerHTML = `
        <div id="llamada-timbre" class="llamada-panel" style="display:none;">
            <img id="llamada-timbre-avatar" alt="">
            <div class="llamada-texto"><strong id="llamada-timbre-nombre"></strong><small id="llamada-timbre-sub">te está llamando…</small></div>
            <button class="llamada-btn llamada-aceptar" title="Aceptar solo con audio" onclick="llAceptar(false)">📞</button>
            <button id="llamada-aceptar-video" class="llamada-btn llamada-aceptar" title="Aceptar con video" onclick="llAceptar(true)" style="display:none;">🎥</button>
            <button class="llamada-btn llamada-colgar" title="Rechazar" onclick="llRechazar()">✖</button>
        </div>
        <div id="llamada-videos" style="display:none;">
            <button id="llamada-grande" class="llamada-grande-btn" title="Agrandar / achicar" onclick="llAlternarGrande()">⛶</button>
            <div id="llamada-videos-grid"></div>
            <video id="llamada-local" autoplay muted playsinline style="display:none;"></video>
        </div>
        <div id="llamada-barra" class="llamada-panel" style="display:none;">
            <div class="llamada-texto"><strong id="llamada-barra-nombre"></strong><small id="llamada-barra-estado"></small></div>
            <button id="llamada-mute" class="llamada-btn" title="Silenciar micrófono" onclick="llAlternarMute()">🎤</button>
            <button id="llamada-camara" class="llamada-btn" title="Activar cámara" onclick="llAlternarCamara()">📷</button>
            <button id="llamada-pantalla" class="llamada-btn" title="Compartir pantalla" onclick="llAlternarPantalla()">🖥️</button>
            <button class="llamada-btn" title="Elegir micrófono y altavoz" onclick="abrirConfiguracion('audio')">🎧</button>
            <button class="llamada-btn" title="Agregar a alguien a la llamada" onclick="llAbrirInvitar()">➕</button>
            <button class="llamada-btn llamada-colgar" title="Colgar" onclick="llColgarManual()">📵</button>
        </div>
        <div id="llamada-invitar" class="llamada-invitar" style="display:none;">
            <strong>Agregar a la llamada</strong>
            <div id="llamada-invitar-lista"></div>
            <div class="llamada-invitar-botones">
                <button class="btn-secondary-sm" onclick="llCerrarInvitar()">Cancelar</button>
                <button class="btn-primary-sm" onclick="llEnviarInvitaciones()">Invitar</button>
            </div>
        </div>
        <div id="llamada-aviso" class="llamada-aviso" style="display:none;"></div>
        <div id="llamada-audios" style="display:none;"></div>`;
    while (cont.firstChild) document.body.appendChild(cont.firstChild);
    if (!navigator.mediaDevices || !navigator.mediaDevices.getDisplayMedia) llOcultar('llamada-pantalla');
}

// Muestra un elemento.
function llMostrar(id) { const e = document.getElementById(id); if (e) e.style.display = 'flex'; }
// Oculta un elemento.
function llOcultar(id) { const e = document.getElementById(id); if (e) e.style.display = 'none'; }

let llAvisoTimer = null;
// Aviso flotante que desaparece a los 4 s.
function llAviso(texto, duracion = 4000) {
    const e = document.getElementById('llamada-aviso');
    if (!e) return;
    e.textContent = texto;
    e.style.display = 'block';
    clearTimeout(llAvisoTimer);
    llAvisoTimer = setTimeout(() => { e.style.display = 'none'; }, duracion);
}

// Actualiza el nombre y el estado en la barra de llamada.
function llEstadoBarra(nombre, estado) {
    document.getElementById('llamada-barra-nombre').textContent = nombre || '';
    document.getElementById('llamada-barra-estado').textContent = estado || '';
    llMostrar('llamada-barra');
}

// Tono de timbre generado por código (no hace falta ningún archivo de sonido)
function llTimbre(activo) {
    llDetenerTimbre();
    if (!activo) return;
    try {
        llTimbreCtx = llTimbreCtx || new AudioContext();
        if (llTimbreCtx.state === 'suspended') llTimbreCtx.resume();
        const pitido = () => {
            const o = llTimbreCtx.createOscillator(), g = llTimbreCtx.createGain();
            o.frequency.value = 880; g.gain.value = 0.08;
            o.connect(g); g.connect(llTimbreCtx.destination);
            o.start(); o.stop(llTimbreCtx.currentTime + 0.25);
        };
        pitido();
        llTimbreTimer = setInterval(pitido, 1500);
    } catch (e) { /* sin sonido, pero el aviso visual sigue */ }
}
// Detiene el timbre.
function llDetenerTimbre() { if (llTimbreTimer) clearInterval(llTimbreTimer); llTimbreTimer = null; }

// ---------------------------------------------------------------------------
// Llamar (botones del chat y de la lista de amigos)
// ---------------------------------------------------------------------------

// Botones de llamada dentro del chat.
async function llamarAmigoChat(conVideo = false) {
    if (!chatAmigo) return;
    await llIniciarLlamada([chatAmigo.user_id], conVideo, chatAmigo.username);
}

// Llamada directa desde la lista de amigos (sin abrir el chat)
async function llamarAmigo(userId, nombre, conVideo = false) {
    await llIniciarLlamada([userId], conVideo, nombre);
}

// Micrófono y altavoz elegidos. Se guardan por nombre: Chromium cambia los ids de dispositivo
// según el origen y esta ventana usa un puerto distinto en cada arranque.
async function llListarDispositivos() {
    let lista = await navigator.mediaDevices.enumerateDevices();
    if (lista.some(d => d.kind === 'audioinput' && !d.label)) {   // sin permiso vigente los nombres vienen vacíos
        const s = await navigator.mediaDevices.getUserMedia({ audio: true });
        s.getTracks().forEach(t => t.stop());
        lista = await navigator.mediaDevices.enumerateDevices();
    }
    return lista;
}

// Busca por nombre el dispositivo elegido; null usa el predeterminado.
async function llIdElegido(campo, tipo) {
    try {
        const nombre = (await window.pywebview.api.obtener_audio_llamadas())[campo];
        if (!nombre) return null;
        const d = (await llListarDispositivos()).find(x => x.kind === tipo && x.label === nombre);
        return d ? d.deviceId : null;     // desconectado: se usa el predeterminado
    } catch (e) {
        return null;
    }
}

// Opciones de micrófono. "ideal" permite seguir si ese micrófono no está.
async function llAudioConstraints() {
    const audio = { echoCancellation: true, noiseSuppression: true, autoGainControl: true };
    const id = await llIdElegido('mic', 'audioinput');
    if (id) audio.deviceId = { ideal: id };
    return audio;
}

// Envía el audio de un participante al altavoz elegido.
async function llAplicarAltavoz(elemento) {
    if (!elemento.setSinkId) return;
    try { await elemento.setSinkId((await llIdElegido('altavoz', 'audiooutput')) || ''); }
    catch (e) { console.warn('[LLAMADAS] No se pudo usar ese altavoz', e); }
}

const LL_PUEDE_ELEGIR_ALTAVOZ = 'setSinkId' in HTMLMediaElement.prototype;

// Cambia el micrófono en plena llamada, sin renegociar con nadie
async function llCambiarMicEnLlamada() {
    const a = llActual;
    if (!a) return;
    const s = await navigator.mediaDevices.getUserMedia({ audio: await llAudioConstraints() });
    const nueva = s.getAudioTracks()[0];
    if (llActual !== a) { nueva.stop(); return; }
    nueva.enabled = !a.silenciado;
    await Promise.all(Array.from(a.peers.values()).map(peer => {
        const emisor = peer.pc.getSenders().find(x => x.track && x.track.kind === 'audio');
        return emisor ? emisor.replaceTrack(nueva) : null;
    }));
    a.local.getAudioTracks().forEach(t => { a.local.removeTrack(t); t.stop(); });
    a.local.addTrack(nueva);
}

// Sección Audio de Configuración
async function cargarConfigAudio() {
    const mic = document.getElementById('audio-mic');
    const altavoz = document.getElementById('audio-altavoz');
    const msg = document.getElementById('audio-msg');
    msg.textContent = 'Buscando dispositivos…';
    let lista, elegidos;
    try {
        [lista, elegidos] = await Promise.all([llListarDispositivos(), window.pywebview.api.obtener_audio_llamadas()]);
    } catch (e) {
        msg.textContent = 'No se pudieron leer los dispositivos: ' + (e.message || e.name || e);
        return;
    }
    const llenar = (select, tipo, actual) => {
        select.innerHTML = '';
        select.add(new Option('Predeterminado del sistema', ''));
        const nombres = lista.filter(d => d.kind === tipo && d.label && d.deviceId !== 'default' && d.deviceId !== 'communications')
            .map(d => d.label);
        new Set(nombres).forEach(n => select.add(new Option(n, n)));
        // Si está desconectado se conserva la elección: vuelve a usarse al conectarlo
        if (actual && !nombres.includes(actual)) select.add(new Option(actual + ' (no conectado)', actual));
        select.value = actual || '';
    };
    llenar(mic, 'audioinput', elegidos.mic);
    llenar(altavoz, 'audiooutput', elegidos.altavoz);
    altavoz.disabled = !LL_PUEDE_ELEGIR_ALTAVOZ;
    document.getElementById('audio-altavoz-aviso').style.display = LL_PUEDE_ELEGIR_ALTAVOZ ? 'none' : '';
    msg.textContent = '';
}

// Guarda la elección y la aplica si hay una llamada en curso.
async function guardarConfigAudio(cambio) {
    const msg = document.getElementById('audio-msg');
    const res = await window.pywebview.api.guardar_audio_llamadas(
        document.getElementById('audio-mic').value, document.getElementById('audio-altavoz').value);
    if (!res || !res.exito) { msg.textContent = (res && res.error) || 'No se pudo guardar.'; return; }
    msg.textContent = '✔ Guardado';
    if (!llActual) return;
    if (cambio === 'altavoz') {
        document.querySelectorAll('#llamada-audios audio').forEach(llAplicarAltavoz);
        return;
    }
    try {
        await llCambiarMicEnLlamada();
    } catch (e) {
        msg.textContent = 'No se pudo cambiar el micrófono: ' + (e.message || e.name);
    }
}

// Micrófono (y cámara si se pide). Si la cámara falla, se sigue solo con audio.
async function llObtenerMedios(conVideo) {
    const audio = await llAudioConstraints();
    try {
        if (conVideo) {
            try {
                return { stream: await navigator.mediaDevices.getUserMedia({ audio, video: LL_VIDEO }), video: true };
            } catch (e) {
                llAviso('No se pudo usar la cámara; seguís solo con audio.');
            }
        }
        return { stream: await navigator.mediaDevices.getUserMedia({ audio }), video: false };
    } catch (e) {
        alert('No se pudo usar el micrófono: ' + (e.message || e.name) +
              '\nRevisá que esté conectado y que la app tenga permiso.');
        return null;
    }
}

// Crea el objeto con todo el estado de la llamada actual.
function llNuevaLlamada(id, soyCreador, medios) {
    const a = {
        id, soyCreador, local: medios.stream, canal: null,
        estado: soyCreador ? 'sonando' : 'conectando',   // sonando | conectando | en_curso
        invitados: new Set(), peers: new Map(), nombres: {},
        silenciado: false, camara: false, videoTrack: null, pantallaTrack: null,
        inicio: null, timerSonando: null,
    };
    const pista = medios.video ? medios.stream.getVideoTracks()[0] : null;
    if (pista) {
        a.camara = true;
        a.videoTrack = pista;
        pista.onended = () => { if (llActual === a && a.videoTrack === pista) llApagarCamara(); };
    }
    return a;
}

// Pide el micrófono, crea la llamada y espera a que atiendan.
async function llIniciarLlamada(ids, conVideo, nombre) {
    if (!llSb) { alert('Las llamadas no están disponibles ahora (revisá tu conexión y reiniciá sesión).'); return; }
    if (llActual || llEntrante || llIniciando) { llAviso('Ya estás en una llamada.'); return; }
    llIniciando = true;
    let medios, res;
    try {
        if (!await llLlavesListas(ids, nombre)) return;
        medios = await llObtenerMedios(conVideo);
        if (!medios) return;
        res = await window.pywebview.api.crear_llamada(ids, conVideo);
    } finally {
        llIniciando = false;
    }
    if (!res || !res.exito) {
        medios.stream.getTracks().forEach(t => t.stop());
        alert((res && res.error) || 'No se pudo iniciar la llamada.');
        return;
    }
    llActual = llNuevaLlamada(res.llamada_id, true, medios);
    ids.forEach(i => llActual.invitados.add(i));
    llActual.nombres[ids[0]] = nombre || '';
    llActualizarBotonCamara();
    llRefrescarVideos();
    llEstadoBarra(nombre, conVideo ? 'Videollamada…' : 'Llamando…');
    try {
        await llUnirseCanal();
    } catch (e) {
        await llColgar('No se pudo conectar con el servidor de llamadas.', true);
        return;
    }
    const idLlamada = llActual.id;
    llActual.timerSonando = setTimeout(() => {
        if (llActual && llActual.id === idLlamada && llActual.estado === 'sonando') {
            llColgar('No respondió.', true);
        }
    }, LL_TIMBRE_MS);
}

// ---------------------------------------------------------------------------
// Recibir (timbre)
// ---------------------------------------------------------------------------

// Llegó una invitación: rechaza si estás ocupado; si no, hace sonar el timbre.
async function llAlInvitacion(fila) {
    if (!fila || fila.estado !== 'invitado') return;
    if (llActual || llEntrante) {                       // ocupado: se rechaza sin molestar
        try { await window.pywebview.api.responder_llamada(fila.llamada_id, false); } catch (e) { /* nada */ }
        return;
    }
    let det;
    try { det = await window.pywebview.api.obtener_llamada(fila.llamada_id); } catch (e) { return; }
    if (!det || !det.exito || !['sonando', 'en_curso'].includes(det.llamada.estado)) return;
    const desde = fila.invitado_en || det.llamada.creada_en;   // si ya estaba en curso, cuenta desde la invitación
    if (Date.now() - new Date(desde).getTime() > LL_VIGENCIA_MS) return;
    if (llActual || llEntrante) return;                 // algo cambió mientras se consultaba

    const quien = det.participantes.find(p => p.user_id === (fila.invitado_por || det.llamada.creador_id))
        || { username: 'Alguien', avatar_url: '' };
    const yaEnCurso = det.llamada.estado === 'en_curso';
    const conVideo = !!det.llamada.con_video;
    llEntrante = { id: fila.llamada_id, de: quien, conVideo };
    document.getElementById('llamada-timbre-nombre').textContent = quien.username || 'Alguien';
    document.getElementById('llamada-timbre-sub').textContent = yaEnCurso ? 'te agregó a una llamada…' : (conVideo ? 'te está haciendo una videollamada…' : 'te está llamando…');
    document.getElementById('llamada-aceptar-video').style.display = conVideo ? '' : 'none';
    document.getElementById('llamada-timbre-avatar').src = avatarDe(quien);
    llMostrar('llamada-timbre');
    llTimbre(true);
    const id = fila.llamada_id;
    setTimeout(() => { if (llEntrante && llEntrante.id === id) llCerrarTimbre('Llamada perdida.'); }, LL_TIMBRE_MS);
}

// Oculta el timbre, con un aviso opcional.
function llCerrarTimbre(aviso) {
    llDetenerTimbre();
    llOcultar('llamada-timbre');
    llEntrante = null;
    if (aviso) llAviso(aviso);
}

// conVideo = true: se entra con la cámara encendida (solo si quien llama pidió videollamada)
async function llAceptar(conVideo = false) {
    const ent = llEntrante;
    if (!ent || ent.aceptando) return;
    ent.aceptando = true;
    if (!await llLlavesListas([ent.de.user_id], ent.de.username)) { await llRechazar(); return; }
    const medios = await llObtenerMedios(conVideo && ent.conVideo);
    if (!medios) { await llRechazar(); return; }
    if (llEntrante !== ent) {                           // dejó de sonar mientras se pedía el micrófono
        medios.stream.getTracks().forEach(t => t.stop());
        return;
    }
    llCerrarTimbre(null);
    const res = await window.pywebview.api.responder_llamada(ent.id, true);
    if (!res || !res.exito) {
        medios.stream.getTracks().forEach(t => t.stop());
        llAviso((res && res.error) || 'No se pudo atender la llamada.');
        return;
    }
    llActual = llNuevaLlamada(ent.id, false, medios);
    llEsperarConexion(llActual);
    llActual.nombres[ent.de.user_id] = ent.de.username;
    llActualizarBotonCamara();
    llRefrescarVideos();
    llEstadoBarra(ent.de.username, 'Conectando…');
    try {
        await llUnirseCanal();
    } catch (e) {
        await llColgar('No se pudo conectar con el servidor de llamadas.');
    }
}

// Rechaza la invitación que está sonando.
async function llRechazar() {
    const ent = llEntrante;
    if (!ent) return;
    llCerrarTimbre(null);
    try { await window.pywebview.api.responder_llamada(ent.id, false); } catch (e) { /* nada */ }
}

// ---------------------------------------------------------------------------
// Cambios en vivo (Realtime)
// ---------------------------------------------------------------------------

// Ya atendieron pero la conexión directa puede no armarse nunca (por ejemplo por la red de alguno):
// sin este límite la llamada se quedaría en "Conectando…" para siempre
function llEsperarConexion(a) {
    clearTimeout(a.timerSonando);
    a.estado = 'conectando';
    a.timerSonando = setTimeout(() => {
        if (llActual === a && a.estado !== 'en_curso') {
            llColgar('No se pudo conectar. Puede que la red de alguno de los dos lo esté bloqueando.');
        }
    }, LL_CONEXION_MS);
}

// La llamada terminó: cierra lo abierto y actualiza el registro del chat.
function llAlCambioLlamada(fila) {
    if (!fila || fila.estado !== 'terminada') return;
    if (llEntrante && llEntrante.id === fila.id) llCerrarTimbre('Llamada perdida.');
    if (llActual && llActual.id === fila.id) llColgar('La llamada terminó.');
    // El registro aparece en el chat: se pide ahora y otra vez enseguida por si algún dato llegó tarde
    chatRefrescarLlamadas();
    setTimeout(chatRefrescarLlamadas, 1500);
}

// Alguien atendió, rechazó o salió de la llamada.
function llAlCambioParticipante(fila) {
    if (fila && fila.usuario_id === llYo) {
        // Me agregaron (de nuevo) a una llamada: se trata como una invitación más
        if (fila.estado === 'invitado') llAlInvitacion(fila);
        return;
    }
    if (!llActual || !fila || fila.llamada_id !== llActual.id) return;
    if (fila.estado === 'unido' && llActual.estado === 'sonando') {
        llEsperarConexion(llActual);                  // ya atendió: "No respondió" dejaría de ser cierto
        llEstadoBarra(llTextoNombres(), 'Conectando…');
    } else if (fila.estado === 'rechazado') {
        llActual.invitados.delete(fila.usuario_id);
        if (llActual.estado === 'sonando' && llActual.invitados.size === 0) {
            llColgar('Rechazó la llamada.', true);
        } else if (llActual.estado !== 'sonando') {
            llAviso((llActual.nombres[fila.usuario_id] || 'Alguien') + ' rechazó la invitación.');
        }
    } else if (fila.estado === 'salio') {
        llActual.invitados.delete(fila.usuario_id);   // así se lo puede volver a invitar
        llCerrarPeer(fila.usuario_id);
    }
}

// ---------------------------------------------------------------------------
// Señalización por el canal broadcast + conexión WebRTC
// Se usa "negociación perfecta": cualquiera puede renegociar (por ejemplo al encender la
// cámara) y si dos ofertas se cruzan, el de id menor cede.
// ---------------------------------------------------------------------------

// Se une al canal de señales de esta llamada y saluda a los demás.
async function llUnirseCanal() {
    const a = llActual;
    const canal = llSb.channel('llamada:' + a.id, { config: { private: true, broadcast: { self: false } } });
    // En orden: abrirlas lleva un instante y una oferta no debe adelantarse a la anterior
    canal.on('broadcast', { event: 'senal' }, ({ payload }) => {
        llColaEntrada = llColaEntrada.then(() => llAlSenal(payload));
    });
    await new Promise((ok, mal) => {
        canal.subscribe(estado => {
            if (estado === 'SUBSCRIBED') ok();
            else if (estado === 'CHANNEL_ERROR' || estado === 'TIMED_OUT') mal(new Error(estado));
        });
    });
    a.canal = canal;
    llEnviar({ tipo: 'hola' });
    llCargarNombres();
}

const LL_SELLADAS = new Set(['descripcion', 'ice']);   // llevan la huella de cifrado y la dirección de red
let llColaEntrada = Promise.resolve();
let llColaSalida = Promise.resolve();

// Envía una señal; "para" la dirige a una sola persona.
function llEnviar(msg, para = null) {
    if (!llActual || !llActual.canal) return;
    const a = llActual;
    if (LL_SELLADAS.has(msg.tipo)) {
        llColaSalida = llColaSalida.then(() => llEnviarSellada(a, msg, para));
        return;
    }
    a.canal.send({ type: 'broadcast', event: 'senal', payload: { de: llYo, para, ...msg } });
}

// Sella la señal en Python y la envía. Sin sellar no sale: mejor que no conecte a que conecte sin protección.
async function llEnviarSellada(a, msg, para) {
    try {
        const res = await window.pywebview.api.llamada_sellar(a.id, para, JSON.stringify(msg));
        if (!res || !res.exito) { llAvisarSenal(res); return; }
        if (llActual === a && a.canal) {
            a.canal.send({ type: 'broadcast', event: 'senal', payload: { de: llYo, para, tipo: 'sellada', sellada: res.sellada } });
        }
    } catch (e) {
        console.warn('[LLAMADAS] No se pudo sellar la señal', e);
    }
}

const LL_AVISO_LLAVE_MS = 8000;   // hay que leerlo y saber qué hacer, no es solo informativo

// Comprueba las llaves antes de que suene: sin esto, la llamada sonaría y después nunca conectaría.
// Si no se pueden consultar se sigue: las señales selladas igual frenan una llave distinta.
async function llLlavesListas(ids, nombre) {
    for (const id of ids) {
        let res = null;
        try { res = await window.pywebview.api.llaves_amigo_estado(id); } catch (e) { /* se sigue */ }
        if (!res || !res.exito) continue;
        const quien = nombre || 'una persona de la llamada';
        if (res.estado === 'cambio') {
            llAviso(`La llave de ${quien} cambió. Abrí su chat y aceptala para poder hablar.`, LL_AVISO_LLAVE_MS);
            return false;
        }
        if (res.estado === 'sin_llave') {
            llAviso(`${quien} todavía no activó sus mensajes privados, y sin eso no se puede conectar la llamada.`, LL_AVISO_LLAVE_MS);
            return false;
        }
        if (!res.codigo) {
            llAviso('Para hablar por llamada, primero activá tu frase de recuperación.', LL_AVISO_LLAVE_MS);
            if (typeof llavesIniciar === 'function') llavesIniciar();
            return false;
        }
    }
    return true;
}

// Explica por qué una señal no se pudo enviar o abrir. Una sola vez por llamada: fallan todas seguidas.
function llAvisarSenal(res) {
    if (llActual) {
        if (llActual.avisoSenal) return;
        llActual.avisoSenal = true;
    }
    llAviso((res && res.error) || 'No se pudo proteger la conexión de la llamada.', LL_AVISO_LLAVE_MS);
    if (res && res.falta_mi_llave && typeof llavesIniciar === 'function') llavesIniciar();
}

// Abre una señal sellada. Las de estos tipos sin sellar se descartan: podrían venir de cualquiera.
async function llAbrirSenal(p) {
    if (LL_SELLADAS.has(p.tipo)) return null;
    if (p.tipo !== 'sellada') return p;
    const res = await window.pywebview.api.llamada_abrir(llActual.id, p.de, p.sellada);
    if (!res || !res.exito) { llAvisarSenal(res); return null; }
    const datos = JSON.parse(res.datos);
    return LL_SELLADAS.has(datos.tipo) ? { ...datos, de: p.de, para: p.para } : null;
}

// Reparte cada señal recibida según su tipo.
async function llAlSenal(recibida) {
    if (!llActual || !recibida || recibida.de === llYo) return;
    if (recibida.para && recibida.para !== llYo) return;
    try {
        const p = await llAbrirSenal(recibida);
        if (!p || !llActual) return;
        if (p.tipo === 'hola') llAlHola(p);
        else if (p.tipo === 'descripcion') await llAlDescripcion(p);
        else if (p.tipo === 'ice') await llAlIce(p);
        else if (p.tipo === 'camara') {
            const peer = llActual.peers.get(p.de);    // una señal tardía de quien ya se fue no lo revive
            if (peer) { peer.camaraRemota = !!p.activa; llRefrescarVideos(); }
        }
        else if (p.tipo === 'chau') llCerrarPeer(p.de);
    } catch (e) {
        console.warn('[LLAMADAS] Error con la señal', recibida.tipo, e);
    }
}

// Devuelve o crea la conexión WebRTC con un participante.
function llPeer(id) {
    if (llActual.peers.has(id)) return llActual.peers.get(id);
    const pc = new RTCPeerConnection(LL_ICE);
    const peer = {
        id, pc, hielo: [],
        cede: llYo < id,                  // en un cruce de ofertas, este lado cede
        haciendoOferta: false, ignorarOferta: false,
        videoSender: null, streamRemoto: null, camaraRemota: false,
    };

    pc.onnegotiationneeded = async () => {
        try {
            peer.haciendoOferta = true;
            await pc.setLocalDescription();
            llEnviar({ tipo: 'descripcion', sdp: pc.localDescription.toJSON() }, id);
        } catch (e) {
            console.warn('[LLAMADAS] No se pudo negociar', e);
        } finally {
            peer.haciendoOferta = false;
        }
    };
    pc.onicecandidate = e => { if (e.candidate) llEnviar({ tipo: 'ice', candidato: e.candidate.toJSON() }, id); };
    pc.ontrack = e => {
        peer.streamRemoto = e.streams[0] || peer.streamRemoto;
        if (e.track.kind === 'audio') {
            let audio = document.querySelector(`#llamada-audios audio[data-peer="${id}"]`);
            if (!audio) {
                audio = document.createElement('audio');
                audio.dataset.peer = id;
                audio.autoplay = true;
                document.getElementById('llamada-audios').appendChild(audio);
                llAplicarAltavoz(audio);
            }
            audio.srcObject = peer.streamRemoto;
            audio.play().catch(() => { /* ya reproduce solo al haber interactuado */ });
        } else {
            llRefrescarVideos();
        }
    };
    pc.onconnectionstatechange = () => {
        if (!llActual) return;
        if (pc.connectionState === 'connected') llMarcarConectada();
        else if (pc.connectionState === 'failed') {
            llAviso('Se perdió la conexión con ' + (llActual.nombres[id] || 'el otro usuario') + '.');
            llCerrarPeer(id);
        }
    };

    llActual.peers.set(id, peer);
    // Al agregar las pistas el navegador dispara la negociación inicial
    llActual.local.getTracks().forEach(t => {
        const sender = pc.addTrack(t, llActual.local);
        if (t.kind === 'video') peer.videoSender = sender;
    });
    return peer;
}

// Alguien entró: se crea la conexión y se responde el saludo.
function llAlHola(p) {
    llPeer(p.de);
    if (!llActual.nombres[p.de]) llCargarNombres();   // alguien nuevo: se pide su nombre
    if (!p.responde) llEnviar({ tipo: 'hola', responde: true }, p.de);
    if (llVideoSaliente(llActual)) llEnviar({ tipo: 'camara', activa: true }, p.de);   // que me vea desde el inicio
}

// Recibe una oferta o respuesta, resolviendo los cruces de ofertas.
async function llAlDescripcion(p) {
    const peer = llPeer(p.de);
    const pc = peer.pc;
    const descripcion = p.sdp;
    const cruce = descripcion.type === 'offer' && (peer.haciendoOferta || pc.signalingState !== 'stable');
    peer.ignorarOferta = !peer.cede && cruce;      // el que no cede ignora la oferta que se le cruza
    if (peer.ignorarOferta) return;
    await pc.setRemoteDescription(descripcion);    // el que cede deshace su oferta automáticamente
    await llVaciarHielo(peer);
    if (descripcion.type === 'offer') {
        await pc.setLocalDescription();
        llEnviar({ tipo: 'descripcion', sdp: pc.localDescription.toJSON() }, p.de);
    }
}

// Agrega un candidato de red; si llegó antes de tiempo, lo guarda.
async function llAlIce(p) {
    const peer = llActual.peers.get(p.de);             // una señal tardía de quien ya se fue no lo revive
    if (!peer) return;
    if (!peer.pc.remoteDescription) { peer.hielo.push(p.candidato); return; }   // llegó antes que la descripción
    try {
        await peer.pc.addIceCandidate(p.candidato);
    } catch (e) {
        if (!peer.ignorarOferta) throw e;
    }
}

// Aplica los candidatos que estaban guardados.
async function llVaciarHielo(peer) {
    while (peer.hielo.length) {
        try { await peer.pc.addIceCandidate(peer.hielo.shift()); } catch (e) { /* candidato de una oferta ignorada */ }
    }
}

// Primera conexión lograda: arranca el contador de duración.
function llMarcarConectada() {
    const a = llActual;
    if (!a || a.estado === 'en_curso') return;
    a.estado = 'en_curso';
    clearTimeout(a.timerSonando);
    a.inicio = Date.now();
    const pintar = () => {
        const s = Math.floor((Date.now() - a.inicio) / 1000);
        llEstadoBarra(llTextoNombres(), 'En llamada · ' + String(Math.floor(s / 60)).padStart(2, '0') + ':' + String(s % 60).padStart(2, '0'));
    };
    pintar();
    clearInterval(llDuracionTimer);
    llDuracionTimer = setInterval(pintar, 1000);
}

// Cierra la conexión con alguien; sin nadie más, termina la llamada.
function llCerrarPeer(id) {
    if (!llActual) return;
    const peer = llActual.peers.get(id);
    if (peer) { try { peer.pc.close(); } catch (e) { /* nada */ } llActual.peers.delete(id); }
    document.querySelectorAll(`#llamada-audios audio[data-peer="${id}"]`).forEach(a => a.remove());
    llRefrescarVideos();
    if (llActual.peers.size === 0 && llActual.estado === 'en_curso') llColgar('La llamada terminó.');
}

// ---------------------------------------------------------------------------
// Video: cámara propia y ventanas de los demás
// ---------------------------------------------------------------------------

// Refleja en el botón si la cámara está encendida.
function llActualizarBotonCamara() {
    const b = document.getElementById('llamada-camara');
    if (!b) return;
    const activa = !!(llActual && llActual.camara);
    b.classList.toggle('activo', activa);
    b.title = activa ? 'Apagar cámara' : 'Activar cámara';
    const p = document.getElementById('llamada-pantalla');
    const compartiendo = !!(llActual && llActual.pantallaTrack);
    p.classList.toggle('activo', compartiendo);
    p.title = compartiendo ? 'Dejar de compartir' : 'Compartir pantalla';
}

// Enciende o apaga la cámara durante la llamada.
async function llAlternarCamara() {
    const a = llActual;
    if (!a) return;
    if (a.camara) { llApagarCamara(); return; }
    let pista;
    try {
        const s = await navigator.mediaDevices.getUserMedia({ video: LL_VIDEO });
        pista = s.getVideoTracks()[0];
    } catch (e) {
        llAviso('No se pudo usar la cámara: ' + (e.message || e.name));
        return;
    }
    if (llActual !== a) { pista.stop(); return; }       // la llamada terminó mientras se pedía la cámara
    a.videoTrack = pista;
    a.camara = true;
    pista.onended = () => { if (llActual === a && a.videoTrack === pista) llApagarCamara(); };
    llPublicarVideo(a);
}

// Apaga la cámara y avisa a los demás.
function llApagarCamara() {
    const a = llActual;
    if (!a || !a.camara) return;
    const pista = a.videoTrack;
    a.camara = false;
    a.videoTrack = null;
    if (pista) pista.stop();
    llPublicarVideo(a);
}

// Cada persona envía un solo video: la pantalla si la está compartiendo y, si no, la cámara
function llVideoSaliente(a) {
    return a.pantallaTrack || a.videoTrack;
}

// Envía a todos el video que corresponde ahora. La cámara no se apaga mientras se comparte
// pantalla: al dejar de compartir vuelve sola.
function llPublicarVideo(a) {
    const pista = llVideoSaliente(a);
    a.local.getVideoTracks().forEach(t => { if (t !== pista) a.local.removeTrack(t); });
    if (pista && !a.local.getVideoTracks().includes(pista)) a.local.addTrack(pista);
    a.peers.forEach(peer => {
        if (peer.videoSender) peer.videoSender.replaceTrack(pista).catch(() => { /* la conexión se está cerrando */ });
        else if (pista) peer.videoSender = peer.pc.addTrack(pista, a.local);  // primera vez: se renegocia
    });
    llEnviar({ tipo: 'camara', activa: !!pista });
    llActualizarBotonCamara();
    llRefrescarVideos();
}

// Botón 🖥️: abre el selector o deja de compartir
async function llAlternarPantalla() {
    const a = llActual;
    if (!a) return;
    if (a.pantallaTrack) { llDetenerPantalla(a); return; }
    let captura;
    try {
        captura = await navigator.mediaDevices.getDisplayMedia({
            video: { frameRate: { ideal: 30, max: 30 }, width: { max: 1920 }, height: { max: 1080 } },
            audio: false,
        });
    } catch (e) {
        if (e.name !== 'NotAllowedError') llAviso('No se pudo compartir la pantalla: ' + (e.message || e.name));  // NotAllowedError = canceló
        return;
    }
    const pista = captura.getVideoTracks()[0];
    if (llActual !== a) { pista.stop(); return; }       // la llamada terminó mientras elegía
    pista.contentHint = 'detail';                       // imagen nítida desde el inicio; con poca conexión baja primero los FPS
    pista.onended = () => { if (llActual === a && a.pantallaTrack === pista) llDetenerPantalla(a); };
    a.pantallaTrack = pista;
    llPublicarVideo(a);
}

function llDetenerPantalla(a) {
    const pista = a.pantallaTrack;
    a.pantallaTrack = null;
    if (pista) pista.stop();
    llPublicarVideo(a);
}

// Agranda o achica la ventana de video.
function llAlternarGrande() {
    const c = document.getElementById('llamada-videos');
    if (c) c.classList.toggle('grande');
}

// Dibuja/quita las ventanas según quién tiene la cámara encendida
function llRefrescarVideos() {
    const cont = document.getElementById('llamada-videos');
    if (!cont) return;
    const a = llActual;
    const grid = document.getElementById('llamada-videos-grid');
    const visibles = new Set();
    if (a) a.peers.forEach(peer => { if (peer.camaraRemota && peer.streamRemoto) visibles.add(peer.id); });

    grid.querySelectorAll('.llamada-tile').forEach(t => { if (!visibles.has(t.dataset.peer)) t.remove(); });
    visibles.forEach(id => {
        const peer = a.peers.get(id);
        let tile = grid.querySelector(`.llamada-tile[data-peer="${id}"]`);
        if (!tile) {
            tile = document.createElement('div');
            tile.className = 'llamada-tile';
            tile.dataset.peer = id;
            const v = document.createElement('video');
            v.autoplay = true; v.muted = true; v.playsInline = true;   // el audio ya suena por su <audio>
            tile.append(v, document.createElement('span'));
            grid.appendChild(tile);
        }
        tile.querySelector('span').textContent = a.nombres[id] || '';   // el nombre puede llegar después que el video
        const v = tile.querySelector('video');
        if (v.srcObject !== peer.streamRemoto) v.srcObject = peer.streamRemoto;
        v.play().catch(() => { /* se reproduce al interactuar */ });
    });

    const local = document.getElementById('llamada-local');
    const saliente = a && llVideoSaliente(a);
    if (saliente) {
        if (!local.srcObject || local.srcObject.getVideoTracks()[0] !== saliente) {
            local.srcObject = new MediaStream([saliente]);
        }
        local.classList.toggle('pantalla', !!a.pantallaTrack);
        local.style.display = 'block';
    } else {
        local.srcObject = null;
        local.style.display = 'none';
    }

    const hay = visibles.size > 0 || !!saliente;
    cont.style.display = hay ? 'flex' : 'none';
    cont.classList.toggle('solo-local', hay && visibles.size === 0);
    if (!hay) cont.classList.remove('grande');
}

// ---------------------------------------------------------------------------
// Controles y cierre
// ---------------------------------------------------------------------------

// Silencia o activa el micrófono.
function llAlternarMute() {
    if (!llActual) return;
    llActual.silenciado = !llActual.silenciado;
    llActual.local.getAudioTracks().forEach(t => { t.enabled = !llActual.silenciado; });
    document.getElementById('llamada-mute').textContent = llActual.silenciado ? '🔇' : '🎤';
}

// Botón colgar: si aún suena y llamaste tú, se cancela para todos.
function llColgarManual() {
    // Si todavía suena y la inicié yo, se cancela para todos
    if (llActual) llColgar(null, llActual.soyCreador && llActual.estado === 'sonando');
}

// Cierra conexiones, apaga micrófono y cámara, y avisa a Supabase.
async function llColgar(aviso, terminar = false) {
    const a = llActual;
    if (!a) return;
    llActual = null;
    clearTimeout(a.timerSonando);
    clearInterval(llDuracionTimer);
    llDuracionTimer = null;
    if (a.canal) {
        try {
            await Promise.race([
                a.canal.send({ type: 'broadcast', event: 'senal', payload: { de: llYo, para: null, tipo: 'chau' } }),
                new Promise(r => setTimeout(r, 500)),
            ]);
        } catch (e) { /* nada */ }
    }
    a.peers.forEach(p => { try { p.pc.close(); } catch (e) { /* nada */ } });
    [...a.local.getTracks(), a.videoTrack, a.pantallaTrack].forEach(t => { if (t) t.stop(); });   // la cámara puede estar en pausa
    if (a.canal && llSb) { try { llSb.removeChannel(a.canal); } catch (e) { /* nada */ } }
    document.getElementById('llamada-audios').innerHTML = '';
    document.getElementById('llamada-videos-grid').innerHTML = '';
    document.getElementById('llamada-mute').textContent = '🎤';
    llActualizarBotonCamara();
    llRefrescarVideos();
    llOcultar('llamada-barra');
    llCerrarInvitar();
    if (aviso) llAviso(aviso);
    try { await window.pywebview.api.salir_llamada(a.id, terminar); } catch (e) { /* nada */ }
}

// ---------------------------------------------------------------------------
// Llamadas grupales: nombres y agregar gente a la llamada
// ---------------------------------------------------------------------------

// Pide los nombres de todos los participantes (para la barra y las ventanas de video)
async function llCargarNombres() {
    const a = llActual;
    if (!a) return;
    try {
        const det = await window.pywebview.api.obtener_llamada(a.id);
        if (llActual !== a || !det || !det.exito) return;
        det.participantes.forEach(p => { if (p.user_id !== llYo && p.username) a.nombres[p.user_id] = p.username; });
        if (a.estado !== 'en_curso') document.getElementById('llamada-barra-nombre').textContent = llTextoNombres();
        llRefrescarVideos();
    } catch (e) { /* se queda con lo que haya */ }
}

// "Ana", "Ana y Luis", "Ana, Luis y 2 más"
function llTextoNombres() {
    const a = llActual;
    if (!a) return '';
    const ids = a.peers.size ? Array.from(a.peers.keys()) : Object.keys(a.nombres);
    const n = ids.map(id => a.nombres[id]).filter(Boolean);
    if (n.length <= 2) return n.join(' y ');
    return `${n[0]}, ${n[1]} y ${n.length - 2} más`;
}

// Lista los amigos que todavía no están en la llamada.
async function llAbrirInvitar() {
    const a = llActual;
    if (!a) return;
    const panel = document.getElementById('llamada-invitar');
    const lista = document.getElementById('llamada-invitar-lista');
    lista.textContent = 'Cargando…';
    panel.style.display = 'flex';
    let res;
    try { res = await window.pywebview.api.obtener_social(); } catch (e) { res = null; }
    if (llActual !== a) { llCerrarInvitar(); return; }
    lista.innerHTML = '';
    if (!res || !res.exito) { lista.textContent = 'No se pudieron cargar tus amigos.'; return; }

    const yaEstan = new Set([llYo, ...a.peers.keys(), ...a.invitados]);
    const candidatos = (res.amigos || []).filter(f => !yaEstan.has(f.user_id));
    if (!candidatos.length) { lista.textContent = 'No tenés más amigos para agregar.'; return; }
    candidatos.forEach(f => {
        const fila = document.createElement('label');
        fila.className = 'llamada-invitar-fila';
        const caja = document.createElement('input');
        caja.type = 'checkbox';
        caja.value = f.user_id;
        caja.dataset.nombre = f.username || '';
        const img = document.createElement('img');
        img.src = avatarDe(f);
        img.alt = '';
        const nombre = document.createElement('span');
        nombre.textContent = f.username || '';
        fila.append(caja, img, nombre);
        lista.appendChild(fila);
    });
}

// Cierra esa lista.
function llCerrarInvitar() {
    document.getElementById('llamada-invitar').style.display = 'none';
}

// Invita a los amigos marcados, respetando el máximo de personas.
async function llEnviarInvitaciones() {
    const a = llActual;
    if (!a) { llCerrarInvitar(); return; }
    const marcados = Array.from(document.querySelectorAll('#llamada-invitar-lista input:checked'));
    if (!marcados.length) { llCerrarInvitar(); return; }
    const ocupados = new Set([llYo, ...a.peers.keys(), ...a.invitados]).size;
    if (ocupados + marcados.length > LL_MAX_PERSONAS) {
        llAviso(`Una llamada admite hasta ${LL_MAX_PERSONAS} personas.`);
        return;
    }
    let res;
    try { res = await window.pywebview.api.invitar_a_llamada(a.id, marcados.map(m => m.value)); } catch (e) { res = null; }
    llCerrarInvitar();
    if (!res || !res.exito) { llAviso((res && res.error) || 'No se pudo invitar.'); return; }
    marcados.forEach(m => {
        a.invitados.add(m.value);
        if (!a.nombres[m.value]) a.nombres[m.value] = m.dataset.nombre;
        // Si no atiende (o no estaba conectado) se libera su lugar y se lo puede volver a invitar
        setTimeout(() => { if (!a.peers.has(m.value)) a.invitados.delete(m.value); }, LL_VIGENCIA_MS);
    });
    llAviso(marcados.length === 1 ? 'Invitación enviada.' : 'Invitaciones enviadas.');
}

// ---------------------------------------------------------------------------
// Registro de llamadas dentro del chat (duración, horarios y cuántas personas hubo)
// ---------------------------------------------------------------------------

let chatLlamadas = [];   // registros de llamadas con el amigo cuyo chat está abierto

// Trae las llamadas terminadas con este amigo.
async function chatCargarLlamadas(amigoId) {
    try {
        const res = await window.pywebview.api.obtener_historial_llamadas(amigoId);
        if (!chatAmigo || chatAmigo.user_id !== amigoId) return false;
        if (res && res.exito) {
            chatLlamadas = (res.llamadas || []).map(l => ({ ...l, tipo: 'registro_llamada', creado_en: l.fin }));
            return true;
        }
    } catch (e) { /* el chat sigue sin el registro */ }
    return false;
}

// Actualiza el registro si el chat sigue abierto.
async function chatRefrescarLlamadas() {
    if (!chatAmigo || socialSeccion !== 'chat') return;
    const id = chatAmigo.user_id;
    if (await chatCargarLlamadas(id) && chatAmigo && chatAmigo.user_id === id) renderizarChat('sync');
}

// Mensajes y registros de llamadas mezclados por hora
function chatItemsOrdenados() {
    return [...chatMensajes, ...chatLlamadas].sort((a, b) => new Date(a.creado_en) - new Date(b.creado_en));
}

// Hora en formato de 24 horas.
function llHora(iso) {
    const d = new Date(iso);
    return isNaN(d.getTime()) ? '' : d.toLocaleTimeString('es-AR', { hour: '2-digit', minute: '2-digit', hour12: false });
}

// Duración legible: 1 h 05 min, 3 min 20 s.
function llDuracionTexto(segundos) {
    const s = Math.max(0, Math.round(segundos));
    const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60), r = s % 60;
    if (h) return `${h} h ${String(m).padStart(2, '0')} min`;
    if (m) return `${m} min ${String(r).padStart(2, '0')} s`;
    return `${r} s`;
}

// Tarjeta del chat con el resultado de una llamada.
function crearRegistroLlamada(l) {
    const fila = document.createElement('div');
    const titulo = document.createElement('strong');
    const detalle = document.createElement('small');
    let lineas;

    if (l.resultado === 'completada') {
        fila.className = 'msg-llamada';
        titulo.textContent = l.con_video ? '🎥 Videollamada finalizada' : '📞 Llamada de voz finalizada';
        lineas = [
            `Duración: ${llDuracionTexto(l.duracion_s)}`,
            `Inició ${llHora(l.inicio)} · Terminó ${llHora(l.fin)}`,
            `${l.personas} ${l.personas === 1 ? 'persona' : 'personas'} en la llamada`,
        ];
    } else {
        fila.className = 'msg-llamada perdida';
        if (l.resultado === 'rechazada') {
            titulo.textContent = l.rechazada_por_mi ? '📵 Rechazaste la llamada' : '📵 Llamada rechazada';
        } else {
            titulo.textContent = l.yo_llame ? '📵 Llamada sin respuesta' : '📵 Llamada perdida';
        }
        lineas = [llHora(l.inicio)];
    }
    detalle.textContent = lineas.join('\n');
    fila.append(titulo, detalle);
    return fila;
}
