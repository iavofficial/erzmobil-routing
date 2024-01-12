from .maps import Maps
from unittest import TestCase

import os

class TestMaps(TestCase):    
    # do the init only once during tests, thus outside all methods
    # read map (either yaml or pickle)
    maps = Maps(data_dir='../maps')
    G = maps.get_graph('meisenheim')

    def setUp(self):
        self.assertIsNotNone(self.G)

    def test_maps_constructor(self):
        self.assertEqual("['1', '1000001', '2', '3', '4', '5', 'Peine_2km', 'StWendel', 'Zwoenitz', 'meisenheim', 'previous-1']", str(self.maps.communities))
        self.assertEqual(80434, len(self.maps.NODES_IN_COMMUNITY['4']))
        self.assertEqual(80434, len(self.maps.NODES_IN_COMMUNITY['meisenheim']))
        self.assertEqual(53112, len(self.maps.NODES_IN_COMMUNITY['1']))
        self.assertEqual(115281, len(self.maps.NODES_IN_COMMUNITY['2']))
        self.assertEqual(115281, len(self.maps.NODES_IN_COMMUNITY['3']))
        self.assertEqual(624, len(self.maps.NODES_IN_COMMUNITY['Peine_2km']))
        self.assertEqual(624, len(self.maps.NODES_IN_COMMUNITY['1000001']))
        self.assertEqual(30401, len(self.maps.NODES_IN_COMMUNITY['5']))
        self.assertEqual(71185, len(self.maps.NODES_IN_COMMUNITY['Zwoenitz']))
        self.assertEqual(38000, len(self.maps.NODES_IN_COMMUNITY['StWendel']))

    def test_get_geo_locations(self):
        # s_Lindenallee in Meisenheim
        lat, lon = self.maps.get_geo_locations('929163070')
        self.assertEqual(lat, 49.7067624)
        self.assertEqual(lon, 7.6690793)

    def test_nearest_node(self):
        # s_Lindenallee in Meisenheim
        nodeId = self.maps.nearest_node('meisenheim', 49.7067624,7.6690793)
        self.assertEqual(nodeId, '929163070')

    def test_nearest_node_multi(self):
        # s_Lindenallee in Meisenheim
        listGps: list = []
        listGps.append((49.7067624,7.6690793))

        #for i in range(0,20):
        nodeIds = self.maps.nearest_node_multi('meisenheim', listGps)
        self.assertEqual(len(nodeIds), 1)
        self.assertEqual(nodeIds[0], '929163070')

    def test_load_graph_compare_yaml_pickle_Peine(self):
        community = str('Peine_2km')
        yaml_name = self.maps.data_dir + community + str('.yaml')
        pickle_name = self.maps.data_dir + community + str('.p')
        pickle_name2 = self.maps.data_dir + '1000001' + str('.p') # same data!

        self.assertTrue(os.path.exists(yaml_name))
        self.assertTrue(os.path.exists(pickle_name))
        self.assertTrue(os.path.exists(pickle_name2))

        G_yaml = self.maps.load_graph_yaml(yaml_name)
        G_pickle = self.maps.load_graph_pickle(pickle_name)
        G_pickle2 = self.maps.load_graph_pickle(pickle_name2)

        # print(G_yaml.nodes.items)
        # print(G_pickle.nodes.items)

        self.assertIsNotNone(G_yaml)
        self.assertIsNotNone(G_pickle)
        self.assertIsNotNone(G_pickle2)

        # the graphs are not completely equivalent, maybe a node for a station "busnow_s1peine" was manually added to the pickle graph
        # that also affects the edges!
        num_nodes = 623
        self.assertEqual(len(G_yaml.nodes), num_nodes)
        self.assertEqual(len(G_pickle.nodes), len(G_yaml.nodes)+1)
        self.assertEqual(len(G_pickle2.nodes), len(G_pickle.nodes))

        count = 0

        for mapId in set(G_yaml.nodes):
            # print(G_yaml.nodes[mapId])
            # print(G_pickle.nodes[mapId])
            self.assertEqual(G_yaml.nodes[mapId]['lat'], G_pickle.nodes[mapId]['lat'])
            self.assertEqual(G_yaml.nodes[mapId]['lon'], G_pickle.nodes[mapId]['lon'])
            self.assertEqual(G_yaml.nodes[mapId]['osmid'], G_pickle.nodes[mapId]['osmid'])
            count = count + 1

        self.assertEqual(count, num_nodes)

        num_edges = 1550
        self.assertEqual(len(G_yaml.edges), num_edges)
        self.assertEqual(len(G_pickle.edges), len(G_yaml.edges)+1)
        
        count = 0

        for edge in G_yaml.edges:
            # print(edge)
            # print(count)
            if G_pickle.has_edge(edge[0], edge[1]):
                count = count + 1            

        self.assertEqual(count, num_edges-1)

        count = 0

        for edge in G_pickle.edges:
            if G_yaml.has_edge(edge[0], edge[1]):
                count = count + 1 
            else:
                # edges for manually added node
                #print(edge)
                self.assertTrue('busnow_s1peine_0' == edge[0] or 'busnow_s1peine_0' == edge[1])
                pass 

        self.assertEqual(count, num_edges-1)   

    def test_load_graph_pickle_StWendel(self):
        community = str('StWendel')
        pickle_name = self.maps.data_dir + community + str('.p')

        self.assertTrue(os.path.exists(pickle_name))

        G_pickle = self.maps.load_graph_pickle(pickle_name)

        nodes_pickle = set(G_pickle.nodes())

        # check if nodes exist
        #print(nodes_pickle)
        self.assertTrue('446284668' in nodes_pickle)
        self.assertTrue('430888873' in nodes_pickle) 

        # G_mod = convertNodeNamesToString(G_pickle)   
        # self.maps.save_graph(community  + "2", G_mod);                
    
    def test_load_graph_pickle_Zwoenitz(self):
        community = str('Zwoenitz')
        pickle_name = self.maps.data_dir + community + str('.p')

        self.assertTrue(os.path.exists(pickle_name))

        G_pickle = self.maps.load_graph_pickle(pickle_name)

        nodes_pickle = set(G_pickle.nodes())

        # check if nodes exist
        #print(nodes_pickle)
        self.assertTrue('2198217231' in nodes_pickle)
        self.assertTrue('2318664298' in nodes_pickle)

