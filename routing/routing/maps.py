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
import pickle
import os
import networkx as nx
#import traceback
from .rutils import convertNodeNamesToString

import logging
logger = logging.getLogger('routing.Maps')


class Maps():
    def __init__(self, data_dir, *args, **kwargs):
        super().__init__(*args, **kwargs)

        if data_dir != '':
            if data_dir[-1] != '/':
                data_dir += '/'
            self.data_dir = data_dir
            self._scan_communities()
            self._cache_nodes()

    def _scan_communities(self):
        logger.debug(f'self.data_dir={self.data_dir}')
        files = os.listdir(self.data_dir)
        map_files = set([])
        for f in files:
            if f.endswith('.yaml'):
                map_files.add(f[:-5])
            if f.endswith('.p'):
                map_files.add(f[:-2])
        
        list_tmp = list(map_files)
        list_tmp.sort()

        self.communities = list_tmp

    def _cache_nodes(self):
        #print('get_graph _cache_nodes')
        self.NODES_IN_COMMUNITY = dict()
        self.graph = dict()

        for community in self.communities:
            self.graph[community] = self._read_graph(community)
            self.NODES_IN_COMMUNITY[community] = set(self.graph[community].nodes())

    def _read_graph(self, community):
        #print('_read_graph')
        # for line in traceback.format_stack():
        #     print(line.strip())

        p_name = self.data_dir + str(community) + '.p'
        yaml_name = self.data_dir + str(community) + '.yaml'

        logger.debug(f'p_name={p_name}')
        logger.debug(f'yaml_name={yaml_name}')        
        logger.debug(f'community={community}')

        if os.path.exists(p_name):
            logger.debug(f'{p_name} exists')
            graph = self.load_graph_pickle(p_name) 
            #pickle.dump(graph, open(p_name + '2', 'wb'))
        elif os.path.exists(yaml_name):            
            logger.debug(f'{p_name} NOT exists but {yaml_name} exists')
            graph = self.load_graph_yaml(yaml_name)            
            pickle.dump(graph, open(p_name, 'wb'))
        else:
            logger.debug(f'{p_name} and {yaml_name} NOT exists')
            raise FileNotFoundError(yaml_name)
        return graph
    
    def get_graph(self, community):
        community_ = str(community)

        if not community_ in self.graph.keys():   
            logger.info('get_graph community ' + community_ + ' must be loaded...')              
            self.graph[community_] = self._read_graph(community_)
            self.NODES_IN_COMMUNITY[community_] = set(self.graph[community_].nodes())

        from copy import deepcopy
        return deepcopy(self.graph[community_])

    def save_graph(self, community, G):
        # node names must be string
        G_save = convertNodeNamesToString(G)

        p_name = self.data_dir + str(community) + '.p'
        with open(p_name, 'wb') as file:
            pickle.dump(G_save, file)
    
    def load_graph_yaml(self, infile: str)->nx.DiGraph:  
        logger.debug('load_graph_yaml from file ' + infile + ' ...')        
         
        import yaml
        graph = None

        with open(infile, 'rb') as f:
            graph = yaml.load(f, Loader=yaml.Loader)

            # with open(infile + '2', 'w') as yamlfile:
            #     yaml.dump(graph, yamlfile)
            #     yamlfile.close()

            labels = {}
            for node in graph.nodes():
                if not isinstance(node, str):
                    labels[node] = str(node)
            if labels:
                nx.relabel_nodes(graph, labels, copy=False)

        logger.debug('load_graph_yaml from file ' + infile + ' done')        

        return graph    

    def load_graph_pickle(self, infile: str) -> nx.DiGraph:
        logger.debug('load_graph_pickle from file ' + infile + ' ...')        
        graph = None

        try:
            with open(infile, 'rb') as file:
                logger.debug(f'with open(infile, rb) as file ({infile})')                
                graph = pickle.load(file)
            logger.debug(f'load_graph_pickle from file {infile} done')
        except FileNotFoundError:
            logger.error(f'File not found {infile}')
        except IOError:
            logger.error(f'An error occurred while opening the file {infile}')
        except TypeError as te:
            logger.error(f'TypeError: {te}')
        except Exception as err:
            logger.error(f'Exception: {err}')
        finally:
            logger.debug(f'load_graph_pickle finished')
        if graph is None or len(graph) <= 0:
            logger.warning(f'Graph is None or empty')
        else:
            logger.debug(f'len(graph)=={len(graph)}')
        return graph

    # todo bei Verwendung von OSRM und weglassen des Einlesens von Maps muss das woanders her kommen (geht das mit OSRM?)
    # von der NodeID an lat/lon kommt man direkt vermutlich nicht ran bei OSRM, muss man sich was anderes ueberlegen, vllt von vornerein lat/lon merken?
    def get_geo_locations(self, mapId):
        for community in self.communities:
            if mapId in self.NODES_IN_COMMUNITY[community]:
                #print('get_graph get_geo_locations')
                graph = self.get_graph(community)
                return (graph.nodes[mapId]['lat'], graph.nodes[mapId]['lon'])
        return None, None

    def nearest_node(self, community, latitude, longitude):
        from routing.rutils import nearest_from_gps

        #print('get_graph nearest_node')
        G = self.get_graph(community=community)
        stop_ids = nearest_from_gps(
            G,
            longitude=longitude,
            latitude=latitude,
            n_nearests=1)
        
        return stop_ids[0]

    def nearest_node_multi_2(self, G, listLatLon):
        from routing.rutils import nearest_from_gps        

        result = []

        for lat, lon in listLatLon:
            stop_ids = nearest_from_gps(
                G,
                longitude=lon,
                latitude=lat,
                n_nearests=1)
            
            result.append(stop_ids[0])
        
        return result

    def nearest_node_multi(self, community, listLatLon):
        #print('get_graph nearest_node_multi')
        G = self.get_graph(community=community)
        return self.nearest_node_multi_2(G, listLatLon=listLatLon)
        

    # todo bei Verwendung von OSRM gibt es G nicht - braucht man eine Alternative - koennte sein, dass es nicht noetig ist?
    def add_station(self, community, station_name, latitude, longitude):
        from routing.rutils import bus_stop_from_gps

        nodes = self.NODES_IN_COMMUNITY[community]
        for node in nodes:
            if node.startswith(f"busnow_{station_name}_"):
                return node

        #print('get_graph add_station')
        G = self.get_graph(community=community)
        stop_ids = bus_stop_from_gps(
            G,
            stop_name=station_name,
            longitude=longitude,
            latitude=latitude,
            n_nearests=5)
        self.save_graph(community=community, G=G)
        self._cache_nodes()

        mapId = stop_ids[0]
        return mapId