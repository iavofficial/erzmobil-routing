from .routing.routing.OSM_map_utils import OSM_map_utils
import argparse

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='Get an OSM graph.')
    parser.add_argument('City')
    parser.add_argument('Range')
    parser.add_argument('mapName')

    args = parser.parse_args()
    OSM_map_utils.getGraph(osmCity=args.City, osmRange=float(args.Range), mapName=args.mapName)
