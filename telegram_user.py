import asyncio
from telethon import TelegramClient
from telethon.sessions import StringSession

async def get_personal_messages(api_id, api_hash, session_string, max_chats=20):
    client = TelegramClient(
        StringSession(session_string),
        api_id,
        api_hash
    )
    messages = []

    try:
        await client.connect()
        dialogs = await client.get_dialogs(limit=max_chats)

        skip_senders = ['Telegram', 'BotFather', 'Telegram Notifications']

        for dialog in dialogs:
            if dialog.is_user:
                last_message = dialog.message
                if last_message and last_message.text:
                    if dialog.name not in skip_senders:
                        messages.append({
                            'sender': dialog.name,
                            'subject': last_message.text[:50],
                            'body': last_message.text,
                            'source': 'telegram'
                        })

        await client.disconnect()

    except Exception as e:
        print(f"Telegram error: {e}")

    return messages