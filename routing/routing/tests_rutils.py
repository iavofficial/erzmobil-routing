import os
from unittest import TestCase
from dateutil.parser import parse
from .rutils import GpsUtmConverter, multi2single, shortest_path_graph_nodes, convertNodeNamesToString
from .maps import Maps
from .routingClasses import Station

class GpsUtmConverterTest(TestCase):
    def setUp(self):
        self.converter = GpsUtmConverter('32')

    def test_normalize_date(self):        
        refDate = None
        date =parse('2090-03-01T16:00.000+00:00')
        (minutes, refDate2) =GpsUtmConverter.normalize_date(date, refDate)
        self.assertEqual(1440+60*16, minutes)
        self.assertEqual(parse('2090-02-28T00:00.000+00:00'), refDate2)

        # local times must be converted to utc
        refDate = None
        date =parse('2090-03-01T16:00.000+01:00')
        (minutes, refDate2) =GpsUtmConverter.normalize_date(date, refDate)
        self.assertEqual(1440+60*15, minutes)
        self.assertEqual(parse('2090-02-28T00:00.000+00:00'), refDate2)

        # local times must be converted to utc
        refDate = parse('2090-02-27T15:00.000+01:00')
        date =parse('2090-03-01T16:00.000+01:00')
        (minutes, refDate2) =GpsUtmConverter.normalize_date(date, refDate)
        self.assertEqual(1440+60*15+10*60, minutes)
        self.assertEqual(parse('2090-02-27T14:00.000+00:00'), refDate2)

        # local times must be converted to utc
        refDate = parse('2090-02-27T15:00.000+01:00')
        date =parse('2090-03-01T16:00.000+00:00')
        (minutes, refDate2) =GpsUtmConverter.normalize_date(date, refDate)
        self.assertEqual(1440+60*16+10*60, minutes)
        self.assertEqual(parse('2090-02-27T14:00.000+00:00'), refDate2)

        # another datetime notation
        refDate = None
        date =parse('2090-03-01T16:00:00.000Z')
        (minutes, refDate2) =GpsUtmConverter.normalize_date(date, refDate)
        self.assertEqual(1440+60*16, minutes)
        self.assertEqual(parse('2090-02-28T00:00.000+00:00'), refDate2)

    def test_denormalize_date(self):
        refDate = parse('2090-02-28T00:00.000+00:00')
        (date, refDate2) =GpsUtmConverter.denormalize_date(1440+60*15, refDate)
        self.assertEqual(parse('2090-03-01T15:00.000+00:00'), date)
        self.assertEqual(parse('2090-02-28T00:00.000+00:00'), refDate2)

        # local times must be converted to utc
        refDate = parse('2090-02-28T00:00.000+01:00')
        (date, refDate2) =GpsUtmConverter.denormalize_date(1440+60*15, refDate)
        self.assertEqual(parse('2090-03-01T14:00.000+00:00'), date)
        self.assertEqual(parse('2090-02-27T23:00.000+00:00'), refDate2)

    def test_normalize_date_get_ref_date_default(self):
        date =parse('2090-03-01T16:00.000+00:00')
        refDate =GpsUtmConverter.normalize_date_get_ref_date_default(date)
        self.assertEqual(parse('2090-02-28T00:00.000+00:00'), refDate)

        # local times must be converted to utc
        date =parse('2090-03-01T16:00.000+01:00')
        refDate =GpsUtmConverter.normalize_date_get_ref_date_default(date)
        self.assertEqual(parse('2090-02-28T00:00.000+00:00'), refDate)


    def test_gps_utm_convert_single(self):

        res = self.converter.gps2utm(40,10)
        self.assertEqual(res[0], 585360.461842771)
        self.assertEqual(res[1], 4428236.064633089)

        # converting back must end in almost the initial values - slightly rounding differences allowed
        res = self.converter.utm2gps(res[0],res[1])
        self.assertAlmostEqual(res[0], 40, 10)
        self.assertAlmostEqual(res[1], 10, 10)

        # centre of Chemnitz: 
        # WGS84 decimal Lat: 50.831907 N, Lon: 12.919099 E
        # WGS84 UTM: Z 33U,  353463.538 E, 5633196.053 N

        self.converter = GpsUtmConverter('33')
        res = self.converter.gps2utm(50.831907,12.919099)
        self.assertEqual(res[0], 353463.53763775656)
        self.assertEqual(res[1], 5633196.053399602)

        res = self.converter.utm2gps(res[0],res[1])
        self.assertAlmostEqual(res[0], 50.831907, 10)
        self.assertAlmostEqual(res[1], 12.919099, 10)

        # centre of Zwoenitz
        # 50.630320388, 12.813627926

        self.converter = GpsUtmConverter('33')
        res = self.converter.gps2utm(50.630320388,12.813627926)
        self.assertAlmostEqual(res[0], 345374.54975640454, 8)
        self.assertAlmostEqual(res[1], 5610997.643908017, 8)

        res = self.converter.utm2gps(res[0],res[1])
        self.assertAlmostEqual(res[0], 50.630320388, 10)
        self.assertAlmostEqual(res[1], 12.813627926, 10)

    def test_gps_utm_convert_list(self):

        # centre of Chemnitz: 
        # WGS84 decimal Lat: 50.831907 N, Lon: 12.919099 E
        # WGS84 UTM: Z 33U,  353463.538 E, 5633196.053 N

        # centre of Zwoenitz
        # 50.630320388, 12.813627926

        listCoords = [(50.831907,12.919099), (50.630320388,12.813627926)]        

        self.converter = GpsUtmConverter('33')
        res = self.converter.gps2utm_list(listCoords)
        self.assertEqual(res[0][0], 353463.53763775656)
        self.assertEqual(res[0][1], 5633196.053399602)
        self.assertAlmostEqual(res[1][0], 345374.54975640454, 8)
        self.assertAlmostEqual(res[1][1], 5610997.643908017, 8)

        # converting back and compare with initial values
        res = self.converter.utm2gps_list(res)
        self.assertAlmostEqual(res[0][0], 50.831907, 10)
        self.assertAlmostEqual(res[0][1], 12.919099, 10)
        self.assertAlmostEqual(res[1][0], 50.630320388, 10)
        self.assertAlmostEqual(res[1][1], 12.813627926, 10)

    
    def test_shortest_path_graph_nodes_stwendel(self):
        community = str('StWendel')
        pickle_name = '../maps/' + community + str('.p')

        self.assertTrue(os.path.exists(pickle_name))

        maps = Maps("")
        G_pickle = maps.load_graph_pickle(pickle_name)
        nodes_pickle = set(G_pickle.nodes())
        self.assertTrue('446284668' in nodes_pickle)
        self.assertTrue('430888873' in nodes_pickle)

        graph = multi2single(G_pickle)

        start = Station(node_id='446284668', name='Station1')
        stop = Station(node_id='430888873', name='Station2')        

        result = shortest_path_graph_nodes(graph, start, stop)

        self.assertEqual('446284668', result[0])
        self.assertEqual('430888873', result[-1])
        self.assertEqual(270, len(result))
        #print(result)