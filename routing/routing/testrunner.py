import cProfile
import unittest
import pstats
import sys
 
if __name__ == '__main__':    
    argv =  sys.argv[1:]

    if 'profile' in argv:
        doProfile = True
    else:
        doProfile = False

    # find all tests
    loader = unittest.TestLoader()
    loader.testMethodPrefix = "test_new_routing_long_calc_time" # run named tests with specified prefix
    suite = loader.discover('.')    

    def runtests():        
        unittest.TextTestRunner(verbosity=2).run(suite)

    if doProfile==True:
        fileStats = 'test_profile_stats_dump.txt'
        cProfile.run('runtests()',sort='tottime', filename=fileStats)    

        with open('test_profile_stats_cumtime.txt', 'w') as stream:
            stats = pstats.Stats(fileStats, stream=stream)
            stats.sort_stats('cumtime')        
            stats.print_stats()        

        with open('test_profile_stats_tottime.txt', 'w') as stream:
            stats = pstats.Stats(fileStats, stream=stream)
            stats.sort_stats('tottime')        
            stats.print_stats()        
    else:
        runtests()

   
   