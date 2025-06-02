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
from Routing_Api.Mobis.EventBus import AsyncPublisher, Consumer, UnthreadedPublisher
import json
from datetime import datetime
import logging

LOGGER = logging.getLogger('Mobis.services')

# Outgoing
# RouteConfirmedIntegrationEvent(int orderId, int routeId)
# RouteRejectedIntegrationEvent(int orderId)
# RouteChangedIntegrationEvent(int orderId, int oldRouteId, int newRouteId)

# Incoming
# OrderCancelledIntegrationEvent(int id)
# OrderStartedIntegrationEvent(int id, double startLatitude, double startLongitude, double endLatitude, double endLongitude, DateTimeOffset time, bool isDeparture, int seats)

class RabbitMqSender():
    """
    Responsible for sending messages to RabbitMQ to indicate events related to the route.
    It defines different message types, which correspond to changes in the route: `RouteConfirmedIntegrationEvent`, 
    `RouteStartedIntegrationEvent`, etc., which handle formatting and sending the respective messages with appropriate routing keys. 
    Each method takes in the necessary parameters for that event and sends a message with the appropriate routing key.

    Attributes:
        exchange (str): Currently unused as the default exchange is defined in the EventBus.py file
        threaded (bool): Determines whether to use a threaded `AsyncPublisher` or an `UnthreadedPublisher`. Defaults to `True`.
    """
    def __init__(self, exchange=None, threaded=True):
        if threaded:
            self._event_bus = AsyncPublisher()
            self._event_bus.start()
        else:
            self._event_bus = UnthreadedPublisher()
    def _send(self, message, routing_key):
        self._event_bus.publish(message=json.dumps(message), routing_key=routing_key)
    

    # ------------------ Outgoing integration events ------------------
    def RouteConfirmedIntegrationEvent(self,
            orderId:int, routeId:int,
            startTimeMinimum:datetime, startTimeMaximum:datetime,
            destinationTimeMinimum:datetime, destinationTimeMaximum:datetime, busId:int):
        message = {
            'orderId': orderId,
            'routeId': routeId,
            'busId': busId,
            'startTimeMinimum': startTimeMinimum.isoformat(),
            'startTimeMaximum': startTimeMaximum.isoformat(),
            'destinationTimeMinimum': destinationTimeMinimum.isoformat(),
            'destinationTimeMaximum': destinationTimeMaximum.isoformat()
        }
        self._send(message=message, routing_key='RouteConfirmedIntegrationEvent')
    def RouteStartedIntegrationEvent(self, routeId:int):
        message = {'routeId': routeId}
        self._send(message=message, routing_key='RouteStartedIntegrationEvent')
    def RouteFinishedIntegrationEvent(self, routeId:int):
        message = {'routeId': routeId}
        self._send(message=message, routing_key='RouteFinishedIntegrationEvent')
    def RouteFrozenIntegrationEvent(self, routeId:int, startTimeMinimum:datetime):
        message = {'routeId': routeId, 'startTimeMinimum': startTimeMinimum.isoformat()}
        self._send(message=message, routing_key='RouteFrozenIntegrationEvent')
    def CurrentRouteChangedDriverWarningIntegrationEvent(self, route_id : int, bus_id : int):
        message = {'routeId': route_id, 'busId': bus_id}
        self._send(message=message, routing_key='CurrentRouteChangedDriverWarningIntegrationEvent')
    def RouteChangedIntegrationEvent(self, orderId:int, oldRouteId:int, newRouteId:int,
            startTimeMinimum:datetime, startTimeMaximum:datetime,
            destinationTimeMinimum:datetime, destinationTimeMaximum:datetime, busId : int):
        message = {
            'orderId': orderId,
            'oldRouteId': oldRouteId,
            'newRouteId': newRouteId,
            'busId': busId,
            'startTimeMinimum': startTimeMinimum.isoformat(),
            'startTimeMaximum': startTimeMaximum.isoformat(),
            'destinationTimeMinimum': destinationTimeMinimum.isoformat(),
            'destinationTimeMaximum': destinationTimeMaximum.isoformat()
        }
        self._send(message=message, routing_key='RouteChangedIntegrationEvent')
    def RouteRejectedIntegrationEvent(self, orderId:int=0, reason:str = "No reason provided", start:str = "", destination:str= "", bookingTime:str= "", seats:int = 0, seats_wheelchair:int=0):
        LOGGER.info("RouteRejectedIntegrationEvent")
        message = {'orderId': orderId, 'reason': reason, 'start': start, 'destination': destination, 'bookingTime': bookingTime, 'seats': seats, 'seats_wheelchair': seats_wheelchair}
        self._send(message=message, routing_key='RouteRejectedIntegrationEvent')
        LOGGER.info("RouteRejectedIntegrationEvent sent")

class RabbitMqListener:
    """
    A RabbitMQ `Consumer`, which serves as an interface for receiving and processing messages from RabbitMQ queues.
    Registers a callback function to a given routing key. The callback function is invoked automatically, 
    when a message with this routing key arrives.
    """
    def __init__(self):
        self._consumer = Consumer()
    def register(self, key, callback):
        self._consumer.register(routing_key=key, callback=callback)
    def listen(self):
        self._consumer.run()