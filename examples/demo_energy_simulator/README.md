# Demo energy simulator

A small, self-contained building energy-simulation service, bundled with the
platform as the worked example for the **API submission** tab. It started life as
a cloud service; here it runs locally in Docker with the same behaviour, just
pointed at a local endpoint and with auth off.

## What it does

`POST /api/energy_simulation` takes a converted Digicities scenario:

```json
{
  "service_name": "demo_energy_simulator",
  "scenario_data": {
    "location": {
      "weather_data": "",
      "buildings": [
        {"SIA2024BuildingType": "MFH", "BuildingAge": "1990",
         "GroundFloorArea": 284, "NumberOfFloors": 4,
         "HeatingSupply": "GasHeated", "DHWSupply": "GasHeated"}
      ]
    }
  }
}
```

It estimates hourly heating / hot-water / electrical demand per building and
returns `{success, scenario_id, result_url, api_url, summary}`. `result_url` is an
HTML results page (`/api/energy_simulation/view/<id>`); full JSON is at
`/api/energy_simulation/results/<id>`. Weather comes from the EPW named in
`weather_data` if present, otherwise a synthetic year — so it runs with no
external data.

## Running

Brought up by the platform's `docker-compose.yml` as service
`demo_energy_simulator` (host port 5001). From the Streamlit app, register the
endpoint `http://demo_energy_simulator:5000/api/energy_simulation` in the API
submission tab (no auth). Standalone:

```bash
docker build -t demo-energy-simulator .
docker run -p 5001:5000 demo-energy-simulator
curl localhost:5001/api/energy_simulation/sample
```

## Auth

Open by default (`AUTH_ENABLED=false`). To require a key, set `AUTH_ENABLED=true`
and `API_KEY=<key>` (sent as `X-API-Key`).
