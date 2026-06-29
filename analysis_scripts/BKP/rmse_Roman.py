import numpy as np
import matplotlib.pyplot as plt

calc_arr=['chgnet','sevenn','mace_mp','Orb']
#temp_arr=['525','800','1075','1350', '1625']

dict_m = {
        'vasp_energy_525' = [...],
        'vasp_energy_800' = [...],
        .
        .
        .
        'chgnet_energy_525' = [...],
        'chgnet_energy_800' = [...],
        .
        .
        .
        }



def rmse(a,b):
    return np.sqrt(np.mean((np.array(a)-np.array(b))**2))



def plot_rmse_energy(calc_arr,temp_arr,dict_m):
#     for i in dict_m:
#
    dict_calc_name = {
        'mace_mp' : 'MACE-MP-0',
        'chgnet' : 'CHGNet',
        'sevenn' : 'SevenNet-0'
    }

    font= 20
    fig, axs = plt.subplots(len(calc_arr), len(temp_arr), figsize=(24, 12))
    for i in range(len(calc_arr)):
        for j in range(len(temp_arr)):
            calc=calc_arr[i]
            temp=temp_arr[j]
            
            x= dict_m['vasp_energy_'+temp] - np.average(dict_m['vasp_energy_'+temp])
            y= dict_m[calc+'_energy_'+temp] - np.average(dict_m[calc+'_energy_'+temp])
            
            
            axs[i, j].scatter(x, y)
            
            som = [abs(min(x)), abs(max(x))]
            
            lin_x = np.arange(-max(som), max(som), 0.001)
            axs[i, j].plot(lin_x, lin_x, label='Ideal Target', linestyle=':')
            axs[i, j].set_ylabel('Predicted energy/eV', fontsize=24)
            axs[i, j].set_xlabel('VASP AIMD energy/eV', fontsize=24)
            axs[i, j].set_xlim(-max(som), max(som))
            axs[i, j].set_ylim(-max(som), max(som))
            
            rmse_energy = rmse(x,y)
            axs[i, j].text(1,0.2,'RMSE = 'f'{rmse_energy:.6f}', fontsize=font , ha='right',transform=axs[i, j].transAxes)
            
            
            axs[i, j].set_title(dict_calc_name[calc], fontsize=28)
    plt.tight_layout()
    plt.savefig("RMSE_energy_foundation.pdf", format="pdf")
    plt.show()

