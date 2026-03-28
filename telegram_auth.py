import streamlit as st
from telethon import TelegramClient
from telethon.sessions import StringSession
from telethon.errors import SessionPasswordNeededError
from supabase import create_client
import threading

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
    }, on_conflict="user_email").execute()

def get_telegram_session(user_email):
    supabase = get_supabase()
    result = supabase.table("telegram_sessions").select("*").eq("user_email", user_email).execute()
    if result.data:
        return result.data[0]
    return None

def delete_telegram_session(user_email):
    supabase = get_supabase()
    supabase.table("telegram_sessions").delete().eq("user_email", user_email).execute()

def send_code_sync(phone, api_id, api_hash):
    result_data = []
    error_data = []

    def run():
        import asyncio
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        async def _do():
            client = TelegramClient(StringSession(), int(api_id), api_hash)
            await client.connect()
            result = await client.send_code_request(phone)
            session = client.session.save()
            await client.disconnect()
            return session, result.phone_code_hash
        try:
            r = loop.run_until_complete(_do())
            result_data.append(r)
        except Exception as e:
            error_data.append(e)
        finally:
            loop.close()

    t = threading.Thread(target=run)
    t.start()
    t.join(timeout=30)
    if error_data:
        raise error_data[0]
    return result_data[0]

def verify_code_sync(session_string, phone, code, phone_code_hash, api_id, api_hash, password=None):
    result_data = []
    error_data = []

    def run():
        import asyncio
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        async def _do():
            client = TelegramClient(StringSession(session_string), int(api_id), api_hash)
            await client.connect()
            try:
                if code:
                    await client.sign_in(phone=phone, code=code, phone_code_hash=phone_code_hash)
                if password:
                    await client.sign_in(password=password)
            except SessionPasswordNeededError:
                if password:
                    await client.sign_in(password=password)
                else:
                    await client.disconnect()
                    return None, "needs_password"
            
            # Verify we are actually authorized before saving
            me = await client.get_me()
            if me is None:
                await client.disconnect()
                raise Exception("Login failed - could not verify identity")
            
            final_session = client.session.save()
            await client.disconnect()
            return final_session, "success"
        try:
            r = loop.run_until_complete(_do())
            result_data.append(r)
        except Exception as e:
            error_data.append(e)
        finally:
            loop.close()

    t = threading.Thread(target=run)
    t.start()
    t.join(timeout=30)
    if error_data:
        raise error_data[0]
    return result_data[0]


def get_telegram_name_sync(session_string, api_id, api_hash):
    result = []
    error = []

    def run():
        import asyncio
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        async def _do():
            client = TelegramClient(StringSession(session_string), int(api_id), api_hash)
            await client.connect()
            me = await client.get_me()
            await client.disconnect()
            if me:
                name = f"{me.first_name or ''} {me.last_name or ''}".strip()
                return name or me.username or "Telegram User"
            return "Telegram User"
        try:
            r = loop.run_until_complete(_do())
            result.append(r)
        except Exception as e:
            error.append(e)
        finally:
            loop.close()

    t = threading.Thread(target=run)
    t.start()
    t.join(timeout=15)
    if error:
        raise error[0]
    return result[0] if result else "Telegram User"

def get_messages_for_user_sync(session_string, api_id, api_hash, max_chats=20):
    result = []
    error = []

    def run_in_thread():
        import asyncio
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        
        async def _fetch():
            client = TelegramClient(
                StringSession(session_string),
                int(api_id),
                api_hash
            )
            messages = []
            try:
                await client.connect()
                
                # Verify session is valid first
                me = await client.get_me()
                if me is None:
                    raise Exception("Session invalid - please reconnect Telegram")
                
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
                error.append(str(e))
            return messages

        try:
            msgs = loop.run_until_complete(_fetch())
            result.extend(msgs)
        finally:
            loop.close()

    t = threading.Thread(target=run_in_thread)
    t.start()
    t.join(timeout=60)
    
    if error:
        raise Exception(error[0])
    return result
