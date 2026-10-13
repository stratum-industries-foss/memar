"""
Database migration: Add WebAuthn tables for passkey support.

Run this script to add webauthn_credentials and webauthn_challenges tables to the database.
"""

import sqlite3
import sys
from pathlib import Path


def migrate(db_path: str) -> None:
    """Add WebAuthn tables to the database."""
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    try:
        # Create webauthn_credentials table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS webauthn_credentials (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                credential_id TEXT NOT NULL UNIQUE,
                public_key TEXT NOT NULL,
                sign_count INTEGER DEFAULT 0 NOT NULL,
                transports TEXT,
                name TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP NOT NULL,
                last_used TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users(id)
            )
        """)

        # Create index on user_id for faster queries
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS ix_webauthn_credentials_user_id
            ON webauthn_credentials(user_id)
        """)

        # Create webauthn_challenges table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS webauthn_challenges (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                challenge TEXT NOT NULL UNIQUE,
                challenge_type TEXT NOT NULL,
                expires_at TIMESTAMP NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP NOT NULL,
                FOREIGN KEY (user_id) REFERENCES users(id)
            )
        """)

        # Create index on user_id for faster queries
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS ix_webauthn_challenges_user_id
            ON webauthn_challenges(user_id)
        """)

        conn.commit()
        print("✅ WebAuthn tables created successfully")

    except sqlite3.OperationalError as e:
        if "already exists" in str(e):
            print("✅ WebAuthn tables already exist")
        else:
            print(f"❌ Error: {e}")
            conn.close()
            sys.exit(1)
    finally:
        conn.close()


if __name__ == "__main__":
    # Default to MEMAR_DB_PATH if not provided
    import os
    db_path = os.getenv("MEMAR_DB_PATH", "/var/lib/memar/memar.db")

    if len(sys.argv) > 1:
        db_path = sys.argv[1]

    print(f"Migrating database: {db_path}")
    migrate(db_path)
    print("✅ Migration complete")
