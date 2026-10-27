"""UI strings in English and Italian. The default comes from the LANGUAGE env
var ("en" or "it", default "en"); each browser can switch with the EN/IT
selector in the top bar (cookie "lang", see main.py). Templates call
t("key", name=value) and the browser gets the same table as window.I18N
(see base.html). Texts sent outside a request (MQTT motion notifications)
use the LANGUAGE default.

To add a language: add its code to LANGUAGES and to the entries below
(missing entries fall back to English)."""

import os
from contextvars import ContextVar

LANGUAGES = ("en", "it")
FALLBACK = "en"

STRINGS: dict[str, dict[str, str]] = {
    # navigation / layout
    "app_title": {"en": "Cameras", "it": "Camere"},
    "nav_live": {"en": "Live", "it": "Live"},
    "nav_recordings": {"en": "Recordings", "it": "Registrazioni"},
    "nav_cameras": {"en": "Cameras", "it": "Telecamere"},
    "nav_stats": {"en": "Stats", "it": "Statistiche"},
    "nav_logout": {"en": "Log out", "it": "Esci"},
    "close": {"en": "Close", "it": "Chiudi"},
    "language": {"en": "Language", "it": "Lingua"},
    # motion popup
    "motion_detected": {"en": "Motion detected", "it": "Movimento rilevato"},
    "toast_camera": {"en": "Camera: {camera}", "it": "Telecamera: {camera}"},
    "see_recordings": {"en": "View recordings →", "it": "Vedi registrazioni →"},
    # login
    "sign_in": {"en": "Sign in", "it": "Accedi"},
    "username": {"en": "Username", "it": "Utente"},
    "password": {"en": "Password", "it": "Password"},
    "log_in": {"en": "Log in", "it": "Entra"},
    "invalid_credentials": {"en": "Invalid credentials", "it": "Credenziali non valide"},
    # cameras page
    "checking": {"en": "Checking…", "it": "Verifica in corso…"},
    "channel_ok": {"en": "{channel} reachable", "it": "{channel} raggiungibile"},
    "channel_error": {"en": "{channel} not reachable", "it": "{channel} non raggiungibile"},
    "no_channels": {
        "en": "No notification channel configured",
        "it": "Nessun canale di notifica configurato",
    },
    "mqtt_connected": {"en": "MQTT connected", "it": "MQTT connesso"},
    "mqtt_not_connected": {"en": "MQTT not connected", "it": "MQTT non connesso"},
    "mqtt_not_configured": {"en": "MQTT not configured", "it": "MQTT non configurato"},
    "test_channel": {"en": "Test {channel}", "it": "Test {channel}"},
    "sent_via": {"en": "Sent via {channel}", "it": "Inviata via {channel}"},
    "send_error": {"en": "Sending via {channel} failed", "it": "Errore nell'invio via {channel}"},
    "notifications": {"en": "Notifications", "it": "Notifiche"},
    "test_motion": {"en": "Test motion", "it": "Test movimento"},
    "test_motion_title": {
        "en": "Simulate a motion event over MQTT",
        "it": "Simula un evento di movimento via MQTT",
    },
    "event_published": {
        "en": "Event published, watch for the popup",
        "it": "Evento pubblicato, controlla il popup",
    },
    "mqtt_missing": {
        "en": "MQTT not connected or topic missing",
        "it": "MQTT non connesso o topic mancante",
    },
    "state_unavailable": {"en": "state unavailable", "it": "stato non disponibile"},
    "status_not_configured": {"en": "status not configured", "it": "stato non configurato"},
    "online": {"en": "online", "it": "online"},
    "offline": {"en": "offline", "it": "offline"},
    "up_for": {"en": "up {uptime}", "it": "attiva da {uptime}"},
    "days_short": {"en": "d", "it": "g"},
    "cameras_hint": {
        "en": "The ON/OFF state is read live from the camera (<code>status_url</code> in config.yml). "
        "The Notifications checkbox covers both motion alerts and on/off changes of that camera. "
        '"Test motion" publishes the configured event (<code>mqtt_topic</code>/<code>mqtt_message</code>) '
        "to MQTT: if everything is wired up, the popup appears at the top right just like for real motion.",
        "it": "Lo stato ON/OFF è letto in tempo reale dalla telecamera (<code>status_url</code> in config.yml). "
        "La casella Notifiche vale sia per i movimenti sia per l'accensione/spegnimento di questa telecamera. "
        '"Test movimento" pubblica l\'evento configurato (<code>mqtt_topic</code>/<code>mqtt_message</code>) '
        "su MQTT: se tutto è collegato, il popup compare in alto a destra come per un movimento vero.",
    },
    # recordings
    "all_cameras": {"en": "All cameras", "it": "Tutte le camere"},
    "rescan": {"en": "Rescan", "it": "Rescan"},
    "scan_started": {"en": "Scan started…", "it": "Scan avviato…"},
    "last_2_days": {"en": "Last 2 days", "it": "Ultimi 2 giorni"},
    "all_recordings": {"en": "All recordings", "it": "Tutte le registrazioni"},
    "no_recordings": {"en": "No recordings found.", "it": "Nessuna registrazione trovata."},
    "no_recordings_recent": {
        "en": "No recordings in the last 2 days.",
        "it": "Nessuna registrazione negli ultimi 2 giorni.",
    },
    "download": {"en": "Download", "it": "Scarica"},
    "prev_short": {"en": "Prev", "it": "Prec"},
    "next_short": {"en": "Next", "it": "Succ"},
    "page_of": {"en": "Page {page} of {total}", "it": "Pagina {page} di {total}"},
    "recording": {"en": "Recording", "it": "Registrazione"},
    "previous": {"en": "Previous", "it": "Precedente"},
    "next": {"en": "Next", "it": "Successiva"},
    "previous_title": {"en": "Previous (older) recording", "it": "Registrazione precedente (più vecchia)"},
    "next_title": {"en": "Next (newer) recording", "it": "Registrazione successiva (più recente)"},
    # live page
    "no_cameras": {
        "en": "No cameras configured. Edit config.yml.",
        "it": "Nessuna telecamera configurata. Modifica config.yml.",
    },
    "columns": {"en": "Columns", "it": "Colonne"},
    "auto": {"en": "Auto", "it": "Auto"},
    "reload_all": {"en": "Reload all", "it": "Ricarica tutte"},
    "esc_to_exit": {"en": "Esc to exit", "it": "Esc per uscire"},
    "reload_live": {"en": "Reload live", "it": "Ricarica live"},
    "toggle_audio": {"en": "Audio on/off", "it": "Attiva/disattiva audio"},
    "unmute": {"en": "Turn audio on", "it": "Attiva audio"},
    "mute": {"en": "Turn audio off", "it": "Disattiva audio"},
    "no_signal": {
        "en": "No signal within {seconds}s (src: {src})",
        "it": "Nessun segnale entro {seconds}s (src: {src})",
    },
    "play_blocked": {"en": "play() blocked: {error}", "it": "play() bloccato: {error}"},
    "no_response": {"en": "no response", "it": "nessuna risposta"},
    "hls_unsupported": {
        "en": "HLS is not supported by this browser",
        "it": "Formato HLS non supportato da questo browser",
    },
    "camera_off": {"en": "Camera turned off", "it": "Telecamera disattivata"},
    "camera_unreachable": {"en": "Camera not reachable", "it": "Telecamera non raggiungibile"},
    "motion_none": {"en": "Today: no motion", "it": "Oggi: nessun movimento"},
    "motion_summary": {"en": "Today: {count} {events} · last {time}", "it": "Oggi: {count} {events} · ultimo {time}"},
    "motion_one": {"en": "motion event", "it": "movimento"},
    "motion_many": {"en": "motion events", "it": "movimenti"},
    "open_clip": {"en": "Open the clip", "it": "Apri la clip"},
    # notification texts and API messages
    "notify_motion": {"en": "Motion detected: {camera}", "it": "Movimento rilevato: {camera}"},
    "notify_power": {"en": "Camera '{camera}' turned {state}", "it": "Telecamera '{camera}' impostata su {state}"},
    "notify_test": {
        "en": "Test notification from the camera dashboard ✅",
        "it": "Notifica di test dalla dashboard delle telecamere ✅",
    },
    # stats page
    "stats_title": {"en": "Motion events per hour", "it": "Eventi di movimento per ora"},
    "stats_prev_day": {"en": "Previous day", "it": "Giorno precedente"},
    "stats_next_day": {"en": "Next day", "it": "Giorno successivo"},
    "stats_today": {"en": "Today", "it": "Oggi"},
    "stats_all": {"en": "All", "it": "Tutte"},
    "stats_none": {"en": "None", "it": "Nessuna"},
    "stats_total": {"en": "{n} events", "it": "{n} eventi"},
    "stats_no_events": {"en": "No motion events on this day.", "it": "Nessun evento di movimento in questa giornata."},
    "stats_no_camera": {"en": "Select at least one camera.", "it": "Seleziona almeno una telecamera."},
    "stats_load_error": {"en": "Could not load the data.", "it": "Impossibile caricare i dati."},
    "stats_hour": {"en": "{from}:00–{to}:00", "it": "{from}:00–{to}:00"},
    "stats_history_note": {
        "en": "Motion events are kept for {days} days.",
        "it": "Gli eventi di movimento restano in archivio per {days} giorni.",
    },
    "not_found": {"en": "Not found", "it": "Non trovato"},
    "camera_not_found": {"en": "Camera not found", "it": "Telecamera non trovata"},
}


def _normalize(code: str | None) -> str | None:
    code = (code or "").strip().lower()[:2]
    return code if code in LANGUAGES else None


DEFAULT_LANGUAGE = _normalize(os.environ.get("LANGUAGE")) or FALLBACK

# Language of the request being served (set by the middleware in main.py).
_current: ContextVar[str] = ContextVar("language", default=DEFAULT_LANGUAGE)


def set_language(code: str | None) -> str:
    """Sets the language for the current request; invalid codes -> default."""
    lang = _normalize(code) or DEFAULT_LANGUAGE
    _current.set(lang)
    return lang


def current() -> str:
    return _current.get()


def t(key: str, **values) -> str:
    entry = STRINGS.get(key)
    if entry is None:
        return key
    text = entry.get(current()) or entry[FALLBACK]
    return text.format(**values) if values else text


def table() -> dict[str, str]:
    """All strings in the current language, for the browser."""
    lang = current()
    return {key: entry.get(lang) or entry[FALLBACK] for key, entry in STRINGS.items()}
