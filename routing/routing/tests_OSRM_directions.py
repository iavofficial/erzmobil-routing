from unittest import TestCase

from .OSRM_directions import OSRM

class Test_OSRM(TestCase):
    def setUp(self):
        self.url = OSRM.getDefaultUrl_OSRM_Testserver()
        self.url_iav_server = OSRM.getDefaultUrl_Testserver() # public iav server for develop
        self.OSRM_Interface = OSRM(self.url)
        self.stationsBerlin=[(52.517037,13.388860),(52.529407,13.397634),(52.523219,13.428555)] # located in centre of Berlin
        
        # located in and around Zwoenitz/Saxony   
        # Markt, Bahnhof, Bruenlos, DorfchemnitzWartehalle, Markt (mod), Bahnhof (mod), Sportkomplex
        self.stationsZwoenitz=[(50.630280000496136, 12.813409859560808),(50.63273595879486, 12.798486326956239),(50.68397044465389, 12.802395531509443),\
            (50.6678396595001,12.8374737110073),(50.629931, 12.812662),(50.632136, 12.798217),(50.6358749673226,12.8125286801734)]          
         

    def shortDescription(self): # turn off printing docstring in tests
        return None

    def test_OSRM_matrix(self):
        '''
        get matrix of travel time in minutes between stations (or other coordinates)
        '''
                
        mat=self.OSRM_Interface.matrix(self.stationsBerlin)

        self.assertEqual(3, len(mat))

        self.assertEqual(3, len(mat[0]))
        self.assertAlmostEqual(0.0, mat[0][0], 6)
        self.assertAlmostEqual(4.3, mat[0][1], delta=0.1)
        self.assertAlmostEqual(6.4383, mat[0][2], delta=0.1)

        self.assertEqual(3, len(mat[1]))
        self.assertAlmostEqual(4.370, mat[1][0], delta=0.1)
        self.assertAlmostEqual(0.0, mat[1][1], 6)
        self.assertAlmostEqual(6.0916, mat[1][2],  delta=0.1)

        self.assertEqual(3, len(mat[2]))
        self.assertAlmostEqual(5.9066, mat[2][0], delta=0.3)
        self.assertAlmostEqual(5.0200, mat[2][1], 1)
        self.assertAlmostEqual(0.0, mat[2][2], 6)

    def test_OSRM_iav_server_matrix(self):
        # test server built 11/2021, available maps: Saxony
        OSRM_interface_iav = OSRM(self.url_iav_server)

        mat=OSRM_interface_iav.matrix(self.stationsZwoenitz)

        numStations  = 7
        self.assertEqual(numStations, len(mat))

        self.assertEqual(numStations, len(mat[0]))
        self.assertAlmostEqual(0.0, mat[0][0], 3)
        self.assertAlmostEqual(2.1867, mat[0][1], delta=0.1) # Zwoenitz Markt - Bahnhof - 2 mins is realistic value
        self.assertAlmostEqual(8.7916, mat[0][2], delta=0.1) # Zwoenitz Markt - Bruenlos - 9 mins is realistic value
        self.assertAlmostEqual(7.7166, mat[0][3], delta=0.1) # Zwoenitz Markt - DorfchemnitzWartehalle - 8 mins is realistic value
        self.assertAlmostEqual(0.24, mat[0][4], 3) # Zwoenitz Markt - Zwoenitz Markt (mod) - 0 mins is realistic value
        self.assertAlmostEqual(2.32833, mat[0][5], delta=0.1) # Zwoenitz Markt - Bahnhof (mod) - 2 mins is realistic value
        self.assertAlmostEqual(2.49, mat[0][6], delta=0.1) # Zwoenitz Markt - Sportkomplex

        self.assertEqual(numStations, len(mat[1]))
        self.assertAlmostEqual(2.2383, mat[1][0], delta=0.1)  # Bahnhof ...
        self.assertAlmostEqual(0.0, mat[1][1], 3)
        self.assertAlmostEqual(9.8933, mat[1][2], delta=0.1) # Bahnhof - Bruenlos - 10 mins is realistic value
        self.assertAlmostEqual(8.8183, mat[1][3], delta=0.1) # Bahnhof - DorfchemnitzWartehalle - 9 mins is realistic value
        self.assertAlmostEqual(1.9466, mat[1][4], delta=0.1) 
        self.assertAlmostEqual(0.18, mat[1][5], delta=0.05) 
        self.assertAlmostEqual(2.846666, mat[1][6], delta=0.1) 

        self.assertEqual(numStations, len(mat[2]))
        self.assertAlmostEqual(8.4, mat[2][0], delta=0.3)  # Bruenlos ...
        self.assertAlmostEqual(8.8783, mat[2][1], delta=0.1)
        self.assertAlmostEqual(0.0, mat[2][2], 3)
        self.assertAlmostEqual(6.1916, mat[2][3], delta=0.1)
        self.assertAlmostEqual(8.25, mat[2][4], delta=0.2)
        self.assertAlmostEqual(9.020, mat[2][5], delta=0.1)
        self.assertAlmostEqual(7.946666, mat[2][6], delta=0.1)

        self.assertEqual(numStations, len(mat[3]))
        self.assertAlmostEqual(8.49, mat[3][0], delta=0.1) # DorfchemnitzWartehalle ...
        self.assertAlmostEqual(8.79166, mat[3][1], delta=0.1)
        self.assertAlmostEqual(6.16, mat[3][2], delta=0.1)
        self.assertAlmostEqual(0.0, mat[3][3], 3)
        self.assertAlmostEqual(8.31, mat[3][4], delta=0.1)
        self.assertAlmostEqual(8.9333, mat[3][5], delta=0.1)
        self.assertAlmostEqual(7.86, mat[3][6], delta=0.1)

        self.assertEqual(numStations, len(mat[4]))
        self.assertAlmostEqual(0.29166, mat[4][0], 3) # Markt (mod) ...
        self.assertAlmostEqual(1.94666, mat[4][1], delta=0.1)
        self.assertAlmostEqual(8.96666, mat[4][2], delta=0.1)
        self.assertAlmostEqual(8.00833, mat[4][3], delta=0.1)
        self.assertAlmostEqual(0.0, mat[4][4], 3)
        self.assertAlmostEqual(2.08833, mat[4][5], delta=0.1)
        self.assertAlmostEqual(2.265, mat[4][6], delta=0.1)

        self.assertEqual(numStations, len(mat[5]))
        self.assertAlmostEqual(2.335, mat[5][0], delta=0.1) # Bahnhof (mod) ...
        self.assertAlmostEqual(0.23166, mat[5][1], 3)
        self.assertAlmostEqual(9.99, mat[5][2], delta=0.1)
        self.assertAlmostEqual(8.915, mat[5][3], delta=0.1)
        self.assertAlmostEqual(2.04333, mat[5][4], delta=0.1)
        self.assertAlmostEqual(0.0, mat[5][5], 3)
        self.assertAlmostEqual(2.94333, mat[5][6], delta=0.1)

        self.assertEqual(numStations, len(mat[6]))
        self.assertAlmostEqual(2.47833, mat[6][0], delta=0.1) # Sportkomplex ...
        self.assertAlmostEqual(2.78, mat[6][1], delta=0.1)
        self.assertAlmostEqual(8.98333, mat[6][2], delta=0.1)
        self.assertAlmostEqual(7.9083, mat[6][3], delta=0.1)
        self.assertAlmostEqual(2.29833, mat[6][4], delta=0.1)
        self.assertAlmostEqual(2.92166, mat[6][5], delta=0.1)
        self.assertAlmostEqual(0.0, mat[6][6], 3)

    def test_OSRM_nearest_osmid(self):
        osmid = self.OSRM_Interface.nearest_osmid(latitude = self.stationsBerlin[0][0], longitude = self.stationsBerlin [0][1])

        self.assertEqual(8507892381, osmid)

    def test_OSRM_nearest_osmids(self):
        osmid = self.OSRM_Interface.nearest_osmids(latitude = self.stationsBerlin[0][0], longitude = self.stationsBerlin [0][1], number=5)

        self.assertEqual(5, len(osmid))
        self.assertEqual(8507892381, osmid[0])
        self.assertEqual(21487242, osmid[1])
        self.assertEqual(2264199819, osmid[2])
        self.assertEqual(6583929466, osmid[3])
        self.assertEqual(6583929460, osmid[4])

    def test_OSRM_route_no_route(self):
        rte=self.OSRM_Interface.route([])

        self.assertEqual(0, len(rte))

    def test_OSRM_route_2_stations(self):
        '''
        get route as list of tuples (node, travel time in seconds), between stops (list of coordinates) in coresponding order
        '''
        
        stations1 = [self.stationsBerlin[0], self.stationsBerlin[1]]

        rte_all=self.OSRM_Interface.route(stations1)

        # check data
        self.assertEqual(1, len(rte_all))
        num_nodes = len(rte_all[0])        
        self.assertGreater(num_nodes,91) # exact routing changes from time to time in OSRM webservice - number of nodes not fixed
        self.assertGreater(115, num_nodes)
        rte = rte_all[0]

        trip_time_without_last = 0 
        for i in range(1, num_nodes-1):
            trip_time_without_last += rte[i][1]

        trip_time = 0
        for i in range(0, num_nodes):
            trip_time += rte[i][1]

        # start station
        self.assertEqual(4, len(rte[0]))
        self.assertAlmostEqual(stations1[0][0], rte[0][0][1], 3)
        self.assertAlmostEqual(stations1[0][1], rte[0][0][0], 3)
        self.assertEqual(0, rte[0][1])

        # waypoint with node-id and travel time of step
        self.assertEqual(2, len(rte[1]))
        self.assertEqual(8507892381, rte[1][0])
        self.assertAlmostEqual(0.0183, rte[1][1], 3)

        # waypoint with node-id and travel time of step
        self.assertEqual(2, len(rte[num_nodes-2]))
        self.assertEqual(659394041, rte[num_nodes-2][0])
        self.assertAlmostEqual(0.01, rte[num_nodes-2][1])

        # stop station with travel time of last step
        self.assertEqual(4, len(rte[num_nodes-1]))        
        self.assertAlmostEqual(stations1[1][0], rte[num_nodes-1][0][1], 3)
        self.assertAlmostEqual(stations1[1][1], rte[num_nodes-1][0][0], 3)
        self.assertAlmostEqual(0.5066, rte[num_nodes-1][1], delta=0.1)

        # trip times
        self.assertAlmostEqual(3.7500, trip_time_without_last, delta=0.1)
        self.assertAlmostEqual(trip_time, (trip_time_without_last+rte[num_nodes-1][1]), 3)

    def test_OSRM_route_3_stations(self):
        stations1 = [self.stationsBerlin[0], self.stationsBerlin[1], self.stationsBerlin[2]]

        rte_all=self.OSRM_Interface.route(stations1)

        # check data - if number of nodes changes sometimes we may no more use the public OSRM server
        self.assertEqual(2, len(rte_all))
        num_nodes_1 = len(rte_all[0])        
        num_nodes_2 = len(rte_all[1])        
        self.assertGreater(num_nodes_1,91)  # exact routing changes from time to time in OSRM webservice - number of nodes not fixed
        self.assertGreater(115, num_nodes_1)
        self.assertGreater(num_nodes_2,133)
        self.assertGreaterEqual(174,num_nodes_2)

        rte1 = rte_all[0]
        rte2 = rte_all[1]

        ####################################
        # first subroute

        # start station
        self.assertEqual(4, len(rte1[0]))
        self.assertAlmostEqual(stations1[0][0], rte1[0][0][1], 3)
        self.assertAlmostEqual(stations1[0][1], rte1[0][0][0], 3)
        self.assertEqual(0, rte1[0][1])

        # intermediate station with travel time of last step for first subroute
        self.assertEqual(4, len(rte1[num_nodes_1-1]))        
        self.assertAlmostEqual(stations1[1][0], rte1[num_nodes_1-1][0][1], 3)
        self.assertAlmostEqual(stations1[1][1], rte1[num_nodes_1-1][0][0], 3)
        self.assertAlmostEqual(0.5066, rte1[num_nodes_1-1][1], delta=0.1)

        ####################################
        # second subroute

        # intermediate station es start of second subroute
        self.assertEqual(4, len(rte2[0]))        
        self.assertAlmostEqual(stations1[1][0], rte2[0][0][1], 3)
        self.assertAlmostEqual(stations1[1][1], rte2[0][0][0], 3)
        self.assertAlmostEqual(0, rte2[0][1], 3)

        # stop station with travel time of last step
        self.assertEqual(4, len(rte2[num_nodes_2-1]))        
        self.assertAlmostEqual(stations1[2][0], rte2[num_nodes_2-1][0][1], 3)
        self.assertAlmostEqual(stations1[2][1], rte2[num_nodes_2-1][0][0], 3)
        self.assertAlmostEqual(0.5599, rte2[num_nodes_2-1][1], delta=0.1)     

    def test_OSRM_getDefaultUrl(self):
        self.assertTrue((OSRM.getDefaultUrl_Environment() is None) or OSRM.getDefaultUrl_Environment() == 'NONE')
        self.assertEqual('http://router.project-osrm.org', OSRM.getDefaultUrl_Testserver())
        #self.assertEqual('xyz', OSRM.getDefaultUrl_Testserver()) # was deactivated !!!
        self.assertEqual('http://router.project-osrm.org', OSRM.getDefaultUrl_OSRM_Testserver())
        self.assertEqual('http://router.project-osrm.org', OSRM.getDefaultUrl())


