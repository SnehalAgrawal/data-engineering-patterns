# Minimal Superset configuration for local use. Metadata lives in SQLite under /app/superset_home.
import os

SECRET_KEY = os.environ["SUPERSET_SECRET_KEY"]
SQLALCHEMY_DATABASE_URI = "sqlite:////app/superset_home/superset.db"
