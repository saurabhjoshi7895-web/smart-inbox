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
    clean = name.split('<')[0].strip()
    parts = clean.split()
    if len(parts) >= 2:
        return (parts[0][0] + parts[1][0]).upper()
    elif len(parts) == 1 and len(parts[0]) >= 2:
        return parts[0][:2].upper()
    return "??"

def avatar_color(source):
    colors = {
        'gmail': ('#EA4335', '#fff'),
        'telegram': ('#229ED9', '#fff'),
    }
    return colors.get(source, ('#6B7280', '#fff'))

st.set_page_config(page_title="Smart Inbox", page_icon="📬", layout="wide")

st.markdown("""
<style>
section[data-testid="stSidebar"] > div {padding-top: 1rem;}
.msg-card {
    border: 1px solid rgba(128,128,128,0.15);
    border-radius: 14px;
    padding: 16px 18px;
    margin-bottom: 12px;
    transition: border-color 0.15s;
}
.msg-card:hover {border-color: rgba(128,128,128,0.35);}
.msg-header {display:flex; align-items:center; gap:12px; margin-bottom:10px;}
.av {width:38px;height:38px;border-radius:50%;display:inline-flex;align-items:center;justify-content:center;font-size:13px;font-weight:600;flex-shrink:0;}
.av-gmail {background:#EA4335;color:#fff;}
.av-telegram {background:#229ED9;color:#fff;}
.sender-name {font-size:14px;font-weight:500;flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;}
.src-badge {display:inline-flex;align-items:center;gap:4px;font-size:11px;font-weight:500;padding:3px 10px;border-radius:20px;flex-shrink:0;}
.sb-gmail {background:#FDECEA;color:#C0392B;}
.sb-telegram {background:#E3F2FD;color:#0D6EAA;}
.msg-subject {font-size:15px;font-weight:600;margin-bottom:4px;line-height:1.4;}
.msg-preview {font-size:13px;color:rgba(128,128,128,0.85);line-height:1.6;margin-bottom:10px;}
.msg-footer {display:flex;align-items:center;gap:6px;padding-top:8px;border-top:1px solid rgba(128,128,128,0.1);font-size:12px;color:rgba(128,128,128,0.6);}
.cat-badge {font-size:11px;font-weight:500;padding:2px 9px;border-radius:12px;}
.cb-work {background:#EDE7F6;color:#512DA8;}
.cb-personal {background:#E8F5E9;color:#2E7D32;}
.cb-spam {background:#FFEBEE;color:#C62828;}
.cb-newsletter {background:#FFF8E1;color:#F57F17;}
.filtered-box {background:rgba(128,128,128,0.04);border:1px dashed rgba(128,128,128,0.2);border-radius:10px;padding:14px;font-size:13px;color:rgba(128,128,128,0.6);text-align:center;margin-top:8px;}
.page-header {display:flex;align-items:center;justify-content:space-between;margin-bottom:20px;}
.page-title {font-size:20px;font-weight:600;}
.page-sub {font-size:13px;color:rgba(128,128,128,0.6);}
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
if 'show_gmail' not in st.session_state:
    st.session_state.show_gmail = True
if 'show_telegram' not in st.session_state:
    st.session_state.show_telegram = True

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
        st.markdown("""
<div style="text-align:center;margin-bottom:24px">
    <div style="font-size:40px;margin-bottom:8px">📬</div>
    <div style="font-size:26px;font-weight:700;margin-bottom:6px">Smart Inbox</div>
    <div style="font-size:15px;color:rgba(128,128,128,0.7)">AI-powered inbox — only what matters</div>
</div>
""", unsafe_allow_html=True)

        st.markdown("""
<div style="background:rgba(128,128,128,0.04);border:1px solid rgba(128,128,128,0.15);border-radius:14px;padding:22px;margin-bottom:22px">
<div style="display:flex;flex-direction:column;gap:10px">
    <div style="display:flex;align-items:center;gap:10px;font-size:14px">
        <span style="width:28px;height:28px;background:#FDECEA;border-radius:8px;display:inline-flex;align-items:center;justify-content:center;font-size:15px">📧</span>
        <span>Reads your <strong>Gmail</strong> emails</span>
    </div>
    <div style="display:flex;align-items:center;gap:10px;font-size:14px">
        <span style="width:28px;height:28px;background:#E3F2FD;border-radius:8px;display:inline-flex;align-items:center;justify-content:center;font-size:15px">✈️</span>
        <span>Reads your <strong>Telegram</strong> messages</span>
    </div>
    <div style="display:flex;align-items:center;gap:10px;font-size:14px">
        <span style="width:28px;height:28px;background:#E8F5E9;border-radius:8px;display:inline-flex;align-items:center;justify-content:center;font-size:15px">🤖</span>
        <span><strong>AI filters</strong> spam and noise automatically</span>
    </div>
    <div style="display:flex;align-items:center;gap:10px;font-size:14px">
        <span style="width:28px;height:28px;background:#F3E5F5;border-radius:8px;display:inline-flex;align-items:center;justify-content:center;font-size:15px">🔒</span>
        <span>Your data stays <strong>private</strong></span>
    </div>
</div>
</div>
""", unsafe_allow_html=True)
        st.link_button("🔐 Continue with Google", get_auth_url(), type="primary", use_container_width=True)
        st.markdown("<br>", unsafe_allow_html=True)
        st.caption("Emails are processed by Anthropic AI for classification only and are never stored.")

else:
    service = get_gmail_service(st.session_state.token)

    with st.sidebar:
        st.markdown("""
<div style="text-align:center;padding-bottom:14px;border-bottom:1px solid rgba(128,128,128,0.15);margin-bottom:14px">
    <div style="width:54px;height:54px;border-radius:50%;background:linear-gradient(135deg,#EA4335,#FBBC04);color:#fff;display:flex;align-items:center;justify-content:center;font-size:18px;font-weight:700;margin:0 auto 8px">SJ</div>
    <div style="font-size:14px;font-weight:600">Saurabh Joshi</div>
    <div style="font-size:11px;color:rgba(128,128,128,0.6);margin-top:2px">saurabhjoshi7895@gmail.com</div>
</div>
""", unsafe_allow_html=True)

        st.markdown("<div style='font-size:10px;font-weight:600;color:rgba(128,128,128,0.5);letter-spacing:0.08em;margin-bottom:8px'>CHANNELS</div>", unsafe_allow_html=True)

        show_gmail = st.checkbox("Gmail", value=st.session_state.show_gmail, key="cb_gmail")
        show_telegram = st.checkbox("Telegram", value=st.session_state.show_telegram, key="cb_telegram")

        st.markdown("""
<div style="display:flex;flex-direction:column;gap:2px;margin:4px 0 14px;opacity:0.4">
    <div style="display:flex;align-items:center;gap:8px;padding:6px 4px;font-size:13px">
        <span>💬</span><span style="flex:1">WhatsApp</span>
        <span style="font-size:10px;background:rgba(128,128,128,0.1);padding:1px 8px;border-radius:10px">Soon</span>
    </div>
    <div style="display:flex;align-items:center;gap:8px;padding:6px 4px;font-size:13px">
        <span>💼</span><span style="flex:1">LinkedIn</span>
        <span style="font-size:10px;background:rgba(128,128,128,0.1);padding:1px 8px;border-radius:10px">Soon</span>
    </div>
    <div style="display:flex;align-items:center;gap:8px;padding:6px 4px;font-size:13px">
        <span>🐦</span><span style="flex:1">Twitter / X</span>
        <span style="font-size:10px;background:rgba(128,128,128,0.1);padding:1px 8px;border-radius:10px">Soon</span>
    </div>
</div>
""", unsafe_allow_html=True)

        st.markdown("<div style='font-size:10px;font-weight:600;color:rgba(128,128,128,0.5);letter-spacing:0.08em;margin-bottom:8px'>STATS</div>", unsafe_allow_html=True)

        c1, c2 = st.columns(2)
        with c1:
            st.metric("Total", st.session_state.total)
            st.metric("Filtered", len(st.session_state.skipped))
        with c2:
            st.metric("Important", len(st.session_state.important))
            gmail_c = sum(1 for m, _ in st.session_state.important if m.get('source') == 'gmail')
            st.metric("Gmail", gmail_c)

        st.markdown("<br>", unsafe_allow_html=True)

        if st.button("🔄 Fetch Messages", type="primary", use_container_width=True):
            all_messages = []

            if show_gmail:
                with st.spinner("Fetching Gmail..."):
                    emails = get_emails_from_service(service)
                    all_messages.extend(emails)

            t_id = st.secrets.get("TELEGRAM_API_ID", "")
            t_hash = st.secrets.get("TELEGRAM_API_HASH", "")
            t_session = st.secrets.get("TELEGRAM_SESSION", "")

            if show_telegram and t_id and t_hash and t_session:
                with st.spinner("Fetching Telegram..."):
                    try:
                        tmsgs = asyncio.run(get_personal_messages(int(t_id), t_hash, t_session))
                        all_messages.extend(tmsgs)
                    except Exception as e:
                        st.warning(f"Telegram: {e}")

            if all_messages:
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

        st.markdown("<br>", unsafe_allow_html=True)
        if st.button("🚪 Logout", use_container_width=True):
            st.session_state.token = None
            st.session_state.important = []
            st.session_state.skipped = []
            st.session_state.total = 0
            st.rerun()

    if not st.session_state.important and st.session_state.total == 0:
        st.markdown("""
<div style="text-align:center;padding:60px 0">
    <div style="font-size:48px;margin-bottom:16px">📬</div>
    <div style="font-size:20px;font-weight:600;margin-bottom:8px">Your inbox is ready</div>
    <div style="font-size:14px;color:rgba(128,128,128,0.6)">Click Fetch Messages in the sidebar to get started</div>
</div>
""", unsafe_allow_html=True)

    elif not st.session_state.important:
        st.markdown("""
<div style="text-align:center;padding:60px 0">
    <div style="font-size:48px;margin-bottom:16px">🎉</div>
    <div style="font-size:20px;font-weight:600;margin-bottom:8px">All clear!</div>
    <div style="font-size:14px;color:rgba(128,128,128,0.6)">No important messages right now</div>
</div>
""", unsafe_allow_html=True)

    else:
        imp = len(st.session_state.important)
        filtered = len(st.session_state.skipped)
        gmail_count = sum(1 for m, _ in st.session_state.important if m.get('source') == 'gmail')
        tg_count = sum(1 for m, _ in st.session_state.important if m.get('source') == 'telegram')

        st.markdown(f"""
<div class="page-header">
    <div>
        <div class="page-title">📬 All messages</div>
        <div class="page-sub">{imp} important &nbsp;·&nbsp; {filtered} filtered out &nbsp;·&nbsp; 📧 {gmail_count} Gmail &nbsp;·&nbsp; ✈️ {tg_count} Telegram</div>
    </div>
</div>
""", unsafe_allow_html=True)

        cat_labels = {"work": "💼 Work", "personal": "👤 Personal", "spam": "🚫 Spam", "newsletter": "📰 Newsletter"}
        cat_badge_class = {"work": "cb-work", "personal": "cb-personal", "spam": "cb-spam", "newsletter": "cb-newsletter"}

        for msg, result in st.session_state.important:
            source = msg.get('source', 'gmail')
            initials = get_initials(msg['sender'])
            cat = result.get('category', 'personal')
            av_cls = "av-gmail" if source == 'gmail' else "av-telegram"
            sb_cls = "sb-gmail" if source == 'gmail' else "sb-telegram"
            src_label = "📧 Gmail" if source == 'gmail' else "✈️ Telegram"
            cb_cls = cat_badge_class.get(cat, "cb-personal")
            cat_label = cat_labels.get(cat, "📌 Other")
            subject = msg.get('subject') or 'No subject'
            preview = msg.get('body', '')[:160]
            sender_display = msg['sender'].split('<')[0].strip()[:40]

            st.markdown(f"""
<div class="msg-card">
    <div class="msg-header">
        <div class="av {av_cls}">{initials[:2]}</div>
        <div class="sender-name">{sender_display}</div>
        <span class="src-badge {sb_cls}">{src_label}</span>
    </div>
    <div class="msg-subject">{subject}</div>
    <div class="msg-preview">{preview}...</div>
    <div class="msg-footer">
        <span class="cat-badge {cb_cls}">{cat_label}</span>
        <span>&nbsp;·&nbsp;</span>
        <span>{result['reason']}</span>
    </div>
</div>
""", unsafe_allow_html=True)

            with st.expander("Show full message"):
                st.text(msg.get('body', ''))

        if st.session_state.skipped:
            st.markdown(f"""
<div class="filtered-box">
    🗑️ &nbsp; <strong>{filtered}</strong> newsletters, promotions and automated notifications were filtered out
</div>
""", unsafe_allow_html=True)
            with st.expander("See what was filtered"):
                for msg, result in st.session_state.skipped:
                    src_icon = "📧" if msg.get('source') == 'gmail' else "✈️"
                    st.markdown(f"- {src_icon} **{msg.get('subject') or 'No subject'}** — {result['reason']}")