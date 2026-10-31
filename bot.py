import base64
import hashlib
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import instaloader
import requests
from cryptography.fernet import Fernet

STATE = Path('state.enc')


def telegram(token, method, payload):
    try:
        response = requests.post(f'https://api.telegram.org/bot{token}/{method}', json=payload, timeout=25)
        data = response.json()
        if not response.ok or not data.get('ok'):
            raise RuntimeError('Telegram request failed; check token, chat ID and Start.')
        return data['result']
    except requests.RequestException:
        raise RuntimeError('Telegram connection failed.') from None


def run():
    token = os.environ['TELEGRAM_BOT_TOKEN'].strip()
    if '--chat-id' in sys.argv:
        updates = telegram(token, 'getUpdates', {'timeout': 0, 'allowed_updates': ['message']})
        ids = sorted({u['message']['chat']['id'] for u in updates if u.get('message', {}).get('chat', {}).get('type') == 'private'})
        print('Private chat IDs:', ', '.join(map(str, ids)) or 'None: send /start to your bot and retry.')
        return 0
    chat = os.environ['TELEGRAM_CHAT_ID'].strip()
    username = os.environ['INSTAGRAM_USERNAME'].strip().lstrip('@')
    cipher = Fernet(base64.urlsafe_b64encode(hashlib.sha256(token.encode()).digest()))
    state = json.loads(cipher.decrypt(STATE.read_bytes())) if STATE.exists() else {}
    if state.get('username', username) != username:
        raise RuntimeError('Target changed: delete state.enc before using a new username.')

    def send(message):
        telegram(token, 'sendMessage', {'chat_id': chat, 'text': message})

    def save():
        STATE.write_bytes(cipher.encrypt(json.dumps(state, ensure_ascii=False).encode()))

    try:
        loader = instaloader.Instaloader(quiet=True, max_connection_attempts=1, request_timeout=25)
        profile = instaloader.Profile.from_username(loader.context, username)
        bio = profile.biography
        profile_id = str(profile.userid)
        if not isinstance(bio, str):
            raise ValueError('Missing biography')
        if state.get('profile_id', profile_id) != profile_id:
            raise ValueError('Username now belongs to a different account')
    except Exception:
        # Do not print provider exceptions: they may contain target data.
        if not state.get('unavailable'):
            send(f'تعذر فحص بايو @{username}. المراقبة غير مؤكدة حاليًا؛ قد يكون السبب تقييد إنستقرام أو عدم توفر الحساب. سأعيد المحاولة في الفحص التالي.')
        state.update(username=username, unavailable=True)
        save()
        print('Instagram check failed. Previous biography preserved.')
        return 1

    now = datetime.now(timezone.utc).isoformat(timespec='seconds')
    if 'bio' not in state:
        send(f'نجح أول فحص لبايو @{username}.\nالبايو الحالي:\n{bio or "(فارغ)"}\n\nالفحص مجدول كل 10 دقائق، وقد تتأخر الجدولة. هذا ليس إشعار تغيير.')
    elif state['bio'] != bio:
        send(f'تغير بايو @{username}\n\nالسابق:\n{state["bio"] or "(فارغ)"}\n\nالجديد:\n{bio or "(فارغ)"}\n\nوقت الرصد UTC: {now}\nوقت التغيير الفعلي غير معروف.')
    elif state.get('unavailable'):
        send(f'عادت قراءة بايو @{username} للعمل. البايو لم يتغير مقارنة بآخر قراءة ناجحة.')
    state.update(username=username, profile_id=profile_id, bio=bio, unavailable=False)
    save()
    print('Check succeeded. Encrypted state saved.')
    return 0


if __name__ == '__main__':
    try:
        sys.exit(run())
    except Exception:
        print('Run failed. Check secrets and encrypted state. No success is assumed.')
        sys.exit(1)
