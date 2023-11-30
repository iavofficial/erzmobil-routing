from functools import partial

# do not change order of ortools imports - may lead to segfaults in docker images (issue #246)
from ortools.constraint_solver import routing_enums_pb2
from ortools.constraint_solver import pywrapcp

import pickle
from pprint import pprint
from collections import defaultdict, namedtuple
import networkx as nx
from uuid import uuid4
from copy import deepcopy
from .routingClasses import Group, Station, Moby, MobyLoad, Vehicle, VehicleCapacity, Node, MapNode, TimeWindow, LocationIndex, BusIndex, Passenger, StationConstraint

from typing import List, Tuple, Dict, Callable, Optional, Union, Any

# debug stuff ####################
import logging
logger = logging.getLogger('routing.routing')
# end debug stuff ################

from .rutils import Path, durations_matrix_OSRM, durations_matrix_graph, shortest_path_OSRM, shortest_path_OSRM_multi, shortest_path_graph, shortest_path_graph_gps, ConsolePrinter, travel_time, multi2single, STNIMMERLEIN
from .errors import NoRouteException, NoRouteExceptionInternalError

###########################
# Problem Data Definition #
###########################


class DataProblem():
    """Stores the data for the problem"""

    def __init__(self,
                 locations: List[MapNode],
                 locations_arrival_fixed: List[bool],
                 time_windows: List[TimeWindow],
                 capacities: List[Vehicle],
                 depot: int=0,
                 demands: List[MobyLoad]=[MobyLoad(1,0)]):
        """Initializes the data for the problem"""
        self._vehicles: List[Vehicle] = []
        for vehicle in capacities:
            if isinstance(vehicle, Vehicle):
                self._vehicles.append(deepcopy(vehicle))
            else:
                raise TypeError('given capacity arguments contains no Vehicle object, but {}', vehicle)

        self._num_vehicles = len(self._vehicles)

        # Locations in meters?
        self._locations = locations
        self._locations_arrival_fixed = locations_arrival_fixed

        self._depot = depot

        # Time per stop in [-]
        self._demands = demands

        # [touple of earliest, latest arrival per stop]
        self._time_windows = time_windows

    @property
    def vehicles(self) -> List[Vehicle]:
        """Gets vehicles"""
        return self._vehicles

    @property
    def num_vehicles(self) -> int:
        """Gets number of vehicles"""
        return self._num_vehicles

    @property
    def locations(self) -> List[MapNode]:
        """Gets locations"""
        return self._locations

    @property
    def num_locations(self) -> int:
        """Gets number of locations"""
        return len(self.locations)

    @property
    def depot(self)->int:
        """Gets depot location index"""
        return self._depot

    @property
    def demands(self)->List[MobyLoad]:
        """Gets demands at each location"""
        return self._demands    

    @property
    def time_windows(self)->List[TimeWindow]:
        """Gets (start time, end time) for each locations"""
        return self._time_windows

#######################
# Problem Constraints #
#######################

# todo nach dem Umbau wg OSRM muss man das hier ueberdenken oder ganz entfernen
class CreateDistanceEvaluator(object):
    """Creates callback to return distance between points."""

    def __init__(self, data:DataProblem,
                 paths: Callable[[LocationIndex, LocationIndex], Path]):
        """Initializes the distance matrix."""
        self._distances: Dict[LocationIndex, Dict[LocationIndex, float]] = {}
        # precompute distance between location to have distance callback in O(1)
        for i_from, from_node in enumerate(data.locations):
            self._distances[i_from] = {}
            for i_to, to_node in enumerate(data.locations):
                if i_to == data.depot or i_from == data.depot:
                    self._distances[i_from][i_to] = 0
                else:
                    self._distances[i_from][i_to] = paths(
                        i_from, i_to).distance

    def distance_evaluator(self, from_node: LocationIndex, to_node: LocationIndex)->float:
        """Returns the time distance between the two nodes"""
        return self._distances[from_node][to_node]


class CreateDemandEvaluator(object):
    """Creates callback to get demands at each location."""

    def __init__(self, data:DataProblem):
        """Initializes the demand array."""
        self._demands = data.demands
        self._wheelchair_weight = 0

        for v in data.vehicles:
            self._wheelchair_weight = max(v.capacity.seatsBlockedPerWheelchair, self._wheelchair_weight)

    def demand_evaluator_seats(self, from_node: LocationIndex)->int:
        """Returns the demand of the current node""" 

        if from_node < len(self._demands):
            retTmp = self._demands[from_node].standardSeats
            #print(f'demand_evaluator_seats {retTmp}')
            return retTmp            
        return 0

    def demand_evaluator_wheelchairs(self, from_node: LocationIndex)->int:
        """Returns the demand of the current node""" 

        if from_node < len(self._demands):
            retTmp = self._demands[from_node].wheelchairs
            #print(f'demand_evaluator_wheelchairs {retTmp}')
            return retTmp
        return 0

    def demand_evaluator_weighted_sum(self, from_node: LocationIndex)->int:
        """Returns the demand of the current node""" 

        wheelchair_weight = 2

        if self._wheelchair_weight > wheelchair_weight:
            raise ValueError('Wheelchair weight can be max 2!') # otherwise our weighted sum constraint will not work

        # calc a weighted sum for seats and wheelchairs that allows us to limit demands such that wheelchairs can reduce standard seats
        if from_node < len(self._demands):
            retTmp = self._demands[from_node].standardSeats + wheelchair_weight*(self._demands[from_node].wheelchairs)
            #print(f'demand_evaluator_weighted_sum {retTmp}')
            return retTmp
        return 0


def add_capacity_constraints(routing:pywrapcp.RoutingModel,
                             data:DataProblem,
                             demand_evaluator_seats: Callable[[LocationIndex],int], demand_evaluator_wheelchairs: Callable[[LocationIndex],int], demand_evaluator_weighted_sum: Callable[[LocationIndex],int])->None:

    """Adds capacity constraint"""
    capacity = "Capacity"   
    
     # standard seats
    capacity = 'Capacity'     
    demand_callback_index_seats = routing.RegisterUnaryTransitCallback(demand_evaluator_seats)

    vCapaStandardTmp = [v.capacity.maxNumStandardSeats for v in data.vehicles]
    #print(f'capa standard {vCapaStandardTmp}')

    routing.AddDimensionWithVehicleCapacity(
        demand_callback_index_seats,
        0,  # null capacity slack
        vCapaStandardTmp,  # vehicle maximum capacity
        True,  # start cumul to zero
        capacity)

    # wheelchairs
    capacityWheelchair = 'CapacityWheelchair'       
    demand_callback_index_wheelchair = routing.RegisterUnaryTransitCallback(demand_evaluator_wheelchairs)

    vCapaWheelchairTmp = [v.capacity.maxNumWheelchairs for v in data.vehicles]
    #print(f'capa wheelchair {vCapaWheelchairTmp}')

    routing.AddDimensionWithVehicleCapacity(
        demand_callback_index_wheelchair,
        0,  # null capacity slack
        vCapaWheelchairTmp,  # vehicle maximum capacity 
        True,  # start cumul to zero
        capacityWheelchair)

    # wheelchairs can reduce number of seats, we add a constraint with general wheelchair weight of 2
    # works only if a wheelchair reduces the seats max by 2

    capacityWeightedSum = 'CapacityWeightedSum'       
    demand_callback_index_weighted_sum = routing.RegisterUnaryTransitCallback(demand_evaluator_weighted_sum)

    vCapaWeightedTmp = [((2-v.capacity.seatsBlockedPerWheelchair)*v.capacity.maxNumWheelchairs+v.capacity.maxNumStandardSeats) for v in data.vehicles]
    #print(f'capa weighted {vCapaWeightedTmp}')

    routing.AddDimensionWithVehicleCapacity(
        demand_callback_index_weighted_sum,
        0,  # null capacity slack
        vCapaWeightedTmp,  # vehicle maximum capacity 
        True,  # start cumul to zero
        capacityWeightedSum)

class CreateTimeEvaluator(object):
    """Creates callback to get total times between locations."""
    @staticmethod
    def service_time_per_stop(data:DataProblem, from_node, to_node)->float:
        """Gets the service time for the specified location.
        from_node, to_node can be Stations, or str 'Depot'."""

        if from_node == 'Depot' or to_node == 'Depot' or from_node == to_node:
            return 0
        else:
            return 1

    def __init__(self, data:DataProblem, durations_dict, service_time_load_seat:int, service_time_load_wheelchair: int):
        """Initializes the total time matrix."""        
        self._total_time = {}
        self._total_time_weighted = {}

        for from_index, from_node in enumerate(data.locations):
            self._total_time[from_index] = {}
            self._total_time_weighted[from_index] = {}

            # take into account service times for passengers hop on
            service_time_per_hop_on_passenger = service_time_load_seat 
            number_passengers_hop_on = max(data.demands[from_index].standardSeats,0) # hop off is < 0
            service_time_per_hop_on_wheelchair = service_time_load_wheelchair
            number_wheelchairs_hop_on_off = abs(data.demands[from_index].wheelchairs) # hop off is < 0, wheelchair hop off takes lot of time, too

            # TODO sehr pauschal: Rollstuhlfahrer, Gruppe mit einem Ticket... waere anders zu modellieren, Aussteigen noch gar nicht modelliert Aussteigen mit weniger Zeitoffset...
            # Rollstuhlfahrer werden vom Optimierer durch die laengeren Service-Zeiten stark benachteiligt, die will man ja eigentlich bevorzugen -> kann man anderswo normale Seats mit penalties versehen, wenn Rollstuhl gebucht wird?
            
            for to_index, to_node in enumerate(data.locations):
                # durations should not be rounded to zero when casted to integer (which is done always)!
                duration_tmp = durations_dict[from_node][to_node]

                if duration_tmp > 0:
                    duration_tmp = max(1.0, duration_tmp)
                    service_time_total = self.service_time_per_stop(data, from_node, to_node) + service_time_per_hop_on_passenger*number_passengers_hop_on + service_time_per_hop_on_wheelchair*number_wheelchairs_hop_on_off
                elif duration_tmp == 0:
                    # no service_time, if from and to is the same station, i.e. multiple mobies at same station
                    service_time_total = 0

                # add service time for hop on/off
                self._total_time[from_index][to_index] = duration_tmp + service_time_total

                # calc a weighted distance: segments with passengers should have short routing times - increase costs
                # reason: optimizer should not minimize distances without load, mobis shoul have shortest times
                # however: note that this is not a general solution, since the load at nodes is NEVER KNOWN, the hop_ons is only a small part of reality
                # as second rule we implement additional constraint
                self._total_time_weighted[from_index][to_index] = self._total_time[from_index][to_index]*(1+2*number_passengers_hop_on+3*number_wheelchairs_hop_on_off)                

                #print(f'service time {from_index} {to_index} {self._total_time[from_index][to_index]}')

    def time_evaluator(self, from_index:LocationIndex, to_index:LocationIndex)->int:
        """Returns the total time between the two nodes"""

        # take care: the ortools solver solves INTEGER problems only - https://developers.google.com/optimization/cp/cp_solver
        if from_index < len(self._total_time) and to_index < len(self._total_time):            
            return int(self._total_time[from_index][to_index])
        else:
            return 0

    def time_evaluator_weighted_demands(self, from_index:LocationIndex, to_index:LocationIndex)->int:
        """Returns the total time between the two nodes"""

        # take care: the ortools solver solves INTEGER problems only - https://developers.google.com/optimization/cp/cp_solver
        if from_index < len(self._total_time_weighted) and to_index < len(self._total_time_weighted):   
            return int(self._total_time_weighted[from_index][to_index])
        else:
            return 0


def add_time_window_constraints(routing:pywrapcp.RoutingModel, 
                                routingIndexManager:pywrapcp.RoutingIndexManager,
                                data:DataProblem,
                                time_evaluator:Callable[[LocationIndex,LocationIndex], int])->None:
    """Add Global Span constraint"""
    time = "Time"
    horizon = STNIMMERLEIN

    time_callback_index = routing.RegisterTransitCallback(time_evaluator)

    routing.AddDimension(
        time_callback_index,
        horizon,  # allow waiting time
        horizon,  # maximum time per vehicle
        False,  # don't force start cumul to zero since we are giving TW to start nodes
        time)
    time_dimension = routing.GetDimensionOrDie(time)
    for location_idx, time_window in enumerate(data.time_windows):
        if location_idx == 0:
            continue
        logger.debug('time window constraint location: {}, window: {}'.format(
            location_idx, time_window))
        #print('time window constraint location: {}, window: {}'.format(location_idx, time_window))
        index: int = routingIndexManager.NodeToIndex(location_idx)
        time_dimension.CumulVar(index).SetRange(time_window[0], time_window[1])
        routing.AddToAssignment(time_dimension.SlackVar(index))

        # try to minimize waiting times for fixed arrivals
        if data._locations_arrival_fixed[location_idx] == True:
            routing.AddVariableMinimizedByFinalizer(time_dimension.SlackVar(index)); 
        
    for vehicle_id in range(data.num_vehicles):
        # TODO: individual start windows & depots
        # break
        index = routing.Start(vehicle_id)
        #time_dimension.CumulVar(index).SetRange(data.time_windows[0][0], data.time_windows[0][1])
        routing.AddToAssignment(time_dimension.SlackVar(index))

def add_pickup_delivery_constraints(routing:pywrapcp.RoutingModel,
                                    routingIndexManager:pywrapcp.RoutingIndexManager,
                                    time_evaluator,
                                    durations_dict,
                                    data:DataProblem,
                                    hop_ons:Dict[LocationIndex, Optional[Passenger]],
                                    hop_offs:Dict[LocationIndex, Optional[Passenger]])->None:
    """Add Correct Order and Vehicle per Moby constraint"""
    time = "Time"
    for pickup, moby in hop_ons.items():
        if moby is None:
            continue
        deliveries = [hofs for hofs in hop_offs if hop_offs[hofs] == moby]

        if len(deliveries) != 1:
            raise NoRouteExceptionInternalError('No routing can be found due to improper deliveries')
        if pickup == 0:
            continue

        delivery = deliveries[0]

        logger.debug(
            'pickup constraint pickup_id: {}, delivery_id: {}'.format(pickup, delivery))
        index_pickup = routingIndexManager.NodeToIndex(pickup)
        index_delivery = routingIndexManager.NodeToIndex(delivery)

        if index_pickup != index_delivery:
            routing.AddPickupAndDelivery(index_pickup, index_delivery)

            time_dimension = routing.GetDimensionOrDie(time)

            routing.solver().Add(
                time_dimension.CumulVar(index_pickup) <= time_dimension.CumulVar(index_delivery))
            routing.solver().Add(
                routing.VehicleVar(index_pickup) == routing.VehicleVar(index_delivery))

            #######################################################################################################################
            # add constraint for maximum allowed travel times, see https://github.com/google/or-tools/issues/1388
            # we define: allowed is an overhead of 15min to shortest time or twice the min time
            # additionally the allowed overhead is defined from pure travel time, but finally the overhead is added to travel time with service

            station_pickup = data.locations[pickup]
            station_delivery = data.locations[delivery]
            time_travel_min = int(durations_dict[station_pickup][station_delivery]+0.5)
            time_travel_min_with_service = int(time_evaluator(pickup, delivery)+0.5)
            delta_allowed = 15

            if time_travel_min > 15:
                delta_allowed = time_travel_min

            # print('time_travel_min')
            # print(time_travel_min)

            routing.solver().Add(
                time_dimension.CumulVar(index_delivery) <= time_dimension.CumulVar(index_pickup) + time_travel_min_with_service + delta_allowed)
        else:
            logger.warning('Tried to add pickup and delivery at same node! Was ignored.')


def add_vehicle_work_time_constraints(routing:pywrapcp.RoutingModel,
                                      data:DataProblem)->None:
    """Add limited working hours for each vehicle"""
    time = "Time"
    time_dimension = routing.GetDimensionOrDie(time)
    for vehicle_idx, vehicle in enumerate(data.vehicles):
        logger.debug(
            'work time constraint vehicle_index: {}, time: {}'.format(vehicle_idx, vehicle.work_time))

        #print('work time constraint vehicle_index: {}, time: {}'.format(vehicle_idx, vehicle.work_time))

        # remove time interval before the vehicle is ready
        index = routing.Start(vehicle_idx)
        time_dimension.CumulVar(index).RemoveInterval(-STNIMMERLEIN, vehicle.work_time[0])
        # remove time interval after the vehicle is finished
        index = routing.End(vehicle_idx)
        time_dimension.CumulVar(index).RemoveInterval(vehicle.work_time[1], STNIMMERLEIN)


def add_mandatory_station_constraints(routing:pywrapcp.RoutingModel,
                                      routingIndexManager:pywrapcp.RoutingIndexManager,
                                      data:DataProblem,
                                      stations:List[Dict[str, List[int]]])->None:
    """Add mandatory station visits for each bus."""
    for station in stations:
        bus_ids = station['bus_ids']
        location_ids = station['location_ids']
        logger.debug('station constraint bus_ids: {}, location_ids: {}'.format(
            bus_ids, location_ids))
        for bus_id, location_id in zip(bus_ids, location_ids):
            index_location = routingIndexManager.NodeToIndex(location_id)
            routing.solver().Add(routing.VehicleVar(index_location) == bus_id)


def add_station_closing_time_constraints(routing:pywrapcp.RoutingModel,
                                         routingIndexManager:pywrapcp.RoutingIndexManager,
                                         data:DataProblem,
                                         station_closing_times:Dict[MapNode,List[TimeWindow]],
                                         buffer_time:int=1)->None:
    """Add forbidden time windows for some stations """
    # time to keep away from closing_window
    # check for overlap in time windows with forbidden time windows.

    time = "Time"
    time_dimension = routing.GetDimensionOrDie(time)
    for location_idx, time_window in enumerate(data.time_windows):
        if location_idx == 0:
            continue

        index = routingIndexManager.NodeToIndex(location_idx)            

        if data.locations[location_idx] != 'Depot' and (data.locations[location_idx].node_id in station_closing_times):            
            for closing_window in station_closing_times[data.locations[location_idx].node_id]:
                # simple adapting time windows is not a proper solution since the resulting time window may be cut into several time windows
                # thus we use the built in RemoveInterval method and do not adapt the time window in the data
                time_dimension.CumulVar(index).RemoveInterval(closing_window[0]-buffer_time, closing_window[1]+buffer_time)                

def add_group_constraints(routing:pywrapcp.RoutingModel,
                          routingIndexManager:pywrapcp.RoutingIndexManager,
                          data:DataProblem,
                          groups: Dict[str, Group])->None:
    """Add soft penalty if groups are broken."""
    for group_id, group in groups.items():
        if len(group.location_ids) < 2:
            continue
        logger.debug(
            f'group constraint group_id: {group_id}, location_ids: {group.location_ids}')
        indices_location: List[int] = [routingIndexManager.NodeToIndex(location_id)
            for location_id in group.location_ids]
        routing.AddSoftSameVehicleConstraint(indices_location, group.penalty)

# todo pruefen, ob man das nach dem Umbau auf OSRM ueberhaupt noch braucht
class CreateShortestPaths(object):
    """Creates callback to return distance between points."""

    def __init__(self, G:nx.DiGraph, data:DataProblem)->None:
        """Initializes the distance matrix."""
        self._paths: Dict[LocationIndex, Dict[LocationIndex, Path]] = {}
        # precompute distance between location to have distance callback in O(1)
        logger.debug(f'shortests paths for: {data.locations}')
        for i_from, from_node in enumerate(data.locations):
            self._paths[i_from] = {}
            for i_to, to_node in enumerate(data.locations):
                if i_to == data.depot or i_from == data.depot:
                    self._paths[i_from][i_to] = Path(G, [])
                else:
                    self._paths[i_from][i_to] = shortest_path_graph(
                        G, from_node, to_node)

    def shortest_path(self, from_node:LocationIndex, to_node:LocationIndex)->Path:
        """Returns path object for the shortest time distance between two nodes"""
        return self._paths[from_node][to_node]


class BusTour:
    """Routing class for one complete tour."""

    def __init__(self, G:nx.DiGraph, OSRM_url:str, capacities: List[Vehicle], time_offset_factor: float, time_per_demand_unit_wheelchair:int, slack:int=30):
        if G != None:
            logger.debug(            
                f'new BusTour G: {G.number_of_nodes} nodes, slack: {slack}, capacities: {capacities}') # do NOT!!! write the graph, this destroys performance!        
            self.G:nx.DiGraph = G
        else:
            logger.debug(            
                f'new BusTour OSRM-url: {OSRM_url}, slack: {slack}, capacities: {capacities}')       
            self.G = None

        self.OSRM_url = OSRM_url
        self.locations:List[MapNode] = ['Depot']
        self.locations_connection: List[str] = ['']
        self.locations_arrival_fixed: List[bool] = [False]
        self.loads:List[MobyLoad] = [MobyLoad(0,0)]
        self.capacities: List[Vehicle] = []
        for vehicle in capacities:
            if isinstance(vehicle, Vehicle):
                self.capacities.append(deepcopy(vehicle))
            else:
                raise TypeError('BusTour needs a list of vehicle objects as input')
        self.hop_ons: Dict[LocationIndex, Optional[Passenger]] = defaultdict(lambda: None)
        self.hop_offs: Dict[LocationIndex, Optional[Passenger]] = defaultdict(lambda: None)
        self._time_windows: List[TimeWindow] = [(0, 0)]
        self.time_windows: List[TimeWindow] = {}
        self._slack: int = slack
        self._time_offset_factor = time_offset_factor
        self._time_per_demand_unit_wheelchair = time_per_demand_unit_wheelchair
        self._final_paths: Dict[BusIndex, List[Node]] = {}
        self.stations: List[Dict[str, List[BusIndex]]] = []
        self.groups: Dict[str, Group] = dict()
        self.station_closing_times:Dict[MapNode,List[TimeWindow]] = dict()
        self.time_matrix: Dict[Dict[int]] = {}  
        self.time_matrix_save: dict[dict[int]] = {}

    @property
    def time_per_demand_unit_seat(self)->int:
        """Gets the time (in min) to load a demand"""
        return 1  # 1min/unit   

    @property
    def time_per_demand_unit_wheelchair(self)->int:
        """Gets the time (in min) to load a demand"""
        return self._time_per_demand_unit_wheelchair  # min/unit

    def set_slack(self, val:int):
        if val>0:
            self._slack = val   

    def get_routes(self)->Dict[BusIndex, List[Node]]:
        return self._final_paths

    def calc_time_matrix(self, station_list)->dict:
        if self.G != None:
            return durations_matrix_graph(tuple(station_list), self.G, self._time_offset_factor, self.time_matrix_save)
        else:
            return durations_matrix_OSRM(tuple(station_list), self.OSRM_url, self._time_offset_factor)

    def calc_shortest_path(self, start: Station, stop: Station)->Path:
        if self.G != None:
            Path = shortest_path_graph(self.G, start, stop)

            # add distances of nodes
            if len(Path.nodes) > 1:
                trip_time = 0.0
                lastNode = Path.nodes[0]
                Path.nodes[0] = {lastNode, trip_time}

                for i in range(1, len(Path.nodes)-1):
                    trip_time = travel_time(self.G[lastNode][Path.nodes[i]])
                    lastNode = Path.nodes[i]
                    Path.nodes[i] = [lastNode, trip_time]    
            return Path
        else:
            return shortest_path_OSRM(start, stop, self.OSRM_url)

    def calc_shortest_path_multi(self, path_locations: List[Station])->List[List]:
        if self.G == None:
            nodes_of_route_all = shortest_path_OSRM_multi(path_locations, self.OSRM_url, onlyGps=False)
        else:
            nodes_of_route_all = []
            for iLoc in range(0, len(path_locations)-1):
                nodes_of_route_all.append(self.calc_shortest_path(path_locations[iLoc], path_locations[iLoc+1]).nodes)                
        
        return nodes_of_route_all

    def calc_shortest_path_gps(self, path_locations: List[Station])->List:
        result= []        

        if self.G == None:
            result = shortest_path_OSRM_multi(path_locations, self.OSRM_url, onlyGps=True)
        else:
            for iLoc in range(0, len(path_locations)-1):                
                result.append(shortest_path_graph_gps(self.G, path_locations[iLoc], path_locations[iLoc+1]))
        
        return result

    def add_moby(self, moby:Moby, build_paths = True, *args, **kwargs)->Optional[str]:
        logger.debug(f'add_moby args: {args}, kwargs: {kwargs}')
        try:
            # save old data
            locations_old = deepcopy(self.locations)            
            loads_old = deepcopy(self.loads)
            groups_old = deepcopy(self.groups)
            time_windows_old = deepcopy(self.time_windows)
            _time_windows_old = deepcopy(self._time_windows)
            
            group_id = self._add_moby(moby, *args, **kwargs)
            self.update()
            if build_paths:
                self.build_paths()
        except NoRouteException as err:
            logger.debug(err)

            # reset data - if moby cannot be added successfully, all moby-specific data must be removed
            self.locations = locations_old            
            self.loads = loads_old
            self.groups = groups_old   
            self.time_windows = time_windows_old 
            self._time_windows = _time_windows_old 

            # remove moby from hop_on/off 
            # (note: deepcopy of hop_on/off does not work, since internally the moby objects are compared by memory address, i.e. moby1==moby2)   

            for hop in list(self.hop_ons.keys()):
                if self.hop_ons[hop] == moby:  
                       del self.hop_ons[hop]

            for hop in list(self.hop_offs.keys()):
                if self.hop_offs[hop] == moby:  
                       del self.hop_offs[hop]            

            return None
        except Exception as err:
            logger.debug(err)
            raise err

        return group_id
        # return self._final_paths

    def add_mobies(self, mobies:List[Moby])->None:
        logger.debug(f'add_mobies mobies: {mobies}')
        group_ids = []
        try:
            for moby in mobies:
                group_ids.append(self._add_moby(moby))
            self.update()
            self.build_paths()
        except NoRouteException as err:
            logger.debug(err)
        except Exception as err:
            logger.debug(err)
            raise err
        return group_ids
        # return self._final_paths

    def _add_moby(self, moby:Moby, group_id:Optional[str]=None,
                  penalty:int=1000, promised:bool=False)->Optional[str]:        

        logger.debug(f'_add_moby: {moby}')
        if not promised:
            if (moby.stop_window is not None and moby.start_window is not None)\
                    or (moby.stop_window is None and moby.start_window is None):
                raise(ValueError(
                    'Exactly one window expected, the second one must be None'))
        
        duration_of_route = 0

        # moby should only be added to data if all checks are valid - otherwise invalid moby remains in data 
        self.locations.append(moby.start_station)
        self.locations.append(moby.stop_station)

        # Check if route may not be possible
        try:
            self.time_matrix = self.calc_time_matrix(self.locations)
            duration_of_route = self.time_matrix[moby.start_station][moby.stop_station]            
        except nx.NetworkXNoPath as err:
            logger.debug('{}'.format(err))
            raise NoRouteExceptionInternalError(f'No routing possible due to error when calculating path. Internal error data: {err}')
        except ValueError as err:
            logger.debug('{}'.format(err))
            raise NoRouteExceptionInternalError(f'No routing possible due to value error in data. Internal error data: {err}')        

        hop_on_idx, hop_off_idx = len(self.locations)-2, len(self.locations)-1

        self.hop_ons[hop_on_idx] = moby
        self.hop_offs[hop_off_idx] = moby

        self.loads.append(moby.number_passengers) # moby picked up
        self.loads.append(-moby.number_passengers) # moby leaves bus

        if group_id is None:
            group = Group(location_ids=[], penalty=penalty)
            group_id = group.id
            self.groups[group.id] = group
        else:
            assert(group_id in self.groups)
        self.groups[group_id].location_ids.append(hop_on_idx)

        # TODO: traffic        
        t_min = int(duration_of_route+0.5)
        dT = t_min+self._slack  # travel time in min

        # for not promised moby: 
        # 1. add not defined time window 
        # 2. adjust time window to connecting times

        connection_start = False
        connection_stop = False

        if not promised:
            if moby.start_window is not None:
                # departure was ordered
                self.locations_arrival_fixed.append(False)
                self.locations_arrival_fixed.append(False)

                # 1. add not defined arrival window
                moby.stop_window = moby.start_window[0], moby.start_window[1]+dT

                # 2. adjust departure window for connecting                
                moby.start_window, connection_start = self.adjust_time_window_for_connecting_times(moby.start_window, moby.start_station, True)
            else:
                # arrival was ordered
                self.locations_arrival_fixed.append(True)
                self.locations_arrival_fixed.append(True)

                # 1. add not defined start window
                moby.start_window = moby.stop_window[0]-dT, moby.stop_window[1]

                # 2. adjust arrival window for connecting times
                moby.stop_window, connection_stop = self.adjust_time_window_for_connecting_times(moby.stop_window, moby.stop_station, False)  
        else:
            # for promises we always assume that departure is the fixed time
            self.locations_arrival_fixed.append(False)
            self.locations_arrival_fixed.append(False)

        self._time_windows.append(moby.start_window)
        self._time_windows.append(moby.stop_window)

        if connection_start:
            self.locations_connection.append('DepartureFixed')
        else:
            self.locations_connection.append('')

        if connection_stop:
            self.locations_connection.append('ArrivalFixed')
        else:
            self.locations_connection.append('') 

        # print(self.locations_connection)       
        # print(self.locations_arrival_fixed)       
        # print(self._time_windows)       

        return group_id

    def adjust_time_window_for_connecting_times(self, time_window:TimeWindow, station: Station, isDeparture: bool) -> Any:
       
        result = time_window
        connection_active = False

        # TODO hard coded: Zwoenitz Station - in future we have to extraxt this information from database or somewhere
        #print("adjust time window")
        #print(station)

        if station.name != 'Zwoenitz, Bahnhof':
            if not hasattr(station, 'latitude') or not hasattr(station, 'longitude') or station.latitude is None or station.longitude is None or abs(station.latitude-50.632136) > 1e-4 or abs(station.longitude-12.798217) > 1e-4:
                #print("no connection found")
                return (result, connection_active)

        # TODO hard coded time min/max for trains at Zwoenitz station - in future we have to extraxt this information from database or somewhere
        # both trains arrive xx:56 and leave xx:58 every hour and every day
        time_connection_arrives = 56
        time_connection_leaves = 58

        # check current time window and normalize minutes
        minutes_to_substract = 0

        if isDeparture:
            minutes_to_substract = (time_window[0]%60)*60
        else:
            minutes_to_substract = (time_window[1]%60)*60

        minutes_start = time_window[0] - minutes_to_substract
        minutes_stop = time_window[1] - minutes_to_substract

        while minutes_start < 0:
            minutes_start+=60
            minutes_stop+=60

        # check if connection needs to be fixed
        delta_minutes_assuming_connection = 10 # within delta interval around the connection time we assume that connection was intended by the order
        delta_minutes_buffer_time=3 # user needs to walk a little

        # check if time was ordered with connection intended
        if isDeparture:
            # moby will leave the connection and enter the bus
            if  minutes_start >= time_connection_arrives and minutes_start <= time_connection_arrives+delta_minutes_assuming_connection and minutes_stop > time_connection_arrives+delta_minutes_buffer_time:
                connection_active = True                
                minutes_mod = time_connection_arrives + delta_minutes_buffer_time - minutes_start
                if minutes_mod > 0:
                    # current start time is too low for fitting connection
                    result = (result[0] + minutes_mod, result[1])
        else:
            # moby will leave the bus and enter connection
            if  minutes_stop <= time_connection_leaves and minutes_stop >= time_connection_leaves-delta_minutes_assuming_connection and minutes_start < time_connection_leaves-delta_minutes_buffer_time:
                connection_active = True                
                minutes_mod = minutes_stop - time_connection_leaves + delta_minutes_buffer_time
                if minutes_mod > 0:
                    # current stop time is too large for fitting connection
                    result = (result[0], result[1] - minutes_mod)
        
        # if connection_active:
        #     print('connection acitve')
        #     print(time_window)
        #     print(result)

        return (result, connection_active)

    def add_station(self, station:Station, time_window:TimeWindow, bus_ids:List[BusIndex], penalty:int=STNIMMERLEIN)->None:
        logger.debug(
            f'add_station station: {station}, time_window: {time_window}, bus_ids: {bus_ids}')
        try:
            self._add_station(station, time_window, bus_ids, penalty)
            self.update()
            self.build_paths()
        except NoRouteException as err:
            logger.debug(err)
        except Exception as err:
            logger.debug(err)
            raise err
        # return self._final_paths

    def add_stations(self, stations:List[Station], time_windows:List[TimeWindow], bus_ids_list:List[List[BusIndex]], penalties:List[int]=[])->None:
        if not penalties:
            penalties = [STNIMMERLEIN]*len(stations)
        try:
            for station, time_window, bus_ids, penalty in\
                    zip(stations, time_windows, bus_ids_list, penalties):
                self._add_station(station, time_window, bus_ids, penalty)
            self.update()
            self.build_paths()
        except NoRouteException as err:
            logger.debug(err)
        except Exception as err:
            logger.debug(err)
            raise err
        # return self._final_paths

    def _add_station(self, station:Station, time_window:TimeWindow, bus_ids:List[BusIndex], penalty:int=STNIMMERLEIN)->None:
        n_busses = len(bus_ids)
        self.locations.extend([station]*n_busses)
        self.locations_connection.extend(['']*n_busses)
        self.locations_arrival_fixed.extend([False]*n_busses)
        self.loads.extend([MobyLoad(0,0)]*n_busses)
        self._time_windows.extend([time_window]*n_busses)
        locations_ids = sorted(
            [len(self.locations)-i-1 for i in range(n_busses)])
        self.stations.append(
            {'bus_ids': bus_ids, 'location_ids': locations_ids})

    def add_station_closing_time(self, station:Station, time_windows:TimeWindow):
        if hasattr(station, 'node_id'):   
            if station.node_id in self.station_closing_times:
                self.station_closing_times[station.node_id].extend(time_windows)
            else:
                self.station_closing_times[station.node_id] = time_windows
        else:
            raise ValueError(f'Location hat not node_id, location data: {station}')

    def update(self)->None:

        # transform windows into [0 inf] domain, we don't want  negative values
        self.time_windows:List[TimeWindow] = [(0, 0)]+self._time_windows[1:]
        # adjust vehicle hours
        vehicles = deepcopy(self.capacities)

        # Instantiate the data problem.
        self.data = DataProblem(
            self.locations,
            self.locations_arrival_fixed,
            self.time_windows,
            demands=self.loads,
            capacities=vehicles)

        # Create Routing Model
        self.routingIndexManager = pywrapcp.RoutingIndexManager(self.data.num_locations,
            self.data.num_vehicles,
            self.data.depot)

        self.routing = pywrapcp.RoutingModel(self.routingIndexManager)

        # Define weight of each edge
        try:            
            # time-matrix for OSRM might be expensive due to api response
            # in this case matrix should only be calculated if locations change
            # however: python magic seems to recognize if calc_time_matrix args are unchanged  
              
            self.time_matrix = self.calc_time_matrix(self.locations)
        except nx.NetworkXNoPath as err:
            logger.debug(f'NetworkXNoPath: {err}')
            raise NoRouteExceptionInternalError('No routing possible due to error when calculating time matrix. Internal error data: {err}')
        except ValueError as err:
            logger.warning(f'ValueError error within calc_time_matrix: {err}')
            raise NoRouteExceptionInternalError('No routing possible due to value error when calculating time matrix. Internal error data: {err}') 
        except:
            import sys
            logger.warning("Unexpected error:", sys.exc_info()[0])
            raise

        # todo umbauen oder entfernen - beachten dass der Ortools-Optimierer nur mit Integer rechnet
        # self.distance_evaluator =\
        #    CreateDistanceEvaluator(self.data, self.paths).distance_evaluator
        # self.routing.SetArcCostEvaluatorOfAllVehicles(self.distance_evaluator)
        # Add Capacity constraint
        self.demand_evaluator = CreateDemandEvaluator(
            self.data)
        add_capacity_constraints(
            self.routing, self.data, self.demand_evaluator.demand_evaluator_seats, self.demand_evaluator.demand_evaluator_wheelchairs, self.demand_evaluator.demand_evaluator_weighted_sum)

        # Add Time Window constraint
        self.time_evaluator = CreateTimeEvaluator(
            self.data, self.time_matrix, self.time_per_demand_unit_seat, self.time_per_demand_unit_wheelchair)
        add_time_window_constraints(
            self.routing, self.routingIndexManager, self.data, self.time_evaluator.time_evaluator)
        # Add pickup & delivery order constraint
        add_pickup_delivery_constraints(
            self.routing, self.routingIndexManager, self.time_evaluator.time_evaluator, self.time_matrix, self.data, self.hop_ons, self.hop_offs)
        # Assign intermediate stops
        add_mandatory_station_constraints(
            self.routing, self.routingIndexManager, self.data, self.stations)
        # Let mobies join their friends and family
        add_group_constraints(self.routing, self.routingIndexManager, self.data, self.groups)
        # Clip solutions that would require vehicles outside their work time
        add_vehicle_work_time_constraints(self.routing, self.data)
        if self.station_closing_times:
            add_station_closing_time_constraints(self.routing, self.routingIndexManager, self.data, self.station_closing_times)

        # define our cost function
        time_callback_index = self.routing.RegisterTransitCallback(self.time_evaluator.time_evaluator_weighted_demands)
        self.routing.SetArcCostEvaluatorOfAllVehicles(time_callback_index)

        # Setting first solution heuristic (cheapest addition).
        # https://developers.google.com/optimization/routing/routing_options#first-solution-strategy-options
        self.search_parameters = pywrapcp.DefaultRoutingSearchParameters()
        self.search_parameters.first_solution_strategy = (
            # routing_enums_pb2.FirstSolutionStrategy.LOCAL_CHEAPEST_INSERTION)
            routing_enums_pb2.FirstSolutionStrategy.PARALLEL_CHEAPEST_INSERTION)  # 4x faster
        # routing_enums_pb2.FirstSolutionStrategy.PATH_CHEAPEST_ARC)  # default
        # Solve the problem.
        logger.info('solve problem...')
        self.assignment = self.routing.SolveWithParameters(self.search_parameters)
        if self.assignment is None:
            logger.info('update: no solution found')
            raise NoRouteException
        else:
            logger.info('success')

    def build_paths(self)->None:
        """Build complete paths."""
        if self.assignment is None:
            logger.warning('build_paths: no solution found')
            raise NoRouteException
        time_dimension = self.routing.GetDimensionOrDie('Time')
        capacity_dimension_seats = self.routing.GetDimensionOrDie('Capacity')
        capacity_dimension_wheelchair = self.routing.GetDimensionOrDie('CapacityWheelchair')

        self._final_paths = {}

        # todo muss man die Pfade hier mit MINIMALEN Time-Windows abspeichern? Denn: fertige Routen sollen sich nicht mehr aendern!
        # es koennte sein, dass es besser ware, das nur fuer start- und end-Knoten der Orders zu machen (also da wo hop-on/off sind), denn bei den anderen Knoten
        # ist es eigentlich egal, andererseits werden sowieso nur stations mit hop-on/off gespeichert...        
        # kann ja auch ein 2. slack-Parameter sein!
        final_paths_slack = 3 # users might not accept large changes of booked orders
        depot_slack = 250 # time change at depot does not matter from user point of view

        for vehicle_idx, vehicle in enumerate(self.data.vehicles): # types: int, Vehicle
            # identify route node indices
            path_indices = []
            path_node_indices = []
            path_locations = []
            path_connections = []
            path_time_windows = []

            index = self.routing.Start(vehicle_idx)

            while True:                
                path_indices.append(index)

                node_index: LocationIndex = self.routingIndexManager.IndexToNode(index)
                path_node_indices.append(node_index)
                path_locations.append(self.locations[node_index])
                path_connections.append(self.locations_connection[node_index])
                path_time_windows.append(self._time_windows[node_index])

                if self.routing.IsEnd(index):
                    # finish
                    break
                else:
                    # next point exists
                    index = self.assignment.Value(self.routing.NextVar(index))

            # calc complete shortest path at once (performance) - TODO in future we might try to eval routes for all vehicles with one call
            nodes_of_route_all = self.calc_shortest_path_multi(path_locations)

            # build complete path data            
            self._final_paths[vehicle_idx] = []

            for iIndex in range(0, len(path_indices)):
                node_index: LocationIndex = path_node_indices[iIndex]                
                index = path_indices[iIndex]
                from_location = path_locations[iIndex]     
                from_connection = path_connections[iIndex]                           

                time_var = time_dimension.CumulVar(index)
                time_min: float = self.assignment.Min(time_var)
                time_max: float = self.assignment.Max(time_var)
                time_value: float = self.assignment.Value(time_var)    

                # time windows for final paths are restricted, for future routings we do not want to change existing too much
                slack_realized_lower = final_paths_slack
                slack_realized_upper = final_paths_slack

                if from_location == 'Depot':
                    slack_realized_lower = depot_slack
                    slack_realized_upper = depot_slack

                time_min = max(time_min, time_value-slack_realized_lower)            
                time_max = min(time_max, time_value+slack_realized_upper)   

                # try to extend interval of lenght 0
                if time_max - time_min < 1:
                    if time_min-1 >= path_time_windows[iIndex][0]:
                        time_min = time_min-1
                    if time_max+1 <= path_time_windows[iIndex][1]:
                        time_max = time_max+1

                # print('time_min_max')               
                # print(time_min)               
                # print(time_max)               

                capacity_var_seats = capacity_dimension_seats.CumulVar(index)
                capacity_var_wheelchair = capacity_dimension_wheelchair.CumulVar(index)
                capacity: VehicleCapacity = vehicle.capacity.calc_changed_capacity(self.assignment.Value(capacity_var_seats),self.assignment.Value(capacity_var_wheelchair))                              

                fromLat = None
                fromLon = None               

                if from_location == 'Depot':
                    from_node_id = 'Depot'
                else:
                    if hasattr(from_location, 'node_id'):
                        from_node_id = from_location.node_id
                    else:
                        raise ValueError(f'Location has not node_id, location data: {from_location}')
                    if hasattr(from_location, 'longitude') and hasattr(from_location, 'latitude'):
                        # for OSRM we need to save the lat/lon info since mapIDs are not sufficient
                        fromLat = from_location.latitude
                        fromLon = from_location.longitude
                    else:
                        raise ValueError(f'Location has not latitude/longitude, location data: {from_location}')

                node:Node = Node(map_id=from_node_id, time_min=time_min,
                    time_max=time_max, hop_off=self.hop_offs[node_index],
                    hop_on=self.hop_ons[node_index], location_id=node_index,
                    capacity=capacity, lat=fromLat, lon=fromLon)
                self._final_paths[vehicle_idx].append(node)
                # self._final_paths[vehicle_idx].append(
                #     (from_node, time_min, time_max, self.hop_offs[node_index],
                #      self.hop_ons[node_index]))

                # is this the end?
                if self.routing.IsEnd(index):
                    break

                # next point exists!
                next_node_index: LocationIndex = path_node_indices[iIndex+1]
                next_location = path_locations[iIndex+1]
                next_connection = path_connections[iIndex+1]

                slack_realized_lower = final_paths_slack
                slack_realized_upper = final_paths_slack

                if next_location == 'Depot':
                    slack_realized_lower = depot_slack
                    slack_realized_upper = depot_slack

                # nodes between stations (no hop on/off): interpolate information for path segments between stations                
                time_max_next:float = self.assignment.Max(time_dimension.CumulVar(next_node_index))
                time_min_next:float = self.assignment.Min(time_dimension.CumulVar(next_node_index))
                time_value_next:float = self.assignment.Value(time_dimension.CumulVar(next_node_index))

                # time windows for final paths are restricted, for future routings we do not want to change existing too much
                time_min_next = max(time_min_next, time_value_next-0.5*slack_realized_lower)            
                time_max_next = min(time_max_next, time_value_next+0.5*slack_realized_upper)        

                duration: float = self.time_evaluator.time_evaluator(node_index, next_node_index)
                dt_min: float = 0
                dt_max: float = duration

                capacity_var_seats = capacity_dimension_seats.CumulVar(next_node_index)
                capacity_var_wheelchair = capacity_dimension_wheelchair.CumulVar(next_node_index)
                capacity = vehicle.capacity.calc_changed_capacity(self.assignment.Value(capacity_var_seats),self.assignment.Value(capacity_var_wheelchair))  

                # when using osrm it is important to precompute complete path at once since api call is expensive
                nodes_tmp = nodes_of_route_all[iIndex][1:-1]

                for to_node in nodes_tmp:
                    edge_time = to_node[1]
                    dt_min += edge_time
                    dt_max -= edge_time
                    dt_max = max(0, dt_max)

                    t_min = min(time_min+dt_min, time_min_next-dt_max)
                    t_max = time_max_next-dt_max
                    node = Node(map_id=to_node[0], time_min=t_min, time_max=t_max,
                                hop_off=None, hop_on=None,
                                location_id=None, capacity=capacity, lat=None, lon=None)
                    self._final_paths[vehicle_idx].append(node)
                    from_node_id = to_node                

                if node_index == self.data.depot:
                    continue

    def printer(self, hideOutput=False)->str:
        printer = ConsolePrinter(
            self.data,
            self.routing,
            self.routingIndexManager,
            self.assignment,
            G=self.G,
            hop_offs=self.hop_offs,
            hop_ons=self.hop_ons)
        return printer.print(hideOutput)

def new_routing(G: nx.DiGraph, ORSM_url: str, request: Moby, promises: dict[int, Moby], mandatory_stations, busses, options, apriori_times_matrix = {}):
    """ Solve a routing problem in one functional call. """    
    # for bus in busses:
    #     print(bus)
    #     print(bus.capacity)

    if len(busses) == 0:
        raise ValueError("Can't find a route without busses!")

    slack_max = options['slack']
    
    tour = BusTour(G, ORSM_url, time_offset_factor=options['time_offset_factor'], time_per_demand_unit_wheelchair=options['time_service_per_wheelchair'], slack=slack_max, capacities=busses)
    
    #print(apriori_times_matrix)
    tour.time_matrix_save = apriori_times_matrix # this may boost performance considerably

    for station in mandatory_stations:
        # transform bus identifiers into bus indices within the problem domain
        bus_indices = [i for i,bus in enumerate(busses) if bus.id in station.bus_ids]
        # add stations without tour update, bc speed
        tour._add_station(station.station, station.time_window, bus_indices)

    # add promises: i.e. earlier orders that might be grouped with the new request
    for promise_id, moby in promises.items():
        logger.info(f'add promise {promise_id}: {moby}') # should be visible in logs for analyzing
        tour._add_moby(moby, promised=True)

    if request.start_window is not None and request.stop_window is not None:
        promised = True
    else:
        promised = False

    # increase slack stepwise and start with low slack
    # do not increase number of steps too much if performance is an issue
    slackValues = []
    slackSteps = 3    
    if 'sleck_steps' in options.keys():
        slackSteps = options['slack_steps']
    slackStepWidthMin = 5

    if slackSteps > 1 and slack_max / slackSteps >= slackStepWidthMin and not(promised):
        for step in (1,slackSteps-1):
            slackValues.append((int)(slack_max / slackSteps*step))
        slackValues.append(slack_max)
    else:
        slackValues.append(slack_max)
    
    #print(slackValues)
    time_window_start_old = request.start_window
    time_window_stop_old = request.stop_window

    # building paths may be omitted if not necessary - performance
    if 'build_paths' in options.keys():
        build_paths = options['build_paths']
    else:
        build_paths = True

    for slack in slackValues:
        tour.set_slack(slack)
        logger.info('new_routing - slack iteration with slack {} and moby {}'.format(slack, request))
        #print('new_routing - slack iteration with slack {} and moby {}'.format(slack, request))
        tour_id = tour.add_moby(request, build_paths=build_paths, promised=promised)  

        if not(tour_id is None):
            break
        else:
            # time windows must remain unchanged
            request.start_window = time_window_start_old
            request.stop_window = time_window_stop_old

    apriori_times_matrix = tour.time_matrix_save

    if tour_id is None:
        return None
    return tour, tour.get_routes()
