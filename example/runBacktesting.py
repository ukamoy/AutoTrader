"""展示如何执行策略回测"""
"""setting start here"""
contracts = {
    "EOS-QUARTER":{
        "size": 1,
        "priceTick": 0.001,
        "rate": 0.003,
        "slippage": 0.001,},
    "RB:SHFE":{
        "size": 10,
        "priceTick": 0.5,
        "rate": 0.0005,
        "slippage": 0.5,
            }}
engine_settings = {
    "setBacktestingMode": "bar",   # 回测模式，bar 模式和 tick 模式
    "setStartDate": ('20180615 00:00', 10), # 设置回测用的数据起始日期，initHours 默认值为 0
    "setEndDate" : ('20190115 23:59',),
    "setCapital": 1000000,      # 设置起始资金，默认值是1,000,000
    "setContracts": contracts,
    "setDatabase" : ("VnTrader_1Min_Db",),
    "setLog":(True, "D:\\vnpy_data\\log\\",), # 设置是否输出日志和交割单, 默认不输出, 默认路径在当前文件夹
    "setCachePath":("D:\\vnpy_data\\",)      # 设置本地数据缓存的路径，默认存在用户文件夹内
    }
from StrategyBollBand import BollBandsStrategy as Strategy
"""setting end here"""
import json
from vnpy.trader.app.ctaStrategy.ctaBacktesting import BacktestingEngine

if __name__ == '__main__':
    # 创建回测引擎，模式为K线
    engine = BacktestingEngine()
    for attr, setting in engine_settings.items():
        func = engine.__getattribute__(attr)
        func(*setting)
    
    # 在引擎中创建策略对象
    with open("CTA_setting.json") as parameterDict:
        srategy_settings = json.load(parameterDict)[0]
    engine.initStrategy(Strategy, srategy_settings)
    
    # 开始跑回测
    engine.runBacktesting()

    # 显示回测结果
    engine.showBacktestingResult()
    engine.showDailyResult()