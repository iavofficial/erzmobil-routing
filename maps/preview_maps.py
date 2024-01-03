from .routing.routing.OSM_map_utils import OSM_map_utils

if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description='Save a networkx graph as graphic')
    parser.add_argument('infile')
    parser.add_argument('picfile')

    args = parser.parse_args()
    OSM_map_utils.plotGraph(infile=args.infile, picfile=args.picfile)