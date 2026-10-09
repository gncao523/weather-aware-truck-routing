# Weather-Aware Truck Routing

[![CI](https://github.com/gncao523/weather-aware-truck-routing/actions/workflows/ci.yml/badge.svg)](https://github.com/gncao523/weather-aware-truck-routing/actions/workflows/ci.yml)

A web app that helps a truck driver pick the safest route. It checks the weather the truck will meet on the road, at the time it gets there.


## How it works

1. You enter a start, a destination, a departure time and the load weight.
2. The app finds 3 routes.
3. It places a checkpoint every 10, 25 or 50 miles and works out when the truck gets to each one.
4. It gets the weather forecast for that place at that time.
5. It gives each checkpoint a risk level using the rules below.
6. It recommends the safest route and says why.

The map shows the routes colored by risk, every checkpoint, a summary for each route, and a weather heatmap with a 0–48 hour slider.

## Risk rules

| | Low | Moderate | High | Severe | No Travel |
|---|---|---|---|---|---|
| Wind (mph) | <25 | 25–34 | 35–44 | 45–54 | ≥55 |
| Rain (in/hr) | <0.10 | 0.10–0.25 | 0.25–0.50 | 0.50–1.00 | >1.00 |
| Snow (in/hr) | <0.5 | 0.5–1.0 | 1.0–2.0 | 2.0–3.0 | >3.0 |

Heavy loads make wind more dangerous:

- 45–54 mph with more than 30,000 lb: No Travel
- 35–44 mph with more than 40,000 lb: Severe

A checkpoint gets the worst level of its wind, rain and snow.

## How the best route is picked

Routes are compared in this order:

1. Fewest No Travel miles
2. Fewest Severe miles
3. Fewest High miles
4. Lowest average risk
5. Shortest drive time

Steps 2–5 come from the brief. I added step 1 so a route that's unsafe to drive is never recommended.

## Run it locally

You need Python 3.11+ and Node 18+.

```bash
# backend (http://127.0.0.1:8000)
cd backend
python -m venv .venv
source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -r requirements.txt
DJANGO_DEBUG=1 python manage.py runserver

# frontend (http://localhost:5173)
cd frontend
npm install
npm run dev
```

On Windows PowerShell, start the backend with `$env:DJANGO_DEBUG=1; python manage.py runserver`.

## Tests

```bash
cd backend && python manage.py test planner
cd frontend && npm test
cd frontend && npx playwright install chromium && npm run test:e2e
```

These run automatically on GitHub after every push.

## Deploy

The whole app runs as one Docker container. On Render, choose **New → Blueprint** and select this repo.

## Free services used

No API keys needed:

- Routes: [OSRM](https://project-osrm.org/)
- Weather: [Open-Meteo](https://open-meteo.com/)
- Place search: [Photon](https://photon.komoot.io/)
- Map: [OpenFreeMap](https://openfreemap.org/)

## Limits

- Routes are for cars, so truck-only rules (low bridges, weight limits) aren't included.
- Drive times don't include rest breaks or traffic.
- You can plan up to 7 days ahead.
- On very long trips, nearby checkpoints share one weather lookup to stay within the free weather service's limits.
