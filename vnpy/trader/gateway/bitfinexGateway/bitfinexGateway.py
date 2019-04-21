# encoding: UTF-8

'''
vnpy.api.bitfinex的gateway接入
author:lynnwong
date:2019-04

'''
from __future__ import print_function
import os
import json
import hashlib
import hmac
import time
from datetime import datetime, timedelta
from copy import copy
from math import pow
import requests
import pandas as pd
from vnpy.api.bitfinex import BitfinexApi
from vnpy.trader.vtGateway import *
from vnpy.trader.vtConstant import *
from vnpy.trader.vtFunction import getJsonPath, getTempPath
from vnpy.trader.app.ctaStrategy.ctaBase import EVENT_CTA_LOG
from vnpy.trader.vtObject import *
from vnpy.trader.app.ctaStrategy.ctaBase import *


# 委托状态类型映射
statusMapReverse = {}
statusMapReverse['ACTIVE'] = STATUS_NOTTRADED
statusMapReverse['PARTIALLYFILLED'] = STATUS_PARTTRADED
statusMapReverse['EXECUTED'] = STATUS_ALLTRADED
statusMapReverse['CANCELED'] = STATUS_CANCELLED

##价格类型映射
priceTypeMap = {}

priceTypeMap[PRICETYPE_LIMITPRICE] =  'LIMIT'
priceTypeMap[PRICETYPE_MARKETPRICE] = 'MARKET'
priceTypeMap[PRICETYPE_FOK] = 'FILL-OR-KILL'

#import pdb;pdb.set_trace()

########################################################################
class BitfinexGateay(VtGateway):
    """Bitfinex接口"""

    #----------------------------------------------------------------------
    def __init__(self, eventEngine, gatewayName=''):
        """Constructor"""

        super(BitfinexGateay, self).__init__(eventEngine, gatewayName)
        self.api = GatewayApi(self)

        self.qryEnabled = False         # 是否要启动循环查询

        self.fileName = self.gatewayName + '_connect.json'
        self.filePath = getJsonPath(self.fileName, __file__)

        self.connected = False
        self.count = 0

    #----------------------------------------------------------------------
    def connect(self):
        """连接"""
        # 如果 accessKey accessSec pairs 在初始化的时候已经设置了，则不用配置文件里的了
        try:
            f = open(self.filePath)
        except IOError:
            log = VtLogData()
            log.gatewayName = self.gatewayName
            log.logContent = u'读取连接配置出错，请检查'
            self.onLog(log)
            return
        # 解析json文件
        setting = json.load(f)
        f.close()
        try:
            apiKey = str(setting['apiKey'])
            secretKey = str(setting['secretKey'])
            symbols = setting['symbols']
        except KeyError:
            log = VtLogData()
            log.gatewayName = self.gatewayName
            log.logContent = u'连接配置缺少字段，请检查'
            self.onLog(log)
            return

        if self.connected:
            return

        # 创建行情和交易接口对象
        self.api.connect(apiKey, secretKey, symbols)
        self.connected = True

    #----------------------------------------------------------------------
    def subscribe(self, subscribeReq):
        """订阅行情"""
        pass

    def sendRestReq(self, path, callback, post=False):
        return self.api.sendRestReq(path, callback, post)

    #----------------------------------------------------------------------
    def sendOrder(self, orderReq):
        """发单"""
        return self.api.sendOrder(orderReq)

    #----------------------------------------------------------------------
    def cancelOrder(self, cancelOrderReq):
        """撤单"""
        self.api.cancelOrder(cancelOrderReq)

    #----------------------------------------------------------------------
    def close(self):
        """关闭"""
        self.api.close()

    #--------------------------------重点-----------------------------------
    def qryPosition(self):
        """查询持仓"""
        self.api.onPosition()

    #----------------------------------------------------------------------
    def qryAccount(self):
        """"""
        self.api.onWallet()

    #----------------------------------------------------------------------
    def initPosition(self, vtSymbol):
        pass

    def qryAllOrders(self,vtSymbol,order_id,status=None):
        pass
    def initQuery(self):
        """初始化连续查询"""
        if self.qryEnabled:
            # 需要循环的查询函数列表
            self.qryFunctionList = [self.qryAccount]

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

    def loadHistoryBar(self,vtSymbol,type_,size = None, since = None):
        url = 'https://www.binance.co/api/v1/klines?'
        symbol = vtSymbol.split(':')[0]
        if 'USD' in symbol:
            symbol = symbol.replace('USD','USDT')
        typeMap = {}
        typeMap['1min'] = '1m'
        typeMap['5min'] = '5m'
        typeMap['15min'] = '15m'
        typeMap['30min'] = '30m'
        typeMap['60min'] = '1h'
        typeMap['120min'] = '2h'
        typeMap['240min'] = '4h'

        params = {
            'symbol': symbol,
            'interval': typeMap[type_]
        }
        if size:
            params['limit'] = size
        if since:
            params['startTime'] = since
        # if endTime:
        #     params['endTime'] = endTime

        r = requests.get(url, headers={
            'Content-Type': 'application/x-www-form-urlencoded',
            'Accept': 'application/json'
        }, params=params, timeout=10)
        text = json.loads(r.content)
        df = pd.DataFrame(text, columns=[
            "opentime", "open", "high", "low", "close", "volume", "closetime", "Quote", "trades", "buybase", "buyquote", "ignore"])
        df["datetime"] = df["opentime"].map(lambda x: datetime.fromtimestamp(x / 1000))
        df['volume'] = df['volume'].map(lambda x:float(x))
        df['open'] = df['open'].map(lambda x: float(x))
        df['high'] = df['high'].map(lambda x: float(x))
        df['low'] = df['low'].map(lambda x: float(x))
        df['close'] = df['close'].map(lambda x: float(x))

        return df

########################################################################
class GatewayApi(BitfinexApi):
    """API实现"""
    #----------------------------------------------------------------------
    def __init__(self, gateway):
        """Constructor"""
        super(GatewayApi, self).__init__()

        self.gateway = gateway                  # gateway对象
        self.gatewayName = gateway.gatewayName  # gateway对象名称
        self.symbols = []

        self.orderId = 1000000
        self.date = int(datetime.now().strftime('%y%m%d%H%M%S')) * self.orderId

        self.currencys = []
        self.tickDict = {}
        self.bidDict = {}
        self.askDict = {}
        self.orderLocalDict = {}
        self.channelDict = {}       # ChannelID : (Channel, Symbol)

        # self.apiKey = "3nreYE5Totpj4Bilr5te8aGfw3jLm3XG3paXJ0pVZUP"
        # self.secretKey = "aXOmuaDcAxV3EHcuoR4Vf4qMzBqCrnO248d633Kg5bD"

    # ----------------------------------------------------------------------
    def connect(self, apiKey, secretKey, symbols):
        """连接服务器"""
        self.apiKey = apiKey
        self.secretKey = secretKey
        self.symbols = symbols

        self.start()
        self.writeLog(u'交易API启动成功')

    #----------------------------------------------------------------------
    def onConnect(self):
        """"""
        for symbol in self.symbols:
            self.subscribe(symbol, 'ticker')
            self.subscribe(symbol, 'book')
        self.writeLog(u'行情推送订阅成功')

        # 只获取数据，不交易
        self.authenticate()
        self.writeLog(u'认证成功，交易推送订阅成功')

        self.sendRestReq('/symbols_details', self.onSymbolDetails)

    #----------------------------------------------------------------------
    def subscribe(self, symbol, channel):
        """"""
        if not symbol.startswith("t"):
            symbol = "t" + symbol

        req = {
            'event': 'subscribe',
            'channel': channel,
            'symbol': symbol
        }
        self.sendReq(req)

    #----------------------------------------------------------------------
    def authenticate(self):
        """"""
        nonce = int(time.time() * 1000000)
        authPayload = 'AUTH' + str(nonce)
        signature = hmac.new(
          self.secretKey.encode(),
          msg = authPayload.encode(),
          digestmod = hashlib.sha384
        ).hexdigest()

        req = {
          'apiKey': self.apiKey,
          'event': 'auth',
          'authPayload': authPayload,
          'authNonce': nonce,
          'authSig': signature
        }

        self.sendReq(req)

    #----------------------------------------------------------------------
    def writeLog(self, content):
        """发出日志"""
        """发出日志"""
        log = VtLogData()
        log.gatewayName = self.gatewayName
        log.logContent = content
        self.gateway.onLog(log)

    #----------------------------------------------------------------------
    def generateDateTime(self, s):
        """生成时间"""
        dt = datetime.fromtimestamp(s/1000.0)
        date = dt.strftime('%Y-%m-%d')
        time = dt.strftime("%H:%M:%S.%f")
        return date, time

    #----------------------------------------------------------------------
    def sendOrder(self, orderReq):
        """"""

        self.orderId += 1
        orderId = self.date + self.orderId

        vtOrderID = ':'.join([self.gatewayName, str(orderId)])

        if orderReq.direction == DIRECTION_LONG:
            amount = orderReq.volume
        else:
            amount = -orderReq.volume

        oSymbol = orderReq.symbol
        if not oSymbol.startswith("t"):
            oSymbol = "t" + oSymbol

        o = {
            'cid': orderId,
            'type': priceTypeMap[orderReq.priceType],
            'symbol': oSymbol,
            'amount': str(amount),
            'price': str(orderReq.price)
        }

        req = [0, 'on', None, o]
        self.sendReq(req)

        return vtOrderID

    #----------------------------------------------------------------------
    def cancelOrder(self, cancelOrderReq):
        """"""
        orderId = int(cancelOrderReq.orderID)
        date = cancelOrderReq.sessionID

        req = [
            0,
            'oc',
            None,
            {
                'cid': orderId,
                'cid_date': date,
            }
        ]

        self.sendReq(req)

    #----------------------------------------------------------------------
    def calc(self):
        """"""
        l = []
        for currency in self.currencys:
            l.append(['wallet_exchange_' + currency])

        req = [0, 'calc', None, l]
        self.sendReq(req)

    #----------------------------------------------------------------------
    def onData(self, data):
        """"""

        if isinstance(data, dict):
            self.onResponse(data)
        else:
            self.onUpdate(data)

    #----------------------------------------------------------------------
    def onResponse(self, data):
        """"""
        if 'event' not in data:
            return

        # 如果有错误的返回信息，要打印出来
        # print("[onResponse]data:" + json.dumps(data))

        if data['event'] == 'subscribed':
            symbol = str(data['symbol'].replace('t', ''))
            #symbol = str(data['symbol'])
            self.channelDict[data['chanId']] = (data['channel'], symbol)

    #----------------------------------------------------------------------
    def onUpdate(self, data):
        """"""
        if data[1] == u'hb':
            return

        channelID = data[0]

        if not channelID:
            self.onTradeUpdate(data)
        else:
            self.onDataUpdate(data)

    #----------------------------------------------------------------------
    def onDataUpdate(self, data):
        """"""
        channelID = data[0]
        channel, symbol = self.channelDict[channelID]
        symbol = str(symbol.replace('t', ''))

        # 获取Tick对象
        if symbol in self.tickDict:
            tick = self.tickDict[symbol]
        else:
            tick = VtTickData()
            tick.gatewayName = self.gatewayName
            tick.symbol = symbol
            tick.exchange = EXCHANGE_BITFINEX
            tick.vtSymbol = ':'.join([tick.symbol, tick.exchange])

            self.tickDict[symbol] = tick

        l = data[1]

        # 常规行情更新
        if channel == 'ticker':
            tick.volume = float(l[-3])
            tick.highPrice = float(l[-2])
            tick.lowPrice = float(l[-1])
            tick.lastPrice = float(l[-4])
            tick.openPrice = float(tick.lastPrice - l[4])
        # 深度报价更新
        elif channel == 'book':
            bid = self.bidDict.setdefault(symbol, {})
            ask = self.askDict.setdefault(symbol, {})

            if len(l) > 3:
                for price, count, amount in l:
                    price = float(price)
                    count = int(count)
                    amount = float(amount)

                    if amount > 0:
                        bid[price] = amount
                    else:
                        ask[price] = -amount
            else:
                price, count, amount = l
                price = float(price)
                count = int(count)
                amount = float(amount)

                if not count:
                    if price in bid:
                        del bid[price]
                    elif price in ask:
                        del ask[price]
                else:
                    if amount > 0:
                        bid[price ] = amount
                    else:
                        ask[price] = -amount

            # Bitfinex的深度数据更新是逐档推送变动情况，而非5档一起推
            # 因此会出现没有Bid或者Ask的情况，这里使用try...catch过滤
            # 只有买卖深度满足5档时才做推送
            try:
                # BID
                bidPriceList = bid.keys()
                #bidPriceList.sort(reverse=True)
                bidPriceList = sorted(bidPriceList)

                tick.bidPrice1 = bidPriceList[0]
                tick.bidPrice2 = bidPriceList[1]
                tick.bidPrice3 = bidPriceList[2]
                tick.bidPrice4 = bidPriceList[3]
                tick.bidPrice5 = bidPriceList[4]

                tick.bidVolume1 = bid[tick.bidPrice1]
                tick.bidVolume2 = bid[tick.bidPrice2]
                tick.bidVolume3 = bid[tick.bidPrice3]
                tick.bidVolume4 = bid[tick.bidPrice4]
                tick.bidVolume5 = bid[tick.bidPrice5]

                # ASK
                askPriceList = ask.keys()
                #askPriceList.sort()
                askPriceList = sorted(askPriceList)

                tick.askPrice1 = askPriceList[0]
                tick.askPrice2 = askPriceList[1]
                tick.askPrice3 = askPriceList[2]
                tick.askPrice4 = askPriceList[3]
                tick.askPrice5 = askPriceList[4]

                tick.askVolume1 = ask[tick.askPrice1]
                tick.askVolume2 = ask[tick.askPrice2]
                tick.askVolume3 = ask[tick.askPrice3]
                tick.askVolume4 = ask[tick.askPrice4]
                tick.askVolume5 = ask[tick.askPrice5]
            except IndexError:
                return

        dt = datetime.now()
        tick.date = dt.strftime('%Y%m%d')
        tick.time = dt.strftime('%H:%M:%S.%f')
        tick.datetime = dt

        # 推送
        self.gateway.onTick(copy(tick))

    #----------------------------------------------------------------------
    def onTradeUpdate(self, data):
        """1. [0, 'ps', []]
              [0, 'pu', ['tEOSUSD', 'ACTIVE', 13, 3.83957692, 0, 0, None, None, None,
                         None, None, None, None, None]]
              [0, 'pn', ['tEOSUSD', 'ACTIVE', 6, 3.8392, 0, 0, None, None, None,
                         None, None, None, None, None]]
           2. [0, 'ws', ['exchange','EOS',6,0,None],['exchange','USD',0.687,0,None]]
              [0, 'wu', ['margin', 'USD', 234.37512979, 0, None]]
           3. [0, 'os', []]
              [0, 'on', [23295449670, None, 1552819315995, 'tEOSUSD', 1552819315996,
                        1552819316000, 7, 7, 'LIMIT', None, None, None, 0, 'ACTIVE', None, None,
                        3.8399, 0, 0, 0, None, None, None, 0, 0, None, None, None, 'BFX', None, None, None]]
              [0, 'oc', [23295449670, None, 1552819315995, 'tEOSUSD', 1552819315996,
                        1552819325667, 0, 7, 'LIMIT', None, None, None, 0, 'EXECUTED @ 3.8399(7.0)',
                        None, None, 3.8399, 3.8399, 0, 0, None, None, None, 0, 0, None, None, None,
                        'BFX', None, None, None]]
           4. [0, 'te', [343948171, 'tEOSUSD', 1552819325658, 23295449670, 7,
                         3.8399, 'LIMIT', 3.8399, 1, None, None, 1552819315995]][0, 'te', []]
              [0, 'tu', [343948171, 'tEOSUSD', 1552819325658, 23295449670, 7,
                         3.8399, 'LIMIT', 3.8399, 1, -0.0268793, 'USD']]
           5. [0, 'fos', []]
              [0, 'fcs', []]
              [0, 'fls', []]

            """
        name = data[1]
        info = data[2]

        if name == 'ws':
            for l in info:
                self.onWallet(l)
            self.writeLog(u'账户资金获取成功')
        elif name == 'wu':
            self.onWallet(info)
        elif name == 'os':
            for l in info:
                self.onOrder(l)
            self.writeLog(u'活动委托获取成功')
        elif name in ['on', 'ou', 'oc']:
            self.onOrder(info)
        elif name == 'te':
            self.onTrade(info)

        #--------------------------重点 margin 账户添加的持仓的信息--------------------------------------------------------
        # elif name == ['pn', 'pu', 'pc']:                                           #这种形式是高级查询 包含利润，杠杆等信息
        elif name == 'pu':                                                           # 这种形式是高级查询 包含利润，杠杆等信息
            for l in info:
                self.onPosition(l)                                #每查询一次将结果更新到持仓函数之中
                self.writeLog(u'持仓信息获取成功')                  # 注意这里获取的每一个资金账户之中的每一个币种，情况单独列举出来

        """
        [0, 'pu', ['tEOSUSD', 'ACTIVE', -26.369349, 2.8374, -5.205e-05, 0, 6.03048553, 8.05994925, 3.32558392, -2.4796]]
        [0, 'ps', [['tEOSUSD', 'ACTIVE', -26.369349, 2.8374, -4.511e-05, 0, None, None, None, None]]]
        """

    #--------------------------exchenge账号，现货交易，不含杠杆，即为持仓信息--------------------------------------------
    # def onWallet(self, data):
    #     """"""
    #     if str(data[0]) == 'exchange':
    #         account = VtAccountData()
    #         account.gatewayName = self.gatewayName
    #
    #         account.accountID = str(data[1])
    #         account.vtAccountID = ':'.join([account.gatewayName, account.accountID])
    #         account.balance = float(data[2])
    #         if data[-1]:
    #             account.available = float(data[-1])
    #
    #         self.gateway.onAccount(account)

    # -----------------------------margin 账户交易，账户信息-----------------------------------------
    def onWallet(self, data):  # 获取钱包信息，注意这里交互获取的方式，本次定义的是现货账户，希望是margin 账户信息
        """
        账户信息推送，这里的三种账户类型

        首先这里的数据是非{};
        然后是没有channelID;
        然后是包含 name: 'ws'
        确定是包含有账户信息的数据，在bitfinex 账户有三种类，magin,exchange,bunding
        数据举例：
        WALLET_TYPE	          string	Wallet name (exchange, margin, funding)
        CURRENCY	          string	Currency (fUSD, etc)
        BALANCE	               float	   Wallet balance
        UNSETTLED_INTEREST	   float	Unsettled interest
        BALANCE_AVAILABLE	   float / null	Amount not tied up in active orders, positions or funding (null if the value is not fresh enough).
        :param data:    Wallet name (exchange, margin, funding)
        :return:
        """
        """
        数据会一行一行传递到data 之中去

            [0, 'ws', [['funding', 'USD', 1200.00951753, 0, None],
                       ['exchange', 'ADD', 0.3840261, 0, None],
                       ['exchange', 'ATD', 0.76805219, 0, None],
                       ['exchange', 'IQX', 3.84026097, 0, None],
                       ['exchange', 'MTO', 0.3840261, 0, None],
                       ['margin', 'ETC', 0.00079896, 0, None],
                       ['margin', 'ETH', 0.00885465, 0, None],
                       ['margin', 'USD', 22.07734697, 0, None],
                       ['exchange', 'USD', 0.80073412, 0, None],
                       ['margin', 'BAB', 0.00421102, 0, None],
                       ['margin', 'BSV', 0.00421102, 0, None]
                       ]
                    ]

        """
        if str(data[0]) == 'margin':
            """
             ['exchange', 'ADD', 0.3840261, 0, None],
            """
            account = VtAccountData()
            account.gatewayName = self.gatewayName

            account.accountID = str(data[1])  # 交易的币种
            account.vtAccountID = ':'.join([account.gatewayName, account.accountID])
            account.balance = float(data[2])  # 现有的数量
            if data[-1]:
                account.available = float(data[-1])

            self.gateway.onAccount(account)

    # ------------为添加到margin 持仓信息---------------------------------------------------------------------------------
    def onPosition(self, data):

        """
        ['tEOSUSD',    'ACTIVE', -26.369349,  2.8374,    -5.205e-05,        0,                6.03048553,         8.05994925,  3.32558392,  -2.4796]
        :param d:
        :return:
        """
        """
        [0, 'ps', [['tEOSUSD', 'ACTIVE', -26.369349,            2.8374,              -4.511e-05, 0, None, None, None, None]]]

                    交易对 SYMBOL    STATUS      ±AMOUNT         BASE_PRICE    MARGIN_FUNDING  MARGIN_FUNDING_TYPE    PL（Profit & Loss）    PL_PERC       PRICE_LIQ   LEVERAGE
        [0, 'pu', ['tEOSUSD',      'ACTIVE',    -26.369349,     2.8374,       -5.205e-05,        0,                   6.03048553,           8.05994925,  3.32558392,  -2.4796]]
        [['         tEOSUSD',      'ACTIVE',    -26.369349,     2.8374,       -4.511e-05,        0,                    None,                 None,       None,        None]]
        """
        pos = VtPositionData()
        # pos.symbol = d['symbol']                   #这种写法是错误的   list indices must be integers or slices, not str
        pos.symbol = data[0]

        pos.gatewayName = self.gatewayName
        pos.exchange = EXCHANGE_BITFINEX
        pos.vtSymbol = ':'.join([pos.symbol, pos.exchange])

        pos.direction = DIRECTION_NET                                                           # 持仓方向  z怎么进行的定义
        pos.vtPositionName = ':'.join([pos.vtSymbol, pos.direction])
        pos.position = data[2]
        pos.frozen = 0                                                                          # 期货没有冻结概念，会直接反向开仓
        pos.price = data[3]                                                                     # 持仓均价
        # if data[6]:
        #     pos.positionProfit = data[6]
        self.gateway.onPosition(pos)

    #----------------------------------------------------------------------
    def onOrder(self, data):
        """"""
        order = VtOrderData()
        order.gatewayName = self.gatewayName

        order.symbol = str(data[3].replace('t', ''))
        order.exchange = EXCHANGE_BITFINEX
        order.vtSymbol = ':'.join([order.symbol, order.exchange])

        order.orderID = str(data[2])
        order.vtOrderID = ':'.join([order.gatewayName, order.orderID])

        if data[7] > 0:
            order.direction = DIRECTION_LONG
        elif data[7] < 0:
            order.direction = DIRECTION_SHORT

        order.price = float(data[16])
        order.totalVolume = abs(data[7])
        order.tradedVolume = order.totalVolume - abs(data[6])

        orderStatus = str(data[13].split('@')[0])
        orderStatus = orderStatus.replace(' ', '')
        #----------------------------------------重点---------------------
        order.status = statusMapReverse[orderStatus]

        order.sessionID, order.orderTime = self.generateDateTime(data[4])
        if order.status == STATUS_CANCELLED:
            buf, order.cancelTime = self.generateDateTime(data[5])

        self.orderLocalDict[data[0]] = order.orderID

        self.gateway.onOrder(order)

        self.calc()

    #----------------------------------------------------------------------
    def onTrade(self, data):
        """"""
        trade = VtTradeData()
        trade.gatewayName = self.gatewayName

        trade.symbol = data[1].replace('t', '')
        trade.exchange = EXCHANGE_BITFINEX
        trade.vtSymbol = ':'.join([trade.symbol, trade.exchange])
        bitfinex_id = self.orderLocalDict.get(data[3], None)
        if not bitfinex_id:
            self.orderLocalDict[data[3]] = data[2]
        trade.orderID = self.orderLocalDict[data[3]]
        trade.vtOrderID = ':'.join([trade.gatewayName, trade.orderID])
        trade.tradeID = str(data[0])
        trade.vtTradeID = ':'.join([trade.gatewayName, trade.tradeID])

        if data[4] > 0:
            trade.direction = DIRECTION_LONG
        else:
            trade.direction = DIRECTION_SHORT

        trade.price = data[5]
        trade.volume = abs(data[4])
        buf, trade.tradeTime = self.generateDateTime(data[2])

        self.gateway.onTrade(trade)

    #----------------------------------------------------------------------
    def onSymbolDetails(self, data):
        """"""
        for d in data:
            contract = VtContractData()
            contract.gatewayName = self.gatewayName
            contract.symbol = d['pair'].upper()
            contract.exchange = EXCHANGE_BITFINEX
            contract.vtSymbol = ':'.join([contract.symbol, contract.exchange])
            contract.name = contract.vtSymbol
            contract.productClass = PRODUCT_SPOT
            contract.priceTick = pow(10, d["price_precision"])
            contract.price_precision = d["price_precision"]
            contract.size = 1

            self.gateway.onContract(contract)
            # ct = contract
            #self.writeLog('get contract info,gatewayName:%s symbol:%s exchange:%s vtSymbol:%s name:%s productClass:%s priceTick:%s'
            #    %(ct.gatewayName, ct.symbol, ct.exchange, ct.vtSymbol, ct.name, ct.productClass, ct.priceTick))

        self.writeLog(u'合约信息查询成功')
