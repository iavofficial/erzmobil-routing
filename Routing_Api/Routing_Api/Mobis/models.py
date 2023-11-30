from datetime import datetime
from dateutil.parser import parse
from typing import List

from django.db import models
from django.db.models.expressions import RawSQL

from routing.routingClasses import MobyLoad, VehicleCapacity

class LocationManager(models.Manager):
    def nearest(self, latitude, longitude, n_nearest=1):
        return self.nearby(latitude, longitude)[:n_nearest]
    # from https://stackoverflow.com/a/26219292
    def nearby(self, latitude, longitude, proximity=50000):
        """
        Return all object which distance to specified coordinates
        is less than proximity given in kilometers
        """
        # Great circle distance formula
        gcd = """
              6371 * acos(
               cos(radians(%s)) * cos(radians(latitude))
               * cos(radians(longitude) - radians(%s)) +
               sin(radians(%s)) * sin(radians(latitude))
              ) * 1000
              """
        return self.get_queryset()\
                   .exclude(latitude=None)\
                   .exclude(longitude=None)\
                   .annotate(distance=RawSQL(gcd, (latitude,
                                                   longitude,
                                                   latitude)))\
                   .filter(distance__lt=proximity)\
                   .order_by('distance')
class Station(models.Model):
    uid = models.PositiveIntegerField(unique=True, null=False)
    name = models.CharField(max_length=256)
    community = models.PositiveIntegerField(null=False)
    objects = LocationManager()
    latitude = models.FloatField(null=False)
    longitude = models.FloatField(null=False)
    mapId = models.CharField(max_length=256, null=True)
    def __str__(self):
        return f'<Station({self.name}/{self.mapId}, {self.community}, ({self.latitude}, {self.longitude}))>'
class Bus(models.Model):
    uid  = models.PositiveIntegerField(unique=True)
    name = models.CharField(max_length=256, null=True)
    community = models.PositiveIntegerField(null=True)
    capacity = models.IntegerField(null=False)
    capacity_wheelchair = models.IntegerField(null=False, default=0)
    capacity_blocked_per_wheelchair = models.IntegerField(null=False, default=2)
    latitude = models.FloatField(null=True, default=None)
    longitude = models.FloatField(null=True, default=None)

    def capa_sufficient_for_load(self, load_needed: MobyLoad):
        # print(load_needed.standardSeats)
        bus_capa_tmp: VehicleCapacity = VehicleCapacity(self.capacity, self.capacity_wheelchair, self.capacity_blocked_per_wheelchair)

        # if nobody enters the bus, capa is sufficient, of course
        if load_needed.standardSeats <= 0 and load_needed.wheelchairs <= 0:
            return True

        return bus_capa_tmp.is_load_allowed(load_needed.standardSeats, load_needed.wheelchairs)

class RouteManager(models.Manager):
    def finished(self):
        return self.get_queryset().filter(status=Route.FINISHED)
    def started(self):
        return self.get_queryset().filter(status=Route.STARTED)
    def booked(self):
        return self.get_queryset().filter(status=Route.BOOKED)
    def frozen(self):
        return self.get_queryset().filter(status=Route.FROZEN)
    def blocking(self):
        return self.get_queryset().filter(status__in=[Route.FROZEN, Route.STARTED, Route.FINISHED])
    def to_be_deleted(self):
        return self.get_queryset().filter(status = Route.FINISHED)
    def empty(self):
        return self.get_queryset().filter(nodes__isnull=True)

    def to_be_deleted_oldest(self, num_routes_remaininig) -> dict:
        # extract the oldest delete candidates
        delete_candidates_all = self.to_be_deleted().order_by('id')

        id_date: dict[int, datetime] = {}
        id_route: dict = {}
        routes_to_delete_final: dict = {}

        if delete_candidates_all.count() > num_routes_remaininig:
            # find out oldest routes and reduce list  
            # ordered by tMin of first node
            # if nodes are empty: use default date      

            time_none: datetime = parse('1950-01-01T06:00.000+00:00')
            for route in delete_candidates_all:
                id_route[route.id] = route

                if route.nodes.count():
                    #print(route.nodes.first().tMin)
                    id_date[route.id] = route.nodes.first().tMin
                else:
                    id_date[route.id] = time_none


            # print(id_date) 
            # print(len(id_date))
            
            # sort ids by date            
            id_date_sorted = sorted(id_date, key=id_date.get)

            # extract delete candidates and save in final data
            for key in id_date_sorted:
                routes_to_delete_final[key] = id_route[key]

                if len(routes_to_delete_final) + num_routes_remaininig == len(id_date):
                    # break if number of remaining routes is reached
                    break

            # print(routes_to_delete_final)
            # print(len(routes_to_delete_final))           

        # return a dictionary of (id, route) with the routes to be deleted
        return routes_to_delete_final

class Route(models.Model):

    DRAFT = 'DRF'
    BOOKED = 'BKD'
    FROZEN = 'FRZ'
    STARTED = 'STR'
    FINISHED = 'FNS'

    STATUSES = ((DRAFT, 'Draft'), (BOOKED, 'Booked'), (FROZEN, 'Frozen'), (STARTED, 'Started'), (FINISHED, 'Finished'))

    bus = models.ForeignKey(Bus, related_name='routes', on_delete=models.PROTECT, null=False)
    status = models.CharField(max_length=3, choices=STATUSES, default=DRAFT)
    community = models.PositiveIntegerField(null=True)

    objects = RouteManager()

    @property
    def busId(self):
        return self.bus.uid
    
    @staticmethod
    def with_busId(busId, *args, **kwargs):
        bus = Bus.objects.get(uid=busId)
        return Route(bus=bus, community=bus.community, *args, **kwargs)

    def clients(self):
        hopOns = set()
        hopOffs = set()
        # iterate over the Node objects that are associated with the current Route object
        # from Route, get the Nodes and from the Nodes access the Orders via the related_name attribute (see Order model)
        # node.hopOns checks if there are any orders which have this node as a hopOn (same for node.hopOffs)
        for node in self.nodes.prefetch_related('hopOns', 'hopOffs').all():
            if node.hopOns.count() > 0:
                hopOns = hopOns.union(order.uid for order in node.hopOns.all())     # collect the order id, where someone is hopping on
            if node.hopOffs.count() > 0:
                hopOffs = hopOffs.union(order.uid for order in node.hopOffs.all())  # collect the order id, where someone is hopping off
        return set.union(hopOns, hopOffs)
    
    @property
    def loads(self) -> List[MobyLoad]:
        load = MobyLoad(0,0)
        cummulative_load: List[MobyLoad] = []

        for node in self.nodes.prefetch_related('hopOns', 'hopOffs'):
            load += node.loadAll_change
            cummulative_load.append(load)
        return cummulative_load
    
    @property
    def needed_capacity(self):
        max_load:MobyLoad = MobyLoad(0,0)
        loadsAll:List[MobyLoad] = self.loads

        for loadTmp in loadsAll:
            max_load.standardSeats = max(max_load.standardSeats,loadTmp.standardSeats)
            max_load.wheelchairs = max(max_load.wheelchairs,loadTmp.wheelchairs)            

        return max_load
    

    @property
    def draft(self):
        return self.status == self.DRAFT
    @property
    def booked(self):
        return self.status == self.BOOKED
    @property
    def finished(self):
        return self.status == self.FINISHED
    @property
    def started(self):
        return self.status == self.STARTED
    @property
    def frozen(self):
        return self.status == self.FROZEN
    @property
    def blocking(self):
        return self.status in [self.FROZEN, self.STARTED, self.FINISHED]
    
    def start(self):
        self.status = self.STARTED
    def finish(self):
        self.status = self.FINISHED
    def freeze(self):
        self.status = self.FROZEN
    
    def __str__(self):
        return f'<Route({self.status}, bus={self.busId}, {len(self.clients())} clients)>'

class Node(models.Model):
    mapId = models.CharField(max_length=64, null=True)
    tMin = models.DateTimeField()
    tMax = models.DateTimeField()
    latitude = models.FloatField(null=True)
    longitude = models.FloatField(null=True)
    route = models.ForeignKey(Route, related_name='nodes', null=True, on_delete=models.CASCADE)

    class Meta:
        ordering = ['tMin']

    def equalsStation(self, station)->bool:
        if self.mapId == station.mapId:
            return True
        
        if self.latitude is not None and abs(self.latitude - station.latitude) < 1e-6 and self.longitude is not None and abs(self.longitude - station.longitude) < 1e-6:
            return True

        return False
    
    def __str__(self):
        mapID = "None"

        if self.mapId is not None:
            mapID = self.mapId

        return f'<Node(id={self.id},mapId={mapID}, tMin/tMax({self.tMin}-{self.tMax}), hopOns/hopOffs({self.hopOns}, {self.hopOffs}), route_id({self.route.id}), lat/lon({self.latitude},{self.longitude}))>'
    
    @property
    def loadSeats_hopOns(self):
        return sum(o.load for o in self.hopOns.all())

    @property
    def loadWheelchair_hopOns(self):
        return sum(o.loadWheelchair for o in self.hopOns.all())

    @property
    def loadAll_hopOns(self):
        return MobyLoad(self.loadSeats_hopOns, self.loadWheelchair_hopOns)
    
    @property
    def loadSeats_hopOffs(self):
        return sum(o.load for o in self.hopOffs.all())

    @property
    def loadWheelchair_hopOffs(self):
        return sum(o.loadWheelchair for o in self.hopOffs.all())

    @property
    def loadAll_hopOffs(self):
        return MobyLoad(self.loadSeats_hopOffs, self.loadWheelchair_hopOffs)

    @property
    def loadSeats_change(self):
        return self.loadSeats_hopOns - self.loadSeats_hopOffs 

    @property
    def loadWheelchair_change(self):
        return self.loadWheelchair_hopOns - self.loadWheelchair_hopOffs 

    @property
    def loadAll_change(self):
        return MobyLoad(self.loadSeats_change, self.loadWheelchair_change)


    @property
    def has_order(self)->bool:
        if self.hopOns.count() > 0 or self.hopOffs.count() > 0:
            return True
        else:
            return False

class Order(models.Model):
    uid = models.PositiveIntegerField(unique=True)
    load = models.IntegerField(null=False, default=1)
    loadWheelchair = models.IntegerField(null=False, default=0)
    hopOnNode  = models.ForeignKey(Node, related_name='hopOns', on_delete=models.SET_NULL, null=True)
    hopOffNode = models.ForeignKey(Node, related_name='hopOffs', on_delete=models.SET_NULL, null=True)
    group_id = models.PositiveIntegerField(null=True, default=None)

    class Meta:
        ordering = ['uid']

    def __str__(self):
        return f'<Order(uid={self.uid}, load={self.load}), loadWheelchair={self.loadWheelchair}), hopOn={self.hopOnNode.pk}, hopOff={self.hopOffNode.pk})>'
