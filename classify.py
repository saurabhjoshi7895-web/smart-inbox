import anthropic

client = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY", ""))

test_email = {
    "sender": "boss@company.com",
    "subject": "Urgent: Meeting tomorrow at 9am",
    "body": "Hi, we have an important client meeting tomorrow. Please be prepared."
}

message = client.messages.create(
    model="claude-haiku-4-5-20251001",
    max_tokens=1000,
    messages=[
        {
            "role": "user",
            "content": f"""Classify this email and reply in JSON format only:

Sender: {test_email['sender']}
Subject: {test_email['subject']}
Body: {test_email['body']}

Reply with only this JSON:
{{
  "importance": "high or medium or low",
  "category": "work or personal or spam or newsletter",
  "reason": "one sentence why"
}}"""
        }
    ]
)

print("AI says:")
print(message.content[0].text)