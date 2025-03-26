""" API functions """
import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Tuple
from urllib import request

from dateutil.parser import parse
from dateutil.tz import tzutc
from django.db.models import Q
from django.http import Http404, HttpResponseBadRequest
from django.shortcuts import get_object_or_404
from rest_framework.exceptions import APIException
from rest_framework.response import Response

from routing.errors import DuplicatedOrder
from Routing_Api.mockups.db_busses import Busses
from Routing_Api.mockups.RoadClosures import RoadClosures
from routing.maps import Maps
from Routing_Api.mockups.stations import WebStations as Stations
from Routing_Api.Mobis.OrdersMQ import OrdersMQ as Orders
from Routing_Api.Mobis.RequestManager import RequestManager
from Routing_Api.Mobis.RoutesDummy import RoutesDummy as Routes
from Routing_Api.Mobis.SolverDummy import SolverDummy as Solver

from Routing_Api.Mobis.models import Bus, Node, Order, Route, Station
from Routing_Api.Mobis.serializers import NodeSerializer, RouteSerializer
from Routing_Api.Mobis.signals import RabbitMqListener as Listener
from Routing_Api.Mobis.signals import RabbitMqSender as Publisher
from Routing_Api.Mobis.RequestManagerConfig import RequestManagerConfig

# do not change order of ortools imports - may lead to segfaults in docker images (issue #246)
from ortools.constraint_solver import routing_enums_pb2
from ortools.constraint_solver import pywrapcp

UTC = tzutc()
API_URI = os.environ.get('BUSNOW_API_URI','http://directus:8055')
# API_URI = 'http://directus:8055'
print(API_URI)
LOGGER = logging.getLogger(__name__)


if os.environ.get('IS_CELERY_APP', 'no') != "yes":
    OSRM_url = None
    maps = None
    OSRM_activated = False

    # check if OSRM is enabled by environment
    # in this case: DO NOT LOAD MAPS - performance!
    osrmEnv = 'OSRM_API_URI'    

    if osrmEnv in os.environ and os.environ.get(osrmEnv) != 'NONE':
        osrmUrl = os.environ.get(osrmEnv,'http://router.project-osrm.org')    
        OSRM_activated = True
        LOGGER.info(f'OSRM_ACTIVATED, osrmUrl={osrmUrl}')
        print('OSRM_ACTIVATED')
    else:
        # load maps from files
        if os.path.isdir('../maps'):
            # print('apifunctions - load maps')
            # print(maps)
            maps = Maps(data_dir='../maps')
            LOGGER.info(f'maps={maps}')       
        else:
            LOGGER.info(f'could not locate a data directory with map data')       
            raise FileNotFoundError('could not locate a data directory with map data')
    
    Requests = RequestManager(
        Routes=Routes(Route=Route, Node=Node, Order=Order),
        Busses=Busses(busUrl=API_URI+'/items/bus',busAvailUrl=API_URI+'/customendpoints/operatingtime', BusDb=Bus, RouteDb=Route),
        Stations=Stations(stopUrl=API_URI+'/customendpoints/stops', StationDb=Station),
        Maps=maps,
        OSRM_activated = OSRM_activated,
        OSRM_url = OSRM_url,
        Solver=Solver(),
        Orders=Orders(MessageBus=Publisher(), Listener=Listener()), RoadClosures=RoadClosures(API_URI))

def GetRequestManager()->RequestManager:
    return Requests
    
def RouteCheck(startLocation, stopLocation, time, isDeparture, seatNumber=1, wheelchairNumber=0, routeId=None, alternatives_mode: str=None):
    """ Check, but don't book, a potential route request and return its possibility. """
    before = timedelta(minutes=10)
    after = timedelta(minutes=10)

    # convert to utc is essential for correct calculations
    time = datetime.fromtimestamp(time.timestamp(), tz=timezone.utc)

    if isDeparture:
        t_stop = None
        t_start = (time, time+after)
    else:
        t_start = None
        t_stop = (time-before, time)

    if routeId:
        routeId = int(routeId)

    # check mode of alternatives search
    alternatives_mode_checked = RequestManagerConfig.ALTERNATIVE_SEARCH_NONE    

    if alternatives_mode is not None:
        if alternatives_mode.upper() == 'EARLIER':
            alternatives_mode_checked = RequestManagerConfig.ALTERNATIVE_SEARCH_EARLIER
        elif alternatives_mode.upper() == 'LATER':
            alternatives_mode_checked = RequestManagerConfig.ALTERNATIVE_SEARCH_LATER

    try:
        result, code, message, time_windows, time_slot = Requests.is_bookable(
            start_location=startLocation, stop_location=stopLocation, start_window=t_start,
            stop_window=t_stop, load=seatNumber, loadWheelchair=wheelchairNumber, group_id=routeId, alternatives_mode=alternatives_mode_checked)

    except Exception as err:
        LOGGER.error(f'RouteCheck failed: {err}')
        raise APIException()

    found_times = []
    time_slot_res = []
    time_format = "%Y-%m-%dT%H:%M:%S%z"

    if time_slot and len(time_slot) > 1:
        time_slot_res.append(time_slot[0].strftime(time_format))
        time_slot_res.append(time_slot[1].strftime(time_format))

    for timeWindow in time_windows:
        if isDeparture:
            found_times.append(timeWindow[0].strftime(time_format))
        else:
            found_times.append(timeWindow[1].strftime(time_format))   

    responseData =  {'result': result, 'reasonCode': code, 'reasonText': message, 'alternativeTimes': found_times, 'timeSlot': time_slot}
    # print(f"DEBUGGING responseData in RouteCheck(): {responseData}")
    LOGGER.info(f'is_bookable response {responseData}')

    return Response(data=responseData)

def RouteRequest(startLocation, stopLocation, time, isDeparture, seatNumber=1, wheelchairNumber=0, routeId=None, orderId=None):
    """ Check and book, a potential route request and return its possibility. """

    # convert to utc is essential for correct calculations
    time = datetime.fromtimestamp(time.timestamp(), tz=timezone.utc)

    before = timedelta(minutes=10)
    after = timedelta(minutes=10)

    if isDeparture:
        t_start = (time, time+after)
        t_stop = None
    else:
        t_start = None
        t_stop = (time-before, after)

    if orderId:
        orderId = int(orderId)
    if routeId:
        routeId = int(routeId)
        
    try:
        solution = Requests.order(start_location=startLocation, stop_location=stopLocation, start_window=t_start,
                                stop_window=t_stop, load=seatNumber, loadwheelchair= wheelchairNumber, group_id=routeId, order_id=orderId)
    except DuplicatedOrder as err:
        message = f'DuplicatedOrder, Order_id={orderId} already exists: {err}'
        Requests.Orders.route_rejected(order_id=orderId, reason=message, start=startLocation, destination=stopLocation, datetime=time, seats=seatNumber, seats_wheelchair=wheelchairNumber)
        LOGGER.error(message, exc_info=True)
        solution = False
    except Exception as err:
        message = f'an error occurred in RouteRequest: {err}'
        Requests.Orders.route_rejected(order_id=orderId, reason=message, start=startLocation, destination=stopLocation, datetime=time, seats=seatNumber, seats_wheelchair=wheelchairNumber)
        LOGGER.error(message, exc_info=True)
        
    return Response(data=solution)

def RouteDetails(routeId):
    return get_object_or_404(Route, pk=routeId)

def RouteStarted(routeId):
    route = get_object_or_404(Route, pk=routeId)
    if route.started:
        return Response(data={'message': f'route {routeId} has already been started'}, status=202)
    if not route.frozen:
        return Response(data={'message': f'route {routeId} has a different status than frozen'}, status=400)
    
    route.start()
    route.save()
    Requests.Orders.route_started(route_id=routeId)

    return Response(data={'message': f'route {routeId} has been started'}, status=202)
def RouteFinished(routeId):
    route = get_object_or_404(Route, pk=routeId)
    if route.finished:
        return Response(data={'message': f'route {routeId} has already finished'}, status=202)
    if not route.started:
        return Response(data={'message': f'route {routeId} has not yet started'}, status=400)
    
    route.finish()
    route.save()
    Requests.Orders.route_finished(route_id=routeId)

    return Response(data={'message': f'route {routeId} has been finished'}, status=202)



def parse_location(location_string: str)->Tuple[float,float]:
    """ transform location input into lat./lon. tuple """
    return location_string
def parse_time(time_string: str)->datetime:
    """ transform time input into a datetime object """
    t = parse(time_string)
    if t.tzinfo is None:
        raise ValueError('could not infer timezone information from input string')
    return t

def parse_boolean(boolean_string: str)->bool:
    """ transform a string "True" or "False" to boolean """
    boolean_string = boolean_string.lower()
    if boolean_string == 'true':
        return True
    elif boolean_string == 'false':
        return False
    else:
        raise ValueError()


def not_pos_integer(iStr, upper_bound=None):
    try:
        if iStr is None:
            return False, None

        value = int(iStr)
        if value <= 0:
            value = None

        if upper_bound is None:
            return 0 < value, value
        else:
            if value > upper_bound:
                value = None
            return 0 < value <= upper_bound, value
    except:
        return False, None

def not_pos_integer_or_null(iStr, upper_bound=None):
    try:
        if iStr is None:
            return False, None

        value = int(iStr)
        if value < 0:
            value = None

        if upper_bound is None:
            return 0 <= value, value
        else:
            if value > upper_bound:
                value = None
            return 0 <= value <= upper_bound, value
    except:
        return False, None

def not_float(fStr):
    try:
        if fStr is None:
            return False, None

        value = float(fStr)
        return True, value
    except:
        return False, None
def not_boolean(bStr):
    try:
        if bStr is None:
            return False, None

        value = parse_boolean(bStr)
        return True, value
    except:
        return False, None
def not_location(locStr):
    try:
        if locStr is None:
            return False, None

        value = parse_location(locStr)
        return True, value
    except:
        return False, None
def not_time(timeStr):
    try:
        if timeStr is None:
            return False, None

        value = parse_time(timeStr)
        return True, value
    except:
        return False, None

def driver_details(routeId):
    route = get_object_or_404(Route.objects.prefetch_related('nodes__hopOns', 'nodes__hopOffs'), pk=routeId)
    route_details = RouteSerializer(route).data
    details = []
    for node in map(lambda n: NodeSerializer(n).data, route.nodes.all()):
        if len(node['hopOns']) == 0 and len(node['hopOffs']) == 0:
            continue
        
        label, lat, lon = find_station_lat_lon_for_node(node)

        node_details = {'latitude': lat,
                        'longitude': lon,
                        'label': label,
                        'tMin': node['tMin'],
                        'tMax': node['tMax'],
                        'hopOns': node['hopOns'],
                        'hopOffs': node['hopOffs']}
        details.append(node_details)
    route_details['nodes'] = details
    return route_details

# return a list of gps coordinates for a whole route (with >= 1 orderIds)
def driver_details_with_gps(routeId):
    
    # print("################# driver_details_with_gps #################")
    route_details = driver_details(routeId)
    
    # print(f"route_details: {route_details}")

    order_ids = []

    for node in route_details['nodes']:
        if node['hopOns']:
            for hop_on in node['hopOns']:
                order_id = hop_on.get('orderId')
                if order_id:
                    order_ids.append(order_id)

    # print(f"order_ids: {order_ids}")

    index = 0

    # add a new key 'orders', which will contain a list of orders with gps coordinates
    route_details['orders'] = []


    for order_id in order_ids:
        order_placeholder = order_details_with_gps(routeId, order_id)
        route_details['orders'].append(order_placeholder)
        route_details['orders'][index]['orderId'] = order_id
        index = index + 1

    if route_details['orders']:
        # print(route_details)
        # print(f"#########################################################\n")
        # print(f"total of {len(route_details['orders'])} orders")
        return route_details
    else:
        return None

def order_details(routeId, orderId):
    details = []
    onBoard = False
    route = get_object_or_404(Route.objects.prefetch_related('nodes__hopOns', 'nodes__hopOffs'), pk=routeId)
    order = get_object_or_404(Order, uid=orderId)
    route_details = RouteSerializer(route).data

    for node in map(lambda n: NodeSerializer(n).data, route.nodes.all()):
        if len(node['hopOns']) == 0 and len(node['hopOffs']) == 0:
            continue

        label, lat, lon = find_station_lat_lon_for_node(node)        

        node_details = {'latitude': lat,
                        'longitude': lon,
                        'label': label,
                        'tMin': node['tMin'],
                        'tMax': node['tMax']}

        if orderId in [order['orderId'] for order in node['hopOns']]:
            onBoard = True
        if onBoard:
            details.append(node_details)
        if orderId in [order['orderId'] for order in node['hopOffs']]:
            onBoard = False

    route_details['nodes'] = details
    return route_details

def order_details_with_gps(routeId, orderId):
    from routing.rutils import shortest_path_OSRM_multi, shortest_path_graph_gps, multi2single
    from routing.routingClasses import Station as StationRouting

    # get detailed gps route
    route_details = order_details(routeId, orderId)
    community = Route.objects.get(id=routeId).community

    # iterate the nodes (i.e. stations) of the order and build list of station objects
    stations = [] 
    listLatLon = []  

    useGraph =  (Requests.OSRM_activated == False)

    for node_detail in route_details['nodes']:
        lat = node_detail['latitude']
        lon = node_detail['longitude']   
        listLatLon.append((lat, lon))     

        mapId = -1        
        station = StationRouting(node_id=mapId, latitude=lat, longitude=lon)
        stations.append(station)

    resultGps = []

    # print("stations")
    # print(stations)

    # get gps subroutes of station list
    if useGraph == False:
        resultGps = shortest_path_OSRM_multi(stations, Requests.OSRM_url, onlyGps=True)
    else:
        # if we work with a map we need the map ids of the stations
        # do not get the mapId from earlier data, since the map may change -> safe way: identify from gps coords
        # get_graph is time consuming, call it only once!

        G = maps.get_graph(community=community)

        mapIds = maps.nearest_node_multi_2(G=G,listLatLon=listLatLon)

        index = 0
        for station in stations:
            station.node_id = mapIds[index]
            index+=1

        Gtmp = multi2single(G)
        for iLoc in range(0, len(stations)-1):                
            resultGps.append(shortest_path_graph_gps(Gtmp, stations[iLoc], stations[iLoc+1]))

    #print(resultGps)
       
    route_details['gps'] = resultGps
    #print(route_details)

    return route_details

def driver_details_busId(busId, timeMin, timeMax):
    details = []
    routes = []
    route_filter = Q(bus__uid=busId)

    routes = Route.objects.prefetch_related('nodes', 'nodes__hopOns', 'nodes__hopOffs', 'bus').filter(route_filter).distinct()
    for route in routes:
        route_details = RouteSerializer(route).data
        route_details['nodes'] = []

        emptyRoute = True        

        for node in map(lambda n: NodeSerializer(n).data, route.nodes.all()):
            if len(node['hopOns']) == 0 and len(node['hopOffs']) == 0:
                continue
            else:
                emptyRoute = False

            label, lat, lon = find_station_lat_lon_for_node(node)     

            node_details = {'latitude': lat,
                            'longitude': lon,
                            'label': label,
                            'tMin': node['tMin'],
                            'tMax': node['tMax'],
                            'hopOns': node['hopOns'],
                            'hopOffs': node['hopOffs']}
            route_details['nodes'].append(node_details)
        
        if not emptyRoute:
            details.append(route_details)
    return details

def find_station_lat_lon_for_node(node): 
    label = ''
    lat = ''
    lon = ''

    try:
        station = Station.objects.get(mapId=node['mapId'])
        label = station.name
        lat = station.latitude
        lon = station.longitude
    except:
        # fallback if station cannot be identified by mapID, however: may not work with OSRM (TODO what to do if this happens?)
        label = 'unknown station'
        nearest_stations = {}

        latlonfound = True

        if 'latitude' in node and 'longitude' in node:
            lat = node['latitude']
            lon = node['longitude']
        elif Requests.OSRM_activated == False:
            lat, lon = maps.get_geo_locations(node['mapId'])
        else:
            latlonfound=False

        if latlonfound==True:
            nearest_stations = list(Station.objects.nearest(
                latitude=lat, longitude=lon, n_nearest=1))

        if len(nearest_stations) > 0:
            station = nearest_stations[0]
            if station.distance > 50:
                LOGGER.warning(
                    f'find_station_lat_lon_for_node: found nearest station for {lat}/{lon} at {station}, {station.distance}m away')
            label = station.name
        else:
            LOGGER.error(f'find_station_lat_lon_for_node: found no nearest station for node')
            pass

    return (label, lat, lon)