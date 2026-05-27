"""
Lab Assistant - Initial Setup Script
Run once after installation:  python scripts/setup.py
"""

import os
import sys
import subprocess
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

# Change to project root so manage.py works correctly
os.chdir(BASE_DIR)


def run(cmd):
    print(f"\n▶  {cmd}")
    result = subprocess.run(cmd, shell=True)
    if result.returncode != 0:
        print(f"   ✗ Command failed (exit code {result.returncode})")
        return False
    print("   ✓ Done")
    return True


def main():
    print("=" * 60)
    print("  LabAssist AI — Initial Setup")
    print("=" * 60)

    # 1. Create required directories
    print("\n[1/6] Creating directories…")
    dirs = [
        BASE_DIR / "db",
        BASE_DIR / "data" / "uploads" / "documents",
        BASE_DIR / "data" / "chroma_db",
        BASE_DIR / "data" / "faiss_index",
        BASE_DIR / "logs",
        BASE_DIR / "staticfiles",
    ]
    for d in dirs:
        d.mkdir(parents=True, exist_ok=True)
        print(f"   ✓ {d}")

    # 2. Create .env if not exists
    print("\n[2/6] Creating .env file…")
    env_file = BASE_DIR / ".env"
    if not env_file.exists():
        env_content = (
            "# Lab Assistant Environment Configuration\n"
            "DJANGO_SECRET_KEY=change-this-to-a-random-secret-key-in-production\n"
            "DEBUG=True\n"
            "ALLOWED_HOSTS=localhost,127.0.0.1\n\n"
            "# Ollama\n"
            "OLLAMA_BASE_URL=http://localhost:11434\n"
            "OLLAMA_MODEL=llama3\n\n"
            "# Vector Store: chroma | faiss\n"
            "VECTOR_STORE_TYPE=chroma\n\n"
            "# Embedding model\n"
            "EMBEDDING_MODEL=sentence-transformers/all-MiniLM-L6-v2\n\n"
            "# SampleManager LIMS Database\n"
            "LIMS_DB_ENGINE=mssql\n"
            "LIMS_DB_HOST=localhost\n"
            "LIMS_DB_PORT=1433\n"
            "LIMS_DB_NAME=SAMPLEMANAGER\n"
            "LIMS_DB_USER=lims_readonly\n"
            "LIMS_DB_PASSWORD=\n"
        )
        env_file.write_text(env_content)
        print(f"   ✓ Created {env_file}")
        print("   ⚠  Edit .env with your LIMS database credentials!")
    else:
        print(f"   ✓ .env already exists")

    # 3. Run migrations
    print("\n[3/6] Running database migrations…")
    mkmig_ok = run("python manage.py makemigrations")
    mig_ok   = run("python manage.py migrate")

    if not mig_ok:
        print("\n   ✗ Migration failed — cannot create admin user without database.")
        print("   Fix the error above, then re-run this script.")
        print("\n[4/6] Collecting static files…")
        run("python manage.py collectstatic --noinput")
        sys.exit(1)

    # 4. Collect static files
    print("\n[4/6] Collecting static files…")
    run("python manage.py collectstatic --noinput")

    # 5. Create superuser
    print("\n[5/6] Create admin user…")

    # Django must be fully set up before importing models
    import django
    django.setup()

    from django.contrib.auth.models import User, Group

    username = input("   Admin username [admin]: ").strip() or "admin"
    email    = input("   Admin email: ").strip()

    import getpass
    password = getpass.getpass("   Admin password: ")

    if password:
        if User.objects.filter(username=username).exists():
            user = User.objects.get(username=username)
            user.set_password(password)
            user.email = email
            user.save()
            print(f"   ✓ Updated existing user '{username}'")
        else:
            User.objects.create_superuser(
                username=username, email=email, password=password
            )
            print(f"   ✓ Created superuser '{username}'")

        # Create default role groups
        for group_name in ["LAB_ANALYST", "LAB_SUPERVISOR", "LIMS_ADMIN", "READ_ONLY"]:
            Group.objects.get_or_create(name=group_name)
        print("   ✓ Created user role groups")
    else:
        print("   ⚠ Skipped user creation (no password provided)")
        print("   Run later:  python manage.py createsuperuser")

    # 6. Check Ollama
    print("\n[6/6] Checking Ollama…")
    import requests
    try:
        r = requests.get("http://localhost:11434/api/tags", timeout=5)
        models = [m["name"] for m in r.json().get("models", [])]
        if models:
            print(f"   ✓ Ollama running. Models: {', '.join(models)}")
        else:
            print("   ⚠ Ollama running but no models found.")
            print("   Run:  ollama pull llama3")
    except Exception:
        print("   ✗ Ollama not reachable at http://localhost:11434")
        print("   Download: https://ollama.com/download")
        print("   Then run: ollama pull llama3")

    print("\n" + "=" * 60)
    print("  Setup complete!")
    print("=" * 60)
    print("\nTo start the server:")
    print("  python manage.py runserver")
    print("\nWith WebSocket streaming support (recommended):")
    print("  daphne -b 127.0.0.1 -p 8000 config.asgi:application")
    print("\nOpen browser: http://localhost:8000")
    print()


if __name__ == "__main__":
    main()
