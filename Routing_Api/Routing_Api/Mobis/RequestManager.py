import json
import os
import time
from datetime import datetime, timezone, timedelta
from functools import wraps
from typing import List

from dateutil.parser import parse
from dateutil.relativedelta import relativedelta
from dateutil.tz import tzutc
from django.core.exceptions import ObjectDoesNotExist
from django.db import transaction, close_old_connections

import Routing_Api.mockups.RoadClosures
from Routing_Api.Mobis.RequestManagerConfig import RequestManagerConfig
from Routing_Api.Mobis.models import Route
from routing.OSRM_directions import OSRM
from routing.errors import DuplicatedOrder, CommunityConflict, SameStop, NoStop, NoBuses, NoBusesDueToBlocker, \
    BusesTooSmall, \
    InvalidTime, InvalidTime2, MalformedMessage
from routing.routingClasses import MobyLoad, Station
from routing.rutils import add_detours_from_gps, multi2single, GpsUtmConverter

import logging

LOGGER = logging.getLogger('Mobis.services')
UTC = tzutc()


def rabbit_callback(fields):
    """
    Decorator function for the callback methods.
    Takes another function as an argument and returns a new function that "wraps" the original function.
    Unpacks the message payload and resets the database connection.

    Args:
        fields (list): A list of required fields to check in the message.

    Returns:
        function: A decorator function that wraps the original function.
    """

    def message_decorator(fun):
        @wraps(fun)
        def wrapper(self, ch=None, method=None, properties=None, body=None):
            try:
                del ch
                del method
                del properties
                message = unpack_message(body=body, fields=fields)
                close_old_connections()
                return fun(self, message)
            except Exception as e:
                LOGGER.error(f'Error in rabbit_callback wrapper: {e}')
                raise e

        return wrapper

    return message_decorator


class MalformedMessage(Exception):
    pass


def unpack_message(body=None, fields=None):
    """
    Unpacks a message from a JSON string or dictionary and checks for required fields.

    Args:
        body (Union[bytes, str, dict]): The message body to unpack.
        fields (list): A list of required fields to check in the message.

    Returns:
        Message: An instance of the Message class with the unpacked data.

    Raises:
        TypeError: If the body is not bytes, str, or dict.
        json.JSONDecodeError: If the body is a string that cannot be decoded as JSON.
        ValueError: If any required fields are missing from the message.
    """

    class Message:
        def __init__(self, data):
            LOGGER.info(f'Message data: {data}')
            self.__dict__ = data

    try:
        # Check if body is a dictionary
        if isinstance(body, dict):
            data = body
        else:
            # If body is not bytes or a string, return errors
            if not isinstance(body, (bytes, str)):
                raise TypeError("body must be bytes, str, or dict")

            # If body bytes are, convert to string
            if isinstance(body, bytes):
                body = body.decode('utf-8')
                LOGGER.info(f'decodeed body to utf-8: {body}')
                
            # Convert the JSON-String to Dictionary
            data = json.loads(body)
            if not isinstance(data, dict):
                data = json.loads(data)
            LOGGER.info(f'data: {data}')

        # Verify that all required fields are present
        missing_fields = [field for field in fields if field not in data]
        if missing_fields:
            raise ValueError(f'missing fields {missing_fields}, got {body}')
        return Message(data)

    except TypeError as e:
        LOGGER.error(f'TypeError: {e}', extra={'body': body}, exc_info=True)
        raise e
    except json.JSONDecodeError as e:
        LOGGER.error(f'JSONDecodeError: {e}', extra={'body': body}, exc_info=True)
        raise e
    except ValueError as e:
        LOGGER.error(f'ValueError: {e}', extra={'body': body}, exc_info=True)
        raise e
    except Exception as e:
        LOGGER.error('Unpacks a message failed: %s', e, extra={'body': body}, exc_info=True)
        raise ValueError(f'Unexpected error: {e}')


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
        self.Orders.register_OrderCancelledIntegrationEvent(
            self.OrderCancelledCallback)
        self.Orders.register_OrderStartedIntegrationEvent(
            self.OrderStartedCallback)
        self.Orders.register_UpdateBusPositionIntegrationEvent(
            self.UpdateBusPositionCallback)
        self.Orders.register_StopAddedIntegrationEvent(
            self.StopAddedIntegrationCallback)
        self.Orders.register_StopDeletedIntegrationEvent(
            self.StopDeletedIntegrationCallback)
        self.Orders.register_StopUpdatedIntegrationEvent(
            self.StopUpdatedIntegrationCallback)
        self.Orders.register_BusDeletedIntegrationEvent(
            self.BusDeletedIntegrationCallback)
        self.Orders.register_BusUpdatedIntegrationEvent(
            self.BusUpdatedIntegrationCallback)
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
        # retrieve the bus with the matching id from the db
        bus = self.Busses._busses.objects.get(uid=message.Id)
        for route in self.Routes._routes.objects.filter(bus=bus):
            for order in route.clients():  # route.clients() returns a set of order ids
                self.cancel_order(order_id=order)
                self.Orders.route_rejected(
                    order_id=order, reason='The bus for which this route was planned got deleted.')
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
                # route.clients() returns a set of order ids
                for order in reversed(sorted(route.clients())):
                    self.cancel_order(order_id=order)
                    self.Orders.route_rejected(
                        order_id=order, reason='The bus for which this route was planned got deleted.')

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
            # print(station)

            # if the mapId of the updated station is different from the mapId of the existing station, the station position has changed
            if mapId != station.mapId:
                # TODO eventuell muss man hier genauer spezifizieren, bei anderer MapID muss sich das noch nicht zwingend geaendert haben, oder?...(OSRM, andere Karte...),
                # in den meisten Faellen duerfte das Kriterium aber passen
                # die Stelle mit mapId muss evtl umgestellt werden auf node.equalsStation(station) ??

                # reject and delete orders which have the old map node as a hopOn or a hopOff and then delete this node
                nodes = self.Routes._nodes.objects.prefetch_related('route', 'hopOns', 'hopOffs') \
                    .filter(mapId=station.mapId, route__community=message.CommunityId).distinct()
                for node in nodes:
                    if node.route.status == Route.BOOKED or node.route.status == Route.DRAFT:  # DO NOT CHANGE FINISHED ROUTES!
                        for order in node.hopOns.all() | node.hopOffs.all():
                            rejectedOrders.append(order.uid)
                            self.Orders.route_rejected(order_id=order.uid,
                                                       reason=f"Start or destination of order (id = {order.uid}) has changed! Old stop: {station.name} ({station.latitude}, {station.longitude}), New stop: {message.Name} ({message.Latitude}, {message.Longitude})")
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
            nodes = self.Routes._nodes.objects.prefetch_related('route', 'hopOns', 'hopOffs') \
                .filter(route__community=station.community).distinct()
            for node in nodes:
                if node.equalsStation(station):
                    for order in node.hopOns.all() | node.hopOffs.all():
                        self.Orders.route_rejected(order_id=order.uid,
                                                   reason=f"Start or destination of order (id = {order.uid}) has been deleted! Deleted stop: {station.name} ({station.latitude}, {station.longitude})")
                        order.delete()
                    node.delete()

            station.delete()

        except ObjectDoesNotExist:
            pass

    @rabbit_callback(fields=['BusId', 'Latitude', 'Longitude'])
    def UpdateBusPositionCallback(self, message):
        """ Updates the position of the bus in the database by setting the latitude and longitude from the received message. """
        LOGGER.info(f'UpdateBusPositionCallback')
        self.Busses.update(
            bus_id=message.BusId, latitude=message.Latitude, longitude=message.Longitude)

    @rabbit_callback(fields=['Id'])
    @transaction.atomic
    def OrderCancelledCallback(self, message):
        """ Cancels the order with the corresponding id. """
        LOGGER.info(f'OrderCancelledCallback order id: {message.Id}')
        try:
            self.cancel_order(order_id=message.Id)
        except ObjectDoesNotExist:
            pass

    @rabbit_callback(
        fields=['Id', 'StartLatitude', 'StartLongitude', 'EndLatitude', 'EndLongitude', 'IsDeparture', 'Time', 'Seats',
                'SeatsWheelchair'])
    # if any part of this method fails, the entire database transaction will be rolled back
    @transaction.atomic
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
            startWindow = (time, time + relativedelta(minutes=10))
            stopWindow = None
        else:
            startWindow = None
            stopWindow = (time - relativedelta(minutes=10), time)

        try:
            self.order(start_location=startLocation, stop_location=stopLocation, start_window=startWindow,
                       stop_window=stopWindow, load=message.Seats, loadWheelchair=message.SeatsWheelchair,
                       order_id=message.Id)
        except DuplicatedOrder as err:
            LOGGER.warning('Order_id already exists: %s', err,
                           extra={'body': message}, exc_info=True)
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
            self.Orders.route_rejected(
                order_id=message.Id, reason=f'an error occurred: {err}')
            LOGGER.error('Order could not be processed: %s', err,
                         extra={'body': message}, exc_info=True)

    def order(self, start_location, stop_location, start_window, stop_window, load=1, loadWheelchair=0, group_id=None,
              order_id=None):
        """
        Creates a new order and attempts to find a route for it.
        If a route is found, it commits the order and returns the order ID.
        If no route can be found, it rejects the order and returns `None`.
        """

        LOGGER.info(f'order {order_id}')
        results, time_slot, original_time_found = self.new_request(start_location, stop_location, start_window,
                                                                   stop_window, MobyLoad(
                load, loadWheelchair), group_id, order_id, RequestManagerConfig.ALTERNATIVE_SEARCH_NONE)
        (solution, comment, start_window, stop_window) = results[0]

        if solution is None:
            LOGGER.info('found no valid solution for request')
            self.Orders.route_rejected(order_id=order_id, reason=comment)
            return None

        if solution['type'] == 'new':
            self.Routes.commit_order(
                order_id=order_id, load=load, loadWheelchair=loadWheelchair, group_id=group_id)
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
                                        stop_time_max=hopOff.tMax,
                                        bus_id=route.busId)
            return order_id

        if solution['type'] == 'free':
            [starts, stops] = self.Stations.get_stops_by_geo_locations(
                [start_location, stop_location])
            start_station = starts[0]
            stop_station = stops[0]
            solution['restrictions'] = start_station, stop_station, start_window, stop_window, load, loadWheelchair
            # assign an order to a route
            self.Routes.hop_on(
                solution['routes'], solution['restrictions'], order_id, self.Orders)
            return order_id

        self.Orders.route_rejected(
            order_id=order_id, reason='unexpected case: solution type is neither "new" nor "free"')
        raise ValueError('solution type is neither new nor free')

    LOGGER = logging.getLogger(__name__)

    def cancel_order(self, order_id):
        """
        Cancels an order with the specified ID and removes it from the list of orders.
        Also removes any associated hop-on or hop-off nodes that become empty after the order is deleted.
        """
        LOGGER.info(f'cancel_order {order_id}')

        try:
            order = self.Routes._orders.objects.get(uid=order_id)
            hopOnNode = order.hopOnNode
            hopOffNode = order.hopOffNode
        except self.Routes._orders.DoesNotExist:
            LOGGER.error(f'Order with ID {order_id} does not exist.')
            return
        except Exception as e:
            LOGGER.error(f'Error retrieving order with ID {order_id}: {e}')
            return

        try:
            self.Routes.remove_order(order_id)
        except Exception as e:
            LOGGER.error(f'Error removing order with ID {order_id}: {e}')
            return

        LOGGER.info(
            f'remove hopOn or hopOff nodes that are empty after order delete:')
        try:
            for node in self.Routes._nodes.objects.all():
                if not node.has_order:
                    if node.id == hopOnNode.id or node.id == hopOffNode.id:
                        LOGGER.info(f'delete empty node {node.id}')
                        node.delete()
        except Exception as e:
            LOGGER.error(f'Error processing nodes after order deletion: {e}')

    def is_bookable(self, start_location, stop_location, start_window, stop_window, load=1, loadWheelchair=0,
                    group_id=None, alternatives_mode=RequestManagerConfig.ALTERNATIVE_SEARCH_NONE):
        """Return result, code and message for a given request."""
        LOGGER.info(f'is_bookable')

        times_found = []
        time_slot_min_max = []  # hier noch das Zeitfenster, das geprueft wurde, draufschreiben
        result = (False, -1, 'nothing calculated',
                  times_found, time_slot_min_max)
        count_solutions_found = 0

        # Get the stops' names
        [starts, stops] = self.Stations.get_stops_by_geo_locations(
            [start_location, stop_location])

        try:
            try:
                results_all, time_slot_min_max, original_time_found = self.new_request(
                    start_location, stop_location, start_window, stop_window, MobyLoad(load, loadWheelchair), None,
                    group_id, alternatives_mode, False)

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
                        result = (True, self.POSSIBLE, 'Hurray',
                                  times_found, time_slot_min_max)
                    else:
                        result = (True, self.NO_BUSES_ALTERNATIVE_FOUND,
                                  'Hurray', times_found, time_slot_min_max)
                else:
                    # The value of start_window may change, when alternatives_mode is activated.
                    # new_request() calls new_request_eval_time_windows(), which creates a list of time windows. If alternatives_mode is activated, results_all grows bigger
                    # results_all[0] contains the very first result (doesn't matter if a routing solution has been found or not)
                    # results_all[0][2] contains start_window of the first result
                    # results_all[0][2][0] contains the first time of the start_window of the first result
                    # Therefore, results_all[0][2][0] always holds the very first start_window, regardless of how big results_all

                    if alternatives_mode == RequestManagerConfig.ALTERNATIVE_SEARCH_NONE:
                        reason = f"No routing found for request - Start: {starts[0].name} {start_location}, Destination: {stops[0].name} {stop_location}, Time: {results_all[0][2][0].strftime('%Y/%m/%d, %H:%M')} (UTC), Seats: {load} standard, {loadWheelchair} wheelchair."
                        result = (False, self.NO_ROUTING, reason,
                                  times_found, time_slot_min_max)
                        self.Orders.route_rejected(order_id=-1, reason=reason)
                    else:
                        reason = f"No routing found for request (including alternatives search) - Start: {starts[0].name} {start_location}, Destination: {stops[0].name} {stop_location}, Time: {results_all[0][2][0].strftime('%Y/%m/%d, %H:%M')} (UTC), Seats: {load} standard, {loadWheelchair} wheelchair."
                        result = (False, self.NO_BUSES_NO_ALTERNATIVE_FOUND,
                                  reason, times_found, time_slot_min_max)
                        self.Orders.route_rejected(order_id=-1, reason=reason)

            except SameStop as err:
                self.Orders.route_rejected(order_id=-1, reason=err.message)
                result = (False, self.SAME_STOPS, err.message,
                          times_found, time_slot_min_max)
            except NoStop as err:
                self.Orders.route_rejected(order_id=-1, reason=err.message)
                result = (False, self.NO_STOPS, err.message,
                          times_found, time_slot_min_max)
            except CommunityConflict as err:
                self.Orders.route_rejected(order_id=-1, reason=err.message)
                result = (False, self.NO_COMMUNITY, err.message,
                          times_found, time_slot_min_max)
            except NoBuses as err:
                self.Orders.route_rejected(order_id=-1, reason=err.message)
                result = (False, self.NO_BUSES, err.message,
                          times_found, time_slot_min_max)
            except NoBusesDueToBlocker as err:
                self.Orders.route_rejected(order_id=-1, reason=err.message)
                result = (False, self.NO_BUSES_DUE_TO_BLOCKER,
                          err.message, times_found, time_slot_min_max)
            except BusesTooSmall as err:
                self.Orders.route_rejected(order_id=-1, reason=err.message)
                result = (False, self.BUSES_TOO_SMALL, err.message,
                          times_found, time_slot_min_max)
            except InvalidTime as err:
                self.Orders.route_rejected(order_id=-1, reason=err.message)
                result = (False, self.WRONG_TIME_PAST, err.message,
                          times_found, time_slot_min_max)
            except InvalidTime2 as err:
                self.Orders.route_rejected(order_id=-1, reason=err.message)
                result = (False, self.WRONG_TIME_FUTURE, err.message,
                          times_found, time_slot_min_max)

            return result
        except Exception as err:  # catch any other exceptions
            self.Orders.route_rejected(
                order_id=-1, reason=('uncaught exception %s', err))
            LOGGER.error('uncaught exception %s', err, exc_info=True)
            raise err

    def order2route(self, order_id):
        """ Return the `Route` object that contains the order with the matching `order_id`. """
        route = self.Routes.contains_order(order_id)
        return route

    def new_request_eval_start_stop(self, start_location, stop_location):
        # get all bus stops around the start and stop position
        LOGGER.info(f'startLocation: {start_location}, stopLocation: {stop_location}')
        [starts, stops] = self.Stations.get_stops_by_geo_locations(
            [start_location, stop_location])
        LOGGER.info(f'starts: {starts}, stops: {stops}')

        if not starts:
            raise NoStop(message=f"No bus stop was found for the given start location (lat: {start_location[0]}, long: {start_location[1]})!")

        if not stops:
            raise NoStop(message=f"No bus stop was found for the given destination location (lat: {stop_location[0]}, long: {stop_location[1]})!")

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
        stops = list(filter(lambda s: s.community == community, stops))

        # keep only one of each for now
        start = starts[0]
        stop = stops[0]

        if start == stop:
            reason = f"Start and destination are the same or too close to each other! Start: {start.name} (mapId: {start.mapId}, lat: {start.latitude}, long: {start.longitude}), Destination: {stop.name} (mapId: {stop.mapId}, lat: {stop.latitude}, long: {stop.longitude})"
            LOGGER.debug(reason)
            raise SameStop(message=reason)

        return start, stop, community

    def new_request_eval_time_windows(self, start_window, stop_window, alternatives_mode):
        time_windows = []

        # order time needs min offset from now
        offsetMinutes_start = self.Config.timeOffset_MinMinutesToOrderFromNow
        # TODO wenn die Ankunftszeit vorgegeben ist, dann ist die Untergrenze eigtl erst nach dem Routing pruefbar, pragmatisch koennte man schon mal in die time-matrix schauen... (?)
        offsetMinutes_stop = offsetMinutes_start + 15

        # print('new_request_eval_time_windows offsetMinutes_start: ' + str(offsetMinutes_start))

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
            time_delta_alternatives_minutes = int(
                os.environ.get('ALTERNATIVES_DELTA_MINUTES', 10))
            time_delta_steps = int(os.environ.get(
                'ALTERNATIVES_DELTA_STEPS', 12))
            time_window_ref = time_windows[0]

            for iStep in range(1, time_delta_steps + 1):
                time_delta = timedelta(
                    minutes=iStep * time_delta_alternatives_minutes)

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

    def new_request(self, start_location, stop_location, start_window_orig, stop_window_orig,
                    load: MobyLoad = MobyLoad(1, 0), group_id=None, order_id=None,
                    alternatives_mode=RequestManagerConfig.ALTERNATIVE_SEARCH_NONE, build_paths=True):
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

        # todo try/catch does not currently work with tests, since mock times cannot be injected appropriately
        # try:
        start_windows, stop_windows = self.new_request_eval_time_windows(
            start_window_orig, stop_window_orig, alternatives_mode)
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
        start, stop, community = self.new_request_eval_start_stop(
            start_location, stop_location)
        station_start = Station(
            node_id=start.mapId, longitude=start.longitude, latitude=start.latitude)
        station_stop = Station(
            node_id=stop.mapId, longitude=stop.longitude, latitude=stop.latitude)

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

        (busses_for_times, time_in_blocker) = self.Busses.get_available_buses(
            community=community, start_times=start_times, stop_times=stop_times)
        LOGGER.info(f'available busses calculated {busses_for_times}')

        # if the first solution works, we do not calc alternatives
        break_if_first_window_works = True

        graph = None

        # once calculated times should be reused within iteration - performance!
        apriori_times_matrix = {}

        # find solution for each time window
        # we assume that the original windows are the first in the list
        for windowIndex in range(len(busses_for_times)):
            # timeElapsed = time.time()-timeStarted
            # print('time elapsed')
            # print(timeElapsed)

            start_window_current = None
            stop_window_current = None

            if start_window_orig:
                start_window_current = start_windows[windowIndex]
            else:
                stop_window_current = stop_windows[windowIndex]

            # check for time blockers
            if time_in_blocker[windowIndex] == True:
                reason = "No busses found in time window due to blocker."
                result.append(
                    (None, reason, start_window_current, stop_window_current))
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
                                                      start_window=start_window_current,
                                                      stop_window=stop_window_current, load=load)
            if free_routes:
                solution = {'type': 'free', 'routes': free_routes}
                result.append(
                    (solution, reason, start_window_current, stop_window_current))

                if windowIndex == 0:
                    original_time_found = True

                if windowIndex == 0 and break_if_first_window_works:
                    return result, time_slot_complete, original_time_found
            else:
                # Apparently, there's no fitting solution yet, so let's find one!
                request = Moby(start=station_start, stop=station_stop,
                               start_window=start_window_current, stop_window=stop_window_current, load=load)
                request.order_id = order_id
                # TODO: not yet in use, clarify when to implement
                mandatory_stations = self.Stations.get_mandatory_stations(
                    community=community, before=stop_window_current, after=start_window_current)

                reason = ''
                busses = busses_for_times[windowIndex]

                bus_ids = [bus.id for bus in busses]
                vehicle_types = [bus.vehicleType for bus in busses]

                # Can't solve if we have no busses in time window
                if len(bus_ids) == 0:
                    reason = (
                        f"No busses available at this time! Requested departure time: {start_window_current[0].strftime('%Y/%m/%d, %H:%M')} (UTC), Start: {start.name} {start_location}, Destination: {stop.name} {stop_location}" if start_window_orig
                        else f"No busses available at this time! Requested arrival time: {stop_window_current[1].strftime('%Y/%m/%d, %H:%M')} (UTC), Start: {start.name} {start_location}, Destination: {stop.name} {stop_location}" if stop_window_orig
                        else f"No busses available at this time! Start: {start.name} {start_location}, Destination: {stop.name} {stop_location}")
                    LOGGER.info(reason)
                    result.append(
                        (None, reason, start_window_current, stop_window_current))
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
                    result.append(
                        (None, reason, start_window_current, stop_window_current))
                    if len(busses_for_times) < 2:
                        raise BusesTooSmall(message=reason)
                    else:
                        # go to next time window
                        continue

                # promises are already existing orders within a specified time slot around the current order
                promises = self.Routes.get_promises(
                    bus_ids=bus_ids, start_time=start_window_current[0] if start_window_current else None,
                    stop_time=stop_window_current[1] if stop_window_current else None)

                t_ref, request, promises, mandatory_stations, busses = self.normalize_dates(
                    request, promises, mandatory_stations, busses)

                # generate graph including road closures do this only once due to performance!

                # road closures
                if windowIndex == 0:
                    self.RoadClosures.initRoadClosures(
                        community, time_slot_complete[0], time_slot_complete[1])

                # graph
                closuresListLatLon = self.RoadClosures.getRoadClosuresList(
                    bus_ids, vehicle_types)

                if self.OSRM_activated == False and graph is None:
                    if self.Maps != None:
                        # print('get graph services')

                        graph_tmp = self.Maps.get_graph(community)

                        if len(closuresListLatLon):
                            # attach road closures to graph
                            # print("attach detours to graph")
                            # print(closuresListLatLon)
                            add_detours_from_gps(
                                graph_tmp, closuresListLatLon, [])

                        graph = multi2single(graph_tmp)

                elif self.OSRM_activated and len(closuresListLatLon) > 0:
                    LOGGER.error("Road closures not implemented for OSRM!")

                optionsDict = {'slack': 30, 'slack_steps': 3,
                               'time_offset_factor': self.Config.timeOffset_FactorForDrivingTimes,
                               'time_service_per_wheelchair': self.Config.timeService_per_wheelchair}
                optionsDict['build_paths'] = build_paths

                # reduce slack iteration for performance reasons if alternative time windows are under consideration
                if windowIndex > 0 and alternatives_mode != RequestManagerConfig.ALTERNATIVE_SEARCH_NONE:
                    optionsDict['slack'] = 20
                    optionsDict['slack_steps'] = 2

                # timeElapsed = time.time()-timeStarted
                # print('time elapsed before solver')
                # print(timeElapsed)
                raw_solution = self.Solver.solve(
                    graph, self.OSRM_url, request, promises, mandatory_stations, busses, optionsDict,
                    apriori_times_matrix)
                # timeElapsed = time.time()-timeStarted
                # print('time elapsed after solver')
                # print(timeElapsed)

                solution = {'type': 'new', 'routes': []}

                if raw_solution is not None:
                    if build_paths:
                        denormed_solution = self.denormalize_dates(
                            t_ref, raw_solution)

                        for bus_idx, route in denormed_solution.items():
                            if len(route) <= 2:
                                continue
                            trip: Trip = Trip(
                                busses[bus_idx].id, route[1:-1], promised=False, community=community)

                            if len(trip.nodes) >= 2:
                                solution['routes'].append(trip)
                            else:
                                LOGGER.warning(
                                    f'Trip has not enough nodes! Ignored in routes.')
                    else:
                        solution['routes'].append(True)

                if solution['routes']:
                    result.append(
                        (solution, reason, start_window_current, stop_window_current))

                    if windowIndex == 0:
                        original_time_found = True

                    if windowIndex == 0 and break_if_first_window_works:
                        return result, time_slot_complete, original_time_found
                else:
                    result.append(
                        (None, reason, start_window_current, stop_window_current))

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

        def norm(t):
            return GpsUtmConverter.normalize_date(t, t_ref)[0]

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

        # TODO:promises
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
        # TODO:mandatory stations

        return t_ref, request, normed_promises, mandatory_stations, busses

    @staticmethod
    def denormalize_dates(t_ref, solution) -> datetime:
        """ Transform int64 values for IP-solver back into datetime objects. """
        if solution is None:
            return None

        def denorm(t_normed):
            return GpsUtmConverter.denormalize_date(
                t_normed, t_ref)[0]

        denormed_solution = dict()
        for bus_id, tour in solution.items():
            denormed_solution[bus_id] = []
            for node in tour:
                node_new = node._replace(time_min=denorm(
                    node.time_min), time_max=denorm(node.time_max))
                denormed_solution[bus_id].append(node_new)

        return denormed_solution
