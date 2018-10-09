# encoding: UTF-8

'''
vnpy.api.bitmex的gateway接入
'''
from __future__ import print_function

import os
import json
import hashlib
import time
import traceback
from datetime import datetime, timedelta
from copy import copy
from math import pow

from vnpy.api.bitmex import BitmexRestApi, BitmexWebsocketApiWithHeartbeat as BitmexWebsocketApi
from vnpy.api.bitmex.utils import hmac_new
from vnpy.trader.vtGateway import *
from vnpy.trader.vtFunction import getJsonPath, getTempPath

# 委托状态类型映射
statusMapReverse = {}
statusMapReverse['New'] = STATUS_NOTTRADED
statusMapReverse['Partially filled'] = STATUS_PARTTRADED
statusMapReverse['Filled'] = STATUS_ALLTRADED
statusMapReverse['Canceled'] = STATUS_CANCELLED
statusMapReverse['Rejected'] = STATUS_REJECTED

# 方向映射
directionMap = {}
directionMap[DIRECTION_LONG] = 'Buy'
directionMap[DIRECTION_SHORT] = 'Sell'
directionMapReverse = {v:k for k,v in directionMap.items()}

# 价格类型映射
priceTypeMap = {}
priceTypeMap[PRICETYPE_LIMITPRICE] = 'Limit'
priceTypeMap[PRICETYPE_MARKETPRICE] = 'Market'

########################################################################
class BitmexGateway(VtGateway):
    """Bitfinex接口"""

    #----------------------------------------------------------------------
    def __init__(self, eventEngine, gatewayName=''):
        """Constructor"""
        super(BitmexGateway, self).__init__(eventEngine, gatewayName)

        self.restApi = RestApi(self)
        self.wsApi = WebsocketApi(self)

        self.qryEnabled = False         # 是否要启动循环查询

        self.fileName = self.gatewayName + '_connect.json'
        self.filePath = getJsonPath(self.fileName, __file__)

    #----------------------------------------------------------------------
    def connect(self):
        """连接"""
        try:
            f = open(self.filePath, "r")
        except IOError:
            log = VtLogData()
            log.gatewayName = self.gatewayName
            log.logContent = u'读取连接配置出错，请检查'
            self.onLog(log)
            return

        # 解析json文件
        setting = json.load(f)
        try:
            apiKey = str(setting['apiKey'])
            apiSecret = str(setting['apiSecret'])
            sessionCount = int(setting['sessionCount'])
            symbols = setting['symbols']
        except KeyError:
            log = VtLogData()
            log.gatewayName = self.gatewayName
            log.logContent = u'连接配置缺少字段，请检查'
            self.onLog(log)
            return

        # 创建行情和交易接口对象
        self.restApi.connect(apiKey, apiSecret, sessionCount)
        self.wsApi.connect(apiKey, apiSecret, symbols)

    #----------------------------------------------------------------------
    def subscribe(self, subscribeReq):
        """订阅行情"""
        pass

    #----------------------------------------------------------------------
    def sendOrder(self, orderReq):
        """发单"""
        return self.restApi.sendOrder(orderReq)

    #----------------------------------------------------------------------
    def cancelOrder(self, cancelOrderReq):
        """撤单"""
        self.restApi.cancelOrder(cancelOrderReq)

    #----------------------------------------------------------------------
    def close(self):
        """关闭"""
        self.restApi.close()
        self.wsApi.close()
    
    #----------------------------------------------------------------------
    def initQuery(self):
        """初始化连续查询"""
        if self.qryEnabled:
            # 需要循环的查询函数列表
            self.qryFunctionList = [self.queryAccount]

            self.qryCount = 0           # 查询触发倒计时
            self.qryTrigger = 1         # 查询触发点
            self.qryNextFunction = 0    # 上次运行的查询函数索引

            self.startQuery()

    #----------------------------------------------------------------------
    def query(self, event):
        """注册到事件处理引擎上的查询函数"""
        self.qryCount += 1

        if self.qryCount > self.qryTrigger:
            # 清空倒计时
            self.qryCount = 0

            # 执行查询函数
            function = self.qryFunctionList[self.qryNextFunction]
            function()

            # 计算下次查询函数的索引，如果超过了列表长度，则重新设为0
            self.qryNextFunction += 1
            if self.qryNextFunction == len(self.qryFunctionList):
                self.qryNextFunction = 0

    #----------------------------------------------------------------------
    def startQuery(self):
        """启动连续查询"""
        self.eventEngine.register(EVENT_TIMER, self.query)

    #----------------------------------------------------------------------
    def setQryEnabled(self, qryEnabled):
        """设置是否要启动循环查询"""
        self.qryEnabled = qryEnabled

    def initPosition(self, vtSymbol):
        pass

    def queryPosition(self):
        pass
        
    def loadHistoryBar(self, vtSymbol, type_, size= None, since = None):
        KlinePeriodMap = {}
        KlinePeriodMap['1min'] = '1m'
        KlinePeriodMap['5min'] = '5m'
        KlinePeriodMap['60min'] = '1h'
        KlinePeriodMap['1day'] = '1d'
        if type_ not in KlinePeriodMap.keys():
            self.writeLog("不支持的历史数据初始化方法，请检查type_参数")
            self.writeLog("BITMEX Type_ hint：1min,5min,60min,1day")
            return '-1'

        symbol= vtSymbol.split(VN_SEPARATOR)[0]
        return self.restApi.rest_future_bar(symbol, KlinePeriodMap[type_], size, since)

    def qryAllOrders(self, vtSymbol, order_id, status= None):
        pass

########################################################################
class RestApi(BitmexRestApi):
    """REST API实现"""

    #----------------------------------------------------------------------
    def __init__(self, gateway):
        """Constructor"""
        super(RestApi, self).__init__()

        self.gateway = gateway                  # gateway对象
        self.gatewayName = gateway.gatewayName  # gateway对象名称
        
        self.orderId = 1000000
        self.date = int(datetime.now().strftime('%y%m%d%H%M%S')) * self.orderId
        
    #----------------------------------------------------------------------
    def connect(self, apiKey, apiSecret, sessionCount):
        """连接服务器"""
        self.init(apiKey, apiSecret)
        self.start(sessionCount)
        
        self.writeLog(u'REST API启动成功')
    
    #----------------------------------------------------------------------
    def writeLog(self, content):
        """发出日志"""
        log = VtLogData()
        log.gatewayName = self.gatewayName
        log.logContent = content
        self.gateway.onLog(log)
    
    #----------------------------------------------------------------------
    def sendOrder(self, orderReq):
        """"""
        self.orderId += 1
        orderId = self.date + self.orderId
        vtOrderID = VN_SEPARATOR.join([self.gatewayName, str(orderId)])
        symbol = orderReq.symbol.split(':')[0]
        
        req = {
            'symbol': orderReq.symbol,
            'side': directionMap[orderReq.direction],
            'ordType': priceTypeMap[orderReq.priceType],            
            'price': orderReq.price,
            'orderQty': orderReq.volume,
            'clOrdID': str(orderId)
        }

        self.addReq('POST', '/order', self.onSendOrder, postdict=req)
        
        return vtOrderID
    
    #----------------------------------------------------------------------
    def cancelOrder(self, cancelOrderReq):
        """"""
        orderID = cancelOrderReq.orderID
        if orderID.isdigit():
            req = {'clOrdID': orderID}
        else:
            req = {'orderID': orderID}
        
        self.addReq('DELETE', '/order', self.onCancelOrder, params=req)

    #----------------------------------------------------------------------
    def onSendOrder(self, data, reqid):
        """
        https://www.bitmex.com:443 "POST /api/v1/order HTTP/1.1" 200 None
        {'multiLegReportingType': 'SingleSecurity', 'displayQty': None, 'workingIndicator': True, 'leavesQty': 1, 'ordRejReason': '', 
        'transactTime': '2018-10-08T02:38:01.201Z', 'triggered': '', 'stopPx': None, 'ordStatus': 'New', 'orderQty': 1, 'cumQty': 0, 
        'symbol': 'EOSZ18', 'currency': 'XBT', 'clOrdID': '181008103701000001', 'ordType': 'Limit', 'pegPriceType': '', 'execInst': '', 
        'orderID': '53913329-7b22-ef10-5a90-457998c1da96', 'simpleCumQty': 0, 'price': 7.17e-05, 'text': 'Submitted via API.', 'contingencyType': '', 
        'exDestination': 'XBME', 'avgPx': None, 'side': 'Buy', 'simpleOrderQty': None, 'timestamp': '2018-10-08T02:38:01.201Z', 'clOrdLinkID': '', 
        'account': 705899, 'settlCurrency': 'XBt', 'simpleLeavesQty': 1, 'timeInForce': 'GoodTillCancel', 'pegOffsetValue': None}
        """
        pass
        # print(data, reqid)
    
    #----------------------------------------------------------------------
    def onCancelOrder(self, data, reqid):
        """
        https://www.bitmex.com:443 "DELETE /api/v1/order?clOrdID=181008103701000001 HTTP/1.1" 200 None
        {'multiLegReportingType': 'SingleSecurity', 'displayQty': None, 'workingIndicator': False, 'leavesQty': 0, 'ordRejReason': '', 
        'transactTime': '2018-10-08T02:38:01.201Z', 'triggered': '', 'stopPx': None, 'ordStatus': 'Canceled', 'orderQty': 1, 'cumQty': 0, 
        'symbol': 'EOSZ18', 'currency': 'XBT', 'clOrdID': '181008103701000001', 'ordType': 'Limit', 'pegPriceType': '', 'execInst': '', 
        'orderID': '53913329-7b22-ef10-5a90-457998c1da96', 'simpleCumQty': 0, 'price': 7.17e-05, 'text': 'Canceled: Canceled via API.\nSubmitted via API.', 
        'contingencyType': '', 'exDestination': 'XBME', 'avgPx': None, 'side': 'Buy', 'simpleOrderQty': None, 'timestamp': '2018-10-08T02:38:14.351Z', 
        'clOrdLinkID': '', 'account': 705899, 'settlCurrency': 'XBt', 'simpleLeavesQty': 0, 'timeInForce': 'GoodTillCancel', 'pegOffsetValue': None}
        """
        pass
    
    #----------------------------------------------------------------------
    def onError(self, code, error):
        """"""
        e = VtErrorData()
        e.errorID = code
        e.errorID = error
        self.gateway.onError(e)
    
    def rest_future_bar(self,symbol, type_, size, since = None):
        kline = self.restKline(symbol, type_, size, since)
        return kline
        

########################################################################
class WebsocketApi(BitmexWebsocketApi):
    """"""

    #----------------------------------------------------------------------
    def __init__(self, gateway):
        """Constructor"""
        super(WebsocketApi, self).__init__()
        
        self.gateway = gateway
        self.gatewayName = gateway.gatewayName
        
        self.apiKey = ''
        self.apiSecret = ''
        
        self.callbackDict = {
            'trade': self.onTick,
            'orderBook10': self.onDepth,
            'execution': self.onTrade,
            'order': self.onOrder,
            'position': self.onPosition,
            'margin': self.onAccount,
            'instrument': self.onContract
        }
        
        self.tickDict = {}
        self.accountDict = {}
        self.orderDict = {}
        self.tradeSet = set()
        
    #----------------------------------------------------------------------
    def connect(self, apiKey, apiSecret, symbols):
        """"""
        self.apiKey = apiKey
        self.apiSecret = apiSecret
        
        for symbol in symbols:
            tick = VtTickData()
            tick.gatewayName = self.gatewayName
            tick.symbol = symbol
            tick.exchange = EXCHANGE_BITMEX
            tick.vtSymbol = VN_SEPARATOR.join([tick.symbol, tick.gatewayName])
            self.tickDict[symbol] = tick
            
        self.start()
    
    #----------------------------------------------------------------------
    def onConnect(self):
        """连接回调"""
        self.writeLog(u'Websocket API连接成功')
        self.authenticate()
    
    #----------------------------------------------------------------------
    def onData(self, data):
        """数据回调"""
        if 'request' in data:
            req = data['request']
            success = data.get("success", False)
            
            if req['op'] == 'authKey':
                if success:
                    self.writeLog(u'Websocket API验证授权成功')
                    self.subscribe()
                else:
                    self.writeLog(u'Websocket API验证失败,退出连接')
                    self.close()
            
        elif 'table' in data:
            name = data['table']
            callback = self.callbackDict[name]
            
            if isinstance(data['data'], list):
                for d in data['data']:
                    callback(d)
            else:
                callback(data['data'])
            
            #if data['action'] == 'update' and data['table'] != 'instrument':
                #callback(data['data'])
            #elif data['action'] == 'partial':
                #for d in data['data']:
                    #callback(d)

    
    #----------------------------------------------------------------------
    def onError(self, msg):
        """错误回调"""
        self.writeLog(msg)
    
    #----------------------------------------------------------------------
    def writeLog(self, content):
        """发出日志"""
        log = VtLogData()
        log.gatewayName = self.gatewayName
        log.logContent = content
        self.gateway.onLog(log)    

    #----------------------------------------------------------------------
    def authenticate(self):
        """
        {'success': True, 'request': {'op': 'authKey', 'args': ['****key******', 15******25, 'cf7*********86f']}}
        """
        expires = int(time.time())
        method = 'GET'
        path = '/realtime'
        msg = method + path + str(expires)
        signature = hmac_new(self.apiSecret, msg, digestmod=hashlib.sha256).hexdigest()
        
        req = {
            'op': 'authKey', 
            'args': [self.apiKey, expires, signature]
        }
        self.sendReq(req)

    #----------------------------------------------------------------------
    def subscribe(self):
        """"""
        req = {
            'op': 'subscribe',
            'args': ['instrument', 'trade', 'orderBook10', 'execution', 'order', 'position', 'margin']
        }
        self.sendReq(req)
    
    #----------------------------------------------------------------------
    def onTick(self, d):
        """
        {'data': [{'grossValue': 15147, 'symbol': 'XBTUSD', 'trdMatchID': 'ea9528d0-e7f3-d1e6-5c8b-24b1bdf7f869', 'homeNotional': 0.00015147, 
        'tickDirection': 'ZeroPlusTick', 'foreignNotional': 1, 'timestamp': '2018-10-09T03:21:02.225Z', 'size': 1, 'price': 6602, 'side': 'Buy'}], 
        'table': 'trade', 'action': 'insert'}

        {'data': [{'grossValue': None, 'symbol': '.XBTUSDPI8H', 'trdMatchID': '00000000-0000-0000-0000-000000000000', 'homeNotional': None, 
        'tickDirection': 'MinusTick', 'foreignNotional': None, 'timestamp': '2018-10-08T20:00:00.000Z', 'size': 0, 'price': 6.6e-05, 'side': 'Buy'}, 
         {'grossValue': 18587772, 'symbol': 'XRPZ18', 'trdMatchID': 'cf95c5c3-c490-b564-65fe-ac8c52455bab', 'homeNotional': 2484, 'tickDirection': 'ZeroPlusTick', 
         'foreignNotional': 0.18587772, 'timestamp': '2018-10-09T03:20:26.958Z', 'size': 2484, 'price': 7.483e-05, 'side': 'Buy'}, 
        {'grossValue': 106036000, 'symbol': 'XBTUSD', 'trdMatchID': 'dd0452a6-592f-c78a-2623-7139e16ca26d', 'homeNotional': 1.06036, 'tickDirection': 'ZeroMinusTick', 
        'foreignNotional': 7000, 'timestamp': '2018-10-09T03:20:50.908Z', 'size': 7000, 'price': 6601.5, 'side': 'Sell'}], 
        'types': {'grossValue': 'long', 'symbol': 'symbol', 'trdMatchID': 'guid', 'homeNotional': 'float', 'tickDirection': 'symbol', 'foreignNotional': 'float', 
        'timestamp': 'timestamp', 'size': 'long', 'price': 'float', 'side': 'symbol'}, 'foreignKeys': {'symbol': 'instrument', 'side': 'side'}, 
        'table': 'trade', 'action': 'partial','attributes': {'symbol': 'grouped', 'timestamp': 'sorted'}, 'filter': {}, 'keys': []}
        """
        symbol = d['symbol']

        tick = self.tickDict.get(symbol, None)
        if not tick:
            return
        
        tick.lastPrice = d['price']
        
        date, time = str(d['timestamp']).split('T')
        tick.date = date.replace('-', '')
        tick.time = time.replace('Z', '')
        tick.datetime = datetime.strptime(' '.join([tick.date, tick.time]), '%Y%m%d %H:%M:%S.%f')
        self.gateway.onTick(tick)

    #----------------------------------------------------------------------
    def onDepth(self, d):
        """
        {'data': [{
        'bids': [[6605.5, 15912], [6605, 125], [6604.5, 125], [6604, 13159], [6603.5, 22975], [6603, 28639], [6602.5, 5429], [6602, 150], [6601.5, 38100], [6601, 15459]], 
        'symbol': 'XBTZ18', 
        'asks': [[6606, 392365], [6606.5, 229102], [6607, 323], [6607.5, 12612], [6608, 20000], [6609, 14500], [6609.5, 102352], [6610, 52487], [6610.5, 2225], [6611.5, 10025]], 
        'timestamp': '2018-10-09T03:21:04.409Z'}], 'table': 'orderBook10', 'action': 'update'}

        """
        symbol = d['symbol']
        tick = self.tickDict.get(symbol, None)
        if not tick:
            return
        
        for n, buf in enumerate(d['bids'][:5]):
            price, volume = buf
            tick.__setattr__('bidPrice%s' %(n+1), price)
            tick.__setattr__('bidVolume%s' %(n+1), volume)
        
        for n, buf in enumerate(d['asks'][:5]):
            price, volume = buf
            tick.__setattr__('askPrice%s' %(n+1), price)
            tick.__setattr__('askVolume%s' %(n+1), volume)                
        
        date, time = str(d['timestamp']).split('T')
        tick.date = date.replace('-', '')
        tick.time = time.replace('Z', '')
        tick.datetime = datetime.strptime(' '.join([tick.date, tick.time]), '%Y%m%d %H:%M:%S.%f')
        
        self.gateway.onTick(tick)
    
    #----------------------------------------------------------------------
    def onTrade(self, d):
        """
        {'data': [], 'types': {
            'lastMkt': 'symbol', 'symbol': 'symbol', 'ordType': 'symbol', 'stopPx': 'float', 'execType': 'symbol', 'trdMatchID': 'guid', 'contingencyType': 'symbol', 
            'lastQty': 'long', 'side': 'symbol', 'avgPx': 'float', 'pegPriceType': 'symbol', 'price': 'float', 
            'ordRejReason': 'symbol', 'pegOffsetValue': 'float', 'exDestination': 'symbol', 'execID': 'guid', 'workingIndicator': 'boolean', 
            'execComm': 'long', 'clOrdLinkID': 'symbol', 'orderQty': 'long', 'multiLegReportingType': 'symbol', 'displayQty': 'long', 'account': 'long', 
            'clOrdID': 'symbol', 'orderID': 'guid', 'lastPx': 'float', 'simpleCumQty': 'float', 'underlyingLastPx': 'float', 'simpleLeavesQty': 'float', 
            'foreignNotional': 'float', 'cumQty': 'long', 'transactTime': 'timestamp', 'timestamp': 'timestamp', 'settlCurrency': 'symbol', 'text': 'symbol', 
            'timeInForce': 'symbol', 'execInst': 'symbol', 'simpleOrderQty': 'float', 'ordStatus': 'symbol', 'leavesQty': 'long', 'execCost': 'long', 'lastLiquidityInd': 'symbol', 
            'homeNotional': 'float', 'triggered': 'symbol', 'commission': 'float', 'tradePublishIndicator': 'symbol', 'currency': 'symbol'}, 
            'foreignKeys': {'ordStatus': 'ordStatus', 'symbol': 'instrument', 'side': 'side'}, 
            'table': 'execution', 'action': 'partial', 'attributes': {'transactTime': 'sorted', 'execID': 'grouped', 'account': 'grouped', 'execType': 'grouped'}, 
            'filter': {'account': 705899}, 'keys': ['execID']}
        """
        if not d['lastQty']:
            return
        
        tradeID = d['execID']
        if tradeID in self.tradeSet:
            return
        self.tradeSet.add(tradeID)
        
        trade = VtTradeData()
        trade.gatewayName = self.gatewayName
        
        trade.symbol = d['symbol']
        trade.exchange = EXCHANGE_BITMEX
        trade.vtSymbol = VN_SEPARATOR.join([trade.symbol, trade.gatewayName])
        if d['clOrdID']:
            orderID = d['clOrdID']
        else:
            orderID = d['orderID']
        trade.orderID = orderID
        trade.vtOrderID = VN_SEPARATOR.join([trade.gatewayName, trade.orderID])
        
        
        trade.tradeID = tradeID
        trade.vtTradeID = VN_SEPARATOR.join([trade.gatewayName, trade.tradeID])
        
        trade.direction = directionMapReverse[d['side']]
        trade.price = d['lastPx']
        trade.volume = d['lastQty']
        trade.tradeTime = d['timestamp'][0:10].replace('-', '')
        
        self.gateway.onTrade(trade)
    
    #----------------------------------------------------------------------
    def onOrder(self, d):
        """
        {'data': [], 'types': {'cumQty': 'long', 'stopPx': 'float', 'symbol': 'symbol', 'ordType': 'symbol', 'multiLegReportingType': 'symbol', 
        'displayQty': 'long', 'triggered': 'symbol', 'clOrdID': 'symbol', 'contingencyType': 'symbol', 'orderID': 'guid', 'timestamp': 'timestamp', 
        'simpleCumQty': 'float', 'text': 'symbol', 'simpleLeavesQty': 'float', 'orderQty': 'long', 'account': 'long', 'transactTime': 'timestamp', 
        'settlCurrency': 'symbol', 'clOrdLinkID': 'symbol', 'avgPx': 'float', 'timeInForce': 'symbol', 'execInst': 'symbol', 'simpleOrderQty': 'float', 
        'ordStatus': 'symbol', 'pegPriceType': 'symbol', 'price': 'float', 'leavesQty': 'long', 'ordRejReason': 'symbol', 'pegOffsetValue': 'float', 
        'exDestination': 'symbol', 'side': 'symbol', 'workingIndicator': 'boolean', 'currency': 'symbol'}, 
        'foreignKeys': {'ordStatus': 'ordStatus', 'symbol': 'instrument', 'side': 'side'}, 
        'table': 'order', 'action': 'partial', 
        'attributes': {'ordStatus': 'grouped', 'workingIndicator': 'grouped', 'account': 'grouped', 'orderID': 'grouped'}, 'filter': {'account': 705899}, 'keys': ['orderID']}
        """
        if 'ordStatus' not in d:
            return
        
        sysID = d['orderID']
        if sysID in self.orderDict:
            order = self.orderDict[sysID]
        else:
            order = VtOrderData()
            order.gatewayName = self.gatewayName
            
            order.symbol = d['symbol']
            order.exchange = EXCHANGE_BITMEX
            order.vtSymbol = VN_SEPARATOR.join([order.symbol, order.gatewayName])
            
            if d['clOrdID']:
                orderID = d['clOrdID']
            else:
                orderID = sysID
            order.orderID = orderID
            order.vtOrderID = VN_SEPARATOR.join([self.gatewayName, order.orderID])
            
            order.direction = directionMapReverse[d['side']]
            
            if d['price']:
                order.price = d['price']
                
            order.totalVolume = d['orderQty']
            order.orderTime = d['timestamp'][0:10].replace('-', '')
    
            self.orderDict[sysID] = order
        
        order.tradedVolume = d.get('cumQty', order.tradedVolume)
        order.status = statusMapReverse.get(d['ordStatus'], STATUS_UNKNOWN)
    
        self.gateway.onOrder(order)        

    #----------------------------------------------------------------------
    def onPosition(self, d):
        """
        {'data': [{'riskValue': 0, 'posComm': 0, 'posCost2': 0, 'riskLimit': 5000000000, 'posState': '', 'execBuyQty': 0, 'currentTimestamp': '2018-10-09T03:00:00.831Z', 
        'prevClosePrice': 0.0008899, 'initMarginReq': 0.05, 'realisedTax': 0, 'posInit': 0, 'prevRealisedPnl': 90, 'grossExecCost': 0, 'simpleCost': 0, 'indicativeTaxRate': 0, 
        'prevUnrealisedPnl': 0, 'execSellQty': 0, 'realisedGrossPnl': 0, 'rebalancedPnl': -90, 'unrealisedRoePcnt': 0, 'simpleQty': 0, 'realisedPnl': 90, 'maintMarginReq': 0.025, 
        'simpleValue': 0, 'simplePnl': 0, 'posAllowance': 0, 'sessionMargin': 0, 'foreignNotional': 0, 'currentQty': 0, 'unrealisedGrossPnl': 0, 'marginCallPrice': None, 'currentCost': 0, 
        'liquidationPrice': None, 'bankruptPrice': None, 'posCost': 0, 'varMargin': 0, 'breakEvenPrice': None, 'crossMargin': True, 'posLoss': 0, 'lastValue': 0, 'unrealisedCost': 0, 
        'targetExcessMargin': 0, 'unrealisedTax': 0, 'realisedCost': 0, 'avgEntryPrice': None, 'symbol': 'EOSZ18', 'isOpen': False, 'maintMargin': 0, 'posCross': 0, 'currentComm': -90, 
        'grossOpenCost': 0, 'initMargin': 0, 'posMaint': 0, 'openOrderSellQty': 0, 'openOrderBuyCost': 0, 'unrealisedPnl': 0, 'posMargin': 0, 'lastPrice': None, 'indicativeTax': 0, 
        'execBuyCost': 0, 'underlying': 'EOS', 'openOrderBuyPremium': 0, 'execSellCost': 0, 'openingTimestamp': '2018-10-09T03:00:00.000Z', 'deleveragePercentile': None, 'execComm': 0, 
        'execQty': 0, 'openOrderSellCost': 0, 'openingCost': 0, 'openOrderBuyQty': 0, 'avgCostPrice': None, 'openingQty': 0, 'taxableMargin': 0, 'shortBankrupt': 0, 'openingComm': -90, 
        'markValue': 0, 'markPrice': None, 'quoteCurrency': 'XBT', 'timestamp': '2018-10-09T03:00:00.831Z', 'unrealisedPnlPcnt': 0, 'account': 705899, 'longBankrupt': 0, 'execCost': 0, 
        'grossOpenPremium': 0, 'homeNotional': 0, 'openOrderSellPremium': 0, 'commission': 0.0025, 'simplePnlPcnt': 0, 'currency': 'XBt', 'leverage': 20, 'taxBase': 0},], 
        
        'types': {'riskValue': 'long', 'posComm': 'long', 'posCost2': 'long', 'riskLimit': 'long', 'posState': 'symbol', 'execBuyQty': 'long', 'currentTimestamp': 'timestamp', 
        'prevClosePrice': 'float', 'initMarginReq': 'float', 'realisedTax': 'long', 'posInit': 'long', 'prevRealisedPnl': 'long', 'grossExecCost': 'long', 'simpleCost': 'float', 'indicativeTaxRate': 'float', 
        'prevUnrealisedPnl': 'long', 'execSellQty': 'long', 'realisedGrossPnl': 'long', 'rebalancedPnl': 'long', 'unrealisedRoePcnt': 'float', 'simpleQty': 'float', 'realisedPnl': 'long', 'maintMarginReq': 'float', 
        'simpleValue': 'float', 'simplePnl': 'float', 'posAllowance': 'long', 'sessionMargin': 'long', 'foreignNotional': 'float', 'currentQty': 'long', 'unrealisedGrossPnl': 'long', 'marginCallPrice': 'float',
         'currentCost': 'long', 'liquidationPrice': 'float', 'bankruptPrice': 'float', 'posCost': 'long', 'varMargin': 'long', 'breakEvenPrice': 'float', 'crossMargin': 'boolean', 'posLoss': 'long', 
         'lastValue': 'long', 'unrealisedCost': 'long', 'targetExcessMargin': 'long', 'unrealisedTax': 'long', 'realisedCost': 'long', 'avgEntryPrice': 'float', 'symbol': 'symbol', 'isOpen': 'boolean', 
         'maintMargin': 'long', 'posCross': 'long', 'currentComm': 'long', 'grossOpenCost': 'long', 'initMargin': 'long', 'posMaint': 'long', 'openOrderSellQty': 'long', 'openOrderBuyCost': 'long', 
         'unrealisedPnl': 'long', 'posMargin': 'long', 'lastPrice': 'float', 'indicativeTax': 'long', 'execBuyCost': 'long', 'underlying': 'symbol', 'openOrderBuyPremium': 'long', 'execSellCost': 'long', 
         'openingTimestamp': 'timestamp', 'deleveragePercentile': 'float', 'execComm': 'long', 'execQty': 'long', 'openOrderSellCost': 'long', 'openingCost': 'long', 'openOrderBuyQty': 'long', 
         'avgCostPrice': 'float', 'openingQty': 'long', 'taxableMargin': 'long', 'shortBankrupt': 'long', 'openingComm': 'long', 'markValue': 'long', 'markPrice': 'float', 'quoteCurrency': 'symbol', 
         'timestamp': 'timestamp', 'unrealisedPnlPcnt': 'float', 'account': 'long', 'longBankrupt': 'long', 'execCost': 'long', 'grossOpenPremium': 'long', 'homeNotional': 'float', 'openOrderSellPremium': 'long', 
         'commission': 'float', 'simplePnlPcnt': 'float', 'currency': 'symbol', 'leverage': 'float', 'taxBase': 'long'}, 'foreignKeys': {'symbol': 'instrument'}, 
         'table': 'position', 'action': 'partial', 'attributes': {'underlying': 'grouped', 'quoteCurrency': 'grouped', 'symbol': 'grouped', 'account': 'sorted', 'currency': 'grouped'}, 
         'filter': {'account': 705899}, 'keys': ['account', 'symbol', 'currency']}
        """
        pos = VtPositionData()
        pos.gatewayName = self.gatewayName
        
        pos.symbol = d['symbol']
        pos.exchange = EXCHANGE_BITMEX
        pos.vtSymbol = VN_SEPARATOR.join([pos.symbol, pos.gatewayName])
        
        pos.direction = DIRECTION_NET
        pos.vtPositionName = VN_SEPARATOR.join([pos.vtSymbol, pos.direction])
        pos.position = d['currentQty']
        pos.frozen = 0      # 期货没有冻结概念，会直接反向开仓
        
        self.gateway.onPosition(pos)        
    
    #----------------------------------------------------------------------
    def onAccount(self, d):
        """
        {'data': [{'prevState': '', 'riskValue': 0, 'availableMargin': 4499912, 'state': '', 'riskLimit': 1000000000000, 'pendingDebit': 0, 'marginLeverage': 0, 
        'realisedPnl': 90, 'maintMargin': 0, 'excessMarginPcnt': 1, 'taxableMargin': 0, 'grossOpenPremium': 0, 'action': '', 'grossLastValue': 0, 'pendingCredit': 0, 
        'prevUnrealisedPnl': 0, 'amount': 4499822, 'initMargin': 0, 'syntheticMargin': 0, 'unrealisedProfit': 0, 'unrealisedPnl': 0, 'marginBalancePcnt': 1, 'account': 705899, 
        'walletBalance': 4499912, 'sessionMargin': 0, 'prevRealisedPnl': 90, 'timestamp': '2018-10-09T02:59:50.550Z', 'marginUsedPcnt': 0, 'grossExecCost': 0, 'indicativeTax': 0, 
        'varMargin': 0, 'grossOpenCost': 0, 'excessMargin': 4499912, 'marginBalance': 4499912, 'withdrawableMargin': 4499912, 'targetExcessMargin': 0, 'confirmedDebit': 0, 
        'grossComm': -90, 'commission': None, 'currency': 'XBt', 'grossMarkValue': 0}], 
        
        'types': {'prevState': 'symbol', 'riskValue': 'long', 'availableMargin': 'long', 'state': 'symbol', 'riskLimit': 'long', 'pendingDebit': 'long', 'marginLeverage': 'float', 
        'realisedPnl': 'long', 'maintMargin': 'long', 'excessMarginPcnt': 'float', 'taxableMargin': 'long','grossOpenPremium': 'long', 'action': 'symbol', 'grossLastValue': 'long', 
        'pendingCredit': 'long', 'prevUnrealisedPnl': 'long', 'amount': 'long', 'initMargin': 'long', 'syntheticMargin': 'long', 'unrealisedProfit': 'long', 'unrealisedPnl': 'long', 
        'marginBalancePcnt': 'float', 'account': 'long', 'walletBalance': 'long', 'sessionMargin': 'long', 'prevRealisedPnl': 'long', 'timestamp': 'timestamp', 'marginUsedPcnt': 'float', 
        'grossExecCost': 'long', 'indicativeTax': 'long', 'varMargin': 'long', 'grossOpenCost': 'long', 'excessMargin': 'long', 'marginBalance': 'long', 'withdrawableMargin': 'long', 
        'targetExcessMargin': 'long', 'confirmedDebit': 'long', 'grossComm': 'long', 'commission': 'float', 'currency': 'symbol', 'grossMarkValue': 'long'}, 'foreignKeys': {}, 
        
        'table': 'margin', 'action': 'partial', 'attributes': {'account': 'sorted', 'currency': 'grouped'}, 'filter': {'account': 705899}, 'keys': ['account', 'currency']}
        """
        accoundID = str(d['account'])
        
        if accoundID in self.accountDict:
            account = self.accountDict[accoundID]
        else:
            account = VtAccountData()
            account.gatewayName = self.gatewayName
        
            account.accountID = accoundID
            account.vtAccountID = VN_SEPARATOR.join([account.gatewayName, account.accountID])
            
            self.accountDict[accoundID] = account
        
        account.balance = d.get('marginBalance', account.balance)
        account.available = d.get('availableMargin', account.available)
        account.closeProfit = d.get('realisedPnl', account.closeProfit)
        account.positionProfit = d.get('unrealisedPnl', account.positionProfit)
        
        self.gateway.onAccount(account)        

    #----------------------------------------------------------------------
    def onContract(self, d):
        """
        {'data': [{'turnover': 72968598484, 'symbol': 'XBTUSD', 'volume': 4817469, 'totalTurnover': 11583681630151756, 
        'totalVolume': 849110663653, 'timestamp': '2018-10-09T03:20:50.908Z'}], 'table': 'instrument', 'action': 'update'}

        {'data': [{'highPrice': None, 'quoteToSettleMultiplier': None, 'riskLimit': None, 'relistInterval': None, 'rootSymbol': 'EVOL', 'publishTime': None, 'turnover': None, 
        'bankruptLimitUpPrice': None, 'fundingQuoteSymbol': '', 'optionStrikeRound': None, 'isQuanto': False, 'bankruptLimitDownPrice': None, 'limitUpPrice': None, 'makerFee': None, 
        'limitDownPrice': None, 'vwap': None, 'fairMethod': '', 'capped': False, 'maxPrice': None, 'lastChangePcnt': -0.0358, 'reference': 'BMEX', 'optionMultiplier': None, 'bidPrice': None, 
        'maintMargin': None, 'openValue': 0, 'prevTotalVolume': None, 'impactAskPrice': None, 'openingTimestamp': None, 'deleverage': False, 'indicativeTaxRate': None, 'timestamp': '2018-10-09T03:15:00.000Z',
         'maxOrderQty': None, 'sellLeg': '', 'indicativeFundingRate': None, 'listing': None, 'fairBasisRate': None, 'rebalanceInterval': None, 'markMethod': 'LastPrice', 'front': None, 'indicativeSettlePrice': None, 
         'lowPrice': None, 'optionUnderlyingPrice': None, 'totalVolume': None, 'inverseLeg': '', 'limit': None, 'volume': None, 'positionCurrency': '', 'sessionInterval': None, 'fundingRate': None, 
         'prevPrice24h': 4.75, 'symbol': '.EVOL7D', 'taxed': False, 'multiplier': None, 'optionStrikePrice': None, 'settle': None, 'expiry': None, 'hasLiquidity': False, 'underlyingToPositionMultiplier': None, 
         'initMargin': None, 'state': 'Unlisted', 'impactBidPrice': None, 'foreignNotional24h': None, 'lastPrice': 4.58, 'buyLeg': '', 'homeNotional24h': None, 'typ': 'MRIXXX', 'settledPrice': None, 
         'volume24h': None, 'rebalanceTimestamp': None, 'lotSize': None, 'underlying': 'ETH', 'fundingPremiumSymbol': '', 'underlyingToSettleMultiplier': None, 'takerFee': None, 
         'referenceSymbol': '.BETHXBT', 'tickSize': 0.01, 'insuranceFee': None, 'midPrice': None, 'fundingInterval': None, 'fairPrice': None, 'settlementFee': None, 'impactMidPrice': None, 
         'fundingTimestamp': None, 'underlyingSymbol': '.EVOL7D', 'markPrice': 4.58, 'quoteCurrency': 'XXX', 'closingTimestamp': None, 'riskStep': None, 'turnover24h': None, 'lastPriceProtected': None, 
         'lastTickDirection': 'ZeroPlusTick', 'settlCurrency': '', 'prevClosePrice': None, 'totalTurnover': None, 'askPrice': None, 'openInterest': None, 'publishInterval': '2000-01-01T00:05:00.000Z', 
         'fundingBaseSymbol': '', 'fairBasis': None, 'optionStrikePcnt': None, 'isInverse': False, 'calcInterval': '2000-01-08T00:00:00.000Z', 'prevTotalTurnover': None},
         'foreignKeys': {'buyLeg': 'instrument', 'sellLeg': 'instrument', 'inverseLeg': 'instrument'}, 
         'table': 'instrument', 'action': 'partial', 'attributes': {'symbol': 'unique'}, 'filter': {}, 'keys': ['symbol']}
        """
        if 'tickSize' not in d:
            return
        
        contract = VtContractData()
        contract.gatewayName = self.gatewayName
        
        contract.symbol = d['symbol']
        contract.exchange = EXCHANGE_BITMEX
        contract.vtSymbol = VN_SEPARATOR.join([contract.symbol, contract.gatewayName])
        contract.name = contract.vtSymbol
        contract.productClass = PRODUCT_FUTURES
        contract.priceTick = d['tickSize']
        contract.size = d['multiplier']

        self.gateway.onContract(contract)        

    #-----------------------------------------------------------------------
    def onClose(self):
        """接口断开"""
        self.gateway.connected = False
        self.writeLog(u'Websocket API连接断开')

#----------------------------------------------------------------------
def printDict(d):
    """"""
    print('-' * 30)
    l = d.keys()
    l.sort()
    for k in l:
        print(k, d[k])
    