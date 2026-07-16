# SPDX-License-Identifier: Apache-2.0
# Copyright © 2026, Empa, James Allan, Reto Fricker

"""Demo energy simulator — standalone Flask service.

A self-contained building energy-simulation service bundled with the platform as
the worked API-submission example. It exposes the same endpoints the platform's
API submission tab expects (POST /api/energy_simulation returning
{success, scenario_id, result_url, summary}), runs a lightweight heuristic
simulation, and falls back to synthetic weather so it needs no external data.

Run locally via docker-compose (see the platform's docker-compose.yml); the API
submission tab points at http://demo_energy_simulator:5000/api/energy_simulation.
"""
from flask import Flask, jsonify
from flask_cors import CORS

from energy_sim_bp import energy_sim_bp


def create_app() -> Flask:
    app = Flask(__name__)
    CORS(app)
    # Blueprint routes live under /api (matches the cloud service it replaces).
    app.register_blueprint(energy_sim_bp, url_prefix="/api")

    @app.get("/health")
    def health():
        return jsonify({"status": "ok", "service": "demo_energy_simulator"})

    return app


app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
