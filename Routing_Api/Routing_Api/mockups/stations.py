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
import requests
import json
from django.core.exceptions import ObjectDoesNotExist


class Stations():
    """ Station accessor with db-backend """

    def __init__(self, StationDb, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._station = StationDb
    # def _nearby(self, lat, lon, cutoff_km, n):
    #     nearest = self._station.objects.nearby(lat, lon, cutoff_km).first()
    #     if nearest:
    #         return [nearest][:n]
    #     return []

    def get_stops_by_geo_locations(self, geo_locations, cutoff_km=5000, n=1):
        nearest_stops = []
        # print(f"geo_locations: {geo_locations}")
        # print(f"geo_locations type: {type(geo_locations)}")
        for (lat, lon) in geo_locations:
            # print(f"{(lat, lon)}")
            nearest = self._nearby(lat=lat, lon=lon, cutoff_km=cutoff_km, n=n)
            # print(f"nearest: {nearest}")
            # print(f"nearest type: {type(nearest)}")
            if nearest:
                nearest_stops.append(nearest)
            else:
                nearest_stops.append([])
            # print(f"nearest_stops: {nearest_stops}")
            # print(f"nearest_stops type: {type(nearest_stops)}")
        return nearest_stops

    def get_mandatory_stations(self, community, before, after):
        del community
        del before
        del after
        return []

    def update(self, station_id, **kwargs):
        try:
            station = self._station.objects.get(uid=station_id)
        except ObjectDoesNotExist:
            station = self._station(uid=station_id)
        for attribute, value in kwargs.items():
            setattr(station, attribute, value)
        station.save()

        return station

    def get_by_id(self, station_id):
        return self._station.objects.get(uid=station_id)


class WebStations(Stations):
    def __init__(self, stopUrl, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._stopUrl = stopUrl

    def _nearby(self, lat, lon, cutoff_km, n):
        parameters = {'lat': lat, 'lng': lon, 'n': n, 'r': cutoff_km*1000}
        url = self._stopUrl + '/nearest'
        print(url)        
        response = requests.get(url, params=parameters, verify=False)
        # print(f"response.content: {response.content}")
        if response.status_code != 200:
            raise ValueError(
                f'Fetching bus stops near {(lat, lon)} failed with status code {response.status_code} , response text:\n{response.text}')
        try:        
            stops_raw = json.loads(response.content)
            # print(f"stops_raw: {stops_raw}")
        except Exception as e:
            raise ValueError(
                f'Fetching bus stops near {(lat, lon)} failed since json response could not be loaded. Json content:\n {response.content} \n Error:\n{e}')
        stops = []
        for stop in stops_raw:
            # print(f"stop {stop} in stops_raw {stops_raw}")
            stops.append(
                self.update(
                    station_id=stop['id'],
                    community=stop['communityId'],
                    name=stop['name'],
                    latitude=stop['latitude'],
                    longitude=stop['longitude']))
        # print(f"found stops in _nearby: {stops}")
        # print(f"found stops[:n] in _nearby: {stops[:n]}")
        # print(f"found stops in _nearby type: {type(stops)}")
        return stops[:n]
