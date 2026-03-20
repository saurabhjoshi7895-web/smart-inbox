import requests

def get_telegram_messages(bot_token, max_messages=20):
    url = f"https://api.telegram.org/bot{bot_token}/getUpdates"
    response = requests.get(url)
    data = response.json()

    if not data.get('ok'):
        return []

    messages = []
    for update in data.get('result', []):
        message = update.get('message', {})
        if not message:
            continue

        sender = message.get('from', {})
        sender_name = f"{sender.get('first_name', '')} {sender.get('last_name', '')}".strip()
        username = sender.get('username', 'unknown')
        text = message.get('text', '')
        date = message.get('date', 0)

        if text:
            messages.append({
                'sender': f"{sender_name} (@{username})",
                'subject': text[:50],
                'body': text,
                'source': 'telegram'
            })

    return messages[-max_messages:]

if __name__ == '__main__':
    import os
    token = input("Enter your bot token: ")
    msgs = get_telegram_messages(token)
    for m in msgs:
        print(f"From: {m['sender']}")
        print(f"Message: {m['body']}")
        print("-" * 30)