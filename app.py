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

st.set_page_config(page_title="Smart Inbox", page_icon="📬", layout="wide")

st.markdown("""
<style>
.gmail-card {
    background: #1a1a2e;
    border-left: 4px solid #4285F4;
    border-radius: 8px;
    padding: 16px;
    margin: 8px 0;
}
.telegram-card {
    background: #1a1a2e;
    border-left: 4px solid #229ED9;
    border-radius: 8px;
    padding: 16px;
    margin: 8px 0;
}
.source-badge-gmail {
    background: #4285F4;
    color: white;
    padding: 2px 10px;
    border-radius: 12px;
    font-size: 12px;
    font-weight: bold;
}
.source-badge-telegram {
    background: #229ED9;
    color: white;
    padding: 2px 10px;
    border-radius: 12px;
    font-size: 12px;
    font-weight: bold;
}
.category-badge {
    background: #2d2d2d;
    color: #aaa;
    padding: 2px 10px;
    border-radius: 12px;
    font-size: 12px;
}
</style>
""", unsafe_allow_html=True)

st.title("📬 Smart Inbox")
st.caption("AI-powered inbox — only what matters")

if 'token' not in st.session_state:
    st.session_state.token = None

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
    st.markdown("---")
    col1, col2, col3 = st.columns([1,2,1])
    with col2:
        st.markdown("### 👋 Welcome to Smart Inbox")
        st.markdown("Your AI assistant that reads Gmail and Telegram and shows only what matters.")
        st.markdown("")
        st.markdown("**What it does:**")
        st.markdown("- Fetches your Gmail emails")
        st.markdown("- Fetches your Telegram messages")
        st.markdown("- AI classifies every message")
        st.markdown("- Shows only important ones")
        st.markdown("")
        st.link_button("🔐 Login with Google to get started", get_auth_url(), type="primary", use_container_width=True)
        st.markdown("")
        st.caption("🔒 Your emails stay private — processed by Anthropic AI for classification only")
else:
    service = get_gmail_service(st.session_state.token)

    with st.sidebar:
        st.markdown("### 📬 Smart Inbox")
        st.markdown("---")

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

        if 'important' in st.session_state:
            st.markdown("---")
            st.metric("Total fetched", st.session_state.total)
            st.metric("Important", len(st.session_state.important))
            st.metric("Filtered out", len(st.session_state.skipped))
            st.markdown("---")

            gmail_count = sum(1 for msg, _ in st.session_state.important if msg.get('source') == 'gmail')
            telegram_count = sum(1 for msg, _ in st.session_state.important if msg.get('source') == 'telegram')

            st.markdown(f"📧 **Gmail:** {gmail_count} important")
            st.markdown(f"✈️ **Telegram:** {telegram_count} important")
            st.markdown("---")

        if st.button("🚪 Logout", use_container_width=True):
            st.session_state.token = None
            st.rerun()

    if 'important' not in st.session_state:
        st.markdown("### 👈 Click Fetch Messages to get started")
        st.markdown("Your inbox will appear here after fetching.")
    elif len(st.session_state.important) == 0:
        st.success("🎉 No important messages right now — your inbox is clean!")
    else:
        st.markdown(f"### ✅ {len(st.session_state.important)} Important Messages")
        st.markdown("---")

        for msg, result in st.session_state.important:
            source = msg.get('source', 'gmail')

            if source == 'gmail':
                badge = '<span class="source-badge-gmail">📧 Gmail</span>'
                card_class = 'gmail-card'
            else:
                badge = '<span class="source-badge-telegram">✈️ Telegram</span>'
                card_class = 'telegram-card'

            cat_icons = {
                "work": "💼",
                "personal": "👤",
                "spam": "🚫",
                "newsletter": "📰"
            }
            cat_icon = cat_icons.get(result['category'], "📌")

            st.markdown(f"""
<div class="{card_class}">
    <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:8px">
        <div>{badge} &nbsp; <span class="category-badge">{cat_icon} {result['category'].upper()}</span></div>
    </div>
    <div style="font-size:16px; font-weight:600; margin-bottom:4px">{msg['subject']}</div>
    <div style="color:#888; font-size:13px; margin-bottom:8px">From: {msg['sender']}</div>
    <div style="color:#aaa; font-size:13px; border-top:1px solid #333; padding-top:8px">{result['reason']}</div>
</div>
""", unsafe_allow_html=True)

            with st.expander("Show full message"):
                st.text(msg['body'][:500])

        if st.session_state.skipped:
            st.markdown("---")
            with st.expander(f"🗑️ {len(st.session_state.skipped)} filtered out messages"):
                for msg, result in st.session_state.skipped:
                    source = msg.get('source', 'gmail')
                    source_icon = "📧" if source == 'gmail' else "✈️"
                    st.markdown(f"- {source_icon} **{msg['subject']}** — {result['reason']}")