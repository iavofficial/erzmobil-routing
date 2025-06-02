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
from copy import deepcopy
from uuid import uuid4
from typing import Optional, List, Tuple, Union, Callable, Set
from collections import namedtuple
from datetime import datetime
from dateutil.tz import tzutc

Numeric = Union[float, int]

TimeWindow = Tuple[int,int]
OptionalTimeWindow = Optional[TimeWindow]
MapNode = str

Node = namedtuple('Node', ['map_id', 'time_min', 'time_max', 'hop_off', 'hop_on', 'location_id', 'capacity', 'lat', 'lon'])
LocationIndex = int
BusIndex = int
BusID = str
TripID = str

def datetime2isostring(t : datetime) -> datetime:
    UTC = tzutc()
    return t.astimezone(UTC).isoformat()

class Group:
    def __init__(self, location_ids:List[LocationIndex]=[], penalty:int=100)->None:
        self.id = str(uuid4())
        self.location_ids = location_ids
        self.penalty = penalty

    def __repr__(self)->str:
        return f'Group({self.id},{self.location_ids},{self.penalty})'


class Station:
    def __init__(self, node_id: str, longitude: float = None, latitude: float = None, name: str = None)->None:
        self.node_id = node_id
        self.longitude = longitude
        self.latitude = latitude
        self.name = name

    def __repr__(self)->str:
        return f'Station({self.node_id}, {self.longitude}, {self.latitude}, {self.name})'

    def equalsStation(self, station)->bool:
        if self.node_id == station.node_id:
            return True
        
        if self.latitude is not None and abs(self.latitude - station.latitude) < 1e-6 and self.longitude is not None and abs(self.longitude - station.longitude) < 1e-6:
            return True

        return False

class MobyLoad:
    def __init__(self, load_standardSeat:int, load_wheelchair:int)->None:
        self.standardSeats = load_standardSeat
        self.wheelchairs = load_wheelchair  

    def __sub__(self, other):
        res = MobyLoad(self.standardSeats-other.standardSeats, self.wheelchairs-other.wheelchairs)        
        return res   
    
    def __add__(self, other):
        res = MobyLoad(self.standardSeats+other.standardSeats, self.wheelchairs+other.wheelchairs)        
        return res   

    def __neg__(self):
        res = MobyLoad(-self.standardSeats, -self.wheelchairs)        
        return res   

    def __repr__(self)->str:
        return f'MobyLoad({self.standardSeats}, {self.wheelchairs})'

    def equals(self, other)->bool:
        return self.standardSeats == other.standardSeats and self.wheelchairs==other.wheelchairs

    def isEmpty(self)->bool:
        return self.standardSeats == 0 and self.wheelchairs==0



class Moby:
    start_station: Station
    stop_station: Station

    def __init__(self, start: Station, stop: Station,
                 start_window: OptionalTimeWindow=None,
                 stop_window: OptionalTimeWindow=None,
                 load: MobyLoad=MobyLoad(1,0))->None:
        self.id = str(uuid4())
        self.start_station = start
        self.stop_station = stop
        self.start_window = start_window
        self.stop_window = stop_window

        if isinstance(load, MobyLoad):
            self.number_passengers = load
        else:
            raise TypeError('Moby needs a load object of type MobyLoad as input')        

    @property
    def start_location(self)->MapNode:
        return self.start_station.node_id
    @property
    def stop_location(self)->MapNode:
        return self.stop_station.node_id

    def __repr__(self)->str:
        if hasattr(self.start_station, 'node_id'):
            if self.start_station.node_id != None:
                start_node = self.start_station.node_id
            else:
                start_node = self.start_station    
        else:
            start_node = self.start_station

        if hasattr(self.stop_station, 'node_id'):
            if self.stop_station.node_id != None:
                stop_node = self.stop_station.node_id
            else:
                stop_node = self.stop_station
        else:
            stop_node = self.stop_station

        return 'Moby({}, {}, {}, {}, {})'.format(
            start_node,
            stop_node,
            self.start_window,
            self.stop_window,
            self.number_passengers)

class VehicleCapacity:    
    def __init__(self, maxNumSeats:int, maxNumWheelchairs:int, seatsBlockedPerWheelchair:int=2)->None:
        self.maxNumStandardSeats = max(0, maxNumSeats)
        self.maxNumWheelchairs = max(0, maxNumWheelchairs)
        self.seatsBlockedPerWheelchair = max(0, seatsBlockedPerWheelchair)  

    def is_load_allowed(self, loadStandardSeats:int, loadWheelchairs: int) -> bool:     
        if loadStandardSeats < 0:
            return False
        if loadWheelchairs < 0:
            return False       
        if loadStandardSeats > self.maxNumStandardSeats:
            return False
        if loadWheelchairs > self.maxNumWheelchairs:
            return False
        if loadStandardSeats + loadWheelchairs*self.seatsBlockedPerWheelchair > self.maxNumStandardSeats:
            return False
        return True

    def calc_changed_capacity(self, loadStandardChange:int, loadWheelchairChange:int):
        result: VehicleCapacity = deepcopy(self)        

        result.maxNumStandardSeats += loadStandardChange
        result.maxNumWheelchairs += loadWheelchairChange       

        if result.maxNumStandardSeats < 0 or result.maxNumWheelchairs < 0:
            raise ValueError('VehicleCapacity: capacity change not allowed')

        return result

    def __repr__(self)->str:
        return 'VehicleCapacity({}, {}, {})'.format(            
            self.maxNumStandardSeats,
            self.maxNumWheelchairs,
            self.seatsBlockedPerWheelchair)

class Vehicle():
    """Stores the property of a vehicle"""

    def __init__(self, capacity: VehicleCapacity, work_time: TimeWindow, start_location: Optional[MapNode]=None, stop_location: Optional[MapNode]=None, vehicleType: Optional[str] = 'bus')->None:
        """Initializes the vehicle properties"""
        self.id: str = str(uuid4())
        self._capacity: VehicleCapacity = capacity
        self._work_time = work_time
        self._start_location = start_location
        self._stop_location = stop_location
        self._vehicleType = vehicleType

    @property
    def vehicleType(self)->str:
        """Gets vehicle txpe"""
        return self._vehicleType

    @property
    def capacity(self)->VehicleCapacity:
        """Gets vehicle capacity"""
        return self._capacity

    @property
    def work_time(self)->TimeWindow:
        """Gets vehicle working time"""
        return self._work_time
    @work_time.setter
    def work_time(self, work_time: TimeWindow)->None:
        self._work_time = work_time
    
    @property
    def start_location(self)->MapNode:
        """MapID of start location, as per map service"""
        return self._start_location
    
    @property
    def stop_location(self)->MapNode:
        """MapID of stop location, as per map service"""
        return self._stop_location

    def __repr__(self)->str:
        return f'Vehicle({self.id},{self.capacity},{self.work_time})'

Passenger = Union[Moby, str]
class StationConstraint:
    def __init__(self, station:Station, time_window:TimeWindow, bus_ids:List[BusIndex], penalty:Optional[int]=None)->None:
        self.station = station
        self.time_window = time_window
        self.bus_ids = bus_ids
        self.penalty = penalty
    def __repr__(self)->str:
        return f'StationConstraint({self.station},{self.time_window},{self.bus_ids},{self.penalty})'

class Trip:
    def __init__(self, bus_id:BusID, nodes:List[Node], community:str, promised:bool=True):
        self.id:str = str(uuid4())
        self.bus_id:BusID = bus_id
        self.nodes:List[Node] = nodes
        self.community:str = community
        self.promised:bool = promised

        self.timestamp: datetime = datetime.utcnow()
        self.__parse__()

    def __parse__(self)->None:
        self.clients:Set[Passenger] = set(node.hop_on or node.hop_off for node in self.nodes \
            if node.hop_on or node.hop_off)
        self.start_location:MapNode = self.nodes[0].map_id
        self.stop_location:MapNode = self.nodes[-1].map_id
        self.start_time:float = self.nodes[0].time_min
        self.stop_time:float = self.nodes[-1].time_max

    def __repr__(self)->str:
        return f'Trip(bus_id={self.bus_id},{len(self.nodes)} nodes,{self.community},{self.promised},clients={self.clients})<trip_id={self.id}>'

    def load_profile(self)->List[int]:
        return [node.capacity for node in self.nodes]
