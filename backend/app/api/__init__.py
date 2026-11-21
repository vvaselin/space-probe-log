from app.api import admin, health, voyage

routers = [health.router, admin.router, voyage.router]
