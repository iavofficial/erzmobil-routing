from rest_framework import serializers

from .models import Route
from .models import Node
from .models import Station, Bus, Order

import ast

class OrderSerializer(serializers.ModelSerializer):
    orderId = serializers.IntegerField(source='uid') 
    seats = serializers.IntegerField(source='load')
    seatsWheelchair = serializers.IntegerField(source='loadWheelchair')
    class Meta:
        model=Order
        fields=('orderId', 'seats', 'seatsWheelchair')

class NodeSerializer(serializers.ModelSerializer):
    hopOns = OrderSerializer(many=True)
    hopOffs = OrderSerializer(many=True)
    class Meta:
        model=Node
        fields=('pk', 'mapId', 'tMin', 'tMax', 'hopOns', 'hopOffs', 'latitude', 'longitude')

class RouteSerializer(serializers.ModelSerializer):
    nodes = NodeSerializer(many=True)
    routeId = serializers.IntegerField(source='pk')
    status = serializers.ChoiceField(Route.STATUSES, source='get_status_display')
    #busId = serializers.PrimaryKeyRelatedField(many=True, read_only=True, pk_field='uid')

    class Meta:
        model=Route
        fields=('routeId', 'busId', 'status', 'nodes')

"""
utility classes for external information
"""
class StationSerializer(serializers.ModelSerializer):
    class Meta:
        model=Station
        fields=('uid', 'mapId', 'name', 'latitude', 'longitude', 'community')

class BusSerializer(serializers.ModelSerializer):
    class Meta:
        model=Bus
        fields=('uid', 'name', 'community', 'capacity', 'capacity_wheelchair', 'capacity_blocked_per_wheelchair')#, 'works')