import logging
from datetime import datetime, timedelta

#from Routing_Api.celery import app
from celery import shared_task
from dateutil.relativedelta import relativedelta
from dateutil.tz import tzutc
from django.db.models import Q
from django.db import transaction

from routing.routingClasses import MobyLoad

from .models import Node, Route, Order, Station
from .signals import RabbitMqSender as Publisher
from .serializers import RouteSerializer
import json

LOGGER = logging.getLogger('Mobis.tasks')
UTC = tzutc()
sender = Publisher(threaded=False)

@shared_task
def split_routes(delta_time_min_for_split=30):
    '''Split booked routes where the bus could be exchanged.'''
    LOGGER.info(f'split_routes...')

    # todo splitten von Routen muss man weiter denken:
    # gibt es ueberhaupt mehr als einen Bus?
    # gibt es mehr als einen Bus verfuegbar im Zeitraum?
    # ist es ueberhaupt sinnvoll zu splitten oder kann der Bus viel effizienter alles auf einer Route abfahren?
    
    numRoutes = 0

    try:
        numRoutes = Route.objects.count()        
    except Exception as e:
        LOGGER.error(f'split_routes: database model not existing')    
        LOGGER.error(e)

    if numRoutes > 0:
        with transaction.atomic():
            routes = Route.objects.prefetch_related('nodes').filter(status=Route.BOOKED)
            for route in routes:  
                # splitting should not be done if time is too close
                time_min_node_old = None

                loads: List[MobyLoad] = route.loads
                # find node where the bus is empty
                # this should happen whenever the number of hopOffs equals the previous load
                current_route = route
                route_id = route.pk  # use the primary key, because the object reference itself changes further down
                first = True  # it's possible to detect a valid change for the very first node - this isn't wanted, so set a flag
                previous_load = MobyLoad(0,0)  # assume the bus is empty before arriving at the first stop
                for load, node in zip(loads, route.nodes.all()):
                    if first == True:
                        time_min_node_old = node.tMin + timedelta(minutes=100000)

                    if route_id != current_route.pk:  # update orders only if the route has changed
                        for order in node.hopOffs.all():
                            # we iterate over hopOffs only, because the route for hopOns might still change
                            hopOnNode = order.hopOnNode
                            try:
                                sender.RouteChangedIntegrationEvent(
                                    orderId=order.uid, oldRouteId=route_id, newRouteId=node.route.pk,
                                    startTimeMinimum=hopOnNode.tMin, startTimeMaximum=hopOnNode.tMax,
                                    destinationTimeMinimum=node.tMin, destinationTimeMaximum=node.tMax, busId=route.busId)
                            except Exception as err:
                                LOGGER.error('split_routes: failed to send RouteChangedEvent for oldRouteId {route_id} with: %s', err, exc_info=True)
                                raise err
                        node.route = current_route
                        node.save()

                    # splitting if hop_offs are equivalent to previous load, i.e. bus is empty after hop_off
                    hopOffsTmp = node.loadAll_hopOffs
                    if previous_load.equals(hopOffsTmp) and not first:
                        time_min_for_splitting = time_min_node_old + timedelta(minutes=delta_time_min_for_split)
                        # splitting is allowed if any moby enters the empty bus and the time step is large enough
                        #print(f'split_routes: splitting candidate, time is {node.tMin}, time min for split is {time_min_for_splitting}')
                        if not node.loadAll_hopOns.isEmpty() and node.tMin >= time_min_for_splitting:
                            # it's empty at this stop, we could exchange the bus now
                            # create a new route
                            current_route.pk = None  # yes, this is how django objects are duplicated with new id
                            current_route.save()
                            
                            # if there are any hopOns, we need to copy the current node as well
                            hopOns = node.hopOns.all()
                            if hopOns:
                                if hopOffsTmp.isEmpty():
                                    # do not copy node
                                    node.route = current_route
                                    node.save()
                                else:
                                    node.pk = None
                                    node.route = current_route
                                    node.save()
                                    hopOns.update(hopOnNode=node)

                            LOGGER.info(f'split_routes: new route created {current_route} with id {current_route.pk}')
                    
                    previous_load = load
                    first = False
                    time_min_node_old = node.tMin

    LOGGER.info(f'split_routes finished')

@shared_task
def freeze_routes(social_time_min=15):

    if social_time_min < 0:
        social_time_min = 0

    LOGGER.info(f'freeze_routes with time delta {social_time_min}...')
    numRoutes = 0    

    try:
        numRoutes = Route.objects.count()       
    except Exception as e:
        LOGGER.error(f'freeze_routes: database model not existing')

    if numRoutes > 0:
        now = datetime.now(UTC)
        routes = Route.objects.prefetch_related('nodes').filter(status=Route.BOOKED).distinct()
        for route in routes:
            if route.nodes.count() == 0:
                continue

            time_start = route.nodes.first().tMin
            if time_start <= now + relativedelta(minutes=social_time_min):
                # remove nodes without hopOn or hopOff
                for node in route.nodes.all():
                    if not node.has_order:
                        node.delete()
                # freeze routes with nodes containing orders only
                route.status = Route.FROZEN
                route.save()
                LOGGER.info(f'froze {route}')   

                # publish event
                try:
                    sender.RouteFrozenIntegrationEvent(routeId=route.id, startTimeMinimum=time_start)
                except Exception as err:
                    LOGGER.error('freeze_routes: failed to send RouteFrozenIntegrationEvent for route_id {route.id} with: %s', err, exc_info=True)
                    raise err 

    LOGGER.info(f'freeze_routes finished')

@shared_task
def delete_empty_routes():
    # this could be used if we didn't intermediate nodes - tbd
    # empty_routes = Route.objects.empty()
    # LOGGER.info(f'delete empty routes: {empty_routes}')
    # empty_routes.delete()    
    
    numRoutes = 0

    try:
        numRoutes = Route.objects.count()       
    except Exception:
        LOGGER.error(f'delete_empty_routes: database model not existing')

    if numRoutes > 0:
        routes = Route.objects.prefetch_related('nodes','nodes__hopOns', 'nodes__hopOffs').all()
        for route in routes:
            if len(route.clients()) == 0:
                LOGGER.info(f'delete empty route: {route}')
                route.delete()    

@shared_task
def delete_unused_nodes():
    """ check for empty nodes that aren't stations and delete them """
    LOGGER.info(f'delete_unused_nodes...')
    
    numNodes = 0

    try:
        numNodes = Node.objects.count()       
    except Exception:
        LOGGER.error(f'delete_unused_nodes: database model not existing')

    if numNodes > 0:
        station_mapIds = set(s['mapId'] for s in Station.objects.values('mapId'))
        is_station = Q(mapId__in=station_mapIds)
        is_empty = Q(hopOns__isnull=True, hopOffs__isnull=True)
        empty_non_stations = is_empty & ~is_station
        Node.objects.filter(empty_non_stations).delete()
    

    LOGGER.info(f'delete_unused_nodes finished')

@shared_task
def delete_routes():
    LOGGER.info(f'delete_routes...')

    numRoutes = 0
    numRoutesRemaining = 100 # do not remove all routes immediately
    numRoutesDeleted = 0

    try:
        numRoutes = Route.objects.count()       
    except Exception:
        LOGGER.error(f'delete_routes: database model not existing')

    if numRoutes > numRoutesRemaining:
        delete_candidates = Route.objects.to_be_deleted_oldest(numRoutesRemaining)   
              
        for id in delete_candidates:
            route = delete_candidates[id]
            print(f'delete_routes: route {route.id} deleted')
            LOGGER.info(f'delete_routes: route {route.id} deleted')
            try:
                dump(route)
            except:
                LOGGER.error(f'delete_routes: dump route failed')

            route.delete() 
            numRoutesDeleted += 1                      

    LOGGER.info(f'delete_routes finished, {numRoutesDeleted} routes deleted')

def dump(route):
    rs = RouteSerializer()

    # todo location to be dumped must be created
    # todo maybe dumping to archive database?
    jsontxt = json.dumps(rs.to_representation(route))
    outpath = f'/log/deleted_routes/route_{route.id:010}'

    print(jsontxt)

    with open(outpath, 'w') as logfile:
        logfile.write(jsontxt)
        logfile.write("\n")

@shared_task
def check_routing_data() -> bool:
    LOGGER.info(f'check_routing_data...')

    result: bool = True    

    numOrders = 0

    try:
        numOrders = Order.objects.count()       
    except Exception:
        LOGGER.error(f'check_routing_data: database model not existing')

    if numOrders > 0:
        for order in Order.objects.all():
            node_id_hop_on = order.hopOnNode_id
            node_id_hop_off = order.hopOffNode_id

            if node_id_hop_on is not None and node_id_hop_off is not None:
                node_hop_on = Node.objects.get(id=node_id_hop_on)
                node_hop_off = Node.objects.get(id=node_id_hop_off)

                if node_hop_on.route_id != node_hop_off.route_id:
                    LOGGER.error(f'check_routing_data: problem in order {order.id}: hop on/off nodes have different routes')
                    result = False
            elif node_id_hop_on is not None or node_id_hop_off is not None:   
                # this is never allowed: one is null, the other is not null         
                LOGGER.error(f'check_routing_data: problem in order {order.id}: only one of the hop on/off nodes is null')
                result = False    

    LOGGER.info(f'check_routing_data finished')
    return result
