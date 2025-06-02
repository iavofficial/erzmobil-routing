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
import json
import logging
from typing import List

import requests
from routing.routingClasses import datetime2isostring

LOGGER = logging.getLogger(__name__)


class RoadClosures:
    def __init__(self, apiurl):
        self._api_uri = apiurl
        self.closures_lat = []
        self.closures_lon = []
        self.closures_vehicle_types = []
        self.closures_vehicles = []

    def getRoadClosuresList(self, bus_ids = [], vehicle_types = []):
        closures_coordinates: List = []

        row = 0
        for lat in self.closures_lat:
            closures_coordinates.append((lat, self.closures_lon[row]))
            row += 1        

        return self.filterClosuresList(closures_coordinates, bus_ids, vehicle_types)

    def filterClosuresList(self, closures_coordinates, bus_ids, vehicle_types):
        # filter closures_list with selected_vehicle and all vehicle_types

        # todo the road closure bus id/type info needs to be requested and initialized properly, currently empty
        if len(self.closures_vehicle_types) == 0 and len(self.closures_vehicles) == 0:
            return closures_coordinates

        filterPossibleBusId = False
        filterPossibleVehicleType = False

        for item in self.closures_vehicle_types:
            if len(item) != 0:
                filterPossibleVehicleType = True

        for item in self.closures_vehicles:
            if len(item) != 0:
                filterPossibleBusId = True
        
        if filterPossibleBusId == False and filterPossibleVehicleType == False:
            #print('closures are  not filtered')
            return closures_coordinates

        filterActiveBusId = False
        filterActiveVehicleType = False

        if len(bus_ids) != 0:
            filterActiveBusId = True

        if len(vehicle_types) != 0:
            filterActiveVehicleType = True

        for item in bus_ids:
            if item != '':
                filterActiveBusId = True

        for item in vehicle_types:
            if item != '':
                filterActiveVehicleType = True

        if filterActiveBusId == False and filterActiveVehicleType == False:
            #print('closures are  not filtered')
            return closures_coordinates
        
        # print('closures are filtered')
        # print('closures are filtered - filter vehicle ids:' + str(bus_ids))
        # print('closures are filtered - filter vehicle types:' + str(vehicle_types))
        # print('closures are filtered - closure vehicle ids:' + str(self.closures_vehicles))
        # print('closures are filtered - closure vehicle types:' + str(self.closures_vehicle_types))
        # print('closures are filtered - closure closures_coordinates:' + str(closures_coordinates))
        
        results: List = []        

        for i, item in enumerate(self.closures_vehicle_types):
            appended = False
                
            for vehicleType in vehicle_types:
                for type in item:
                    #print('closures are filtered - item and vehicleType:' + str(item) + ' ' + str(vehicleType))                
                    if type == vehicleType and appended == False:
                        results.append(closures_coordinates[i])
                        appended = True

            if appended == False:
                item = self.closures_vehicles[i]
                for id in bus_ids:
                    for id2 in item:
                        #print('closures are filtered - item and bus_ids:' + str(item) + ' ' + str(id))                
                        if id2 == id and appended == False:
                            results.append(closures_coordinates[i])
                            appended = True

        #print('closures are filtered - result:' + str(results))

        return results

    def initRoadClosures(self, communityId, start_time, stop_time):
        self.closures_lat = []
        self.closures_lon = []
        self.closures_vehicle_types = []
        self.closures_vehicles = []

        start_time_str = datetime2isostring(start_time)
        stop_time_str = datetime2isostring(stop_time)

        url = self._api_uri + '/customendpoints/roadclosures/' + str(
            communityId) + '/' + start_time_str + '/' + stop_time_str

        # print(url)
        LOGGER.info('requesting road closures at %s', url)

        try:
            response = requests.get(url, verify=False)
            if response.status_code != 200:
                raise ValueError(f'Could not get resources from {url}, got {response.status_code}:{response.text}')
        except Exception as err:
            raise ValueError(f'Error while calling url: {url}, error message: {err}')

        closures_raw = json.loads(response.text)

        for closure in closures_raw:
            self.closures_lat.append(closure['latitude'])
            self.closures_lon.append(closure['longitude'])
            self.closures_vehicle_types.append(closure['vehicleTypes'] if 'vehicleTypes' in closure else [])
            self.closures_vehicles.append(closure['vehicles'] if 'vehicles' in closure else [])
