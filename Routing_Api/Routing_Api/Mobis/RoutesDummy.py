from typing import List
from dateutil.relativedelta import relativedelta
from routing.routingClasses import MobyLoad
import logging

LOGGER = logging.getLogger('Mobis.services')

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
                        start_time_min=hopOn.tMin, start_time_max=hopOn.tMax, stop_time_min=hopOff.tMin, stop_time_max=hopOff.tMax, bus_id = route.bus_id)

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
                                   stop_time_max=stop_node.tMax,
                                   bus_id = route.busId)

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
