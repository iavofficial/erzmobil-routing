from routing.routingClasses import MobyLoad, Station
from routing.rutils import moby2order


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
        return moby2order(routing)
    
