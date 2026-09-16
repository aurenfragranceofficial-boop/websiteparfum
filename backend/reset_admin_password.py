"""
Reset or create the admin user using values from .env.
Usage:
  python reset_admin_password.py new_password

Requires: python-dotenv, pymongo, bcrypt
Install with:
  pip install python-dotenv pymongo bcrypt

The script reads MONGO_URL, DB_NAME, ADMIN_EMAIL from backend/.env and will
create or update the admin user with the provided password.
"""
import sys
from dotenv import load_dotenv
from pathlib import Path
import os
import uuid
from datetime import datetime, timezone
import bcrypt
from pymongo import MongoClient

ROOT = Path(__file__).parent
load_dotenv(ROOT / '.env')

MONGO_URL = os.environ.get('MONGO_URL')
DB_NAME = os.environ.get('DB_NAME', 'auren')
ADMIN_EMAIL = os.environ.get('ADMIN_EMAIL', 'aurenfragranceofficial@gmail.com')

if not MONGO_URL:
    print('MONGO_URL not set in backend/.env')
    sys.exit(1)

if len(sys.argv) < 2:
    print('Usage: python reset_admin_password.py <new_password>')
    sys.exit(1)

new_password = sys.argv[1]

client = MongoClient(MONGO_URL)
db = client[DB_NAME]

users = db.users

now = datetime.now(timezone.utc).isoformat()

hashed = bcrypt.hashpw(new_password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')

existing = users.find_one({'email': ADMIN_EMAIL.lower().strip()})
if existing:
    users.update_one({'email': ADMIN_EMAIL.lower().strip()}, {'$set': {'password_hash': hashed}})
    print(f'Updated password for {ADMIN_EMAIL}')
else:
    doc = {
        'id': str(uuid.uuid4()),
        'email': ADMIN_EMAIL.lower().strip(),
        'password_hash': hashed,
        'name': os.environ.get('ADMIN_NAME', 'Admin'),
        'role': 'admin',
        'created_at': now,
    }
    users.insert_one(doc)
    print(f'Created admin {ADMIN_EMAIL}')

print('Done.')
