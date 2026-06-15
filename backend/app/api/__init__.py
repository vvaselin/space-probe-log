from app.api import health, logs, probe, settings, simulation, world

routers = [health.router, probe.router, logs.router, world.router, settings.router, simulation.router]
