"""Application layer: config, database, authentication.

Importing this package must stay cheap: the bot-only entry points
(``main.py``) never import SQLAlchemy or argon2.
"""
