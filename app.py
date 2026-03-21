import streamlit as st
import anthropic
import json
import os
import base64
import asyncio
import requests
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from urllib.parse import urlencode
from telegram_user import get_personal_messages

SCOPES = 'https://www.googleapis.com/auth/gmail.readonly'

def get_client():
    return anthropic.Anthropic(api_key=st.secrets.get("ANTHROPIC_API_KEY", ""))

def get_redirect_uri():
    return st.secrets.get("REDIRECT_URI", "http://localhost:8501")

def get_auth_url():
    params = {
        'client_id': st.secrets["GOOGLE_CLIENT_ID"],
        'redirect_uri': get_redirect_uri(),
        'response_type': 'code',
        'scope': SCOPES,
        'access_type': 'offline',
        'prompt': 'consent'
    }
    return 'https://accounts.google.com/o/oauth2/auth?' + urlencode(params)

def exchange_code_for_token(code):
    response = requests.post('https://oauth2.googleapis.com/token', data={
        'client_id': st.secrets["GOOGLE_CLIENT_ID"],
        'client_secret': st.secrets["GOOGLE_CLIENT_SECRET"],
        'code': code,
        'grant_type': 'authorization_code',
        'redirect_uri': get_redirect_uri()
    })
    return response.json()

def classify_email(email):
    client = get_client()
    message = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=300,
        messages=[
            {
                "role": "user",
                "content": f"""You are a smart email assistant. Classify this email strictly.

An email is HIGH importance if ANY of these are true:
- Someone is asking you to call, meet, or respond urgently
- It contains words like: urgent, important, call me, please reply, help, emergency
- It is from a real person (not a company or automated system)
- It is about money, payments, deadlines, or appointments
- It is a direct personal message from someone you know

An email is LOW importance if ANY of these are true:
- It is from a newsletter, promotion, or marketing list
- It is an automated notification from Google, Facebook, LinkedIn etc
- It is a job alert, recruitment email, or digest
- Nobody is directly asking you to do something

Sender: {email['sender']}
Subject: {email['subject']}
Body: {email['body']}

Reply with only this JSON:
{{
  "importance": "high or medium or low",
  "category": "work or personal or spam or newsletter",
  "reason": "one sentence why"
}}"""
            }
        ]
    )
    result = message.content[0].text
    result = result.strip().replace('```json', '').replace('```', '')
    return json.loads(result)

def get_emails_from_service(service, max_results=20):
    results = service.users().messages().list(
        userId='me',
        maxResults=max_results
    ).execute()
    messages = results.get('messages', [])
    emails = []
    for msg in messages:
        txt = service.users().messages().get(
            userId='me',
            id=msg['id'],
            format='full'
        ).execute()
        payload = txt['payload']
        headers = payload.get('headers', [])
        sender = ''
        subject = ''
        for header in headers:
            if header['name'] == 'From':
                sender = header['value']
            if header['name'] == 'Subject':
                subject = header['value']
        body = ''
        if 'parts' in payload:
            for part in payload['parts']:
                if part['mimeType'] == 'text/plain':
                    data = part['body'].get('data', '')
                    if data:
                        body = base64.urlsafe_b64decode(data).decode('utf-8')
                        break
        elif 'body' in payload:
            data = payload['body'].get('data', '')
            if data:
                body = base64.urlsafe_b64decode(data).decode('utf-8')
        emails.append({
            'sender': sender,
            'subject': subject,
            'body': body[:500],
            'source': 'gmail'
        })
    return emails

def get_gmail_service(token):
    creds = Credentials(
        token=token['access_token'],
        refresh_token=token.get('refresh_token'),
        token_uri='https://oauth2.googleapis.com/token',
        client_id=st.secrets["GOOGLE_CLIENT_ID"],
        client_secret=st.secrets["GOOGLE_CLIENT_SECRET"],
        scopes=[SCOPES]
    )
    return build('gmail', 'v1', credentials=creds)

def get_initials(name):
    parts = name.replace('<', '').replace('>', '').split()
    if len(parts) >= 2:
        return (parts[0][0] + parts[1][0]).upper()
    elif len(parts) == 1:
        return parts[0][:2].upper()
    return "??"

st.set_page_config(page_title="Smart Inbox", page_icon="📬", layout="wide")

st.markdown("""
<style>
section[data-testid="stSidebar"] > div {padding-top: 1rem;}
.msg-card {
    background: var(--background-color);
    border: 0.5px solid rgba(128,128,128,0.2);
    border-radius: 12px;
    padding: 14px 16px;
    margin-bottom: 10px;
}
.msg-card:hover {border-color: rgba(128,128,128,0.45);}
.msg-top {display:flex; align-items:center; gap:10px; margin-bottom:8px;}
.avatar {
    width: 36px; height: 36px; border-radius: 50%;
    display: flex; align-items: center; justify-content: center;
    font-size: 12px; font-weight: 500; flex-shrink: 0;
}
.av-gmail {background:#E6F1FB; color:#0C447C;}
.av-telegram {background:#E1F5EE; color:#085041;}
.msg-name {font-size:14px; font-weight:500; color:var(--text-color);}
.msg-time {font-size:11px; color:rgba(128,128,128,0.7);}
.source-pill {
    font-size: 10px; padding: 2px 8px;
    border-radius: 10px; font-weight: 500;
    margin-left: auto; flex-shrink: 0;
}
.sp-gmail {background:#E6F1FB; color:#0C447C;}
.sp-telegram {background:#E1F5EE; color:#085041;}
.msg-body {font-size:13px; color:rgba(128,128,128,0.85); line-height:1.5; margin-bottom:8px;}
.msg-reason {
    font-size:11px; color:rgba(128,128,128,0.6);
    padding-top:8px; border-top:0.5px solid rgba(128,128,128,0.15);
}
.filtered-row {
    background:rgba(128,128,128,0.05);
    border:0.5px solid rgba(128,128,128,0.15);
    border-radius:8px; padding:12px;
    font-size:12px; color:rgba(128,128,128,0.6);
    text-align:center; margin-top:4px;
}
</style>
""", unsafe_allow_html=True)

if 'token' not in st.session_state:
    st.session_state.token = None
if 'important' not in st.session_state:
    st.session_state.important = []
if 'skipped' not in st.session_state:
    st.session_state.skipped = []
if 'total' not in st.session_state:
    st.session_state.total = 0
if 'view' not in st.session_state:
    st.session_state.view = 'important'

params = st.query_params
if 'code' in params and st.session_state.token is None:
    try:
        token = exchange_code_for_token(params['code'])
        if 'access_token' in token:
            st.session_state.token = token
            st.query_params.clear()
            st.rerun()
        else:
            st.error(f"Login failed: {token.get('error_description', 'Unknown error')}")
    except Exception as e:
        st.error(f"Login failed: {e}")

if st.session_state.token is None:
    col1, col2, col3 = st.columns([1, 2, 1])
    with col2:
        st.markdown("<br><br>", unsafe_allow_html=True)
        st.markdown("## 📬 Smart Inbox")
        st.markdown("Your AI assistant that filters noise and shows only what matters.")
        st.markdown("<br>", unsafe_allow_html=True)
        st.markdown("""
<div style="background:rgba(128,128,128,0.05);border:0.5px solid rgba(128,128,128,0.2);border-radius:12px;padding:20px;margin-bottom:20px">
<div style="font-size:13px;color:rgba(128,128,128,0.8);line-height:2">
✅ &nbsp; Reads your Gmail emails<br>
✅ &nbsp; Reads your Telegram messages<br>
✅ &nbsp; AI filters out spam and noise<br>
✅ &nbsp; Shows only important messages<br>
🔒 &nbsp; Your data stays private
</div>
</div>
""", unsafe_allow_html=True)
        st.link_button("🔐 Login with Google", get_auth_url(), type="primary", use_container_width=True)
        st.markdown("<br>", unsafe_allow_html=True)
        st.caption("Emails processed by Anthropic AI for classification only — not stored.")
else:
    service = get_gmail_service(st.session_state.token)

    with st.sidebar:
        initials = "SJ"
        st.markdown(f"""
<div style="text-align:center;padding-bottom:12px;border-bottom:0.5px solid rgba(128,128,128,0.2);margin-bottom:12px">
    <div style="width:52px;height:52px;border-radius:50%;background:#E6F1FB;color:#0C447C;display:flex;align-items:center;justify-content:center;font-size:15px;font-weight:500;margin:0 auto 8px">{initials}</div>
    <div style="font-size:13px;font-weight:500">Saurabh Joshi</div>
    <div style="font-size:11px;color:rgba(128,128,128,0.7);margin-top:2px">saurabhjoshi7895@gmail.com</div>
</div>
""", unsafe_allow_html=True)

        st.markdown("<div style='font-size:10px;font-weight:500;color:rgba(128,128,128,0.6);letter-spacing:0.06em;padding:0 4px;margin-bottom:6px'>CHANNELS</div>", unsafe_allow_html=True)

        st.markdown("""
<div style="display:flex;flex-direction:column;gap:2px;margin-bottom:12px">
<div style="display:flex;align-items:center;gap:8px;padding:7px 8px;border-radius:8px;background:rgba(128,128,128,0.08);font-size:13px">
    <span>📧</span><span style="flex:1">Gmail</span>
    <span style="font-size:10px;background:#E6F1FB;color:#0C447C;padding:1px 7px;border-radius:10px">✓ ON</span>
</div>
<div style="display:flex;align-items:center;gap:8px;padding:7px 8px;border-radius:8px;background:rgba(128,128,128,0.08);font-size:13px">
    <span>✈️</span><span style="flex:1">Telegram</span>
    <span style="font-size:10px;background:#E1F5EE;color:#085041;padding:1px 7px;border-radius:10px">✓ ON</span>
</div>
<div style="display:flex;align-items:center;gap:8px;padding:7px 8px;border-radius:8px;font-size:13px;color:rgba(128,128,128,0.5)">
    <span>💬</span><span style="flex:1">WhatsApp</span>
    <span style="font-size:10px;background:rgba(128,128,128,0.1);color:rgba(128,128,128,0.5);padding:1px 7px;border-radius:10px">Soon</span>
</div>
<div style="display:flex;align-items:center;gap:8px;padding:7px 8px;border-radius:8px;font-size:13px;color:rgba(128,128,128,0.5)">
    <span>💼</span><span style="flex:1">LinkedIn</span>
    <span style="font-size:10px;background:rgba(128,128,128,0.1);color:rgba(128,128,128,0.5);padding:1px 7px;border-radius:10px">Soon</span>
</div>
<div style="display:flex;align-items:center;gap:8px;padding:7px 8px;border-radius:8px;font-size:13px;color:rgba(128,128,128,0.5)">
    <span>🐦</span><span style="flex:1">Twitter</span>
    <span style="font-size:10px;background:rgba(128,128,128,0.1);color:rgba(128,128,128,0.5);padding:1px 7px;border-radius:10px">Soon</span>
</div>
</div>
""", unsafe_allow_html=True)

        st.markdown("<div style='font-size:10px;font-weight:500;color:rgba(128,128,128,0.6);letter-spacing:0.06em;padding:0 4px;margin-bottom:6px'>STATS</div>", unsafe_allow_html=True)

        col1, col2 = st.columns(2)
        with col1:
            st.metric("Total", st.session_state.total)
        with col2:
            st.metric("Important", len(st.session_state.important))

        st.markdown("<br>", unsafe_allow_html=True)

        if st.button("🔄 Fetch Messages", type="primary", use_container_width=True):
            all_messages = []
            with st.spinner("Fetching Gmail..."):
                emails = get_emails_from_service(service)
                all_messages.extend(emails)

            telegram_api_id = st.secrets.get("TELEGRAM_API_ID", "")
            telegram_api_hash = st.secrets.get("TELEGRAM_API_HASH", "")
            telegram_session = st.secrets.get("TELEGRAM_SESSION", "")

            if telegram_api_id and telegram_api_hash and telegram_session:
                with st.spinner("Fetching Telegram..."):
                    try:
                        telegram_msgs = asyncio.run(get_personal_messages(
                            int(telegram_api_id),
                            telegram_api_hash,
                            telegram_session
                        ))
                        all_messages.extend(telegram_msgs)
                    except Exception as e:
                        st.warning(f"Telegram: {e}")

            important = []
            skipped = []
            progress = st.progress(0)
            for i, msg in enumerate(all_messages):
                result = classify_email(msg)
                if result['importance'] == 'high':
                    important.append((msg, result))
                else:
                    skipped.append((msg, result))
                progress.progress((i + 1) / len(all_messages))
            progress.empty()

            st.session_state.important = important
            st.session_state.skipped = skipped
            st.session_state.total = len(all_messages)
            st.rerun()

        if st.button("🚪 Logout", use_container_width=True):
            for key in ['token', 'important', 'skipped']:
                st.session_state[key] = None if key == 'token' else []
            st.session_state.total = 0
            st.rerun()

    if not st.session_state.important and st.session_state.total == 0:
        st.markdown("## 👈 Click Fetch Messages to start")
        st.markdown("Your important messages will appear here.")
    elif not st.session_state.important:
        st.success("🎉 All clear — inbox is clean!")
    else:
        total = st.session_state.total
        imp = len(st.session_state.important)
        filtered = len(st.session_state.skipped)

        st.markdown(f"""
<div style="display:flex;align-items:center;justify-content:space-between;padding:4px 0 16px">
    <div style="font-size:18px;font-weight:500">All messages</div>
    <div style="font-size:12px;color:rgba(128,128,128,0.7)">{imp} important &nbsp;·&nbsp; {filtered} filtered out</div>
</div>
""", unsafe_allow_html=True)

        for msg, result in st.session_state.important:
            source = msg.get('source', 'gmail')
            av_class = "av-gmail" if source == 'gmail' else "av-telegram"
            sp_class = "sp-gmail" if source == 'gmail' else "sp-telegram"
            source_label = "📧 Gmail" if source == 'gmail' else "✈️ Telegram"
            initials = get_initials(msg['sender'])
            cat = result.get('category', 'personal')
            cat_icons = {"work": "💼", "personal": "👤", "spam": "🚫", "newsletter": "📰"}
            cat_icon = cat_icons.get(cat, "📌")

            st.markdown(f"""
<div class="msg-card">
    <div class="msg-top">
        <div class="avatar {av_class}">{initials[:2]}</div>
        <div style="flex:1;min-width:0">
            <div class="msg-name">{msg['sender'][:40]}</div>
        </div>
        <span class="source-pill {sp_class}">{source_label}</span>
    </div>
    <div class="msg-body"><strong>{msg['subject'] or 'No subject'}</strong><br>{msg['body'][:120]}...</div>
    <div class="msg-reason">{cat_icon} {cat.upper()} &nbsp;·&nbsp; {result['reason']}</div>
</div>
""", unsafe_allow_html=True)

            with st.expander("Show full message"):
                st.text(msg['body'])

        if st.session_state.skipped:
            st.markdown(f"""
<div class="filtered-row">
    🗑️ &nbsp; {filtered} newsletters, promotions and automated notifications were filtered out
</div>
""", unsafe_allow_html=True)
            with st.expander("See filtered messages"):
                for msg, result in st.session_state.skipped:
                    icon = "📧" if msg.get('source') == 'gmail' else "✈️"
                    st.markdown(f"- {icon} **{msg['subject'] or 'No subject'}** — {result['reason']}")