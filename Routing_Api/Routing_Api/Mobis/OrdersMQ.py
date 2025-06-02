"""
 Copyright © 2025 IAV GmbH Ingenieurgesellschaft Auto und Verkehr, All Rights Reserved.
 
 Licensed under the Apache License, Version 2.0 (the "License");
 you may not use this file except in compliance with the License.
 You may obtain a copy of the License at
 
 http://www.apache.org/licenses/LICENSE-2.0
 
 Unless required by applicable law or agreed to in writing, software
 distributed under the License is distributed on an "AS IS" BASIS,
 WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
 See the License for the specific language governing permissions and
 limitations under the License.
 
 SPDX-License-Identifier: Apache-2.0
"""
from datetime import datetime
import logging

LOGGER = logging.getLogger('Mobis.services')

class OrdersMQ():
    def __init__(self, MessageBus, Listener):
        self._messageBus = MessageBus
        self._listener = Listener
    def listen(self):
        self._listener.listen()

    # ------------------- Messages sent to Directus -------------------
    def route_changed(self, order_id, new_route_id, old_route_id, start_time_min, start_time_max, stop_time_min, stop_time_max, bus_id : int):
        LOGGER.info(f'route_changed for order {order_id}, route old {old_route_id}, route new {new_route_id}, bus {bus_id}')
        self._messageBus.RouteChangedIntegrationEvent(orderId=order_id, oldRouteId=old_route_id, newRouteId=new_route_id,
            startTimeMinimum=start_time_min,
            startTimeMaximum=start_time_max,
            destinationTimeMinimum=stop_time_min,
            destinationTimeMaximum=stop_time_max,
            busId=bus_id)
        
    def current_route_changed_driver_warning(self, route_id : int, bus_id : int):
        LOGGER.info(f'current route_changed driver warning: route {route_id}, bus {bus_id}')
        self._messageBus.CurrentRouteChangedDriverWarningIntegrationEvent(route_id=route_id, bus_id=bus_id)
        
    def route_rejected(self, order_id=0, reason="No reason provided", start="", destination="", bookingTime="", seats=0, seats_wheelchair=0):
        bookingTime = self.datetime2isoformat(bookingTime)
        LOGGER.info(f'route_rejected {order_id}, reason: {reason}, start: {start}, destination: {destination}, bookingTime: {bookingTime}, seats: {seats}, seats_wheelchair: {seats_wheelchair}')
        
        self._messageBus.RouteRejectedIntegrationEvent(orderId=order_id, reason=reason, start=start, destination=destination, bookingTime=bookingTime, seats=seats, seats_wheelchair=seats_wheelchair)

    def datetime2isoformat(self, date_time: any) -> str:
        LOGGER.info(f'datetime2isoformat: {date_time}')       
        if isinstance(date_time, datetime):
            # If date_time is already a datetime object, convert it to ISO format
            new_datetime = date_time.isoformat()
            LOGGER.info(f'date_time is in datetime object. New_datetime in isoformat {new_datetime}')            
            return new_datetime
        elif isinstance(date_time, str):
            LOGGER.info(f'date_time is a string')
            try:
                LOGGER.info(f'delete milliseconds and replace time zone offset (000Z / 0000) with +00:00 - {date_time}')
                date_string_cleaned = date_time.split('.')[0] + '+00:00'
                parsed_datetime = datetime.strptime(date_string_cleaned, '%Y-%m-%dT%H:%M:%S%z')
                LOGGER.info(f'parsed_datetime : {parsed_datetime}')
                
                # convert datetime-Objekts to ISO format
                new_datetime = parsed_datetime.isoformat()
                LOGGER.info(f'new_datetime in isoformat: {new_datetime}')
                return new_datetime
            except ValueError as err:
                LOGGER.error(f'error in formating of string datetime: {err}')
                return ""
        else:
            LOGGER.info(f'date_time is neither a string nor a datetime object')
            return ""
    
    def route_confirmed(self, order_id, route_id, start_time_min, start_time_max, stop_time_min, stop_time_max, bus_id):
        LOGGER.info(f'route_confirmed for order {order_id}, route {route_id}, bus {bus_id}')
        self._messageBus.RouteConfirmedIntegrationEvent(orderId=order_id, routeId=route_id,
            startTimeMinimum=start_time_min,
            startTimeMaximum=start_time_max,
            destinationTimeMinimum=stop_time_min,
            destinationTimeMaximum=stop_time_max,
            busId = bus_id)
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
