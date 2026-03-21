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
from telegram_auth import (
    send_code, verify_code, save_telegram_session,
    get_telegram_session, delete_telegram_session,
    get_messages_for_user
)

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
        messages=[{
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
        }]
    )
    result = message.content[0].text
    result = result.strip().replace('```json', '').replace('```', '')
    return json.loads(result)

def get_emails_from_service(service, max_results=20):
    results = service.users().messages().list(userId='me', maxResults=max_results).execute()
    messages = results.get('messages', [])
    emails = []
    for msg in messages:
        txt = service.users().messages().get(userId='me', id=msg['id'], format='full').execute()
        payload = txt['payload']
        headers = payload.get('headers', [])
        sender = subject = ''
        for h in headers:
            if h['name'] == 'From': sender = h['value']
            if h['name'] == 'Subject': subject = h['value']
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
            if data: body = base64.urlsafe_b64decode(data).decode('utf-8')
        emails.append({'sender': sender, 'subject': subject, 'body': body[:500], 'source': 'gmail'})
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

def get_user_email(token):
    response = requests.get(
        'https://www.googleapis.com/oauth2/v2/userinfo',
        headers={'Authorization': f'Bearer {token["access_token"]}'}
    )
    data = response.json()
    return data.get('email', ''), data.get('name', ''), data.get('picture', '')

st.set_page_config(page_title="Smart Inbox", page_icon="📬", layout="wide")

st.markdown("""
<style>
section[data-testid="stSidebar"] > div {padding-top: 0 !important;}
section[data-testid="stSidebar"] {background: #FAFAFA !important;}
.block-container {padding-top: 1.5rem !important;}
.card {border:1px solid #F0F0F0;border-radius:14px;padding:14px 16px;margin-bottom:10px;background:#fff;}
.card:hover {border-color:#E0E0E0;}
.card-top {display:flex;align-items:center;gap:10px;margin-bottom:10px;}
.app-icon {width:36px;height:36px;border-radius:10px;display:flex;align-items:center;justify-content:center;font-size:18px;flex-shrink:0;}
.icon-gmail {background:#FDECEA;}
.icon-telegram {background:#E3F2FD;}
.card-sender {font-size:13px;font-weight:600;color:#111;flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;}
.src-pill {font-size:10px;font-weight:600;padding:3px 10px;border-radius:20px;flex-shrink:0;}
.sp-g {background:#FDECEA;color:#C0392B;}
.sp-t {background:#E3F2FD;color:#0D6EAA;}
.card-subject {font-size:14px;font-weight:600;color:#111;margin-bottom:4px;line-height:1.4;}
.card-preview {font-size:12px;color:#999;line-height:1.6;margin-bottom:10px;}
.card-footer {display:flex;align-items:center;gap:6px;padding-top:8px;border-top:1px solid #F5F5F5;font-size:11px;color:#bbb;}
.cat {font-size:10px;font-weight:500;padding:2px 8px;border-radius:8px;}
.c-work {background:#EDE7F6;color:#512DA8;}
.c-personal {background:#E8F5E9;color:#2E7D32;}
.c-spam {background:#FFEBEE;color:#C62828;}
.c-newsletter {background:#FFF8E1;color:#F57F17;}
.filtered-box {background:#FAFAFA;border:1px dashed #E8E8E8;border-radius:12px;padding:14px;font-size:13px;color:#bbb;text-align:center;margin-top:8px;}
.page-header {display:flex;align-items:center;justify-content:space-between;margin-bottom:20px;padding-bottom:16px;border-bottom:1px solid #F5F5F5;}
.empty-state {text-align:center;padding:80px 0;}
.section-lbl {font-size:9px;font-weight:700;letter-spacing:0.12em;color:#ccc;margin-bottom:8px;padding-left:4px;}
.tg-connected {background:#E3F2FD;border:1px solid #BBDEFB;border-radius:10px;padding:10px 12px;font-size:12px;color:#0D6EAA;margin-bottom:8px;}
.tg-form {background:#F8F9FA;border:1px solid #EFEFEF;border-radius:12px;padding:14px;margin-bottom:8px;}
</style>
""", unsafe_allow_html=True)

for k, v in [
    ('token', None), ('important', []), ('skipped', []), ('total', 0),
    ('show_gmail', True), ('show_telegram', True),
    ('user_email', ''), ('user_name', ''), ('user_pic', ''),
    ('tg_step', 'idle'), ('tg_phone', ''), ('tg_session_tmp', ''),
    ('tg_code_hash', '')
]:
    if k not in st.session_state: st.session_state[k] = v

params = st.query_params
if 'code' in params and st.session_state.token is None:
    try:
        token = exchange_code_for_token(params['code'])
        if 'access_token' in token:
            st.session_state.token = token
            email, name, pic = get_user_email(token)
            st.session_state.user_email = email
            st.session_state.user_name = name
            st.session_state.user_pic = pic
            st.query_params.clear()
            st.rerun()
        else:
            st.error(f"Login failed: {token.get('error_description','Unknown')}")
    except Exception as e:
        st.error(f"Login failed: {e}")

if st.session_state.token is None:
    col1, col2, col3 = st.columns([1, 2, 1])
    with col2:
        st.markdown("<br>", unsafe_allow_html=True)
        st.markdown(f"""
<div style="min-height:700px;background:#0A0A0A;border-radius:20px;overflow:hidden;display:flex;flex-direction:column;align-items:center;padding:48px 32px 40px;position:relative">

<div style="position:absolute;top:-60px;left:50%;transform:translateX(-50%);width:400px;height:300px;background:radial-gradient(ellipse,rgba(234,67,53,0.15) 0%,transparent 70%);pointer-events:none"></div>

<div style="display:flex;align-items:center;gap:12px;margin-bottom:44px;z-index:1">
    <div style="width:42px;height:42px;border-radius:12px;background:linear-gradient(135deg,#EA4335,#FF6B35);display:flex;align-items:center;justify-content:center">
        <svg width="22" height="18" viewBox="0 0 22 18" fill="none"><path d="M1 1L11 10L21 1" stroke="white" stroke-width="2" stroke-linecap="round"/><rect x="1" y="1" width="20" height="16" rx="3" stroke="white" stroke-width="1.5" fill="none"/></svg>
    </div>
    <span style="font-size:18px;font-weight:700;color:#fff;letter-spacing:-0.3px">Smart Inbox</span>
</div>

<div style="text-align:center;margin-bottom:36px;z-index:1;max-width:380px">
    <div style="display:inline-flex;align-items:center;gap:6px;background:rgba(255,255,255,0.06);border:1px solid rgba(255,255,255,0.1);border-radius:20px;padding:5px 12px;font-size:11px;color:rgba(255,255,255,0.6);margin-bottom:18px">
        <div style="width:6px;height:6px;border-radius:50%;background:#4CAF50"></div>
        AI-powered · only what matters
    </div>
    <div style="font-size:34px;font-weight:800;color:#fff;line-height:1.15;letter-spacing:-0.5px;margin-bottom:12px">One inbox.<br><span style="background:linear-gradient(135deg,#EA4335,#FF8A65);-webkit-background-clip:text;-webkit-text-fill-color:transparent">Zero noise.</span></div>
    <div style="font-size:13px;color:rgba(255,255,255,0.4);line-height:1.7">Connect Gmail, Telegram and more. Our AI reads everything and shows only what truly needs your attention.</div>
</div>

<div style="display:flex;gap:24px;margin-bottom:32px;z-index:1">
    <div style="text-align:center"><div style="font-size:20px;font-weight:800;color:#fff">98%</div><div style="font-size:10px;color:rgba(255,255,255,0.35);margin-top:2px">Noise filtered</div></div>
    <div style="width:1px;background:rgba(255,255,255,0.08)"></div>
    <div style="text-align:center"><div style="font-size:20px;font-weight:800;color:#fff">5+</div><div style="font-size:10px;color:rgba(255,255,255,0.35);margin-top:2px">Platforms</div></div>
    <div style="width:1px;background:rgba(255,255,255,0.08)"></div>
    <div style="text-align:center"><div style="font-size:20px;font-weight:800;color:#fff">AI</div><div style="font-size:10px;color:rgba(255,255,255,0.35);margin-top:2px">Powered</div></div>
</div>

<div style="display:flex;flex-direction:column;gap:10px;width:100%;max-width:360px;z-index:1">

    <a href="{get_auth_url()}" style="text-decoration:none">
    <div style="display:flex;align-items:center;gap:14px;padding:14px 18px;border-radius:14px;cursor:pointer;border:1px solid rgba(234,67,53,0.3);background:rgba(234,67,53,0.12)">
        <div style="width:38px;height:38px;border-radius:10px;background:rgba(234,67,53,0.2);display:flex;align-items:center;justify-content:center;flex-shrink:0">
            <svg width="20" height="20" viewBox="0 0 24 24" fill="#EA4335"><path d="M24 5.457v13.909c0 .904-.732 1.636-1.636 1.636h-3.819V11.73L12 16.64l-6.545-4.91v9.273H1.636A1.636 1.636 0 0 1 0 19.366V5.457c0-.561.289-1.078.766-1.376l10.598-6.547a1.636 1.636 0 0 1 1.272 0l10.598 6.547c.477.298.766.815.766 1.376z"/></svg>
        </div>
        <div style="flex:1">
            <div style="font-size:14px;font-weight:600;color:#FF8A7A">Continue with Gmail</div>
            <div style="font-size:11px;color:rgba(255,255,255,0.35);margin-top:1px">Required — connects your Google account</div>
        </div>
        <span style="color:rgba(234,67,53,0.6);font-size:18px">›</span>
    </div>
    </a>

    <div style="display:flex;align-items:center;gap:10px;margin:2px 0">
        <div style="flex:1;height:1px;background:rgba(255,255,255,0.06)"></div>
        <div style="font-size:10px;color:rgba(255,255,255,0.2)">also connect</div>
        <div style="flex:1;height:1px;background:rgba(255,255,255,0.06)"></div>
    </div>

    <div style="display:flex;align-items:center;gap:14px;padding:14px 18px;border-radius:14px;border:1px solid rgba(34,158,217,0.25);background:rgba(34,158,217,0.1)">
        <div style="width:38px;height:38px;border-radius:10px;background:rgba(34,158,217,0.2);display:flex;align-items:center;justify-content:center;flex-shrink:0">
            <svg width="20" height="20" viewBox="0 0 24 24" fill="#229ED9"><path d="M11.944 0A12 12 0 0 0 0 12a12 12 0 0 0 12 12 12 12 0 0 0 12-12A12 12 0 0 0 12 0a12 12 0 0 0-.056 0zm4.962 7.224c.1-.002.321.023.465.14a.506.506 0 0 1 .171.325c.016.093.036.306.02.472-.18 1.898-.962 6.502-1.36 8.627-.168.9-.499 1.201-.82 1.23-.696.065-1.225-.46-1.9-.902-1.056-.693-1.653-1.124-2.678-1.8-1.185-.78-.417-1.21.258-1.91.177-.184 3.247-2.977 3.307-3.23.007-.032.014-.15-.056-.212s-.174-.041-.249-.024c-.106.024-1.793 1.14-5.061 3.345-.48.33-.913.49-1.302.48-.428-.008-1.252-.241-1.865-.44-.752-.245-1.349-.374-1.297-.789.027-.216.325-.437.893-.663 3.498-1.524 5.83-2.529 6.998-3.014 3.332-1.386 4.025-1.627 4.476-1.635z"/></svg>
        </div>
        <div style="flex:1">
            <div style="font-size:14px;font-weight:600;color:#64B5F6">Connect Telegram</div>
            <div style="font-size:11px;color:rgba(255,255,255,0.35);margin-top:1px">Read your personal chats</div>
        </div>
        <span style="color:rgba(34,158,217,0.5);font-size:18px">›</span>
    </div>

    <div style="opacity:0.35;display:flex;align-items:center;gap:14px;padding:14px 18px;border-radius:14px;border:1px solid rgba(255,255,255,0.08);background:rgba(255,255,255,0.04)">
        <div style="width:38px;height:38px;border-radius:10px;background:rgba(37,211,102,0.15);display:flex;align-items:center;justify-content:center;flex-shrink:0">
            <svg width="20" height="20" viewBox="0 0 24 24" fill="#25D366"><path d="M17.472 14.382c-.297-.149-1.758-.867-2.03-.967-.273-.099-.471-.148-.67.15-.197.297-.767.966-.94 1.164-.173.199-.347.223-.644.075-.297-.15-1.255-.463-2.39-1.475-.883-.788-1.48-1.761-1.653-2.059-.173-.297-.018-.458.13-.606.134-.133.298-.347.446-.52.149-.174.198-.298.298-.497.099-.198.05-.371-.025-.52-.075-.149-.669-1.612-.916-2.207-.242-.579-.487-.5-.669-.51-.173-.008-.371-.01-.57-.01-.198 0-.52.074-.792.372-.272.297-1.04 1.016-1.04 2.479 0 1.462 1.065 2.875 1.213 3.074.149.198 2.096 3.2 5.077 4.487.709.306 1.262.489 1.694.625.712.227 1.36.195 1.871.118.571-.085 1.758-.719 2.006-1.413.248-.694.248-1.289.173-1.413-.074-.124-.272-.198-.57-.347m-5.421 7.403h-.004a9.87 9.87 0 0 1-5.031-1.378l-.361-.214-3.741.982.998-3.648-.235-.374a9.86 9.86 0 0 1-1.51-5.26c.001-5.45 4.436-9.884 9.888-9.884 2.64 0 5.122 1.03 6.988 2.898a9.825 9.825 0 0 1 2.893 6.994c-.003 5.45-4.437 9.884-9.885 9.884m8.413-18.297A11.815 11.815 0 0 0 12.05 0C5.495 0 .16 5.335.157 11.892c0 2.096.547 4.142 1.588 5.945L.057 24l6.305-1.654a11.882 11.882 0 0 0 5.683 1.448h.005c6.554 0 11.89-5.335 11.893-11.893a11.821 11.821 0 0 0-3.48-8.413z"/></svg>
        </div>
        <div style="flex:1">
            <div style="font-size:14px;font-weight:600;color:#fff">WhatsApp</div>
            <div style="font-size:11px;color:rgba(255,255,255,0.35);margin-top:1px">Personal messages</div>
        </div>
        <span style="font-size:9px;font-weight:700;background:rgba(255,255,255,0.06);color:rgba(255,255,255,0.3);padding:3px 8px;border-radius:8px;border:1px solid rgba(255,255,255,0.08)">SOON</span>
    </div>

    <div style="opacity:0.35;display:flex;align-items:center;gap:14px;padding:14px 18px;border-radius:14px;border:1px solid rgba(255,255,255,0.08);background:rgba(255,255,255,0.04)">
        <div style="width:38px;height:38px;border-radius:10px;background:rgba(10,102,194,0.15);display:flex;align-items:center;justify-content:center;flex-shrink:0">
            <svg width="20" height="20" viewBox="0 0 24 24" fill="#0A66C2"><path d="M20.447 20.452h-3.554v-5.569c0-1.328-.027-3.037-1.852-3.037-1.853 0-2.136 1.445-2.136 2.939v5.667H9.351V9h3.414v1.561h.046c.477-.9 1.637-1.85 3.37-1.85 3.601 0 4.267 2.37 4.267 5.455v6.286zM5.337 7.433a2.062 2.062 0 0 1-2.063-2.065 2.064 2.064 0 1 1 2.063 2.065zm1.782 13.019H3.555V9h3.564v11.452zM22.225 0H1.771C.792 0 0 .774 0 1.729v20.542C0 23.227.792 24 1.771 24h20.451C23.2 24 24 23.227 24 22.271V1.729C24 .774 23.2 0 22.222 0h.003z"/></svg>
        </div>
        <div style="flex:1">
            <div style="font-size:14px;font-weight:600;color:#fff">LinkedIn</div>
            <div style="font-size:11px;color:rgba(255,255,255,0.35);margin-top:1px">Messages and notifications</div>
        </div>
        <span style="font-size:9px;font-weight:700;background:rgba(255,255,255,0.06);color:rgba(255,255,255,0.3);padding:3px 8px;border-radius:8px;border:1px solid rgba(255,255,255,0.08)">SOON</span>
    </div>

    <div style="opacity:0.35;display:flex;align-items:center;gap:14px;padding:14px 18px;border-radius:14px;border:1px solid rgba(255,255,255,0.08);background:rgba(255,255,255,0.04)">
        <div style="width:38px;height:38px;border-radius:10px;background:rgba(255,255,255,0.08);display:flex;align-items:center;justify-content:center;flex-shrink:0">
            <svg width="20" height="20" viewBox="0 0 24 24" fill="rgba(255,255,255,0.7)"><path d="M18.244 2.25h3.308l-7.227 8.26 8.502 11.24H16.17l-4.714-6.231-5.401 6.231H2.746l7.73-8.835L1.254 2.25H8.08l4.713 6.231zm-1.161 17.52h1.833L7.084 4.126H5.117z"/></svg>
        </div>
        <div style="flex:1">
            <div style="font-size:14px;font-weight:600;color:#fff">Twitter / X</div>
            <div style="font-size:11px;color:rgba(255,255,255,0.35);margin-top:1px">DMs and mentions</div>
        </div>
        <span style="font-size:9px;font-weight:700;background:rgba(255,255,255,0.06);color:rgba(255,255,255,0.3);padding:3px 8px;border-radius:8px;border:1px solid rgba(255,255,255,0.08)">SOON</span>
    </div>

</div>

<div style="font-size:11px;color:rgba(255,255,255,0.2);text-align:center;margin-top:24px;z-index:1;line-height:1.6">
    🔒 End-to-end private. Processed by AI for classification only.<br>Never stored, never shared.
</div>

</div>
""", unsafe_allow_html=True)

else:
    service = get_gmail_service(st.session_state.token)
    user_email = st.session_state.user_email
    user_name = st.session_state.user_name or "User"
    initials = ''.join([p[0].upper() for p in user_name.split()[:2]]) if user_name else "??"

    tg_session_data = get_telegram_session(user_email) if user_email else None
    tg_connected = tg_session_data is not None

    with st.sidebar:
        st.markdown(f"""
<div style="text-align:center;padding:20px 0 16px;border-bottom:1px solid #EFEFEF;margin-bottom:16px">
    <div style="width:54px;height:54px;border-radius:50%;background:#111;color:#fff;display:flex;align-items:center;justify-content:center;font-size:18px;font-weight:700;margin:0 auto 10px">{initials}</div>
    <div style="font-size:14px;font-weight:700;color:#111">{user_name}</div>
    <div style="font-size:11px;color:#bbb;margin-top:2px">{user_email}</div>
</div>
""", unsafe_allow_html=True)

        st.markdown('<div class="section-lbl">CHANNELS</div>', unsafe_allow_html=True)

        col1, col2 = st.columns([4,1])
        with col1:
            st.markdown('<div style="display:flex;align-items:center;gap:8px;padding:6px 0"><span style="width:26px;height:26px;background:#FDECEA;border-radius:7px;display:inline-flex;align-items:center;justify-content:center;font-size:14px">📧</span><span style="font-size:13px;font-weight:500;color:#111">Gmail</span></div>', unsafe_allow_html=True)
        with col2:
            show_gmail = st.checkbox("", value=st.session_state.show_gmail, key="cb_gmail")

        col1, col2 = st.columns([4,1])
        with col1:
            tg_status = "✅" if tg_connected else "⚪"
            st.markdown(f'<div style="display:flex;align-items:center;gap:8px;padding:6px 0"><span style="width:26px;height:26px;background:#E3F2FD;border-radius:7px;display:inline-flex;align-items:center;justify-content:center;font-size:14px">✈️</span><span style="font-size:13px;font-weight:500;color:#111">Telegram {tg_status}</span></div>', unsafe_allow_html=True)
        with col2:
            show_telegram = st.checkbox("", value=st.session_state.show_telegram and tg_connected, key="cb_telegram", disabled=not tg_connected)

        st.session_state.show_gmail = show_gmail
        st.session_state.show_telegram = show_telegram and tg_connected

        st.markdown("""
<div style="margin:8px 0 8px;opacity:0.38">
    <div style="display:flex;align-items:center;gap:8px;padding:6px 4px;font-size:13px;color:#aaa">
        <span style="width:26px;height:26px;background:#E8F5E9;border-radius:7px;display:inline-flex;align-items:center;justify-content:center;font-size:14px">💬</span>
        <span style="flex:1">WhatsApp</span><span style="font-size:9px;background:#F5F5F5;color:#bbb;padding:2px 7px;border-radius:8px">Soon</span>
    </div>
    <div style="display:flex;align-items:center;gap:8px;padding:6px 4px;font-size:13px;color:#aaa">
        <span style="width:26px;height:26px;background:#E8F0FE;border-radius:7px;display:inline-flex;align-items:center;justify-content:center;font-size:14px">💼</span>
        <span style="flex:1">LinkedIn</span><span style="font-size:9px;background:#F5F5F5;color:#bbb;padding:2px 7px;border-radius:8px">Soon</span>
    </div>
    <div style="display:flex;align-items:center;gap:8px;padding:6px 4px;font-size:13px;color:#aaa">
        <span style="width:26px;height:26px;background:#F5F5F5;border-radius:7px;display:inline-flex;align-items:center;justify-content:center;font-size:14px">🐦</span>
        <span style="flex:1">Twitter / X</span><span style="font-size:9px;background:#F5F5F5;color:#bbb;padding:2px 7px;border-radius:8px">Soon</span>
    </div>
</div>
""", unsafe_allow_html=True)

        st.markdown("---")

        if not tg_connected:
            st.markdown("**Connect Telegram**")
            if st.session_state.tg_step == 'idle':
                phone = st.text_input("Your phone number", placeholder="+917895827654", key="tg_phone_input")
                if st.button("Send OTP", use_container_width=True):
                    if phone:
                        with st.spinner("Sending OTP..."):
                            try:
                                session_tmp, code_hash = asyncio.run(send_code(phone))
                                st.session_state.tg_phone = phone
                                st.session_state.tg_session_tmp = session_tmp
                                st.session_state.tg_code_hash = code_hash
                                st.session_state.tg_step = 'otp'
                                st.rerun()
                            except Exception as e:
                                st.error(f"Error: {e}")
                    else:
                        st.warning("Please enter your phone number")

            elif st.session_state.tg_step == 'otp':
                st.success(f"OTP sent to {st.session_state.tg_phone}")
                otp = st.text_input("Enter OTP from Telegram", key="tg_otp_input")
                if st.button("Verify OTP", use_container_width=True):
                    if otp:
                        with st.spinner("Verifying..."):
                            try:
                                final_session, status = asyncio.run(verify_code(
                                    st.session_state.tg_session_tmp,
                                    st.session_state.tg_phone,
                                    otp,
                                    st.session_state.tg_code_hash
                                ))
                                if status == 'needs_password':
                                    st.session_state.tg_step = 'password'
                                    st.rerun()
                                elif status == 'success':
                                    save_telegram_session(user_email, final_session, st.session_state.tg_phone)
                                    st.session_state.tg_step = 'idle'
                                    st.success("Telegram connected!")
                                    st.rerun()
                            except Exception as e:
                                st.error(f"Error: {e}")
                if st.button("Back", use_container_width=True):
                    st.session_state.tg_step = 'idle'
                    st.rerun()

            elif st.session_state.tg_step == 'password':
                st.info("2-step verification required")
                pwd = st.text_input("Enter your Telegram password", type="password", key="tg_pwd_input")
                if st.button("Submit Password", use_container_width=True):
                    if pwd:
                        with st.spinner("Verifying..."):
                            try:
                                final_session, status = asyncio.run(verify_code(
                                    st.session_state.tg_session_tmp,
                                    st.session_state.tg_phone,
                                    None,
                                    st.session_state.tg_code_hash,
                                    password=pwd
                                ))
                                if status == 'success':
                                    save_telegram_session(user_email, final_session, st.session_state.tg_phone)
                                    st.session_state.tg_step = 'idle'
                                    st.success("Telegram connected!")
                                    st.rerun()
                            except Exception as e:
                                st.error(f"Error: {e}")
        else:
            st.markdown(f'<div class="tg-connected">✅ Telegram connected<br><small>{tg_session_data["phone"]}</small></div>', unsafe_allow_html=True)
            if st.button("Disconnect Telegram", use_container_width=True):
                delete_telegram_session(user_email)
                st.rerun()

        st.markdown("---")
        st.markdown('<div class="section-lbl">STATS</div>', unsafe_allow_html=True)
        c1, c2 = st.columns(2)
        with c1:
            st.metric("Total", st.session_state.total)
            st.metric("Filtered", len(st.session_state.skipped))
        with c2:
            st.metric("Important", len(st.session_state.important))
            st.metric("Gmail", sum(1 for m,_ in st.session_state.important if m.get('source')=='gmail'))

        st.markdown("<br>", unsafe_allow_html=True)

        if st.button("🔄  Fetch Messages", type="primary", use_container_width=True):
            all_messages = []
            if show_gmail:
                with st.spinner("Fetching Gmail..."):
                    all_messages.extend(get_emails_from_service(service))
            if st.session_state.show_telegram and tg_connected:
                with st.spinner("Fetching Telegram..."):
                    try:
                        tmsgs = asyncio.run(get_messages_for_user(tg_session_data['session_string']))
                        all_messages.extend(tmsgs)
                    except Exception as e:
                        st.warning(f"Telegram: {e}")
            if all_messages:
                imp, skp = [], []
                prog = st.progress(0)
                for i, msg in enumerate(all_messages):
                    r = classify_email(msg)
                    (imp if r['importance']=='high' else skp).append((msg, r))
                    prog.progress((i+1)/len(all_messages))
                prog.empty()
                st.session_state.important = imp
                st.session_state.skipped = skp
                st.session_state.total = len(all_messages)
            st.rerun()

        st.markdown("<br>", unsafe_allow_html=True)
        if st.button("Logout", use_container_width=True):
            for k in ['token','important','skipped','user_email','user_name','user_pic']:
                st.session_state[k] = None if k == 'token' else ''  if k in ['user_email','user_name','user_pic'] else []
            st.session_state.total = 0
            st.rerun()

    if not st.session_state.important and st.session_state.total == 0:
        st.markdown("""
<div class="empty-state">
    <div style="font-size:52px;margin-bottom:16px">📬</div>
    <div style="font-size:22px;font-weight:700;color:#111;margin-bottom:8px">Your inbox is ready</div>
    <div style="font-size:14px;color:#bbb">Click Fetch Messages in the sidebar to get started</div>
</div>""", unsafe_allow_html=True)

    elif not st.session_state.important:
        st.markdown("""
<div class="empty-state">
    <div style="font-size:52px;margin-bottom:16px">🎉</div>
    <div style="font-size:22px;font-weight:700;color:#111;margin-bottom:8px">All clear!</div>
    <div style="font-size:14px;color:#bbb">No important messages right now</div>
</div>""", unsafe_allow_html=True)

    else:
        imp = len(st.session_state.important)
        flt = len(st.session_state.skipped)
        gc = sum(1 for m,_ in st.session_state.important if m.get('source')=='gmail')
        tc = sum(1 for m,_ in st.session_state.important if m.get('source')=='telegram')

        st.markdown(f"""
<div class="page-header">
    <div>
        <div style="font-size:20px;font-weight:800;color:#111">All messages</div>
        <div style="font-size:12px;color:#bbb;margin-top:3px">{imp} important &nbsp;·&nbsp; {flt} filtered &nbsp;·&nbsp; 📧 {gc} Gmail &nbsp;·&nbsp; ✈️ {tc} Telegram</div>
    </div>
</div>""", unsafe_allow_html=True)

        cat_cls = {"work":"c-work","personal":"c-personal","spam":"c-spam","newsletter":"c-newsletter"}
        cat_lbl = {"work":"💼 Work","personal":"👤 Personal","spam":"🚫 Spam","newsletter":"📰 Newsletter"}

        for msg, result in st.session_state.important:
            source = msg.get('source','gmail')
            cat = result.get('category','personal')
            sender = msg['sender'].split('<')[0].strip()[:45]
            subject = msg.get('subject') or 'No subject'
            preview = msg.get('body','')[:160]
            icon_cls = "icon-gmail" if source=='gmail' else "icon-telegram"
            icon_emoji = "📧" if source=='gmail' else "✈️"
            pill_cls = "sp-g" if source=='gmail' else "sp-t"
            pill_lbl = "📧 Gmail" if source=='gmail' else "✈️ Telegram"

            st.markdown(f"""
<div class="card">
    <div class="card-top">
        <div class="app-icon {icon_cls}">{icon_emoji}</div>
        <div class="card-sender">{sender}</div>
        <span class="src-pill {pill_cls}">{pill_lbl}</span>
    </div>
    <div class="card-subject">{subject}</div>
    <div class="card-preview">{preview}...</div>
    <div class="card-footer">
        <span class="cat {cat_cls.get(cat,'c-personal')}">{cat_lbl.get(cat,'📌 Other')}</span>
        <span>·</span>
        <span>{result['reason']}</span>
    </div>
</div>""", unsafe_allow_html=True)

            with st.expander("Show full message"):
                st.text(msg.get('body',''))

        if st.session_state.skipped:
            st.markdown(f'<div class="filtered-box">🗑️ &nbsp; <strong>{flt}</strong> newsletters, promotions and notifications filtered out</div>', unsafe_allow_html=True)
            with st.expander("See what was filtered"):
                for msg, result in st.session_state.skipped:
                    icon = "📧" if msg.get('source')=='gmail' else "✈️"
                    st.markdown(f"- {icon} **{msg.get('subject') or 'No subject'}** — {result['reason']}")
