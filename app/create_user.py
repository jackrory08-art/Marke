"""Create the owner account: ``python -m app.create_user --username NAME``.

There are no default credentials and no registration route. The password is
read with ``getpass`` (never from argv) and must be at least 12 characters.
"""

import argparse
import getpass
import os
import sys
from typing import Optional

from app import repo
from app.auth import hash_password, validate_password_strength
from app.db import Database, init_database


class CreateUserError(Exception):
    pass


def create_user(db: Database, username: str, password: str, add: bool = False) -> int:
    username = username.strip().lower()
    if not username:
        raise CreateUserError("Username must not be empty")
    problem = validate_password_strength(password)
    if problem:
        raise CreateUserError(problem)
    with db.session() as s:
        if repo.count_users(s) > 0 and not add:
            raise CreateUserError(
                "A user already exists. Pass --add to create another account.")
        if repo.get_user_by_username(s, username) is not None:
            raise CreateUserError(f"User '{username}' already exists")
        user = repo.create_user(s, username, hash_password(password))
        repo.add_audit(s, "user_created", user_id=user.id, detail={"username": username})
        return user.id


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Create a dashboard user")
    parser.add_argument("--username", required=True)
    parser.add_argument("--add", action="store_true",
                        help="allow creating a user when one already exists")
    parser.add_argument("-c", "--config", default=os.environ.get("MARKE_CONFIG", "config.yaml"))
    args = parser.parse_args(argv)

    try:
        from dotenv import load_dotenv
        load_dotenv()
    except ImportError:  # pragma: no cover
        pass
    from utils.config_loader import load_config
    config = load_config(args.config)

    password = getpass.getpass("Password: ")
    if password != getpass.getpass("Repeat password: "):
        print("Passwords do not match", file=sys.stderr)
        return 1

    db = init_database(config.database.url, config.database.auto_migrate)
    try:
        create_user(db, args.username, password, add=args.add)
    except CreateUserError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1
    finally:
        db.dispose()
    print(f"Created user '{args.username.strip().lower()}'")
    return 0


if __name__ == "__main__":
    sys.exit(main())
