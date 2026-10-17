# Operations and recovery

Keep the working directory stable: the default SQLite URL is relative to it.
Stop the bot before copying a SQLite database for a simple offline backup. Store
the copy outside the repository and verify recovery against a separate working
directory before replacing live data. Do not run two polling processes for one
token. PostgreSQL requires its own backup tooling and async SQLAlchemy driver.

The FSM store is in memory. Restarting loses in-progress registration and judging
conversations, but committed database rows remain. Ask affected users to restart
their action. Changing to persistent FSM storage is a separate deployment choice.

Common startup issues: a missing token, an invalid token format, a missing async
database driver or an unavailable database. Verify `.env`, dependency installation
and the database path before retrying. Application logs go to the console; capture
them using the process manager in a deployed environment.

CI uses only local fixtures and never requires a Telegram token or real bot
account. Run the same suite before deployment:

```bash
python -m unittest discover -s tests -v
```
