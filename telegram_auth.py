import asyncio
import streamlit as st
from telethon import TelegramClient
from telethon.sessions import StringSession
from telethon.errors import SessionPasswordNeededError
from supabase import create_client

def get_supabase():
    return create_client(
        st.secrets["SUPABASE_URL"],
        st.secrets["SUPABASE_KEY"]
    )

def save_telegram_session(user_email, session_string, phone):
    supabase = get_supabase()
    supabase.table("telegram_sessions").upsert({
        "user_email": user_email,
        "session_string": session_string,
        "phone": phone
    }).execute()

def get_telegram_session(user_email):
    supabase = get_supabase()
    result = supabase.table("telegram_sessions").select("*").eq("user_email", user_email).execute()
    if result.data:
        return result.data[0]
    return None

def delete_telegram_session(user_email):
    supabase = get_supabase()
    supabase.table("telegram_sessions").delete().eq("user_email", user_email).execute()

async def send_code(phone):
    client = TelegramClient(
        StringSession(),
        int(st.secrets["TELEGRAM_API_ID"]),
        st.secrets["TELEGRAM_API_HASH"]
    )
    await client.connect()
    result = await client.send_code_request(phone)
    session = client.session.save()
    await client.disconnect()
    return session, result.phone_code_hash

async def verify_code(session_string, phone, code, phone_code_hash, password=None):
    client = TelegramClient(
        StringSession(session_string),
        int(st.secrets["TELEGRAM_API_ID"]),
        st.secrets["TELEGRAM_API_HASH"]
    )
    await client.connect()
    try:
        await client.sign_in(phone=phone, code=code, phone_code_hash=phone_code_hash)
    except SessionPasswordNeededError:
        if password:
            await client.sign_in(password=password)
        else:
            await client.disconnect()
            return None, "needs_password"
    final_session = client.session.save()
    await client.disconnect()
    return final_session, "success"

async def get_messages_for_user(session_string, max_chats=20):
    client = TelegramClient(
        StringSession(session_string),
        int(st.secrets["TELEGRAM_API_ID"]),
        st.secrets["TELEGRAM_API_HASH"]
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