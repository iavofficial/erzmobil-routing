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
from routing.routingClasses import MobyLoad, Station
from routing.rutils import moby2order


class SolverDummy():
    def solve(self, graph, OSRM_url:str, request, promises, mandatory_stations, busses, t_min_start_time_for_orders, options, apriori_times_matrix):

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

        solution = new_routing(graph, OSRM_url, request, promise_mobies, mandatory_stations, busses, t_min_start_time_for_orders, options, apriori_times_matrix)
        if solution is None:
            return None
        routing = solution[1]
        return moby2order(routing)
    
