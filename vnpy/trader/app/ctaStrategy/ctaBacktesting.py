'''
本文件中包含的是CTA模块的回测引擎，回测引擎的API和CTA引擎一致，
可以使用和实盘相同的代码进行回测。
'''
from datetime import datetime, timedelta
from collections import OrderedDict,defaultdict
from itertools import product
import copy
import sys
import os
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
from vnpy.trader.vtObject import VtTickData, VtBarData, VtLogData
from vnpy.trader.vtGateway import VtOrderData, VtTradeData
from vnpy.trader.language import constant
from vnpy.trader.app.ctaStrategy.ctaBase import *

########################################################################
class BacktestingEngine(object):
    """
    CTA回测引擎
    函数接口和策略引擎保持一样，
    从而实现同一套代码从回测到实盘。
    """
    
    TICK_MODE = 'tick'
    BAR_MODE = 'bar'
    END_OF_THE_WORLD = datetime.now().strftime(constant.DATETIME)

    #----------------------------------------------------------------------
    def __init__(self):
        """Constructor"""
        # 本地停止单
        self.stopOrderCount = 0     # 编号计数：stopOrderID = STOPORDERPREFIX + str(stopOrderCount)
        
        # 本地停止单字典, key为stopOrderID，value为stopOrder对象
        self.stopOrderDict = {}             # 停止单撤销后不会从本字典中删除
        self.workingStopOrderDict = {}      # 停止单撤销后会从本字典中删除
        
        self.engineType = ENGINETYPE_BACKTESTING    # 引擎类型为回测
        
        self.strategy = None        # 回测策略
        self.mode = self.BAR_MODE   # 回测模式，默认为K线
        
        self.startDate = ''
        self.initHours = 0        
        self.endDate = ''

        self.capital = 1000000      # 回测时的起始本金（默认100万）
        
        self.dbClient = None  # 数据库客户端
        self.dbURI = ''       # 回测数据库地址
        self.dbName = ''      # 数据库名称
        self.dbCursor = None  # 数据库指针
        
        self.initData = []          # 初始化用的数据
        self.backtestData = []      # 回测用历史数据
        self.contractInfo = {}      # 回测标的信息字典

        self.cachePath = os.path.join(os.path.expanduser("~"), "vnpy_data")       # 本地数据缓存地址
        self.logActive = False      # 回测日志开关
        self.logPath = os.path.join(os.getcwd(), "Backtest_Log")  # 回测日志自定义路径

        self.dataStartDate = None       # 回测数据开始日期，datetime对象
        self.dataEndDate = None         # 回测数据结束日期，datetime对象
        self.strategyStartDate = None   # 策略启动日期（即前面的数据用于初始化），datetime对象
        
        self.limitOrderCount = 0                    # 限价单编号
        self.limitOrderDict = OrderedDict()         # 限价单字典
        self.workingLimitOrderDict = OrderedDict()  # 活动限价单字典，用于进行撮合用
        
        self.tradeCount = 0             # 成交编号
        self.tradeDict = OrderedDict()  # 成交字典
        
        self.logList = []               # 日志记录
        self.orderList = []             # 订单记录
        
        # 当前最新数据，用于模拟成交用
        self.tickDict = defaultdict(lambda: None)
        self.barDict = defaultdict(lambda: None)
        self.dt = None      # 最新的时间
        self.annualDays = 240  # 年化的基数
        
        # 日线回测结果计算用
        self.dailyResultDict = defaultdict(OrderedDict)
    
    #------------------------------------------------
    # 通用功能
    #------------------------------------------------    
    
    #----------------------------------------------------------------------
    def roundToPriceTick(self, vtSymbol, price):
        """取整价格到合约最小价格变动"""
        priceTick = self.contractInfo[vtSymbol].get("priceTick", 0)
        if not priceTick:
            return price
        
        newPrice = round(price/priceTick, 0) * priceTick
        return newPrice

    #----------------------------------------------------------------------
    def output(self, content, carriageReturn=False):
        """输出内容"""
        if carriageReturn:
            sys.stdout.write("%s\t%s    \r" % (str(datetime.now()), content))
            sys.stdout.flush()
        else:
            print(str(datetime.now()) + "\t" + content)

    #------------------------------------------------
    # 参数设置相关
    #------------------------------------------------
    
    #----------------------------------------------------------------------
    def setStartDate(self, startDate='20100416 01:00:00', initHours= 0):
        """设置回测的启动日期"""
        self.startDate = startDate
        self.initHours = initHours
        
        self.dataStartDate = datetime.strptime(startDate, constant.DATETIME)
        
        initTimeDelta = timedelta(hours = initHours)
        self.strategyStartDate = self.dataStartDate - initTimeDelta
        
    #----------------------------------------------------------------------
    def setEndDate(self, endDate=''):
        """设置回测的结束日期"""
        self.endDate = endDate
        
        if endDate:
            self.dataEndDate = datetime.strptime(endDate, constant.DATETIME)
        else:
            self.dataEndDate = datetime.strptime(self.END_OF_THE_WORLD, constant.DATETIME)
        
    #----------------------------------------------------------------------
    def setBacktestingMode(self, mode):
        """设置回测模式"""
        self.mode = mode
    
    #----------------------------------------------------------------------
    def setDB_URI(self, dbURI):
        """设置历史数据所用的数据库"""
        self.dbURI = dbURI

    #----------------------------------------------------------------------
    def setDatabase(self,dbName):
        """设置数据库名称"""
        self.dbName = dbName
    
    #----------------------------------------------------------------------
    def setCapital(self, capital):
        """设置资本金"""
        self.capital = capital
    
    def setContracts(self, contractInfo = {}):
        self.contractInfo = contractInfo
    
    #----------------------------------------------------------------------
    def setLog(self, active = False, path = None):
        """设置是否出交割单和日志"""
        if path:
            self.logPath = path
        self.logActive = active

    #----------------------------------------------------------------------
    def setCachePath(self, path):
        self.cachePath = path

    #------------------------------------------------
    # 数据回放相关
    #------------------------------------------------
    def parseData(self, dataClass, dataDict):
        data = dataClass()
        data.__dict__.update(dataDict)
        return data
        """
        "data.__dict__"  sample:
        {'close': 2374.4, 'date': '20170701', 'datetime': Timestamp('2017-07-01 10:44:00'), 'exchange': 'bitfinex', 
        'gatewayName': '', 'high': 2374.4, 'low': 2374.1, 'open': 2374.1, 'openInterest': 0, 'rawData': None,
        'symbol': 'tBTCUSD', 'time': '10:44:00.000000', 'volume': 12.18062789, 'vtSymbol': 'tBTCUSD:bitfinex'}
        """
    # ----------------------------------------------------------------------
    def loadHistoryData(self, symbolList, startDate, endDate=None):
        """载入历史数据:数据范围[start:end)"""
        if not endDate:
            endDate = datetime.strptime(self.END_OF_THE_WORLD, constant.DATETIME)

        modeMap = {
            self.BAR_MODE: "datetime", 
            self.TICK_MODE: "date"
            }

        # 根据回测模式，确认要使用的数据类
        if self.mode == self.BAR_MODE:
            dataClass = VtBarData
            datetime_list = get_minutes_list(start=startDate, end=endDate)
            date_list = list(set([date.strftime(constant.DATE) for date in datetime_list]))
            need_files = [f"{d}.hd5" for d in date_list]
        else:
            dataClass = VtTickData
            datetime_list = [date.strftime(constant.DATE) for date in get_date_list(start=startDate, end=endDate)]
            need_files = [f"{d}.hd5" for d in datetime_list]
        need_files = list(set(need_files))

        start = startDate.strftime(constant.DATETIME)
        end = endDate.strftime(constant.DATETIME)
        self.output(f"准备载入数据：时间段:[{start} , {end})")

        # 下载数据
        dataList = []
        df_cached = {}
        # 优先从本地文件缓存读取数据
        symbols_no_data = dict()  # 本地缓存没有的数据
        
        for symbol in self.strategy.symbolList:
            # 如果存在缓存文件，则读取日期列表和bar数据，否则初始化df_cached和dates_cached
            save_path = os.path.join(self.cachePath, self.mode, symbol.replace(":", "_"))
            symbols_no_data[symbol] = datetime_list
            df_cached[symbol] = {}
            dt_list_acquired = []

            for file_ in need_files:
                hd5_file_path = f'{save_path}/{file_}'
                if os.path.isfile(hd5_file_path):
                    # 读取 hd5
                    df_cached[symbol][file_] = pd.read_hdf(hd5_file_path)
                    df_acquired = df_cached[symbol][file_][
                        (df_cached[symbol][file_].datetime >= start) & (df_cached[symbol][file_].datetime < end)
                        ]
                    dataList += [self.parseData(dataClass, item) for item in df_acquired.to_dict("record")]
                    dt_list_acquired += list(set(df_acquired[modeMap[self.mode]]))  # bar 回测按datetime, tick 回测按date

            symbols_no_data[symbol] = list(set(dt_list_acquired) ^ (set(datetime_list)))
            acq, need = len(dt_list_acquired), len(datetime_list)
            self.output(f"{symbol}： 从本地缓存文件实取{acq}, 最大应取{need}, 还需从数据库取{need-acq}")

        # 如果没有完全从本地文件加载完数据, 则尝试从指定的mongodb下载数据, 并缓存到本地
        if self.dbURI:
            import pymongo
            self.dbClient = pymongo.MongoClient(self.dbURI)[self.dbName]
            for symbol, need_datetimes in symbols_no_data.items():
                if len(need_datetimes) > 0:  # 需要从数据库取数据
                    if symbol in self.dbClient.collection_names():
                        collection = self.dbClient[symbol]
                        Cursor = collection.find({modeMap[self.mode]: {"$in": need_datetimes}})  # 按时间回测检索
                        data_df = pd.DataFrame(list(Cursor))
                        if data_df.size > 0:
                            del data_df["_id"]
                            # 筛选出需要的时间段
                            dataList += [self.parseData(dataClass, item) for item in
                                            data_df[(data_df.datetime >= start) & (data_df.datetime < end)].to_dict(
                                                "record")]
                            # 缓存到本地文件
                            save_path = os.path.join(self.cachePath, self.mode, symbol.replace(":", "_"))
                            if not os.path.isdir(save_path):
                                os.makedirs(save_path)

                            if self.mode == self.BAR_MODE:
                                dates = [datetimes.strftime(constant.DATE) for datetimes in symbols_no_data[symbol]]
                                symbols_no_data[symbol] = list(set(dates))
                            for date in symbols_no_data[symbol]:
                                update_df = data_df[data_df["date"] == date]
                                if update_df.size > 0:
                                    update_df.to_hdf(f"{save_path}/{date}.hd5", "/", format = "table", append=True, complevel=9)

                            acq, need = len(list(set(data_df[modeMap[self.mode]]))), len(need_datetimes)
                            self.output(f"{symbol}： 从数据库存取了{acq}, 应补{need}, 缺失了{need-acq}")
                        else:
                            self.output(f"{symbol}： 数据库也没能补到缺失的数据")
                    else:
                        self.output(f"数据库没有 {symbol} 这个品种")
                        self.output(f"这些品种在我们的数据库里: {self.dbClient.collection_names()}")
        else:
            self.output('没有设置回测数据库URI, 无法回补缓存数据。请在回测设置 engine.setDB_URI("mongodb://localhost:27017")')

        if len(dataList) > 0:
            dataList.sort(key=lambda x: x.datetime)
            self.output(f"载入完成, 数据量:{len(dataList)}")
            return dataList
        else:
            self.output(f'WARNING: 该时间段:[%s,%s) 数据量为0!' % (start, end))
            return []
        
    #----------------------------------------------------------------------
    def runBacktesting(self, prepared_data = [], cache_data =False):
        """运行回测"""

        dataLimit = 1000000
        self.clearBacktestingResult()  # 清空策略的所有状态（指如果多次运行同一个策略产生的状态）
        # 首先根据回测模式，确认要使用的数据类,以及数据的分批回放范围
        if self.mode == self.BAR_MODE:
            func = self.newBar
            dataDays = max(dataLimit // (len(self.contractInfo.keys()) * 24 * 60), 1)
        else:
            func = self.newTick
            dataDays = max(dataLimit // (len(self.contractInfo.keys()) * 24 * 60 * 60 * 5), 1)
        
        if cache_data:  # 为优化缓存数据到内存中
            self.output("预加载优化数据到内存中")
            if self.strategyStartDate != self.dataStartDate:
                prepared_data.append(self.loadHistoryData(self.strategyStartDate, self.dataStartDate))
            start = self.dataStartDate
            stop = self.dataEndDate
            while start < stop:
                end = min(start + timedelta(dataDays), stop)
                backtest_data = self.loadHistoryData(start, end)
                prepared_data.append(backtest_data)
                if len(backtest_data) == 0:
                    break
                else:
                    start = end
            return prepared_data

        # 开始回测, 加载初始化数据, 数据范围:[self.strategyStartDate,self.dataStartDate)
        self.output(u'开始回测')
        self.output(u'策略初始化')
        self.initData = []     # 清空内存里的数据
        self.backtestData = [] # 清空内存里的数据

        if self.strategyStartDate == self.dataStartDate:
            self.output(u'策略无请求历史数据初始化')
        else:
            if not prepared_data:
                self.initData = self.loadHistoryData(self.strategyStartDate, self.dataStartDate)
            else:
                self.initData = prepared_data[0]
            self.output(u'初始化预加载数据成功, 数据长度:%s' % (len(self.initData)))    
        self.strategy.inited = True
        self.strategy.onInit()
        self.output(u'策略初始化完成')

        self.strategy.trading = True
        self.strategy.onStart()
        self.output(u'策略启动完成')

        # 分批加载回测数据.数据范围:[self.dataStartDate,self.dataEndDate+1)
        begin = start = self.dataStartDate
        stop = self.dataEndDate + timedelta(munutes = 1)
        i = 1 # 缓存回测数据的起始位置
        self.output(f'开始回放回测数据,回测范围:[{begin.strftime(constant.DATETIME)},{stop.strftime(constant.DATETIME)})')
        while start<stop:
            end = min(start + timedelta(dataDays), stop)
            if not prepared_data:
                self.backtestData = self.loadHistoryData(start, end)
            else:
                self.backtestData = prepared_data[i]
                i+=1
            if len(self.backtestData)==0:
                break
            else:
                self.output(f'当前回放数据:[{start.strftime(constant.DATETIME)},{end.strftime(constant.DATETIME)})')
                oneP = len(self.backtestData)
                for idx, data in enumerate(self.backtestData):
                    pct = int((idx+1)*100 / oneP)
                    if pct%1 == 0:
                        self.output(f'Progress: {str(pct)}%', True)
                    func(data)
                start = end

        self.output(u'数据回放结束')

        # 日志输出模块
        if self.logActive:
            filename = os.path.join(self.logPath, u"Backtesting.log")
            f = open(filename, "w+")
            for line in self.logList:
                print(f"{line}", file = f)
            self.output(u'Backtesting log Recorded')
        
    #----------------------------------------------------------------------
    def newBar(self, bar):
        """新的K线"""
        self.barDict[bar.vtSymbol] = bar
        self.dt = bar.datetime        

        self.crossLimitOrder(bar)      # 先撮合限价单
        self.crossStopOrder(bar)       # 再撮合停止单
        self.strategy.onBar(bar)       # 推送K线到策略中
        
        self.updateDailyClose(bar.vtSymbol, bar.datetime, bar.close)
    
    #----------------------------------------------------------------------
    def newTick(self, tick):
        """新的Tick"""
        self.tickDict[tick.vtSymbol] = tick
        self.dt = tick.datetime
        self.crossLimitOrder(tick)
        self.crossStopOrder(tick)
        self.strategy.onTick(tick)

        self.updateDailyClose(tick.vtSymbol, tick.datetime, tick.lastPrice)

    # ----------------------------------------------------------------------
    def createFolder(self, symbolList):
        alpha='abcdefghijklmnopqrstuvwxyz'
        filter_text = "0123456789._-" + alpha + alpha.upper()
        new_name = filter(lambda ch: ch in filter_text, str(symbolList))
        symbol_name = ''.join(list(new_name))
        Folder_Name = f'{self.strategy.name.replace("Strategy","")}_{symbol_name}_{datetime.now().strftime("%y%m%d%H%M")}'
        self.logPath = os.path.join(self.logPath, Folder_Name[:50])
        if not os.path.isdir(self.logPath):
            os.makedirs(self.logPath)

    #----------------------------------------------------------------------
    def initStrategy(self, strategyClass, setting=None):
        """
        初始化策略
        setting是策略的参数设置，如果使用类中写好的默认设置则可以不传该参数
        """

        if not self.contractInfo:
            for symbol in setting['symbolList']:
                self.contractInfo.update({symbol:{}})
        else:
            setting['symbolList'] = list(self.contractInfo.keys())
        self.strategy = strategyClass(self, setting)
        self.strategy.name = self.strategy.className
        self.initPosition(self.strategy)

        # 初始化日志文件夹
        if self.logActive:
            self.createFolder(setting['symbolList'])

    #----------------------------------------------------------------------
    def crossLimitOrder(self, data):
        """基于最新数据撮合限价单"""
        # 先确定会撮合成交的价格
        if self.mode == self.BAR_MODE:
            buyCrossPrice = data.low        # 若买入方向限价单价格高于该价格，则会成交
            sellCrossPrice = data.high      # 若卖出方向限价单价格低于该价格，则会成交
            buyBestCrossPrice = data.open   # 在当前时间点前发出的买入委托可能的最优成交价
            sellBestCrossPrice = data.open  # 在当前时间点前发出的卖出委托可能的最优成交价
        else:
            buyCrossPrice = data.askPrice1
            sellCrossPrice = data.bidPrice1
            buyBestCrossPrice = data.askPrice1
            sellBestCrossPrice = data.bidPrice1

        symbol = data.vtSymbol
        
        # 遍历限价单字典中的所有限价单
        for orderID in list(self.workingLimitOrderDict):
            order = self.workingLimitOrderDict[orderID]
            if order.vtSymbol == symbol:
                # 推送委托进入队列（未成交）的状态更新
                if not order.status:
                    order.status = constant.STATUS_NOTTRADED
                    self.strategy.onOrder(order)

                # 判断是否会成交
                buyCross = (order.direction==constant.DIRECTION_LONG and 
                            order.price>=buyCrossPrice and
                            buyCrossPrice > 0)      # 国内的tick行情在涨停时askPrice1为0，此时买无法成交
                
                sellCross = (order.direction==constant.DIRECTION_SHORT and 
                            order.price<=sellCrossPrice and
                            sellCrossPrice > 0)     # 国内的tick行情在跌停时bidPrice1为0，此时卖无法成交
                
                # 如果发生了成交
                if buyCross or sellCross:
                    # 推送成交数据
                    self.tradeCount += 1            # 成交编号自增1
                    tradeID = str(self.tradeCount)
                    trade = VtTradeData()
                    trade.vtSymbol = order.vtSymbol
                    trade.tradeID = tradeID
                    trade.vtTradeID = tradeID
                    trade.orderID = order.orderID
                    trade.vtOrderID = order.orderID
                    trade.direction = order.direction
                    trade.offset = order.offset

                    # 以买入为例：
                    # 1. 假设当根K线的OHLC分别为：100, 125, 90, 110
                    # 2. 假设在上一根K线结束(也是当前K线开始)的时刻，策略发出的委托为限价105
                    # 3. 则在实际中的成交价会是100而不是105，因为委托发出时市场的最优价格是100
                    if buyCross and trade.offset == constant.OFFSET_OPEN:
                        trade.price = min(order.price, buyBestCrossPrice)
                        self.strategy.posDict[symbol + "_LONG"] += order.totalVolume
                        self.strategy.eveningDict[symbol + "_LONG"] += order.totalVolume
                        self.strategy.posDict[symbol + "_LONG"] = round(self.strategy.posDict[symbol + "_LONG"], 4)
                        self.strategy.eveningDict[symbol + "_LONG"] = round(self.strategy.eveningDict[symbol + "_LONG"], 4)
                        self.strategy.accountDict["balance"] += ((order.price-trade.price) * order.volume)
                    elif buyCross and trade.offset == constant.OFFSET_CLOSE:
                        trade.price = min(order.price, buyBestCrossPrice)
                        self.strategy.posDict[symbol + "_SHORT"] -= order.totalVolume
                        self.strategy.posDict[symbol + "_SHORT"] = round(self.strategy.posDict[symbol + "_SHORT"], 4)
                    elif sellCross and trade.offset == constant.OFFSET_OPEN:
                        trade.price = max(order.price, sellBestCrossPrice)
                        self.strategy.posDict[symbol + "_SHORT"] += order.totalVolume
                        self.strategy.eveningDict[symbol + "_SHORT"] += order.totalVolume
                        self.strategy.posDict[symbol + "_SHORT"] = round(self.strategy.posDict[symbol + "_SHORT"], 4)
                        self.strategy.eveningDict[symbol + "_SHORT"] = round(self.strategy.eveningDict[symbol + "_SHORT"], 4)
                        self.strategy.accountDict["balance"] -= ((trade.price-order.price) * order.volume)
                    elif sellCross and trade.offset == constant.OFFSET_CLOSE:
                        trade.price = max(order.price, sellBestCrossPrice)
                        self.strategy.posDict[symbol + "_LONG"] -= order.totalVolume
                        self.strategy.posDict[symbol + "_LONG"] = round(self.strategy.posDict[symbol + "_LONG"], 4)

                    # 现货仓位
                    elif buyCross and trade.offset == constant.OFFSET_NONE:
                        trade.price = min(order.price, buyBestCrossPrice)
                        self.strategy.posDict[symbol + "_LONG"] += order.totalVolume
                        self.strategy.posDict[symbol + "_LONG"] = round(self.strategy.posDict[symbol + "_LONG"], 4)
                        self.strategy.accountDict["balance"] += ((order.price-trade.price) * order.volume)
                    elif sellCross and trade.offset == constant.OFFSET_NONE:
                        trade.price = max(order.price, sellBestCrossPrice)
                        self.strategy.posDict[symbol + "_LONG"] -= order.totalVolume
                        self.strategy.posDict[symbol + "_LONG"] = round(self.strategy.posDict[symbol + "_LONG"], 4)
                        self.strategy.accountDict["balance"] += (trade.price * order.volume)

                    trade.volume = order.totalVolume
                    trade.tradeTime = self.dt.strftime(constant.DATETIME)
                    trade.tradeDatetime = self.dt
                    self.strategy.onTrade(trade)
                    
                    self.tradeDict[tradeID] = trade
                    
                    # 推送委托数据
                    order.price_avg = trade.price
                    order.tradedVolume = order.totalVolume
                    order.status = constant.STATUS_ALLTRADED
                    self.strategy.onOrder(order)
                    
                    # 从字典中删除该限价单
                    if orderID in self.workingLimitOrderDict:
                        del self.workingLimitOrderDict[orderID]
                
    #----------------------------------------------------------------------
    def crossStopOrder(self, data):
        """基于最新数据撮合停止单"""
        # 先确定会撮合成交的价格，这里和限价单规则相反
        if self.mode == self.BAR_MODE:
            buyCrossPrice = data.high    # 若买入方向停止单价格低于该价格，则会成交
            sellCrossPrice = data.low    # 若卖出方向限价单价格高于该价格，则会成交
            bestCrossPrice = data.open   # 最优成交价，买入停止单不能低于，卖出停止单不能高于
        else:
            buyCrossPrice = data.lastPrice
            sellCrossPrice = data.lastPrice
            bestCrossPrice = data.lastPrice
        symbol = data.vtSymbol

        # 遍历停止单字典中的所有停止单

        for stopOrderID in list(self.workingStopOrderDict):
            so = self.workingStopOrderDict[stopOrderID]
            if so.vtSymbol == symbol:
                # 判断是否会成交
                buyCross = so.direction==constant.DIRECTION_LONG and so.price<=buyCrossPrice
                sellCross = so.direction==constant.DIRECTION_SHORT and so.price>=sellCrossPrice
                
                # 如果发生了成交
                if buyCross or sellCross:
                    # 更新停止单状态，并从字典中删除该停止单
                    so.status = STOPORDER_TRIGGERED
                    if stopOrderID in self.workingStopOrderDict:
                        del self.workingStopOrderDict[stopOrderID]                        

                    # 推送成交数据
                    self.tradeCount += 1            # 成交编号自增1
                    tradeID = str(self.tradeCount)
                    trade = VtTradeData()
                    trade.vtSymbol = so.vtSymbol
                    trade.tradeID = tradeID
                    trade.vtTradeID = tradeID

                    if buyCross and so.offset == constant.OFFSET_OPEN: # 买开
                        self.strategy.posDict[symbol+"_LONG"] += so.volume
                        trade.price = max(bestCrossPrice, so.price)
                    elif buyCross and so.offset == constant.OFFSET_CLOSE: # 买平
                        self.strategy.posDict[symbol+"_SHORT"] -= so.volume
                        trade.price = max(bestCrossPrice, so.price)
                    elif sellCross and so.offset == constant.OFFSET_OPEN: # 卖开
                        self.strategy.posDict[symbol+"_SHORT"] += so.volume
                        trade.price = min(bestCrossPrice, so.price)
                    elif sellCross and so.offset == constant.OFFSET_CLOSE: # 卖平
                        self.strategy.posDict[symbol+"_LONG"] -= so.volume
                        trade.price = min(bestCrossPrice, so.price)

                    elif buyCross and so.offset == constant.OFFSET_NONE: 
                        self.strategy.posDict[symbol] += so.volume
                        trade.price = max(bestCrossPrice, so.price)
                    elif sellCross and so.offset == constant.OFFSET_NONE: 
                        self.strategy.posDict[symbol] -= so.volume
                        trade.price = min(bestCrossPrice, so.price)
                    
                    self.limitOrderCount += 1
                    orderID = str(self.limitOrderCount)
                    trade.orderID = orderID
                    trade.vtOrderID = orderID
                    trade.direction = so.direction
                    trade.offset = so.offset
                    trade.volume = so.volume
                    trade.tradeTime = self.dt.strftime(constant.DATETIME)
                    trade.tradeDatetime = self.dt
                    
                    self.tradeDict[tradeID] = trade
                    
                    # 推送委托数据
                    order = VtOrderData()
                    order.vtSymbol = so.vtSymbol
                    order.symbol = so.vtSymbol
                    order.orderID = orderID
                    order.vtOrderID = orderID
                    order.direction = so.direction
                    order.offset = so.offset
                    order.price = so.price
                    order.totalVolume = so.volume
                    order.tradedVolume = so.volume
                    order.status = constant.STATUS_ALLTRADED
                    order.orderTime = trade.tradeTime
                    
                    self.limitOrderDict[orderID] = order
                    
                    # 按照顺序推送数据
                    self.strategy.onStopOrder(so)
                    self.strategy.onOrder(order)
                    self.strategy.onTrade(trade)

    #------------------------------------------------
    # 策略接口相关
    #----------------------------------------------------------------------
    def sendOrder(self, vtSymbol, orderType, price, volume, priceType, strategy):
        """发单"""
        self.limitOrderCount += 1
        orderID = str(self.limitOrderCount)
        order = VtOrderData()
        order.vtSymbol = order.symbol = vtSymbol
        order.totalVolume = round(volume, 5)
        order.orderID = orderID
        order.vtOrderID = orderID
        order.priceType = priceType
        order.orderTime = self.dt.strftime(constant.DATETIME)
        order.orderDatetime = self.dt
        
        # CTA委托类型映射
        if orderType == CTAORDER_BUY:
            order.direction = constant.DIRECTION_LONG
            order.offset = constant.OFFSET_OPEN
        elif orderType == CTAORDER_SELL:
            order.direction = constant.DIRECTION_SHORT
            order.offset = constant.OFFSET_CLOSE
            closable = self.strategy.eveningDict[order.vtSymbol + '_LONG']
            if order.totalVolume > closable:
                self.output(f"当前order：{order.orderTime}, {order.vtSymbol}, 卖平{order.totalVolume}, 可平{closable}")
                self.output("实盘下可能拒单, 请小心处理")              
            closable -= order.totalVolume
            self.strategy.eveningDict[order.vtSymbol + '_LONG'] = round(closable, 4)
        elif orderType == CTAORDER_SHORT:
            order.direction = constant.DIRECTION_SHORT
            order.offset = constant.OFFSET_OPEN
        elif orderType == CTAORDER_COVER:
            order.direction = constant.DIRECTION_LONG
            order.offset = constant.OFFSET_CLOSE
            closable = self.strategy.eveningDict[order.vtSymbol + '_SHORT']
            if order.totalVolume > closable:
                self.output(f"当前order：{order.orderTime}, {order.vtSymbol}, 买平{order.totalVolume}, 可平{closable}")
                self.output("实盘下可能拒单, 请小心处理")  
            closable -= order.totalVolume
            self.strategy.eveningDict[order.vtSymbol + '_SHORT'] = round(closable, 4)

        if priceType == constant.PRICETYPE_LIMITPRICE:
            order.price = self.roundToPriceTick(vtSymbol, price)
        elif priceType == constant.PRICETYPE_MARKETPRICE:
            if order.direction == constant.DIRECTION_LONG:
                order.price = self.roundToPriceTick(vtSymbol, price) * 1000
            elif order.direction == constant.DIRECTION_SHORT:
                order.price = self.roundToPriceTick(vtSymbol, price) / 1000

        balance = self.strategy.accountDict["balance"]
        if not order.offset == constant.OFFSET_CLOSE:
            if balance < (price * order.totalVolume):
                self.output("INSUFFICIENT FUND")
            else:
                self.strategy.accountDict["balance"] -= price * order.totalVolume

        # 保存到限价单字典中
        self.workingLimitOrderDict[orderID] = order
        self.limitOrderDict[orderID] = order
        
        return [orderID]
    
    #----------------------------------------------------------------------
    def sendStopOrder(self, vtSymbol, orderType, price, volume, priceType, strategy):
        """发停止单（本地实现）"""
        self.stopOrderCount += 1
        stopOrderID = STOPORDERPREFIX + str(self.stopOrderCount)
        
        so = StopOrder()
        so.vtSymbol = vtSymbol
        so.priceType = priceType
        so.price = self.roundToPriceTick(vtSymbol, price)
        so.volume = volume
        so.strategy = strategy
        so.status = STOPORDER_WAITING
        so.stopOrderID = stopOrderID
        
        if orderType == CTAORDER_BUY:
            so.direction = constant.DIRECTION_LONG
            so.offset = constant.OFFSET_OPEN
        elif orderType == CTAORDER_SELL:
            so.direction = constant.DIRECTION_SHORT
            so.offset = constant.OFFSET_CLOSE
        elif orderType == CTAORDER_SHORT:
            so.direction = constant.DIRECTION_SHORT
            so.offset = constant.OFFSET_OPEN
        elif orderType == CTAORDER_COVER:
            so.direction = constant.DIRECTION_LONG
            so.offset = constant.OFFSET_CLOSE

        # 保存stopOrder对象到字典中
        self.stopOrderDict[stopOrderID] = so
        self.workingStopOrderDict[stopOrderID] = so
        
        # 推送停止单初始更新
        self.strategy.onStopOrder(so)        
        
        return [stopOrderID]

    #----------------------------------------------------------------------
    def cancelOrder(self, vtOrderID):
        """撤单"""
        if vtOrderID in self.workingLimitOrderDict:
            order = self.workingLimitOrderDict[vtOrderID]

            order.status = constant.STATUS_CANCELLED
            order.cancelTime = self.dt.strftime(constant.DATETIME)
            order.cancelDatetime = self.dt

            if order.offset == constant.OFFSET_CLOSE:
                if order.direction == constant.DIRECTION_LONG:
                    self.strategy.eveningDict[order.vtSymbol + '_SHORT'] += order.totalVolume
                    self.strategy.eveningDict[order.vtSymbol + '_SHORT'] = round(self.strategy.posDict[order.vtSymbol + '_SHORT'], 4)
                elif order.direction == constant.DIRECTION_SHORT:
                    self.strategy.eveningDict[order.vtSymbol + '_LONG'] += order.totalVolume
                    self.strategy.eveningDict[order.vtSymbol + '_LONG'] = round(self.strategy.posDict[order.vtSymbol + '_LONG'], 4)
            else:
                if not (order.direction == constant.DIRECTION_SHORT and order.offset == constant.OFFSET_NONE):
                    self.strategy.accountDict["balance"] += order.price * order.volume
            
            self.strategy.onOrder(order)

            del self.workingLimitOrderDict[vtOrderID]
            
    #----------------------------------------------------------------------
    def cancelStopOrder(self, stopOrderID):
        """撤销停止单"""
        # 检查停止单是否存在
        if stopOrderID in self.workingStopOrderDict:
            so = self.workingStopOrderDict[stopOrderID]
            so.status = STOPORDER_CANCELLED
            del self.workingStopOrderDict[stopOrderID]
            self.strategy.onStopOrder(so)
    
    #----------------------------------------------------------------------
    def putStrategyEvent(self, name):
        """发送策略更新事件，回测中忽略"""
        pass
     
    #----------------------------------------------------------------------
    def insertData(self, dbName, collectionName, data):
        """考虑到回测中不允许向数据库插入数据，防止实盘交易中的一些代码出错"""
        pass
    
    #----------------------------------------------------------------------
    def loadBar(self, dbName, collectionName, startDate):
        """直接返回初始化数据列表中的Bar"""
        return self.initData
    
    #----------------------------------------------------------------------
    def loadTick(self, dbName, collectionName, startDate):
        """直接返回初始化数据列表中的Tick"""
        return self.initData
    
    #----------------------------------------------------------------------
    def writeCtaLog(self, content):
        """记录日志"""
        log = str(self.dt) + ' ' + content 
        self.logList.append(log)
    
    #----------------------------------------------------------------------
    def cancelAll(self, name):
        """全部撤单"""
        # 撤销限价单
        for orderID in list(self.workingLimitOrderDict.keys()):
            self.cancelOrder(orderID)

    def cancelAllStopOrder(self,name):
        # 撤销停止单
        for stopOrderID in list(self.workingStopOrderDict.keys()):
            self.cancelStopOrder(stopOrderID)

    def batchCancelOrder(self, vtOrderList):
        # 为了和实盘一致撤销限价单
        for orderID in list(self.workingLimitOrderDict.keys()):
            self.cancelOrder(orderID)

    #----------------------------------------------------------------------
    def saveSyncData(self, strategy):
        """保存同步数据（无效）"""
        pass
    
    #----------------------------------------------------------------------
    def getPriceTick(self, strategy):
        """获取最小价格变动"""
        return 0
    
    #-------------------------------------------
    def initPosition(self, strategy):
        for symbol in strategy.symbolList:
            strategy.posDict[symbol+"_LONG"] = 0
            strategy.posDict[symbol+"_SHORT"] = 0
            strategy.eveningDict[symbol+"_LONG"] = 0
            strategy.eveningDict[symbol+"_SHORT"] = 0
            strategy.accountDict["balance"] = self.capital
            
        print(f"仓位字典构造完成\n初始仓位:{strategy.posDict}")
    
    def mail(self,content,strategy):
        self.writeCtaLog(f'email func if real:{content}')
                
    #------------------------------------------------
    # 结果计算相关
    #------------------------------------------------      
    
    #----------------------------------------------------------------------
    def calculateBacktestingResult(self):
        """
        计算回测结果
        """
        self.output(u'计算回测结果')
                
        # 检查成交记录
        if not self.tradeDict:
            self.output(u'成交记录为空，无法计算回测结果')
            return {}
        # 首先基于回测后的成交记录，计算每笔交易的盈亏
        resultList = []             # 交易结果列表
        deliverSheet = []

        longTrade = defaultdict(list)  # 未平仓的多头交易
        shortTrade = defaultdict(list)  # 未平仓的空头交易
        
        tradeTimeList = []          # 每笔成交时间戳
        posList = [0]               # 每笔成交后的持仓情况        

        # 复制成交对象，因为下面的开平仓交易配对涉及到对成交数量的修改
        # 若不进行复制直接操作，则计算完后所有成交的数量会变成0
        tradeDict = copy.deepcopy(self.tradeDict)
        for trade in tradeDict.values():

            if trade.direction == constant.DIRECTION_LONG:
                if trade.offset in [constant.OFFSET_OPEN, constant.OFFSET_NONE]:
                    longTrade[trade.vtSymbol].append(trade)
                elif trade.offset == constant.OFFSET_CLOSE:
                    while True:
                        entryTrade = shortTrade[trade.vtSymbol][0]
                        exitTrade = trade
                        
                        # 清算开平仓交易
                        closedVolume = min(exitTrade.volume, entryTrade.volume)
                        result = TradingResult(entryTrade.price, entryTrade.tradeDatetime, entryTrade.orderID,
                                               exitTrade.price, exitTrade.tradeDatetime,exitTrade.orderID,
                                               -closedVolume, self.contractInfo[trade.vtSymbol])
                        resultList.append(result)
                        r = result.__dict__
                        r.update({"symbol":trade.vtSymbol})
                        deliverSheet.append(r)

                        posList.extend([-1, 0])
                        tradeTimeList.extend([result.entryDt, result.exitDt])

                        # 计算未清算部分
                        entryTrade.volume -= closedVolume
                        exitTrade.volume -= closedVolume

                        entryTrade.volume = round(entryTrade.volume, 4)
                        exitTrade.volume = round(exitTrade.volume, 4)


                        # 如果开仓交易已经全部清算，则从列表中移除
                        if not entryTrade.volume:
                            shortTrade[trade.vtSymbol].pop(0)

                        # 如果平仓交易已经全部清算，则退出循环
                        if not exitTrade.volume:
                            break

                        # 如果平仓交易未全部清算，
                        if exitTrade.volume:
                            # 且开仓交易已经全部清算完，则平仓交易剩余的部分
                            # 等于新的反向开仓交易，添加到队列中
                            if not shortTrade[trade.vtSymbol]:
                                self.output("出现平空单多于空仓单的情况，请检查策略")
                                break
                            # 如果开仓交易还有剩余，则进入下一轮循环
                            else:
                                pass

            elif trade.direction == constant.DIRECTION_SHORT:
                if trade.offset  == constant.OFFSET_OPEN:
                    shortTrade[trade.vtSymbol].append(trade)
                elif trade.offset in [constant.OFFSET_CLOSE, constant.OFFSET_NONE]:
                    while True:
                        entryTrade = longTrade[trade.vtSymbol][0]
                        exitTrade = trade

                        # 清算开平仓交易
                        closedVolume = min(exitTrade.volume, entryTrade.volume)
                        result = TradingResult(entryTrade.price, entryTrade.tradeDatetime, entryTrade.orderID,
                                               exitTrade.price, exitTrade.tradeDatetime, exitTrade.orderID,
                                               closedVolume, self.contractInfo[trade.vtSymbol])
                        resultList.append(result)
                        r = result.__dict__
                        r.update({"symbol":trade.vtSymbol})
                        deliverSheet.append(r)

                        posList.extend([1, 0])
                        tradeTimeList.extend([result.entryDt, result.exitDt])

                        # 计算未清算部分
                        entryTrade.volume -= closedVolume
                        exitTrade.volume -= closedVolume

                        entryTrade.volume = round(entryTrade.volume, 4)
                        exitTrade.volume = round(exitTrade.volume, 4)

                        # 如果开仓交易已经全部清算，则从列表中移除
                        if not entryTrade.volume:
                            longTrade[trade.vtSymbol].pop(0)

                        # 如果平仓交易已经全部清算，则退出循环
                        if not exitTrade.volume:
                            break

                        # 如果平仓交易未全部清算，
                        if exitTrade.volume:
                            # 且开仓交易已经全部清算完，则平仓交易剩余的部分
                            # 等于新的反向开仓交易，添加到队列中
                            if not longTrade[trade.vtSymbol]:
                                self.output("出现平多单多于多仓单的情况，请检查策略")
                                break
                            # 如果开仓交易还有剩余，则进入下一轮循环
                            else:
                                pass
        # 到最后交易日尚未平仓的交易，则以最后价格平仓
        for symbol, tradeList in longTrade.items():

            if self.mode == self.BAR_MODE:
                endPrice = self.barDict[symbol].close
            else:
                endPrice = self.tickDict[symbol].lastPrice

            for trade in tradeList:
                result = TradingResult(trade.price, trade.tradeDatetime, trade.orderID,
                                       endPrice, self.dt, "LastDay",
                                       trade.volume, self.contractInfo[symbol])

                resultList.append(result)
                r = result.__dict__
                r.update({"symbol":symbol})
                deliverSheet.append(r)

        for symbol, tradeList in shortTrade.items():

            if self.mode == self.BAR_MODE:
                endPrice = self.barDict[symbol].close
            else:
                endPrice = self.tickDict[symbol].lastPrice

            for trade in tradeList:
                result = TradingResult(trade.price, trade.tradeDatetime, trade.orderID,
                                       endPrice, self.dt, "LastDay",
                                       -trade.volume, self.contractInfo[symbol])
                resultList.append(result)
                r = result.__dict__
                r.update({"symbol":symbol})
                deliverSheet.append(r)

        # 检查是否有交易
        if not resultList:
            self.output(u'无交易结果')
            return {}

        # 交割单输出模块
        if self.logActive:
            resultDF = pd.DataFrame(deliverSheet)
            filename = os.path.join(self.logPath, u"trading result.csv")
            resultDF.to_csv(filename, index=False, sep=',', encoding="utf_8_sig")
            self.output(u'trading result saved')

        # 然后基于每笔交易的结果，我们可以计算具体的盈亏曲线和最大回撤等
        capital = 0             # 资金
        maxCapital = 0          # 资金最高净值
        drawdown = 0            # 回撤
        
        totalResult = 0         # 总成交数量
        totalTurnover = 0       # 总成交金额（合约面值）
        totalCommission = 0     # 总手续费
        totalSlippage = 0       # 总滑点
        
        timeList = []           # 时间序列
        pnlList = []            # 每笔盈亏序列
        capitalList = []        # 盈亏汇总的时间序列
        drawdownList = []       # 回撤的时间序列
        
        winningResult = 0       # 盈利次数
        losingResult = 0        # 亏损次数		
        totalWinning = 0        # 总盈利金额		
        totalLosing = 0         # 总亏损金额       

        longPnlList = []        # 多仓盈亏
        shortPnlList = []       # 空仓盈亏
        holdingList = []        # 持仓日记录

        for result in resultList:
            capital += result.pnl
            maxCapital = max(capital, maxCapital)
            drawdown = capital - maxCapital
            
            pnlList.append(result.pnl)
            timeList.append(result.exitDt)      # 交易的时间戳使用平仓时间
            capitalList.append(capital)
            drawdownList.append(drawdown)
            
            totalResult += 1
            totalTurnover += result.turnover
            totalCommission += result.commission
            totalSlippage += result.slippage
            
            if result.pnl >= 0:
                winningResult += 1
                totalWinning += result.pnl
            else:
                losingResult += 1
                totalLosing += result.pnl

            if result.volume > 0:
                longPnlList.append(result.pnl)
            if result.volume < 0 :
                shortPnlList.append(result.pnl)

            holdingdays = result.exitDt-result.entryDt
            holdingList.append(holdingdays)

        # 计算盈亏相关数据
        winningRate = winningResult / totalResult * 100  # 胜率

        averageWinning = 0  # 这里把数据都初始化为0
        averageLosing = 0
        profitLossRatio = 0

        if winningResult:
            averageWinning = totalWinning / winningResult  # 平均每笔盈利
        if losingResult:
            averageLosing = totalLosing / losingResult  # 平均每笔亏损
        if averageLosing:
            profitLossRatio = -averageWinning / averageLosing  # 盈亏比

        # 返回回测结果
        d = {}
        d['capital'] = capital
        d['maxCapital'] = maxCapital
        d['drawdown'] = drawdown
        d['totalResult'] = totalResult
        d['totalTurnover'] = totalTurnover
        d['totalCommission'] = totalCommission
        d['totalSlippage'] = totalSlippage
        d['timeList'] = timeList
        d['pnlList'] = pnlList
        d['longPnl'] = longPnlList
        d['shortPnl'] = shortPnlList
        d['capitalList'] = capitalList
        d['drawdownList'] = drawdownList
        d['winningRate'] = winningRate
        d['averageWinning'] = averageWinning
        d['averageLosing'] = averageLosing
        d['profitLossRatio'] = profitLossRatio
        d['posList'] = posList
        d['tradeTimeList'] = tradeTimeList
        d['resultList'] = resultList
        d['holdingPeriod'] = holdingList
        
        return d
        
    #----------------------------------------------------------------------
    def showBacktestingResult(self):
        """显示回测结果"""
        d = self.calculateBacktestingResult()
        if not d:
            return
        
        # 输出
        self.output('-' * 30)
        self.output(u'第一笔交易：\t%s' % d['timeList'][0])
        self.output(u'最后一笔交易：\t%s' % d['timeList'][-1])

        self.output(u'总交易次数：\t%s' % formatNumber(d['totalResult']))
        self.output(u'总盈亏：\t%s' % formatNumber(d['capital']))
        self.output(u'最大回撤: \t%s' % formatNumber(min(d['drawdownList'])))

        self.output(u'平均每笔盈利：\t%s' % formatNumber(d['capital'] / d['totalResult']))
        self.output(u'平均每笔滑点：\t%s' % formatNumber(d['totalSlippage'] / d['totalResult']))
        self.output(u'平均每笔佣金：\t%s' % formatNumber(d['totalCommission'] / d['totalResult']))

        self.output(u'胜率\t\t%s%%' % formatNumber(d['winningRate']))
        self.output(u'盈利交易平均值\t%s' % formatNumber(d['averageWinning']))
        self.output(u'亏损交易平均值\t%s' % formatNumber(d['averageLosing']))
        self.output(u'盈亏比：\t%s' % formatNumber(d['profitLossRatio']))

        # 绘图 #1
        fig = plt.figure(figsize=(10, 20))

        pCapital = plt.subplot(5, 1, 1)
        pCapital.set_ylabel("capital")
        pCapital.plot(d['capitalList'], color='r', lw=0.8)

        pDD = plt.subplot(5, 1, 2)
        pDD.set_ylabel("DD")
        pDD.bar(range(len(d['drawdownList'])), d['drawdownList'], color='g')

        pPnl = plt.subplot(5, 1, 3)
        pPnl.set_ylabel("pnl")
        pPnl.hist(d['pnlList'], color='c')

        plong = plt.subplot(5, 1, 4)
        plong.set_ylabel("long_pnl")
        plong.plot(d['longPnl'])

        pshort = plt.subplot(5, 1, 5)
        pshort.set_ylabel("short_pnl")
        pshort.plot(d['shortPnl'])


        # 输出回测统计图
        if self.logActive:
            filename = os.path.join(self.logPath, u"pnl.png")
            plt.savefig(filename)
            self.output(u'pnl saved')
        plt.show()

        # 绘图 #2
        fig = plt.figure(figsize=(10, 16))

        pPos = plt.subplot(3, 1, 1)
        pPos.set_ylabel("Position")
        if d['posList'][-1] == 0:
            del d['posList'][-1]

        pHold = plt.subplot(3,1,2)
        pHold.set_ylabel("Holding_Period")
        pHold.plot(d['holdingPeriod'])


        # 输出回测统计图-2
        if self.logActive:
            filename = os.path.join(self.logPath, u"holding.png" )
            plt.savefig(filename)
            self.output(u'holding saved') 
            
            
            dd={'First Trade':d['timeList'][0],'Last Trade':d['timeList'][-1],'Total Trade':formatNumber(d['totalResult']),'Pnl':formatNumber(d['capital']),
            'Max DrawDown':formatNumber(min(d['drawdownList'])),'Profit per Trade':formatNumber(d['capital']/d['totalResult']),'Slippage per Trade':formatNumber(d['totalSlippage']/d['totalResult']),
            'Commission per Trade':formatNumber(d['totalCommission']/d['totalResult']),'Winning Rate':formatNumber(d['winningRate']),'Profit per Trade':formatNumber(d['averageWinning']),
            'Loss per Trade':formatNumber(d['averageLosing']),'PNL Ratio':formatNumber(d['profitLossRatio']),'Longpos PNL':formatNumber(sum(d['longPnl'])),'Shortpos PNL':formatNumber(sum(d['shortPnl']))}
            
            ddresult = pd.DataFrame(dd,index=[0]).T
            filename = os.path.join(self.logPath, u"BacktestingResult.csv" )
            ddresult.to_csv(filename, index=False, sep=',', encoding="utf_8_sig")
            self.output(u'BacktestingResult saved') 
        plt.show()
    
    #----------------------------------------------------------------------
    def clearBacktestingResult(self):
        """清空之前回测的结果"""
        # 清空限价单相关
        self.limitOrderCount = 0
        self.limitOrderDict.clear()
        self.workingLimitOrderDict.clear()        
        
        # 清空停止单相关
        self.stopOrderCount = 0
        self.stopOrderDict.clear()
        self.workingStopOrderDict.clear()
        
        # 清空成交相关
        self.tradeCount = 0
        self.tradeDict.clear()

        # 清空历史数据
        self.initData = []
        self.backtestData = []

        # 清空日线回测结果
        self.dailyResultDict = defaultdict(OrderedDict)
        
    #----------------------------------------------------------------------
    def runOptimization(self, strategyClass, optimizationSetting):
        """优化参数"""
        # 获取优化设置        
        settingList = optimizationSetting.generateSetting()
        targetName = optimizationSetting.optimizeTarget
        
        # 检查参数设置问题
        if not settingList or not targetName:
            self.output(u'优化设置有问题，请检查')
        
        # 遍历优化
        resultList = []
        for setting in settingList:
            self.clearBacktestingResult()
            self.output('-' * 30)
            self.output('setting: %s' %str(setting))
            self.initStrategy(strategyClass, setting)
            self.runBacktesting()
            df = self.calculateDailyResult()
            # 没有逐日结果，直接返回
            if not isinstance(df, pd.DataFrame) or df.size <= 0:
                continue
            df, d = self.calculateDailyStatistics(df)
            try:
                targetValue = d[targetName]
            except KeyError:
                targetValue = 0
            resultList.append((setting, targetValue, d))
        
        # 显示结果
        resultList.sort(reverse=True, key=lambda result:result[1])
        self.output('-' * 30)
        self.output(u'优化结果：')
        for result in resultList:
            self.output(u'参数：%s，目标：%s' %(result[0], result[1]))    
        return resultList
            
    #----------------------------------------------------------------------
    def runParallelOptimization(self, strategyClass, optimizationSetting, strategySetting = {}, prepared_data = []):
        """并行优化参数"""
        import multiprocessing

        # 获取优化设置        
        settingList = optimizationSetting.generateSetting()
        targetName = optimizationSetting.optimizeTarget
        
        # 检查参数设置问题
        if not settingList or not targetName:
            self.output(u'优化设置有问题，请检查')
        
        # 多进程优化，启动一个对应CPU核心数量的进程池
        pool = multiprocessing.Pool(multiprocessing.cpu_count()-1)
        l = []

        for setting in settingList:
            setting.update(strategySetting)
            self.clearBacktestingResult()  # 清空策略的所有状态（指如果多次运行同一个策略产生的状态）
            l.append(pool.apply_async(optimize, (self.__class__, strategyClass, setting,
                                                 targetName, self.mode,
                                                 self.startDate, self.initHours, self.endDate,
                                                 self.dbURI, self.dbName, self.contractInfo, prepared_data)))
        pool.close()
        pool.join()
        
        # 显示结果
        resultList = [res.get() for res in l]
        resultList.sort(reverse=True, key=lambda result:result[1])
        self.output('-' * 30)
        self.output(u'优化结果：')
        for result in resultList:
            self.output(u'参数：%s，目标：%s' %(result[0], result[1]))    
            
        return resultList

    #----------------------------------------------------------------------
    def updateDailyClose(self, symbol, dt, price):
        """更新每日收盘价"""
        date = dt.date()
        resultDict = self.dailyResultDict[symbol]
        if date not in resultDict:
            resultDict[date] = DailyResult(symbol, date, price)
        else:
            resultDict[date].closePrice = price
            
    #----------------------------------------------------------------------
    def calculateDailyResult(self):
        """计算按日统计的交易结果"""
        self.output(u'计算按日统计结果')
        
        # 检查成交记录
        if not self.tradeDict:
            self.output(u'成交记录为空，无法计算回测结果')
            return {}

        dailyResultDict = copy.deepcopy(self.dailyResultDict)
        
        # 将成交添加到每日交易结果中
        for trade in self.tradeDict.values():
            date = trade.dt.date()
            symbol = trade.vtSymbol
            dailyResult = self.dailyResultDict[symbol][date]
            dailyResult.addTrade(trade)

        resultDf = pd.DataFrame([])
        for symbol, resultDictByDay in self.dailyResultDict.items():

            # 遍历计算每日结果
            previousClose = 0
            openPosition = 0
            for dailyResult in resultDictByDay.values():
                dailyResult.previousClose = previousClose
                previousClose = dailyResult.closePrice

                dailyResult.calculatePnl(openPosition, self.contractInfo[symbol])
                openPosition = dailyResult.closePosition

            # 生成DataFrame
            resultDf = pd.concat(
                [resultDf, pd.DataFrame([item.__dict__ for item in resultDictByDay.values()])], axis=0
            )

        resultDf = resultDf.sort_values(by=['date', 'symbol']).set_index(['date', 'symbol'])
        resultDf = resultDf[
            ['netPnl', 'slippage', 'commission', 'turnover', 'tradeCount',
             'tradingPnl', 'positionPnl', 'totalPnl']
        ]

        # 恢复self.dailyResultDict未被修改前的状态，防止重复调用本方法结果计算出错
        self.dailyResultDict = dailyResultDict
        return resultDf.groupby(level=['date']).sum()
    
    #----------------------------------------------------------------------
    def calculateDailyStatistics(self, df):
        """计算按日统计的结果"""
        if not isinstance(df, pd.DataFrame) or df.size <= 0:
            return None, {}
        
        df['balance'] = df['netPnl'].cumsum() + self.capital
        df['return'] = df["netPnl"] / self.capital
        df['highlevel'] = df['balance'].rolling(min_periods=1, window=len(df), center=False).max()
        df['drawdown'] = df['balance'] - df['highlevel']
        df['ddPercent'] = df['drawdown'] / df['highlevel'] * 100

        # 计算统计结果
        startDate = df.index[0]
        endDate = df.index[-1]

        totalDays = len(df)
        profitDays = len(df[df['netPnl'] > 0])
        lossDays = len(df[df['netPnl'] < 0])

        endBalance = df['balance'].iloc[-1]
        maxDrawdown = df['drawdown'].min()
        maxDdPercent = df['ddPercent'].min()

        totalNetPnl = df['netPnl'].sum()
        dailyNetPnl = totalNetPnl / totalDays

        totalCommission = df['commission'].sum()
        dailyCommission = totalCommission / totalDays

        totalSlippage = df['slippage'].sum()
        dailySlippage = totalSlippage / totalDays

        totalTurnover = df['turnover'].sum()
        dailyTurnover = totalTurnover / totalDays

        totalTradeCount = df['tradeCount'].sum()
        dailyTradeCount = totalTradeCount / totalDays

        totalReturn = (endBalance / self.capital - 1) * 100
        annualizedReturn = totalReturn / totalDays * 240
        dailyReturn = df['return'].mean() * 100
        returnStd = df['return'].std() * 100

        if returnStd:
            sharpeRatio = dailyReturn / returnStd * np.sqrt(240)
        else:
            sharpeRatio = 0

        # 返回结果
        result = {
            'startDate': startDate.strftime("%Y-%m-%d"),
            'endDate': endDate.strftime("%Y-%m-%d"),
            'totalDays': totalDays,
            'profitDays': profitDays,
            'lossDays': lossDays,
            'endBalance': endBalance,
            'maxDrawdown': maxDrawdown,
            'maxDdPercent': maxDdPercent,
            'totalNetPnl': totalNetPnl,
            'dailyNetPnl': dailyNetPnl,
            'totalCommission': totalCommission,
            'dailyCommission': dailyCommission,
            'totalSlippage': totalSlippage,
            'dailySlippage': dailySlippage,
            'totalTurnover': totalTurnover,
            'dailyTurnover': dailyTurnover,
            'totalTradeCount': totalTradeCount,
            'dailyTradeCount': dailyTradeCount,
            'totalReturn': totalReturn,
            'annualizedReturn': annualizedReturn,
            'dailyReturn': dailyReturn,
            'returnStd': returnStd,
            'sharpeRatio': sharpeRatio
        }

        # 输出回测结果
        if self.logActive:
            ddresult = pd.DataFrame(result,index=[0]).T
            filename = os.path.join(self.logPath, u"DailyStatistics.csv" )
            ddresult.to_csv(filename, index=False, sep=',', encoding="utf_8_sig")
            self.output(u'DailyStatistics saved') 

        return df, result
    
    #----------------------------------------------------------------------
    def showDailyResult(self, df=None, result=None):
        """显示按日统计的交易结果"""
        df = self.calculateDailyResult()

        # 没有逐日结果，直接返回
        if not isinstance(df, pd.DataFrame) or df.size <= 0:
            return

        df, result = self.calculateDailyStatistics(df)
            
        # 输出统计结果
        self.output('-' * 30)
        self.output(u'首个交易日：\t%s' % result['startDate'])
        self.output(u'最后交易日：\t%s' % result['endDate'])
        
        self.output(u'总交易日：\t%s' % result['totalDays'])
        self.output(u'盈利交易日\t%s' % result['profitDays'])
        self.output(u'亏损交易日：\t%s' % result['lossDays'])
        
        self.output(u'起始资金：\t%s' % self.capital)
        self.output(u'结束资金：\t%s' % formatNumber(result['endBalance']))
    
        self.output(u'总收益率：\t%s%%' % formatNumber(result['totalReturn']))
        self.output(u'年化收益：\t%s%%' % formatNumber(result['annualizedReturn']))
        self.output(u'总盈亏：\t%s' % formatNumber(result['totalNetPnl']))
        self.output(u'最大回撤: \t%s' % formatNumber(result['maxDrawdown']))   
        self.output(u'百分比最大回撤: %s%%' % formatNumber(result['maxDdPercent']))   
        
        self.output(u'总手续费：\t%s' % formatNumber(result['totalCommission']))
        self.output(u'总滑点：\t%s' % formatNumber(result['totalSlippage']))
        self.output(u'总成交金额：\t%s' % formatNumber(result['totalTurnover']))
        self.output(u'总成交笔数：\t%s' % formatNumber(result['totalTradeCount']))
        
        self.output(u'日均盈亏：\t%s' % formatNumber(result['dailyNetPnl']))
        self.output(u'日均手续费：\t%s' % formatNumber(result['dailyCommission']))
        self.output(u'日均滑点：\t%s' % formatNumber(result['dailySlippage']))
        self.output(u'日均成交金额：\t%s' % formatNumber(result['dailyTurnover']))
        self.output(u'日均成交笔数：\t%s' % formatNumber(result['dailyTradeCount']))
        
        self.output(u'日均收益率：\t%s%%' % formatNumber(result['dailyReturn']))
        self.output(u'收益标准差：\t%s%%' % formatNumber(result['returnStd']))
        self.output(u'Sharpe Ratio：\t%s' % formatNumber(result['sharpeRatio']))
        
        # 绘图
        fig = plt.figure(figsize=(10, 16))
        
        pBalance = plt.subplot(4, 1, 1)
        pBalance.set_title('Balance')
        df['balance'].plot(legend=True)
        
        pDrawdown = plt.subplot(4, 1, 2)
        pDrawdown.set_title('Drawdown')
        pDrawdown.fill_between(range(len(df)), df['drawdown'].values)
        
        pPnl = plt.subplot(4, 1, 3)
        pPnl.set_title('Daily Pnl') 
        df['netPnl'].plot(kind='bar', legend=False, grid=False, xticks=[])

        pKDE = plt.subplot(4, 1, 4)
        pKDE.set_title('Daily Pnl Distribution')
        df['netPnl'].hist(bins=50)
        
        # 输出回测绩效图
        if self.logActive:
            filename = os.path.join(self.logPath, u"DailyResult.png")
            plt.savefig(filename)
            self.output(u'DailyResult saved')

        plt.show()
        
########################################################################
class TradingResult(object):
    """每笔交易的结果"""

    #----------------------------------------------------------------------
    def __init__(self, entryPrice, entryDt, entryID, exitPrice, 
                 exitDt, exitID, volume, contractInfo):
        """Constructor"""
        self.entryPrice = entryPrice    # 开仓价格
        self.entryDt = entryDt          # 开仓时间datetime
        self.entryID = entryID

        self.exitPrice = exitPrice      # 平仓价格
        self.exitDt = exitDt            # 平仓时间
        self.exitID = exitID

        self.volume = volume            # 交易数量（+/-代表方向）

        size = contractInfo.get("size", 1)
        rate = contractInfo.get("rate", 0)
        slippage = contractInfo.get("slippage", 0)

        self.turnover = (self.entryPrice + self.exitPrice) * size * abs(volume)   # 成交金额

        self.commission = self.turnover * rate                              # 手续费成本   
        self.slippage = slippage * 2 * size * abs(volume)                   # 滑点成本

        self.pnl = ((self.exitPrice - self.entryPrice) * volume * size 
                    - self.commission - self.slippage)                      # 净盈亏
        

########################################################################
class DailyResult(object):
    """每日交易的结果"""

    #----------------------------------------------------------------------
    def __init__(self, symbol, date, closePrice):
        """Constructor"""
        self.symbol = symbol
        self.date = date                # 日期
        self.closePrice = closePrice    # 当日收盘价
        self.previousClose = 0          # 昨日收盘价
        
        self.tradeList = []             # 成交列表
        self.tradeCount = 0             # 成交数量
        
        self.openPosition = 0           # 开盘时的持仓
        self.closePosition = 0          # 收盘时的持仓
        
        self.tradingPnl = 0             # 交易盈亏
        self.positionPnl = 0            # 持仓盈亏
        self.totalPnl = 0               # 总盈亏
        
        self.turnover = 0               # 成交量
        self.commission = 0             # 手续费
        self.slippage = 0               # 滑点
        self.netPnl = 0                 # 净盈亏
        
    #----------------------------------------------------------------------
    def addTrade(self, trade):
        """添加交易"""
        self.tradeList.append(trade)

    #----------------------------------------------------------------------
    def calculatePnl(self, openPosition=0, contractInfo = {}):
        """
        计算盈亏
        size: 合约乘数
        rate：手续费率
        slippage：滑点点数
        """
        size = contractInfo.get("size", 1)
        rate = contractInfo.get("rate", 0)
        slippage = contractInfo.get("slippage", 0)

        # 持仓部分
        self.openPosition = openPosition
        self.positionPnl = self.openPosition * (self.closePrice - self.previousClose) * size
        self.closePosition = self.openPosition
        
        # 交易部分
        self.tradeCount = len(self.tradeList)
        
        for trade in self.tradeList:
            if trade.direction == constant.DIRECTION_LONG:
                posChange = trade.volume
            else:
                posChange = -trade.volume

            self.tradingPnl += posChange * (self.closePrice - trade.price) * size
            self.turnover += trade.price * trade.volume * size
            self.closePosition += posChange

            self.commission += trade.price * trade.volume * size * rate
            self.slippage += trade.volume * size * slippage

        # 汇总
        self.totalPnl = self.tradingPnl + self.positionPnl
        self.netPnl = self.totalPnl - self.commission - self.slippage


########################################################################
class OptimizationSetting(object):
    """优化设置"""

    #----------------------------------------------------------------------
    def __init__(self):
        """Constructor"""
        self.paramDict = OrderedDict()
        
        self.optimizeTarget = ''        # 优化目标字段
        
    #----------------------------------------------------------------------
    def addParameter(self, name, start, end=None, step=None):
        """增加优化参数"""
        if end is None and step is None:
            self.paramDict[name] = [start]
            return 
        
        if end < start:
            print(u'参数起始点必须不大于终止点')
            return
        
        if step <= 0:
            print(u'参数布进必须大于0')
            return
        
        l = []
        param = start
        
        while param <= end:
            l.append(param)
            param += step
        
        self.paramDict[name] = l

    #----------------------------------------------------------------------    
    """接受迭代器"""
    def addParams(self, name, params):
        if isinstance(params, str):
            params = eval(params)
        self.paramDict[name] = list(params)        

    #----------------------------------------------------------------------
    def generateSetting(self):
        """生成优化参数组合"""
        # 参数名的列表
        nameList = self.paramDict.keys()
        paramList = self.paramDict.values()
        
        # 使用迭代工具生产参数对组合
        productList = list(product(*paramList))
        
        # 把参数对组合打包到一个个字典组成的列表中
        settingList = []
        for p in productList:
            d = dict(zip(nameList, p))
            settingList.append(d)
    
        return settingList
    
    #----------------------------------------------------------------------
    def setOptimizeTarget(self, target):
        """设置优化目标字段"""
        self.optimizeTarget = target

#----------------------------------------------------------------------
def formatNumber(n):
    """格式化数字到字符串"""
    rn = round(n, 2)        # 保留两位小数
    return format(rn, ',')  # 加上千分符

#----------------------------------------------------------------------
def optimize(backtestEngineClass, strategyClass, setting, targetName,
             mode, startDate, initHours, endDate,
             dbURI, dbName, contractInfo={}, prepared_data = []):
    """多进程优化时跑在每个进程中运行的函数"""
    engine = backtestEngineClass()
    engine.setBacktestingMode(mode)
    engine.setStartDate(startDate, initHours)
    engine.setEndDate(endDate)
    engine.setContracts(contractInfo)
    engine.setDB_URI(dbURI)
    engine.setDatabase(dbName)
    
    engine.initStrategy(strategyClass, setting)
    engine.runBacktesting(prepared_data)
    
    df = engine.calculateDailyResult()
    df, d = engine.calculateDailyStatistics(df)
    try:
        targetValue = d[targetName]
    except KeyError:
        targetValue = 0            
    return (setting, targetValue, d)


def gen_dates(b_date, days):
    day = timedelta(days=1)
    for i in range(days):
        yield b_date + day * i

def get_date_list(start=None, end=None):
    """
    获取日期列表
    :param start: 开始日期
    :param end: 结束日期
    :return:
    """
    if start is None:
        start = datetime.strptime("2000-01-01 01:00:00", constant.DATETIME)
    if end is None:
        end = datetime.now()
    data = []
    for d in gen_dates(start, (end - start).days):
        data.append(d)
    return data

def gen_minutes(b_date, days, minutes):
    minute = timedelta(minutes = 1)
    for i in range(days * 1440 + minutes):
        yield b_date + minute * i

def get_minutes_list(start=None, end=None):
    """
    获取日期列表
    :param start: 开始日期
    :param end: 结束日期
    :return:
    """
    if start is None:
        start = datetime.strptime("2019-01-01 01:00:00", constant.DATETIME)
    if end is None:
        end = datetime.now()
    data = []
    days = (end - start).days
    minutes = int((end - start).seconds / 60)
    for d in gen_minutes(start, days, minutes):
        data.append(d)
    return data