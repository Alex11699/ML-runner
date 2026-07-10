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
from patched_utils import apply_patch



#from matador.utils.cursor_utils import get_array_from_cursor
## here we grab the first element of the concentration array, which only contains 1 element for a binary system
#concentrations = get_array_from_cursor(hull.hull_cursor, ['concentration', 0])
#formation_enthalpy = get_array_from_cursor(hull.hull_cursor, 'formation_enthalpy_per_atom')
#hull_distances = get_array_from_cursor(hull.hull_cursor, 'hull_distance')
#for conc, eform, hdist in zip(concentrations, formation_enthalpy, hull_distances):
#    print(f"{conc:12.4f} {eform:12.4f} {1000*hdist:12.4f}")

initT=time.time()

parser = argparse.ArgumentParser(description='Script for converting between different file formats using the ASE interface.')

parser.add_argument('-i','--inpf', nargs='*', type=str,required=True, help='Input file(s)')

parser.add_argument("-c","--comp", type=str,required=1,
                    help="Chemical composition to be analysed. No default")
args = parser.parse_args()



#query=DBQuery(**{'composition': 'LiVNbO', 'intersection': True, 'subcmd': 'query', 'biggest': True, 'details': 0, 'cutoff': [300,301], 'kpoints': 0.07, 'kpoint_tolerance': 0.1, 'source': 0,'summary':1,'no_plot':False , 'hull_cutoff': 0.00, 'db': 'bk393-LiPS'})  # 
#cursor=query.cursor


cursor, failures = res2dict(args.inpf, as_model=True)


# filter structure for uniqueness
filtering = 0
if filtering:
    polished_cursor = filter_unique_structures(cursor, sim_tol=0.1, enforce_same_stoich=True, quiet=True)
else:
    polished_cursor = cursor

# do some pruning: reevaluate symmetries and reduce cells
polished_cursor = [Crystal(standardize_doc_cell(doc)) for doc in polished_cursor]


# Apply the patch
apply_patch()

polished_hull = QueryConvexHull(
    cursor=polished_cursor,
    species=args.comp,
    no_plot=True,  # don't auto-plot
    hull_cutoff=0.1,
    labels=True,

)

hull_cutoff = polished_hull.hull_cutoff

from matador.utils.cursor_utils import display_results, get_guess_doc_provenance
table_cursor = [
    doc for doc in polished_hull.cursor
    if doc['hull_distance'] <= hull_cutoff
    and get_guess_doc_provenance(doc['source']) in ('FUSE', 'MatterGen')
]
display_results(table_cursor, hull=True, summary=False, use_source=True)

matador.plotting.plot_ternary_hull(
    polished_hull,
    show=True,
    labels=True,
    sources=['AIRSS', 'FUSE', 'MatterGen', 'MP', 'ICSD'],
    source_labels=['AIRSS', 'FUSE', 'MatterGen', 'MP/OQMD', 'ICSD'],
)

exit()
