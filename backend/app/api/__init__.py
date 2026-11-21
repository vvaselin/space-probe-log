from app.api import admin, health, logs, probe, settings, simulation, voyage, world

routers = [health.router, admin.router, probe.router, logs.router, world.router, settings.router, simulation.router, voyage.router]
