import json
from datetime import datetime, timedelta, timezone, tzinfo
from time import sleep
import time
from typing import Any

import django
from dateutil.parser import parse
from dateutil.relativedelta import relativedelta
from dateutil.tz import tzutc
from django.db import connections
from django.db.models import Max
from django.test import (Client, LiveServerTestCase, TestCase,
                         TransactionTestCase, tag)
from django.urls import reverse
from django.conf import settings

from .services import OrdersMQ as Orders, RequestManagerConfig
from .services import RoutesDummy as Routes
from routing.OSRM_directions import OSRM
from routing.routingClasses import MobyLoad
from routing.errors import InvalidTime2, BusesTooSmall, NoBuses

from . import tasks
from .apifunctions import API_URI, RouteRequest, GetRequestManager, driver_details, driver_details_busId, order_details, order_details_with_gps, driver_details_with_gps
from .EventBus import Consumer, Publisher, UnthreadedPublisher
from .models import Bus, Node, Order, Route, Station
from .signals import RabbitMqListener as Listener
from .signals import RabbitMqSender as MessageBus

from django.core.exceptions import ObjectDoesNotExist

from unittest import mock

UTC = tzutc()

#####################################################
# set config values

# activate OSRM as default
GetRequestManager().OSRM_activated = True
GetRequestManager().OSRM_url = OSRM.getDefaultUrl_OSRM_Testserver()

# others
GetRequestManager().Config.timeOffset_MaxDaysOrderInFuture = 100000
GetRequestManager().Config.timeOffset_FactorForDrivingTimes = 1.00
GetRequestManager().Config.timeService_per_wheelchair = 5

#####################################################

class Test_Data:
    def __init__(self):
        self.community_id_Peine = 1000001
        self.community_id_Meisenheim = 4   

        self.s1_uid=0
        self.s1_name='s1'
        self.s1_mapId='291521266'
        self.s1_community=self.community_id_Peine
        self.s1_latitude=52.3093421
        self.s1_longitude=10.2505459

        self.s2_uid=1
        self.s2_name='s2'
        self.s2_mapId='59908328'
        self.s2_community=self.community_id_Peine
        self.s2_latitude=52.3096315
        self.s2_longitude=10.2467584

        self.Lindenallee_uid=2
        self.Lindenallee_name='Lindenallee'
        self.Lindenallee_mapId='929163070'
        self.Lindenallee_community=self.community_id_Meisenheim
        self.Lindenallee_latitude=49.7067624
        self.Lindenallee_longitude=7.6690793

        self.Untergasse_uid=3
        self.Untergasse_name='Untergasse'
        self.Untergasse_mapId='288942560'
        self.Untergasse_community=self.community_id_Meisenheim
        self.Untergasse_latitude=49.7079532
        self.Untergasse_longitude=7.6721057

        self.Bahnhof_uid=4
        self.Bahnhof_name='Bahnhof'
        self.Bahnhof_mapId='288939733'
        self.Bahnhof_community=self.community_id_Meisenheim
        self.Bahnhof_latitude=49.7097201
        self.Bahnhof_longitude=7.6663633        

        self.Roth_uid=8
        self.Roth_name='Roth'
        self.Roth_mapId='1258712074'
        self.Roth_community=self.community_id_Meisenheim
        self.Roth_latitude=49.6751843
        self.Roth_longitude=7.6753142

        # todo if due to changes in source errors arise in tests these stations may be better
        # Kühnhaide, Fleischerei Meischner and Hormersdorf, Grundschule are actual stations
        # Added to test data, because test_order_max_date_error was using Lindenallee and Untergasse, but the backend evaluates them as the same stop, because the coords are so close to each other
        # with the old stations, SameStop exception gets raised, which prevents the test from testing the max date
        # self.Fleischerei_uid=20
        # self.Fleischerei_name='Kühnhaide, Fleischerei Meischner'
        # self.Fleischerei_mapId='779164671'
        # self.Fleischerei_community=self.community_id_Meisenheim
        # self.Fleischerei_latitude=50.616948
        # self.Fleischerei_longitude=12.801235

        # self.Grundschule_uid=40
        # self.Grundschule_name='Hormersdorf, Grundschule'
        # self.Grundschule_mapId='393185051'
        # self.Grundschule_community=self.community_id_Meisenheim
        # self.Grundschule_latitude=50.670821
        # self.Grundschule_longitude=12.881401

# mock non existing API calls for tests, see https://stackoverflow.com/questions/15753390/how-can-i-mock-requests-and-the-response
def mocked_requests_get(*args, **kwargs):
    class MockResponse:
        def __init__(self, json_data, status_code):
            self.json_data = json_data
            self.text = json_data
            self.content = json.dumps(json_data)
            self.status_code = status_code

        def json(self):
            return self.json_data        

    test_data = Test_Data()

    mock_availabilities_meise_1 = MockResponse('[{"busId": 2, "name": "meise_0", "communityId": '+str(test_data.community_id_Meisenheim)+', "seats": 3, "seatsWheelchair": 1, "seatsBlockedPerWheelchair": 2, "availabilitySlots": [{"startDate": "2090-03-01T11:50:00+00:00", "endDate": "2090-03-01T15:50:00+00:00"}], "blockingSlots" : []}]', 200)

    if args[0] == API_URI + '/customendpoints/stops/nearest':
        # mock nearest stops request
        latAsked = kwargs['params']['lat']
        lonAsked = kwargs['params']['lng']

        if latAsked > 52 and latAsked < 52.3095 and lonAsked > 10.0:
            return MockResponse([{'id': test_data.s1_uid, 'communityId': test_data.s1_community, 'name': test_data.s1_name, 'latitude': test_data.s1_latitude, 'longitude': test_data.s1_longitude, 'mapId': test_data.s1_mapId}], 200)
        elif latAsked >= 52.3095 and latAsked < 52.5 and lonAsked > 10.0:
            return MockResponse([{'id': test_data.s2_uid, 'communityId': test_data.s2_community, 'name': test_data.s2_name, 'latitude': test_data.s2_latitude, 'longitude': test_data.s2_longitude, 'mapId': test_data.s2_mapId}], 200)        
        elif latAsked >= 49.7079 and latAsked < 49.708 and lonAsked > 7.672 and lonAsked < 7.673:
            return MockResponse([{'id': test_data.Untergasse_uid, 'communityId': test_data.Untergasse_community, 'name': test_data.Untergasse_name, 'latitude': test_data.Untergasse_latitude, 'longitude': test_data.Untergasse_longitude, 'mapId': test_data.Untergasse_mapId}], 200)   
        elif latAsked >= 49.706 and latAsked < 49.708 and lonAsked > 7.668 and lonAsked < 7.69:
            return MockResponse([{'id': test_data.Lindenallee_uid, 'communityId': test_data.Lindenallee_community, 'name': test_data.Lindenallee_name, 'latitude': test_data.Lindenallee_latitude, 'longitude': test_data.Lindenallee_longitude, 'mapId': test_data.Lindenallee_mapId}], 200)               
        elif latAsked >= 49.5 and latAsked < 49.706 and ((lonAsked > 7.69 and lonAsked < 7.71) or lonAsked == test_data.Roth_longitude):
            return MockResponse([{'id': test_data.Roth_uid, 'communityId': test_data.Roth_community, 'name': test_data.Roth_name, 'latitude': test_data.Roth_latitude, 'longitude': test_data.Roth_longitude, 'mapId': test_data.Roth_mapId}], 200)               
        elif latAsked ==test_data.Bahnhof_latitude and lonAsked == test_data.Bahnhof_longitude:
            return MockResponse([{'id': test_data.Bahnhof_uid, 'communityId': test_data.Bahnhof_community, 'name': test_data.Bahnhof_name, 'latitude': test_data.Bahnhof_latitude, 'longitude': test_data.Bahnhof_longitude, 'mapId': test_data.Bahnhof_mapId}], 200)                       
        else:
            # no station defined
            return MockResponse(None, 404)

    elif args[0] == API_URI + '/customendpoints/operatingtime/'+str(test_data.community_id_Peine)+'/2090-03-01T01:50:00+00:00/2090-03-01T23:50:00+00:00':
        # mock available buses request
        return MockResponse('[{"busId": 0, "name": "bus1", "communityId": '+str(test_data.community_id_Peine)+', "seats": 8, "seatsWheelchair": 2, "seatsBlockedPerWheelchair": 2, "availabilitySlots": [{"startDate": "2090-03-01T10:50:00+00:00", "endDate": "2090-03-01T16:50:00+00:00"}], "blockingSlots": []}]', 200)
    elif args[0] == API_URI + '/customendpoints/operatingtime/'+str(test_data.community_id_Peine)+'/2090-03-01T03:50:00+00:00/2090-03-02T01:50:00+00:00':
        # mock available buses request
        return MockResponse('[{"busId": 0, "name": "bus1", "communityId": '+str(test_data.community_id_Peine)+', "seats": 8, "seatsWheelchair": 2, "seatsBlockedPerWheelchair": 2, "availabilitySlots": [{"startDate": "2090-03-01T10:50:00+00:00", "endDate": "2090-03-01T16:50:00+00:00"}], "blockingSlots": []}]', 200)
    elif args[0] == API_URI + '/customendpoints/operatingtime/'+str(test_data.community_id_Peine)+'/2090-03-01T12:50:00+00:00/2090-03-01T17:00:00+00:00':
        # mock available buses request
        return MockResponse('[{"busId": 0, "name": "bus1", "communityId": '+str(test_data.community_id_Peine)+', "seats": 8, "seatsWheelchair": 2, "seatsBlockedPerWheelchair": 2, "availabilitySlots": [{"startDate": "2090-03-01T10:50:00+00:00", "endDate": "2090-03-01T16:50:00+00:00"}], "blockingSlots": []}]', 200)
    elif args[0] == API_URI + '/customendpoints/operatingtime/'+str(test_data.community_id_Peine)+'/2090-03-01T03:50:00+00:00/2090-03-01T23:50:00+00:00':
        # mock available buses request
        return MockResponse('[{"busId": 0, "name": "bus1", "communityId": '+str(test_data.community_id_Peine)+', "seats": 8, "seatsWheelchair": 2, "seatsBlockedPerWheelchair": 2, "availabilitySlots": [{"startDate": "2090-03-01T10:50:00+00:00", "endDate": "2090-03-01T16:50:00+00:00"}], "blockingSlots": []}]', 200)    
    elif args[0] == API_URI + '/customendpoints/operatingtime/'+str(test_data.community_id_Peine)+'/2090-03-01T03:50:00+00:00/2090-03-02T00:50:00+00:00':
        # mock available buses request
        return MockResponse('[{"busId": 0, "name": "bus1", "communityId": '+str(test_data.community_id_Peine)+', "seats": 8, "seatsWheelchair": 2, "seatsBlockedPerWheelchair": 2, "availabilitySlots": [{"startDate": "2090-03-01T10:50:00+00:00", "endDate": "2090-03-01T17:50:00+00:00"}], "blockingSlots": []}]', 200)        
    elif args[0] == API_URI + '/customendpoints/operatingtime/'+str(test_data.community_id_Peine)+'/2090-03-01T12:50:00+00:00/2090-03-01T14:50:00+00:00':
        # mock available buses request
        return MockResponse('[{"busId": 0, "name": "bus1", "communityId": '+str(test_data.community_id_Peine)+', "seats": 8, "seatsWheelchair": 2, "seatsBlockedPerWheelchair": 2, "availabilitySlots": [{"startDate": "2090-03-01T10:50:00+00:00", "endDate": "2090-03-01T16:50:00+00:00"}], "blockingSlots": []}]', 200)        
    elif args[0] == API_URI + '/customendpoints/operatingtime/'+str(test_data.community_id_Peine)+'/2090-03-01T12:50:00+00:00/2090-03-01T15:50:00+00:00':
        # mock available buses request
        return MockResponse('[{"busId": 0, "name": "bus1", "communityId": '+str(test_data.community_id_Peine)+', "seats": 8, "seatsWheelchair": 2, "seatsBlockedPerWheelchair": 2, "availabilitySlots": [{"startDate": "2090-03-01T10:50:00+00:00", "endDate": "2090-03-01T17:50:00+00:00"}], "blockingSlots": []}]', 200)    
    elif args[0] == API_URI + '/customendpoints/operatingtime/'+str(test_data.community_id_Peine)+'/2090-03-01T12:50:00+00:00/2090-03-01T17:05:00+00:00':
        # mock available buses request
        return MockResponse('[{"busId": 0, "name": "bus1", "communityId": '+str(test_data.community_id_Peine)+', "seats": 8, "seatsWheelchair": 2, "seatsBlockedPerWheelchair": 2, "availabilitySlots": [{"startDate": "2090-03-01T10:50:00+00:00", "endDate": "2090-03-01T18:50:00+00:00"}], "blockingSlots": []}]', 200)        
    elif args[0] == API_URI + '/customendpoints/operatingtime/'+str(test_data.community_id_Peine)+'/2090-03-01T21:50:00+00:00/2090-03-02T18:10:00+00:00':
        # mock available buses request
        return MockResponse('[{"busId": 0, "name": "bus1", "communityId": '+str(test_data.community_id_Peine)+', "seats": 8, "seatsWheelchair": 2, "seatsBlockedPerWheelchair": 2, "availabilitySlots": [{"startDate": "2090-03-02T07:50:00+00:00", "endDate": "2090-03-02T08:05:00+00:00"}], "blockingSlots": [{"startDate": "2090-03-02T08:05:00+00:00", "endDate": "2090-03-02T08:45:00+00:00"}]}]', 200)            
    elif args[0] == API_URI + '/customendpoints/operatingtime/'+str(test_data.community_id_Peine)+'/2090-03-02T06:50:00+00:00/2090-03-02T09:10:00+00:00':
        # mock available buses request
        return MockResponse('[{"busId": 0, "name": "bus1", "communityId": '+str(test_data.community_id_Peine)+', "seats": 8, "seatsWheelchair": 2, "seatsBlockedPerWheelchair": 2, "availabilitySlots": [{"startDate": "2090-03-02T07:50:00+00:00", "endDate": "2090-03-02T08:05:00+00:00"}], "blockingSlots": [{"startDate": "2090-03-02T08:05:00+00:00", "endDate": "2090-03-02T08:45:00+00:00"}]}]', 200)            
    elif args[0] == API_URI + '/customendpoints/operatingtime/'+str(test_data.community_id_Peine)+'/2090-03-01T22:10:00+00:00/2090-03-02T18:10:00+00:00':
        # mock available buses request
        return MockResponse('[{"busId": 0, "name": "bus1", "communityId": '+str(test_data.community_id_Peine)+', "seats": 8, "seatsWheelchair": 2, "seatsBlockedPerWheelchair": 2, "availabilitySlots": [{"startDate": "2090-03-02T07:50:00+00:00", "endDate": "2090-03-02T08:05:00+00:00"}], "blockingSlots": [{"startDate": "2090-03-02T08:05:00+00:00", "endDate": "2090-03-02T08:45:00+00:00"}]}]', 200)                
    elif args[0] == API_URI + '/customendpoints/operatingtime/'+str(test_data.community_id_Peine)+'/2090-03-02T03:30:00+00:00/2090-03-02T23:30:00+00:00':
        # mock available buses request
        return MockResponse('[{"busId": 0, "name": "bus1", "communityId": '+str(test_data.community_id_Peine)+', "seats": 8, "seatsWheelchair": 2, "seatsBlockedPerWheelchair": 2, "availabilitySlots": [{"startDate": "2090-03-02T12:30:00+00:00", "endDate": "2090-03-02T14:30:00+00:00"}], "blockingSlots": []}]', 200)    
    elif args[0] == API_URI + '/customendpoints/operatingtime/'+str(test_data.community_id_Peine)+'/2090-03-03T03:30:00+00:00/2090-03-03T23:30:00+00:00':
        # mock available buses request
        return MockResponse('[{"busId": 0, "name": "bus1", "communityId": '+str(test_data.community_id_Peine)+', "seats": 8, "seatsWheelchair": 2, "seatsBlockedPerWheelchair": 2, "availabilitySlots": [{"startDate": "2090-03-03T12:30:00+00:00", "endDate": "2090-03-03T14:30:00+00:00"}], "blockingSlots": []}]', 200)    
    elif args[0] == API_URI + '/customendpoints/operatingtime/'+str(test_data.community_id_Peine)+'/2099-03-01T02:50:00+00:00/2099-03-01T22:50:00+00:00':
        # mock available buses request
        return MockResponse('''[]''', 200)
    elif args[0] == API_URI + '/customendpoints/operatingtime/'+str(test_data.community_id_Meisenheim)+'/2090-03-01T03:50:00+00:00/2090-03-01T23:50:00+00:00':
        # mock available buses request
        return mock_availabilities_meise_1
    elif args[0] == API_URI + '/customendpoints/operatingtime/'+str(test_data.community_id_Meisenheim)+'/2090-03-01T12:50:00+00:00/2090-03-01T17:00:00+00:00':
        # mock available buses request
        return mock_availabilities_meise_1
    elif args[0] == API_URI + '/customendpoints/operatingtime/'+str(test_data.community_id_Meisenheim)+'/2090-03-01T06:00:00+00:00/2090-03-02T04:00:00+00:00':
        # mock available buses request
        return mock_availabilities_meise_1
    elif args[0] == API_URI + '/customendpoints/operatingtime/'+str(test_data.community_id_Meisenheim)+'/2090-03-01T03:20:00+00:00/2090-03-01T23:20:00+00:00':
        # mock available buses request
        return mock_availabilities_meise_1    
    elif args[0] == API_URI + '/customendpoints/operatingtime/'+str(test_data.community_id_Meisenheim)+'/2090-03-01T03:30:00+00:00/2090-03-01T23:30:00+00:00':
        # mock available buses request
        return mock_availabilities_meise_1
    elif args[0] == API_URI + '/customendpoints/operatingtime/'+str(test_data.community_id_Meisenheim)+'/2090-03-01T03:32:00+00:00/2090-03-01T23:32:00+00:00':
        # mock available buses request
        return mock_availabilities_meise_1     
    elif args[0] == API_URI + '/customendpoints/operatingtime/'+str(test_data.community_id_Meisenheim)+'/2090-03-01T12:45:00+00:00/2090-03-01T17:00:00+00:00':
        # mock available buses request
        return mock_availabilities_meise_1      
    elif args[0] == API_URI + '/customendpoints/operatingtime/'+str(test_data.community_id_Meisenheim)+'/2090-03-01T04:20:00+00:00/2090-03-02T00:20:00+00:00':
        # mock available buses request
        return mock_availabilities_meise_1    
    elif args[0] == API_URI + '/customendpoints/operatingtime/'+str(test_data.community_id_Meisenheim)+'/2090-03-01T06:00:00+00:00/2090-03-02T02:00:00+00:00':
        # mock available buses request
        return mock_availabilities_meise_1    
    elif args[0] == API_URI + '/customendpoints/operatingtime/'+str(test_data.community_id_Meisenheim)+'/2090-03-01T04:00:00+00:00/2090-03-02T02:00:00+00:00':
        # mock available buses request
        return mock_availabilities_meise_1    
    elif args[0] == API_URI + '/customendpoints/operatingtime/'+str(test_data.community_id_Meisenheim)+'/2090-03-01T04:50:00+00:00/2090-03-02T00:50:00+00:00':
        # mock available buses request
        return MockResponse('[{"busId": 2, "name": "meise_0", "communityId": '+str(test_data.community_id_Meisenheim)+', "seats": 3, "seatsWheelchair": 1, "seatsBlockedPerWheelchair": 2, "availabilitySlots": [{"startDate": "2090-03-01T11:50:00+00:00", "endDate": "2090-03-01T15:50:00+00:00"}], "blockingSlots": []}]', 200)   
    elif args[0] == API_URI + '/customendpoints/operatingtime/'+str(test_data.community_id_Meisenheim)+'/2090-03-02T12:30:00+00:00/2090-03-02T14:30:00+00:00':
        # mock available buses request
        return MockResponse('[{"busId": 2, "name": "meise_0", "communityId": '+str(test_data.community_id_Meisenheim)+', "seats": 3, "seatsWheelchair": 1, "seatsBlockedPerWheelchair": 2, "availabilitySlots": [{"startDate": "2090-03-02T12:30:00+00:00", "endDate": "2090-03-02T14:30:00+00:00"}], "blockingSlots": []}]', 200)       
    elif args[0] == API_URI + '/customendpoints/operatingtime/'+str(test_data.community_id_Meisenheim)+'/2090-03-03T12:30:00+00:00/2090-03-03T14:30:00+00:00':
        # mock available buses request
        return MockResponse('[{"busId": 2, "name": "meise_0", "communityId": '+str(test_data.community_id_Meisenheim)+', "seats": 3, "seatsWheelchair": 1, "seatsBlockedPerWheelchair": 2, "availabilitySlots": [{"startDate": "2090-03-03T12:30:00+00:00", "endDate": "2090-03-03T14:30:00+00:00"}], "blockingSlots": []}]', 200)       
    
    elif args[0] == API_URI + '/items/bus/1':
        # mock buses request
        return MockResponse('{"id": 1, "name": "bus1_update", "community_id": 1, "seats": 4, "seats_wheelchair": 2, "seatsBlockedByWheelchair": 2}', 200)      
    
    elif args[0] == API_URI + '/customendpoints/roadclosures/'+str(test_data.community_id_Peine)+'/2090-03-02T12:50:00+00:00/2090-03-02T14:50:00+00:00':
        # mock road closures request
        return MockResponse('''[{"latitude": 52.309409276213145, "longitude": 10.249192679384402}, {"latitude": 52.30886871841433, "longitude": 10.250494761672451}]''', 200) 
    elif args[0] == API_URI + '/customendpoints/roadclosures/'+str(test_data.community_id_Peine)+'/2090-03-02T13:30:00+00:00/2090-03-02T13:40:00+00:00':
        # mock road closures request
        return MockResponse('''[{"latitude": 52.309550769718946, "longitude": 10.247906992115212}, {"latitude": 52.31016080442586, "longitude": 10.246329853110497}, {"latitude": 52.31094137420135, "longitude": 10.246533701003997}, {"latitude": 52.308279989340946, "longitude": 10.248185924981511}]''', 200) 
    elif args[0] == API_URI + '/customendpoints/roadclosures/'+str(test_data.community_id_Peine)+'/2090-03-03T13:30:00+00:00/2090-03-03T13:40:00+00:00':
        # mock road closures request
        return MockResponse('''[]''', 200)     
    elif args[0] == API_URI + '/customendpoints/roadclosures/'+str(test_data.community_id_Peine)+'/2090-03-01T13:50:00+00:00/2090-03-01T15:50:00+00:00':
        # mock road closures request
        return MockResponse('''[]''', 200)  
    elif args[0] == API_URI + '/customendpoints/roadclosures/'+str(test_data.community_id_Peine)+'/2090-03-01T11:50:00+00:00/2090-03-01T13:50:00+00:00':
        # mock road closures request
        return MockResponse('''[]''', 200)
    elif args[0] == API_URI + '/customendpoints/roadclosures/'+str(test_data.community_id_Peine)+'/2090-03-01T13:50:00+00:00/2090-03-01T14:00:00+00:00':
        # mock road closures request
        return MockResponse('''[]''', 200)
    elif args[0] == API_URI + '/customendpoints/roadclosures/'+str(test_data.community_id_Meisenheim)+'/2090-03-01T13:50:00+00:00/2090-03-01T14:00:00+00:00':
        # mock road closures request
        return MockResponse('''[]''', 200)
    elif args[0] == API_URI + '/customendpoints/roadclosures/'+str(test_data.community_id_Meisenheim)+'/2090-03-01T13:20:00+00:00/2090-03-01T13:30:00+00:00':
        # mock road closures request
        return MockResponse('''[]''', 200)   
    elif args[0] == API_URI + '/customendpoints/roadclosures/'+str(test_data.community_id_Meisenheim)+'/2090-03-01T13:30:00+00:00/2090-03-01T13:40:00+00:00':
        # mock road closures request
        return MockResponse('''[]''', 200)  
    elif args[0] == API_URI + '/customendpoints/roadclosures/'+str(test_data.community_id_Meisenheim)+'/2090-03-02T13:30:00+00:00/2090-03-02T13:40:00+00:00':
        # mock road closures request
        return MockResponse('''[]''', 200)
    elif args[0] == API_URI + '/customendpoints/roadclosures/'+str(test_data.community_id_Meisenheim)+'/2090-03-02T12:30:00+00:00/2090-03-02T14:30:00+00:00':
        # mock road closures request
        return MockResponse('''[]''', 200) 
    elif args[0] == API_URI + '/customendpoints/roadclosures/'+str(test_data.community_id_Meisenheim)+'/2090-03-01T13:32:00+00:00/2090-03-01T13:42:00+00:00':
        # mock road closures request
        return MockResponse('''[]''', 200)    
    elif args[0] == API_URI + '/customendpoints/roadclosures/'+str(test_data.community_id_Meisenheim)+'/2090-03-01T14:20:00+00:00/2090-03-01T14:30:00+00:00':
        # mock road closures request
        return MockResponse('''[]''', 200) 
    elif args[0] == API_URI + '/customendpoints/roadclosures/'+str(test_data.community_id_Meisenheim)+'/2090-03-01T14:50:00+00:00/2090-03-01T15:00:00+00:00':
        # mock road closures request
        return MockResponse('''[]''', 200)   
    
    elif args[0] == 'http://router.project-osrm.org/table/v1/driving/10.2467584,52.3096315;10.2505459,52.3093421.json':
        restext={'code':'Ok','durations':[[0,40.3],[42.8,0]],'sources':[{'hint':'dKtYjpirWI4AAAAACgAAAAAAAACLAAAAAAAAAMyCN0EAAAAALrcEQwAAAAAKAAAAAAAAAIsAAAAQ6QAAZlqcAIAuHgNmWpwAgC4eAwAAzxQrk1Re','distance':0,'location':[10.246758,52.309632],'name':'Braunschweiger Straße'},{'hint':'sKtYjrOrWI4AAAAAlgAAAAAAAAAAAAAAAAAAANv3z0IAAAAAAAAAAAAAAACWAAAAAAAAAAAAAAAQ6QAAMmmcAF4tHgMyaZwAXi0eAwAArwsrk1Re','distance':0,'location':[10.250546,52.309342],'name':'Hüttenweg'}],'destinations':[{'hint':'dKtYjpirWI4AAAAACgAAAAAAAACLAAAAAAAAAMyCN0EAAAAALrcEQwAAAAAKAAAAAAAAAIsAAAAQ6QAAZlqcAIAuHgNmWpwAgC4eAwAAzxQrk1Re','distance':0,'location':[10.246758,52.309632],'name':'Braunschweiger Straße'},{'hint':'sKtYjrOrWI4AAAAAlgAAAAAAAAAAAAAAAAAAANv3z0IAAAAAAAAAAAAAAACWAAAAAAAAAAAAAAAQ6QAAMmmcAF4tHgMyaZwAXi0eAwAArwsrk1Re','distance':0,'location':[10.250546,52.309342],'name':'Hüttenweg'}]}
        return MockResponse(restext, 200)
    elif args[0] == 'http://router.project-osrm.org/table/v1/driving/7.6690793,49.7067624;7.6753142,49.6751843.json':
        restext={'code':'Ok','durations':[[0,417.8],[420.4,0]],'sources':[{'hint':'9lN1gXbvz48AAAAA3gAAAAAAAAAAAAAAAAAAAMXXGkMAAAAAAAAAAAAAAADeAAAAAAAAAAAAAAAQ6QAAVwV1AAp39gJXBXUACnf2AgAAbxArk1Re','distance':0,'location':[7.669079,49.706762],'name':'Herzog-Wolfgang-Straße'},{'hint':'yOrPj87qz48SAAAAAAAAAEEAAAAAAAAA_uJKQQAAAACBDzNCAAAAABIAAAAAAAAAQQAAAAAAAAAQ6QAAsh11ALD79QKyHXUAsPv1AgMATwUrk1Re','distance':0,'location':[7.675314,49.675184],'name':'Vordergasse'}],'destinations':[{'hint':'9lN1gXbvz48AAAAA3gAAAAAAAAAAAAAAAAAAAMXXGkMAAAAAAAAAAAAAAADeAAAAAAAAAAAAAAAQ6QAAVwV1AAp39gJXBXUACnf2AgAAbxArk1Re','distance':0,'location':[7.669079,49.706762],'name':'Herzog-Wolfgang-Straße'},{'hint':'yOrPj87qz48SAAAAAAAAAEEAAAAAAAAA_uJKQQAAAACBDzNCAAAAABIAAAAAAAAAQQAAAAAAAAAQ6QAAsh11ALD79QKyHXUAsPv1AgMATwUrk1Re','distance':0,'location':[7.675314,49.675184],'name':'Vordergasse'}]}
        return MockResponse(restext, 200)
    elif args[0] == 'http://router.project-osrm.org/table/v1/driving/7.6690793,49.7067624;7.6721057,49.7079532.json':
        restext={'code':'Ok','durations':[[0,107.9],[159.2,0]],'sources':[{'hint':'Bd18gcj0KJAAAAAA3gAAAAAAAAAAAAAAAAAAAMXXGkMAAAAAAAAAAAAAAADeAAAAAAAAAAAAAAAJ6QAAVwV1AAp39gJXBXUACnf2AgAAbxBVcNyF','distance':0,'location':[7.669079,49.706762],'name':'Herzog-Wolfgang-Straße'},{'hint':'nPIokP___38AAAAACAAAAAAAAAA1AAAAAAAAAHsmuEAAAAAAVqkUQgAAAAAIAAAAAAAAADUAAAAJ6QAAKhF1ALF79gIqEXUAsXv2AgAAvwNVcNyF','distance':0,'location':[7.672106,49.707953],'name':'Untertor'}],'destinations':[{'hint':'Bd18gcj0KJAAAAAA3gAAAAAAAAAAAAAAAAAAAMXXGkMAAAAAAAAAAAAAAADeAAAAAAAAAAAAAAAJ6QAAVwV1AAp39gJXBXUACnf2AgAAbxBVcNyF','distance':0,'location':[7.669079,49.706762],'name':'Herzog-Wolfgang-Straße'},{'hint':'nPIokP___38AAAAACAAAAAAAAAA1AAAAAAAAAHsmuEAAAAAAVqkUQgAAAAAIAAAAAAAAADUAAAAJ6QAAKhF1ALF79gIqEXUAsXv2AgAAvwNVcNyF','distance':0,'location':[7.672106,49.707953],'name':'Untertor'}]}
        return MockResponse(restext, 200)
    elif args[0] == 'http://router.project-osrm.org/table/v1/driving/7.6690793,49.7067624;7.6721057,49.7079532;7.6690793,49.7067624;7.6753142,49.6751843.json':
        restext={'code':'Ok','durations':[[0,107.9,0,417.8],[159.2,0,159.2,571.8],[0,107.9,0,417.8],[420.4,471.7,420.4,0]],'sources':[{'hint':'Bd18gcj0KJAAAAAA3gAAAAAAAAAAAAAAAAAAAMXXGkMAAAAAAAAAAAAAAADeAAAAAAAAAAAAAAAJ6QAAVwV1AAp39gJXBXUACnf2AgAAbxBVcNyF','distance':0,'location':[7.669079,49.706762],'name':'Herzog-Wolfgang-Straße'},{'hint':'nPIokP___38AAAAACAAAAAAAAAA1AAAAAAAAAHsmuEAAAAAAVqkUQgAAAAAIAAAAAAAAADUAAAAJ6QAAKhF1ALF79gIqEXUAsXv2AgAAvwNVcNyF','distance':0,'location':[7.672106,49.707953],'name':'Untertor'},{'hint':'Bd18gcj0KJAAAAAA3gAAAAAAAAAAAAAAAAAAAMXXGkMAAAAAAAAAAAAAAADeAAAAAAAAAAAAAAAJ6QAAVwV1AAp39gJXBXUACnf2AgAAbxBVcNyF','distance':0,'location':[7.669079,49.706762],'name':'Herzog-Wolfgang-Straße'},{'hint':'besokHPrKJASAAAAAAAAAEEAAAAAAAAA_uJKQQAAAACBDzNCAAAAABIAAAAAAAAAQQAAAAAAAAAJ6QAAsh11ALD79QKyHXUAsPv1AgMATwVVcNyF','distance':0,'location':[7.675314,49.675184],'name':'Vordergasse'}],'destinations':[{'hint':'Bd18gcj0KJAAAAAA3gAAAAAAAAAAAAAAAAAAAMXXGkMAAAAAAAAAAAAAAADeAAAAAAAAAAAAAAAJ6QAAVwV1AAp39gJXBXUACnf2AgAAbxBVcNyF','distance':0,'location':[7.669079,49.706762],'name':'Herzog-Wolfgang-Straße'},{'hint':'nPIokP___38AAAAACAAAAAAAAAA1AAAAAAAAAHsmuEAAAAAAVqkUQgAAAAAIAAAAAAAAADUAAAAJ6QAAKhF1ALF79gIqEXUAsXv2AgAAvwNVcNyF','distance':0,'location':[7.672106,49.707953],'name':'Untertor'},{'hint':'Bd18gcj0KJAAAAAA3gAAAAAAAAAAAAAAAAAAAMXXGkMAAAAAAAAAAAAAAADeAAAAAAAAAAAAAAAJ6QAAVwV1AAp39gJXBXUACnf2AgAAbxBVcNyF','distance':0,'location':[7.669079,49.706762],'name':'Herzog-Wolfgang-Straße'},{'hint':'besokHPrKJASAAAAAAAAAEEAAAAAAAAA_uJKQQAAAACBDzNCAAAAABIAAAAAAAAAQQAAAAAAAAAJ6QAAsh11ALD79QKyHXUAsPv1AgMATwVVcNyF','distance':0,'location':[7.675314,49.675184],'name':'Vordergasse'}]}
        return MockResponse(restext, 200)
    elif args[0] == 'http://router.project-osrm.org/table/v1/driving/7.6690793,49.7067624;7.6721057,49.7079532;7.6690793,49.7067624;7.6721057,49.7079532.json':
        restext={'code':'Ok','durations':[[0,107.9,0,107.9],[159.2,0,159.2,0],[0,107.9,0,107.9],[159.2,0,159.2,0]],'sources':[{'hint':'HTx5gZh__I8AAAAA3gAAAAAAAAAAAAAAAAAAAMXXGkMAAAAAAAAAAAAAAADeAAAAAAAAAAAAAADM6AAAVwV1AAp39gJXBXUACnf2AgAAbxD3hyK-','distance':0,'location':[7.669079,49.706762],'name':'Herzog-Wolfgang-Straße'},{'hint':'0nf8j____38AAAAACAAAAAAAAAA1AAAAAAAAAHsmuEAAAAAAVqkUQgAAAAAIAAAAAAAAADUAAADM6AAAKhF1ALF79gIqEXUAsXv2AgAAvwP3hyK-','distance':0,'location':[7.672106,49.707953],'name':'Untertor'},{'hint':'HTx5gZh__I8AAAAA3gAAAAAAAAAAAAAAAAAAAMXXGkMAAAAAAAAAAAAAAADeAAAAAAAAAAAAAADM6AAAVwV1AAp39gJXBXUACnf2AgAAbxD3hyK-','distance':0,'location':[7.669079,49.706762],'name':'Herzog-Wolfgang-Straße'},{'hint':'0nf8j____38AAAAACAAAAAAAAAA1AAAAAAAAAHsmuEAAAAAAVqkUQgAAAAAIAAAAAAAAADUAAADM6AAAKhF1ALF79gIqEXUAsXv2AgAAvwP3hyK-','distance':0,'location':[7.672106,49.707953],'name':'Untertor'}],'destinations':[{'hint':'HTx5gZh__I8AAAAA3gAAAAAAAAAAAAAAAAAAAMXXGkMAAAAAAAAAAAAAAADeAAAAAAAAAAAAAADM6AAAVwV1AAp39gJXBXUACnf2AgAAbxD3hyK-','distance':0,'location':[7.669079,49.706762],'name':'Herzog-Wolfgang-Straße'},{'hint':'0nf8j____38AAAAACAAAAAAAAAA1AAAAAAAAAHsmuEAAAAAAVqkUQgAAAAAIAAAAAAAAADUAAADM6AAAKhF1ALF79gIqEXUAsXv2AgAAvwP3hyK-','distance':0,'location':[7.672106,49.707953],'name':'Untertor'},{'hint':'HTx5gZh__I8AAAAA3gAAAAAAAAAAAAAAAAAAAMXXGkMAAAAAAAAAAAAAAADeAAAAAAAAAAAAAADM6AAAVwV1AAp39gJXBXUACnf2AgAAbxD3hyK-','distance':0,'location':[7.669079,49.706762],'name':'Herzog-Wolfgang-Straße'},{'hint':'0nf8j____38AAAAACAAAAAAAAAA1AAAAAAAAAHsmuEAAAAAAVqkUQgAAAAAIAAAAAAAAADUAAADM6AAAKhF1ALF79gIqEXUAsXv2AgAAvwP3hyK-','distance':0,'location':[7.672106,49.707953],'name':'Untertor'}]}
        return MockResponse(restext, 200)
    elif args[0] == 'http://router.project-osrm.org/table/v1/driving/7.6690793,49.7067624;7.6721057,49.7079532;7.6690793,49.7067624;7.6721057,49.7079532;7.6690793,49.7067624;7.6721057,49.7079532.json':
        restext={'code':'Ok','durations':[[0,107.9,0,107.9,0,107.9],[159.2,0,159.2,0,159.2,0],[0,107.9,0,107.9,0,107.9],[159.2,0,159.2,0,159.2,0],[0,107.9,0,107.9,0,107.9],[159.2,0,159.2,0,159.2,0]],'sources':[{'hint':'HTx5gZh__I8AAAAA3gAAAAAAAAAAAAAAAAAAAMXXGkMAAAAAAAAAAAAAAADeAAAAAAAAAAAAAADM6AAAVwV1AAp39gJXBXUACnf2AgAAbxD3hyK-','distance':0,'location':[7.669079,49.706762],'name':'Herzog-Wolfgang-Straße'},{'hint':'0nf8j____38AAAAACAAAAAAAAAA1AAAAAAAAAHsmuEAAAAAAVqkUQgAAAAAIAAAAAAAAADUAAADM6AAAKhF1ALF79gIqEXUAsXv2AgAAvwP3hyK-','distance':0,'location':[7.672106,49.707953],'name':'Untertor'},{'hint':'HTx5gZh__I8AAAAA3gAAAAAAAAAAAAAAAAAAAMXXGkMAAAAAAAAAAAAAAADeAAAAAAAAAAAAAADM6AAAVwV1AAp39gJXBXUACnf2AgAAbxD3hyK-','distance':0,'location':[7.669079,49.706762],'name':'Herzog-Wolfgang-Straße'},{'hint':'0nf8j____38AAAAACAAAAAAAAAA1AAAAAAAAAHsmuEAAAAAAVqkUQgAAAAAIAAAAAAAAADUAAADM6AAAKhF1ALF79gIqEXUAsXv2AgAAvwP3hyK-','distance':0,'location':[7.672106,49.707953],'name':'Untertor'},{'hint':'HTx5gZh__I8AAAAA3gAAAAAAAAAAAAAAAAAAAMXXGkMAAAAAAAAAAAAAAADeAAAAAAAAAAAAAADM6AAAVwV1AAp39gJXBXUACnf2AgAAbxD3hyK-','distance':0,'location':[7.669079,49.706762],'name':'Herzog-Wolfgang-Straße'},{'hint':'0nf8j____38AAAAACAAAAAAAAAA1AAAAAAAAAHsmuEAAAAAAVqkUQgAAAAAIAAAAAAAAADUAAADM6AAAKhF1ALF79gIqEXUAsXv2AgAAvwP3hyK-','distance':0,'location':[7.672106,49.707953],'name':'Untertor'}],'destinations':[{'hint':'HTx5gZh__I8AAAAA3gAAAAAAAAAAAAAAAAAAAMXXGkMAAAAAAAAAAAAAAADeAAAAAAAAAAAAAADM6AAAVwV1AAp39gJXBXUACnf2AgAAbxD3hyK-','distance':0,'location':[7.669079,49.706762],'name':'Herzog-Wolfgang-Straße'},{'hint':'0nf8j____38AAAAACAAAAAAAAAA1AAAAAAAAAHsmuEAAAAAAVqkUQgAAAAAIAAAAAAAAADUAAADM6AAAKhF1ALF79gIqEXUAsXv2AgAAvwP3hyK-','distance':0,'location':[7.672106,49.707953],'name':'Untertor'},{'hint':'HTx5gZh__I8AAAAA3gAAAAAAAAAAAAAAAAAAAMXXGkMAAAAAAAAAAAAAAADeAAAAAAAAAAAAAADM6AAAVwV1AAp39gJXBXUACnf2AgAAbxD3hyK-','distance':0,'location':[7.669079,49.706762],'name':'Herzog-Wolfgang-Straße'},{'hint':'0nf8j____38AAAAACAAAAAAAAAA1AAAAAAAAAHsmuEAAAAAAVqkUQgAAAAAIAAAAAAAAADUAAADM6AAAKhF1ALF79gIqEXUAsXv2AgAAvwP3hyK-','distance':0,'location':[7.672106,49.707953],'name':'Untertor'},{'hint':'HTx5gZh__I8AAAAA3gAAAAAAAAAAAAAAAAAAAMXXGkMAAAAAAAAAAAAAAADeAAAAAAAAAAAAAADM6AAAVwV1AAp39gJXBXUACnf2AgAAbxD3hyK-','distance':0,'location':[7.669079,49.706762],'name':'Herzog-Wolfgang-Straße'},{'hint':'0nf8j____38AAAAACAAAAAAAAAA1AAAAAAAAAHsmuEAAAAAAVqkUQgAAAAAIAAAAAAAAADUAAADM6AAAKhF1ALF79gIqEXUAsXv2AgAAvwP3hyK-','distance':0,'location':[7.672106,49.707953],'name':'Untertor'}]}
        return MockResponse(restext, 200)
    elif args[0] == 'http://router.project-osrm.org/route/v1/driving/7.6690793,49.7067624;7.6690793,49.7067624;7.6721057,49.7079532;7.6753142,49.6751843.json':
        # intern wird 'http://router.project-osrm.org/route/v1/driving/...,49.6751843?annotations=true&geometries=geojson' abgefragt
        restext={'code':'Ok','routes':[{'geometry':{'coordinates':[[7.669079,49.706762],[7.669079,49.706762],[7.66925,49.705518],[7.672376,49.70538],[7.672106,49.707953],[7.672525,49.708219],[7.670832,49.709186],[7.669455,49.708793],[7.668121,49.709624],[7.666363,49.70972],[7.667378,49.708908],[7.667066,49.708423],[7.668896,49.707088],[7.66925,49.705518],[7.670304,49.704216],[7.669369,49.703384],[7.666992,49.702531],[7.666719,49.701736],[7.665861,49.701128],[7.665777,49.699544],[7.664537,49.699032],[7.66327,49.696913],[7.664432,49.694387],[7.66581,49.693137],[7.66959,49.693403],[7.671307,49.692207],[7.672165,49.68919],[7.672184,49.685665],[7.671744,49.68448],[7.669754,49.683028],[7.669729,49.682461],[7.670031,49.681756],[7.67093,49.681005],[7.671519,49.678996],[7.673586,49.677656],[7.673677,49.675924],[7.674529,49.675108],[7.675314,49.675184]],'type':'LineString'},'legs':[{'steps':[],'summary':'','weight':0,'duration':0,'annotation':{'metadata':{'datasource_names':['lua profile']},'datasources':[0],'weight':[0],'nodes':[8926366194,929163070],'distance':[0],'duration':[0],'speed':[0]},'distance':0},{'steps':[],'summary':'','weight':107.9,'duration':107.9,'annotation':{'metadata':{'datasource_names':['lua profile']},'datasources':[0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0],'weight':[0,2,1.4,1.4,3.8,0.6,1.1,1.5,1.6,6.9,0.7,4.1,2.7,2.8,7,2.3,9.1,1.4,1.2,0.9,0.5,0.6,2.7,0.5,5.4,0.9,1.2,4.2,0.5,1.9,6.8,2,2.3,3.4,5.6,1,0.9,1.1,0],\
            'nodes':[8926366194,929163070,293644800,3372775732,2071420730,3372775724,9019012086,2071420729,3372775723,293644809,293644732,301617177,1374244356,2178713942,1236586376,288942571,2178713931,288942564,3883853507,3883853506,1236586933,3883853508,3883853509,1866098314,288942563,2713716110,2177696446,288942562,2715125060,2177696450,1866099465,288942576,2713696116,2178714204,1236586381,1236586602,3883853537,2177696510,288942560,2183660825],'distance':[0,13.705236,9.683369,9.507716,26.117089,4.117887,7.902307,10.36004,11.134995,47.965875,7.819434,28.238242,18.893336,19.638639,48.431373,16.084164,63.449551,9.711349,8.50452,6.273885,3.46396,4.121027,19.068738,3.562148,37.250007,6.132652,8.402537,29.378629,3.559968,13.020632,46.949898,13.971151,16.15185,23.416038,39.183624,7.222742,6.358125,7.934235,0],'duration':[0,2,1.4,1.4,3.8,0.6,1.1,1.5,1.6,6.9,0.7,4.1,2.7,2.8,7,2.3,9.1,1.4,1.2,0.9,0.5,0.6,2.7,0.5,5.4,0.9,1.2,4.2,0.5,1.9,6.8,2,2.3,3.4,5.6,1,0.9,1.1,0],'speed':[0,6.9,6.9,6.8,6.9,6.9,7.2,6.9,7,7,11.2,6.9,7,7,6.9,7,7,6.9,7.1,7,6.9,6.9,7.1,7.1,6.9,6.8,7,7,7.1,6.9,6.9,7,7,6.9,7,7.2,7.1,7.2,7.2]},'distance':656.7},{'steps':[],'summary':'','weight':571.8,'duration':571.8,'annotation':{'metadata':{'datasource_names':['lua profile']},\
                'datasources':[0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0],'weight':[0.8,1.4,1.3,0.9,1,0.7,6.3,4.5,2.1,3.6,4.6,2.5,0.9,0.8,0.7,1.4,1.2,1.3,9.7,13.8,3.3,2.1,1.1,1.1,1.2,11.3,1.3,1.2,1.3,1.9,1.3,1.4,10.5,1,0.9,0.8,0.8,0.9,3.4,0.8,0.7,1,0.8,0.8,1.2,2.2,1.5,1.3,4.9,3.3,3.1,1.7,2.4,1,3.4,2.1,5.6,2,1.4,1.4,3.8,0.6,1.1,1.5,1.6,6.9,0.7,1.5,1.4,0.2,1.9,1,2,0.6,1.2,1.2,0.8,0.6,0.6,0.6,0.6,1,1.1,0.9,1,0.8,0.9,1.2,1.3,1.2,2.1,1.4,1.5,1.3,1.1,1.1,1.3,1.1,1,0.9,0.9,1,0.8,1,0.7,0.9,0.6,0.5,0.8,0.7,0.7,0.7,0.8,0.8,0.9,0.7,1.4,1.5,0.8,0.8,1.7,1.6,1.6,1,0.8,0.7,0.8,2.5,3.2,6.2,0.8,0.9,0.8,0.7,0.7,0.7,0.9,1,2,0.9,0.7,0.7,0.7,0.8,1.1,6.6,11.2,1.6,0.8,0.7,0.8,1.1,2,1.8,2.3,5.6,5.5,6.6,1.7,2.1,6.3,5,2,0.9,0.6,1,1.4,9.7,6.1,0.6,2.8,0.8,0.9,0.8,0.8,1,1.2,7.5,0.5,2.1,1.3,1.6,1.5,2.4,2.7,7.1,5.5,9.7,1.8,5.3,3.2,3.6,2.9,1.4,1.2,2.5,2.2,2,1.9,3.4,3.9,1.9,1.9,1.9,1.7,1.4,1.4,1.3,1.3,1.4,1.2,1.2,1.1,0.9,4.5,4.7,1,3,0.6,0.6,0.7,0.7,0.7,0.7,1.1,1.2,1.3,1.2,2.4,3,0.7,0.6,0.7,0.9,2.2,0.8,1.1,1.1,1.1,1.2,1.1,7.7,10.1,0.9,0.7,0.7,10.2,1,0.9,3.3,0.7,0.7,0.8,0.9,0.8,0.7,0.8,3.3,2.9,3,1.6,0.7,1.1,0.9,0.7,0.9,1.7,3.5,0.5,0.5,0.8,1.4,0.8,0.7,1.3,2.5,2.7,1.8],'nodes':[288942560,2183660825,2178714284,2180223776,2177696529,2713713507,481103604,481103605,2471880276,691760168,481103610,2071420737,1236586672,2177696651,3390153884,481103606,3390153883,1236586545,3390153882,481103607,285323454,3883853552,285323485,288941559,3883853554,1236586318,288941557,3883853556,288941556,288939733,2071420739,3883853553,2071420738,3883853551,293644749,3883853550,293644753,3883853549,293644755,293644757,3883853547,293644764,3883853544,293644767,3358928041,2071420734,293644774,3358928040,2071420732,9019022420,293644781,9019022432,2177696485,2071420731,9019012113,9177742195,293644791,929163070,293644800,3372775732,2071420730,3372775724,9019012086,2071420729,3372775723,293644809,293644732,301617177,1374244354,2180223775,2713557887,2180223773,301617182,3786394355,301617183,301617184,301617185,3709250250,301617186,3709250244,301617188,3709262132,3709262131,301617189,3709250232,301617190,3709250225,301617191,301617192,3709250210,301617193,301617194,3372092234,301617195,3372092233,301617196,3372092232,301617197,3372092231,301617198,3372092230,301617199,3372092229,301617200,3372092228,301617201,3372092227,301617202,2178158730,301617203,3372092225,2178158726,3709411052,1236586409,3372092223,3709411050,3372092221,9473747044,301617207,3372092220,301617208,301617209,2178158701,301617210,2178158695,301617212,3372092219,301617213,301617215,301617216,301617219,3372092211,301617220,1236586661,3372092204,419023256,3372092199,419023255,3372092195,1236587162,3372090591,419023254,3372090589,1236586329,3372090586,419023253,1236586571,419023252,1236586827,3085160297,6804706968,1236587084,3085160294,419023251,6804706967,6804706966,419023250,2205069784,419023249,1236586234,6804706965,419023248,419023246,419023245,2205069756,419023244,2205069755,419023243,419023242,2988722705,419023241,1236586718,2991673414,419023240,2991673412,1236586401,2991673413,419023239,3084960475,2991673411,419023237,1236587145,2991673410,419023236,2991673409,2991673408,2991673407,419023234,419023233,2991673406,2991673404,2991673405,419023232,2991673403,3786900162,324295323,3786900159,3786900158,324295318,3786899256,324295314,3786899247,3786899246,324295477,3786899245,324295308,2071420628,3786899228,3786899227,324295302,3163894774,2071420623,3163894771,324295300,3786899226,324295296,324295182,6804706964,2071420607,324295180,3163894767,2071420600,324295178,3786899221,3163894763,3786899219,3786899218,324295177,3786899214,324295327,2929243658,3786899213,1602531305,324295330,3786899211,3786899210,2071420587,2071420584,3163893858,324295335,2071420573,324295339,324295341,3786899192,324295348,3786899190,324295352,324295355,3786899184,2725029526,2725029525,3785121885,324295357,3785121884,2725029524,3785121883,324295364,3785121882,3785121881,324295367,2724964918,2724964916,2724964915,324295371,3784077645,3052164065,2724964905,2724964903,3784077644,3829778746,324295375,2724964899,2724964897,3784077641,1258711432,2725029521,1258713033,2725029522,1258712074],\
                    'distance':[5.744114,9.971338,9.092015,6.338403,7.096283,4.624273,43.567593,31.080465,14.533395,25.117508,31.822742,17.246354,6.545718,5.279997,5.094693,9.665317,8.435903,8.765333,67.549529,96.028573,22.875413,14.36413,7.566249,7.306112,8.605301,78.736802,9.145381,8.594487,8.742202,13.127548,8.707975,9.394609,72.820204,6.871313,6.336938,5.555853,5.709359,6.099189,23.933706,5.325846,4.746669,7.079242,5.782061,5.72766,8.376793,15.064832,10.51545,9.173802,34.070931,23.143822,21.20888,11.792094,16.410485,7.060129,23.754252,14.914034,38.575118,13.705236,9.683369,9.507716,26.117089,4.117887,7.902307,10.36004,11.134995,47.965875,7.819434,16.227762,15.764975,2.209694,21.394054,10.729053,22.087573,6.871563,13.714857,13.787906,8.418629,7.192523,6.301196,6.692547,6.288202,10.654523,12.314233,9.797457,11.079154,9.309836,9.687397,13.341203,14.481818,13.875393,23.705427,15.514339,16.255733,14.316335,12.433287,12.333268,14.272056,12.636348,10.794186,10.503864,9.996898,11.2462,8.728238,11.357754,8.034348,10.252166,6.635196,5.287339,8.968535,8.144523,8.007342,7.510611,8.579216,9.011915,9.587347,8.190907,15.458082,17.082614,9.158223,9.028208,19.415223,17.426195,18.045546,10.565247,8.738261,7.558029,9.091955,27.925308,35.151118,69.212077,9.127647,10.103256,9.02642,7.818264,8.009759,7.468559,9.556179,11.466437,22.670594,10.343706,7.427481,8.04249,7.564535,9.404983,11.906378,73.456169,124.475658,18.208819,8.62863,7.975005,8.588867,12.154367,22.224874,19.658675,25.257813,61.971739,60.999968,73.067186,18.420507,23.014414,70.165041,55.998289,21.904102,9.807328,6.785018,10.767228,16.019753,107.998409,67.409704,7.156447,31.553767,9.428046,10.139229,8.523302,8.593854,11.308449,13.185372,82.82452,5.382893,23.438819,14.190666,17.326125,16.726351,26.427904,30.510067,78.710505,61.062797,108.140162,19.847488,59.188846,35.507521,39.826882,31.703497,15.905361,13.01666,27.23673,24.960477,21.696767,21.355935,37.915676,43.020347,21.308599,20.594784,21.038944,19.050236,15.299355,15.617942,14.919711,14.007278,15.712759,13.480161,13.521701,12.204384,10.473445,49.579874,52.60799,11.260443,33.725255,6.702526,7.172772,7.232977,7.755382,8.286513,8.009587,12.235105,13.033361,14.56221,13.203996,27.144689,33.051273,8.069148,6.774022,7.314216,10.51103,24.230738,8.470837,12.322069,12.04175,12.332162,12.923543,12.074602,85.959747,111.780627,9.784061,8.285355,7.380068,112.847462,11.044048,10.156818,36.692961,7.953434,7.616061,8.855651,9.798289,8.348828,7.529957,9.121692,36.945083,32.536166,33.148251,17.935762,7.785841,12.464829,9.643402,8.275841,10.53876,19.087263,39.223775,5.619885,5.949352,9.01277,15.833154,8.450646,7.48259,8.936872,17.14637,18.559855,12.644949],'duration':[0.8,1.4,1.3,0.9,1,0.7,6.3,4.5,2.1,3.6,4.6,2.5,0.9,0.8,0.7,1.4,1.2,1.3,9.7,13.8,3.3,2.1,1.1,1.1,1.2,11.3,1.3,1.2,1.3,1.9,1.3,1.4,10.5,1,0.9,0.8,0.8,0.9,3.4,0.8,0.7,1,0.8,0.8,1.2,2.2,1.5,1.3,4.9,3.3,3.1,1.7,2.4,1,3.4,2.1,5.6,2,1.4,1.4,3.8,0.6,1.1,1.5,1.6,6.9,0.7,1.5,1.4,0.2,1.9,1,2,0.6,1.2,1.2,0.8,0.6,0.6,0.6,0.6,1,1.1,0.9,1,0.8,0.9,1.2,1.3,1.2,2.1,1.4,1.5,1.3,1.1,1.1,1.3,1.1,1,0.9,0.9,1,0.8,1,0.7,0.9,0.6,0.5,0.8,0.7,0.7,0.7,0.8,0.8,0.9,0.7,1.4,1.5,0.8,0.8,1.7,1.6,1.6,1,0.8,0.7,0.8,2.5,3.2,6.2,0.8,0.9,0.8,0.7,0.7,0.7,0.9,1,2,0.9,0.7,0.7,0.7,0.8,1.1,6.6,11.2,1.6,0.8,0.7,0.8,1.1,2,1.8,2.3,5.6,5.5,6.6,1.7,2.1,6.3,5,2,0.9,0.6,1,1.4,9.7,6.1,0.6,2.8,0.8,0.9,0.8,0.8,1,1.2,7.5,0.5,2.1,1.3,1.6,1.5,2.4,2.7,7.1,5.5,9.7,1.8,5.3,3.2,3.6,2.9,1.4,1.2,2.5,2.2,2,1.9,3.4,3.9,1.9,1.9,1.9,1.7,1.4,1.4,1.3,1.3,1.4,1.2,1.2,1.1,0.9,4.5,4.7,1,3,0.6,0.6,0.7,0.7,0.7,0.7,1.1,1.2,1.3,1.2,2.4,3,0.7,0.6,0.7,0.9,2.2,0.8,1.1,1.1,1.1,1.2,1.1,7.7,10.1,0.9,0.7,0.7,10.2,1,0.9,3.3,0.7,0.7,0.8,0.9,0.8,0.7,0.8,3.3,2.9,3,1.6,0.7,1.1,0.9,0.7,0.9,1.7,3.5,0.5,0.5,0.8,1.4,0.8,0.7,1.3,2.5,2.7,1.8],'speed':[7.2,7.1,7,7,7.1,6.6,6.9,6.9,6.9,7,6.9,6.9,7.3,6.6,7.3,6.9,7,6.7,7,7,6.9,6.8,6.9,6.6,7.2,7,7,7.2,6.7,6.9,6.7,6.7,6.9,6.9,7,6.9,7.1,6.8,7,6.7,6.8,7.1,7.2,7.2,7,6.8,7,7.1,7,7,6.8,6.9,6.8,7.1,7,7.1,6.9,6.9,6.9,6.8,6.9,6.9,7.2,6.9,7,7,11.2,10.8,11.3,11,11.3,10.7,11,11.5,11.4,11.5,10.5,12,10.5,11.2,10.5,10.7,11.2,10.9,11.1,11.6,10.8,11.1,11.1,11.6,11.3,11.1,10.8,11,11.3,11.2,11,11.5,10.8,11.7,11.1,11.2,10.9,11.4,11.5,11.4,11.1,10.6,11.2,11.6,11.4,10.7,10.7,11.3,10.7,11.7,11,11.4,11.4,11.3,11.4,10.9,11.3,10.6,10.9,10.8,11.4,11.2,11,11.2,11.4,11.2,11.3,11.2,11.4,10.7,10.6,11.5,11.3,11.5,10.6,11.5,10.8,11.8,10.8,11.1,11.1,11.4,10.8,11.4,10.7,11,11.1,10.9,11,11.1,11.1,11.1,10.8,11,11.1,11.2,11,10.9,11.3,10.8,11.4,11.1,11.1,11.9,11.3,11.8,11.3,10.7,10.7,11.3,11,11,10.8,11.2,10.9,10.8,11.2,11,11.3,11.1,11.1,11.1,11,11.2,11.1,11.1,10.9,11.4,10.8,10.9,11.3,10.8,11.2,11.2,11,11.2,10.8,11.1,11.2,10.9,11.2,11.5,10.8,11.2,11.2,11.3,11.1,11.6,11,11.2,11.3,11.2,11.2,12,10.3,11.1,11.8,11.4,11.1,10.9,11.2,11,11.3,11,11.5,11.3,10.4,11.7,11,10.6,11.2,10.9,11.2,10.8,11,11.2,11.1,10.9,11.8,10.5,11.1,11,11.3,11.1,11.4,10.9,11.1,10.9,10.4,10.8,11.4,11.2,11.2,11,11.2,11.1,11.3,10.7,11.8,11.7,11.2,11.2,11.2,11.9,11.3,11.3,10.6,10.7,6.9,6.9,6.9,7]},'distance':5428.4}],\
                        'weight_name':'routability','weight':679.7,'duration':679.7,'distance':6085.1}],'waypoints':[{'hint':'QaBXgiAawI8AAAAA3gAAAAAAAAAAAAAAAAAAAMXXGkMAAAAAAAAAAAAAAADeAAAAAAAAAAAAAAC57AAAVwV1AAp39gJXBXUACnf2AgAAbxAJMyRJ','distance':0,'name':'Herzog-Wolfgang-Straße','location':[7.669079,49.706762]},{'hint':'QaBXgiAawI8AAAAA3gAAAAAAAAAAAAAAAAAAAMXXGkMAAAAAAAAAAAAAAADeAAAAAAAAAAAAAAC57AAAVwV1AAp39gJXBXUACnf2AgAAbxAJMyRJ','distance':0,'name':'Herzog-Wolfgang-Straße','location':[7.669079,49.706762]},{'hint':'eQ7AgP___38AAAAACAAAAAAAAAA1AAAAAAAAAHsmuEAAAAAAVqkUQgAAAAAIAAAAAAAAADUAAAC57AAAKhF1ALF79gIqEXUAsXv2AgAAvwMJMyRJ','distance':0,'name':'Untertor','location':[7.672106,49.707953]},{'hint':'SM0Kg43NCoMSAAAAAAAAAEEAAAAAAAAA_uJKQQAAAACBDzNCAAAAABIAAAAAAAAAQQAAAAAAAAC57AAAsh11ALD79QKyHXUAsPv1AgMATwUJMyRJ','distance':0,'name':'Vordergasse','location':[7.675314,49.675184]}]}
        return MockResponse(restext, 200)
    elif args[0] == 'http://router.project-osrm.org/route/v1/driving/7.6690793,49.7067624;7.6690793,49.7067624;7.6721057,49.7079532.json':
        # intern wird 'http://router.project-osrm.org/route/v1/driving/...,49.6751843?annotations=true&geometries=geojson' abgefragt
        restext={'code':'Ok','routes':[{'geometry':{'coordinates':[[7.669079,49.706762],[7.669079,49.706762],[7.66912,49.706554],[7.669063,49.706035],[7.66925,49.705518],[7.67001,49.705567],[7.670955,49.705542],[7.672376,49.70538],[7.672403,49.705444],[7.672304,49.706524],[7.672319,49.706946],[7.672259,49.707214],[7.672214,49.707776],[7.672106,49.707953]],'type':'LineString'},'legs':[{'steps':[],'summary':'','weight':0,'duration':0,'annotation':{'metadata':{'datasource_names':['lua profile']},'datasources':[0],'weight':[0],'nodes':[8926366194,929163070],'distance':[0],'duration':[0],'speed':[0]},'distance':0},{'steps':[],'summary':'','weight':107.9,'duration':107.9,'annotation':{'metadata':{'datasource_names':['lua profile']},'datasources':[0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0],'weight':[0,2,1.4,1.4,3.8,0.6,1.1,1.5,1.6,6.9,0.7,4.1,2.7,2.8,7,2.3,9.1,1.4,1.2,0.9,0.5,0.6,2.7,0.5,5.4,0.9,1.2,4.2,0.5,1.9,6.8,2,2.3,3.4,5.6,1,0.9,1.1,0],'nodes':[8926366194,929163070,293644800,3372775732,2071420730,3372775724,9019012086,2071420729,3372775723,293644809,293644732,301617177,1374244356,2178713942,1236586376,288942571,2178713931,288942564,3883853507,3883853506,1236586933,3883853508,3883853509,1866098314,288942563,2713716110,2177696446,288942562,2715125060,2177696450,1866099465,288942576,2713696116,2178714204,1236586381,1236586602,3883853537,2177696510,288942560,2183660825],'distance':[0,13.705236,9.683369,9.507716,26.117089,4.117887,7.902307,10.36004,11.134995,47.965875,7.819434,28.238242,18.893336,19.638639,48.431373,16.084164,63.449551,9.711349,8.50452,6.273885,3.46396,4.121027,19.068738,3.562148,37.250007,6.132652,8.402537,29.378629,3.559968,13.020632,46.949898,13.971151,16.15185,23.416038,39.183624,7.222742,6.358125,7.934235,0],'duration':[0,2,1.4,1.4,3.8,0.6,1.1,1.5,1.6,6.9,0.7,4.1,2.7,2.8,7,2.3,9.1,1.4,1.2,0.9,0.5,0.6,2.7,0.5,5.4,0.9,1.2,4.2,0.5,1.9,6.8,2,2.3,3.4,5.6,1,0.9,1.1,0],'speed':[0,6.9,6.9,6.8,6.9,6.9,7.2,6.9,7,7,11.2,6.9,7,7,6.9,7,7,6.9,7.1,7,6.9,6.9,7.1,7.1,6.9,6.8,7,7,7.1,6.9,6.9,7,7,6.9,7,7.2,7.1,7.2,7.2]},'distance':656.7}],'weight_name':'routability','weight':107.9,'duration':107.9,'distance':656.7}],'waypoints':[{'hint':'QaBXgiAawI8AAAAA3gAAAAAAAAAAAAAAAAAAAMXXGkMAAAAAAAAAAAAAAADeAAAAAAAAAAAAAAC57AAAVwV1AAp39gJXBXUACnf2AgAAbxAJMyRJ','distance':0,'name':'Herzog-Wolfgang-Straße','location':[7.669079,49.706762]},{'hint':'QaBXgiAawI8AAAAA3gAAAAAAAAAAAAAAAAAAAMXXGkMAAAAAAAAAAAAAAADeAAAAAAAAAAAAAAC57AAAVwV1AAp39gJXBXUACnf2AgAAbxAJMyRJ','distance':0,'name':'Herzog-Wolfgang-Straße','location':[7.669079,49.706762]},{'hint':'eQ7AgP___38AAAAACAAAAAAAAAA1AAAAAAAAAHsmuEAAAAAAVqkUQgAAAAAIAAAAAAAAADUAAAC57AAAKhF1ALF79gIqEXUAsXv2AgAAvwMJMyRJ','distance':0,'name':'Untertor','location':[7.672106,49.707953]}]}
        return MockResponse(restext, 200)
    elif args[0] == 'http://router.project-osrm.org/route/v1/driving/7.6690793,49.7067624;7.6721057,49.7079532;7.6753142,49.6751843.json':
        # intern wird 'http://router.project-osrm.org/route/v1/driving/...,49.6751843?annotations=true&geometries=geojson' abgefragt
        restext={'code':'Ok','routes':[{'geometry':{'coordinates':[[7.669079,49.706762],[7.66925,49.705518],[7.672376,49.70538],[7.672106,49.707953],[7.672525,49.708219],[7.670832,49.709186],[7.669455,49.708793],[7.668121,49.709624],[7.666363,49.70972],[7.667378,49.708908],[7.667066,49.708423],[7.668896,49.707088],[7.66925,49.705518],[7.670304,49.704216],[7.669369,49.703384],[7.666992,49.702531],[7.666719,49.701736],[7.665861,49.701128],[7.665777,49.699544],[7.664537,49.699032],[7.66327,49.696913],[7.664432,49.694387],[7.66581,49.693137],[7.66959,49.693403],[7.671307,49.692207],[7.672165,49.68919],[7.672184,49.685665],[7.671744,49.68448],[7.669754,49.683028],[7.669729,49.682461],[7.670031,49.681756],[7.67093,49.681005],[7.671519,49.678996],[7.673586,49.677656],[7.673677,49.675924],[7.674529,49.675108],[7.675314,49.675184]],'type':'LineString'},'legs':[{'steps':[],'summary':'','weight':107.9,'duration':107.9,'annotation':{'metadata':{'datasource_names':['lua profile']},'datasources':[0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0],'weight':[0,2,1.4,1.4,3.8,0.6,1.1,1.5,1.6,6.9,0.7,4.1,2.7,2.8,7,2.3,9.1,1.4,1.2,0.9,0.5,0.6,2.7,0.5,5.4,0.9,1.2,4.2,0.5,1.9,6.8,2,2.3,3.4,5.6,1,0.9,1.1,0],'nodes':[8926366194,929163070,293644800,3372775732,2071420730,3372775724,9019012086,2071420729,3372775723,293644809,293644732,301617177,1374244356,2178713942,1236586376,288942571,2178713931,288942564,3883853507,3883853506,1236586933,3883853508,3883853509,1866098314,288942563,2713716110,2177696446,288942562,2715125060,2177696450,1866099465,288942576,2713696116,2178714204,1236586381,1236586602,3883853537,2177696510,288942560,2183660825],'distance':[0,13.705236,9.683369,9.507716,26.117089,4.117887,7.902307,10.36004,11.134995,47.965875,7.819434,28.238242,18.893336,19.638639,48.431373,16.084164,63.449551,9.711349,8.50452,6.273885,3.46396,4.121027,19.068738,3.562148,37.250007,6.132652,8.402537,29.378629,3.559968,13.020632,46.949898,13.971151,16.15185,23.416038,39.183624,7.222742,6.358125,7.934235,0],'duration':[0,2,1.4,1.4,3.8,0.6,1.1,1.5,1.6,6.9,0.7,4.1,2.7,2.8,7,2.3,9.1,1.4,1.2,0.9,0.5,0.6,2.7,0.5,5.4,0.9,1.2,4.2,0.5,1.9,6.8,2,2.3,3.4,5.6,1,0.9,1.1,0],'speed':[0,6.9,6.9,6.8,6.9,6.9,7.2,6.9,7,7,11.2,6.9,7,7,6.9,7,7,6.9,7.1,7,6.9,6.9,7.1,7.1,6.9,6.8,7,7,7.1,6.9,6.9,7,7,6.9,7,7.2,7.1,7.2,7.2]},'distance':656.7},\
            {'steps':[],'summary':'','weight':571.8,'duration':571.8,'annotation':{'metadata':{'datasource_names':['lua profile']},'datasources':[0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0],'weight':[0.8,1.4,1.3,0.9,1,0.7,6.3,4.5,2.1,3.6,4.6,2.5,0.9,0.8,0.7,1.4,1.2,1.3,9.7,13.8,3.3,2.1,1.1,1.1,1.2,11.3,1.3,1.2,1.3,1.9,1.3,1.4,10.5,1,0.9,0.8,0.8,0.9,3.4,0.8,0.7,1,0.8,0.8,1.2,2.2,1.5,1.3,4.9,3.3,3.1,1.7,2.4,1,3.4,2.1,5.6,2,1.4,1.4,3.8,0.6,1.1,1.5,1.6,6.9,0.7,1.5,1.4,0.2,1.9,1,2,0.6,1.2,1.2,0.8,0.6,0.6,0.6,0.6,1,1.1,0.9,1,0.8,0.9,1.2,1.3,1.2,2.1,1.4,1.5,1.3,1.1,1.1,1.3,1.1,1,0.9,0.9,1,0.8,1,0.7,0.9,0.6,0.5,0.8,0.7,0.7,0.7,0.8,0.8,0.9,0.7,1.4,1.5,0.8,0.8,1.7,1.6,1.6,1,0.8,0.7,0.8,2.5,3.2,6.2,0.8,0.9,0.8,0.7,0.7,0.7,0.9,1,2,0.9,0.7,0.7,0.7,0.8,1.1,6.6,11.2,1.6,0.8,0.7,0.8,1.1,2,1.8,2.3,5.6,5.5,6.6,1.7,2.1,6.3,5,2,0.9,0.6,1,1.4,9.7,6.1,0.6,2.8,0.8,0.9,0.8,0.8,1,1.2,7.5,0.5,2.1,1.3,1.6,1.5,2.4,2.7,7.1,5.5,9.7,1.8,5.3,3.2,3.6,2.9,1.4,1.2,2.5,2.2,2,1.9,3.4,3.9,1.9,1.9,1.9,1.7,1.4,1.4,1.3,1.3,1.4,1.2,1.2,1.1,0.9,4.5,4.7,1,3,0.6,0.6,0.7,0.7,0.7,0.7,1.1,1.2,1.3,1.2,2.4,3,0.7,0.6,0.7,0.9,2.2,0.8,1.1,1.1,1.1,1.2,1.1,7.7,10.1,0.9,0.7,0.7,10.2,1,0.9,3.3,0.7,0.7,0.8,0.9,0.8,0.7,0.8,3.3,2.9,3,1.6,0.7,1.1,0.9,0.7,0.9,1.7,3.5,0.5,0.5,0.8,1.4,0.8,0.7,1.3,2.5,2.7,1.8],\
                'nodes':[288942560,2183660825,2178714284,2180223776,2177696529,2713713507,481103604,481103605,2471880276,691760168,481103610,2071420737,1236586672,2177696651,3390153884,481103606,3390153883,1236586545,3390153882,481103607,285323454,3883853552,285323485,288941559,3883853554,1236586318,288941557,3883853556,288941556,288939733,2071420739,3883853553,2071420738,3883853551,293644749,3883853550,293644753,3883853549,293644755,293644757,3883853547,293644764,3883853544,293644767,3358928041,2071420734,293644774,3358928040,2071420732,9019022420,293644781,9019022432,2177696485,2071420731,9019012113,9177742195,293644791,929163070,293644800,3372775732,2071420730,3372775724,9019012086,2071420729,3372775723,293644809,293644732,301617177,1374244354,2180223775,2713557887,2180223773,301617182,3786394355,301617183,301617184,301617185,3709250250,301617186,3709250244,301617188,3709262132,3709262131,301617189,3709250232,301617190,3709250225,301617191,301617192,3709250210,301617193,301617194,3372092234,301617195,3372092233,301617196,3372092232,301617197,3372092231,301617198,3372092230,301617199,3372092229,301617200,3372092228,301617201,3372092227,301617202,2178158730,301617203,3372092225,2178158726,3709411052,1236586409,3372092223,3709411050,3372092221,9473747044,301617207,3372092220,301617208,301617209,2178158701,301617210,2178158695,301617212,3372092219,301617213,301617215,301617216,301617219,3372092211,301617220,1236586661,3372092204,419023256,3372092199,419023255,3372092195,1236587162,3372090591,419023254,3372090589,1236586329,3372090586,419023253,1236586571,419023252,1236586827,3085160297,6804706968,1236587084,3085160294,419023251,6804706967,6804706966,419023250,2205069784,419023249,1236586234,6804706965,419023248,419023246,419023245,2205069756,419023244,2205069755,419023243,419023242,2988722705,419023241,1236586718,2991673414,419023240,2991673412,1236586401,2991673413,419023239,3084960475,2991673411,419023237,1236587145,2991673410,419023236,2991673409,2991673408,2991673407,419023234,419023233,2991673406,2991673404,2991673405,419023232,2991673403,3786900162,324295323,3786900159,3786900158,324295318,3786899256,324295314,3786899247,3786899246,324295477,3786899245,324295308,2071420628,3786899228,3786899227,324295302,3163894774,2071420623,3163894771,324295300,3786899226,324295296,324295182,6804706964,2071420607,324295180,3163894767,2071420600,324295178,3786899221,3163894763,3786899219,3786899218,324295177,3786899214,324295327,2929243658,3786899213,1602531305,324295330,3786899211,3786899210,2071420587,2071420584,3163893858,324295335,2071420573,324295339,324295341,3786899192,324295348,3786899190,324295352,324295355,3786899184,2725029526,2725029525,3785121885,324295357,3785121884,2725029524,3785121883,324295364,3785121882,3785121881,324295367,2724964918,2724964916,2724964915,324295371,3784077645,3052164065,2724964905,2724964903,3784077644,3829778746,324295375,2724964899,2724964897,3784077641,1258711432,2725029521,1258713033,2725029522,1258712074],\
                    'distance':[5.744114,9.971338,9.092015,6.338403,7.096283,4.624273,43.567593,31.080465,14.533395,25.117508,31.822742,17.246354,6.545718,5.279997,5.094693,9.665317,8.435903,8.765333,67.549529,96.028573,22.875413,14.36413,7.566249,7.306112,8.605301,78.736802,9.145381,8.594487,8.742202,13.127548,8.707975,9.394609,72.820204,6.871313,6.336938,5.555853,5.709359,6.099189,23.933706,5.325846,4.746669,7.079242,5.782061,5.72766,8.376793,15.064832,10.51545,9.173802,34.070931,23.143822,21.20888,11.792094,16.410485,7.060129,23.754252,14.914034,38.575118,13.705236,9.683369,9.507716,26.117089,4.117887,7.902307,10.36004,11.134995,47.965875,7.819434,16.227762,15.764975,2.209694,21.394054,10.729053,22.087573,6.871563,13.714857,13.787906,8.418629,7.192523,6.301196,6.692547,6.288202,10.654523,12.314233,9.797457,11.079154,9.309836,9.687397,13.341203,14.481818,13.875393,23.705427,15.514339,16.255733,14.316335,12.433287,12.333268,14.272056,12.636348,10.794186,10.503864,9.996898,11.2462,8.728238,11.357754,8.034348,10.252166,6.635196,5.287339,8.968535,8.144523,8.007342,7.510611,8.579216,9.011915,9.587347,8.190907,15.458082,17.082614,9.158223,9.028208,19.415223,17.426195,18.045546,10.565247,8.738261,7.558029,9.091955,27.925308,35.151118,69.212077,9.127647,10.103256,9.02642,7.818264,8.009759,7.468559,9.556179,11.466437,22.670594,10.343706,7.427481,8.04249,7.564535,9.404983,11.906378,73.456169,124.475658,18.208819,8.62863,7.975005,8.588867,12.154367,22.224874,19.658675,25.257813,61.971739,60.999968,73.067186,18.420507,23.014414,70.165041,55.998289,21.904102,9.807328,6.785018,10.767228,16.019753,107.998409,67.409704,7.156447,31.553767,9.428046,10.139229,8.523302,8.593854,11.308449,13.185372,82.82452,5.382893,23.438819,14.190666,17.326125,16.726351,26.427904,30.510067,78.710505,61.062797,108.140162,19.847488,59.188846,35.507521,39.826882,31.703497,15.905361,13.01666,27.23673,24.960477,21.696767,21.355935,37.915676,43.020347,21.308599,20.594784,21.038944,19.050236,15.299355,15.617942,14.919711,14.007278,15.712759,13.480161,13.521701,12.204384,10.473445,49.579874,52.60799,11.260443,33.725255,6.702526,7.172772,7.232977,7.755382,8.286513,8.009587,12.235105,13.033361,14.56221,13.203996,27.144689,33.051273,8.069148,6.774022,7.314216,10.51103,24.230738,8.470837,12.322069,12.04175,12.332162,12.923543,12.074602,85.959747,111.780627,9.784061,8.285355,7.380068,112.847462,11.044048,10.156818,36.692961,7.953434,7.616061,8.855651,9.798289,8.348828,7.529957,9.121692,36.945083,32.536166,33.148251,17.935762,7.785841,12.464829,9.643402,8.275841,10.53876,19.087263,39.223775,5.619885,5.949352,9.01277,15.833154,8.450646,7.48259,8.936872,17.14637,18.559855,12.644949],'duration':[0.8,1.4,1.3,0.9,1,0.7,6.3,4.5,2.1,3.6,4.6,2.5,0.9,0.8,0.7,1.4,1.2,1.3,9.7,13.8,3.3,2.1,1.1,1.1,1.2,11.3,1.3,1.2,1.3,1.9,1.3,1.4,10.5,1,0.9,0.8,0.8,0.9,3.4,0.8,0.7,1,0.8,0.8,1.2,2.2,1.5,1.3,4.9,3.3,3.1,1.7,2.4,1,3.4,2.1,5.6,2,1.4,1.4,3.8,0.6,1.1,1.5,1.6,6.9,0.7,1.5,1.4,0.2,1.9,1,2,0.6,1.2,1.2,0.8,0.6,0.6,0.6,0.6,1,1.1,0.9,1,0.8,0.9,1.2,1.3,1.2,2.1,1.4,1.5,1.3,1.1,1.1,1.3,1.1,1,0.9,0.9,1,0.8,1,0.7,0.9,0.6,0.5,0.8,0.7,0.7,0.7,0.8,0.8,0.9,0.7,1.4,1.5,0.8,0.8,1.7,1.6,1.6,1,0.8,0.7,0.8,2.5,3.2,6.2,0.8,0.9,0.8,0.7,0.7,0.7,0.9,1,2,0.9,0.7,0.7,0.7,0.8,1.1,6.6,11.2,1.6,0.8,0.7,0.8,1.1,2,1.8,2.3,5.6,5.5,6.6,1.7,2.1,6.3,5,2,0.9,0.6,1,1.4,9.7,6.1,0.6,2.8,0.8,0.9,0.8,0.8,1,1.2,7.5,0.5,2.1,1.3,1.6,1.5,2.4,2.7,7.1,5.5,9.7,1.8,5.3,3.2,3.6,2.9,1.4,1.2,2.5,2.2,2,1.9,3.4,3.9,1.9,1.9,1.9,1.7,1.4,1.4,1.3,1.3,1.4,1.2,1.2,1.1,0.9,4.5,4.7,1,3,0.6,0.6,0.7,0.7,0.7,0.7,1.1,1.2,1.3,1.2,2.4,3,0.7,0.6,0.7,0.9,2.2,0.8,1.1,1.1,1.1,1.2,1.1,7.7,10.1,0.9,0.7,0.7,10.2,1,0.9,3.3,0.7,0.7,0.8,0.9,0.8,0.7,0.8,3.3,2.9,3,1.6,0.7,1.1,0.9,0.7,0.9,1.7,3.5,0.5,0.5,0.8,1.4,0.8,0.7,1.3,2.5,2.7,1.8],\
                        'speed':[7.2,7.1,7,7,7.1,6.6,6.9,6.9,6.9,7,6.9,6.9,7.3,6.6,7.3,6.9,7,6.7,7,7,6.9,6.8,6.9,6.6,7.2,7,7,7.2,6.7,6.9,6.7,6.7,6.9,6.9,7,6.9,7.1,6.8,7,6.7,6.8,7.1,7.2,7.2,7,6.8,7,7.1,7,7,6.8,6.9,6.8,7.1,7,7.1,6.9,6.9,6.9,6.8,6.9,6.9,7.2,6.9,7,7,11.2,10.8,11.3,11,11.3,10.7,11,11.5,11.4,11.5,10.5,12,10.5,11.2,10.5,10.7,11.2,10.9,11.1,11.6,10.8,11.1,11.1,11.6,11.3,11.1,10.8,11,11.3,11.2,11,11.5,10.8,11.7,11.1,11.2,10.9,11.4,11.5,11.4,11.1,10.6,11.2,11.6,11.4,10.7,10.7,11.3,10.7,11.7,11,11.4,11.4,11.3,11.4,10.9,11.3,10.6,10.9,10.8,11.4,11.2,11,11.2,11.4,11.2,11.3,11.2,11.4,10.7,10.6,11.5,11.3,11.5,10.6,11.5,10.8,11.8,10.8,11.1,11.1,11.4,10.8,11.4,10.7,11,11.1,10.9,11,11.1,11.1,11.1,10.8,11,11.1,11.2,11,10.9,11.3,10.8,11.4,11.1,11.1,11.9,11.3,11.8,11.3,10.7,10.7,11.3,11,11,10.8,11.2,10.9,10.8,11.2,11,11.3,11.1,11.1,11.1,11,11.2,11.1,11.1,10.9,11.4,10.8,10.9,11.3,10.8,11.2,11.2,11,11.2,10.8,11.1,11.2,10.9,11.2,11.5,10.8,11.2,11.2,11.3,11.1,11.6,11,11.2,11.3,11.2,11.2,12,10.3,11.1,11.8,11.4,11.1,10.9,11.2,11,11.3,11,11.5,11.3,10.4,11.7,11,10.6,11.2,10.9,11.2,10.8,11,11.2,11.1,10.9,11.8,10.5,11.1,11,11.3,11.1,11.4,10.9,11.1,10.9,10.4,10.8,11.4,11.2,11.2,11,11.2,11.1,11.3,10.7,11.8,11.7,11.2,11.2,11.2,11.9,11.3,11.3,10.6,10.7,6.9,6.9,6.9,7]},'distance':5428.4}],'weight_name':'routability','weight':679.7,'duration':679.7,'distance':6085.1}],'waypoints':[{'hint':'QaBXgiAawI8AAAAA3gAAAAAAAAAAAAAAAAAAAMXXGkMAAAAAAAAAAAAAAADeAAAAAAAAAAAAAAC57AAAVwV1AAp39gJXBXUACnf2AgAAbxAJMyRJ','distance':0,'name':'Herzog-Wolfgang-Straße','location':[7.669079,49.706762]},{'hint':'eQ7AgP___38AAAAACAAAAAAAAAA1AAAAAAAAAHsmuEAAAAAAVqkUQgAAAAAIAAAAAAAAADUAAAC57AAAKhF1ALF79gIqEXUAsXv2AgAAvwMJMyRJ','distance':0,'name':'Untertor','location':[7.672106,49.707953]},{'hint':'SM0Kg43NCoMSAAAAAAAAAEEAAAAAAAAA_uJKQQAAAACBDzNCAAAAABIAAAAAAAAAQQAAAAAAAAC57AAAsh11ALD79QKyHXUAsPv1AgMATwUJMyRJ','distance':0,'name':'Vordergasse','location':[7.675314,49.675184]}]}
        return MockResponse(restext, 200)
    elif args[0] == 'http://router.project-osrm.org/route/v1/driving/7.6690793,49.7067624;7.6690793,49.7067624;7.6690793,49.7067624;7.6721057,49.7079532;7.6721057,49.7079532;7.6721057,49.7079532.json':
        # intern wird 'http://router.project-osrm.org/route/v1/driving/...json?annotations=true' abgefragt
        restext={'code':'Ok','waypoints':[{'hint':'HTx5gZh__I8AAAAA3gAAAAAAAAAAAAAAAAAAAMXXGkMAAAAAAAAAAAAAAADeAAAAAAAAAAAAAADM6AAAVwV1AAp39gJXBXUACnf2AgAAbxD3hyK-','distance':0,'location':[7.669079,49.706762],'name':'Herzog-Wolfgang-Straße'},{'hint':'HTx5gZh__I8AAAAA3gAAAAAAAAAAAAAAAAAAAMXXGkMAAAAAAAAAAAAAAADeAAAAAAAAAAAAAADM6AAAVwV1AAp39gJXBXUACnf2AgAAbxD3hyK-','distance':0,'location':[7.669079,49.706762],'name':'Herzog-Wolfgang-Straße'},{'hint':'HTx5gZh__I8AAAAA3gAAAAAAAAAAAAAAAAAAAMXXGkMAAAAAAAAAAAAAAADeAAAAAAAAAAAAAADM6AAAVwV1AAp39gJXBXUACnf2AgAAbxD3hyK-','distance':0,'location':[7.669079,49.706762],'name':'Herzog-Wolfgang-Straße'},{'hint':'0nf8j____38AAAAACAAAAAAAAAA1AAAAAAAAAHsmuEAAAAAAVqkUQgAAAAAIAAAAAAAAADUAAADM6AAAKhF1ALF79gIqEXUAsXv2AgAAvwP3hyK-','distance':0,'location':[7.672106,49.707953],'name':'Untertor'},{'hint':'0nf8j____38AAAAACAAAAAAAAAA1AAAAAAAAAHsmuEAAAAAAVqkUQgAAAAAIAAAAAAAAADUAAADM6AAAKhF1ALF79gIqEXUAsXv2AgAAvwP3hyK-','distance':0,'location':[7.672106,49.707953],'name':'Untertor'},{'hint':'0nf8j____38AAAAACAAAAAAAAAA1AAAAAAAAAHsmuEAAAAAAVqkUQgAAAAAIAAAAAAAAADUAAADM6AAAKhF1ALF79gIqEXUAsXv2AgAAvwP3hyK-','distance':0,'location':[7.672106,49.707953],'name':'Untertor'}],'routes':[{'legs':[{'steps':[],'weight':0,'distance':0,'annotation':{'speed':[0],'metadata':{'datasource_names':['lua profile']},'nodes':[8926366194,929163070],'duration':[0],'distance':[0],'weight':[0],'datasources':[0]},'summary':'','duration':0},{'steps':[],'weight':0,'distance':0,'annotation':{'speed':[0],'metadata':{'datasource_names':['lua profile']},'nodes':[8926366194,929163070],'duration':[0],'distance':[0],'weight':[0],'datasources':[0]},'summary':'','duration':0},{'steps':[],'weight':107.9,'distance':656.7,'annotation':{'speed':[0,6.9,6.9,6.8,6.9,6.9,7.2,6.9,7,7,11.2,6.9,7,7,6.9,7,7,6.9,7.1,7,6.9,6.9,7.1,7.1,6.9,6.8,7,7,7.1,6.9,6.9,7,7,6.9,7,7.2,7.1,7.2,7.2],'metadata':{'datasource_names':['lua profile']},'nodes':[8926366194,929163070,293644800,3372775732,2071420730,3372775724,9019012086,2071420729,3372775723,293644809,293644732,301617177,1374244356,2178713942,1236586376,288942571,2178713931,288942564,3883853507,3883853506,1236586933,3883853508,3883853509,1866098314,288942563,2713716110,2177696446,288942562,2715125060,2177696450,1866099465,288942576,2713696116,2178714204,1236586381,1236586602,3883853537,2177696510,288942560,2183660825],'duration':[0,2,1.4,1.4,3.8,0.6,1.1,1.5,1.6,6.9,0.7,4.1,2.7,2.8,7,2.3,9.1,1.4,1.2,0.9,0.5,0.6,2.7,0.5,5.4,0.9,1.2,4.2,0.5,1.9,6.8,2,2.3,3.4,5.6,1,0.9,1.1,0],'distance':[0,13.705236,9.683369,9.507716,26.117089,4.117887,7.902307,10.36004,11.134995,47.965875,7.819434,28.238242,18.893336,19.638639,48.431373,16.084164,63.449551,9.711349,8.50452,6.273885,3.46396,4.121027,19.068738,3.562148,37.250007,6.132652,8.402537,29.378629,3.559968,13.020632,46.949898,13.971151,16.15185,23.416038,39.183624,7.222742,6.358125,7.934235,0],'weight':[0,2,1.4,1.4,3.8,0.6,1.1,1.5,1.6,6.9,0.7,4.1,2.7,2.8,7,2.3,9.1,1.4,1.2,0.9,0.5,0.6,2.7,0.5,5.4,0.9,1.2,4.2,0.5,1.9,6.8,2,2.3,3.4,5.6,1,0.9,1.1,0],'datasources':[0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0]},'summary':'','duration':107.9},{'steps':[],'weight':0,'distance':0,'annotation':{'speed':[0],'metadata':{'datasource_names':['lua profile']},'nodes':[288942560,2183660825],'duration':[0],'distance':[0],'weight':[0],'datasources':[0]},'summary':'','duration':0},{'steps':[],'weight':0,'distance':0,'annotation':{'speed':[0],'metadata':{'datasource_names':['lua profile']},'nodes':[288942560,2183660825],'duration':[0],'distance':[0],'weight':[0],'datasources':[0]},'summary':'','duration':0}],'weight_name':'routability','geometry':'gjknHwzxm@????h@GdBJfBe@IwCD}D^{GKCwERuACs@JqBHa@R????','weight':107.9,'distance':656.7,'duration':107.9}]}
        return MockResponse(restext, 200)
    # request not mocked
    return MockResponse(None, 404)

class Setups:
    """ Init functions for all our test classes. Simply inherit to use. """
    def init_db(self):
        test_data = Test_Data()

        self.client = Client()
        self.default_params = {
            'startLatitude': 52.3096,
            'startLongitude': 10.2505,
            'stopLatitude': 52.3093,
            'stopLongitude': 10.2467,
            'time': '2090-03-01T13:50:00+0000',
            'isDeparture': True,
            'seatNumber': 1,
            'seatNumberWheelchair': 0
            
        }
        self.default_params_meisenheim = {
            'startLatitude': 49.707,
            'startLongitude': 7.68,
            'stopLatitude': 49.6,
            'stopLongitude': 7.7,
            'time': '2090-03-01T13:50:00+0000',
            'isDeparture': True,
            'seatNumber': 1,
            'seatNumberWheelchair': 0
        }

        # Dummy entries for test db and mock servers
        Station.objects.all().delete()
        Route.objects.all().delete()
        Node.objects.all().delete()
        Bus.objects.all().delete()

        Peine = test_data.community_id_Peine
        self.s1 = Station.objects.create(uid=test_data.s1_uid, name=test_data.s1_name, mapId=test_data.s1_mapId, community=test_data.s1_community, latitude=test_data.s1_latitude, longitude=test_data.s1_longitude)
        self.s2 = Station.objects.create(uid=test_data.s2_uid, name=test_data.s2_name, mapId=test_data.s2_mapId, community=test_data.s2_community, latitude=test_data.s2_latitude, longitude=test_data.s2_longitude)
        self.b1 = Bus.objects.create(uid=0, name="bus1", community=Peine, capacity=8, capacity_wheelchair=2,capacity_blocked_per_wheelchair=2)
        self.b2 = Bus.objects.create(uid=1, name="bus2", community=Peine, capacity=8, capacity_wheelchair=2,capacity_blocked_per_wheelchair=2)

        Meisenheim = test_data.community_id_Meisenheim
        self.s_Lindenallee = Station.objects.create(uid=test_data.Lindenallee_uid, name=test_data.Lindenallee_name, latitude=test_data.Lindenallee_latitude, longitude=test_data.Lindenallee_longitude, mapId=test_data.Lindenallee_mapId, community=test_data.Lindenallee_community)
        self.s_Untergasse = Station.objects.create(uid=test_data.Untergasse_uid, name=test_data.Untergasse_name, latitude=test_data.Untergasse_latitude, longitude=test_data.Untergasse_longitude, mapId=test_data.Untergasse_mapId, community=test_data.Untergasse_community)
        self.s_Bahnhof = Station.objects.create(uid=test_data.Bahnhof_uid, name=test_data.Bahnhof_name, latitude=test_data.Bahnhof_latitude,
                                                longitude=test_data.Bahnhof_longitude, mapId=test_data.Bahnhof_mapId, community=test_data.Bahnhof_community)
        self.s_Edeka = Station.objects.create(
            uid=5, name="Edeka", latitude=49.7142613, longitude=7.6656951, mapId='469732623', community=Meisenheim)
        self.s_Gymnasium = Station.objects.create(
            uid=6, name="Gymnasium", latitude=49.7085358, longitude=7.6670296, mapId='293644764', community=Meisenheim)
        self.s_Reiffelbach = Station.objects.create(
            uid=7, name="Reiffelbach", latitude=49.6830937, longitude=7.688216, mapId='1236586204', community=Meisenheim)
        self.s_Roth = Station.objects.create(uid=test_data.Roth_uid, name=test_data.Roth_name, latitude=test_data.Roth_latitude,
                                             longitude=test_data.Roth_longitude, mapId=test_data.Roth_mapId, community=test_data.Roth_community)

        for i_bus, capa in enumerate((3,3,4)):
            Bus.objects.create(uid=2+i_bus, name='meise_'+str(i_bus), capacity=capa,capacity_wheelchair=1,capacity_blocked_per_wheelchair=0, community=Meisenheim)

    def kill_db(self):
        connections.close_all()

    def init_rabbit(self):
        #self.consumer = Consumer(queue_name=)
        self.publisher = UnthreadedPublisher()
    
    def init_routes(self):
        """ Create routes for later use here """
        RouteRequest(startLocation=(self.s1.latitude, self.s1.longitude), stopLocation=(self.s2.latitude, self.s2.longitude),
                     time=datetime.now(UTC), isDeparture=True, seatNumber=1, orderId = 1, routeId = 1)

        self.order = Order.objects.last()
        self.route = self.order.hopOnNode.route
        self.invalid_order_id = 0
        while Order.objects.filter(uid=self.invalid_order_id).count() > 0:
            self.invalid_order_id += 1
        self.invalid_route_id = Route.objects.last().id + 10

    def single_route(self, time_step: int = 8):
        self.community = 1
        self.bus = Bus.objects.create(uid=1, community=self.community, name="bus1", capacity=5, capacity_wheelchair=1)
        self.route = Route.objects.create(bus=self.bus, community=self.community, status=Route.BOOKED)
        self.t = datetime.now(UTC)
        self.nodes = []
        self.stations=[]

        t = self.t
        for i in range(5):
            tmin = t
            tmax = t + relativedelta(minutes=10)
            node = Node.objects.create(mapId=str(i), route=self.route, tMin=tmin, tMax=tmax)
            station = Station.objects.create(uid=100+i, name="test_station_" + str(i), latitude=52.3+0.1*i, longitude=10.2+0.1*i, mapId=i, community=self.community)        
            self.nodes.append(node)
            self.stations.append(station)
            t += relativedelta(minutes=time_step)
        
        self.order = Order.objects.create(uid=1, load=2, hopOnNode=self.nodes[0], hopOffNode=self.nodes[-1])
    
    def second_route(self):
        self.bus2 = Bus.objects.create(uid=2, community=self.community, name="bus2", capacity=8, capacity_wheelchair=1)
        self.route2 = Route.objects.create(bus=self.bus2, community=self.community, status=Route.BOOKED)
        self.t = datetime.now(UTC)
        self.nodes = []

        t = self.t
        for i in range(5):
            tmin = t
            tmax = t + relativedelta(minutes=10)
            node = Node.objects.create(mapId=str(i), route=self.route2, tMin=tmin, tMax=tmax)
            self.nodes.append(node)
            t += relativedelta(minutes=8)
        
        self.order = Order.objects.create(uid=3, load=3, hopOnNode=self.nodes[0], hopOffNode=self.nodes[-1])

    def second_community(self):
        self.community2 = 2
        self.bus2 = Bus.objects.create(uid=2, community=self.community2, name="bus1_comm2", capacity=5, capacity_wheelchair=1)
        self.route2 = Route.objects.create(bus=self.bus2, status=Route.BOOKED)
        self.t2 = datetime.now(UTC) + relativedelta(hours=4)
        self.nodes2 = []

        t = self.t2
        for i in range(7):
            tmin = t
            tmax = t + relativedelta(minutes=10)
            node = Node.objects.create(mapId=str(i), route=self.route2, tMin=tmin, tMax=tmax)
            self.nodes2.append(node)
            t += relativedelta(minutes=8)
        
        self.order2 = Order.objects.create(uid=2, load=2, hopOnNode=self.nodes2[0], hopOffNode=self.nodes2[-1])

    def init_routes_Meisenheim(self):
        """ Create routes for Meisenheim (for later use)"""
        RouteRequest(startLocation=(self.s_Lindenallee.latitude, self.s_Lindenallee.longitude), 
                     stopLocation=(self.s_Untergasse.latitude, self.s_Untergasse.longitude),
                     time=datetime.now(UTC), isDeparture=True, seatNumber=1, orderId = 2, routeId = 2)
                    
        self.order_m = Order.objects.last()
        self.route_m = self.order_m.hopOnNode.route
        self.invalid_order_id_m = 0
        while Order.objects.filter(uid=self.invalid_order_id_m).count() > 0:
            self.invalid_order_id_m += 1
        self.invalid_route_id_m = Route.objects.last().id + 10

    @staticmethod
    def iso_format(t):
        return t.isoformat()
    
    @staticmethod
    def iso2datetime(isoString):
        return parse(isoString)


# Only debug views - exclude on deploy
class Endpoints(TestCase):
    def setUp(self):
        self.client = Client()

    # we could make this an optional alternative for requests without '/' at the end
    def test_routes_as_list(self):
        response = self.client.get('/routes')   
        if settings.DEBUG==True:
            self.assertEqual(response.status_code, 200)   
            self.assertIsInstance(response.data, list)  
        else:
            self.assertEqual(response.status_code, 301)             

    def test_station_list_should_not_be_included_in_urls(self):
        response = self.client.get('/stops')
        if settings.DEBUG==True:
            self.assertEqual(response.status_code, 200)
            self.assertIsInstance(response.data, list)  
        else:
            self.assertEqual(response.status_code, 404)
        #print(response.data)

    def test_community_list_should_not_be_included_in_urls(self):
        response = self.client.get('/communities')
        if settings.DEBUG==True:            
            self.assertEqual(response.status_code, 404)
        else:
            self.assertEqual(response.status_code, 404)
        #print(response.data)
    
    def test_buses_list_should_not_be_included_in_urls(self):
        response = self.client.get('/buses')
        if settings.DEBUG==True:            
            self.assertEqual(response.status_code, 200)
        else:
            self.assertEqual(response.status_code, 404)
        #print(response.data)

class UnverbindlicheAnfrage(TestCase, Setups):

    def setUp(self):
        self.init_db()
        self.test_data = Test_Data()

    # The following couple of tests have `with self.settings(DEBUG=True)` removed, because
    # according to the docs, django.conf.settings.DEBUG is always False while testing, even if the env is True
    # and these couple of tests were setting DEBUG=True, which conflicted with the internal setting. See the docs:
    # https://docs.djangoproject.com/en/4.2/topics/testing/overview/#other-test-conditions
    
    def test_invalid_request_returns_400(self):
        #with self.settings(DEBUG=True):
        response = self.client.get(reverse('UnverbindlicheAnfrage'))
        self.assertEqual(response.status_code, 400)

    @mock.patch('Routing_Api.mockups.stations.requests.get', side_effect=mocked_requests_get)
    def test_valid_request_returns_200(self, mock_get):
        OSRM_activated_in_Test = GetRequestManager().OSRM_activated

        #with self.settings(DEBUG=True):            
        GetRequestManager().OSRM_activated = False # does not work with OSRM
        response = self.client.get(reverse("UnverbindlicheAnfrage"), self.default_params)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['result'], True)
        self.assertEqual(response.data['reasonCode'], GetRequestManager().POSSIBLE)
        self.assertEqual(response.data['reasonText'], 'Hurray')

        times_found = []
        times_found.append(self.default_params['time'])
        self.assertEqual(response.data['alternativeTimes'], times_found)
        self.assertEqual(str(response.data['timeSlot']), '[datetime.datetime(2090, 3, 1, 13, 50, tzinfo=datetime.timezone.utc), datetime.datetime(2090, 3, 1, 14, 0, tzinfo=datetime.timezone.utc)]')

        GetRequestManager().OSRM_activated = OSRM_activated_in_Test

        # todo analogen test fuer Zwoenitz aufbauen, der zwingend OSRM nutzt

    @mock.patch('Routing_Api.mockups.stations.requests.get', side_effect=mocked_requests_get)
    def test_valid_request_returns_200_alternatives_search_later(self, mock_get):
        OSRM_activated_in_Test = GetRequestManager().OSRM_activated

        #with self.settings(DEBUG=True):            
        GetRequestManager().OSRM_activated = False # does not work with OSRM
        new_params = self.default_params.copy()
        new_params['suggestAlternatives'] = 'later'
        response = self.client.get(reverse('UnverbindlicheAnfrage'), new_params)            
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['result'], True)
        self.assertEqual(response.data['reasonCode'], GetRequestManager().POSSIBLE) #important: if requested time is possible we should response this code even if alternative search was enabled        
        self.assertEqual(response.data['reasonText'], 'Hurray')

        times_found = []
        times_found.append(new_params['time'])
        self.assertEqual(response.data['alternativeTimes'], times_found) # since the first time works, no alternatives are calculated (performance!)
        self.assertEqual(str(response.data['timeSlot']), '[datetime.datetime(2090, 3, 1, 13, 50, tzinfo=datetime.timezone.utc), datetime.datetime(2090, 3, 1, 15, 50, tzinfo=datetime.timezone.utc)]')
              
        GetRequestManager().OSRM_activated = OSRM_activated_in_Test

    @mock.patch('Routing_Api.mockups.stations.requests.get', side_effect=mocked_requests_get)
    def test_valid_request_returns_200_alternatives_search_earlier(self, mock_get):
        OSRM_activated_in_Test = GetRequestManager().OSRM_activated

        #with self.settings(DEBUG=True):            
        GetRequestManager().OSRM_activated = False # does not work with OSRM
        new_params = self.default_params.copy()
        new_params['suggestAlternatives'] = 'earlier'
        response = self.client.get(reverse('UnverbindlicheAnfrage'), new_params)            
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['result'], True)
        self.assertEqual(response.data['reasonCode'], 0)
        self.assertEqual(response.data['reasonText'], 'Hurray')

        times_found = []
        times_found.append(new_params['time'])
        self.assertEqual(response.data['alternativeTimes'], times_found) # since the first time works, no alternatives are calculated (performance!)
        self.assertEqual(str(response.data['timeSlot']), '[datetime.datetime(2090, 3, 1, 11, 50, tzinfo=datetime.timezone.utc), datetime.datetime(2090, 3, 1, 13, 50, tzinfo=datetime.timezone.utc)]')
            
        GetRequestManager().OSRM_activated = OSRM_activated_in_Test

    # parameter tests
    @mock.patch('Routing_Api.mockups.db_busses.requests.get', side_effect=mocked_requests_get)
    def test_maximal_seatNumber(self, mock_get):
        #with self.settings(DEBUG=True):            
        new_params = self.default_params.copy()
        new_params['seatNumber'] = 20
        response = self.client.get(reverse('UnverbindlicheAnfrage'), new_params)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['result'], False)
        self.assertEqual(response.data['reasonCode'], GetRequestManager().BUSES_TOO_SMALL)
        self.assertEqual(response.data['reasonText'], f"Insufficient capacity! Capacity of Bus (id=0): 8 standard seats, 2 wheelchair seats. Requested seats: {new_params['seatNumber']} standard seats, {new_params['seatNumberWheelchair']} wheelchair seats.")
        self.assertEqual(response.data['alternativeTimes'], [])
        self.assertEqual(response.data['timeSlot'], [])

    # missing parameters
    def test_no_startLatitude_returns_400(self):
        #with self.settings(DEBUG=True):
        new_params = self.default_params.copy()
        new_params['startLatitude'] = ''
        response = self.client.get(reverse('UnverbindlicheAnfrage'), new_params)
        self.assertEqual(response.status_code, 400)
        #print(response.data)

    def test_no_startLongitude_returns_400(self):
        #with self.settings(DEBUG=True):
        new_params = self.default_params.copy()
        new_params['startLongitude'] = ''
        response = self.client.get(reverse('UnverbindlicheAnfrage'), new_params)
        self.assertEqual(response.status_code, 400)
        #print(response.data)
   
    def test_no_stopLatitude_returns_400(self):
        new_params = self.default_params.copy()
        new_params['stopLatitude'] = ''
        response = self.client.get(reverse('UnverbindlicheAnfrage'), new_params)
        self.assertEqual(response.status_code, 400)
        #print(response.data)

    def test_no_stopLongitude_returns_400(self):
        new_params = self.default_params.copy()
        new_params['stopLongitude'] = ''
        response = self.client.get(reverse('UnverbindlicheAnfrage'), new_params)
        self.assertEqual(response.status_code, 400)
        #print(response.data)

    def test_no_time_returns_400(self):
        new_params = self.default_params.copy()
        new_params['time'] = ''
        response = self.client.get(reverse('UnverbindlicheAnfrage'), new_params)
        self.assertEqual(response.status_code, 400)
        #print(response.data)

    def test_no_Departure_returns_400(self):
        new_params = self.default_params.copy()
        new_params['isDeparture'] = ''
        response = self.client.get(reverse('UnverbindlicheAnfrage'), new_params)
        self.assertEqual(response.status_code, 400)
        #print(response.data)

    ## wrong parameters
    def test_invalid_startLatitude_returns_400(self):
        new_params = self.default_params.copy()
        new_params['startLatitude'] = 'fifty'
        response = self.client.get(reverse('UnverbindlicheAnfrage'), new_params)
        self.assertEqual(response.status_code, 400)
        #print(response.data)

    def test_invalid_startLongitude_returns_400(self):
        new_params = self.default_params.copy()
        new_params['startLongitude'] = 'ten'
        response = self.client.get(reverse('UnverbindlicheAnfrage'), new_params)
        self.assertEqual(response.status_code, 400)
        #print(response.data)
   
    def test_invalid_stopLatitude_returns_400(self):
        new_params = self.default_params.copy()
        new_params['stopLatitude'] = 'fiftyone'
        response = self.client.get(reverse('UnverbindlicheAnfrage'), new_params)
        self.assertEqual(response.status_code, 400)
        #print(response.data)

    def test_invalid_stopLongitude_returns_400(self):
        new_params = self.default_params.copy()
        new_params['stopLongitude'] = 'eleven'
        response = self.client.get(reverse('UnverbindlicheAnfrage'), new_params)
        self.assertEqual(response.status_code, 400)
        #print(response.data)

    def test_invalid_Departure_returns_400(self):
        new_params = self.default_params.copy()
        new_params['isDeparture'] = 'yes'
        response = self.client.get(reverse('UnverbindlicheAnfrage'), new_params)
        self.assertEqual(response.status_code, 400)
        #print(response.data)

    def test_nonexistant_date_returns_400(self):
        new_params = self.default_params.copy()
        new_params['time'] = '201802311350'
        response = self.client.get(reverse('UnverbindlicheAnfrage'), new_params)
        self.assertEqual(response.status_code, 400)
        #print('stop',response.data)

    def test_invalid_time_returns_400(self):
        new_params = self.default_params.copy()
        new_params['time'] = 'eleven'
        response = self.client.get(reverse('UnverbindlicheAnfrage'), new_params)
        self.assertEqual(response.status_code, 400)
        #print('stop',response.data)

    def test_seatNumber_0_returns_400(self):
        new_params = self.default_params.copy()
        new_params['seatNumber'] = 0
        response = self.client.get(reverse('UnverbindlicheAnfrage'), new_params)
        self.assertEqual(response.status_code, 400)
        #print(response.data)

    def test_negative_seatNumber_returns_400(self):
        new_params = self.default_params.copy()
        new_params['seatNumber'] = -1
        response = self.client.get(reverse('UnverbindlicheAnfrage'), new_params)
        self.assertEqual(response.status_code, 400)
        #print(response.data)

    def test_seatNumber_asfloat_returns_400(self):
        new_params = self.default_params.copy()
        new_params['seatNumber'] = 1.5
        response = self.client.get(reverse('UnverbindlicheAnfrage'), new_params)
        self.assertEqual(response.status_code, 400)
        #print(response.data)

    def test_seatNumber_bigger200_returns_400(self):
        new_params = self.default_params.copy()
        new_params['seatNumber'] = 201
        response = self.client.get(reverse('UnverbindlicheAnfrage'), new_params)
        self.assertEqual(response.status_code, 400)
        #print(response.data)
    
    @mock.patch('Routing_Api.mockups.db_busses.requests.get', side_effect=mocked_requests_get)
    def test_no_busses_returns_200_and_false(self, mock_get):
        new_params = self.default_params.copy()
        new_params['time'] = '2099-03-01T12:50:00+00:00' # time with no bus available!
        response = self.client.get(reverse('UnverbindlicheAnfrage'), new_params)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['result'], False)
        self.assertEqual(response.data['reasonCode'], GetRequestManager().NO_BUSES)
        self.assertEqual(response.data['reasonText'], "No busses available at this time! Requested departure time: 2099/03/01, 12:50 (UTC), Start: s2 (52.3096, 10.2505), Destination: s1 (52.3093, 10.2467)")
        self.assertEqual(response.data['alternativeTimes'], [])

    #correct routing tests
    @mock.patch('Routing_Api.mockups.db_busses.requests.get', side_effect=mocked_requests_get)
    def test_departurerequest_for_wrong_community_200_false(self, mock_get):
        # parameters from Meisenheim, but departure coordinates in Peine
        new_params = self.default_params_meisenheim.copy()
        new_params['startLatitude'] = self.default_params['startLatitude']
        new_params['startLongitude'] = self.default_params['startLongitude']
        response = self.client.get(reverse('UnverbindlicheAnfrage'), new_params)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['result'], False)
        self.assertEqual(response.data['reasonCode'], GetRequestManager().NO_COMMUNITY)
        self.assertEqual(response.data['reasonText'], f"No matching communities - Start: {self.test_data.s2_name} ({new_params['startLatitude']}, {new_params['startLongitude']}) in community {{{self.test_data.community_id_Peine}}}, Destination: {self.test_data.Roth_name} ({new_params['stopLatitude']}, {new_params['stopLongitude']}) in community {{{self.test_data.community_id_Meisenheim}}}.")
        self.assertEqual(response.data['alternativeTimes'], [])


    @mock.patch('Routing_Api.mockups.db_busses.requests.get', side_effect=mocked_requests_get)
    def test_arrivalrequest_for_wrong_community_200_false(self, mock_get):
        # parameters from Meisenheim, but departure coordinates in Peine
        new_params = self.default_params_meisenheim.copy()
        new_params['stopLatitude'] = self.default_params['stopLatitude']
        new_params['stopLongitude'] = self.default_params['stopLongitude']
        response = self.client.get(reverse('UnverbindlicheAnfrage'), new_params)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['result'], False)
        self.assertEqual(response.data['reasonCode'], GetRequestManager().NO_COMMUNITY)        
        self.assertEqual(response.data['reasonText'],  f"No matching communities - Start: {self.test_data.Lindenallee_name} ({new_params['startLatitude']}, {new_params['startLongitude']}) in community {{{self.test_data.community_id_Meisenheim}}}, Destination: {self.test_data.s1_name} ({new_params['stopLatitude']}, {new_params['stopLongitude']}) in community {{{self.test_data.community_id_Peine}}}.")
        self.assertEqual(response.data['alternativeTimes'], [])

    @mock.patch('Routing_Api.mockups.db_busses.requests.get', side_effect=mocked_requests_get)
    def test_too_many_mobies_one_request_above_bus_capacity_200_false(self, mock_get):
        new_params = self.default_params.copy()
        # bus capacity of 8
        new_params['seatNumber'] = 9
        response = self.client.get(reverse('UnverbindlicheAnfrage'), new_params)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['result'], False)
        self.assertEqual(response.data['reasonCode'], GetRequestManager().BUSES_TOO_SMALL)
        self.assertEqual(response.data['reasonText'], f"Insufficient capacity! Capacity of Bus (id=0): 8 standard seats, 2 wheelchair seats. Requested seats: {new_params['seatNumber']} standard seats, {new_params['seatNumberWheelchair']} wheelchair seats.")
        self.assertEqual(response.data['alternativeTimes'], [])

    @mock.patch('Routing_Api.mockups.db_busses.requests.get', side_effect=mocked_requests_get)
    def test_busses_get_availabilities_in_community_local_time(self, mock_get):  
        timeStart = datetime(2090,3,1,12,50)
        timeEnde = datetime(2090,3,1,14,50)
        availabilities = GetRequestManager().Busses._get_availabilities_in_community(self.test_data.community_id_Peine, timeStart, timeEnde)

        self.assertEqual(1, len(availabilities))
        self.assertEqual("<Availability(bus_id=0,timeslots=[((datetime.datetime(2090, 3, 1, 10, 50, tzinfo=tzlocal()), 'Depot'), (datetime.datetime(2090, 3, 1, 16, 50, tzinfo=tzlocal()), 'Depot'))],timeslots_blocker=[])>", str(availabilities[0]))

    @mock.patch('Routing_Api.mockups.db_busses.requests.get', side_effect=mocked_requests_get)
    def test_busses_get_availabilities_in_community_utc(self, mock_get):  
        timeStart = datetime(2090,3,1,12,50, tzinfo=timezone.utc)
        timeEnde = datetime(2090,3,1,14,50, tzinfo=timezone.utc)
        availabilities = GetRequestManager().Busses._get_availabilities_in_community(self.test_data.community_id_Peine, timeStart, timeEnde)

        self.assertEqual(1, len(availabilities))
        self.assertEqual("<Availability(bus_id=0,timeslots=[((datetime.datetime(2090, 3, 1, 10, 50, tzinfo=tzlocal()), 'Depot'), (datetime.datetime(2090, 3, 1, 16, 50, tzinfo=tzlocal()), 'Depot'))],timeslots_blocker=[])>", str(availabilities[0]))


    @mock.patch('Routing_Api.mockups.db_busses.requests.get', side_effect=mocked_requests_get)
    def test_busses_get_availabilities_in_community_blocker(self, mock_get):  
       
        timeStart = parse('2090-03-02T06:50.000+00:00')
        timeEnde = parse('2090-03-02T09:10.000+00:00')
        availabilities = GetRequestManager().Busses._get_availabilities_in_community(self.test_data.community_id_Peine, timeStart, timeEnde)

        self.assertEqual(1, len(availabilities))
        self.assertEqual("<Availability(bus_id=0,timeslots=[((datetime.datetime(2090, 3, 2, 7, 50, tzinfo=tzlocal()), 'Depot'), (datetime.datetime(2090, 3, 2, 8, 5, tzinfo=tzlocal()), 'Depot'))],timeslots_blocker=[((datetime.datetime(2090, 3, 2, 8, 5, tzinfo=tzlocal()), 'Depot'), (datetime.datetime(2090, 3, 2, 8, 45, tzinfo=tzlocal()), 'Depot'))])>", str(availabilities[0]))

    @mock.patch('Routing_Api.mockups.db_busses.requests.get', side_effect=mocked_requests_get)
    def test_busses_get_available_buses_single_time(self, mock_get):  
        timeStart = parse('2090-03-01T13:50.000+00:00')
        timeEnde = parse('2090-03-01T15:50.000+00:00')

        timesStart = []
        timesStart.append(timeStart)
        timesStop = []
        timesStop.append(timeEnde)

        (availableBuses, times_in_blocker) = GetRequestManager().Busses.get_available_buses(self.test_data.community_id_Peine, timesStart, timesStop)

        self.assertEqual(1, len(availableBuses))
        self.assertEqual(1, len(availableBuses[0]))
        self.assertEqual(1, len(times_in_blocker))
        self.assertFalse(times_in_blocker[0])

        #print(str(availableBuses[0]))
        self.assertEqual('[Vehicle(0,VehicleCapacity(8, 2, 2),(datetime.datetime(2090, 3, 1, 10, 50, tzinfo=tzlocal()), datetime.datetime(2090, 3, 1, 16, 50, tzinfo=tzlocal())))]', str(availableBuses[0]))

    @mock.patch('Routing_Api.mockups.db_busses.requests.get', side_effect=mocked_requests_get)
    def test_busses_get_available_buses_multiple_times(self, mock_get):  
        timeStart = parse('2090-03-01T13:50.000+00:00')
        timeEnde = parse('2090-03-01T14:50.000+00:00')
        timeStart2 = parse('2090-03-01T14:50.000+00:00')
        timeEnde2 = parse('2090-03-01T15:50.000+00:00')

        timesStart = []
        timesStart.append(timeStart)
        timesStart.append(timeStart2)
        timesStop = []
        timesStop.append(timeEnde)
        timesStop.append(timeEnde2)

        (availableBuses, times_in_blocker) = GetRequestManager().Busses.get_available_buses(self.test_data.community_id_Peine, timesStart, timesStop)

        self.assertEqual(2, len(availableBuses))
        self.assertEqual(1, len(availableBuses[0]))
        self.assertEqual(1, len(availableBuses[1]))
        self.assertEqual(2, len(times_in_blocker))
        self.assertFalse(times_in_blocker[0])
        self.assertFalse(times_in_blocker[1])

        #print(str(availableBuses[0]))
        print(str(availableBuses[1]))

        content_cmp = '[Vehicle(0,VehicleCapacity(8, 2, 2),(datetime.datetime(2090, 3, 1, 10, 50, tzinfo=tzlocal()), datetime.datetime(2090, 3, 1, 17, 50, tzinfo=tzlocal())))]'
        self.assertEqual(content_cmp, str(availableBuses[0]))
        self.assertEqual(content_cmp, str(availableBuses[1]))

    @mock.patch('Routing_Api.mockups.db_busses.requests.get', side_effect=mocked_requests_get)
    def test_busses_get_available_buses_blocker(self, mock_get):  
       
        timeStart = parse('2090-03-02T07:50.000+00:00')
        timeEnde = parse('2090-03-02T08:05.000+00:00')
        timeStart2 = parse('2090-03-02T08:10.000+00:00')
        timeEnde2 = parse('2090-03-02T08:20.000+00:00')

        timesStart = []
        timesStart.append(timeStart)
        timesStart.append(timeStart2)
        timesStop = []
        timesStop.append(timeEnde)
        timesStop.append(timeEnde2)

        (availableBuses, times_in_blocker) = GetRequestManager().Busses.get_available_buses(self.test_data.community_id_Peine, timesStart, timesStop)

        self.assertEqual(2, len(availableBuses))
        self.assertEqual(1, len(availableBuses[0]))
        self.assertEqual(0, len(availableBuses[1]))
        self.assertEqual(2, len(times_in_blocker))
        self.assertFalse(times_in_blocker[0])
        self.assertTrue(times_in_blocker[1])

        #print(str(availableBuses[0]))
        self.assertEqual('[Vehicle(0,VehicleCapacity(8, 2, 2),(datetime.datetime(2090, 3, 2, 7, 50, tzinfo=tzlocal()), datetime.datetime(2090, 3, 2, 8, 5, tzinfo=tzlocal())))]', str(availableBuses[0]))
        self.assertEqual('[]', str(availableBuses[1]))    

    @mock.patch('Routing_Api.mockups.stations.requests.get', side_effect=mocked_requests_get)
    def test_maximum_number_mobies_one_request_200_true(self, mock_get):
        OSRM_activated_in_Test = GetRequestManager().OSRM_activated
        GetRequestManager().OSRM_activated = False # does not work with OSRM

        new_params = self.default_params.copy()
        # bus capacity of 8
        new_params['seatNumber'] = 8
        response = self.client.get(reverse('UnverbindlicheAnfrage'), new_params)
        
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['result'], True)
        self.assertEqual(response.data['reasonCode'], GetRequestManager().POSSIBLE)        
        self.assertEqual(response.data['reasonText'], 'Hurray')   

        GetRequestManager().OSRM_activated = OSRM_activated_in_Test     

    @mock.patch('Routing_Api.mockups.stations.requests.get', side_effect=mocked_requests_get)
    def test_busses_seperate_for_Meisenheim_and_Peine(self, mock_get):
        # max seatNumber in bus for Meisenheim: 4, 
        # max seatNumber in bus for Peine 8:
        # -> can't take more than 4 passengers in Meisenheim without using Peine bus.
        new_params = self.default_params_meisenheim.copy()
        new_params['seatNumber'] = 5
        response = self.client.get(reverse('UnverbindlicheAnfrage'), new_params)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['result'], False)
        self.assertEqual(response.data['reasonCode'], GetRequestManager().BUSES_TOO_SMALL)
        self.assertEqual(response.data['reasonText'], f"Insufficient capacity! Capacity of Bus (id=2): 3 standard seats, 1 wheelchair seats. Requested seats: {new_params['seatNumber']} standard seats, {new_params['seatNumberWheelchair']} wheelchair seats.")

    @mock.patch('Routing_Api.mockups.db_busses.requests.get', side_effect=mocked_requests_get)
    def test_roadclosures_init_roadclosures(self, mock_get):  
       
        timeStart = datetime(2090,3,2,12,50)
        timeEnde = datetime(2090,3,2,14,50)
        GetRequestManager().RoadClosures.initRoadClosures(self.test_data.community_id_Peine, timeStart, timeEnde)

        resLat = GetRequestManager().RoadClosures.closures_lat
        resLon = GetRequestManager().RoadClosures.closures_lon
        resList = GetRequestManager().RoadClosures.getRoadClosuresList()

        self.assertEqual(2, len(resLat))
        self.assertEqual(2, len(resLon))
        self.assertAlmostEqual(52.309409276213145, resLat[0], delta=1e-5)
        self.assertAlmostEqual(52.30886871841433, resLat[1], delta=1e-5)
        self.assertAlmostEqual(10.249192679384402, resLon[0], delta=1e-5)
        self.assertAlmostEqual(10.250494761672451, resLon[1], delta=1e-5)
        self.assertEqual(resLat[0], resList[0][0])
        self.assertEqual(resLat[1], resList[1][0])
        self.assertEqual(resLon[0], resList[0][1])
        self.assertEqual(resLon[1], resList[1][1])

class RoutendetailsAnfrageMobi(TestCase, Setups):
    def setUp(self):
        self.single_route()

    def test_valid_request_basic(self):  
        # test with maps and OSRM
        OSRM_activated_in_Test = GetRequestManager().OSRM_activated        
    
        GetRequestManager().OSRM_activated = False
        response1 = self.client.get(reverse('RoutendetailsAnfrageMobi', kwargs={'orderId': self.order.uid, 'routeId':self.route.id}))

        GetRequestManager().OSRM_activated = True
        response2 = self.client.get(reverse('RoutendetailsAnfrageMobi', kwargs={'orderId': self.order.uid, 'routeId':self.route.id}))

        self.assertEqual(response1.status_code, 200)
        self.assertEqual(response2.status_code, 200)

        self.assertEqual(response1.data['busId'],1)
        self.assertEqual(response2.data['busId'],1)

        self.assertEqual(response1.data['nodes'][0]['latitude'],52.3)
        self.assertEqual(response1.data['nodes'][0]['longitude'],10.2)
        self.assertEqual(response1.data['nodes'][0]['label'],'test_station_0')
        self.assertAlmostEqual(response1.data['nodes'][1]['latitude'],52.7, delta=1e-6)
        self.assertEqual(response1.data['nodes'][1]['longitude'],10.6)
        self.assertEqual(response1.data['nodes'][1]['label'],'test_station_4')
        self.assertEqual(len(response1.data['nodes']), 2)

        self.assertEqual(response1.data['nodes'], response2.data['nodes'])

        GetRequestManager().OSRM_activated = OSRM_activated_in_Test
    
    def test_valid_request_return_gps(self):  
        # test with maps and OSRM, return gps coords
        OSRM_activated_in_Test = GetRequestManager().OSRM_activated        
    
        GetRequestManager().OSRM_activated = False
        timeStarted = time.time()
        response1 = self.client.get(reverse('RoutendetailsAnfrageMobi', kwargs={'orderId': self.order.uid, 'routeId':self.route.id}), data={ 'gps': 'true'})
        timeElapsed = time.time() - timeStarted
        
        # performance must not be too bad if working with maps
        self.assertGreater(6.0, timeElapsed)

        GetRequestManager().OSRM_activated = True
        timeStarted = time.time()
        response2 = self.client.get(reverse('RoutendetailsAnfrageMobi', kwargs={'orderId': self.order.uid, 'routeId':self.route.id}), data={ 'gps': 'true'})
        timeElapsed = time.time() - timeStarted

        # OSRM performance much better than self managed maps
        # increase time because it might take a bit longer in the CI pipeline
        self.assertGreater(1, timeElapsed)

        self.assertEqual(response1.status_code, 200)
        self.assertEqual(response2.status_code, 200)

        self.assertEqual(response1.data['busId'],1)
        self.assertEqual(response2.data['busId'],1)

        self.assertEqual(len(response1.data['nodes']), 2)
        self.assertEqual(response1.data['nodes'][0]['latitude'],52.3)
        self.assertEqual(response1.data['nodes'][0]['longitude'],10.2)
        self.assertEqual(response1.data['nodes'][0]['label'],'test_station_0')
        self.assertAlmostEqual(response1.data['nodes'][1]['latitude'],52.7, delta=1e-6)
        self.assertEqual(response1.data['nodes'][1]['longitude'],10.6)
        self.assertEqual(response1.data['nodes'][1]['label'],'test_station_4')
        self.assertEqual(len(response1.data['nodes']), 2)

        self.assertEqual(response1.data['nodes'], response2.data['nodes'])

        # note: the node coords are nonsense in this example if we use the map, thus gps results differ considerable to the OSRM results
        self.assertEqual(len(response1.data['gps']), 1)
        self.assertEqual(len(response1.data['gps'][0]), 476) # sometimes results in either 476 or 1
        self.assertAlmostEqual(response1.data['gps'][0][0][0], 52.00, delta=1.5)
        self.assertAlmostEqual(response1.data['gps'][0][0][1], 13.21, delta=1.0)
        # Index out of range, because we don't receive 476 elements - see a couple of lines above
        #self.assertAlmostEqual(response1.data['gps'][0][200][0], 52.524, 2)
        #self.assertAlmostEqual(response1.data['gps'][0][200][1], 13.279, 2)
        #self.assertAlmostEqual(response1.data['gps'][0][475][0], 52.577, 2)
        #self.assertAlmostEqual(response1.data['gps'][0][475][1], 13.21, 2)

        self.assertEqual(len(response2.data['gps']), 1)
        self.assertEqual(len(response2.data['gps'][0]), 26)
        self.assertAlmostEqual(response2.data['gps'][0][0][0], 52.30, 2)
        self.assertAlmostEqual(response2.data['gps'][0][0][1], 10.20, 2)
        self.assertAlmostEqual(response2.data['gps'][0][15][0], 52.444, 2)
        self.assertAlmostEqual(response2.data['gps'][0][15][1], 10.538, 2)
        self.assertAlmostEqual(response2.data['gps'][0][25][0], 52.70, 2)
        self.assertAlmostEqual(response2.data['gps'][0][25][1], 10.60, 2)

        # print(response1.data['gps'])
        # print(response2.data['gps'])        

        GetRequestManager().OSRM_activated = OSRM_activated_in_Test
    
    def test_invalid_request_404(self):
        response = self.client.get(reverse('RoutendetailsAnfrageMobi', kwargs={'orderId': self.order.uid+1, 'routeId': self.route.id+1}))
        self.assertEqual(response.status_code, 404)

    def test_nonexistant_orderId_404(self):
        response = self.client.get(reverse('RoutendetailsAnfrageMobi', kwargs={'orderId': self.order.uid+1, 'routeId': self.route.id}))
        self.assertEqual(response.status_code, 404)

    def test_nonexistant_routeId_404(self):
        response = self.client.get(reverse('RoutendetailsAnfrageMobi', kwargs={'orderId': self.order.uid, 'routeId': self.route.id+1}))
        self.assertEqual(response.status_code, 404)

    def test_several_communities(self):
        self.second_community()

        response_p = self.client.get(reverse('RoutendetailsAnfrageMobi', kwargs={'orderId': self.order.uid, 'routeId':self.route.id}))
        self.assertEqual(response_p.status_code, 200)
        self.assertEqual(len(response_p.data['nodes']),2)
        self.assertEqual(response_p.data['busId'],1)

        response_m = self.client.get(reverse('RoutendetailsAnfrageMobi', kwargs={'orderId': self.order2.uid, 'routeId':self.route2.id}))
        self.assertEqual(response_m.status_code, 200)
        self.assertEqual(len(response_m.data['nodes']), 2)
        self.assertEqual(response_m.data['busId'],2)

class RoutendetailsAnfrageBusfahrer(TestCase, Setups):
    def setUp(self):
        self.single_route()

    def test_invalid_routeId_404(self):
        response = self.client.get(reverse('RoutendetailsAnfrageBusfahrer', kwargs={'routeId': self.route.id + 1}))
        self.assertEqual(response.status_code, 404)

    def test_valid_routeId_200(self):
        # test with maps and OSRM
        OSRM_activated_in_Test = GetRequestManager().OSRM_activated        
    
        GetRequestManager().OSRM_activated = False
        response1 = self.client.get(reverse('RoutendetailsAnfrageBusfahrer', kwargs={'routeId': self.route.id}))

        GetRequestManager().OSRM_activated = True
        response2 = self.client.get(reverse('RoutendetailsAnfrageBusfahrer', kwargs={'routeId': self.route.id}))

        self.assertEqual(response1.status_code, 200)
        self.assertEqual(response2.status_code, 200)

        self.assertEqual(response1.data['nodes'][0]['latitude'],52.3)
        self.assertEqual(response1.data['nodes'][0]['longitude'],10.2)
        self.assertEqual(response1.data['nodes'][0]['label'],'test_station_0')
        self.assertAlmostEqual(response1.data['nodes'][1]['latitude'],52.7, delta=1e-6)
        self.assertEqual(response1.data['nodes'][1]['longitude'],10.6)
        self.assertEqual(response1.data['nodes'][1]['label'],'test_station_4')
        self.assertEqual(len(response1.data['nodes']), 2)

        self.assertEqual(response1.data['nodes'], response2.data['nodes'])

        GetRequestManager().OSRM_activated = OSRM_activated_in_Test

@tag('details_bus')
class RoutendetailsAnfrageBus(TestCase, Setups):
    def setUp(self):
        self.single_route()
        self.second_community()

    def test_valid_busId_returns_route(self):
        # test with maps and OSRM
        OSRM_activated_in_Test = GetRequestManager().OSRM_activated        
    
        GetRequestManager().OSRM_activated = False
        response1 = self.client.get(reverse('RoutendetailsBusId', kwargs={'busId': self.bus.uid}))

        GetRequestManager().OSRM_activated = True
        response2 = self.client.get(reverse('RoutendetailsBusId', kwargs={'busId': self.bus.uid}))

        self.assertEqual(response1.status_code, 200)
        self.assertEqual(response2.status_code, 200)
        self.assertEqual(len(response1.data), 1)
        self.assertEqual(len(response2.data), 1)

        route1 = response1.data[0]
        route2 = response2.data[0]
        self.assertEqual(route1['busId'], self.bus.uid)
        self.assertEqual(route1['routeId'], self.route.id)
        self.assertEqual(route1, route2)

        self.assertEqual(route1['nodes'][0]['latitude'],52.3)
        self.assertEqual(route1['nodes'][0]['longitude'],10.2)
        self.assertEqual(route1['nodes'][0]['label'],'test_station_0')
        self.assertAlmostEqual(route1['nodes'][1]['latitude'],52.7, delta=1e-6)
        self.assertEqual(route1['nodes'][1]['longitude'],10.6)
        self.assertEqual(route1['nodes'][1]['label'],'test_station_4')
        self.assertEqual(len(route1['nodes']), 2)

        self.assertEqual(route1['nodes'], route2['nodes'])       

        GetRequestManager().OSRM_activated = OSRM_activated_in_Test        

class RoutendetailsCapacity(TestCase, Setups):  	

    def setUp(self):
        self.single_route()
        self.RoutesInterface = Routes(Route, Node, Order)
    	
    def test_free_routes_returns_route(self):
        free_routes = self.RoutesInterface.get_free_routes(1, self.nodes[0], self.nodes[-1], (self.t, self.t + relativedelta(minutes=10)), \
            (self.t + relativedelta(minutes=10), self.t + relativedelta(minutes=20)),MobyLoad(2,0))
        self.assertEqual(len(free_routes), 1)

    def test_free_routes_returns_2_routes(self):
        self.second_route()
        free_routes = self.RoutesInterface.get_free_routes(1, self.nodes[0], self.nodes[-1], (self.t, self.t + relativedelta(minutes=10)), \
            (self.t + relativedelta(minutes=10), self.t + relativedelta(minutes=20)),MobyLoad(2,0))
        self.assertEqual(len(free_routes), 2)

    def test_no_free_routes(self):
        self.order = Order.objects.create(uid=3, load=3, hopOnNode=self.nodes[1], hopOffNode=self.nodes[-2])

        free_routes = self.RoutesInterface.get_free_routes(1, self.nodes[0], self.nodes[-1], (self.t, self.t + relativedelta(minutes=10)), \
            (self.t + relativedelta(minutes=10), self.t + relativedelta(minutes=20)),MobyLoad(2,0))

        self.assertEqual(free_routes, [])

    def test_hop_on_first_node_possible_returns_route(self):
        restrictions = (self.nodes[0], self.nodes[-1], (self.t, self.t + relativedelta(minutes=10)), \
            (self.t + relativedelta(minutes=10), self.t + relativedelta(minutes=20)),2,0)
        self.RoutesInterface.hop_on([self.route], restrictions, 2, Orders=Orders(MessageBus=MessageBus(), Listener=Listener()))
        response = self.client.get(reverse('RoutendetailsBusId', kwargs={'busId': self.bus.uid})) 
        route = response.data[0]
        self.assertEqual(response.status_code, 200)
        self.assertEqual(route['busId'], self.bus.uid)
        self.assertEqual(route['routeId'], self.route.id)
        self.assertEqual(len(route['nodes'][0]['hopOns']), 2)

    def test_hop_on_second_node_possible_returns_route(self):
        restrictions = (self.nodes[1], self.nodes[-2], (self.t, self.t + relativedelta(minutes=10)), \
            (self.t + relativedelta(minutes=10), self.t + relativedelta(minutes=20)),2,0)
        self.RoutesInterface.hop_on([self.route], restrictions, 2, Orders=Orders(MessageBus=MessageBus(), Listener=Listener()))
        response = self.client.get(reverse('RoutendetailsBusId', kwargs={'busId': self.bus.uid})) 
        route = response.data[0]
        self.assertEqual(response.status_code, 200)
        self.assertEqual(route['busId'], self.bus.uid)
        self.assertEqual(route['routeId'], self.route.id)
        self.assertEqual(len(route['nodes'][0]['hopOns']), 1)
        self.assertEqual(len(route['nodes'][1]['hopOns']), 1)
    
    def test_hop_on_first_node_full_capacity_returns_error(self):
        restrictions = (self.nodes[0], self.nodes[-1], (self.t, self.t + relativedelta(minutes=10)), \
            (self.t + relativedelta(minutes=10), self.t + relativedelta(minutes=20)),4,0)
        with self.assertRaises(Exception) as testContext:
                self.RoutesInterface.hop_on([self.route], restrictions, 2, Orders=Orders(MessageBus=MessageBus(), Listener=Listener()))
        self.assertEqual(str(testContext.exception), 'Could not push order onto any of our found solutions.')
    
    def test_hop_on_second_node_full_capacity_returns_error(self):
        restrictions = (self.nodes[1], self.nodes[-2], (self.t, self.t + relativedelta(minutes=10)), \
            (self.t + relativedelta(minutes=10), self.t + relativedelta(minutes=20)),4,0)
        with self.assertRaises(Exception) as testContext:
                self.RoutesInterface.hop_on([self.route], restrictions, 2, Orders=Orders(MessageBus=MessageBus(), Listener=Listener()))
        self.assertEqual(str(testContext.exception), 'Could not push order onto any of our found solutions.')

    def test_hop_on_first_node_capacity_full_second_node_returns_false(self):
        self.order = Order.objects.create(uid=3, load=2, hopOnNode=self.nodes[1], hopOffNode=self.nodes[-2])
        restrictions = (self.nodes[0], self.nodes[-1], (self.t, self.t + relativedelta(minutes=10)), \
            (self.t + relativedelta(minutes=10), self.t + relativedelta(minutes=20)),2,0)
        with self.assertRaises(Exception) as testContext:
                self.RoutesInterface.hop_on([self.route], restrictions, 2, Orders=Orders(MessageBus=MessageBus(), Listener=Listener()))
        self.assertEqual(str(testContext.exception), 'Could not push order onto any of our found solutions.')

#################################################################################

class Services(TransactionTestCase, Setups):
    # test routing functions on database, but without web requests
    # advantage: faster, no subprocesses, sequential working code, testing of algorithms
    # disadvantage:  does not prove that API works

    def setUp(self):
        self.init_db()
        self.test_data = Test_Data()
        self.init_rabbit()

    def test_order_max_date_error(self):
        time_offset_max_days_backup = GetRequestManager().Config.timeOffset_MaxDaysOrderInFuture

        # reduce max allowed date
        GetRequestManager().Config.timeOffset_MaxDaysOrderInFuture = 10

        load1 = 0
        loadWheelchair1 = 1
        startLocation1 = self.test_data.Lindenallee_latitude, self.test_data.Lindenallee_longitude
        stopLocation1 = self.test_data.Untergasse_latitude, self.test_data.Untergasse_longitude        
        # startLocation1 = self.test_data.Fleischerei_latitude, self.test_data.Fleischerei_longitude # todo if due to changes in source errors arise in this test these station may be better
        # stopLocation1 = self.test_data.Grundschule_latitude, self.test_data.Grundschule_longitude # todo if due to changes in source errors arise in this test these station may be better     
        time1 = parse('2090-03-01T13:50.000+00:00')        
        startWindow1 = (time1, time1+relativedelta(minutes=10)) # departure!
        stopWindow1 = None

        correctErrorFound = False
        result = None

        try:
            result = GetRequestManager().order(start_location=startLocation1, stop_location=stopLocation1, start_window=startWindow1, stop_window=stopWindow1, load=load1, loadWheelchair=loadWheelchair1, order_id=None)       
        
        except InvalidTime2:
            correctErrorFound = True

        # error must be thrown that date is not allowed
        self.assertTrue(correctErrorFound)        
        self.assertIsNone(result)

        # reset the config val
        GetRequestManager().Config.timeOffset_MaxDaysOrderInFuture = time_offset_max_days_backup

    @mock.patch('Routing_Api.mockups.stations.requests.get', side_effect=mocked_requests_get)
    def test_order_ordersWithMapsAndOSRMinSameRoute(self, mock_get):
        self.setUp

        OSRM_activated_in_Test = GetRequestManager().OSRM_activated

        # deactivate OSRM
        GetRequestManager().OSRM_activated = False

        # choose a non-existing order id
        order_id1 = Order.objects.all().aggregate(Max('uid'))['uid__max']
        order_id1 = order_id1 + 33 if order_id1 is not None else 33

        load1 = 0
        loadWheelchair1 = 1
        startLocation1 = self.test_data.Lindenallee_latitude, self.test_data.Lindenallee_longitude
        stopLocation1 = self.test_data.Untergasse_latitude, self.test_data.Untergasse_longitude        
        time1 = parse('2090-03-01T13:50.000+00:00')        
        startWindow1 = (time1, time1+relativedelta(minutes=10)) # departure!
        stopWindow1 = None

        result = GetRequestManager().order(start_location=startLocation1, stop_location=stopLocation1, start_window=startWindow1, stop_window=stopWindow1, load=load1, loadWheelchair=loadWheelchair1, order_id=order_id1)
                
        orderCheck = Order.objects.get(uid=order_id1)
        #print(orderCheck)
        self.assertEqual(order_id1, result)
        self.assertEqual(order_id1, orderCheck.uid)
        self.assertEqual(load1, orderCheck.load)
        self.assertEqual(loadWheelchair1, orderCheck.loadWheelchair)
        self.assertEqual(self.test_data.Lindenallee_mapId, orderCheck.hopOnNode.mapId)
        self.assertEqual(self.test_data.Untergasse_mapId, orderCheck.hopOffNode.mapId)
        self.assertEqual(None, orderCheck.group_id)        
        # activate OSRM
        GetRequestManager().OSRM_activated = True

        # do not forget that the available buses are mocked and may have restricted capa -> test may fail with wheelchair and seat
        load2 = 1
        loadWheelchair2 = 0
        order_id2 = order_id1+1
        startLocation2 = startLocation1
        stopLocation2 = self.test_data.Roth_latitude, self.test_data.Roth_longitude        
        startWindow2 = startWindow1 # departure!
        stopWindow2 = None

        result = GetRequestManager().order(start_location=startLocation2, stop_location=stopLocation2, start_window=startWindow2, stop_window=stopWindow2, load=load2, loadWheelchair=loadWheelchair2, order_id=order_id2)
        
        self.assertEqual(order_id2, result)        
        orderCheck2 = Order.objects.get(uid=order_id2)
        #print(orderCheck)
        self.assertEqual(order_id2, orderCheck2.uid)
        self.assertEqual(load2, orderCheck2.load)
        self.assertEqual(loadWheelchair2, orderCheck2.loadWheelchair)
        self.assertEqual(self.test_data.Lindenallee_mapId, orderCheck2.hopOnNode.mapId)
        self.assertEqual(self.test_data.Roth_mapId, orderCheck2.hopOffNode.mapId)
        self.assertEqual(None, orderCheck.group_id)

        self.assertEqual(Route.objects.count(),1)
        routeId = Route.objects.last().id

        resultRoute = driver_details(routeId)
        #print(resultRoute)
        self.assertEqual(len(resultRoute['nodes']), 4)
        # note: in future we might combine nodes that have same station within same time window, up to no each hop_on gets its own node
        self.assertEqual(str(resultRoute['nodes'][0]),"{'latitude': 49.7067624, 'longitude': 7.6690793, 'label': 'Lindenallee', 'tMin': '2090-03-01T13:50:00Z', 'tMax': '2090-03-01T13:53:00Z', 'hopOns': [OrderedDict([('orderId', 33), ('seats', 0), ('seatsWheelchair', 1)])], 'hopOffs': []}")
        self.assertEqual(str(resultRoute['nodes'][1]),"{'latitude': 49.7067624, 'longitude': 7.6690793, 'label': 'Lindenallee', 'tMin': '2090-03-01T13:50:00Z', 'tMax': '2090-03-01T13:53:00Z', 'hopOns': [OrderedDict([('orderId', 34), ('seats', 1), ('seatsWheelchair', 0)])], 'hopOffs': []}")
        self.assertEqual(str(resultRoute['nodes'][2]),"{'latitude': 49.7079532, 'longitude': 7.6721057, 'label': 'Untergasse', 'tMin': '2090-03-01T13:57:00Z', 'tMax': '2090-03-01T14:00:00Z', 'hopOns': [], 'hopOffs': [OrderedDict([('orderId', 33), ('seats', 0), ('seatsWheelchair', 1)])]}")
        self.assertEqual(str(resultRoute['nodes'][3]),"{'latitude': 49.6751843, 'longitude': 7.6753142, 'label': 'Roth', 'tMin': '2090-03-01T14:12:00Z', 'tMax': '2090-03-01T14:15:00Z', 'hopOns': [], 'hopOffs': [OrderedDict([('orderId', 34), ('seats', 1), ('seatsWheelchair', 0)])]}")

        result = driver_details_busId(2, None, None)        
        self.assertEqual(len(result),1)
        self.assertEqual(str(result[0]),str(resultRoute))
        
        result = order_details(routeId, order_id1)
        #print(result)          
                 
        self.assertEqual(len(result['nodes']), 3)
        self.assertEqual(result['routeId'], routeId)
        self.assertEqual(str(result['nodes'][0]), "{'latitude': 49.7067624, 'longitude': 7.6690793, 'label': 'Lindenallee', 'tMin': '2090-03-01T13:50:00Z', 'tMax': '2090-03-01T13:53:00Z'}")
        self.assertEqual(str(result['nodes'][1]), "{'latitude': 49.7067624, 'longitude': 7.6690793, 'label': 'Lindenallee', 'tMin': '2090-03-01T13:50:00Z', 'tMax': '2090-03-01T13:53:00Z'}")
        self.assertEqual(str(result['nodes'][2]), "{'latitude': 49.7079532, 'longitude': 7.6721057, 'label': 'Untergasse', 'tMin': '2090-03-01T13:57:00Z', 'tMax': '2090-03-01T14:00:00Z'}")

        # check gps coords of order
        result_gps = order_details_with_gps(routeId, order_id1)
        self.assertEqual(len(result['nodes']), len(result_gps['nodes']))
        self.assertEqual(result_gps['routeId'], result['routeId'])
        self.assertEqual(str(result['nodes'][0]), str(result_gps['nodes'][0]))
        self.assertEqual(str(result['nodes'][1]), str(result_gps['nodes'][1]))
        self.assertEqual(str(result['nodes'][2]), str(result_gps['nodes'][2]))
        self.assertEqual(len(result_gps['gps']), len(result_gps['nodes'])-1)
        self.assertEqual(len(result_gps['gps'][0]), 2)
        self.assertAlmostEqual(result_gps['gps'][0][0][0], self.test_data.Lindenallee_latitude, 4) 
        self.assertAlmostEqual(result_gps['gps'][0][0][1], self.test_data.Lindenallee_longitude, 4) 
        self.assertAlmostEqual(result_gps['gps'][0][1][0], self.test_data.Lindenallee_latitude, 4)  
        self.assertAlmostEqual(result_gps['gps'][0][1][1], self.test_data.Lindenallee_longitude, 4) 
        self.assertEqual(len(result_gps['gps'][1]), 13)
        self.assertAlmostEqual(result_gps['gps'][1][0][0], self.test_data.Lindenallee_latitude, 4) 
        self.assertAlmostEqual(result_gps['gps'][1][0][1], self.test_data.Lindenallee_longitude, 4)  
        self.assertAlmostEqual(result_gps['gps'][1][12][0], self.test_data.Untergasse_latitude, 4)  
        self.assertAlmostEqual(result_gps['gps'][1][12][1], self.test_data.Untergasse_longitude, 4) 

        result = order_details(routeId, order_id2)
        #print(result)
        self.assertEqual(len(result['nodes']), 3)
        self.assertEqual(result['routeId'], routeId)
        self.assertEqual(str(result['nodes'][0]), "{'latitude': 49.7067624, 'longitude': 7.6690793, 'label': 'Lindenallee', 'tMin': '2090-03-01T13:50:00Z', 'tMax': '2090-03-01T13:53:00Z'}")
        self.assertEqual(str(result['nodes'][1]), "{'latitude': 49.7079532, 'longitude': 7.6721057, 'label': 'Untergasse', 'tMin': '2090-03-01T13:57:00Z', 'tMax': '2090-03-01T14:00:00Z'}")
        self.assertEqual(str(result['nodes'][2]), "{'latitude': 49.6751843, 'longitude': 7.6753142, 'label': 'Roth', 'tMin': '2090-03-01T14:12:00Z', 'tMax': '2090-03-01T14:15:00Z'}")

        # check gps coords of order
        result_gps = order_details_with_gps(routeId, order_id2)
        self.assertEqual(len(result['nodes']), len(result_gps['nodes']))
        self.assertEqual(result_gps['routeId'], result['routeId'])
        self.assertEqual(str(result['nodes'][0]), str(result_gps['nodes'][0]))
        self.assertEqual(str(result['nodes'][1]), str(result_gps['nodes'][1]))
        self.assertEqual(str(result['nodes'][2]), str(result_gps['nodes'][2]))
        self.assertEqual(len(result_gps['gps']), len(result_gps['nodes'])-1)
        self.assertEqual(len(result_gps['gps'][0]), 4)
        self.assertAlmostEqual(result_gps['gps'][0][0][0], self.test_data.Lindenallee_latitude, 4) 
        self.assertAlmostEqual(result_gps['gps'][0][0][1], self.test_data.Lindenallee_longitude, 4) 
        self.assertAlmostEqual(result_gps['gps'][0][3][0], self.test_data.Untergasse_latitude, 4)  
        self.assertAlmostEqual(result_gps['gps'][0][3][1], self.test_data.Untergasse_longitude, 4) 
        self.assertEqual(len(result_gps['gps'][1]), 34)
        self.assertAlmostEqual(result_gps['gps'][1][0][0], self.test_data.Untergasse_latitude, 4) 
        self.assertAlmostEqual(result_gps['gps'][1][0][1], self.test_data.Untergasse_longitude, 4)  
        self.assertAlmostEqual(result_gps['gps'][1][33][0], self.test_data.Roth_latitude, 4)  
        self.assertAlmostEqual(result_gps['gps'][1][33][1], self.test_data.Roth_longitude, 4)    

        GetRequestManager().OSRM_activated = OSRM_activated_in_Test  

    @mock.patch('Routing_Api.mockups.stations.requests.get', side_effect=mocked_requests_get)
    def test_order_and_split_route(self, mock_get):
        self.setUp

        OSRM_activated_in_Test = GetRequestManager().OSRM_activated

        # deactivate OSRM
        GetRequestManager().OSRM_activated = False

        # choose a non-existing order id
        order_id1 = Order.objects.all().aggregate(Max('uid'))['uid__max']
        order_id1 = order_id1 + 33 if order_id1 is not None else 33

        load1 = 1
        loadWheelchair1 = 0
        startLocation1 = self.test_data.Lindenallee_latitude, self.test_data.Lindenallee_longitude
        stopLocation1 = self.test_data.Untergasse_latitude, self.test_data.Untergasse_longitude        
        time1 = parse('2090-03-01T13:30.000+00:00')        
        startWindow1 = (time1, time1+relativedelta(minutes=10)) # departure!
        stopWindow1 = None

        result = GetRequestManager().order(start_location=startLocation1, stop_location=stopLocation1, start_window=startWindow1, stop_window=stopWindow1, load=load1, loadWheelchair=loadWheelchair1, order_id=order_id1)
                
        orderCheck = Order.objects.get(uid=order_id1)
        #print(orderCheck)
        self.assertEqual(order_id1, result)
        self.assertEqual(order_id1, orderCheck.uid)
        self.assertEqual(load1, orderCheck.load)
        self.assertEqual(loadWheelchair1, orderCheck.loadWheelchair)
        self.assertEqual(self.test_data.Lindenallee_mapId, orderCheck.hopOnNode.mapId)
        self.assertEqual(self.test_data.Untergasse_mapId, orderCheck.hopOffNode.mapId)
        self.assertEqual(None, orderCheck.group_id)                

        # do not forget that the available buses are mocked and may have restricted capa -> test may fail with wheelchair and seat
        load2 = 1
        loadWheelchair2 = 0
        order_id2 = order_id1+1
        startLocation2 = self.test_data.Roth_latitude, self.test_data.Roth_longitude 
        stopLocation2 = self.test_data.Lindenallee_latitude, self.test_data.Lindenallee_longitude      
        time2 = parse('2090-03-01T13:50.000+00:00')        
        startWindow2 = (time2, time2+relativedelta(minutes=10)) # departure!
        stopWindow2 = None

        result = GetRequestManager().order(start_location=startLocation2, stop_location=stopLocation2, start_window=startWindow2, stop_window=stopWindow2, load=load2, loadWheelchair=loadWheelchair2, order_id=order_id2)
        
        self.assertEqual(order_id2, result)        
        orderCheck2 = Order.objects.get(uid=order_id2)
        #print(orderCheck)
        self.assertEqual(order_id2, orderCheck2.uid)
        self.assertEqual(load2, orderCheck2.load)
        self.assertEqual(loadWheelchair2, orderCheck2.loadWheelchair)
        self.assertEqual(self.test_data.Roth_mapId, orderCheck2.hopOnNode.mapId)
        self.assertEqual(self.test_data.Lindenallee_mapId, orderCheck2.hopOffNode.mapId)
        self.assertEqual(None, orderCheck.group_id)

        self.assertEqual(Route.objects.count(),1)
        routeId = Route.objects.last().id

        resultRoute = driver_details(routeId)
        #print(resultRoute)
        self.assertEqual(len(resultRoute['nodes']), 4)
        self.assertEqual(str(resultRoute['nodes'][0]),"{'latitude': 49.7067624, 'longitude': 7.6690793, 'label': 'Lindenallee', 'tMin': '2090-03-01T13:30:00Z', 'tMax': '2090-03-01T13:33:00Z', 'hopOns': [OrderedDict([('orderId', 33), ('seats', 1), ('seatsWheelchair', 0)])], 'hopOffs': []}")
        self.assertEqual(str(resultRoute['nodes'][1]),"{'latitude': 49.7079532, 'longitude': 7.6721057, 'label': 'Untergasse', 'tMin': '2090-03-01T13:33:00Z', 'tMax': '2090-03-01T13:36:00Z', 'hopOns': [], 'hopOffs': [OrderedDict([('orderId', 33), ('seats', 1), ('seatsWheelchair', 0)])]}")
        self.assertEqual(str(resultRoute['nodes'][2]),"{'latitude': 49.6751843, 'longitude': 7.6753142, 'label': 'Roth', 'tMin': '2090-03-01T13:50:00Z', 'tMax': '2090-03-01T13:53:00Z', 'hopOns': [OrderedDict([('orderId', 34), ('seats', 1), ('seatsWheelchair', 0)])], 'hopOffs': []}")
        self.assertEqual(str(resultRoute['nodes'][3]),"{'latitude': 49.7067624, 'longitude': 7.6690793, 'label': 'Lindenallee', 'tMin': '2090-03-01T13:57:00Z', 'tMax': '2090-03-01T14:00:00Z', 'hopOns': [], 'hopOffs': [OrderedDict([('orderId', 34), ('seats', 1), ('seatsWheelchair', 0)])]}")

        result = driver_details_busId(2, None, None)        
        self.assertEqual(len(result),1)
        self.assertEqual(str(result[0]),str(resultRoute))
        
        result = order_details(routeId, order_id1)
        #print(result)           
        self.assertEqual(len(result['nodes']), 2)
        self.assertEqual(result['routeId'], routeId)
        self.assertEqual(str(result['nodes'][0]), "{'latitude': 49.7067624, 'longitude': 7.6690793, 'label': 'Lindenallee', 'tMin': '2090-03-01T13:30:00Z', 'tMax': '2090-03-01T13:33:00Z'}")
        self.assertEqual(str(result['nodes'][1]), "{'latitude': 49.7079532, 'longitude': 7.6721057, 'label': 'Untergasse', 'tMin': '2090-03-01T13:33:00Z', 'tMax': '2090-03-01T13:36:00Z'}")

        result = order_details(routeId, order_id2)
        #print(result)
        self.assertEqual(len(result['nodes']), 2)
        self.assertEqual(result['routeId'], routeId)
        self.assertEqual(str(result['nodes'][0]), "{'latitude': 49.6751843, 'longitude': 7.6753142, 'label': 'Roth', 'tMin': '2090-03-01T13:50:00Z', 'tMax': '2090-03-01T13:53:00Z'}")
        self.assertEqual(str(result['nodes'][1]), "{'latitude': 49.7067624, 'longitude': 7.6690793, 'label': 'Lindenallee', 'tMin': '2090-03-01T13:57:00Z', 'tMax': '2090-03-01T14:00:00Z'}")
        
        # split route must split and must have consistent result
        tasks.split_routes(delta_time_min_for_split=5)
        self.assertTrue(tasks.check_routing_data())

        # check split data
        result = driver_details_busId(2, None, None)    
        #print(result)    
        self.assertEqual(len(result),2)
        self.assertEqual(result[0]['routeId'],routeId)
        routeId2  = result[1]['routeId']
        
        result = order_details(routeId, order_id1)
        #print(result)           
        self.assertEqual(len(result['nodes']), 2)
        self.assertEqual(result['routeId'], routeId)
        self.assertEqual(str(result['nodes'][0]), "{'latitude': 49.7067624, 'longitude': 7.6690793, 'label': 'Lindenallee', 'tMin': '2090-03-01T13:30:00Z', 'tMax': '2090-03-01T13:33:00Z'}")
        self.assertEqual(str(result['nodes'][1]), "{'latitude': 49.7079532, 'longitude': 7.6721057, 'label': 'Untergasse', 'tMin': '2090-03-01T13:33:00Z', 'tMax': '2090-03-01T13:36:00Z'}")

        result = order_details(routeId2, order_id2)
        #print(result)
        self.assertEqual(len(result['nodes']), 2)
        self.assertEqual(result['routeId'], routeId2)
        self.assertEqual(str(result['nodes'][0]), "{'latitude': 49.6751843, 'longitude': 7.6753142, 'label': 'Roth', 'tMin': '2090-03-01T13:50:00Z', 'tMax': '2090-03-01T13:53:00Z'}")
        self.assertEqual(str(result['nodes'][1]), "{'latitude': 49.7067624, 'longitude': 7.6690793, 'label': 'Lindenallee', 'tMin': '2090-03-01T13:57:00Z', 'tMax': '2090-03-01T14:00:00Z'}")
        
        countNodeRoute1 = 0
        countNodeRoute2 = 0

        for node in Node.objects.all():
            if node.route_id == routeId and node.latitude is not None:
                countNodeRoute1 += 1
            if node.route_id == routeId2 and node.latitude is not None:
                countNodeRoute2 += 1

        self.assertEqual(countNodeRoute1, 2)
        self.assertEqual(countNodeRoute2, 2)

        # for order in Order.objects.all():
        #     print(order)

        GetRequestManager().OSRM_activated = OSRM_activated_in_Test 
    
    @mock.patch('Routing_Api.mockups.stations.requests.get', side_effect=mocked_requests_get)
    def test_order_and_promises_for_long_route(self, mock_get):
        self.setUp

        # for long routes all necessary promises need to be found, even if orders are not within lookaround

        OSRM_activated_in_Test = GetRequestManager().OSRM_activated

        # deactivate OSRM
        GetRequestManager().OSRM_activated = False

        # check config of look_around for promises: muss be one hour, following route is longer than look_around - all promises must be found even outside the look around
        self.assertEqual(10, GetRequestManager().Busses._look_around)
        self.assertEqual(1, GetRequestManager().Routes._look_around)

        # choose a non-existing order id
        order_id1 = Order.objects.all().aggregate(Max('uid'))['uid__max']
        order_id1 = order_id1 + 33 if order_id1 is not None else 33

        load1 = 1
        loadWheelchair1 = 0
        startLocation1 = self.test_data.Lindenallee_latitude, self.test_data.Lindenallee_longitude
        stopLocation1 = self.test_data.Untergasse_latitude, self.test_data.Untergasse_longitude        
        time1 = parse('2090-03-01T13:30.000+00:00')        
        startWindow1 = (time1, time1+relativedelta(minutes=10)) # departure!
        stopWindow1 = None

        result = GetRequestManager().order(start_location=startLocation1, stop_location=stopLocation1, start_window=startWindow1, stop_window=stopWindow1, load=load1, loadWheelchair=loadWheelchair1, order_id=order_id1)
                
        orderCheck = Order.objects.get(uid=order_id1)
        #print(orderCheck)
        self.assertEqual(order_id1, result)
        self.assertEqual(order_id1, orderCheck.uid)
        self.assertEqual(load1, orderCheck.load)
        self.assertEqual(loadWheelchair1, orderCheck.loadWheelchair)
        self.assertEqual(self.test_data.Lindenallee_mapId, orderCheck.hopOnNode.mapId)
        self.assertEqual(self.test_data.Untergasse_mapId, orderCheck.hopOffNode.mapId)
        self.assertEqual(None, orderCheck.group_id)                

        # add few orders for extra long route
        order_id2 = order_id1+1
        time2 = parse('2090-03-01T13:50.000+00:00')        
        startWindow2 = (time2, time2+relativedelta(minutes=10)) # departure!

        result = GetRequestManager().order(start_location=startLocation1, stop_location=stopLocation1, start_window=startWindow2, stop_window=stopWindow1, load=load1, loadWheelchair=loadWheelchair1, order_id=order_id2)
        
        order_id3 = order_id2+1
        time3 = parse('2090-03-01T14:20.000+00:00')        
        startWindow3 = (time3, time3+relativedelta(minutes=10)) # departure!

        result = GetRequestManager().order(start_location=startLocation1, stop_location=stopLocation1, start_window=startWindow3, stop_window=stopWindow1, load=load1, loadWheelchair=loadWheelchair1, order_id=order_id3)
        
        order_id4 = order_id3+1
        time4 = parse('2090-03-01T14:50.000+00:00')        
        startWindow4 = (time4, time4+relativedelta(minutes=10)) # departure!

        result = GetRequestManager().order(start_location=startLocation1, stop_location=stopLocation1, start_window=startWindow4, stop_window=stopWindow1, load=load1, loadWheelchair=loadWheelchair1, order_id=order_id4)        
        
        # result must be one route with all 4 orders
        self.assertEqual(Route.objects.count(),1)
        routeId = Route.objects.last().id

        resultRoute = driver_details(routeId)
        #print(resultRoute)
        self.assertEqual(len(resultRoute['nodes']), 8)
        
        result = driver_details_busId(2, None, None)        
        self.assertEqual(len(result),1)
        self.assertEqual(str(result[0]),str(resultRoute))
        
        result = order_details(routeId, order_id1)
        #print(result)           
        self.assertEqual(len(result['nodes']), 2)
        self.assertEqual(result['routeId'], routeId)
        
        result = order_details(routeId, order_id2)
        #print(result)
        self.assertEqual(len(result['nodes']), 2)
        self.assertEqual(result['routeId'], routeId)

        result = order_details(routeId, order_id3)
        #print(result)
        self.assertEqual(len(result['nodes']), 2)
        self.assertEqual(result['routeId'], routeId)

        result = order_details(routeId, order_id4)
        #print(result)
        self.assertEqual(len(result['nodes']), 2)
        self.assertEqual(result['routeId'], routeId)  

        GetRequestManager().OSRM_activated = OSRM_activated_in_Test 

    @mock.patch('Routing_Api.mockups.stations.requests.get', side_effect=mocked_requests_get)
    def test_order_2_times_the_same_order(self, mock_get):
        self.setUp

        OSRM_activated_in_Test = GetRequestManager().OSRM_activated

        # deactivate OSRM
        GetRequestManager().OSRM_activated = False

        # choose a non-existing order id
        order_id1 = Order.objects.all().aggregate(Max('uid'))['uid__max']
        order_id1 = order_id1 + 33 if order_id1 is not None else 33

        load1 = 1
        loadWheelchair1 = 0
        startLocation1 = self.test_data.Lindenallee_latitude, self.test_data.Lindenallee_longitude
        stopLocation1 = self.test_data.Untergasse_latitude, self.test_data.Untergasse_longitude        
        time1 = parse('2090-03-01T13:30.000+00:00')        
        startWindow1 = (time1, time1+relativedelta(minutes=10)) # departure!
        stopWindow1 = None

        result = GetRequestManager().order(start_location=startLocation1, stop_location=stopLocation1, start_window=startWindow1, stop_window=stopWindow1, load=load1, loadWheelchair=loadWheelchair1, order_id=order_id1)
                
        orderCheck = Order.objects.get(uid=order_id1)
        #print(orderCheck)
        self.assertEqual(order_id1, result)
        self.assertEqual(order_id1, orderCheck.uid)
        self.assertEqual(load1, orderCheck.load)
        self.assertEqual(loadWheelchair1, orderCheck.loadWheelchair)
        self.assertEqual(self.test_data.Lindenallee_mapId, orderCheck.hopOnNode.mapId)
        self.assertEqual(self.test_data.Untergasse_mapId, orderCheck.hopOffNode.mapId)
        self.assertEqual(None, orderCheck.group_id)                

        ##############################################################################
        # do the same order a second time
        order_id2 = order_id1+1

        result = GetRequestManager().order(start_location=startLocation1, stop_location=stopLocation1, start_window=startWindow1, stop_window=stopWindow1, load=load1, loadWheelchair=loadWheelchair1, order_id=order_id2)
        
        self.assertEqual(order_id2, result)        
        orderCheck2 = Order.objects.get(uid=order_id2)
        #print(orderCheck)
        self.assertEqual(order_id2, orderCheck2.uid)
        self.assertEqual(load1, orderCheck2.load)
        self.assertEqual(loadWheelchair1, orderCheck2.loadWheelchair)
        self.assertEqual(self.test_data.Lindenallee_mapId, orderCheck2.hopOnNode.mapId)
        self.assertEqual(self.test_data.Untergasse_mapId, orderCheck2.hopOffNode.mapId)
        self.assertEqual(None, orderCheck.group_id)

        self.assertEqual(Route.objects.count(),1)
        routeId = Route.objects.last().id

        resultRoute = driver_details(routeId)
        #print(resultRoute)
        self.assertEqual(len(resultRoute['nodes']), 2)
        self.assertEqual(str(resultRoute['nodes'][0]),"{'latitude': 49.7067624, 'longitude': 7.6690793, 'label': 'Lindenallee', 'tMin': '2090-03-01T13:30:00Z', 'tMax': '2090-03-01T13:33:00Z', 'hopOns': [OrderedDict([('orderId', 33), ('seats', 1), ('seatsWheelchair', 0)]), OrderedDict([('orderId', 34), ('seats', 1), ('seatsWheelchair', 0)])], 'hopOffs': []}")
        self.assertEqual(str(resultRoute['nodes'][1]),"{'latitude': 49.7079532, 'longitude': 7.6721057, 'label': 'Untergasse', 'tMin': '2090-03-01T13:33:00Z', 'tMax': '2090-03-01T13:36:00Z', 'hopOns': [], 'hopOffs': [OrderedDict([('orderId', 33), ('seats', 1), ('seatsWheelchair', 0)]), OrderedDict([('orderId', 34), ('seats', 1), ('seatsWheelchair', 0)])]}")        
        
        result = driver_details_busId(2, None, None)        
        self.assertEqual(len(result),1)
        self.assertEqual(str(result[0]),str(resultRoute))
        
        result = order_details(routeId, order_id1)
        #print(result)           
        self.assertEqual(len(result['nodes']), 2)
        self.assertEqual(result['routeId'], routeId)
        self.assertEqual(str(result['nodes'][0]), "{'latitude': 49.7067624, 'longitude': 7.6690793, 'label': 'Lindenallee', 'tMin': '2090-03-01T13:30:00Z', 'tMax': '2090-03-01T13:33:00Z'}")
        self.assertEqual(str(result['nodes'][1]), "{'latitude': 49.7079532, 'longitude': 7.6721057, 'label': 'Untergasse', 'tMin': '2090-03-01T13:33:00Z', 'tMax': '2090-03-01T13:36:00Z'}")

        result = order_details(routeId, order_id2)
        #print(result)
        self.assertEqual(len(result['nodes']), 2)
        self.assertEqual(result['routeId'], routeId)
        self.assertEqual(str(result['nodes'][0]), "{'latitude': 49.7067624, 'longitude': 7.6690793, 'label': 'Lindenallee', 'tMin': '2090-03-01T13:30:00Z', 'tMax': '2090-03-01T13:33:00Z'}")
        self.assertEqual(str(result['nodes'][1]), "{'latitude': 49.7079532, 'longitude': 7.6721057, 'label': 'Untergasse', 'tMin': '2090-03-01T13:33:00Z', 'tMax': '2090-03-01T13:36:00Z'}")

        ##############################################################################
        # repeat order - must not be allowed du to max. load exceeded
        order_id3 = order_id2+1
        busesToSmallEx = False

        try:  
            result = None          
            result = GetRequestManager().order(start_location=startLocation1, stop_location=stopLocation1, start_window=startWindow1, stop_window=stopWindow1, load=100, loadWheelchair=loadWheelchair1, order_id=order_id3)
        except BusesTooSmall:
            busesToSmallEx = True

        self.assertTrue(busesToSmallEx)
        self.assertIsNone(result)

        ##############################################################################
        # activate OSRM for third repeat
        GetRequestManager().OSRM_activated = True  

        # do the same order a third time
        order_id3 = order_id2+1
        result = GetRequestManager().order(start_location=startLocation1, stop_location=stopLocation1, start_window=startWindow1, stop_window=stopWindow1, load=load1, loadWheelchair=loadWheelchair1, order_id=order_id3)
        
        self.assertEqual(order_id3, result)        
        orderCheck3 = Order.objects.get(uid=order_id3)
        #print(orderCheck)
        self.assertEqual(order_id3, orderCheck3.uid)
        self.assertEqual(load1, orderCheck3.load)
        self.assertEqual(loadWheelchair1, orderCheck3.loadWheelchair)
        self.assertEqual(self.test_data.Lindenallee_mapId, orderCheck3.hopOnNode.mapId)
        self.assertEqual(self.test_data.Untergasse_mapId, orderCheck3.hopOffNode.mapId)
        self.assertEqual(None, orderCheck.group_id)

        self.assertEqual(Route.objects.count(),1)
        routeId = Route.objects.last().id

        resultRoute = driver_details(routeId)
        #print(resultRoute)
        self.assertEqual(len(resultRoute['nodes']), 2)
        
        result = order_details(routeId, order_id3)
        #print(result)
        self.assertEqual(len(result['nodes']), 2)
        self.assertEqual(result['routeId'], routeId)
        self.assertEqual(str(result['nodes'][0]), "{'latitude': 49.7067624, 'longitude': 7.6690793, 'label': 'Lindenallee', 'tMin': '2090-03-01T13:30:00Z', 'tMax': '2090-03-01T13:33:00Z'}")
        self.assertEqual(str(result['nodes'][1]), "{'latitude': 49.7079532, 'longitude': 7.6721057, 'label': 'Untergasse', 'tMin': '2090-03-01T13:33:00Z', 'tMax': '2090-03-01T13:36:00Z'}")
        

        GetRequestManager().OSRM_activated = OSRM_activated_in_Test 
    
    @mock.patch('Routing_Api.mockups.stations.requests.get', side_effect=mocked_requests_get)
    def test_order_with_road_closures(self, mock_get):
        # check orders with road closures
        self.setUp

        OSRM_activated_in_Test = GetRequestManager().OSRM_activated

        # deactivate OSRM
        GetRequestManager().OSRM_activated = False

        # choose a non-existing order id
        order_id1 = Order.objects.all().aggregate(Max('uid'))['uid__max']
        order_id1 = order_id1 + 33 if order_id1 is not None else 33

        load1 = 1
        loadWheelchair1 = 0
        startLocation1 = self.test_data.s1_latitude, self.test_data.s1_longitude
        stopLocation1 = self.test_data.s2_latitude, self.test_data.s2_longitude        
        time1 = parse('2090-03-02T13:30.000+00:00')        
        startWindow1 = (time1, time1+relativedelta(minutes=10)) # departure!
        stopWindow1 = None

        result = GetRequestManager().order(start_location=startLocation1, stop_location=stopLocation1, start_window=startWindow1, stop_window=stopWindow1, load=load1, loadWheelchair=loadWheelchair1, order_id=order_id1)

        orderCheck = Order.objects.get(uid=order_id1)
        #print(orderCheck)
        self.assertEqual(order_id1, result)
        self.assertEqual(order_id1, orderCheck.uid)
        self.assertEqual(load1, orderCheck.load)
        self.assertEqual(loadWheelchair1, orderCheck.loadWheelchair)
        self.assertEqual(self.test_data.s1_mapId, orderCheck.hopOnNode.mapId)
        self.assertEqual(self.test_data.s2_mapId, orderCheck.hopOffNode.mapId)
        self.assertEqual(None, orderCheck.group_id)  

        self.assertEqual(Route.objects.count(),1)
        routeId1 = Route.objects.last().id              

        ##############################################################################
        # do the same order a second time without road closures
        order_id2 = order_id1+1

        time2 = parse('2090-03-03T13:30.000+00:00')        
        startWindow2 = (time2, time2+relativedelta(minutes=10)) # departure!

        result = GetRequestManager().order(start_location=startLocation1, stop_location=stopLocation1, start_window=startWindow2, stop_window=stopWindow1, load=load1, loadWheelchair=loadWheelchair1, order_id=order_id2)
        
        self.assertEqual(order_id2, result)        
        orderCheck2 = Order.objects.get(uid=order_id2)
        #print(orderCheck)
        self.assertEqual(order_id2, orderCheck2.uid)
        self.assertEqual(load1, orderCheck2.load)
        self.assertEqual(loadWheelchair1, orderCheck2.loadWheelchair)
        self.assertEqual(self.test_data.s1_mapId, orderCheck2.hopOnNode.mapId)
        self.assertEqual(self.test_data.s2_mapId, orderCheck2.hopOffNode.mapId)
        self.assertEqual(None, orderCheck.group_id)

        self.assertEqual(Route.objects.count(),2)
        routeId2 = Route.objects.last().id

        result1 = order_details(routeId1, order_id1)
        print(result1)           
        self.assertEqual(len(result1['nodes']), 2)
        self.assertEqual(result1['routeId'], routeId1)
        self.assertEqual(str(result1['nodes'][0]), "{'latitude': 52.3093421, 'longitude': 10.2505459, 'label': 's1', 'tMin': '2090-03-02T13:30:00Z', 'tMax': '2090-03-02T13:33:00Z'}")
        self.assertEqual(str(result1['nodes'][1]), "{'latitude': 52.3096315, 'longitude': 10.2467584, 'label': 's2', 'tMin': '2090-03-02T13:34:00Z', 'tMax': '2090-03-02T13:37:00Z'}")

        # for the second order the times must be shorter, since no road closure exists
        result2 = order_details(routeId2, order_id2)
        print(result2)
        self.assertEqual(len(result2['nodes']), 2)
        self.assertEqual(result2['routeId'], routeId2)
        self.assertEqual(str(result2['nodes'][0]), "{'latitude': 52.3093421, 'longitude': 10.2505459, 'label': 's1', 'tMin': '2090-03-03T13:30:00Z', 'tMax': '2090-03-03T13:33:00Z'}")
        self.assertEqual(str(result2['nodes'][1]), "{'latitude': 52.3096315, 'longitude': 10.2467584, 'label': 's2', 'tMin': '2090-03-03T13:33:00Z', 'tMax': '2090-03-03T13:36:00Z'}")
 
        GetRequestManager().OSRM_activated = OSRM_activated_in_Test

    @mock.patch('Routing_Api.mockups.stations.requests.get', side_effect=mocked_requests_get)
    def test_order_blocked_by_frozen_or_started_route_at_same_time(self, mock_get):
        self.setUp

        # HOTFIX for problem from 1.6.2022: frozen or started routes did not block concurrent new orders

        OSRM_activated_in_Test = GetRequestManager().OSRM_activated

        # deactivate OSRM
        GetRequestManager().OSRM_activated = False

        # choose a non-existing order id
        order_id1 = Order.objects.all().aggregate(Max('uid'))['uid__max']
        order_id1 = order_id1 + 33 if order_id1 is not None else 33

        load1 = 1
        loadWheelchair1 = 0
        startLocation1 = self.test_data.Lindenallee_latitude, self.test_data.Lindenallee_longitude
        stopLocation1 = self.test_data.Untergasse_latitude, self.test_data.Untergasse_longitude        
        time1 = parse('2090-03-01T13:30.000+00:00')        
        startWindow1 = (time1, time1+relativedelta(minutes=10)) # departure!
        stopWindow1 = None

        result = GetRequestManager().order(start_location=startLocation1, stop_location=stopLocation1, start_window=startWindow1, stop_window=stopWindow1, load=load1, loadWheelchair=loadWheelchair1, order_id=order_id1)
                
        orderCheck = Order.objects.get(uid=order_id1)
        #print(orderCheck)
        self.assertEqual(order_id1, result)
        self.assertEqual(order_id1, orderCheck.uid)
        self.assertEqual(load1, orderCheck.load)
        self.assertEqual(loadWheelchair1, orderCheck.loadWheelchair)
        self.assertEqual(self.test_data.Lindenallee_mapId, orderCheck.hopOnNode.mapId)
        self.assertEqual(self.test_data.Untergasse_mapId, orderCheck.hopOffNode.mapId)
        self.assertEqual(None, orderCheck.group_id)    

        ##############################################################################
        # freeze the one existing route, what here means: start the route!

        self.assertEqual(Route.objects.count(),1)
        routeId = Route.objects.last().id     
        self.assertEqual(Route.objects.get(id=routeId).status,Route.BOOKED)
        Route.objects.update(id=routeId, status=Route.STARTED)
        self.assertEqual(Route.objects.get(id=routeId).status,Route.STARTED)

        ##############################################################################
        # do an additional order at concurrent time
        # hoewer this one is accepted since it fits an existing "free route" exactly
        order_id2 = order_id1+1

        time2 = time1 + timedelta(minutes=2)    
        startWindow2 = (time2, time2+relativedelta(minutes=10)) # departure!
        stopWindow2 = None

        result = GetRequestManager().order(start_location=startLocation1, stop_location=stopLocation1, start_window=startWindow2, stop_window=stopWindow2, load=load1, loadWheelchair=loadWheelchair1, order_id=order_id2)
        
        self.assertEqual(order_id2, result)        
        orderCheck2 = Order.objects.get(uid=order_id2)
        #print(orderCheck)
        self.assertEqual(order_id2, orderCheck2.uid)
        self.assertEqual(load1, orderCheck2.load)
        self.assertEqual(loadWheelchair1, orderCheck2.loadWheelchair)
        self.assertEqual(self.test_data.Lindenallee_mapId, orderCheck2.hopOnNode.mapId)
        self.assertEqual(self.test_data.Untergasse_mapId, orderCheck2.hopOffNode.mapId)
        self.assertEqual(None, orderCheck.group_id)

        self.assertEqual(Route.objects.count(),1)
        self.assertEqual(routeId, Route.objects.last().id)

        resultRoute = driver_details(routeId)
        #print(resultRoute)
        strNode1= "{'latitude': 49.7067624, 'longitude': 7.6690793, 'label': 'Lindenallee', 'tMin': '2090-03-01T13:30:00Z', 'tMax': '2090-03-01T13:33:00Z', 'hopOns': [OrderedDict([('orderId', 33), ('seats', 1), ('seatsWheelchair', 0)]), OrderedDict([('orderId', 34), ('seats', 1), ('seatsWheelchair', 0)])], 'hopOffs': []}"
        strNode2= "{'latitude': 49.7079532, 'longitude': 7.6721057, 'label': 'Untergasse', 'tMin': '2090-03-01T13:33:00Z', 'tMax': '2090-03-01T13:36:00Z', 'hopOns': [], 'hopOffs': [OrderedDict([('orderId', 33), ('seats', 1), ('seatsWheelchair', 0)]), OrderedDict([('orderId', 34), ('seats', 1), ('seatsWheelchair', 0)])]}"
        self.assertEqual(len(resultRoute['nodes']), 2)
        self.assertEqual(str(resultRoute['nodes'][0]),strNode1)
        self.assertEqual(str(resultRoute['nodes'][1]),strNode2)        
        
        result = driver_details_busId(2, None, None)        
        self.assertEqual(len(result),1)
        self.assertEqual(str(result[0]),str(resultRoute))
        
        result = order_details(routeId, order_id1)
        #print(result)           
        self.assertEqual(len(result['nodes']), 2)
        self.assertEqual(result['routeId'], routeId)
        self.assertEqual(str(result['nodes'][0]), "{'latitude': 49.7067624, 'longitude': 7.6690793, 'label': 'Lindenallee', 'tMin': '2090-03-01T13:30:00Z', 'tMax': '2090-03-01T13:33:00Z'}")
        self.assertEqual(str(result['nodes'][1]), "{'latitude': 49.7079532, 'longitude': 7.6721057, 'label': 'Untergasse', 'tMin': '2090-03-01T13:33:00Z', 'tMax': '2090-03-01T13:36:00Z'}")

        result = order_details(routeId, order_id2)
        #print(result)
        self.assertEqual(len(result['nodes']), 2)
        self.assertEqual(result['routeId'], routeId)
        self.assertEqual(str(result['nodes'][0]), "{'latitude': 49.7067624, 'longitude': 7.6690793, 'label': 'Lindenallee', 'tMin': '2090-03-01T13:30:00Z', 'tMax': '2090-03-01T13:33:00Z'}")
        self.assertEqual(str(result['nodes'][1]), "{'latitude': 49.7079532, 'longitude': 7.6721057, 'label': 'Untergasse', 'tMin': '2090-03-01T13:33:00Z', 'tMax': '2090-03-01T13:36:00Z'}")        

        ##############################################################################
        # do an additional order at concurrent time which is not realizable
        # muste be rejected

        order_id3 = order_id2+1        

        result = GetRequestManager().order(start_location=stopLocation1, stop_location=startLocation1, start_window=startWindow2, stop_window=stopWindow2, load=load1, loadWheelchair=loadWheelchair1, order_id=order_id3)
        
        self.assertIsNone(result)         
        self.assertEqual(Route.objects.count(),1)
        self.assertEqual(routeId, Route.objects.last().id)

        # route must remain unchanged
        resultRoute = driver_details(routeId)
        #print(resultRoute)
        self.assertEqual(len(resultRoute['nodes']), 2)
        self.assertEqual(str(resultRoute['nodes'][0]),strNode1)
        self.assertEqual(str(resultRoute['nodes'][1]),strNode2)    

        GetRequestManager().OSRM_activated = OSRM_activated_in_Test 

    @mock.patch('Routing_Api.mockups.stations.requests.get', side_effect=mocked_requests_get)
    def test_order_out_of_timeslot_check_correct_error_message(self, mock_get):
        self.setUp

        # if time is requested close to time slot but not inside slot, out-of-timeslot-error MUST be returned        

        # choose a non-existing order id
        order_id1 = Order.objects.all().aggregate(Max('uid'))['uid__max']
        order_id1 = order_id1 + 33 if order_id1 is not None else 33

        load1 = 1
        loadWheelchair1 = 0
        startLocation1 = self.test_data.Lindenallee_latitude, self.test_data.Lindenallee_longitude
        stopLocation1 = self.test_data.Untergasse_latitude, self.test_data.Untergasse_longitude        
        time1 = parse('2090-03-01T16:00.000+00:00')        
        startWindow1 = (time1, time1+relativedelta(minutes=10)) # departure!
        stopWindow1 = None

        noBusInTimeSlot = False
        result = None

        try:
            result = GetRequestManager().order(start_location=startLocation1, stop_location=stopLocation1, start_window=startWindow1, stop_window=stopWindow1, load=load1, loadWheelchair=loadWheelchair1, order_id=order_id1)
        except NoBuses:
            noBusInTimeSlot = True       

        self.assertTrue(noBusInTimeSlot)
        self.assertIsNone(result) 

    @mock.patch('Routing_Api.mockups.stations.requests.get', side_effect=mocked_requests_get)
    def test_is_bookable_in_blocker_check_correct_error_message(self, mock_get):
        self.setUp

        # the user must not get an "out of service times" response                

        load1 = 1
        loadWheelchair1 = 0
        startLocation1 = self.test_data.s1_latitude, self.test_data.s1_longitude
        stopLocation1 = self.test_data.s2_latitude, self.test_data.s2_longitude        
        time1 = parse('2090-03-02T08:10.000+00:00')        
        startWindow1 = (time1, time1+relativedelta(minutes=10)) # departure!
        stopWindow1 = None

        noBusInTimeSlot = False
        result = None

        try:
            result = GetRequestManager().is_bookable(start_location=startLocation1, stop_location=stopLocation1, start_window=startWindow1, stop_window=stopWindow1, load=load1, loadWheelchair=loadWheelchair1)
        except NoBuses:
            noBusInTimeSlot = True   

        #print(result)    

        self.assertFalse(noBusInTimeSlot)
        self.assertIsNotNone(result)
        self.assertEqual(5, len(result))
        self.assertFalse(result[0])
        self.assertEqual(GetRequestManager().NO_BUSES_DUE_TO_BLOCKER, result[1])
        self.assertEqual('No buses available in time window due to time blocker.', result[2])
        self.assertEqual([], result[3])
        self.assertEqual('[]', str(result[4]))

    @mock.patch('Routing_Api.mockups.stations.requests.get', side_effect=mocked_requests_get)
    def test_is_bookable_search_alternatives_earlier(self, mock_get):
        self.setUp

        OSRM_activated_in_Test = GetRequestManager().OSRM_activated

        # deactivate OSRM
        GetRequestManager().OSRM_activated = False

        # check order and find alternatives        

        # choose a non-existing order id
        order_id1 = Order.objects.all().aggregate(Max('uid'))['uid__max']
        order_id1 = order_id1 + 33 if order_id1 is not None else 33

        # define order request that cannot be satisfied in requested time and search for alternatives
        load1 = 1
        loadWheelchair1 = 0
        startLocation1 = self.test_data.Lindenallee_latitude, self.test_data.Lindenallee_longitude
        stopLocation1 = self.test_data.Untergasse_latitude, self.test_data.Untergasse_longitude        
        time1 = parse('2090-03-01T16:00.000+00:00')        
        startWindow1 = (time1, time1+relativedelta(minutes=10)) # departure!
        stopWindow1 = None

        noBusInTimeSlot = False
        result = None

        timeStarted = time.time()       

        try:
            result = GetRequestManager().is_bookable(start_location=startLocation1, stop_location=stopLocation1, start_window=startWindow1, stop_window=stopWindow1, load=load1, loadWheelchair=loadWheelchair1, alternatives_mode=RequestManagerConfig.ALTERNATIVE_SEARCH_EARLIER)
        except NoBuses:
            noBusInTimeSlot = True     

        timeElapsed = time.time() - timeStarted
        
        # performance must not be too bad if a big number of variants is calculated inside
        self.assertGreater(6.2, timeElapsed)  

        self.assertFalse(noBusInTimeSlot) # exception must not be raised
        self.assertIsNotNone(result)  
        self.assertEqual(5, len(result))
        self.assertTrue(result[0])
        self.assertEqual(result[1], 10)
        self.assertEqual(result[2], 'Hurray')
        self.assertEqual(str(result[4]), '[datetime.datetime(2090, 3, 1, 14, 0, tzinfo=tzlocal()), datetime.datetime(2090, 3, 1, 16, 0, tzinfo=tzlocal())]')
        self.maxDiff = None

        self.assertEqual(len(result[3]), 11)
        resultCmp = '(datetime.datetime(2090, 3, 1, 15, 40, tzinfo=tzlocal()), datetime.datetime(2090, 3, 1, 15, 50, tzinfo=tzlocal()))'
        self.assertEqual(str(result[3][0]), resultCmp)
        resultCmp = '(datetime.datetime(2090, 3, 1, 15, 30, tzinfo=tzlocal()), datetime.datetime(2090, 3, 1, 15, 40, tzinfo=tzlocal()))'
        self.assertEqual(str(result[3][1]), resultCmp)
        resultCmp = '(datetime.datetime(2090, 3, 1, 15, 20, tzinfo=tzlocal()), datetime.datetime(2090, 3, 1, 15, 30, tzinfo=tzlocal()))'
        self.assertEqual(str(result[3][2]), resultCmp)

        resultCmp = '(datetime.datetime(2090, 3, 1, 14, 0, tzinfo=tzlocal()), datetime.datetime(2090, 3, 1, 14, 10, tzinfo=tzlocal()))'
        self.assertEqual(str(result[3][10]), resultCmp)

        # test search later - should get no solution due to not existing bus availability but adequate response
        result = GetRequestManager().is_bookable(start_location=startLocation1, stop_location=stopLocation1, start_window=startWindow1, stop_window=stopWindow1, load=load1, loadWheelchair=loadWheelchair1, alternatives_mode=RequestManagerConfig.ALTERNATIVE_SEARCH_LATER)
        self.assertIsNotNone(result)  
        self.assertFalse(result[0])
        self.assertEqual(result[1], 11)
        self.assertEqual(result[2], f"No routing found for request (including alternatives search) - Start: {self.test_data.Lindenallee_name} {startLocation1}, Destination: {self.test_data.Untergasse_name} {stopLocation1}, Time: {time1.strftime('%Y/%m/%d, %H:%M')} (UTC), Seats: {load1} standard, {loadWheelchair1} wheelchair.")
        self.assertEqual(str(result[3]), '[]')       
        self.assertEqual(str(result[4]), '[datetime.datetime(2090, 3, 1, 16, 0, tzinfo=tzlocal()), datetime.datetime(2090, 3, 1, 18, 0, tzinfo=tzlocal())]')

        # reset OSRM mode
        GetRequestManager().OSRM_activated = OSRM_activated_in_Test



    @mock.patch('Routing_Api.mockups.stations.requests.get', side_effect=mocked_requests_get)
    def test_driver_details_with_gps(self, mock_get):
        self.setUp

        OSRM_activated_in_Test = GetRequestManager().OSRM_activated

        # deactivate OSRM
        GetRequestManager().OSRM_activated = False

        # choose a non-existing order id
        order_id1 = Order.objects.all().aggregate(Max('uid'))['uid__max']
        order_id1 = order_id1 + 33 if order_id1 is not None else 33

        load1 = 0
        loadWheelchair1 = 1
        startLocation1 = self.test_data.Lindenallee_latitude, self.test_data.Lindenallee_longitude
        stopLocation1 = self.test_data.Untergasse_latitude, self.test_data.Untergasse_longitude        
        time1 = parse('2090-03-01T13:50.000+00:00')        
        startWindow1 = (time1, time1+relativedelta(minutes=10)) # departure!
        stopWindow1 = None

        result = GetRequestManager().order(start_location=startLocation1, stop_location=stopLocation1, start_window=startWindow1, stop_window=stopWindow1, load=load1, loadWheelchair=loadWheelchair1, order_id=order_id1)
                
        orderCheck = Order.objects.get(uid=order_id1)
        # print(f"orderCheck: {orderCheck}")
        self.assertEqual(order_id1, result)
        self.assertEqual(order_id1, orderCheck.uid)
        self.assertEqual(load1, orderCheck.load)
        self.assertEqual(loadWheelchair1, orderCheck.loadWheelchair)
        self.assertEqual(self.test_data.Lindenallee_mapId, orderCheck.hopOnNode.mapId)
        self.assertEqual(self.test_data.Untergasse_mapId, orderCheck.hopOffNode.mapId)
        self.assertEqual(None, orderCheck.group_id)        
        # # activate OSRM
        # GetRequestManager().OSRM_activated = True

        # do not forget that the available buses are mocked and may have restricted capa -> test may fail with wheelchair and seat
        load2 = 1
        loadWheelchair2 = 0
        order_id2 = order_id1+1
        startLocation2 = stopLocation1
        stopLocation2 = self.test_data.Roth_latitude, self.test_data.Roth_longitude        
        time2 = parse('2090-03-01T13:50.000+00:00')        
        startWindow2 = (time2, time2+relativedelta(minutes=10)) # departure!
        stopWindow2 = None

        result = GetRequestManager().order(start_location=startLocation2, stop_location=stopLocation2, start_window=startWindow2, stop_window=stopWindow2, load=load2, loadWheelchair=loadWheelchair2, order_id=order_id2)
        
        self.assertEqual(order_id2, result)        
        orderCheck2 = Order.objects.get(uid=order_id2)
        # print(f"orderCheck2: {orderCheck}")
        self.assertEqual(order_id2, orderCheck2.uid)
        self.assertEqual(load2, orderCheck2.load)
        self.assertEqual(loadWheelchair2, orderCheck2.loadWheelchair)
        self.assertEqual(self.test_data.Untergasse_mapId, orderCheck2.hopOnNode.mapId)
        self.assertEqual(self.test_data.Roth_mapId, orderCheck2.hopOffNode.mapId)
        self.assertEqual(None, orderCheck.group_id)

        self.assertEqual(Route.objects.count(),1)
        routeId = Route.objects.last().id

        resultRoute = driver_details(routeId)
        # print(f"resultRoute: {resultRoute}")
        self.assertEqual(len(resultRoute['nodes']), 4)
        # note: in future we might combine nodes that have same station within same time window, up to no each hop_on gets its own node
        self.assertEqual(str(resultRoute['nodes'][0]),"{'latitude': 49.7067624, 'longitude': 7.6690793, 'label': 'Lindenallee', 'tMin': '2090-03-01T13:50:00Z', 'tMax': '2090-03-01T13:53:00Z', 'hopOns': [OrderedDict([('orderId', 33), ('seats', 0), ('seatsWheelchair', 1)])], 'hopOffs': []}")
        
        # sequence may differ, thus we cannot test a fixed sequence
        strCmp1 = "{'latitude': 49.7079532, 'longitude': 7.6721057, 'label': 'Untergasse', 'tMin': '2090-03-01T13:57:00Z', 'tMax': '2090-03-01T14:00:00Z', 'hopOns': [], 'hopOffs': [OrderedDict([('orderId', 33), ('seats', 0), ('seatsWheelchair', 1)])]}"
        strCmp2 = "{'latitude': 49.7079532, 'longitude': 7.6721057, 'label': 'Untergasse', 'tMin': '2090-03-01T13:57:00Z', 'tMax': '2090-03-01T14:00:00Z', 'hopOns': [OrderedDict([('orderId', 34), ('seats', 1), ('seatsWheelchair', 0)])], 'hopOffs': []}"
                
        self.assertTrue(str(resultRoute['nodes'][1]) == strCmp1 or str(resultRoute['nodes'][2]) == strCmp1)
        self.assertTrue(str(resultRoute['nodes'][1]) == strCmp2 or str(resultRoute['nodes'][2]) == strCmp2)

        self.assertEqual(str(resultRoute['nodes'][3]),"{'latitude': 49.6751843, 'longitude': 7.6753142, 'label': 'Roth', 'tMin': '2090-03-01T14:04:00Z', 'tMax': '2090-03-01T14:07:00Z', 'hopOns': [], 'hopOffs': [OrderedDict([('orderId', 34), ('seats', 1), ('seatsWheelchair', 0)])]}")

        result = driver_details_busId(2, None, None)        
        self.assertEqual(len(result),1)
        self.assertEqual(str(result[0]),str(resultRoute))
        
        result = order_details(routeId, order_id1)
        #print(f"result (order_details1): {result}")          
                 
        self.assertTrue(len(result['nodes']) == 2 or len(result['nodes']) == 3)
        self.assertEqual(result['routeId'], routeId)
        self.assertEqual(str(result['nodes'][0]), "{'latitude': 49.7067624, 'longitude': 7.6690793, 'label': 'Lindenallee', 'tMin': '2090-03-01T13:50:00Z', 'tMax': '2090-03-01T13:53:00Z'}")
        strCmp3 = "{'latitude': 49.7079532, 'longitude': 7.6721057, 'label': 'Untergasse', 'tMin': '2090-03-01T13:57:00Z', 'tMax': '2090-03-01T14:00:00Z'}"
        self.assertEqual(str(result['nodes'][1]), strCmp3)

        if len(result['nodes']) == 3: # sometimes the node is splitted
            self.assertEqual(str(result['nodes'][2]), strCmp3)

        # check gps coords of order
        result_gps = order_details_with_gps(routeId, order_id1)
        # print(f"result_gps1: {result_gps}")
        self.assertEqual(len(result['nodes']), len(result_gps['nodes']))
        self.assertEqual(result_gps['routeId'], result['routeId'])
        self.assertEqual(str(result['nodes'][0]), str(result_gps['nodes'][0]))
        self.assertEqual(str(result['nodes'][1]), str(result_gps['nodes'][1]))
        self.assertEqual(len(result_gps['gps']), len(result_gps['nodes'])-1)
        self.assertEqual(len(result_gps['gps'][0]), 31)
        self.assertAlmostEqual(result_gps['gps'][0][0][0], self.test_data.Lindenallee_latitude, 4) 
        self.assertAlmostEqual(result_gps['gps'][0][0][1], self.test_data.Lindenallee_longitude, 4) 
        self.assertAlmostEqual(result_gps['gps'][0][-1][0], self.test_data.Untergasse_latitude, 4)  
        self.assertAlmostEqual(result_gps['gps'][0][-1][1], self.test_data.Untergasse_longitude, 4) 

        result = order_details(routeId, order_id2)
        #print(f"result (order_details2): {result}")

        self.assertTrue(len(result['nodes']) == 2 or len(result['nodes']) == 3)
        self.assertEqual(result['routeId'], routeId)
        self.assertEqual(str(result['nodes'][0]), strCmp3)
        strCmp4 = "{'latitude': 49.6751843, 'longitude': 7.6753142, 'label': 'Roth', 'tMin': '2090-03-01T14:04:00Z', 'tMax': '2090-03-01T14:07:00Z'}"

        if len(result['nodes']) == 3: # sometimes the node is splitted
            self.assertEqual(str(result['nodes'][1]), strCmp3)
            self.assertEqual(str(result['nodes'][2]), strCmp4)
        else:
            self.assertEqual(str(result['nodes'][1]), strCmp4)

        # check gps coords of order
        result_gps = order_details_with_gps(routeId, order_id2)
        # print(f"result_gps2: {result_gps}")
        self.assertEqual(len(result['nodes']), len(result_gps['nodes']))
        self.assertEqual(result_gps['routeId'], result['routeId'])
        self.assertEqual(str(result['nodes'][0]), str(result_gps['nodes'][0]))
        self.assertEqual(str(result['nodes'][1]), str(result_gps['nodes'][1]))
        self.assertEqual(len(result_gps['gps']), len(result_gps['nodes'])-1)

        indexHelp = len(result_gps['gps'])-1

        self.assertEqual(len(result_gps['gps'][indexHelp]), 247)
        self.assertAlmostEqual(result_gps['gps'][indexHelp][0][0], self.test_data.Untergasse_latitude, 4) 
        self.assertAlmostEqual(result_gps['gps'][indexHelp][0][1], self.test_data.Untergasse_longitude, 4) 
        self.assertAlmostEqual(result_gps['gps'][indexHelp][-1][0], self.test_data.Roth_latitude, 4)  
        self.assertAlmostEqual(result_gps['gps'][indexHelp][-1][1], self.test_data.Roth_longitude, 4) 

        result_route_gps = driver_details_with_gps(routeId)
        self.assertEqual(len(result_route_gps['orders']), 2)
        self.assertAlmostEqual(result_route_gps['orders'][0]['nodes'][0]['latitude'], self.test_data.Lindenallee_latitude, 4)
        self.assertAlmostEqual(result_route_gps['orders'][0]['nodes'][0]['longitude'], self.test_data.Lindenallee_longitude, 4)
        self.assertAlmostEqual(result_route_gps['orders'][0]['nodes'][-1]['latitude'], self.test_data.Untergasse_latitude, 4)
        self.assertAlmostEqual(result_route_gps['orders'][0]['nodes'][-1]['longitude'], self.test_data.Untergasse_longitude, 4)
        self.assertAlmostEqual(result_route_gps['orders'][-1]['nodes'][0]['latitude'], self.test_data.Untergasse_latitude, 4)
        self.assertAlmostEqual(result_route_gps['orders'][-1]['nodes'][0]['longitude'], self.test_data.Untergasse_longitude, 4)
        self.assertAlmostEqual(result_route_gps['orders'][-1]['nodes'][-1]['latitude'], self.test_data.Roth_latitude, 4)
        self.assertAlmostEqual(result_route_gps['orders'][-1]['nodes'][-1]['longitude'], self.test_data.Roth_longitude, 4)

        # print(f"##################### complete route with gps #####################\n{result_route_gps}")
        GetRequestManager().OSRM_activated = OSRM_activated_in_Test
                      
            
#################################################################################

@tag('rabbitmq')
class RabbitMQ(LiveServerTestCase, Setups):
    serialised_rollback=True
    def setUp(self):
        self.init_db()
        self.init_rabbit()
        self.test_data = Test_Data()
    
    def tearDown(self):
        pass
    
    @mock.patch('Routing_Api.mockups.stations.requests.get', side_effect=mocked_requests_get)
    def test_valid_OrderStartedIntegrationEvent_singleRoute(self, mock_get):
        self.setUp

        OSRM_activated_in_Test = GetRequestManager().OSRM_activated
        GetRequestManager().OSRM_activated = False # does not work with OSRM

        # choose a non-existing order id
        order_id = Order.objects.all().aggregate(Max('uid'))['uid__max']
        order_id = order_id + 33 if order_id is not None else 33

        load = 1
        loadWheelchair = 1

        data = {"StartLatitude": self.test_data.Lindenallee_latitude, "StartLongitude": self.test_data.Lindenallee_longitude, "EndLatitude": self.test_data.Untergasse_latitude, "EndLongitude": self.test_data.Untergasse_longitude,
                "Time": '2090-03-01T13:50.000+00:00', "Seats": load, "SeatsWheelchair": loadWheelchair, "IsDeparture": True, "Id": order_id}
            
        # send request
        self.publisher.publish(message=json.dumps(data), routing_key='OrderStartedIntegrationEvent')

        # wait just a moment to let our server react
        sleep(5)   

        orderCheck = None     

        try:
            orderCheck = Order.objects.get(uid=order_id)
        except:
            # wait just a moment to let our server react
            sleep(10) 
            orderCheck = Order.objects.get(uid=order_id)

        #print(orderCheck)
        self.assertEqual(order_id, orderCheck.uid)
        self.assertEqual(load, orderCheck.load)
        self.assertEqual(loadWheelchair, orderCheck.loadWheelchair)
        self.assertEqual(self.test_data.Lindenallee_mapId, orderCheck.hopOnNode.mapId)
        self.assertEqual(self.test_data.Untergasse_mapId, orderCheck.hopOffNode.mapId)
        self.assertEqual(None, orderCheck.group_id)

        GetRequestManager().OSRM_activated = OSRM_activated_in_Test        

    @mock.patch('Routing_Api.mockups.stations.requests.get', side_effect=mocked_requests_get)
    def test_valid_OrderStartedIntegrationEvent_interactingRoutes(self, mock_get):
        self.setUp

        # orders need to be empty
        self.assertEqual(0, Order.objects.count())

        OSRM_activated_in_Test = GetRequestManager().OSRM_activated
        GetRequestManager().OSRM_activated = False # does not work with OSRM

        # choose a non-existing order id
        order_id = Order.objects.all().aggregate(Max('uid'))['uid__max']
        order_id = order_id + 33 if order_id is not None else 33

        load = 1
        loadWheelchair = 0

        data = {"StartLatitude": self.test_data.Lindenallee_latitude, "StartLongitude": self.test_data.Lindenallee_longitude, "EndLatitude": self.test_data.Untergasse_latitude, "EndLongitude": self.test_data.Untergasse_longitude,
                "Time": '2090-03-01T13:20.000+00:00', "Seats": load, "SeatsWheelchair": loadWheelchair, "IsDeparture": True, "Id": order_id}

        # send request
        self.publisher.publish(message=json.dumps(data), routing_key='OrderStartedIntegrationEvent')

        # wait just a moment to let our server react
        sleep_steps_max = 10
        sleep_step = 2

        for iStep in range(1,sleep_steps_max):
            sleep(sleep_step)
            if Order.objects.filter(uid=order_id).exists():
                sleep(1)
                #print(iStep)
                break

        orderCheck = Order.objects.get(uid=order_id)
        self.assertEqual(order_id, orderCheck.uid)
        self.assertEqual(load, orderCheck.load)
        self.assertEqual(loadWheelchair, orderCheck.loadWheelchair)
        self.assertEqual(self.test_data.Lindenallee_mapId, orderCheck.hopOnNode.mapId)
        self.assertEqual(self.test_data.Untergasse_mapId, orderCheck.hopOffNode.mapId)
        self.assertEqual(None, orderCheck.group_id)

        # check route 1
        routeCheck1 = Route.objects.last()
        route1_id = routeCheck1.id
        self.assertEqual(routeCheck1.busId, 2)
        routeClients1: set = routeCheck1.clients()
        self.assertEqual(len(routeClients1), 1)
        it = iter(routeClients1)
        self.assertEqual(next(it), order_id)

        # check what is the result for the driver
        response1 = self.client.get(reverse('RoutendetailsBusId', kwargs={'busId': routeCheck1.busId}))

        self.assertEqual(response1.status_code, 200)
        self.assertEqual(len(response1.data), 1)
        route = response1.data[0]
        self.assertEqual(route['busId'], routeCheck1.busId)
        self.assertEqual(route['status'], 'Booked')
        self.assertEqual(route['routeId'], route1_id)
        self.assertEqual(len(route['nodes']),2)

        # check proper times and stations: 1 minute from Lindenallee to Untergasse
        timeLindenalleeCmp = '2090-03-01T13:20:00Z'
        timeLindenalleeCmp2 = '2090-03-01T13:23:00Z'
        timeUntergasseCmp = '2090-03-01T13:23:00Z'
        timeUntergasseCmp2 = '2090-03-01T13:26:00Z'

        self.assertEqual(route['nodes'][0]['latitude'],self.test_data.Lindenallee_latitude)
        self.assertEqual(route['nodes'][0]['tMin'],timeLindenalleeCmp)
        self.assertEqual(route['nodes'][0]['tMax'],timeLindenalleeCmp2)
        self.assertEqual(route['nodes'][1]['latitude'],self.test_data.Untergasse_latitude)
        self.assertEqual(route['nodes'][1]['tMin'],timeUntergasseCmp)
        self.assertEqual(route['nodes'][1]['tMax'],timeUntergasseCmp2)
        self.assertEqual(len(route['nodes'][0]['hopOns']), 1)
        self.assertEqual(route['nodes'][0]['hopOns'][0]['orderId'], order_id)
        self.assertEqual(len(route['nodes'][0]['hopOffs']), 0)
        self.assertEqual(len(route['nodes'][1]['hopOns']), 0)
        self.assertEqual(len(route['nodes'][1]['hopOffs']), 1)
        self.assertEqual(route['nodes'][1]['hopOffs'][0]['orderId'], order_id)

        # driver should see the same info if he requests the route
        response2 = self.client.get(reverse('RoutendetailsAnfrageBusfahrer', kwargs={'routeId': routeCheck1.id}))
        
        self.assertEqual(response2.status_code, 200)
        routeCmp = response2.data
        self.assertEqual(routeCmp, route)

        ################################################################################################
        # second route at same time in different direction - should be grouped properly

        # do the update stuff done by celery worker - should not change the data unexpected
        tasks.freeze_routes()    
        tasks.delete_routes()
        tasks.delete_empty_routes()
        tasks.delete_unused_nodes()
        tasks.split_routes()

        order_id2 = order_id+1
        
        data = {"StartLatitude": self.test_data.Roth_latitude, "StartLongitude": self.test_data.Roth_longitude, "EndLatitude": self.test_data.Lindenallee_latitude, "EndLongitude": self.test_data.Lindenallee_longitude,
                "Time": '2090-03-01T13:50.000+00:00', "Seats": load, "SeatsWheelchair": loadWheelchair, "IsDeparture": True, "Id": order_id2}

        # send request
        self.publisher.publish(message=json.dumps(data), routing_key='OrderStartedIntegrationEvent')

        # wait just a moment to let our server react
        for iStep in range(1,sleep_steps_max):
            sleep(sleep_step)
            if Order.objects.filter(uid=order_id2).exists():
                sleep(3)
                #print(iStep)
                break

        orderCheck = Order.objects.get(uid=order_id2)
        
        self.assertEqual(order_id2, orderCheck.uid)
        self.assertEqual(load, orderCheck.load)
        self.assertEqual(loadWheelchair, orderCheck.loadWheelchair)
        self.assertEqual(self.test_data.Roth_mapId, orderCheck.hopOnNode.mapId)
        self.assertEqual(self.test_data.Lindenallee_mapId, orderCheck.hopOffNode.mapId)
        self.assertEqual(None, orderCheck.group_id)

        # check route 2 - must contain the 2 orders, repo contains only one modified route
        routeCheck2 = Route.objects.last()    
        self.assertEqual(Route.objects.count(), 1)
        route2_id = routeCheck2.id
        self.assertEqual(routeCheck2.busId, 2)
        routeClients2: set = routeCheck2.clients()
        self.assertEqual(len(routeCheck2.clients()), 2)
        it = iter(routeClients2)
        self.assertEqual(next(it), order_id)
        self.assertEqual(next(it), order_id2)
        self.assertEqual(str(routeCheck2.needed_capacity), 'MobyLoad(1, 0)')
        
        response1 = self.client.get(reverse('RoutendetailsBusId', kwargs={'busId': 2}))
        self.assertEqual(response1.status_code, 200)

        self.assertEqual(len(response1.data), 1)
        route2 = response1.data[0]
        self.assertEqual(route2['busId'], 2)
        self.assertEqual(route2['status'], 'Booked')
        self.assertEqual(route2['routeId'], route2_id)
        self.assertEqual(len(route2['nodes']),4)

        # check proper times and stations: times from Lindenallee to Untergasse should not be changed        
        self.assertEqual(route2['nodes'][0]['latitude'],self.test_data.Lindenallee_latitude)
        self.assertEqual(route2['nodes'][0]['tMin'],timeLindenalleeCmp)
        self.assertEqual(route2['nodes'][0]['tMax'],timeLindenalleeCmp2)
        self.assertEqual(route2['nodes'][1]['latitude'],self.test_data.Untergasse_latitude)
        self.assertEqual(route2['nodes'][1]['tMin'],timeUntergasseCmp)
        self.assertEqual(route2['nodes'][1]['tMax'],timeUntergasseCmp2)
        self.assertEqual(route2['nodes'][2]['latitude'],self.test_data.Roth_latitude)
        self.assertEqual(route2['nodes'][2]['tMin'],'2090-03-01T13:50:00Z')
        self.assertEqual(route2['nodes'][2]['tMax'],'2090-03-01T13:53:00Z')
        self.assertEqual(route2['nodes'][3]['latitude'],self.test_data.Lindenallee_latitude)
        self.assertEqual(route2['nodes'][3]['tMin'],'2090-03-01T13:57:00Z')
        self.assertEqual(route2['nodes'][3]['tMax'],'2090-03-01T14:00:00Z')
        self.assertEqual(len(route2['nodes'][0]['hopOns']), 1)
        self.assertEqual(route2['nodes'][0]['hopOns'][0]['orderId'], order_id)
        self.assertEqual(len(route2['nodes'][0]['hopOffs']), 0)
        self.assertEqual(len(route2['nodes'][1]['hopOns']), 0)
        self.assertEqual(len(route2['nodes'][1]['hopOffs']), 1)
        self.assertEqual(route2['nodes'][1]['hopOffs'][0]['orderId'], order_id)
        self.assertEqual(len(route2['nodes'][2]['hopOns']), 1)
        self.assertEqual(route2['nodes'][2]['hopOns'][0]['orderId'], order_id2)
        self.assertEqual(len(route2['nodes'][2]['hopOffs']), 0)
        self.assertEqual(len(route2['nodes'][3]['hopOns']), 0)
        self.assertEqual(len(route2['nodes'][3]['hopOffs']), 1)
        self.assertEqual(route2['nodes'][3]['hopOffs'][0]['orderId'], order_id2)

        # old route must not exist, because it is now part of the new route
        response2 = self.client.get(reverse('RoutendetailsAnfrageBusfahrer', kwargs={'routeId': routeCheck1.id}))
        self.assertEqual(response2.status_code, 404)

        # driver should see the same info if he requests the route
        response3 = self.client.get(reverse('RoutendetailsAnfrageBusfahrer', kwargs={'routeId': routeCheck2.id}))
        self.assertEqual(response3.status_code, 200)
        routeCmp = response3.data
        self.assertEqual(routeCmp, route2)

        ################################################################################################
        # third route intersecting times and locations of prior route

        # do the update stuff done by celery worker - should not change the data unexpected
        tasks.freeze_routes()    
        tasks.delete_routes()
        tasks.delete_empty_routes()
        tasks.delete_unused_nodes()
        tasks.split_routes()

        order_id3 = order_id2+1
        load3 = 2 
        loadWheelchair3 = 0
        
        data = {"StartLatitude": self.test_data.Untergasse_latitude, "StartLongitude": self.test_data.Untergasse_longitude, "EndLatitude": self.test_data.Lindenallee_latitude, "EndLongitude": self.test_data.Lindenallee_longitude,
                "Time": '2090-03-01T13:30.000+00:00', "Seats": load3, "SeatsWheelchair": loadWheelchair3, "IsDeparture": False, "Id": order_id3}

        # send request
        self.publisher.publish(message=json.dumps(data), routing_key='OrderStartedIntegrationEvent')

        # wait just a moment to let our server react
        for iStep in range(1,sleep_steps_max):
            sleep(sleep_step)
            if Order.objects.filter(uid=order_id3).exists():
                sleep(3)
                #print(iStep)
                break   

        self.assertEqual(Order.objects.count(),3)
        orderCheck = Order.objects.get(uid=order_id3)
        self.assertEqual(order_id3, orderCheck.uid)
        self.assertEqual(load3, orderCheck.load)
        self.assertEqual(loadWheelchair3, orderCheck.loadWheelchair)
        self.assertEqual(self.test_data.Untergasse_mapId, orderCheck.hopOnNode.mapId)
        self.assertEqual(self.test_data.Lindenallee_mapId, orderCheck.hopOffNode.mapId)
        self.assertEqual(None, orderCheck.group_id)

        # check route 3 - must contain the 3 orders, repo contains only one modified route        
        routeCheck3 = Route.objects.last()    
        self.assertEqual(Route.objects.count(), 1)
        route3_id = routeCheck3.id
        self.assertEqual(routeCheck3.busId, 2)
        routeClients3: set = routeCheck3.clients()
        self.assertEqual(len(routeCheck3.clients()), 3)
        it = iter(routeClients3)
        self.assertEqual(next(it), order_id)
        self.assertEqual(next(it), order_id2)
        self.assertEqual(next(it), order_id3)

        # at the moment there is a problem: the optimizer solution is not unique, at Untergasse, the order of hopon/off may vary
        # todo einbauen, dass solche Knoten zusammengefuehrt werden
        self.assertTrue(str(routeCheck3.needed_capacity)== 'MobyLoad(3, 0)' or str(routeCheck3.needed_capacity) == 'MobyLoad(2, 0)')

        response1 = self.client.get(reverse('RoutendetailsBusId', kwargs={'busId': 2}))
        self.assertEqual(response1.status_code, 200)

        #print(response1.content)

        self.assertEqual(len(response1.data), 1)
        route3 = response1.data[0]
        self.assertEqual(route3['busId'], 2)
        self.assertEqual(route3['status'], 'Booked')
        self.assertEqual(route3['routeId'], route3_id)
        self.assertEqual(len(route3['nodes']),6)

        # check proper times and stations: times from Lindenallee to Untergasse should not be changed  
        self.assertEqual(route3['nodes'][0]['latitude'],self.test_data.Lindenallee_latitude)
        self.assertEqual(route3['nodes'][0]['tMin'],timeLindenalleeCmp)
        self.assertEqual(route3['nodes'][0]['tMax'],timeLindenalleeCmp2)
        self.assertEqual(route3['nodes'][1]['latitude'],self.test_data.Untergasse_latitude)
        self.assertEqual(route3['nodes'][1]['tMin'],timeUntergasseCmp)
        self.assertEqual(route3['nodes'][1]['tMax'],timeUntergasseCmp2)        
        self.assertEqual(route3['nodes'][2]['latitude'],self.test_data.Untergasse_latitude)
        self.assertEqual(route3['nodes'][2]['tMin'],timeUntergasseCmp)
        self.assertEqual(route3['nodes'][2]['tMax'],timeUntergasseCmp2)
        self.assertEqual(route3['nodes'][3]['latitude'],self.test_data.Lindenallee_latitude)
        self.assertEqual(route3['nodes'][3]['tMin'],'2090-03-01T13:29:00Z')
        self.assertEqual(route3['nodes'][3]['tMax'],'2090-03-01T13:30:00Z')
        self.assertEqual(route3['nodes'][4]['latitude'],self.test_data.Roth_latitude)
        self.assertEqual(route3['nodes'][4]['tMin'],'2090-03-01T13:50:00Z')
        self.assertEqual(route3['nodes'][4]['tMax'],'2090-03-01T13:51:00Z')
        self.assertEqual(route3['nodes'][5]['latitude'],self.test_data.Lindenallee_latitude)
        self.assertEqual(route3['nodes'][5]['tMin'],'2090-03-01T13:57:00Z')
        self.assertEqual(route3['nodes'][5]['tMax'],'2090-03-01T14:00:00Z')
        self.assertEqual(len(route3['nodes'][0]['hopOns']), 1)
        self.assertEqual(route3['nodes'][0]['hopOns'][0]['orderId'], order_id)
        self.assertEqual(len(route3['nodes'][0]['hopOffs']), 0)

        # at the moment there is a problem: the optimizer solution is not unique, at Untergasse, the order of hopon/off may vary
        if len(route3['nodes'][1]['hopOns'])== 1:            
            self.assertEqual(len(route3['nodes'][1]['hopOns']), 1)
            self.assertEqual(route3['nodes'][1]['hopOns'][0]['orderId'], order_id3)
            self.assertEqual(len(route3['nodes'][1]['hopOffs']), 0)
            self.assertEqual(len(route3['nodes'][2]['hopOns']), 0)
            self.assertEqual(len(route3['nodes'][2]['hopOffs']), 1)
            self.assertEqual(route3['nodes'][2]['hopOffs'][0]['orderId'], order_id)
        elif len(route3['nodes'][1]['hopOns'])== 0:    
            self.assertEqual(len(route3['nodes'][1]['hopOffs']), 1)
            self.assertEqual(route3['nodes'][1]['hopOffs'][0]['orderId'], order_id)
            self.assertEqual(len(route3['nodes'][1]['hopOns']), 0)
            self.assertEqual(len(route3['nodes'][2]['hopOffs']), 0)
            self.assertEqual(len(route3['nodes'][2]['hopOns']), 1)
            self.assertEqual(route3['nodes'][2]['hopOns'][0]['orderId'], order_id3)        
        else:
            # must not happen
            self.assertEqual(False)
        
        self.assertEqual(len(route3['nodes'][3]['hopOns']), 0)
        self.assertEqual(len(route3['nodes'][3]['hopOffs']), 1)
        self.assertEqual(route3['nodes'][3]['hopOffs'][0]['orderId'], order_id3)
        self.assertEqual(len(route3['nodes'][4]['hopOns']), 1)
        self.assertEqual(route3['nodes'][4]['hopOns'][0]['orderId'], order_id2)
        self.assertEqual(len(route3['nodes'][4]['hopOffs']), 0)
        self.assertEqual(len(route3['nodes'][5]['hopOns']), 0)
        self.assertEqual(len(route3['nodes'][5]['hopOffs']), 1)
        self.assertEqual(route3['nodes'][5]['hopOffs'][0]['orderId'], order_id2)

        # old route must not exist, because it is now part of the new route
        response2 = self.client.get(reverse('RoutendetailsAnfrageBusfahrer', kwargs={'routeId': routeCheck2.id}))
        self.assertEqual(response2.status_code, 404)

        # driver should see the same info if he requests the route
        response3 = self.client.get(reverse('RoutendetailsAnfrageBusfahrer', kwargs={'routeId': routeCheck3.id}))
        self.assertEqual(response3.status_code, 200)

        #print(response3.content)

        routeCmp = response3.data
        self.assertEqual(routeCmp, route3)

        # database must be ok
        self.assertTrue(tasks.check_routing_data())

        GetRequestManager().OSRM_activated = OSRM_activated_in_Test  

    @mock.patch('Routing_Api.mockups.stations.requests.get', side_effect=mocked_requests_get)
    def test_valid_OrderStartedIntegrationEvent_addAndDeleteRoutes_1(self, mock_get):
        self.setUp
        # check problems

        # orders need to be empty
        self.assertEqual(0, Order.objects.count())

        OSRM_activated_in_Test = GetRequestManager().OSRM_activated
        GetRequestManager().OSRM_activated = False # does not work with OSRM

        # choose a non-existing order id
        order_id = Order.objects.all().aggregate(Max('uid'))['uid__max']
        order_id = order_id + 33 if order_id is not None else 33

        load = 1
        loadWheelchair = 0

        data = {"StartLatitude": self.test_data.Roth_latitude, "StartLongitude": self.test_data.Roth_longitude, "EndLatitude": self.test_data.Bahnhof_latitude, "EndLongitude": self.test_data.Bahnhof_longitude,
                "Time": '2090-03-01T13:50.000+00:00', "Seats": load, "SeatsWheelchair": loadWheelchair, "IsDeparture": True, "Id": order_id}
        
        # send request
        self.publisher.publish(message=json.dumps(data), routing_key='OrderStartedIntegrationEvent')

        # wait just a moment to let our server react
        sleep_steps_max = 10
        sleep_step = 3

        for iStep in range(1,sleep_steps_max):
            sleep(sleep_step)
            if Order.objects.filter(uid=order_id).exists():
                sleep(1)
                #print(iStep)
                break

        orderCheck = Order.objects.get(uid=order_id)
        self.assertEqual(order_id, orderCheck.uid)
        self.assertEqual(load+2*loadWheelchair, orderCheck.load)
        self.assertEqual(self.test_data.Roth_mapId, orderCheck.hopOnNode.mapId)
        self.assertEqual(self.test_data.Bahnhof_mapId, orderCheck.hopOffNode.mapId)
        self.assertEqual(None, orderCheck.group_id)

        # check route 1
        routeCheck1 = Route.objects.last()
        route1_id = routeCheck1.id
        self.assertEqual(routeCheck1.busId, 2)
        routeClients1: set = routeCheck1.clients()
        self.assertEqual(len(routeClients1), 1)
        it = iter(routeClients1)
        self.assertEqual(next(it), order_id)   

        ################################################################################################
        # delete the first order
        
        self.assertEqual(243, Node.objects.count())

        self.publisher.publish(json.dumps({'Id': order_id}), 'OrderCancelledIntegrationEvent')
        sleep(2)        

        # hopOn/hopOff nodes are cleaned
        self.assertEqual(241, Node.objects.count())

        ################################################################################################
        # second order at close time, little bit earlier than first order

        order_id2 = order_id+1
        
        data = {"StartLatitude": self.test_data.Lindenallee_latitude, "StartLongitude": self.test_data.Lindenallee_longitude, "EndLatitude": self.test_data.Untergasse_latitude, "EndLongitude": self.test_data.Untergasse_longitude,
                "Time": '2090-03-01T13:20.000+00:00', "Seats": load, "SeatsWheelchair": loadWheelchair, "IsDeparture": True, "Id": order_id2}

        # send request
        self.publisher.publish(message=json.dumps(data), routing_key='OrderStartedIntegrationEvent')        

        # wait just a moment to let our server react
        for iStep in range(1,sleep_steps_max):
            sleep(sleep_step)           

            if Order.objects.filter(uid=order_id2).exists():
                sleep(2)
                #print(iStep)
                break 

        # do the update stuff done by celery worker - should not change the data unexpected
        tasks.freeze_routes()    
        tasks.delete_routes()
        tasks.delete_empty_routes()
        tasks.delete_unused_nodes()
        tasks.split_routes()       

        orderCheck = Order.objects.get(uid=order_id2)
        
        self.assertEqual(order_id2, orderCheck.uid)
        self.assertEqual(load+2*loadWheelchair, orderCheck.load)
        self.assertEqual(self.test_data.Lindenallee_mapId, orderCheck.hopOnNode.mapId)
        self.assertEqual(self.test_data.Untergasse_mapId, orderCheck.hopOffNode.mapId)
        self.assertEqual(None, orderCheck.group_id)        

        # check route 2 - must contain only the second order, repo contains only one modified route   
        routeCheck2 = Route.objects.last()    
        self.assertEqual(Route.objects.count(), 1)
        route2_id = routeCheck2.id
        self.assertEqual(routeCheck2.busId, 2)
        routeClients2: set = routeCheck2.clients()
        self.assertEqual(len(routeCheck2.clients()), 1)
        it = iter(routeClients2)
        self.assertEqual(next(it), order_id2)
        
        response1 = self.client.get(reverse('RoutendetailsBusId', kwargs={'busId': 2}))
        self.assertEqual(response1.status_code, 200)

        self.assertEqual(len(response1.data), 1)
        route2 = response1.data[0]
        self.assertEqual(route2['busId'], 2)
        self.assertEqual(route2['status'], 'Booked')
        self.assertEqual(route2['routeId'], route2_id)
        self.assertEqual(len(route2['nodes']),2)

        # check proper times and stations: times from Lindenallee to Untergasse should not be changed        
        self.assertEqual(route2['nodes'][0]['latitude'],self.test_data.Lindenallee_latitude)
        self.assertEqual(route2['nodes'][0]['tMin'],'2090-03-01T13:20:00Z')
        self.assertEqual(route2['nodes'][0]['tMax'],'2090-03-01T13:23:00Z')
        self.assertEqual(route2['nodes'][1]['latitude'],self.test_data.Untergasse_latitude)
        self.assertEqual(route2['nodes'][1]['tMin'],'2090-03-01T13:23:00Z')
        self.assertEqual(route2['nodes'][1]['tMax'],'2090-03-01T13:26:00Z')        
        self.assertEqual(len(route2['nodes'][0]['hopOns']), 1)
        self.assertEqual(route2['nodes'][0]['hopOns'][0]['orderId'], order_id2)
        self.assertEqual(len(route2['nodes'][0]['hopOffs']), 0)
        self.assertEqual(len(route2['nodes'][1]['hopOns']), 0)
        self.assertEqual(len(route2['nodes'][1]['hopOffs']), 1)
        self.assertEqual(route2['nodes'][1]['hopOffs'][0]['orderId'], order_id2)        

        # if old still existing, remember that deleting empty routes is done by tasks defined in CELERY_BEAT_SCHEDULE in productive environment
        response2 = self.client.get(reverse('RoutendetailsAnfrageBusfahrer', kwargs={'routeId': routeCheck1.id}))        

        self.assertEqual(len(response2.data), 1)        
        self.assertEqual(response2.status_code, 404)

        # driver should see the same info if he requests the route
        response3 = self.client.get(reverse('RoutendetailsAnfrageBusfahrer', kwargs={'routeId': routeCheck2.id}))
        self.assertEqual(response3.status_code, 200)
        routeCmp = response3.data
        self.assertEqual(routeCmp, route2)      

        # do the update stuff done by celery worker - should not change the data unexpected
        tasks.freeze_routes()    
        tasks.delete_routes()
        tasks.delete_empty_routes()
        tasks.delete_unused_nodes()
        tasks.split_routes()

        response4 = self.client.get(reverse('RoutendetailsBusId', kwargs={'busId': 2}))
        self.assertEqual(response4.data, response1.data)  

        # database must be ok
        self.assertTrue(tasks.check_routing_data())

        GetRequestManager().OSRM_activated = OSRM_activated_in_Test  

    def test_UpdateBusPositionIntegrationEvent(self):
        bus = Bus.objects.last()
        self.publisher.publish(
            message=json.dumps({
                'BusId': bus.uid,
                'Latitude': 12,
                'Longitude': 34,
                }),
            routing_key='UpdateBusPositionIntegrationEvent')
        sleep(0.2)
        updated_bus = Bus.objects.get(uid=bus.uid)
        self.assertTrue(abs(updated_bus.latitude-12) < 0.1)
        self.assertTrue(abs(updated_bus.longitude-34) < 0.1)


@tag('health')
class HealthCheck(TestCase):
    def test_health_endpoint_responds_with_200(self):
        client = Client()
        response = client.get(reverse('HealthCheck'))
        self.assertEqual(response.status_code, 200)

@tag('route_started')
class RouteStarted(TestCase, Setups):
    def setUp(self):
        self.single_route()
        self.second_community()
    
    def test_valid_case(self):
        self.route.freeze()
        self.route.save()
        response = self.client.put(reverse('RouteStarted', kwargs={'routeId': self.route.id}))
        self.assertEqual(response.status_code, 202)
        
        route = Route.objects.get(id=self.route.id)
        started_routes = list(Route.objects.started())
        self.assertEqual(len(started_routes), 1)
        self.assertEqual(started_routes[0], route)
        self.assertEqual(route.started, True)
    
    def test_PUT_only(self):
        response = self.client.get(reverse('RouteStarted', kwargs={'routeId': self.route.id}))
        self.assertEqual(response.status_code, 405)
        response = self.client.post(reverse('RouteStarted', kwargs={'routeId': self.route.id}))
        self.assertEqual(response.status_code, 405)
        response = self.client.patch(reverse('RouteStarted', kwargs={'routeId': self.route.id}))
        self.assertEqual(response.status_code, 405)
        response = self.client.delete(reverse('RouteStarted', kwargs={'routeId': self.route.id}))
        self.assertEqual(response.status_code, 405)
    
    def test_route_not_found(self):
        response = self.client.put(reverse('RouteStarted', kwargs={'routeId': self.route.id+99}))
        self.assertEqual(response.status_code, 404)
    
    def test_route_not_frozen_returns_bad_argument(self):
        response = self.client.put(reverse('RouteStarted', kwargs={'routeId': self.route.id}))
        self.assertEqual(response.status_code, 400)

@tag('route_finished')
class RouteFinished(TestCase, Setups):
    def setUp(self):
        self.single_route()
        self.second_community()
    
    def test_valid_case(self):
        self.route.freeze()
        self.route.start()
        self.route.save()
        response = self.client.put(reverse('RouteFinished', kwargs={'routeId': self.route.id}))
        self.assertEqual(response.status_code, 202)
        
        finished_routes = list(Route.objects.finished())
        self.assertEqual(len(finished_routes), 1)
        self.assertEqual(finished_routes[0], self.route)
    
    def test_unstarted_route_results_in_bad_argument(self):
        # we leave out
        # """response = self.client.put(reverse('RouteStarted', kwargs={'routeId': self.route.id}))"""
        # and thus make this route an invalid choice to finish
        response = self.client.put(reverse('RouteFinished', kwargs={'routeId': self.route.id}))
        self.assertEqual(response.status_code, 400)
        
        finished_routes = list(Route.objects.finished())
        self.assertEqual(len(finished_routes), 0)

    def test_PUT_only(self):
        response = self.client.get(reverse('RouteFinished', kwargs={'routeId': self.route.id}))
        self.assertEqual(response.status_code, 405)
        response = self.client.post(reverse('RouteFinished', kwargs={'routeId': self.route.id}))
        self.assertEqual(response.status_code, 405)
        response = self.client.patch(reverse('RouteFinished', kwargs={'routeId': self.route.id}))
        self.assertEqual(response.status_code, 405)
        response = self.client.delete(reverse('RouteFinished', kwargs={'routeId': self.route.id}))
        self.assertEqual(response.status_code, 405)
    
    def test_route_not_found(self):
        response = self.client.put(reverse('RouteFinished', kwargs={'routeId': self.route.id+99}))
        self.assertEqual(response.status_code, 404)

class StopEvents(TransactionTestCase, Setups):
    def setUp(self):
        self.single_route()
        self.init_rabbit()

    def test_update_stop_1_order_not_allowed_to_cancel(self):
        # set current route to finished
        Route.objects.update(id=self.route.id, status=Route.FINISHED)
        self.assertEqual(Route.objects.get(id=self.route.id).status,Route.FINISHED)
        self.assertEqual(Route.objects.count(),1)
        self.assertEqual(Order.objects.count(),1)
        self.assertEqual('test_station_0',Station.objects.get(uid=self.stations[0].uid).name) 

        OSRM_activated_in_Test = GetRequestManager().OSRM_activated
        GetRequestManager().OSRM_activated = False

        # first station is on the existing order - create event for editing this station
        #message = json.dumps({'Id': self.stations[0].id, 'CommunityId': self.bus.community, 'Latitude': 50.0, 'Longitude': 12.0})     

        Message = type("Message", (object,), dict())
        message = Message() 
         
        setattr(message, 'Id',self.stations[0].uid)
        setattr(message, 'CommunityId',self.bus.community)
        setattr(message, 'Name','NewName_abc')

        # enforce change of station!
        self.assertNotEqual(self.stations[0].mapId,self.stations[1].mapId)
        setattr(message, 'Latitude',self.stations[1].latitude) 
        setattr(message, 'Longitude',self.stations[1].longitude)

        # orders on finished routes must no be canceled!        
        rejectedIds = GetRequestManager().StopUpdatedCore(message)
        
        self.assertEqual(0, len(rejectedIds))      
        self.assertEqual('NewName_abc',Station.objects.get(uid=message.Id).name)   

        GetRequestManager().OSRM_activated = OSRM_activated_in_Test
    
    def test_update_stop_2_order_can_be_canceled(self):
        # set current route to booked
        Route.objects.update(id=self.route.id, status=Route.BOOKED)
        self.assertEqual(Route.objects.get(id=self.route.id).status,Route.BOOKED)
        self.assertEqual(Route.objects.count(),1)
        self.assertEqual(Order.objects.count(),1)
        self.assertEqual('test_station_0',Station.objects.get(uid=self.stations[0].uid).name)

        OSRM_activated_in_Test = GetRequestManager().OSRM_activated
        GetRequestManager().OSRM_activated = False

        # first station is on the existing order - create event for editing this station
        #message = json.dumps({'Id': self.stations[0].id, 'CommunityId': self.bus.community, 'Latitude': 50.0, 'Longitude': 12.0})     

        Message = type("Message", (object,), dict())
        message = Message()
        
        setattr(message, 'Id',self.stations[0].uid)
        setattr(message, 'CommunityId',self.bus.community)
        setattr(message, 'Name','NewName_abc')

        # enforce change of station!
        self.assertNotEqual(self.stations[0].mapId,self.stations[1].mapId)
        setattr(message, 'Latitude',self.stations[1].latitude)
        setattr(message, 'Longitude',self.stations[1].longitude)

        # if route is not finished we currently allow to cancel orders due to changed stop location
        rejectedIds = GetRequestManager().StopUpdatedCore(message)
        
        self.assertEqual(1, len(rejectedIds))
        self.assertEqual(self.order.uid, rejectedIds[0])
        self.assertEqual('NewName_abc',Station.objects.get(uid=message.Id).name)

        GetRequestManager().OSRM_activated = OSRM_activated_in_Test

class BusEvents(TransactionTestCase, Setups):
    def setUp(self):
        self.single_route()
        self.init_rabbit()

    def test_delete_bus(self):
        self.publisher.publish(json.dumps({'Id': self.bus.uid, 'CommunityId': self.bus.community, 'Name': self.bus.name}), 'BusDeletedIntegrationEvent')
        sleep(10)
        with self.assertRaises(ObjectDoesNotExist):
            Bus.objects.get(uid=self.bus.uid) # this sometimes failes, may be due to slow done event callback -> increase sleep
        with self.assertRaises(ObjectDoesNotExist):
            Route.objects.get(id=self.route.id)
        with self.assertRaises(ObjectDoesNotExist):
            Order.objects.get(uid=self.order.uid)

    @mock.patch('Routing_Api.mockups.stations.requests.get', side_effect=mocked_requests_get)
    def test_update_bus(self, mock_get):
        routeLoad = self.route.needed_capacity
        self.assertEqual(str(routeLoad), 'MobyLoad(2, 0)')        

        busCmp = Bus.objects.get(uid=self.bus.uid)
        self.assertEqual(busCmp.name, 'bus1')   
        self.assertEqual(busCmp.capacity, 5)   
        self.assertEqual(busCmp.capacity_wheelchair, 1)   
        self.assertEqual(busCmp.capacity_blocked_per_wheelchair, 2)           

        self.publisher.publish(json.dumps({'Id': self.bus.uid, 'CommunityId': self.bus.community, 'Name': self.bus.name}), 'BusUpdatedIntegrationEvent')
        sleep(2)

        busCmp = Bus.objects.get(uid=self.bus.uid)
        self.assertEqual(busCmp.name, 'bus1_update')   
        self.assertEqual(busCmp.capacity, 4)   
        self.assertEqual(busCmp.capacity_wheelchair, 2)   
        self.assertEqual(busCmp.capacity_blocked_per_wheelchair, 2)      

        # assume a second order exists above bus capa, since capa may be changed
        self.order2 = Order.objects.create(uid=self.order.uid+1, load=2, loadWheelchair=3, hopOnNode=self.nodes[0], hopOffNode=self.nodes[-1])
        routeLoad = self.route.needed_capacity
        self.assertEqual(str(routeLoad), 'MobyLoad(4, 3)')   

        self.publisher.publish(json.dumps({'Id': self.bus.uid, 'CommunityId': self.bus.community, 'Name': self.bus.name}), 'BusUpdatedIntegrationEvent')
        sleep(2)

        # order2 deleted due to low capa; first order, route and bus already existing
        busCmp = Bus.objects.get(uid=self.bus.uid)
        self.assertEqual(busCmp.name, 'bus1_update')   
        self.assertEqual(busCmp.capacity, 4)   
        self.assertEqual(busCmp.capacity_wheelchair, 2)   
        self.assertEqual(busCmp.capacity_blocked_per_wheelchair, 2)        
        
        routeCmp = Route.objects.get(id=self.route.id)
        self.assertEqual(str(routeCmp.needed_capacity), 'MobyLoad(2, 0)')  

        orderCmp = Order.objects.get(uid=self.order.uid)   
        self.assertIsNotNone(orderCmp)

        with self.assertRaises(ObjectDoesNotExist):
            Order.objects.get(uid=self.order2.uid)

        # now first order assumed to be too large
        Order.objects.update(uid=self.order.uid,load=10)

        self.publisher.publish(json.dumps({'Id': self.bus.uid, 'CommunityId': self.bus.community, 'Name': self.bus.name}), 'BusUpdatedIntegrationEvent')
        sleep(5)

        # now bus, route, order deleted
        with self.assertRaises(ObjectDoesNotExist):
            Bus.objects.get(uid=self.bus.uid) 
        with self.assertRaises(ObjectDoesNotExist):
            Route.objects.get(id=self.route.id)
        with self.assertRaises(ObjectDoesNotExist):
            Order.objects.get(uid=self.order.uid)

@tag('orders')
class OrderEvents(TransactionTestCase, Setups):
    def setUp(self):
        self.single_route()
        self.init_rabbit()
    def test_existing_order_canceled(self):
        self.assertEqual(5, Node.objects.count())

        self.publisher.publish(json.dumps({'Id': self.order.uid}), 'OrderCancelledIntegrationEvent')
        sleep(3)
        with self.assertRaises(ObjectDoesNotExist):
            Order.objects.get(uid=self.order.uid) # this sometimes failes, may be due to slow done event callback -> increase sleep

        # check if hopOn/hopOff nodes are cleanded
        self.assertEqual(3, Node.objects.count())

    def test_non_existing_order_canceled(self):
        self.assertEqual(5, Node.objects.count())

        self.publisher.publish(json.dumps({'Id': self.order.uid+9999999}), 'OrderCancelledIntegrationEvent')
        sleep(1)
        Order.objects.get(uid=self.order.uid)

        self.assertEqual(5, Node.objects.count())

@tag('task')
class Tasks(TestCase, Setups):
    def setUp(self):
        self.single_route()
        self.init_rabbit()
    
    def test_freeze(self):
        tasks.freeze_routes(0)

        sleep(7)

        route = Route.objects.all()[0]
        self.assertEqual(route.nodes.count(), 2)
        self.assertEqual(route.status, Route.FROZEN)
        
        order = Order.objects.all()[0]
        self.assertTrue(len(Order.objects.all()) > 0)
        self.assertEqual(order.hopOnNode.route, route)
        self.assertEqual(order.hopOffNode.route, route)        

    def test_split_routes_1(self):
        split_node = self.nodes[1]
        last_node = self.nodes[-1]
        self.order.hopOffNode = split_node
        self.order.save()
        order_id1 = self.order.pk
        self.order.pk = None
        self.order.uid = self.order.uid + 1
        self.order.hopOnNode = split_node
        self.order.hopOffNode = last_node
        self.order.save()
        order_id2 = self.order.pk

        self.assertEqual(1, Route.objects.count())

        o1 = Order.objects.get(pk=order_id1)
        o2 = Order.objects.get(pk=order_id2)
        self.assertTrue(o1.hopOnNode.route == o2.hopOnNode.route)

        tasks.split_routes(delta_time_min_for_split=5) # splitting works for large time distances between nodes
        o1 = Order.objects.get(pk=order_id1)
        o2 = Order.objects.get(pk=order_id2)

        self.assertEqual(o1.hopOnNode.route, o1.hopOffNode.route)
        self.assertEqual(o2.hopOnNode.route, o2.hopOffNode.route)
        self.assertTrue(o1.hopOnNode.route != o2.hopOnNode.route)
        self.assertEqual(2, Route.objects.count())

        self.assertTrue(tasks.check_routing_data())

    def test_split_routes_2(self):

        self.assertEqual(5, len(self.nodes))
        self.assertEqual(5, Node.objects.count())

        split_node = self.nodes[1]
        last_node = self.nodes[-1]
        self.order.hopOffNode = split_node
        self.order.save()
        order_id1 = self.order.pk
        self.order.pk = None
        self.order.uid = self.order.uid + 1
        self.order.hopOnNode = split_node
        self.order.hopOffNode = last_node
        self.order.save()
        order_id2 = self.order.pk
        self.order.pk = None
        self.order.uid = self.order.uid + 1
        self.order.hopOnNode = self.nodes[2]
        self.order.hopOffNode = self.nodes[3]
        self.order.save()
        order_id3 = self.order.pk

        self.assertEqual(1, Route.objects.count())
        self.assertEqual(5, len(self.nodes))
        self.assertEqual(5, Node.objects.count())

        o1 = Order.objects.get(pk=order_id1)
        o2 = Order.objects.get(pk=order_id2)
        o3 = Order.objects.get(pk=order_id3)
        self.assertTrue(o1.hopOnNode.route == o2.hopOnNode.route)
        self.assertTrue(o1.hopOnNode.route == o3.hopOnNode.route)

        tasks.split_routes(delta_time_min_for_split=5) # splitting works for large time distances between nodes
        o1 = Order.objects.get(pk=order_id1)
        o2 = Order.objects.get(pk=order_id2)
        o3 = Order.objects.get(pk=order_id3)

        self.assertEqual(5, len(self.nodes))
        self.assertEqual(6, Node.objects.count())
        self.assertEqual(o1.hopOnNode.route, o1.hopOffNode.route)
        self.assertEqual(o2.hopOnNode.route, o2.hopOffNode.route)
        self.assertEqual(o3.hopOnNode.route, o3.hopOffNode.route)
        self.assertEqual(o2.hopOnNode.route, o3.hopOnNode.route)
        self.assertTrue(o1.hopOnNode.route != o2.hopOnNode.route)
        self.assertEqual(2, Route.objects.count())

        self.assertTrue(tasks.check_routing_data())
    
    def test_split_routes_3_no_splitting(self):
        self.assertEqual(5, len(self.nodes))
        self.assertEqual(5, Node.objects.count())

        split_node = self.nodes[1]
        last_node = self.nodes[-1]
        self.order.hopOffNode = split_node
        self.order.save()
        order_id1 = self.order.pk
        self.order.pk = None
        self.order.uid = self.order.uid + 1
        self.order.hopOnNode = split_node
        self.order.hopOffNode = last_node
        self.order.save()
        order_id2 = self.order.pk
        self.order.pk = None
        self.order.uid = self.order.uid + 1
        self.order.hopOnNode = self.nodes[2]
        self.order.hopOffNode = self.nodes[3]
        self.order.save()
        order_id3 = self.order.pk

        self.assertEqual(1, Route.objects.count())
        self.assertEqual(5, len(self.nodes))
        self.assertEqual(5, Node.objects.count())

        o1 = Order.objects.get(pk=order_id1)
        o2 = Order.objects.get(pk=order_id2)
        o3 = Order.objects.get(pk=order_id3)
        self.assertTrue(o1.hopOnNode.route == o2.hopOnNode.route)
        self.assertTrue(o1.hopOnNode.route == o3.hopOnNode.route)

        tasks.split_routes(delta_time_min_for_split=30) # splitting works not for low time distances between nodes
        o1 = Order.objects.get(pk=order_id1)
        o2 = Order.objects.get(pk=order_id2)
        o3 = Order.objects.get(pk=order_id3)

        self.assertEqual(5, len(self.nodes))
        self.assertEqual(5, Node.objects.count())
        self.assertEqual(o1.hopOnNode.route, o1.hopOffNode.route)
        self.assertEqual(o2.hopOnNode.route, o2.hopOffNode.route)
        self.assertEqual(o3.hopOnNode.route, o3.hopOffNode.route)
        self.assertEqual(o2.hopOnNode.route, o3.hopOnNode.route)
        self.assertEqual(o1.hopOnNode.route, o2.hopOnNode.route)
        self.assertEqual(1, Route.objects.count())

        self.assertTrue(tasks.check_routing_data())

    def test_check_routing_data(self):
        # setup data must be ok
        self.assertEqual(1, Route.objects.count())
        self.assertEqual(1, Order.objects.count())
        self.assertEqual(5, Node.objects.count())
        self.assertTrue(tasks.check_routing_data())

        # add second order that is not ok, due to mixed routes
        route2 = Route.objects.create(bus=self.bus, community=self.community, status=Route.BOOKED)
        nodeRoute2 = Node.objects.create(mapId=str(Node.objects.count()+1), route=route2, tMin=self.t, tMax=self.t + relativedelta(minutes=10))
        self.nodes.append(nodeRoute2)
        order2 = Order.objects.create(uid=self.order.uid+1, load=2, hopOnNode=self.nodes[0], hopOffNode=self.nodes[-1])
        order2.save()

        self.assertFalse(self.route.id==route2.id)
        self.assertEqual(order2.hopOnNode.route.id,self.route.id)
        self.assertEqual(order2.hopOffNode.route.id,route2.id)

        self.assertEqual(2, Route.objects.count())
        self.assertEqual(2, Order.objects.count())
        self.assertEqual(6, Node.objects.count())

        # test must be aware that data is not ok
        self.assertFalse(tasks.check_routing_data())

    def test_delete_routes_1(self):
        # do not delete immediately all delete candidates
        delete_candidates = Route.objects.to_be_deleted()
        self.assertEqual(0, delete_candidates.count())

        # add 102 delete candidates (frozen routes)
        cand_remaining = 100
        cand_deleted = 2
        iNumRoutesRemaining=0
        listRouteIds = [] 
        listRouteIds2 = []         

        while iNumRoutesRemaining < cand_remaining+cand_deleted:
            self.route = Route.objects.create(bus=self.bus, community=self.community, status=Route.FINISHED)
            iNumRoutesRemaining+=1
            listRouteIds.append(self.route.id)

        self.assertEqual(cand_remaining+cand_deleted+1, Route.objects.count())
        delete_candidates = Route.objects.to_be_deleted()
        self.assertEqual(cand_remaining+cand_deleted, delete_candidates.count())

        #print(delete_candidates)

        # delete routes must remain 100 delete candidates (frozen routes)
        tasks.delete_routes()
        delete_candidates = Route.objects.to_be_deleted()
        self.assertEqual(cand_remaining, delete_candidates.count())

        for route in delete_candidates:
            listRouteIds2.append(route.id)

        # the oldest routes must be deleted, i.e. here: first ids deleted, since no date info at nodes
        for index in (0, cand_remaining-1):
            self.assertEqual(listRouteIds[index+cand_deleted], listRouteIds2[index])

        # print(listRouteIds)
        # print(listRouteIds2)        

        #print(delete_candidates)

    def test_delete_routes_2_routes_unordered(self):
        # enforce that oldest routes are deleted, oldest must be identified by datetime on nodes, id or standard order in database is not sufficient
        delete_candidates = Route.objects.to_be_deleted()
        self.assertEqual(0, delete_candidates.count())

        # add 102 delete candidates (frozen routes)
        cand_remaining = 100
        cand_deleted = 2
        iNumRoutesRemaining=0
        listRouteIds = [] 
        listRouteIds2 = []         

        while iNumRoutesRemaining < cand_remaining+cand_deleted:
            self.route = Route.objects.create(bus=self.bus, community=self.community, status=Route.FINISHED)

            # create nodes with decreasing time (i.e. "incorrect" order) - delete must recognize the oldest routes even if order is not a priori given!
            nodeRoute = Node.objects.create(mapId=str(Node.objects.count()+1), route=self.route, tMin=self.t - relativedelta(minutes=iNumRoutesRemaining+10), tMax=self.t - relativedelta(minutes=iNumRoutesRemaining))
            self.nodes.append(nodeRoute)
            iNumRoutesRemaining+=1
            listRouteIds.append(self.route.id)

        self.assertEqual(cand_remaining+cand_deleted+1, Route.objects.count())
        delete_candidates = Route.objects.to_be_deleted()
        self.assertEqual(cand_remaining+cand_deleted, delete_candidates.count())

        #print(delete_candidates)

        # delete routes must remain 100 oldest(!) delete candidates (frozen routes)
        tasks.delete_routes()
        delete_candidates = Route.objects.to_be_deleted()
        self.assertEqual(cand_remaining, delete_candidates.count())

        for route in delete_candidates:
            listRouteIds2.append(route.id)

        # print(listRouteIds)
        # print(listRouteIds2)  

        # the oldest routes must be deleted, i.e. here: last ids deleted since datetime info was added in reverse order - "oldest" were the last
        for index in (0, cand_remaining-1):
            self.assertEqual(listRouteIds[index], listRouteIds2[index])              

        #print(delete_candidates)




        

