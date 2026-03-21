import streamlit as st
import anthropic
import json
import os
import base64
import requests
from telegram_inbox import get_telegram_messages
from telegram_user import get_personal_messages
import asyncio
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from urllib.parse import urlencode

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
            'body': body[:500]
        })
    return emails

def get_gmail_service(token):
    creds = Credentials(token=token['access_token'],
        refresh_token=token.get('refresh_token'),
        token_uri='https://oauth2.googleapis.com/token',
        client_id=st.secrets["GOOGLE_CLIENT_ID"],
        client_secret=st.secrets["GOOGLE_CLIENT_SECRET"],
        scopes=[SCOPES]
    )
    return build('gmail', 'v1', credentials=creds)

st.set_page_config(page_title="Smart Inbox", page_icon="📬", layout="wide")
st.title("📬 Smart Inbox")
st.caption("AI-powered inbox that shows only what matters")

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
    st.markdown("### Welcome! Please login with your Google account.")
    st.markdown("Your emails stay private — we only read them to classify importance.")
    st.divider()
    st.link_button("🔐 Login with Google", get_auth_url(), type="primary")
else:
    service = get_gmail_service(st.session_state.token)
    col1, col2, col3 = st.columns(3)

    if st.button("🔄 Fetch & Classify Messages", type="primary"):
        all_messages = []

        with st.spinner("Fetching your Gmail emails..."):
            emails = get_emails_from_service(service)
            for email in emails:
                email['source'] = 'gmail'
            all_messages.extend(emails)

        telegram_api_id = st.secrets.get("TELEGRAM_API_ID", "")
        telegram_api_hash = st.secrets.get("TELEGRAM_API_HASH", "")
        telegram_session = st.secrets.get("TELEGRAM_SESSION", "")

        if telegram_api_id and telegram_api_hash and telegram_session:
             with st.spinner("Fetching your Telegram personal chats..."):
                try:
                    telegram_msgs = asyncio.run(get_personal_messages(
                        int(telegram_api_id),
                        telegram_api_hash,
                        telegram_session
                    ))
                    all_messages.extend(telegram_msgs)
                except Exception as e:
                    st.warning(f"Telegram fetch failed: {e}")

        important = []
        skipped = []
        progress = st.progress(0)
        status = st.empty()

        for i, email in enumerate(all_messages):
            status.text(f"Classifying message {i+1} of {len(all_messages)}...")
            result = classify_email(email)
            if result['importance'] == 'high':
                important.append((email, result))
            else:
                skipped.append((email, result))
            progress.progress((i + 1) / len(all_messages))

        progress.empty()
        status.empty()

        with col1:
            st.metric("Total Fetched", len(all_messages))
        with col2:
            st.metric("Important", len(important))
        with col3:
            st.metric("Filtered Out", len(skipped))

        st.divider()

        if important:
            st.subheader("✅ Important Messages")
            for email, result in important:
                cat_colors = {
                    "work": "🔵",
                    "personal": "🟢",
                    "spam": "🔴",
                    "newsletter": "🟡"
                }
                icon = cat_colors.get(result['category'], "⚪")
                source = email.get('source', 'gmail')
                source_icon = "📧" if source == 'gmail' else "✈️"
                st.markdown(f"### {icon} {email['subject']}")
                st.markdown(f"**From:** {email['sender']} {source_icon} {source.upper()}")
                st.markdown(f"**Category:** {result['category'].upper()}")
                st.markdown(f"**Why important:** {result['reason']}")
                with st.expander("Show message body"):
                    st.text(email['body'][:500])
                st.divider()
        else:
            st.info("No important messages found!")

        if skipped:
            with st.expander(f"🗑️ See {len(skipped)} filtered out messages"):
                for email, result in skipped:
                    st.markdown(f"- **{email['subject']}** — {result['reason']}")