import osmnx, networkx, yaml

import logging
logger = logging.getLogger('routing.OSM_map_utils')

class OSM_map_utils:

    @classmethod 
    def setOsmnxSetting(cls):
        osmnx.settings.cache_folder = 'osmnx_cache'
        osmnx.settings.data_folder = osmnx.settings.cache_folder

        dict_requests_args = {}

        # proxies = {
        #     'http':'your_proxy',
        #     'https':'your_proxy',
        #     'no_proxy':'your_ignore_list',
        # }

        # dict_requests_args['proxies']  = proxies
        #dict_requests_args['verify'] = 'your_cert-Bundle.crt'
        osmnx.settings.requests_kwargs = dict_requests_args

    @classmethod    
    def getGraph(cls, osmCity="Berlin, Deutschland", osmRange=0.5, mapName=None):
        osmCity = osmCity
        osmRange = osmRange
        if mapName:
            mapName = mapName
        else:
            mapName = ''.join(filter(str.isalpha, osmCity))        

        logger.info('downloading map file: ' + mapName)
        OSM_map_utils.setOsmnxSetting()

        #print(osmnx.settings.requests_kwargs)

        G = osmnx.graph_from_address(osmCity, dist=osmRange*1000, network_type='drive', simplify=False)
        G = osmnx.project_graph(G)

        logger.info('saving map file ' + mapName)

        with open('osmnx_cache/' + mapName + '.yaml', 'w') as yamlfile:
            yaml.dump(G, yamlfile)
            yamlfile.close()

        logger.info('getGraph done for ' + mapName)    

    @classmethod    
    def getGraph2(cls, north=49.51, south=49.42, west=7.1, east=7.31, mapName="St. Wendel"):    

        mapName = ''.join(filter(str.isalpha, mapName))    

        logger.info('downloading map file: ' + mapName)
        OSM_map_utils.setOsmnxSetting()        
        G = osmnx.graph_from_bbox(north=north, south=south, west=west, east=east, network_type='drive', simplify=False)
        G = osmnx.project_graph(G)

        logger.info('saving map file ' + mapName)

        with open('osmnx_cache/' + mapName + '.yaml', 'w') as yamlfile:
            yaml.dump(G, yamlfile)
            yamlfile.close()

        logger.info('getGraph2 done for ' + mapName)  


    @classmethod
    def plotGraph(cls, infile, picfile):
        import pickle
        if infile.lower().endswith('.yaml'):
            with open(infile, 'r') as fileHandle:    
                g = yaml.load(fileHandle, Loader=yaml.Loader)
                fileHandle.close()

                with open(infile.replace('.yaml', '.p'), 'wb') as fileHandle2:    
                    pickle.dump(g, fileHandle2)      
                    fileHandle2.close()

        elif infile.lower().endswith('.p'):
            
            with open(infile, 'rb') as f:
                g = pickle.load(f)
                f.close()
        else:
            raise ValueError('can only read .yaml or .p files')
        osmnx.plot_graph(g, bgcolor='w', node_color='b', node_size=1, show=False, save=True, filepath=picfile, dpi=600)