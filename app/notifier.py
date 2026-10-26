"""Push notifications (motion detected, camera turned on/off) with an optional
snapshot. Every channel configured in .env receives each notification:

- Telegram: TELEGRAM_BOT_TOKEN + TELEGRAM_CHAT_ID (Bot API, sendPhoto/sendMessage)
- ntfy:     NTFY_URL (full topic URL, e.g. https://ntfy.sh/my-secret-topic),
            optional NTFY_TOKEN (access token for protected topics)
- webhook:  WEBHOOK_URL, receives a multipart POST with a `message` field and
            an optional `file` (the snapshot). Handy to plug in your own relay.

Leave a channel's variables empty to disable it. Whether a camera notifies at
all is a per-camera checkbox on the Cameras page (stored in the DB).
"""

import asyncio
import logging
import os

import httpx

logger = logging.getLogger("camera-app.notifier")

TIMEOUT = 15

CHANNEL_LABELS = {"telegram": "Telegram", "ntfy": "ntfy", "webhook": "Webhook"}


def _env(name: str) -> str:
    return os.environ.get(name, "").strip()


def enabled_channels() -> list[str]:
    channels = []
    if _env("TELEGRAM_BOT_TOKEN") and _env("TELEGRAM_CHAT_ID"):
        channels.append("telegram")
    if _env("NTFY_URL"):
        channels.append("ntfy")
    if _env("WEBHOOK_URL"):
        channels.append("webhook")
    return channels


def _read(file_path: str | None) -> tuple[str, bytes] | None:
    if not file_path or not os.path.exists(file_path):
        return None
    with open(file_path, "rb") as f:
        return os.path.basename(file_path), f.read()


def _send_telegram(client: httpx.Client, message: str, attachment) -> httpx.Response:
    base = f"https://api.telegram.org/bot{_env('TELEGRAM_BOT_TOKEN')}"
    chat_id = _env("TELEGRAM_CHAT_ID")
    if attachment:
        return client.post(
            f"{base}/sendPhoto",
            data={"chat_id": chat_id, "caption": message},
            files={"photo": attachment},
        )
    return client.post(f"{base}/sendMessage", data={"chat_id": chat_id, "text": message})


def _send_ntfy(client: httpx.Client, message: str, attachment) -> httpx.Response:
    headers = {"Title": "Camera"}
    if _env("NTFY_TOKEN"):
        headers["Authorization"] = f"Bearer {_env('NTFY_TOKEN')}"
    if attachment:
        # With an attachment the body is the file, so the text goes in the query
        # string (headers can't carry non-ASCII text reliably).
        name, content = attachment
        return client.put(
            _env("NTFY_URL"), params={"message": message, "filename": name}, content=content, headers=headers
        )
    return client.post(_env("NTFY_URL"), content=message.encode(), headers=headers)


def _send_webhook(client: httpx.Client, message: str, attachment) -> httpx.Response:
    files = {"file": attachment} if attachment else None
    return client.post(_env("WEBHOOK_URL"), data={"message": message}, files=files)


_SENDERS = {"telegram": _send_telegram, "ntfy": _send_ntfy, "webhook": _send_webhook}


def send(channel: str, message: str, file_path: str | None = None) -> bool:
    """Sends to one channel. True if the service answered 2xx. Never raises."""
    sender = _SENDERS.get(channel)
    if sender is None or channel not in enabled_channels():
        return False
    try:
        with httpx.Client(timeout=TIMEOUT) as client:
            resp = sender(client, message, _read(file_path))
        if resp.status_code >= 300:
            logger.warning(f"{channel} notification failed: HTTP {resp.status_code}")
            return False
        return True
    except Exception as e:
        # Only the exception type: its message can contain the URL, and with it a token.
        logger.warning(f"{channel} notification failed: {type(e).__name__}")
        return False


def notify_sync(message: str, file_path: str | None = None) -> dict[str, bool]:
    """Sends to every configured channel. Used from the MQTT thread."""
    return {channel: send(channel, message, file_path) for channel in enabled_channels()}


async def notify(message: str, file_path: str | None = None) -> dict[str, bool]:
    return await asyncio.to_thread(notify_sync, message, file_path)


async def send_async(channel: str, message: str) -> bool:
    return await asyncio.to_thread(send, channel, message)
