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
    #species='In2O3:ZnO:Ga2O3',
    species=args.comp,
#    species = ['In', 'Ga', 'Zn'],
    no_plot=0,
    #hull_cutoff=0.05,
    hull_cutoff=1,
    labels=True,
    plot_kwargs={
        'colour_by_source': True,
        'sources': ['_pso', '_rand', '_tpe', '_mp', '_oqmd', 'CollCode', 'input-'],
        'source_labels': ['PSO', 'Random', 'TPE', 'MP', 'OQMD', 'ICSD', 'AIRSS'],
    }
)

#print(set(doc.get('source_label', 'MISSING') for doc in polished_hull.cursor))


exit()


#species = ['In', 'Ga', 'Zn']  # Directly specify the elements
#element_colours = [get_element_colours()[s] for s in species]  # Fetch colors for In, Ga, Zn


#"""
# Plot the convex hull of the structures from filtering, also label with respect to the source of the structure
fig, ax = plt.subplots()
polished_hull.hull_cutoff = 0 # This allows us to then add the color shading up to the 0.02 cutoff
ax = matador.plotting.plot_2d_hull(
    polished_hull,
    ax=ax,
    #label_cutoff=0.012,
    label_cutoff=1,
    colour_by_source=True,
    plot_hull_points=False,
    show=1,
    alpha=0.8, 
    label_offset=(1.15, 0.02),
#    eform_limits=(-0.24, 0.03),
    sources=['input-', '_mp', '_oqmd', 'CollCode', 'pso', 'rand','tpe'],
    source_labels=['AIRSS', 'MP', 'OQMD', 'ICSD', 'FUSE','FUSE', 'FUSE'],
    #    element_colours=element_colours  # Pass the element colors here
)

print(set(doc.get('source_label', 'MISSING') for doc in polished_hull.cursor))


# plot up to 20 meV/atom with gray shading
tie_line = polished_hull.convex_hull.points[polished_hull.convex_hull.vertices]
#hull_cutoff = 0.02
hull_cutoff = 0.1
ax.fill_between(np.sort(tie_line[:, 0]), tie_line[np.argsort(tie_line[:, 0]), 1], 
                tie_line[np.argsort(tie_line[:, 0]), 1] + hull_cutoff,
                facecolor='gray', alpha=0.5)

print(set(doc.get('source_label', 'MISSING') for doc in polished_hull.cursor))

#ax.set_yticks([-0.2, -0.15, -0.1, -0.05, 0.0])
ax.tick_params(direction='in')
ax.legend(loc='lower right')
plt.savefig('convex-hull.pdf', bbox_inches='tight')



# Print a table of all the structures with negative formation energy which are also within 50 meV of hull
# currently "summary" means it takes the best structure at each stoich
table_args = {'hull': True, 'summary': False,'use_source': True}

table_cursor = [doc for doc in polished_hull.cursor if doc['hull_distance'] <= 0.05 and doc['formation_enthalpy'] <= 0]
display_results(table_cursor, **table_args)
latex_table = display_results(table_cursor, latex=True, return_str=True, **table_args)

# Replace caps "SWAPS" with "swaps"
latex_table = latex_table.replace("SWAPS", "swaps")
with open('CuP_table.tex', 'w') as f:
    f.write(latex_table)



if 0:
  dir_name = 'SAVED'
  for doc in cursor_1:
    try:doc2res(doc, dir_name + '/' + get_root_source(doc))
    except:continue


exit()

