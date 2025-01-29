from datetime import datetime, timedelta
from routing.routingClasses import Vehicle, VehicleCapacity, datetime2isostring
from dateutil.relativedelta import relativedelta
from dateutil.tz import tzutc
import requests
import json
import logging
from dateutil.parser import parse
from typing import List

LOGGER = logging.getLogger(__name__)
UTC = tzutc()


class Availability():
    def __init__(self, bus_id, timeslots, timeslots_blocker):
        self.bus_id = bus_id
        self.timeslots = timeslots
        self.timeslots_blocker = timeslots_blocker

    def __str__(self):
        return f'<Availability(bus_id={self.bus_id},timeslots={self.timeslots},timeslots_blocker={self.timeslots_blocker})>'


class Busses():
    """ Bus service that is connected to a django db-model """

    def __init__(self, busUrl, busAvailUrl, BusDb, RouteDb, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._busUrl = busUrl
        self._busAvailUrl = busAvailUrl
        self._busses = BusDb
        self._routes = RouteDb
        self._look_around = kwargs.get('look_around', 1)
        self.__fetch_initial_data()

    def __fetch_initial_data(self):
        pass

    def update(self, bus_id, **kwargs):
        bus = self._busses.objects.get(uid=bus_id)
        for attribute, value in kwargs.items():
            setattr(bus, attribute, value)
        bus.save()

    def _get_buses_in_community(self, community, start_time=None, stop_time=None):
        return self._busses.objects.filter(community=community)

    def _get_availabilities_in_community(self, community, start_time, stop_time):
        # print(f"DEBUGGING start_time (Eingabeparameter) in _get_availabilities_in_community: {start_time}")
        # print(f"DEBUGGING stop_time (Eingabeparameter) in _get_availabilities_in_community: {stop_time}")
        start_time_str = datetime2isostring(start_time)
        stop_time_str = datetime2isostring(stop_time)
        # print(f"DEBUGGING start_time_str in _get_availabilities_in_community: {start_time_str}")
        # print(f"DEBUGGING stop_time_str in _get_availabilities_in_community: {stop_time_str}")
        url = self._busAvailUrl + '/' + str(community) + '/' + start_time_str + '/' + stop_time_str
        # print(f"DEBUGGING url in _get_availabilities_in_community: {url}")
        LOGGER.info('requesting bus availabilities at %s', url)

        response = requests.get(url, verify=False)
        # print(f"DEBUGGING response in _get_availabilities_in_community: {response}")
        if response.status_code != 200:
            raise ValueError(f'Could not get resources from {url}, got {response.status_code}:{response.text}')

        available_buses = json.loads(response.text)
        # print(f"DEBUGGING available_buses in _get_availabilities_in_community: {available_buses}")
        availabilities = []

        try:
            for availability_information in available_buses:
                busID_requested = -1
                busID_requested = availability_information['busId']
                try:
                    bus = self._busses.objects.get(uid=busID_requested)
                except Exception:
                    bus = self._busses(uid=busID_requested)
                bus.name = availability_information['name']
                bus.community = availability_information['communityId']
                bus.capacity = availability_information['seats']
                bus.capacity_wheelchair = availability_information['seatsWheelchair']
                bus.capacity_blocked_per_wheelchair = availability_information['seatsBlockedPerWheelchair']
                bus.vehicleType = availability_information['vehicleType'] if 'vehicleType' in availability_information else 'bus'

                bus.save()

                timeslots = [((parse(slot['startDate']), 'Depot'), (parse(slot['endDate']), 'Depot')) for slot in
                             availability_information['availabilitySlots']]
                timeslots_blocker = [((parse(slot['startDate']), 'Depot'), (parse(slot['endDate']), 'Depot')) for slot
                                     in availability_information['blockingSlots']]  # blocker slots
                availability = Availability(bus_id=busID_requested, timeslots=timeslots,
                                            timeslots_blocker=timeslots_blocker)
                # print(f"availability in _get_availabilities_in_community: {availability.bus_id}")
                availabilities.append(availability)
                # print(f"availabilities in _get_availabilities_in_community: {availabilities}")

        except Exception as err:
            raise ValueError(f'Could not read json data properly:{available_buses}, error message: {err}')

        return availabilities

    def _get_bus(self, bus_id):
        return self._busses.objects.get(uid=bus_id)

    def refresh_bus(self, bus_id):
        """
        Retrieves information about a bus from the Directus API, parses the JSON response, and updates a Bus object
        in the database with the retrieved information. If the bus does not exist in the database, 
        it creates a new Bus object with the specified ID and fields. Returns the updated Bus object.
        """
        url = self._busUrl + '/' + str(bus_id)
        response = requests.get(url, verify=False)
        if response.status_code != 200:
            raise ValueError(f'Could not get information for bus id {bus_id}, got ' +
                             '{response.status_code}: {response.text}')
        bus_information = json.loads(response.text)

        # bus info attribute names to lower
        bus_information = {k.lower(): v for k, v in bus_information.items()}

        print(bus_information)

        try:
            bus = self._busses.objects.get(uid=bus_id)
        except:
            bus = self._busses(uid=bus_id, name=bus_information['name'])

        # call the attributes from response, names must be LOWER!
        bus.name = bus_information['name']
        bus.community = bus_information['community_id']
        bus.capacity = bus_information['seats']
        bus.capacity_wheelchair = bus_information['seats_wheelchair']
        bus.capacity_blocked_per_wheelchair = bus_information['seatsblockedbywheelchair']
        bus.vehicleType = bus_information['vehicletype']

        bus.save()
        return bus

    def _get_frozen_routes_for_busses(self, bus_ids, start_time, stop_time):

        # print("results _get_frozen_routes_for_busses")
        # print(start_time)
        # print(stop_time)

        result = self._routes.objects.prefetch_related('nodes', 'bus').filter(
            bus__uid__in=bus_ids,
            status__in=[self._routes.FROZEN, self._routes.STARTED, self._routes.FINISHED],
            nodes__tMin__lte=stop_time,
            nodes__tMax__gte=start_time).all()

        # print(result)        

        return result

    @staticmethod
    def __routes_to_constraints(routes, buffertime_minutes):
        # create a list for each bus with first and last (location, time) information
        constraints = {route.busId: [] for route in routes}
        for route in routes:
            busId = route.busId
            start_node = route.nodes.first()
            stop_node = route.nodes.last()
            # print("__routes_to_constraints start_node stop_node")   
            # print(start_node)   
            # print(stop_node)   
            constraints[busId].append(((start_node.tMin - timedelta(minutes=buffertime_minutes), start_node.mapId),
                                       (stop_node.tMax + timedelta(minutes=buffertime_minutes), stop_node.mapId)))
        return constraints

    @staticmethod
    def __reduce_timeslot(timeslot, constraints):
        """ Reduce a given timeslot by route time windows.
        :timeslot: {start: datetime, end:datetime, start_location:mapid, end_location:mapid}
        :constraints: [((start, start_location), (end, endlocation)), ...]

        Return list of timeslots like timeslot
        """

        # the bus is currently useable during this slot, if we ignore frozen routes
        # we only have on work slot in the beginning
        slots = [timeslot]

        # make a sorted copy, because we don't want to destroy the data source
        constraints = sorted(constraints)

        for constraint in constraints:
            # deconstruct constraint
            ((constraint_start, constraint_start_location),
             (constraint_end, constraint_end_location)) = constraint
            # the currently relevant slot is always the last
            ((slot_start, slot_start_location),
             (slot_end, slot_end_location)) = slots[-1]

            # skip obvious, non-overlapping situations:
            if constraint_start > slot_end or constraint_end < slot_start:
                pass

            # fully enveloped constraint -> we need to split our slot into two
            elif constraint_start > slot_start and constraint_end < slot_end:
                # first half:
                slots[-1] = ((slot_start, slot_start_location),
                             (constraint_start, constraint_start_location))
                # second half:
                slots.append(((constraint_end, constraint_end_location),
                              (slot_end, slot_end_location)))

            # left are only cases where an edge overlaps, like [...( .. ] ...)
            # constraint overlaps with first part of slot
            elif constraint_start <= slot_start:
                # so simply move the start of the slot up in time
                slots[-1] = ((constraint_end, constraint_end_location),
                             (slot_end, slot_end_location))

            # constraint overlaps with later part of slot
            elif constraint_end >= slot_end:
                # so simply move the end of the slot back in time
                slots[-1] = ((slot_start, slot_start_location),
                             (constraint_start, constraint_start_location))

            # if all cases are covered, this should not happen
            else:
                LOGGER.error(f"couldn't find matching case for slot {slots[-1]} and constraint: {constraint}",
                             exc_info=True)

        def nonempty_slot(slot):
            """ Compare start and end time of slot and return only true if there's space in-between. """
            ((start, _), (end, __)) = slot
            return start < end

        # return only slots that have time left to manoeuver
        return list(filter(nonempty_slot, slots))

    def get_available_buses(self, community, start_times: List[datetime] = None, stop_times: List[datetime] = None):
        # print("get_available_buses")
        # print(f"DEBUGGING start_times in get_available_buses: {start_times}")
        # print(f"DEBUGGING stop_times in get_available_buses: {stop_times}")

        # define time constraint of problem domain -> only consider information within [lower, upper]
        time_min = None
        time_max = None
        times_all = None

        if start_times and len(start_times) > 0:
            times_all = start_times
        else:
            times_all = stop_times

        time_min = times_all[0]
        time_max = times_all[-1]

        for time in times_all:
            if time < time_min:
                time_min = time
            if time > time_max:
                time_max = time

        time_domain = relativedelta(hours=self._look_around)
        lower_time_range = time_min - time_domain
        upper_time_range = time_max + time_domain
        # print(f"DEBUGGING time_domain in get_available_buses: {time_domain}")
        # print(f"DEBUGGING lower_time_range in get_available_buses: {lower_time_range}")
        # print(f"DEBUGGING upper_time_range in get_available_buses: {upper_time_range}")

        availabilities = list(self._get_availabilities_in_community(
            community=community,
            start_time=lower_time_range,
            stop_time=upper_time_range))
        # print(f"DEBUGGING availabilities in get_available_buses: {availabilities}")

        # remove reserved times of frozen routes from time slot
        routes = list(self._get_frozen_routes_for_busses(
            bus_ids=[availability.bus_id for availability in availabilities],
            start_time=lower_time_range,
            stop_time=upper_time_range))

        # create a list for each bus with first and last (location, time) information
        # buffer is used that there is little time remaining between frozen routes an new ones
        constraints = self.__routes_to_constraints(routes, buffertime_minutes=15)

        result = []
        time_in_blocker = []

        for time in times_all:

            resources_of_time = []
            current_time_in_blocker = False
            time_slots_empty = True

            for availability in availabilities:
                bus_id = availability.bus_id
                bus = self._get_bus(bus_id=bus_id)
                # print(f"DEBUGGING bus (result from self._get_bus(): {bus})")

                unmodified_timeslots = availability.timeslots
                timeslots = []

                for timeslot in unmodified_timeslots:
                    ((start, start_location), (end, end_location)) = timeslot

                    # do not add raw timeslots that are not containing the requested time
                    # would be unnecessary data and may lead to misinterpreted error messages
                    # TODO note: if in the following frozen routes modify the timeslots we might accept empty slots, since then the error messsage "bus full" is ok - maybe error-message-strategy
                    # needs to be improved

                    # print("raw timeslots")
                    # print(time)
                    # print(timeslot)
                    # print(start)
                    # print(end)

                    if time >= start and time <= end:
                        timeslots.extend(self.__reduce_timeslot(timeslot, constraints.get(bus_id, [])))
                    else:
                        print("time not in timeslot")
                        pass

                time_slots_empty = (time_slots_empty and (len(timeslots) == 0))
                # print(time_slots_empty)
                # print(len(timeslots))

                for timeslot in timeslots:
                    # print("remaining timeslots")
                    # print(timeslot)
                    ((start, start_location), (end, end_location)) = timeslot

                    vehicle = Vehicle(
                        start_location=start_location,
                        stop_location=end_location,
                        work_time=(start, end),
                        vehicleType = bus.vehicleType,
                        capacity=VehicleCapacity(bus.capacity, bus.capacity_wheelchair,
                                                 bus.capacity_blocked_per_wheelchair))

                    # print(f"DEBUGGING vehicle in db_busses.py: {vehicle})")

                    # make sure we use the correct ids for later use in our assignments
                    vehicle.id = bus_id
                    # and add this instance to our list of useable buses

                    resources_of_time.append(vehicle)

                # check if time is in blocker
                for timeslotBlocker in availability.timeslots_blocker:
                    # print("blocker timeslots")
                    # print(timeslotBlocker)
                    # print(time)
                    ((start, start_location), (end, end_location)) = timeslotBlocker

                    if time >= start and time <= end:
                        current_time_in_blocker = True

            result.append(resources_of_time)
            time_in_blocker.append(
                time_slots_empty and current_time_in_blocker)  # time in blocker only if no slots were found
        # print(f"DEBUGGING result in db_busses.py: {result}")
        return (result, time_in_blocker)



