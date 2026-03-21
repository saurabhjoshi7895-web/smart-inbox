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

GMAIL_SVG = '<svg width="16" height="16" viewBox="0 0 24 24" fill="#EA4335"><path d="M24 5.457v13.909c0 .904-.732 1.636-1.636 1.636h-3.819V11.73L12 16.64l-6.545-4.91v9.273H1.636A1.636 1.636 0 0 1 0 19.366V5.457c0-.561.289-1.078.766-1.376l10.598-6.547a1.636 1.636 0 0 1 1.272 0l10.598 6.547c.477.298.766.815.766 1.376z"/></svg>'
TELEGRAM_SVG = '<svg width="16" height="16" viewBox="0 0 24 24" fill="#229ED9"><path d="M11.944 0A12 12 0 0 0 0 12a12 12 0 0 0 12 12 12 12 0 0 0 12-12A12 12 0 0 0 12 0a12 12 0 0 0-.056 0zm4.962 7.224c.1-.002.321.023.465.14a.506.506 0 0 1 .171.325c.016.093.036.306.02.472-.18 1.898-.962 6.502-1.36 8.627-.168.9-.499 1.201-.82 1.23-.696.065-1.225-.46-1.9-.902-1.056-.693-1.653-1.124-2.678-1.8-1.185-.78-.417-1.21.258-1.91.177-.184 3.247-2.977 3.307-3.23.007-.032.014-.15-.056-.212s-.174-.041-.249-.024c-.106.024-1.793 1.14-5.061 3.345-.48.33-.913.49-1.302.48-.428-.008-1.252-.241-1.865-.44-.752-.245-1.349-.374-1.297-.789.027-.216.325-.437.893-.663 3.498-1.524 5.83-2.529 6.998-3.014 3.332-1.386 4.025-1.627 4.476-1.635z"/></svg>'

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

st.set_page_config(page_title="Smart Inbox", page_icon="📬", layout="wide")

st.markdown("""
<style>
section[data-testid="stSidebar"] > div {padding-top:1rem}
.card {
    border:1px solid rgba(128,128,128,0.12);
    border-radius:14px;
    padding:14px 16px;
    margin-bottom:10px;
    background:var(--background-color);
}
.card:hover{border-color:rgba(128,128,128,0.3)}
.card-top{display:flex;align-items:center;gap:10px;margin-bottom:10px}
.app-icon{width:36px;height:36px;border-radius:10px;display:flex;align-items:center;justify-content:center;flex-shrink:0}
.icon-gmail{background:#FDECEA}
.icon-telegram{background:#E3F2FD}
.card-meta{flex:1;min-width:0}
.card-sender{font-size:13px;font-weight:600;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.card-time{font-size:10px;color:rgba(128,128,128,0.6);margin-top:1px}
.src-pill{display:inline-flex;align-items:center;gap:4px;font-size:10px;font-weight:600;padding:3px 9px;border-radius:20px;flex-shrink:0}
.sp-g{background:#FDECEA;color:#C0392B}
.sp-t{background:#E3F2FD;color:#0D6EAA}
.card-subject{font-size:14px;font-weight:600;margin-bottom:4px;line-height:1.3}
.card-preview{font-size:12px;color:rgba(128,128,128,0.8);line-height:1.6;margin-bottom:10px}
.card-footer{display:flex;align-items:center;gap:6px;padding-top:8px;border-top:1px solid rgba(128,128,128,0.08);font-size:11px;color:rgba(128,128,128,0.6)}
.cat{font-size:11px;font-weight:500;padding:2px 8px;border-radius:10px}
.c-work{background:#EDE7F6;color:#512DA8}
.c-personal{background:#E8F5E9;color:#2E7D32}
.c-spam{background:#FFEBEE;color:#C62828}
.c-newsletter{background:#FFF8E1;color:#F57F17}
.filtered-box{background:rgba(128,128,128,0.03);border:1px dashed rgba(128,128,128,0.18);border-radius:12px;padding:14px;font-size:13px;color:rgba(128,128,128,0.55);text-align:center;margin-top:4px}
.sidebar-ch{display:flex;align-items:center;gap:8px;padding:7px 8px;border-radius:8px;margin-bottom:2px;font-size:13px}
.ch-icon-box{width:26px;height:26px;border-radius:7px;display:flex;align-items:center;justify-content:center;flex-shrink:0}
</style>
""", unsafe_allow_html=True)

for k, v in [('token',None),('important',[]),('skipped',[]),('total',0),('show_gmail',True),('show_telegram',True)]:
    if k not in st.session_state: st.session_state[k] = v

params = st.query_params
if 'code' in params and st.session_state.token is None:
    try:
        token = exchange_code_for_token(params['code'])
        if 'access_token' in token:
            st.session_state.token = token
            st.query_params.clear()
            st.rerun()
        else:
            st.error(f"Login failed: {token.get('error_description','Unknown error')}")
    except Exception as e:
        st.error(f"Login failed: {e}")

if st.session_state.token is None:
    col1, col2, col3 = st.columns([1,2,1])
    with col2:
        st.markdown("<br><br>", unsafe_allow_html=True)
        st.markdown("""
<div style="text-align:center;margin-bottom:28px">
    <div style="font-size:44px;margin-bottom:10px">📬</div>
    <div style="font-size:28px;font-weight:700;margin-bottom:6px">Smart Inbox</div>
    <div style="font-size:15px;color:rgba(128,128,128,0.65)">AI-powered · only what matters</div>
</div>
<div style="background:rgba(128,128,128,0.04);border:1px solid rgba(128,128,128,0.12);border-radius:16px;padding:24px;margin-bottom:24px">
<div style="display:flex;flex-direction:column;gap:12px">
    <div style="display:flex;align-items:center;gap:12px;font-size:14px">
        <span style="width:32px;height:32px;background:#FDECEA;border-radius:10px;display:inline-flex;align-items:center;justify-content:center">📧</span>
        Reads your <strong>Gmail</strong> emails
    </div>
    <div style="display:flex;align-items:center;gap:12px;font-size:14px">
        <span style="width:32px;height:32px;background:#E3F2FD;border-radius:10px;display:inline-flex;align-items:center;justify-content:center">✈️</span>
        Reads your <strong>Telegram</strong> messages
    </div>
    <div style="display:flex;align-items:center;gap:12px;font-size:14px">
        <span style="width:32px;height:32px;background:#E8F5E9;border-radius:10px;display:inline-flex;align-items:center;justify-content:center">🤖</span>
        <strong>AI</strong> filters spam and noise automatically
    </div>
    <div style="display:flex;align-items:center;gap:12px;font-size:14px">
        <span style="width:32px;height:32px;background:#F3E5F5;border-radius:10px;display:inline-flex;align-items:center;justify-content:center">🔒</span>
        Your data stays <strong>private</strong>
    </div>
</div>
</div>
""", unsafe_allow_html=True)
        st.link_button("🔐 Continue with Google", get_auth_url(), type="primary", use_container_width=True)
        st.caption("Processed by Anthropic AI for classification only — never stored.")

else:
    service = get_gmail_service(st.session_state.token)

    with st.sidebar:
        st.markdown("""
<div style="text-align:center;padding-bottom:14px;border-bottom:1px solid rgba(128,128,128,0.12);margin-bottom:14px">
<div style="width:54px;height:54px;border-radius:50%;background:linear-gradient(135deg,#EA4335,#FBBC04);color:#fff;display:flex;align-items:center;justify-content:center;font-size:18px;font-weight:700;margin:0 auto 8px">SJ</div>
<div style="font-size:14px;font-weight:600">Saurabh Joshi</div>
<div style="font-size:11px;color:rgba(128,128,128,0.55);margin-top:2px">saurabhjoshi7895@gmail.com</div>
</div>
""", unsafe_allow_html=True)

        st.markdown("<div style='font-size:9px;font-weight:700;letter-spacing:0.1em;color:rgba(128,128,128,0.5);margin-bottom:8px'>CHANNELS</div>", unsafe_allow_html=True)

        show_gmail = st.toggle("Gmail", value=st.session_state.show_gmail)
        show_telegram = st.toggle("Telegram", value=st.session_state.show_telegram)
        st.session_state.show_gmail = show_gmail
        st.session_state.show_telegram = show_telegram

        st.markdown("""
<div style="opacity:0.38;margin:4px 0 14px">
<div class="sidebar-ch"><div class="ch-icon-box" style="background:#E8F5E9">💬</div><span style="flex:1">WhatsApp</span><span style="font-size:9px;background:rgba(128,128,128,0.1);padding:2px 7px;border-radius:8px">Soon</span></div>
<div class="sidebar-ch"><div class="ch-icon-box" style="background:#E8F0FE">💼</div><span style="flex:1">LinkedIn</span><span style="font-size:9px;background:rgba(128,128,128,0.1);padding:2px 7px;border-radius:8px">Soon</span></div>
<div class="sidebar-ch"><div class="ch-icon-box" style="background:#F5F5F5">🐦</div><span style="flex:1">Twitter / X</span><span style="font-size:9px;background:rgba(128,128,128,0.1);padding:2px 7px;border-radius:8px">Soon</span></div>
</div>
""", unsafe_allow_html=True)

        st.markdown("<div style='font-size:9px;font-weight:700;letter-spacing:0.1em;color:rgba(128,128,128,0.5);margin-bottom:8px'>STATS</div>", unsafe_allow_html=True)

        c1, c2 = st.columns(2)
        with c1:
            st.metric("Total", st.session_state.total)
            st.metric("Filtered", len(st.session_state.skipped))
        with c2:
            st.metric("Important", len(st.session_state.important))
            st.metric("Gmail", sum(1 for m,_ in st.session_state.important if m.get('source')=='gmail'))

        st.markdown("<br>", unsafe_allow_html=True)

        if st.button("🔄 Fetch Messages", type="primary", use_container_width=True):
            all_messages = []
            if show_gmail:
                with st.spinner("Fetching Gmail..."):
                    all_messages.extend(get_emails_from_service(service))
            t_id = st.secrets.get("TELEGRAM_API_ID","")
            t_hash = st.secrets.get("TELEGRAM_API_HASH","")
            t_session = st.secrets.get("TELEGRAM_SESSION","")
            if show_telegram and t_id and t_hash and t_session:
                with st.spinner("Fetching Telegram..."):
                    try:
                        tmsgs = asyncio.run(get_personal_messages(int(t_id), t_hash, t_session))
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
        if st.button("🚪 Logout", use_container_width=True):
            for k in ['token','important','skipped']: st.session_state[k] = None if k=='token' else []
            st.session_state.total = 0
            st.rerun()

    if not st.session_state.important and st.session_state.total == 0:
        st.markdown("""
<div style="text-align:center;padding:80px 0">
<div style="font-size:52px;margin-bottom:16px">📬</div>
<div style="font-size:22px;font-weight:600;margin-bottom:8px">Your inbox is ready</div>
<div style="font-size:14px;color:rgba(128,128,128,0.6)">Click Fetch Messages in the sidebar to start</div>
</div>""", unsafe_allow_html=True)

    elif not st.session_state.important:
        st.markdown("""
<div style="text-align:center;padding:80px 0">
<div style="font-size:52px;margin-bottom:16px">🎉</div>
<div style="font-size:22px;font-weight:600;margin-bottom:8px">All clear!</div>
<div style="font-size:14px;color:rgba(128,128,128,0.6)">No important messages right now</div>
</div>""", unsafe_allow_html=True)

    else:
        imp = len(st.session_state.important)
        flt = len(st.session_state.skipped)
        gc = sum(1 for m,_ in st.session_state.important if m.get('source')=='gmail')
        tc = sum(1 for m,_ in st.session_state.important if m.get('source')=='telegram')

        st.markdown(f"""
<div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:20px">
<div>
    <div style="font-size:20px;font-weight:700">📬 All messages</div>
    <div style="font-size:12px;color:rgba(128,128,128,0.6);margin-top:3px">{imp} important &nbsp;·&nbsp; {flt} filtered &nbsp;·&nbsp; 📧 {gc} Gmail &nbsp;·&nbsp; ✈️ {tc} Telegram</div>
</div>
</div>""", unsafe_allow_html=True)

        cat_cls = {"work":"c-work","personal":"c-personal","spam":"c-spam","newsletter":"c-newsletter"}
        cat_lbl = {"work":"💼 Work","personal":"👤 Personal","spam":"🚫 Spam","newsletter":"📰 Newsletter"}

        for msg, result in st.session_state.important:
            source = msg.get('source','gmail')
            cat = result.get('category','personal')
            sender = msg['sender'].split('<')[0].strip()[:45]
            subject = msg.get('subject') or 'No subject'
            preview = msg.get('body','')[:150]

            if source == 'gmail':
                icon_html = f'<div class="app-icon icon-gmail">{GMAIL_SVG}</div>'
                pill_html = f'<span class="src-pill sp-g">{GMAIL_SVG}&nbsp;Gmail</span>'
            else:
                icon_html = f'<div class="app-icon icon-telegram">{TELEGRAM_SVG}</div>'
                pill_html = f'<span class="src-pill sp-t">{TELEGRAM_SVG}&nbsp;Telegram</span>'

            st.markdown(f"""
<div class="card">
    <div class="card-top">
        {icon_html}
        <div class="card-meta">
            <div class="card-sender">{sender}</div>
        </div>
        {pill_html}
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
            st.markdown(f'<div class="filtered-box">🗑️ &nbsp; <strong>{flt}</strong> newsletters, promotions and notifications were filtered out</div>', unsafe_allow_html=True)
            with st.expander("See what was filtered"):
                for msg, result in st.session_state.skipped:
                    icon = "📧" if msg.get('source')=='gmail' else "✈️"
                    st.markdown(f"- {icon} **{msg.get('subject') or 'No subject'}** — {result['reason']}")
