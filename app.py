from flask import Flask, request
from openai import OpenAI
from dotenv import load_dotenv
from deep_translator import GoogleTranslator
import os
import traceback
import requests
import threading

load_dotenv()

app = Flask(__name__)

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
VERIFY_TOKEN = os.getenv("VERIFY_TOKEN")
PAGE_ACCESS_TOKEN = os.getenv("PAGE_ACCESS_TOKEN")
GRAPH_VERSION = os.getenv("GRAPH_VERSION", "v25.0")

client = OpenAI(
    api_key=GEMINI_API_KEY,
    base_url="https://generativelanguage.googleapis.com/v1beta/openai/"
)

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


def traduire_texte(texte, source_lang="fr", cible_lang="mg"):
    try:
        return GoogleTranslator(
            source=source_lang.lower(),
            target=cible_lang.lower()
        ).translate(texte)
    except Exception as e:
        print("Erreur traduction:", e)
        return texte


def detect_lang(text: str) -> str:
    """
    Détection simple.
    Tu peux améliorer plus tard avec langdetect.
    """
    text_lower = text.lower()

    mots_mg = [
        "aho", "ianao", "manao", "inona", "firy", "marary",
        "fahasalamana", "aretina", "misaotra", "azafady",
        "ve", "tsy", "eny", "tsia"
    ]

    if any(mot in text_lower.split() for mot in mots_mg):
        return "MG"

    return "FR"


def simple_chat(message: str, lang="FR") -> str:
    if not message:
        return "Message requis."

    lang = lang.upper()

    original_lang = lang
    message_for_ai = message

    if lang == "MG":
        message_for_ai = traduire_texte(message, source_lang="mg", cible_lang="fr")
        system_prompt = CHAT_CONTENT["FR"]
    elif lang == "EN":
        system_prompt = CHAT_CONTENT["EN"]
    else:
        system_prompt = CHAT_CONTENT["FR"]

    try:
        response = client.chat.completions.create(
            model="gemini-2.0-flash",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": message_for_ai}
            ],
            temperature=0.5
        )

        reponse_chat = response.choices[0].message.content

        if original_lang == "MG":
            reponse_chat = traduire_texte(reponse_chat, source_lang="fr", cible_lang="mg")

        print("✔ Génération IA réussie.")
        return reponse_chat

    except Exception as e:
        print(traceback.format_exc())
        return "Désolé, le service IA est temporairement indisponible."


@app.route("/", methods=["GET"])
def home():
    return {
        "status": "ok",
        "service": "Sexual AI Messenger Webhook"
    }


@app.route("/chat", methods=["POST"])
def chat_test():
    """
    Endpoint local pour tester ton IA sans Facebook.
    Exemple:
    curl -X POST http://localhost:5000/chat \
      -H "Content-Type: application/json" \
      -d '{"message":"Bonjour","lang":"FR"}'
    """
    data = request.get_json(silent=True) or {}
    message = data.get("message", "")
    lang = data.get("lang") or detect_lang(message)

    reply = simple_chat(message, lang)

    return {
        "reply": reply,
        "lang": lang
    }


@app.route("/webhook", methods=["GET"])
def verify_webhook():
    """
    Vérification du webhook par Meta.
    Meta va appeler:
    GET /webhook?hub.mode=subscribe&hub.verify_token=...&hub.challenge=...
    """
    mode = request.args.get("hub.mode")
    token = request.args.get("hub.verify_token")
    challenge = request.args.get("hub.challenge")

    if mode == "subscribe" and token == VERIFY_TOKEN:
        print("✔ Webhook vérifié par Meta.")
        return challenge, 200

    print("❌ Vérification webhook refusée.")
    return "Forbidden", 403


@app.route("/webhook", methods=["POST"])
def receive_webhook():
    """
    Réception des messages Messenger.
    On répond vite 200 à Meta, puis on traite le message dans un thread.
    """
    data = request.get_json(silent=True) or {}

    if data.get("object") != "page":
        return "Not found", 404

    threading.Thread(target=process_webhook_event, args=(data,)).start()

    return "EVENT_RECEIVED", 200


def process_webhook_event(data):
    try:
        for entry in data.get("entry", []):
            for messaging_event in entry.get("messaging", []):
                handle_messenger_event(messaging_event)
    except Exception:
        print("Erreur process_webhook_event:")
        print(traceback.format_exc())


def handle_messenger_event(event):
    sender_id = event.get("sender", {}).get("id")

    if not sender_id:
        return

    message_data = event.get("message")

    if not message_data:
        return

    if message_data.get("is_echo"):
        return

    user_text = message_data.get("text")

    if not user_text:
        send_messenger_message(
            sender_id,
            "Désolé, je peux répondre aux messages texte pour le moment."
        )
        return

    print(f"Message reçu de {sender_id}: {user_text}")

    lang = detect_lang(user_text)
    ai_reply = simple_chat(user_text, lang)

    if len(ai_reply) > 1900:
        chunks = split_text(ai_reply, 1900)
        for chunk in chunks:
            send_messenger_message(sender_id, chunk)
    else:
        send_messenger_message(sender_id, ai_reply)


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

    return chunks


def send_messenger_message(recipient_id, text):
    """
    Envoie une réponse à l'utilisateur via Messenger Send API.
    """
    if not PAGE_ACCESS_TOKEN:
        print("❌ PAGE_ACCESS_TOKEN manquant.")
        return

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
        response = requests.post(url, json=payload, params=params, timeout=15)

        if response.status_code >= 400:
            print("❌ Erreur Messenger API:")
            print(response.status_code)
            print(response.text)
        else:
            print("✔ Réponse Messenger envoyée.")

    except Exception:
        print("Erreur send_messenger_message:")
        print(traceback.format_exc())


if __name__ == "__main__":
    port = int(os.getenv("PORT", 5487))
    app.run(host="0.0.0.0", port=port, debug=True)