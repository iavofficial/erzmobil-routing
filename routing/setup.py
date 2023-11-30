from setuptools import setup

setup(name='routing',
      version='0.1',
      description='Class definitions and solver for bUSnow routing problems',
      packages=['routing'],
      install_requires=[
          'networkx',
          'ortools',
          'shapely',
      ],
      zip_safe=False)