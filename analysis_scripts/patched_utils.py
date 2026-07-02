from matador.plotting.hull_plotting import get_element_colours, plot_ternary_hull

def patched_get_element_colours():
    #from matador.plotting.hull_plotting import get_element_colours
    element_colours = get_element_colours()  # Load the original mapping
    # Add a custom color mapping for missing elements
    element_colours.update({
        'In2O3': [0, 1, 0],  # Example RGB values, customize as needed
        'Ga2O3': [1, 0, 0],
        'ZnO': [0,0,1]
    })
    return element_colours

def apply_patch():
    # Overwrite the original `get_element_colours` function in the `matador` package
 
    import matador.plotting.hull_plotting
    matador.plotting.hull_plotting.get_element_colours = patched_get_element_colours


####Colour by source fix######

    import matador.utils.cursor_utils as cu
    import matador.plotting.hull_plotting as hp

    # Part 1: patch get_guess_doc_provenance to recognise FUSE methods
    original_provenance = cu.get_guess_doc_provenance

    def patched_provenance(sources, icsd=None):
        if isinstance(sources, str):
            sources = [sources]
        fname = ''.join(s.split('/')[-1] for s in sources).lower()
        #fname = ''.join(sources).lower()
        #if 'pso' in fname:
         #   return 'FUSE'
        #elif 'rand' in fname:
         #   return 'FUSE'
        #elif 'tpe' in fname:
         #   return 'FUSE'
        #return original_provenance(sources, icsd=icsd)
        if any(s in fname for s in ['pso', 'rand', 'tpe']):
            return 'FUSE'
        if '_mat_' in fname:
            return 'MatterGen'
        result = original_provenance(sources, icsd=icsd)
        if result == 'OQMD':
            return 'MP'  # merge OQMD into MP label
        return result
    cu.get_guess_doc_provenance = patched_provenance

    # Part 2: wrap plot_ternary_hull to add source colouring
    original_ternary = hp.plot_ternary_hull

    def patched_ternary_hull(hull, *args, **kwargs):
        sources = kwargs.pop('sources', None)
        source_labels = kwargs.pop('source_labels', None)
        plot_cutoff = kwargs.pop('plot_cutoff', None)
        show = kwargs.pop('show', True)  # intercept show
        if sources is not None:
            kwargs['plot_points'] = False
        ax = original_ternary(hull, *args, show=False, **kwargs)  # never show early
        if sources is not None:
            scale = 1
            _ternary_scatter_by_source(
                hull, ax, scale,
                sources=sources,
                source_labels=source_labels,
                plot_cutoff=plot_cutoff,
            )
        import matplotlib.pyplot as plt
        plt.savefig('ternary_hull.png', bbox_inches='tight', dpi=300)
        if show:
            import matplotlib.pyplot as plt
            plt.show()
        return ax

    hp.plot_ternary_hull = patched_ternary_hull
    import matador.plotting                                    
    matador.plotting.plot_ternary_hull = patched_ternary_hull  


def _ternary_scatter_by_source(hull, ax, scale, sources=None, source_labels=None, plot_cutoff=None):
    """Ternary-aware reimplementation of _scatter_plot_by_source."""
    from collections import defaultdict
    from matador.utils.cursor_utils import get_guess_doc_provenance
    import numpy as np
    import matplotlib.patches as mpatches

    SOURCE_COLOURS = {
        'FUSE':  '#2196F3',  # blue
        'AIRSS': '#FF5722',  # orange
        'MatterGen': '#FC0FC0', #pink
        'MP':    '#00ff00',  # green
        'ICSD':  '#212121',  # dark/black
        'Other': '#BDBDBD',  # light gray
    }

    if sources is None:
        sources = ['FUSE', 'MP', 'AIRSS', 'ICSD', 'Other', 'MatterGen']
    if source_labels is None:
        source_labels = sources
    else:
        assert len(source_labels) == len(sources)
    if 'Other' not in sources:
        sources.append('Other')
        source_labels.append('Other')

    points_by_source = {source: [] for source in sources}
    hdist_by_source = {source: [] for source in sources}


    if plot_cutoff is None:
        plot_cutoff = hull.hull_cutoff

    for doc in hull.cursor:
        if doc['hull_distance'] > plot_cutoff:  # add this filter
            continue
        source = get_guess_doc_provenance(doc['source'])
        if source not in sources:
            source = 'Other'
        conc = doc.get('concentration')
        if conc is None:
            continue
        x, y = conc
        a = scale * x
        b = scale * y
        c = scale * (1 - x - y)
        points_by_source[source].append((a, b, c))
        hdist_by_source[source].append(doc['hull_distance'])

    legend_handles = []

    """
    # Print FUSE structures that appear on the diagram
    print("\nFUSE structures plotted:")
    print(f"{'Source':<50} {'Formula':<20} {'Space group':<15} {'Hull dist (meV/atom)'}")
    print("-" * 100)
    for doc in hull.cursor:
        source = get_guess_doc_provenance(doc['source'])
        if source != 'FUSE':
            continue
        conc = doc.get('concentration')
        if conc is None:
            continue
        src_name = doc.get('source', [''])[0].split('/')[-1].replace('.res', '')
        formula = doc.get('formula', '?')
        spg = doc.get('space_group', '?')
        hdist = doc.get('hull_distance', float('nan')) * 1000
        print(f"{src_name:<50} {formula:<20} {spg:<15} {hdist:.1f}")
    print("-" * 100)
    """

    for ind, source in enumerate(sources):
        pts = points_by_source[source]
        if not pts:
            continue
        colour = SOURCE_COLOURS.get(source, '#BDBDBD')
        pts_array = np.array(pts)
        hdists = np.array(hdist_by_source[source])
        sizes = 150 * (1 - hdists / plot_cutoff) + 5
        ax.scatter(pts_array, c=colour, s=sizes, alpha=0.6, zorder=100, edgecolors='k', linewidths=0.5)
        legend_handles.append(
            mpatches.Patch(color=colour, label=source_labels[ind])
        )

    ax.ax.legend(handles=legend_handles, ncol=2)
