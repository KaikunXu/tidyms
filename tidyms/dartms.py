"""

  File for many functions concerning the processing of a DART-MS experiment. 

"""

import tqdm
import numpy as np
import pandas as pd
import tidyms as ms
import os
import plotnine as p9
import pickle
import datetime
import math
import scipy
import warnings



def subset_MSData_chronogram(msData, startInd, endInd):
    """
    Function subsets a MSData object by chronogram time into a new MSData_subset_spectra object via an internal reference

    Args:
        msData (MSData): The MSData object to subset
        startInd (int): Index of first spectrum (included)
        endInd (int): Index of last spectrum (included)

    Returns:
        MSData: The new MSData subset object
    """    
    return ms.fileio.MSData_subset_spectra(start_ind = startInd, end_ind = endInd, from_MSData_object = msData)

def get_separate_chronogram_indices(msData, msData_ID, spotsFile, intensityThreshold = 0.00001, startTime_seconds = 0, endTime_seconds = 1E6):
    """
    Function separats a chronogram MSData object into spots that are defined as being continuously above the set threshold. 
    Spots are either automatically detected (when the sportsFile is not available) or user-guided (when the spotsFile exists)
    There is deliberately no option to superseed the automated extraction of the spots to not remove an existing spotsFile by accident. If the user wishes to automatically find the spots, the spotsFile file should be deleted by them    

    Args:
        msData (MSData): The chronogram MSData object to separate into spots
        msData_ID (string): The name of the chronogram object
        spotsFile (string): The file to which the spots information will be written to. Furthermore, if the file already exists, information provided there will superseed the automated detection of the spots. 
        intensityThreshold (float, optional): _description_. Defaults to 0.00001.
        startTime_seconds (int, optional): _description_. Defaults to 0.
        endTime_seconds (_type_, optional): _description_. Defaults to 1E6.

    Raises:
        RuntimeError: 

    Returns:
        list of (startInd, endInd, spotName, group, class, batch): Detected of user-guided spots.
    """    
    if spotsFile is None:
        raise RuntimeError("Parameter spotsFile must be specified either to save extracted spots to or to read from there. ")
    
    spots = None
    if type(spotsFile) is str:
        if os.path.exists(spotsFile) and os.path.isfile(spotsFile):
            spots = pd.read_csv(spotsFile, sep = "\t")
        else:
            spots = pd.DataFrame({
                "msData_ID": [],
                "spotInd": [],
                "name": [],
                "group": [],
                "class": [],
                "batch": [],
                "startRT_seconds": [],
                "endRT_seconds": [],
                "comment": []
            })
    else:
        raise RuntimeError("Parameter spotsFile must be a str")

    spotsCur = spots[spots["msData_ID"] == msData_ID]
    separationInds = []
    if spotsCur.shape[0] == 0:
        ticInts = [sum(msData.get_spectrum(i).spint) for i in range(msData.get_n_spectra())]
        startInd = None
        endInd = None
        for i, inte in enumerate(ticInts):
            time = msData.get_spectrum(i).time
            if inte >= intensityThreshold and time >= startTime_seconds and time <= endTime_seconds:
                if startInd is None:
                    startInd = i
                endInd = i
                
            else:
                if startInd is not None:
                    separationInds.append((startInd, endInd, "Spot_%d"%len(separationInds), 0, 0, 0))
                    startInd = None
                    endInd = None
        
        if startInd is not None:
            separationInds.append((startInd, endInd, "Spot_%d"%len(separationInds), 0, 0, 0))
        
        for spotInd, spot in enumerate(separationInds):
            print(spot)
            temp = pd.DataFrame({
                "msData_ID": [msData_ID],
                "spotInd": [int(spotInd)],
                "name": [spot[2]],
                "group": [0],
                "class": [0],
                "batch": [0],
                "startRT_seconds": [msData.get_spectrum(spot[0]).time],
                "endRT_seconds": [msData.get_spectrum(spot[1]).time],
                "comment": ["spot automatically extracted by get_separate_chronogram_indices(msData, '%s', intensityThreshold = %f, startTime_seconds = %f, endTime_seconds = %f)"%(msData_ID, intensityThreshold, startTime_seconds, endTime_seconds)]
            })
            spotsCur = pd.concat([spotsCur, temp], axis = 0)
        spots = pd.concat([spots, spotsCur], axis = 0, ignore_index = True).reset_index(drop = True)
        spots.to_csv(spotsFile, sep = "\t", index = False)
    
    else:
        for index, row in spotsCur.iterrows():
            if row["include"]:
                startInd, timeDiff_start = msData.get_closest_spectrum_to_RT(row["startRT_seconds"])
                endInd, timeDiff_end = msData.get_closest_spectrum_to_RT(row["endRT_seconds"])
                separationInds.append((startInd, endInd, row["name"], row["group"], row["class"], row["batch"]))

    return separationInds

def add_chronograms_samples_to_assay(assay, sepInds, msData, filename, fileNameChangeFunction = None, verbose = True):
    """
    Function adds spots from a chronogram file to an existing assay

    Args:
        assay (Assay): Assay object to add the spots to
        sepInds (list of (startInd, endInd, spotName, group, class, batch)): Information of spots
        msData (MSData): Chronogram from which the spots are generated
        filename (str): Name of the chronogram sample
        verbose (bool, optional): Print additional debugging information. Defaults to True.
    """    
    if fileNameChangeFunction is None:
        fileNameChangeFunction = lambda x: x
    for subseti, _ in enumerate(sepInds):
        subset_name = fileNameChangeFunction("VIRTUAL(%s::%s)"%(os.path.splitext(os.path.basename(filename))[0], sepInds[subseti][2]))
        if verbose: 
            print("      .. adding subset %4d with name '%35s', width %6.1f sec, RTs %6.1f - %6.1f"%(subseti, subset_name, msData.get_spectrum(sepInds[subseti][1]).time - msData.get_spectrum(sepInds[subseti][0]).time, msData.get_spectrum(sepInds[subseti][0]).time, msData.get_spectrum(sepInds[subseti][1]).time))
        subset = ms.fileio.MSData_Proxy(ms.dartms.subset_MSData_chronogram(msData, sepInds[subseti][0], sepInds[subseti][1]))
        assay.add_virtual_sample(
            MSData_object = subset,
            virtual_name = subset_name,
            sample_metadata = pd.DataFrame({
                "sample": [subset_name],
                "group": sepInds[subseti][3],
                "class": sepInds[subseti][4],
                "order": [1],
                "batch": sepInds[subseti][5],
                "basefile": [os.path.splitext(os.path.basename(filename))[0]],
                "extracted_spectra_indices": ["%.2f - %.2f seconds"%(msData.get_spectrum(sepInds[subseti][0]).time, msData.get_spectrum(sepInds[subseti][1]).time)],
                "spotwidth_seconds": [msData.get_spectrum(sepInds[subseti][1]).time - msData.get_spectrum(sepInds[subseti][0]).time]
            })
        )


def create_assay_from_chronogramFiles(filenames, spot_file, ms_mode, instrument, centroid_profileMode = True, fileNameChangeFunction = None):
    """
    Generates a new assay from a series of chronograms and a spot_file

    Args:
        filenames (list of str): File path of the chronograms
        spot_file (str): File path of the spot file
        centroid_profileMode (bool): indicates if profile mode data shall be centroided automatically

    Returns:
        Assay: The new generated assay object with the either automatically or user-guided spots from the spot_file
    """    
    assay = ms.assay.Assay(
        data_path = None,
        sample_metadata = None,
        ms_mode = "centroid",
        instrument = "qtof",
        separation = "uplc",
        data_import_mode = "memory",
        n_jobs = 2,
        cache_MSData_objects = True)
    print("   - Created empty assay")
    
    for filename in filenames:
        print("   - File '%s'"%(filename), end = "")

        msData = None
        if os.path.exists(filename + ".pickle") and os.path.isfile(filename + ".pickle"):
            print(" // loaded from pickle file")
            with open(filename + ".pickle", "rb") as fin:
                msData = pickle.load(fin)
        else:
            print("")
            msData = ms.fileio.MSData.create_MSData_instance(
                path = filename,
                ms_mode = ms_mode,
                instrument = instrument,
                separation = "None/DART", 
                data_import_mode = ms._constants.MEMORY,
            )
        
            if centroid_profileMode and ms_mode == "profile":
                print("      .. centroiding")
                for k, spectrum in msData.get_spectra_iterator():
                    mzs, intensities = spectrum.find_centroids()
                    if k == 50 and False:
                        temp = {
                            "mz": [],
                            "intensity": [],
                            "mode":[]
                        }
                        temp["mz"].extend(spectrum.mz)
                        temp["intensity"].extend(spectrum.spint)
                        temp["mode"].extend(("profile" for i in spectrum.mz))
                        
                        temp["mz"].extend(mzs)
                        temp["intensity"].extend(intensities)
                        temp["mode"].extend(("centroid" for i in intensities))

                        import plotnine as p9
                        import pandas as pd

                        temp = pd.DataFrame(temp)

                        p = (p9.ggplot(data = temp, mapping = p9.aes(x = "mz", ymin = 0, ymax = "intensity", colour = "mode"))
                            + p9.geom_linerange()
                        )
                        print(p)

                    spectrum.mz = mzs
                    spectrum.spint = intensities
                    spectrum.centroid = True

            with open(filename + ".pickle", "wb") as fout:
                pickle.dump(msData, fout)

        sepInds = ms.dartms.get_separate_chronogram_indices(msData, os.path.splitext(os.path.basename(filename))[0], spot_file, intensityThreshold = 1E3)
        if len(sepInds) == 0:
            print("      .. no spots to extract")
        else:
            ms.dartms.add_chronograms_samples_to_assay(assay, sepInds, msData, filename, fileNameChangeFunction = fileNameChangeFunction)
    return assay



## Plot sample TICs
def plot_sample_TICs(assay):
    temp = {
        "sample": [],
        "group": [],
        "time": [],
        "kSpectrum": [],
        "totalIntensity": []
    }
    sample_metadata = assay.manager.get_sample_metadata()
    for samplei, sample in enumerate(assay.manager.get_sample_names()):
        msDataObj = assay.get_ms_data(sample)
        for k, spectrum in msDataObj.get_spectra_iterator():
            temp["sample"].append(sample)
            temp["group"].append(sample_metadata.loc[sample, "group"])
            temp["time"].append(spectrum.time - msDataObj.get_spectrum(0).time)
            temp["kSpectrum"].append(k)
            temp["totalIntensity"].append(np.sum(spectrum.spint))

    temp = pd.DataFrame(temp)
    p = (p9.ggplot(data = temp, mapping = p9.aes(
            x = "time", y = "totalIntensity", colour = "group", group = "sample"
        ))
        + p9.geom_line(alpha = 0.8)
        + p9.theme_minimal()
        + p9.theme(legend_position = "bottom")
        + p9.theme(subplots_adjust={'wspace':0.15, 'hspace':0.25, 'top':0.93, 'right':0.99, 'bottom':0.15, 'left':0.15})
        + p9.ggtitle("TIC of chronogram samples")
    )
    print(p)

def drop_lower_spectra(assay, drop_rate = None):
    for samplei, sample in enumerate(assay.manager.get_sample_names()):
        totalInt = []
        msDataObj = assay.get_ms_data(sample)
        for k, spectrum in msDataObj.get_spectra_iterator():
            totalInt.append(np.sum(spectrum.spint))

        if drop_rate is not None:
            sampleObjNew = ms.fileio.MSData_in_memory.generate_from_MSData_object(msDataObj)
            ordInte = np.argsort(np.array(totalInt))
            ordInte = ordInte[0:math.floor(sampleObjNew.get_n_spectra() * drop_rate)]
            ordInte = np.sort(ordInte)[::-1]
            c = 0
            while c < ordInte.shape[0] and msDataObj.get_n_spectra() > 0:
                sampleObjNew.delete_spectrum(ordInte[c])
                c = c + 1
            msDataObj.to_MSData_object = sampleObjNew

def select_top_n_spectra(assay, n = None):
    for samplei, sample in enumerate(assay.manager.get_sample_names()):
        totalInt = []
        msDataObj = assay.get_ms_data(sample)
        for k, spectrum in msDataObj.get_spectra_iterator():
            totalInt.append(np.sum(spectrum.spint))

        if n is not None:
            sampleObjNew = ms.fileio.MSData_in_memory.generate_from_MSData_object(msDataObj)
            ordInte = np.argsort(np.array(totalInt))
            ordInte = ordInte[0:ordInte.shape[0]-n]
            ordInte = np.sort(ordInte)[::-1]
            c = 0
            while c < ordInte.shape[0] and msDataObj.get_n_spectra() > 0:
                sampleObjNew.delete_spectrum(ordInte[c])
                c = c + 1
            msDataObj.to_MSData_object = sampleObjNew

def normalize_samples_by_TICs(assay, multiplication_factor = 1):
    for samplei, sample in enumerate(assay.manager.get_sample_names()):
        totalInt = []
        msDataObj = assay.get_ms_data(sample)
        for k, spectrum in msDataObj.get_spectra_iterator():
            totalInt.append(np.sum(spectrum.spint))
        totalInt = np.sum(np.array(totalInt))

        sampleObjNew = ms.fileio.MSData_in_memory.generate_from_MSData_object(msDataObj)
        msDataObj.to_MSData_object = sampleObjNew

        if totalInt > 0:
            for k, spectrum in msDataObj.get_spectra_iterator():
                spectrum.spint = spectrum.spint / totalInt * multiplication_factor
        else:
            print("   .. Error: cannot normalize sample '%35s' to TIC as it is zero"%(sample))

def normalize_to_internal_standard(assay, std, multiplication_factor = 1, plot = False):
    stdMZmin, stdMZmax = std
    
    sample_metadata = assay.manager.get_sample_metadata()
    
    temp = {"sample": [], "group": [], "istdAbundance": []}
    for samplei, sample in enumerate(assay.manager.get_sample_names()):
        sampleType = sample_metadata.loc[sample, "group"]
        totalSTDInt = 0
        msDataObj = assay.get_ms_data(sample)
        for k, spectrum in msDataObj.get_spectra_iterator():
            use = np.logical_and(spectrum.mz >= stdMZmin, spectrum.mz <= stdMZmax)
            if np.sum(use) > 0:
                totalSTDInt = totalSTDInt + np.sum(spectrum.spint[use])
        
        if totalSTDInt > 0:
            print("   .. sample '%35s' STD intensity (sum) %12.1ff * %12.1f"%(sample, totalSTDInt, multiplication_factor))
            for k, spectrum in msDataObj.get_spectra_iterator():
                spectrum.spint = spectrum.spint / totalSTDInt * multiplication_factor
            temp["sample"].append(sample)
            temp["group"].append(sampleType)
            temp["istdAbundance"].append(totalSTDInt)
        else:
            print("   .. Error: cannot normalize sample '%35s' to internal standard as no signals for it have been found"%(sample))

    if plot:
        temp = pd.DataFrame(temp)
        p = (p9.ggplot(data = temp, mapping = p9.aes(
                x = "sample", y = "istdAbundance", group = "group", colour = "group"
            ))
            + p9.geom_point()
            + p9.theme_minimal()
            + p9.theme(legend_position = "bottom")
            + p9.theme(subplots_adjust={'wspace':0.15, 'hspace':0.25, 'top':0.93, 'right':0.99, 'bottom':0.05, 'left':0.05})
            + p9.guides(alpha = False, colour = False)
            + p9.ggtitle("Abundance of internal standard (mz %.5f - %.5f)"%(std[0], std[1]))
        )
        
    







def get_MZ_offsets(assay, referenceMZs = [165.078978594 + 1.007276], max_mz_deviation_absolute = 0.1):
    """
    Function to calculate the mz offsets of several reference features in the dataset. 
    A signal for a feature on the referenceMZs list is said to be found, if it is within the max_mz_deviation_absolute parameter. The feature with the closest mz difference will be used in cases where several features are present in the search window

    Args:
        assay (Assay): The assay of the experiment
        referenceMZs (list of MZ values (floats)): The reference features for which the offsets shall be calculated. Defaults to [165.078978594 + 1.007276].
        max_mz_deviation_absolute (float, optional): Maximum deviation used for the search. Defaults to 0.1.

    Returns:
        _type_: _description_
    """    
    temp = {
        "time": [],
        "intensity": [],
        "referenceMZ": [],
        "mz": [],
        "mzDeviation": [],
        "mzDeviationPPM": [],
        "sample": [],
        "file": [],
        "chromID": []
    }

    if type(referenceMZs) is list:
        referenceMZs = np.array(referenceMZs)
    
    for sample in assay.manager.get_sample_names():
        msDataObj = assay.get_ms_data(sample)
        chroms = ms.raw_data_utils.make_chromatograms(msDataObj, referenceMZs, window = max_mz_deviation_absolute)
        for i, chrom in tqdm.tqdm(enumerate(chroms), total = len(chroms), delay = 5):
            referenceMZ = referenceMZs[i]
            for j in range(chrom.time.shape[0]):
                ind, curMZ, deltaMZ, deltaMZPPM, inte = msDataObj.get_spectrum(j).get_closest_mz(referenceMZ, max_offset_absolute = max_mz_deviation_absolute)
                if ind is not None:
                    temp["referenceMZ"].append(referenceMZ)
                    temp["mz"].append(curMZ)
                    temp["mzDeviation"].append(deltaMZ)
                    temp["mzDeviationPPM"].append(deltaMZPPM)
                    temp["time"].append(chrom.time[j])
                    temp["intensity"].append(inte)
                    temp["sample"].append(sample)
                    temp["file"].append(sample.split("::")[0])
                    temp["chromID"].append("%s %.4f"%(sample, referenceMZ))

    return pd.DataFrame(temp)

def correct_MZ_shift_across_samples(assay, referenceMZs = [165.078978594 + 1.007276], max_mz_deviation_absolute = 0.1, correctby = "mzDeviationPPM", max_deviationPPM_to_use_for_correction = 80, plot = False, verbose = True):
    """
    Function to correct systematic shifts of mz values in individual spot samples
    Currently, only a constant MZ offset relative to several reference features can be corrected. The correction is carried out by calculating the median error relative to the reference features' and then apply either the aboslute or ppm devaition to all mz values in the spot sample. 
    A signal for a feature on the referenceMZs list is said to be found, if it is within the max_mz_deviation_absolute parameter. The feature with the closest mz difference will be used in cases where several features are present in the search window

    Args:
        assay (Assay): The assay object of the experiment
        referenceMZs (list of MZ values (float), optional): The reference features for which the offsets shall be calculated. Defaults to [165.078978594 + 1.007276].
        max_mz_deviation_absolute (float, optional): Maximum deviation used for the search. Defaults to 0.1.
        correctby (str, optional): Either "mzDeviation" for correcting by a constant mz offset or "mzDeviationPPM" to correct by a constant PPM offset. Defaults to "mzDeviationPPM".
        plot (bool, optional): Indicates if a plot shall be generated and returned. Defaults to False.

    Returns:
        (pandas.DataFrame, plot): Overview of the correction and plot (if it shall be generated)
    """    
    temp = get_MZ_offsets(assay, referenceMZs = referenceMZs, max_mz_deviation_absolute = max_mz_deviation_absolute)
    temp["mode"] = "original MZs"

    tempMod = temp.copy()
    tempMod["mode"] = "corrected MZs (by ppm mz deviation)"
    transformFactors = None
    if correctby == "mzDeviationPPM":
        transformFactors = tempMod[(np.abs(tempMod["mzDeviationPPM"]) <= max_deviationPPM_to_use_for_correction)].groupby("sample")["mzDeviationPPM"].median()
        tempMod["mz"] = tempMod["mz"] * (1 - tempMod[(np.abs(tempMod["mzDeviationPPM"]) <= max_deviationPPM_to_use_for_correction)].groupby("sample")["mzDeviationPPM"].transform("median") / 1E6) #* (1. - (temp.groupby("chromID")["mzDeviationPPM"].transform("median")) / 1E6)  ## Error
    elif correctby == "mzDeviation":
        transformFactors = tempMod[(np.abs(tempMod["mzDeviationPPM"]) <= max_deviationPPM_to_use_for_correction)].groupby("sample")["mzDeviation"].median()
        tempMod["mz"] = tempMod["mz"] - tempMod[(np.abs(tempMod["mzDeviationPPM"]) <= max_deviationPPM_to_use_for_correction)].groupby("sample")["mzDeviation"].transform("median")
    else:
        raise RuntimeError("Unknown option for correctby parameter. Must be 'mzDeviation' or 'mzDeviationPPM'")
        
    tempMod["mzDeviationPPM"] = (tempMod["mz"] - tempMod["referenceMZ"]) / tempMod["referenceMZ"] * 1E6
    tempMod["mzDeviation"] = (tempMod["mz"] - tempMod["referenceMZ"])

    for samplei, sample in enumerate(assay.manager.get_sample_names()):
        msDataObj = assay.get_ms_data(sample)
        if issubclass(type(msDataObj), ms.fileio.MSData_in_memory):
            raise RuntimeError("Function correct_MZ_shift_across_samples only works with objects of class ms.fileio.MSData_in_memory. Please switch data_import_mode to ms._constancts.MEMORY")

        if sample not in transformFactors.index:
            print("Error: sample '%s' could not be corrected as no reference MZs were detected in it"%(sample))
            for k, spectrum in msDataObj.get_spectra_iterator():
                spectrum.original_mz = spectrum.mz
        else:
            transformFactor = transformFactors.loc[sample]

            for k, spectrum in msDataObj.get_spectra_iterator():
                spectrum.original_mz = spectrum.mz
                if correctby == "mzDeviationPPM":
                    spectrum.mz = spectrum.mz * (1 - transformFactor / 1E6)
                elif correctby == "mzDeviation":
                    spectrum.mz = spectrum.mz - transformFactor

        if verbose:
            print("    .. Sample %3d / %3d (%45s): correcting by %.1f (%s)"%(samplei, len(assay.manager.get_sample_names()), sample, transformFactor, correctby))

    tempMod["mode"] = "corrected MZs (by %s)"%(correctby)
    temp_ = pd.concat([temp, tempMod], axis = 0, ignore_index = True).reset_index(drop = False)

    p = None
    if plot:
        p = (p9.ggplot(data = temp_[(~(temp_["intensity"].isna())) & (np.abs(temp_["mzDeviationPPM"]) <= 100)], mapping = p9.aes(
                x = "referenceMZ", y = "mzDeviationPPM", group = "chromID", colour = "sample", alpha = "intensity"
            ))
            + p9.geom_hline(yintercept = 0, size = 1, colour = "Black", alpha = 0.25)
            + p9.geom_line()
            + p9.geom_point()
            + p9.facet_wrap("~file + mode", ncol = 6)
            + p9.theme_minimal()
            + p9.theme(legend_position = "bottom")
            + p9.theme(subplots_adjust={'wspace':0.15, 'hspace':0.25, 'top':0.93, 'right':0.99, 'bottom':0.05, 'left':0.05})
            + p9.guides(alpha = False, colour = False)
            + p9.ggtitle("MZ deviation before and after correction for each sample/chronogram file")
        )

    return tempMod, p








    
def crude_cluster_mz_list(sample, mz, intensity, min_difference_ppm):
    """
    Function for a crude clustering of similar mz values in a spot sample

    Args:
        mz (numpy array): All mz values of a spot sample
        intensity (numpy array): All intensity values associated with the mz values in the parameter mz
        min_difference_ppm (float): Minimum difference in PPM required to separate into different clusters
        return_details_object (bool, optional): Indicator if the . Defaults to False.

    Returns:
        np array: Array with cluster IDs for each signal (i.e., mz value and intensity in the parameters mz and intensity)
    """    
    mzOrd = np.argsort(mz)
    mz_ = mz[mzOrd]
    intensity_ = intensity[mzOrd]
    elems = mz.shape[0]
    diffsPPM = (mz_[1:elems] - mz_[0:(elems-1)]) / mz_[0:(elems-1)] * 1E6
    clust = np.concatenate([[0], np.cumsum(diffsPPM > min_difference_ppm)], axis = 0)

    return clust[np.argsort(mzOrd)]

import numba
global refine_clustering
@numba.jit(nopython=True)
def refine_clustering(sample, mzs, intensities, spectrumID, clusts, expected_mz_deviation_ppm = 15, closest_signal_max_deviation_ppm = 15, max_mz_deviation_ppm = None):
    clustInds = np.unique(clusts)
    maxClust = np.max(clusts)
    newClusts = np.copy(clusts)

    #degubPrint_ = True
    
    for i, clust in enumerate(clustInds):
        n = np.sum(clusts == i)

        if n > 1:
            maxClust = maxClust + 1
            pos = clusts == clust
            mzs_ = mzs[pos]
            intensities_ = intensities[pos]
            pos = np.argwhere(pos)
            used = np.zeros((mzs_.shape[0]), dtype = numba.int32)
            usedMZs = np.zeros_like(mzs_)

            #if degubPrint_ and abs(np.mean(mzs_) - 412) < 1: print("\n\nsample", sample)
            #if degubPrint_ and abs(np.mean(mzs_) - 412) < 1: print("starting new cluster")
            #if degubPrint_ and abs(np.mean(mzs_) - 412) < 1: print("mzs_ is", mzs_)
            
            while sum(used == 0) > 0:
                c = np.argmax(intensities_ * (used == 0))
                used[c] = 1
                usedMZs[c] = mzs_[c]
                newClusts[pos[c]] = maxClust + 1
                lastPPMDev = 0
                
                #if degubPrint_ and abs(np.mean(mzs_) - 412) < 1: print("seed mz is", usedMZs[c])
        
                cont = sum(used == 0) > 0
                while cont:
                    tTop = np.abs(mzs_ - np.max(usedMZs[used == 1]) ) + np.abs(used) * 1E6
                    closestTop = np.argmin(tTop)
                    tLow = np.abs(mzs_ - np.min(usedMZs[used == 1]) ) + np.abs(used) * 1E6
                    closestLow = np.argmin(tLow)

                    closest = closestTop if tTop[closestTop] < tLow[closestLow] else closestLow

                    used[closest] = 1
                    usedMZs[closest] = mzs_[closest]
                    newClusts[pos[closest]] = maxClust + 1

                    mzdevRSTD = np.std(usedMZs[used == 1]) / np.mean(usedMZs[used == 1])
                    newPPMDev = (np.max(usedMZs[used == 1]) - np.min(usedMZs[used == 1])) / np.average(usedMZs[used == 1]) * 1E6
                    #if degubPrint_ and abs(np.mean(mzs_) - 412) < 1: print("closest new mz is ", usedMZs[closest], "added ppm deviation", (newPPMDev - lastPPMDev), "min/max are ", np.min(usedMZs[used == 1]), np.max(usedMZs[used == 1]), "RSTD mz", mzdevRSTD)
                    if sum(used == 0) == 0 or (newPPMDev - lastPPMDev) > closest_signal_max_deviation_ppm or (max_mz_deviation_ppm is not None and newPPMDev > max_mz_deviation_ppm):
                        cont = False
        
                        used[closest] = 0
                        usedMZs[closest] = 0
                        newClusts[pos[closest]] = clusts[pos[closest]]
        
                        used = -np.abs(used)
                        usedMZs = usedMZs * 0.
                        maxClust = maxClust + 1
                        #if degubPrint_ and abs(np.mean(mzs_) - 412) < 1: print("closing cluster", sum(used == 0) == 0,  (newPPMDev > 3*lastPPMDev and lastPPMDev > 0 and newPPMDev > expected_mz_deviation_ppm), (max_mz_deviation_ppm is not None and newPPMDev > max_mz_deviation_ppm), "\n")
                    
                    else:
                        lastPPMDev = (np.max(usedMZs[used == 1]) - np.min(usedMZs[used == 1])) / np.average(usedMZs[used == 1]) * 1E6
    
    return newClusts






def reindex_cluster(cluster):
    """
    Function to reindex a cluster if certain cluster IDs have been deleted previously. 
    Clusters will be ascendingly processed by lexiographic sorting resulting in new IDs for any cluster that has an ID higher than a deleted cluster ID

    For example:
    cluster = [0,0,0,1,2,4,4,4,5,6]
    The cluster 3 has been deleted, therefore the cluster IDs 4,5, and 6 will be shifted by -1 each resulting in the new clusters
    returns: [0,0,0,1,2,3,3,3,4,5]

    Note
    Even negative cluster IDs (-1) will be reindexed

    Args:
        cluster (numpy array): Cluster IDs for any clustering

    Returns:
        numpy array: The new cluster IDs for each cluster
    """    
    newClust = np.zeros(cluster.shape[0], dtype = int)

    clustInds, ns = np.unique(cluster, return_counts = True)

    use = 0
    for i, clustInd in enumerate(clustInds):
        #print(clustInd, ns[i], np.sum(cluster == clustInd), "--->", use) 
        newClust[cluster == clustInd] = use
        use += 1

    return newClust

## TODO implement fine clustering after crude one

def describe_MZ_cluster(mz, intensity, clust):
    """
    Function to calculate summary information about each mz cluster

    Args:
        mz (numpy array): The mz values of each signal
        intensity (numpy array): The intensity values of each signal
        clust (numpy array): The cluster IDs of each signal

    Returns:
        numpy matrix: Each row in the matrix corresponds to one clusters in the clusterd signal space. The columns of the matrix indicate the cluster IDs, the number of signals, the minimum, average and maximum MZ values, the MZ deviation and the sum of the intensities of the respective signals.
    """    
    mzOrd = np.argsort(mz)

    uniqClusts, ns = np.unique(clust, return_counts = True)
    mzDesc = np.zeros([uniqClusts.shape[0], 7])  ## clusterID = rowInd:   0: clusterID   1: Ns   2: Min.MZ   3: Avg.MZ   4: Max.MZ   5: MZ.Dev   6: sum.Int.
    mzDesc[:,2] = np.Inf
    for i in range(mz.shape[0]):
        j = clust[i]
        mzDesc[j,0] = j
        mzDesc[j,1] = mzDesc[j,1] + 1
        mzDesc[j,2] = np.minimum(mz[i], mzDesc[j,2])
        mzDesc[j,3] = mzDesc[j,3] + mz[i]
        mzDesc[j,4] = np.maximum(mz[i], mzDesc[j,4])
        mzDesc[j,6] =mzDesc[j,6] + intensity[i]
    
    mzDesc[:,3] = mzDesc[:,3] / mzDesc[:,1]
    mzDesc[:,5] = (mzDesc[:,4] - mzDesc[:,2]) / mzDesc[:,3] * 1E6
    return mzDesc
    

def collapse_mz_info(mz, intensity, cluster, intensity_collapse_method = "sum"):
    clusts, ns = np.unique(cluster, return_counts = True)
    if -1 in clusts:
        clusts = clusts[1:]
        ns = ns[1:]
    
    mz_ = np.zeros(clusts.shape[0])
    intensity_ = np.zeros(clusts.shape[0])

    for i in range(mz.shape[0]):
        j = cluster[i]
        if j >= 0:
            mz_[j] += mz[i] * intensity[i]
            intensity_[j] += intensity[i]
    
    mz_ = mz_ / intensity_
    if intensity_collapse_method == "sum":
        pass
    elif intensity_collapse_method == "average":
        intensity_ = intensity_ / ns
    elif intensity_collapse_method == "max":
        intensity_ = np.max(intensity_)
    else:
        raise RuntimeError("Unknown option for parameter intensity_collapse_method, allowed are 'sum' and 'average'")

    ord = np.argsort(mz_)
    return mz_[ord], intensity_[ord]


def cluster_quality_check_function__peak_form(sample, msDataObj, spectrumIDs, time, mz, intensity, cluster, min_correlation_for_cutoff = 0.5):
    removed = 0
    clustInds = np.unique(cluster)
    refTimes = []
    for i, spectrum in msDataObj.get_spectra_iterator():
        refTimes.append(spectrum.time)
    refTimes = np.array(refTimes)
    refEIC = scipy.stats.norm.pdf(refTimes, loc = np.mean(refTimes), scale = (np.max(refTimes) - np.min(refTimes)) / 6)
    corrs = []

    for clusti, clustID in enumerate(clustInds):
        if clustID >= 0:
            mzs = mz[cluster == clustID]
            if mzs.shape[0] > 0:
                ints = intensity[cluster == clustID]
                times = time[cluster == clustID]

                eic = np.zeros_like(refTimes)
                for i in range(ints.shape[0]):
                    eic[np.argwhere(times[i] == refTimes)] += ints[i]

                corr = np.corrcoef(refEIC, eic)[1,0]
                corrs.append(corr)

                if corr < min_correlation_for_cutoff:
                    cluster[cluster == clustID] = -1
                    removed = removed + 1

    #print("'%s' correlation filter, removed %d features"%(sample, removed))
    
    if False:
        temp = pd.DataFrame({"correlations": corrs})
        p = (p9.ggplot(data = temp, mapping = p9.aes(x = "correlations"))
            + p9.geom_histogram(binwidth = 0.1)
            + p9.geom_vline(xintercept = min_correlation_for_cutoff)
            + p9.ggtitle("correlations in sample '%s' removed %d corrs %d"%(sample, removed, len(corrs)))
        )
        print(p)
    
    return cluster


def cluster_quality_check_function__ppmDeviationCheck(sample, msDataObj, spectrumIDs, time, mz, intensity, cluster, max_weighted_ppm_deviation = 15):
    removed = 0
    clustInds = np.unique(cluster)

    for clusti, clustID in enumerate(clustInds):
        if clustID >= 0:
            mzs = mz[cluster == clustID]
            if mzs.shape[0] > 0:
                ints = intensity[cluster == clustID]

                mmzW = np.average(mzs, weights = intensity[cluster == clustID])
                ppmsW = (mzs - mmzW) / mmzW * 1E6
                stdppmW = np.sqrt(np.cov(ppmsW, aweights = ints))

                if stdppmW > max_weighted_ppm_deviation:
                    cluster[cluster == clustID] = -1
                    removed = removed + 1

    #print("'%s' ppmDeviationCheck filter filter, removed %d features"%(sample, removed))

    return cluster

def calculate_concensus_spectra_per_sample(assay, min_difference_ppm = 30, min_signals_per_cluster = 10, cluster_quality_check_functions = None, aggregation_function = "sum", exportAsFeatureML = True, featureMLlocation = ".", verbose = True):
    """
    Function to collapse several spectra into a single concensus spectrum per spot

    Args:
        assay (Assay): The assay of the experiment
        min_difference_ppm (float, optional): Minimum difference in PPM required to separate into different clusters. Defaults to 30.
        min_signals_per_cluster (int, optional): Minimum number of signals for a certain MZ cluster for it to be used in the collapsed spectrum. Defaults to 10.
    """    

    if cluster_quality_check_functions is None:
        cluster_quality_check_functions = []

    for samplei, sample in enumerate(assay.manager.get_sample_names()):
        temp = {
            "sample": [],
            "spectrumInd": [],
            "time": [],
            "mz": [],
            "intensity": []
        }
        msDataObj = assay.get_ms_data(sample)
        summary_totalSpectra = 0
        for k, spectrum in msDataObj.get_spectra_iterator():
            temp["sample"].extend((sample for i in range(spectrum.mz.shape[0])))
            temp["spectrumInd"].extend((k for i in range(spectrum.mz.shape[0])))
            temp["time"].extend((spectrum.time for i in range(spectrum.mz.shape[0])))
            temp["mz"].append(spectrum.mz)
            temp["intensity"].append(spectrum.spint)
            summary_totalSpectra += 1
        
        temp["sample"] = np.array(temp["sample"])
        temp["spectrumInd"] = np.array(temp["spectrumInd"])
        temp["time"] = np.array(temp["time"])
        temp["mz"] = np.concatenate(temp["mz"], axis = 0)
        temp["intensity"] = np.concatenate(temp["intensity"], axis = 0)
        summary_totalSignals = len(temp["mz"])

        temp["cluster"] = ms.dartms.crude_cluster_mz_list(sample, temp["mz"], temp["intensity"], min_difference_ppm = min_difference_ppm)
        summary_clusterAfterCrude = np.unique(temp["cluster"]).shape[0]
        
        ## remove any cluster with less than min_signals_per_cluster signals
        clustInds, ns = np.unique(temp["cluster"], return_counts = True)
        clustNs = ns[temp["cluster"]]
        temp["cluster"][clustNs < min_signals_per_cluster] = -1
        
        keep = temp["cluster"] >= 0
        temp["sample"] = temp["sample"][keep]
        temp["spectrumInd"] = temp["spectrumInd"][keep]
        temp["time"] = temp["time"][keep]
        temp["mz"] = temp["mz"][keep]
        temp["intensity"] = temp["intensity"][keep]
        temp["cluster"] = reindex_cluster(temp["cluster"][keep])

        ## refine cluster
        temp["cluster"] = ms.dartms.refine_clustering(sample, temp["mz"], temp["intensity"], temp["spectrumInd"], temp["cluster"])
        temp["cluster"] = reindex_cluster(temp["cluster"])
        summary_clusterAfterFine = np.unique(temp["cluster"]).shape[0]
    
        ## remove any cluster with less than min_signals_per_cluster signals
        clustInds, ns = np.unique(temp["cluster"], return_counts = True)
        clustNs = ns[temp["cluster"]]
        temp["cluster"][clustNs < min_signals_per_cluster] = -1
        for cluster_quality_check_function in cluster_quality_check_functions:
            temp["cluster"] = cluster_quality_check_function(sample, msDataObj, temp["spectrumInd"], temp["time"], temp["mz"], temp["intensity"], temp["cluster"])
        summary_clusterAfterQualityFunctions = np.unique(temp["cluster"]).shape[0]

        keep = temp["cluster"] >= 0
        temp["sample"] = temp["sample"][keep]
        temp["spectrumInd"] = temp["spectrumInd"][keep]
        temp["time"] = temp["time"][keep]
        temp["mz"] = temp["mz"][keep]
        temp["intensity"] = temp["intensity"][keep]
        temp["cluster"] = reindex_cluster(temp["cluster"][keep])

        if exportAsFeatureML:
            with open(os.path.join(featureMLlocation, "%s.featureML"%(sample)).replace(":", "_"), "w") as fout:
                minRT = np.min(temp["time"])
                maxRT = np.max(temp["time"])

                ns = np.unique(temp["cluster"])

                fout.write('<?xml version="1.0" encoding="ISO-8859-1"?>\n')
                fout.write('  <featureMap version="1.4" id="fm_16311276685788915066" xsi:noNamespaceSchemaLocation="http://open-ms.sourceforge.net/schemas/FeatureXML_1_4.xsd" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">\n')
                fout.write('    <dataProcessing completion_time="%s">\n'%datetime.datetime.now().strftime("%m/%d/%Y, %H:%M:%S"))
                fout.write('      <software name="tidyms" version="%s" />\n'%(ms.__version__))
                fout.write('      <software name="tidyms.dartms.calculate_concensus_spectra_per_sample" version="%s" />\n'%(ms.__version__))
                fout.write('    </dataProcessing>\n')
                fout.write('    <featureList count="%d">\n'%(ns.shape[0]))

                for j in range(ns.shape[0]):
                    clust = ns[j]
                    mzs = np.copy(temp["mz"][temp["cluster"] == clust])
                    ints = np.copy(temp["intensity"][temp["cluster"] == clust])
                    fout.write('<feature id="%s">\n'%j)
                    fout.write('  <position dim="0">%f</position>\n'%((maxRT + minRT) / 2))
                    fout.write('  <position dim="1">%f</position>\n'%np.average(mzs, weights = ints))
                    fout.write('  <intensity>%f</intensity>\n'%np.sum(temp["intensity"][temp["cluster"] == clust]))
                    fout.write('  <quality dim="0">0</quality>\n')
                    fout.write('  <quality dim="1">0</quality>\n')
                    fout.write('  <overallquality>0</overallquality>\n')
                    fout.write('  <charge>1</charge>\n')
                    fout.write('  <convexhull nr="0">\n')
                    fout.write('    <pt x="%f" y="%f" />\n'%(minRT, np.min(mzs)))
                    fout.write('    <pt x="%f" y="%f" />\n'%(minRT, np.max(mzs)))
                    fout.write('    <pt x="%f" y="%f" />\n'%(maxRT, np.max(mzs)))
                    fout.write('    <pt x="%f" y="%f" />\n'%(maxRT, np.min(mzs)))
                    fout.write('  </convexhull>\n')
                    fout.write('</feature>\n')

                fout.write('    </featureList>\n')
                fout.write('  </featureMap>\n')

        if verbose:
            print("   .. Sample %4d / %4d (%45s): spectra %3d, signals %6d, cluster after crude %6d, fine %6d, quality control %6d, final number of features %6d"%(samplei, len(assay.manager.get_sample_names()), sample, summary_totalSpectra, summary_totalSignals, summary_clusterAfterCrude, summary_clusterAfterFine, summary_clusterAfterQualityFunctions, np.unique(temp["cluster"]).shape[0]))

        mzs, intensities = ms.dartms.collapse_mz_info(temp["mz"], temp["intensity"], temp["cluster"], intensity_collapse_method = aggregation_function)
        
        sampleObjNew = ms.fileio.MSData_in_memory.generate_from_MSData_object(msDataObj)
        startRT = sampleObjNew.get_spectrum(0).time
        endRT = sampleObjNew.get_spectrum(sampleObjNew.get_n_spectra() - 1).time
        sampleObjNew.delete_spectra(ns = [i for i in range(1, msDataObj.get_n_spectra())])
        spectrum = sampleObjNew.get_spectrum(0)
        spectrum.mz = mzs
        spectrum.spint = intensities
        spectrum.startRT = startRT
        spectrum.endRT = endRT
        msDataObj.to_MSData_object = sampleObjNew




















def write_concensus_spectrum_to_featureML(assay, widthRT = 40):
    for samplei, sample in tqdm.tqdm(enumerate(assay.manager.get_sample_names()), total = len(assay.manager.get_sample_names())):

        with open(os.path.join(".", "%s.featureML"%(sample)).replace(":", "_"), "w") as fout:
            msDataObj = assay.get_ms_data(sample)
            spectra = []
            for k, spectrum in msDataObj.get_spectra_iterator():
                spectra.append(spectrum)
            assert len(spectra) == 1

            spectrum = spectra[0]

            fout.write('<?xml version="1.0" encoding="ISO-8859-1"?>\n')
            fout.write('  <featureMap version="1.4" id="fm_16311276685788915066" xsi:noNamespaceSchemaLocation="http://open-ms.sourceforge.net/schemas/FeatureXML_1_4.xsd" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">\n')
            fout.write('    <dataProcessing completion_time="%s">\n'%datetime.datetime.now().strftime("%m/%d/%Y, %H:%M:%S"))
            fout.write('      <software name="PeakBot" version="4.6" />\n')
            fout.write('    </dataProcessing>\n')
            fout.write('    <featureList count="%d">\n'%(spectrum.mz.shape[0]))

            for j in range(spectrum.mz.shape[0]):
                fout.write('<feature id="%s">\n'%j)
                fout.write('  <position dim="0">%f</position>\n'%(spectrum.time + widthRT / 2))
                fout.write('  <position dim="1">%f</position>\n'%spectrum.mz[j])
                fout.write('  <intensity>%f</intensity>\n'%spectrum.spint[j])
                fout.write('  <quality dim="0">0</quality>\n')
                fout.write('  <quality dim="1">0</quality>\n')
                fout.write('  <overallquality>0</overallquality>\n')
                fout.write('  <charge>1</charge>\n')
                fout.write('  <convexhull nr="0">\n')
                fout.write('    <pt x="%f" y="%f" />\n'%(spectrum.time          , spectrum.mz[j]))
                fout.write('    <pt x="%f" y="%f" />\n'%(spectrum.time + widthRT, spectrum.mz[j]))
                fout.write('  </convexhull>\n')
                fout.write('</feature>\n')

            fout.write('    </featureList>\n')
            fout.write('  </featureMap>\n')



def print_sample_overview(assay):
    temp = {
        "sample": [],
        "spectra": [],
        "mzs": [],
    }

    for samplei, sample in enumerate(assay.manager.get_sample_names()):
        msDataObj = assay.get_ms_data(sample)

        temp["sample"].append(sample)
        temp["spectra"].append(msDataObj.get_n_spectra())
        temp["mzs"].append(sum((spectrum.mz.shape[0] for k, spectrum in msDataObj.get_spectra_iterator())))

    temp = pd.DataFrame(temp)
    with pd.option_context('display.max_rows', None, 'display.max_columns', None):  # more options can be specified also
        print(temp)








def bracket_samples(assay, max_ppm_deviation = 25, show_diagnostic_plots = False):
    temp = {
        "sample": [],
        "sampleType": [],
        "mz": [],
        "original_mz": [],
        "startRT": [],
        "endRT": [],
        "intensity": [],
        "cluster": [],
    }
    tempClusterInfo = {
        "cluster": [],
        "meanMZ": [],
        "minMZ": [],
        "maxMZ": [],
        "mzDevPPM": [],
        "assignedSamples": [],
        "uniqueSamples": [],
        "featureMLInfo": []
    }
    
    sample_metadata = assay.manager.get_sample_metadata()
    for samplei, sample in tqdm.tqdm(enumerate(assay.manager.get_sample_names()), total = len(assay.manager.get_sample_names())):
        msDataObj = assay.get_ms_data(sample)
        sampleType = sample_metadata.loc[sample, "group"]
        for k, spectrum in msDataObj.get_spectra_iterator():
            temp["sample"].extend((sample for i in range(spectrum.mz.shape[0])))
            temp["sampleType"].extend((sampleType for i in range(spectrum.mz.shape[0])))
            temp["mz"].extend((mz for mz in spectrum.mz))
            temp["original_mz"].extend((mz for mz in spectrum.original_mz))
            temp["startRT"].extend((spectrum.startRT for mz in spectrum.mz))
            temp["endRT"].extend((spectrum.endRT for mz in spectrum.mz))
            temp["intensity"].extend((np.log10(inte) for inte in spectrum.spint))
            temp["cluster"].extend((0 for inte in spectrum.spint))
    
    cclust = 1
    temp["sample"] = np.array(temp["sample"])
    temp["sampleType"] = np.array(temp["sampleType"])
    temp["mz"] = np.array(temp["mz"])
    temp["original_mz"] = np.array(temp["original_mz"])
    temp["startRT"] = np.array(temp["startRT"])
    temp["endRT"] = np.array(temp["endRT"])
    temp["intensity"] = np.array(temp["intensity"])
    temp["cluster"] = np.array(temp["cluster"])

    while np.sum(temp["cluster"] == 0) > 0:
        c = np.argmax(temp["intensity"] * (temp["cluster"] == 0))
        cmz = temp["mz"][c]

        assign = np.where(np.abs(temp["mz"] - cmz) / temp["mz"] * 1E6 <= max_ppm_deviation)
        temp["cluster"][assign] = cclust

        tempClusterInfo["cluster"].append(cclust)
        mzs = temp["mz"][assign]
        tempClusterInfo["meanMZ"].append(np.mean(mzs))
        tempClusterInfo["minMZ"].append(np.min(mzs))
        tempClusterInfo["maxMZ"].append(np.max(mzs))
        tempClusterInfo["mzDevPPM"].append((np.max(mzs) - np.min(mzs)) / np.mean(mzs) * 1E6)
        tempClusterInfo["assignedSamples"].append(assign[0].size)
        tempClusterInfo["uniqueSamples"].append(np.unique(temp["sample"][assign]).shape[0])
        tempClusterInfo["featureMLInfo"].append({})

        cclust = cclust + 1

    
    ns = len(tempClusterInfo["cluster"])
    for j in range(ns):
        clust = tempClusterInfo["cluster"][j]
        tempClusterInfo["featureMLInfo"][j]["overallquality"] = tempClusterInfo["assignedSamples"][j]
        tempClusterInfo["featureMLInfo"][j]["meanMZ"] = tempClusterInfo["meanMZ"][j]
        tempClusterInfo["featureMLInfo"][j]["mzDevPPM"] = tempClusterInfo["mzDevPPM"][j]

        omzs = temp["original_mz"][temp["cluster"] == clust]
        startRTs = temp["startRT"][temp["cluster"] == clust]
        endRTs   = temp["endRT"  ][temp["cluster"] == clust]
        samples  = temp["sample" ][temp["cluster"] == clust]

        tempClusterInfo["featureMLInfo"][j]["sampleHulls"] = {}
        for samplei, sample in enumerate(assay.manager.get_sample_names()):
            use = samples == sample
            if np.sum(use) > 0:
                domzs = omzs[use]
                startRT = startRTs[use][0]
                endRT = endRTs[use][0]
                tempClusterInfo["featureMLInfo"][j]["sampleHulls"][sample] = [(startRT, np.min(domzs)), (startRT, np.max(domzs)), (endRT, np.max(domzs)), (endRT, np.min(domzs))]
    
    if show_diagnostic_plots:
        temp = pd.DataFrame(temp)
        p = (p9.ggplot(data = temp, mapping = p9.aes(x = "sample", y = "mz", group = "cluster", colour = "cluster", symbol = "sampleType", alpha = "intensity"))
            + p9.geom_point()
            + p9.geom_line()
            #+ p9.facet_wrap("~sample")
            #+ p9.theme(subplots_adjust={'wspace':0.15, 'hspace':0.25, 'top':0.93, 'right':0.99, 'bottom':0.05, 'left':0.15})
            + p9.theme_minimal()
            + p9.ggtitle("All samples")
            + p9.theme(axis_text_x = p9.element_text(angle = 45, hjust = 1))
            + p9.theme(legend_position = "bottom")
            )
        print(p)

        temp = pd.DataFrame(tempClusterInfo)
        p = (p9.ggplot(data = temp, mapping = p9.aes(x = "assignedSamples", y = "mzDevPPM"))
            + p9.geom_point(alpha = 0.2)
            #+ p9.facet_wrap("~sample")
            #+ p9.theme(subplots_adjust={'wspace':0.15, 'hspace':0.25, 'top':0.93, 'right':0.99, 'bottom':0.05, 'left':0.15})
            + p9.theme_minimal()
            + p9.ggtitle("All samples")
            + p9.theme(axis_text_x = p9.element_text(angle = 45, hjust = 1))
            + p9.theme(legend_position = "bottom")
            )
        print(p)

        p = (p9.ggplot(data = temp, mapping = p9.aes(x = "assignedSamples", y = "uniqueSamples"))
            + p9.geom_point(alpha = 0.2)
            #+ p9.facet_wrap("~sample")
            #+ p9.theme(subplots_adjust={'wspace':0.15, 'hspace':0.25, 'top':0.93, 'right':0.99, 'bottom':0.05, 'left':0.15})
            + p9.theme_minimal()
            + p9.ggtitle("All samples")
            + p9.theme(axis_text_x = p9.element_text(angle = 45, hjust = 1))
            + p9.theme(legend_position = "bottom")
            )
        print(p)

    return [e for e in zip(tempClusterInfo["minMZ"], tempClusterInfo["meanMZ"], tempClusterInfo["maxMZ"], tempClusterInfo["featureMLInfo"])]


def write_brac_results_to_featureML(bracRes, featureMLlocation = "./bracketedResults.featureML", featureMLStartRT = 0, featureMLEndRT = 1400):
    with open(featureMLlocation, "w") as fout:
        
        bracRes = [b[3] for b in bracRes]
        ns = len(bracRes)
        fout.write('<?xml version="1.0" encoding="ISO-8859-1"?>\n')
        fout.write('  <featureMap version="1.4" id="fm_16311276685788915066" xsi:noNamespaceSchemaLocation="http://open-ms.sourceforge.net/schemas/FeatureXML_1_4.xsd" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">\n')
        fout.write('    <dataProcessing completion_time="%s">\n'%datetime.datetime.now().strftime("%m/%d/%Y, %H:%M:%S"))
        fout.write('      <software name="tidyms" version="%s" />\n'%(ms.__version__))
        fout.write('      <software name="tidyms.bracket_samples" version="%s" />\n'%(ms.__version__))
        fout.write('    </dataProcessing>\n')
        fout.write('    <featureList count="%d">\n'%(ns))

        for j in tqdm.tqdm(range(ns)):

            fout.write('<feature id="%s">\n'%j)
            fout.write('  <position dim="0">%f</position>\n'%((featureMLStartRT + featureMLEndRT) / 2))
            fout.write('  <position dim="1">%f</position>\n'%(bracRes[j]["meanMZ"]))
            fout.write('  <intensity>1</intensity>\n')
            fout.write('  <quality dim="0">0</quality>\n')
            fout.write('  <quality dim="1">0</quality>\n')
            fout.write('  <overallquality>%d</overallquality>\n'%(bracRes[j]["overallquality"]))
            fout.write('  <charge>1</charge>\n')
            fout.write('  <convexhull nr="0">\n')
            fout.write('    <pt x="%f" y="%f" />\n'%(featureMLStartRT, bracRes[j]["meanMZ"] * (1. - bracRes[j]["mzDevPPM"] / 1E6)))
            fout.write('    <pt x="%f" y="%f" />\n'%(featureMLStartRT, bracRes[j]["meanMZ"] * (1. + bracRes[j]["mzDevPPM"] / 1E6)))
            fout.write('    <pt x="%f" y="%f" />\n'%(featureMLEndRT  , bracRes[j]["meanMZ"] * (1. + bracRes[j]["mzDevPPM"] / 1E6)))
            fout.write('    <pt x="%f" y="%f" />\n'%(featureMLEndRT  , bracRes[j]["meanMZ"] * (1. - bracRes[j]["mzDevPPM"] / 1E6)))
            fout.write('  </convexhull>\n')

            for samplei, sample in enumerate(bracRes[j]["sampleHulls"]):
                fout.write('  <convexhull nr="%d">\n'%(samplei))
                fout.write('    <pt x="%f" y="%f" />\n'%(bracRes[j]["sampleHulls"][sample][0][0], bracRes[j]["sampleHulls"][sample][0][1]))
                fout.write('    <pt x="%f" y="%f" />\n'%(bracRes[j]["sampleHulls"][sample][1][0], bracRes[j]["sampleHulls"][sample][1][1]))
                fout.write('    <pt x="%f" y="%f" />\n'%(bracRes[j]["sampleHulls"][sample][2][0], bracRes[j]["sampleHulls"][sample][2][1]))
                fout.write('    <pt x="%f" y="%f" />\n'%(bracRes[j]["sampleHulls"][sample][3][0], bracRes[j]["sampleHulls"][sample][3][1]))
                fout.write('  </convexhull>\n')

            fout.write('</feature>\n')

        fout.write('    </featureList>\n')
        fout.write('  </featureMap>\n')


    

## Generate data matrix from bracketing information
def build_data_matrix(assay, bracketing_results):
    sampleNames = assay.manager.get_sample_names()
    sampleNamesToRowI = dict(((sample, i) for i, sample in enumerate(sampleNames)))
    dataMatrix = np.zeros((len(sampleNames), len(bracketing_results)))
    for samplei, sample in tqdm.tqdm(enumerate(sampleNames), total = len(sampleNames)):
        msDataObj = assay.get_ms_data(sample)
        spectrum = msDataObj.get_spectrum(0)
        for braci, (mzmin, meanmz, mzmax, _) in enumerate(bracketing_results):
            use = np.logical_and(spectrum.mz >= mzmin, spectrum.mz <= mzmax)
            if np.sum(use) > 0:
                s = np.sum(spectrum.spint[use])
                dataMatrix[sampleNamesToRowI[sample], braci] = s
            else:
                dataMatrix[sampleNamesToRowI[sample], braci] = np.nan
    
    return sampleNames, bracketing_results, dataMatrix



def blank_subtraction(dat, features, groups, blankGroup, toTestGroups, foldCutoff = 2, pvalueCutoff = 0.05, minDetected = 2, plot = False, verbose = True):

    keeps = [0 for i in range(dat.shape[1])]

    folds = []
    pvals = []
    sigInds = []
    comparisons = []

    debugPrint = False

    for featurei in range(dat.shape[1]):
        blankInds = [i for i, group in enumerate(groups) if group == blankGroup]
        valsBlanks = dat[blankInds, featurei]
        notInBlanks = False

        
        if debugPrint and abs(features[featurei][1] - 872.8) <= 1:
            print(features[featurei][1])
            print("blanks are", valsBlanks)

        if np.sum(~np.isnan(dat[:,featurei])) < minDetected:
            continue

        if np.all(np.isnan(valsBlanks)):
            notInBlanks = True

        valsBlanks = valsBlanks[~np.isnan(valsBlanks)]

        if debugPrint and abs(features[featurei][1] - 872.8) <= 1:
            print("blanks are", valsBlanks)
            print("notInBlanks", notInBlanks)

        for toTestGroup in toTestGroups:
            toTestInds = [i for i, group in enumerate(groups) if group == toTestGroup]
            valsGroup = dat[toTestInds, featurei]

            if np.sum(~np.isnan(valsGroup)) < minDetected:
                if debugPrint and abs(features[featurei][1] - 872.8) <= 1: print("1")
                pass

            elif notInBlanks:
                if debugPrint and abs(features[featurei][1] - 872.8) <= 1: print(2)
                pval = -np.inf
                fold = np.inf

                pvals.append(pval)
                folds.append(fold)
                sigInds.append("only in group")
                comparisons.append("'%s' vs '%s'"%(toTestGroup, blankGroup))

                assert keeps[featurei] <= 0
                keeps[featurei] -= 1

            else:
                if debugPrint and abs(features[featurei][1] - 872.8) <= 1: print(3)
                valsGroup = valsGroup[~np.isnan(valsGroup)]
                pval = scipy.stats.ttest_ind(valsBlanks, valsGroup, equal_var = False, alternative = 'two-sided', trim = 0)[1]
                fold = np.mean(valsGroup) / np.mean(valsBlanks)
                sigInd = pval <= pvalueCutoff and fold >= foldCutoff

                assert keeps[featurei] >= 0
                if sigInd:
                    keeps[featurei] += 1

                pvals.append(-np.log10(pval))
                folds.append(np.log2(fold))
                sigInds.append("group >> blank" if sigInd else "-")
                comparisons.append("'%s' vs '%s'"%(toTestGroup, blankGroup))

            if debugPrint and abs(features[featurei][1] - 872.8) <= 1:
                print("    ", notInBlanks, valsBlanks, valsGroup, pval, fold, sigInd, toTestGroup, keeps[featurei])
        if debugPrint and abs(features[featurei][1] - 872.8) <= 1:
            print("decision is", keeps[featurei])
            print("")


    if plot:
        folds = np.array(folds)
        pvals = np.array(pvals)
        temp = {"pvalues": pvals, "folds": folds, "sigIndicators": sigInds, "comparison": comparisons}
        temp = pd.DataFrame(temp)
        p = (p9.ggplot(data = temp, mapping = p9.aes(
                x = "folds", y = "pvalues", colour = "sigIndicators"
            ))
            + p9.geom_point(alpha = 0.8)
            + p9.geom_hline(yintercept = -np.log10(0.05), alpha = 0.3, colour = "black")
            + p9.geom_vline(xintercept = [np.log2(foldCutoff), np.log2(1/foldCutoff)], alpha = 0.3, colour = "black")
            + p9.facet_wrap("~comparison")
            + p9.theme_minimal()
            #+ p9.theme(legend_position = "bottom")
            #+ p9.theme(subplots_adjust={'wspace':0.15, 'hspace':0.25, 'top':0.93, 'right':0.99, 'bottom':0.15, 'left':0.15})
            + p9.ggtitle("Blank subtraction volcano plots\n%d features in blanks and samples; %d not in blanks (not illustrated)"%(np.sum(np.array(keeps) > 0), np.sum(np.array(keeps) < 0)))
        )
        print(p)

    if verbose:
        for i in sorted(list(set(keeps))):
            if i < 0: 
                print("   .. %d features not found in any of the blank samples, but at least in %d samples of %d groups and thus these features will be used"%(sum([k == i for k in keeps]), minDetected, -i))
            elif i == 0:
                print("   .. %d features found in None of the blank comparisons with higher abundances in the samples. These features will be removed"%(sum([k == i for k in keeps])))
            else:
                print("   .. %d features found in %d of the blank comparisons with higher abundances in the samples and in at least %d samples. These features will be used"%(sum([k == i for k in keeps]), i, minDetected))
        print("Significance criteria are pval <= pvalueCutoff (%.3f) and fold >= foldCutoff (%.1f) and detected in at least %d samples of a non-Blank group"%(pvalueCutoff, foldCutoff, minDetected))
    
    return [k != 0 for k in keeps]















    
def find_feature(features, mz, max_deviation_ppm = 20):
    mzmax = mz * (1. + max_deviation_ppm / 1E6)
    mzmin = mz * (1. - max_deviation_ppm / 1E6)
    ind = np.argmin(np.abs(features[:,1] - mz))
    if features[ind,1] >= mzmin and features[ind,1] <= mzmax:
        return ind
    else:
        return None 

def calculate_mz_deviationPPM(a, b):
    return (a - b) / b * 1E6

def annotate_features(dat, features, samples, plot = False):
    features_ = np.array(features)
    order = np.argsort(features_[:,1])
    features_ = features_[order,:]
    dat_ = dat[:, order]

    annotations = ["" for i in range(features_.shape[0])]

    cns = []
    deviations = []
    mzs = []
    intensitiesMean = []
    ratiosMean = []
    ratiosSTD = []
    ratiosCount = []

    searchIons = {"+Na": 22.989218 - 1.007276, "+NH4": 18.033823 - 1.007276, "+CH3OH+H": 33.033489 - 1.007276}#, "arbi1": 0.5, "arbi2": 0.75, "arbi3": 0.9, "arbi4": 1.04, "arbi5": 1.1}
    for cn in range(1, 5):
        searchIons["[13C%d]"%cn] = 1.00335484 * cn

    for featurei in range(features_.shape[0]):
        mz = features_[featurei, 1]

        intensities = []
        for samplei, sample in enumerate(samples):
            if not np.isnan(dat_[samplei, featurei]):
                intensities.append(dat_[samplei, featurei]) 
        intensities = np.array(intensities)

        for searchIon in searchIons:

            searchMZ = mz + searchIons[searchIon]
            inds = find_feature(features_, searchMZ, max_deviation_ppm = 100)
            if inds is not None:
                if intensities.shape[0] > 0:
                    intensitiesMean.append(np.mean(intensities))
                else:
                    intensitiesMean.append(0)
                
                deviationPPM = calculate_mz_deviationPPM(features_[inds,1], searchMZ)
                mzs.append(mz)
                cns.append("%s (%.4f)"%(searchIon, searchIons[searchIon]))
                deviations.append(deviationPPM)
                ratios = []
                for samplei, sample in enumerate(samples):
                    ratio = dat_[samplei, inds] / dat_[samplei, featurei] * 100.
                    if not np.isnan(ratio):
                        ratios.append(ratio)
                ratios = np.array(ratios)
                if ratios.shape[0] > 0:
                    ratiosMean.append(np.mean(ratios))
                    ratiosSTD.append(np.std(ratios))
                    ratiosCount.append(ratios.shape[0])
                else:
                    ratiosMean.append(0)
                    ratiosSTD.append(0)
                    ratiosCount.append(ratios.shape[0])

                if ratios.shape[0] > 10 and np.mean(ratios) > 2. and np.mean(ratios) < 200. and np.std(ratios) < 50.:
                    annotations[inds] = searchIon if annotations[inds] == "" else annotations[inds] + ";" + searchIon

    if plot: 
        temp = {"MZs": mzs, "searchIon": cns, "deviations": deviations, "ratiosMean": np.log10(np.array(ratiosMean)), "ratiosSTD": np.log10(np.array(ratiosSTD)), "ratiosCount": ratiosCount, "intensityMeans": np.log10(np.array(intensitiesMean))}
        temp = pd.DataFrame(temp)
        temp['searchIon'] = temp['searchIon'].astype(object)
        p = (p9.ggplot(data = temp, mapping = p9.aes(
                x = "MZs", y = "deviations", colour = "searchIon"
            ))
            + p9.geom_point(alpha = 0.05)
            + p9.facet_wrap("~searchIon")
            + p9.theme_minimal()
            + p9.theme(legend_position = "bottom")
            + p9.theme(subplots_adjust={'wspace':0.15, 'hspace':0.25, 'top':0.93, 'right':0.99, 'bottom':0.15, 'left':0.15})
            + p9.ggtitle("Distribution of mz deviation of sister ions")
        )
        print(p)
        p = (p9.ggplot(data = temp, mapping = p9.aes(
                x = "ratiosMean", y = "ratiosSTD", colour = "ratiosCount"
            ))
            + p9.geom_point(alpha = 0.05)
            + p9.facet_wrap("~ratiosCount")
            + p9.theme_minimal()
            + p9.theme(legend_position = "bottom")
            + p9.theme(subplots_adjust={'wspace':0.15, 'hspace':0.25, 'top':0.93, 'right':0.99, 'bottom':0.15, 'left':0.15})
            + p9.ggtitle("Distribution of mz deviation of sister ions")
        )
        print(p)

    return ["; ".join(sorted(set(annotations[i].split(";")))) for i in np.argsort(order)]

















def print_results_overview(dat, groups):
    print("There are %d features (columns) and %d samples (rows) in the dataset"%(dat.shape[1], dat.shape[0]))
    print("   .. %d (%.1f%%) features have at least one missing value (np.nan)"%(np.sum(np.isnan(dat).any(axis = 0)), np.sum(np.isnan(dat).any(axis = 0)) / dat.shape[1] * 100))
    maxGroupSize = 0
    print("Groups are")
    for grp in set(groups):
        temp = sum((group == grp for group in groups))
        print("   .. '%s' with %d samples"%(grp, temp))
        maxGroupSize = max(maxGroupSize, temp)
    a = {}
    for grp in set(groups):
        groupInd = [i for i, group in enumerate(groups) if group == grp]
        a[grp] = [0 for i in range(maxGroupSize + 1)]
        for featurei in range(dat.shape[1]):
            vals = dat[groupInd, featurei]
            f = np.sum(~np.isnan(vals))
            a[grp][f] += 1
    print("Overview of detections in replicates")
    print("%30s         Detected in x samples"%(""))
    print("%30s         "%(""), end = "")
    for i in range(maxGroupSize + 1):
        print("%8d   "%(i), end = "")
    print("%8s"%("total"), end = "")
    print("")
    for grp in sorted(list(set(groups))):
        nSamples = sum((group == grp for group in groups))
        print("%30s (%3d)   "%(grp, nSamples), end = "")
        for i in range(maxGroupSize + 1):
            if i <= nSamples:
                print("%8d   "%(a[grp][i]), end = "")
            else:
                print("%8s   "%(""), end = "")
        print("%8d   "%(sum(a[grp][1:])), end = "")
        print("")





def rsd(vals):
    return np.std(vals) / np.mean(vals) * 100

def plot_RSDs_per_group(dat, groups, type = "points"):
    temp ={"rsd": [], "mean": [], "sd": [], "featurei": [], "group": [], "type": []}

    for grp in sorted(list(set(groups))):
        groupInd = [i for i, group in enumerate(groups) if group == grp]
        for featurei in range(dat.shape[1]):
            vals = dat[groupInd, featurei]

            if np.all(np.isnan(vals)):
                next

            if np.any(np.isnan(vals)) and np.any(~np.isnan(vals)):
                vals_ = np.copy(vals)
                vals_ = vals_[~np.isnan(vals_)]
                if vals_.shape[0] > 1:
                    temp["rsd"].append(rsd(vals_))
                    temp["mean"].append(np.log2(np.mean(vals_)))
                    temp["sd"].append(np.log2(np.std(vals_)))
                    temp["featurei"].append(featurei)
                    temp["group"].append(grp)
                    temp["type"].append("without np.nan")
        
            vals_ = np.copy(vals)
            vals_[np.isnan(vals_)] = 0
            if np.sum(vals_ > 0) > 1:
                temp["rsd"].append(rsd(vals_))
                temp["mean"].append(np.log2(np.mean(vals_)))
                temp["sd"].append(np.log2(np.std(vals_)))
                temp["featurei"].append(featurei)
                temp["group"].append(grp)
                temp["type"].append("np.nan replaced with 0")
            
    temp = pd.DataFrame(temp)
    if type == "histogram": 
        p = (p9.ggplot(data = temp, mapping = p9.aes(
                x = "rsd", fill = "group"
            ))
            + p9.geom_histogram()
            + p9.facet_grid("type~group")
            + p9.theme_minimal()
            + p9.theme(legend_position = "bottom")
            #+ p9.theme(subplots_adjust={'wspace':0.15, 'hspace':0.25, 'top':0.93, 'right':0.99, 'bottom':0.15, 'left':0.15})
            + p9.ggtitle("RSD plots")
        )

    elif type == "points":
        p = (p9.ggplot(data = temp, mapping = p9.aes(
                x = "mean", y = "rsd", colour = "group"
            ))
            + p9.geom_point(alpha = 0.3)
            #+ p9.geom_abline(slope = 0.15, intercept = 0, colour = "slategrey")
            #+ p9.geom_abline(slope = 0.5, intercept = 0, colour = "black")
            #+ p9.geom_abline(slope = 1, intercept = 0, colour = "firebrick")
            + p9.facet_grid("type~group")
            + p9.theme_minimal()
            + p9.theme(legend_position = "bottom")
            #+ p9.theme(subplots_adjust={'wspace':0.15, 'hspace':0.25, 'top':0.93, 'right':0.99, 'bottom':0.15, 'left':0.15})
            + p9.ggtitle("RSD plots")
        )
    
    else:
        raise RuntimeError("Unknown plot type. Must be 'histogram' or 'points'")
    
    return p





def remove_blank_groups(samples, groups, batches, dat, blankGroups):
    for bGrp in blankGroups:
        if bGrp in groups:
        ## find all samples not associated with the blank group
            inds = [i for i, group in enumerate(groups) if group != bGrp]
        
        ## keep all these samples thereby removing the samples of the particular blank group
            dat = dat[inds, :]
            samples = [samples[i] for i in inds]
            groups = [groups[i] for i in inds]
            batches = [batches[i] for i in inds]

            print("   .. removed group %s"%(bGrp))
        else:
            warnings.warn("Blank group '%s' is not present (%s)"%(bGrp, str(sorted(list(set(groups))))))
    return samples,groups,batches,dat





