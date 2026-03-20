import streamlit as st
import anthropic
import json
import os
import base64
from google_auth_oauthlib.flow import InstalledAppFlow
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from googleapiclient.discovery import build

SCOPES = ['https://www.googleapis.com/auth/gmail.readonly']
os.environ['OAUTHLIB_INSECURE_TRANSPORT'] = '1'

client = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY", ""))

def classify_email(email):
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

def login_with_google():
    flow = InstalledAppFlow.from_client_secrets_file(
        'credentials.json',
        scopes=SCOPES
    )
    creds = flow.run_local_server(port=8502)
    return {
        'token': creds.token,
        'refresh_token': creds.refresh_token,
        'token_uri': creds.token_uri,
        'client_id': creds.client_id,
        'client_secret': creds.client_secret,
        'scopes': list(creds.scopes)
    }

def get_gmail_service(creds_dict):
    creds = Credentials(
        token=creds_dict['token'],
        refresh_token=creds_dict['refresh_token'],
        token_uri=creds_dict['token_uri'],
        client_id=creds_dict['client_id'],
        client_secret=creds_dict['client_secret'],
        scopes=creds_dict['scopes']
    )
    if creds.expired and creds.refresh_token:
        creds.refresh(Request())
    return build('gmail', 'v1', credentials=creds)

st.set_page_config(page_title="Smart Inbox", page_icon="📬", layout="wide")
st.title("📬 Smart Inbox")
st.caption("AI-powered inbox that shows only what matters")

if 'credentials' not in st.session_state:
    st.session_state.credentials = None

if st.session_state.credentials is None:
    st.markdown("### Welcome! Please login with your Google account.")
    st.markdown("Your emails stay private — we only read them to classify importance.")
    st.divider()

    if st.button("🔐 Login with Google", type="primary"):
        with st.spinner("Opening Google login..."):
            try:
                creds = login_with_google()
                st.session_state.credentials = creds
                st.rerun()
            except Exception as e:
                st.error(f"Login failed: {e}")
else:
    service = get_gmail_service(st.session_state.credentials)

    col1, col2, col3 = st.columns(3)

    if st.button("🔄 Fetch & Classify Emails", type="primary"):
        with st.spinner("Fetching your emails..."):
            emails = get_emails_from_service(service)

        important = []
        skipped = []

        progress = st.progress(0)
        status = st.empty()

        for i, email in enumerate(emails):
            status.text(f"Classifying email {i+1} of {len(emails)}...")
            result = classify_email(email)
            if result['importance'] == 'high':
                important.append((email, result))
            else:
                skipped.append((email, result))
            progress.progress((i + 1) / len(emails))

        progress.empty()
        status.empty()

        with col1:
            st.metric("Total Fetched", len(emails))
        with col2:
            st.metric("Important", len(important))
        with col3:
            st.metric("Filtered Out", len(skipped))

        st.divider()

        if important:
            st.subheader("✅ Important Emails")
            for email, result in important:
                cat_colors = {
                    "work": "🔵",
                    "personal": "🟢",
                    "spam": "🔴",
                    "newsletter": "🟡"
                }
                icon = cat_colors.get(result['category'], "⚪")
                st.markdown(f"### {icon} {email['subject']}")
                st.markdown(f"**From:** {email['sender']}")
                st.markdown(f"**Category:** {result['category'].upper()}")
                st.markdown(f"**Why important:** {result['reason']}")
                with st.expander("Show email body"):
                    st.text(email['body'][:500])
                st.divider()
        else:
            st.info("No important emails found!")

        if skipped:
            with st.expander(f"🗑️ See {len(skipped)} filtered out emails"):
                for email, result in skipped:
                    st.markdown(f"- **{email['subject']}** — {result['reason']}")

    if st.button("Logout"):
        st.session_state.credentials = None
        st.rerun()