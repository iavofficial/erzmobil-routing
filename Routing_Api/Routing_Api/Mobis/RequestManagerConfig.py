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
from django.conf import settings


class RequestManagerConfig:

   # modes for altetnatives search
    ALTERNATIVE_SEARCH_NONE = 'alternatives_none'
    ALTERNATIVE_SEARCH_EARLIER = 'alternatives_earlier'
    ALTERNATIVE_SEARCH_LATER = 'alternatives_later'

    def __init__(self):
        self.timeOffset_MaxDaysOrderInFuture = 28
        self.timeOffset_MinMinutesToOrderFromNow = (int)(settings.ROUTING_TIMEOFFSET_MINMINUTESTOORDERFROMNOW) # no orders possible closer to now in general
        self.timeOffset_MinMinutesToOrderFromNowIntoStartedRoutes = 30 # no orders possible closer to now if started routes exist
        self.timeOffset_MinMinutesToOrderFromNowOffsetForDepartureBooked = 15 # additional offset for departure booked since we do not now the driving time for order a priori
        self.timeOffset_FactorForDrivingTimes = 1.25
        self.timeOffset_LookAroundHoursPromises = 1
        self.timeOffset_LookAroundHoursBusAvailabilites = 10 # do not use same look_around for promises und availabilities, otherwise for long routes we we might not get solutions

        self.timeService_per_wheelchair = 3
