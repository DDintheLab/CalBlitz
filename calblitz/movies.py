# -*- coding: utf-8 -*-
"""
Spyder Editor

author: agiovann
"""
#%%
import cv2
import os
import sys
import copy
import pims
import scipy.ndimage
import scipy
import sklearn
import warnings
import numpy as np
from sklearn.decomposition import NMF,IncrementalPCA, FastICA
from sklearn.cluster import KMeans
from sklearn.metrics.pairwise import euclidean_distances
import pylab as plt
import h5py
import cPickle as cpk
from scipy.io import loadmat
from matplotlib import animation
import pylab as pl
from skimage.external.tifffile import imread

#from ca_source_extraction.utilities import save_memmap,load_memmap

try:
    plt.ion()
except:
    1


from skimage.transform import warp, AffineTransform
from skimage.feature import match_template
from skimage import data

import timeseries as ts
from traces import trace
from utils import display_animation    

#%%
class movie(ts.timeseries):
    """ 
    Class representing a movie. This class subclasses timeseries, that in turn subclasses ndarray

    movie(input_arr, fr=None,start_time=0,file_name=None, meta_data=None)
    
    Example of usage
    ----------
    input_arr = 3d ndarray
    fr=33; # 33 Hz
    start_time=0
    m=movie(input_arr, start_time=0,fr=33);
    
    Parameters
    ----------
    input_arr:  np.ndarray, 3D, (time,height,width)
    fr: frame rate
    start_time: time beginning movie, if None it is assumed 0    
    meta_data: dictionary including any custom meta data
    file_name:name associated with the file (for instance path to the original file)

    """
#    def __new__(cls, input_arr,fr=None,start_time=0,file_name=None, meta_data=None,**kwargs):        
    def __new__(cls, input_arr,**kwargs):   
        
        if type(input_arr) is np.ndarray or  type(input_arr) is h5py._hl.dataset.Dataset:            
#            kwargs['start_time']=start_time;
#            kwargs['file_name']=file_name;
#            kwargs['meta_data']=meta_data;
            #kwargs['fr']=fr;                    
            return super(movie, cls).__new__(cls, input_arr,**kwargs)
            
        else:
            raise Exception('Input must be an ndarray, use load instead!')
    
    
    def motion_correct(self, max_shift_w=5,max_shift_h=5, num_frames_template=None, template=None,method='opencv',remove_blanks=False):
        
        '''
        Extract shifts and motion corrected movie automatically, for more control consider the functions extract_shifts and apply_shifts   
        Disclaimer, it might change the object itself.
        
        Parameters
        ----------
        max_shift_w,max_shift_h: maximum pixel shifts allowed when correcting in the width and height direction
        template: if a good template for frame by frame correlation is available it can be passed. If None it is automatically computed
        method: depends on what is installed 'opencv' or 'skimage'. 'skimage' is an order of magnitude slower
        num_frames_template: if only a subset of the movies needs to be loaded for efficiency/speed reasons
        
         
        Returns
        -------
        self: motion corected movie, it might change the object itself              
        shifts : tuple, contains shifts in x and y and correlation with template
        xcorrs: cross correlation of the movies with the template
        template= the computed template

        '''
        
        # adjust the movie so that valuse are non negative  

        min_val=np.min(np.mean(self,axis=0))
        self=self-min_val
        
        if template is None:  # if template is not provided it is created
            if num_frames_template is None:
                num_frames_template=10e7/(512*512)
            
            frames_to_skip=np.round(np.maximum(1,self.shape[0]/num_frames_template)) # sometimes it is convenient to only consider a subset of the movie when computing the median            
            #idx=np.random.randint(0,high=self.shape[0],size=(num_frames_template,))
            submov=self[::frames_to_skip,:].copy()
            templ=submov.bin_median(); # create template with portion of movie
            shifts,xcorrs=submov.extract_shifts(max_shift_w=max_shift_w, max_shift_h=max_shift_h, template=templ, method=method)  #
            submov.apply_shifts(shifts,interpolation='cubic',method=method)
            template=submov.bin_median()
            del submov
            m=self.copy()
            shifts,xcorrs=m.extract_shifts(max_shift_w=max_shift_w, max_shift_h=max_shift_h, template=template, method=method)  #
            m=m.apply_shifts(shifts,interpolation='cubic',method=method)
            template=(m.bin_median())      
            del m
        
        # now use the good template to correct        
        shifts,xcorrs=self.extract_shifts(max_shift_w=max_shift_w, max_shift_h=max_shift_h, template=template, method=method)  #               
        self=self.apply_shifts(shifts,interpolation='cubic',method=method)
        self=self+min_val       
        
        if remove_blanks:
            max_h,max_w= np.max(shifts,axis=0)
            min_h,min_w= np.min(shifts,axis=0)
            self=self.crop(crop_top=max_h,crop_bottom=-min_h+1,crop_left=max_w,crop_right=-min_w,crop_begin=0,crop_end=0)
        
         
        return self,shifts,xcorrs,template

               
    def bin_median(self,window=10):
        T,d1,d2=np.shape(self)
        num_windows=np.int(T/window)
        num_frames=num_windows*window
        return np.median(np.mean(np.reshape(self[:num_frames],(window,num_windows,d1,d2)),axis=0),axis=0)
        
    
    def extract_shifts(self, max_shift_w=5,max_shift_h=5, template=None, method='opencv'):
        """
        Performs motion corretion using the opencv matchtemplate function. At every iteration a template is built by taking the median of all frames and then used to align the other frames.
         
        Parameters
        ----------
        max_shift_w,max_shift_h: maximum pixel shifts allowed when correcting in the width and height direction
        template: if a good template for frame by frame correlation is available it can be passed. If None it is automatically computed
        method: depends on what is installed 'opencv' or 'skimage'. 'skimage' is an order of magnitude slower
         
        Returns
        -------
        shifts : tuple, contains shifts in x and y and correlation with template
        xcorrs: cross correlation of the movies with the template
        """
        
        if np.min(np.mean(self,axis=0))<0:
            warnings.warn('Pixels averages are too negative. Algorithm might not work.')
            
        if type(self[0,0,0]) is not np.float32:
            warnings.warn('Casting the array to float 32')
            self=np.asanyarray(self,dtype=np.float32)
                    
        n_frames_,h_i, w_i = self.shape
        
        ms_w = max_shift_w
        ms_h = max_shift_h
        
        if template is None:
            template=np.median(self,axis=0)            
            
        template=template[ms_h:h_i-ms_h,ms_w:w_i-ms_w].astype(np.float32)    
        h,w = template.shape      # template width and height
        
        
        #% run algorithm, press q to stop it 
        shifts=[];   # store the amount of shift in each frame
        xcorrs=[];
        
        for i,frame in enumerate(self):
             if i%100==99:
                 print "Frame %i"%(i+1);
             if method == 'opencv':
                 res = cv2.matchTemplate(frame,template,cv2.TM_CCORR_NORMED)             
                 top_left = cv2.minMaxLoc(res)[3]
             elif method == 'skimage':
                 res = match_template(frame,template)                 
                 top_left = np.unravel_index(np.argmax(res),res.shape);
                 top_left=top_left[::-1]   
             else:
                 raise Exception('Unknown motion correction ethod!')
             avg_corr=np.mean(res);
             sh_y,sh_x = top_left
             bottom_right = (top_left[0] + w, top_left[1] + h)
        
             if (0 < top_left[1] < 2 * ms_h-1) & (0 < top_left[0] < 2 * ms_w-1):
                 # if max is internal, check for subpixel shift using gaussian
                 # peak registration
                 log_xm1_y = np.log(res[sh_x-1,sh_y]);             
                 log_xp1_y = np.log(res[sh_x+1,sh_y]);             
                 log_x_ym1 = np.log(res[sh_x,sh_y-1]);             
                 log_x_yp1 = np.log(res[sh_x,sh_y+1]);             
                 four_log_xy = 4*np.log(res[sh_x,sh_y]);
    
                 sh_x_n = -(sh_x - ms_h + (log_xm1_y - log_xp1_y) / (2 * log_xm1_y - four_log_xy + 2 * log_xp1_y))
                 sh_y_n = -(sh_y - ms_w + (log_x_ym1 - log_x_yp1) / (2 * log_x_ym1 - four_log_xy + 2 * log_x_yp1))
             else:
                 sh_x_n = -(sh_x - ms_h)
                 sh_y_n = -(sh_y - ms_w)
            
#             if not only_shifts:
#                 if method == 'opencv':        
#                     M = np.float32([[1,0,sh_y_n],[0,1,sh_x_n]])
#                     self[i] = cv2.warpAffine(frame,M,(w_i,h_i),flags=interpolation)
#                 elif method == 'skimage':
#                     tform = AffineTransform(translation=(-sh_y_n,-sh_x_n))             
#                     self[i] = warp(frame, tform,preserve_range=True,order=3)
#                 if show_movie:        
#                 fr = cv2.resize(self[i],None,fx=2, fy=2, interpolation = cv2.INTER_CUBIC)
#                 cv2.imshow('frame',fr/255.0)
#                 if cv2.waitKey(1) & 0xFF == ord('q'):
#                     cv2.destroyAllWindows()
#                     break     

             shifts.append([sh_x_n,sh_y_n]) 
             xcorrs.append([avg_corr])
             

        return (shifts,xcorrs)
        
        

        
        
    def apply_shifts(self, shifts,interpolation='linear',method='opencv',remove_blanks=False):
        """ 
        Apply precomputed shifts to a movie, using subpixels adjustment (cv2.INTER_CUBIC function)
        
        Parameters
        ------------
        shifts: array of tuples representing x and y shifts for each frame        
        interpolation: 'linear', 'cubic', 'nearest' or cvs.INTER_XXX
        """
        if type(self[0,0,0]) is not np.float32:
            warnings.warn('Casting the array to float 32')
            self=np.asanyarray(self,dtype=np.float32)
        
        if interpolation == 'cubic':     
            if method == 'opencv':
                interpolation=cv2.INTER_CUBIC
            else:
                interpolation=3
            print 'cubic interpolation'
            
        elif interpolation == 'nearest':
            if method == 'opencv':            
                interpolation=cv2.INTER_NEAREST 
            else:
                interpolation=0
            print 'nearest interpolation'
            
        elif interpolation == 'linear':
            if method=='opencv':            
                interpolation=cv2.INTER_LINEAR
            else:
                interpolation=1
            print 'linear interpolation'
        elif interpolation == 'area':   
            if method=='opencv': 
                interpolation=cv2.INTER_AREA
            else:
                raise Exception('Method not defined')
            print 'area interpolation'
        elif interpolation == 'lanczos4': 
            if method=='opencv': 
                interpolation=cv2.INTER_LANCZOS4
            else:
                interpolation=4
            print 'lanczos/biquartic interpolation'            
            
        else:
            raise Exception('Interpolation method not available')
    
            
        t,h,w=self.shape
        for i,frame in enumerate(self):
            
             if i%100==99:
                 print "Frame %i"%(i+1); 

             sh_x_n, sh_y_n = shifts[i]
               
             if method == 'opencv':
                 M = np.float32([[1,0,sh_y_n],[0,1,sh_x_n]])
                 self[i] = cv2.warpAffine(frame,M,(w,h),flags=interpolation)
             elif method == 'skimage':
                 
                 tform = AffineTransform(translation=(-sh_y_n,-sh_x_n))             
                 self[i] = warp(frame, tform,preserve_range=True,order=interpolation)
                                                     
             else:
                 raise Exception('Unknown shift  application method')

        if remove_blanks:
            max_h,max_w= np.max(shifts,axis=0)
            min_h,min_w= np.min(shifts,axis=0)
            self=self.crop(crop_top=max_h,crop_bottom=-min_h+1,crop_left=max_w,crop_right=-min_w,crop_begin=0,crop_end=0)
            
        return self
    

    def crop(self,crop_top=0,crop_bottom=0,crop_left=0,crop_right=0,crop_begin=0,crop_end=0):
        """ Crop movie        
        """
        
        t,h,w=self.shape
        
        return self[crop_begin:t-crop_end,crop_top:h-crop_bottom,crop_left:w-crop_right]
        
        
    def computeDFF(self,secsWindow=5,quantilMin=8,method='only_baseline'):
        """ 
        compute the DFF of the movie or remove baseline
        In order to compute the baseline frames are binned according to the window length parameter
        and then the intermediate values are interpolated. 
        Parameters
        ----------
        secsWindow: length of the windows used to compute the quantile
        quantilMin : value of the quantile
        method='only_baseline','delta_f_over_f','delta_f_over_sqrt_f'
        
        Returns 
        -----------
        self: DF or DF/F or DF/sqrt(F) movies
        movBL=baseline movie
        """
        
        print "computing minimum ..."; sys.stdout.flush()
        minmov=np.min(self)
        
        if np.min(self)<=0 and method != 'only_baseline':
            raise ValueError("All pixels must be positive")

        numFrames,linePerFrame,pixPerLine=np.shape(self)
        downsampfact=int(secsWindow*1.*self.fr);
        elm_missing=int(np.ceil(numFrames*1.0/downsampfact)*downsampfact-numFrames)
        padbefore=int(np.floor(elm_missing/2.0))
        padafter=int(np.ceil(elm_missing/2.0))
       
        print 'Inizial Size Image:' + np.str(np.shape(self)); sys.stdout.flush()
        self=movie(np.pad(self,((padbefore,padafter),(0,0),(0,0)),mode='reflect'),**self.__dict__)
        numFramesNew,linePerFrame,pixPerLine=np.shape(self)
        
        #% compute baseline quickly
        print "binning data ..."; sys.stdout.flush()
        movBL=np.reshape(self,(downsampfact,int(numFramesNew/downsampfact),linePerFrame,pixPerLine));
        movBL=np.percentile(movBL,quantilMin,axis=0);
        print "interpolating data ..."; sys.stdout.flush()   
        print movBL.shape 
        
        movBL=scipy.ndimage.zoom(np.array(movBL,dtype=np.float32),[downsampfact ,1, 1],order=0, mode='constant', cval=0.0, prefilter=False)
        
        #% compute DF/F
        if method == 'delta_f_over_sqrt_f':
            self=(self-movBL)/np.sqrt(movBL)
        elif method == 'delta_f_over_f':
            self=(self-movBL)/movBL
        elif method  =='only_baseline':
            self=(self-movBL)/movBL
        else:
            raise Exception('Unknown method')
            
        self=self[padbefore:len(movBL)-padafter,:,:]; 
        print 'Final Size Movie:' +  np.str(self.shape) 
        return self,movie(movBL,fr=self.fr,start_time=self.start_time,meta_data=self.meta_data,file_name=self.file_name)      
        
    
    def NonnegativeMatrixFactorization(self,n_components=30, init='nndsvd', beta=1,tol=5e-7, sparseness='components',**kwargs):
        '''
        See documentation for scikit-learn NMF
        '''
        
        minmov=np.min(self)        
        if np.min(self)<0:
            raise ValueError("All values must be positive") 
            
        T,h,w=self.shape
        Y=np.reshape(self,(T,h*w))
        Y=Y-np.percentile(Y,1)
        Y=np.clip(Y,0,np.Inf)
        estimator=NMF(n_components=n_components, init=init, beta=beta,tol=tol, sparseness=sparseness,**kwargs)
        time_components=estimator.fit_transform(Y)
        components_ = estimator.components_        
        space_components=np.reshape(components_,(n_components,h,w))
        
        return space_components,time_components    
        
    
    
    def online_NMF(self,n_components=30,method='nnsc',lambda1=100,iterations=-5,batchsize=512,model=None,**kwargs):
        """ Method performing online matrix factorization and using the spams (http://spams-devel.gforge.inria.fr/doc-python/html/index.html) package from Inria. 
        Implements bith the nmf and nnsc methods
        
        Parameters
        ----------
        n_components: int
        
        method: 'nnsc' or 'nmf' (see http://spams-devel.gforge.inria.fr/doc-python/html/index.html)
        
        lambda1: see http://spams-devel.gforge.inria.fr/doc-python/html/index.html
        iterations: see http://spams-devel.gforge.inria.fr/doc-python/html/index.html
        batchsize: see http://spams-devel.gforge.inria.fr/doc-python/html/index.html 
        model: see http://spams-devel.gforge.inria.fr/doc-python/html/index.html
        **kwargs: more arguments to be passed to nmf or nnsc         
        
        Return:
        -------
        time_comps
        space_comps
        """
        try:
            import spams
        except:
            print "You need to install the SPAMS package"
            raise
            
        T,d1,d2=np.shape(self)
        d=d1*d2
        X=np.asfortranarray(np.reshape(self,[T,d],order='F'))
        
        if method == 'nmf':
            (time_comps,V) = spams.nmf(X,return_lasso= True ,K = n_components,numThreads=4,iter = iterations,**kwargs)
        
        elif method == 'nnsc':
            (time_comps,V) = spams.nnsc(X,return_lasso=True,K=n_components, lambda1 = lambda1,iter = iterations, model = model, **kwargs)        
        else:
            raise Exception('Method unknown')
        
        space_comps=[]
        
        for idx,mm in enumerate(V):
            space_comps.append(np.reshape(mm.todense(),(d1,d2),order='F'))
            
        return time_comps,np.array(space_comps)        
#        pl.figure()
#        for idx,mm in enumerate(V):
#            pl.subplot(6,5,idx+1)
#            pl.imshow(np.reshape(mm.todense(),(d1,d2),order='F'),cmap=pl.cm.gray)
        
    def IPCA(self, components = 50, batch =1000):
        '''
        Iterative Principal Component analysis, see sklearn.decomposition.incremental_pca
        Parameters:
        ------------
        components (default 50) = number of independent components to return
        batch (default 1000)  = number of pixels to load into memory simultaneously in IPCA. More requires more memory but leads to better fit
        Returns
        -------
        eigenseries: principal components (pixel time series) and associated singular values
        eigenframes: eigenframes are obtained by multiplying the projected frame matrix by the projected movie (whitened frames?)
        proj_frame_vectors:the reduced version of the movie vectors using only the principal component projection
        '''
        # vectorize the images
        num_frames, h, w = np.shape(self);
        frame_size = h * w;
        frame_samples = np.reshape(self, (num_frames, frame_size)).T
        
        # run IPCA to approxiate the SVD        
        ipca_f = IncrementalPCA(n_components=components, batch_size=batch)
        ipca_f.fit(frame_samples)
        
        # construct the reduced version of the movie vectors using only the 
        # principal component projection
        
        proj_frame_vectors = ipca_f.inverse_transform(ipca_f.transform(frame_samples))
            
        # get the temporal principal components (pixel time series) and 
        # associated singular values
        
        eigenseries = ipca_f.components_.T

        # the rows of eigenseries are approximately orthogonal
        # so we can approximately obtain eigenframes by multiplying the 
        # projected frame matrix by this transpose on the right
        
        eigenframes = np.dot(proj_frame_vectors, eigenseries)

        return eigenseries, eigenframes, proj_frame_vectors    
    
    def IPCA_stICA(self, componentsPCA=50,componentsICA = 40, batch = 1000, mu = 1, ICAfun = 'logcosh', **kwargs):
        '''
        Compute PCA + ICA a la Mukamel 2009. 
        
        
        
        Parameters:
        components (default 50) = number of independent components to return
        batch (default 1000) = number of pixels to load into memory simultaneously in IPCA. More requires more memory but leads to better fit
        mu (default 0.05) = parameter in range [0,1] for spatiotemporal ICA, higher mu puts more weight on spatial information
        ICAFun (default = 'logcosh') = cdf to use for ICA entropy maximization    
        Plus all parameters from sklearn.decomposition.FastICA
        
        Returns:
        ind_frames [components, height, width] = array of independent component "eigenframes"
        '''
        eigenseries, eigenframes,_proj = self.IPCA(componentsPCA, batch)
        # normalize the series
    
        frame_scale = mu / np.max(eigenframes)
        frame_mean = np.mean(eigenframes, axis = 0)
        n_eigenframes = frame_scale * (eigenframes - frame_mean)
    
        series_scale = (1-mu) / np.max(eigenframes)
        series_mean = np.mean(eigenseries, axis = 0)
        n_eigenseries = series_scale * (eigenseries - series_mean)
    
        # build new features from the space/time data
        # and compute ICA on them
    
        eigenstuff = np.concatenate([n_eigenframes, n_eigenseries])
    
        ica = FastICA(n_components=componentsICA, fun=ICAfun,**kwargs)
        joint_ics = ica.fit_transform(eigenstuff)
    
        # extract the independent frames
        num_frames, h, w = np.shape(self);
        frame_size = h * w;
        ind_frames = joint_ics[:frame_size, :]
        ind_frames = np.reshape(ind_frames.T, (componentsICA, h, w))
        
        return ind_frames  

    
    def IPCA_denoise(self, components = 50, batch = 1000):
        '''
        Create a denoise version of the movie only using the first 'components' components
        '''
        _, _, clean_vectors = self.IPCA(components, batch)
        self = self.__class__(np.reshape(clean_vectors.T, np.shape(self)),**self.__dict__)
        return self
                
    def IPCA_io(self, n_components=50, fun='logcosh', max_iter=1000, tol=1e-20):
        ''' DO NOT USE STILL UNDER DEVELOPMENT
        '''
        pca_comp=n_components;        
        [T,d1,d2]=self.shape
        M=np.reshape(self,(T,d1*d2))                
        [U,S,V] = scipy.sparse.linalg.svds(M,pca_comp)
        S=np.diag(S);
#        whiteningMatrix = np.dot(scipy.linalg.inv(np.sqrt(S)),U.T)
#        dewhiteningMatrix = np.dot(U,np.sqrt(S))
        whiteningMatrix = np.dot(scipy.linalg.inv(S),U.T)
        dewhiteningMatrix = np.dot(U,S)
        whitesig =  np.dot(whiteningMatrix,M)
        wsigmask=np.reshape(whitesig.T,(d1,d2,pca_comp));
        f_ica=sklearn.decomposition.FastICA(whiten=False, fun=fun, max_iter=max_iter, tol=tol)
        S_ = f_ica.fit_transform(whitesig.T)
        A_ = f_ica.mixing_
        A=np.dot(A_,whitesig)        
        mask=np.reshape(A.T,(d1,d2,pca_comp))
        return mask

    def compute_StructuredNMFactorization(self):
        print "to do"
        
   
    def local_correlations(self,eight_neighbours=False):
         '''
         Compute local correlations.
         Parameters:
         -----------
         if eight_neighbours=True it will take the diagonal neighbours too
         
         Returns
         -------
         rho M x N matrix, cross-correlation with adjacent pixel
         '''

         rho = np.zeros(np.shape(self)[1:3])
         w_mov = (self - np.mean(self, axis = 0))/np.std(self, axis = 0)
 
         rho_h = np.mean(np.multiply(w_mov[:,:-1,:], w_mov[:,1:,:]), axis = 0)
         rho_w = np.mean(np.multiply(w_mov[:,:,:-1], w_mov[:,:,1:,]), axis = 0)
         
         if True:
             rho_d1 = np.mean(np.multiply(w_mov[:,1:,:-1], w_mov[:,:-1,1:,]), axis = 0)
             rho_d2 = np.mean(np.multiply(w_mov[:,:-1,:-1], w_mov[:,1:,1:,]), axis = 0)


         rho[:-1,:] = rho[:-1,:] + rho_h
         rho[1:,:] = rho[1:,:] + rho_h
         rho[:,:-1] = rho[:,:-1] + rho_w
         rho[:,1:] = rho[:,1:] + rho_w
         
         if eight_neighbours:
             rho[:-1,:-1] = rho[:-1,:-1] + rho_d2
             rho[1:,1:] = rho[1:,1:] + rho_d1
             rho[1:,:-1] = rho[1:,:-1] + rho_d1
             rho[:-1,1:] = rho[:-1,1:] + rho_d2
         
         
         if eight_neighbours:
             neighbors = 8 * np.ones(np.shape(self)[1:3])  
             neighbors[0,:] = neighbors[0,:] - 3;
             neighbors[-1,:] = neighbors[-1,:] - 3;
             neighbors[:,0] = neighbors[:,0] - 3;
             neighbors[:,-1] = neighbors[:,-1] - 3;
             neighbors[0,0] = neighbors[0,0] + 1;
             neighbors[-1,-1] = neighbors[-1,-1] + 1;
             neighbors[-1,0] = neighbors[-1,0] + 1;
             neighbors[0,-1] = neighbors[0,-1] + 1;
         else:
             neighbors = 4 * np.ones(np.shape(self)[1:3]) 
             neighbors[0,:] = neighbors[0,:] - 1;
             neighbors[-1,:] = neighbors[-1,:] - 1;
             neighbors[:,0] = neighbors[:,0] - 1;
             neighbors[:,-1] = neighbors[:,-1] - 1;
         
         
         

         rho = np.divide(rho, neighbors)

         return rho
         
    def partition_FOV_KMeans(self,tradeoff_weight=.5,fx=.25,fy=.25,n_clusters=4,max_iter=500):
        """ 
        Partition the FOV in clusters that are grouping pixels close in space and in mutual correlation
                        
        Parameters
        ------------------------------
        tradeoff_weight:between 0 and 1 will weight the contributions of distance and correlation in the overall metric
        fx,fy: downsampling factor to apply to the movie 
        n_clusters,max_iter: KMeans algorithm parameters
        
        Outputs
        -------------------------------
        fovs:array 2D encoding the partitions of the FOV
        mcoef: matric of pairwise correlation coefficients
        distanceMatrix: matrix of picel distances
        
        Example
        
        """
        
        _,h1,w1=self.shape
        self.resize(fx,fy)
        T,h,w=self.shape
        Y=np.reshape(self,(T,h*w))
        mcoef=np.corrcoef(Y.T)
        idxA,idxB =  np.meshgrid(range(w),range(h));
        coordmat=np.vstack((idxA.flatten(),idxB.flatten()))
        distanceMatrix=euclidean_distances(coordmat.T);
        distanceMatrix=distanceMatrix/np.max(distanceMatrix)
        estim=KMeans(n_clusters=n_clusters,max_iter=max_iter);
        kk=estim.fit(tradeoff_weight*mcoef-(1-tradeoff_weight)*distanceMatrix)
        labs=kk.labels_
        fovs=np.reshape(labs,(h,w))
        fovs=cv2.resize(np.uint8(fovs),(w1,h1),1./fx,1./fy,interpolation=cv2.INTER_NEAREST)
        return np.uint8(fovs), mcoef, distanceMatrix
    
    
    def extract_traces_from_masks(self,masks):
        """                        
        Parameters
        ----------------------
        masks: array, 3D with each 2D slice bein a mask (integer or fractional)  
        
        Outputs
        ----------------------
        traces: array, 2D of fluorescence traces
        """
        T,h,w=self.shape
        Y=np.reshape(self,(T,h*w))
        nA,_,_=masks.shape
        A=np.reshape(masks,(nA,h*w))
        pixelsA=np.sum(A,axis=1)
        A=A/pixelsA[:,None] # obtain average over ROI
        traces=trace(np.dot(A,np.transpose(Y)).T,**self.__dict__)               
        return traces
            
    def resize(self,fx=1,fy=1,fz=1,interpolation=cv2.INTER_AREA):  
        """
        resize movies along axis and interpolate or lowpass when necessary
        it will not work without opencv
        
        Parameters
        -------------------
        fx,fy,fz:fraction/multiple of dimension (.5 means the image will be half the size)
        interpolation=cv2.INTER_AREA. Set to none if you do not want interpolation or lowpass
        

        """              
        if fx!=1 or fy!=1:
            print "reshaping along x and y"
            t,h,w=self.shape
            newshape=(int(w*fy),int(h*fx))
            mov=[];
            print(newshape)
            for frame in self:                
                mov.append(cv2.resize(frame,newshape,fx=fx,fy=fy,interpolation=interpolation))
            self=movie(np.asarray(mov),**self.__dict__)
        if fz!=1:
            print "reshaping along z"            
            t,h,w=self.shape
            self=np.reshape(self,(t,h*w))            
            mov=cv2.resize(self,(h*w,int(fz*t)),fx=1,fy=fz,interpolation=interpolation)            
#            self=cv2.resize(self,(h*w,int(fz*t)),fx=1,fy=fz,interpolation=interpolation)
            mov=np.reshape(mov,(int(fz*t),h,w))
            self=movie(mov,**self.__dict__)
            self.fr=self.fr*fz  
            
        return self
        
        
    def guided_filter_blur_2D(self,guide_filter,radius=5, eps=0):
        """ 
        performs guided filtering on each frame. See opencv documentation of cv2.ximgproc.guidedFilter
        """       
        for idx,fr in enumerate(self):
            if idx%1000==0:
                print idx
            self[idx] =  cv2.ximgproc.guidedFilter(guide_filter,fr,radius=radius,eps=eps)  

        return self
    
    def bilateral_blur_2D(self,diameter=5,sigmaColor=10000,sigmaSpace=0):
        """ 
        performs bilateral filtering on each frame. See opencv documentation of cv2.bilateralFilter
        """        
        if type(self[0,0,0]) is not np.float32:
            warnings.warn('Casting the array to float 32')
            self=np.asanyarray(self,dtype=np.float32)
            
        for idx,fr in enumerate(self):
            if idx%1000==0:
                print idx
            self[idx] =   cv2.bilateralFilter(fr,diameter,sigmaColor,sigmaSpace)     
        
        return self
        
    
      
    def gaussian_blur_2D(self,kernel_size_x=5,kernel_size_y=5,kernel_std_x=1,kernel_std_y=1,borderType=cv2.BORDER_REPLICATE):
        """
        Compute gaussian blut in 2D. Might be useful when motion correcting

        Parameters
        ----------
        kernel_size: double
            see opencv documentation of GaussianBlur
        kernel_std_: double
            see opencv documentation of GaussianBlur
        borderType: int
            see opencv documentation of GaussianBlur
            
        Returns
        --------        
        self: ndarray
            blurred movie
        """        
        
        for idx,fr in enumerate(self):
                print idx
                self[idx] = cv2.GaussianBlur(fr,ksize=(kernel_size_x,kernel_size_y),sigmaX=kernel_std_x,sigmaY=kernel_std_y,borderType=borderType)  
                
        return self       
                
    def median_blur_2D(self,kernel_size=3):
        """
        Compute gaussian blut in 2D. Might be useful when motion correcting

        Parameters
        ----------
        kernel_size: double
            see opencv documentation of GaussianBlur
        kernel_std_: double
            see opencv documentation of GaussianBlur
        borderType: int
            see opencv documentation of GaussianBlur
            
        Returns
        --------        
        self: ndarray
            blurred movie
        """        
        
        for idx,fr in enumerate(self):
                print idx
                self[idx] = cv2.medianBlur(fr,ksize=kernel_size)  
                
        return self   
        
    def resample(self,new_time_vect):
        print 1        
    
    def to_2D(self,order='F'):
        [T,d1,d2]=self.shape
        d=d1*d2
        return np.reshape(self,(T,d),order=order)
    
    def zproject(self,method='mean',cmap=pl.cm.gray,aspect='auto',**kwargs):
        """                                                                                                                                                                                       
        Compute and plot projection across time:                                                                                                                                                  
                                                                                                                                                                                                  
        method: String                                                                                                                                                                            
            'mean','median','std'                                                                                                                                                                 
                                                                                                                                                                                                  
        **kwargs: dict                                                                                                                                                                            
            arguments to imagesc                                                                                                                                                                  
        """
        if method is 'mean':
            zp=np.mean(self,axis=0)
        elif method is 'median':
            zp=np.median(self,axis=0)
        elif method is 'std':
            zp=np.std(self,axis=0)
        else:
            raise Exception('Method not implemented')
        pl.imshow(zp,cmap=cmap,aspect=aspect,**kwargs)
        return zp
        
    def local_correlations_movie(self,window=10):
        [T,d1,d2]=self.shape
        return movie(np.concatenate([self[j:j+window,:,:].local_correlations(eight_neighbours=True)[np.newaxis,:,:] for j in range(T-window)],axis=0),fr=self.fr)    
    
    def play(self,gain=1,fr=None,magnification=1,offset=0,interpolation=cv2.INTER_LINEAR,backend='pylab'):
         """
         Play the movie using opencv
         
         Parameters
         ----------
         gain: adjust  movie brightness
         frate : playing speed if different from original (inter frame interval in seconds)
         backend: 'pylab' or 'opencv', the latter much faster
         """  
         if backend is 'pylab':
             print '*** WARNING *** SPEED MIGHT BE LOW. USE opencv backend if available'
         
         gain*=1.
         maxmov=np.max(self)
         
         if backend is 'pylab':
            plt.ion()
            fig = plt.figure( 1 )
            ax = fig.add_subplot( 111 )
            ax.set_title("Play Movie")                
            im = ax.imshow( (offset+self[0])*gain/maxmov ,cmap=plt.cm.gray,vmin=0,vmax=1,interpolation='none') # Blank starting image
            fig.show()
            im.axes.figure.canvas.draw()
            plt.pause(1)
         
         if backend is 'notebook':
             # First set up the figure, the axis, and the plot element we want to animate
            fig = plt.figure()
            im = plt.imshow(self[0],interpolation='None',cmap=plt.cm.gray)
            plt.axis('off')
            def animate(i):
                im.set_data(self[i])
                return im,
            
            # call the animator.  blit=True means only re-draw the parts that have changed.
            anim = animation.FuncAnimation(fig, animate, 
                                           frames=self.shape[0], interval=1, blit=True)
            
            # call our new function to display the animation
            return display_animation(anim,fps=fr)

         
         if fr==None:
            fr=self.fr
            
         for iddxx,frame in enumerate(self):
            if backend is 'opencv':
                if magnification != 1:
                    frame = cv2.resize(frame,None,fx=magnification, fy=magnification, interpolation = interpolation)
                    
                cv2.imshow('frame',(offset+frame)*gain/maxmov)
                if cv2.waitKey(int(1./fr*1000)) & 0xFF == ord('q'):
                    cv2.destroyAllWindows()
                    break  
                   
                
            elif backend is 'pylab':

                im.set_data((offset+frame)*gain/maxmov)
                ax.set_title( str( iddxx ) )
                plt.axis('off')
                fig.canvas.draw()
                plt.pause(1./fr*.5) 
                ev=plt.waitforbuttonpress(1./fr*.5)
                if ev is not None:                                    
                    plt.close()
                    break
                
            elif backend is 'notebook':

                print 'Animated via MP4'
                break

            else:
                
                raise Exception('Unknown backend!')
        
         if backend is 'opencv':
            cv2.destroyAllWindows()
        
    

def load(file_name,fr=None,start_time=0,meta_data=None,subindices=None,shape=None):
    '''
    load movie from file. 
    
    Parameters
    -----------
    file_name: string 
        name of file. Possible extensions are tif, avi, npy, (npz and hdf5 are usable only if saved by calblitz)
    fr: float
        frame rate
    start_time: float
        initial time for frame 1
    meta_data: dict 
        same as for calblitz.movie
    subindices: iterable indexes
        for loading only portion of the movie
    shape: tuple of two values
        dimension of the movie along x and y if loading from a two dimensional numpy array
    
    Returns
    -------
    mov: calblitz.movie
        
    '''  
    
    # case we load movie from file
    if os.path.exists(file_name):        
            
        name,extension = os.path.splitext(file_name)[:2]

        if extension == '.tif': # load avi file
            print('Loading tif...')
            if subindices is not None:
                input_arr=imread(file_name)[subindices,:,:]
            else:
                input_arr=imread(file_name)
            
            input_arr=np.squeeze(input_arr)
            
#            with pims.open(file_name) as f:
#                if len(f.frame_shape)==3:
#                    for ext_fr in f:
#                        if subindices is None:
#                            input_arr = np.array(ext_fr)    
#                        else:
#                            input_arr = np.array([ext_fr[j] for j in subindices])
#                elif len(f.frame_shape)==2:                    
#                        if subindices is None:
#                            input_arr = np.array(f)    
#                        else:
#                            input_arr = np.array([f[j] for j in subindices])
#                else:
#                    raise Exception('The input file has an unknown numberof dimensions')
                    
            # necessary for the way pims work with tiffs      
#            input_arr = input_arr[:,::-1,:]

        elif extension == '.avi': # load avi file
            #raise Exception('Use sintax mov=cb.load(filename)')
            if subindices is not None:
                raise Exception('Subindices not implemented')
            cap = cv2.VideoCapture(file_name)
            try: 
                length = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
                width  = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
                height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
            except:
                print 'Roll back top opencv 2'
                length = int(cap.get(cv2.cv.CV_CAP_PROP_FRAME_COUNT))
                width  = int(cap.get(cv2.cv.CV_CAP_PROP_FRAME_WIDTH))
                height = int(cap.get(cv2.cv.CV_CAP_PROP_FRAME_HEIGHT))
                
            input_arr=np.zeros((length, height,width),dtype=np.uint8)
            counter=0
            ret=True
            while True:
                # Capture frame-by-frame
                ret, frame = cap.read()
                if not ret:
                    break
                input_arr[counter]=frame[:,:,0]
                counter=counter+1
                if not counter%100:
                    print counter
            
            # When everything done, release the capture
            cap.release()
            cv2.destroyAllWindows()   
            
        elif extension == '.npy': # load npy file     
            if subindices is not None:
                input_arr=np.load(file_name)[subindices]     
            else:                   
                input_arr=np.load(file_name)
            if input_arr.ndim==2:
                if shape is not None:
                    d,T=np.shape(input_arr)
                    d1,d2=shape
                    input_arr=np.transpose(np.reshape(input_arr,(d1,d2,T),order='F'),(2,0,1))
                else:
                    raise Exception('Loaded vector is 2D , you need to provide the shape parameter')
           
        elif extension == '.mat': # load npy file     
            input_arr=loadmat(file_name)['data']
            input_arr=np.rollaxis(input_arr,2,-3)
            if subindices is not None:
                input_arr=input_arr[subindices]     
            
                
        elif extension == '.npz': # load movie from saved file                          
            if subindices is not None:
                raise Exception('Subindices not implemented')
            with np.load(file_name) as f:
                return movie(**f)  
            
        elif extension== '.hdf5':
            
            with h5py.File(file_name, "r") as f:     
                attrs=dict(f['mov'].attrs)
                attrs['meta_data']=cpk.loads(attrs['meta_data'])
                if subindices is None:
#                    fr=f['fr'],start_time=f['start_time'],file_name=f['file_name']
                    return movie(f['mov'],**attrs)   
                else:
                    return movie(f['mov'][subindices],**attrs)         

        else:
            raise Exception('Unknown file type')    
    else:
        raise Exception('File not found!')
        
    return movie(input_arr,fr=fr,start_time=start_time,file_name=file_name, meta_data=meta_data)
          
        
def load_movie_chain(file_list,fr=None,start_time=0,meta_data=None,subindices=None,bottom=0,top=0,left=0,right=0):
    ''' load movies from list of file names
    file_list: list of file names in string format
    other parameters as in load_movie except
    bottom, top, left, right to load only portion of the field of view
    '''

    mov=[];    
    for f in file_list:
        m=load(f,fr=fr,start_time=start_time,meta_data=meta_data,subindices=subindices);
        tm,h,w=np.shape(m)
        m=m[:,top:h-bottom,left:w-right]
        mov.append(m)
        
    return ts.concatenate(mov,axis=0)
        


def to_3D(mov2D,shape,order='F'):
    """
    transform to 3D a vectorized movie
    """
    return np.reshape(mov2D,shape,order=order) 

        
             
if __name__ == "__main__":
    print 1
#    mov=movie('/Users/agiovann/Dropbox/Preanalyzed Data/ExamplesDataAnalysis/Andrea/PC1/M_FLUO.tif',fr=15.62,start_time=0,meta_data={'zoom':2,'location':[100, 200, 300]})
#    mov1=movie('/Users/agiovann/Dropbox/Preanalyzed Data/ExamplesDataAnalysis/Andrea/PC1/M_FLUO.tif',fr=15.62,start_time=0,meta_data={'zoom':2,'location':[100, 200, 300]})    
##    newmov=ts.concatenate([mov,mov1])    
##    mov.save('./test.npz')
##    mov=movie.load('test.npz')
#    max_shift=5;
#    mov,template,shifts,xcorrs=mov.motion_correct(max_shift_h=max_shift,max_shift_w=max_shift,show_movie=0)
#    max_shift=5;
#    mov1,template1,shifts1,xcorrs1=mov1.motion_correct(max_shift_h=max_shift,max_shift_w=max_shift,show_movie=0,method='skimage')
    
#    mov=mov.apply_shifts(shifts)    
#    mov=mov.crop(crop_top=max_shift,crop_bottom=max_shift,crop_left=max_shift,crop_right=max_shift)    
#    mov=mov.resize(fx=.25,fy=.25,fz=.2)    
#    mov=mov.computeDFF()      
#    mov=mov-np.min(mov)
#    space_components,time_components=mov.NonnegativeMatrixFactorization();
#    trs=mov.extract_traces_from_masks(1.*(space_components>0.4))
#    trs=trs.computeDFF()
