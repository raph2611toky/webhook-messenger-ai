from flask import Flask, request
from werkzeug.exceptions import HTTPException
from openai import OpenAI
from dotenv import load_dotenv
from deep_translator import GoogleTranslator
from logging.handlers import RotatingFileHandler

import os
import sys
import time
import uuid
import logging
import requests
import threading

load_dotenv()

# ============================================================
# CONFIGURATION LOGS
# ============================================================

LOG_FILE = os.getenv("LOG_FILE", "/app/logs/endpoints.log")
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()

os.makedirs(os.path.dirname(LOG_FILE), exist_ok=True)


class FrenchLevelFormatter(logging.Formatter):
    LEVEL_LABELS = {
        logging.DEBUG: "DEBUG",
        logging.INFO: "INFO",
        logging.WARNING: "INFO",
        logging.ERROR: "ERREUR",
        logging.CRITICAL: "ERREUR",
    }

    def format(self, record):
        record.level_fr = self.LEVEL_LABELS.get(record.levelno, record.levelname)
        return super().format(record)


def get_log_level(level_name: str):
    return getattr(logging, level_name, logging.INFO)


LOG_LEVEL_VALUE = get_log_level(LOG_LEVEL)

formatter = FrenchLevelFormatter(
    "%(asctime)s | [%(level_fr)s] | %(name)s | %(message)s"
)

file_handler = RotatingFileHandler(
    LOG_FILE,
    maxBytes=10 * 1024 * 1024,
    backupCount=5,
    encoding="utf-8"
)
file_handler.setFormatter(formatter)
file_handler.setLevel(LOG_LEVEL_VALUE)

console_handler = logging.StreamHandler(sys.stdout)
console_handler.setFormatter(formatter)
console_handler.setLevel(LOG_LEVEL_VALUE)

root_logger = logging.getLogger()
root_logger.handlers.clear()
root_logger.setLevel(LOG_LEVEL_VALUE)
root_logger.addHandler(file_handler)
root_logger.addHandler(console_handler)

# Harmoniser aussi les logs Gunicorn / Werkzeug
for logger_name in ["gunicorn.error", "gunicorn.access", "werkzeug"]:
    ext_logger = logging.getLogger(logger_name)
    ext_logger.handlers = root_logger.handlers
    ext_logger.setLevel(LOG_LEVEL_VALUE)
    ext_logger.propagate = False


# ============================================================
# APPLICATION FLASK
# ============================================================

app = Flask(__name__)

app.logger.handlers.clear()
app.logger.handlers = root_logger.handlers
app.logger.setLevel(LOG_LEVEL_VALUE)
app.logger.propagate = False


@app.before_request
def log_request():
    request.start_time = time.time()
    request.request_id = str(uuid.uuid4())[:8]

    ip = request.headers.get("X-Forwarded-For", request.remote_addr)
    user_agent = request.headers.get("User-Agent", "-")

    app.logger.info(
        f"REQ {request.request_id} | {request.method} {request.path} | "
        f"ip={ip} | ua={user_agent}"
    )

    app.logger.debug(
        f"REQ_DEBUG {request.request_id} | content_type={request.content_type} | "
        f"content_length={request.content_length}"
    )


@app.after_request
def log_response(response):
    start_time = getattr(request, "start_time", time.time())
    request_id = getattr(request, "request_id", "unknown")

    duration_ms = round((time.time() - start_time) * 1000, 2)

    app.logger.info(
        f"RES {request_id} | {request.method} {request.path} | "
        f"status={response.status_code} | duration={duration_ms}ms"
    )

    return response


@app.errorhandler(Exception)
def log_exception(error):
    if isinstance(error, HTTPException):
        app.logger.info(
            f"HTTP_EXCEPTION | {request.method} {request.path} | "
            f"status={error.code} | message={error.description}"
        )
        return {"error": error.description}, error.code

    app.logger.exception(
        f"ERR | {request.method} {request.path} | {str(error)}"
    )
    return {"error": "Erreur interne du serveur"}, 500


# ============================================================
# VARIABLES ENV
# ============================================================

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
VERIFY_TOKEN = os.getenv("VERIFY_TOKEN")
PAGE_ACCESS_TOKEN = os.getenv("PAGE_ACCESS_TOKEN")
GRAPH_VERSION = os.getenv("GRAPH_VERSION", "v25.0")

if not GEMINI_API_KEY:
    app.logger.error("GEMINI_API_KEY manquant dans les variables d'environnement.")

if not VERIFY_TOKEN:
    app.logger.error("VERIFY_TOKEN manquant dans les variables d'environnement.")

if not PAGE_ACCESS_TOKEN:
    app.logger.error("PAGE_ACCESS_TOKEN manquant dans les variables d'environnement.")

client = OpenAI(
    api_key=GEMINI_API_KEY,
    base_url="https://generativelanguage.googleapis.com/v1beta/openai/"
)


# ============================================================
# PROMPTS IA
# ============================================================

CHAT_CONTENT = {
    "FR": (
        "Tu es un assistant exceptionnel appelé Sexual AI, spécialisé dans la santé sexuelle. "
        "Tu es basé à Madagascar et tu connais toutes les provinces, régions, districts et villes du pays. "
        "Tu fournis des informations claires, éducatives et responsables sur la santé sexuelle : causes, "
        "symptômes, prévention, options de traitement et conseils pratiques. "
        "Tu ne remplaces pas un médecin. Quand il y a douleur forte, saignement, fièvre, grossesse, infection suspectée, "
        "violence sexuelle, rapport non protégé récent, ou situation urgente, tu recommandes de contacter rapidement "
        "un médecin, un hôpital ou le CSB le plus proche."
    ),
    "EN": (
        "You are an exceptional assistant called Sexual AI, specialized in sexual health. "
        "You are based in Madagascar and know the provinces, regions, districts, and cities of the country. "
        "You provide clear, educational, and responsible sexual health information. "
        "You do not replace a doctor. For urgent or risky symptoms, advise the user to contact a doctor, "
        "hospital, or nearest CSB."
    ),
    "MG": (
        "Ianao dia mpanampy antsoina hoe Sexual AI, manampahaizana amin'ny fahasalamana ara-pananahana. "
        "Manome fampahalalana mazava sy tompon'andraikitra ianao, ary manoro hevitra ny olona hijery dokotera "
        "na CSB akaiky raha misy soritr'aretina mampiahiahy na maika."
    )
}


# ============================================================
# OUTILS
# ============================================================

def mask_id(value: str) -> str:
    if not value:
        return "unknown"
    value = str(value)
    if len(value) <= 4:
        return "****"
    return f"***{value[-4:]}"


def traduire_texte(texte, source_lang="fr", cible_lang="mg"):
    try:
        app.logger.debug(
            f"Traduction demandée | source={source_lang} | cible={cible_lang} | "
            f"length={len(texte) if texte else 0}"
        )

        traduction = GoogleTranslator(
            source=source_lang.lower(),
            target=cible_lang.lower()
        ).translate(texte)

        app.logger.info(
            f"Traduction réussie | source={source_lang} | cible={cible_lang}"
        )

        return traduction

    except Exception as e:
        app.logger.exception(
            f"Erreur traduction | source={source_lang} | cible={cible_lang} | erreur={str(e)}"
        )
        return texte


def detect_lang(text: str) -> str:
    text_lower = text.lower()

    mots_mg = [
        "aho", "ianao", "manao", "inona", "firy", "marary",
        "fahasalamana", "aretina", "misaotra", "azafady",
        "ve", "tsy", "eny", "tsia"
    ]

    if any(mot in text_lower.split() for mot in mots_mg):
        app.logger.debug("Langue détectée: MG")
        return "MG"

    app.logger.debug("Langue détectée: FR")
    return "FR"


def split_text(text, max_len=1900):
    chunks = []
    current = ""

    for paragraph in text.split("\n"):
        if len(current) + len(paragraph) + 1 <= max_len:
            current += paragraph + "\n"
        else:
            if current.strip():
                chunks.append(current.strip())
            current = paragraph + "\n"

    if current.strip():
        chunks.append(current.strip())

    app.logger.debug(
        f"Split texte | taille_originale={len(text)} | nombre_chunks={len(chunks)}"
    )

    return chunks


# ============================================================
# IA
# ============================================================

def simple_chat(message: str, lang="FR") -> str:
    if not message:
        app.logger.info("Message vide reçu dans simple_chat.")
        return "Message requis."

    lang = lang.upper()
    original_lang = lang
    message_for_ai = message

    app.logger.info(
        f"Demande IA reçue | lang={lang} | message_length={len(message)}"
    )

    app.logger.debug(
        f"Message utilisateur DEBUG | lang={lang} | message={message}"
    )

    if lang == "MG":
        app.logger.info("Traduction MG -> FR avant appel IA.")
        message_for_ai = traduire_texte(message, source_lang="mg", cible_lang="fr")
        system_prompt = CHAT_CONTENT["FR"]
    elif lang == "EN":
        system_prompt = CHAT_CONTENT["EN"]
    else:
        system_prompt = CHAT_CONTENT["FR"]

    try:
        app.logger.debug("Appel Gemini démarré.")

        response = client.chat.completions.create(
            model="gemini-2.5-flash",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": message_for_ai}
            ],
            temperature=0.5
        )

        reponse_chat = response.choices[0].message.content

        if original_lang == "MG":
            app.logger.info("Traduction FR -> MG après réponse IA.")
            reponse_chat = traduire_texte(reponse_chat, source_lang="fr", cible_lang="mg")

        app.logger.info(
            f"Génération IA réussie | lang={original_lang} | response_length={len(reponse_chat)}"
        )

        app.logger.debug(
            f"Réponse IA DEBUG | lang={original_lang} | response={reponse_chat}"
        )

        return reponse_chat

    except Exception as e:
        app.logger.exception(
            f"Erreur lors de la communication avec l'IA | erreur={str(e)}"
        )
        return "Désolé, le service IA est temporairement indisponible."


# ============================================================
# ROUTES
# ============================================================

@app.route("/", methods=["GET"])
def home():
    app.logger.info("Health check appelé.")
    return {
        "status": "ok",
        "service": "Sexual AI Messenger Webhook"
    }


@app.route("/chat", methods=["POST"])
def chat_test():
    data = request.get_json(silent=True) or {}

    message = data.get("message", "")
    lang = data.get("lang") or detect_lang(message)

    app.logger.info(
        f"Endpoint /chat appelé | lang={lang} | message_length={len(message)}"
    )

    reply = simple_chat(message, lang)

    return {
        "reply": reply,
        "lang": lang
    }


@app.route("/webhook", methods=["GET"])
def verify_webhook():
    mode = request.args.get("hub.mode")
    token = request.args.get("hub.verify_token")
    challenge = request.args.get("hub.challenge")

    app.logger.info(
        f"Vérification webhook Meta reçue | mode={mode}"
    )

    if mode == "subscribe" and token == VERIFY_TOKEN:
        app.logger.info("Webhook vérifié par Meta avec succès.")
        return challenge, 200

    app.logger.error("Vérification webhook refusée: verify_token invalide.")
    return "Forbidden", 403


@app.route("/webhook", methods=["POST"])
def receive_webhook():
    data = request.get_json(silent=True) or {}

    app.logger.info(
        f"Webhook POST reçu | object={data.get('object')}"
    )

    app.logger.debug(
        f"Webhook payload DEBUG | data={data}"
    )

    if data.get("object") != "page":
        app.logger.info("Webhook ignoré: object différent de page.")
        return "Not found", 404

    threading.Thread(
        target=process_webhook_event,
        args=(data,),
        daemon=True
    ).start()

    app.logger.info("Webhook accepté, traitement lancé dans un thread.")
    return "EVENT_RECEIVED", 200


# ============================================================
# TRAITEMENT MESSENGER
# ============================================================

def process_webhook_event(data):
    try:
        entries = data.get("entry", [])
        app.logger.info(f"Traitement webhook démarré | entries={len(entries)}")

        for entry in entries:
            messaging_events = entry.get("messaging", [])
            app.logger.debug(
                f"Entry webhook | messaging_events={len(messaging_events)}"
            )

            for messaging_event in messaging_events:
                handle_messenger_event(messaging_event)

        app.logger.info("Traitement webhook terminé.")

    except Exception as e:
        app.logger.exception(
            f"Erreur process_webhook_event | erreur={str(e)}"
        )


def handle_messenger_event(event):
    sender_id = event.get("sender", {}).get("id")

    if not sender_id:
        app.logger.debug("Événement Messenger ignoré: sender_id absent.")
        return

    sender_masked = mask_id(sender_id)

    message_data = event.get("message")

    if not message_data:
        app.logger.debug(
            f"Événement Messenger ignoré: message absent | sender={sender_masked}"
        )
        return

    if message_data.get("is_echo"):
        app.logger.debug(
            f"Message echo ignoré | sender={sender_masked}"
        )
        return

    user_text = message_data.get("text")

    if not user_text:
        app.logger.info(
            f"Message non textuel reçu | sender={sender_masked}"
        )

        send_messenger_message(
            sender_id,
            "Désolé, je peux répondre aux messages texte pour le moment."
        )
        return

    app.logger.info(
        f"Message texte reçu | sender={sender_masked} | message_length={len(user_text)}"
    )

    app.logger.debug(
        f"Message Messenger DEBUG | sender={sender_masked} | text={user_text}"
    )

    lang = detect_lang(user_text)
    ai_reply = simple_chat(user_text, lang)

    if len(ai_reply) > 1900:
        chunks = split_text(ai_reply, 1900)

        app.logger.info(
            f"Réponse longue détectée | sender={sender_masked} | chunks={len(chunks)}"
        )

        for index, chunk in enumerate(chunks, start=1):
            app.logger.debug(
                f"Envoi chunk Messenger | sender={sender_masked} | chunk={index}/{len(chunks)}"
            )
            send_messenger_message(sender_id, chunk)
    else:
        send_messenger_message(sender_id, ai_reply)


def send_messenger_message(recipient_id, text):
    if not PAGE_ACCESS_TOKEN:
        app.logger.error("PAGE_ACCESS_TOKEN manquant. Impossible d'envoyer le message Messenger.")
        return

    recipient_masked = mask_id(recipient_id)

    url = f"https://graph.facebook.com/{GRAPH_VERSION}/me/messages"

    payload = {
        "recipient": {
            "id": recipient_id
        },
        "message": {
            "text": text
        }
    }

    params = {
        "access_token": PAGE_ACCESS_TOKEN
    }

    try:
        app.logger.info(
            f"Envoi Messenger démarré | recipient={recipient_masked} | text_length={len(text)}"
        )

        app.logger.debug(
            f"Payload Messenger DEBUG | recipient={recipient_masked} | payload_message={payload['message']}"
        )

        response = requests.post(
            url,
            json=payload,
            params=params,
            timeout=15
        )

        if response.status_code >= 400:
            app.logger.error(
                f"Erreur Messenger API | recipient={recipient_masked} | "
                f"status={response.status_code} | response={response.text}"
            )
        else:
            app.logger.info(
                f"Réponse Messenger envoyée | recipient={recipient_masked} | "
                f"status={response.status_code}"
            )

    except Exception as e:
        app.logger.exception(
            f"Erreur send_messenger_message | recipient={recipient_masked} | erreur={str(e)}"
        )


# ============================================================
# MAIN LOCAL
# ============================================================

if __name__ == "__main__":
    port = int(os.getenv("PORT", 5487))

    app.logger.info(
        f"Démarrage Flask local | host=0.0.0.0 | port={port} | log_file={LOG_FILE}"
    )

    app.run(host="0.0.0.0", port=port, debug=False)