#!/usr/bin/env python
"""
Command-line utility for administrative tasks.
"""

import os
import sys
import cProfile
import pstats

if __name__ == "__main__":
    os.environ.setdefault(
        "DJANGO_SETTINGS_MODULE",
        "Routing_Api.settings"
    )

    from django.core.management import execute_from_command_line
    
    doProfile = False

    if doProfile == False:
        execute_from_command_line(sys.argv)
    else:
        # profile 
        fileStats = 'test_profile_stats_dump.txt'
        cProfile.run('execute_from_command_line(sys.argv)',sort='tottime', filename=fileStats)    

        with open('test_profile_stats_cumtime.txt', 'w') as stream:
            stats = pstats.Stats(fileStats, stream=stream)
            stats.sort_stats('cumtime')        
            stats.print_stats()        

        with open('test_profile_stats_tottime.txt', 'w') as stream:
            stats = pstats.Stats(fileStats, stream=stream)
            stats.sort_stats('tottime')        
            stats.print_stats()    
