import anthropic
from gmail import get_emails

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
- It is from a real person 
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
    import json
    result = message.content[0].text
    result = result.strip().replace('```json', '').replace('```', '')
    return json.loads(result)

def run_smart_inbox():
    print("Fetching your emails...")
    emails = get_emails(10)

    print("Running AI classification...\n")
    print("=" * 50)
    print("YOUR SMART INBOX — IMPORTANT EMAILS ONLY")
    print("=" * 50)

    important = []
    skipped = []

    for email in emails:
        result = classify_email(email)
        if result['importance'] == 'high':
            important.append((email, result))
        else:
            skipped.append((email, result))

    print(f"\nFound {len(important)} important emails out of {len(emails)} total\n")

    for email, result in important:
        print(f"From    : {email['sender']}")
        print(f"Subject : {email['subject']}")
        print(f"Category: {result['category']}")
        print(f"Reason  : {result['reason']}")
        print("-" * 50)

    print(f"\nFiltered out {len(skipped)} unimportant emails (spam/newsletters/low priority)")

if __name__ == '__main__':
    run_smart_inbox()