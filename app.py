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
section[data-testid="stSidebar"] > div {padding-top: 0 !important;}
section[data-testid="stSidebar"] {background: #FAFAFA !important;}
.block-container {padding-top: 1.5rem !important;}
.card {
    border: 1px solid #F0F0F0;
    border-radius: 14px;
    padding: 14px 16px;
    margin-bottom: 10px;
    background: #fff;
}
.card:hover {border-color: #E0E0E0;}
.card-top {display:flex; align-items:center; gap:10px; margin-bottom:10px;}
.app-icon {width:36px; height:36px; border-radius:10px; display:flex; align-items:center; justify-content:center; font-size:18px; flex-shrink:0;}
.icon-gmail {background:#FDECEA;}
.icon-telegram {background:#E3F2FD;}
.card-sender {font-size:13px; font-weight:600; color:#111; flex:1; overflow:hidden; text-overflow:ellipsis; white-space:nowrap;}
.src-pill {font-size:10px; font-weight:600; padding:3px 10px; border-radius:20px; flex-shrink:0;}
.sp-g {background:#FDECEA; color:#C0392B;}
.sp-t {background:#E3F2FD; color:#0D6EAA;}
.card-subject {font-size:14px; font-weight:600; color:#111; margin-bottom:4px; line-height:1.4;}
.card-preview {font-size:12px; color:#999; line-height:1.6; margin-bottom:10px;}
.card-footer {display:flex; align-items:center; gap:6px; padding-top:8px; border-top:1px solid #F5F5F5; font-size:11px; color:#bbb;}
.cat {font-size:10px; font-weight:500; padding:2px 8px; border-radius:8px;}
.c-work {background:#EDE7F6; color:#512DA8;}
.c-personal {background:#E8F5E9; color:#2E7D32;}
.c-spam {background:#FFEBEE; color:#C62828;}
.c-newsletter {background:#FFF8E1; color:#F57F17;}
.filtered-box {background:#FAFAFA; border:1px dashed #E8E8E8; border-radius:12px; padding:14px; font-size:13px; color:#bbb; text-align:center; margin-top:8px;}
.page-header {display:flex; align-items:center; justify-content:space-between; margin-bottom:20px; padding-bottom:16px; border-bottom:1px solid #F5F5F5;}
.empty-state {text-align:center; padding:80px 0;}
.empty-icon {font-size:52px; margin-bottom:16px;}
.empty-title {font-size:22px; font-weight:700; color:#111; margin-bottom:8px;}
.empty-sub {font-size:14px; color:#bbb;}
.section-lbl {font-size:9px; font-weight:700; letter-spacing:0.12em; color:#ccc; margin-bottom:8px; padding-left:4px;}
div[data-testid="stCheckbox"] label {font-size:13px !important; font-weight:500 !important; color:#111 !important;}
div[data-testid="stCheckbox"] {padding: 4px 0 !important;}
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
            st.error(f"Login failed: {token.get('error_description','Unknown')}")
    except Exception as e:
        st.error(f"Login failed: {e}")

if st.session_state.token is None:
    col1, col2, col3 = st.columns([1,2,1])
    with col2:
        st.markdown("<br><br>", unsafe_allow_html=True)
        st.markdown("""
<div style="text-align:center;margin-bottom:32px">
    <div style="font-size:42px;margin-bottom:12px">📬</div>
    <div style="font-size:30px;font-weight:800;color:#111;margin-bottom:8px">Smart Inbox</div>
    <div style="font-size:15px;color:#bbb">AI-powered · only what matters</div>
</div>
<div style="background:#FAFAFA;border:1px solid #EFEFEF;border-radius:16px;padding:24px;margin-bottom:24px">
<div style="display:flex;flex-direction:column;gap:14px">
    <div style="display:flex;align-items:center;gap:12px;font-size:14px;color:#555">
        <span style="width:34px;height:34px;background:#FDECEA;border-radius:10px;display:inline-flex;align-items:center;justify-content:center;flex-shrink:0">📧</span>
        Reads your <strong style="color:#111">Gmail</strong> emails automatically
    </div>
    <div style="display:flex;align-items:center;gap:12px;font-size:14px;color:#555">
        <span style="width:34px;height:34px;background:#E3F2FD;border-radius:10px;display:inline-flex;align-items:center;justify-content:center;flex-shrink:0">✈️</span>
        Reads your <strong style="color:#111">Telegram</strong> personal chats
    </div>
    <div style="display:flex;align-items:center;gap:12px;font-size:14px;color:#555">
        <span style="width:34px;height:34px;background:#F5F5F5;border-radius:10px;display:inline-flex;align-items:center;justify-content:center;flex-shrink:0">🤖</span>
        <strong style="color:#111">AI filters</strong> spam and noise automatically
    </div>
    <div style="display:flex;align-items:center;gap:12px;font-size:14px;color:#555">
        <span style="width:34px;height:34px;background:#F0FDF4;border-radius:10px;display:inline-flex;align-items:center;justify-content:center;flex-shrink:0">🔒</span>
        Your data stays <strong style="color:#111">100% private</strong>
    </div>
</div>
</div>
""", unsafe_allow_html=True)
        st.link_button("Continue with Google →", get_auth_url(), type="primary", use_container_width=True)
        st.markdown("<br>", unsafe_allow_html=True)
        st.caption("Processed by Anthropic AI for classification only — never stored or shared.")

else:
    service = get_gmail_service(st.session_state.token)

    with st.sidebar:
        st.markdown("""
<div style="text-align:center;padding:20px 0 16px;border-bottom:1px solid #EFEFEF;margin-bottom:16px">
    <div style="width:54px;height:54px;border-radius:50%;background:#111;color:#fff;display:flex;align-items:center;justify-content:center;font-size:18px;font-weight:700;margin:0 auto 10px">SJ</div>
    <div style="font-size:14px;font-weight:700;color:#111">Saurabh Joshi</div>
    <div style="font-size:11px;color:#bbb;margin-top:2px">saurabhjoshi7895@gmail.com</div>
</div>
""", unsafe_allow_html=True)

        st.markdown('<div class="section-lbl">CHANNELS</div>', unsafe_allow_html=True)

        col1, col2 = st.columns([4, 1])
        with col1:
            st.markdown("""
<div style="display:flex;align-items:center;gap:8px;padding:6px 0">
    <span style="width:26px;height:26px;background:#FDECEA;border-radius:7px;display:inline-flex;align-items:center;justify-content:center;font-size:14px">📧</span>
    <span style="font-size:13px;font-weight:500;color:#111">Gmail</span>
</div>
""", unsafe_allow_html=True)
        with col2:
            show_gmail = st.checkbox("", value=st.session_state.show_gmail, key="cb_gmail")

        col1, col2 = st.columns([4, 1])
        with col1:
            st.markdown("""
<div style="display:flex;align-items:center;gap:8px;padding:6px 0">
    <span style="width:26px;height:26px;background:#E3F2FD;border-radius:7px;display:inline-flex;align-items:center;justify-content:center;font-size:14px">✈️</span>
    <span style="font-size:13px;font-weight:500;color:#111">Telegram</span>
</div>
""", unsafe_allow_html=True)
        with col2:
            show_telegram = st.checkbox("", value=st.session_state.show_telegram, key="cb_telegram")

        st.session_state.show_gmail = show_gmail
        st.session_state.show_telegram = show_telegram

        st.markdown("""
<div style="margin:8px 0 16px;opacity:0.38">
    <div style="display:flex;align-items:center;gap:8px;padding:6px 4px;font-size:13px;color:#aaa">
        <span style="width:26px;height:26px;background:#E8F5E9;border-radius:7px;display:inline-flex;align-items:center;justify-content:center;font-size:14px">💬</span>
        <span style="flex:1">WhatsApp</span>
        <span style="font-size:9px;background:#F5F5F5;color:#bbb;padding:2px 7px;border-radius:8px">Soon</span>
    </div>
    <div style="display:flex;align-items:center;gap:8px;padding:6px 4px;font-size:13px;color:#aaa">
        <span style="width:26px;height:26px;background:#E8F0FE;border-radius:7px;display:inline-flex;align-items:center;justify-content:center;font-size:14px">💼</span>
        <span style="flex:1">LinkedIn</span>
        <span style="font-size:9px;background:#F5F5F5;color:#bbb;padding:2px 7px;border-radius:8px">Soon</span>
    </div>
    <div style="display:flex;align-items:center;gap:8px;padding:6px 4px;font-size:13px;color:#aaa">
        <span style="width:26px;height:26px;background:#F5F5F5;border-radius:7px;display:inline-flex;align-items:center;justify-content:center;font-size:14px">🐦</span>
        <span style="flex:1">Twitter / X</span>
        <span style="font-size:9px;background:#F5F5F5;color:#bbb;padding:2px 7px;border-radius:8px">Soon</span>
    </div>
</div>
""", unsafe_allow_html=True)

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
        if st.button("Logout", use_container_width=True):
            for k in ['token','important','skipped']: st.session_state[k] = None if k=='token' else []
            st.session_state.total = 0
            st.rerun()

    if not st.session_state.important and st.session_state.total == 0:
        st.markdown("""
<div class="empty-state">
    <div class="empty-icon">📬</div>
    <div class="empty-title">Your inbox is ready</div>
    <div class="empty-sub">Click Fetch Messages in the sidebar to get started</div>
</div>""", unsafe_allow_html=True)

    elif not st.session_state.important:
        st.markdown("""
<div class="empty-state">
    <div class="empty-icon">🎉</div>
    <div class="empty-title">All clear!</div>
    <div class="empty-sub">No important messages right now — enjoy your focus time</div>
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
        <div style="font-size:12px;color:#bbb;margin-top:3px">{imp} important &nbsp;·&nbsp; {flt} filtered out &nbsp;·&nbsp; 📧 {gc} Gmail &nbsp;·&nbsp; ✈️ {tc} Telegram</div>
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
            st.markdown(f'<div class="filtered-box">🗑️ &nbsp; <strong>{flt}</strong> newsletters, promotions and automated notifications filtered out</div>', unsafe_allow_html=True)
            with st.expander("See what was filtered"):
                for msg, result in st.session_state.skipped:
                    icon = "📧" if msg.get('source')=='gmail' else "✈️"
                    st.markdown(f"- {icon} **{msg.get('subject') or 'No subject'}** — {result['reason']}")
