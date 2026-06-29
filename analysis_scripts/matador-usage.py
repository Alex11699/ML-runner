#!/usr/bin/python
#Adapted from Angela Harpers script.

import matplotlib,time
#matplotlib.rcParams['figure.figsize'] = (8, 6)
matplotlib.rcParams['savefig.dpi'] = 300
# %matplotlib inline 
#from matador.query import DBQuery
#from matador.hull import QueryConvexHull
#from matador.similarity.similarity import get_uniq_cursor
#from matador.scrapers.castep_scrapers import res2dict
#from matador.utils.cursor_utils import filter_cursor, get_array_from_cursor
#from matador.export import doc2res
#from ilustrado.ilustrado import ArtificialSelector
#import seaborn as sns

import numpy as np
import matplotlib.pyplot as plt

from os import chdir, makedirs
from glob import glob

from sys import argv,exit
from matador.utils.chem_utils import get_root_source

from matador.utils.cursor_utils import get_array_from_cursor
from matador.query import DBQuery
from matador.hull import QueryConvexHull
from matador.hull import EnsembleHull
from matador.scrapers import castep2dict, res2dict, bands2dict
from matador.utils.cursor_utils import filter_unique_structures, display_results
from matador.crystal import Crystal
from matador.utils.cell_utils import standardize_doc_cell, get_spacegroup_spg, get_space_group_label_latex
from matador.utils.chem_utils import get_formula_from_stoich
from matador.hull.hull_temperature import TemperatureDependentHull
from matador.orm.spectral import VibrationalDOS, ElectronicDispersion
import matador.plotting
from matador import __version__
print(f"This notebook run was performed with matador {__version__}.")

import argparse

# Import the patch utility
#from patched_utils import apply_patch
#apply_patch()

parser = argparse.ArgumentParser(description='Script for extracting structure properties using the matador package.')
parser.add_argument('-i', '--inpf', nargs='*', type=str, required=True, help='Input file(s)')
parser.add_argument("-c", "--comp", type=str, required=True, help="Chemical composition to be analysed. No default")
args = parser.parse_args()

cursor, failures = res2dict(args.inpf, as_model=True)

# Filter structure for uniqueness
filtering = 0
if filtering:
    polished_cursor = filter_unique_structures(cursor, sim_tol=0.1, enforce_same_stoich=True, quiet=True)
else:
    polished_cursor = cursor

# Prune: reevaluate symmetries and reduce cells
polished_cursor = [Crystal(standardize_doc_cell(doc)) for doc in polished_cursor]

polished_hull = QueryConvexHull(
    cursor=polished_cursor, 
    #species='In2O3:ZnO:Ga2O3',
    species=args.comp,
#    species = ['In', 'Ga', 'Zn'],
    no_plot=1,
    #hull_cutoff=0.05,
    hull_cutoff=1.5,
    labels=True,
)


# Extract and print required properties
for doc in polished_hull.cursor:
    volume = doc['cell_volume']
    pressure = doc['pressure']
    lattice_params = doc['lattice_abc']
    hull_distance = 1000*doc['hull_distance']
    space_group_name = get_spacegroup_spg(doc)[0]
    space_group_no = get_spacegroup_spg(doc)[1]
    fu = doc['num_fu']


    """print(f"Volume: {volume:.2f} Å³")
    print(f"Absolute Pressure: {pressure:.2f} GPa")
    print(f"Lattice Parameters: {lattice_params}")
    print(f"Hull Distance: {hull_distance:.4f}")"""
    #print(f"Space Group: {space_group}")

    #print(doc['source'])  # Debugging output
    with open(f"{doc['source'][0]}.txt", 'w') as f:
        #print(f"Writing to {doc['source'][0]}.txt")
        f.write(f"{doc}")
        f.write(f"Total volume: {volume:.2f} Å³\n")
        f.write(f"#Fu: {fu}\n")
        f.write(f"Cell volume: {volume/fu:.2f} Å³/fu\n")
        f.write(f"Absolute Pressure: {pressure:.2f} GPa\n")
        f.write(f"Lattice Parameters: {lattice_params}\n")
        f.write(f"Hull Distance: {hull_distance:.4f}\n")
        f.write(f"Space Group: {space_group_name}, {space_group_no}\n")
