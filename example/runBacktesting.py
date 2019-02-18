# encoding: UTF-8
"""展示如何执行策略回测"""
"""setting start here"""
engine_settings = {
            "setStartDate":('20180615 00:00',0), # 设置回测用的数据起始日期，initHours 默认值为 0
            "setEndDate" : ('20190115 23:59',),
            "setCapital":1000000,      # 设置起始资金，默认值是1,000,000
            "setSlippage" : (0.002,),  # 股指1跳
            "setRate" : (5/10000,),    # 万0.3
            "setSize":(300,),          # 股指合约大小 
            "setPriceTick":(0.2,),     # 股指最小价格变动
            "setDatabase" : ("VnTrader_1Min_Db",),
            "setLog":(True,"D:\\vnpy_data\\log\\",), # 设置是否输出日志和交割单, 默认不输出, 默认路径在当前文件夹
            "setCachePath":("D:\\vnpy_data\\",)      # 设置本地数据缓存的路径，默认存在用户文件夹内
            }
srategy_settings = {'symbolList':['tBTCUSD:bitfinex']}
from StrategyBollBand import BollBandsStrategy as Strategy
"""setting end here"""

from vnpy.trader.app.ctaStrategy.ctaBacktesting import BacktestingEngine

if __name__ == '__main__':
    # 创建回测引擎，模式为K线
    engine = BacktestingEngine()
    engine.setBacktestingMode(engine.BAR_MODE)
    for attr, setting in engine_settings.items():
        func = engine.__getattribute__(attr)
        func(*setting)
    
    # 在引擎中创建策略对象
    engine.initStrategy(Strategy, srategy_settings)
    
    # 开始跑回测
    engine.runBacktesting()

    # 显示回测结果
    engine.showBacktestingResult()
    engine.showDailyResult()