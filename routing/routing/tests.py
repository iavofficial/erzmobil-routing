from unittest import TestCase
import time
import networkx as nx
import pickle
from pprint import pprint
from ortools.constraint_solver import routing_enums_pb2, pywrapcp
from copy import deepcopy

from .OSRM_directions import OSRM
from .routing import BusTour, Moby, MobyLoad, Station, Vehicle, VehicleCapacity, new_routing
from .rutils import durations_matrix_graph, add_bus_stop, bus_stop_from_gps, nearest_from_gps, multi2single, durations_matrix_OSRM, shortest_path_graph, add_detours_from_gps, dist_of_point_to_edge_2d

from .maps import Maps

class TestMeisenheim(TestCase):
    def setUp(self):
        # read map (either yaml or pickle)
        m = Maps(data_dir='../maps')
        self.G: nx.DiGraph = multi2single(m.get_graph('meisenheim'))
        self.assertIsNotNone(self.G)

    def _std_fleet_1(self):
        fleet = [Vehicle(capacity=cap, work_time=(0, 1440)) for cap in [VehicleCapacity(3,0), VehicleCapacity(3,0), VehicleCapacity(4,0)]]
        return fleet

    def _std_tour_1(self, fleet):
        tour = BusTour(self.G, None, slack=1, capacities=fleet, time_offset_factor=1.0, time_per_demand_unit_wheelchair=3.0)
        return tour

    def test_Meisenheim(self):
        s_Lindenallee = Station('929163070')
        s_Untergasse = Station('288942560')
        s_Bahnhof = Station('288939733')
        s_Edeka = Station('469732623')
        s_Gymnasium = Station('293644764')
        s_Reiffelbach = Station('1236586204')
        s_Roth = Station('1258712074')

        m1 = [Moby(s_Lindenallee, s_Untergasse, None, (45, 60)),
              Moby(s_Untergasse, s_Reiffelbach, (50, 70), None)]
        m2 = [Moby(s_Gymnasium, s_Edeka, None, (30, 45), load=MobyLoad(2,0)),
              Moby(s_Edeka, s_Bahnhof, None, (70, 90), load=MobyLoad(2,0))]
        m3 = Moby(s_Gymnasium, s_Edeka, None, (35, 45), load=MobyLoad(1,0)) # will zusammen mit m2 fahren
        m4 = [Moby(s_Reiffelbach, s_Roth, None, (90, 120)),
            Moby(s_Roth, s_Bahnhof, None, (70, 90), load=MobyLoad(4,0))]

        fleet = self._std_fleet_1()
        tour = self._std_tour_1(fleet)
        g1 = tour.add_mobies(m1)
        g2 = tour.add_moby(m2[0])
        g3 = tour.add_moby(m3, group_id=g2, penalty=int(1e10))
        g4 = tour.add_mobies(m4)

        #tour.printer()

        # check result
        routes = tour.get_routes()
        self.assertEqual(len(routes), 3)

        lenRoute =len(routes[0])
        self.assertEqual(lenRoute, 479)
        self.assertEqual(routes[0][1].map_id, s_Lindenallee.node_id)
        self.assertEqual(routes[0][lenRoute-2].map_id, s_Roth.node_id)

        lenRoute =len(routes[1])
        self.assertEqual(lenRoute, 35)
        self.assertEqual(routes[1][1].map_id, s_Gymnasium.node_id)
        self.assertEqual(routes[1][lenRoute-2].map_id, s_Edeka.node_id)

        lenRoute =len(routes[2])
        self.assertEqual(lenRoute, 245)
        self.assertEqual(routes[2][1].map_id, s_Roth.node_id)
        self.assertEqual(routes[2][lenRoute-2].map_id, s_Bahnhof.node_id)

class BusTourTest(TestCase):
    # read map (either yaml or pickle) - due to performance we should do that only once for all tests (if possible)!  
    _maps = Maps(data_dir='../maps')
    _Graph_raw = _maps.get_graph('Peine_2km')
    _Graph: nx.DiGraph = multi2single(_Graph_raw)
    _Graph_Zwoenitz_raw = _maps.get_graph('Zwoenitz')    
    _Graph_Zwoenitz: nx.DiGraph = multi2single(_Graph_Zwoenitz_raw)

    def shortDescription(self): # turn off printing docstring in tests
        return None

    def setUp(self):        
        self.assertIsNotNone(self._Graph)

    def _std_fleet_1(self):
        return [Vehicle(capacity=cap, work_time=(0, 1440)) for cap in [VehicleCapacity(4,0), VehicleCapacity(4,0), VehicleCapacity(2,0)]]

    def _std_fleet_2a_wheelchair(self):
        return [Vehicle(capacity=cap, work_time=(0, 1440)) for cap in [VehicleCapacity(6,1,2)]]

    def _std_fleet_2b_wheelchair(self):
        return [Vehicle(capacity=cap, work_time=(0, 1440)) for cap in [VehicleCapacity(6,2,0)]]

    def _std_fleet_2c_wheelchair(self):
        return [Vehicle(capacity=cap, work_time=(0, 1440)) for cap in [VehicleCapacity(3,1,0)]]        

    def _std_tour_1(self, fleet):
        # set up tour and check
        return BusTour(self._Graph, None, slack=1, capacities=fleet, time_offset_factor=1.0, time_per_demand_unit_wheelchair=3.0)

    def _std_tour_1_OSRM(self, fleet):
        # set up tour and check
        return BusTour(None, OSRM.getDefaultUrl_OSRM_Testserver(), slack=1, capacities=fleet, time_offset_factor=1.0, time_per_demand_unit_wheelchair=3.0)

    def _std_tour_1_OSRM_Zwoenitz(self, fleet):
        # set up tour and check
        return BusTour(None, OSRM.getDefaultUrl_Testserver(), slack=1, capacities=fleet, time_offset_factor=1.0, time_per_demand_unit_wheelchair=3.0)

    def _std_tour_1_maps_Zwoenitz(self, fleet):
        # set up tour and check
        return BusTour(self._Graph_Zwoenitz, None, slack=30, capacities=fleet, time_offset_factor=1.0, time_per_demand_unit_wheelchair=3.0)

    def test_constructor(self):
        # capa arg must be appropriate type    
        errMess = ''

        try:
           BusTour(self._Graph, None, slack=1, capacities=[1], time_offset_factor=1.0, time_per_demand_unit_wheelchair=3.0) 
        except TypeError as err:
            errMess = err

        self.assertEqual(str(errMess), str(TypeError('BusTour needs a list of vehicle objects as input')))    
        

    def test_add_fleet_1(self):
        # set up fleet and check
        fleet = self._std_fleet_1()
        self.assertEqual(len(fleet), 3)
        # check for the given capacities
        cap = [f.capacity for f in fleet]
        self.assertEqual(len(cap),3)
        self.assertEqual(cap[0].maxNumStandardSeats,4)
        self.assertEqual(cap[0].maxNumWheelchairs,0)
        self.assertEqual(cap[1].maxNumStandardSeats,4)
        self.assertEqual(cap[1].maxNumWheelchairs,0)
        self.assertEqual(cap[2].maxNumStandardSeats,2)
        self.assertEqual(cap[2].maxNumWheelchairs,0)        
        # check for the given work time
        wt = [f.work_time for f in fleet]
        self.assertEqual(wt, [(0, 1440), (0, 1440), (0, 1440)])

    def test_add_tour_1(self):
        fleet = self._std_fleet_1()
        tour = self._std_tour_1(fleet)
        self.assertIsNotNone(tour)
        self.assertIsInstance(tour.G, nx.DiGraph)
        self.assertEqual(tour._slack, 1)
        # sowas in der art: self.assertEqual(tour.capacities, fleet.capacity)

    def test_add_mobies_delete_refused_moby(self):
        """
        Test for breaking errors on new mobies
        """

        fleet = self._std_fleet_1()
        tour = self._std_tour_1(fleet)

        station1 = Station('323200732')
        station2 = Station('291520520')
        station3 = Station('291521266')
        station4 = Station('286042889')

        m1 = Moby(station1, station2, None, (504, 506))
        m2 = Moby(station3, station4, None, (506, 510))
        m3 = Moby(station1, station4, (495, 508), None)
        m4 = Moby(station1, station2, (495, 508), None, load=MobyLoad(3,0))
        
        # add moobies at once
        tour.add_mobies([m1, m2, m3, m4])

        ##############################################
        # add moby for who the shortest path time yields a negative starting time

        locations_old = ','.join(map(str, tour.locations))
        hop_ons_old = ','.join(map(str, tour.hop_ons))
        hop_offs_old = ','.join(map(str, tour.hop_offs))
        loads_old = ','.join(map(str, tour.loads))
        groups_old = ','.join(map(str, tour.groups))

        self.assertEqual('Depot,Station(323200732, None, None, None),Station(291520520, None, None, None),Station(291521266, None, None, None),Station(286042889, None, None, None),Station(323200732, None, None, None),Station(286042889, None, None, None),Station(323200732, None, None, None),Station(291520520, None, None, None)', locations_old)
        self.assertEqual('1,3,5,7,0,2,8,4,6', hop_ons_old)
        self.assertEqual('2,4,6,8,0,7,1,3,5', hop_offs_old)
        self.assertEqual('MobyLoad(0, 0),MobyLoad(1, 0),MobyLoad(-1, 0),MobyLoad(1, 0),MobyLoad(-1, 0),MobyLoad(1, 0),MobyLoad(-1, 0),MobyLoad(3, 0),MobyLoad(-3, 0)', loads_old)
        
        # add moby
        m1 = Moby(station1, station2, None, (4, 6))
        gid = tour.add_moby(m1)
        self.assertIsNone(gid) # this moby has no solution, thus data must be properly cleaned, otherwise next moby might fail by improper data
        
        # data must not be changed
        self.assertEqual(','.join(map(str, tour.locations)), locations_old)
        self.assertEqual(','.join(map(str, tour.hop_ons)), hop_ons_old)
        self.assertEqual(','.join(map(str, tour.hop_offs)), hop_offs_old)
        self.assertEqual(','.join(map(str, tour.loads)), loads_old)
        self.assertEqual(','.join(map(str, tour.groups)), groups_old)          
        
        ##############################################
        # possible route must be found with 4, 9 - AFTER the refused request before

        m2 = Moby(station1, station2, None, (4, 9))
        gid = tour.add_moby(m2)
        self.assertIsNotNone(gid)

    def test_add_mobies_sequentially(self):
        """
        Test for breaking errors on new mobies
        """
        
        # focus of this test: non successfull add_moby MUST NOT CHANGE DATA
        fleet = self._std_fleet_1()
        tour = self._std_tour_1(fleet)

        station1 = Station('323200732')
        station2 = Station('291520520')
        station3 = Station('291521266')
        station4 = Station('286042889')

        m1 = Moby(station1, station2, None, (504, 506))
        m2 = Moby(station3, station4, None, (506, 510))
        m3 = Moby(station1, station4, (495, 508), None)
        m4 = Moby(station1, station2, (495, 508), None, load=MobyLoad(3,0))

        # add mobies sequentially
        for m in [m1, m2, m3, m4]:
            gid = tour.add_moby(m)
            self.assertIsNotNone(gid)        

        # check tour details
        locations_old = ','.join(map(str, tour.locations))
        hop_ons_old = ','.join(map(str, tour.hop_ons))
        hop_offs_old = ','.join(map(str, tour.hop_offs))
        loads_old = ','.join(map(str, tour.loads))

        self.assertEqual('Depot,Station(323200732, None, None, None),Station(291520520, None, None, None),Station(291521266, None, None, None),Station(286042889, None, None, None),Station(323200732, None, None, None),Station(286042889, None, None, None),Station(323200732, None, None, None),Station(291520520, None, None, None)', locations_old)
        self.assertEqual('1,0,2,3,4,5,6,7,8', hop_ons_old)
        self.assertEqual('2,0,1,4,3,6,5,8,7', hop_offs_old)
        self.assertEqual('MobyLoad(0, 0),MobyLoad(1, 0),MobyLoad(-1, 0),MobyLoad(1, 0),MobyLoad(-1, 0),MobyLoad(1, 0),MobyLoad(-1, 0),MobyLoad(3, 0),MobyLoad(-3, 0)', loads_old)

    def test_add_moby_and_get_route(self):        

        fleet = self._std_fleet_1()
        tour = self._std_tour_1(fleet)

        station1 = Station('323200732', 50.1, 10.5, 'stop1')
        station2 = Station('291520520', 51.2, 9.8, 'stop2')

        m1 = Moby(station1, station2, None, (504, 506))        
        
        gid = tour.add_moby(m1)
        self.assertIsNotNone(gid)        

        # check tour details
        locations_old = ','.join(map(str, tour.locations))
        hop_ons_old = ','.join(map(str, tour.hop_ons))
        hop_offs_old = ','.join(map(str, tour.hop_offs))
        loads_old = ','.join(map(str, tour.loads))        

        self.assertEqual('Depot,Station(323200732, 50.1, 10.5, stop1),Station(291520520, 51.2, 9.8, stop2)', locations_old)
        self.assertEqual('1,0,2', hop_ons_old)
        self.assertEqual('2,0,1', hop_offs_old)
        self.assertEqual('MobyLoad(0, 0),MobyLoad(1, 0),MobyLoad(-1, 0)', loads_old)

        # check route
        routes=tour.get_routes()
        self.assertEqual(len(routes), len(fleet))
        subroute1 = routes[0]
        subroute2 = routes[1]
        subroute3 = routes[2]
        self.assertEqual(len(subroute1), 39)  
        self.assertEqual(len(subroute2), 2)
        self.assertEqual(len(subroute3), 2)

        nodeDepotStart=subroute1[0]
        self.assertEqual(nodeDepotStart.map_id, 'Depot')
        self.assertEqual(nodeDepotStart.lon, None)
        self.assertEqual(nodeDepotStart.lat, None)
        nodeStation1=subroute1[1]
        self.assertEqual(nodeStation1.map_id, '323200732')
        self.assertEqual(nodeStation1.lon, 50.1)
        self.assertEqual(nodeStation1.lat, 10.5)
        nodeStation2=subroute1[37]
        self.assertEqual(nodeStation2.map_id, '291520520')
        self.assertEqual(nodeStation2.lon, 51.2)
        self.assertEqual(nodeStation2.lat, 9.8)
        nodeDepotEnd=subroute1[38]
        self.assertEqual(nodeDepotEnd.map_id, 'Depot')
        self.assertEqual(nodeDepotEnd.lon, None)
        self.assertEqual(nodeDepotEnd.lat, None)

        #print(routes)

    def test_add_moby_promised_2_orders_with_same_start(self):        

        fleet = self._std_fleet_2c_wheelchair()
        tour = self._std_tour_1(fleet)

        station1 = Station('323200732')
        station2 = Station('291520520')
        station3 = Station('286042889')

        m1 = Moby(station1, station2, (500, 503), (503, 515), MobyLoad(2,1))     
        
        gid = tour.add_moby(m1, promised=True)
        self.assertIsNotNone(gid)  

        m2 = Moby(station1, station3, (500, 510), None, MobyLoad(1,0))      
        
        gid = tour.add_moby(m2)
        self.assertIsNotNone(gid)  

    def test_add_moby_optimize_moby_travel_times_large_slack_1(self):        
        # routing should not focus on minimizing driving time of bus, if moby trip time is much larger due to avoiding bus detours
        fleet = self._std_fleet_2c_wheelchair()
        tour = self._std_tour_1_maps_Zwoenitz(fleet)

        # large slack as used in practice (large slack makes sense for allowing the optimizer some kind of variation options)
        self.assertEqual(tour._slack,30)

        station1 = Station('785870070',12.812662,50.629931,'ZwoenitzMarkt')
        station2 = Station('771928984',12.8374737110073,50.6678396595001,'DorfchemnitzWartehalle') 
        station3 = Station ('4384385900',12.798217,50.632136,'ZwoenitzBahnhof')

        m1 = Moby(station2, station1, (500, 503), (508, 511), MobyLoad(1,0))     
        
        gid = tour.add_moby(m1, promised=True)
        self.assertIsNotNone(gid)  

        m2 = Moby(station1, station3, (475, 485), None, MobyLoad(1,0))      
        
        gid = tour.add_moby(m2)
        self.assertIsNotNone(gid)  

        routes=tour.get_routes()

        # check route
        routes=tour.get_routes()
        self.assertEqual(len(routes), len(fleet))
        subroute1 = routes[0]        
        self.assertEqual(len(subroute1), 469) 

        #print(subroute1)

        # bus route should be: moby m2 delivered first; then m1, should not mix m2 around m1
        # this may be enforced by adapting optimizer objective: minimize routes with moby loads, distances without load do not matter
        nodeDepotStart=subroute1[0]
        self.assertEqual(nodeDepotStart.map_id, 'Depot')
        nodeStation1=subroute1[1]
        self.assertEqual(nodeStation1.map_id, '785870070')
        self.assertEqual(nodeStation1.time_min, 475)
        self.assertEqual(nodeStation1.time_max, 478)
        self.assertEqual(str(nodeStation1.hop_on), str(m2))
        nodeStation2=subroute1[46]
        self.assertEqual(nodeStation2.map_id, '4384385900')
        self.assertEqual(nodeStation2.time_min, 478)
        self.assertEqual(nodeStation2.time_max, 481)
        self.assertEqual(str(nodeStation2.hop_off), str(m2))
        nodeStation3=subroute1[270]
        self.assertEqual(nodeStation3.map_id, '771928984')
        self.assertEqual(nodeStation3.time_min, 500)
        self.assertEqual(nodeStation3.time_max, 503)
        self.assertEqual(str(nodeStation3.hop_on), str(m1))
        nodeStation4=subroute1[467]
        self.assertEqual(nodeStation4.map_id, '785870070')
        self.assertEqual(nodeStation4.time_min, 508)
        self.assertEqual(nodeStation4.time_max, 511)
        self.assertEqual(str(nodeStation4.hop_off), str(m1))
        nodeDepotEnd=subroute1[468]
        self.assertEqual(nodeDepotEnd.map_id, 'Depot')

    def test_add_moby_optimize_moby_travel_times_large_slack_2(self):        
        # routing should not focus on minimizing driving time of bus, if moby trip time is much larger due to avoiding bus detours
        fleet = self._std_fleet_2c_wheelchair()
        tour = self._std_tour_1_maps_Zwoenitz(fleet)

        # large slack as used in practice (large slack makes sense for allowing the optimizer some kind of variation options)
        self.assertEqual(tour._slack,30)

        station1 = Station('785870070',12.812662,50.629931,'ZwoenitzMarkt')
        station2 = Station('771928984',12.8374737110073,50.6678396595001,'DorfchemnitzWartehalle') 
        station3 = Station ('708549125',12.81604,50.685502,'BruenlosGemeinde')
        station4 = Station ('1843842890',12.8125286801734,50.6358749673226,'ZwoenitzSportkomplex')

        m1 = Moby(station2, station1, (500, 503), (508, 511), MobyLoad(1,0))     
        
        gid = tour.add_moby(m1, promised=True)
        self.assertIsNotNone(gid)  

        m2 = Moby(station4, station3, (475, 485), None, MobyLoad(2,0))      
        
        gid = tour.add_moby(m2)
        self.assertIsNotNone(gid)  

        routes=tour.get_routes()

        #print(tour.time_matrix)

        # check route
        routes=tour.get_routes()
        self.assertEqual(len(routes), len(fleet))
        subroute1 = routes[0]  
        #print(subroute1)
        self.assertEqual(len(subroute1), 507) 

        # bus route should be: moby m2 delivered first; then m1, should not mix m2 around m1
        # this may be enforced by adapting optimizer objective: minimize routes with moby loads, distances without load do not matter
        # additionally we needed to add a constraint of max allowed travelling time compared to min possible time
        nodeDepotStart=subroute1[0]
        self.assertEqual(nodeDepotStart.map_id, 'Depot')
        nodeStation1=subroute1[1]
        self.assertEqual(nodeStation1.map_id, '1843842890')
        self.assertEqual(nodeStation1.time_min, 475)
        self.assertEqual(nodeStation1.time_max, 478)
        self.assertEqual(str(nodeStation1.hop_on), str(m2))
        nodeStation2=subroute1[185]
        self.assertEqual(nodeStation2.map_id, '708549125')
        self.assertEqual(nodeStation2.time_min, 484)
        self.assertEqual(nodeStation2.time_max, 487)
        self.assertEqual(str(nodeStation2.hop_off), str(m2))
        nodeStation3=subroute1[308]
        self.assertEqual(nodeStation3.map_id, '771928984')
        self.assertEqual(nodeStation3.time_min, 500)
        self.assertEqual(nodeStation3.time_max, 503)
        self.assertEqual(str(nodeStation3.hop_on), str(m1))
        nodeStation4=subroute1[505]
        self.assertEqual(nodeStation4.map_id, '785870070')
        self.assertEqual(nodeStation4.time_min, 508)
        self.assertEqual(nodeStation4.time_max, 511)
        self.assertEqual(str(nodeStation4.hop_off), str(m1))
        nodeDepotEnd=subroute1[506]
        self.assertEqual(nodeDepotEnd.map_id, 'Depot')

    def test_add_moby_with_time_offset_factor(self):        
        fleet = self._std_fleet_2c_wheelchair()
        tour = self._std_tour_1_maps_Zwoenitz(fleet)

        # slower bus may be respected by time offset factor
        self.assertEqual(1.0, tour._time_offset_factor)
        tour._time_offset_factor = 1.5
        self.assertEqual(1.5, tour._time_offset_factor)        

        station1 = Station('785870070',12.812662,50.629931,'ZwoenitzMarkt')
        station2 = Station('771928984',12.8374737110073,50.6678396595001,'DorfchemnitzWartehalle') 

        m1 = Moby(station2, station1, (500, 503), None, MobyLoad(1,0))     
        
        gid = tour.add_moby(m1, promised=False)
        self.assertIsNotNone(gid)          

        #print(tour.time_matrix)

        # check route - times decreas due to time offset factor
        routes=tour.get_routes()
        self.assertEqual(len(routes), len(fleet))
        subroute1 = routes[0]  
        #print(subroute1)
        self.assertEqual(len(subroute1), 200) 

        nodeDepotStart=subroute1[0]
        self.assertEqual(nodeDepotStart.map_id, 'Depot')
        nodeStation1=subroute1[1]
        self.assertEqual(nodeStation1.map_id, '771928984')
        self.assertEqual(nodeStation1.time_min, 500)
        self.assertEqual(nodeStation1.time_max, 503)        
        self.assertEqual(str(nodeStation1.hop_on), str(m1))
        nodeStation4=subroute1[198]
        self.assertEqual(nodeStation4.map_id, '785870070')
        self.assertEqual(nodeStation4.time_min, 511)
        self.assertEqual(nodeStation4.time_max, 514)
        self.assertEqual(str(nodeStation4.hop_off), str(m1))
        nodeDepotEnd=subroute1[199]
        self.assertEqual(nodeDepotEnd.map_id, 'Depot')

    def test_add_moby_with_connections(self):          

        fleet = self._std_fleet_2c_wheelchair()

        s1 = Station(longitude=12.812662, latitude=50.629931,\
            name = "Markt", node_id='785870070')
        s2 = Station(longitude=12.798217, latitude=50.632136,\
            name = "Bahnhof", node_id='4384385900')

        # no connection
        tour = self._std_tour_1_maps_Zwoenitz(fleet)
        m1 = Moby(s2, s1, (620, 630), None, MobyLoad(1,0))
        gid = tour.add_moby(m1, promised=False)
        self.assertIsNotNone(gid)
        routes=tour.get_routes()
        self.assertEqual(len(routes), len(fleet))
        subroute1 = routes[0]  
        #print(subroute1)
        self.assertEqual(len(subroute1), 48) 
        nodeDepotStart=subroute1[0]
        self.assertEqual(nodeDepotStart.map_id, 'Depot')
        nodeStation1=subroute1[1]
        self.assertEqual(nodeStation1.map_id, '4384385900')
        self.assertEqual(nodeStation1.time_min, 620)
        self.assertEqual(nodeStation1.time_max, 623)        
        self.assertEqual(str(nodeStation1.hop_on), str(m1))
        nodeStation4=subroute1[46]
        self.assertEqual(nodeStation4.map_id, '785870070')
        self.assertEqual(nodeStation4.time_min, 623)
        self.assertEqual(nodeStation4.time_max, 626)
        self.assertEqual(str(nodeStation4.hop_off), str(m1))
        nodeDepotEnd=subroute1[47]
        self.assertEqual(nodeDepotEnd.map_id, 'Depot')
        self.assertEqual(str(tour.locations_connection), '[\'\', \'\', \'\']')
        self.assertEqual(str(tour.time_windows), '[(0, 0), (620, 630), (620, 662)]')

        # connection at departure with adjusted time window
        tour = self._std_tour_1_maps_Zwoenitz(fleet)
        m1 = Moby(s2, s1, (656, 666), None, MobyLoad(1,0))
        gid = tour.add_moby(m1, promised=False)
        self.assertIsNotNone(gid)
        routes=tour.get_routes()
        self.assertEqual(len(routes), len(fleet))
        subroute1 = routes[0]  
        #print(subroute1)
        self.assertEqual(len(subroute1), 48) 
        nodeDepotStart=subroute1[0]
        self.assertEqual(nodeDepotStart.map_id, 'Depot')
        nodeStation1=subroute1[1]
        self.assertEqual(nodeStation1.map_id, '4384385900')
        self.assertEqual(nodeStation1.time_min, 659)
        self.assertEqual(nodeStation1.time_max, 662)        
        self.assertEqual(str(nodeStation1.hop_on), str(m1))
        nodeStation4=subroute1[46]
        self.assertEqual(nodeStation4.map_id, '785870070')
        self.assertEqual(nodeStation4.time_min, 662)
        self.assertEqual(nodeStation4.time_max, 665)
        self.assertEqual(str(nodeStation4.hop_off), str(m1))
        nodeDepotEnd=subroute1[47]
        self.assertEqual(nodeDepotEnd.map_id, 'Depot')
        self.assertEqual(str(tour.locations_connection), '[\'\', \'DepartureFixed\', \'\']')
        self.assertEqual(str(tour.time_windows), '[(0, 0), (659, 666), (656, 698)]')

        # no connection if promised
        tour = self._std_tour_1_maps_Zwoenitz(fleet)
        m1 = Moby(s2, s1, (656, 666), (662,672), MobyLoad(1,0))
        gid = tour.add_moby(m1, promised=True)
        self.assertIsNotNone(gid)
        routes=tour.get_routes()
        self.assertEqual(len(routes), len(fleet))
        subroute1 = routes[0]  
        #print(subroute1)
        self.assertEqual(len(subroute1), 48) 
        nodeDepotStart=subroute1[0]
        self.assertEqual(nodeDepotStart.map_id, 'Depot')
        nodeStation1=subroute1[1]
        self.assertEqual(nodeStation1.map_id, '4384385900')
        self.assertEqual(nodeStation1.time_min, 656)
        self.assertEqual(nodeStation1.time_max, 659)        
        self.assertEqual(str(nodeStation1.hop_on), str(m1))
        nodeStation4=subroute1[46]
        self.assertEqual(nodeStation4.map_id, '785870070')
        self.assertEqual(nodeStation4.time_min, 662)
        self.assertEqual(nodeStation4.time_max, 665)
        self.assertEqual(str(nodeStation4.hop_off), str(m1))
        nodeDepotEnd=subroute1[47]
        self.assertEqual(nodeDepotEnd.map_id, 'Depot')
        self.assertEqual(str(tour.locations_connection), '[\'\', \'\', \'\']')
        self.assertEqual(str(tour.time_windows), '[(0, 0), (656, 666), (662, 672)]')

        # connection at arrival with adjusted time window
        tour = self._std_tour_1_maps_Zwoenitz(fleet)
        m1 = Moby(s1, s2, None, (654, 657), MobyLoad(1,0))
        gid = tour.add_moby(m1, promised=False)
        self.assertIsNotNone(gid)
        routes=tour.get_routes()
        self.assertEqual(len(routes), len(fleet))
        subroute1 = routes[0]  
        #print(subroute1)
        self.assertEqual(len(subroute1), 48) 
        nodeDepotStart=subroute1[0]
        self.assertEqual(nodeDepotStart.map_id, 'Depot')
        nodeStation1=subroute1[1]
        self.assertEqual(nodeStation1.map_id, '785870070')
        self.assertEqual(nodeStation1.time_min, 651)
        self.assertEqual(nodeStation1.time_max, 652)        
        self.assertEqual(str(nodeStation1.hop_on), str(m1))
        nodeStation4=subroute1[46]
        self.assertEqual(nodeStation4.map_id, '4384385900')
        self.assertEqual(nodeStation4.time_min, 654)
        self.assertEqual(nodeStation4.time_max, 655)
        self.assertEqual(str(nodeStation4.hop_off), str(m1))
        nodeDepotEnd=subroute1[47]
        self.assertEqual(nodeDepotEnd.map_id, 'Depot')
        self.assertEqual(str(tour.locations_connection), '[\'\', \'\', \'ArrivalFixed\']')
        self.assertEqual(str(tour.time_windows), '[(0, 0), (622, 657), (654, 655)]')
    
    def test_moby_hops_equal(self):
        """
        Test for breaking errors on new mobies
        """

        fleet = self._std_fleet_1()
        tour = self._std_tour_1(fleet)

        station1 = Station('323200732')
        station2 = Station('291520520')
        station3 = Station('291521266')
        station4 = Station('286042889')

        m1 = Moby(station1, station2, None, (504, 506))
        m2 = Moby(station3, station4, None, (506, 510))
        m3 = Moby(station1, station4, (495, 508), None)
        m4 = Moby(station1, station2, (495, 508), None, load=MobyLoad(3,0))

        for m in [m1, m2, m3, m4]:
            tour.add_moby(m)

        ons = [id(moby) for _, moby in tour.hop_ons.items() if moby is not None]
        offs = [id(moby) for _, moby in tour.hop_offs.items() if moby is not None]

        assert(sorted(ons) == sorted(offs))

    def test_add_moby_with_wheelchairs_fitting_bus_capa_1(self):
        # test max capa of bus with wheelchairs
        # bus capa: VehicleCapacity(6,1,2)

        fleet = self._std_fleet_2a_wheelchair()
        tour = self._std_tour_1(fleet)

        station1 = Station('323200732')
        station2 = Station('291520520')
               
        ###########################################################
        # add moby: not allowed loads - use large time windows due to growing service times for large groups

        m1 = Moby(station1, station2, None, (100, 200), load=MobyLoad(7,0))  
        gid = tour.add_moby(m1)
        self.assertIsNone(gid) # this moby has no solution, bus capa not sufficient

        m2 = Moby(station1, station2, None, (100, 200), load=MobyLoad(4,2))  
        gid = tour.add_moby(m2)
        self.assertIsNone(gid) # this moby has no solution, bus capa not sufficient

        m3 = Moby(station1, station2, None, (100, 200), load=MobyLoad(5,1))  
        gid = tour.add_moby(m3)
        self.assertIsNone(gid) # this moby has no solution, bus capa not sufficient

        self.assertEqual(len(tour.locations), 1)
        self.assertEqual(len(tour.hop_ons), 0)
        self.assertEqual(len(tour.hop_offs), 0)
        self.assertEqual(len(tour.loads), 1)

        ###########################################################
        # allowed loads  - use large time windows due to growing service times for large groups

        m4 = Moby(station1, station2, None, (100, 200), load=MobyLoad(4,1))  
        gid = tour.add_moby(m4)
        self.assertIsNotNone(gid)

        self.assertEqual(len(tour.locations), 3)
        self.assertEqual(len(tour.hop_ons), 3)
        self.assertEqual(len(tour.hop_offs), 3)
        self.assertEqual(len(tour.loads), 3)

        m5 = Moby(station1, station2, None, (400, 500), load=MobyLoad(6,0))  
        gid = tour.add_moby(m5)
        self.assertIsNotNone(gid)

        self.assertEqual(len(tour.locations), 5)
        self.assertEqual(len(tour.hop_ons), 5)
        self.assertEqual(len(tour.hop_offs), 5)
        self.assertEqual(len(tour.loads), 5)

    def test_add_moby_with_wheelchairs_fitting_bus_capa_2(self):
        # test max capa of bus with wheelchairs
        # bus capa: VehicleCapacity(6,2,0)

        fleet = self._std_fleet_2b_wheelchair()
        tour = self._std_tour_1(fleet)

        station1 = Station('323200732')
        station2 = Station('291520520')
               
        ###########################################################
        # add moby: not allowed loads - use large time windows due to growing service times for large groups

        m1 = Moby(station1, station2, None, (100, 200), load=MobyLoad(7,0))  
        gid = tour.add_moby(m1)
        self.assertIsNone(gid) # this moby has no solution, bus capa not sufficient

        m2 = Moby(station1, station2, None, (100, 200), load=MobyLoad(6,3))  
        gid = tour.add_moby(m2)
        self.assertIsNone(gid) # this moby has no solution, bus capa not sufficient

        m3 = Moby(station1, station2, None, (100, 200), load=MobyLoad(7,2))  
        gid = tour.add_moby(m3)
        self.assertIsNone(gid) # this moby has no solution, bus capa not sufficient

        self.assertEqual(len(tour.locations), 1)
        self.assertEqual(len(tour.hop_ons), 0)
        self.assertEqual(len(tour.hop_offs), 0)
        self.assertEqual(len(tour.loads), 1)

        ###########################################################
        # allowed loads  - use large time windows due to growing service times for large groups

        m4 = Moby(station1, station2, None, (100, 200), load=MobyLoad(6,2))  
        gid = tour.add_moby(m4)
        self.assertIsNotNone(gid)

        self.assertEqual(len(tour.locations), 3)
        self.assertEqual(len(tour.hop_ons), 3)
        self.assertEqual(len(tour.hop_offs), 3)
        self.assertEqual(len(tour.loads), 3)

        m5 = Moby(station1, station2, None, (400, 500), load=MobyLoad(6,0))  
        gid = tour.add_moby(m5)
        self.assertIsNotNone(gid)

        self.assertEqual(len(tour.locations), 5)
        self.assertEqual(len(tour.hop_ons), 5)
        self.assertEqual(len(tour.hop_offs), 5)
        self.assertEqual(len(tour.loads), 5)

    
    def test_moby_hop_ons_before_offs(self):
        """
        Test for breaking errors on new mobies
        """

        station1 = Station('323200732')
        station2 = Station('291520520')
        station3 = Station('291521266')
        station4 = Station('286042889')

        fleet = self._std_fleet_1()
        tour = self._std_tour_1(fleet)
        m1 = Moby(station1, station2, None, (504, 506))
        m2 = Moby(station3, station4, None, (506, 510))
        m3 = Moby(station1, station4, (495, 508), None)
        m4 = Moby(station1, station2, (495, 508), None, load=MobyLoad(3,0))

        for m in [m1, m2, m3, m4]:
            tour.add_moby(m)
    
        t = tour.get_routes()
        ons = []
        offs = []
        for route in t.values():
            for node in route:
                if node.hop_on:
                    ons.append(node)
                
                if node.hop_off:
                    offs.append(node)
        for on_node in ons:
            off_nodes = [n for n in offs if n.hop_off ==  on_node.hop_on]
            '''if off and on_nodes not equal: test above (test_moby_hops_equal) fails'''
            assert((on_node.time_min <= off_nodes[0].time_min) & (on_node.time_max <= off_nodes[0].time_max))      

    def test_add_station(self):
        # """Test for breaking errors on mandatory stations"""
        fleet = self._std_fleet_1()
        tour = self._std_tour_1(fleet)
        s = Station('323200732')
        tour.add_station(station=s, time_window=(540,560), bus_ids=[2])
        t = tour.get_routes()
        in2 = False
        for node in t[2]:
            osmid, tmin, tmax, *rest = node
            if osmid == '323200732':
                if not ((tmax < 540) and (tmin > 560)):
                    in2 = True
                    break
        assert(in2)

    def test_add_stations(self):
        """
        Test for breaking errors on mandatory stations
        """

        fleet = self._std_fleet_1()
        tour = self._std_tour_1(fleet)
        s1 = Station('323200732')
        s2 = Station('286042889')

        tour.add_stations(stations=[s1,s2],
                          time_windows=[(540,560), (600,700)],
                          bus_ids_list=[[2],[0,1]])
        t = tour.get_routes()
        in0 = False
        in1 = False
        in2 = False
        for node in t[2]:
            osmid, tmin, tmax, *rest = node
            if osmid == '323200732':
                if not ((tmax < 540) and (tmin > 560)):
                    in2 = True
                    break
        for node in t[0]:
            osmid, tmin, tmax, *rest = node
            if osmid == '286042889':
                if not ((tmax < 600) and (tmin > 700)):
                    in0 = True
                    break
        for node in t[1]:
            osmid, tmin, tmax, *rest = node
            if osmid == '286042889':
                if not ((tmax < 600) and (tmin > 700)):
                    in1 = True
                    break
        assert(in2 and in0 and in1)

    def test_moby_groups(self):
        """
        Test assignment of mobies to a group
        """

        fleet = self._std_fleet_1()
        tour = self._std_tour_1(fleet)

        station1 = Station('323200732')
        station2 = Station('291520520')
        station3 = Station('291521266')
        station4 = Station('286042889')

        m1 = Moby(station1, station2, None, (510, 520))
        m2 = Moby(station3, station4, None, (510, 520))
        m3 = Moby(station1, station4, (500, 520), None)
        m4 = Moby(station1, station2, (500, 520), None, load=MobyLoad(3,0))

        # default: m1&m4 same vehicle
        group_id=None
        for m in [m1,m2]:
            group_id = tour.add_moby(m, group_id=group_id, penalty=int(1e10))

        group_id=None
        for m in [m3,m4]:
            group_id = tour.add_moby(m, group_id=group_id, penalty=int(1e10))

        t = tour.get_routes()
        in0 = [node_details[4] for node_details in t[0] if node_details is not None]
        in1 = [node_details[4] for node_details in t[1] if node_details is not None]
        in2 = [node_details[4] for node_details in t[2] if node_details is not None]

        for partner1, partner2 in [(m1,m2), (m3,m4)]:
            found = False
            for l in [in0, in1, in2]:
                if partner1 in l and partner2 in l:
                    found = True
            assert(found)

    def test_group_to_big_for_one_vehicle(self):
        """
        Test if group is split to two vehicles if to big 
        """

        fleet = self._std_fleet_1()
        tour = self._std_tour_1(fleet)

        station1 = Station('323200732')
        station2 = Station('291520520')

        m1 = Moby(station1, station2, None, (510, 520), MobyLoad(2,0))
        m2 = Moby(station1, station2, None, (510, 520), MobyLoad(3,0))

        group_id=None
        for m in [m1,m2]:
            group_id = tour.add_moby(m, group_id=group_id, penalty=int(1e10))
        t = tour.get_routes()
        in0 = [node_details[4] for node_details in t[0] if node_details is not None]
        in1 = [node_details[4] for node_details in t[1] if node_details is not None]
        in2 = [node_details[4] for node_details in t[2] if node_details is not None]
        
        for partner1, partner2 in [(m1,m2)]:
            found = False
            for l in [in0, in1, in2]:
                if partner1 in l and partner2 in l:
                    found = True
            assert(not found)

    def test_add_bus_stop(self):      
        """
        Add a custom bus station to the graph.        
        """
        fleet = self._std_fleet_1()
        tour = self._std_tour_1(fleet)
        # split the from start to end and check that it has the osmid edge_id
        start_node = '358006731'
        end_node = '94535093'
        edge_id = 31960570
        fraction = 0.3
        stop_id = add_bus_stop(self._Graph_raw, 'haltestelle 1', start_node, end_node, edge_id, fraction)
        assert(stop_id in self._Graph_raw[start_node])
        assert(end_node in self._Graph_raw[stop_id])
        self._Graph = multi2single(self._Graph_raw)

        station1 = Station('323200732')
        station2 = Station(node_id = stop_id)

        m1 = Moby(station1, station2, None, (510, 520))
        tour = BusTour(self._Graph, None, slack=1, capacities=fleet, time_offset_factor=1.0, time_per_demand_unit_wheelchair=3.0)
        tour.add_moby(m1)

    def test_add_station_closing_time(self):
        fleet = self._std_fleet_1()
        tour_graph = self._std_tour_1(fleet)
        tour_OSRM = self._std_tour_1_OSRM(fleet)

        # station1 = Station('323200732')
        # station2 = Station('291520520')

        station1 = Station(longitude=10.129, latitude=52.316, name='Station 1', node_id=1)
        station1.node_id = nearest_from_gps(self._Graph, longitude=station1.longitude, latitude=station1.latitude, n_nearests = 1)[0]    
       
        station2 = Station(longitude=10.229, latitude=52.321, name='Station 2', node_id=2)
        station2.node_id = nearest_from_gps(self._Graph, longitude=station2.longitude, latitude=station2.latitude, n_nearests = 1)[0]  

        m1 = Moby(station1, station2, None, (510, 520))
        m1_OSRM = Moby(station1, station2, None, (510, 520))

        # method using graph
        tour_graph.add_station_closing_time(station2, [(0, 515)])
        tour_graph.add_moby(m1)

        adapt_window = True
        t = tour_graph.get_routes()
        for node in t[0]:
            osmid, tmin, tmax, *rest = node
            if osmid == station2.node_id:
                if (tmin < 515):
                    adapt_window = False
        assert(adapt_window)

        # method using OSMR
        tour_OSRM.add_station_closing_time(station2, [(0, 515)])
        tour_OSRM.add_moby(m1_OSRM)

        adapt_window = True
        t = tour_OSRM.get_routes()
        for node in t[0]:
            osmid, tmin, tmax, *rest = node
            if osmid == station2.node_id:
                if (tmin < 515):
                    adapt_window = False
        assert(adapt_window)

    def test_add_station_closing_times(self):
        fleet = self._std_fleet_1()
        tour = self._std_tour_1(fleet)
        adapt_window = True

        station1 = Station('323200732')
        station2 = Station('291520520')
        station3 = Station('291521266')
        station4 = Station('286042889')

        m1 = Moby(station1, station2, None, (510, 520))
        m2 = Moby(station3, station4, None, (510, 520))
        m3 = Moby(station1, station4, (510, 520), None)
        m4 = Moby(station1, station2, (990, 1010), None, MobyLoad(3,0))
        
        tour.add_station_closing_time(station2, [(0, 515)])
        tour.add_station_closing_time(station1, [(0, 510),(1000,1440)])
        tour.add_mobies([m1,m2,m3,m4])
        ts = tour.get_routes()
        for t in ts.values():
            for node in t:
                osmid, tmin, tmax, *rest = node
                if osmid == station2.node_id:
                    if (tmin < 515):
                        adapt_window = False
                if osmid == station1.node_id:
                    if (tmin < 510):
                        adapt_window = False
                    if (tmax > 1000):
                        adapt_window = False
        assert(adapt_window)

    def test_add_overlapping_station_closing_times(self):
        fleet = self._std_fleet_1()
        tour = self._std_tour_1(fleet)
        adapt_window = True

        station1 = Station('323200732')
        station2 = Station('291520520')
        station3 = Station('291521266')
        station4 = Station('286042889')

        m1 = Moby(station1, station2, None, (510, 520))
        m2 = Moby(station3, station4, None, (400, 500))
        m3 = Moby(station1, station4, (510, 520), None)
        m4 = Moby(station1, station2, (640, 715), None, MobyLoad(3,0))
        
        tour.add_station_closing_time(station1, [(515, 615),(600,700)])
        tour.add_station_closing_time(station4, [(420,440)])
        tour.add_mobies([m1,m2,m3,m4])
        #tour.printer()
        ts = tour.get_routes()
        for t in ts.values():
            for node in t:
                osmid, tmin, tmax, *rest = node
                if osmid == station1.node_id:
                    if (515 <= tmin) & (tmax <= 700):
                        adapt_window = False
                if osmid == station4.node_id:
                    if (420 <= tmin <= 440) or (420 <= tmax <= 440):
                        adapt_window = False
        assert(adapt_window)
        
    def test_bus_stop_from_gps(self):
        stop_ids=bus_stop_from_gps(self._Graph_raw, stop_name='Peine Freibad', longitude=10.223938, latitude=52.316184, n_nearests = 5)
        for stop_id in stop_ids:
            for neighbor_id in self._Graph_raw[stop_id].keys():
                assert(self._Graph_raw[stop_id][neighbor_id][0]['name'] == 'Neustadtmühlendamm')

    def test_node_from_gps_1(self):
        node_ids=nearest_from_gps(self._Graph_raw, longitude=10.223938, latitude=52.316184, n_nearests = 1)
        self.assertEqual(1, len(node_ids))
        self.assertEqual('busnow_Peine Freibad_0', node_ids[0])

    def test_node_from_gps_2_graph_vs_OSRM(self):
        # graph and OSRM devliver not the same Id
        lat = 52.316
        lon = 10.129
        node_ids=nearest_from_gps(self._Graph, longitude=lon, latitude=lat, n_nearests = 10)
        self.assertEqual('323200727', node_ids[0])

        node_id_osrm = OSRM(OSRM.getDefaultUrl_OSRM_Testserver()).nearest_osmids(lat,lon,10)
        self.assertEqual(960103702, node_id_osrm[0])        

    # Tests with impossible input
    def test_moby_start_and_end_time(self):
            """
            Add start and end time for moby
            """

            fleet = self._std_fleet_1()
            tour = self._std_tour_1(fleet)

            station1 = Station('323200732')
            station2 = Station('291520520')

            m1 = Moby(station1, station2, (504, 506), (600,605))
            with self.assertRaises(ValueError):
                tour.add_moby(m1)

    def test_bus_stop_on_wrong_edge_id(self):
            """
            Try adding a bus station on a nonexistant edge id
            """

            fleet = self._std_fleet_1()
            tour = self._std_tour_1(fleet)
            start_node = '358006731'
            end_node = '94535093'
            edge_id = 41960570
            fraction = 0.3
            with self.assertRaises(AssertionError):
                self._Graph_raw = self._maps.get_graph('Peine_2km')
                add_bus_stop(self._Graph_raw, 'haltestelle 1', start_node, end_node, edge_id, fraction)

    def test_bus_stop_on_nonexitant_edge(self):
            """
            Try adding a bus station on a nonexistant edge
            """

            fleet = self._std_fleet_1()
            tour = self._std_tour_1(fleet)
            start_node = '293399027'
            end_node = '94535093'
            edge_id = 31960570
            fraction = 0.3
            with self.assertRaises(KeyError):
                add_bus_stop(self._Graph_raw, 'haltestelle 1', start_node, end_node, edge_id, fraction)

    def test_more_mobies_than_capacity(self):
        """
        Add more mobies than capacity (10) to tour
        """
        fleet = self._std_fleet_1()
        tour = self._std_tour_1(fleet)

        station1 = Station('323200732')
        station2 = Station('291520520')

        m1 = Moby(station1, station2, None, (510, 520),MobyLoad(11,0))
        tour.add_moby(m1)
        t = tour.get_routes()
        assert{bool(t), False}

    def test_excluding_request_times(self):
        """
        Mobies request starting times and places wich rule each other out.
        """

        fleet = self._std_fleet_1()
        tour = self._std_tour_1(fleet)

        station1 = Station('323200732')
        station2 = Station('291521266')
        station3 = Station('291520520')
        station4 = Station('286042889')

        m1 = Moby(station1, station2, (506, 510), None, load=MobyLoad(2,0))
        m2 = Moby(station3, station4, (506, 510), None, load=MobyLoad(2,0))
        m3 = Moby(station2, station1, (506, 510), None, load=MobyLoad(2,0))
        m4 = Moby(station1, station2, (506, 510), None, load=MobyLoad(2,0))

        tour.add_mobies([m1,m2,m3, m4])
        t = tour.get_routes()
        assert{bool(t), False}

    def test_station_closing_time_impossible_request(self):
        fleet = self._std_fleet_1()
        tour = self._std_tour_1(fleet)
        adapt_window = True

        station1 = Station('323200732')
        station2 = Station('291520520')

        m1 = Moby(station1, station2, (410, 450), None)
        
        tour.add_station_closing_time(station1, [(0,500)])
        tour.add_moby(m1)
        ts = tour.get_routes()
        self.assertEqual(ts, {})

    def test_shortest_path(self):
        """
        test core algorithm for shortest path on graph
        """

        GraphMod = multi2single(self._Graph)

        distCheck = 4323.386
        duration_check = 5.271494
        nodes_check = "323200732,323200717,323200693,302116750,323200711,302116530,910775898,3326907447,93899696,910775921,3326907432,93899645,307464947,323200784,94535074,323200598,3338518857,94535093,3338518850,3338518849,287949923,291517129,291508428,291516385,287949926,291503858,289345362,291518712,289841988,291519739,59908328,289841977,291521266"

        # loop may be used for performance checks
        station1 = Station('323200732')
        station2 = Station('291521266')

        for iter in range(1):
            path = shortest_path_graph(GraphMod,station1, station2, 'dijkstra')

        self.assertEqual(distCheck, path.distance)
        self.assertAlmostEqual(duration_check, path.duration, 6)
        self.assertEqual(nodes_check, ','.join(map(str, path.nodes)))

        for iter in range(1):
            path = shortest_path_graph(GraphMod,station1, station2, 'astar')

        self.assertEqual(distCheck, path.distance)
        self.assertAlmostEqual(duration_check, path.duration, 6)
        self.assertEqual(nodes_check, ','.join(map(str, path.nodes)))

    def test_durations_matrix(self):
        station1 = Station(longitude=10.129, latitude=52.316, name='Station 1', node_id=1)
        station1.node_id = nearest_from_gps(self._Graph, longitude=station1.longitude, latitude=station1.latitude, n_nearests = 1)[0]    
       
        station2 = Station(longitude=10.229, latitude=52.321, name='Station 2', node_id=2)
        station2.node_id = nearest_from_gps(self._Graph, longitude=station2.longitude, latitude=station2.latitude, n_nearests = 1)[0]      

        station3 = Station(longitude=10.335, latitude=52.371, name='Station 3', node_id=3)
        station3.node_id = nearest_from_gps(self._Graph, longitude=station3.longitude, latitude=station3.latitude, n_nearests = 1)[0]      

        self.assertFalse(station1.node_id == station2.node_id)
        self.assertFalse(station1.node_id == station3.node_id)
        self.assertFalse(station2.node_id == station3.node_id)
        self.assertEqual('323200727', station1.node_id )
        self.assertEqual('305672776', station2.node_id )
        self.assertEqual('2462773288', station3.node_id )

        # durations matrix with OSRM
        listStations = ['Depot', station1, station2, station3]
        durations_dict_OSRM = durations_matrix_OSRM(tuple(listStations), OSRM.getDefaultUrl_OSRM_Testserver(), 1.0)        
                
        self.assertEqual(len(listStations), len(durations_dict_OSRM))        

        self.assertEqual(0, durations_dict_OSRM['Depot'][station1])
        self.assertEqual(0, durations_dict_OSRM['Depot'][station2])
        self.assertEqual(0, durations_dict_OSRM['Depot'][station3])
        self.assertEqual(0, durations_dict_OSRM['Depot']['Depot'])
        self.assertEqual(0, durations_dict_OSRM[station1]['Depot'])
        self.assertEqual(0, durations_dict_OSRM[station2]['Depot'])
        self.assertEqual(0, durations_dict_OSRM[station3]['Depot'])

        self.assertEqual(0, durations_dict_OSRM[station1][station1])
        self.assertAlmostEqual(13.54, durations_dict_OSRM[station1][station2], delta=0.1)
        self.assertAlmostEqual(33.10, durations_dict_OSRM[station1][station3], delta=0.1)

        self.assertAlmostEqual(13.41, durations_dict_OSRM[station2][station1], delta=0.1)
        self.assertEqual(0, durations_dict_OSRM[station2][station2])
        self.assertAlmostEqual(24.03, durations_dict_OSRM[station2][station3], delta=0.1)

        self.assertAlmostEqual(32.97, durations_dict_OSRM[station3][station1], delta=0.1)
        self.assertAlmostEqual(24.24, durations_dict_OSRM[station3][station2], delta=0.1)
        self.assertEqual(0, durations_dict_OSRM[station3][station3], 2)

        # durations matrix with graph - absolute values of course differ from OSRM but relative duration should be somehow comparable
        durations_dict_graph = durations_matrix_graph(tuple(listStations), multi2single(self._Graph), 1.0, {})
        self.assertEqual(len(listStations), len(durations_dict_graph))

        self.assertEqual(0, durations_dict_graph['Depot'][station1])
        self.assertEqual(0, durations_dict_graph['Depot'][station2])
        self.assertEqual(0, durations_dict_graph['Depot'][station3])
        self.assertEqual(0, durations_dict_graph['Depot']['Depot'])
        self.assertEqual(0, durations_dict_graph[station1]['Depot'])
        self.assertEqual(0, durations_dict_graph[station2]['Depot'])
        self.assertEqual(0, durations_dict_graph[station3]['Depot'])

        self.assertEqual(0, durations_dict_graph[station1][station1])
        self.assertAlmostEqual(3.06, durations_dict_graph[station1][station2], 2)
        self.assertAlmostEqual(6.11, durations_dict_graph[station1][station3], 2)

        self.assertAlmostEqual(3.06, durations_dict_graph[station2][station1], 2)
        self.assertEqual(0, durations_dict_graph[station2][station2])
        self.assertAlmostEqual(5.47, durations_dict_graph[station2][station3], 2)

        self.assertAlmostEqual(5.744, durations_dict_graph[station3][station1], 2)
        self.assertAlmostEqual(5.53, durations_dict_graph[station3][station2], 2)
        self.assertEqual(0, durations_dict_graph[station3][station3], 2)

    def test_durations_matrix_with_time_factor(self):
        station1 = Station(longitude=10.129, latitude=52.316, name='Station 1', node_id=1)
        station1.node_id = nearest_from_gps(self._Graph, longitude=station1.longitude, latitude=station1.latitude, n_nearests = 1)[0]    
       
        station2 = Station(longitude=10.229, latitude=52.321, name='Station 2', node_id=2)
        station2.node_id = nearest_from_gps(self._Graph, longitude=station2.longitude, latitude=station2.latitude, n_nearests = 1)[0]      

        station3 = Station(longitude=10.335, latitude=52.371, name='Station 3', node_id=3)
        station3.node_id = nearest_from_gps(self._Graph, longitude=station3.longitude, latitude=station3.latitude, n_nearests = 1)[0]      

        self.assertFalse(station1.node_id == station2.node_id)
        self.assertFalse(station1.node_id == station3.node_id)
        self.assertFalse(station2.node_id == station3.node_id)
        self.assertEqual('323200727', station1.node_id )
        self.assertEqual('305672776', station2.node_id )
        self.assertEqual('2462773288', station3.node_id )

        # durations matrix with OSRM
        listStations = ['Depot', station1, station2, station3]
        time_factor = 1.15
        durations_dict_OSRM = durations_matrix_OSRM(tuple(listStations), OSRM.getDefaultUrl_OSRM_Testserver(), time_factor)        
                
        self.assertEqual(len(listStations), len(durations_dict_OSRM))        

        self.assertEqual(0, durations_dict_OSRM['Depot'][station1])
        self.assertEqual(0, durations_dict_OSRM['Depot'][station2])
        self.assertEqual(0, durations_dict_OSRM['Depot'][station3])
        self.assertEqual(0, durations_dict_OSRM['Depot']['Depot'])
        self.assertEqual(0, durations_dict_OSRM[station1]['Depot'])
        self.assertEqual(0, durations_dict_OSRM[station2]['Depot'])
        self.assertEqual(0, durations_dict_OSRM[station3]['Depot'])

        self.assertEqual(0, durations_dict_OSRM[station1][station1])
        self.assertAlmostEqual(time_factor*13.54, durations_dict_OSRM[station1][station2], delta=0.2)
        self.assertAlmostEqual(time_factor*33.10, durations_dict_OSRM[station1][station3], delta=0.2)

        self.assertAlmostEqual(time_factor*13.41, durations_dict_OSRM[station2][station1],  delta=0.2)
        self.assertEqual(0, durations_dict_OSRM[station2][station2])
        self.assertAlmostEqual(time_factor*24.03, durations_dict_OSRM[station2][station3], delta=0.2)

        self.assertAlmostEqual(time_factor*32.97, durations_dict_OSRM[station3][station1], delta=0.2)
        self.assertAlmostEqual(time_factor*24.24, durations_dict_OSRM[station3][station2], delta=0.2)
        self.assertEqual(0, durations_dict_OSRM[station3][station3], 2)

        # durations matrix with graph - absolute values of course differ from OSRM but relative duration should be somehow comparable
        durations_dict_graph = durations_matrix_graph(tuple(listStations), multi2single(self._Graph),time_factor, {})
        self.assertEqual(len(listStations), len(durations_dict_graph))

        self.assertEqual(0, durations_dict_graph['Depot'][station1])
        self.assertEqual(0, durations_dict_graph['Depot'][station2])
        self.assertEqual(0, durations_dict_graph['Depot'][station3])
        self.assertEqual(0, durations_dict_graph['Depot']['Depot'])
        self.assertEqual(0, durations_dict_graph[station1]['Depot'])
        self.assertEqual(0, durations_dict_graph[station2]['Depot'])
        self.assertEqual(0, durations_dict_graph[station3]['Depot'])

        self.assertEqual(0, durations_dict_graph[station1][station1])
        self.assertAlmostEqual(time_factor*3.06, durations_dict_graph[station1][station2], 2)
        self.assertAlmostEqual(time_factor*6.11, durations_dict_graph[station1][station3], 2)

        self.assertAlmostEqual(time_factor*3.06, durations_dict_graph[station2][station1], 2)
        self.assertEqual(0, durations_dict_graph[station2][station2])
        self.assertAlmostEqual(time_factor*5.47, durations_dict_graph[station2][station3], 2)

        self.assertAlmostEqual(time_factor*5.744, durations_dict_graph[station3][station1], 2)
        self.assertAlmostEqual(time_factor*5.53, durations_dict_graph[station3][station2], 2)
        self.assertEqual(0, durations_dict_graph[station3][station3], 2)

    def test_adjust_time_window_for_connecting_times(self):

        s1 = Station(longitude=12.813409859560808, latitude=50.630280000496136,\
            name = "Markt", node_id=1)
        s2 = Station(longitude=12.7983, latitude=50.6322,\
            name = "Bahnhof", node_id=2)

        fleet = self._std_fleet_2c_wheelchair()
        tour = self._std_tour_1_maps_Zwoenitz(fleet)

        # no connection in this time
        timeWindow = (20,30)
        timeWindowResult, connection = tour.adjust_time_window_for_connecting_times(timeWindow, s2, True)
        self.assertEqual(timeWindowResult[0], timeWindow[0])
        self.assertEqual(timeWindowResult[1], timeWindow[1])
        self.assertFalse(connection)

        # connection in this time at this station with change of time window - for departure
        timeWindow = (656,664)
        timeWindowResult, connection = tour.adjust_time_window_for_connecting_times(timeWindow, s2, True)
        self.assertEqual(timeWindowResult[0], 659)
        self.assertEqual(timeWindowResult[1], timeWindow[1])
        self.assertTrue(connection)

        # but no connection in this time at the other station
        timeWindow = (656,664)
        timeWindowResult, connection = tour.adjust_time_window_for_connecting_times(timeWindow, s1, True)
        self.assertEqual(timeWindowResult[0], timeWindow[0])
        self.assertEqual(timeWindowResult[1], timeWindow[1])
        self.assertFalse(connection)

        # connection detected if window is not changed
        timeWindow = (659,664)
        timeWindowResult, connection = tour.adjust_time_window_for_connecting_times(timeWindow, s2, True)
        self.assertEqual(timeWindowResult[0], timeWindow[0])
        self.assertEqual(timeWindowResult[1], timeWindow[1])
        self.assertTrue(connection)

        # no connection detected if arrival
        timeWindow = (659,664)
        timeWindowResult, connection = tour.adjust_time_window_for_connecting_times(timeWindow, s2, False)
        self.assertEqual(timeWindowResult[0], timeWindow[0])
        self.assertEqual(timeWindowResult[1], timeWindow[1])
        self.assertFalse(connection)

        # now connection detected with change of time window if arrival
        timeWindow = (50,56)
        timeWindowResult, connection = tour.adjust_time_window_for_connecting_times(timeWindow, s2, False)
        self.assertEqual(timeWindowResult[0], timeWindow[0])
        self.assertEqual(timeWindowResult[1], 55)
        self.assertTrue(connection)

        # connection in this time but intervall too small for adjusting
        timeWindow = (55,58)
        timeWindowResult, connection = tour.adjust_time_window_for_connecting_times(timeWindow, s2, False)
        self.assertEqual(timeWindowResult[0], timeWindow[0])
        self.assertEqual(timeWindowResult[1], timeWindow[1])
        self.assertFalse(connection)

        # large time interval with multiple connections - no connection assumed
        timeWindow = (650,870)
        timeWindowResult, connection = tour.adjust_time_window_for_connecting_times(timeWindow, s2, True)
        self.assertEqual(timeWindowResult[0], timeWindow[0])
        self.assertEqual(timeWindowResult[1], timeWindow[1])
        self.assertFalse(connection)

        # large time interval with multiple connections - no connection assumed
        timeWindow = (650,870)
        timeWindowResult, connection = tour.adjust_time_window_for_connecting_times(timeWindow, s2, False)
        self.assertEqual(timeWindowResult[0], timeWindow[0])
        self.assertEqual(timeWindowResult[1], timeWindow[1])
        self.assertFalse(connection)

    def test_new_routing_improve_pooling_by_stepwise_increasing_slack(self):

        s1 = Station(longitude=12.8075643236188, latitude=50.6323489794738,\
            name = "Schillerstrasse", node_id=0)
        s1.node_id = nearest_from_gps(self._Graph_Zwoenitz, longitude=s1.longitude, latitude=s1.latitude, n_nearests = 1)[0]    

        s2 = Station(longitude=12.7983, latitude=50.6322,\
            name = "Kuehnhaide Wendeschleife", node_id=0)
        s2.node_id = nearest_from_gps(self._Graph_Zwoenitz, longitude=s2.longitude, latitude=s2.latitude, n_nearests = 1)[0]  

        s3 = Station(longitude=12.797741, latitude=50.611254,\
            name = "Markt", node_id=0)
        s3.node_id = nearest_from_gps(self._Graph_Zwoenitz, longitude=s3.longitude, latitude=s3.latitude, n_nearests = 1)[0] 

        s4 = Station(longitude=12.7983, latitude=50.6322,\
            name = "Bahnhof", node_id=0)
        s4.node_id = nearest_from_gps(self._Graph_Zwoenitz, longitude=s4.longitude, latitude=s4.latitude, n_nearests = 1)[0]  

        m1 = Moby(s1, s2, (620, 623), (628,631))
        m2 = Moby(s3, s4, (595, 605), None)

        promise_mobies: dict[int, Moby] = {}
        promise_mobies[1]=m1

        mandatory_stations= []

        fleet = self._std_fleet_2c_wheelchair()

        options = {'slack': 30, 'time_offset_factor': 1.15, 'time_service_per_wheelchair' : 3}
        solution = new_routing(self._Graph_Zwoenitz, None, m2, promise_mobies, mandatory_stations, fleet, options)

        self.assertIsNotNone(solution)
        routes = solution[1]

        #print(routes)

        # check route
        self.assertEqual(len(routes), len(fleet))
        subroute1 = routes[0]        
        self.assertEqual(len(subroute1), 176) 

        # bus route should be: moby m2 delivered first; then m1, should not mix m2 around m1
        nodeDepotStart=subroute1[0]
        self.assertEqual(nodeDepotStart.map_id, 'Depot')
        nodeStation1=subroute1[1]
        self.assertEqual(nodeStation1.map_id, s3.node_id)
        self.assertEqual(nodeStation1.time_min, 595)
        self.assertEqual(nodeStation1.time_max, 598)
        self.assertEqual(str(nodeStation1.hop_on), str(m2))
        nodeStation2=subroute1[114]
        self.assertEqual(nodeStation2.map_id, s4.node_id)
        self.assertEqual(nodeStation2.time_min, 601)
        self.assertEqual(nodeStation2.time_max, 604)
        self.assertEqual(str(nodeStation2.hop_off), str(m2))
        nodeStation3=subroute1[144]
        self.assertEqual(nodeStation3.map_id, s1.node_id)
        self.assertEqual(nodeStation3.time_min, 620)
        self.assertEqual(nodeStation3.time_max, 623)
        self.assertEqual(str(nodeStation3.hop_on), str(m1))
        nodeStation4=subroute1[174]
        self.assertEqual(nodeStation4.map_id, s2.node_id)
        self.assertEqual(nodeStation4.time_min, 628)
        self.assertEqual(nodeStation4.time_max, 631)
        self.assertEqual(str(nodeStation4.hop_off), str(m1))
        nodeDepotEnd=subroute1[175]
        self.assertEqual(nodeDepotEnd.map_id, 'Depot')

    def test_new_routing_stepwise_increasing_slack_must_have_valid_time_windows(self):       
        # during slack iteration time windows were manipulated which is not allowed

        s1 = Station(longitude=12.8075643236188, latitude=50.6323489794738,\
            name = "Schillerstrasse", node_id=0)
        s1.node_id = nearest_from_gps(self._Graph_Zwoenitz, longitude=s1.longitude, latitude=s1.latitude, n_nearests = 1)[0]    

        s2 = Station(longitude=12.7983, latitude=50.6322,\
            name = "Kuehnhaide Wendeschleife", node_id=0)
        s2.node_id = nearest_from_gps(self._Graph_Zwoenitz, longitude=s2.longitude, latitude=s2.latitude, n_nearests = 1)[0]  

        s3 = Station(longitude=12.797741, latitude=50.611254,\
            name = "Markt", node_id=0)
        s3.node_id = nearest_from_gps(self._Graph_Zwoenitz, longitude=s3.longitude, latitude=s3.latitude, n_nearests = 1)[0] 

        s4 = Station(longitude=12.7983, latitude=50.6322,\
            name = "Bahnhof", node_id=0)
        s4.node_id = nearest_from_gps(self._Graph_Zwoenitz, longitude=s4.longitude, latitude=s4.latitude, n_nearests = 1)[0]  

        # we try to enforce following situation: order not possible (here: exceeding capa), which can only be detected by optimizer, thus slack iteration is done     

        
        m1 = Moby(s3, s2, (595, 605), (628,631))
        m2 = Moby(s3, s4, (595, 605), None, MobyLoad(3,1)) 

        promise_mobies: dict[int, Moby] = {}
        promise_mobies[1]=m1

        mandatory_stations= []

        fleet = self._std_fleet_2c_wheelchair()

        options = {'slack': 30, 'time_offset_factor': 1.15, 'time_service_per_wheelchair' : 3}
        
        solution = new_routing(self._Graph_Zwoenitz, None, m2, promise_mobies, mandatory_stations, fleet, options)

        # no solution in this case - we wanted to test the slack iteration in new_request
        self.assertIsNone(solution)

    def test_new_routing_improve_routing_for_arrival_fixed(self):
       
        s1 = Station(longitude=12.797741, latitude=50.611254,\
            name = "Markt", node_id=0)
        s1.node_id = nearest_from_gps(self._Graph_Zwoenitz, longitude=s1.longitude, latitude=s1.latitude, n_nearests = 1)[0] 

        s2 = Station(longitude=12.7983, latitude=50.6322,\
            name = "Bahnhof", node_id=0)
        s2.node_id = nearest_from_gps(self._Graph_Zwoenitz, longitude=s2.longitude, latitude=s2.latitude, n_nearests = 1)[0]  

        m1 = Moby(s1, s2, None, (600,610))

        promise_mobies: dict[int, Moby] = {}        

        mandatory_stations= []

        fleet = self._std_fleet_2c_wheelchair()

        options = {'slack': 30, 'time_offset_factor': 1.15, 'time_service_per_wheelchair' : 3}
        solution = new_routing(self._Graph_Zwoenitz, None, m1, promise_mobies, mandatory_stations, fleet, options)

        self.assertIsNotNone(solution)
        routes = solution[1]

        #print(routes)

        # check route
        self.assertEqual(len(routes), len(fleet))
        subroute1 = routes[0]        
        self.assertEqual(len(subroute1), 116) 

        # bus route should be: not too much waiting time for fixed arrival
        nodeDepotStart=subroute1[0]
        self.assertEqual(nodeDepotStart.map_id, 'Depot')
        nodeStation1=subroute1[1]
        self.assertEqual(nodeStation1.map_id, s1.node_id)
        self.assertEqual(nodeStation1.time_min, 594)
        self.assertEqual(nodeStation1.time_max, 597)
        self.assertEqual(str(nodeStation1.hop_on), str(m1))        
        nodeStation4=subroute1[114]
        self.assertEqual(nodeStation4.map_id, s2.node_id)
        self.assertEqual(nodeStation4.time_min, 600)
        self.assertEqual(nodeStation4.time_max, 603)
        self.assertEqual(str(nodeStation4.hop_off), str(m1))
        nodeDepotEnd=subroute1[115]
        self.assertEqual(nodeDepotEnd.map_id, 'Depot')

    def test_new_routing_long_calc_time(self):
        
        s1 = Station(longitude=12.816144882878351, latitude=50.685605366187545,\
            name = "Bruenlos Gemeindeverwaltung", node_id=0)
        s1.node_id = nearest_from_gps(self._Graph_Zwoenitz, longitude=s1.longitude, latitude=s1.latitude, n_nearests = 1)[0] 

        s2 = Station(longitude=12.7983, latitude=50.6322,\
            name = "Kuehnhaide Wendeschleife", node_id=0)
        s2.node_id = nearest_from_gps(self._Graph_Zwoenitz, longitude=s2.longitude, latitude=s2.latitude, n_nearests = 1)[0] 

        s3 = Station(longitude=12.820999720423973, latitude=50.684964996209125,\
            name = "Bruenlos Am Tampel", node_id=0)
        s3.node_id = nearest_from_gps(self._Graph_Zwoenitz, longitude=s3.longitude, latitude=s3.latitude, n_nearests = 1)[0] 
        
        # optimize performance by ignoring build paths (e.g. if only checking for existing solution within is_bookable)
        options = {'slack': 30, 'time_offset_factor': 1.15, 'time_service_per_wheelchair' : 3, 'build_paths' : False}
        mandatory_stations= []
        fleet = self._std_fleet_2c_wheelchair()
        promise_mobies: dict[int, Moby] = {} 

        # long route: slow
        timeStarted = time.time()

        apriori_times_matrix = {}

        for step in range(0,5):
            #print(step)
            m1 = Moby(s1, s2, (600,610), None, MobyLoad(1,0))
            solution = new_routing(self._Graph_Zwoenitz, None, m1, promise_mobies, mandatory_stations, fleet, options, apriori_times_matrix)
            self.assertIsNotNone(solution)

        self.assertEqual("{'708549125': {'708549125': None, '313187588': 9.297745695714282}, '313187588': {'708549125': 9.319514012857146, '313187588': None}}", str(apriori_times_matrix))

        timeElapsed1 = time.time() - timeStarted
        timeStarted = time.time()

        # short route: fast
        for step in range(0,5):
            #print(step)
            m1 = Moby(s1, s3, (600,610), None, MobyLoad(1,0))
            solution = new_routing(self._Graph_Zwoenitz, None, m1, promise_mobies, mandatory_stations, fleet, options, apriori_times_matrix)
            self.assertIsNotNone(solution)
        
        timeElapsed2 = time.time() - timeStarted
        self.assertEqual("{'708549125': {'708549125': None, '313187588': 9.297745695714282, '1103189775': 0.49140695999999995}, '313187588': {'708549125': 9.319514012857146, '313187588': None}, '1103189775': {'708549125': 0.49140695999999995, '1103189775': None}}", str(apriori_times_matrix))

        # print(timeElapsed1)
        # print(timeElapsed2)

        self.assertGreater(0.25*timeElapsed1, timeElapsed2)     
        self.assertGreater(0.03, timeElapsed2)     
        self.assertGreater(0.2, timeElapsed1)     
            

    def test_calc_shortest_path_gps(self):
        
        s1 = Station(longitude=12.8075643236188, latitude=50.6323489794738, name = "Schillerstrasse", node_id=0)
        s1.node_id = nearest_from_gps(self._Graph_Zwoenitz, longitude=s1.longitude, latitude=s1.latitude, n_nearests = 1)[0]    

        s2 = Station(longitude=12.7983, latitude=50.6322, name = "Kuehnhaide Wendeschleife", node_id=0)
        s2.node_id = nearest_from_gps(self._Graph_Zwoenitz, longitude=s2.longitude, latitude=s2.latitude, n_nearests = 1)[0]  

        s3 = Station(longitude=12.797741, latitude=50.611254, name = "Markt", node_id=0)
        s3.node_id = nearest_from_gps(self._Graph_Zwoenitz, longitude=s3.longitude, latitude=s3.latitude, n_nearests = 1)[0] 

        s4 = Station(longitude=12.7983, latitude=50.6322, name = "Bahnhof", node_id=0)
        s4.node_id = nearest_from_gps(self._Graph_Zwoenitz, longitude=s4.longitude, latitude=s4.latitude, n_nearests = 1)[0] 

        fleet = self._std_fleet_2c_wheelchair()
        tour = self._std_tour_1_maps_Zwoenitz(fleet)

        stations = [s1, s2, s3, s4]

        # timeStarted = time.time()
        # for i in range(0,10):

        result = tour.calc_shortest_path_gps(stations)

        # timeElapsed = time.time() - timeStarted
        # print('Time consumed')
        # print(timeElapsed)

        self.assertEqual(len(stations)-1, len(result))
        numPath1 = len(result[0])
        self.assertEqual(31, numPath1)
        self.assertAlmostEqual(s1.longitude, result[0][0][1], places=3)    
        self.assertAlmostEqual(s1.latitude, result[0][0][0], places=3)        
        self.assertAlmostEqual(s2.longitude, result[0][numPath1-1][1], places=3)        
        self.assertAlmostEqual(s2.latitude, result[0][numPath1-1][0], places=3)     

        numPath2 = len(result[1])
        self.assertEqual(114, numPath2)
        self.assertAlmostEqual(s2.longitude, result[1][0][1], places=3)       
        self.assertAlmostEqual(s2.latitude, result[1][0][0], places=3)       
        self.assertAlmostEqual(s3.longitude, result[1][numPath2-1][1], places=3)       
        self.assertAlmostEqual(s3.latitude, result[1][numPath2-1][0], places=3)      

        numPath3 = len(result[2])
        self.assertEqual(114, numPath3)
        self.assertAlmostEqual(s3.longitude, result[2][0][1], places=3)       
        self.assertAlmostEqual(s3.latitude, result[2][0][0], places=3)       
        self.assertAlmostEqual(s4.longitude, result[2][numPath3-1][1], places=3)       
        self.assertAlmostEqual(s4.latitude, result[2][numPath3-1][0], places=3)  

    def test_add_detours_from_gps(self):
        latlonlist = []
        detours_around_in_metres = []

        # detour close to Zwoenitzer Strasse, number 38
        latlonlist.append((50.66270542, 12.83489914)) # alternative can be easily found
        detours_around_in_metres.append(0)
        latlonlist.append((50.66863, 12.87566)) # additional detours for harder alternative routing        
        detours_around_in_metres.append(75)

        # insert detour in graph
        graphZwoenitz = deepcopy(self._Graph_Zwoenitz_raw)
        result_detour, distances_detour = add_detours_from_gps(graphZwoenitz, latlonlist, detours_around_in_metres)
        start_node, end_node = result_detour[0][0]
        self.assertEqual(start_node, '736952428')
        self.assertEqual(end_node, '29830803')

        self.assertEqual(len(result_detour[1]),6)
        start_node2, end_node2 = result_detour[1][0]  
        self.assertEqual(start_node2, '1260696312')
        self.assertEqual(end_node2, '100320883')  
        start_node3, end_node3 = result_detour[1][1]  
        self.assertEqual(start_node3, '100320882')
        self.assertEqual(end_node3, '100320881') 

        data = graphZwoenitz.get_edge_data(start_node, end_node)
        self.assertEqual(data[0]['maxspeed'], '0')
        data = graphZwoenitz.get_edge_data(start_node2, end_node2)
        self.assertEqual(data[0]['maxspeed'], '0')     
        data = graphZwoenitz.get_edge_data(start_node3, end_node3)
        self.assertEqual(data[0]['maxspeed'], '0')     

        self.assertAlmostEqual(distances_detour[0], 0.8701, 3)     
        self.assertAlmostEqual(distances_detour[1], 7.4436, 3)   

        graph_with_detour = multi2single(graphZwoenitz)

        #print(data)

        # create routing that must be affected by detour
        s1 = Station(longitude=12.797741, latitude=50.611254,\
            name = "Markt", node_id=0)
        s1.node_id = nearest_from_gps(graph_with_detour, longitude=s1.longitude, latitude=s1.latitude, n_nearests = 1)[0] 

        s2 = Station(longitude=12.8824333561927, latitude=50.670810353453255,\
            name = "Hormersdorf", node_id=0)
        s2.node_id = nearest_from_gps(graph_with_detour, longitude=s2.longitude, latitude=s2.latitude, n_nearests = 1)[0]  

        m1 = Moby(s1, s2, None, (600,610))

        promise_mobies: dict[int, Moby] = {}        

        mandatory_stations= []

        fleet = self._std_fleet_2c_wheelchair()

        options = {'slack': 30, 'time_offset_factor': 1.15, 'time_service_per_wheelchair' : 3}
        solution = new_routing(graph_with_detour, None, m1, promise_mobies, mandatory_stations, fleet, options)

        self.assertIsNotNone(solution)
        routes = solution[1]

        #print(routes)

        # check route
        self.assertEqual(len(routes), len(fleet))
        subroute1 = routes[0]        
        self.assertEqual(len(subroute1), 507) 

        # bus route should be longer than without detour, time diff about 7 mins
        nodeDepotStart=subroute1[0]
        self.assertEqual(nodeDepotStart.map_id, 'Depot')
        nodeStation1=subroute1[1]
        self.assertEqual(nodeStation1.map_id, s1.node_id)
        self.assertEqual(nodeStation1.time_min, 577)
        self.assertEqual(nodeStation1.time_max, 580)
        self.assertEqual(str(nodeStation1.hop_on), str(m1))        
        nodeStation4=subroute1[505]
        self.assertEqual(nodeStation4.map_id, s2.node_id)
        self.assertEqual(nodeStation4.time_min, 600)
        self.assertEqual(nodeStation4.time_max, 603)
        self.assertEqual(str(nodeStation4.hop_off), str(m1))
        nodeDepotEnd=subroute1[506]
        self.assertEqual(nodeDepotEnd.map_id, 'Depot')

        # reset max speed at segment        
        graphZwoenitz[start_node][end_node][0]['maxspeed'] = '50'
        data = graphZwoenitz.get_edge_data(start_node, end_node)
        self.assertEqual(data[0]['maxspeed'], '50')

        # routing must be faster now
        m2 = Moby(s1, s2, None, (500,510))
        solution = new_routing(self._Graph_Zwoenitz, None, m2, promise_mobies, mandatory_stations, fleet, options, {})

        self.assertIsNotNone(solution)
        routes = solution[1]

        #print(routes)

        # check route
        self.assertEqual(len(routes), len(fleet))
        subroute1 = routes[0]        
        self.assertEqual(len(subroute1), 374) 

        # bus route should be longer than without detour, time diff about 7 mins
        nodeDepotStart=subroute1[0]
        self.assertEqual(nodeDepotStart.map_id, 'Depot')
        nodeStation1=subroute1[1]
        self.assertEqual(nodeStation1.map_id, s1.node_id)
        self.assertEqual(nodeStation1.time_min, 484)
        self.assertEqual(nodeStation1.time_max, 487)
        self.assertEqual(str(nodeStation1.hop_on), str(m2))        
        nodeStation4=subroute1[372]
        self.assertEqual(nodeStation4.map_id, s2.node_id)
        self.assertEqual(nodeStation4.time_min, 500)
        self.assertEqual(nodeStation4.time_max, 503)
        self.assertEqual(str(nodeStation4.hop_off), str(m2))
        nodeDepotEnd=subroute1[373]
        self.assertEqual(nodeDepotEnd.map_id, 'Depot')
    
    def test_dist_of_point_to_edge_2d(self):
        
        result = dist_of_point_to_edge_2d((10,10), (15,10), (15,10))
        self.assertEqual(0, result)

        result = dist_of_point_to_edge_2d((10,10), (15,10), (12,15))
        self.assertEqual(5, result)

        # degenerated edge, situation may happen!
        result = dist_of_point_to_edge_2d((10,10), (10,10), (15,10))
        self.assertEqual(5, result)

    # test to investigate Joerg's problem with road closures
    # GPS coordinates of the suggested route (affected by detour) 
    # is also calculated here for visualization purposes
    def test_add_detours_from_gps_2(self):

        latlonlist = []
        detours_around_in_metres = []

        # in der nähe von Dorfchemnitz Ortseingang 39
        latlonlist.append((50.65421814384453,12.828104827933146))
        detours_around_in_metres.append(10)
        # in der nähe von Günsdorf (ab Dorfchemnitz) 37
        latlonlist.append((50.66750860061592, 12.841030820818219))
        detours_around_in_metres.append(10)
        # in der nähe von Dorfchemnitz Hauptstr. 40
        latlonlist.append((50.66807675717209, 12.837831558420277))
        detours_around_in_metres.append(10)
        # in der nähe von Dorfchemnitz Zwönitz 41
        latlonlist.append((50.662867529598856, 12.834976208637755))
        detours_around_in_metres.append(10)
        # in der nähe von Dorfchemnitz Querstrasse 42
        latlonlist.append((50.65883564206706, 12.833105047712735))
        detours_around_in_metres.append(10)

        graphZwoenitz = deepcopy(self._Graph_Zwoenitz_raw)
        result_detour, distances_detour = add_detours_from_gps(graphZwoenitz, latlonlist, detours_around_in_metres)
        # print(f"result_detour:\n{result_detour}")
        start_node, end_node = result_detour[0][0]

        data = graphZwoenitz.get_edge_data(start_node, end_node)
        self.assertEqual(data[0]['maxspeed'], '0')

        graph_with_detour = multi2single(graphZwoenitz)

        s1 = Station(longitude=12.8161687, latitude=50.6308424, \
            name = "Zwoenitz, Markt", node_id=0)
        s1.node_id = nearest_from_gps(self._Graph_Zwoenitz, longitude=s1.longitude, latitude=s1.latitude, n_nearests = 1)[0]

        s2 = Station(longitude=12.855937, latitude=50.6671462, \
            name = "Guensdorf, Wartehalle", node_id=0)
        s2.node_id = nearest_from_gps(self._Graph_Zwoenitz, longitude=s2.longitude, latitude=s2.latitude, n_nearests = 1)[0]

        stations = [s2,s1]

        # Günsdorf - Zwönitz
        m1 = Moby(s2, s1, None, (600,610))

        promise_mobies: dict[int, Moby] = {}        

        mandatory_stations= []

        fleet = self._std_fleet_2c_wheelchair()
        options = {'slack': 30, 'time_offset_factor': 1.15, 'time_service_per_wheelchair' : 3}
        tour_with_detour = BusTour(graph_with_detour, None, fleet, 1.15, 3.0, 30)

        # options = {'slack': 30, 'time_offset_factor': 1.15, 'time_service_per_wheelchair' : 3}
        solution = new_routing(graph_with_detour, None, m1, promise_mobies, mandatory_stations, fleet, options)

        self.assertIsNotNone(solution)
        routes = solution[1]

        # print("################### with detour ###################")
        # check route
        self.assertEqual(len(routes), len(fleet))
        subroute1 = routes[0]
        # print(f"len(subroute1): {len(subroute1)}")
        self.assertEqual(len(subroute1), 456) 

        # bus route should be longer than without detour
        nodeDepotStart=subroute1[0]
        self.assertEqual(nodeDepotStart.map_id, 'Depot')
        nodeStation1=subroute1[1]
        # print(f"nodeStation1.time_min: {nodeStation1.time_min}")
        # print(f"nodeStation1.time_max: {nodeStation1.time_max}")
        self.assertEqual(nodeStation1.time_min, 578)
        self.assertEqual(nodeStation1.time_max, 581)
        self.assertEqual(str(nodeStation1.hop_on), str(m1)) 
        nodeStation2=subroute1[-2]
        # print(f"nodeStation2.time_min: {nodeStation2.time_min}")
        # print(f"nodeStation2.time_max: {nodeStation2.time_max}")
        self.assertEqual(nodeStation2.time_min, 600)
        self.assertEqual(nodeStation2.time_max, 603)
        self.assertEqual(str(nodeStation2.hop_off), str(m1))
        nodeDepotEnd=subroute1[-1]
        self.assertEqual(nodeDepotEnd.map_id, 'Depot')

        total_time_with_detour = nodeStation2.time_max - nodeStation1.time_max
        # print(f"total time (with detour): {total_time_with_detour}")

        result_detour = tour_with_detour.calc_shortest_path_gps(stations)
        # print(f"gps_coordinates for the detour:\n{result_detour}")

        # reset max speed at segment        
        graphZwoenitz[start_node][end_node][0]['maxspeed'] = '50'
        data = graphZwoenitz.get_edge_data(start_node, end_node)
        self.assertEqual(data[0]['maxspeed'], '50')

        # print("################### without detour ###################")

        tour_without_detour = BusTour(self._Graph_Zwoenitz, None, fleet, 1.15, 3.0, 30)


        # routing must be faster now
        m2 = Moby(s1, s2, None, (500,510))
        solution = new_routing(self._Graph_Zwoenitz, None, m2, promise_mobies, mandatory_stations, fleet, options, {})



        self.assertIsNotNone(solution)
        routes = solution[1]

        # check route
        self.assertEqual(len(routes), len(fleet))
        subroute1 = routes[0]
        # print(f"len(subroute1): {len(subroute1)}")
        # self.assertEqual(len(subroute1), 233) 


        # bus route should be shorter without detour
        nodeDepotStart=subroute1[0]
        self.assertEqual(nodeDepotStart.map_id, 'Depot')
        nodeStation1=subroute1[1]
        # print(f"nodeStation1.time_min: {nodeStation1.time_min}")
        # print(f"nodeStation1.time_max: {nodeStation1.time_max}")
        self.assertEqual(nodeStation1.time_min, 490)
        self.assertEqual(nodeStation1.time_max, 493)
        self.assertEqual(str(nodeStation1.hop_on), str(m2)) 
        nodeStation2=subroute1[231]
        # print(f"nodeStation2.time_min: {nodeStation2.time_min}")
        # print(f"nodeStation2.time_max: {nodeStation2.time_max}")
        self.assertEqual(nodeStation2.time_min, 500)
        self.assertEqual(nodeStation2.time_max, 503)
        self.assertEqual(str(nodeStation2.hop_off), str(m2))
        nodeDepotEnd=subroute1[232]
        self.assertEqual(nodeDepotEnd.map_id, 'Depot')

        total_time_without_detour = nodeStation2.time_max - nodeStation1.time_max

        self.assertGreater(total_time_with_detour, total_time_without_detour)
        # print(f"total time (without detour): {total_time_without_detour}")

        result_tour = tour_without_detour.calc_shortest_path_gps(stations)
        # print(f"gps_coordinates for the normal tour:\n{result_tour}")

        gps_coords = []
        gps_coords.append(result_detour)
        gps_coords.append(result_tour)

        # print(gps_coords)
        # print(f"latlonlist: {latlonlist}")




class BusTourTest_OSRM(TestCase):
    def setUp(self):
        self.OSRM_test_url = OSRM.getDefaultUrl_OSRM_Testserver()  
        self.OSRM_iav_url = OSRM.getDefaultUrl_Testserver()   

    def shortDescription(self): # turn off printing docstring in tests
        return None     

    def test_example_by_OSRM(self):
        """
        Example to try OSRM routing
        """
        timeStarted = time.time()

        s1 = Station(longitude=13.301210690450006, latitude=52.53004035573715,\
            name = "S Jungfernheide Bhf", node_id=1)
        s2 = Station(longitude=13.328485707361551, latitude=52.53425245466951,\
            name = "S Beusselstraße", node_id=2)
        s3 = Station(longitude=13.343616529440226, latitude=52.53615566398298,\
            name = "S Westhafen", node_id=3)
        s4 = Station(longitude=13.366369651048444, latitude=52.54248572379109,\
            name = "S Wedding", node_id=4)

        m1 = Moby(s1, s3, None, (0, 60))
        m2 = Moby(s1, s4, None, (70, 120))
        m3 = Moby(s2, s3, (5, 10), None)
        m4 = Moby(s4, s2, (7,15), None, load=MobyLoad(3,0))

        busses = [Vehicle(capacity=VehicleCapacity(4,0), work_time= (0, 100)),
                Vehicle(capacity=VehicleCapacity(4,0), work_time= (70, 200)),
                Vehicle(capacity=VehicleCapacity(4,0), work_time= (-300000, 800000))]
        tour = BusTour(None, self.OSRM_test_url, slack=10, capacities=busses, time_offset_factor=1.0, time_per_demand_unit_wheelchair=3.0)

        # check data an compare with former results
        print_data = False

        for m in [m1, m2, m3, m4]:
            if print_data == True:
                print('adding', m)
            gid = tour.add_moby(m)
            routes = tour.get_routes()
            if print_data == True:
                print('modified to', m)

            if not gid:
                if print_data == True:
                    print('no route found')
                break
                
            self.assertTrue(gid != None)

        self.assertEqual(3, len(routes))

        # print results to console
        
        from pprint import pprint
        if gid:  
            hide_output = not print_data    
            result_string = tour.printer(hide_output)
        else:
            pprint(routes)

        timeElapsed = time.time() - timeStarted
        if print_data == True:
            print('Elapsed Time: %s' % (timeElapsed))

        #self.maxDiff = None
        # print(result_string)

        cmp_string = ('Route for vehicle 0:\tworking minutes (0, 100)\n'
                    '\t        0 \t               depot Load( 0(seats), 0(wheelchairs)) Time(    1,    5) Slack(    0,    4) -> \n'
                    '\t        1 \t S Jungfernheide Bhf Load( 0(seats), 0(wheelchairs)) Time(    1,    5) Slack(    0,    0) -> moby Moby(1, 3, (-18, 60), (0, 60), MobyLoad(1, 0)) enters\n'
                    '\t        2 \t     S Beusselstraße Load( 1(seats), 0(wheelchairs)) Time(    6,   10) Slack(    0,   13) -> moby Moby(2, 3, (5, 10), (5, 26), MobyLoad(1, 0)) enters\n'
                    '\t        3 \t         S Westhafen Load( 2(seats), 0(wheelchairs)) Time(   13,   26) Slack(    0,    0) -> moby Moby(1, 3, (-18, 60), (0, 60), MobyLoad(1, 0)) exits\n'
                    '\t        3 \t         S Westhafen Load( 1(seats), 0(wheelchairs)) Time(   13,   26) Slack(    0,   86) -> moby Moby(2, 3, (5, 10), (5, 26), MobyLoad(1, 0)) exits\n'
                    '\t        0 Load( 0(seats), 0(wheelchairs)) Time(   13,   99)\n'
                    'Load of the route (seats): 0\n'
                    'Load of the route (wheelchairs): 0\n'
                    'Time of the route (including time before start of route): 13min\n'
                    'Time of the route (excluding time before start of route): 12min\n'
                    '\n'
                    'Route for vehicle 1:\tworking minutes (70, 200)\n'
                    '\t        0 \t               depot Load( 0(seats), 0(wheelchairs)) Time(   71,  109) Slack(    0,   38) -> \n'
                    '\t        1 \t S Jungfernheide Bhf Load( 0(seats), 0(wheelchairs)) Time(   71,  109) Slack(    0,    0) -> moby Moby(1, 4, (51, 120), (70, 120), MobyLoad(1, 0)) enters\n'
                    '\t        4 \t           S Wedding Load( 1(seats), 0(wheelchairs)) Time(   82,  120) Slack(    0,    0) -> moby Moby(1, 4, (51, 120), (70, 120), MobyLoad(1, 0)) exits\n'
                    '\t        0 Load( 0(seats), 0(wheelchairs)) Time(   82,  120)\n'
                    'Load of the route (seats): 0\n'
                    'Load of the route (wheelchairs): 0\n'
                    'Time of the route (including time before start of route): 82min\n'
                    'Time of the route (excluding time before start of route): 11min\n'
                    '\n'
                    'Route for vehicle 2:\tworking minutes (-300000, 800000)\n'
                    '\t        0 \t               depot Load( 0(seats), 0(wheelchairs)) Time(    0,   15) Slack(    0,   15) -> \n'
                    '\t        4 \t           S Wedding Load( 0(seats), 0(wheelchairs)) Time(    7,   15) Slack(    0,   15) -> moby Moby(4, 2, (7, 15), (7, 32), MobyLoad(3, 0)) enters\n'
                    '\t        2 \t     S Beusselstraße Load( 3(seats), 0(wheelchairs)) Time(   17,   32) Slack(    0,799982) -> moby Moby(4, 2, (7, 15), (7, 32), MobyLoad(3, 0)) exits\n'
                    '\t        0 Load( 0(seats), 0(wheelchairs)) Time(   17,799999)\n'
                    'Load of the route (seats): 0\n'
                    'Load of the route (wheelchairs): 0\n'
                    'Time of the route (including time before start of route): 17min\n'
                    'Time of the route (excluding time before start of route): 17min\n'
                    '\n'
                    'Total Time of all routes (including time before start of route): 112minTotal Time of all routes (including time before start of route): 40min')

        # times may vary slightly if the OSRM test server updates its database
        self.assertEqual(cmp_string,result_string)

    def test_example_Zwoenitz(self): 
        timeStarted = time.time()

        s1 = Station(longitude=12.813409859560808, latitude=50.630280000496136,\
            name = "Markt", node_id=1)
        s2 = Station(longitude=12.798486326956239, latitude=50.63273595879486,\
            name = "Bahnhof", node_id=2)
        s3 = Station(longitude=12.802395531509443, latitude=50.68397044465389,\
            name = "S258 Abzw Bruenlos", node_id=3)
        s4 = Station(longitude=12.816533671712282, latitude=50.68539837215421,\
            name = "Bruenlos Grundschule", node_id=4)

        m1 = Moby(s1, s3, None, (0, 60))
        m2 = Moby(s1, s4, None, (70, 120))
        m3 = Moby(s2, s3, (5, 10), None)
        m4 = Moby(s4, s2, (7,15), None, load=MobyLoad(3,0))

        busses = [Vehicle(capacity= VehicleCapacity(4,0), work_time= (0, 100)),
                Vehicle(capacity= VehicleCapacity(4,0), work_time= (70, 200)),
                Vehicle(capacity= VehicleCapacity(4,0), work_time= (-300000, 800000))]
        tour = BusTour(None, self.OSRM_iav_url, slack=10, capacities=busses, time_offset_factor=1.0, time_per_demand_unit_wheelchair=3.0)

        for m in [m1, m2, m3, m4]:
            gid = tour.add_moby(m)
            routes = tour.get_routes()

            self.assertTrue(gid != None)

            if not gid:                
                print('no route found')
                break  

        timeElapsed = time.time() - timeStarted 

        print_data = False

        from pprint import pprint
        if gid:  
            hide_output = not print_data    
            result_string = tour.printer(hide_output)
        else:
            pprint(routes)

        self.assertEqual(3, len(routes)) 
        self.assertGreater(2.5*20, timeElapsed) # the OSRM testserver is somtimes really slow, adapted OSRM servers are much faster (usually this test max 2.5 sec)!

    def test_calc_shortest_path_gps_OSRM(self):

        s1 = Station(longitude=12.8075643236188, latitude=50.6323489794738,name = "Schillerstrasse", node_id=0)
        s2 = Station(longitude=12.7983, latitude=50.6322,name = "Kuehnhaide Wendeschleife", node_id=0)
        s3 = Station(longitude=12.797741, latitude=50.611254,name = "Markt", node_id=0)
        s4 = Station(longitude=12.7983, latitude=50.6322,name = "Bahnhof", node_id=0)

        busses = [Vehicle(capacity= VehicleCapacity(4,0), work_time= (0, 100)),
                Vehicle(capacity= VehicleCapacity(4,0), work_time= (70, 200)),
                Vehicle(capacity= VehicleCapacity(4,0), work_time= (-300000, 800000))]
        tour = BusTour(None, self.OSRM_iav_url, slack=10, capacities=busses, time_offset_factor=1.0, time_per_demand_unit_wheelchair=3.0)

        stations = [s1, s2, s3, s4]

        result = tour.calc_shortest_path_gps(stations)

        #print(result)    

        self.assertEqual(len(stations)-1, len(result))
        numPath1 = len(result[0])
        self.assertGreater(numPath1, 4)
        self.assertGreater(7, numPath1)
        self.assertAlmostEqual(s1.longitude, result[0][0][1], places=3)    
        self.assertAlmostEqual(s1.latitude, result[0][0][0], places=3)        
        self.assertAlmostEqual(s2.longitude, result[0][numPath1-1][1], places=3)        
        self.assertAlmostEqual(s2.latitude, result[0][numPath1-1][0], places=3)     

        numPath2 = len(result[1])
        self.assertGreater(numPath2, 16)
        self.assertGreater(19, numPath2)
        self.assertAlmostEqual(s2.longitude, result[1][0][1], places=3)       
        self.assertAlmostEqual(s2.latitude, result[1][0][0], places=3)       
        self.assertAlmostEqual(s3.longitude, result[1][numPath2-1][1], places=3)       
        self.assertAlmostEqual(s3.latitude, result[1][numPath2-1][0], places=3)      

        numPath3 = len(result[2])
        self.assertEqual(17, numPath3)
        self.assertAlmostEqual(s3.longitude, result[2][0][1], places=3)       
        self.assertAlmostEqual(s3.latitude, result[2][0][0], places=3)       
        self.assertAlmostEqual(s4.longitude, result[2][numPath3-1][1], places=3)       
        self.assertAlmostEqual(s4.latitude, result[2][numPath3-1][0], places=3)  
