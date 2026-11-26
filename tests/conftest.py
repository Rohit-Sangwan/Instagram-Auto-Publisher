import atexit
import os
import tempfile

from cryptography.fernet import Fernet

root = tempfile.TemporaryDirectory()
atexit.register(root.cleanup)
os.environ.update({
    "DATA_DIR": root.name,
    "PUBLIC_URL": "http://localhost:5173",
    "ADMIN_USERNAME": "admin",
    "ADMIN_PASSWORD": "integration-test-password",
    "TOKEN_KEY": Fernet.generate_key().decode(),
    "MEDIA_SECRET": "integration-test-media-secret-long-enough",
})


def close_database():
    from app.db import engine
    engine.dispose()


atexit.register(close_database)
