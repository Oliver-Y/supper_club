#!/usr/bin/env bash
set -e

echo "=== Supper Club Setup ==="

# Install Python deps
pip install -r requirements.txt

# Create .env if missing
if [ ! -f .env ]; then
    SECRET_KEY=$(python3 -c "import secrets; print(secrets.token_hex(32))")
    read -p "Admin password: " ADMIN_PASSWORD
    echo "SECRET_KEY=$SECRET_KEY" > .env
    echo "ADMIN_PASSWORD=$ADMIN_PASSWORD" >> .env
    echo "Created .env"
fi

# Install cloudflared if missing
if ! command -v cloudflared &>/dev/null; then
    echo "Installing cloudflared..."
    if [ "$(uname)" = "Linux" ]; then
        curl -fsSL https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64 -o /usr/local/bin/cloudflared
        chmod +x /usr/local/bin/cloudflared
    elif [ "$(uname)" = "Darwin" ]; then
        brew install cloudflared
    fi
fi

echo ""
echo "Starting gunicorn + cloudflare tunnel..."
echo "Press Ctrl+C to stop."
echo ""

# Start gunicorn in background
gunicorn app:app -b 127.0.0.1:8000 &
GUNICORN_PID=$!

# Start tunnel (prints the public URL)
cloudflared tunnel --url http://127.0.0.1:8000 &
TUNNEL_PID=$!

# Clean up both on exit
trap "kill $GUNICORN_PID $TUNNEL_PID 2>/dev/null" EXIT
wait
