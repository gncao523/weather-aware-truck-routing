import logging

from django.conf import settings
from django.http import FileResponse, Http404, HttpRequest
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from .serializers import HeatmapRequestSerializer, PlanRequestSerializer
from .services import geocoding
from .services.heatmap import build_heatmap
from .services.http import UpstreamError
from .services.planner import Place, TripRequest, plan_trip

logger = logging.getLogger(__name__)


def _upstream_error(exc: UpstreamError) -> Response:
    logger.warning("Upstream failure: %s", exc)
    return Response({"detail": str(exc)}, status=exc.status_code)


class HealthView(APIView):
    throttle_classes: list = []

    def get(self, request: Request) -> Response:
        return Response({"status": "ok"})


class GeocodeView(APIView):
    throttle_scope = "geocode"

    def get(self, request: Request) -> Response:
        query = request.query_params.get("q", "").strip()
        if len(query) < 2:
            return Response({"results": []})
        try:
            return Response({"results": geocoding.search(query[:200])})
        except UpstreamError as exc:
            return _upstream_error(exc)


class PlanView(APIView):
    throttle_scope = "plan"

    def post(self, request: Request) -> Response:
        s = PlanRequestSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        d = s.validated_data
        trip = TripRequest(
            origin=Place(**d["origin"]),
            destination=Place(**d["destination"]),
            departure=d["departure"],
            load_lbs=d["load_lbs"],
            interval_mi=int(d["interval_miles"]),
        )
        try:
            return Response(plan_trip(trip))
        except UpstreamError as exc:
            return _upstream_error(exc)


class HeatmapView(APIView):
    throttle_scope = "heatmap"

    def post(self, request: Request) -> Response:
        s = HeatmapRequestSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        d = s.validated_data
        try:
            return Response(build_heatmap(d["routes"], d["departure"].timestamp(), d["load_lbs"]))
        except UpstreamError as exc:
            return _upstream_error(exc)


def spa_index(request: HttpRequest) -> FileResponse:
    """Serve the built React app for client-side routes."""
    index = settings.FRONTEND_DIST / "index.html"
    if not index.is_file():
        raise Http404("Frontend not built. Run `npm run build` in /frontend or use the Vite dev server.")
    return FileResponse(index.open("rb"), content_type="text/html")
