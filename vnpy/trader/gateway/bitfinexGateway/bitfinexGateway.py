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

        self.qryEnabled = False                 # 是否要启动循环查询

        self.fileName = self.gatewayName + '_connect.json'
        self.filePath = getJsonPath(self.fileName, __file__)

        self.connected = False
        self.count = 0

    #----------------------------------------------------------------------
    def connect(self):
        """连接"""
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

    def loadHistoryBar(self, vtSymbol, type_, size = None, since = None):
        symbol = vtSymbol.split(':')[0]
        
        typeMap = {}
        typeMap['1min'] = '1m'
        typeMap['5min'] = '5m'
        typeMap['15min'] = '15m'
        typeMap['30min'] = '30m'
        typeMap['60min'] = '1h'
        typeMap['360min'] = '6h'

        url = f'https://api.bitfinex.com/v2/candles/trade:{typeMap[type_]}:t{symbol}/hist'

        params = {}
        if size:
            params['limit'] = size
        if since:
            params['start'] = since

        r = requests.get(url, headers={
            'Content-Type': 'application/x-www-form-urlencoded',
            'Accept': 'application/json'
        }, params=params, timeout=10)

        df = pd.DataFrame(r.json(), columns=["MTS", "open", "close", "high", "low", "volume"])
        df["datetime"] = df["MTS"].map(lambda x: datetime.fromtimestamp(x / 1000))
        df[["open", "close", "high", "low", "volume"]] = df[["open", "close", "high", "low", "volume"]].map(lambda x:float(x))

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

        # self.orderId = 1000000
        # self.date = int(datetime.now().strftime('%y%m%d%H%M%S')) * self.orderId

        #根据其中的api 接口这里传入的是utc 标准时间格式数组  经过验证
        self.orderId = 1
        self.date = int(datetime.now().timestamp()) * self.orderId

        self.currencys = []
        self.tickDict = {}
        self.bidDict = {}
        self.askDict = {}
        self.orderLocalDict = {}
        self.channelDict = {}       # ChannelID : (Channel, Symbol)


        """
        # 因为在bitfinex上没有order 的开平的属性，根据程序监听的结果，
        # 首先获得positon 的direction，然后根据order 交易的正负值去进行定义
        # 定义了变量仓位方向，这里默认为空
        """
        self.direction = DIRECTION_NET           #默认方向为空方向


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
    # 种类使用ws 进行发单
    def sendOrder(self, orderReq):
        # print('gateway senderorder orderReq._dict_', orderReq.__dict__)
        """
        有策略生成的 挂单操作 volume 都是正数，由于在bitfinex 里面开仓数量为 正负 值，这里需要根据  “买开” 进项转换
        """
        amount = 0                               #在引入amount 之前定义amount变量，防止后边变量引入报错
        self.orderId += 1
        orderId = self.date + self.orderId
        print('self.date',self.date)             #1553358144
        print(type(self.date))                   # int
        print('orderId ',orderId)                #1553358147
        print(type(orderId))                     # int

        vtOrderID = ':'.join([self.gatewayName, str(orderId)])
        # print('gateway senderorder vtOrderID ',vtOrderID)                  #BITFINEX:1553358147

        # 注意对amount 的定义，  在策略之中生成四种下单情况  买开  买平  卖开   卖平
        if orderReq.direction == DIRECTION_LONG and orderReq.offset == OFFSET_OPEN:            #买开
            amount = orderReq.volume
        elif orderReq.direction == DIRECTION_SHORT and orderReq.offset == OFFSET_CLOSE:        #卖平
            amount = -orderReq.volume
        elif orderReq.direction == DIRECTION_SHORT and orderReq.offset == OFFSET_OPEN:         #卖开
            amount = -orderReq.volume
        elif orderReq.direction == DIRECTION_LONG and orderReq.offset == OFFSET_CLOSE:         #买平
            amount = orderReq.volume

        oSymbol = orderReq.symbol
        if not oSymbol.startswith("t"):
            oSymbol = "t" + oSymbol
            print('gateway senderorder oSymbol', oSymbol)

        o = {
            'cid': orderId,                              #Should be unique in the day (UTC) (not enforced)  int45
            'type': priceTypeMap[orderReq.priceType],
            'symbol': oSymbol,
            'amount': str(amount),
            'price': str(orderReq.price)
        }

        req = [0, 'on', None, o]
        # print(' gateway senderorder sendOrder  req', req)
        #[0, 'on', None, {'cid': 1553358147, 'type': 'LIMIT', 'symbol': 'tEOSUSD', 'amount': '7', 'price': '3.7'}]

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
        """
        这里要注意的是bitfinex 数据推送的数据，看到是首先推送position 的
        """
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

        # print('ontradeupdate',data)
        name = data[1]
        info = data[2]

        if name == 'os':                                                  #orders活动委托，发单委托
            for l in info:
                self.onOrder(l)
            self.writeLog(u' order 快照   活动委托orders获取成功')
        elif name in ['on', 'ou', 'oc']:                                 #orders活动委托，发单更新
            self.onOrder(info)
            self.writeLog(u'order更新 活动委托orders更新成功')

        elif name == 'te':                                              # trade 交易委托
            self.onTrade(info)
        elif name == 'tu':                                              # trade updates 交易委托更新
            self.onTrade(info)
            self.writeLog(u'trade 更新 交易委托trades更新成功')

        elif name == 'ps':                                              #position
            for l in info:
                self.onPosition(l)
                self.writeLog(u'pos 快照 初始化持仓信息获取成功')
        elif name in ['pn', 'pu', 'pc']:                                # position update这种形式是高级查询 包含利润，杠杆等信息
            self.onPosition(info)
            self.writeLog(u'pos 更新   持仓信息【更新】成功')              # 获取的每一个账户持仓 之中的每一个币种，币种的详情信息
        elif name == 'ws':                                             # wallets 账户信息包含 exchange  margin
            for l in info:
                self.onWallet(l)
            self.writeLog(u'account 快照 账户资金获取成功')
        elif name == 'wu':                                              # wallets 账户信息仅包含usd 信息   [0, 'wu', ['margin', 'USD', 213.06576039, 0, None]]
            self.onWallet(info)
            self.writeLog(u'账户资金usd 【更新】获取成功')

        # elif name == 'miu':                                            # margin 账户信息包含 利润杠杆等信息
        #     self.onAccount(info)
        #     self.writeLog(u'margin 账户信息获取成功')



    def onWallet(self, data):
    # 获取钱包信息，注意这里交互获取的方式，本次定义的是现货账户，希望是margin 账户信息
    """
    账户信息推送，这里的三种账户类型
    确定是包含有账户信息的数据，在bitfinex 账户有三种类，magin,exchange,bunding
    数据举例：
    WALLET_TYPE	           string	Wallet name (exchange, margin, funding)
    CURRENCY	           string	Currency (fUSD, etc)
    BALANCE	               float	   Wallet balance
    UNSETTLED_INTEREST	   float	Unsettled interest
    BALANCE_AVAILABLE	   float / null	Amount not tied up in active orders, positions or funding (null if the value is not fresh enough).
    :param data:    Wallet name (exchange, margin, funding)
    :return:
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
            account = VtAccountData()
            account.gatewayName = self.gatewayName

            account.accountID = str(data[1])                             # 交易的币种
            account.vtAccountID = ':'.join([account.gatewayName, account.accountID])
            account.balance = float(data[2])                             # 现有的数量
            if data[-1]:
                account.available = float(data[-1])

            self.gateway.onAccount(account)

    def onPosition(self, data):
        # print('gateway onPosition持仓信息',data)

        """
                   POS_PAIR   POS_STATUS,  POS_AMOUNT,   POS_BASE_PRICE,  POS_MARGIN_FUNDING, POS_MARGIN_FUNDING_TYPE,
        0, 'pu', ['tEOSUSD', 'ACTIVE',    155.94831517, 3.75735133,     -0.01911379,             0,                       None, None, None, None, None, None, None, None]]

                    交易对 SYMBOL    STATUS      ±AMOUNT         BASE_PRICE    MARGIN_FUNDING  MARGIN_FUNDING_TYPE    PL（Profit & Loss）    PL_PERC       PRICE_LIQ   LEVERAGE
        [0, 'pu', ['tEOSUSD',      'ACTIVE',    -26.369349,     2.8374,       -5.205e-05,        0,                   6.03048553,           8.05994925,  3.32558392,  -2.4796]]
        [['         tEOSUSD',      'ACTIVE',    -26.369349,     2.8374,       -4.511e-05,        0,                    None,                 None,       None,        None]]

        ['tEOSUSD', 'CLOSED', 0, 5.2103, 0, 0, None, None, None, None, None, None, None, None]

        """
        pos = VtPositionData()

        Symbol = data[0].split('t')[-1]
        pos.symbol = Symbol
        pos.gatewayName = self.gatewayName
        pos.exchange = EXCHANGE_BITFINEX
        pos.vtSymbol = ':'.join([pos.symbol, pos.exchange])                                       # 合约在vt系统中的唯一代码，合约代码:交易所代码
        pos.position = abs(data[2])                                                               #持仓量  ws持仓量 正负值，所以需要 abs

        if data[2] > 0:
            pos.direction = DIRECTION_LONG
        elif data[2] < 0:
            pos.direction = DIRECTION_SHORT
        else:
            pos.direction = DIRECTION_NET

        #这里定义了一个全局变量,当更新pos 之后我们可以根据pos 的信息判断下一个订单是开平方向，当pos  大于0 的时候，volume 大于0 我们判定为 买开
        self.direction = pos.direction

        pos.vtPositionName = ':'.join([pos.vtSymbol, pos.direction])
        pos.frozen = 0                                                                           # 期货没有冻结概念，会直接反向开仓
        pos.price = data[3]                                                                      # 持仓均价
        if data[6]:                                                                              # 持仓盈亏
            print(data[6])
            pos.positionProfit = data[6]
        self.gateway.onPosition(pos)
        # print('gateway onPosition ._dict_', pos.__dict__)


    def onOrder(self, data):
        """"""
        # print('gateway onOrder data-',data)

        order = VtOrderData()
        order.gatewayName = self.gatewayName

        order.symbol = str(data[3].replace('t', ''))                                   #交易对 EOSUSD
        order.exchange = EXCHANGE_BITFINEX                                             #交易对 BITFINEX
        order.vtSymbol = ':'.join([order.symbol, order.exchange])                      #vnpy 系统编号 EOSUSD:BITFINEX

        order.orderID = str(data[2])                                                   #交易对 1553115420502   交易所返回的client订单编号
        order.vtOrderID = ':'.join([order.gatewayName, order.orderID])                 #vnpy 系统编号 BITFINEX:1553115420502
        order.priceType = str(data[8])                                                 # 价格类型


        """
        这里我们使用了pos 的self.direction 的属性，进行判定order 的买开属性
        """
        # print('gateway onOrder self.direction ',self.direction)

        if data[7] > 0 and self.direction == DIRECTION_LONG:
            print('买开')
            order.direction = DIRECTION_LONG
            order.offset = OFFSET_OPEN
        elif data[7] > 0 and self.direction == DIRECTION_NET:
            print('买平')
            order.direction = DIRECTION_LONG
            order.offset = OFFSET_CLOSE
        elif data[7] < 0 and self.direction == DIRECTION_SHORT:
            print('卖开')
            order.direction = DIRECTION_SHORT
            order.offset = OFFSET_OPEN
        elif data[7] < 0 and self.direction ==  DIRECTION_NET:
            print('卖平')
            order.direction = DIRECTION_SHORT
            order.offset = OFFSET_CLOSE

        order.price = float(data[16])                                                  #价格
        """
        #data[7]  What was the order originally submitted for?     data[6]   How much is still remaining to be submitted?
        order.totalVolume = abs(data[7])
        order.tradedVolume = order.totalVolume - abs(data[6])
        order.thisTradedVolume = order.tradedVolume
        """

        # #======================================================================= 暂时先这样进行定义  v3
        # 由于在ctaenging 之中有根据order 进行计算持仓量，但是bitfinex 首先推送到是position 为了避免冲突所以，这里全部置为0;
        # 同时引入第三方变量  order.signalTradedVolume  在策略之中onOrder等使用
        order.totalVolume = 0
        order.tradedVolume = 0
        order.thisTradedVolume = 0
        order.signalTradedVolume = abs(data[7])- abs(data[6])      #这里定义一个新的变量作为策略之中的判定使用


        #对订单状态进行判断
        if str(data[13]) == 'INSUFFICIENT BALANCE (U1)':

            order.status = STATUS_UNKNOWN                                            #状态为 未知  order.status = "资金量不足"
            print("资金量不足")
        else:
            orderStatus = str(data[13].split('@')[0])
            orderStatus = orderStatus.replace(' ', '')
            order.status = statusMapReverse[orderStatus]                            #对应的映射为STATUS_ALLTRADED    完全成交

        order.sessionID, order.orderTime = self.generateDateTime(data[4])           #订单创建时间
        if order.status == STATUS_CANCELLED:
            buf, order.cancelTime = self.generateDateTime(data[5])

        # ===============================     本地的订单编号为，key 为ID即order 编号，此标号为trade   values 为订单cid 即我们传入的cid
        self.orderLocalDict[data[0]] = order.orderID
        # print('gateway onOrderself.orderLocalDict',self.orderLocalDict)
        #{23446020903: 1553354160375, 23446102274: '1553353932'}
        self.gateway.onOrder(order)


        self.calc()

    #----------------------------------------------------------------------
    def onTrade(self, data):
        #trade updatedata 是在order之后
        """"""
        trade = VtTradeData()
        trade.gatewayName = self.gatewayName

        trade.symbol = data[1].replace('t', '')
        trade.exchange = EXCHANGE_BITFINEX
        trade.vtSymbol = ':'.join([trade.symbol, trade.exchange])

        #注意这里的前提是有onder 之后的trade,如果是在order 更新之前的话，是直接取最后的值，即为order ，如果不是这里取data[3]为 ORDER_ID 也就是oder 创建时间
        #=============================================================原版
        # trade.orderID = self.orderLocalDict[data[3]]
        # trade.vtOrderID = ':'.join([trade.gatewayName, trade.orderID])
        #============================================================修改为
        bitfinex_id = self.orderLocalDict.get(data[3],None)
        if not bitfinex_id:
            self.orderLocalDict[data[3]] = data[11]
        trade.orderID = self.orderLocalDict[data[3]]

        trade.vtOrderID = ':'.join([trade.gatewayName, str(trade.orderID)])
        # 注意返回值之中的第一个是trade 的编号id,这里需要是str
        trade.tradeID = str(data[0])
        trade.vtTradeID = ':'.join([trade.gatewayName, trade.tradeID])

        #因为trade 返回只有成交的数量，没有成交的方向，所以可以根据仓位来进行判定，思路与order 是一致的；
        if data[4] > 0 and self.direction == DIRECTION_LONG:
            print('买开')
            trade.direction = DIRECTION_LONG
            trade.offset = OFFSET_OPEN
        elif data[4] > 0 and self.direction == DIRECTION_NET:
            print('买平')
            trade.direction = DIRECTION_LONG
            trade.offset = OFFSET_CLOSE
        elif data[4] < 0 and self.direction == DIRECTION_SHORT:
            print('卖开')
            trade.direction = DIRECTION_SHORT
            trade.offset = OFFSET_OPEN
        elif data[4] < 0 and self.direction ==  DIRECTION_NET:
            print('卖平')
            trade.direction = DIRECTION_SHORT
            trade.offset = OFFSET_CLOSE

        trade.price = data[5]                                     #成交的价格
        buf, trade.tradeTime = self.generateDateTime(data[2])     #成交的时间


        #根据目前的测试 暂时修改为  v3   思路与order 一样为了避免与position 更新的冲突造成对持仓的判断，这里将volume 全部重置为0.引入变量 trade.signalvolume
        trade.volume = 0                          # 成交的数量v1
        trade.signalvolume = abs(data[4])         # 这里重新定义一个新的标量作为策略之中的判定使用

        self.gateway.onTrade(trade)
        print('gateway trade._dict_', trade.__dict__)



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
