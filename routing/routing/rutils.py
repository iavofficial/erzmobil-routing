from datetime import datetime
from datetime import timezone
from turtle import distance
import networkx as nx
from math import hypot
from math import sqrt
import pickle
from collections import defaultdict, OrderedDict
from functools import lru_cache, partial
from uuid import uuid4
from shapely.geometry import LineString
import pyproj
import time
from dateutil.relativedelta import relativedelta

from .OSRM_directions import OSRM
from .routingClasses import MobyLoad, Node, MapNode, Station, Trip

from typing import List, Dict, Any, Union, Callable

# debug stuff ####################
import logging
logger = logging.getLogger('routing.rutils')
# end debug stuff ################

# Constants
# unlikely to ever happen, extremely long time span. any bigger and ortool collapses
STNIMMERLEIN = int(1e17)

# Classes


class Path:
    """Container for path nodes, total distance in m and travel time in min."""

    def __init__(self, G: nx.DiGraph, nodes: List[MapNode])->None:
        self.nodes: List[MapNode] = nodes

        if G != None:
            self.distance: float = path_length(G, self.nodes)
            self.duration: float = path_length(G, self.nodes, weight=travel_time)

# Utility functions

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

def travel_time(edge: Dict[str, float])->float:
    """Return estimated edge travel time in minutes."""
    if 'length' in edge:
        length = edge["length"]
        #print("Normal-Edge")
        #print(edge)
    else:
        #length = 0
        # print("Problem-Edge")
        # print(edge)
        # print(edge_speed(edge))
        length = edge["length"]

    maxspeed = edge_speed(edge, lower=0)

    if maxspeed == 0:
        # detour, nobody should drive here
        #print('detour in travel_time')
        return 10000
    else:
        return length/maxspeed/60


def travel_time_min(edges)->float:
    """Find smallest value for all edges in a dict"""
    return min(travel_time(edges[i]) for i in edges)


def edge_speed(edge, lower=1, upper=120, fallback=50)->float:
    """Return maxspeed attribute of networkx edge in m/s."""
    try:
        # this should work most of the time
        if 'maxspeed' in edge:
            maxspeed = edge['maxspeed']

            if maxspeed == 'signals':
                maxspeed = fallback
            else:                
                # sometimes there are several speed limits
                # TODO: find out why
                if isinstance(maxspeed, list):
                    maxspeed = sum(float(s) for s in maxspeed)/len(maxspeed)
                maxspeed = float(maxspeed)
        else:
            maxspeed = fallback
    except:
        maxspeed = fallback

    return min(upper, max(lower, maxspeed)) / 3.6


def path_length(G, path, weight=None, key=travel_time):
    """Cummulated weight function for connected nodes in path over graph G."""
    if len(path) == 0:
        return 0
    l = 0
    if weight is None:
        weight = lambda edge: edge['length']
    for start, end in zip(path[:-1], path[1:]):
        if isinstance(G, nx.MultiDiGraph):
            edge = min(G[start][end], key=lambda d: key(G[start][end][d]))
            l += weight(G[start][end][edge])
        else:
            l += weight(G[start][end])
    return l


@lru_cache(maxsize=2**12)

def durations_matrix_OSRM(stations:list, OSRM_url:str, time_offset_factor: float)->dict:
    """
    Get matrix (dictionary) of total travel time between stations in min.
    matrix[station i][station j] gives travel time from station i to station j
    (station i and station j are Station objects (or str 'Depot') from provided 
    list of stations).
    """
    station_list = list(OrderedDict.fromkeys(stations))
    matrix_dict = {}

    # the following works only if the first station is depot, if other situations needed the zero-durations need to be implemented more flexible
    if len(station_list) == 0:
        return matrix_dict
    elif station_list[0]  != 'Depot':
        raise "Duration matrix currently only implemented for station list starting with 'Depot'"

    stations_coords = []
    for station in station_list:
        if station == 'Depot':
            continue
        else:
            if station.latitude == None or station.longitude == None:
                logger.warning(f'For OSRM stations need to know long/lat! Please check code.')
                print('OSRM ValueError + For graph stations need to know node_id! Please check code. Station data')
                print(station)
                raise ValueError("For OSRM stations need to know long/lat! Please check code.")
            stations_coords.append((station.latitude, station.longitude))
    
    time_matrix = OSRM(OSRM_url).matrix(stations_coords)

    # add travel time to and from Depot to and from all stations as 0    
    for idx, row in enumerate(time_matrix):
        time_matrix[idx] = [0] + row
    time_matrix = [[0] * len(time_matrix[0])] + time_matrix

    # collect durations    
    for i, from_node in enumerate(station_list):
        matrix_dict[from_node] = {to_node: time_offset_factor*time_matrix[i][j] for j, to_node in enumerate(station_list)}
    return matrix_dict

def durations_matrix_graph(stations:list, G: nx.DiGraph, time_offset_factor: float, time_matrix_apriori:dict[dict[int]])->dict:
    # timeStarted = time.time()
    
    station_list = list(OrderedDict.fromkeys(stations))
    matrix_dict = {}

    if len(station_list) == 0:
        return matrix_dict
   
    for station in station_list:
        if station == 'Depot':
            continue
        else:
            if not hasattr(station, 'node_id') or  station.node_id == None:
                print('GRAPH ValueError + For graph stations need to know node_id! Please check code. Station data')
                print(station)
                raise ValueError(f'For graph stations need to know node_id! Please check code. Station data:{station}')    

    # collect durations    
    for i, from_node in enumerate(station_list):
        rowTmp = {}

        if from_node != 'Depot' and not(from_node.node_id in time_matrix_apriori.keys()):
            time_matrix_apriori[from_node.node_id] = {}

        for j, to_node in enumerate(station_list): 
            if from_node != 'Depot' and to_node != 'Depot': 
                if not(to_node.node_id in time_matrix_apriori[from_node.node_id].keys()):
                    time_matrix_apriori[from_node.node_id][to_node.node_id] = None

            if from_node == 'Depot' or to_node == 'Depot' or i==j:
                rowTmp[to_node] = 0
            elif  to_node.node_id in time_matrix_apriori[from_node.node_id].keys() and time_matrix_apriori[from_node.node_id][to_node.node_id] is not None:
                rowTmp[to_node] = time_matrix_apriori[from_node.node_id][to_node.node_id] # do not calculate if it is already known - performance!
            else:
                rowTmp[to_node] = time_offset_factor*shortest_path_graph(G, from_node, to_node).duration
                time_matrix_apriori[from_node.node_id][to_node.node_id] = rowTmp[to_node] # save for later reuse - performance!
        
        matrix_dict[from_node] = rowTmp

    # timeElapsed = time.time()-timeStarted
    # print('time elapsed durations_matrix_graph')
    # print(timeElapsed)

    return matrix_dict

def shortest_path_graph_nodes(G: nx.DiGraph, start: any, stop: any, method = 'dijkstra')->List:
    """
    Create a path object from start to stop with meta information.
    The length of this path corresponds to its total travel time.
    """
    
    if start == 'Depot' or stop == 'Depot':
        return []

    # weight = lambda _, __, edges: travel_time_min(edges)  # MultiDiGraph
    weight = lambda _, __, edge: travel_time(edge)  # DiGraph

    if method == 'dijkstra':
        # Version 1: dijkstra, reference implementation
        nodes = nx.dijkstra_path(G, start.node_id, stop.node_id, weight=weight)
    elif method == 'astar':
        # Version 2: astar ~30% faster
        # def t_est(startID: MapNode, stopID: MapNode)->float:
        #    return time_estimate(G.node[startID], G.node[stopID])
        nodes = nx.astar_path(G, start.node_id, stop.node_id, weight=weight) # heuristic=t_est

    return nodes

def shortest_path_graph(G: nx.DiGraph, start: any, stop: any, method = 'dijkstra')->Path:
    if start == 'Depot' or stop == 'Depot':
        return Path(None, [])
    else:    
        return Path(G, shortest_path_graph_nodes(G, start, stop, method))

def shortest_path_graph_gps(G: nx.DiGraph, start: any, stop: any)->List:
    utm_zone = utm_zone_from_graph(G)
    GUC = GpsUtmConverter(utm_zone)

    path_nodes = shortest_path_graph_nodes(G, start, stop)

    coords = []
    xy_temp = []

    for node_id in path_nodes:
        xy_temp.append((G.nodes[node_id]['x'], G.nodes[node_id]['y']))

    # init of utm2gps ist slow - convert whole list at once
    coords = (GUC.utm2gps_list(xy_temp))       

    return coords

def shortest_path_OSRM(start: Station, stop: Station, OSRM_url: str)->Path:
    """
    Create a path object from start to stop with meta information.
    The length of this path corresponds to its total travel time.
    """
    if start == 'Depot' or stop == 'Depot':
        return Path(None, [])
    else:        
        nodes = OSRM(OSRM_url).route([(start.latitude, start.longitude),(stop.latitude, stop.longitude)])[0]
        return Path(None, nodes)

def shortest_path_OSRM_multi(locations: List[Station], OSRM_url: str, onlyGps: bool)->List:
    """
    Create a path object from start to stop with meta information.
    The length of this path corresponds to its total travel time.
    """

    if len(locations) < 2:
        return []

    if len(locations) == 2 and (locations[0] =='Depot' or locations[1] == 'Depot'):
        result = []
        result.append([])
        return result
    else:       
        routePoints = []

        for loc in locations:           
            if loc != 'Depot':   
                routePoints.append((loc.latitude, loc.longitude))

        resultTmp = OSRM(OSRM_url).route(routePoints, onlyGps=onlyGps)

        if onlyGps==True:
            return resultTmp

        result = []
        indexTmp = 0

        # depot is special case
        for indexloc in range(0, len(locations)-1): 
            if locations[indexloc] != 'Depot' and locations[indexloc+1] != 'Depot':  
                result.append(resultTmp[indexTmp])
                indexTmp += 1
            else:
                result.append([])
        return result


def time_estimate(start: Dict[str, float], stop: Dict[str, float], speed_ms: float = 60.0/3.6)->float:
    """
    Lower estimate on travel time in minutes.
    Travel distance is 'as the crow flies' and a max speed is assumed at 120kmh
    """
    # distance in m
    distance: float = hypot(start['x']-stop['x'], start['y']-stop['y'])
    # travel time in minutes : (m/m*s) / (60s/1min)
    return (distance / speed_ms) / 60.0


# Graph utils #####################
def penalize_node(G: nx.DiGraph, node: MapNode, penalty: float = 1e27)->None:
    """
    Lock node in netx graph in case of lockdowns or emergencies.
    WARNING: This operation modifies the graph!
    """
    for node_in, node_out in G.in_edges(node):
        for edge in G[node_in][node_out]:
            G[node_in][node_out][edge]['length'] = penalty
    for node_in, node_out in G.out_edges(node):
        for edge in G[node_in][node_out]:
            G[node_in][node_out][edge]['length'] = penalty

def multi2single(G: Union[nx.DiGraph, nx.MultiDiGraph], qualifier=travel_time)->nx.DiGraph:
    """Convert MultiDiGraph to DiGraph for use with astar."""
    # time_started = time.time()

    assert(isinstance(G, nx.DiGraph))
    if not isinstance(G, nx.MultiDiGraph):
        import copy
        return copy.deepcopy(G)    

    g = nx.DiGraph()
    g.add_nodes_from(G.nodes(data=True))

    edges = list(G.edges(data=True))
    g.add_edges_from(edges)

    last_connection = (None, None)
    for start, end, edge_attributes in edges:
        if (start, end) == last_connection:
            if qualifier(edge_attributes) < qualifier(g[start][end]):
                g.add_edges_from([(start, end, edge_attributes)])
        last_connection = (start, end)

    # time_elapsed = time.time() - time_started
    # print('time elapsed in multi2single')
    # print(time_elapsed)
    return g

def convertNodeNamesToString(G: nx.MultiDiGraph):
    node_names_old = set(G.nodes())

    mapping={}

    for name in node_names_old:
        mapping[name] = str(name)

    return nx.relabel_nodes(G, mapping)

def add_detours_from_gps(G: nx.MultiDiGraph, latlonlist: List, detours_around_in_metres: List):
    #time_started = time.time()
    logger.debug(f'add_detours_from_gps')
    
    # transform gps coords
    utm_zone = utm_zone_from_graph(G)
    logger.debug(f'utm_zone {utm_zone}')
    GUC = GpsUtmConverter(utm_zone)    
    logger.debug(f'GUC {GUC}')
    logger.debug(f'latlonlist {latlonlist}')
    graph_coords = GUC.gps2utm_list(lat_lon_list=latlonlist)
    logger.debug(f'graph_coords {graph_coords}')
    
    #print(graph_coords)
    found_nodes = []
    found_indices = []
    count_found = 0
    found_distances = []

    max_dist_in_metres = []
    find_all_around = []

    if len(detours_around_in_metres) == 0:
        logger.debug(f'len(detours_around_in_metres) == 0')
        for coords in graph_coords:
            detours_around_in_metres.append(10)
            
    logger.debug(f'for maxdist in detours_around_in_metres')

    # set allowed distances, but minimum 50m
    # check if only best solution is wanted for detour
    for maxdist in detours_around_in_metres:
        max_dist_in_metres.append(max(maxdist,50))    
        find_all_around.append((maxdist > 0))
    
    logger.debug(f'for detour_coords in graph_coords')
    for detour_coords in graph_coords:
        found_nodes.append(False)
        found_distances.append(1000000)
        found_indices_sublist = []
        found_indices.append(found_indices_sublist)
        
    logger.debug(f'for start_node, end_node, data in G.edges(data=True)')
    for start_node, end_node, data in G.edges(data=True):        
        coords_start = (G.nodes[start_node]['x'], G.nodes[start_node]['y'])
        coords_end = (G.nodes[end_node]['x'], G.nodes[end_node]['y'])

        index_coords = 0

        for detour_coords in graph_coords:            
            dist_to_edge = dist_of_point_to_edge_2d(coords_start, coords_end, detour_coords)     

            # decide if all segments are wanted or only best
            if dist_to_edge < max_dist_in_metres[index_coords] and (dist_to_edge<found_distances[index_coords] or find_all_around[index_coords] == True):            
                # print(data)
                # print(dist_to_edge)
                # print(f"coords_start: \n{coords_start}")
                # print(GUC.utm2gps(coords_start[0], coords_start[1]))
                # print(f"coords_end: \n{coords_end}")
                # print(GUC.utm2gps(coords_end[0], coords_end[1]))
                # print('=====')
                found_nodes[index_coords] = True
                found_distances[index_coords] = min(dist_to_edge, found_distances[index_coords])

                # if all segments are wanted: append
                if find_all_around[index_coords] == True or len(found_indices[index_coords]) == 0:
                    found_indices[index_coords].append((start_node, end_node))
                else:
                    found_indices[index_coords][0] = (start_node, end_node)

                count_found += 1

            index_coords+=1

    logger.debug(f'for sublist in found_indices')

    for sublist in found_indices:        
        for (start, end) in sublist:            
            # reset maxspeed for all wanted segments
            G[start][end][0]['maxspeed'] = '0' 
    
    # time_elapsed = time.time() - time_started
    # print('time elapsed in add_detours_from_gps')
    # print(time_elapsed)
    
    logger.debug(f'found_indices, found_distances')

    return found_indices, found_distances

def dist_of_point_to_edge_2d(edge_a, edge_b, point_c):
    # formula derived from area of triangle a) between two vectors by crossprod and b) height multiplied by base side lenght -> distance is the unknown height
    # cutting param is t where the projected point_c on the line of the edge lies, must not be too far away from [0,1] since the edge ends there
    # distances calculated here with UTM coords are approximatly the real distances in metres (compare segment lenght in data with calculated values)

    x1=edge_b[0]-edge_a[0]
    y1=edge_b[1]-edge_a[1]
    x2=point_c[0]-edge_a[0]
    y2=point_c[1]-edge_a[1]

    if x1==0 and y1==0:
        # degenerated edge - distance point-point
        return sqrt(x2*x2+y2*y2)

    height = abs(x1*y2-x2*y1)/sqrt(x1*x1+y1*y1)
    cutting_param = (x1*x2-y1*y2)/(x1*x1+y1*y1)       

    distance = height

    # projected point may be not inside the segment - distance is distance to start/end
    if cutting_param < 0:
        distance = sqrt((point_c[0]-edge_a[0])*(point_c[0]-edge_a[0])+(point_c[1]-edge_a[1])*(point_c[1]-edge_a[1]))
    elif cutting_param > 1:
        distance = sqrt((point_c[0]-edge_b[0])*(point_c[0]-edge_b[0])+(point_c[1]-edge_b[1])*(point_c[1]-edge_b[1]))

    # if distance < 50:
    #     print(distance)
    #     print(sqrt(x1*x1+y1*y1))
    #     print(f"edge_a: {edge_a}")
    #     print(f"edge_b: {edge_b}")
    #     print(f"point_c: {point_c}")
    #     print('===')

    return distance

def add_bus_stop(G: nx.MultiDiGraph , name, start_node, end_node, edge_id, fraction, bus_stop_id=None):
    assert(isinstance(G, nx.MultiDiGraph))
    edge = None
    for idx, e in G[start_node][end_node].items():
        if e['osmid'] == edge_id:
            edge = e
    assert(edge is not None)

    # read geo data
    if 'geometry' in edge: #some edges do not contain geometry information
        coords = list(edge['geometry'].coords)
    else:
        coords = [(G.nodes[start_node]['x'], G.nodes[start_node]['y']),
                   (G.nodes[end_node]['x'], G.nodes[end_node]['y'])]
    # map partial distances
    distances = []
    for start, end in zip(coords[:-1], coords[1:]):
        distance = hypot(start[0]-end[0], start[1]-end[1])
        distances.append(distance)
    total_dist = sum(distances)
    # figure out where this stop should be
    stop_dist = fraction*total_dist
    end_distance = 0
    start_distance = 0
    first_path = [coords[0]]
    second_path = coords[1:]
    x_stop = y_stop = None
    for partial_distance, start, end in zip(distances, coords[:-1], coords[1:]):
        start_distance, end_distance = end_distance, end_distance + partial_distance

        if end_distance >= stop_dist:
            xinterp = (stop_dist - start_distance) / partial_distance
            x_stop = start[0]+xinterp*(end[0]-start[0])
            y_stop = start[1]+xinterp*(end[1]-start[1])
            break
        first_path.append(second_path.pop(0))
    first_path.append((x_stop, y_stop))
    second_path.insert(0, (x_stop, y_stop))

    if bus_stop_id is None:
        bus_stop_id = str(uuid4())
    first_edge_id = str(uuid4())
    second_edge_id = str(uuid4())
    node_attributes = {'osmid': bus_stop_id, 'x': x_stop, 'y': y_stop}

    first_attributes = edge.copy()
    first_attributes['length'] *= fraction

    first_attributes['geometry'] = LineString(first_path)
    first_attributes['osmid'] = first_edge_id

    second_attributes = edge.copy()
    second_attributes['length'] *= 1-fraction
    second_attributes['geometry'] = LineString(second_path)
    second_attributes['osmid'] = second_edge_id

    G.add_node(bus_stop_id, **node_attributes)
    G.add_edge(start_node, bus_stop_id, **first_attributes)
    G.add_edge(bus_stop_id, end_node, **second_attributes)

    G.remove_edge(start_node, end_node, key=idx)
    return bus_stop_id


def get_nearests(G, node_coords, n_nearest):
    ''' node_coords are tuple of x, y (UTM) coordinates '''
    node_distances = []

    for osmid, data in G.nodes(data=True):
        distance = (data['x']-node_coords[0])**2 + (data['y']-node_coords[1])**2
        node_distances.append((osmid, distance, data))
    nearests = sorted(node_distances, key=lambda x: x[1])[:n_nearest]
    return(nearests)

def bus_stop_from_nearests(G, nearests, stop_name, stop_coords):
    '''
    nearests: list of tuples from nearest neighbors of stop, (osmid, distance, data).
    Stop_coords tuple of x, y (UTM coordinates).
    '''
    edge_found = False
    bus_stop_ids = []
    for node1 in nearests[:-1]:
        for node2 in nearests[1:]:
            edge1 = None
            edge2 = None
            # FIXME TODO How to handle if bus stops are on different position on either side of the road.
            if G.has_edge(node1[0], node2[0]):
                edge1 = (node1, node2, G[node1[0]][node2[0]][0])
                edge_found = True
            if G.has_edge(node2[0], node1[0]):
                edge2 = (node2, node1, G[node2[0]][node1[0]])
                edge_found = True
            if edge1 or edge2:
                for start_node, end_node, data in filter(None, [edge1, edge2]):
                    a, b, c = None, None, None
                    if 0 in data:
                        data = data[0]
                    if 'geometry' in data:
                        coords = list(data['geometry'].coords)
                        # map partial distances
                        distances = []
                        stop_distances = []
                        dists_from_busstop = []
                        for start, end in zip(coords[:-1], coords[1:]):
                            distance = hypot(start[0]-end[0], start[1]-end[1])
                            distances.append(distance)
                            if not dists_from_busstop:
                                dists_from_busstop.append(hypot(start[0] - stop_coords[0], start[1] - stop_coords[1]))
                            dist_from_busstop = hypot(end[0] - stop_coords[0], end[1] - stop_coords[1])
                            dists_from_busstop.append(dist_from_busstop)
                        idx_min_from_busstop = dists_from_busstop.index(min(dists_from_busstop))

                        stop_length = sum(distances[:(idx_min_from_busstop)])
                        edge_length = sum(distances)
                        #TODO do no take first edge found automatically, but check for best fit.
                        # draft to increase accuracy
                        # TODO more precise location
                        '''if (idx_min_from_busstop != 0) & (idx_min_from_busstop < (len(distances))):
                            if dists_from_busstop[idx_min_from_busstop-1] > dists_from_busstop[idx_min_from_busstop+1]:
                                a = dists_from_busstop[idx_min_from_busstop]
                                b = dists_from_busstop[idx_min_from_busstop+1]
                                c = distances[idx_min_from_busstop-1]
                                op = +1
                            elif dists_from_busstop[idx_min_from_busstop-1] < dists_from_busstop[idx_min_from_busstop+1]:
                                a = dists_from_busstop[idx_min_from_busstop]
                                b = dists_from_busstop[idx_min_from_busstop-1]
                                c = distances[idx_min_from_busstop]
                                op = -1
                        elif idx_min_from_busstop == 0:
                            a = dists_from_busstop[idx_min_from_busstop]
                            b = dists_from_busstop[idx_min_from_busstop + 1]
                            c = distances[idx_min_from_busstop]
                            op = +1
                        elif (idx_min_from_busstop) == (len(distances)):
                            a = dists_from_busstop[idx_min_from_busstop]
                            b = dists_from_busstop[idx_min_from_busstop - 1]
                            c = distances[idx_min_from_busstop-1]
                            op = -1

                        s = 0.5 * (a+b+c)
                        h = 2 / c * sqrt(s * (s-a)*(s-b)*(s-c))
                        residual = op * sqrt((a**2 - h**2))
                        stop_length = stop_length + residual'''
                    else:
                        edge_length = hypot(start_node[2]['x']-end_node[2]['x'], start_node[2]['y']-end_node[2]['y'])
                        stop_length = hypot(start_node[2]['x']-stop_coords[0], start_node[2]['y']-stop_coords[1])
                    fraction = stop_length/edge_length
                    if fraction > 1.0:
                        edge_found = False
                    else:
                        edge_found = True
                    if edge_found:
                        stop_id = add_bus_stop(G, stop_name, start_node[0], end_node[0], data['osmid'], fraction,
                            bus_stop_id=f'busnow_{stop_name}_{len(bus_stop_ids)}')
                        bus_stop_ids.append(stop_id)
            if edge_found:
                 # TODO Validate if edge found is correct edge'
                return bus_stop_ids
    # if no edge has been found: return empty list
    return bus_stop_ids

def bus_stop_from_gps(G, stop_name, longitude, latitude, n_nearests = 5):
    
    utm_zone = utm_zone_from_graph(G)
    GUC = GpsUtmConverter(utm_zone)
    stop_coords = GUC.gps2utm(longitude=longitude, latitude=latitude)
    nearests = get_nearests(G, stop_coords, n_nearests)
    stop_ids = bus_stop_from_nearests(G, nearests, stop_name, stop_coords)
    '''for stop in stop_ids:
       print(GUC.utm2gps(G.node[stop]['x'], G.node[stop]['y'])) '''
    return stop_ids

def nearest_from_gps(G, longitude, latitude, n_nearests = 5):
    utm_zone = utm_zone_from_graph(G)
    GUC = GpsUtmConverter(utm_zone)
    stop_coords = GUC.gps2utm(longitude=longitude, latitude=latitude)
    nearests = [n[0] for n in get_nearests(G, stop_coords, n_nearests)]
    return nearests

def get_utm_zone(lon_min, lon_max, lat_min, lat_max):
    # TODO make conversion possible outside of Germany
    if (lon_min >= 6.0) and (lon_max <= 12):
        utm_zone = '32'
    elif (lon_min > 12) and (lon_max <= 18):
        utm_zone = '33'
    else:
        raise ValueError('Covering more than one UTM zone or UTM zone not in range of longitude [6,18].')
    # FIXME TODO Check for max and min latitude
    # (36.7 <= lat <= 70.0): epsg:3044)
    # (35.0 <= lat <= 75.0): (epsg:3045)
    return utm_zone

def utm_zone_from_graph(graph):
    longitudes = nx.get_node_attributes(graph, 'lon')
    latitudes = nx.get_node_attributes(graph, 'lat')
    lon_max = max(longitudes.values())
    lon_min = min(longitudes.values())
    lat_max = max(latitudes.values())
    lat_min = min(latitudes.values())
    return get_utm_zone(lon_min, lon_max, lat_min, lat_max)

class GpsUtmConverter():

    def __init__(self, utm_zone):        
        self.gps = 4326
        self.utm_zone = utm_zone

    def gps2utm(self, latitude, longitude):
        'latitude and longitude are gps coordinates in decimal degrees'
        p_xy = pyproj.Proj(proj='utm', zone=self.utm_zone)  

        transformer = pyproj.Transformer.from_crs(self.gps, p_xy.crs, always_xy=True)
        x, y = transformer.transform(longitude,latitude)

        return(x,y)

    def gps2utm_list(self, lat_lon_list) -> List:
        logger.debug(f'gps2utm_list')
        'latitude and longitude are gps coordinates in decimal degrees'
        
        logger.debug(f'self.utm_zone {self.utm_zone}')

        p_xy = pyproj.Proj(proj='utm', zone=self.utm_zone)
        logger.debug(f'p_xy {p_xy}')

        transformer = pyproj.Transformer.from_crs(self.gps, p_xy.crs, always_xy=True)
        logger.debug(f'transformer {transformer}')

        result = []

        for lat, lon in lat_lon_list:
            x, y = transformer.transform(lon,lat)
            logger.debug(f'x, y = {x} {y}')
            result.append((x, y))
            
        logger.debug(f'result')

        return result

    def utm2gps(self, x, y):
        p_xy = pyproj.Proj(proj='utm', zone=self.utm_zone)

        transformer = pyproj.Transformer.from_crs(p_xy.crs, self.gps, always_xy=True)
        lon, lat = transformer.transform(x,y)

        return(lat, lon)

    def utm2gps_list(self, xy_List:List) -> List:
        p_xy = pyproj.Proj(proj='utm', zone=self.utm_zone)

        transformer = pyproj.Transformer.from_crs(p_xy.crs, self.gps, always_xy=True)

        result = []

        for x,y in xy_List:
            lon, lat = transformer.transform(x,y)
            result.append((lat, lon))

        return result

    @staticmethod
    def normalize_date(aDate: datetime, aRefDate: datetime):
        aDate = datetime.fromtimestamp(aDate.timestamp(), tz=timezone.utc)

        # make the beginning of the previous day the total reference for ip-values
        if aRefDate is None:
            aRefDate =  GpsUtmConverter.normalize_date_get_ref_date_default(aDate)
        else:
            aRefDate = datetime.fromtimestamp(aRefDate.timestamp(), tz=timezone.utc)

        norm = lambda t: int((t-aRefDate).total_seconds() // 60)

        return (norm(aDate), aRefDate)

    @staticmethod
    def denormalize_date(aTimeInMinutes: int, aRefDate: datetime):
        aRefDate = datetime.fromtimestamp(aRefDate.timestamp(), tz=timezone.utc)

        denorm = lambda t_normed: aRefDate + relativedelta(minutes=t_normed)

        return (denorm(aTimeInMinutes), aRefDate)

    @staticmethod
    def normalize_date_get_ref_date_default(aDate: datetime) -> datetime:
        aDate = datetime.fromtimestamp(aDate.timestamp(), tz=timezone.utc)
        return aDate - relativedelta(days=1) + relativedelta(hour=0, minute=0, second=0)



class ContinuityException(Exception):
    pass


def trips2routes(G: nx.DiGraph, trips: List[Trip], id_modifier: Callable = lambda item: item)->Dict[Any, List[Node]]:
    routes = dict()
    for trip in sorted(trips, key=lambda trip: (trip.start_time, trip.stop_time)):
        bus_id = id_modifier(trip.bus_id)
        if bus_id not in routes:
            routes[bus_id] = []
        elif len(routes[bus_id]) > 0:
            # stich them together
            last_node = routes[bus_id][-1]
            path = shortest_path(G, last_node.map_id, trip.nodes[0].map_id)
            time_per_node = path.duration / \
                (len(path.nodes)-1) if len(path.nodes) > 1 else path.duration
            time_min, time_max = last_node.time_min, last_node.time_max
            d_time_max = path.duration
            for node_id in path.nodes[1:-1]:
                time_min += time_per_node
                d_time_max -= time_per_node
                node = Node(map_id=node_id, time_min=time_min, time_max=time_max-d_time_max,
                            hop_off=None, hop_on=None, location_id=None, capacity=last_node.capacity)
                routes[bus_id].append(node)

        routes[bus_id].extend(trip.nodes)

    for key, route in routes.items():
        for from_node, to_node in zip(route[:-1], route[1:]):
            if from_node.map_id not in G:
                logger.warning(f'from_node not in graph {from_node.map_id}')
            if to_node.map_id not in G[from_node.map_id] and to_node.map_id != from_node.map_id:
                raise ContinuityException()
    return routes


###########
# Printer #
###########
class ConsolePrinter():
    """Print solution to console"""

    def __init__(self, data, routing, routingIndexManager, assignment, tw_offset=0, G=None,
                 durations_matrix=None, hop_offs=defaultdict(list), hop_ons=defaultdict(list)):
        """Initializes the printer"""
        #logger.debug(f'new Printer: {data}, {routing}, {assignment}, {tw_offset}, {G}, {paths}, {hop_offs}, {hop_ons}')
        self._data = data
        self._routing = routing
        self.routingIndexManager = routingIndexManager
        self._assignment = assignment
        self.tw_offset = tw_offset
        self.G = G
        self.durations_matrix = durations_matrix
        self.hop_offs = hop_offs
        self.hop_ons = hop_ons

    @property
    def data(self):
        """Gets problem data"""
        return self._data

    @property
    def routing(self):
        """Gets routing model"""
        return self._routing

    @property
    def assignment(self):
        """Gets routing model"""
        return self._assignment

    def print(self, hideOutput = False)-> str:
        """Prints assignment on console"""
        # Inspect solution.
        resultString = ''
        route_load: MobyLoad

        time_dimension = self.routing.GetDimensionOrDie('Time')
        capacity_dimension_seats = self.routing.GetDimensionOrDie('Capacity')
        capacity_dimension_wheelchair = self.routing.GetDimensionOrDie('CapacityWheelchair')
        total_dist = 0
        total_time = 0
        total_time_before_start = 0
        for vehicle_id in range(self.data.num_vehicles):
            index = self.routing.Start(vehicle_id)
            plan_output = 'Route for vehicle {}:\tworking minutes {}\n'.format(
                vehicle_id, self.data.vehicles[vehicle_id].work_time)
            route_dist = 0
            while not self.routing.IsEnd(index):
                node_index = self.routingIndexManager.IndexToNode(index)

                if node_index == 0:
                    route_load = MobyLoad(0,0)
                else:
                    load_var_seats = capacity_dimension_seats.CumulVar(index)
                    load_var_wheelchair = capacity_dimension_wheelchair.CumulVar(index)
                    route_load = MobyLoad(self.assignment.Value(load_var_seats),self.assignment.Value(load_var_wheelchair))

                time_var = time_dimension.CumulVar(index)
                time_min = self.assignment.Min(time_var)+self.tw_offset
                time_max = self.assignment.Max(time_var)+self.tw_offset
                slack_var = time_dimension.SlackVar(index)
                slack_min = self.assignment.Min(slack_var)
                slack_max = self.assignment.Max(slack_var)
                action = ''
                if self.hop_ons[node_index]:
                    action += 'moby {} enters'.format(self.hop_ons[node_index])
                if self.hop_offs[node_index]:
                    action += 'moby {} exits'.format(self.hop_offs[node_index])
                plan_output += '\t{:>9} \t{:>20} Load({:>2}(seats),{:>2}(wheelchairs)) Time({:>5},{:>5}) Slack({:>5},{:>5}) -> {}\n'.format(
                    self._data.locations[node_index].node_id if node_index > 0 else 0,
                    self._data.locations[node_index].name if node_index > 0 else 'depot',
                    route_load.standardSeats,
                    route_load.wheelchairs,
                    time_min, time_max,
                    slack_min, slack_max,
                    action)
                if self._data.locations[node_index] == 'Depot':
                    start_time_depot = time_min
                try:
                    next_node_index = self.routingIndexManager.IndexToNode(
                        self.assignment.Value(self.routing.NextVar(index)))
                    # route_dist += self.paths(node_index,
                    #                          next_node_index).distance
                except:
                    break
                index = self.assignment.Value(self.routing.NextVar(index))

            node_index = self.routingIndexManager.IndexToNode(index)
            if node_index == 0:
                route_load = MobyLoad(0,0)
            else:
                load_var_seats = capacity_dimension_seats.CumulVar(index)
                load_var_wheelchair = capacity_dimension_wheelchair.CumulVar(index)
                route_load = MobyLoad(self.assignment.Value(load_var_seats),self.assignment.Value(load_var_wheelchair))

            time_var = time_dimension.CumulVar(index)
            route_time = self.assignment.Value(time_var)
            time_min = self.assignment.Min(time_var)
            time_max = self.assignment.Max(time_var)
            #total_dist += route_dist
            total_time += route_time
            total_time_before_start += start_time_depot
            plan_output += '\t{:>9} Load({:>2}(seats),{:>2}(wheelchairs)) Time({:>5},{:>5})\n'.format(node_index, route_load.standardSeats, route_load.wheelchairs, time_min, time_max)
            #plan_output += 'Distance of the route: {0}m\n'.format(route_dist)
            plan_output += 'Load of the route (seats): {0}\n'.format(route_load.standardSeats)
            plan_output += 'Load of the route (wheelchairs): {0}\n'.format(route_load.wheelchairs)
            plan_output += 'Time of the route (including time before start of route): {0}min\n'.format(route_time)
            plan_output += 'Time of the route (excluding time before start of route): {0}min\n'.format(route_time-start_time_depot)            
            resultString = resultString + plan_output + '\n'
        #print('Total Distance of all routes: {0}m'.format(total_dist))
        resultString += 'Total Time of all routes (including time before start of route): {0}min'.format(total_time)
        resultString += 'Total Time of all routes (including time before start of route): {0}min'.format(total_time-total_time_before_start)        

        if hideOutput != True:
            print(resultString)

        return resultString

