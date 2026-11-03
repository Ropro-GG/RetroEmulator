<div align="center">

  <h1>🎮 RetroEmulator</h1>
  <p><strong>El launcher definitivo de videojuegos retro enfocado en la comunidad, totalmente gratuito y de código abierto.</strong></p>

  <p>
    <a href="#-características-principales">Características</a> •
    <a href="#-requisitos-e-instalación">Instalación</a> •
    <a href="#-capturas-de-pantalla">Capturas</a> •
    <a href="#-contribuciones">Contribuciones</a> •
    <a href="#-licencia">Licencia</a>
  </p>

  <p>
    <img src="https://img.shields.io/badge/License-MIT-blue.svg" alt="License MIT">
    <img src="https://img.shields.io/badge/Price-100%25%20Free-brightgreen.svg" alt="100% Gratis">
    <img src="https://img.shields.io/badge/Platform-Windows%20%7C%20Linux-orange.svg" alt="Plataformas">
    <img src="https://img.shields.io/badge/Status-Active-success.svg" alt="Estado">
  </p>

  <br>
</div>

---

## 💿 ¿Qué es RetroEmulator?

**RetroEmulator** es un launcher y gestor de catálogo retro inspirado en la interfaz y experiencia social de plataformas modernas como **Steam, Epic Games Launcher, GOG y Hydra Launcher**, pero diseñado exclusivamente para **juegos retro y consolas clásicas**.

Nuestro objetivo es brindar una experiencia completa de biblioteca digital con funciones comunitarias avanzadas, **sin pagos de ningún tipo, suscripciones premium ni publicidad**. 100% gratuito para la comunidad retro gamer.

---

## 🛠 Características Principales

<table>
  <tr>
    <td width="50%">
      <h3>🕹️ Biblioteca & Tienda Retro</h3>
      <ul>
        <li><strong>Catálogo y Tienda Retro:</strong> Descubre y organiza títulos clásicos por consola y género.</li>
        <li><strong>Boxarts & Carátulas:</strong> Visualización en alta calidad de carátulas retro y arte de caja.</li>
        <li><strong>Lista de Deseados:</strong> Guarda tus próximos retro-juegos a jugar o coleccionar.</li>
        <li><strong>Logros (Achievements):</strong> Desbloquea trofeos y logros jugando a tus títulos preferidos.</li>
      </ul>
    </td>
    <td width="50%">
      <h3>🌍 Comunidad & Social</h3>
      <ul>
        <li><strong>Perfiles Personalizables:</strong> Muestra tus estadísticas, logros y juegos favoritos.</li>
        <li><strong>Lista de Amigos & Chats:</strong> Mensajería directa, llamadas de voz y video, y compartir pantalla.</li>
        <li><strong>Publicaciones & Noticias:</strong> Entérate de las últimas novedades del gaming retro y comparte posts.</li>
        <li><strong>Reseñas por Juego:</strong> Calificaciones y opiniones de tus amigos en cada juego.</li>
      </ul>
    </td>
  </tr>
</table>

---

## 🔓 Filosofía 100% Gratis

* ❌ **Cero Funciones Premium:** Todos los usuarios tienen acceso al 100% de la plataforma.
* ❌ **Sin Anuncios ni Paywalls:** Disfruta de la interfaz sin interrupciones ni micropagos.
* ✔️ **Open Source:** Código abierto enfocado en la transparencia y mejora continua por la comunidad.

---

## ⤵ Requisitos e Instalación

### Requisitos Previos
* **Python 3.10+** (si lo ejecutas desde el código fuente)
* Dependencias descritas en `requirements.txt`

### Instalación Rápida

1. **Clona el repositorio:**
   ```bash
   git clone https://github.com/Ropro-GG/RetroEmulator.git
   cd RetroEmulator
   ```

2. **Instala las dependencias y crea tu configuración:**
   ```bash
   python -m venv .venv
   source .venv/bin/activate   # en Windows: .venv\Scripts\activate
   pip install -r requirements.txt
   cp .env.example .env        # y completa tus claves
   ```

3. **Ejecuta el launcher:**
   ```bash
   python gui_app.py
   ```

---

## 📂 Estructura

```
gui_app.py     Punto de entrada y puente entre la interfaz y Python
nucleo/        Biblioteca, nube, llamadas, GIFs, imágenes y logros
ui/            Interfaz (HTML, CSS y JavaScript)
supabase/      Registro de cambios de la base de datos
tests/         Pruebas: python -m unittest discover -s tests
```
