# encoding: UTF-8
"""展示如何执行策略参数优化"""
"""setting start here"""
engine_settings = {
            "setStartDate":('20180615 00:00',0),
            "setEndDate" : ('20190115 23:59',),
            "setSlippage" : (0.002,),
            "setRate" : (5/10000,),
            "setDatabase" : ("VnTrader_1Min_Db",),
            }
# optimization_setting
opt_target = 'sharpeRatio' #优化目标
opt_settings = {'symbolList':['eos.usd.q:okef'], 'barPeriod':300} # 策略常量
task_lists = [
    {"task_name":"task1_BB_Window", 
        "pick_opt_param":[                  # pick_opt_param 用于找到最优的参数
            {"param_name":'fastWindow', "range":(10, 50, 5)},
            {"param_name":'slowWindow', "range":(50, 100, 5)}
        ]},                              

    {"task_name":"task2_MaPeriod", 
        "pick_opt_param":[
            {"param_name":'kdjMaPeriod', "range":(50, 100, 5)},
            {"param_name":'signalMaPeriod', "range":(10, 30, 1)}
                    ]},       
    
    {"task_name":"task3_lowVolRate", 
        "pick_best_param":[                 # pick_best_param 用于找到参数组结果的最大值
            {"param_name":'lowVolRate', "range":(1, 20, 1)}
                    ]}
    ]
from StrategyBollBand import BollBandsStrategy as Strategy
"""setting end here"""

from vnpy.trader.app.ctaStrategy.ctaBacktesting import BacktestingEngine,OptimizationSetting
from datetime import datetime
import pandas as pd
import os
import json

def start_optimize_n_output(task, setting, param_mode):
    for param in task[param_mode]:
        setting.addParameter(param["param_name"], *param["range"])
    opt_output = engine.runParallelOptimization(Strategy, setting)
    result_list = []
    col=[]
    for result in opt_output:
        param,target,stat = result
        param = eval(param)
        result_dict = {**param, **stat}
        result_list.append(result_dict)
    col.extend(param.keys())
    col.extend(['sharpeRatio','endBalance','totalReturn','maxDdPercent','totalDays','totalTradeCount'])
    result_df = pd.DataFrame(result_list, columns=col)
    result_df.sort_values(opt_target, ascending = False, inplace = True)
    result_df.to_csv(f"{now}_opt_result_{task['task_name']}.csv")
    func = str_func_pair[param_mode]
    for param in task[param_mode]:
        func(result_df, param["param_name"], setting)

def pick_opt_param(df, param_name, setting):
    count = 0
    for i in [20,10,5]:
        opt=df.head(i)
        count += opt[param_name].value_counts()
    setting.paramDict[param_name] = [float(count.idxmax())]

def pick_best_param(df, param_name, setting):
    best_param = list(df[param_name])[0]
    setting.paramDict[param_name] = [best_param]

def run_tasks(setting):
    for task in task_lists:
        task_name, param_mode = task
        start_optimize_n_output(task, setting, param_mode)
    with open(f'opt_result_{now}.json', "w", encoding="utf-8") as f:
        json.dump(setting.paramDict, f,indent=4)

    print("*** tasks finished ****")

if __name__ == '__main__':
    # 创建回测引擎，模式为K线
    engine = BacktestingEngine()
    engine.setBacktestingMode(engine.BAR_MODE)
    for attr, setting in engine_settings.items():
        func = engine.__getattribute__(attr)
        func(*setting)

    str_func_pair = {"pick_opt_param": pick_opt_param,
                 'pick_best_param': pick_best_param}
    now = datetime.now().strftime("%Y%m%d%H%M%S")
    
    # 跑优化
    setting = OptimizationSetting()
    setting.setOptimizeTarget(opt_target)
    for opt_name, opt_setting in opt_settings.items():
        setting.addParameter(opt_name, opt_setting)
    run_tasks(setting)