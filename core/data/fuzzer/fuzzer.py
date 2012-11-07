'''
fuzzer.py

Copyright 2006 Andres Riancho

This file is part of w3af, w3af.sourceforge.net .

w3af is free software; you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation version 2 of the License.

w3af is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
GNU General Public License for more details.

You should have received a copy of the GNU General Public License
along with w3af; if not, write to the Free Software
Foundation, Inc., 51 Franklin St, Fifth Floor, Boston, MA  02110-1301  USA

'''
import copy
import re
import urllib
import cgi
import json

import core.data.kb.config as cf
import core.controllers.outputManager as om

from core.controllers.misc.io import NamedStringIO

from core.data.dc.cookie import Cookie
from core.data.dc.form import Form
from core.data.dc.dataContainer import DataContainer
from core.data.request.HTTPPostDataRequest import HTTPPostDataRequest
from core.data.request.HTTPQsRequest import HTTPQSRequest

from core.data.fuzzer.utils import rand_alpha
from core.data.fuzzer.form_filler import smart_fill
from core.data.fuzzer.mutants.querystring_mutant import mutantQs
from core.data.fuzzer.mutants.postdata_mutant import mutantPostData
from core.data.fuzzer.mutants.filename_mutant import mutantFileName
from core.data.fuzzer.mutants.urlparts_mutant import mutantUrlParts
from core.data.fuzzer.mutants.headers_mutant import mutantHeaders
from core.data.fuzzer.mutants.json_mutant import mutantJSON
from core.data.fuzzer.mutants.cookie_mutant import mutantCookie
from core.data.fuzzer.mutants.filecontent_mutant import mutantFileContent

#
# The following is a list of parameter names that will be ignored during
# the fuzzing process
#
IGNORED_PARAMETERS = [
    '__EVENTTARGET', '__EVENTARGUMENT', '__VIEWSTATE', '__VIEWSTATEENCRYPTED', 
    '__EVENTVALIDATION', '__dnnVariable', 'javax.faces.ViewState',
    'jsf_state_64', 'jsf_sequence', 'jsf_tree', 'jsf_tree_64', 
    'jsf_viewid', 'jsf_state', 'cfid', 'cftoken','ASP.NET_sessionid',
    'ASPSESSIONID', 'PHPSESSID', 'JSESSIONID'
    ]


def create_mutants(freq, mutant_str_list, append=False,
                   fuzzable_param_list=[], orig_resp=None):
    '''
    @parameter freq: A fuzzable request with a DataContainer inside.
    @parameter mutant_str_list: a list with mutant strings to use
    @parameter append: This indicates if the content of mutant_str_list should
        be appended to the variable value
    @parameter fuzzable_param_list: If [] then all params are fuzzed. If ['a'],
        then only 'a' is fuzzed.
    @return: A Mutant object List.
    '''
    result = []
    _fuzzable = _createFuzzable(freq)
    
    if isinstance(freq, HTTPQSRequest):
        
        # Query string parameters    
        _fuzzing('_create_mutantsWorker/QS', freq)
        result.extend(_create_mutantsWorker(freq, mutantQs, mutant_str_list,
                                           fuzzable_param_list, append))
        
        # File name
        if 'fuzzedFname' in _fuzzable:
            _fuzzing('_createFileNameMutants', freq)
            result.extend(_createFileNameMutants(freq, mutantFileName, 
                                 mutant_str_list, fuzzable_param_list, append))

        if 'fuzzURLParts' in _fuzzable:
            _fuzzing('_createUrlPartsMutants', freq)
            result.extend(_createUrlPartsMutants(freq, mutantUrlParts, 
                                 mutant_str_list, fuzzable_param_list, append))
 
    # POST-data parameters
    elif isinstance(freq, HTTPPostDataRequest):
        # If this is a POST request, it could be a JSON request, and I want
        # to fuzz it!
        
        if isJSON(freq):
            _fuzzing('_createJSONMutants', freq)
            result.extend(_createJSONMutants(freq, mutantJSON, mutant_str_list,
                                             fuzzable_param_list, append))
        else:
            _fuzzing('_createJSONMutants/post-data', freq)
            result.extend(_create_mutantsWorker(freq, mutantPostData,
                                   mutant_str_list, fuzzable_param_list, append))
        
        # File content of multipart forms
        if 'fuzzFileContent' in _fuzzable:
            _fuzzing('_createFileContentMutants', freq)
            result.extend(_createFileContentMutants(freq, mutant_str_list,
                                                    fuzzable_param_list, append))
    # Headers
    if 'headers' in _fuzzable:
        _fuzzing('_create_mutantsWorker/headers', freq)
        result.extend(_create_mutantsWorker(freq, mutantHeaders, mutant_str_list,
                                           fuzzable_param_list, append, 
                                           dataContainer=_fuzzable['headers']))
        
    # Cookie values
    if 'cookie' in _fuzzable and freq.getCookie():
        _fuzzing('_create_mutantsWorker/cookie', freq)
        mutants = _create_mutantsWorker(freq, mutantCookie, mutant_str_list,
                                       fuzzable_param_list, append,
                                       dataContainer=freq.getCookie())        
        result.extend( mutants )
    
    #
    # Improvement to reduce false positives with a double check:
    #    Get the original response and link it to each mutant.
    #
    # Improvement to reduce network traffic:
    #    If the original response has an "ETag" header, set a "If-None-Match"
    #    header with the same value. On a test that I ran, the difference was
    #    very noticeable:
    #        - Without sending ETag headers: 304046 bytes
    #        - Sending ETag headers:          55320 bytes
    #
    # This is very impressing, but the performance enhancement is only
    # possible IF the remote server sends the ETag header, and for example
    # Apache+PHP doesn't send that tag by default (only sent if the PHP developer
    # added some code to his PHP to do it).
    #
    if orig_resp is not None:
        
        headers = orig_resp.getHeaders()
        etag = headers.get('ETag', None)
        
        for m in result:
            m.setOriginalResponseBody( orig_resp.getBody() )
            
            if etag is not None:
                orig_headers = m.getHeaders()
                orig_headers['If-None-Match'] = etag
                m.setHeaders(orig_headers) 
        
    return result

def _fuzzing(what, who):
    om.out.debug('Calling "%s" with "%s" as fuzzable request.' % (what,who) )

def _createJSONMutants(freq, mutantClass, mutant_str_list, fuzzable_param_list, append):
    '''
    @param freq: A fuzzable request with a DataContainer inside.
    @param mutantClass: The class to use to create the mutants
    @param fuzzable_param_list: What parameters should be fuzzed
    @param append: True/False, if we should append the value or replace it.
    @param mutant_str_list: a list with mutant strings to use
    @return: Mutants that have the JSON postdata changed with the strings at mutant_str_list
    '''
    # We define a function that creates the mutants...
    def _makeMutants( freq, mutantClass, mutant_str_list, fuzzable_param_list , append, jsonPostData):
        res = []
        
        for fuzzed_json, original_value in _fuzzJSON( mutant_str_list, jsonPostData, append ):
        
            # Create the mutants
            freq_copy = freq.copy()
            m = mutantClass( freq_copy ) 
            m.setOriginalValue( original_value )
            m.setVar( 'JSON data' )
            m.setDc( fuzzed_json )
            res.append( m )
            
        return res
        
    # Now we define a function that does the work...
    def _fuzzJSON( mutant_str_list, jsonPostData, append ):
        '''
        @return: A list with tuples containing
        (fuzzed list/dict/string/int that represents a JSON object, original value)
        '''
        res = []
        
        if isinstance(jsonPostData, int):
            for mutant_str in mutant_str_list:
                if mutant_str.isdigit():
                    # This (a mutant str that really is an integer) will happend once every 100000 years, 
                    # but I wanted to be sure to cover all cases. This will look something like:
                    #
                    # 1
                    #
                    # In the postdata.
                    if append:
                        fuzzed = int(str(jsonPostData) +  str(mutant_str))
                        res.append( (fuzzed, str(jsonPostData)) )
                    else:
                        fuzzed = int(mutant_str)
                        res.append( (fuzzed, jsonPostData) )
        
        elif isinstance(jsonPostData, basestring):
            # This will look something like:
            #
            # "abc"
            #
            # In the postdata.
            for mutant_str in mutant_str_list:
                if append:
                    fuzzed = jsonPostData +  mutant_str
                    res.append( (fuzzed, jsonPostData) )
                else:
                    res.append( (mutant_str, jsonPostData) )
                    
                    
        elif isinstance( jsonPostData, list ):
            # This will look something like:
            #
            # ["abc", "def"]
            #
            # In the postdata.
            for item, i in zip( jsonPostData,xrange(len(jsonPostData)) ):
                fuzzed_item_list = _fuzzJSON( mutant_str_list, jsonPostData[i] , append )
                for fuzzed_item, original_value in fuzzed_item_list:
                    jsonPostDataCopy = copy.deepcopy( jsonPostData )
                    jsonPostDataCopy[ i ] = fuzzed_item
                    res.append( (jsonPostDataCopy, original_value) )
        
        elif isinstance( jsonPostData, dict ):
            for key in jsonPostData:
                fuzzed_item_list = _fuzzJSON( mutant_str_list, jsonPostData[key] , append )
                for fuzzed_item, original_value in fuzzed_item_list:
                    jsonPostDataCopy = copy.deepcopy( jsonPostData )
                    jsonPostDataCopy[ key ] = fuzzed_item
                    res.append( (jsonPostDataCopy, original_value) )
        
        return res
    
    # Now, fuzz the parsed JSON data...
    postdata = freq.getData()
    jsonPostData = json.loads( postdata )
    return _makeMutants( freq, mutantClass, mutant_str_list, fuzzable_param_list , append, jsonPostData )

def isJSON( freq ):
    # Only do the JSON stuff if this is really a JSON request...
    postdata = freq.getData()
    try:
        cgi.parse_qs( postdata ,keep_blank_values=True,strict_parsing=True)
    except Exception:
        # We have something that's not URL encoded in the postdata, it could be something
        # like JSON, XML, or multipart encoding. Let's try with JSON
        try:
            json.loads( postdata )
        except:
            # It's not json, maybe XML or multipart, I don't really care
            # (at least not in this section of the code)
            return False
        else:
            # Now, fuzz the parsed JSON data...
            return True
    else:
        # No need to do any JSON stuff, the postdata is urlencoded
        return False
    
def _createFileContentMutants(freq, mutant_str_list, fuzzable_param_list, append):
    '''
    @parameter freq: A fuzzable request with a DataContainer inside.
    @parameter mutantClass: The class to use to create the mutants
    @parameter fuzzable_param_list: What parameters should be fuzzed
    @parameter append: True/False, if we should append the value or replace it.
    @parameter mutant_str_list: a list with mutant strings to use
    @return: Mutants that have the file content changed with the strings at mutant_str_list
    '''
    res = []
    file_vars = freq.get_file_vars()
    
    if file_vars:
        tmp = []
        ext = cf.cf.get('fuzzFCExt') or 'txt'
        
        for mutant_str in mutant_str_list:
            if isinstance(mutant_str, basestring):
                # I have to create the NamedStringIO with a "name".
                # This is needed for MultipartPostHandler
                fname = "%s.%s" % (rand_alpha(7), ext)
                str_file = NamedStringIO(mutant_str, name=fname)
                tmp.append(str_file)
        res = _create_mutantsWorker(freq, mutantFileContent,
                                   tmp, file_vars, append)
    
    return res
    
def _createFileNameMutants(freq, mutantClass, mutant_str_list, fuzzable_param_list, append ):
    '''
    @parameter freq: A fuzzable request with a DataContainer inside.
    @parameter mutantClass: The class to use to create the mutants
    @parameter fuzzable_param_list: What parameters should be fuzzed
    @parameter append: True/False, if we should append the value or replace it.
    @parameter mutant_str_list: a list with mutant strings to use
    
    @return: Mutants that have the filename URL changed with the strings at mutant_str_list
    
    >>> from core.data.parsers.url import URL
    >>> from core.data.request.fuzzable_request import FuzzableRequest
    >>> url = URL('http://www.w3af.com/abc/def.html')
    >>> fr = FuzzableRequest(url)
    >>> mutant_list = _createFileNameMutants( fr, mutantFileName, ['ping!','pong-'], [], False )
    >>> [ m.getURL().url_string for m in mutant_list]
    [u'http://www.w3af.com/abc/ping%21.html', u'http://www.w3af.com/abc/pong-.html', u'http://www.w3af.com/abc/def.ping%21', u'http://www.w3af.com/abc/def.pong-']
    
    >>> mutant_list = _createFileNameMutants( fr, mutantFileName, ['/etc/passwd',], [], False )
    >>> [ m.getURL().url_string for m in mutant_list]
    [u'http://www.w3af.com/abc/%2Fetc%2Fpasswd.html', u'http://www.w3af.com/abc//etc/passwd.html', u'http://www.w3af.com/abc/def.%2Fetc%2Fpasswd', u'http://www.w3af.com/abc/def./etc/passwd']

    '''
    res = []
    fname = freq.getURL().getFileName()
    fname_chunks = [x for x in re.split(r'([a-zA-Z0-9]+)', fname) if x] 
    
    for idx, fn_chunk in enumerate(fname_chunks):
        
        for mutant_str in mutant_str_list:
            
            if re.match('[a-zA-Z0-9]', fn_chunk):
                divided_fname = DataContainer()
                divided_fname['start'] = ''.join(fname_chunks[:idx])
                divided_fname['end'] = ''.join(fname_chunks[idx+1:])
                divided_fname['fuzzedFname'] = \
                    (fn_chunk if append else '') + urllib.quote_plus(mutant_str)
                
                freq_copy = freq.copy()
                freq_copy.setURL(freq.getURL())
                
                # Create the mutant
                m = mutantClass(freq_copy) 
                m.setOriginalValue(fn_chunk)
                m.setVar('fuzzedFname')
                m.setMutantDc(divided_fname)
                m.setModValue(mutant_str)
                # Special for filename fuzzing and some configurations
                # of mod_rewrite
                m.setDoubleEncoding(False)
                res.append(m)
                
                # The same but with a different type of encoding! (mod_rewrite)
                m2 = m.copy()
                m2.setSafeEncodeChars('/')
                
                if m2.getURL() != m.getURL():
                    res.append(m2)
    return res
    
def _create_mutantsWorker(freq, mutantClass, mutant_str_list,
                         fuzzable_param_list, append, dataContainer=None):
    '''
    An auxiliary function to create_mutants.
    
    @return: A list of mutants.

    >>> from core.data.request.fuzzable_request import FuzzableRequest
    >>> from core.data.parsers.url import URL
    >>> from core.data.dc.dataContainer import DataContainer

    Mutant creation
    >>> d = DataContainer()
    >>> d['a'] = ['1',]
    >>> d['b'] = ['2',]
    >>> freq = FuzzableRequest(URL('http://www.w3af.com/'), dc=d)
    >>> f = _create_mutantsWorker( freq, mutantQs, ['abc', 'def'], [], False)
    >>> [ i.getDc() for i in f ]
    [DataContainer({'a': ['abc'], 'b': ['2']}), DataContainer({'a': ['def'], 'b': ['2']}), DataContainer({'a': ['1'], 'b': ['abc']}), DataContainer({'a': ['1'], 'b': ['def']})]

    Append
    >>> d = DataContainer()
    >>> d['a'] = ['1',]
    >>> d['b'] = ['2',]
    >>> freq = FuzzableRequest(URL('http://www.w3af.com/'), dc=d)
    >>> f = _create_mutantsWorker( freq, mutantQs, ['abc', 'def'], [], True)
    >>> [ i.getDc() for i in f ]
    [DataContainer({'a': ['1abc'], 'b': ['2']}), DataContainer({'a': ['1def'], 'b': ['2']}), DataContainer({'a': ['1'], 'b': ['2abc']}), DataContainer({'a': ['1'], 'b': ['2def']})]

    Repeated parameters
    >>> d = DataContainer()
    >>> d['a'] = ['1','2','3']
    >>> freq.setDc(d)
    >>> f = _create_mutantsWorker( freq, mutantQs, ['abc', 'def'], [], False)
    >>> [ i.getDc() for i in f ]
    [DataContainer({'a': ['abc', '2', '3']}), DataContainer({'a': ['def', '2', '3']}), DataContainer({'a': ['1', 'abc', '3']}), DataContainer({'a': ['1', 'def', '3']}), DataContainer({'a': ['1', '2', 'abc']}), DataContainer({'a': ['1', '2', 'def']})]

    SmartFill of parameters
    >>> from core.data.dc.form import Form
    >>> from core.data.request.HTTPPostDataRequest import HTTPPostDataRequest
    >>> f = Form()
    >>> _ = f.addInput( [("name", "address") , ("type", "text")] )
    >>> _ = f.addInput( [("name", "foo") , ("type", "text")] )
    >>> pdr = HTTPPostDataRequest(URL('http://www.w3af.com/'), dc=f)
    >>> f = _create_mutantsWorker( pdr, mutantPostData, ['abc', 'def'], [], False)
    >>> [ i.getDc() for i in f ]
    [Form({'address': ['abc'], 'foo': ['56']}), Form({'address': ['def'], 'foo': ['56']}), Form({'address': ['Bonsai Street 123'], 'foo': ['abc']}), Form({'address': ['Bonsai Street 123'], 'foo': ['def']})]

    Support for HTTP requests that have both QS and POST-Data
    >>> f = Form()
    >>> _ = f.addInput( [("name", "password") , ("type", "password")] )
    >>> pdr = HTTPPostDataRequest(URL('http://www.w3af.com/foo.bar?action=login'), dc=f)
    >>> mutants = _create_mutantsWorker( pdr, mutantPostData, ['abc', 'def'], [], False)
    >>> [ i.getURI() for i in mutants ]
    [<URL for "http://www.w3af.com/foo.bar?action=login">, <URL for "http://www.w3af.com/foo.bar?action=login">]
    >>> [ i.getDc() for i in mutants ]
    [Form({'password': ['abc']}), Form({'password': ['def']})]
    '''
    result = []
    if not dataContainer:
        dataContainer = freq.getDc()

    for pname in dataContainer:
        
        #
        # Ignore the banned parameter names
        #
        if pname in IGNORED_PARAMETERS:
            continue
        
        # This for is to support repeated parameter names
        for element_index, element_value in enumerate(dataContainer[pname]):
            
            for mutant_str in mutant_str_list:
                
                # Exclude the file parameters, those are fuzzed in _createFileContentMutants()
                # (if the framework if configured to do so)
                #
                # But if we have a form with files, then we have a multipart form, and we have to keep it
                # that way. If we don't send the multipart form as multipart, the remote programming
                # language may ignore all the request, and the parameter that we are
                # fuzzing (that's not the file content one) will be ignored too
                #
                # The "keeping the multipart form alive" thing is done some lines below, search for
                # the "__HERE__" string!
                #
                # The exclusion is done here:
                if pname in freq.get_file_vars() and not hasattr(mutant_str, 'name'):
                    continue
                    
                # Only fuzz the specified parameters (if any)
                # or fuzz all of them (the fuzzable_param_list == [] case)
                if pname in fuzzable_param_list or fuzzable_param_list == []:
                    
                    dc_copy = dataContainer.copy()
                    original_value = element_value
                    
                    # Ok, now we have a data container with the mutant string, but it's possible that
                    # all the other fields of the data container are empty (think about a form)
                    # We need to fill those in, with something *useful* to get around the easiest
                    # developer checks like: "parameter A was filled".
                    
                    # But I only perform this task in HTML forms, everything else is left as it is:
                    if isinstance(dc_copy, Form):
                        for var_name_dc in dc_copy:
                            for element_index_dc, element_value_dc in enumerate(dc_copy[var_name_dc]):
                                if (var_name_dc, element_index_dc) != (pname, element_index) and\
                                dc_copy.get_type(var_name_dc) not in ['checkbox', 'radio', 'select', 'file' ]:
                                    
                                    #   Fill only if the parameter does NOT have a value set.
                                    #
                                    #   The reason of having this already set would be that the form
                                    #   has something like this:
                                    #
                                    #   <input type="text" name="p" value="foobar">
                                    #
                                    if dc_copy[var_name_dc][element_index_dc] == '':
                                        #
                                        #   Fill it smartly
                                        #
                                        dc_copy[var_name_dc][element_index_dc] = smart_fill(var_name_dc)

                    # __HERE__
                    # Please see the comment above for an explanation of what we are doing here:
                    for var_name in freq.get_file_vars():
                        # I have to create the NamedStringIO with a "name".
                        # This is needed for MultipartPostHandler
                        fname = "%s.%s" % (rand_alpha(7), 
                                           cf.cf.get('fuzzFCExt' ) or 'txt') 
                        str_file = NamedStringIO('', name=fname)
                        dc_copy[var_name][0] = str_file
                    
                    if append:
                        mutant_str = original_value + mutant_str
                    dc_copy[pname][element_index] = mutant_str
                    
                    # Create the mutant
                    freq_copy = freq.copy()
                    m = mutantClass( freq_copy )
                    m.setVar( pname, index=element_index )
                    m.setDc( dc_copy )
                    m.setOriginalValue( original_value )
                    m.setModValue( mutant_str )
                    
                    # Done, add it to the result
                    result.append( m )

    return result
    
def _createUrlPartsMutants(freq, mutantClass, mutant_str_list, fuzzable_param_list, append):
    '''
    @parameter freq: A fuzzable request with a DataContainer inside.
    @parameter mutantClass: The class to use to create the mutants
    @parameter fuzzable_param_list: What parameters should be fuzzed
    @parameter append: True/False, if we should append the value or replace it.
    @parameter mutant_str_list: a list with mutant strings to use
    
    @return: Mutants that have the filename URL changed with the strings at mutant_str_list
    
    >>> from core.data.parsers.url import URL
    >>> from core.data.request.fuzzable_request import FuzzableRequest
    >>> url = URL('http://www.w3af.com/abc/def')
    >>> fr = FuzzableRequest(url)
    >>> mutant_list = _createUrlPartsMutants(fr, mutantUrlParts, ['ping!'], [], False)
    >>> [m.getURL().url_string for m in mutant_list]
    [u'http://www.w3af.com/ping%21/def', u'http://www.w3af.com/ping%2521/def', u'http://www.w3af.com/abc/ping%21', u'http://www.w3af.com/abc/ping%2521']
    
    '''
    res = []
    path_sep = '/'
    path = freq.getURL().getPath()
    path_chunks = path.split(path_sep)
    for idx, p_chunk in enumerate(path_chunks):
        if not p_chunk:
            continue
        for mutant_str in mutant_str_list:
            divided_path = DataContainer()
            divided_path['start'] = path_sep.join(path_chunks[:idx] + [''])
            divided_path['end'] = path_sep.join([''] + path_chunks[idx+1:])
            divided_path['fuzzedUrlParts'] = \
                (p_chunk if append else '') + urllib.quote_plus(mutant_str)
            freq_copy = freq.copy()
            freq_copy.setURL(freq.getURL())
            m = mutantClass(freq_copy) 
            m.setOriginalValue(p_chunk)
            m.setVar('fuzzedUrlParts')
            m.setMutantDc(divided_path)
            m.setModValue(mutant_str)
            res.append(m)
            # Same URLs but with different types of encoding!
            m2 = m.copy()
            m2.setDoubleEncoding(True)
            res.append(m2)
    return res

def _createFuzzable(freq):
    '''
    @return: This function verifies the configuration, and creates a map of
        things that can be fuzzed.
    '''
    _fuzzable = {}
    _fuzzable['dc'] = freq.getDc()
    config = cf.cf
    
    # Add the fuzzable headers
    fuzzheaders = dict((h, '') for h in config.get('fuzzable_headers', []))
    
    if fuzzheaders:
        _fuzzable['headers'] = fuzzheaders
        
    if config.get('fuzzableCookie'):     
        _fuzzable['cookie'] = Cookie()
    
    if config.get('fuzzFileName'):
        _fuzzable['fuzzedFname'] = None
        
    if config.get('fuzzFileContent'):
        _fuzzable['fuzzFileContent'] = None

    if config.get('fuzzURLParts'):
        _fuzzable['fuzzURLParts'] = None
    
    return _fuzzable