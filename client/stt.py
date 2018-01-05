#!/usr/bin/env python2
# -*- coding: utf-8-*-
import os
import time
import wave
import json
import tempfile
import logging
import urllib
import urlparse
import re
import subprocess
from abc import ABCMeta, abstractmethod
import requests
import yaml
import jasperpath
import diagnose
import vocabcompiler
import hashlib, base64


class AbstractSTTEngine(object):
    """
    Generic parent class for all STT engines
    """

    __metaclass__ = ABCMeta
    VOCABULARY_TYPE = None

    @classmethod
    def get_config(cls):
        return {}

    @classmethod
    def get_instance(cls, vocabulary_name, phrases):
        config = cls.get_config()
        if cls.VOCABULARY_TYPE:
            vocabulary = cls.VOCABULARY_TYPE(vocabulary_name,
                                             path=jasperpath.config(
                                                 'vocabularies'))
            if not vocabulary.matches_phrases(phrases):
                vocabulary.compile(phrases)
            config['vocabulary'] = vocabulary
        instance = cls(**config)
        return instance

    @classmethod
    def get_passive_instance(cls):
        phrases = vocabcompiler.get_keyword_phrases()
        return cls.get_instance('keyword', phrases)

    @classmethod
    def get_active_instance(cls):
        phrases = vocabcompiler.get_all_phrases()
        return cls.get_instance('default', phrases)

    @classmethod
    @abstractmethod
    def is_available(cls):
        return True

    @abstractmethod
    def transcribe(self, fp):
        pass


class PocketSphinxSTT(AbstractSTTEngine):
    """
    The default Speech-to-Text implementation which relies on PocketSphinx.
    """

    SLUG = 'sphinx'
    VOCABULARY_TYPE = vocabcompiler.PocketsphinxVocabulary

    def __init__(self, vocabulary, hmm_dir="/usr/local/share/" +
                 "pocketsphinx/model/hmm/en_US/hub4wsj_sc_8k"):

        """
        Initiates the pocketsphinx instance.

        Arguments:
            vocabulary -- a PocketsphinxVocabulary instance
            hmm_dir -- the path of the Hidden Markov Model (HMM)
        """

        self._logger = logging.getLogger(__name__)

        # quirky bug where first import doesn't work
        try:
            import pocketsphinx as ps
        except:
            import pocketsphinx as ps

        with tempfile.NamedTemporaryFile(prefix='psdecoder_',
                                         suffix='.log', delete=False) as f:
            self._logfile = f.name

        self._logger.debug("Initializing PocketSphinx Decoder with hmm_dir " +
                           "'%s'", hmm_dir)

        # Perform some checks on the hmm_dir so that we can display more
        # meaningful error messages if neccessary
        if not os.path.exists(hmm_dir):
            msg = ("hmm_dir '%s' does not exist! Please make sure that you " +
                   "have set the correct hmm_dir in your profile.") % hmm_dir
            self._logger.error(msg)
            raise RuntimeError(msg)
        # Lets check if all required files are there. Refer to:
        # http://cmusphinx.sourceforge.net/wiki/acousticmodelformat
        # for details
        missing_hmm_files = []
        for fname in ('mdef', 'feat.params', 'means', 'noisedict',
                      'transition_matrices', 'variances'):
            if not os.path.exists(os.path.join(hmm_dir, fname)):
                missing_hmm_files.append(fname)
        mixweights = os.path.exists(os.path.join(hmm_dir, 'mixture_weights'))
        sendump = os.path.exists(os.path.join(hmm_dir, 'sendump'))
        if not mixweights and not sendump:
            # We only need mixture_weights OR sendump
            missing_hmm_files.append('mixture_weights or sendump')
        if missing_hmm_files:
            self._logger.warning("hmm_dir '%s' is missing files: %s. Please " +
                                 "make sure that you have set the correct " +
                                 "hmm_dir in your profile.",
                                 hmm_dir, ', '.join(missing_hmm_files))

        self._decoder = ps.Decoder(hmm=hmm_dir, logfn=self._logfile,
                                   **vocabulary.decoder_kwargs)

    def __del__(self):
        os.remove(self._logfile)

    @classmethod
    def get_config(cls):
        # FIXME: Replace this as soon as we have a config module
        config = {}
        # HMM dir
        # Try to get hmm_dir from config
        profile_path = jasperpath.config('profile.yml')

        if os.path.exists(profile_path):
            with open(profile_path, 'r') as f:
                profile = yaml.safe_load(f)
                try:
                    config['hmm_dir'] = profile['pocketsphinx']['hmm_dir']
                except KeyError:
                    pass

        return config

    def transcribe(self, fp):
        """
        Performs STT, transcribing an audio file and returning the result.

        Arguments:
            fp -- a file object containing audio data
        """

        fp.seek(44)

        # FIXME: Can't use the Decoder.decode_raw() here, because
        # pocketsphinx segfaults with tempfile.SpooledTemporaryFile()
        data = fp.read()
        self._decoder.start_utt()
        self._decoder.process_raw(data, False, True)
        self._decoder.end_utt()

        result = self._decoder.get_hyp()
        with open(self._logfile, 'r+') as f:
            for line in f:
                self._logger.debug(line.strip())
            f.truncate()

        transcribed = [result[0]]
        self._logger.info('Transcribed: %r', transcribed)
        return transcribed

    @classmethod
    def is_available(cls):
        return diagnose.check_python_import('pocketsphinx')


class JuliusSTT(AbstractSTTEngine):
    """
    A very basic Speech-to-Text engine using Julius.
    """

    SLUG = 'julius'
    VOCABULARY_TYPE = vocabcompiler.JuliusVocabulary

    def __init__(self, vocabulary=None, hmmdefs="/usr/share/voxforge/julius/" +
                 "acoustic_model_files/hmmdefs", tiedlist="/usr/share/" +
                 "voxforge/julius/acoustic_model_files/tiedlist"):
        self._logger = logging.getLogger(__name__)
        self._vocabulary = vocabulary
        self._hmmdefs = hmmdefs
        self._tiedlist = tiedlist
        self._pattern = re.compile(r'sentence(\d+): <s> (.+) </s>')

        # Inital test run: we run this command once to log errors/warnings
        cmd = ['julius',
               '-input', 'stdin',
               '-dfa', self._vocabulary.dfa_file,
               '-v', self._vocabulary.dict_file,
               '-h', self._hmmdefs,
               '-hlist', self._tiedlist,
               '-forcedict']
        cmd = [str(x) for x in cmd]
        self._logger.debug('Executing: %r', cmd)
        with tempfile.SpooledTemporaryFile() as out_f:
            with tempfile.SpooledTemporaryFile() as f:
                with tempfile.SpooledTemporaryFile() as err_f:
                    subprocess.call(cmd, stdin=f, stdout=out_f, stderr=err_f)
            out_f.seek(0)
            for line in out_f.read().splitlines():
                line = line.strip()
                if len(line) > 7 and line[:7].upper() == 'ERROR: ':
                    if not line[7:].startswith('adin_'):
                        self._logger.error(line[7:])
                elif len(line) > 9 and line[:9].upper() == 'WARNING: ':
                    self._logger.warning(line[9:])
                elif len(line) > 6 and line[:6].upper() == 'STAT: ':
                    self._logger.debug(line[6:])

    @classmethod
    def get_config(cls):
        # FIXME: Replace this as soon as we have a config module
        config = {}
        # HMM dir
        # Try to get hmm_dir from config
        profile_path = jasperpath.config('profile.yml')

        if os.path.exists(profile_path):
            with open(profile_path, 'r') as f:
                profile = yaml.safe_load(f)
                if 'julius' in profile:
                    if 'hmmdefs' in profile['julius']:
                        config['hmmdefs'] = profile['julius']['hmmdefs']
                    if 'tiedlist' in profile['julius']:
                        config['tiedlist'] = profile['julius']['tiedlist']
        return config

    def transcribe(self, fp, mode=None):
        cmd = ['julius',
               '-quiet',
               '-nolog',
               '-input', 'stdin',
               '-dfa', self._vocabulary.dfa_file,
               '-v', self._vocabulary.dict_file,
               '-h', self._hmmdefs,
               '-hlist', self._tiedlist,
               '-forcedict']
        cmd = [str(x) for x in cmd]
        self._logger.debug('Executing: %r', cmd)
        with tempfile.SpooledTemporaryFile() as out_f:
            with tempfile.SpooledTemporaryFile() as err_f:
                subprocess.call(cmd, stdin=fp, stdout=out_f, stderr=err_f)
            out_f.seek(0)
            results = [(int(i), text) for i, text in
                       self._pattern.findall(out_f.read())]
        transcribed = [text for i, text in
                       sorted(results, key=lambda x: x[0])
                       if text]
        if not transcribed:
            transcribed.append('')
        self._logger.info('Transcribed: %r', transcribed)
        return transcribed

    @classmethod
    def is_available(cls):
        return diagnose.check_executable('julius')


class GoogleSTT(AbstractSTTEngine):
    """
    Speech-To-Text implementation which relies on the Google Speech API.

    This implementation requires a Google API key to be present in profile.yml

    To obtain an API key:
    1. Join the Chromium Dev group:
       https://groups.google.com/a/chromium.org/forum/?fromgroups#!forum/chromium-dev
    2. Create a project through the Google Developers console:
       https://console.developers.google.com/project
    3. Select your project. In the sidebar, navigate to "APIs & Auth." Activate
       the Speech API.
    4. Under "APIs & Auth," navigate to "Credentials." Create a new key for
       public API access.
    5. Add your credentials to your profile.yml. Add an entry to the 'keys'
       section using the key name 'GOOGLE_SPEECH.' Sample configuration:
    6. Set the value of the 'stt_engine' key in your profile.yml to 'google'


    Excerpt from sample profile.yml:

        ...
        timezone: US/Pacific
        stt_engine: google
        keys:
            GOOGLE_SPEECH: $YOUR_KEY_HERE

    """

    SLUG = 'google'

    def __init__(self, api_key=None, language='en-us'):
        # FIXME: get init args from config
        """
        Arguments:
        api_key - the public api key which allows access to Google APIs
        """
        self._logger = logging.getLogger(__name__)
        self._request_url = None
        self._language = None
        self._api_key = None
        self._http = requests.Session()
        self.language = language
        self.api_key = api_key

    @property
    def request_url(self):
        return self._request_url

    @property
    def language(self):
        return self._language

    @language.setter
    def language(self, value):
        self._language = value
        self._regenerate_request_url()

    @property
    def api_key(self):
        return self._api_key

    @api_key.setter
    def api_key(self, value):
        self._api_key = value
        self._regenerate_request_url()

    def _regenerate_request_url(self):
        if self.api_key and self.language:
            query = urllib.urlencode({'output': 'json',
                                      'client': 'chromium',
                                      'key': self.api_key,
                                      'lang': self.language,
                                      'maxresults': 6,
                                      'pfilter': 2})
            self._request_url = urlparse.urlunparse(
                ('https', 'www.google.com', '/speech-api/v2/recognize', '',
                 query, ''))
        else:
            self._request_url = None

    @classmethod
    def get_config(cls):
        # FIXME: Replace this as soon as we have a config module
        config = {}
        # HMM dir
        # Try to get hmm_dir from config
        profile_path = jasperpath.config('profile.yml')
        if os.path.exists(profile_path):
            with open(profile_path, 'r') as f:
                profile = yaml.safe_load(f)
                if 'keys' in profile and 'GOOGLE_SPEECH' in profile['keys']:
                    config['api_key'] = profile['keys']['GOOGLE_SPEECH']
        return config

    def transcribe(self, fp):
        """
        Performs STT via the Google Speech API, transcribing an audio file and
        returning an English string.

        Arguments:
        audio_file_path -- the path to the .wav file to be transcribed
        """

        if not self.api_key:
            self._logger.critical('API key missing, transcription request ' +
                                  'aborted.')
            return []
        elif not self.language:
            self._logger.critical('Language info missing, transcription ' +
                                  'request aborted.')
            return []

        wav = wave.open(fp, 'rb')
        frame_rate = wav.getframerate()
        wav.close()
        data = fp.read()

        headers = {'content-type': 'audio/l16; rate=%s' % frame_rate}
        r = self._http.post(self.request_url, data=data, headers=headers)
        try:
            r.raise_for_status()
        except requests.exceptions.HTTPError:
            self._logger.critical('Request failed with http status %d',
                                  r.status_code)
            if r.status_code == requests.codes['forbidden']:
                self._logger.warning('Status 403 is probably caused by an ' +
                                     'invalid Google API key.')
            return []
        r.encoding = 'utf-8'
        try:
            # We cannot simply use r.json() because Google sends invalid json
            # (i.e. multiple json objects, seperated by newlines. We only want
            # the last one).
            response = json.loads(list(r.text.strip().split('\n', 1))[-1])
            if len(response['result']) == 0:
                # Response result is empty
                raise ValueError('Nothing has been transcribed.')
            results = [alt['transcript'] for alt
                       in response['result'][0]['alternative']]
        except ValueError as e:
            self._logger.warning('Empty response: %s', e.args[0])
            results = []
        except (KeyError, IndexError):
            self._logger.warning('Cannot parse response.', exc_info=True)
            results = []
        else:
            # Convert all results to uppercase
            results = tuple(result.upper() for result in results)
            self._logger.info('Transcribed: %r', results)
        return results

    @classmethod
    def is_available(cls):
        return diagnose.check_network_connection()


class BaiduSTT(AbstractSTTEngine):
    """
    Speech-To-Text implementation which relies on the Baidu Speech API.

    This implementation requires an Baidu app_key/app_secret to be present in
    profile.yml. Please sign up at http://yuyin.baidu.com/ and
    create a new app. You can then take the app_key/app_secret and put it into
    your profile.yml:
        ...
        stt_engine: baidu-stt
        baidu_api:
          app_key:    LMFYhLdXSSthxCNLR7uxFszQ
          app_secret: 14dbd10057xu7b256e537455698c0e4e
    """

    SLUG = 'baidu-stt'

    def __init__(self, app_key, app_secret):
        self._logger = logging.getLogger(__name__)
        self.access_token = ''
        self.expires_in = 0
        self.current_time = 0
        self.app_key = app_key
        self.app_secret = app_secret

    @classmethod
    def get_config(cls):
        # FIXME: Replace this as soon as we have a config module
        config = {}
        # Try to get baidu app_key/app_secret from config
        profile_path = jasperpath.config('profile.yml')
        if os.path.exists(profile_path):
            with open(profile_path, 'r') as f:
                profile = yaml.safe_load(f)
                if 'baidu_api' in profile:
                    if 'app_key' in profile['baidu_api']:
                        config['app_key'] = profile['baidu_api']['app_key']
                    if 'app_secret' in profile['baidu_api']:
                        config['app_secret'] = profile['baidu_api']['app_secret']
        return config

    def get_token(self):
        # Check the access_token expires or not
        # Why minus 30, I don't know, this is how official sample do
        if self.current_time + self.expires_in - 30 > int(time.time()):
            return

        URL = 'https://aip.baidubce.com/oauth/2.0/token'
        params = urllib.urlencode({'grant_type':    'client_credentials',
                                   'client_id':     self.app_key,
                                   'client_secret': self.app_secret})
        r = requests.get(URL, params=params)
        try:
            r.raise_for_status()
            self.access_token = r.json()['access_token']
            self.expires_in = int(r.json()['expires_in'])
            self.current_time = int(time.time())
            return
        except requests.exceptions.HTTPError:
            self._logger.critical('Token request failed with response: %r', r.text, exc_info=True)
            return

    def transcribe(self, fp):
        try:
            wav_file = wave.open(fp, 'rb')
        except IOError:
            self._logger.critical('wav file not found: %s', fp, exc_info=True)
            return []
        n_frames = wav_file.getnframes()
        frame_rate = wav_file.getframerate()
        audio = wav_file.readframes(n_frames)
        base_data = base64.b64encode(audio)
        self.get_token()
        data = {'format':  'wav',
                'token':   self.access_token,
                'len':     len(audio),
                'rate':    frame_rate,
                'speech':  base_data,
                'cuid':    hashlib.md5(self.access_token.encode()).hexdigest(),
                'channel': 1}
        data = json.dumps(data)
        r = requests.post('http://vop.baidu.com/server_api', data=data,
                          headers={'content-type': 'application/json'})
        try:
            r.raise_for_status()
            text = ''
            if 'result' in r.json():
                text = r.json()['result'][0].encode('utf-8')
        except requests.exceptions.HTTPError:
            self._logger.critical('Request failed with response: %r', r.text, exc_info=True)
            return []
        except requests.exceptions.RequestException:
            self._logger.critical('Request failed.', exc_info=True)
            return []
        except ValueError as e:
            self._logger.critical('Cannot parse response: %s', e.args[0])
            return []
        except KeyError:
            self._logger.critical('Cannot parse response.', exc_info=True)
            return []
        else:
            transcribed = []
            if text:
                transcribed.append(text.upper())
            self._logger.info('Transcribed: %s' % transcribed)
            return transcribed

    @classmethod
    def is_available(cls):
        return diagnose.check_network_connection()


def get_engine_by_slug(slug=None):
    """
    Returns:
        An STT Engine implementation available on the current platform

    Raises:
        ValueError if no speaker implementation is supported on this platform
    """

    if not slug or type(slug) is not str:
        raise TypeError("Invalid slug '%s'", slug)

    selected_engines = filter(lambda engine: hasattr(engine, "SLUG") and
                              engine.SLUG == slug, get_engines())
    if len(selected_engines) == 0:
        raise ValueError("No STT engine found for slug '%s'" % slug)
    else:
        if len(selected_engines) > 1:
            print(("WARNING: Multiple STT engines found for slug '%s'. " +
                   "This is most certainly a bug.") % slug)
        engine = selected_engines[0]
        if not engine.is_available():
            raise ValueError(("STT engine '%s' is not available (due to " +
                              "missing dependencies, missing " +
                              "dependencies, etc.)") % slug)
        return engine


def get_engines():
    def get_subclasses(cls):
        subclasses = set()
        for subclass in cls.__subclasses__():
            subclasses.add(subclass)
            subclasses.update(get_subclasses(subclass))
        return subclasses
    return [tts_engine for tts_engine in
            list(get_subclasses(AbstractSTTEngine))
            if hasattr(tts_engine, 'SLUG') and tts_engine.SLUG]
