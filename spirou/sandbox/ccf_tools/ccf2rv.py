import numpy as np
import os
import glob
from astropy.io import fits
from tqdm import tqdm
import matplotlib.pyplot as plt
from astropy.table import Table
from bisector import *
from scipy.optimize import curve_fit

#
# we get the user name. as we are just a few people in the team, we could all
# have our paths hard coded here.
#
name = os.popen('whoami').read().split('\n')[0]

if name == 'eartigau':
    PATH = '/Users/eartigau/wrap_drs_rv';
elif name=='andres':
    PATH = '/some/folder/somewhere';
elif name == 'pascal':
    PATH = '/some/folder/somewhere';
else:
    default: PATH = ''



def gauss(v,v0,ew,zp,amp):
    # gaussian with a constant offset. As we know that the ccfs are negative structures, amp will be negative
    return zp+amp*np.exp( -0.5*(v-v0)**2/ew**2)

def dispatch_object(object, all_ccf_dir = 'all_ccfs'):
    # find all ccf files and copy those that match your object into a folder with the object's name
    #
    # set object to "all" to dispatch all files in folders
    #
    all_ccf_files = glob.glob(PATH+'/'+all_ccf_dir+'/*ccf*.fits')

    ngood_AB = 0
    ngood_C = 0

    print('we are dispatching CCF files into the proper directory for {0}'.format(object))
    for file in tqdm(all_ccf_files):
        # read ccf file
        im, h = fits.getdata(file, header=True)
        outname = PATH+'/'+h['DRSOBJN']+'/'+file.split('/')[-1]


        if (h['DRSOBJN'] == object) or (object == 'all'):
            # if the directory with the object name does not exist, we create it
            if os.path.isdir(PATH+'/'+h['DRSOBJN']) == False:
                os.system('mkdir {0}/{1}'.format(PATH,h['DRSOBJN']))
            if os.path.isfile(outname) == False:
                os.system('cp {0} {1}'.format(file,outname))

            if '_AB.fits' in file:
                ngood_AB+=1
            if '_C.fits' in file:
                ngood_C+=1

    print('We found {0} files for that object. It includes {1} AB files and {2} C drift files'.format(ngood_AB+ngood_C,ngood_AB, ngood_C))

def get_object_rv(object,mask = 'sept18_andres_trans50', method = 'bisector_40_60', exclude_orders = [-1],
                  weight_table = ''):
    # parameters :
    #
    # object -> name of the object to be analyzed, linked to the folder where the data should be. You need
    #           to use dispatch_object first to put the data where it belongs
    #
    #
    # mask = X -> name of the mask used for the CCF. You can have a number of different masks for the same object
    #           and these should be processed individually
    #
    # if you want to systematically exclude orders, then set exclude_orders = [a,b,c,d]. Leave to -1 if you want to
    #          keep all valid orders
    #
    # method = X -> Method to measured velocity. Add you own! For now we have---
    #
    #          bisector_N_M returns the velocity between N and Mth percentile of line depth.
    #
    #         gaussfit --> fits a gaussian to the mean CCF
    #

    ccf_files = glob.glob('{0}/{1}/*tcorr*{2}*.fits'.format(PATH,object,mask))

    # form a unique batch name with mask, object and method
    batch_name = '{0}/{1}_mask_{2}_{3}'.format(PATH,object,mask,method)

    tbl = Table()# output table to be saved as CSV file with RV measurements
    tbl['FILES'] = ccf_files
    tbl['RV'] = np.zeros_like(ccf_files,dtype = float) # measured RV

    # keywords from file headers to be added to the CSV table.
    keywords = ['MJDATE','BERV', 'RV_DRIFT','EXTSN035','AIRMASS','TLPEH2O','TLPEOTR','RV_WAVFP','RV_SIMFP','DATE',
                'MJDMID']


    # add method-specific keywords
    if 'bisector' in method:
        tbl['BIS_SLOPE'] = np.zeros_like(ccf_files,dtype = float)  # bisector slope
        tbl['BIS_WIDTH'] = np.zeros_like(ccf_files,dtype = float)  # bisector slope

    # add method-specific keywords
    if 'gaussian' in method:
        tbl['GAUSS_WIDTH'] = np.zeros_like(ccf_files,dtype = float)  # bisector slope
        tbl['GAUSS_AMP'] = np.zeros_like(ccf_files,dtype = float)  # bisector slope
        tbl['GAUSS_ZP'] = np.zeros_like(ccf_files,dtype = float)  # bisector slope

    #... feel free to add columns here

    print('we load all CCFs into one big cube')
    for i in (range(len(ccf_files))):
        # we loop through all files
        ccf_tbl, hdr = fits.getdata(ccf_files[i], header=True)

        if i ==0:
            # now that we have a first header, we add the relevant columns to the CSV table
            for key in keywords:
                if key in hdr:

                    key_type = type(hdr[key])
                    # if we have a string, we set the table to accept long values (up to 99 characters)
                    if key_type == str:
                        key_type = '<U99'
                else:
                    # keyword not in header, we need to assume something. The safest is string
                    key_type = str

                # add the column to the CSV file
                tbl[key] = np.zeros_like(ccf_files,dtype = key_type)

        for key in keywords:
            if key in hdr:
                tbl[key][i] = hdr[key]

        ccf_RV = ccf_tbl['RV'] # ccf velocity offset, not to be confused with measured RV

        # We must absolutely have always the same RV grid for the CCF. We must check that consecutive ccf_RV are i
        # identical
        if i != 0:
            if np.sum(ccf_RV != ccf_RV_previous):
                print('We have a big problem! The RV vector of CCF files are not all the same')
                print('Files {0} and {1} have different RV vectors.'.format(ccf_files[i-1],ccf_files[i]))
                return
        ccf_RV_previous = np.array(ccf_RV)


        print(np.min(ccf_RV),np.max(ccf_RV),ccf_files[i])
        # if this is the first file, we create a cube that contains all CCFs for all orders for all files
        if i ==0:
            ccf_cube = np.zeros([49,len(ccf_tbl),len(ccf_files)])+np.nan

        # we input the CCFs in the CCF cube
        for j in range(49):
            # if we need to exlude orders, we do it here.
            if j in exclude_orders:
                continue

            tmp =  ccf_tbl['ORDER'+str(j).zfill(2)]


            if False not in  np.isfinite(tmp):
                # we normalize to a continuum of 1
                tmp /= np.polyval(np.polyfit(ccf_RV, tmp, 1), ccf_RV)
                ccf_cube[j,:,i] = tmp

    # this is the median CCF  all epochs for the 49 orders
    med_ccf =  np.nanmedian(ccf_cube,axis = 2)

    # find minimum for CCF. This is used to fit a gaussian to each order and force
    # velocity to zero
    id_min = np.nanargmin( np.nanmedian(med_ccf,axis=0))
    # find the depth of the CCF at minimum position
    ccf_depth = 1-med_ccf[:,id_min]
    # this is analoguous to signal. We could add a factor linked to the width of the line to be even
    # ore accurate
    ccf_depth[ccf_depth<0] = 0


    # now we find the RMS of the Nth spectrum relative to the median
    rms = np.zeros([len(ccf_files),49])
    for i in range(len(ccf_files)):
        rms[i,:] = np.nanstd(ccf_cube[:,:,i]-med_ccf,axis=1)
        rms[i, :] /= np.nanmedian(rms[i, :])

    # this is the typical noise from the ccf dispersion
    ccf_rms = np.nanmedian(rms,axis=0)

    # set to NaN values that are invalid
    ccf_rms[ccf_rms == 0] = np.nan

    # assuming that the CCF has the same depth everywhere, this is the correct weighting of orders
    ccf_snr = ccf_depth / ccf_rms
    weights = ccf_snr**2
    # we normalize the sum of the weights to one
    weights /= np.nansum(weights)

    fig,ax = plt.subplots(nrows = 3, ncols=1,sharex = True)
    ax[0].plot(weights,'go')
    ax[0].set(title = '{0}, mask {1}'.format(object,mask),xlabel = 'Nth order', ylabel = 'Relative order weight')

    ax[1].plot(ccf_depth,'go')
    ax[1].set(xlabel = 'Nth order', ylabel = 'ccf depth')

    ax[2].plot(1/ccf_rms**2,'go')
    ax[2].set(xlabel = 'Nth order', ylabel = '1/$\sigma_{CCF}^2$')
    plt.tight_layout()
    plt.savefig('{0}_weights.pdf'.format(batch_name))
    plt.show()


    plt.imshow(med_ccf,aspect = 'auto',vmin = 0.8,vmax= 1.05)
    plt.xlabel('Velocity bin')
    plt.ylabel('Nth order')
    plt.title('Median CCF')
    plt.savefig('{0}_medianccf.pdf'.format(batch_name))
    plt.show()

    plt.imshow(ccf_cube[:,:,0]-med_ccf,aspect = 'auto',vmin = -0.1,vmax= 0.1)
    plt.xlabel('Velocity bin')
    plt.ylabel('Nth order')
    plt.title('Sample residual CCF map')
    plt.savefig('{0}_residualccf.pdf'.format(batch_name))
    plt.show()

    plt.plot(tbl['MJDATE'], tbl['EXTSN035'], 'g.')
    plt.xlabel('MJDATE')
    plt.ylabel('SNR for order 35\n(around 1.6 $\mu$m)')
    plt.title('Signal-to-noise ratio')
    plt.savefig('{0}_snr.pdf'.format(batch_name))
    plt.show()

    ccf_cube_norm = np.zeros_like(ccf_cube)
    for i in range(49):
        if np.isfinite(weights[i]):
            ccf_cube_norm[i, :, :] = (ccf_cube[i,:,:] * weights[i])

    # get a per-file weighted mean CCF
    mean_ccf = np.nansum(ccf_cube_norm,axis=0)

    fig,ax = plt.subplots(nrows = 2, ncols = 1)
    for i in range(len(ccf_files)):
        color = [i/len(ccf_files),1-i/len(ccf_files),1-i/len(ccf_files)]
        ax[0].plot(ccf_RV,mean_ccf[:,i],color = color,alpha = 0.2)
        ax[1].plot(ccf_RV, mean_ccf[:, i], color=color, alpha=0.2)

    ax[0].set(xlabel = 'Velocity [km/s]',ylabel = 'CCF depth', title = 'Mean CCFs')
    ax[1].set(xlabel = 'Velocity [km/s]',ylabel = 'CCF depth', title = 'Mean CCFs',xlim = [ccf_RV[id_min]-10,
                                                                                           ccf_RV[id_min]+10])
    plt.tight_layout()
    plt.savefig('{0}_CCFs.pdf'.format(batch_name))
    plt.show()

    # we use the bisector method, the name should be something like
    # method = 'bisector_30_70' to get the mean bisector between the 30th and 70th percentile
    if 'bisector' in method:
        # we find the min of CCF and will only compute bisector of +-50 km/s to avoid problems at ccf edges
        imin = np.argmin(np.nanmedian(mean_ccf, axis=1))
        good_RV = np.abs(ccf_RV - ccf_RV[imin]) < 50

        bis_min, bis_max = np.array(method.split('_')[1:3], dtype=float) / 100.

        for i in range(len(ccf_files)):


            try:
                depth, bis, width = bisector(ccf_RV[good_RV], mean_ccf[good_RV,i], low_high_cut=0.2)
                fit = np.polyfit(depth[(depth > bis_min) & (depth < bis_max)] - (bis_min + bis_max) / 2,
                           bis[(depth > bis_min) & (depth < bis_max)], 1)

                tbl['RV'][i] =  fit[1]
                tbl['BIS_SLOPE'][i] =  fit[0]
                tbl['BIS_WIDTH'][i] = np.mean(width[(depth > bis_min) & (depth < bis_max)])
            except:
                print('We had an error with file {0} computing the bisector'.format(ccf_files[i]))
                print('Values will be reported as NaN')
                tbl['RV'][i] =  np.nan
                tbl['BIS_SLOPE'][i] =  np.nan
                tbl['BIS_WIDTH'][i] = np.nan

        fig,ax = plt.subplots(nrows = 2, ncols=1,sharex = True)
        ax[0].plot(tbl['MJDATE'], tbl['RV'], 'g.')
        ax[0].set(title='Velocity',xlabel = 'MJDATE',ylabel = 'RV [km/s]')
        ax[1].plot(tbl['MJDATE'], tbl['BIS_SLOPE'], 'g.')
        ax[1].set(title='Bisector slope',xlabel = 'MJDATE',ylabel = 'slope [km/s/fract. depth]')
        plt.tight_layout()
        plt.savefig('{0}_RV.pdf'.format(batch_name))
        plt.show()

    if 'gaussian' in method:
        imin = np.argmin(np.nanmedian(mean_ccf, axis=1))

        for i in range(len(ccf_files)):
            p0 = [ccf_RV[imin],1,1,-0.1]
            fit, pcov = curve_fit(gauss,ccf_RV,mean_ccf[:,i],p0 = p0)

            tbl['RV'][i] = fit[0]
            tbl['GAUSS_WIDTH'][i] = fit[1]
            tbl['GAUSS_AMP'][i] = fit[3]
            tbl['GAUSS_ZP'][i] = fit[2]

        fig,ax = plt.subplots(nrows = 2, ncols=1,sharex = True)
        ax[0].plot(tbl['MJDATE'], tbl['RV'], 'g.')
        ax[0].set(title='Velocity',xlabel = 'MJDATE',ylabel = 'RV [km/s]')
        ax[1].plot(tbl['MJDATE'], tbl['GAUSS_WIDTH'], 'g.')
        ax[1].set(title='Gaussian width',xlabel = 'MJDATE',ylabel = 'Gaussian e-width [km/s]')
        plt.tight_layout()
        plt.savefig('{0}_RV.pdf'.format(batch_name))
        plt.show()

    # output to csv file
    tbl.write('{0}.csv'.format(batch_name),overwrite = True)

