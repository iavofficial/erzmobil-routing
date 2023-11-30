import json
import logging
from datetime import datetime, timedelta, timezone
from functools import wraps
import time
import os

from typing import List

from dateutil.parser import parse
from dateutil.relativedelta import relativedelta
from dateutil.tz import tzutc
from django.core.exceptions import ObjectDoesNotExist
from django.db import close_old_connections, transaction
from django.conf import settings

from routing.errors import (CommunityConflict, DuplicatedOrder, InvalidTime, InvalidTime2,
                            MalformedMessage, NoBuses, NoBusesDueToBlocker, BusesTooSmall, NoStop, SameStop)
from routing.OSRM_directions import OSRM
from routing.routingClasses import Station, MobyLoad
from routing.rutils import multi2single, add_detours_from_gps, GpsUtmConverter

from .models import Route

UTC = tzutc()
LOGGER = logging.getLogger('Mobis.services')

def unpack_message(body=None, fields=None):
    class Message():
        def __init__(self, data):
            self.__dict__ = data
    
    data = json.loads(body)
    missing_fields = []
    for field in fields:
        if field not in data:
            missing_fields.append(field)
    if missing_fields:
        raise MalformedMessage(f'missing fields {missing_fields}, got {body}')
    
    return Message(data)

def rabbit_callback(fields):
    """
    Decorator function for the callback methods.
    Takes another function as an argument and returns a new function that "wraps" the original function.
    Unpacks the message payload and resets the database connection. 
    """
    def message_decorator(fun):
        @wraps(fun)     # @wraps is used to preserve the metadata of the original function
        def wrapper(self, ch=None, method=None, properties=None, body=None):
            del ch
            del method
            del properties
            message = unpack_message(body=body, fields=fields)
            close_old_connections()
            return fun(self, message)
        return wrapper
    return message_decorator

class RequestManagerConfig:

   # modes for altetnatives search
    ALTERNATIVE_SEARCH_NONE = 'alternatives_none'
    ALTERNATIVE_SEARCH_EARLIER = 'alternatives_earlier'
    ALTERNATIVE_SEARCH_LATER = 'alternatives_later'

    def __init__(self):
        self.timeOffset_MaxDaysOrderInFuture = 28 
        self.timeOffset_MinMinutesToOrderFromNow = (int)(settings.ROUTING_TIMEOFFSET_MINMINUTESTOORDERFROMNOW) 
        self.timeOffset_FactorForDrivingTimes = 1.25 
        self.timeOffset_LookAroundHoursPromises = 1 
        self.timeOffset_LookAroundHoursBusAvailabilites = 10 # do not use same look_around for promises und availabilities, otherwise for long routes we we might not get solutions 

        self.timeService_per_wheelchair = 3 

class RequestManager:
    """ Manages abstraction layers of services to interact with each other. """

    POSSIBLE = 0
    NO_BUSES = 1
    WRONG_TIME_PAST = 2
    NO_COMMUNITY = 3
    NO_STOPS = 4
    SAME_STOPS = 5
    NO_ROUTING = 6
    WRONG_TIME_FUTURE = 7
    BUSES_TOO_SMALL = 8
    NO_BUSES_DUE_TO_BLOCKER = 9
    NO_BUSES_ALTERNATIVE_FOUND = 10
    NO_BUSES_NO_ALTERNATIVE_FOUND = 11 

    def __init__(self, Routes, Busses, Stations, Maps, OSRM_activated, OSRM_url, Solver, Orders, RoadClosures):
        self.Routes = Routes
        self.Busses = Busses
        self.Stations = Stations
        self.Maps = Maps
        self.OSRM_activated = OSRM_activated
        self.OSRM_url = OSRM_url
        self.Solver = Solver
        self.Orders = Orders
        self.Config = RequestManagerConfig()
        self.RoadClosures = RoadClosures

        # do not use same look_around for promises and availabilities, otherwise for long routes we we might not get solutions 
        self.Routes._look_around = self.Config.timeOffset_LookAroundHoursPromises
        self.Busses._look_around = self.Config.timeOffset_LookAroundHoursBusAvailabilites

        # register listener callbacks for order events
        self.Orders.register_OrderCancelledIntegrationEvent(self.OrderCancelledCallback)
        self.Orders.register_OrderStartedIntegrationEvent(self.OrderStartedCallback)
        self.Orders.register_UpdateBusPositionIntegrationEvent(self.UpdateBusPositionCallback)
        self.Orders.register_StopAddedIntegrationEvent(self.StopAddedIntegrationCallback)
        self.Orders.register_StopDeletedIntegrationEvent(self.StopDeletedIntegrationCallback)
        self.Orders.register_StopUpdatedIntegrationEvent(self.StopUpdatedIntegrationCallback)
        self.Orders.register_BusDeletedIntegrationEvent(self.BusDeletedIntegrationCallback)
        self.Orders.register_BusUpdatedIntegrationEvent(self.BusUpdatedIntegrationCallback)
        self.Orders.listen()

    def nearest_node(self, communityId, lat, lon):
        if self.OSRM_activated == False:
            return self.Maps.nearest_node(
                community=communityId,
                latitude=lat,
                longitude=lon)
        else:
            return OSRM(self.OSRM_url).nearest_osmid(lat, lon)

    # ------------------- Callback functions to act on messages received from Directus -------------------
    # The specified fields by the rabbit_callback tag are expected to be present in the message payload

    @rabbit_callback(fields=['Id', 'CommunityId', 'Name'])
    def BusDeletedIntegrationCallback(self, message):
        """Deletes the bus and all routes which were planned for this bus. """
        LOGGER.info(f'BusDeletedIntegrationCallback')
        bus = self.Busses._busses.objects.get(uid=message.Id)   # retrieve the bus with the matching id from the db
        for route in self.Routes._routes.objects.filter(bus=bus):
            for order in route.clients():   # route.clients() returns a set of order ids
                self.cancel_order(order_id=order)
                self.Orders.route_rejected(order_id=order, reason='The bus for which this route was planned got deleted.')
            route.delete()
        self.Busses._busses.objects.filter(uid=message.Id).delete()
    
    @rabbit_callback(fields=['Id', 'CommunityId', 'Name'])
    def BusUpdatedIntegrationCallback(self, message):
        """
        Updates a bus object in the database and then checks if it still has enough capacity for its routes,
        deleting any excess routes and orders. If no routes remain, it deletes the bus object.
        """
        LOGGER.info(f'BusUpdatedIntegrationCallback')
        bus = self.Busses.refresh_bus(bus_id=message.Id)
        
        # check capacities
        for route in self.Routes._routes.objects.filter(bus=bus):
            if not bus.capa_sufficient_for_load(route.needed_capacity):
                # delete orders, start with newest
                for order in reversed(sorted(route.clients())):     # route.clients() returns a set of order ids
                    self.cancel_order(order_id=order)
                    self.Orders.route_rejected(order_id=order, reason='The bus for which this route was planned got deleted.')

                    # stop deleting orders if capa is sufficient
                    if bus.capa_sufficient_for_load(route.needed_capacity):
                        break
                
                # route without clients remaining can be removed
                if len(route.clients()) == 0:
                    route.delete()

        # if no route remains for the bus, the bus can be removed from db
        if self.Routes._routes.objects.filter(bus=bus).count() == 0:
            self.Busses._busses.objects.filter(uid=message.Id).delete()

    @rabbit_callback(fields=['Id', 'CommunityId', 'Name', 'Latitude', 'Longitude'])
    def StopAddedIntegrationCallback(self, message):
        """ Updates the stations table in the database by adding the new station. """
        LOGGER.info(f'StopAddedIntegrationCallback')
        # todo test dafuer schreiben und am besten mit graph und mit OSRM testen -> macht es was aus, dass die ID bei OSRM anders ist?
        mapId = self.nearest_node(
            message.CommunityId,
            message.Latitude,
            message.Longitude)
        
        self.Stations.update(
            station_id=message.Id,
            community=message.CommunityId,
            name=message.Name,
            latitude=message.Latitude,
            longitude=message.Longitude,
            mapId=mapId)
    
    @rabbit_callback(fields=['Id', 'CommunityId', 'Name', 'Latitude', 'Longitude'])
    def StopUpdatedIntegrationCallback(self, message):
        """ Rejects and deletes any orders that have the old map node as a hop-on or hop-off and then deletes the node itself. """
        self.StopUpdatedCore(message)

    def StopUpdatedCore(self, message):
        LOGGER.info(f'StopUpdatedIntegrationCallback')
        
        from django.core.exceptions import ObjectDoesNotExist

        # get the mapId of the updated station from the StopUpdatedIntegrationEvent message
        mapId = self.nearest_node(
            message.CommunityId,
            message.Latitude,
            message.Longitude)

        rejectedOrders: List[int] = []        

        try:
            # print("StopUpdatedCore")
            # print(message.Id)
            # print(mapId)

            station = self.Stations.get_by_id(station_id=message.Id)
            #print(station)

            # if the mapId of the updated station is different from the mapId of the existing station, the station position has changed
            if mapId != station.mapId:
                # TODO eventuell muss man hier genauer spezifizieren, bei anderer MapID muss sich das noch nicht zwingend geaendert haben, oder?...(OSRM, andere Karte...),
                # in den meisten Faellen duerfte das Kriterium aber passen  
                # die Stelle mit mapId muss evtl umgestellt werden auf node.equalsStation(station) ??  

                # reject and delete orders which have the old map node as a hopOn or a hopOff and then delete this node
                nodes = self.Routes._nodes.objects.prefetch_related('route', 'hopOns', 'hopOffs')\
                    .filter(mapId=station.mapId, route__community=message.CommunityId).distinct()
                for node in nodes:
                    if node.route.status == Route.BOOKED or node.route.status == Route.DRAFT: # DO NOT CHANGE FINISHED ROUTES!
                        for order in node.hopOns.all() | node.hopOffs.all():
                            rejectedOrders.append(order.uid)
                            self.Orders.route_rejected(order_id=order.uid, reason=f"Start or destination of order (id = {order.uid}) has changed! Old stop: {station.name} ({station.latitude}, {station.longitude}), New stop: {message.Name} ({message.Latitude}, {message.Longitude})")
                            order.delete()
                        node.delete()

        except ObjectDoesNotExist:
            LOGGER.warning(f'StopUpdatedCore: station to update not found')
            pass

        self.Stations.update(
            station_id=message.Id,
            community=message.CommunityId,
            name=message.Name,
            latitude=message.Latitude,
            longitude=message.Longitude,
            mapId=mapId)

        return rejectedOrders

    @rabbit_callback(fields=['Id', 'CommunityId', 'Name', 'Latitude', 'Longitude'])
    def StopDeletedIntegrationCallback(self, message):
        """ Rejects and deletes any orders that have the deleted node as a hop-on or hop-off and then deletes the node itself. """
        LOGGER.info(f'StopDeletedIntegrationCallback')
        from django.core.exceptions import ObjectDoesNotExist

        try:
            station = self.Stations.get_by_id(station_id=message.Id)

            # reject and delete orders which have the deleted node as a hopOn or a hopOff and then delete this node
            nodes = self.Routes._nodes.objects.prefetch_related('route', 'hopOns', 'hopOffs')\
                .filter(route__community=station.community).distinct()
            for node in nodes:
                if node.equalsStation(station):
                    for order in node.hopOns.all() | node.hopOffs.all():
                        self.Orders.route_rejected(order_id=order.uid, reason=f"Start or destination of order (id = {order.uid}) has been deleted! Deleted stop: {station.name} ({station.latitude}, {station.longitude})")
                        order.delete()
                    node.delete()

            station.delete()

        except ObjectDoesNotExist:
            pass

    @rabbit_callback(fields=['BusId', 'Latitude', 'Longitude'])
    def UpdateBusPositionCallback(self, message):
        """ Updates the position of the bus in the database by setting the latitude and longitude from the received message. """
        LOGGER.info(f'UpdateBusPositionCallback')
        self.Busses.update(bus_id=message.BusId, latitude=message.Latitude, longitude=message.Longitude)

    @rabbit_callback(fields=['Id'])
    @transaction.atomic
    def OrderCancelledCallback(self, message):
        """ Cancels the order with the corresponding id. """
        LOGGER.info(f'OrderCancelledCallback {message.Id}')
        try:
            self.cancel_order(order_id=message.Id)
        except ObjectDoesNotExist:
            pass

    @rabbit_callback(fields=['Id', 'StartLatitude', 'StartLongitude', 'EndLatitude', 'EndLongitude', 'IsDeparture', 'Time', 'Seats', 'SeatsWheelchair'])
    @transaction.atomic     # if any part of this method fails, the entire database transaction will be rolled back
    def OrderStartedCallback(self, message):
        """ Called when a new order is received from RabbitMQ. Creates a new order in the system with the requested parameters. """
        LOGGER.info(f'OrderStartedCallback {message.Id}')
        startLocation = message.StartLatitude, message.StartLongitude
        stopLocation = message.EndLatitude, message.EndLongitude
        
        time = parse(message.Time)
        if time.tzinfo is None:
            raise ValueError('Time needs to include time zone.')

        # convert to utc is essential for correct calculations
        time = datetime.fromtimestamp(time.timestamp(), tz=timezone.utc)

        if message.IsDeparture:            
            startWindow = (time, time+relativedelta(minutes=10))
            stopWindow = None
        else:
            startWindow = None
            stopWindow = (time-relativedelta(minutes=10), time)

        try:
            self.order(start_location=startLocation, stop_location=stopLocation, start_window=startWindow, stop_window=stopWindow, load=message.Seats, loadWheelchair=message.SeatsWheelchair, order_id=message.Id)
        except DuplicatedOrder as err:
            LOGGER.warning('Order_id already exists: %s', err, extra={'body': message}, exc_info=True)
        except CommunityConflict as err:
            self.Orders.route_rejected(order_id=message.Id, reason=err.message)
        except SameStop as err:
            self.Orders.route_rejected(order_id=message.Id, reason=err.message)
        except NoStop as err:
            self.Orders.route_rejected(order_id=message.Id, reason=err.message)
        except NoBuses as err:
            self.Orders.route_rejected(order_id=message.Id, reason=err.message)
        except NoBusesDueToBlocker as err:
            self.Orders.route_rejected(order_id=message.Id, reason=err.message)
        except BusesTooSmall as err:
            self.Orders.route_rejected(order_id=message.Id, reason=err.message)
        except InvalidTime as err:
            self.Orders.route_rejected(order_id=message.Id, reason=err.message)
        except InvalidTime2 as err:
            self.Orders.route_rejected(order_id=message.Id, reason=err.message)

        except Exception as err:
            self.Orders.route_rejected(order_id=message.Id, reason=f'an error occurred: {err}')
            LOGGER.error('Order could not be processed: %s', err, extra={'body': message}, exc_info=True)
    
    def order(self, start_location, stop_location, start_window, stop_window, load=1, loadWheelchair=0, group_id=None, order_id=None):
        """
        Creates a new order and attempts to find a route for it.
        If a route is found, it commits the order and returns the order ID.
        If no route can be found, it rejects the order and returns `None`.
        """
        
        LOGGER.info(f'order {order_id}')
        results, time_slot, original_time_found = self.new_request(start_location, stop_location, start_window, stop_window, MobyLoad(load, loadWheelchair), group_id, order_id, RequestManagerConfig.ALTERNATIVE_SEARCH_NONE)
        (solution, comment, start_window, stop_window) = results[0]

        if solution is None:
            LOGGER.info('found no valid solution for request')
            self.Orders.route_rejected(order_id=order_id, reason=comment)
            return None
        
        if solution['type'] == 'new':
            self.Routes.commit_order(order_id=order_id, load=load, loadWheelchair=loadWheelchair, group_id=group_id)
            self.Routes.commit(solution['routes'], self.Orders)
            order_entry = self.Routes._orders.objects.get(uid=order_id)
            route = self.Routes.contains_order(order_id)
            hopOn = order_entry.hopOnNode
            hopOff = order_entry.hopOffNode

            # Send a message to Directus
            self.Orders.route_confirmed(order_id=order_id, 
                                        route_id=route.id, 
                                        start_time_min=hopOn.tMin, 
                                        start_time_max=hopOn.tMax, 
                                        stop_time_min=hopOff.tMin, 
                                        stop_time_max=hopOff.tMax)
            return order_id
        
        if solution['type'] == 'free':
            [starts, stops] = self.Stations.get_stops_by_geo_locations([start_location, stop_location])
            start_station = starts[0]
            stop_station = stops[0]
            solution['restrictions'] = start_station, stop_station, start_window, stop_window, load, loadWheelchair
            self.Routes.hop_on(solution['routes'], solution['restrictions'], order_id, self.Orders)     # assign an order to a route
            return order_id
        
        self.Orders.route_rejected(order_id=order_id, reason='unexpected case: solution type is neither "new" nor "free"')
        raise ValueError('solution type is neither new nor free')

    def cancel_order(self, order_id):
        """
        Cancels an order with the specified ID and removes it from the list of orders.
        Also removes any associated hop-on or hop-off nodes that become empty after the order is deleted.
        """
        LOGGER.info(f'cancel_order {order_id}')
        hopOnNode = self.Routes._orders.objects.get(uid=order_id).hopOnNode
        hopOffNode = self.Routes._orders.objects.get(uid=order_id).hopOffNode

        self.Routes.remove_order(order_id)        

        # remove hopOn or hopOff nodes that are empty after order delete
        for node in self.Routes._nodes.objects.all():
            if not node.has_order:
                #print(f'delete node {node}')
                if node.id == hopOnNode.id or node.id == hopOffNode.id:
                    node.delete()
                    pass

    def is_bookable(self, start_location, stop_location, start_window, stop_window, load=1, loadWheelchair=0, group_id=None, alternatives_mode=RequestManagerConfig.ALTERNATIVE_SEARCH_NONE):
        """Return result, code and message for a given request."""
        LOGGER.info(f'is_bookable')        

        times_found = []
        time_slot_min_max = [] # hier noch das Zeitfenster, das geprueft wurde, draufschreiben
        result=(False, -1, 'nothing calculated', times_found, time_slot_min_max)
        count_solutions_found = 0

        # Get the stops' names
        [starts, stops] = self.Stations.get_stops_by_geo_locations([start_location, stop_location])

        try:
            try:
                results_all, time_slot_min_max, original_time_found = self.new_request(start_location, stop_location, start_window, stop_window, MobyLoad(load,loadWheelchair), None, group_id, alternatives_mode, False)

                for (solution, comment, start_window, stop_window) in results_all:
                    if solution:
                        count_solutions_found += 1

                        if start_window:
                            times_found.append(start_window)
                        else:
                            times_found.append(stop_window)
                # print("solution")
                # print(solution)
                
                if count_solutions_found > 0:
                    # important: if original time was found we should respond the standard success code even if alternative search was enabled
                    if alternatives_mode == RequestManagerConfig.ALTERNATIVE_SEARCH_NONE or original_time_found:
                        result = (True, self.POSSIBLE, 'Hurray', times_found, time_slot_min_max)
                    else:
                        result = (True, self.NO_BUSES_ALTERNATIVE_FOUND, 'Hurray', times_found, time_slot_min_max)
                else:
                    # The value of start_window may change, when alternatives_mode is activated.
                    # new_request() calls new_request_eval_time_windows(), which creates a list of time windows. If alternatives_mode is activated, results_all grows bigger
                    # results_all[0] contains the very first result (doesn't matter if a routing solution has been found or not)
                    # results_all[0][2] contains start_window of the first result
                    # results_all[0][2][0] contains the first time of the start_window of the first result
                    # Therefore, results_all[0][2][0] always holds the very first start_window, regardless of how big results_all
                    
                    if alternatives_mode == RequestManagerConfig.ALTERNATIVE_SEARCH_NONE:
                        reason = f"No routing found for request - Start: {starts[0].name} {start_location}, Destination: {stops[0].name} {stop_location}, Time: {results_all[0][2][0].strftime('%Y/%m/%d, %H:%M')} (UTC), Seats: {load} standard, {loadWheelchair} wheelchair."
                        result = (False, self.NO_ROUTING, reason, times_found, time_slot_min_max)
                        self.Orders.route_rejected(order_id=-1, reason=reason)
                    else:
                        reason = f"No routing found for request (including alternatives search) - Start: {starts[0].name} {start_location}, Destination: {stops[0].name} {stop_location}, Time: {results_all[0][2][0].strftime('%Y/%m/%d, %H:%M')} (UTC), Seats: {load} standard, {loadWheelchair} wheelchair."
                        result = (False, self.NO_BUSES_NO_ALTERNATIVE_FOUND, reason, times_found, time_slot_min_max)
                        self.Orders.route_rejected(order_id=-1, reason=reason)

            except SameStop as err:
                self.Orders.route_rejected(order_id=-1, reason=err.message)
                result = (False, self.SAME_STOPS, err.message, times_found, time_slot_min_max)
            except NoStop as err:
                self.Orders.route_rejected(order_id=-1, reason=err.message)
                result = (False, self.NO_STOPS, err.message, times_found, time_slot_min_max)
            except CommunityConflict as err:
                self.Orders.route_rejected(order_id=-1, reason=err.message)
                result = (False, self.NO_COMMUNITY, err.message, times_found, time_slot_min_max)
            except NoBuses as err:
                self.Orders.route_rejected(order_id=-1, reason=err.message)
                result = (False, self.NO_BUSES, err.message, times_found, time_slot_min_max)
            except NoBusesDueToBlocker as err:
                self.Orders.route_rejected(order_id=-1, reason=err.message)
                result = (False, self.NO_BUSES_DUE_TO_BLOCKER, err.message, times_found, time_slot_min_max)
            except BusesTooSmall as err:
                self.Orders.route_rejected(order_id=-1, reason=err.message)
                result = (False, self.BUSES_TOO_SMALL, err.message, times_found, time_slot_min_max)
            except InvalidTime as err:
                self.Orders.route_rejected(order_id=-1, reason=err.message)
                result = (False, self.WRONG_TIME_PAST, err.message, times_found, time_slot_min_max)
            except InvalidTime2 as err:
                self.Orders.route_rejected(order_id=-1, reason=err.message)
                result = (False, self.WRONG_TIME_FUTURE, err.message, times_found, time_slot_min_max)

            return result
        except Exception as err: # catch any other exceptions
            self.Orders.route_rejected(order_id=-1, reason=('uncaught exception %s', err))
            LOGGER.error('uncaught exception %s', err, exc_info=True)
            raise err        
    
    def order2route(self, order_id):
        """ Return the `Route` object that contains the order with the matching `order_id`. """
        route = self.Routes.contains_order(order_id)
        return route

    def new_request_eval_start_stop(self, start_location, stop_location):
        # get all bus stops around the start and stop position
        LOGGER.info(f'startLocation: {start_location}, stopLocation: {stop_location}')
        [starts, stops] = self.Stations.get_stops_by_geo_locations([start_location, stop_location])
        LOGGER.info(f'starts: {starts}, stops: {stops}')

        if not starts:
            raise NoStop(message=f"No bus stop was found for the given start location (lat: {start_location[0]}, long: {start_location[1]})!")
        
        if not stops:
            raise NoStop(message = f"No bus stop was found for the given destination location (lat: {stop_location[0]}, long: {stop_location[1]})!")
        
        # look for communities that contain both a start and stop bus stop
        start_commmunities = set(s.community for s in starts)
        stop_commmunities = set(s.community for s in stops)

        # FIXME TODO: solve community conflicts
        # there are 3 possible outcomes:
        # 0 communities contain both a start and stop -> currently no multi-community solution
        # exactly 1 community contains start and stop -> this is where we'll look and the prefered outcome
        # multiple communities contain a start and stop -> currently no solution, but we could look in each
        communities = start_commmunities.intersection(stop_commmunities)
        if not communities:
            reason = f"No matching communities - Start: {starts[0].name} {start_location} in community {start_commmunities}, Destination: {stops[0].name} {stop_location} in community {stop_commmunities}."
            LOGGER.debug(reason)
            raise CommunityConflict(message=reason)
        if len(communities) > 1:
            reason = "Intersecting communities found. This isn't currently supported."
            LOGGER.debug(reason)
            raise CommunityConflict(reason)
        
        if len(communities) == 1:
            community = communities.pop()

        # only keep stops in non-overlapping community
        starts = list(filter(lambda s: s.community == community, starts))
        stops =  list(filter(lambda s: s.community == community, stops))        
        
        # keep only one of each for now
        start = starts[0]
        stop = stops[0]        

        if start == stop:
            reason = f"Start and destination are the same or too close to each other! Start: {start.name} (mapId: {start.mapId}, lat: {start.latitude}, long: {start.longitude}), Destination: {stop.name} (mapId: {stop.mapId}, lat: {stop.latitude}, long: {stop.longitude})"
            LOGGER.debug(reason)
            raise SameStop(message=reason)

        return start, stop, community

    def new_request_eval_time_windows(self, start_window, stop_window, alternatives_mode):
        time_windows=[]

        # order time needs min offset from now
        offsetMinutes_start = self.Config.timeOffset_MinMinutesToOrderFromNow
        offsetMinutes_stop = offsetMinutes_start + 15 # TODO wenn die Ankunftszeit vorgegeben ist, dann ist die Untergrenze eigtl erst nach dem Routing pruefbar, pragmatisch koennte man schon mal in die time-matrix schauen... (?)
        
        #print('new_request_eval_time_windows offsetMinutes_start: ' + str(offsetMinutes_start))

        # maximum order time should not be too far away in future
        offsetDaysInFuture = self.Config.timeOffset_MaxDaysOrderInFuture     
        time_max = datetime.now(UTC) + timedelta(days=offsetDaysInFuture)
        time_min = None
        # print(f"start_window: {start_window}")
        # print(f"time_min: {time_min}")
        # print(f"time_max: {time_max}")
        
        if start_window:       
            # order requests a start time     
            time_offset = timedelta(minutes=offsetMinutes_start)
            # print(f"time_offset: {time_offset}")
            time_min = datetime.now(UTC) + time_offset
            for time in start_window:
                # print(f"time: {time}")
                if time is not None and time < time_min:
                    raise InvalidTime(message=f"Departure used past time data. Requested time: {time.strftime('%Y/%m/%d, %H:%M')} (UTC)")
                if time is not None and time > time_max:
                    raise InvalidTime2(message=f"Departure is too far away in future. Requested time: {time.strftime('%Y/%m/%d, %H:%M')} (UTC)")
            time_windows.append(start_window)            
        elif stop_window:
            # order requests a stop time - route time unknown -> additional offset
            time_offset = timedelta(minutes=offsetMinutes_stop)
            time_min = datetime.now(UTC) + time_offset
            for time in stop_window:
                if time is not None and time < time_min:
                    raise InvalidTime(message=f"Arrival used past time data. Requested time: {time.strftime('%Y/%m/%d, %H:%M')} (UTC)")
                if time is not None and time > time_max:
                    raise InvalidTime2(message=f"Arrival is too far away in future. Requested time: {time.strftime('%Y/%m/%d, %H:%M')} (UTC)")
            time_windows.append(stop_window)

        # generate time windows for alternative search
        # print(f"DEBUGGING value of alternatives_mode: {alternatives_mode}")
        if alternatives_mode == RequestManagerConfig.ALTERNATIVE_SEARCH_LATER or alternatives_mode == RequestManagerConfig.ALTERNATIVE_SEARCH_EARLIER:
            time_delta_alternatives_minutes = int(os.environ.get('ALTERNATIVES_DELTA_MINUTES',10))
            time_delta_steps = int(os.environ.get('ALTERNATIVES_DELTA_STEPS',12))
            time_window_ref = time_windows[0]

            for iStep in range(1, time_delta_steps+1):  
                time_delta = timedelta(minutes=iStep*time_delta_alternatives_minutes)   

                # print(iStep)
                # print(time_delta)
                # print(time_min)
                # print(time_max)

                if alternatives_mode == RequestManagerConfig.ALTERNATIVE_SEARCH_LATER:
                    time1 = time_window_ref[0] + time_delta
                    time2 = time_window_ref[1] + time_delta

                    # print(time1)
                    # print(time2)

                    if time1 <= time_max and time2 <= time_max:
                        time_windows.append((time1, time2))
                else:
                    time1 = time_window_ref[0] - time_delta
                    time2 = time_window_ref[1] - time_delta

                    # print(time1)
                    # print(time2)

                    if time1 >= time_min and time2 >= time_min:
                        time_windows.append((time1, time2))

        # return final time windows
        # print('new_request_eval_time_windows')
        # print(start_window)
        # print(stop_window)
        # print(time_windows)

        if start_window:
            return time_windows, None
        else:
            return None, time_windows

    def new_request(self, start_location, stop_location, start_window_orig, stop_window_orig, load:MobyLoad=MobyLoad(1,0), group_id=None, order_id=None, alternatives_mode=RequestManagerConfig.ALTERNATIVE_SEARCH_NONE, build_paths= True):
        """ Try to generate a solution for a given request and return a descriptive dictionary if there is one, or None. """
        LOGGER.info(f'new_request with order_id {order_id}, start_window_orig{start_window_orig}, stop_window_orig{stop_window_orig}')
        timeStarted = time.time()  

        result: List = []   
        time_slot_complete = []    
        original_time_found = False

        if self.OSRM_activated:
            LOGGER.info(f'OSRM is used for routing')
        
        from routing.routingClasses import Moby, Trip
        reason = ''
        
        # eval bus stops and community from coords
        # start, stop, community = self.new_request_eval_start_stop(start_location, stop_location)
        # station_start = Station(node_id=start.mapId, longitude=start.longitude, latitude=start.latitude)
        # station_stop = Station(node_id=stop.mapId, longitude=stop.longitude, latitude=stop.latitude)  

        # eval all suitable start times according to alternatives mode
        # new_request_eval_time_windows pretty much converts the start_window_orig from a tuple to a list of tuples: () becomes [()], if alternatives_mode is True, then more time windows are added
        # all of this is in a try-except block, so we can catch the exception from the function and then add some more infos to it, which are not available from inside new_request_eval_time_windows (in this case, the stops' names)
        
        #todo try/catch does not currently work with tests, since mock times cannot be injected appropriately
        #try:
        start_windows, stop_windows = self.new_request_eval_time_windows(start_window_orig, stop_window_orig, alternatives_mode)
        # except InvalidTime as err:
        #     err.message = f"{err.message}, Start: {start.name} {start_location}, Destination: {stop.name} {stop_location}"
        #     raise err
        # except InvalidTime2 as err:
        #     err.message = f"{err.message}, Start: {start.name} {start_location}, Destination: {stop.name} {stop_location}"
        #     raise err
        

        # check if order exists already
        if order_id:
            booked_route = self.order2route(order_id)
            if booked_route is not None:
                reason = f"Order id {order_id} is already in use."
                LOGGER.warning(reason)
                raise DuplicatedOrder(reason)
            
        # todo this might be shifted before new_request_eval_time_windows since then addtional station info can be added to error message
        start, stop, community = self.new_request_eval_start_stop(start_location, stop_location)
        station_start = Station(node_id=start.mapId, longitude=start.longitude, latitude=start.latitude)
        station_stop = Station(node_id=stop.mapId, longitude=stop.longitude, latitude=stop.latitude)  

        # eval al available busses for all requested times at once - performance!
        start_times = []
        stop_times = []        

        if start_window_orig:
            stop_times = None
            for start_window_tmp in start_windows:
                start_times.append(start_window_tmp[0])                
        elif stop_window_orig:
            start_times = None
            for stop_window_tmp in stop_windows:
                stop_times.append(stop_window_tmp[1])
        
        # eval the time slot under consideration        
        if start_times and len(start_times) > 1:
            time_slot_complete.append(min(start_times))
            time_slot_complete.append(max(start_times))
        elif stop_times and len(stop_times) > 1:
            time_slot_complete.append(min(stop_times))
            time_slot_complete.append(max(stop_times))
        elif start_window_orig:
            time_slot_complete.append(start_window_orig[0])
            time_slot_complete.append(start_window_orig[1])
        elif stop_window_orig:
            time_slot_complete.append(stop_window_orig[0])
            time_slot_complete.append(stop_window_orig[1])
        
        (busses_for_times, time_in_blocker) = self.Busses.get_available_buses(community=community, start_times=start_times, stop_times=stop_times)
        LOGGER.info(f'available busses calculated {busses_for_times}')

        # if the first solution works, we do not calc alternatives
        break_if_first_window_works = True

        graph = None   

        apriori_times_matrix = {} # once calculated times should be reused within iteration - performance!     

        # find solution for each time window
        # we assume that the original windows are the first in the list
        for windowIndex in range(len(busses_for_times)):
            # timeElapsed = time.time()-timeStarted
            # print('time elapsed')
            # print(timeElapsed)            

            start_window_current=None
            stop_window_current=None            

            if start_window_orig:
                start_window_current = start_windows[windowIndex]
            else:
                stop_window_current = stop_windows[windowIndex]

            # check for time blockers
            if time_in_blocker[windowIndex] == True:
                reason = "No busses found in time window due to blocker."
                result.append((None, reason, start_window_current, stop_window_current))
                if len(busses_for_times) < 2:
                    raise NoBusesDueToBlocker
                else:
                    # go to next time window
                    continue

            # print("requested time")
            # print(start_window_current)
            # print(stop_window_current)
            # print(windowIndex)
            # print(start_windows)
            # print(stop_windows)
            # print(start_times)
            # print(stop_times)
            # print(busses_for_times)

            # Check precomputed routes for an open spot and exit if we find one
            free_routes = self.Routes.get_free_routes(community=community, start_location=start, stop_location=stop,
                start_window=start_window_current, stop_window=stop_window_current, load=load)
            if free_routes:
                solution = {'type': 'free', 'routes': free_routes}
                result.append((solution, reason, start_window_current, stop_window_current))

                if windowIndex == 0:
                        original_time_found = True

                if windowIndex == 0 and break_if_first_window_works: 
                    return result, time_slot_complete, original_time_found
            else:
                # Apparently, there's no fitting solution yet, so let's find one!
                request = Moby(start=station_start, stop=station_stop, start_window=start_window_current, stop_window=stop_window_current, load=load)
                request.order_id = order_id
                # TODO: not yet in use, clarify when to implement
                mandatory_stations = self.Stations.get_mandatory_stations(community=community, before=stop_window_current, after=start_window_current)   

                reason = ''
                busses = busses_for_times[windowIndex]

                bus_ids = [bus.id for bus in busses]

                # Can't solve if we have no busses in time window
                if len(bus_ids) == 0:
                    reason=(f"No busses available at this time! Requested departure time: {start_window_current[0].strftime('%Y/%m/%d, %H:%M')} (UTC), Start: {start.name} {start_location}, Destination: {stop.name} {stop_location}" if start_window_orig
                            else f"No busses available at this time! Requested arrival time: {stop_window_current[1].strftime('%Y/%m/%d, %H:%M')} (UTC), Start: {start.name} {start_location}, Destination: {stop.name} {stop_location}" if stop_window_orig
                            else f"No busses available at this time! Start: {start.name} {start_location}, Destination: {stop.name} {stop_location}")
                    LOGGER.info(reason)
                    result.append((None, reason, start_window_current, stop_window_current))
                    if len(busses_for_times) < 2:
                        raise NoBuses(reason)
                    else:
                        # go to next time window
                        continue

                # cannot solve if buses are too small
                busses_too_small = True
                for bus in busses:
                    if bus.capacity.is_load_allowed(load.standardSeats, load.wheelchairs):
                        busses_too_small = False

                if busses_too_small:
                    reason = f"Insufficient capacity! Capacity of Bus (id={busses[0].id}): {busses[0].capacity.maxNumStandardSeats} standard seats, {busses[0].capacity.maxNumWheelchairs} wheelchair seats. Requested seats: {load.standardSeats} standard seats, {load.wheelchairs} wheelchair seats."
                    LOGGER.info(reason)
                    result.append((None, reason, start_window_current, stop_window_current))
                    if len(busses_for_times) < 2:
                        raise BusesTooSmall(message=reason)
                    else:
                        # go to next time window
                        continue

                # promises are already existing orders within a specified time slot around the current order        
                promises = self.Routes.get_promises(bus_ids=bus_ids, start_time=start_window_current[0] if start_window_current else None, stop_time=stop_window_current[1] if stop_window_current else None)

                t_ref, request, promises, mandatory_stations, busses = self.normalize_dates(request, promises, mandatory_stations, busses)                

                # generate graph including road closures do this only once due to performance!

                # road closures
                if windowIndex == 0:
                    self.RoadClosures.initRoadClosures(community, time_slot_complete[0], time_slot_complete[1])

                # graph
                closuresListLatLon= self.RoadClosures.getRoadClosuresList()

                if self.OSRM_activated == False and graph is None:                    
                    if self.Maps != None:
                        #print('get graph services')                       
                        
                        graph_tmp = self.Maps.get_graph(community)

                        if len(closuresListLatLon):
                            # attach road closures to graph
                            # print("attach detours to graph")
                            # print(closuresListLatLon)
                            add_detours_from_gps(graph_tmp, closuresListLatLon, [])
                        
                        graph = multi2single(graph_tmp)

                elif self.OSRM_activated and len(closuresListLatLon) > 0:
                    LOGGER.error("Road closures not implemented for OSRM!")
                        
                optionsDict = {'slack': 30, 'slack_steps': 3, 'time_offset_factor': self.Config.timeOffset_FactorForDrivingTimes, 'time_service_per_wheelchair' : self.Config.timeService_per_wheelchair}
                optionsDict['build_paths'] = build_paths

                # reduce slack iteration for performance reasons if alternative time windows are under consideration
                if windowIndex > 0 and alternatives_mode != RequestManagerConfig.ALTERNATIVE_SEARCH_NONE:
                    optionsDict['slack'] = 20
                    optionsDict['slack_steps'] = 2

                # timeElapsed = time.time()-timeStarted
                # print('time elapsed before solver')
                # print(timeElapsed)
                raw_solution = self.Solver.solve(graph, self.OSRM_url, request, promises, mandatory_stations, busses, optionsDict, apriori_times_matrix)
                # timeElapsed = time.time()-timeStarted
                # print('time elapsed after solver')
                # print(timeElapsed)

                solution = {'type': 'new', 'routes': []}

                if raw_solution is not None:
                    if build_paths:
                        denormed_solution = self.denormalize_dates(t_ref, raw_solution)

                        for bus_idx, route in denormed_solution.items():
                            if len(route) <= 2:
                                continue
                            trip: Trip = Trip(busses[bus_idx].id, route[1:-1], promised=False, community=community)

                            if len(trip.nodes) >= 2:
                                solution['routes'].append(trip)
                            else:
                                LOGGER.warning(f'Trip has not enough nodes! Ignored in routes.')
                    else:
                        solution['routes'].append(True)

                if solution['routes']:
                    result.append((solution, reason, start_window_current, stop_window_current))  
                    
                    if windowIndex == 0:
                        original_time_found = True

                    if windowIndex == 0 and break_if_first_window_works:                        
                        return result, time_slot_complete, original_time_found                            
                else:
                    result.append((None, reason, start_window_current, stop_window_current))

        return result, time_slot_complete, original_time_found
    
    @staticmethod
    def normalize_dates(request, promises, mandatory_stations, busses, t_ref=None):
        """ Transform datetime objects into int64 values for IP-solver. """
        from copy import deepcopy

        if request.start_window:
            t_min = request.start_window[0]
        elif request.stop_window:
            t_min = request.stop_window[0]
        else:
            raise ValueError('request has neither start nor stop window')
        
        # make the beginning of the previous day the total reference for ip-values
        if t_ref is None:
            t_ref = GpsUtmConverter.normalize_date_get_ref_date_default(t_min)

        norm = lambda t: GpsUtmConverter.normalize_date(t, t_ref)[0]

        if request.start_window:
            request.start_window = (
                norm(request.start_window[0]),
                norm(request.start_window[1]))

        if request.stop_window:
            request.stop_window = (
                norm(request.stop_window[0]),
                norm(request.stop_window[1]))

        busses = deepcopy(busses)
        for bus in busses:
            if bus.work_time:
                bus.work_time = (
                    norm(bus.work_time[0]),
                    norm(bus.work_time[1]),
                )
        
        #TODO:promises
        normed_promises = {}
        for order_id, old_promise in promises.items():
            normed_promises[order_id] = dict()
            start_location, (tMin, tMax) = old_promise['start']
            tMin = norm(tMin)
            tMax = norm(tMax)
            normed_promises[order_id]['start'] = (start_location, (tMin, tMax))
            normed_promises[order_id]['start_lat_lon'] = old_promise['start_lat_lon']
            stop_location, (tMin, tMax) = old_promise['stop']
            tMin = norm(tMin)
            tMax = norm(tMax)
            normed_promises[order_id]['stop'] = (stop_location, (tMin, tMax))
            normed_promises[order_id]['stop_lat_lon'] = old_promise['stop_lat_lon']
            normed_promises[order_id]['load'] = old_promise['load']
            normed_promises[order_id]['loadWheelchair'] = old_promise['loadWheelchair']
        #TODO:mandatory stations

        return t_ref, request, normed_promises, mandatory_stations, busses

    @staticmethod
    def denormalize_dates(t_ref, solution) -> datetime:
        """ Transform int64 values for IP-solver back into datetime objects. """
        if solution is None:
            return None

        denorm = lambda t_normed: GpsUtmConverter.denormalize_date(t_normed,t_ref)[0]

        denormed_solution = dict()
        for bus_id, tour in solution.items():
            denormed_solution[bus_id] = []
            for node in tour:
                node_new = node._replace(time_min=denorm(node.time_min), time_max=denorm(node.time_max))
                denormed_solution[bus_id].append(node_new)

        return denormed_solution

""" Dummy/mockup implementations """
class RoutesDummy():
    def __init__(self, Route, Node, Order, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._routes = Route
        self._nodes = Node
        self._orders = Order
        self._look_around = kwargs.get('look_around', 1)
    def get_free_routes(self, community, start_location, stop_location, start_window, stop_window, load: MobyLoad):
        routes = []
        for route in self._routes.objects.prefetch_related('nodes').all():
            first_node = route.nodes.first()
            last_node = route.nodes.last()
            nodes = route.nodes.prefetch_related('hopOns', 'hopOffs').all()
            if not first_node:
                continue
            if start_window is not None and start_window[1] < first_node.tMin:
                continue
            if stop_window is not None and stop_window[0] > last_node.tMax:
                continue
            
            if start_window:
                start_node, stop_node = self.find_node_pair(route.nodes.all(), start_location, stop_location, start_window)
            elif stop_window:
                stop_node, start_node = self.find_node_pair(reversed(route.nodes.all()), stop_location, start_location, stop_window)
            if (start_node is not None) and (stop_node is not None):
                i=0
                start_idx = stop_idx = None
                for node in nodes:
                    if node.equalsStation(start_location):
                        start_idx=i
                    elif node.equalsStation(stop_location):
                        stop_idx=i
                        break
                    i+=1
            else:
                # there were no matching nodes within this route, so skip it
                continue
            
            if start_idx is None or stop_idx is None:
                LOGGER.error("Either start or stop location didn't match selected route despite it being selected by 'find_node_pair'.", exc_info=True)
                continue

            if not self.free_capacities_sufficient_for_load(route.bus, nodes, load, start_idx, stop_idx+1):
                continue            

            # print('free route found')
            # print(route)

            routes.append(route)
            #TODO: compare locations
        return routes
    def commit(self, solution, Orders):
        """ Take a list of routing.Trip elements and our Order abstraction and create/assign order->route relationships. """

        for route in solution:
            # get all order_ids that are included in this route
            orders = route.clients
            # remenber their previous assignment, because we'll change that attribute
            old_routes = {order_id: self.contains_order(order_id) for order_id in orders}

            # subtract order from old assignment
            for order_id in orders:
                # but only if there actually is one
                if old_routes[order_id] is not None:
                    self.remove_from_route(old_routes[order_id].id, order_id)
            
            # create and save routes that actually serve someone
            if len(orders) > 0:
                db_entry = self.create_route(bus_id=route.bus_id, status='BKD', nodes=route.nodes)
            
            # communicate new assignments with our event bus
            for order_id in orders:
                if old_routes[order_id] is not None:
                    order = self._orders.objects.get(uid=order_id)
                    hopOn = order.hopOnNode
                    hopOff = order.hopOffNode
                    Orders.route_changed(order_id=order_id, new_route_id=db_entry.id, old_route_id=old_routes[order_id].id,
                        start_time_min=hopOn.tMin, start_time_max=hopOn.tMax, stop_time_min=hopOff.tMin, stop_time_max=hopOff.tMax)
    
    def commit_order(self, order_id, load, loadWheelchair, group_id):
        """
        Creates a new order entity in the database if one doesn't already exist, or updates an existing order with the provided details.
        """
        order, is_new = self._orders.objects.get_or_create(uid=order_id)
        order.load = load
        order.loadWheelchair = loadWheelchair
        order.group_id = group_id
        order.save()
        return order

    def remove_from_route(self, route_id, order_id):
        route = self._routes.objects.filter(pk=route_id).first()
        order = self._orders.objects.filter(uid=order_id).first()
        if not route:
            return
        if not order:
            return
        for node in route.nodes.all():
            changed = False
            if order in node.hopOns.all():
                node.hopOns.remove(order)
                changed = True
            if order in node.hopOffs.all():
                node.hopOffs.remove(order)
                changed = True
            if changed:
                node.save()
        if (len(route.clients()) == 0) and not route.blocking:
            route.delete()

    def hop_on(self, solution, restrictions, order_id, Orders) -> bool:
        """
        Used to assign an order to a route, taking into account various constraints such as start and stop windows, load, and wheelchair requirements.
        It iterates through the routes in the solution and checks if there is a valid sequence of nodes that can accommodate the order's requirements.

        Attributes:
            solution: A list of routes, one of which the order will be assigned to
            restrictions: A tuple containing the start and stop locations, start and stop windows, load, and load wheelchair requirements
            order_id: The unique identifier for the order being assigned to a route
            Orders: An instance of the Order model

        Returns:
            orderAdded: A Boolean value indicating whether an order was successfully added to a route
        """

        # Unpack the restrictions tuple into individual variables
        start_location, stop_location, start_window, stop_window, load, loadWheelchair = restrictions

        orderAdded: bool = False

        # Loop over the found routes in solution
        for route in solution:
            # Get all the nodes in a route as well as the orders they are associated with
            nodes = route.nodes.prefetch_related('hopOns', 'hopOffs').all()
            
            if start_window:
                start_node, stop_node = self.find_node_pair(nodes, start_location, stop_location, start_window)
            elif stop_window:
                stop_node, start_node = self.find_node_pair(reversed(nodes), stop_location, start_location, stop_window)
            else:
                continue
                #raise Exception('neither start nor stop window given')
            
            # Skip to the next route if either the start ot stop node couldn't be found
            if (start_node is None) or (stop_node is None):
                continue

            #Reduce set of nodes to all in-between start_ and stop_location
            i=0

            # Loop over the nodes in the current route
            for node in nodes:
                if node.equalsStation(start_location):
                    start_idx=i
                elif node.equalsStation(stop_location):
                    stop_idx=i
                    break
                i+=1
            
            # Skip to the next route if the bus has insufficient free capacity
            if not self.free_capacities_sufficient_for_load(route.bus, nodes, MobyLoad(load, loadWheelchair),start_idx,stop_idx+1):
                continue            

            order, is_new = self._orders.objects.get_or_create(uid=order_id)
            order.load = load
            order.loadWheelchair = loadWheelchair
            order.save()
            start_node.hopOns.add(order)    # add the order to the start_node's hopOns list
            stop_node.hopOffs.add(order)    # add the order to the start_node's hopOffs list

            start_node.save()
            stop_node.save()

            orderAdded = True

            # Send a message to Directus
            Orders.route_confirmed(order_id=order_id, 
                                   route_id=route.id,
                                   start_time_min=start_node.tMin, 
                                   start_time_max=start_node.tMax, 
                                   stop_time_min=stop_node.tMin, 
                                   stop_time_max=stop_node.tMax)
            
            if route.started:
                # FIXME TODO: this is temporary, we should replace this with graphQl oder something alike
                # let order service (and possibly others) know that this route has already started
                Orders.route_started(route_id=route.id)
            break
        else:
            raise Exception('Could not push order onto any of our found solutions.')

        return orderAdded

    @staticmethod
    def find_node_pair(nodes, loc1, loc2, twin):
        """
        Find the first matching node with time window `twin` and location `loc1`
        as well as the next node with location `loc2`.
        """
        tMin, tMax = twin
        node1, node2 = None, None
        # look for matching start node first and find the next stop
        for node in nodes:
            if node1 is None:
                if not node.equalsStation(loc1):
                    continue
                if (node.tMin > tMax) or (node.tMax < tMin):
                    continue
                node1 = node
            else:
                if not node.equalsStation(loc2):
                    continue
                node2 = node
                break
        return node1, node2

    def get_promises(self, bus_ids, start_time, stop_time):
        """ Returns all active promises (i.e., already existing orders) within the given time frame and bus list """

        from collections import defaultdict

        promises = defaultdict(dict)
        time = start_time if start_time else stop_time

        shift_start = time - relativedelta(hours=self._look_around)
        shift_end = time + relativedelta(hours=self._look_around)

        orders = self._orders.objects.prefetch_related('hopOnNode', 'hopOnNode__route', 'hopOnNode__route__bus', 'hopOffNode', 'hopOffNode__route').filter(
            hopOnNode__route__status=self._routes.BOOKED)
        orders = orders.filter(hopOnNode__route__bus__uid__in=bus_ids)
        orders_within_time = orders.filter(hopOnNode__tMin__gte=shift_start, hopOnNode__tMax__lte=shift_end)        

        # extract all order ids satisfiying above simple boundaries
        # then additionally find all order ids not within time but on the found routes, otherwise routes will be split in an unexpected manner
        route_ids = []  

        #print('get_promises')      
        #print(orders_within_time.count())

        for order in orders_within_time.all():
            route_id = order.hopOnNode.route_id
            if not route_id in route_ids:
                route_ids.append(route_id)

        # get all orders with extracted route ids
        orders = orders.filter(hopOnNode__route__id__in=route_ids)        
        #print(orders.count())

        for order in orders.all():
            promises[order.uid]['start'] = (order.hopOnNode.mapId, (order.hopOnNode.tMin, order.hopOnNode.tMax))
            promises[order.uid]['start_lat_lon'] = (order.hopOnNode.latitude, order.hopOnNode.longitude)
            promises[order.uid]['stop'] = (order.hopOffNode.mapId, (order.hopOffNode.tMin, order.hopOffNode.tMax))
            promises[order.uid]['stop_lat_lon'] = (order.hopOffNode.latitude, order.hopOffNode.longitude)
            promises[order.uid]['load'] = order.load
            promises[order.uid]['loadWheelchair'] = order.loadWheelchair

        return promises

    def create_route(self, bus_id, status, nodes):
        """ Create a 'proper' route object from a list of nodes """

        route = self._routes.with_busId(busId=bus_id, status=status)
        route.save()
        for n in nodes:
            node = self._nodes(mapId=n.map_id,tMin=n.time_min,tMax=n.time_max,
                               route=route, latitude=n.lat, longitude=n.lon)            
            node.save()
            if n.hop_on:
                hop_on, created = self._orders.objects.get_or_create(uid=n.hop_on)
                hop_on.hopOnNode = node
                hop_on.save()                
            if n.hop_off:
                hop_off, created = self._orders.objects.get_or_create(uid=n.hop_off)
                hop_off.hopOffNode = node
                hop_off.save()  

        return route
    def contains_order(self, order_id):
        """
        Retrieve a `Route` object that contains a specific `order_id`,
        and checks that the `hopOnNode` and `hopOffNode` of the order are part of the same route.
        If the nodes are not part of the same route, it raises an exception. If no order is found, it returns `None`.
        """
        
        order = self._orders.objects.filter(uid=order_id).first()
        if order is None:
            return None
        route1 = None
        route2 = None

        if order.hopOnNode:
            route1 = order.hopOnNode.route      # get the route associated with the hopOnNode of the order
        if order.hopOffNode:
            route2 = order.hopOffNode.route     # get the route associated with the hopOffNode of the order

        if route1 is None and route2 is None:
            return None

        if route1 is None or route2 is None or route1.id != route2.id:
            LOGGER.warning(f'Node data invalid! Nodes for hop on/off of order {order_id} are not at same route.')
            raise Exception(f'Node data invalid! Nodes for hop on/off of order {order_id} are not at same route.')        
        else:
            return route1
    
    def remove_order(self, order_id):
        order = self._orders.objects.get(uid=order_id)
        order.delete()
        
    @staticmethod
    def node_loads(nodes)-> List[MobyLoad]:
        from django.db.models import Sum
        loads: List[MobyLoad] = []

        load = 0
        loadWheelchair = 0

        for node in nodes:            
            if node.hopOns.count() > 0:
                load += node.hopOns.aggregate(Sum('load'))['load__sum']
                loadWheelchair += node.hopOns.aggregate(Sum('loadWheelchair'))['loadWheelchair__sum']                
            if node.hopOffs.count() > 0:
                load -= node.hopOffs.aggregate(Sum('load'))['load__sum']
                loadWheelchair -= node.hopOffs.aggregate(Sum('loadWheelchair'))['loadWheelchair__sum']
            loads.append(MobyLoad(load,loadWheelchair))
        return loads

    @classmethod
    def free_capacities_sufficient_for_load(cls, bus, nodes, loadAdded:MobyLoad, startIndex, stopIndex) -> bool:
        loads = cls.node_loads(nodes)
        # print('node_loads')
        # print(loads)

        for load in loads[startIndex:stopIndex]:
            loadTmp = load+loadAdded
            if not bus.capa_sufficient_for_load(loadTmp):
                #print("Bus capa cannot accept added load")
                return False
        return True

class SolverDummy():
    def solve(self, graph, OSRM_url:str, request, promises, mandatory_stations, busses, options, apriori_times_matrix):
        
        from routing.routing import new_routing, Moby
        promise_mobies: dict[int, Moby] = {}
        for order_id, promise in promises.items():
            start_location, start_window = promise['start']
            start_lat, start_lon = promise['start_lat_lon']
            stop_location, stop_window = promise['stop']
            stop_lat, stop_lon = promise['stop_lat_lon']
            load = MobyLoad(promise['load'], promise['loadWheelchair'])
            station_start = Station(node_id=start_location, latitude=start_lat, longitude=start_lon)
            station_stop = Station(node_id=stop_location, latitude=stop_lat, longitude=stop_lon)
            promise_mobies[order_id] = Moby(station_start, station_stop, start_window, stop_window, load)
            promise_mobies[order_id].order_id = order_id
        
        solution = new_routing(graph, OSRM_url, request, promise_mobies, mandatory_stations, busses, options, apriori_times_matrix)
        if solution is None:
            return None
        routing = solution[1]
        return self.moby2order(routing)
    @staticmethod
    def moby2order(routing):
        """ translate moby objects in solution nodes to order ids for external use """
        out = dict()
        for bus, nodes in routing.items():
            out[bus] = []
            for node in nodes:
                hop_off = node.hop_off.order_id if node.hop_off else None
                hop_on = node.hop_on.order_id if node.hop_on else None
                out[bus].append(node._replace(hop_on=hop_on, hop_off=hop_off))
        return out
    
class OrdersMQ():
    def __init__(self, MessageBus, Listener):
        self._messageBus = MessageBus
        self._listener = Listener
    def listen(self):
        self._listener.listen()

    # ------------------- Messages sent to Directus -------------------
    def route_changed(self, order_id, new_route_id, old_route_id, start_time_min, start_time_max, stop_time_min, stop_time_max):
        LOGGER.info(f'route_changed {order_id}')
        self._messageBus.RouteChangedIntegrationEvent(orderId=order_id, oldRouteId=old_route_id, newRouteId=new_route_id,
            startTimeMinimum=start_time_min,
            startTimeMaximum=start_time_max,
            destinationTimeMinimum=stop_time_min,
            destinationTimeMaximum=stop_time_max)
    def route_rejected(self, order_id, reason):
        LOGGER.info(f'route_rejected {order_id}, reason: {reason}')
        self._messageBus.RouteRejectedIntegrationEvent(orderId=order_id, cancellationReason=reason)
    def route_confirmed(self, order_id, route_id, start_time_min, start_time_max, stop_time_min, stop_time_max):
        LOGGER.info(f'route_confirmed {order_id}')
        self._messageBus.RouteConfirmedIntegrationEvent(orderId=order_id, routeId=route_id,
            startTimeMinimum=start_time_min,
            startTimeMaximum=start_time_max,
            destinationTimeMinimum=stop_time_min,
            destinationTimeMaximum=stop_time_max)
    def route_started(self, route_id):
        LOGGER.info(f'route_started {route_id}')
        self._messageBus.RouteStartedIntegrationEvent(routeId=route_id)
    def route_finished(self, route_id):
        LOGGER.info(f'route_finished {route_id}')
        self._messageBus.RouteFinishedIntegrationEvent(routeId=route_id)
    def route_frozen(self, route_id, start_time_min):
        LOGGER.info(f'route_frozen {route_id}')
        self._messageBus.RouteFrozenIntegrationEvent(routeId=route_id, startTimeMinimum=start_time_min)

    # ------------------- Messages received from Directus -------------------
    # These methods register the callback functions for different events
    def register_OrderStartedIntegrationEvent(self, OrderStartedCallback):
        self._listener.register(key='OrderStartedIntegrationEvent', callback=OrderStartedCallback)
    def register_OrderCancelledIntegrationEvent(self, OrderCancelledCallback):
        self._listener.register(key='OrderCancelledIntegrationEvent', callback=OrderCancelledCallback)
    def register_UpdateBusPositionIntegrationEvent(self, UpdateBusPositionCallback):
        self._listener.register(key='UpdateBusPositionIntegrationEvent', callback=UpdateBusPositionCallback)
    def register_StopAddedIntegrationEvent(self, StopAddedCallback):
        self._listener.register(key='StopAddedIntegrationEvent', callback=StopAddedCallback)
    def register_StopDeletedIntegrationEvent(self, StopDeletedCallback):
        self._listener.register(key='StopDeletedIntegrationEvent', callback=StopDeletedCallback)
    def register_StopUpdatedIntegrationEvent(self, StopUpdatedCallback):
        self._listener.register(key='StopUpdatedIntegrationEvent', callback=StopUpdatedCallback)
    def register_BusDeletedIntegrationEvent(self, BusDeletedIntegrationCallback):
        self._listener.register(key='BusDeletedIntegrationEvent', callback=BusDeletedIntegrationCallback)
    def register_BusUpdatedIntegrationEvent(self, BusUpdatedIntegrationCallback):
        self._listener.register(key='BusUpdatedIntegrationEvent', callback=BusUpdatedIntegrationCallback)
