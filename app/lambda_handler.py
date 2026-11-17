"""Punto de entrada de AWS Lambda: adapta la app FastAPI a eventos de API Gateway (HTTP API)."""

from mangum import Mangum

from app.main import app

handler = Mangum(app, lifespan="off")
