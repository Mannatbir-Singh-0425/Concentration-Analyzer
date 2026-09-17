web: python -c "from app import init_db; init_db()" && gunicorn --bind 0.0.0.0:$PORT --workers 2 --threads 4 --preload --timeout 120 app:app
