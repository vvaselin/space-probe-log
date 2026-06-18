from app.api import admin, health, logs, probe, settings, simulation, world

routers = [health.router, admin.router, probe.router, logs.router, world.router, settings.router, simulation.router]
