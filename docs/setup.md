# Local setup

Use Python 3.9 or newer. Run from the repository root:

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
cp .env.example .env
python main.py
```

Replace both placeholders before starting. `BOT_TOKEN` comes from Telegram
BotFather. Keep `.env` out of version control. `ADMIN_PASSWORD` accepts plaintext
for compatibility or a bcrypt hash; do not publish the configured value.
`DATABASE_URL` defaults to a SQLite file relative to the working directory.

The bot creates missing tables at startup. This is not a migration system:
changes to existing columns or constraints require a deliberate migration and a
backup first. Registration is started with `/start`; administration with
`/admin_login`. Only one process should consume updates for the same bot token.
