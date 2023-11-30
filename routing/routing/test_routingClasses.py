from .routingClasses import Group, Station, Moby, MobyLoad, Vehicle, VehicleCapacity, Node, MapNode, TimeWindow, LocationIndex, BusIndex, Passenger, StationConstraint, datetime2isostring
from unittest import TestCase
from dateutil.parser import parse

class TestMoby(TestCase):
    def setUp(self):
        pass

    def test_constructor(self):
        # load arg must be appropriate type
        errMess = ''

        try:
           Moby('abc', 'def', None, (30, 45), load=2)        
        except TypeError as err:
            errMess = err

        self.assertEqual(str(errMess), str(TypeError('Moby needs a load object of type MobyLoad as input')))

    def test_datetime2isostring(self):
        timeStart = parse('2090-03-02T07:50.000+00:00')
        self.assertEqual('2090-03-02T07:50:00+00:00',datetime2isostring(timeStart))

        timeStart = parse('2090-03-02T07:50.000+01:00')
        self.assertEqual('2090-03-02T06:50:00+00:00',datetime2isostring(timeStart))

class TestMobyLoad(TestCase):
    def setUp(self):
        pass

    def test_toString(self):
        load = MobyLoad(4,2)
        self.assertEqual(str(load), 'MobyLoad(4, 2)')

    def test_equals(self):
        load1 = MobyLoad(4,2)
        load2 = MobyLoad(4,2)
        load3 = MobyLoad(1,1)
        self.assertTrue(load1.equals(load2))
        self.assertFalse(load1.equals(load3))

    def test_isEmpty(self):
        load1 = MobyLoad(0,0)
        load2 = MobyLoad(4,2)
        self.assertTrue(load1.isEmpty())
        self.assertFalse(load2.isEmpty())

    def test_arithmetic_operations(self):
        load1 = MobyLoad(4,2)
        load2 = MobyLoad(3,2)
        load3 = MobyLoad(1,1)

        loadRes = load1+load2
        self.assertEqual(loadRes.standardSeats,7)
        self.assertEqual(loadRes.wheelchairs,4)

        loadRes = load1-load3
        self.assertEqual(loadRes.standardSeats,3)
        self.assertEqual(loadRes.wheelchairs,1)        

