from datetime import UTC, datetime, timedelta

from rest_framework import serializers

from .services.geo import haversine_mi

MAX_DEPARTURE_AHEAD = timedelta(days=7)
MAX_DEPARTURE_PAST = timedelta(hours=2)
MAX_LOAD_LBS = 150_000


class PlaceSerializer(serializers.Serializer):
    lat = serializers.FloatField(min_value=-90, max_value=90)
    lon = serializers.FloatField(min_value=-180, max_value=180)
    label = serializers.CharField(required=False, allow_blank=True, max_length=300, default="")


def validate_departure(value: datetime) -> datetime:
    now = datetime.now(UTC)
    if value < now - MAX_DEPARTURE_PAST:
        raise serializers.ValidationError("Departure can't be more than 2 hours in the past.")
    if value > now + MAX_DEPARTURE_AHEAD:
        raise serializers.ValidationError("Departure must be within the next 7 days (forecast range).")
    return value


class PlanRequestSerializer(serializers.Serializer):
    origin = PlaceSerializer()
    destination = PlaceSerializer()
    departure = serializers.DateTimeField(validators=[validate_departure])
    load_lbs = serializers.FloatField(min_value=0, max_value=MAX_LOAD_LBS)
    interval_miles = serializers.ChoiceField(choices=[10, 25, 50])

    def validate(self, attrs):
        o, d = attrs["origin"], attrs["destination"]
        if haversine_mi(o["lat"], o["lon"], d["lat"], d["lon"]) < 1:
            raise serializers.ValidationError("Origin and destination must be at least 1 mile apart.")
        return attrs


class LineField(serializers.ListField):
    """A polyline as [[lon, lat], ...]."""

    child = serializers.ListField(child=serializers.FloatField(), min_length=2, max_length=2)

    def to_internal_value(self, data):
        line = super().to_internal_value(data)
        for lon, lat in line:
            if not (-180 <= lon <= 180 and -90 <= lat <= 90):
                raise serializers.ValidationError("Coordinates must be [lon, lat] in degrees.")
        return [(lon, lat) for lon, lat in line]


class HeatmapRequestSerializer(serializers.Serializer):
    routes = serializers.ListField(child=LineField(min_length=2, max_length=3000), min_length=1, max_length=3)
    departure = serializers.DateTimeField(validators=[validate_departure])
    load_lbs = serializers.FloatField(min_value=0, max_value=MAX_LOAD_LBS)
