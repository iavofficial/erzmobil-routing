import requests
import os

class OSRM:
    @classmethod
    def getDefaultUrl_OSRM_Testserver(cls):
        osrmUrl = 'http://router.project-osrm.org' # public osrm test server, may be slow
        return osrmUrl

    @classmethod
    def getDefaultUrl_Testserver(cls):        
        #osrmUrl = 'xyz' # test-server, maps restricted (11/2021: currently Saxony) # was deactivated!!!
        osrmUrl = 'http://router.project-osrm.org' # public osrm test server, may be slow
        return osrmUrl

    @classmethod
    def getDefaultUrl_Environment(cls):
        osrmEnv = 'OSRM_API_URI'

        osrmUrl = None

        if osrmEnv in os.environ:
            osrmUrl = os.environ.get(osrmEnv)        

        return osrmUrl

    url_default = None

    @classmethod
    def getDefaultUrl(cls)->str:  
        if cls.url_default == None:
            return cls.getDefaultUrl_OSRM_Testserver()
        else:  
            return cls.url_default

    @classmethod
    def setDefaultUrl(cls, url: str):        
        cls.url_default = url

    def __init__(self, url):
        self.url = url

    def nearest_segments(self, latitude, longitude, profile='driving', number=1):
        #http://project-osrm.org/docs/v5.22.0/api/#nearest-service

        coordstring = self.coord2string(latitude=latitude, longitude=longitude)
        url = f'{self.url}/nearest/v1/{profile}/{coordstring}.json'
        # print(url)

        response = requests.get(url, params={'number': number})
        if response.status_code == 407:
            raise ValueError((' '.join((str(response.status_code), 'Check your proxy settings'))))
        elif response.status_code == 429:
            raise ValueError((' '.join((str(response.status_code), 'Too many requests, check again later'))))
        
        # print(response.status_code)

        data = response.json()
        if data['code'].lower() != 'ok':
            raise ValueError(' '.join(('ups', str(response.status_code))))
        
        waypoints = data['waypoints']
        return waypoints

    def nearest_osmid(self, latitude, longitude) -> int:
        nearest_segment = self.nearest_segments(latitude, longitude, profile='driving', number=1)[0]['nodes']

        osmid_1 = nearest_segment[0]
        osmid_2 = nearest_segment[1]

        if osmid_1 > 0:
            return osmid_1
        elif osmid_2 > 0:
            return osmid_2
        else:
            raise ValueError("OSRM returns 0 as node id from nearest service") # this is an OSRM issue (https://github.com/Project-OSRM/osrm-backend/issues/5415)!

    def nearest_osmids(self, latitude, longitude, number=1) -> list:
        osmids = []

        nearest_segments = self.nearest_segments(latitude, longitude, profile='driving', number=number)

        for segment in nearest_segments:
            osmid_1 = segment['nodes'][0]
            osmid_2 = segment['nodes'][1]

            if osmid_1 > 0 and not(osmid_1 in osmids) and len(osmids) < number:
                osmids.append(osmid_1)

            if osmid_2 > 0 and not(osmid_2 in osmids) and len(osmids) < number:
                osmids.append(osmid_2)
        
        return(osmids)

    #updated matrix function from directions.py
    def matrix(self, coordinates, profile='driving'):
        '''Return a list of lists with driving duration in seconds'''
        coordstring = self.coords2string(coordinates)
        url = f'{self.url}/table/v1/{profile}/{coordstring}.json'
        # print(url)
        response = requests.get(url)        

        if response.status_code == 407:
            raise ValueError((' '.join((str(response.status_code), 'Check your proxy settings'))))
        elif response.status_code == 429:
            raise ValueError((' '.join((str(response.status_code), 'Too many requests, check again later'))))

        # print(response.status_code)
        
        data = response.json()
        if data['code'].lower() != 'ok':
            raise ValueError(' '.join(('ups', str(response.status_code))))
        
        #change time to min
        matrix_min = []
        
        # print(data['durations'])       

        for row in data['durations']:     
            matrix_min.append([x / 60 for x in row])

        return matrix_min
    
    def route(self, coordinates, profile='driving', onlyGps=False):
        '''Returns route (list of waypoints and tuples of nodes and travel time in between) 
        as well as overall distance and duration
        coordinates must be ordered in stop sequence'''  

        nodes = []

        # for route we need at least 2 stations
        if len(coordinates) < 2:
            return nodes

        coordstring = self.coords2string(coordinates)
        url = f'{self.url}/route/v1/{profile}/{coordstring}.json'
        #print(url)
        response = requests.get(url, params={'annotations': 'true', 'geometries': 'geojson'})
        
        if response.status_code == 407:
            raise ValueError((' '.join((str(response.status_code), 'Check your proxy settings'))))
        elif response.status_code == 429:
            raise ValueError((' '.join((str(response.status_code), 'Too many requests, check again later'))))
        
        data = response.json()
        #print(data)

        if data['code'].lower() != 'ok':
            raise ValueError(' '.join(('OSRM response invalid', str(response.status_code))))       

        #waypoints where hopOns and hopOffs happen, legs contain nodes in between        

        for idx,leg in enumerate(data['routes'][0]['legs']):
            nodes_leg = []
            durations = [x / 60 for x in leg['annotation']['duration']] #transform duration from sec to min
            nodes_leg = [(data['waypoints'][idx]['location'], 0, data['waypoints'][idx]['name'], ('hopOns', 'hopOffs'))]
            nodes_leg = nodes_leg + list((zip(leg['annotation']['nodes'], durations)))             
            duration = leg['duration']/60 #duration in min     
            #print(data['waypoints'][idx+1])  
            # print(idx)    
            # print(leg) 
            nodes_leg = nodes_leg + [(data['waypoints'][idx+1]['location'], duration-sum(durations), data['waypoints'][idx+1]['name'], ('hopOns', 'hopOffs'))]
            nodes.append(nodes_leg)        

        # extract gps if wanted
        if onlyGps == True:
            coords = data['routes'][0]['geometry']['coordinates']
            waypoints = data['waypoints']            
            subroute_idx = 0
            waypt_idx = 0

            nodes_coords = []

            for subroute in nodes:
                nodes_coords.append([])

            subroute_coords = []

            for lon, lat in coords:
                subroute_coords.append((lat, lon))
                lon_way, lat_way = waypoints[waypt_idx]['location']

                if lon_way == lon and lat_way == lat:
                    if len(subroute_coords) > 1:
                        # print(nodes_coords)
                        # print(subroute_idx)
                        nodes_coords[subroute_idx] = subroute_coords
                        subroute_coords = []  
                        subroute_coords.append((lat, lon))                        
                        subroute_idx+=1  

                    waypt_idx+=1   

            return nodes_coords
        else:           
            return(nodes)
    
    @classmethod
    #same function as in directions.py
    def coord2string(cls, latitude, longitude):
        '''Transform latitude and longitude information into OSRM specific format 'lon,lat'.'''
        return f'{float(longitude)},{float(latitude)}'
    @classmethod
    #same function as in directions.py
    def coords2string(cls, coordinates):
        '''Transform an iterator of pairs (lat, lon) into an OSRM string.'''
        cs = []
        for latitude, longitude in coordinates:
            cs.append(cls.coord2string(latitude=latitude, longitude=longitude))
        return ';'.join(cs)
    
    