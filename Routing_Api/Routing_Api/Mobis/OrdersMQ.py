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
    def route_rejected(self, order_id, reason):
        LOGGER.info(f'route_rejected {order_id}, reason: {reason}')
        self._messageBus.RouteRejectedIntegrationEvent(orderId=order_id, cancellationReason=reason)
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
