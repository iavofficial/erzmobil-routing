from django.conf import settings


class RequestManagerConfig:

   # modes for altetnatives search
    ALTERNATIVE_SEARCH_NONE = 'alternatives_none'
    ALTERNATIVE_SEARCH_EARLIER = 'alternatives_earlier'
    ALTERNATIVE_SEARCH_LATER = 'alternatives_later'

    def __init__(self):
        self.timeOffset_MaxDaysOrderInFuture = 28
        self.timeOffset_MinMinutesToOrderFromNow = (int)(settings.ROUTING_TIMEOFFSET_MINMINUTESTOORDERFROMNOW)
        self.timeOffset_FactorForDrivingTimes = 1.25
        self.timeOffset_LookAroundHoursPromises = 1
        self.timeOffset_LookAroundHoursBusAvailabilites = 10 # do not use same look_around for promises und availabilities, otherwise for long routes we we might not get solutions
        self.timeOffset_MaxMinutesFromNowToReduceAvailabilitesByStartedRoutes = 30

        self.timeService_per_wheelchair = 3
