# BIZBRIDGE v2

Features: accounts/login, SQLite database, photo/video posts, likes, comments, follow/unfollow, one-to-one text messages, blogs, search, mobile-responsive UI.

Deploy as a Python Web Service, not as a static Netlify ZIP:
- Build command: `pip install -r requirements.txt`
- Start command: `gunicorn app:app`

Important: starter prototype only. Messaging is refresh-based (not realtime). Local uploads/SQLite can be lost on hosts with ephemeral storage. For persistent public launch, configure persistent storage or managed database/object storage, and add CSRF protection, email verification, password reset, moderation/reporting, rate limiting, backups, and video processing. Do not treat this as production-ready.
