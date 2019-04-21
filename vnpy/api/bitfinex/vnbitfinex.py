# encoding: UTF-8
"""
author：lynnwong
date:2019-04

"""

from __future__ import print_function
import json
import requests
import traceback
import ssl
from threading import Thread
from queue import Queue, Empty
import time
import hmac
import base64
import hashlib
import websocket

from six.moves import input


WEBSOCKET_V2_URL = 'wss://api.bitfinex.com/ws/2'
RESTFUL_V1_URL = 'https://api.bitfinex.com/v1'
RESTFUL_V1_DOMAIN = 'https://api.bitfinex.com'


########################################################################
class BitfinexApi(object):
    """"""

    #----------------------------------------------------------------------
    def __init__(self):
        """Constructor"""
        self.ws = None
        self.thread = None
        self.active = False

        self.restQueue = Queue()
        self.restThread = None

        self.apiKey = ""
        self.secretKey = ""



    #----------------------------------------------------------------------
    def start(self):
        """"""
        self.ws = websocket.create_connection(WEBSOCKET_V2_URL,
                                              sslopt={'cert_reqs': ssl.CERT_NONE})

        self.active = True
        self.thread = Thread(target=self.run)
        self.thread.start()

        self.restThread = Thread(target=self.runRest)
        self.restThread.start()

        self.onConnect()

    #----------------------------------------------------------------------
    def reconnect(self):
        """"""
        self.ws = websocket.create_connection(WEBSOCKET_V2_URL,
                                              sslopt={'cert_reqs': ssl.CERT_NONE})

        self.onConnect()

    #----------------------------------------------------------------------
    def run(self):
        """"""
        while self.active:
            try:
                stream = self.ws.recv()
                data = json.loads(stream)
                self.onData(data)
            except:
                msg = traceback.format_exc()
                self.onError(msg)
                self.reconnect()

    #----------------------------------------------------------------------
    def close(self):
        """"""
        self.active = False

        if self.thread:
            self.thread.join()

        if self.restThread:
            self.thread.join()

    #----------------------------------------------------------------------
    def onConnect(self):
        """"""
        print('connected')

    #----------------------------------------------------------------------
    def onData(self, data):
        """"""
        print(data)

    #----------------------------------------------------------------------
    def onError(self, msg):
        """"""
        print(msg)

    #----------------------------------------------------------------------
    def sendReq(self, req):
        """"""
        self.ws.send(json.dumps(req))

    #----------------------------------------------------------------------
    def sendRestReq(self, path, callback, post=False):
        """"""
        self.restQueue.put((path, callback,post))




    #----------------------------------------------------------------------
    def runRest(self):
        """"""
        while self.active:
            try:
                path, callback, post = self.restQueue.get(timeout=1)
                if post:
                    self.httpPost(path, callback)
                else:
                    self.httpGet(path, callback)
            except Empty:
                pass
            except Exception as e:
                print(traceback.format_exc())

    #----------------------------------------------------------------------
    def httpGet(self, path, callback):
        """"""
        url = RESTFUL_V1_URL + path
        resp = requests.get(url)
        callback(resp.json())

    def __signature(self, payload):
        j = json.dumps(payload)
        data = base64.standard_b64encode(j.encode('utf8'))

        h = hmac.new(self.secretKey.encode('utf8'), data, hashlib.sha384)
        signature = h.hexdigest()
        return {
            "X-BFX-APIKEY": self.apiKey,
            "X-BFX-SIGNATURE": signature,
            "X-BFX-PAYLOAD": data
        }



    def _post(self, path, params):
        body = params
        rawBody = json.dumps(body)
        headers = self.__signature(body)
        url = RESTFUL_V1_DOMAIN + path
        resp = requests.post(url, headers=headers, data=rawBody, verify=True)

        return resp


    def httpPost(self, path, callback):
        """"""
        if path.startswith("/"):
            v1_path = "/v1" + path
        else:
            v1_path = '/v1/' + path

        payload = {
            'request': v1_path,
            'nonce': str(int(time.time() * 1000000)) # nonce
        }
        resp = self._post(v1_path, payload)
        callback(resp.json())

    # ==========================================非行情的 API 都用 RESTAPI 实现
    def _sendRestReq(self, path, post=False, params=None):
        if post:
            return self._httpPost(path, params)
        else:
            return self._httpGet(path)

    def _httpGet(self, path):
        """"""
        url = RESTFUL_V1_URL + path
        resp = requests.get(url)
        return resp.json()
    # {'symbol': 'tEOSUSD', 'side': 'buy', 'type': '限价', 'amount': '7', 'price': '3.8', 'exchange': 'BITFINEX'}
    def _httpPost(self, path, params):
        """"""
        payload = {
            'request': "/v1" + path,
            'nonce': str(int(time.time() * 1000000))  # nonce
        }
        if isinstance(params, dict):
            for k, v in params.items():
                payload[k] = v
        print("payload",payload)
        resp = self.post_(path, payload)
        return resp.json()

    def post_(self, path, params):
        body = params
        rawBody = json.dumps(body)
        headers = self.__signature(body)
        url = RESTFUL_V1_URL + path
        resp = requests.post(url, headers=headers, data=rawBody, verify=True)

        return resp



