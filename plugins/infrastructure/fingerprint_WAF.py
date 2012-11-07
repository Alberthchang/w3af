'''
fingerprint_WAF.py

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
import re

from itertools import izip, repeat

import core.controllers.outputManager as om
import core.data.kb.knowledge_base as kb
import core.data.kb.info as info

from core.controllers.plugins.infrastructure_plugin import InfrastructurePlugin
from core.controllers.w3afException import w3afException
from core.controllers.w3afException import w3afRunOnce
from core.controllers.misc.decorators import runonce
from core.data.fuzzer.utils import rand_alpha


class fingerprint_WAF(InfrastructurePlugin):
    '''
    Identify if a Web Application Firewall is present and if possible identify
    the vendor and version.
    
    @author: Andres Riancho (andres.riancho@gmail.com)
    '''
    
    '''
    CHANGELOG:
    Feb/17/2009- Added Signatures by Aung Khant (aungkhant[at]yehg.net):
    - Old version F5 Traffic Shield, NetContinuum, TEROS, BinarySec
    '''
    
    def __init__(self):
        InfrastructurePlugin.__init__(self)

    @runonce(exc_class=w3afRunOnce)        
    def discover(self, fuzzable_request ):
        '''
        @parameter fuzzable_request: A fuzzable_request instance that contains
                                    (among other things) the URL to test.
        '''
        methods = [ self._fingerprint_URLScan,
                    self._fingerprint_ModSecurity,
                    self._fingerprint_SecureIIS,
                    self._fingerprint_Airlock,
                    self._fingerprint_Barracuda,
                    self._fingerprint_DenyAll,
                    self._fingerprint_F5ASM,
                    self._fingerprint_F5TrafficShield,
                    self._fingerprint_TEROS,
                    self._fingerprint_NetContinuum,
                    self._fingerprint_BinarySec,
                    self._fingerprint_HyperGuard]
        
        args_iter = izip( methods, repeat(fuzzable_request))
        self._tm.threadpool.map_multi_args(self._worker, args_iter)
    
    def _worker(self, func, fuzzable_request):
        return func(fuzzable_request)
    
    def _fingerprint_SecureIIS(self, fuzzable_request):
        '''
        Try to verify if SecureIIS is installed or not.
        '''
        # And now a final check for SecureIIS
        headers = fuzzable_request.getHeaders()
        headers['Transfer-Encoding'] = rand_alpha(1024 + 1)
        try:
            lock_response2 = self._uri_opener.GET( fuzzable_request.getURL(), 
                                                   headers=headers, cache=True )
        except w3afException, w3:
            om.out.debug('Failed to identify secure IIS, exception: ' + str(w3) )
        else:
            if lock_response2.getCode() == 404:
                self._report_finding('SecureIIS', lock_response2)
        
    def _fingerprint_ModSecurity(self, fuzzable_request):
        '''
        Try to verify if mod_security is installed or not AND try to get the
        installed version.
        '''
        pass

    def _fingerprint_Airlock(self, fuzzable_request):
        '''
        Try to verify if Airlock is present.
        '''
        om.out.debug( 'detect Airlock' )
        response = self._uri_opener.GET( fuzzable_request.getURL(), cache=True )
        for header_name in response.getHeaders().keys():
            if header_name.lower() == 'set-cookie':
                protected_by = response.getHeaders()[header_name]
                if re.match('^AL[_-]?(SESS|LB)=', protected_by):
                    self._report_finding('Airlock', response, protected_by)
                    return
            # else 
                # more checks, like path /error_path or encrypted URL in response

    def _fingerprint_Barracuda(self, fuzzable_request):
        '''
        Try to verify if Barracuda is present.
        '''
        om.out.debug( 'detect Barracuda' )
        response = self._uri_opener.GET( fuzzable_request.getURL(), cache=True )
        for header_name in response.getHeaders().keys():
            if header_name.lower() == 'set-cookie':
                # ToDo: not sure if this is always there (08jul08 Achim)
                protected_by = response.getHeaders()[header_name]
                if re.match('^barra_counter_session=', protected_by):
                    self._report_finding('Barracuda', protected_by)
                    return
            # else 
                # don't know ...

    def _fingerprint_DenyAll(self, fuzzable_request):
        '''
        Try to verify if Deny All rWeb is present.
        '''
        om.out.debug( 'detect Deny All' )
        response = self._uri_opener.GET( fuzzable_request.getURL(), cache=True )
        for header_name in response.getHeaders().keys():
            if header_name.lower() == 'set-cookie':
                protected_by = response.getHeaders()[header_name]
                if re.match('^sessioncookie=', protected_by):
                    self._report_finding('Deny All rWeb', response, protected_by)
                    return
            # else
                # more checks like detection=detected cookie

    def _fingerprint_F5ASM(self, fuzzable_request):
        '''
        Try to verify if F5 ASM (also TrafficShield) is present.
        '''
        om.out.debug( 'detect F5 ASM or TrafficShield' )
        response = self._uri_opener.GET( fuzzable_request.getURL(), cache=True )
        for header_name in response.getHeaders().keys():
            if header_name.lower() == 'set-cookie':
                protected_by = response.getHeaders()[header_name]
                if re.match('^TS[a-zA-Z0-9]{3,6}=', protected_by):
                    self._report_finding('F5 ASM', response, protected_by)
                    return
            # else
                # more checks like special string in response

    def _fingerprint_F5TrafficShield(self, fuzzable_request):
        '''
        Try to verify if the older version F5 TrafficShield is present.
        Ref: Hacking Exposed - Web Application
        
        '''
        om.out.debug( 'detect the older version F5 TrafficShield' )
        response = self._uri_opener.GET( fuzzable_request.getURL(), cache=True )
        for header_name in response.getHeaders().keys():
            if header_name.lower() == 'set-cookie':
                protected_by = response.getHeaders()[header_name]
                if re.match('^ASINFO=', protected_by):
                    self._report_finding('F5 TrafficShield', response, protected_by)
                    return
            # else
                # more checks like special string in response
                    
    def _fingerprint_TEROS(self, fuzzable_request):
        '''
        Try to verify if TEROS is present.
        Ref: Hacking Exposed - Web Application
        
        '''
        om.out.debug( 'detect TEROS' )
        response = self._uri_opener.GET( fuzzable_request.getURL(), cache=True )
        for header_name in response.getHeaders().keys():
            if header_name.lower() == 'set-cookie':
                protected_by = response.getHeaders()[header_name]
                if re.match('^st8id=', protected_by):
                    self._report_finding('TEROS', response, protected_by)
                    return
            # else
                # more checks like special string in response
     
    def _fingerprint_NetContinuum(self, fuzzable_request):
        '''
        Try to verify if NetContinuum is present.
        Ref: Hacking Exposed - Web Application
        
        '''
        om.out.debug( 'detect NetContinuum' )
        response = self._uri_opener.GET( fuzzable_request.getURL(), cache=True )
        for header_name in response.getHeaders().keys():
            if header_name.lower() == 'set-cookie':
                protected_by = response.getHeaders()[header_name]
                if re.match('^NCI__SessionId=', protected_by):
                    self._report_finding('NetContinuum', response, protected_by)
                    return
            # else
                # more checks like special string in response
    
    def _fingerprint_BinarySec(self, fuzzable_request):
        '''
        Try to verify if BinarySec is present.
        '''
        om.out.debug( 'detect BinarySec' )
        response = self._uri_opener.GET( fuzzable_request.getURL(), cache=True )
        for header_name in response.getHeaders().keys():
            if header_name.lower() == 'server':
                protected_by = response.getHeaders()[header_name]                    
                if re.match('BinarySec', protected_by, re.IGNORECASE):
                    self._report_finding('BinarySec', response, protected_by)
                    return
            # else
                # more checks like special string in response

    
    def _fingerprint_HyperGuard(self, fuzzable_request):
        '''
        Try to verify if HyperGuard is present.
        '''
        om.out.debug( 'detect HyperGuard' )
        response = self._uri_opener.GET( fuzzable_request.getURL(), cache=True )
        for header_name in response.getHeaders().keys():
            if header_name.lower() == 'set-cookie':
                protected_by = response.getHeaders()[header_name]
                if re.match('^WODSESSION=', protected_by):
                    self._report_finding('HyperGuard', response, protected_by)
                    return
            # else
                # more checks like special string in response

    def _fingerprint_URLScan(self, fuzzable_request):
        '''
        Try to verify if URLScan is installed or not.
        '''
        # detect using GET
        # Get the original response
        orig_response = self._uri_opener.GET( fuzzable_request.getURL(), cache=True )
        if orig_response.getCode() != 404:
            # Now add the if header and try again
            headers = fuzzable_request.getHeaders()
            headers['If'] = rand_alpha(8)
            if_response = self._uri_opener.GET( fuzzable_request.getURL(),
                                                headers=headers,
                                                cache=True )
            headers = fuzzable_request.getHeaders()
            headers['Translate'] = rand_alpha(8)
            translate_response = self._uri_opener.GET( fuzzable_request.getURL(),
                                                       headers=headers, 
                                                       cache=True )
            
            headers = fuzzable_request.getHeaders()
            headers['Lock-Token'] = rand_alpha(8)
            lock_response = self._uri_opener.GET( fuzzable_request.getURL(),
                                                  headers=headers, 
                                                  cache=True )
            
            headers = fuzzable_request.getHeaders()
            headers['Transfer-Encoding'] = rand_alpha(8)
            transfer_enc_response = self._uri_opener.GET( fuzzable_request.getURL(), 
                                                          headers=headers,
                                                          cache=True )
        
            if if_response.getCode() == 404 or translate_response.getCode() == 404 or\
            lock_response.getCode() == 404 or transfer_enc_response.getCode() == 404:
                self._report_finding('URLScan', lock_response)

    
    def _report_finding( self, name, response, protected_by=None):
        '''
        Creates a information object based on the name and the response parameter
        and saves the data in the kb.
        
        @parameter name: The name of the WAF
        @parameter response: The HTTP response object that was used to identify the WAF
        @parameter protected_by: A more detailed description/version of the WAF
        '''
        i = info.info()
        i.setPluginName(self.get_name())
        i.setURL( response.getURL() )
        i.set_id( response.id )
        msg = 'The remote network seems to have a "'+name+'" WAF deployed to' \
              ' protect access to the web server.'
        if protected_by:
            msg += ' The following is a detailed version of the WAF: "' + protected_by + '".'
        i.set_desc( msg )
        i.set_name('Found '+name)
        kb.kb.append( self, name, i )
        om.out.information( i.get_desc() )

    def get_plugin_deps( self ):
        '''
        @return: A list with the names of the plugins that should be run before the
        current one.
        '''
        return ['infrastructure.afd']

    def get_long_desc( self ):
        '''
        @return: A DETAILED description of the plugin functions and features.
        '''
        return '''
        Try to fingerprint the Web Application Firewall that is running on the
        remote end.
        
        Please note that the detection of the WAF is performed by the 
        infrastructure.afd plugin (afd stands for Active Filter Detection).
        '''
