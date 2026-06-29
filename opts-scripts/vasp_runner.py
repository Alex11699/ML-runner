#!/usr/bin/env python3
import ase.io
from ase.visualize import view
from os import system,popen,chdir,getcwd,getenv,putenv,listdir,environ
import os.path,glob
from re import search
from sys import exit,stdout
#from ase.build import *
import ase.build
from ase import Atoms,Atom
import fractions
from copy import deepcopy
import time
#import ase.build.tools
import matplotlib.pyplot as plt
import ase.calculators.castep,ase.calculators.vasp
from ase.calculators.vasp import Vasp#,Vasp2 #requires ase 3.17.0 or higher

#from mace.calculators import MACECalculator

from spglib import find_primitive,standardize_cell,get_spacegroup #, niggli_reduce #niggli_reduce from ASE-tools conflicts with that from spglib.
from ase.build import niggli_reduce
import argparse

import os.path
from ase.phonons import Phonons

from random import uniform



from subprocess import Popen,PIPE # as popen # check_output
from sys import stdout,version_info
def Popen4(cmd,timeout=None):
    proc=Popen(cmd,shell=True, stdin=PIPE, stdout=PIPE, close_fds=True)
    out,err=proc.communicate(timeout=timeout)
    #out=proc.stdout.readline() #does not work.

    if version_info[0] < 3: out2=[x for x in str(out).replace("b'",'').replace("'",'').split("\n") if x!=""] #python3 adds \\n to the end, python2 adds \n
    else:out2=[x for x in str(out).replace("b'",'').replace("'",'').split("\\n") if x!=""]

    return out2,err


def vasp_continue(ifDel=0):
        fl = listdir(".")
        fl.sort()
        #print fl
        flag=0
        ind=0
        for fn in fl:
                if fn[0:3]=="RUN" :
                        ind = int(fn[3:])

        run="RUN%d"%(ind+1)
        print ("Previous data stored in %s."%run)
        system('mkdir %s'%run)
        system('cp * %s/ 2> /dev/null '%run)
        system('cp CONTCAR POSCAR') #this was missing in the previous version !!
        if ifDel: system('rm WAVECAR CHGCAR')


def grep(key,fname,n=-1): 
    #Uses grep to get the nth line with the keyword from a given file. By default the last occurence is returned.
        #try:
        #        return popen4('grep -m %d "%s" %s '%(n,key,fname),"r")[1].readlines()[-1][0:-1] #don't take \n at the end.  #Fastest one!!!
        #except: 
        try:
                return popen('grep -m %d "%s" %s '%(n,key,fname),"r").read()[0:-1]
        except:
                return ""


def handle_magmoms(atoms, magmoms):
    """
    The magamoms variable should be a list parsed by argparse in the form:
    [...] -mgm Fe 5 Nb 0.6 O 0.6 [...]
    which is then converted to a dictionary:
    d = {
        'Fe': 5.,
        'Nb': 0.6,
        'O': 0.6
        }
    """
    if magmoms is None:   return atoms
    else: print("Magnetic moments are set with ASE: %s"%magmoms)
    
    elements = magmoms[::2]
    values = magmoms[1::2]
    d = dict(zip(elements, values))
    init_mgm = []
    #for s in atoms.symbols:
    for s in atoms.get_chemical_symbols():
        if s not in elements:
            init_mgm.append(0)
        else:
            init_mgm.append(d[s])
    #print([[atoms.get_chemical_symbols()[i],init_mgm[i]] for i in range(len(init_mgm))])
    atoms.set_initial_magnetic_moments(init_mgm)
    return atoms

def set_hubU(atoms,hubU):
    #atoms.calc.set(ldau_luj={'Si': {'L': 1, 'U': 3, 'J': 0}})

    if len(hubU)>0: #is not None:
        atoms.calc.set(ldau=".True.",ldauprint=0,ldautype=2,lmaxmix=6)
        ats=sorted(hubU.keys())
        ldauu=[];ldaul=[]
        #asyms=np.unique(atoms.get_chemical_symbols())#this automatically sorts the atom order
        asyms = list(dict.fromkeys(atoms.get_chemical_symbols()))
        #print (atoms.get_chemical_symbols(),asyms)
        for at in asyms:
            if at in ats: #continue
                if len(hubU[at].keys())>1: print("WARNING: cannot set multiple U values for the same atom type (%s), setting to 0... "%at);ldauu.append(0);ldaul.append(0);continue
                #print (hubU[at].keys()[0])
                orb="".join(hubU[at].keys())#[0] indexing in dict_key format is a problem in Python3.
                ldauu.append(float(hubU[at][orb]))
                if orb=="p":ldaul.append(1)
                elif orb=="d":ldaul.append(2)
                elif orb=="f":ldaul.append(3)
            else:ldaul.append(-1);ldauu.append(0)
        atoms.calc.set(ldauj=[ 0 for i in range(len(asyms)) ])
        atoms.calc.set(ldauu=ldauu,ldaul=ldaul)
        atoms.calc.set(lasph=1)#This is essential for accurate total energies and band structure calculations for f-elements (e.g. ceria), all 3d-elements (transition metal oxides), and magnetic atoms in the 2nd row (B-F atom), in particular if LDA+U or hybrid functionals or meta-GGAs are used, since these functionals often result in aspherical charge densities.
    return atoms

def get_potcar(elements, xc):
    ppdir = os.path.join(vasppp, xc)

    pp = ''
    for e in elements:
        #print os.path.join(ppdir, e, 'POTCAR')
        pp += open(os.path.join(ppdir, e, 'POTCAR')).read()

    return pp

def make_potcar(xc="potpaw_PBE",elements=None,wDir='./'):
    try:    vasppp = os.environ['VASP_PP_PATH']
    except: print ("VASP_PP_PATH is not defined, but neededor VASP calculation setup. Terminating. ");exit()

    print('Making potcar using %s'%vasppp);stdout.flush();


    if elements==None:#Try to read it from POSCAR if not explicitly given.
        try: #VASP5 format.
            elements = open(wDir+"/POSCAR").readlines()[5].strip().split()
        except:
            print ('Elements not given on command line and POSCAR not found')
            exit(-1)

    pp = get_potcar(elements, xc)

    p = open(wDir+"/POTCAR", 'w')
    p.write(pp);    p.close()
            
def call_vasp_v2(fname,exe=None,xc='pbe', mgms=None,hubU={}, dipolCorr=False):#,dipolDir='z'):

    if not exe: exe=getenv('VASP_COMMAND') ; #print ('bk')
    if not exe: exe='vasp_std'
    
    os.environ['VASP_COMMAND']=exe
    print("VASP command: ", exe)#, os.environ['VASP_COMMAND'])

    cwd=os.getcwd()

    seed=fname.split('.')[0]
    try:chdir(seed)
    except:None
    
    #system('vasp_make_potcar -xc potpaw_PBE.54 &> /dev/null')
    if args.makepotcar: make_potcar(xc=args.potcarxc,wDir='.')

    flag=0 #whether to start a new/continuation run 
    try:
        calc = Vasp(restart=True)
        atoms = calc.get_atoms()
        print ("VASP run was read succesfully from OUTCAR.")
        if Vasp.read_convergence(calc): print('Geom opt already converged...')
        else:
          print('Geom opt not converged; running a continuation job...')
          flag=1
        
    except: 
        print ("VASP run could not be read, starting a new run...")
        flag=1

    if flag:
        calc=Vasp()
        #calc = Vasp2(atoms,restart=restart, directory="./", label='vasp', ignore_bad_restart_file=False, command=exe, txt=None)
        calc.read_incar(filename='INCAR')
        if os.path.exists("./OUTCAR"):   vasp_continue()
        atoms=ase.io.read("POSCAR",format="vasp")
        #atoms=ase.io.read(fname)

        calc.set(xc=xc)
        setups='recommended'
        #setups='minimal'
        calc.set(setups=setups)
        calc.directory="."#cdir

        
        if (dipolCorr and dipolCorr.lower()!='none'):
                calc.set(ldipol = ".TRUE.") #this one switches on  the corrections to the potential and thus forces
                if   dipolCorr.lower()=='x': idipol=1 #IDIPOL switches on the single point energy corrections.
                elif dipolCorr.lower()=='y': idipol=2
                elif dipolCorr.lower()=='z': idipol=3
                calc.set(idipol = idipol) #no need to set DIPOL keyword (giving the charge center, if no charged dipole in the system (i.e. total charge=0) 

                #One needs to set the DIPOL keyword (i.e. the center of the net charge in scaled/fractional coordinates), as the automated algorithm leads to terrible convergence. It should be the centre of charge (that requires the CHG file to be created and analysed to be determined), instead  the centre of mass could be used as a good approximation. Setting DIPOL helps even the veryslow convergence when the LDIPOL=true. It even affects the total spin of the system (when ISPIN=2).
                calc.set(dipol=atoms.get_center_of_mass(scaled=1)) #Does this need to be updated for continuation run or better to stick with initial value for better covnergence ??? (CHECK)

        atoms.set_calculator(calc)

    # Adding MAGMOM and ISPIN to INCAR if -mgm or --magmoms is defined.
    atoms = handle_magmoms(atoms=atoms, magmoms=mgms) 
    if len(hubU)>0: atoms=set_hubU(atoms,hubU)

    Ep = atoms.get_potential_energy()

    chdir(cwd)

    return Ep,atoms


################
# Main Program #
################

try:    
    vasppp = os.environ['VASP_PP_PATH']
    ppdirs=os.listdir(vasppp)
    ppdirs.sort()
except: ppdirs=""

parser = argparse.ArgumentParser(description='Script for running a set of structure files (any format supported by ASE) using the ASE/VASP interface. An Example is vasp_runner.py -i *.res -np 128 -exe vasp_std -hubU V d 3.25 -mgm Nb 5 V 0.6 Li 0.6 O 0.6  -xc pbesol & ')


parser.add_argument('-i','--inpf', nargs='*', type=str,required=True, help='Input file(s)')
parser.add_argument('-it','--itype', type=str,required=False, help='Input file type. Def: determined automatically from the extension.')

parser.add_argument('-t', '--tol',type=float, default=1e-4,help="The symmetry tolerance.")


parser.add_argument('-ow','--overwrite', default=False,action='store_true', help='Overwrite if output file exists. Def: No')

parser.add_argument('-dry','--dryrun', default=False,action='store_true', help='Dry run: do not call VASP, just gather information from VASP run folders. Def: No')

parser.add_argument('-np', '--nprocs',type=int, default=32,help="No of processes to start for each VASP calculation throuh mpirun. Def:32")
parser.add_argument('-mpi','--mpirun', default=False,action='store_true', help='Use mpirun for parallel runs. Default: srun is used')
parser.add_argument('-exe','--exe', type=str,required=False, default='vasp_std',help='Vasp exectuable. Def: vasp_std')


parser.add_argument('-ph','--phonons', default=False,action='store_true',help='Do a phonon calculation if the geometry is converged.')
parser.add_argument('-ph_sc','--phonons_supercell', type=int,nargs=3,default=(2,2,2),help='Size of the supercell to be uused in the phonon calculation.Def: No supercell used, i.e. 1 1 1')
parser.add_argument('-ph_del', '--phonons_delta',type=float, default=0.03,help="Stepsize to use in the finite difference method to compute force constants. Def:0.03 A")
parser.add_argument('-ph_np','--phonons_noplot', default=False,action='store_true',help='Do a phonon calculation if the geometry is converged.')
parser.add_argument('-ph_path','--phonons_path', default=None,type=str,help='The high-symmetry Q-point path for a phonon calculation.')

parser.add_argument('-dip','--dipolCorr', default=None,type=str,help='Activate the dipole corrections (suggested for calculations with surbace slab containing vacuum), indicate the direction (x/y/z). Def: None. Usage: -dip z ')
parser.add_argument("-mgm","--magmoms", default=None, nargs="*", required=False, help="Magnetic moments for a collinear calculation. Eg, 'Fe 5.0 Nb 0.6 O 0.6' Def.: None. If a defined element is not present in the POSCAR, no MAGMOM will be set for it.")
parser.add_argument("-hubU", "--hubU", type=str,nargs="*",help="For defining the Hubbard U parameters (in eV) for specific atom and orbital types, e.g. -hubU Fe d 2.7, Sm f 6.1")
parser.add_argument('-xc','--xc', type=str,required=False, default='pbe',help='Exchange correlation functional to use (pseudopots will be selected accordingly, e.g. LDA, PBE,PBEsol, etc. Def: PBE')
parser.add_argument('-mp','-makepotcar','--makepotcar', default=False,action='store_true', help='to compile POTCAR (for VASP) using actual atomic content. The environment variable ($VASP_PP_PATH) should be defined beforehand. Default: False.')
parser.add_argument('--potcarxc', default="potpaw_PBE",type=str,choices=ppdirs,help='XC functional to use in making of POTCAR. Def: potpaw_PBE')

args = parser.parse_args()

initT=time.time()

from ase.spacegroup import Spacegroup,get_spacegroup


if args.mpirun: exe="mpirun -np %d %s"%(args.nprocs,args.exe)
else: exe="srun -n %d %s"%(args.nprocs,args.exe)


#########
if 0: #Get the non-converged structures (res files) from calculation folders.
  files=Popen4("""grep "reached required accuracy - stopping structural energy minimisation" */vasp.out -L | awk -F/ '{print $1}' """) [0]

  print('List of calculations with non-converged geometry: ', files)

  cwd=os.getcwd()
  for f in files:
      atoms=ase.io.read('%s/XDATCAR'%f, index=-1)
      ase.io.write('%s.res'%f,atoms,format='res')

#######

#Parse the Hubbard_U info and make the dict
hubU={}
if args.hubU:
    U=" ".join(args.hubU)
    xxx=U.split(',')
    for xx in xxx:
        x=xx.split()
        if not x[0] in hubU:  hubU[x[0]]={x[1]:x[2]}
        else: hubU[x[0]][x[1]]=x[2]
    print ("Hubbard U values to be used: ",hubU)
#######

system ('mkdir -p ./inputs')
cwd=os.getcwd()
cnt=0
import random
#for inpf in random.choices(args.inpf):
for inpf in args.inpf:
    print (inpf);            stdout.flush()


    if not os.path.isfile(inpf):
        print('%s does not exists, skipping...'%inpf)
        continue

    atoms=ase.io.read(inpf)
    seed=inpf.split('.')[0]
    if not args.dryrun:
      system('mkdir -p %s'%seed) 
      atoms.write('%s/POSCAR'%seed,format='vasp',vasp5=1)
      system('cp -f INCAR  POTCAR KPOINTS %s/'%(seed))
      system('cp %s inputs/; mv %s %s/'%(inpf,inpf,seed))

    chdir(seed)

    if not args.dryrun:
        time.sleep(uniform(0.5, 2.0)) #this to prevent overwriting when two seperate instances of vasp_runner starts running in parallel in the same folder at the same exact time.
        try: Ep,atoms=call_vasp_v2(inpf,exe,xc=args.xc, mgms=args.magmoms,hubU=hubU,dipolCorr=args.dipolCorr)
        except Exception as err:print('%s: Problem with %s, skipping...'%(err,inpf));chdir(cwd);continue
    else: 
      try: Ep=atoms.info['energy']; 
      except Exception as err: print(err); Ep=0.0; #atoms=ase.io.read(inpf)
      if Ep==None: Ep=0.0


    atoms.info['energy']=Ep #atoms.get_total_energy()
    atoms.info['name']=inpf

    #ASE does not get the Pressure right when restarting
    #P=atoms.info.get('pressure')
    P=float(Popen4("""grep pressure OUTCAR | tail -1 | awk '{print ($4+$9)*0.1}' """)[0][0]) #kB to GPa
    atoms.info['pressure']=P

    SG=atoms.info.get('spacegroup')
    if SG is None: 

        try:SG=Popen4('symm %s'%seed,timeout=30)[0][0]  #part of the airss package #now only for cluster, also support the crystal mode.  # symm -cl
        except Exception as err: print(err); SG=''
        print (inpf,SG)#,get_spacegroup(atoms, symprec=args.tol))

    if SG is None or SG == '':   SG=str(get_spacegroup(atoms, symprec=args.tol).symbol.replace(' ',''))
    atoms.info['spacegroup']=SG.replace('(','').replace(')','')
    atoms.info['times_found']=1
    atoms.info['name']=seed
    
    print('%s: Ep=%.5f P= %.2f GPa SG=%s'%(inpf,Ep,P,atoms.info['spacegroup']))


    myres=ase.io.res.Res(atoms)
    myres.energy=Ep
    myres.write_file('%s.res'%(seed), write_info=0,  significant_figures=6) #works!

    #other ways
    #ase.io.res.write_res('%s.res'%(seed), atoms, write_info=0, write_results=1, significant_figures=6) #worksbut energy is written as None even though the value is stored.    
    #ase.io.write('%s-final.res'%(seed), atoms,format='res')


    #Do the phonons calculations (if requested by the user and if the geometry has converged)
    if args.phonons: 
        print('Doing phonons calculations as requested')
        calc=atoms.get_calculator()
        if not args.dryrun and not Vasp.read_convergence(calc): print('Geometry has not converged, skipping the phonons calculation...')
        else:
            
            if os.path.exists('phonon'): 
                print('Previous phonons calc was found in the %s/phonon directory, will read existing force data and do the missing points.'%seed)
                for f in glob.glob("phonon/*.json",recursive=0):
                    if os.path.getsize(f)==0: system('rm %s'%f); print (f,' is empty, deleted')#delete the empty files to recalculate

            calc.directory=calc.directory+"/Phonon-tmp/"
            print(calc.directory)
            calc.set(nsw=0,ibrion=-1,algo='fast') #do a single point at each phonon step
            calc.set(lwave=1) #save wavecar for restarting electronic wavefunction

            ph = Phonons(atoms, calc, supercell=args.phonons_supercell, delta=args.phonons_delta)
            if not args.dryrun: ph.run()
            else: print('Dry run, no phonon calculations wll be done for %s'%inpf)

            # Read forces and assemble the dynamical matrix
            #method='Frederiksen' 
            method='standard'
            try: ph.read(acoustic=True,method=method) 
            except: print ('Problem while reading phonon calc from %s, skipping...'%seed);continue

            path = atoms.cell.bandpath(args.phonons_path, npoints=100) #if special_path is set to None,then it will be automatically determined.

            bs = ph.get_band_structure(path)
            dos = ph.get_dos(kpts=(20, 20, 20)).sample_grid(npts=100, width=1e-3)
            print(path)

            if args.phonons_noplot: chdir(cwd); continue

            # Plot the band structure and DOS:
            fig = plt.figure(1, figsize=(7, 4))
            ax = fig.add_axes([.12, .07, .67, .85])

            emax=0.04
            #emax=max(dos.get_energies()) #TODO: get this from user
            bs.plot(ax=ax, emin=0.0, emax=emax)

            dosax = fig.add_axes([.8, .07, .17, .85])
            dosax.fill_between(dos.get_weights(), dos.get_energies(), y2=0, color='grey',
                               edgecolor='k', lw=1)

            dosax.set_ylim(0, emax)
            dosax.set_yticks([])
            dosax.set_xticks([])
            dosax.set_xlabel("DOS", fontsize=14)

            fig.savefig('%s_phonon.png'%seed)
            #plt.show()

            # Write modes for specific q-vector to trajectory files:
            #L = path.special_points['L']
            #ph.write_modes([l / 2 for l in L], branches=[2], repeat=(8, 8, 8), kT=3e-4,
            #   center=True)


            # Generate gif animation:
            # XXX Temporarily disabled due to matplotlib writer compatibility issue.
            # with Trajectory('phonon.mode.2.traj', 'r') as traj:
            #     write('Al_mode.gif', traj, interval=50,
            #           rotation='-36x,26.5y,-25z')


    chdir(cwd)








#grep "free  energy   TOTEN  = " $seed/OUTCAR  | tail -1 | awk '{print " VASP: Final Enthalpy     = "$5}' >> $seed.castep
